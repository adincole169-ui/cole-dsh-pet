# -*- coding: utf-8 -*-
"""诊断：多显示器 / DPI 下，桌宠**实际允许活动的范围**到底是多少。

用户报（外接显示器上）："从屏幕中间开始往右往下都不能放" —— 也就是可活动区域
只有左上那一块。这类症状几乎都是**逻辑坐标与物理坐标混用**或**屏幕几何取错**。

这个脚本把桌宠真正会用到的东西全部打印出来：

  * 每块屏的 geometry / availableGeometry / devicePixelRatio / logicalDpi；
  * 虚拟桌面的并集范围；
  * `screen_area_for(point)` 对每块屏的中心返回什么；
  * 正在运行的那只桌宠的位置（读 /debug），以及按那次位置算出来的
    **允许范围**（左右上下各能到哪），并与它所在屏的可用区对照。

    python tools/probe_screens.py
"""

import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)


def pet_debug(port=8899):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/debug" % port, timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as error:
        return {"_error": str(error)}


def main():
    from PyQt5.QtCore import QPoint, QRect
    from PyQt5.QtWidgets import QApplication

    # 与桌宠一致的 DPI 相关设置：先看一眼有没有被改过
    print()
    print("  屏幕 / DPI 诊断")
    print("  " + "=" * 74)

    app = QApplication.instance() or QApplication([])      # noqa: F841

    screens = QApplication.screens()
    union = QRect()
    print("  共 %d 块屏" % len(screens))
    for index, screen in enumerate(screens):
        geo = screen.geometry()
        avail = screen.availableGeometry()
        union = union.united(geo)
        print()
        print("  [屏 %d] %s" % (index, screen.name() or "(无名)"))
        print("      geometry          = (%d,%d) %dx%d"
              % (geo.x(), geo.y(), geo.width(), geo.height()))
        print("      availableGeometry = (%d,%d) %dx%d"
              % (avail.x(), avail.y(), avail.width(), avail.height()))
        print("      devicePixelRatio  = %.2f" % screen.devicePixelRatio())
        print("      logicalDpi        = %.0f x %.0f"
              % (screen.logicalDotsPerInchX(), screen.logicalDotsPerInchY()))
        print("      physicalDpi       = %.0f x %.0f"
              % (screen.physicalDotsPerInchX(), screen.physicalDotsPerInchY()))

    print()
    print("  虚拟桌面并集 = (%d,%d) %dx%d"
          % (union.x(), union.y(), union.width(), union.height()))
    print("  可用屏幕列表 = %s" % ", ".join(s.name() or "?" for s in screens))
    print("  主屏 = %s" % (QApplication.primaryScreen().name() or "?"))

    # screen_area_for 对每块屏的中心应当返回**那块屏**的可用区
    import pet as pet_module
    print()
    print("  screen_area_for(point) 的返回（对该点所在屏的可用区）")
    for index, screen in enumerate(screens):
        centre = screen.geometry().center()
        area = pet_module.screen_area_for(QPoint(centre.x(), centre.y()))
        own = screen.availableGeometry()
        same = (area.x() == own.x() and area.y() == own.y()
                and area.width() == own.width() and area.height() == own.height())
        print("      屏 %d 中心 (%d,%d) -> (%d,%d) %dx%d  %s"
              % (index, centre.x(), centre.y(), area.x(), area.y(),
                 area.width(), area.height(), "与所在屏一致 ✓" if same else "**与所在屏不一致**"))

    # 正在跑的那只桌宠：位置 + 允许范围
    debug = pet_debug()
    print()
    print("  正在运行的桌宠（读 127.0.0.1:8899/debug）")
    if "_error" in debug:
        print("      读不到：%s" % debug["_error"])
        return 1
    window = debug.get("window")
    print("      window(宽高) = %s" % window)
    # /debug 里没有位置字段时，退回到屏幕诊断即可
    pos = debug.get("pos")
    print("      /debug 里的位置字段 = %s" % (pos if pos is not None else "(没有)"))

    print()
    print("  **允许范围对照**（若宠物在某块屏上，它能到哪）")
    for index, screen in enumerate(screens):
        avail = screen.availableGeometry()
        if not window:
            continue
        width, height = int(window[0]), int(window[1])
        # 窗口**左上角**的允许范围（左右贴边按角色留白放宽，这里先给窗口级别的边界）
        print("      屏 %d: 窗口左上角 x 在 [%d, %d]、y 在 [%d, %d]（按窗口完全在屏内算）"
              % (index, avail.left(), avail.right() - width,
                 avail.top(), avail.bottom() - height))
        print("            该屏可用区 %dx%d，窗口 %dx%d —— 可移动范围约为 %dx%d 像素"
              % (avail.width(), avail.height(), width, height,
                 max(0, avail.width() - width), max(0, avail.height() - height)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
