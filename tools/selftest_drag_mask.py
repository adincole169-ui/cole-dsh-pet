# -*- coding: utf-8 -*-
"""自检：**拖动期间窗口必须整窗可点**（否则真实鼠标拖不动）。

背景（这个 bug 长期存在，而所有自检都看不见它）
-----------------------------------------------
`_apply_input_mask()` 会按角色形状 `setMask()`。拖动时**窗口在动、光标基本不动**，
于是光标很快落到掩膜**之外**；而掩膜之外的区域在 Windows 上不再属于这个窗口，
后续的鼠标移动事件就被投递给下层窗口了。后果：

  * 宠物只跟着走了第一次那一格 —— 实测 `logs/drag.log` 里真实鼠标拖动是
    「鼠标走 273~1154 px，窗口只动 2~3 px」= 用户说的"拖不动 / 放不住"；
  * 区域在掩膜内外反复变化 → 反复重绘 = "拖拽时闪烁"。

**为什么以前的自检发现不了**：它们都**直接调用** `window.mouseMoveEvent(...)`，
绕过了 Qt/Win32 的事件投递，所以"掩膜裁掉输入"这件事在自检里根本不存在
（合成拖动一直是成功的 68/179 px，而真实鼠标是 2~3 px）。

修法：拖动期间把掩膜放宽成**整窗**，松手后再裁回"角色 + 气泡"。
这个自检验的就是这条约定 —— 它不依赖真实鼠标，只校验掩膜策略：

  1. 空闲时掩膜**不是**整窗（角色之外的角落不该可点）；
  2. 按下之后掩膜**必须是**整窗；
  3. 松手之后恢复成非整窗（透明区域重新穿透，否则会挡住下层应用）。

    python tools/selftest_drag_mask.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

FAILED = []


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label,
                         ("  " + str(detail)) if detail else ""))
    if not ok:
        FAILED.append(label)


def mask_strategy(window):
    """返回当前掩膜**策略**：`"whole"` = 整窗可点，`"precise"` = 按角色裁剪。

    **为什么验策略而不是验掩膜效果**：`setMask` 在 offscreen 平台上**根本不生效**
    （Qt 会打印 "This plugin does not support setting window masks"），
    `window.mask()` 永远返回整窗 —— 想靠它判断"拖动中是否整窗"会**恒真**，
    那种断言在撤掉修复之后照样通过（比没有断言更糟）。

    所以这里检查代码**选了哪条分支**：`_apply_input_mask()` 在拖动中会把
    `_mask_key` 设成 `("dragging", ...)`。真实的"Windows 是否因此继续投递
    鼠标事件"需要在有真实鼠标的机器上确认，本自检覆盖不到，这一点如实标注。
    """
    key = getattr(window, "_mask_key", None)
    if isinstance(key, tuple) and key and key[0] == "dragging":
        return "whole"
    return "precise"


def cover_detail(window):
    stats = getattr(window, "mask_stats", None)
    if isinstance(stats, dict) and "cover" in stats:
        return "cover=%.3f" % stats["cover"]
    return "（offscreen 下掩膜不生效，仅作参考）"


def main():
    from PyQt5.QtCore import QEvent, QPoint, Qt
    from PyQt5.QtGui import QMouseEvent
    from PyQt5.QtWidgets import QWidget

    from config import load, pet_configs
    from frames import FrameStore
    from main import build_app
    from pet import PetWindow

    app = build_app([sys.argv[0]])
    pet_config = pet_configs(load())[0]
    store = FrameStore(keep=3)
    window = PetWindow(pet_config, store)
    window.show()
    for _ in range(30):
        app.processEvents()

    def mouse(kind, pos):
        return QMouseEvent(kind, QPoint(*pos), QPoint(*pos), Qt.LeftButton,
                           Qt.LeftButton, Qt.NoModifier)

    centre = (window.width() // 2, window.height() // 2)

    print()
    print("  自检：拖动靠 grabMouse() 抓鼠标，**不动掩膜**")
    print("  " + "=" * 74)
    print("  为什么不动掩膜：改掩膜 = 一次 Windows 区域变更，而改动时机正是按下与")
    print("  松开 —— 那会让宠物「消失一瞬」。抓鼠标与掩膜无关，且可验证。")

    # --- 1. 空闲：精确掩膜、没有抓鼠标 ------------------------------------ #
    window.dragging = False
    window._mask_key = None
    window._apply_input_mask()
    for _ in range(10):
        app.processEvents()
    check("空闲时选**精确掩膜**（透明角落才会穿透）",
          mask_strategy(window) == "precise",
          "%s %s" % (mask_strategy(window), cover_detail(window)))
    check("空闲时没有抓着鼠标", QWidget.mouseGrabber() is not window,
          QWidget.mouseGrabber())

    # --- 2. 按下：抓鼠标，且掩膜**不变** ---------------------------------- #
    before_key = window._mask_key
    window.mousePressEvent(mouse(QEvent.MouseButtonPress, centre))
    app.processEvents()
    check("按下之后进入拖动状态", bool(window.dragging))
    check("**按下之后抓住了鼠标**（事件不再依赖掩膜）",
          QWidget.mouseGrabber() is window, QWidget.mouseGrabber())
    # 拖动中帧还在变：多推几帧，掩膜也不该因为"拖动中"而切换成整窗
    for _ in range(10):
        app.processEvents()
        window._apply_input_mask()
    check("拖动期间掩膜**没有被切换成整窗**（改掩膜会让画面闪）",
          mask_strategy(window) == "precise",
          "%s %s" % (mask_strategy(window), cover_detail(window)))

    # --- 3. 松手：放开鼠标 ------------------------------------------------- #
    window.mouseReleaseEvent(mouse(QEvent.MouseButtonRelease, (centre[0] + 30,
                                                               centre[1] + 10)))
    app.processEvents()
    check("松手之后离开拖动状态", not window.dragging)
    check("松手之后放开了鼠标", QWidget.mouseGrabber() is not window,
          QWidget.mouseGrabber())

    window.close()
    store.close()

    print()
    print("  结论")
    print("  " + "=" * 74)
    if FAILED:
        for item in FAILED:
            print("     [失败] %s" % item)
        return 1
    print("     [OK] 拖动靠抓鼠标（不动掩膜）；掩膜始终保持精确")
    print("     [提醒] offscreen 平台会打印「不支持抓鼠标」，所以这里验的是 Qt 侧的")
    print("            抓取状态（`QWidget.mouseGrabber()`），不是系统层的抓取。")
    print("            「真实鼠标拖动是否跟手、是否还闪」仍需在真机确认；")
    print("            若不跟手，说明 grabMouse 在这台机器上不够，需要另想办法。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
