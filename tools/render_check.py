# -*- coding: utf-8 -*-
"""把"角色实际画的"和"掩膜允许的"导出成两张图，比对它们的占位。

这是定位"图像显示不全"的关键一步：`setMask` 既限制点击**也裁掉绘制**，所以只要两者
错位，角色就会缺一块。用同一张底色渲染 + 同一套 alpha 判据，才能看出到底谁偏了。

    python tools/render_check.py
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


def occupied_box(image, alpha_min=ALPHA_MIN):
    left = top = 10 ** 9
    right = bottom = -1
    for y in range(image.height()):
        for x in range(image.width()):
            if QColor(image.pixel(x, y)).alpha() > alpha_min:
                left = min(left, x)
                top = min(top, y)
                right = max(right, x)
                bottom = max(bottom, y)
    return None if right < left else (left, top, right, bottom)


def main(argv):
    app = build_app([argv[0]])
    store = FrameStore(keep=4)
    window = PetWindow(pet_configs(load())[0], store)
    window.show()
    names = list((pet_configs(load())[0].animations.get("events") or {}).get("workStatus") or [])[:1]
    names += [(pet_configs(load())[0].actions("idle") or ["待机呼吸休闲"])[0]]

    rows = []
    for index, name in enumerate(names):
        store.animation(name)
        window.animator.play(name, loop=True)
        window._mask_key = None
        for _ in range(6):
            window.animator._tick()
            window._repaint()
            app.processEvents()

        # 1) 去掉掩膜，看"角色本来该占哪"：临时清掉掩膜再渲染
        saved = window.mask()
        window.clearMask()
        canvas = QImage(window.width(), window.height(), QImage.Format_ARGB32)
        canvas.fill(Qt.transparent)
        painter = QPainter(canvas)
        window.render(painter)
        painter.end()
        sprite_box = occupied_box(canvas)
        window.setMask(saved)

        # 2) 掩膜的占位
        rect = window.mask().boundingRect()
        mask_box = (rect.left(), rect.top(), rect.right(), rect.bottom())
        # 掩膜位图本身也存一份，肉眼确认白色（可显示/可点）到底在哪
        window._build_input_bitmap(
            window.animator.current_frame(), window.sprite_rect(), int(window.top_pad)
        ).toImage().convertToFormat(QImage.Format_ARGB32).save(
            os.path.join(ROOT, "logs", "mask-raw-%d.png" % index), "PNG")

        # 3) 带掩膜时的实际显示（渲染到深底上）
        shown = QImage(window.width(), window.height(), QImage.Format_ARGB32)
        shown.fill(QColor(40, 44, 56))
        painter = QPainter(shown)
        window.render(painter)
        painter.end()

        print("  %-16s 角色占位=%s  掩膜占位=%s" % (name, sprite_box, mask_box))
        rows.append((name, canvas, shown))

    # 输出：每个动画一行两张（左=角色本来的样子，右=带掩膜的实际显示）
    tile_w = max(1, window.width())
    tile_h = max(1, window.height())
    sheet = QImage(tile_w * 2 + 12, tile_h * len(rows) + 8 * (len(rows) - 1),
                   QImage.Format_ARGB32)
    sheet.fill(QColor(20, 22, 28))
    painter = QPainter(sheet)
    y = 0
    for _name, canvas, shown in rows:
        backdrop = QImage(tile_w, tile_h, QImage.Format_ARGB32)
        backdrop.fill(QColor(40, 44, 56))
        inner = QPainter(backdrop)
        inner.drawImage(0, 0, canvas)
        inner.end()
        painter.drawImage(0, y, backdrop)
        painter.drawImage(tile_w + 12, y, shown)
        y += tile_h + 8
    painter.end()
    out = os.path.join(ROOT, "logs", "mask-check.png")
    sheet.save(out, "PNG")
    print("  已存 %s（左=角色本来该有的样子，右=当前实际显示）" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
