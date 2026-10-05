# -*- coding: utf-8 -*-
"""自检：移动动作撞墙后必须**掉头继续走**，不能贴着墙把剩下的路"耗"完。

背景（DEVNOTES 第 29 条）
------------------------
`start_move()` 里 `move_vx = MOVE_SPEED × facing` 是**一次性定死**的。撞墙时
`step_physics` 只把 `self.vx` 取反、并翻转 `animator.facing`，`move_vx` 不变 ——
下一帧 `_tick` 又按原方向发 `moved(move_vx, True)`，`on_move` 把 `vx` 设回原方向。
于是宠物**顶在墙上**把 `move_left` 耗完：逐帧日志里 pos_x 从撞墙那一帧起恒定不变，
而 `move_left` 一直在减。

判据：让宠物贴着右墙开始走，统计"**声明在走（|vx|>1）但位置丝毫没动**"的连续帧数。
修复前那是一长串（顶墙到底）；修复后最多一两帧（撞墙那一瞬，随后就掉头了）。
同时要求它最终确实**离开了墙**（净位移向左）。

    python tools/selftest_wall_turnaround.py
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

FAILED = []


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label,
                         ("  " + detail) if detail else ""))
    if not ok:
        FAILED.append(label)


def main():
    try:
        from PyQt5.QtWidgets import QApplication                 # noqa: F401
    except ImportError as error:
        print("  需要 PyQt5: %s" % error)
        return 1

    from config import load, pet_configs
    from frames import FrameStore
    from main import build_app
    from pet import PetWindow

    app = build_app([sys.argv[0]])
    pet_config = pet_configs(load())[0]
    specs = pet_config.move_specs()
    if not specs:
        print("  配置里没有移动动作")
        return 1
    spec = specs[0]

    print()
    print("  自检：移动动作撞墙后掉头（用「%s」）" % spec.name)
    print("  " + "=" * 74)

    store = FrameStore(keep=4)
    window = PetWindow(pet_config, store)
    window.show()
    app.processEvents()

    # 就绪（stream 模式首帧要约 94 ms，必须给真实时间）
    window.animator.play(spec.name, loop=False, crossfade=0)
    deadline = time.time() + 6.0
    while time.time() < deadline:
        window.animator._tick()
        app.processEvents()
        playing = window.animator.playing
        if playing is not None and playing.animation is not None:
            break
        time.sleep(0.02)
    if window.animator.playing is None or window.animator.playing.animation is None:
        check("动画能就绪", False)
        return 1

    area = window.current_screen_area()
    insets = window.character_insets()
    # 把宠物摆到"右边缘正好贴住屏幕右缘"的位置，并且朝右走 —— 一迈步就撞墙
    window.pos_x = float(area.right() - window.width() + insets[1])
    window.pos_y = float(area.top() + area.height() * 0.4)
    window.animator.facing = 1
    window.vx = 0.0
    window.vy = 0.0
    window.mode = "roam"
    window._manual_move = True

    window.animator.start_move(spec)
    wall_x = window.pos_x

    # 逐帧跑完整段动画
    duration = window.animator.playing.duration
    steps = int((duration + 1.0) / 0.033)
    stuck_run = 0          # 当前"在走但没动"的连续帧数
    worst_stuck = 0        # 最长的一次
    previous_x = window.pos_x
    collided = False
    for _ in range(steps):
        window.animator._tick()
        window.step_physics()
        walking = abs(window.vx) > 1.0
        moved = abs(window.pos_x - previous_x) > 0.01
        if walking and not moved:
            stuck_run += 1
            worst_stuck = max(worst_stuck, stuck_run)
            collided = True
        else:
            stuck_run = 0
        previous_x = window.pos_x

    final_x = window.pos_x
    travelled = wall_x - final_x        # 向左走出来的距离（正数 = 离开了右墙）

    print()
    print("  起始（贴着右墙）pos_x = %.1f" % wall_x)
    print("  结束            pos_x = %.1f" % final_x)
    print("  向左走出        %.1f px" % travelled)
    print("  最长「在走却不动」连续帧数 = %d" % worst_stuck)
    print()
    check("确实撞到过墙（否则这个自检没意义）", collided,
          "没撞到墙 —— 起始位置或距离不合适")
    check("撞墙后没有长时间顶墙（最长 < 8 帧）", worst_stuck < 8,
          "最长 %d 帧" % worst_stuck)
    check("撞墙后确实离开了墙（向左 > 30px）", travelled > 30.0,
          "%.1f px" % travelled)

    print()
    if FAILED:
        print("  失败 %d 项：%s" % (len(FAILED), "、".join(FAILED)))
        return 1
    print("  全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
