# -*- coding: utf-8 -*-
"""查清"恒定 ~7.3 px/s 漂移"的方向与来源。

上一版探针发现：**所有动作**（含完全不该动的「待机呼吸休闲」）都以约 7.3 px/s 持续移动。
7.3 px/s ≈ 每分钟 440 像素，肉眼就是"宠物一直在慢慢滑"。这不是"某些动作会走"，
而是一个恒定的背景位移，很可能不是动画逻辑造成的。

这一版把 X / Y 分开量，并顺便报告重力、模式、拖拽标记，用来判断来源：
  * 主要偏 Y（向下）→ 重力的缓慢沉降
  * 主要在 X 上、且与朝向一致 → 移动逻辑/惯性
  * 与 help 里的字段无关地乱跳 → 窗口被外部挪动

    python tools/probe_drift_direction.py --seconds 20
"""

import json
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


def main():
    argv = sys.argv[1:]
    seconds = float(argv[argv.index("--seconds") + 1]) if "--seconds" in argv else 20.0
    # 默认拿「待机呼吸休闲」当"绝不该移动"的对照；也可以用 --anim 指定别的动作，
    # 用来验证**移动类动作仍然会移动**（光证明不动的都停住了还不够 ——
    # 一不小心就会把功能一起修掉）。
    animation = "待机呼吸休闲"
    if "--anim" in argv:
        animation = argv[argv.index("--anim") + 1]

    if api("/health") is None:
        print("  桌宠没在跑")
        return 1

    print()
    print("  漂移方向与来源（%.0f 秒，动作「%s」）" % (seconds, animation))
    print("  " + "=" * 84)

    # 先让它进入自由活动，并**强制播指定的动作**做对照
    api("/mood", {"mood": "idle"})
    api("/anim", {"name": animation, "loop": False})
    time.sleep(1.0)

    data = api("/debug") or {}
    print("  重力        : %s" % data.get("gravity"))
    print("  模式        : %s" % data.get("mode"))
    print("  手动移动标记 : %s" % data.get("manualMove"))
    print("  窗口尺寸     : %s" % (data.get("window"),))
    print()
    print("  %-6s %-10s %-10s %-10s %-10s %s"
          % ("秒", "x", "y", "dx", "dy", "在播"))
    print("  " + "-" * 84)

    previous = None
    totals = [0.0, 0.0]
    started = time.time()
    while time.time() - started < seconds:
        now = time.time() - started
        data = api("/debug")
        if data:
            pos = data.get("pos") or [0, 0]
            x, y = float(pos[0]), float(pos[1])
            if previous is not None:
                dx, dy = x - previous[0], y - previous[1]
                totals[0] += dx
                totals[1] += dy
                print("  %-6.1f %-10.1f %-10.1f %-10.1f %-10.1f %s"
                      % (now, x, y, dx, dy, (data.get("playing") or "-")[:20]))
            previous = (x, y, now)
        time.sleep(0.6)

    print()
    print("  合计位移: dx=%.1f  dy=%.1f" % (totals[0], totals[1]))
    print()
    print("  判读")
    print("  " + "-" * 84)
    if abs(totals[1]) > abs(totals[0]) * 2 and totals[1] > 0:
        print("     **主要向下漂移** —— 像是重力的缓慢沉降（宠物没能稳定停在地面）")
    elif abs(totals[0]) > abs(totals[1]) * 2:
        print("     **主要水平漂移** —— 像是移动逻辑/惯性没被清零")
        print("     注意此时播的是「待机呼吸休闲」，它**不在** moves.actions 里，")
        print("     所以这份位移不该出现 —— 说明来源不是「哪个动作被选中」，")
        print("     而是**上一段移动的残留在持续作用**。")
    elif abs(totals[0]) < 1 and abs(totals[1]) < 1:
        print("     这次没有漂移（可能上一轮量到的是移动动画的残留惯性）")
    else:
        print("     两个方向都在动，需要看上面的逐行数据判断来源")
    return 0


if __name__ == "__main__":
    sys.exit(main())
