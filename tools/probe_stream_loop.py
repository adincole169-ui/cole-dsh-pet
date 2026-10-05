# -*- coding: utf-8 -*-
"""写流式模块前，先验证三个决定成败的假设。

假设一：`-stream_loop -1` 能用在带 alpha 的 VP9 上，且循环时帧不重不漏。
        （循环播放必须靠它 —— 否则每转一圈都要重起 ffmpeg。）

假设二：能在不解码全片的前提下拿到**准确的帧数**（`Playing.frame_index()` 用
        `index % len` 算循环，`duration = len/fps` 判结束，所以必须精确）。
        对比 ffprobe 的 `-count_frames` 与容器里的 `duration`，看哪个可信。

假设三：**流式解出来的像素与磁盘 PNG 缓存逐像素相同**。
        若不同，说明现在的 PNG 链路里有额外处理（裁剪/缩放），流式会改变画面。
        这一条最重要 —— 它是"换了帧来源但画面不变"的前提。

    python tools/probe_stream_loop.py 东张西望
"""

import hashlib
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FRAME_BYTES_640 = 640 * 360 * 4


def ffmpeg_path():
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("需要 PATH 里有 ffmpeg")
    return exe


def ffprobe_path():
    exe = shutil.which("ffprobe")
    if not exe:
        raise RuntimeError("需要 PATH 里有 ffprobe")
    return exe


def probe_count(webm):
    """数帧数与尺寸。"""
    done = subprocess.run(
        [ffprobe_path(), "-v", "error", "-select_streams", "v:0",
         "-count_frames", "-show_entries",
         "stream=nb_read_frames,width,height,r_frame_rate",
         "-of", "default=noprint_wrappers=1", webm],
        capture_output=True, text=True)
    info = {}
    for line in done.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            info[key.strip()] = value.strip()
    return info


def probe_container(webm):
    """容器层声明的时长与帧数（不解码，很快）。"""
    done = subprocess.run(
        [ffprobe_path(), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=nb_frames,duration,r_frame_rate,width,height",
         "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1", webm],
        capture_output=True, text=True)
    info = {}
    for line in done.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            info[key.strip()] = value.strip()
    return info


def read_frames(webm, count, loop=False):
    """读 count 帧原始 RGBA，返回字节列表。"""
    command = [ffmpeg_path(), "-v", "error"]
    if loop:
        command += ["-stream_loop", "-1"]
    command += ["-c:v", "libvpx-vp9", "-i", webm,
                "-f", "rawvideo", "-pix_fmt", "rgba", "-"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL)
    frames = []
    try:
        for _ in range(count):
            buffer = b""
            while len(buffer) < FRAME_BYTES_640:
                chunk = process.stdout.read(FRAME_BYTES_640 - len(buffer))
                if not chunk:
                    break
                buffer += chunk
            if len(buffer) < FRAME_BYTES_640:
                break
            frames.append(buffer)
    finally:
        try:
            process.stdout.close()
        except Exception:
            pass
        process.terminate()
        try:
            process.wait(timeout=10)
        except Exception:
            process.kill()
    return frames


def main():
    argv = sys.argv[1:]
    animation = argv[0] if argv and not argv[0].startswith("-") else "东张西望"
    webm = os.path.join(ROOT, "webm", animation + ".webm")
    if not os.path.exists(webm):
        print("  找不到 %s" % webm)
        return 1

    print()
    print("  流式方案的前置验证（%s）" % animation)
    print("  " + "=" * 76)

    # --- 假设二：帧数 ---
    print()
    print("  假设二：能否拿到**准确的**帧数")
    print("  " + "-" * 76)
    counted = probe_count(webm)
    container = probe_container(webm)
    print("     ffprobe -count_frames : %s"
          % {k: counted.get(k) for k in ("width", "height", "r_frame_rate",
                                         "nb_read_frames")})
    print("     容器层声明            : %s"
          % {k: container.get(k) for k in ("nb_frames", "duration",
                                           "r_frame_rate")})
    print("     format.duration       : %s" % container.get("duration"))
    exact = counted.get("nb_read_frames")
    print("     -> 用 -count_frames 的 nb_read_frames = %s（精确，但要解码全片）" % exact)

    # 磁盘缓存的真实帧数（对照）
    cache = os.path.join(ROOT, "frames", animation)
    if os.path.isdir(cache):
        on_disk = len([f for f in os.listdir(cache) if f.endswith(".png")])
        print("     磁盘缓存的 PNG 帧数   : %d" % on_disk)
        if exact and int(exact) == on_disk:
            print("     -> **一致**，可以用 ffprobe 的帧数")
        else:
            print("     -> **不一致！** 流式会改变循环长度，要查清原因")

    # --- 假设三：像素是否相同 ---
    print()
    print("  假设三：流式像素 vs 磁盘 PNG 缓存（逐像素）")
    print("  " + "-" * 76)
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        print("     需要 numpy + Pillow")
        return 1
    if not os.path.isdir(cache):
        print("     没有磁盘缓存可对照，跳过")
    else:
        frames = read_frames(webm, 6)
        print("     流式读到 %d 帧" % len(frames))
        worst = 0
        for index in range(min(len(frames), 6)):
            streamed = np.frombuffer(frames[index], np.uint8).reshape(360, 640, 4)
            path = os.path.join(cache, "%04d.png" % (index + 1))
            if not os.path.isfile(path):
                continue
            with Image.open(path) as raw:
                cached = np.asarray(raw.convert("RGBA"))
            if cached.shape != streamed.shape:
                print("     第 %d 帧尺寸不同: 流式 %s vs 缓存 %s"
                      % (index + 1, streamed.shape, cached.shape))
                continue
            diff = np.abs(streamed.astype(np.int16) - cached.astype(np.int16))
            worst = max(worst, int(diff.max()))
        print("     前 6 帧最大逐通道差: %d / 255" % worst)
        if worst == 0:
            print("     -> **逐像素完全相同**")
        elif worst <= 2:
            print("     -> 几乎相同（差 %d，可能是解码路径的舍入）" % worst)
        else:
            print("     -> **有明显差异**，换源会改变画面，需要查")

    # --- 假设一：循环 ---
    print()
    print("  假设一：-stream_loop -1 能不能用在带 alpha 的 VP9 上")
    print("  " + "-" * 76)
    if not exact:
        print("     拿不到帧数，跳过循环验证")
        return 0
    count = int(exact)
    # 读 count + 8 帧，检查第 count 帧是否回到第 0 帧
    frames = read_frames(webm, count + 8, loop=True)
    print("     请求 %d 帧，实际读到 %d 帧" % (count + 8, len(frames)))
    if len(frames) < count + 2:
        print("     -> **循环没生效**（读不到第二圈）")
        return 1
    first = frames[0]
    wrap = frames[count]
    same = hashlib.sha256(first).hexdigest() == hashlib.sha256(wrap).hexdigest()
    print("     第 0 帧与第 %d 帧是否相同: %s" % (count, "是" if same else "否"))
    if same:
        print("     -> **-stream_loop -1 可用，循环精确回到第 0 帧**")
        print("        所以循环播放不需要重起 ffmpeg，一个进程可以一直转")
    else:
        # 差一帧也算可用，只要稳定
        shifted = hashlib.sha256(frames[count - 1]).hexdigest() == \
            hashlib.sha256(wrap).hexdigest()
        print("     第 %d 帧与第 0 帧是否相同: %s"
              % (count - 1, "是" if shifted else "否"))
        print("     -> 循环点有偏移，但可以用『按序号取模』的方式索引，不影响使用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
