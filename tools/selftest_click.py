# -*- coding: utf-8 -*-
"""自检：反复"点击 / 拖拽 / 甩出"宠物，看会不会崩。

用户在点击之后发现桌宠消失，而进程确实退出了、且 `pythonw` 下没有留下任何 stderr。
远程切换动画复现不出来，所以差别一定在**窗口自己的鼠标事件链路**上：拖拽状态机、
Q 弹挤压、输入掩膜重建、以及右键菜单。

这里用合成的 `QMouseEvent` 直接打这些处理器，跑到崩溃点为止。

    python tools/selftest_click.py [轮数]
"""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QApplication

from config import load, pet_configs
from frames import FrameStore
from main import build_app
from pet import PetWindow

FAILED = []


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label, ("  " + detail) if detail else ""))
    if not ok:
        FAILED.append(label)


def mouse(kind, pos, button=Qt.LeftButton):
    return QMouseEvent(kind, QPoint(*pos), Qt.NoButton, button, Qt.NoModifier)


def click(window, pos=(160, 90)):
    window.mousePressEvent(mouse(QEvent.MouseButtonPress, pos))
    window.mouseReleaseEvent(mouse(QEvent.MouseButtonRelease, pos))


def drag(window, start=(160, 90), end=(260, 40)):
    window.mousePressEvent(mouse(QEvent.MouseButtonPress, start))
    steps = 6
    for index in range(1, steps + 1):
        x = start[0] + (end[0] - start[0]) * index // steps
        y = start[1] + (end[1] - start[1]) * index // steps
        window.mouseMoveEvent(mouse(QEvent.MouseMove, (x, y)))
    window.mouseReleaseEvent(mouse(QEvent.MouseButtonRelease, end))


def main(argv):
    rounds = int(argv[1]) if len(argv) > 1 else 60
    app = build_app([argv[0]])
    config = pet_configs(load())[0]
    store = FrameStore(keep=4)
    window = PetWindow(config, store)
    window.show()
    window.animator.play((config.actions("idle") or ["待机呼吸休闲"])[0], loop=True)

    # 逐轮推进并检查窗口是否还"活着"
    for index in range(rounds):
        try:
            window.animator._tick()
            window.tick()
            window._repaint()
            if index % 3 == 0:
                click(window, (160 + index % 40, 90))
            if index % 5 == 0:
                drag(window, (140, 80), (240 + index % 60, 30))
            if index % 7 == 0:
                window.animator.next_auto()
            app.processEvents()
        except Exception:
            print("  第 %d 轮抛出异常：" % index)
            traceback.print_exc()
            FAILED.append("click loop round %d" % index)
            break

        # 崩溃会先表现为窗口被销毁
        if not window.isVisible():
            FAILED.append("窗口在第 %d 轮变得不可见" % index)
            break

    check("窗口仍然可见", window.isVisible())
    check("没有异常抛出", not any("round" in item for item in FAILED))
    check("掩膜仍然存在", window.mask() is not None and not window.mask().isEmpty(),
          "=%s" % (window.mask_stats,))
    check("动画仍在推进", window.animator.playing is not None,
          "=%s" % (window.animator.playing.name if window.animator.playing else None))

    window.close()
    print("失败 %d 项" % len(FAILED) if FAILED else "全部通过")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
