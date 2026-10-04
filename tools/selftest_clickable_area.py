# -*- coding: utf-8 -*-
"""自检：角色的**可见区域必须可点**，透明留白必须**穿透**。

为什么重要：`setMask` 同时裁"绘制"和"输入"。用户报"拖不动大肥鱼"，
最直接的解释就是——按下去的那个点不在掩膜里，于是 `mousePressEvent` 根本没被触发，
`dragging` 起不来，拖拽完全无效（而掩膜每次重建又会把窗口搬回出生点）。

所以要验两件事，方向相反：
  1. 角色包围盒**内部**的采样点 -> 必须在掩膜里（可点、可拖）；
  2. 窗口四角那片**全透明**区域   -> 必须不在掩膜里（点击穿透到下层）。

掩膜的位语义容易记反（`Format_Mono` 下黑=置位=可点，且构造时 `mask_invert=True`），
所以这里不靠推理，直接用 `window.mask()` 这个 Qt 自己给的 QRegion 去判定。

    python tools/selftest_clickable_area.py
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from PyQt5.QtCore import QPoint                                  # noqa: E402
from PyQt5.QtWidgets import QApplication                         # noqa: E402

from config import load, pet_configs                             # noqa: E402
from frames import FrameStore                                    # noqa: E402
from main import build_app                                       # noqa: E402
from pet import PetWindow                                        # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label, ("  " + detail) if detail else ""))
    if not ok:
        FAILED.append(label)


def inside(region, x, y):
    return region.contains(QPoint(int(x), int(y)))


def main():
    app = build_app([])
    config = load()
    entries = pet_configs(config)
    store = FrameStore(keep=6)
    window = PetWindow(entries[0], store)
    window.show()

    # 跑一会儿，让若干动画帧都算过掩膜（角色宽度在不同动画里差别很大）
    deadline = time.monotonic() + 6.0
    samples = []
    while time.monotonic() < deadline:
        app.processEvents()
        region = window.mask()
        stats = getattr(window, "mask_stats", None) or {}
        rect = stats.get("rect")
        if region and not region.isEmpty() and rect:
            samples.append((region, rect, window.width(), window.height()))
        time.sleep(0.05)

    print()
    print("  采样到 %d 个「已算好掩膜」的瞬间" % len(samples))
    if not samples:
        print("  **一个都没有** —— 掩膜始终为空，那整个窗口都不可点（这本身就是 bug）")
        return 1

    # --- 1. 角色包围盒内部必须可点 ---
    ok_inside = 0
    bad_inside = []
    for region, rect, width, height in samples:
        cx = rect[0] + rect[2] / 2.0
        cy = rect[1] + rect[3] / 2.0
        if inside(region, cx, cy):
            ok_inside += 1
        else:
            bad_inside.append((cx, cy, rect))

    print()
    print("  1) 角色包围盒**中心**是否可点")
    check("所有采样里角色中心都在掩膜内",
          ok_inside == len(samples),
          "%d/%d 可点%s" % (ok_inside, len(samples),
                          ("；反例 %s" % bad_inside[:2]) if bad_inside else ""))

    # --- 2. 窗口四角（全透明留白）必须穿透 ---
    corner_hits = []
    for region, rect, width, height in samples:
        corners = [(2, 2), (width - 3, 2), (2, height - 3), (width - 3, height - 3)]
        for x, y in corners:
            # 只要该角远离角色包围盒，就该在掩膜之外
            far_x = x < rect[0] - 6 or x > rect[0] + rect[2] + 6
            far_y = y < rect[1] - 6 or y > rect[1] + rect[3] + 6
            if far_x and far_y and inside(region, x, y):
                corner_hits.append((x, y, rect))
    print()
    print("  2) 远离角色的窗口四角是否**穿透**（不该可点）")
    check("透明四角不在掩膜内", not corner_hits,
          "命中 %d 次%s" % (len(corner_hits), ("，例 %s" % corner_hits[:2]) if corner_hits else ""))

    # --- 3. 用真实鼠标事件走一遍拖动：位置必须真的变 ---
    print()
    print("  3) 合成一次真实拖动，窗口位置必须变化")
    window._user_took_over()
    region = window.mask()
    stats = getattr(window, "mask_stats", None) or {}
    rect = stats.get("rect")
    if rect:
        grab_x = int(rect[0] + rect[2] / 2.0)
        grab_y = int(rect[1] + rect[3] / 2.0)
    else:
        grab_x, grab_y = window.width() // 2, window.height() // 2
    print("     抓取点（角色中心）: (%d, %d)" % (grab_x, grab_y))

    from PyQt5.QtCore import QEvent, Qt
    from PyQt5.QtGui import QMouseEvent

    def event(kind, local, screen, button=Qt.LeftButton):
        """构造一个带**显式屏幕坐标**的鼠标事件。

        必须用 6 参数版 `(type, localPos, screenPos, button, buttons, modifiers)`：
        5 参数版会把 `globalPos()` 初始化成 `QCursor::pos()`（真实光标位置），
        于是所有合成事件的屏幕坐标都相同 —— 拖动里
        `target = globalPos + drag_offset` 恒等于当前位置，**位移永远是 0**，
        看起来就像"拖动无效"。本项目已有的 selftest_click 正是这个毛病。
        另外第 3 个参数才是 `event.button()`，传成 NoButton 会让处理器整个被跳过。
        """
        return QMouseEvent(kind, QPoint(*local), QPoint(*screen),
                           button, button, Qt.NoModifier)

    before = (window.pos_x, window.pos_y)
    grab_local = (grab_x, grab_y)
    grab_screen = (int(window.pos_x) + grab_x, int(window.pos_y) + grab_y)
    window.mousePressEvent(event(QEvent.MouseButtonPress, grab_local, grab_screen))
    dragging_started = window.dragging

    # 光标向左上移动，窗口应当跟过去
    for step in range(1, 9):
        dx, dy = -step * 12, -step * 7
        screen = (grab_screen[0] + dx, grab_screen[1] + dy)
        local = (grab_x + dx, grab_y + dy)
        window.mouseMoveEvent(event(QEvent.MouseMove, local, screen))
    window.mouseReleaseEvent(event(QEvent.MouseButtonRelease, local, screen))
    after = (window.pos_x, window.pos_y)
    check("按下能进入拖动状态", dragging_started, "dragging=%s" % dragging_started)
    check("拖动让窗口位置变化",
          abs(after[0] - before[0]) > 20 or abs(after[1] - before[1]) > 20,
          "(%.0f, %.0f) -> (%.0f, %.0f)" % (before[0], before[1], after[0], after[1]))

    print()
    if FAILED:
        print("  结论：%d 项不通过 —— 角色的可点区域有问题。" % len(FAILED))
    else:
        print("  结论：全部通过 —— 角色中心可点、透明处穿透、拖动生效。")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
