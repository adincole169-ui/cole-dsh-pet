# -*- coding: utf-8 -*-
"""量"用 1280x720 源重建素材"的真实代价与收益。

已确认的事实：
  * 源视频 1280x720（绿幕 mp4），现有 webm 640x360 —— 正好 2 倍
  * 上游用**手工 PR 抠像**；自动抠像有绿边（实测可见像素里 1.38% 偏绿），
    我已用"去绿溢 + 软边"压到 0.00%（见 probe_source_keying.py）
  * 角色在全部 106 个动画里的并集包围盒几乎占满整帧（x 6..629 / y 0..359 @640），
    所以**不能统一裁到角色**（各动画的角色位置与尺度本来就不同）

于是方案只能是"保持 16:9 画布，把分辨率翻倍"。这个脚本量它的代价：

  1. 抽若干帧，做完整处理（去绿溢 + 软边 + 可选调色板量化），量单帧 PNG 体积
  2. 外推到全量 25423 帧，给出磁盘预算
  3. 给出显示链路的换算（哪种 size 才是 1:1）

    python tools/probe_hires_cost.py
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

SRC_DIR = r"E:\dsh\_src\probe\video"
ANIMATIONS = ["东张西望", "三球抛接", "撸猫"]
FRAMES = [10, 60, 120, 180, 230]
TOTAL_FRAMES = 25423          # 全量帧数（实测）
W, H = 1280, 720


def ffmpeg_path():
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("需要 PATH 里有 ffmpeg")
    return exe


def read_frame(path, index):
    import numpy as np
    command = [ffmpeg_path(), "-v", "error", "-i", path,
               "-vf", "select=eq(n\\,%d)" % index, "-vsync", "0",
               "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    done = subprocess.run(command, capture_output=True)
    if done.returncode != 0 or len(done.stdout) < W * H * 3:
        raise RuntimeError("抽帧失败: %s" % done.stderr.decode("utf-8", "replace")[:160])
    return np.frombuffer(done.stdout[:W * H * 3], np.uint8).reshape(H, W, 3).copy()


def rgb_to_hsv(frame):
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
                   np.where((mx == g) & nz, hg, np.where((mx == b) & nz, hb, 0.0)))
    sat = np.where(mx > 0, delta / np.maximum(mx, 1e-6), 0.0)
    return hue, sat, mx


def key_and_clean(frame):
    """上游硬抠 + 去绿溢 + 软边。返回 RGBA uint8。"""
    import numpy as np
    GREEN_HUE_MIN, GREEN_HUE_MAX, FEATHER = 70.0, 170.0, 6.0
    SAT_MIN, VAL_MIN = 0.15, 0.15
    lo, hi = GREEN_HUE_MIN - FEATHER, GREEN_HUE_MAX + FEATHER

    hue, sat, val = rgb_to_hsv(frame)
    in_hue = (np.clip((hue - lo) / FEATHER, 0, 1) * np.clip((hi - hue) / FEATHER, 0, 1))
    bg = (sat >= SAT_MIN) & (val >= VAL_MIN) & (hue >= lo) & (hue <= hi)
    alpha = np.where(bg, (1.0 - in_hue) * 255, 255).astype(np.float32)

    work = frame.astype(np.float32)
    g = work[..., 1]
    other = np.maximum(work[..., 0], work[..., 2])
    work[..., 1] = np.where(g > other, other, g)          # 去绿溢

    greenish = (sat >= 0.10) & (val >= 0.10) & (hue >= lo) & (hue <= hi)
    soft = np.clip(1.0 - in_hue * 0.6, 0.0, 1.0)
    alpha = np.where(greenish & (alpha > 127), alpha * soft, alpha)

    out = np.concatenate([work, alpha[..., None]], axis=2)
    return np.clip(out, 0, 255).astype(np.uint8)


def main():
    import numpy as np
    from PIL import Image
    import io as _io

    print()
    print("  量算：用 1280x720 源重建素材的代价")
    print("  " + "=" * 70)
    print("  每帧尺寸: %dx%d   全量帧数: %d" % (W, H, TOTAL_FRAMES))
    print()

    rows = []
    for name in ANIMATIONS:
        path = os.path.join(SRC_DIR, name + ".mp4")
        if not os.path.exists(path):
            print("  跳过（没有源）: %s" % name)
            continue
        for index in FRAMES:
            rgb = read_frame(path, index)
            rgba = key_and_clean(rgb)
            image = Image.fromarray(rgba, "RGBA")

            # 原始 RGBA PNG
            buffer = _io.BytesIO()
            image.save(buffer, "PNG", optimize=True)
            raw_kb = buffer.tell() / 1024.0

            # 调色板量化（我们现在用的做法：256 色 + 原 alpha）
            alpha = image.getchannel("A")
            quantized = image.convert("RGB").quantize(colors=256, method=Image.MEDIANCUT)
            quantized = quantized.convert("RGBA")
            quantized.putalpha(alpha)
            buffer2 = _io.BytesIO()
            quantized.save(buffer2, "PNG", optimize=True)
            q_kb = buffer2.tell() / 1024.0

            rows.append((name, index, raw_kb, q_kb))
            print("     %-8s 第%3d帧   原始 RGBA %6.1f KB   256色 %6.1f KB"
                  % (name, index, raw_kb, q_kb))

    if not rows:
        print("  没采到样本")
        return 1

    raw_avg = sum(r[2] for r in rows) / len(rows)
    q_avg = sum(r[3] for r in rows) / len(rows)

    # 对照：现有 640x360 帧的实测平均体积
    current_dir = os.path.join(ROOT, "frames", ANIMATIONS[0])
    entries = sorted(os.listdir(current_dir))[:40]
    current_kb = sum(os.path.getsize(os.path.join(current_dir, e))
                     for e in entries) / float(len(entries)) / 1024.0

    print()
    print("  汇总（单帧平均）")
    print("  " + "-" * 70)
    print("     现有 640x360 帧（实测）      %6.1f KB" % current_kb)
    print("     新 1280x720 原始 RGBA       %6.1f KB   （%.1f 倍）"
          % (raw_avg, raw_avg / current_kb))
    print("     新 1280x720 256 色调色板     %6.1f KB   （%.1f 倍）"
          % (q_avg, q_avg / current_kb))

    print()
    print("  全量 %d 帧的磁盘预算" % TOTAL_FRAMES)
    print("  " + "-" * 70)
    print("     现有（640x360，256 色）     %5.2f GB" % (current_kb * TOTAL_FRAMES / 1048576.0))
    print("     新 1280x720 原始 RGBA        %5.2f GB" % (raw_avg * TOTAL_FRAMES / 1048576.0))
    print("     新 1280x720 256 色           %5.2f GB" % (q_avg * TOTAL_FRAMES / 1048576.0))

    print()
    print("  显示链路换算（本机 dpr = 2.0）")
    print("  " + "-" * 70)
    print("     size=320  -> 640 物理像素   源 1280 缩到 640 = 2 倍超采样（边缘更干净）")
    print("     size=480  -> 960 物理像素   源 1280 缩到 960 = 1.33 倍超采样")
    print("     size=640  -> 1280 物理像素  **1:1，宠物比现在大一倍且同样锐利**")
    return 0


if __name__ == "__main__":
    sys.exit(main())
