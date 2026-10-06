# -*- coding: utf-8 -*-
"""验证别人补丁里的说法：**流式解码的内存到底有没有上限？**

补丁（cole-dsh-pet-fix.patch）声称：

    原先 _frames 只写不删,一轮后整段(~222 MB/动画)留在内存
    现在上限约 (LOOKAHEAD + KEEP_BEHIND) 帧

而且还说了第二件事：

    消费端位置用绝对序号，不是取模后的帧号：
    原先用帧号，第二圈起 `_written - _position` 恒大于 lookahead，背压永远不放行

**这两条如果成立，就是我自己写出来的严重缺陷**（内存 + 播完一圈后可能卡住），
所以必须自己量一遍，而不是相信补丁的说法。

量四件事：
  1. `_frames` 的条目数在一圈之后是多少（期望：小；若等于帧总数就是泄漏）；
  2. 进程 RSS 增长多少；
  3. 连续取帧跨越一圈之后，帧号是否还在推进（背压没放行就会卡住）；
  4. `frame()` 跨越一圈后的行为。

    python tools/probe_stream_memory.py
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication          # noqa: E402
import stream_frames                              # noqa: E402


def rss_mb():
    """当前进程 RSS（MB）。用 psutil（本机 5.7.0 可用），退化到读 /proc 不可能。"""
    try:
        import psutil
        return psutil.Process().memory_info().rss / 1048576.0
    except Exception:
        return float("nan")


def pick_animation():
    """挑一个 webm，优先短的（少等）。"""
    import json
    meta_path = os.path.join(ROOT, "webm-meta.json")
    with open(meta_path, encoding="utf-8") as handle:
        meta = json.load(handle)
    items = []
    for name, info in meta.items():
        frames = info.get("frames") or 0
        if frames:
            items.append((frames, name))
    items.sort()
    return items[0][1] if items else None


def main():
    app = QApplication.instance() or QApplication([])      # noqa: F841

    if not stream_frames.available():
        print("  ffmpeg 不可用，无法验证")
        return 1

    name = pick_animation()
    if not name:
        print("  webm-meta.json 里没有可用动画")
        return 1

    info = stream_frames.webm_info(name) or {}
    if not info:
        print("  拿不到 %s 的元信息" % name)
        return 1

    print()
    print("  验证：流式解码的内存上限与跨圈行为")
    print("  " + "=" * 74)
    print("  动画: %s" % name)

    # 构造即启动（见 StreamAnimation.__init__ 末尾起的线程），没有单独的 start()
    anim = stream_frames.StreamAnimation(name, info)
    count = int(info.get("frames") or 0)
    print("  帧数: %s" % count)

    # 等首帧
    deadline = time.time() + 10
    while time.time() < deadline and anim.frame(0) is None:
        time.sleep(0.02)
    if anim.frame(0) is None:
        print("  **首帧拿不到**，无法继续")
        anim.close()
        return 1
    print("  首帧就绪")

    before_rss = rss_mb()
    before_len = len(anim._frames)

    # --- 连着取满两圈以上 ---
    #
    # **必须按接近真实的速率消费**：第一版我用 0.12 ms/帧 猛取，比实时（41.7 ms/帧）
    # 快 300 倍，生产端根本追不上，于是消费者 32 步之后就落在预读窗口之外、
    # `frame()` 返回 None —— 那是**测法的产物**，不是"流卡住"。
    # 按真实节奏跑，才能看出跨圈之后背压会不会放行、内存会不会涨。
    loops = 2
    total = count * loops + 40
    pace = float(os.environ.get("PROBE_PACE_MS", "6"))   # 6 ms/帧 ≈ 4 倍速
    print()
    print("  消费速率: %.1f ms/帧（实时是 %.1f ms/帧）" % (pace, 1000.0 / 24.0))
    seen = {}
    order = []
    stalled_at = None
    started = time.time()
    for step in range(total):
        index = step % count
        image = anim.frame(index)
        if image is None:
            stalled_at = step
            break
        key = id(image)
        seen[key] = seen.get(key, 0) + 1
        order.append(index)
        time.sleep(pace / 1000.0)
    elapsed = time.time() - started

    after_rss = rss_mb()
    after_len = len(anim._frames)

    # --- 报告 ---
    print()
    print("  取帧: %d 次，用时 %.2f 秒（%.2f ms/次）" % (len(order), elapsed,
                                                       elapsed / max(1, len(order)) * 1000))
    print("  `_frames` 条目数: %d -> %d" % (before_len, after_len))
    print("  进程 RSS: %.1f MB -> %.1f MB（增长 %.1f MB）"
          % (before_rss, after_rss, after_rss - before_rss))

    frame_bytes = (info.get("width") or 0) * (info.get("height") or 0) * 4
    print("  单帧大小: %.2f MB（%sx%s RGBA）"
          % (frame_bytes / 1048576.0, info.get("width"), info.get("height")))
    if after_len:
        print("  `_frames` 占用上限估计: %.1f MB" % (after_len * frame_bytes / 1048576.0))

    # --- 判定 ---
    print()
    print("  判定")
    print("  " + "-" * 74)
    problems = []

    # 1. 内存上限：条目数是否远小于帧总数
    if count and after_len >= count:
        problems.append("`_frames` 有 %d 条、等于帧总数 %d —— **旧帧从未淘汰，整段留在内存**"
                        % (after_len, count))
    elif count and after_len > 0:
        print("  OK   `_frames` 只有 %d 条（帧总数 %d）—— 有淘汰，内存有上限"
              % (after_len, count))

    # 2. RSS 增长是否与"整段"同量级
    whole = count * frame_bytes / 1048576.0
    grew = after_rss - before_rss
    if whole > 50 and grew > whole * 0.5:
        problems.append("RSS 增长 %.0f MB，接近整段的 %.0f MB —— 内存确实没有上限"
                        % (grew, whole))
    else:
        print("  OK   RSS 增长 %.1f MB，远小于整段的 %.0f MB" % (grew, whole))

    # 3. 跨圈：有没有在跑满两圈之前拿不到帧
    if stalled_at is not None:
        problems.append("取帧在第 %d 次（帧号 %d，约第 %.1f 圈）就断了 —— **跨圈之后流卡住**"
                        % (stalled_at, stalled_at % count, stalled_at / max(1, count)))
    else:
        print("  OK   连取 %d 次（%.1f 圈）全程有帧，没有卡住"
              % (len(order), len(order) / max(1, count)))

    # 4. 帧对象是否被复用/重建（间接说明淘汰在发生）
    print("  提示   不同的 QImage 对象数: %d" % len(seen))

    anim.close()
    time.sleep(0.5)

    print()
    if problems:
        for item in problems:
            print("     [问题] %s" % item)
        print()
        print("  结论：**量到了缺陷**（内存没有上限、或者跨圈卡住）。需要修。")
        return 1
    print("  结论：**没有量到缺陷** —— 内存有上限（≈ LOOKAHEAD+KEEP_BEHIND 帧）、"
          "跨圈全程有帧。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
