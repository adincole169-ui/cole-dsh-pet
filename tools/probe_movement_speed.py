# -*- coding: utf-8 -*-
"""实测：每个动作让宠物移动的**瞬时速度**（px/秒），而不是整段的位移。

上一版探针有两个缺陷，都会给出错误结论：

  1. **按"整段位移"归因**：一段动画开始时的残留惯性会被算成"这个动作在走"。
     实测就踩了 —— 宠物一直停在 `工作状态-忙碌点按`（因为我在干活，DSH 事件让它保持
     忙碌），却记到 865 px 的位移，看上去像"工作动作也在走"。
  2. **没把宠物从"忙碌"里拉出来**：忙碌时它不自由活动，观察到的根本不是漫游行为。

所以这一版：
  * 先用 `POST /mood {"mood":"idle"}` 把工作状态清掉，让宠物真的进入自由活动；
  * 高频采样（0.2 秒）算**瞬时速度**，按"这段间隔里播放的是哪个动作"归因；
  * 每个动作汇总：移动样本占比、中位速度、最大速度。

    python tools/probe_movement_speed.py --seconds 90
"""

import json
import statistics
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8899"


def api(path, payload=None, timeout=4):
    try:
        if payload is None:
            with urllib.request.urlopen(BASE + path, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            BASE + path, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


# 配置里声明"会真的位移"的动作（`moves.actions`）
DECLARED = ("螃蟹走路", "原地漂浮踏步", "原地左转奔跑")


def main():
    argv = sys.argv[1:]
    seconds = float(argv[argv.index("--seconds") + 1]) if "--seconds" in argv else 90.0
    interval = 0.2

    if api("/health") is None:
        print("  桌宠没在跑")
        return 1

    print()
    print("  实测：各动作的移动速度（采样 %.1f 秒/次，共 %.0f 秒）" % (interval, seconds))
    print("  " + "=" * 78)
    cleared = api("/mood", {"mood": "idle"})
    print("  已把工作状态清成 idle（%s），让宠物进入自由活动"
          % ("成功" if cleared else "失败"))
    print()

    samples = []
    started = time.time()
    previous = None
    while time.time() - started < seconds:
        data = api("/debug")
        now = time.time() - started
        if data:
            pos = data.get("pos") or [0, 0]
            current = (now, data.get("playing") or "-", float(pos[0]), float(pos[1]),
                       data.get("mode") or "?")
            if previous is not None:
                # 位移速度归因到**这段间隔里播放的动作**（用后一个采样点的动作）
                dt = current[0] - previous[0]
                if dt > 1e-6:
                    distance = ((current[2] - previous[2]) ** 2
                                + (current[3] - previous[3]) ** 2) ** 0.5
                    samples.append((current[1], distance / dt, current[4]))
            previous = current
        time.sleep(interval)

    if not samples:
        print("  取不到样本")
        return 1

    stats = {}
    for name, speed, mode in samples:
        entry = stats.setdefault(name, {"n": 0, "speeds": [], "modes": set()})
        entry["n"] += 1
        entry["speeds"].append(speed)
        entry["modes"].add(mode)

    print("  %-26s %-8s %-10s %-10s %-10s %s"
          % ("动作", "样本", "移动占比", "中位速度", "最大速度", "判定"))
    print("  " + "-" * 78)
    rows = sorted(stats.items(), key=lambda item: -statistics.median(item[1]["speeds"]))
    for name, entry in rows:
        speeds = entry["speeds"]
        moving = [s for s in speeds if s > 2.0]      # > 2 px/s 才算在动
        ratio = 100.0 * len(moving) / len(speeds)
        median = statistics.median(speeds)
        top = max(speeds)
        if ratio >= 40:
            verdict = "**会移动**"
        elif ratio >= 8:
            verdict = "偶尔微动"
        else:
            verdict = "原地"
        print("  %-26s %-8d %-10s %-10.1f %-10.1f %s"
              % (name[:26], entry["n"], "%.0f%%" % ratio, median, top, verdict))

    movers = [n for n, e in rows
              if 100.0 * len([s for s in e["speeds"] if s > 2.0]) / len(e["speeds"]) >= 8]
    print()
    print("  结论")
    print("  " + "=" * 78)
    print("     观察到会移动的动作 %d 个：%s" % (len(movers), "、".join(movers) or "(无)"))
    extra = [n for n in movers if n not in DECLARED]
    if extra:
        print()
        print("     **配置里没声明会移动、但实际在动的动作 %d 个**：" % len(extra))
        for name in extra:
            entry = stats[name]
            moving = [s for s in entry["speeds"] if s > 2.0]
            print("        %-24s 中位速度 %.1f px/s，最大 %.1f px/s"
                  % (name, statistics.median(entry["speeds"]), max(entry["speeds"])))
        print()
        print("     这些正是新规则要处理的对象（要么拦住、要么给个慢速）。")
    else:
        print("     没有多出来的 —— 位移只发生在 moves.actions 声明的动作上。")
    print()
    modes = set()
    for entry in stats.values():
        modes |= entry["modes"]
    print("     观察到的模式: %s" % "、".join(sorted(modes)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
