# -*- coding: utf-8 -*-
"""评估"把 PNG 帧缓存换成更小的格式"是否可行、能省多少。

背景：上游是让浏览器/Electron 的 `<video>` 直接播透明 VP9 webm（GPU 解码，不落盘），
所以它只占 52 MB。我们因为 PyQt5 播不了带独立 alpha 流的 VP9，只能解成 PNG，
于是本机有 2.68 GB 缓存。

**但"播视频"不是唯一出路** —— 也可以**保持现有架构**（帧序列 → QPixmap），
只把存储格式从 PNG 换成更紧凑的。关键前提是 Qt 得能读、且**保住 alpha**。

本脚本量四件事：
  1. Qt（当前这套 PyQt5）支持哪些图片格式 —— 有没有 webp
  2. 带 alpha 的 WebP 读进来 alpha 还在不在
  3. 同一帧存成 PNG / 无损 WebP / 有损 WebP(q90/q80) 的体积
  4. 各自与 PNG 的逐像素差异（有损的代价有多大）

    python tools/probe_frame_format.py 东张西望
"""

import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FRAMES = ["0031.png", "0090.png", "0150.png", "0210.png"]


def main():
    argv = sys.argv[1:]
    animation = argv[0] if argv and not argv[0].startswith("-") else "东张西望"
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        print("  需要 numpy + Pillow")
        return 1

    # --- 1. Qt 支持哪些格式 ---
    print()
    print("  ① Qt 支持的图片格式")
    print("  " + "=" * 72)
    try:
        sys.path.insert(0, os.path.join(ROOT, "src"))
        sys.path.insert(0, ROOT)
        from PyQt5.QtGui import QImageReader
        from PyQt5.QtWidgets import QApplication
        app = QApplication([])                                   # noqa: F841
        formats = sorted(bytes(f).decode("ascii", "replace")
                         for f in QImageReader.supportedImageFormats())
        print("     数量: %d" % len(formats))
        print("     列表: %s" % ", ".join(formats))
        has_webp = "webp" in formats
        print("     **webp: %s**" % ("支持" if has_webp else "**不支持 —— 这条路走不通**"))
    except Exception as error:
        print("     取不到: %s" % error)
        has_webp = False

    # --- 2/3/4. 各格式的体积与差异 ---
    folder = os.path.join(ROOT, "frames", animation)
    if not os.path.isdir(folder):
        print("  找不到 %s" % folder)
        return 1
    entries = [e for e in FRAMES if os.path.isfile(os.path.join(folder, e))]
    if not entries:
        return 1

    cases = [
        ("PNG（现状）", lambda im, buf: im.save(buf, "PNG", optimize=True)),
        ("WebP 无损", lambda im, buf: im.save(buf, "WEBP", lossless=True, quality=100)),
        ("WebP 有损 q90", lambda im, buf: im.save(buf, "WEBP", quality=90)),
        ("WebP 有损 q80", lambda im, buf: im.save(buf, "WEBP", quality=80)),
        ("WebP 有损 q70", lambda im, buf: im.save(buf, "WEBP", quality=70)),
    ]

    print()
    print("  ② 各格式的体积与画质（%d 帧平均）" % len(entries))
    print("  " + "=" * 72)
    print("  %-18s %-12s %-12s %s" % ("格式", "单帧", "全量缓存", "与 PNG 的差异"))
    print("  " + "-" * 72)

    base_arrays = {}
    for entry in entries:
        with Image.open(os.path.join(folder, entry)) as raw:
            base_arrays[entry] = np.asarray(raw.convert("RGBA")).astype(np.int16)

    png_bytes = 0
    results = []
    for label, saver in cases:
        total = 0
        worst_mean = 0.0
        worst_max = 0
        alpha_ok = True
        for entry in entries:
            with Image.open(os.path.join(folder, entry)) as raw:
                image = raw.convert("RGBA")
            buffer = io.BytesIO()
            saver(image, buffer)
            total += buffer.tell()
            # 读回来比
            buffer.seek(0)
            with Image.open(buffer) as back:
                restored = np.asarray(back.convert("RGBA")).astype(np.int16)
            reference = base_arrays[entry]
            visible = (reference[..., 3] > 16) & (restored[..., 3] > 16)
            if visible.any():
                diff = np.abs(reference[..., :3] - restored[..., :3])[visible]
                worst_mean = max(worst_mean, float(diff.mean()))
                worst_max = max(worst_max, int(diff.max()))
            # alpha 是否被改动
            if not np.array_equal(reference[..., 3], restored[..., 3]):
                alpha_ok = False
        average = total / float(len(entries))
        if label.startswith("PNG"):
            png_bytes = average
        results.append((label, average, worst_mean, worst_max, alpha_ok))
        print("  %-18s %-12s %-12s 平均差 %.2f  最大 %d  alpha %s"
              % (label, "%.1f KB" % (average / 1024.0),
                 "%.2f GB" % (average * 25423 / 1073741824.0),
                 worst_mean, worst_max, "保持" if alpha_ok else "**变了**"))

    print()
    print("  ③ 结论")
    print("  " + "=" * 72)
    best = None
    for label, average, mean_diff, _max_diff, alpha_ok in results:
        if label.startswith("PNG"):
            continue
        saving = 100.0 * (1.0 - average / max(1.0, png_bytes))
        print("     %-18s 省 %4.0f%%   画质代价 平均差 %.2f/255"
              % (label, saving, mean_diff))
        if mean_diff < 1.0 and alpha_ok and (best is None or average < best[1]):
            best = (label, average, mean_diff)
    print()
    if best:
        print("     推荐: **%s** —— 省 %.0f%%，而平均差只有 %.2f/255（肉眼不可见），"
              % (best[0], 100.0 * (1.0 - best[1] / max(1.0, png_bytes)), best[2]))
        print("     alpha 完整保留。前提是 Qt 支持 webp（见 ①）。")
    else:
        print("     没有既保 alpha、画质代价又足够小的选项。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
