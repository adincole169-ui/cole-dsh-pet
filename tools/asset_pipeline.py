# -*- coding: utf-8 -*-
"""素材管线：把 dsh-pet 的透明 webm 动画转成本程序能直接贴图的 PNG 帧序列。

为什么需要这一步
----------------
这套素材是 **VP9 + 独立 alpha 流** 的 webm（容器里带 `ALPHA_MODE=1`）。Qt 的解码器
不会合并那路 alpha，而且本机 PyQt5 连 QtMultimedia 都没有，因此：

    视频  →  ffmpeg 解码成一帧帧带透明通道的 PNG  →  Qt 按帧率贴图

关键是解码时必须显式指定 `-c:v libvpx-vp9`：只有 libvpx 的 VP9 解码器会去取那路
隐藏的 alpha 流并合并成 RGBA。默认解码器（以及任何"先转 PNG 再切"的做法）拿到的
是**全不透明**的画面，透明区域会变成黑块。

存储策略
--------
全量解码 106 个动画约 2.5 万帧、原生 PNG 约 2.6 GB，不能常驻。所以：

* **按需解码**：某个动画第一次被播放时才解码，之后复用；
* **压缩存放**：降采样到目标宽度 + 调色板量化，单帧从约 100 KB 降到约 8–15 KB；
* 缓存目录可按需整体删除，删掉后下次播放会重新生成。

命令行
------
    python tools/asset_pipeline.py build <名称...>     # 解码指定动画
    python tools/asset_pipeline.py build-all          # 全部解码（约 300 MB 缓存）
    python tools/asset_pipeline.py list               # 列出可用动画与缓存状态
    python tools/asset_pipeline.py clean              # 清空缓存
"""

import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WEBM_DIR = os.path.join(ROOT, "webm")
FRAME_DIR = os.path.join(ROOT, "frames")

# ffmpeg 的查找结果缓存（见 ffmpeg_path）；`_FFMPEG_SOURCE` 记它是从哪找到的
_FFMPEG_CACHE = None
_FFMPEG_SOURCE = None
# 最近一次兜底解码实际用了哪个暂存目录（诊断用；正常路径为 None）
_LAST_STAGING = None

# 目标帧宽。素材原生 640x360，而本机桌宠用 size 320 逻辑（dpr=2，即物理 640 显示），
# 所以缓存宽度就是清晰度上限：
#
#   640 = 原生，最清晰，全量缓存约 2.6 GB    ← 当前选择
#   480 = 按 640 显示时放大 1.33 倍；全量约 1.5 GB
#   320 = 放大 2 倍，明显发糊（最早那版就是这样）
#
# 想更清晰：调到 640 后 `asset_pipeline.py clean` 再重生成。
# 想更省：继续调小，代价是发糊。
#
# 为什么最终选 640（原生）：用户反馈是"放大了也觉得糊"。
# 实测 480→640 的平均像素差只有 1.85/255（数值上几乎无差），但**放大本身**会让边缘
# 变软，而这个观感确实看得出来。640 就是素材原生宽度，不需要额外上采样，所以用它；
# 代价是缓存 1.5 GB → 2.6 GB。
TARGET_WIDTH = 640
# 调色板量化：这套画风是平涂 + 硬边，256 色几乎无损。它只影响颜色数，不影响尺寸，
# 因此对清晰度没有影响，可以放心保留。
PALETTE_COLORS = 256


