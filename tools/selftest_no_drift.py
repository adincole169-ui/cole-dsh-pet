# -*- coding: utf-8 -*-
"""自检：关掉重力时，宠物在"不该移动的动作"里不得自行漂移。

背景（实测查出来的真问题）
--------------------------
用户报"自由活动时其他动作也在动"。实测采样发现：宠物在播「待机呼吸休闲」
（完全不在 `moves.actions` 里）时，仍以约 **5.7 px/s 恒定向右滑**。

根因在 `PetWindow.step_physics()`：

    重力关（`gravity: 0`）→ 宠物永远落不到 ground_line → `pos_y < floor`
    → 走 `else` 分支 → `self.grounded = False`
    → 而**水平摩擦只在 `if self.grounded:` 里执行**
    → 于是任何残余 `vx`（移动动画的收尾、撞墙反弹、拖拽甩出）**永不衰减**

命中判据：在"关掉重力 + 播放非移动动作"的条件下推进物理若干秒，
宠物水平位置的变化必须接近 0。修复前会得到约 5.7 px/s，修复后应为 0。

    python tools/selftest_no_drift.py
"""

import os
import sys

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
    config = load()
    entries = pet_configs(config)
    pet_config = entries[0]

    print()
    print("  自检：关掉重力时不得自行漂移")
    print("  " + "=" * 72)
    print("  physics.gravity = %s（use_gravity=%s）"
          % (pet_config.physics.get("gravity"), None))

    store = FrameStore(keep=4)
    window = PetWindow(pet_config, store)
    window.show()
    app.processEvents()

    # 挑一个**不在 moves.actions 里**的动作：它绝不该让宠物移动
    moves = [spec.name for spec in pet_config.move_specs()]
    idle = pet_config.actions("idle") or []
    target = next((n for n in idle if n not in moves), None)
    if target is None:
        target = next((n for n in (pet_config.actions("clicks") or [])
                       if n not in moves), None)
    if target is None:
        # 全都在移动池里就退而求其次：随便找个非移动动作
        for category in pet_config.animations.get("categories") or []:
            for name in (category.get("actions") or []):
                if name not in moves:
                    target = name
                    break
            if target:
                break
    check("找到一个不在 moves.actions 里的动作", bool(target),
          "%s（moves=%s）" % (target, moves))
    if not target:
        return 1

    window.animator.play(target, loop=True)
    for _ in range(4):
        window.animator._tick()
        app.processEvents()
    window.animator.move = None            # 确保没有移动规格
    window.vx = 0.0
    window._manual_move = False
    window.mode = "roam"

    # 先推进几秒让它"静下来"（挤压、贴边这些一次性动作做完）
    for _ in range(120):
        window.step_physics()
    base_x, base_y = window.pos_x, window.pos_y
    for _ in range(150):                   # 150 帧 × 33ms ≈ 5 秒
        window.step_physics()
    drift_x = window.pos_x - base_x
    drift_y = window.pos_y - base_y
    speed = abs(drift_x) / (150 * 0.033)

    print()
    print("  静置 5 秒后的位移: dx=%.2f  dy=%.2f（约 %.2f px/s）"
          % (drift_x, drift_y, speed))
    check("水平没有自行漂移（|dx| < 2 像素）", abs(drift_x) < 2.0,
          "dx=%.2f" % drift_x)
    check("速度接近 0（< 0.5 px/s）", speed < 0.5, "%.2f px/s" % speed)

    # 给一个残余速度，确认它会被摩擦吃掉（这才是"摩擦生效"的直接证据）
    window.vx = 60.0
    window.pos_x = base_x
    for _ in range(150):
        window.step_physics()
    leftover = window.pos_x - base_x
    print()
    print("  注入 vx=60 px/s 后 5 秒: dx=%.2f  残留 vx=%.2f" % (leftover, window.vx))
    check("残余速度会被摩擦吃掉（5 秒内停下）", abs(window.vx) < 1.0,
          "残留 vx=%.2f" % window.vx)
    check("停下后不再继续滑（位移有限）", abs(leftover) < 60.0,
          "dx=%.2f" % leftover)

    print()
    if FAILED:
        print("  失败 %d 项：%s" % (len(FAILED), "、".join(FAILED)))
        return 1
    print("  全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
