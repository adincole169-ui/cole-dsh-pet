# -*- coding: utf-8 -*-
"""alpha bleed：把透明区的 RGB 换成角色边缘的颜色，修掉缩放时的边缘偏色。

问题链（这次终于查清了）
------------------------
1. 我的抠像**只把背景 alpha 置 0，保留了它的 RGB** —— 而且因为去绿溢压了 G，
   那个 RGB 是**橄榄色 (140,140,117)**；上游手工素材的背景 RGB 近黑 (34,34,35)。
2. PNG 存的是**非预乘** RGBA。任何缩放（PIL.resize、Qt.drawPixmap、甚至
   生成掩膜时的缩放）都会**逐通道插值**，于是透明区的橄榄色被混进边缘：
   实测边缘均色 (73,76,75) -> (26,28,32)，明显发暗偏色。

做法
----
对每个透明像素，取其**最近的不透明像素的颜色**（`distance_transform_edt`
的 return_indices 一次算完）。这样边缘附近几像素内的 RGB 就都是角色色，
缩放混进来的自然也是角色色。

**只外扩 BLEED_PX 像素**：缩放核只有 2~3 像素宽，扩 6 像素足够；
更远处保持原样（平坦）有利于 PNG 压缩 —— 全图 bleed 会让背景变成渐变，
文件明显变大。

    python tools/bleed_alpha.py <目录> [--px 6]
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BLEED_PX = 6


def bleed(image_array, px=BLEED_PX):
    """返回 bleed 之后的 RGBA 数组。"""
    import numpy as np
    from scipy import ndimage

    alpha = image_array[..., 3]
    transparent = alpha == 0
    if not transparent.any() or transparent.all():
        return image_array

    # 每个像素到最近"不透明像素"的索引
    _distance, indices = ndimage.distance_transform_edt(transparent, return_indices=True)
    iy, ix = indices

    # 只处理距边缘 px 以内的透明像素
    near = transparent & (_distance <= px)
    out = image_array.copy()
    out[near, :3] = image_array[iy[near], ix[near], :3]

    # 更远处的透明像素统一压成近黑：既利于压缩，也不会在极端缩放时泛出怪色
    far = transparent & (_distance > px)
    out[far, :3] = 0
    return out


def process_folder(folder, px=BLEED_PX):
    import numpy as np
    from PIL import Image
    entries = sorted(f for f in os.listdir(folder) if f.endswith(".png"))
    changed = 0
    for entry in entries:
        path = os.path.join(folder, entry)
        with Image.open(path) as raw:
            array = np.asarray(raw.convert("RGBA"))
        result = bleed(array, px)
        if not np.array_equal(result, array):
            Image.fromarray(result, "RGBA").save(path, "PNG", optimize=True)
            changed += 1
    return len(entries), changed


def main():
    argv = sys.argv[1:]
    if not argv:
        print("  用法: python tools/bleed_alpha.py <目录> [--px N]")
        print("  例:   python tools/bleed_alpha.py frames/待机呼吸休闲-高清")
        return 2
    folder = argv[0]
    if not os.path.isabs(folder):
        folder = os.path.join(ROOT, folder)
    px = BLEED_PX
    if "--px" in argv:
        px = int(argv[argv.index("--px") + 1])
    if not os.path.isdir(folder):
        print("  没有目录: %s" % folder)
        return 1

    try:
        import numpy                                                # noqa: F401
        from PIL import Image                                       # noqa: F401
        from scipy import ndimage                                   # noqa: F401
    except ImportError as error:
        print("  需要 numpy + Pillow + scipy: %s" % error)
        return 1

    before = sum(os.path.getsize(os.path.join(folder, f))
                 for f in os.listdir(folder) if f.endswith(".png"))
    total, changed = process_folder(folder, px)
    after = sum(os.path.getsize(os.path.join(folder, f))
                for f in os.listdir(folder) if f.endswith(".png"))
    print()
    print("  alpha bleed 完成: %s" % os.path.relpath(folder, ROOT))
    print("  " + "=" * 62)
    print("     帧数        : %d（改了 %d）" % (total, changed))
    print("     外扩像素    : %d" % px)
    print("     体积        : %.1f MB -> %.1f MB（%+.1f%%）"
          % (before / 1048576.0, after / 1048576.0,
             100.0 * (after - before) / max(1, before)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
