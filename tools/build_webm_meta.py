# -*- coding: utf-8 -*-
"""生成 webm-meta.json：每个动画的帧数/帧率/尺寸。

为什么需要它
------------
流式播放要知道**准确的帧数**（`Playing.frame_index()` 用 `index % len` 算循环，
`duration = len/fps` 判结束）。拿帧数有两条路：

  * `ffprobe -count_frames` —— 精确，但要**解码全片**，约 0.2 秒/动画。
    加在每次"首次播放"上，会变成 94 ms（起 ffmpeg 到首帧）+ 200 ms 的额外卡顿。
  * 本文件预先生成一份 —— 8 KB 的 JSON，读一下就是 0 毫秒。

所以把帧数**预先算好并随仓库分发**（8 KB 进 git 完全可以接受），
运行时只在遇到"元数据里没有的动画"（用户自己丢进来的 webm）才退回 ffprobe。

    python tools/build_webm_meta.py            # 生成/更新
    python tools/build_webm_meta.py --check    # 只校验是否过期，不写
"""

import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WEBM_DIR = os.path.join(ROOT, "webm")
META = os.path.join(ROOT, "webm-meta.json")


def ffprobe_path():
    exe = shutil.which("ffprobe")
    if not exe:
        raise RuntimeError("需要 PATH 里有 ffprobe（装 ffmpeg 时自带）")
    return exe


def parse_rate(text):
    """'24/1' -> 24.0；'30000/1001' -> 29.97"""
    try:
        if "/" in text:
            numerator, denominator = text.split("/", 1)
            denominator = float(denominator)
            return round(float(numerator) / denominator, 6) if denominator else 0.0
        return round(float(text), 6)
    except (TypeError, ValueError):
        return 0.0


def probe(webm):
    """返回 {frames, fps, width, height, duration}。"""
    done = subprocess.run(
        [ffprobe_path(), "-v", "error", "-select_streams", "v:0",
         "-count_frames", "-show_entries",
         "stream=nb_read_frames,width,height,r_frame_rate,duration",
         "-of", "default=noprint_wrappers=1", webm],
        capture_output=True, text=True)
    info = {}
    for line in done.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            info[key.strip()] = value.strip()
    frames = info.get("nb_read_frames")
    frames = int(frames) if frames and frames.isdigit() else 0
    duration = 0.0
    try:
        duration = round(float(info.get("duration") or 0.0), 6)
    except ValueError:
        pass
    return {
        "frames": frames,
        "fps": parse_rate(info.get("r_frame_rate", "")),
        "width": int(info.get("width") or 0),
        "height": int(info.get("height") or 0),
        "duration": duration,
    }


def load_meta():
    if not os.path.isfile(META):
        return {}
    try:
        with open(META, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def entry_signature(webm):
    """用文件大小当"这份 webm 还是不是当初那一份"的指纹。

    不用 mtime：clone 下来之后 mtime 会变，但内容没变，那样会导致每次都判定过期。
    """
    try:
        return os.path.getsize(webm)
    except OSError:
        return -1


def build(names=None, progress=None):
    meta = load_meta()
    animations = names or sorted(
        os.path.splitext(f)[0] for f in os.listdir(WEBM_DIR) if f.endswith(".webm"))
    added = updated = skipped = failed = 0
    for index, name in enumerate(animations):
        webm = os.path.join(WEBM_DIR, name + ".webm")
        if not os.path.isfile(webm):
            failed += 1
            continue
        size = entry_signature(webm)
        existing = meta.get(name)
        if (isinstance(existing, dict) and existing.get("bytes") == size
                and existing.get("frames")):
            skipped += 1
        else:
            try:
                info = probe(webm)
            except Exception as error:
                sys.stderr.write("  %s 探测失败: %s\n" % (name, error))
                failed += 1
                continue
            if not info["frames"]:
                failed += 1
                continue
            info["bytes"] = size
            if existing:
                updated += 1
            else:
                added += 1
            meta[name] = info
        if progress:
            progress(index + 1, len(animations), name)
    # 清掉已经不存在的动画（webm 被删了）
    alive = set(os.path.splitext(f)[0] for f in os.listdir(WEBM_DIR)
                if f.endswith(".webm"))
    for name in list(meta):
        if name not in alive:
            meta.pop(name)
    return meta, {"added": added, "updated": updated, "skipped": skipped,
                  "failed": failed}


def main():
    argv = sys.argv[1:]
    check_only = "--check" in argv
    if not os.path.isdir(WEBM_DIR):
        print("  找不到 %s" % WEBM_DIR)
        return 1

    started = time.time()
    print()
    print("  %s webm-meta.json" % ("校验" if check_only else "生成"))
    print("  " + "=" * 68)

    def progress(done, total, name):
        if done % 20 == 0 or done == total:
            print("     %3d/%d  %s" % (done, total, name))

    try:
        meta, stats = build(progress=progress)
    except RuntimeError as error:
        print("  %s" % error)
        return 1

    print()
    print("     新增 %d，更新 %d，未变 %d，失败 %d"
          % (stats["added"], stats["updated"], stats["skipped"], stats["failed"]))
    print("     动画数 %d，用时 %.1f 秒" % (len(meta), time.time() - started))

    total_frames = sum(item.get("frames", 0) for item in meta.values())
    rates = sorted(set(item.get("fps") for item in meta.values()))
    sizes = sorted(set((item.get("width"), item.get("height"))
                       for item in meta.values()))
    print("     帧数合计 %d" % total_frames)
    print("     出现的帧率: %s" % rates)
    print("     出现的尺寸: %s" % sizes)

    if check_only:
        if stats["added"] or stats["updated"] or stats["failed"]:
            print()
            print("     **webm-meta.json 已过期**，需要运行不带 --check 的命令重新生成")
            return 1
        print()
        print("     webm-meta.json 是最新的")
        return 0

    with open(META, "w", encoding="utf-8") as handle:
        json.dump(meta, handle, ensure_ascii=False, indent=1, sort_keys=True)
        handle.write("\n")
    print()
    print("     已写出 %s（%.1f KB）"
          % (os.path.relpath(META, ROOT), os.path.getsize(META) / 1024.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
