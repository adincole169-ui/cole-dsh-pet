# -*- coding: utf-8 -*-
"""定位：`selftest_still_mode` 的"原地待着不许动"为什么会有位移。

自检的步骤是：`set_mode("still")` -> 人为 `vx=400`（模拟惯性）-> 强制挑移动档 ->
跑 2 秒 -> 要求位移 < 0.5 像素。实测在我的气泡改动之后变成 15~85 像素。

这个探针把那段复现出来，并**每一步**打印谁可能动了它：
位置、速度、模式、`_manual_move`、当前移动规格、`move_vx`、以及掩膜/对齐是否在跑。

    python tools/probe_still_drift.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main():
    from config import load, pet_configs
    from frames import FrameStore
    from main import build_app
    from pet import PetWindow
    import selftest_still_mode as helper

    app = build_app([sys.argv[0]])
    pet_config = pet_configs(load())[0]
    store = FrameStore(keep=3)
    window = PetWindow(pet_config, store)
    window.show()
    for _ in range(20):
        app.processEvents()

    # 先自由活动走一段，和自检一致
    window.set_mode("roam")
    helper.force_move_pick(window)
    helper.pump(app, window, 3.0)

    window.set_mode("still")
    window.vx = 400.0
    helper.force_move_pick(window)
    start = window.pos_x

    print()
    print("  原地待着阶段（每 5 步打印一次）")
    print("  " + "=" * 74)
    print("  %4s %8s %8s %6s %6s %-18s %8s %s"
          % ("步", "pos_x", "vx", "mode", "manual", "移动规格", "move_vx", "掩膜key"))
    for step in range(60):
        window.animator._tick()
        window.tick()
        window._repaint()
        app.processEvents()
        if step % 5 == 0 or step == 59:
            move = window.animator.move
            key = getattr(window, "_mask_key", None)
            key_text = "无" if key is None else (str(key[0])[:12] if isinstance(key, tuple) else "?")
            print("  %4d %8.1f %8.1f %6s %6s %-18s %8.1f %s"
                  % (step, window.pos_x, window.vx, window.mode,
                     getattr(window, "_manual_move", None),
                     (move.name[:18] if move else "-"),
                     window.animator.move_vx, key_text))

    drift = abs(window.pos_x - start)
    print()
    print("  起始 %.1f -> 结束 %.1f，位移 %.2f 像素 %s"
          % (start, window.pos_x, drift, "✓" if drift < 0.5 else "✗"))
    window.close()
    store.close()
    return 0 if drift < 0.5 else 1


if __name__ == "__main__":
    sys.exit(main())
