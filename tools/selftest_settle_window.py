# -*- coding: utf-8 -*-
"""自检：启动期的"自动对齐"窗口必须**会过期**，之后不能再动用户摆放的位置。

背景（用户报的现象）：在不认识的机器上"拖不动，松手后消失又回到出生点"。

读代码发现一个**必然触发的逻辑 bug**：
  * `_place_initial()` 结尾会写 `self._placed_at = time.monotonic()`（重置计时）；
  * `_settle_initial_placement()` 又调用 `_place_initial()`；
  * 而 settle 是**掩膜每次重建**时被调的，播放动画时掩膜持续变化。
  于是"4 秒窗口"每次触发都被重新计时 —— **窗口永远不会过期**，
  宠物会在每个动画帧被搬回出生点。用户一碰（`_user_took_over`）才会停止。

本测试不去猜，直接验：
  1. 超过 SETTLE_WINDOW_SEC 之后，掩膜变化**不该**再把窗口搬回出生点；
  2. 模拟一次成功的拖动之后，位置必须保持住。

    python tools/selftest_settle_window.py
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from PyQt5.QtCore import QEvent, QPoint, Qt                     # noqa: E402
from PyQt5.QtGui import QMouseEvent                              # noqa: E402
from PyQt5.QtWidgets import QApplication                         # noqa: E402

from config import load, pet_configs                             # noqa: E402
from frames import FrameStore                                    # noqa: E402
from main import build_app                                       # noqa: E402
from pet import PetWindow, SETTLE_WINDOW_SEC                     # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label, ("  " + detail) if detail else ""))
    if not ok:
        FAILED.append(label)


def pump(app, seconds):
    """跑事件循环若干秒，让动画与掩膜真正变化。"""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


def force_mask_rebuild(window):
    """强制重建一次掩膜（等价于动画换了一帧）。"""
    window._mask_key = None
    window._apply_input_mask()


def main():
    app = build_app([])
    config = load()
    entries = pet_configs(config)
    store = FrameStore(keep=4)
    window = PetWindow(entries[0], store)
    window.show()
    pump(app, 2.0)

    spawn = (window.pos_x, window.pos_y)
    print()
    print("  启动位置 (出生点): (%.0f, %.0f)" % spawn)
    print("  SETTLE_WINDOW_SEC = %.1f" % SETTLE_WINDOW_SEC)

    # --- 1. 等过"启动窗口"，其间掩膜一直在变 ---
    print()
    print("  阶段 1：等 %.1f 秒（远超启动窗口），期间掩膜持续变化" % (SETTLE_WINDOW_SEC + 2.0))
    settled_count = 0
    deadline = time.monotonic() + SETTLE_WINDOW_SEC + 2.0
    while time.monotonic() < deadline:
        app.processEvents()
        force_mask_rebuild(window)
        settled_count += 1
        time.sleep(0.05)
    print("     期间强制重建掩膜 %d 次" % settled_count)

    # --- 2. 把"用户摆到别处"的状态做出来，再看掩膜变化会不会把它搬回去 ---
    print()
    print("  阶段 2：把窗口移到别处，再让掩膜变化，看会不会被搬回出生点")
    window._user_took_over()          # 模拟"用户已经碰过"（正常拖动必然经过这一步）
    away = (spawn[0] - 180.0, spawn[1] - 60.0)
    window.pos_x, window.pos_y = away
    window.move(int(window.pos_x), int(window.pos_y))
    pump(app, 0.3)
    for _ in range(6):
        force_mask_rebuild(window)
        app.processEvents()
        time.sleep(0.05)
    after = (window.pos_x, window.pos_y)
    moved_back = abs(after[0] - spawn[0]) < 2 and abs(after[1] - spawn[1]) < 2
    check("用户碰过之后，掩膜变化不再搬回出生点",
          not moved_back,
          "位置 (%.0f, %.0f) -> (%.0f, %.0f)" % (away[0], away[1], after[0], after[1]))

    # --- 3. 关键：**没有**用户碰过的情况下，启动窗口是否真的会过期 ---
    #
    # 顺序很重要：必须**先**等过截止时刻，**再**把窗口挪走，然后看掩膜变化会不会
    # 把它搬回去。反过来（先挪走再等）测不出问题——启动期内搬回去是**设计如此**，
    # 结束时它本来就已经在出生点，末尾的断言会靠容差侥幸通过（第一版就是这样假通过的）。
    print()
    print("  阶段 3：新建一个窗口，**完全不碰它**，先等过截止时刻，再挪走看会不会被搬回")
    fresh = PetWindow(entries[0], store)
    fresh.show()
    pump(app, 0.5)
    fresh_spawn = (fresh.pos_x, fresh.pos_y)
    print("     出生点 (%.0f, %.0f)" % fresh_spawn)

    # 先等过期（期间掩膜持续变化，启动期内被搬回属正常）
    deadline = time.monotonic() + SETTLE_WINDOW_SEC + 1.0
    while time.monotonic() < deadline:
        app.processEvents()
        force_mask_rebuild(fresh)
        time.sleep(0.05)
    expired_at = getattr(fresh, "_settle_deadline", "缺失")
    check("等待超过 SETTLE_WINDOW_SEC 后，截止时刻应已被清空",
          expired_at is None,
          "_settle_deadline=%s" % expired_at)

    # 现在才挪走：此后任何掩膜变化都不该再搬它
    fresh.pos_x, fresh.pos_y = fresh_spawn[0] - 200.0, fresh_spawn[1] - 80.0
    fresh.move(int(fresh.pos_x), int(fresh.pos_y))
    displaced = (fresh.pos_x, fresh.pos_y)
    pump(app, 0.3)
    for _ in range(8):
        force_mask_rebuild(fresh)
        app.processEvents()
        time.sleep(0.05)
    final = (fresh.pos_x, fresh.pos_y)
    pulled_back = (abs(final[0] - fresh_spawn[0]) < 40
                   and abs(final[1] - fresh_spawn[1]) < 40)
    detail = "挪到 (%.0f, %.0f)，之后 (%.0f, %.0f)，出生点 (%.0f, %.0f)" % (
        displaced[0], displaced[1], final[0], final[1], fresh_spawn[0], fresh_spawn[1])
    check("过期后，掩膜变化不得再把窗口搬回出生点", not pulled_back, detail)

    print()
    if FAILED:
        print("  结论：%d 项不通过 —— 启动对齐窗口**不会过期**。" % len(FAILED))
        print("        它就是「拖不动、松手回出生点」的成因：掩膜在播放中不断变化，")
        print("        每次变化都把窗口搬回角落，而拖动会被它抢走。")
    else:
        print("  结论：全部通过")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
