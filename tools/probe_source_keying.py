# -*- coding: utf-8 -*-
"""实测：用源视频（1280x720 绿幕）自己抠像，质量到底比现有 640x360 素材好还是差。

背景
----
已查明：
  * 源视频 = 106 个 **1280x720 绿幕 mp4**（`assets-videos.zip`，182 MB）
  * 现有 webm = **640x360**，由作者用 **Premiere 手工抠像**导出（上游原话：
    自动 HSV 抠像"易残边或误抠"，所以 106 个动作全部走手工路线）
  * 上游自己的自动抠像脚本 `chroma_step02.py` 在 1280x720 上处理，算法是
    **HSV 色相硬抠**：hue∈[64,176] 且 sat≥0.15 且 val≥0.15 → 透明，
    仅色相边界 6° 做线性渐变，**没有去绿溢**

所以问题不是"能不能变清晰"（2 倍分辨率是实打实的），而是"自己抠像会不会把边缘搞脏"。
这个脚本用一张对照图把这件事摊开看，而不是靠猜。

三种处理放在一起比：
  A. 现有 webm 帧（640x360，放大到 1280 便于同尺寸比较）—— 基准
  B. 源视频 + 上游原版硬抠（复刻 chroma_step02.py 的算法）
  C. 源视频 + 硬抠 + 去绿溢 + 软边（我加的改进）

    python tools/probe_source_keying.py
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC_DIR = r"E:\dsh\_src\probe\video"
OUT = os.path.join(ROOT, "logs", "keying-compare.png")
ANIMATION = "东张西望"
FRAME_INDEX = 30

# 上游 chroma_step02.py 的参数（照抄，不要改）
GREEN_HUE_MIN, GREEN_HUE_MAX = 70.0, 170.0
SAT_MIN, VAL_MIN = 0.15, 0.15
HUE_FEATHER = 6.0


def ffmpeg_path():
    import shutil
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("需要 PATH 里有 ffmpeg")
    return exe


def read_frame(path, index, width=None, height=None):
    """用 ffmpeg 抽一帧到 rawvideo rgb24，返回 numpy 数组 (H,W,3)。"""
    import numpy as np
    command = [ffmpeg_path(), "-v", "error", "-i", path,
               "-vf", "select=eq(n\\,%d)" % index, "-vsync", "0",
               "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    if width and height:
        command = [ffmpeg_path(), "-v", "error", "-i", path,
                   "-vf", "select=eq(n\\,%d),scale=%d:%d:flags=lanczos"
                          % (index, width, height),
                   "-vsync", "0", "-frames:v", "1",
                   "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    done = subprocess.run(command, capture_output=True)
    if done.returncode != 0 or not done.stdout:
        raise RuntimeError("抽帧失败: %s" % done.stderr.decode("utf-8", "replace")[:200])
    raw = done.stdout
    import numpy as np
    pixels = len(raw) // 3
    # 需要知道尺寸：让调用方给，或者从长度反推
    if width and height:
        return np.frombuffer(raw, np.uint8).reshape(height, width, 3).copy()
    raise RuntimeError("必须给出 width/height")


def rgb_to_hsv(frame):
    """numpy 向量化 RGB→HSV，与 chroma_step02.py 的实现一致。"""
    import numpy as np
    r = frame[..., 0].astype(np.float32) / 255.0
    g = frame[..., 1].astype(np.float32) / 255.0
    b = frame[..., 2].astype(np.float32) / 255.0
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    delta = mx - mn
    nz = delta > 0
    with np.errstate(divide="ignore", invalid="ignore"):
        safe = np.where(nz, delta, 1.0)
        hr = 60.0 * (((g - b) / safe) % 6.0)
        hg = 60.0 * (((b - r) / safe) + 2.0)
        hb = 60.0 * (((r - g) / safe) + 4.0)
    hue = np.where((mx == r) & nz, hr,
                   np.where((mx == g) & nz, hg,
                            np.where((mx == b) & nz, hb, 0.0)))
    sat = np.where(mx > 0, delta / np.maximum(mx, 1e-6), 0.0)
    return hue, sat, mx


def key_upstream(frame):
    """复刻上游 chroma_step02.py 的抠像：返回 alpha (H,W) uint8。"""
    import numpy as np
    hue, sat, val = rgb_to_hsv(frame)
    lo = GREEN_HUE_MIN - HUE_FEATHER
    hi = GREEN_HUE_MAX + HUE_FEATHER
    in_hue = (np.clip((hue - lo) / HUE_FEATHER, 0, 1)
              * np.clip((hi - hue) / HUE_FEATHER, 0, 1))
    bg = (sat >= SAT_MIN) & (val >= VAL_MIN) & (hue >= lo) & (hue <= hi)
    return np.where(bg, (1.0 - in_hue) * 255, 255).astype(np.uint8)


def key_improved(frame):
    """硬抠 + 去绿溢 + 软边。

    两个改进点：
      1. **去绿溢**：边缘像素是角色色与绿幕的混合，绿通道被抬高。凡
         `G > max(R,B)` 的像素都把 G 压到 max(R,B)（只压不抬），消除绿描边。
      2. **软边**：硬抠的 alpha 非 0 即 255，抗锯齿信息全丢。这里用"绿的程度"
         算一个 0~1 的过渡：越像绿幕越透明，越不像越实。
    """
    import numpy as np
    hue, sat, val = rgb_to_hsv(frame)
    lo = GREEN_HUE_MIN - HUE_FEATHER
    hi = GREEN_HUE_MAX + HUE_FEATHER
    alpha = key_upstream(frame).astype(np.float32) / 255.0

    # --- 去绿溢 ---
    work = frame.astype(np.float32)
    g = work[..., 1]
    other = np.maximum(work[..., 0], work[..., 2])
    spill = g > other
    work[..., 1] = np.where(spill, other, g)

    # --- 软边 ---
    # 在色相边界附近，按"离绿幕中心的距离"给一个中间值；同时对只剩一点绿的
    # 边缘像素再降一点 alpha，避免残留的绿点被当作实体。
    greenish = (sat >= 0.10) & (val >= 0.10) & (hue >= lo) & (hue <= hi)
    soft = np.clip(1.0 - in_hue_of(hue, lo, hi) * 0.6, 0.0, 1.0)
    alpha = np.where(greenish & (alpha > 0.5), alpha * soft, alpha)

    out = np.concatenate([work, (alpha * 255).astype(np.uint8)[..., None]], axis=2)
    return out.astype(np.uint8), work.astype(np.uint8)


def in_hue_of(hue, lo, hi):
    import numpy as np
    return (np.clip((hue - lo) / HUE_FEATHER, 0, 1)
            * np.clip((hi - hue) / HUE_FEATHER, 0, 1))


def composite(rgb, alpha, background):
    """把 RGBA 合成到纯色背景上，返回 RGB。"""
    import numpy as np
    a = (alpha.astype(np.float32) / 255.0)[..., None]
    bg = np.array(background, np.float32)
    return (rgb.astype(np.float32) * a + bg * (1 - a)).astype(np.uint8)


def main():
    import numpy as np
    try:
        from PIL import Image
    except ImportError:
        print("  需要 Pillow")
        return 1

    mp4 = os.path.join(SRC_DIR, ANIMATION + ".mp4")
    webm = os.path.join(ROOT, "webm", ANIMATION + ".webm")
    frame_png = os.path.join(ROOT, "frames", ANIMATION, "%04d.png" % (FRAME_INDEX + 1))
    for path in (mp4, webm, frame_png):
        if not os.path.exists(path):
            print("  缺文件: %s" % path)
            return 1

    print()
    print("  抠像对照实验：%s 第 %d 帧" % (ANIMATION, FRAME_INDEX))
    print("  " + "=" * 66)

    # A. 现有素材（640x360）放大到 1280x720，便于同尺寸并排
    import PIL.Image as PImage
    current = np.array(PImage.open(frame_png).convert("RGBA").resize(
        (1280, 720), PImage.LANCZOS))
    cur_rgb, cur_alpha = current[..., :3], current[..., 3]
    print("  A 现有 webm 帧: %s -> 放大到 1280x720" % (PImage.open(frame_png).size,))

    # B/C. 源视频 1280x720
    src = read_frame(mp4, FRAME_INDEX, 1280, 720)
    print("  B 源视频帧    : %s" % (src.shape,))
    alpha_up = key_upstream(src)
    rgba_imp, rgb_imp = key_improved(src)
    alpha_imp = rgba_imp[..., 3]

    # 统计
    def stats(alpha, rgb, label):
        semi = int(((alpha > 8) & (alpha < 248)).sum())
        opaque = int((alpha >= 248).sum())
        clear = int((alpha <= 8).sum())
        total = alpha.size
        # 绿溢：不透明/半透明像素里 G 明显高于 R 与 B 的比例
        g = rgb[..., 1].astype(np.int16)
        other = np.maximum(rgb[..., 0], rgb[..., 2]).astype(np.int16)
        vis = alpha > 8
        spill = int(((g > other + 12) & vis).sum())
        vis_count = max(1, int(vis.sum()))
        print("     %-6s 透明 %.1f%%  半透明 %.2f%%  不透明 %.1f%%   可见像素中偏绿 %.2f%%"
              % (label, 100.0 * clear / total, 100.0 * semi / total,
                 100.0 * opaque / total, 100.0 * spill / vis_count))

    print()
    print("  指标")
    print("  " + "-" * 66)
    stats(cur_alpha, cur_rgb, "A 现有")
    stats(alpha_up, src, "B 硬抠")
    stats(alpha_imp, rgb_imp, "C 改进")

    # --- 拼对照图 ---
    # 背景用中间的灰 + 一块洋红，绿边在灰底上最容易看出来
    def tile(rgb, alpha):
        bg = np.zeros((rgb.shape[0], rgb.shape[1], 3), np.float32)
        bg[:, :, :] = (70, 74, 86)
        bg[:, rgb.shape[1] // 2:, :] = (180, 60, 140)     # 右半洋红，绿边会很明显
        return composite(rgb, alpha, (0, 0, 0)) if False else \
            (rgb.astype(np.float32) * (alpha[..., None] / 255.0)
             + bg * (1 - alpha[..., None] / 255.0)).astype(np.uint8)

    rows = [
        ("A 现有 640x360（放大）", tile(cur_rgb, cur_alpha)),
        ("B 源 1280x720 + 上游硬抠", tile(src, alpha_up)),
        ("C 源 + 硬抠+去绿溢+软边", tile(rgb_imp, alpha_imp)),
    ]
    # 每行左侧整图缩略 + 右侧**头部**放大（看清边缘，这才是抠像质量的关键）
    thumb_w, thumb_h = 420, 236
    # 角色在 1280x720 里的包围盒是 x 486..880, y 126..658 —— 头部在上半部分
    zoom = (470, 110, 900, 430)
    zoom_size = (430, 320)
    sheet_w = thumb_w + zoom_size[0] + 40
    sheet_h = (thumb_h + 34) * len(rows) + 16
    sheet = Image.new("RGB", (sheet_w, sheet_h), (24, 26, 32))
    for index, (label, image) in enumerate(rows):
        y = 8 + index * (thumb_h + 34)
        full = Image.fromarray(image).resize((thumb_w, thumb_h), Image.LANCZOS)
        crop = Image.fromarray(image).crop(zoom).resize(zoom_size, Image.NEAREST)
        sheet.paste(full, (10, y + 22))
        sheet.paste(crop, (thumb_w + 30, y + 22))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    sheet.save(OUT)
    print()
    print("  对照图已写出: %s" % os.path.relpath(OUT, ROOT))
    print("     左列=整图（右半是洋红底，绿边最显眼）  右列=头部区域 NEAREST 放大")
    return 0


if __name__ == "__main__":
    sys.exit(main())
