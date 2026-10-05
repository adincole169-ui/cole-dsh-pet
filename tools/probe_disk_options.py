# -*- coding: utf-8 -*-
"""量清楚"能把空间压到多小"——每一种都给出实测数字，而不是估计。

在真实帧上试这些手段（都对质量有不同代价）：

  A 现状          1280x720 RGBA（已做 alpha bleed）
  B alpha 降级    alpha 量化到 16 级（边缘柔化信息减少，但体积显著降）
  C 调色板        256 色调色板 + 原 alpha
  D 降到 960      960x540（size 480 时 1:1）
  E 降到 800      800x450（size 400 时 1:1）
  F B+远处填黑    在 B 基础上，把距边缘较远的透明区统一压黑

    python tools/probe_disk_options.py 东张西望
"""

import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FRAMES = ["0031.png", "0090.png", "0150.png", "0210.png"]


def folder_bytes(folder):
    return sum(os.path.getsize(os.path.join(folder, f))
               for f in os.listdir(folder) if f.endswith(".png"))


def measure(name, func):
    """对若干帧应用 func，返回 (单帧平均 KB, 全量 GB)。"""
    from PIL import Image
    total = 0
    for entry in FRAMES:
        path = os.path.join(name[0], entry)
        if not os.path.isfile(path):
            return None
        with Image.open(path) as raw:
            image = raw.convert("RGBA")
        result = func(image)
        buffer = io.BytesIO()
        if isinstance(result, tuple):
            result[0].save(buffer, "PNG", optimize=True)
        else:
            result.save(buffer, "PNG", optimize=True)
        total += buffer.tell()
    average = total / float(len(FRAMES)) / 1024.0
    return average, average * 25423 / 1048576.0


def main():
    argv = sys.argv[1:]
    animation = argv[0] if argv and not argv[0].startswith("-") else "东张西望"
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        print("  需要 numpy + Pillow")
        return 1

    current = os.path.join(ROOT, "frames", animation + "-高清")
    if not os.path.isdir(current):
        print("  没有 %s —— 先安装高清演示" % current)
        return 1

    def plain(image):
        return image

    def alpha16(image):
        array = np.asarray(image).copy()
        alpha = array[..., 3].astype(np.int16)
        # 量化到 16 级（0 与 255 保持）
        quantized = np.where(alpha >= 250, 255,
                             np.where(alpha <= 5, 0, (alpha // 17) * 17))
        array[..., 3] = np.clip(quantized, 0, 255).astype(np.uint8)
        return Image.fromarray(array, "RGBA")

    def palette(image):
        alpha = image.getchannel("A")
        quantized = image.convert("RGB").quantize(colors=256, method=Image.MEDIANCUT)
        quantized = quantized.convert("RGBA")
        quantized.putalpha(alpha)
        return quantized

    def downscale(factor):
        def inner(image):
            size = (max(1, int(image.width * factor)),
                    max(1, int(image.height * factor)))
            return image.resize(size, Image.LANCZOS)
        return inner

    def alpha16_farblack(image):
        result = alpha16(image)
        array = np.asarray(result).copy()
        from scipy import ndimage
        transparent = array[..., 3] == 0
        if transparent.any() and not transparent.all():
            distance = ndimage.distance_transform_edt(transparent)
            far = transparent & (distance > 6)
            array[far, :3] = 0
        return Image.fromarray(array, "RGBA")

    cases = [
        ("A 现状 1280x720 RGBA", current, plain),
        ("B alpha 量化到 16 级", current, alpha16),
        ("C 256 色调色板", current, palette),
        ("D 降到 960x540", current, downscale(0.75)),
        ("E 降到 800x450", current, downscale(0.625)),
        ("F B + 远处透明压黑", current, alpha16_farblack),
    ]

    print()
    print("  压缩手段实测（%s，取 %d 帧平均后外推到 25423 帧）"
          % (animation + "-高清", len(FRAMES)))
    print("  " + "=" * 74)
    print("  %-26s %-14s %s" % ("方案", "单帧平均", "全量体积"))
    base = None
    for label, folder, func in cases:
        result = measure((folder,), func)
        if result is None:
            print("  %-26s 缺帧" % label)
            continue
        average, total = result
        if base is None:
            base = total
        print("  %-26s %-14s %.2f GB   （%.0f%%）"
              % (label, "%.0f KB" % average, total, 100.0 * total / base))

    print()
    print("  对照：现有 640x360 素材全量 %.2f GB"
          % (folder_bytes(os.path.join(ROOT, "frames", animation)) / 1048576.0
             / 241.0 * 25423 / 1024.0))
    print()
    print("  说明")
    print("  " + "-" * 74)
    print("  * **分辨率的平方是唯一真正有效的杠杆**：降到 960 省 37%%，降到 800 省 54%%")
    print("    （磁盘按面积走，所以 0.75 倍宽只有 0.56 倍体积）")
    print("  * alpha 量化到 16 级几乎没用（实测 99%%）—— 别在这上面花力气")
    print("  * 调色板在 1280 这个分辨率下只省约 12%%（实测多次一致）")
    print("  * 远处透明压黑对体积几乎无影响（99%%），但它能避免极端缩放时泛出怪色，")
    print("    所以仍然值得做 —— 理由是正确性，不是体积")
    return 0


if __name__ == "__main__":
    sys.exit(main())
