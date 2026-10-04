# -*- coding: utf-8 -*-
"""在线验证：动画切换**不再**搬动宠物位置（对着正在运行的桌宠采样）。

针对的 bug：`_place_initial()` 会重置"启动对齐"的计时，而掩膜每换一帧就触发一次
对齐 —— 于是窗口被无限期地持续搬回出生点。用户的观感就是"拖不动、松手回出生点"。

`tools/selftest_settle_window.py` 已经在进程内证明了这一点；本脚本是**对着真实运行
的桌宠**再验一次：轮询 `/debug`，看"动画换了"与"位置变了"是否还同时发生。

启动窗口（`SETTLE_WINDOW_SEC`）之内的移动是**设计如此**，所以脚本会先等过它。

    python tools/verify_no_placement_drift.py            # 默认采样 25 秒
    python tools/verify_no_placement_drift.py 40         # 采样 40 秒
"""

import json
import sys
import time
import urllib.request

PORT = 8899
URL = "http://127.0.0.1:%d/debug" % PORT
# 与 src/pet.py 的 SETTLE_WINDOW_SEC 对齐；留出余量
SETTLE_WINDOW_SEC = 4.0
LEAD_IN = SETTLE_WINDOW_SEC + 3.0


def probe():
    try:
        with urllib.request.urlopen(URL, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 25.0

    first = probe()
    if first is None:
        print()
        print("  桌宠没有应答（%s）。先启动它：" % URL)
        print("     python main.py")
        return 1

    print()
    print("  在线验证：动画切换是否还会搬动位置")
    print("  " + "=" * 62)
    print("  先等 %.0f 秒越过启动对齐窗口 ..." % LEAD_IN)
    deadline = time.monotonic() + LEAD_IN
    while time.monotonic() < deadline:
        time.sleep(0.5)

    print("  开始采样 %.0f 秒（每秒一条）" % seconds)
    print()
    print("  %-10s %-12s %-28s %s" % ("时刻", "位置/底边", "动画", "说明"))

    samples = []
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        data = probe()
        if data is None:
            time.sleep(1.0)
            continue
        pos = tuple(data.get("pos") or ())
        window = tuple(data.get("window") or ())
        # 底边 = y + 窗口高。**窗口高会随动画变化**（180 / 213 ...），
        # 而 `_place_initial` 与 `ground_line()` 都让窗口底贴着"地面"，
        # 所以真正该稳定的是**底边**，不是 y。
        bottom = (pos[1] + window[1]) if len(pos) == 2 and len(window) == 2 else None
        samples.append({
            "at": time.monotonic(),
            "pos": pos,
            "bottom": bottom,
            "anim": data.get("playing") or "",
            "window": window,
        })
        time.sleep(1.0)

    if len(samples) < 2:
        print("  采样太少，无法判断")
        return 1

    rows = []
    anim_changed = 0
    bottom_changed_without_anim = []
    bottom_changed_with_anim = []
    for index in range(1, len(samples)):
        previous, current = samples[index - 1], samples[index]
        changed_anim = previous["anim"] != current["anim"]
        bottom_moved = (previous["bottom"] is not None
                        and current["bottom"] is not None
                        and abs(previous["bottom"] - current["bottom"]) > 2)
        note = ""
        if changed_anim:
            anim_changed += 1
            if bottom_moved:
                note = "**动画切换时底边也变了**"
                bottom_changed_with_anim.append((previous, current))
            else:
                note = "动画切换，底边稳定"
        elif bottom_moved:
            note = "底边变了（动画未变）"
            bottom_changed_without_anim.append((previous, current))
        rows.append((current, note))

    for current, note in rows:
        stamp = time.strftime("%H:%M:%S", time.localtime(time.time()
                                                         - (samples[-1]["at"] - current["at"])))
        pos_text = ("%g,%g" % current["pos"]) if len(current["pos"]) == 2 else "?"
        bottom_text = ("底边 %g" % current["bottom"]) if current["bottom"] is not None else ""
        print("  %-10s %-12s %-28s %s"
              % (stamp, pos_text, current["anim"][:26],
                 note or bottom_text))

    print()
    print("  结论")
    print("  " + "=" * 62)
    print("  采样 %d 条，动画切换 %d 次" % (len(samples), anim_changed))

    if anim_changed == 0:
        print()
        print("  **无法判断**：这段时间里动画一次都没换（可能 DSH 一直是同一个状态）。")
        print("  让它多切几个动画再测，例如手动触发或等状态变化。")
        return 0

    if bottom_changed_with_anim:
        print("  **有问题**：动画一切换，底边就变 —— 说明启动对齐窗口又没关掉。")
        for previous, current in bottom_changed_with_anim[:3]:
            print("     %s 底边 %s  ->  %s 底边 %s"
                  % (previous["anim"][:20], previous["bottom"],
                     current["anim"][:20], current["bottom"]))
        return 1

    print("  动画切换时底边保持稳定：%d 次切换，0 次被搬走。" % anim_changed)
    if bottom_changed_without_anim:
        print("  （另有 %d 次底边变化发生在动画未切换时 —— 那是物理：落地/走动/抛掷。"
              % len(bottom_changed_without_anim))
    print()
    print("  通过：启动窗口过期后，动画切换不再搬动宠物。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
