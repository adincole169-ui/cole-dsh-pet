# -*- coding: utf-8 -*-
"""复现：桌宠开着 `AA_EnableHighDpiScaling` 时，它看到的屏幕是多大。

关键差别（先前我一直没注意到，白测了几轮）：

  * `tools/probe_display_env.py` / `probe_screens.py` **没有**设
    `AA_EnableHighDpiScaling`，看到的是 2560x1440、DPR 1.00；
  * 桌宠（`main.py:196`）**设了** `AA_EnableHighDpiScaling` + `AA_UseHighDpiPixmaps`，
    于是 Qt 会把 DPI 缩放算进去，坐标系与上面那个**不是同一个**。

这个探针**照桌宠的顺序**设好属性再建 QApplication，然后打印 Qt 认为的屏幕尺寸、
DPR、logicalDpi，以及由此推出的"允许摆放范围"——和桌宠实测到的 (1052, 506) 对照。

    python tools/probe_hidpi_scaling.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)


def report(title, enable_scaling):
    """建一个 QApplication 并报告屏幕参数。

    注意：`AA_EnableHighDpiScaling` **必须在** `QApplication` 之前设置
    （main.py 的注释也强调了这一点），而且同一个进程只能建一个 QApplication，
    所以两种模式必须**分开进程**跑 —— 本脚本用 `--mode` 参数区分。
    """
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication

    if enable_scaling:
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication([])          # noqa: F841

    print()
    print("  %s" % title)
    print("  " + "=" * 74)
    print("  AA_EnableHighDpiScaling = %s" % enable_scaling)
    for index, screen in enumerate(QApplication.screens()):
        geo = screen.geometry()
        avail = screen.availableGeometry()
        print("  屏 %d %s" % (index, screen.name() or "?"))
        print("      geometry          = (%d,%d) %dx%d"
              % (geo.x(), geo.y(), geo.width(), geo.height()))
        print("      availableGeometry = (%d,%d) %dx%d"
              % (avail.x(), avail.y(), avail.width(), avail.height()))
        print("      devicePixelRatio  = %.2f" % screen.devicePixelRatio())
        print("      logicalDpi        = %.0f" % screen.logicalDotsPerInchX())
        width, height = 320, 213
        print("      -> 窗口 %dx%d 时，左上角最多到 (%.0f, %.0f)"
              % (width, height,
                 avail.left() + max(0, avail.width() - width),
                 avail.top() + max(0, avail.height() - height)))
        print("      -> 居中的话在 (%.0f, %.0f)"
              % (avail.left() + max(0, avail.width() - width) / 2.0,
                 avail.top() + max(0, avail.height() - height) / 2.0))
    return 0


def main(argv):
    enable = "--off" not in argv
    title = ("桌宠的方式（开着高 DPI 缩放）" if enable
             else "对照组（不开高 DPI 缩放）")
    return report(title, enable)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
