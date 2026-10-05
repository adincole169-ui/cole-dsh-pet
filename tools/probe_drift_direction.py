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
    steps = []                      # 每次采样的 (dx, dy)
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
                steps.append((dx, dy))
                print("  %-6.1f %-10.1f %-10.1f %-10.1f %-10.1f %s"
                      % (now, x, y, dx, dy, (data.get("playing") or "-")[:20]))
            previous = (x, y, now)
        time.sleep(0.6)

    print()
    print("  合计位移: dx=%.1f  dy=%.1f" % (totals[0], totals[1]))

    # **判读要用逐步数据，不能只看合计。**
    # 踩过：宠物因为窗口高度变化（气泡留白）会有一次性的竖直沉降（实测 33 px），
    # 而它只是一步、之后恒为 0 —— 拿合计去比就会把"一次性调整"误判成"竖直漂移"，
    # 甚至反过来盖掉真正的水平漂移。所以分别数"有多少步真的在动"。
    moving_x = [d for d, _e in steps if abs(d) > 1.0]
    moving_y = [e for _d, e in steps if abs(e) > 1.0]
    print("  逐步统计: %d 步采样；水平在动的 %d 步，竖直在动的 %d 步"
          % (len(steps), len(moving_x), len(moving_y)))
    if moving_y:
        print("            竖直那几步的位移: %s"
              % "、".join("%.0f" % v for v in moving_y[:6]))

    print()
    print("  判读")
    print("  " + "-" * 84)
    # 真正的漂移 = **持续**在动：超过 3 成的采样步都在同一方向移动
    sustained_x = len(moving_x) > max(2, len(steps) * 0.3)
    sustained_y = len(moving_y) > max(2, len(steps) * 0.3)
    if not sustained_x and not sustained_y:
        if moving_x or moving_y:
            print("     **没有持续漂移** —— 只有一次性的位置调整（窗口高度变化等），")
            print("     之后恒为 0。这与「慢慢滑走」是两回事。")
        else:
            print("     **完全没有位移**：宠物纹丝不动（正确行为）。")
    elif sustained_x and not sustained_y:
        print("     **持续水平漂移** —— 像是移动逻辑/惯性没被清零。")
        print("     此时若播的是「待机呼吸休闲」这类不在 moves.actions 里的动作，")
        print("     说明来源不是「哪个动作被选中」，而是残余速度在持续作用")
        print("     （对应 DEVNOTES 第 28 条，修在 step_physics 的 else 分支）。")
    elif sustained_y and not sustained_x:
        print("     **持续竖直漂移** —— 像是重力/地面判定有问题。")
    else:
        print("     **两个方向都在持续漂移**，需要看上面的逐行数据判断来源。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
