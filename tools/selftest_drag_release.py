# -*- coding: utf-8 -*-
"""自检：**松开鼠标之后必须离开"拖拽"动画**，且甩抛速度按真实耗时算。

补丁（cole-dsh-pet-fix.patch）指出的两条，我已核实成立：

  1. `Animator.play_drag()` 用的是 `play(..., loop=True)`，而循环动画的 `done`
     永远不会置位。甩抛分支里**没有任何人换段**，于是松手之后宠物会一直保持
     "被拎着"的姿势（只有点一下才会 `play_click()` 换掉）。
  2. 甩抛速度按 `DT * len(drag_history)` 算，等于假设每个鼠标事件间隔一个 tick
     （33 ms）；实际鼠标事件是 125 Hz 以上（约 8 ms），于是同样的手势算出来的
     速度偏小、甩不动。改成用 `drag_history` 里的**真实时间戳**。

    python tools/selftest_drag_release.py
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


def main():
    from PyQt5.QtCore import QEvent, QPoint, Qt
    from PyQt5.QtGui import QMouseEvent

    from config import load, pet_configs
    from frames import FrameStore
    from main import build_app
    from pet import DT, PetWindow

    app = build_app([sys.argv[0]])
    pet_config = pet_configs(load())[0]
    store = FrameStore(keep=4)
    window = PetWindow(pet_config, store)
    window.show()
    app.processEvents()

    drag_names = list(pet_config.actions("drag") or [])

    def mouse(kind, pos, button=Qt.LeftButton):
        # Qt5 **六参**签名: (type, localPos, globalPos, button, buttons, modifiers)。
        #
        # **必须显式给 globalPos**：`mouseMoveEvent` / `mousePressEvent` 用的都是
        # `event.globalPos()`，而四参构造出来的事件 globalPos 不随参数变化 ——
        # 于是 `target_x` 恒定、`pos_x` 收敛后不再动，`drag_history` 里所有样本
        # 完全相同，甩抛速度恒为 0（实测踩过：断言"新算法与旧算法不同"因此假失败）。
        # 写法参照 tools/selftest_clickable_area.py。
        return QMouseEvent(kind, QPoint(*pos), QPoint(*pos), button, button,
                           Qt.NoModifier)

    print()
    print("  自检：松手之后要离开拖拽动画；甩抛速度按真实耗时")
    print("  " + "=" * 74)
    check("配置里有拖拽动画", bool(drag_names), "、".join(drag_names[:3]))

    # --- 1. 按下之后应当进入拖拽动画，而且它是循环的 -------------------- #
    window.mousePressEvent(mouse(QEvent.MouseButtonPress, (160, 90)))
    app.processEvents()
    playing = window.animator.playing
    check("按下之后进入拖拽动画",
          playing is not None and playing.name in drag_names,
          playing.name if playing else None)
    check("拖拽动画确实是循环的（所以它不会自己结束）",
          bool(playing and playing.loop))

    # --- 2. 拖动若干步（模拟 125 Hz：每次之间给一点真实时间）---------- #
    import time as _time
    start = (160, 90)
    end = (360, 40)
    steps = 6
    for index in range(1, steps + 1):
        _time.sleep(0.008)          # 约 125 Hz，正是补丁说的真实频率
        x = start[0] + (end[0] - start[0]) * index // steps
        y = start[1] + (end[1] - start[1]) * index // steps
        window.mouseMoveEvent(mouse(QEvent.MouseMove, (x, y)))
    app.processEvents()

    history = list(window.drag_history)
    check("drag_history 带上了时间戳（三元组）",
          bool(history) and len(history[0]) == 3,
          "样本 %r" % (history[0] if history else None,))

    # --- 3. 松手（甩抛）之后必须离开拖拽动画 -------------------------- #
    window.mouseReleaseEvent(mouse(QEvent.MouseButtonRelease, end))
    # **必须紧接着读 `vx`**：`processEvents()` 会跑物理 tick，把刚算出来的速度
    # 衰减掉（实测：晚一步读就是 0.0，看起来像"修复没生效"，其实是读晚了）。
    released_vx = float(window.vx)
    app.processEvents()
    after = window.animator.playing
    check("**松手之后离开了拖拽动画**（不再保持「被拎着」的姿势）",
          after is None or after.name not in drag_names,
          after.name if after else None)

    # --- 4. 甩抛速度用真实耗时：核对量级 ------------------------------ #
    power = float(pet_config.physics.get("throwPower", 1.0))
    if len(history) >= 2:
        (x0, y0, t0), (x1, y1, t1) = history[0], history[-1]
        measured_elapsed = max(t1 - t0, DT)
        expect_vx = (x1 - x0) / measured_elapsed * power
        old_vx = (x1 - x0) / (DT * len(history)) * power
        print("      实测耗时 %.1f ms；新算法 vx≈%.1f，旧算法 vx≈%.1f（差 %.1f 倍）"
              % (measured_elapsed * 1000, expect_vx, old_vx,
                 (expect_vx / old_vx) if old_vx else float("nan")))
        got = released_vx
        check("vx 与「按真实耗时」的算法一致（而不是旧的 DT×样本数）",
              abs(got - expect_vx) < max(1.0, abs(expect_vx) * 0.02),
              "实际 vx=%.1f 期望 %.1f" % (got, expect_vx))
        check("新算法确实和旧算法不同（否则这条断言没有意义）",
              abs(expect_vx - old_vx) > 1.0,
              "新 %.1f vs 旧 %.1f" % (expect_vx, old_vx))
        check("横向速度方向正确（向右甩 -> vx > 0）", got > 0, got)

    # --- 5. 轻点（位移很小）走的是另一条分支，也应当离开拖拽动画 ------- #
    window.mousePressEvent(mouse(QEvent.MouseButtonPress, (160, 90)))
    app.processEvents()
    window.mouseReleaseEvent(mouse(QEvent.MouseButtonRelease, (161, 91)))
    app.processEvents()
    after2 = window.animator.playing
    check("轻点之后也离开了拖拽动画",
          after2 is None or after2.name not in drag_names,
          after2.name if after2 else None)

    window.close()
    store.close()

    print()
    print("  结论")
    print("  " + "=" * 74)
    if FAILED:
        for item in FAILED:
            print("     [失败] %s" % item)
        return 1
    print("     [OK] 松手后离开拖拽动画；甩抛速度按真实耗时计算")
    return 0


if __name__ == "__main__":
    sys.exit(main())
