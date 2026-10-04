# -*- coding: utf-8 -*-
"""自检：配置里配好的动画**都能被播到**（可达性）。

为什么需要它：`animations.turn`（「东张西望」，权重 5）曾经配了却永远不播——
`next_auto()` 的权重池只装了 idle / categories / move，漏了 turn，而唯一会播它的
`Animator.face()` 又没有任何调用点。这类"配了但到不了"的问题不会报错，只会让人觉得
"怎么翻来覆去就这几个动作"，所以值得自动检查。

判定方式：在**受控随机数**下穷举 `next_auto()` 的分支，看每个组能不能被选中。

    python tools/selftest_anim_reachability.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

import random                                 # noqa: E402

from config import load, pet_configs          # noqa: E402
from frames import FrameStore                 # noqa: E402
from main import build_app                    # noqa: E402
from pet import PetWindow                     # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label,
                         ("  " + detail) if detail else ""))
    if not ok:
        FAILED.append(label)


def sweep(window, rolls):
    """在不同 roll 下各跑一次 next_auto，收集它选中的组与动画名。

    用受控随机数**穷举**分支，而不是"跑一会儿看运气"——后者可能因为恰好没抽到
    而误判成不可达。
    """
    animator = window.animator
    picked = []
    original_uniform = random.uniform
    original_choice = random.choice
    try:
        for roll in rolls:
            # 关掉工作状态，确保走权重池那条路
            animator.work_status = None
            animator.playing = None
            animator.move = None
            random.uniform = lambda a, b, _r=roll: _r
            random.choice = lambda seq: seq[0]      # 组内取第一个，结果可预期
            animator.next_auto()
            if animator.move is not None:
                picked.append(("move", animator.move.name))
            elif animator.playing is not None:
                picked.append((getattr(animator.playing, "group", None)
                               or "?", animator.playing.name))
            animator.playing = None
            animator.move = None
    finally:
        random.uniform = original_uniform
        random.choice = original_choice
    return picked


def main(argv):
    app = build_app([argv[0]])
    config = pet_configs(load())[0]
    window = PetWindow(config, FrameStore(keep=8))
    window.show()
    idle = (config.actions("idle") or ["待机呼吸休闲"])[0]
    window.store.animation(idle)
    window.animator.play(idle, loop=True)
    for spec in config.move_specs():
        window.store.animation(spec.name)

    # 权重池的规模（idle 10 + turn 5 + 分类权重和 + move 5）
    category_weight = sum(float(c.get("weight", 1))
                          for c in (config.animations.get("categories") or [])
                          if isinstance(c, dict))
    total = 10 + 5 + category_weight + 5
    print("  权重池：idle 10 + turn 5 + categories %.0f + move 5 = %.0f"
          % (category_weight, total))

    rolls = [i * total / 200.0 for i in range(1, 200)]
    picked = sweep(window, rolls)
    names = {name for _group, name in picked}
    print("  穷举 %d 个 roll，选中过的动画 %d 种" % (len(rolls), len(names)))

    print("  -- turn（东张西望）必须可达 --")
    turn_actions = config.actions("turn") or []
    for name in turn_actions:
        check("「%s」能被自动抽到" % name, name in names,
              "" if name in names else "（权重 %.0f 已在池中，但仍没抽到）"
              % config.weight_of("turn"))

    print("  -- idle 必须可达 --")
    for name in (config.actions("idle") or []):
        check("「%s」能被自动抽到" % name, name in names)

    print("  -- 移动也必须可达（自由活动时）--")
    window.set_mode("roam")
    picked_roam = sweep(window, rolls)
    move_names = {n for g, n in picked_roam if g == "move"}
    check("自由活动时能抽到移动", bool(move_names), "抽到: %s" % sorted(move_names))

    print("  -- 原地待着时不该抽到移动 --")
    window.set_mode("still")
    picked_still = sweep(window, rolls)
    move_still = {n for g, n in picked_still if g == "move"}
    check("原地待着时抽不到移动", not move_still, "抽到: %s" % sorted(move_still))

    print("  -- 分类里的动画也要可达（抽查每类第一个）--")
    window.set_mode("roam")
    for category in (config.animations.get("categories") or []):
        actions = category.get("actions") or []
        if not actions:
            continue
        check("分类「%s」可达" % category.get("id"), actions[0] in names,
              "" if actions[0] in names else "（%s 不在抽到的集合里）" % actions[0])

    window.close()
    print("失败 %d 项" % len(FAILED) if FAILED else "全部通过")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
