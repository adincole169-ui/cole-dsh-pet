# -*- coding: utf-8 -*-
"""实测：**哪些动作真的让宠物位移了**，每个动作期间走了多少像素。

为什么要实测而不是读代码：`animator._tick()` 里位移挂在 `self.move` 上，看起来只有
`moves.actions` 那几个动作会走；但用户看到的现象是"别的动作也在动"。可能的来源有
好几处（物理惯性、拖拽残留、`moved` 信号、窗口被别的机制挪动），读代码容易漏。

做法：高频采样 `/debug` 的 `pos` 与 `playing`，按"同一段动画的连续采样"分组，
算出每段动画期间的位置变化，再按动画名汇总。

    python tools/probe_movement_by_anim.py --seconds 75
"""

import json
import sys
import time
import urllib.request

DEBUG = "http://127.0.0.1:8899/debug"


def api(url, timeout=4):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def main():
    argv = sys.argv[1:]
    seconds = float(argv[argv.index("--seconds") + 1]) if "--seconds" in argv else 75.0
    interval = 0.35

    print()
    print("  实测：每个动作期间的位移（采样 %.2f 秒，共 %.0f 秒）" % (interval, seconds))
    print("  " + "=" * 78)
    print("  请让宠物自由活动（不要拖它）。")
    print()

    samples = []
    started = time.time()
    while time.time() - started < seconds:
        data = api(DEBUG)
        if data:
            pos = data.get("pos") or [0, 0]
            samples.append((time.time() - started, data.get("playing") or "-",
                            float(pos[0]), float(pos[1]),
                            bool(data.get("manualMove"))))
        time.sleep(interval)

    if not samples:
        print("  取不到 /debug —— 桌宠没在跑？")
        return 1

    # 按"同一段动画的连续采样"分组
    segments = []
    current = [samples[0]]
    for sample in samples[1:]:
        if sample[1] == current[-1][1]:
            current.append(sample)
        else:
            segments.append(current)
            current = [sample]
    segments.append(current)

    # 只统计"完整看到"的段（首尾都在采样范围内，且持续 > 1 秒），
    # 否则边界段会把上一段/下一段的位移算进来
    stats = {}
    print("  %-26s %-8s %-10s %-10s %s"
          % ("动作", "时长", "水平位移", "垂直位移", "是否位移"))
    print("  " + "-" * 78)
    for segment in segments:
        name = segment[0][1]
        duration = segment[-1][0] - segment[0][0]
        if duration < 1.0:
            continue
        dx = segment[-1][2] - segment[0][2]
        dy = segment[-1][3] - segment[0][3]
        moved = abs(dx) > 4
        entry = stats.setdefault(name, {"segments": 0, "seconds": 0.0,
                                        "moved_segments": 0, "total_dx": 0.0})
        entry["segments"] += 1
        entry["seconds"] += duration
        entry["total_dx"] += abs(dx)
        if moved:
            entry["moved_segments"] += 1
        print("  %-26s %6.1fs %9.0f %10.0f %s"
              % (name[:26], duration, dx, dy, "**是**" if moved else "否"))

    print()
    print("  按动作汇总")
    print("  " + "=" * 78)
    print("  %-26s %-8s %-10s %-10s %s"
          % ("动作", "出现段数", "位移段数", "累计水平", "判定"))
    print("  " + "-" * 78)
    rows = sorted(stats.items(), key=lambda item: -item[1]["moved_segments"])
    for name, entry in rows:
        verdict = "会移动" if entry["moved_segments"] else "原地"
        print("  %-26s %-8d %-10d %-10.0f %s"
              % (name[:26], entry["segments"], entry["moved_segments"],
                 entry["total_dx"], verdict))

    movers = [name for name, entry in rows if entry["moved_segments"]]
    print()
    print("  结论")
    print("  " + "=" * 78)
    print("     观察到会移动的动作 %d 个：%s" % (len(movers), "、".join(movers) or "(无)"))
    print("     观察到原地不动的动作 %d 个：%s"
          % (len(rows) - len(movers),
             "、".join(n for n, _e in rows if n not in movers) or "(无)"))
    print()
    print("     配置里 `moves.actions` 声明会移动的是：螃蟹走路、原地漂浮踏步、原地左转奔跑")
    extra = [n for n in movers if n not in ("螃蟹走路", "原地漂浮踏步", "原地左转奔跑")]
    if extra:
        print("     **多出来的（配置没声明却在动的）: %s**" % "、".join(extra))
        print("     这些就是「规则要拦掉」的对象。")
    else:
        print("     没有多出来的 —— 位移只发生在 moves.actions 声明的三个动作上。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
