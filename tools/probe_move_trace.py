# -*- coding: utf-8 -*-
"""逐帧诊断一次 `start_move()`：为什么有的移动动作几乎不位移。

`selftest_move_translates.py` 实测：「螃蟹走路」走 130 px，而「原地漂浮踏步」
（预期 89）和「原地左转奔跑」（预期 154）都只走了 6 px。三个动作时长都是 10.04 秒，
leadSec/tailSec 也排得开，所以原因不在时长 —— 只能逐帧看。

打印每帧的：elapsed / 期望(leadSec) / walk 标记 / vx / pos_x / move_left / done。

    python tools/probe_move_trace.py 原地漂浮踏步
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)


def main():
    argv = sys.argv[1:]
    name = argv[0] if argv and not argv[0].startswith("-") else "原地漂浮踏步"

    from config import load, pet_configs
    from frames import FrameStore
    from main import build_app
    from pet import PetWindow

    app = build_app([sys.argv[0]])
    pet_config = pet_configs(load())[0]
    spec = next((s for s in pet_config.move_specs() if s.name == name), None)
    if spec is None:
        print("  配置里没有移动动作「%s」" % name)
        print("  有的是: %s" % "、".join(s.name for s in pet_config.move_specs()))
        return 1

    store = FrameStore(keep=4)
    window = PetWindow(pet_config, store)
    window.show()
    app.processEvents()

    area = window.current_screen_area()
    window.pos_x = float(area.left() + area.width() / 2.0)
    window.pos_y = float(area.top() + area.height() / 2.0)
    window.vx = 0.0
    window.vy = 0.0
    window.mode = "roam"
    window._manual_move = True
    window.animator.facing = 1

    print()
    print("  逐帧诊断「%s」" % name)
    print("  " + "=" * 90)
    print("  spec: 距离 %.0f-%.0f  lead %.2fs  tail %.2fs"
          % (spec.min_dist, spec.max_dist, spec.lead_sec, spec.tail_sec))
    print("  起始 pos_x=%.1f  （屏幕 %d..%d）"
          % (window.pos_x, area.left(), area.right()))

    # 先就绪
    window.animator.play(name, loop=False, crossfade=0)
    deadline = time.time() + 6.0
    while time.time() < deadline:
        window.animator._tick()
        app.processEvents()
        playing = window.animator.playing
        if playing is not None and playing.animation is not None:
            break
        time.sleep(0.02)
    playing = window.animator.playing
    print("  就绪: animation=%s  duration=%.2f  len=%s"
          % (playing.animation is not None if playing else "no playing",
             playing.duration if playing else -1,
             len(playing.source) if playing and playing.source else -1))

    window.animator.start_move(spec)
    print("  start_move 之后: move=%s  move_left=%.1f  move_vx=%.1f  facing=%s"
          % (window.animator.move is not None, window.animator.move_left,
             window.animator.move_vx, window.animator.facing))
    print()
    print("  %-6s %-9s %-7s %-6s %-9s %-9s %-10s %s"
          % ("帧", "elapsed", ">lead?", "walk", "vx", "pos_x", "move_left", "done"))
    print("  " + "-" * 90)

    start_x = window.pos_x
    previous_x = start_x
    for index in range(400):
        window.animator._tick()
        window.step_physics()
        playing = window.animator.playing
        elapsed = playing.elapsed if playing else -1
        done = playing.done if playing else True
        # 只在"有变化"或关键帧打印，否则 400 行太多
        interesting = (index < 6 or index % 20 == 0 or window.animator.move is None
                       or abs(window.vx) > 1.0)
        if interesting and index < 340:
            print("  %-6d %-9.2f %-7s %-6s %-9.1f %-9.1f %-10.1f %s"
                  % (index, elapsed,
                     "是" if elapsed >= spec.lead_sec else "否",
                     "走" if abs(window.vx) > 1.0 else "-",
                     window.vx, window.pos_x,
                     window.animator.move_left if window.animator.move else -1,
                     done))
        previous_x = window.pos_x
        if done and window.animator.move is None and index > 20:
            break

    print()
    print("  合计位移: %.1f px（预期 %.1f）"
          % (window.pos_x - start_x, 0))
    print("  结束状态: vx=%.2f  move=%s"
          % (window.vx, window.animator.move is not None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
