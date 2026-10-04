# -*- coding: utf-8 -*-
"""帧素材完整性检查：每个动画目录必须有 PNG、且首帧宽度是 640。

为什么需要：`assess_no_frames.py` 那个一次性评估脚本会临时把某个动画的缓存移走再
还原，但它没有写完整的还原逻辑，结果把一个动画目录清空了（实测 `东张西望` 变成
0 个文件，而它的 webm 源还在）。这类"动缓存的脚本"很容易留下这种坑，所以要有一个
便宜的完整性检查，随时能查。

    python tools/check_frames.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FRAMES = os.path.join(ROOT, "frames")
EXPECTED_WIDTH = 640
EXPECTED_ANIMATIONS = 106


def png_width(path):
    with open(path, "rb") as handle:
        head = handle.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return int.from_bytes(head[16:20], "big")


def main():
    if not os.path.isdir(FRAMES):
        print("  找不到 %s" % FRAMES)
        return 1
    animations = sorted(name for name in os.listdir(FRAMES)
                        if os.path.isdir(os.path.join(FRAMES, name)))
    print("  动画数: %d  (期望 %d)" % (len(animations), EXPECTED_ANIMATIONS))

    empty = []
    wrong_width = []
    total_frames = 0
    total_bytes = 0
    for animation in animations:
        folder = os.path.join(FRAMES, animation)
        pngs = sorted(name for name in os.listdir(folder) if name.endswith(".png"))
        if not pngs:
            empty.append(animation)
            continue
        total_frames += len(pngs)
        total_bytes += sum(os.path.getsize(os.path.join(folder, name)) for name in pngs)
        width = png_width(os.path.join(folder, pngs[0]))
        if width != EXPECTED_WIDTH:
            wrong_width.append((animation, width, len(pngs)))

    print("  总帧数: %d" % total_frames)
    print("  总体积: %.2f GB" % (total_bytes / 1073741824.0))
    print()
    failed = 0
    if empty:
        failed += len(empty)
        print("  **空目录（需要重新解码）**: %d 个" % len(empty))
        for name in empty:
            has_source = os.path.exists(os.path.join(ROOT, "webm", name + ".webm"))
            print("     %-24s webm 源%s" % (name, "在" if has_source else "**也缺**"))
    if wrong_width:
        failed += len(wrong_width)
        print("  **宽度不对**: %d 个" % len(wrong_width))
        for name, width, count in wrong_width:
            print("     %-24s 宽度 %s（%d 帧）" % (name, width, count))
    if not empty and not wrong_width:
        print("  全部正常：每个动画都有帧，且首帧宽度是 %d" % EXPECTED_WIDTH)
    print()
    print("  结论: %s" % ("全部通过" if failed == 0 else "有 %d 项问题，见上" % failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
