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
    print("  自检：拖动期间选「整窗可点」策略、松手后恢复精确掩膜")
    print("  " + "=" * 74)
    print("  注意：offscreen 平台上 setMask 不生效，所以本自检验的是**策略选择**；")
    print("        真实 Windows 上的鼠标投递行为需要在有真实鼠标的机器上确认。")

    # --- 1. 空闲：应当是精确掩膜 ------------------------------------------ #
    window.dragging = False
    window._mask_key = None
    window._apply_input_mask()
    for _ in range(10):
        app.processEvents()
    check("空闲时选**精确掩膜**（透明角落才会穿透）",
          mask_strategy(window) == "precise",
          "%s %s" % (mask_strategy(window), cover_detail(window)))

    # --- 2. 按下之后必须切到整窗 ------------------------------------------ #
    window.mousePressEvent(mouse(QEvent.MouseButtonPress, centre))
    app.processEvents()
    check("按下之后进入拖动状态", bool(window.dragging))
    # 拖动中帧还在变（本来会按新帧重建精确掩膜），多推几帧确认不会被裁回去
    for _ in range(10):
        app.processEvents()
        window._apply_input_mask()
    check("**拖动期间选整窗策略**（真实鼠标才不会丢事件）",
          mask_strategy(window) == "whole",
          "%s %s" % (mask_strategy(window), cover_detail(window)))

    # --- 3. 松手之后恢复 -------------------------------------------------- #
    window.mouseReleaseEvent(mouse(QEvent.MouseButtonRelease, (centre[0] + 30,
                                                               centre[1] + 10)))
    app.processEvents()
    check("松手之后离开拖动状态", not window.dragging)
    check("松手之后恢复**精确掩膜**（否则透明区会挡住下层应用）",
          mask_strategy(window) == "precise",
          "%s %s" % (mask_strategy(window), cover_detail(window)))

    window.close()
    store.close()

    print()
    print("  结论")
    print("  " + "=" * 74)
    if FAILED:
        for item in FAILED:
            print("     [失败] %s" % item)
        return 1
    print("     [OK] 拖动中选整窗策略、松手后恢复精确掩膜")
    print("     [提醒] 「Windows 是否因此继续投递鼠标事件」需要真实鼠标确认，")
    print("            请在有真实鼠标的机器上拖一次宠物验证。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
