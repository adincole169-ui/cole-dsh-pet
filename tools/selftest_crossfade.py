# -*- coding: utf-8 -*-
"""自检：切换动画时画面会不会"闪一下不见"。

判据是**合成后画面的平均不透明度**：宠物实心像素的平均 alpha 应该始终接近满值。
旧实现在切换时"新段从 0 淡入 + 旧段瞬间消失"，中间平均 alpha 会掉一大截，表现就是
短暂消失。现在旧帧作为垫层全程在下面，平均 alpha 不该有明显凹陷。

    python tools/selftest_crossfade.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

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


def mean_alpha(window):
    """窗口里"宠物实心像素"的平均 alpha（0–255）。

    只看 alpha>8 的像素：背景本来就是透明的，把它算进来会让平均值失去意义。
    """
    image = window.grab().toImage()
    total = 0
    count = 0
    for y in range(2, image.height(), 3):
        for x in range(2, image.width(), 3):
            alpha = image.pixelColor(x, y).alpha()
            if alpha > 8:
                total += alpha
                count += 1
    if count == 0:
        return 0.0
    return total / float(count)


def main(argv):
    app = build_app([argv[0]])
    entries = pet_configs(load())
    store = FrameStore(keep=6)
    window = PetWindow(entries[0], store)
    window.show()

    # 先把候选动画解码好，这样测的是"淡化"而不是"加载"
    candidates = []
    events = entries[0].animations.get("events") or {}
    for names in events.values():
        candidates.extend(names or [])
    candidates.extend(entries[0].actions("clicks"))
    candidates = [name for name in dict.fromkeys(candidates)][:8]
    for name in candidates:
        store.animation(name)
    print("  预解码 %d 个候选动画" % len(candidates))

    if not candidates:
        print("  FAIL 没有可用的候选动画")
        return 1

    # 基线要在"确实有帧可画"之后量：animator 刚建时 playing 还是空的，
    # 这时 grab() 出来的几乎全透明，拿它当基线没有意义（第一版就量到了 95）。
    window.animator.play(candidates[0], loop=True)
    for _ in range(8):
        window.animator._tick()
        app.processEvents()
    baseline = mean_alpha(window)
    print("  基线平均 alpha: %.1f" % baseline)
    check("基线画面可见", baseline > 180, "%.1f" % baseline)

    worst = 255.0
    worst_name = ""
    worst_instant = 255.0
    instant_name = ""
    samples = 0
    for name in candidates:
        window.animator.play(name, loop=True, crossfade=200)
        # 关键采样点：切换的**那一瞬**（新段 elapsed=0）。旧实现这一帧的新段 alpha=0
        # 且旧段已经消失，整只宠物是看不见的——这一步会直接把它抓出来。
        app.processEvents()
        instant = mean_alpha(window)
        if instant > 0 and instant < worst_instant:
            worst_instant = instant
            instant_name = name
        # 再用 33ms 的帧步进覆盖整段淡化
        for _ in range(14):
            window.animator._tick()
            app.processEvents()
            value = mean_alpha(window)
            if value > 0:            # 0 = 完全没画出东西，单列
                worst = min(worst, value)
                if value == worst:
                    worst_name = name
            samples += 1

    print("  采样 %d 次" % samples)
    print("  切换瞬间最差: %.1f（%s）" % (worst_instant, instant_name))
    print("  淡化期间最差: %.1f（%s）" % (worst, worst_name))
    # 阈值 120：允许淡化期间变淡，但不允许接近"看不见"
    check("切换瞬间没有透明空档", worst_instant > 120, "最差 %.1f" % worst_instant)
    check("淡化过程中没有明显空档", worst > 120, "最差 %.1f" % worst)

    window.close()
    print("失败 %d 项" % len(FAILED) if FAILED else "全部通过")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
