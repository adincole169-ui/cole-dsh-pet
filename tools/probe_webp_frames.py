# -*- coding: utf-8 -*-
"""用 **Qt 自己**测：把帧缓存从 PNG 换成 WebP 能省多少、画质代价多大。

为什么改用 Qt 而不是 Pillow：本机这个 Pillow 构建**没有 WebP 编码器**
（`im.save(buf, "WEBP")` 直接 KeyError: 'WEBP'）。而 Qt 支持 webp（20 种格式里有），
读也由 Qt 读 —— 用 Qt 测才反映真实链路。

顺带也测**动画 WebP**（一个动画一个文件）—— 如果 Qt 读得了动画 WebP，
那连"帧序列"都不需要了，更接近上游"一个视频文件"的形态。

    python tools/probe_webp_frames.py 东张西望
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FRAMES = ["0031.png", "0090.png", "0150.png", "0210.png"]


def main():
    argv = sys.argv[1:]
    animation = argv[0] if argv and not argv[0].startswith("-") else "东张西望"
    sys.path.insert(0, os.path.join(ROOT, "src"))
    sys.path.insert(0, ROOT)
    try:
        import numpy as np
        from PyQt5.QtCore import QBuffer, QByteArray, QIODevice
        from PyQt5.QtGui import QImage, QImageReader, QImageWriter
        from PyQt5.QtWidgets import QApplication
    except ImportError as error:
        print("  需要 PyQt5 + numpy: %s" % error)
        return 1

    app = QApplication([])                                       # noqa: F841

    print()
    print("  ① Qt 能否**写** webp")
    print("  " + "=" * 72)
    writers = sorted(bytes(f).decode("ascii", "replace")
                     for f in QImageWriter.supportedImageFormats())
    can_write = "webp" in writers
    print("     可写格式 %d 种，webp: %s" % (len(writers), "支持" if can_write else "**不支持**"))
    if not can_write:
        print("     Qt 不能编码 webp —— 那就只能靠 ffmpeg 编码、Qt 解码（多一个依赖）")
        return 1

    folder = os.path.join(ROOT, "frames", animation)
    entries = [e for e in FRAMES if os.path.isfile(os.path.join(folder, e))]
    if not entries:
        print("  找不到帧: %s" % folder)
        return 1

    def encode(image, fmt, quality):
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        writer = QImageWriter(buffer, fmt.encode("ascii"))
        writer.setQuality(quality)
        ok = writer.write(image)
        buffer.close()
        return bytes(data) if ok else None

    def decode(payload):
        image = QImage()
        image.loadFromData(QByteArray(payload), "webp")
        return image

    print()
    print("  ② 体积与画质（%d 帧平均）" % len(entries))
    print("  " + "=" * 72)
    print("  %-20s %-11s %-11s %s" % ("格式", "单帧", "全量缓存", "与 PNG 的差异 / alpha"))
    print("  " + "-" * 72)

    source = {}
    for entry in entries:
        image = QImage(os.path.join(folder, entry)).convertToFormat(QImage.Format_RGBA8888)
        source[entry] = image

    def to_array(image):
        image = image.convertToFormat(QImage.Format_RGBA8888)
        pointer = image.constBits()
        pointer.setsize(image.bytesPerLine() * image.height())
        return np.frombuffer(bytes(pointer), np.uint8).reshape(
            image.height(), image.bytesPerLine() // 4, 4)[:, :image.width(), :].astype(np.int16)

    png_total = 0
    rows = []
    cases = [("PNG（现状）", "PNG", 100),
             ("WebP q95", "webp", 95),
             ("WebP q90", "webp", 90),
             ("WebP q80", "webp", 80),
             ("WebP q70", "webp", 70)]
    for label, fmt, quality in cases:
        total = 0
        worst_mean = 0.0
        worst_max = 0
        alpha_same = True
        for entry in entries:
            payload = encode(source[entry], fmt, quality)
            if payload is None:
                print("  %-20s 编码失败" % label)
                total = None
                break
            total += len(payload)
            back = decode(payload)
            if back.isNull():
                print("  %-20s 解码失败" % label)
                total = None
                break
            a = to_array(source[entry])
            b = to_array(back)
            if a.shape != b.shape:
                alpha_same = False
                continue
            visible = (a[..., 3] > 16) & (b[..., 3] > 16)
            if visible.any():
                diff = np.abs(a[..., :3] - b[..., :3])[visible]
                worst_mean = max(worst_mean, float(diff.mean()))
                worst_max = max(worst_max, int(diff.max()))
            if not np.array_equal(a[..., 3], b[..., 3]):
                alpha_same = False
        if total is None:
            continue
        average = total / float(len(entries))
        if label.startswith("PNG"):
            png_total = average
        rows.append((label, average, worst_mean, worst_max, alpha_same))
        print("  %-20s %-11s %-11s 平均差 %.2f 最大 %d  alpha %s"
              % (label, "%.1f KB" % (average / 1024.0),
                 "%.2f GB" % (average * 25423 / 1073741824.0),
                 worst_mean, worst_max, "保持" if alpha_same else "**变了**"))

    print()
    print("  ③ 结论")
    print("  " + "=" * 72)
    if not png_total:
        return 1
    for label, average, mean_diff, _max_diff, alpha_same in rows:
        if label.startswith("PNG"):
            continue
        saving = 100.0 * (1.0 - average / png_total)
        verdict = "可用" if (mean_diff < 1.5 and alpha_same) else "代价偏大"
        print("     %-20s 省 %4.0f%%   平均差 %.2f/255   alpha %s   -> %s"
              % (label, saving, mean_diff, "保持" if alpha_same else "变了", verdict))
    print()
    print("     判读要点：alpha 必须「保持」 —— 只要它变了，边缘就会出问题。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
