# -*- coding: utf-8 -*-
"""一键准备素材：检查依赖 -> 解码全部动画 -> 报告。

给**从源码 clone 下来**的使用者用。目标是把"接下来该做什么"压缩成一条命令：

    python tools/setup_assets.py

它会：
  1. 检查 webm 素材在不在（本仓库已附带 106 个）；
  2. 找一个可用的 ffmpeg（PATH 里的优先，其次 imageio-ffmpeg 自带的）；
  3. **并行**把全部动画解码成 PNG 帧（实测 106 个约 10 分钟，具体看机器）；
  4. 报出结果，并告诉你怎么启动。

常用参数：
    --jobs N      并行度（默认按 CPU 核数自动决定，2~6）
    --check       只检查环境与素材，不解码
    --force       已解码的也重解

    python tools/setup_assets.py --check
    python tools/setup_assets.py --jobs 8
"""

import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import asset_pipeline as pipeline                        # noqa: E402


def human(seconds):
    if seconds < 60:
        return "%.0f 秒" % seconds
    return "%.1f 分钟" % (seconds / 60.0)


def main():
    argv = sys.argv[1:]
    check_only = "--check" in argv
    force = "--force" in argv
    jobs = None
    if "--jobs" in argv:
        try:
            jobs = int(argv[argv.index("--jobs") + 1])
        except (IndexError, ValueError):
            print("  --jobs 后面要跟一个数字，例如 --jobs 6")
            return 2

    print()
    print("  大肥鱼桌宠：素材准备")
    print("  " + "=" * 62)

    # --- 1. 素材 ---
    animations = pipeline.list_animations()
    print()
    print("  [1/3] 动画源素材（webm/）")
    if not animations:
        print("      **没找到任何 webm**")
        print("      本仓库应当自带 106 个。请确认 clone 完整，或按 ASSETS.md 自行准备。")
        return 1
    print("      找到 %d 个动画" % len(animations))

    # --- 2. ffmpeg ---
    print()
    print("  [2/3] 解码器（ffmpeg）")
    try:
        exe, origin = pipeline.ffmpeg_origin()
    except RuntimeError as error:
        print("      **找不到 ffmpeg**")
        for line in str(error).splitlines():
            print("      %s" % line)
        return 1

    version = pipeline.ffmpeg_version()
    print("      来源 : %s" % origin)
    print("      路径 : %s" % exe)
    print("      版本 : %s" % (version[:70] or "(取不到)"))

    staging = pipeline.ascii_staging_root()
    print("      ASCII 暂存目录: %s" % (staging or "**找不到（旧版 ffmpeg 可能解码失败）**"))
    if origin == "imageio-ffmpeg" and not staging:
        print("      提示：自带的是旧版 ffmpeg，且没有可用的 ASCII 暂存目录，")
        print("            若解码失败请装一个较新的 ffmpeg 放进 PATH。")

    # --- 3. 解码 ---
    pending = animations if force else [
        name for name in animations if not pipeline.is_cached(name)]
    cached = len(animations) - len(pending)

    print()
    print("  [3/3] 解码成 PNG 帧")
    print("      已解码 : %d 个" % cached)
    print("      待解码 : %d 个" % len(pending))

    if check_only:
        print()
        print("  （--check：只检查，不解码）")
        if not pending:
            print("  素材已就绪，可以直接启动：python main.py")
        else:
            print("  运行下面的命令开始解码：")
            print("     python tools/setup_assets.py")
        return 0

    if not pending:
        print()
        print("  全部已解码，无需操作。直接启动：")
        print("     python main.py")
        return 0

    workers = jobs if jobs else pipeline.default_workers()
    print("      并行度 : %d" % workers)
    print()

    started = time.time()

    def progress(index, count, name, frames):
        elapsed = time.time() - started
        rate = elapsed / max(1, index)
        remaining = rate * (count - index)
        print("      [%3d/%3d] %-24s %4d 帧   已用 %s，预计还需 %s"
              % (index, count, name[:24], frames, human(elapsed), human(remaining)))

    results = pipeline.build_all_parallel(
        workers=workers, names=pending, progress=progress)

    elapsed = time.time() - started
    failed = [item for item in results if item[1] < 0]

    print()
    print("  " + "=" * 62)
    print("  完成：成功 %d，失败 %d，用时 %s"
          % (len(results) - len(failed), len(failed), human(elapsed)))
    for name, _count, error in failed[:8]:
        print("     失败 %s: %s" % (name, (error or "")[:120]))

    # 复核一遍
    print()
    total = sum(1 for name in animations if pipeline.is_cached(name))
    print("  现在已有 %d / %d 个动画的帧缓存" % (total, len(animations)))
    size = pipeline.cache_size()
    print("  缓存体积: %.2f GB" % (size / 1073741824.0))

    if failed:
        print()
        print("  有失败的动画。常见原因：ffmpeg 太旧或路径问题；")
        print("  可试：装一个较新的 ffmpeg 放进 PATH，再重跑本脚本。")
        return 1

    print()
    print("  可以启动了：")
    print("     python main.py")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
