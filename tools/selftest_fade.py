# -*- coding: utf-8 -*-
"""自检：交叉淡化与后台加载时的"可见性下限"。

不依赖截图（截图受分层窗口与 DPI 缩放影响，之前量出过假数据），而是直接验证
判定逻辑本身：

  场景一  新段已就绪 + 有垫层   → 允许从 0 淡入（有东西垫着，不会空）
  场景二  新段已就绪 + 无垫层   → 必须从 >0 起淡入（旧行为就是这里空掉的）
  场景三  新段还在加载 + 有垫层 → **不能淡化**，且必须仍有一帧可画

前两个场景的差异就是"切换动作时短暂消失"的根因。

    python tools/selftest_fade.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QApplication

from animator import Animator
from config import load, pet_configs
from main import build_app

FAILED = []


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label, ("  " + detail) if detail else ""))
    if not ok:
        FAILED.append(label)


class StubAnimation(object):
    """能出帧的最小替身：只需要 `frame()` / `fps` / `duration` / `__len__`。

    直接用 `object()` 会让 `Playing.frame()` 抛 AttributeError —— 那样测出来的
    "没有帧"是替身不完整，不是被测逻辑的问题。
    """

    def __init__(self, name="stub", count=4, fps=24.0):
        self.name = name
        self._count = count
        self.fps = fps
        self.duration = count / fps
        self._pixmap = QPixmap(4, 4)

    def __len__(self):
        return self._count

    def frame(self, index):
        return self._pixmap


class FakeStore(object):
    """只回答"缓存里有没有"，不做任何 IO。"""

    def __init__(self, ready):
        self._ready = ready

    def peek(self, name):
        return StubAnimation(name) if self._ready else None

    def pin(self, name):
        pass

    def is_loading(self, name):
        return False

    def request(self, name):
        pass


def main(argv):
    app = build_app([argv[0]])
    config = pet_configs(load())[0]

    # 场景一：已就绪 + 有垫层
    one = Animator(FakeStore(True), config)
    one.last_frame = QPixmap(4, 4)
    one.play("X", crossfade=200)
    check("已就绪+有垫层：垫层存在", one.outgoing_frame() is not None)
    check("已就绪+有垫层：可以从 0 淡入", one.fade_alpha() == 0.0,
          "alpha=%.2f" % one.fade_alpha())

    # 场景二：已就绪但没有垫层（旧行为）—— 必须给一个下限，否则这一帧整只透明
    two = Animator(FakeStore(True), config)
    two.play("X", crossfade=200)
    check("已就绪+无垫层：垫层为空", two.outgoing_frame() is None)
    check("已就绪+无垫层：淡入有下限（不整帧透明）", two.fade_alpha() > 0.0,
          "alpha=%.2f" % two.fade_alpha())

    # 场景三：还在后台加载——靠垫层撑着，绝不能淡化
    three = Animator(FakeStore(False), config)
    three.last_frame = QPixmap(4, 4)
    three.play("X", crossfade=200)
    check("未就绪：playing.ready 为假", not three.playing.ready)
    check("未就绪：不淡化（垫层要满不透明）", three.fade_alpha() == 1.0,
          "alpha=%.2f" % three.fade_alpha())
    check("未就绪：仍有帧可画", three.current_frame() is not None)

    print("失败 %d 项" % len(FAILED) if FAILED else "全部通过")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
