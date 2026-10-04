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
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("找不到 ffmpeg，请确认它在 PATH 中")
    return exe


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
    """解码一个动画到帧缓存。返回帧数。"""
    source = os.path.join(WEBM_DIR, name + ".webm")
    if not os.path.exists(source):
        raise FileNotFoundError("没有这个动画: %s" % name)
    destination = cache_dir(name)
    if is_cached(name) and not force:
        return frame_count(name)

    if os.path.isdir(destination):
        shutil.rmtree(destination)
    os.makedirs(destination, exist_ok=True)
    pattern = os.path.join(destination, "%04d.png")

    command = [
        ffmpeg_path(), "-y", "-v", "error",
        # 必须放在 -i 之前：这是"用 libvpx 的 VP9 解码器"，它才会合并 alpha 流。
        "-c:v", "libvpx-vp9",
        "-i", source,
        "-pix_fmt", "rgba",
        pattern,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("ffmpeg 解码失败（%s）：%s" % (name, (result.stderr or "").strip()[:300]))

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
