# -*- coding: utf-8 -*-
"""出"size 调到 640 时你会看到什么"的对照图。

前提：`tools/install_hires_demo.py` 已把高清帧**几何归一化**成现有帧的 2 倍
（实测包围盒偏差 1 像素）。所以这两者在构图、角色大小、站位上**完全一致**，
唯一的差别就是分辨率 —— 这正是"把宠物放大一倍"时该看到的差别。

    左：现有 640x360 放大到 1280x720（这就是 size=640 时原版的样子）
    右：高清 1280x720 1:1

    python tools/compare_at_size640.py 东张西望
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SUFFIX = "-高清"
BACKGROUND = (52, 56, 68)
FRAMES = ["0031.png", "0060.png"]
ZOOM = (470, 100, 910, 440)          # 1280x720 坐标下的头部


def flatten(image):
    from PIL import Image
    canvas = Image.new("RGB", image.size, BACKGROUND)
    canvas.paste(image, (0, 0), image)
    return canvas


def main():
    argv = sys.argv[1:]
    animation = argv[0] if argv and not argv[0].startswith("-") else "东张西望"
    try:
        from PIL import Image
    except ImportError:
        print("  需要 Pillow")
        return 1

    old_dir = os.path.join(ROOT, "frames", animation)
    new_dir = os.path.join(ROOT, "frames", animation + SUFFIX)
    if not os.path.isdir(new_dir):
        print("  还没安装高清版: %s" % new_dir)
        return 1

    rows = []
    for name in FRAMES:
        old_path = os.path.join(old_dir, name)
        new_path = os.path.join(new_dir, name)
        if not (os.path.exists(old_path) and os.path.exists(new_path)):
            continue
        old = Image.open(old_path).convert("RGBA")
        new = Image.open(new_path).convert("RGBA")
        old_up = old.resize(new.size, Image.LANCZOS)
        rows.append(("现有 640 放大到 1280（原版在 size=640 下的样子）", flatten(old_up)))
        rows.append(("高清 1280 1:1（%s，第 %s 帧）" % (animation + SUFFIX, name[:4]),
                     flatten(new)))

    if not rows:
        print("  没有可比较的帧")
        return 1

    panel_w, panel_h = 380, 214
    zoom_w, zoom_h = 380, 296
    sheet = Image.new("RGB", (panel_w + zoom_w + 44, (panel_h + 24) * len(rows) + 10),
                      (20, 22, 28))
    for index, (_label, image) in enumerate(rows):
        y = 5 + index * (panel_h + 24)
        sheet.paste(image.resize((panel_w, panel_h), Image.LANCZOS), (10, y + 18))
        sheet.paste(image.crop(ZOOM).resize((zoom_w, zoom_h), Image.NEAREST),
                    (panel_w + 30, y + 18))
    out = os.path.join(ROOT, "logs", "compare-at-size640.png")
    sheet.save(out)
    print()
    print("  已写出 %s" % os.path.relpath(out, ROOT))
    print("  每两行一组：上=现有放大两倍（会糊）  下=高清 1:1（锐）")
    print("  右列是头部区域的 NEAREST 放大，刻意不插值，便于看像素")
    return 0


if __name__ == "__main__":
    sys.exit(main())
