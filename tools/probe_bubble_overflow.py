# -*- coding: utf-8 -*-
"""量一下：气泡**量尺寸用的字体**与**画笔默认字体**差多少。

怀疑点：`_draw_bubble` 用 `QFont(FONT_FAMILY, 9)` 量文字宽度来定气泡大小，
但 `painter.drawText(...)` 之前**从来没有 `painter.setFont(...)`** ——
画出来用的是应用默认字体。两者不一致时，文字的实际宽度就和气泡宽度对不上，
表现就是"气泡装不下文字"。

这个脚本把两种字体的宽度/行高并排打出来，并**渲染成图**用像素验证：
文字墨迹（近白色）是否越出气泡矩形。

    python tools/probe_bubble_overflow.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

# **不要设 offscreen**：这一条要**真渲染**再看像素，而 offscreen 平台没有字体
# （Qt 会打印 "QFontDatabase: Cannot find font directory"），文字根本画不出来，
# 于是"找不到墨迹"——第一版就因此什么也没测到。真实平台下 QImage + QPainter
# 不需要可见窗口，足够。

TEXT = "窗外的云软绵绵的，好想咬一口呀，可是主人还在忙呢"


def main():
    from PyQt5.QtCore import QPoint, Qt
    from PyQt5.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter
    from PyQt5.QtWidgets import QApplication

    from config import load, pet_configs
    from frames import FrameStore
    from main import build_app
    from pet import PetWindow

    app = build_app([sys.argv[0]])

    print()
    print("  ① 两种字体的宽度/行高对比")
    print("  " + "=" * 74)
    layout_font = QFont("Microsoft YaHei UI", 9)
    default_font = app.font()
    print("  量尺寸用的字体: %s %dpt   画笔默认字体: %s %dpt"
          % (layout_font.family(), layout_font.pointSize(),
             default_font.family(), default_font.pointSize()))
    w_layout = QFontMetrics(layout_font).width(TEXT)
    w_default = QFontMetrics(default_font).width(TEXT)
    h_layout = QFontMetrics(layout_font).height()
    h_default = QFontMetrics(default_font).height()
    print("  同一句话宽度  : 按 layout %d px / 按默认 %d px（差 %+d px，%+.0f%%）"
          % (w_layout, w_default, w_default - w_layout,
             (w_default - w_layout) * 100.0 / max(1, w_layout)))
    print("  行高          : 按 layout %d px / 按默认 %d px（差 %+d px）"
          % (h_layout, h_default, h_default - h_layout))

    # ② 真渲染：把气泡画到一张空图上，找"近白色"的文字墨迹，看它是否越出气泡矩形
    print()
    print("  ② 渲染验证：文字墨迹是否落在气泡矩形内")
    print("  " + "-" * 74)
    pet_config = pet_configs(load())[0]
    store = FrameStore(keep=2)
    window = PetWindow(pet_config, store)
    window.show()
    for _ in range(20):
        app.processEvents()

    problems = []
    for size in (160, 320, 480):
        window.size_px = size
        window._resize_window()
        window.bubble_image = None
        window.say(TEXT, None, 5.0)
        for _ in range(6):
            app.processEvents()

        rect = window.bubble_rect
        image = QImage(window.width(), window.height(), QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        window._draw_bubble(painter, window.sprite_size()[0])
        painter.end()

        # 近白色 = 文字（气泡底是深色 24,28,38，描边是中蓝 120,170,255）
        left = top = 10 ** 6
        right = bottom = -1
        for y in range(image.height()):
            for x in range(image.width()):
                color = QColor(image.pixel(x, y))
                if color.alpha() > 200 and color.red() > 180 \
                        and color.green() > 190 and color.blue() > 200:
                    left = min(left, x)
                    top = min(top, y)
                    right = max(right, x)
                    bottom = max(bottom, y)
        if right < 0:
            print("  size=%-4d 没找到文字墨迹（无法判断）" % size)
            continue
        inside = (rect is not None
                  and left >= rect.left() - 1 and right <= rect.right() + 1
                  and top >= rect.top() - 1 and bottom <= rect.bottom() + 1)
        over_w = max(0, int(right - rect.right()))
        over_h = max(0, int(bottom - rect.bottom()))
        print("  size=%-4d 气泡=(%d,%d %dx%d)  文字墨迹=(%d,%d)-(%d,%d)  越界 %s"
              % (size, rect.left(), rect.top(), rect.width(), rect.height(),
                 left, top, right, bottom,
                 "无 ✓" if inside else "右 %d px / 下 %d px ✗" % (over_w, over_h)))
        if not inside:
            problems.append("size=%d：文字越出气泡（右 %d / 下 %d px）"
                            % (size, over_w, over_h))
        window.clear_bubble()
        app.processEvents()

    window.close()
    store.close()
    print()
    if problems:
        for item in problems:
            print("     [问题] %s" % item)
        return 1
    print("  结论：各尺寸下文字墨迹都在气泡内。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