def ffmpeg_path():
    """找一个可用的 ffmpeg 可执行文件。

    查找顺序：
      1. **PATH 里的 ffmpeg**（优先）—— 通常是较新的构建，行为最标准；
      2. `imageio-ffmpeg` 自带的那个 —— `pip install imageio-ffmpeg` 就会带一个
         ffmpeg 二进制进来（约 62 MB 的 wheel），这样使用者**不必手动安装 ffmpeg**。

    注意第 2 条那个自带的是 **4.2.2（2019 年）**，它在**本项目目录下直接写文件会失败**
    （实测：`Could not open file` / `I/O error`，只在本项目的 `frames/<中文名>/` 下复现，
    换个中文目录却成功，原因未查明）。`build()` 里有针对它的兜底：写不进去就先解到
    ASCII 临时目录再搬 —— 已实测该兜底有效。

    结果会缓存，避免每次解码都重新探测。
    """
    global _FFMPEG_CACHE, _FFMPEG_SOURCE
    if _FFMPEG_CACHE:
        return _FFMPEG_CACHE

    exe = shutil.which("ffmpeg")
    if exe:
        _FFMPEG_CACHE = exe
        _FFMPEG_SOURCE = "PATH"
        return exe

    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            _FFMPEG_CACHE = exe
            _FFMPEG_SOURCE = "imageio-ffmpeg"
            return exe
    except Exception:
        pass

    raise RuntimeError(
        "找不到 ffmpeg。二选一：\n"
        "  * 装一个 ffmpeg 并加进 PATH（推荐，用较新版本）；或\n"
        "  * pip install imageio-ffmpeg   —— 它会自带一个 ffmpeg，免手动安装")


def last_staging_used():
    """最近一次兜底解码用的暂存目录（没走兜底则为 None）。给自检/诊断用。"""
    return _LAST_STAGING


def ffmpeg_origin():
    """返回 (可执行文件路径, 来源说明)。给自检/诊断用。"""
    path = ffmpeg_path()
    return path, _FFMPEG_SOURCE or "未知"


def ffmpeg_version():
    """取版本号第一行，失败返回空串。"""
    try:
        done = subprocess.run([ffmpeg_path(), "-version"],
                              capture_output=True, text=True, timeout=20)
        line = (done.stdout or "").splitlines()
        return line[0] if line else ""
    except Exception:
        return ""


def staging_candidates():
    """按优先级返回若干**暂存目录候选**，供解码兜底逐个尝试。

    为什么不是一个目录而是一串：imageio-ffmpeg 自带的 ffmpeg 4.2.2 在本机
    **对某些目录写不出文件**（`Could not open file` / `I/O error`）。实测规律
    （同一命令、每目录重复 3 次，结果完全稳定）：

        项目外的浅层目录（盘符根下第一层）   成功 3/3
        项目内的任意目录                     失败 3/3
        系统 TEMP（层级较深）                失败 3/3

    也就是说：**浅层且不在项目内**的目录可用；项目内、或层级很深的都不行。
    至于根因（路径长度？项目目录里什么东西在干扰？）**没有查明**，
    所以这里不赌单一位置，而是**逐个试**，谁能写就用谁。

    顺序：先试 `%TEMP%`（常规位置），再试**项目同级**的目录（实测这种形状可用），
    最后才试项目内。
    """
    parent = os.path.dirname(ROOT.rstrip(os.sep))
    temp_root = os.environ.get("TEMP") or os.environ.get("TMP") or ""
    raw = [
        os.path.join(temp_root, "dsh-pet-decode") if temp_root else "",
        os.path.join(parent, "dsh-pet-decode") if parent else "",
        os.path.join(os.environ.get("SystemDrive", "C:") + os.sep,
                     "Windows", "Temp", "dsh-pet-decode"),
        os.path.join(ROOT, ".decode-staging"),
    ]
    result = []
    for candidate in raw:
        if not candidate:
            continue
        if candidate in result:
            continue
        result.append(candidate)
    return result


def ascii_staging_root():
    """第一个**可写**的暂存目录候选；都不行则 None。

    只检查"目录能建、Python 能写"——**不检查 ffmpeg 能不能写**（那要给每个候选
    跑一次解码，太贵）。ffmpeg 层面的失败由 `build()` 逐个候选重试处理。
    """
    for candidate in staging_candidates():
        try:
            candidate.encode("ascii")            # 旧版 ffmpeg 走窄字符，要求纯 ASCII
        except UnicodeEncodeError:
            continue
        try:
            os.makedirs(candidate, exist_ok=True)
            probe = os.path.join(candidate, "write-probe.tmp")
            with open(probe, "w") as handle:
                handle.write("ok")
            os.remove(probe)
            return candidate
        except Exception:
            continue
    return None


