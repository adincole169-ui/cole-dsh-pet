# -*- coding: utf-8 -*-
"""自检：内存里的动画数量必须有界（pin 泄漏回归）。

为什么需要它：`Animator.play()` 每换一段都会 `store.pin(name)`，但**原先从不 unpin**，
于是 `_pinned` 无限增长。而 `FrameStore._touch()` 淘汰时会"跳过 pinned"，钉子一多，
淘汰就逐渐失效——内存里的动画只增不减（实测常驻 500MB 以上）。

现在 `play()` 改走 `store.retain(name, 2)`：只保留最近两个钉子
（当前 + 上一段，后者是交叉淡化要用的垫层）。

判定方式：连续播很多不同的动画，看内存里的动画数是否被 `keep` 约束住。

    python tools/selftest_memory_bound.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

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


def main(argv):
    app = build_app([argv[0]])
    config = pet_configs(load())[0]
    keep = 4
    store = FrameStore(keep=keep)
    window = PetWindow(config, store)
    window.show()

    # 收集一批**已解码**的动画（避免触发 20 秒的后台解码）
    idle = config.actions("idle") or ["待机呼吸休闲"]
    pool = list(idle)
    for category in (config.animations.get("categories") or []):
        pool.extend((category.get("actions") or [])[:3])
    pool.extend(m.name for m in config.move_specs())
    pool = [p for p in pool if p]

    print("  keep=%d，准备轮流播 %d 个不同动画" % (keep, len(pool)))

    # 全部先同步解码到内存（这一步会占内存，但我们要看的是**上限**）
    loaded = []
    for name in pool[:8]:
        try:
            window.store.animation(name)
            loaded.append(name)
        except Exception as error:
            print("    跳过 %s（%s）" % (name, error))
    if len(loaded) < 4:
        print("  可用动画太少（%d），无法验证" % len(loaded))
        window.close()
        return 0

    print("  实际轮流播 %d 个动画" % len(loaded))
    for _round in range(3):
        for name in loaded:
            window.animator.play(name, loop=True)
            window.animator._tick()
            window.tick()
            app.processEvents()

    stats = store.stats()
    cached = len(stats["cached"])
    pinned = len(store._pinned)
    print("  播完 %d 段后: 内存动画 %d 个（keep=%d），钉子 %d 个"
          % (len(loaded) * 3, cached, keep, pinned))

    check("内存动画数不超过 keep+pinned", cached <= keep + 2,
          "cached=%d 上限=%d" % (cached, keep + 2))
    check("钉子数量有界（不随播放次数增长）", pinned <= 2, "pinned=%d" % pinned)

    print("  -- 再播一轮，数量不应继续增长 --")
    for name in loaded:
        window.animator.play(name, loop=True)
        window.animator._tick()
        app.processEvents()
    after = len(store.stats()["cached"])
    check("再播一轮后没有增长", after <= keep + 2, "cached=%d" % after)

    window.close()
    print("失败 %d 项" % len(FAILED) if FAILED else "全部通过")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
