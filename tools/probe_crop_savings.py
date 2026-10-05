# -*- coding: utf-8 -*-
"""量清楚"裁剪到底能省多少"，别拿估算的数字做决定。

背景：我先前给出"修掉裁剪 bug 后 1280x720 只要约 3.4 GB"的估算，依据是
"角色约占画面 35%"。但那个 35% 是**单个动画**的量。要保持"切换动画时宠物不忽大忽小"，
所有动画必须共用**同一个裁剪切法**，于是只能用**全局公共包围盒** ——
而先前粗测显示全局包围盒几乎占满整帧（x 6..629 / y 0..359 @640x360）。
若真如此，裁剪在 1280 下几乎省不了什么，3.4 GB 就是错的。

而且——裁剪本身还会改变精灵几何（帧尺寸变了，`sprite_size()` 把整帧缩到窗口宽，
角色看起来就会变大），所以"裁不裁"必须一次性想清楚。

本脚本量：
  1. 每个动画自己的并集包围盒（宽/高/原点）
  2. 全局公共包围盒，以及按分位数取"覆盖 95% / 99% 动画"的包围盒
  3. 各自对应到 1280x720 全量帧缓存上的磁盘预算

    python tools/probe_crop_savings.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FRAMES = os.path.join(ROOT, "frames")
SAMPLE_STEP = 8
TOTAL_FRAMES = 25423
# 实测：1280x720 的帧平均 401.4 KB（原始 RGBA）
KB_PER_FRAME_1280 = 401.4
# 现有 640x360 帧平均 99.8 KB
KB_PER_FRAME_640 = 99.8


def union_for(folder):
    import numpy as np
    from PIL import Image
    left = top = 10 ** 9
    right = bottom = -1
    entries = sorted(f for f in os.listdir(folder) if f.endswith(".png"))
    for entry in entries[::SAMPLE_STEP]:
        with Image.open(os.path.join(folder, entry)) as raw:
            alpha = np.array(raw.convert("RGBA").getchannel("A"))
        ys, xs = np.where(alpha > 16)
        if not len(xs):
            continue
        left = min(left, int(xs.min()))
        top = min(top, int(ys.min()))
        right = max(right, int(xs.max()))
        bottom = max(bottom, int(ys.max()))
    if right < 0:
        return None
    return (left, top, right, bottom)


def main():
    try:
        import numpy                                              # noqa: F401
        from PIL import Image                                     # noqa: F401
    except ImportError:
        print("  需要 numpy + Pillow")
        return 1

    names = sorted(d for d in os.listdir(FRAMES) if os.path.isdir(os.path.join(FRAMES, d)))
    print()
    print("  按动画量并集包围盒（采样步长 %d 帧）" % SAMPLE_STEP)
    print("  " + "=" * 72)

    boxes = {}
    for name in names:
        box = union_for(os.path.join(FRAMES, name))
        if box:
            boxes[name] = box

    widths = sorted(boxes[n][2] - boxes[n][0] for n in boxes)
    heights = sorted(boxes[n][3] - boxes[n][1] for n in boxes)

    def pct(values, q):
        return values[min(len(values) - 1, int(len(values) * q))]

    print("  动画数: %d" % len(boxes))
    print("  单动画包围盒宽度: 最小 %d  中位 %d  95%% %d  最大 %d（画布宽 640）"
          % (widths[0], pct(widths, 0.5), pct(widths, 0.95), widths[-1]))
    print("  单动画包围盒高度: 最小 %d  中位 %d  95%% %d  最大 %d（画布高 360）"
          % (heights[0], pct(heights, 0.5), pct(heights, 0.95), heights[-1]))

    # 全局并集
    g_left = min(b[0] for b in boxes.values())
    g_top = min(b[1] for b in boxes.values())
    g_right = max(b[2] for b in boxes.values())
    g_bottom = max(b[3] for b in boxes.values())
    gw, gh = g_right - g_left + 1, g_bottom - g_top + 1
    print()
    print("  全局并集包围盒: x %d..%d  y %d..%d  ->  %dx%d"
          % (g_left, g_right, g_top, g_bottom, gw, gh))
    print("     占 640x360 画布面积 %.1f%%" % (100.0 * gw * gh / (640.0 * 360.0)))

    # 按"覆盖多少动画"取包围盒：找出使覆盖率达到 95%/99% 的最小矩形
    # 简化做法：对每个分位取左/上/右/下的分位值
    lefts = sorted(b[0] for b in boxes.values())
    tops = sorted(b[1] for b in boxes.values())
    rights = sorted(b[2] for b in boxes.values())
    bottoms = sorted(b[3] for b in boxes.values())

    print()
    print("  覆盖率不同的公共包围盒 -> 磁盘预算（1280x720 全量 %d 帧）" % TOTAL_FRAMES)
    print("  " + "-" * 72)
    print("  %-12s %-18s %-10s %s" % ("覆盖", "包围盒(w x h)", "面积占比", "全量体积"))
    for label, q in (("含全部", 1.0), ("99%", 0.99), ("95%", 0.95), ("90%", 0.90)):
        lo = 0.0 if q >= 1.0 else (1.0 - q)
        hi = 1.0 if q >= 1.0 else q
        l = lefts[min(len(lefts) - 1, int(len(lefts) * lo))]
        t = tops[min(len(tops) - 1, int(len(tops) * lo))]
        r = rights[min(len(rights) - 1, int(len(rights) * hi))]
        b = bottoms[min(len(bottoms) - 1, int(len(bottoms) * hi))]
        w, h = r - l + 1, b - t + 1
        ratio = (w * h) / (640.0 * 360.0)
        # 1280x720 下的像素数 → 按面积线性放大单帧体积（近似）
        gb = KB_PER_FRAME_1280 * ratio * TOTAL_FRAMES / 1048576.0
        print("  %-12s %-18s %-10s %.2f GB" % (label, "%dx%d" % (w, h),
                                              "%.1f%%" % (ratio * 100), gb))

    print()
    print("  不裁剪（保持 16:9 画布，帧 1280x720）")
    print("  " + "-" * 72)
    print("     全量体积: %.2f GB" % (KB_PER_FRAME_1280 * TOTAL_FRAMES / 1048576.0))
    print("     对照：现有 640x360 全量 %.2f GB" % (KB_PER_FRAME_640 * TOTAL_FRAMES / 1048576.0))
    print()
    print("  ⚠️ 注意：裁剪会改变**帧尺寸**，而 `sprite_size()` 是把整帧缩到窗口宽度，")
    print("     所以裁得越紧，角色在窗口里显得越大 —— 改裁剪必须同时重新校准")
    print("     窗口尺寸 / 初始摆放 / 掩膜，不能只改管线。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
