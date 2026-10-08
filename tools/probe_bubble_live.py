# -*- coding: utf-8 -*-
"""验证：让**正在运行**的那只桌宠说一句话，再把气泡的实际状态读回来。

为什么单独写：用 PowerShell 的 `Invoke-RestMethod` 发中文很容易变成 `????`
（编码没走 UTF-8），那样看到的"气泡内容"是**发送端**的问题，不是桌宠的问题。
这里收发都按 UTF-8 显式处理。

    python tools/probe_bubble_live.py ["自定义台词"]
"""

import json
import sys
import time
import urllib.request

PORT = 8899
BASE = "http://127.0.0.1:%d" % PORT


def post(path, payload):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def debug():
    with urllib.request.urlopen(BASE + "/debug", timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def main(argv):
    text = argv[1] if len(argv) > 1 else "窗外的云软绵绵的，好想咬一口呀，可是主人还在忙呢"
    print()
    print("  验证运行中的桌宠气泡")
    print("  " + "=" * 74)
    print("  发送台词: %s（%d 字）" % (text, len(text)))
    try:
        post("/say", {"text": text, "seconds": 8})
    except Exception as error:
        print("  发送失败（桌宠在跑吗？）: %s" % error)
        return 1
    time.sleep(1.0)
    info = debug()
    bubble = info.get("bubble")
    window = info.get("window")
    print("  桌宠回读气泡: %r" % (bubble,))
    print("  窗口尺寸    : %s" % window)
    problems = []
    if not bubble:
        problems.append("桌宠里没有气泡内容")
    elif bubble != text:
        problems.append("气泡内容与发送的不一致（发送端或接收端编码问题）")
    else:
        print("  OK   气泡内容与发送**完全一致**（编码没问题）")
    if window:
        # 窗口高度 = 精灵高度 + 气泡留白；有气泡时必须比精灵高
        sprite_like = 180
        if window[1] <= sprite_like:
            problems.append("窗口高度 %d 不大于精灵高度 %d —— 气泡没有把窗口撑开"
                            % (window[1], sprite_like))
        else:
            print("  OK   窗口被气泡撑高到 %d（精灵约 %d，留白 %d）"
                  % (window[1], sprite_like, window[1] - sprite_like))
    print()
    if problems:
        for item in problems:
            print("     [问题] %s" % item)
        return 1
    print("  结论：气泡内容与尺寸都正常。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
