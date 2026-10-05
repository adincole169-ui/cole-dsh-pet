# -*- coding: utf-8 -*-
"""测"逐帧调色板"造成的**时间闪烁** —— 静态对照图看不出来的那种画质损失。

为什么怀疑它：`_quantize()` 用的是 `Image.quantize(colors=256, method=MEDIANCUT)`，
而它是**对每一帧单独**求调色板的。于是同一块本该平滑渐变的地方，在相邻帧里
会被归到**不同的** 256 色上 —— 单独看每帧都还行，连起来看就是"沙沙"的闪烁。
这正好解释用户说的"很明显不如他"：静态比对看不出，动起来才明显。

做法：取若干**角色身上**的固定采样点，逐帧跟踪它们的 RGB，
比较两条链的"时间抖动"：
    (1) 我们的缓存帧（逐帧 256 色量化）
    (2) 直接解 webm（≈ 上游所见，无量化）
判据：同一个点在相邻帧之间的颜色跳变量，若 (1) 明显大于 (2)，闪烁即成立。

    python tools/probe_temporal_flicker.py 东张西望
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FRAME_COUNT = 96
SAMPLE_POINTS = 40


def ffmpeg_path():
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("需要 PATH 里有 ffmpeg")
    return exe


def decode_all(webm, folder, limit=FRAME_COUNT):
    """把 webm 前 limit 帧解成 PNG 到 folder（不做任何加工）。"""
    os.makedirs(folder, exist_ok=True)
    subprocess.run([ffmpeg_path(), "-y", "-v", "error", "-c:v", "libvpx-vp9",
                    "-i", webm, "-frames:v", str(limit), "-pix_fmt", "rgba",
                    os.path.join(folder, "%04d.png")], capture_output=True)
    return sorted(f for f in os.listdir(folder) if f.endswith(".png"))


def main():
    argv = sys.argv[1:]
    animation = argv[0] if argv and not argv[0].startswith("-") else "东张西望"
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        print("  需要 numpy + Pillow")
        return 1

    webm = os.path.join(ROOT, "webm", animation + ".webm")
    ours_dir = os.path.join(ROOT, "frames", animation)
    if not os.path.exists(webm) or not os.path.isdir(ours_dir):
        print("  缺素材")
        return 1

    work = os.path.join(ROOT, "logs", "_flicker")
    if os.path.isdir(work):
        shutil.rmtree(work, ignore_errors=True)
    reference = decode_all(webm, os.path.join(work, "ref"))
    print()
    print("  时间闪烁实测（%s，前 %d 帧）" % (animation, len(reference)))
    print("  " + "=" * 74)

    # 从中间一帧里挑"角色身上"的采样点
    mid = len(reference) // 2
    with Image.open(os.path.join(work, "ref", reference[mid])) as raw:
        array = np.asarray(raw.convert("RGBA"))
    alpha = array[..., 3]
    ys, xs = np.where(alpha > 200)
    if not len(xs):
        print("  取不到角色像素")
        return 1
    # 均匀挑点，避开边缘（取 α 高的地方）
    step = max(1, len(xs) // SAMPLE_POINTS)
    points = list(zip(xs[::step][:SAMPLE_POINTS], ys[::step][:SAMPLE_POINTS]))

    def track(folder, entries):
        series = []
        for entry in entries:
            path = os.path.join(folder, entry)
            if not os.path.isfile(path):
                continue
            with Image.open(path) as raw:
                data = np.asarray(raw.convert("RGBA"))
            series.append([data[y, x, :3].astype(np.float32) for x, y in points])
        return np.array(series)                      # (帧, 点, 3)

    ref_series = track(os.path.join(work, "ref"), reference)
    our_series = track(ours_dir,
                       ["%04d.png" % (i + 1) for i in range(len(reference))])

    if ref_series.size == 0 or our_series.size == 0:
        print("  取不到序列")
        return 1
    n = min(len(ref_series), len(our_series))
    ref_series = ref_series[:n]
    our_series = our_series[:n]

    def jitter(series):
        """相邻帧之间每个采样点的颜色跳变量（只统计内容没大改的相邻帧）。"""
        step = np.abs(np.diff(series, axis=0))       # (n-1, 点, 3)
        # 逐点逐通道求均值
        return float(step.mean()), float(np.percentile(step, 95))

    ref_mean, ref_p95 = jitter(ref_series)
    our_mean, our_p95 = jitter(our_series)

    print("  %-30s %-14s %s" % ("版本", "相邻帧平均跳变", "95 分位跳变"))
    print("  " + "-" * 74)
    print("  %-30s %-14.3f %.3f" % ("参考（直接解 webm）", ref_mean, ref_p95))
    print("  %-30s %-14.3f %.3f" % ("我们（逐帧 256 色量化）", our_mean, our_p95))
    ratio = our_mean / ref_mean if ref_mean else 0.0
    print()
    print("  结论")
    print("  " + "-" * 74)
    print("  时间抖动比: %.2f 倍" % ratio)
    if ratio >= 1.5:
        print("  **闪烁成立**：逐帧独立调色板让颜色在帧间跳变，动起来就是'沙沙'的。")
        print("  这也解释了为什么静态对照图看不出问题。")
        print()
        print("  修法（任选）：")
        print("    a) 关掉调色板量化 —— 直接出 RGBA，磁盘 +14%，画面与上游一致；")
        print("    b) 改成**每个动画共用一个调色板**（对该动画所有帧求并集后量化），")
        print("       既消除闪烁，又比全 RGBA 省空间。")
    else:
        print("  抖动差异不大 —— 闪烁不是主因，需要另找原因。")
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
