# -*- coding: utf-8 -*-
"""核对更新补丁 zip 里某个动画是否完整（帧数 + 首帧宽度）。

用途：`assess_no_frames.py` 那个一次性脚本曾把工作目录里的 `东张西望` 清空。
补丁 zip 是**事故之前**建立的，按道理不受影响，但要能**证明**这一点——
所以就逐个动画数条目、量首帧宽度。

    python tools/check_zip_animation.py 东张西望 [更多动画...]
"""

import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZIP = os.path.join(ROOT, "dist", "dsh-pet-update.zip")
PREFIX = "dsh-pet-update/payload/frames/"
EXPECTED_WIDTH = 640
EXPECTED_FRAMES = 241


def main(argv):
    animations = argv[1:] or ["东张西望"]
    if not os.path.exists(ZIP):
        print("  找不到 %s" % ZIP)
        return 1

    failed = 0
    with zipfile.ZipFile(ZIP) as archive:
        names = [name.replace("\\", "/") for name in archive.namelist()]
        for animation in animations:
            key = PREFIX + animation + "/"
            frames = sorted(name for name in names
                            if name.startswith(key) and name.endswith(".png"))
            if not frames:
                print("  %-24s **补丁里没有这个动画**" % animation)
                failed += 1
                continue
            data = archive.read(frames[0])
            width = int.from_bytes(data[16:20], "big")
            first = frames[0][len(key):]
            last = frames[-1][len(key):]
            ok = (width == EXPECTED_WIDTH and len(frames) >= 200)
            if not ok:
                failed += 1
            print("  %-24s 帧数 %-5d 首帧宽 %-5d  范围 %s..%s  %s"
                  % (animation, len(frames), width, first, last,
                     "OK" if ok else "**异常**"))
            # 抽中间一帧也确认可读
            middle = frames[len(frames) // 2]
            middle_data = archive.read(middle)
            middle_width = int.from_bytes(middle_data[16:20], "big")
            if middle_width != EXPECTED_WIDTH:
                failed += 1
                print("       中间帧 %s 宽度异常: %d" % (middle, middle_width))
    print()
    print("  结论: %s" % ("全部正常" if failed == 0 else "有 %d 项异常" % failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
