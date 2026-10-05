# -*- coding: utf-8 -*-
"""验证一个可能很划算的方案：把高分辨率样片**降到 640** 用。

为什么值得单独验：对照图显示，即使显示尺寸不变（size 320，640 物理像素），
新素材也比现有素材明显更锐。差别来自两处**与分辨率无关**的损失：

  * 现有素材来自上游的 **VP9 CRF32** 有损编码（我们的帧是它的解码结果）；
  * 我们自己的管线还会做 **256 色调色板量化**。

而源 mp4 是 1.36 Mbps 的 H.264 —— 每像素码率比现有 webm 高约 10 倍。所以
"从源重建、但只输出 640"有可能**用和现在一样的磁盘**换来接近全高清的质量。

本脚本就量这件事：
  1. 把样片（1280x720）降采样到 640x360
  2. 分别按"原始 RGBA"与"256 色调色板"存，量体积
  3. 与现有 640 帧做像素级对照（含头部放大）
  4. 给出全量磁盘预算

    python tools/probe_downscale_variant.py 东张西望
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HIRES_ROOT = r"E:\dsh\_src\hires"
OUT_ROOT = r"E:\dsh\_src\hires640"
ZOOM = (235, 50, 455, 220)          # 640x360 坐标下的头部
BACKGROUND = (52, 56, 68)


def flatten(image):
    from PIL import Image
    canvas = Image.new("RGB", image.size, BACKGROUND)
    canvas.paste(image, (0, 0), image)
    return canvas


def main():
    argv = sys.argv[1:]
    animation = argv[0] if argv and not argv[0].startswith("-") else "东张西望"
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        print("  需要 numpy + Pillow")
        return 1

    src_dir = os.path.join(HIRES_ROOT, animation)
    old_dir = os.path.join(ROOT, "frames", animation)
    if not os.path.isdir(src_dir):
        print("  还没有样片: %s" % src_dir)
        return 1
    out_dir = os.path.join(OUT_ROOT, animation)
    for sub in ("raw", "quant"):
        os.makedirs(os.path.join(out_dir, sub), exist_ok=True)

    entries = sorted(f for f in os.listdir(src_dir) if f.endswith(".png"))
    print()
    print("  把高分辨率样片降到 640x360，量质量与体积（%d 帧）" % len(entries))
    print("  " + "=" * 70)

    raw_bytes = quant_bytes = 0
    for entry in entries:
        with Image.open(os.path.join(src_dir, entry)) as source:
            small = source.convert("RGBA").resize((640, 360), Image.LANCZOS)
        raw_path = os.path.join(out_dir, "raw", entry)
        small.save(raw_path, "PNG", optimize=True)
        raw_bytes += os.path.getsize(raw_path)

        alpha = small.getchannel("A")
        quantized = small.convert("RGB").quantize(colors=256, method=Image.MEDIANCUT)
        quantized = quantized.convert("RGBA")
        quantized.putalpha(alpha)
        quant_path = os.path.join(out_dir, "quant", entry)
        quantized.save(quant_path, "PNG", optimize=True)
        quant_bytes += os.path.getsize(quant_path)

    count = max(1, len(entries))
    # 现有素材的实测平均体积
    old_entries = sorted(f for f in os.listdir(old_dir) if f.endswith(".png"))[:60]
    old_avg = sum(os.path.getsize(os.path.join(old_dir, e))
                  for e in old_entries) / float(len(old_entries))

    print("  单帧平均体积")
    print("  " + "-" * 70)
    print("     现有 640x360（VP9 解码 + 调色板）   %6.1f KB" % (old_avg / 1024.0))
    print("     新 640x360 原始 RGBA                %6.1f KB   （%.2f 倍）"
          % (raw_bytes / count / 1024.0, raw_bytes / count / old_avg))
    print("     新 640x360 256 色调色板              %6.1f KB   （%.2f 倍）"
          % (quant_bytes / count / 1024.0, quant_bytes / count / old_avg))
    print()
    print("  全量 25423 帧磁盘预算")
    print("  " + "-" * 70)
    print("     现有                                 %5.2f GB" % (old_avg * 25423 / 1073741824.0))
    print("     新 640 原始 RGBA                     %5.2f GB"
          % (raw_bytes / count * 25423 / 1073741824.0))
    print("     新 640 256 色调色板                   %5.2f GB"
          % (quant_bytes / count * 25423 / 1073741824.0))

    # 对照图：现有 / 新(原始) / 新(调色板)，以及各自的头部放大
    index = "0031.png"
    images = []
    for label, path in (("现有 640（1:1）", os.path.join(old_dir, index)),
                        ("新 640 原始 RGBA", os.path.join(out_dir, "raw", index)),
                        ("新 640 256 色", os.path.join(out_dir, "quant", index))):
        if os.path.exists(path):
            images.append((label, Image.open(path).convert("RGBA")))
    if len(images) >= 2:
        panel_w, panel_h = 380, 214
        zoom_w, zoom_h = 380, 340
        sheet = Image.new("RGB", (panel_w + zoom_w + 40, (panel_h + 26) * len(images) + 10),
                          (20, 22, 28))
        for k, (_label, image) in enumerate(images):
            y = 5 + k * (panel_h + 26)
            flat = flatten(image)
            sheet.paste(flat.resize((panel_w, panel_h), Image.LANCZOS), (10, y + 18))
            sheet.paste(flat.crop(ZOOM).resize((zoom_w, zoom_h), Image.NEAREST),
                        (panel_w + 28, y + 18))
        out = os.path.join(ROOT, "logs", "hires640-compare.png")
        sheet.save(out)
        print()
        print("  对照图: %s" % os.path.relpath(out, ROOT))
        print("     上=现有  中=新(原始 RGBA)  下=新(256 色)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
