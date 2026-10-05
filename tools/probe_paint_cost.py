# -*- coding: utf-8 -*-
"""量一下：帧换成 1280x720 后，绘制开销会不会成为瓶颈。

为什么必须量：`PetWindow._draw_sprite()` 是

    painter.drawPixmap(self.sprite_rect(), pixmap, QRectF(pixmap.rect()))

也就是**每次重绘都把整张帧缩放到窗口尺寸**（`SmoothPixmapTransform` 是开着的）。
而 `FrameStore` 缓存的 QPixmap 是**文件原生分辨率**：

  * 现在帧是 640x360，画到 ~640x360 —— 尺寸基本一致，接近位块传送
  * 换成 1280x720 后，每帧要真的把 4 倍像素重采样一次

窗口重绘是 30fps，所以这是每秒 30 次重采样。如果开销可观，就必须**在加载时
把 QPixmap 预先缩放到绘制尺寸**（每个动画只做一次），而不是每帧现缩。

本脚本用同一套绘制路径测三种情形的耗时：
  A. 640x360 源 -> 640 目标（现状）
  B. 1280x720 源 -> 640 目标（2 倍超采样）
  C. 1280x720 源 -> 1280 目标（1:1，宠物显示大一倍）

    python tools/probe_paint_cost.py
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

HIRES = r"E:\dsh\_src\hires\东张西望"
CURRENT = os.path.join(ROOT, "frames", "东张西望")
ROUNDS = 300


def main():
    try:
        from PyQt5.QtCore import QRectF, Qt
        from PyQt5.QtGui import QPainter, QPixmap
        from PyQt5.QtWidgets import QApplication
    except ImportError as error:
        print("  需要 PyQt5: %s" % error)
        return 1

    app = QApplication([])

    def measure(source_png, target_w, target_h, label):
        pixmap = QPixmap(source_png)
        if pixmap.isNull():
            print("  %-42s **打不开 %s**" % (label, source_png))
            return None
        canvas = QPixmap(target_w, target_h)
        canvas.fill(Qt.transparent)
        rect = QRectF(0, 0, target_w, target_h)
        source_rect = QRectF(pixmap.rect())
        # 预热
        for _ in range(20):
            painter = QPainter(canvas)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.drawPixmap(rect, pixmap, source_rect)
            painter.end()
        started = time.perf_counter()
        for _ in range(ROUNDS):
            painter = QPainter(canvas)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.drawPixmap(rect, pixmap, source_rect)
            painter.end()
        elapsed = time.perf_counter() - started
        per = elapsed / ROUNDS * 1000.0
        budget = 1000.0 / 30.0
        print("  %-42s %6.2f ms/帧   占 30fps 预算 %.1f%%"
              % (label, per, per / budget * 100.0))
        return per

    print()
    print("  绘制开销（每帧把源缩放到目标尺寸，%d 次平均）" % ROUNDS)
    print("  " + "=" * 74)

    current_png = os.path.join(CURRENT, "0031.png")
    hires_png = os.path.join(HIRES, "0031.png")
    if not os.path.isfile(hires_png):
        print("  还没有高分辨率样片: %s" % hires_png)
        print("  先跑: python tools/build_hires_sample.py 东张西望")
        hires_png = None

    results = {}
    results["A"] = measure(current_png, 640, 360, "A 640x360 源 -> 640x360 目标（现状）")
    if hires_png:
        results["B"] = measure(hires_png, 640, 360, "B 1280x720 源 -> 640x360 目标（2倍超采样）")
        results["C"] = measure(hires_png, 1280, 720, "C 1280x720 源 -> 1280x720 目标（1:1 大图）")

    print()
    print("  判读")
    print("  " + "=" * 74)
    if results.get("A") and results.get("B"):
        ratio = results["B"] / results["A"]
        print("  B/A = %.2f 倍" % ratio)
        if ratio > 3.0:
            print("  **重采样开销显著** —— 必须把 QPixmap 在加载时预缩放到绘制尺寸，")
            print("  否则 30fps 下每帧都在现缩 1280x720。")
        else:
            print("  开销可接受；但预缩放仍然值得做（一次缩放胜过每帧缩放）。")
    if results.get("C"):
        print("  C 是 1:1 绘制（不缩放），所以反而便宜 —— 大图并不等于更慢。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
