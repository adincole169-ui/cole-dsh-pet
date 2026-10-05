# -*- coding: utf-8 -*-
"""自检：移动类动作**仍然会让宠物位移**（与 selftest_no_drift 配对）。

为什么要单独测这一条：修"关掉重力时残余速度不衰减"那个 bug 时，加的是
`if not use_gravity(): vx -= vx * friction * DT`。而移动动画正是靠**每帧把
`self.vx` 设成 `move_vx`**（`on_move`）来推进的 —— 摩擦和它抢同一个变量。
一不小心就会把移动一起修掉（"宠物再也不会走"），而且这种回归很隐蔽：
宠物看起来正常，只是永远待在原地。

**不能靠 `/anim` 接口验证**：那个端点直接调 `animator.play(name)`，
**不经过 `start_move()`**，所以本来就不会位移。实测就踩过这个坑
（三个移动动作的 dx 全是 0，误以为功能被修坏了）。
必须走真实路径：`start_move(spec)` → `_tick` 每帧发 `moved` 信号 → `on_move` 置 vx
→ `step_physics` 推进 `pos_x`。

    python tools/selftest_move_translates.py
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

    print()
    print("  自检：移动类动作仍然会位移")
    print("  " + "=" * 74)
    check("配置里有移动动作", bool(specs),
          "、".join(s.name for s in specs) or "(无)")
    if not specs:
        return 1

    store = FrameStore(keep=4)
    window = PetWindow(pet_config, store)
    window.show()
    app.processEvents()

    print()
    print("  %-24s %-10s %-10s %-10s %s"
          % ("动作", "预期距离", "实际位移", "误差", "判定"))
    print("  " + "-" * 74)
    for spec in specs:
        window.animator.move = None
        window.animator.facing = 1
        window.vx = 0.0
        window.vy = 0.0
        window.mode = "roam"
        window._manual_move = True     # 手动走动：不受"原地待着"拦截

        # 先让动画就绪。**必须带真实 sleep**：stream 模式下首帧要约 94 ms
        # （起 ffmpeg → 读到第一帧），而 `_tick` + `processEvents` 是微秒级空转，
        # 不给真实时间就永远等不到就绪（实测踩过：三个动作全部"动画能就绪 FAIL"）。
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
            check("%s：动画能就绪" % spec.name, False)
            continue

        # **起始位置必须在就绪之后再定，并且留足行走空间。**
        # 踩过：把位置设在屏幕中间，而 `move_vx` 恒为 `120 * facing`（朝右），
        # 于是宠物一开始走就撞上右墙 —— 撞墙把 vx 翻成负数，但 `move_vx` 是
        # `start_move()` 里定死的，下一帧又按 +120 往墙上推，宠物就**贴在墙上
        # 走完全程**（实测 pos_x 从帧 66 起一动不动，位移只有 6 px）。
        # 屏幕宽度的左侧 1/4 起步、朝右走，才有足够距离走完。
        area = window.current_screen_area()
        window.pos_x = float(area.left() + area.width() * 0.15)
        window.pos_y = float(area.top() + area.height() * 0.4)
        window.animator.facing = 1
        window.vx = 0.0

        # 记下这次要走多远（`distance()` 是随机的，取完要自己留着，否则对不上）
        window.animator.start_move(spec)
        expected = window.animator.move_left if window.animator.move else 0.0
        start_x = window.pos_x

        # 走完整段动画（时长 + 余量）
        duration = window.animator.playing.duration if window.animator.playing else 10.0
        steps = int((duration + 1.0) / 0.033)
        for _ in range(steps):
            window.animator._tick()
            window.step_physics()

        moved = abs(window.pos_x - start_x)
        error = moved - expected
        ok = moved > max(20.0, expected * 0.6)
        print("  %-24s %-10.0f %-10.0f %-10.0f %s"
              % (spec.name[:24], expected, moved, error, "OK" if ok else "FAIL"))
        if not ok:
            FAILED.append("%s 没有位移（预期 %.0f，实际 %.0f）"
                          % (spec.name, expected, moved))

    # 走完之后速度必须归零（否则又会变成"永远慢慢滑"）
    window.vx = 0.0
    window.animator.move = None
    for _ in range(120):
        window.step_physics()
    check("停下后 vx 归零", abs(window.vx) < 1.0, "vx=%.2f" % window.vx)

    print()
    if FAILED:
        print("  失败 %d 项：%s" % (len(FAILED), "、".join(FAILED)))
        return 1
    print("  全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
