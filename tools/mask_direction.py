# -*- coding: utf-8 -*-
"""判定掩膜位的方向：把两种方向各渲染一次，量"实际显示了多少角色像素"。

背景：`QBitmap` 的位是"置位=可见且可点"，但把灰阶图转成位图时"白对应置位还是清零"
在这台机器上与我原先的假设相反——白处反而被裁掉了。这个脚本用数据判定，不靠推断：

  * 先渲染一张**不带掩膜**的基准图，量出角色像素数（这是上限）；
  * 再各用 `mask_invert=False/True` 渲染一次，量出实际显示的角色像素数；
  * 谁更接近基准，谁就是正确方向。

    python tools/mask_direction.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QImage, QPainter

from config import load, pet_configs
from frames import FrameStore
from main import build_app
from pet import PetWindow

ALPHA_MIN = 16


def visible_pixels(window, use_mask):
    """渲染窗口，数"非透明且非背景"的像素（背景填纯洋红以便区分）。"""
    if not use_mask:
        saved = window.mask()
        window.clearMask()
    canvas = QImage(window.width(), window.height(), QImage.Format_ARGB32)
    canvas.fill(QColor(255, 0, 255))
    painter = QPainter(canvas)
    window.render(painter)
    painter.end()
    if not use_mask:
        window.setMask(saved)

    count = 0
    for y in range(canvas.height()):
        for x in range(canvas.width()):
            color = QColor(canvas.pixel(x, y))
            # 洋红背景 = 没画东西
            if not (color.red() > 250 and color.green() < 5 and color.blue() > 250):
                count += 1
    return count


def main(argv):
    app = build_app([argv[0]])
    store = FrameStore(keep=4)
    window = PetWindow(pet_configs(load())[0], store)
    window.show()

    name = (pet_configs(load())[0].actions("idle") or ["待机呼吸休闲"])[0]
    store.animation(name)
    window.animator.play(name, loop=True)

    def settle():
        window._mask_key = None
        for _ in range(6):
            window.animator._tick()
            window._repaint()
            app.processEvents()

    settle()
    baseline = visible_pixels(window, use_mask=False)
    print("  基准（不带掩膜）显示像素: %d" % baseline)

    results = {}
    for invert in (False, True):
        window.mask_invert = invert
        settle()
        shown = visible_pixels(window, use_mask=True)
        results[invert] = shown
        print("  mask_invert=%-5s 显示像素: %d  (%.0f%% 于基准)"
              % (invert, shown, 100.0 * shown / max(1, baseline)))

    best = max(results, key=results.get)
    print("  => 正确方向是 mask_invert=%s" % best)
    if results[best] < baseline * 0.5:
        print("  !! 两个方向都远低于基准，说明掩膜把角色裁掉了，方向不是唯一问题")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
