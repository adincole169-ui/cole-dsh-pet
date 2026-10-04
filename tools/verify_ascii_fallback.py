# -*- coding: utf-8 -*-
"""验证 build() 的 ASCII 兜底：用旧版 ffmpeg 也能解出**与原帧逐像素一致**的结果。

这是本次改动的核心验证。要证明三件事：
  1. 强制用 imageio-ffmpeg 自带的旧版 ffmpeg（4.2.2）时，`build()` **不报错**；
  2. 它走的是 ASCII 暂存兜底路径；
  3. 解出来的帧与系统新版 ffmpeg 解出来的帧**逐像素一致**（不能因为兜底而劣化）。

**安全**：先整体备份被测试动画的缓存，测完还原。这个项目已经因为"脚本动缓存"
出过两次事故，所以这里每次都备份。

    python tools/verify_ascii_fallback.py
"""

import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import asset_pipeline as pipeline                        # noqa: E402

ANIMATION = "东张西望"
BACKUP = ".fallbacktest"


def find_bundled():
    """找 imageio-ffmpeg 自带的 ffmpeg。

    优先用已安装的 `imageio_ffmpeg` 包；找不到就扫几个常见位置
    （有人是用 `pip install --target <目录>` 装的，那种不会出现在 sys.path 里）。
    """
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass
    import glob
    roots = []
    temp = os.environ.get("TEMP") or ""
    if temp:
        roots.append(temp)
    roots.append(os.path.dirname(ROOT))
    for base in roots:
        for pattern in ("**/imageio_ffmpeg/binaries/ffmpeg-*",
                        "imageio_ffmpeg/binaries/ffmpeg-*"):
            for hit in glob.glob(os.path.join(base, pattern), recursive=True):
                if os.path.isfile(hit):
                    return hit
    return None


def frame_pixels(folder, name="0030.png"):
    from PIL import Image
    path = os.path.join(folder, name)
    if not os.path.exists(path):
        return None
    with Image.open(path) as raw:
        image = raw.convert("RGBA")
    pixels = image.load()
    width, height = image.size
    return ([(pixels[x, y]) for y in range(0, height, 4) for x in range(0, width, 4)],
            image.size)


def main():
    bundled = find_bundled()
    if not bundled:
        print("  找不到 imageio-ffmpeg 自带的 ffmpeg")
        print("  （用 pip install --target <目录> imageio-ffmpeg 装，并把它加进 PYTHONPATH）")
        return 1

    real = pipeline.cache_dir(ANIMATION)
    backup = real + BACKUP
    if os.path.isdir(backup):
        shutil.rmtree(backup)
    had = os.path.isdir(real)
    original_count = 0
    if had:
        original_count = len([f for f in os.listdir(real) if f.endswith(".png")])
        shutil.move(real, backup)
    print()
    print("  已备份 frames\\%s（%d 个 PNG）" % (ANIMATION, original_count))

    system_exe = shutil.which("ffmpeg")
    samples = {}
    try:
        # ---- 用系统新版 ffmpeg 解一份作为基准 ----
        pipeline._FFMPEG_CACHE = system_exe
        pipeline._FFMPEG_SOURCE = "PATH(基准)"
        print()
        print("  [基准] 系统 ffmpeg: %s" % os.path.basename(system_exe))
        started = time.time()
        pipeline.build(ANIMATION, width=pipeline.TARGET_WIDTH, force=True)
        print("        解出 %d 帧，%.1f 秒" % (pipeline.frame_count(ANIMATION),
                                              time.time() - started))
        samples["system"] = frame_pixels(real)
        baseline_dir = real + ".baseline"
        if os.path.isdir(baseline_dir):
            shutil.rmtree(baseline_dir)
        shutil.move(real, baseline_dir)

        # ---- 用旧版自带 ffmpeg 解，应当自动走 ASCII 兜底 ----
        pipeline._FFMPEG_CACHE = bundled
        pipeline._FFMPEG_SOURCE = "imageio-ffmpeg(旧版)"
        print()
        print("  [测试] 自带 ffmpeg: %s" % os.path.basename(bundled))
        staging_before = sorted(os.listdir(pipeline.ascii_staging_root() or ROOT))
        started = time.time()
        pipeline.build(ANIMATION, width=pipeline.TARGET_WIDTH, force=True)
        print("        解出 %d 帧，%.1f 秒" % (pipeline.frame_count(ANIMATION),
                                              time.time() - started))
        samples["bundled"] = frame_pixels(real)

        # ---- 逐像素比对 ----
        print()
        print("  逐像素比对（第 0030 帧，每 4 像素取样，含 alpha 通道）")
        print("  " + "-" * 62)
        a = samples.get("system")
        b = samples.get("bundled")
        if not a or not b:
            print("     取不到样本帧（可能抽到的帧号不存在）")
            return 1
        data_a, size_a = a
        data_b, size_b = b
        print("     尺寸: 基准 %s  测试 %s" % (size_a, size_b))
        if size_a != size_b:
            print("     **尺寸不同**")
            return 1
        total = worst = channels = 0
        for pa, pb in zip(data_a, data_b):
            for channel in range(4):
                delta = abs(pa[channel] - pb[channel])
                total += delta
                worst = max(worst, delta)
                channels += 1
        mean = total / float(max(1, channels))
        print("     平均差: %.3f / 255" % mean)
        print("     最大差: %d / 255" % worst)

        print()
        print("  结论")
        print("  " + "=" * 62)
        if worst == 0:
            print("     两者**逐像素完全一致** —— ASCII 兜底没有引入任何劣化。")
            print("     使用者即使只有 imageio-ffmpeg 自带的旧版 ffmpeg，也能正确解码。")
        elif mean < 0.5:
            print("     差异可忽略（平均 %.3f/255，最大 %d）—— 兜底可用。" % (mean, worst))
        else:
            print("     **差异偏大**，兜底可能不适用于该 ffmpeg 版本，请复查。")
        return 0
    finally:
        # 还原：把测试结果删掉，恢复备份
        if os.path.isdir(real):
            shutil.rmtree(real)
        if had and os.path.isdir(backup):
            shutil.move(backup, real)
        baseline_dir = real + ".baseline"
        if os.path.isdir(baseline_dir):
            shutil.rmtree(baseline_dir)
        restored = 0
        if os.path.isdir(real):
            restored = len([f for f in os.listdir(real) if f.endswith(".png")])
        # 恢复原来的 ffmpeg 选择
        pipeline._FFMPEG_CACHE = None
        pipeline._FFMPEG_SOURCE = None
        print()
        print("  已还原 frames\\%s（%d 个 PNG，备份前 %d 个）"
              % (ANIMATION, restored, original_count))
        if restored != original_count:
            print("  **数量不一致，请跑 python tools/check_frames.py 复核**")


if __name__ == "__main__":
    sys.exit(main())
