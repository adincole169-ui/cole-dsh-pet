# -*- coding: utf-8 -*-
"""探针：拖到某个位置松手之后，宠物**还留在那儿吗**？会不会闪？

用户报的两个回归：

  1. "无法放在屏幕的任何地方" —— 拖到哪儿都待不住；
  2. "拖拽时闪烁"。

怀疑对象是我在整合补丁时加的那一行 `self.animator.next_auto()`（松手后换段）。
`next_auto()` 会按权重挑段，而**移动档（move）也在权重池里** —— 于是松手之后
宠物可能立刻开始"走开"，看起来就是"放不住"；换段本身还会触发交叉淡化，看着就是"闪"。

这个探针做一次真实拖动，然后**连续 tick 若干秒**，记录：

  * 松手瞬间的位置 vs 若干秒后的位置（位移多大 = 能不能放住）；
  * 期间动画切换了几次（换段频繁 = 闪）；
  * 是否进入了移动（`animator.move` 非空 / `move_vx` 非 0）。

    python tools/probe_drag_placement.py
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main():
    from PyQt5.QtCore import QEvent, QPoint, Qt
    from PyQt5.QtGui import QMouseEvent

    from config import load, pet_configs
    from frames import FrameStore
    from main import build_app
    from pet import PetWindow

    app = build_app([sys.argv[0]])
    pet_config = pet_configs(load())[0]
    store = FrameStore(keep=4)
    window = PetWindow(pet_config, store)
    window.show()
    for _ in range(20):
        app.processEvents()
        time.sleep(0.02)

    def mouse(kind, pos):
        # 六参签名，**必须显式给 globalPos**（见 tools/selftest_drag_release.py）
        return QMouseEvent(kind, QPoint(*pos), QPoint(*pos), Qt.LeftButton,
                           Qt.LeftButton, Qt.NoModifier)

    print()
    print("  探针：松手之后宠物还留在原地吗？")
    print("  " + "=" * 74)

    # 起点与目标：把宠物拖到屏幕左上去
    start = (int(window.pos_x), int(window.pos_y))
    target = (start[0] - 300, start[1] - 200)
    print("  起点 (%d, %d)  ->  目标 (%d, %d)" % (start + target))

    # --- 一次真实拖动 ------------------------------------------------------ #
    window.mousePressEvent(mouse(QEvent.MouseButtonPress, start))
    steps = 10
    for index in range(1, steps + 1):
        time.sleep(0.01)
        x = start[0] + (target[0] - start[0]) * index // steps
        y = start[1] + (target[1] - start[1]) * index // steps
        window.mouseMoveEvent(mouse(QEvent.MouseMove, (x, y)))
        app.processEvents()

    drag_pose = window.animator.playing.name if window.animator.playing else None
    window.mouseReleaseEvent(mouse(QEvent.MouseButtonRelease, target))

    thrown_vx, thrown_vy = float(window.vx), float(window.vy)
    # **对照实验**：`PROBE_NO_THROW=1` 时把甩抛速度清零再观察。
    # 如果清零之后不漂了，说明漂移来自甩抛速度（而不是"启动窗口自动对齐"那条老 bug）。
    if os.environ.get("PROBE_NO_THROW") == "1":
        window.vx = 0.0
        window.vy = 0.0

    drop_x, drop_y = window.pos_x, window.pos_y
    drop_anim = window.animator.playing.name if window.animator.playing else None
    print()
    print("  松手瞬间: 位置 (%.0f, %.0f)  动画=%s" % (drop_x, drop_y, drop_anim))
    print("  甩抛速度: vx=%.0f vy=%.0f px/s%s"
          % (thrown_vx, thrown_vy,
             "（已按 PROBE_NO_THROW 清零）" if os.environ.get("PROBE_NO_THROW") == "1" else ""))

    # --- 连续 tick 6 秒，记录轨迹与切换次数 ------------------------------- #
    switches = []
    last = drop_anim
    moves = []
    trace = []
    deadline = time.time() + 6.0
    while time.time() < deadline:
        app.processEvents()
        time.sleep(1.0 / 60.0)
        now = window.animator.playing.name if window.animator.playing else None
        if now != last:
            switches.append((round(time.time() - (deadline - 6.0), 2), last, now))
            last = now
        if window.animator.move is not None:
            moves.append((round(window.pos_x, 1), round(window.pos_y, 1)))
        trace.append((window.pos_x, window.pos_y))

    final_x, final_y = window.pos_x, window.pos_y
    drift = ((final_x - drop_x) ** 2 + (final_y - drop_y) ** 2) ** 0.5

    print("  6 秒后  : 位置 (%.0f, %.0f)  动画=%s" % (final_x, final_y, last))
    print("  漂移距离: %.1f 像素" % drift)
    print()
    print("  期间动画切换 %d 次:" % len(switches))
    for at, was, now in switches[:10]:
        print("    %5.2fs  %s  ->  %s" % (at, was, now))
    print("  期间处于「移动」状态的采样数: %d" % len(moves))

    if trace:
        xs = [p[0] for p in trace]
        ys = [p[1] for p in trace]
        print("  轨迹范围: x %.0f..%.0f  y %.0f..%.0f"
              % (min(xs), max(xs), min(ys), max(ys)))

    # --- 判定 -------------------------------------------------------------- #
    print()
    print("  判定")
    print("  " + "-" * 74)
    problems = []
    if drift > 40:
        problems.append("松手后漂移 %.0f 像素 —— **放不住**（>40px 就看得出来）" % drift)
    else:
        print("  OK   漂移 %.0f 像素，基本待在原地" % drift)
    if len(switches) > 3:
        problems.append("6 秒内换段 %d 次 —— 太频繁，看起来就是**闪**" % len(switches))
    else:
        print("  OK   6 秒内换段 %d 次" % len(switches))
    if moves:
        problems.append("松手后进入了移动状态（%d 个采样）—— 宠物会自己走开" % len(moves))
    else:
        print("  OK   松手后没有进入移动状态")
    if drag_pose == drop_anim:
        problems.append("松手后仍停在拖拽动画 %s" % drop_anim)
    else:
        print("  OK   松手后离开了拖拽动画（%s -> %s）" % (drag_pose, drop_anim))

    window.close()
    store.close()

    print()
    if problems:
        for item in problems:
            print("     [问题] %s" % item)
        return 1
    print("  结论：拖放正常（放得住、不频繁换段、不自己走开）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