def _decode_to(exe, source, out_dir, frames_limit=None):
    """把 source 解成 PNG 序列到 out_dir。返回 (是否成功, 帧数, 报错摘要)。"""
    os.makedirs(out_dir, exist_ok=True)
    command = [
        exe, "-y", "-v", "error",
        # 必须放在 -i 之前：这是"用 libvpx 的 VP9 解码器"，它才会合并 alpha 流。
        "-c:v", "libvpx-vp9",
        "-i", source,
    ]
    if frames_limit:
        command += ["-frames:v", str(frames_limit)]
    command += ["-pix_fmt", "rgba", os.path.join(out_dir, "%04d.png")]
    result = subprocess.run(command, capture_output=True, text=True)
    produced = sorted(name for name in os.listdir(out_dir) if name.endswith(".png"))
    error = (result.stderr or "").strip()[:300]
    return (len(produced) > 0), len(produced), error


def _png_count(folder):
    if not os.path.isdir(folder):
        return 0
    return len([name for name in os.listdir(folder) if name.endswith(".png")])


def _clear_pngs(folder):
    if not os.path.isdir(folder):
        return
    for name in os.listdir(folder):
        if name.endswith(".png"):
            os.remove(os.path.join(folder, name))


def list_animations():
    """素材目录里的动画名（不含扩展名），按名称排序。"""
    if not os.path.isdir(WEBM_DIR):
        return []
    return sorted(os.path.splitext(name)[0]
                  for name in os.listdir(WEBM_DIR)
                  if name.lower().endswith(".webm"))


def cache_dir(name):
    return os.path.join(FRAME_DIR, name)


def is_cached(name):
    directory = cache_dir(name)
    if not os.path.isdir(directory):
        return False
    for entry in os.listdir(directory):
        if entry.endswith(".png"):
            return True
    return False


def cached_frames(name):
    """已缓存的帧路径，按文件名排序（文件名是零填充序号）。"""
    directory = cache_dir(name)
    if not os.path.isdir(directory):
        return []
    return sorted(os.path.join(directory, entry)
                  for entry in os.listdir(directory)
                  if entry.endswith(".png"))


def frame_count(name):
    return len(cached_frames(name))


