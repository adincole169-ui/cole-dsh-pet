# -*- coding: utf-8 -*-
"""自检：在进程内走完整的碎碎念路径，并逐步记录。

为什么不用桥的 `/whisper` 接口测：那个接口是我为了诊断临时加的，它自己在 HTTP 线程里
emit 信号，反而引入了新的变量（而且在真机上会让进程用致命信号退出）。这里直接在
**GUI 线程**里调用 `whisper_now`，就是用户右键菜单走的那条路，没有任何中间环节。

    python tools/selftest_whisper_live.py
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from config import load, pet_configs
from frames import FrameStore
from main import build_app
from pet import PetWindow


def main(argv):
    app = build_app([argv[0]])
    config = pet_configs(load())[0]
    store = FrameStore(keep=4)
    window = PetWindow(config, store)
    window.show()
    window.animator.play((config.actions("idle") or ["待机呼吸休闲"])[0], loop=True)
    for _ in range(6):
        window.animator._tick()
        window._repaint()
        app.processEvents()

    print("  动作前: bubble=%s topPad=%s window=%dx%d"
          % (window.bubble, window.top_pad, window.width(), window.height()))

    window.whisper_now(announce=True)
    print("  调用后立刻: bubble=%s topPad=%s window=%dx%d"
          % (window.bubble, window.top_pad, window.width(), window.height()))

    # 让 GUI 事件循环转起来，等异步回调。
    # 超时给到 75 秒：模型响应时间波动很大（实测 2~30 秒），而**必须等到真实台词**，
    # 否则只测到占位气泡"……"，这条自检就失去了意义（曾经因此误判为通过）。
    deadline = time.time() + 75
    seen = []
    while time.time() < deadline:
        app.processEvents()
        window.tick()
        window._repaint()
        if window.bubble:
            seen.append(window.bubble[0])
        if window.whisper_log and "on_done" in window.whisper_log[-1]:
            break
        if window.whisper_log and "on_error" in window.whisper_log[-1]:
            break
        time.sleep(0.05)

    print("  最终: bubble=%s topPad=%s window=%dx%d"
          % (window.bubble, window.top_pad, window.width(), window.height()))

    # 掩膜必须覆盖气泡：`setMask` 同时裁绘制，气泡落在掩膜外就是"看不见"。
    # 这条断言是补上一个真实踩过的坑——碎碎念成功了但屏幕上没有气泡。
    mask_rect = window.mask().boundingRect()
    bubble_rect = window.bubble_rect
    covered = False
    if bubble_rect is not None and not bubble_rect.isEmpty():
        covered = (mask_rect.top() <= int(bubble_rect.top()) + 1
                   and mask_rect.bottom() >= int(bubble_rect.bottom()) - 1)
        print("  掩膜 rect=(%d,%d,%d,%d)  气泡 rect=(%d,%d,%d,%d)  -> %s"
              % (mask_rect.left(), mask_rect.top(), mask_rect.width(), mask_rect.height(),
                 int(bubble_rect.left()), int(bubble_rect.top()),
                 int(bubble_rect.width()), int(bubble_rect.height()),
                 "OK 已覆盖" if covered else "FAIL 气泡被裁"))
    else:
        print("  掩膜 rect=(%d,%d,%d,%d)  但气泡矩形未记录 -> FAIL"
              % (mask_rect.left(), mask_rect.top(), mask_rect.width(), mask_rect.height()))

    print("  气泡出现过的文本: %s" % (sorted(set(seen)) or "（从未出现）"))
    print("  逐步流水:")
    for line in window.whisper_log:
        print("    %s" % line)

    callback = bool(window.whisper_log) and any("on_" in item for item in window.whisper_log)
    # 必须拿到**真实台词**：只有占位气泡"……"说明模型那一步还没走完，
    # 那时测出来的掩膜是占位符的尺寸，不能代表最终气泡（曾经在这里放过水）。
    got_reply = any("on_done" in item and "reply='" in item
                    and "reply=''" not in item for item in window.whisper_log)
    ok = callback and covered and got_reply
    if not callback:
        print("失败：没有拿到回调")
    elif not covered:
        print("失败：气泡没进掩膜（会被裁掉）")
    elif not got_reply:
        print("失败：只等到占位气泡，没拿到台词（模型超时？）")
    else:
        print("全部通过")
    window.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
