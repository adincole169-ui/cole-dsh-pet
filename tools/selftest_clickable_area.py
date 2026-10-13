# -*- coding: utf-8 -*-
"""自检：角色的**可见区域必须可点**，透明留白必须**穿透**。

为什么重要：`setMask` 同时裁"绘制"和"输入"。用户报"拖不动大肥鱼"，
最直接的解释就是——按下去的那个点不在掩膜里，于是 `mousePressEvent` 根本没被触发，
`dragging` 起不来，拖拽完全无效（而掩膜每次重建又会把窗口搬回出生点）。

所以要验两件事，方向相反：
  1. **画出来的每一层**（角色本体，含交叉淡化的垫层）-> 必须**完整地**在掩膜里；
     只要有一像素被掩膜裁掉，屏幕上那块就画不出来；
  2. 窗口四角那片**全透明**区域   -> 必须不在掩膜里（点击穿透到下层）。

第 1 条原来是"掩膜包围盒的**中心**必须可点"。那个判据隐含了"掩膜只按一帧算"这个前提，
而交叉淡入时画的是**两层**（垫层 + 新段），两层并集的包围盒中心完全可能落在两个姿势之间
的空隙里 —— 于是修复"切换动作时角色消失 0.3 秒"（掩膜改成按 `sprite_layers()` 取并集）
之后，这个判据会**时而失败时而通过**（同一份代码实测出现过 67/90 与 89/89）。
判据必须与实现一致，所以改成直接量"有没有被裁掉"：

    实测（tools 里同一套缩放与阈值，见 _verify 的 measure_mask_clip）：
        并集规则（现在）    裁掉 0.0%
        只看 current_frame  交叉淡入期间裁掉 5~6%；新段那一帧还没有时裁掉 100%

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


def layer_pixels(window, frame):
    """某一层**实际画出来的**不透明像素（与 `_build_input_bitmap` 同一套缩放与阈值）。

    numpy 只在函数里 import：本项目的 `tools/check_without_numpy.py` 要求在**没有
    numpy** 的环境下也能跑起来，顶层 import 会把那条自检一起打断。
    """
    import numpy as np
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QImage

    rect = window.sprite_rect()
    margin = 2
    box_w = max(1, int(round(rect.width())) + margin * 2)
    box_h = max(1, int(round(rect.height())))
    image = frame.toImage().convertToFormat(QImage.Format_ARGB32)
    if image.width() != box_w or image.height() != box_h:
        image = image.scaled(box_w, box_h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    solid = np.frombuffer(window._threshold_bytes(image), dtype=np.uint8)
    return (solid.reshape(box_h, box_w) > 0,
            int(round(rect.left())) - margin, int(round(rect.top())), box_w, box_h)


def painted_pixels(window, frames):
    """`paintEvent` 这一帧画出来的全部像素（各层取并集）。"""
    import numpy as np

    height, width = window.height(), window.width()
    canvas = np.zeros((height, width), dtype=bool)
    for frame in frames:
        solid, left, top, box_w, box_h = layer_pixels(window, frame)
        sy0, sy1 = max(0, top), min(height, top + box_h)
        sx0, sx1 = max(0, left), min(width, left + box_w)
        if sy1 <= sy0 or sx1 <= sx0:
            continue
        canvas[sy0:sy1, sx0:sx1] |= solid[sy0 - top:sy1 - top, sx0 - left:sx1 - left]
    return canvas


def masked_pixels(window):
    """掩膜真正覆盖的像素（把 QRegion 的矩形栅格化）。"""
    import numpy as np

    height, width = window.height(), window.width()
    canvas = np.zeros((height, width), dtype=bool)
    region = window.mask()
    if region is None or region.isEmpty():
        return canvas
    for rect in region.rects():
        x0, y0 = max(0, rect.left()), max(0, rect.top())
        x1, y1 = min(width, rect.right() + 1), min(height, rect.bottom() + 1)
        if x1 > x0 and y1 > y0:
            canvas[y0:y1, x0:x1] = True
    return canvas


def main():
    app = build_app([])
    config = load()
    entries = pet_configs(config)
    store = FrameStore(keep=6)
    window = PetWindow(entries[0], store)
    window.show()

    # 跑一会儿，让若干动画帧都算过掩膜（角色宽度在不同动画里差别很大）。
    # 采样时就把"被裁掉多少"算好：掩膜每帧都会重建，事后拿旧的 QRegion 去对没有意义。
    #
    # **必须自己调 `_apply_input_mask()`**：生产路径里 `_repaint` 每帧都调
    # （`_apply_input_mask()` → `update()`），而这个自检没有跑 main 的定时器，
    # 不调的话掩膜会停在上一帧 —— 量到的就是"掩膜落后一帧"，不是掩膜的规则有问题。
    deadline = time.monotonic() + 6.0
    samples = []
    while time.monotonic() < deadline:
        app.processEvents()
        window._apply_input_mask()
        region = window.mask()
        stats = getattr(window, "mask_stats", None) or {}
        rect = stats.get("rect")
        if region and not region.isEmpty() and rect:
            frames = [frame for frame, _opacity in window.sprite_layers()]
            need = painted_pixels(window, frames) if frames else None
            cut = painted = 0
            if need is not None and need.any():
                painted = int(need.sum())
                cut = int((need & ~masked_pixels(window)).sum())
            samples.append((region, rect, window.width(), window.height(), cut, painted))
        time.sleep(0.05)

    print()
    print("  采样到 %d 个「已算好掩膜」的瞬间" % len(samples))
    if not samples:
        print("  **一个都没有** —— 掩膜始终为空，那整个窗口都不可点（这本身就是 bug）")
        return 1

    # --- 1. 画出来的每一层都必须完整地在掩膜里（被裁掉就等于屏幕上画不出来）---
    clipped_total = 0
    painted_total = 0
    worst = (0.0, "")
    for region, rect, width, height, cut, painted in samples:
        clipped_total += cut
        painted_total += painted
        if painted:
            fraction = cut / float(painted)
            if fraction > worst[0]:
                worst = (fraction, "%.1f%% (%d/%d)" % (fraction * 100.0, cut, painted))

    print()
    print("  1) 画出来的角色（含交叉淡化的垫层）是否被掩膜裁掉")
    check("所有采样里画出来的像素都不被掩膜裁掉",
          clipped_total == 0,
          "合计裁掉 %d / %d 像素%s"
          % (clipped_total, painted_total,
             ("；最坏一帧 %s" % worst[1]) if clipped_total else ""))

    # --- 2. 窗口四角（全透明留白）必须穿透 ---
    corner_hits = []
    for region, rect, width, height, _cut, _painted in samples:
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
        print("  结论：%d 项不通过 —— 角色的可点/可见区域有问题。" % len(FAILED))
    else:
        print("  结论：全部通过 —— 角色画出来的部分都在掩膜内、透明处穿透、拖动生效。")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