def _common_crop(paths, sample=24):
    """所有帧共同的非透明包围盒。

    素材是 640x360 的画布，但角色通常只占中间一小块，四周是整片透明——那部分空白
    会给每一帧都带来固定的 PNG 体积。裁掉它能把缓存压到约三分之一。

    这里用**所有帧的并集**，而不是逐帧各自的包围盒：逐帧裁剪会让角色在窗口里随
    帧漂移（每帧被重新居中），动画就抖了。并集裁剪保持帧间相对位置不变。
    """
    from PIL import Image
    if not paths:
        return None
    step = max(1, len(paths) // sample)
    left = top = 10 ** 9
    right = bottom = -1
    for path in paths[::step]:
        with Image.open(path) as image:
            box = image.convert("RGBA").getchannel("A").getbbox()
        if box is None:
            continue
        left = min(left, box[0])
        top = min(top, box[1])
        right = max(right, box[2])
        bottom = max(bottom, box[3])
    if right <= left or bottom <= top:
        return None
    return (left, top, right, bottom)


def _quantize(paths, width):
    """降采样 → 按共用包围盒裁剪 → 调色板量化，就地替换。"""
    from PIL import Image
    box = _common_crop(paths)
    for path in paths:
        with Image.open(path) as image:
            image = image.convert("RGBA")
            if image.width > width:
                height = max(1, int(round(image.height * width / float(image.width))))
                image = image.resize((width, height), Image.LANCZOS)
            if box is not None:
                scale = image.width / float(width)
                crop = (max(0, int(box[0] * scale)), max(0, int(box[1] * scale)),
                        min(image.width, int(box[2] * scale) + 1),
                        min(image.height, int(box[3] * scale) + 1))
                if crop[2] - crop[0] > 4 and crop[3] - crop[1] > 4:
                    image = image.crop(crop)
            # 调色板化保留 alpha：先量化 RGB，再把原 alpha 贴回去。
            alpha = image.getchannel("A")
            quantized = image.convert("RGB").quantize(colors=PALETTE_COLORS, method=Image.MEDIANCUT)
            quantized = quantized.convert("RGBA")
            quantized.putalpha(alpha)
            quantized.save(path, "PNG", optimize=True)


def build(name, width=TARGET_WIDTH, force=False):
    """解码一个动画到帧缓存。返回帧数。

    先尝试**直接写到目标目录**（正常 ffmpeg 都行，也省一次搬文件）。
    若失败，改用**纯 ASCII 暂存目录再搬进来** —— 因为 imageio-ffmpeg 自带的
    ffmpeg 4.2.2 在本项目的 `frames/<中文名>/` 下写文件会失败（实测可复现，
    换个中文目录却成功，原因未查明）。已实测该兜底有效。
    """
    source = os.path.join(WEBM_DIR, name + ".webm")
    if not os.path.exists(source):
        raise FileNotFoundError("没有这个动画: %s" % name)
    destination = cache_dir(name)
    if is_cached(name) and not force:
        return frame_count(name)

    if os.path.isdir(destination):
        shutil.rmtree(destination)
    os.makedirs(destination, exist_ok=True)

    exe = ffmpeg_path()
    ok, _count, error = _decode_to(exe, source, destination)
    if not ok:
        # 直接写失败：清掉半成品，改走暂存目录 —— 而且**逐个候选试**，
        # 因为旧版 ffmpeg 的失败与目录位置有关（见 staging_candidates 的说明）。
        _clear_pngs(destination)
        tried = []
        for root in staging_candidates():
            try:
                root.encode("ascii")
            except UnicodeEncodeError:
                continue
            staging = os.path.join(root, "decode")
            try:
                if os.path.isdir(staging):
                    shutil.rmtree(staging)
                os.makedirs(staging, exist_ok=True)
            except Exception as exc:
                tried.append("%s（建目录失败: %s）" % (root, exc))
                continue

            ok2, _count2, error2 = _decode_to(exe, source, staging)
            moved = 0
            if ok2:
                for entry in sorted(os.listdir(staging)):
                    if entry.endswith(".png"):
                        shutil.move(os.path.join(staging, entry),
                                    os.path.join(destination, entry))
                        moved += 1
                ok2 = moved > 0
            shutil.rmtree(staging, ignore_errors=True)

            if ok2:
                # 记下这次用的是哪个候选（诊断用）
                global _LAST_STAGING
                _LAST_STAGING = root
                break
            tried.append("%s（%s）" % (root, (error2 or "").strip()[:80]))

        # 清掉空的暂存目录，别在项目同级或 TEMP 里留垃圾
        for root in staging_candidates():
            try:
                if os.path.isdir(root) and not os.listdir(root):
                    os.rmdir(root)
            except Exception:
                pass

        if not ok2:
            raise RuntimeError(
                "ffmpeg 解码失败（%s）。\n"
                "  直接写到目标目录: %s\n"
                "  逐个尝试暂存目录也都失败:\n    %s\n"
                "建议：装一个较新的 ffmpeg 放进 PATH（旧版 ffmpeg 对目录位置敏感）。"
                % (name, error, "\n    ".join(tried) or "（没有可用候选）"))

    frames = cached_frames(name)
    if not frames:
        raise RuntimeError("ffmpeg 没有产出任何帧: %s" % name)
    _quantize(frames, width)
    return len(frames)


def build_all(width=TARGET_WIDTH, progress=None):
    names = list_animations()
    done = []
    for index, name in enumerate(names):
        try:
            count = build(name, width=width)
        except Exception as error:
            done.append((name, -1, str(error)))
            continue
        done.append((name, count, ""))
        if progress:
            progress(index + 1, len(names), name, count)
    return done


def build_all_parallel(width=TARGET_WIDTH, workers=4, progress=None, names=None):
    """并行解码动画。

    每个动画都是一次独立的 ffmpeg 进程 + 一次 Pillow 量化，天然可并行。
    实测（16 核，6 worker）：串行 27.1 秒/动画 -> 并行 5.8 秒/动画，**提速约 4.7 倍**。
    106 个动画从约 48 分钟降到约 10 分钟。

    参数 `names` 指定要解哪几个（默认全部）。**每个动画仍然写自己的目录**，
    互不干扰；`progress` 会被串行化调用（加锁），避免多线程同时打印导致输出交错。
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    if names is None:
        names = list_animations()
    names = [name for name in names if name]
    if not names:
        return []
    workers = max(1, min(int(workers or 1), len(names)))
    lock = threading.Lock()
    results = {}
    finished = [0]

    def work(name):
        try:
            count = build(name, width=width)
            outcome = (name, count, "")
        except Exception as error:
            outcome = (name, -1, str(error))
        with lock:
            results[name] = outcome
            finished[0] += 1
            if progress:
                progress(finished[0], len(names), name, outcome[1])
        return outcome

    if workers == 1:
        return [work(name) for name in names]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(work, names))

    # 按原顺序返回，便于比对
    return [results.get(name, (name, -1, "未执行")) for name in names]


def default_workers():
    """默认并行度：核数的一半，夹在 2~6 之间。

    不取满核：ffmpeg 解码本身已多线程，满核并行反而互相抢 CPU（实测 6 worker
    比 16 worker 的单动画吞吐更好）。核少时至少 2，单核机器退回 1。
    """
    cores = os.cpu_count() or 1
    if cores <= 2:
        return max(1, cores)
    return max(2, min(6, cores // 2))


def cache_size():
    total = 0
    if os.path.isdir(FRAME_DIR):
        for base, _dirs, files in os.walk(FRAME_DIR):
            for entry in files:
                total += os.path.getsize(os.path.join(base, entry))
    return total


def main(argv):
    action = (argv[1] if len(argv) > 1 else "list").lower()

    if action == "list":
        names = list_animations()
        print("素材动画 %d 个，帧缓存目录 %s" % (len(names), FRAME_DIR))
        for name in names:
            state = "%4d 帧" % frame_count(name) if is_cached(name) else "未缓存"
            print("  %-9s %s" % (state, name))
        print("缓存占用: %.1f MB" % (cache_size() / 1048576.0))
        return 0

    if action == "build":
        names = argv[2:]
        if not names:
            print("用法: build <动画名...>")
            return 2
        for name in names:
            count = build(name)
            print("  %s -> %d 帧" % (name, count))
        return 0

    if action == "build-all":
        def report(index, total, name, count):
            print("  [%3d/%3d] %-24s %4d 帧" % (index, total, name, count))
        results = build_all(progress=report)
        failed = [item for item in results if item[1] < 0]
        print("完成 %d 个，失败 %d 个；缓存占用 %.1f MB"
              % (len(results) - len(failed), len(failed), cache_size() / 1048576.0))
        for name, _count, error in failed:
            print("  失败 %s: %s" % (name, error))
        return 0

    if action == "clean":
        if os.path.isdir(FRAME_DIR):
            shutil.rmtree(FRAME_DIR)
        print("缓存已清空")
        return 0

    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
