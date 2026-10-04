# -*- coding: utf-8 -*-
"""校验更新补丁 zip 的内容。

要确认的：
  1. update.ps1 / 更新.cmd / 更新说明.md 在补丁根目录
  2. payload 里有那 4 个变动的代码文件
  3. payload\\frames 里是 **106 个动画**、抽样帧是 **640 宽**（不是旧的 480）
  4. 不该带的没带（logs / .venv / webm / frames_old_480）
  5. update.ps1 是 UTF-8 with BOM（否则 PowerShell 5.1 把中文读成乱码）
  6. 中文文件名没有被写成乱码（bsdtar 出过这个问题）

    python tools/verify_update_zip.py
"""

import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZIP = os.path.join(ROOT, "dist", "dsh-pet-update.zip")
DISPLAY = "dsh-pet-update/"
BOM = b"\xef\xbb\xbf"

REQUIRED = [
    "update.ps1",
    "更新.cmd",
    "更新说明.md",
    "payload/config.jsonc",
    "payload/main.py",
    "payload/README.md",
    "payload/src/pet.py",
    "payload/src/config.py",
]
MUST_NOT_HAVE = [
    "payload/logs/pet-run.log",
    "payload/.venv",
    "payload/webm",
    "payload/frames_old_480",
    "payload/tools/run_logged.py",
]


def main():
    if not os.path.exists(ZIP):
        print("  找不到 %s" % ZIP)
        return 1
    print("  zip: %s  (%.2f GB)" % (ZIP, os.path.getsize(ZIP) / 1073741824.0))

    failed = 0
    with zipfile.ZipFile(ZIP) as archive:
        entries = archive.namelist()
        # 统一成 "dsh-pet-update/xxx"（带或不带顶层目录都能处理）
        normalized = []
        for name in entries:
            cleaned = name.replace("\\", "/")
            if not cleaned.startswith(DISPLAY):
                cleaned = DISPLAY + cleaned
            normalized.append(cleaned)
        present = set(normalized)

        print()
        print("  == 必需文件 ==")
        for item in REQUIRED:
            key = DISPLAY + item
            found = key in present
            if not found:
                failed += 1
            print("     %s %s" % ("有  " if found else "缺失", item))

        print()
        print("  == 不该带的 ==")
        for item in MUST_NOT_HAVE:
            key = DISPLAY + item
            hit = any(name == key or name.startswith(key + "/") for name in normalized)
            if hit:
                failed += 1
            print("     %s %s" % ("**泄漏**" if hit else "没带（正确）", item))

        print()
        print("  == 中文文件名 ==")
        for item in ("更新.cmd", "更新说明.md"):
            key = DISPLAY + item
            ok = key in present
            if not ok:
                failed += 1
            print("     %s %s" % ("正确" if ok else "**乱码或缺失**", item))
        # 顺带报一下实际含中文的条目，便于发现乱码
        chinese = [name for name in normalized
                   if any("\u4e00" <= char <= "\u9fff" for char in name)
                   and name.count("/") == 1]
        print("     根目录含中文的条目: %d 个" % len(chinese))

        print()
        print("  == 帧素材 ==")
        frame_prefix = DISPLAY + "payload/frames/"
        frames = [name for name in normalized
                  if name.startswith(frame_prefix) and name.endswith(".png")]
        animations = set()
        for name in frames:
            parts = name[len(frame_prefix):].split("/")
            if len(parts) >= 2:
                animations.add(parts[0])
        print("     动画数: %d  (期望 106)" % len(animations))
        print("     PNG 数: %d  (期望约 25423)" % len(frames))
        if len(animations) != 106:
            failed += 1

        print()
        print("     %-24s %s" % ("抽样动画", "首帧宽度"))
        print("     " + "-" * 40)
        ordered = sorted(animations)
        samples = ordered[:3] + ordered[len(ordered) // 2:len(ordered) // 2 + 2]
        widths = []
        for animation in samples:
            key = "%s%s/0001.png" % (frame_prefix, animation)
            if key not in present:
                print("     %-24s 找不到首帧" % animation)
                failed += 1
                continue
            data = archive.read(key)
            width = int.from_bytes(data[16:20], "big")
            widths.append(width)
            print("     %-24s %d" % (animation, width))
        if widths and any(width != 640 for width in widths):
            failed += 1
            print("     **有抽样帧不是 640 —— 帧素材没更新**")

        print()
        print("  == update.ps1 的 BOM ==")
        key = DISPLAY + "update.ps1"
        if key in present:
            head = archive.read(key)[:3]
            has_bom = head == BOM
            if not has_bom:
                failed += 1
            print("     %s" % ("有 BOM（正确）" if has_bom
                              else "**没有 BOM —— PowerShell 5.1 会读成乱码**"))
        else:
            failed += 1
            print("     找不到 update.ps1")

    print()
    print("  结论: %s" % ("全部通过" if failed == 0 else "有 %d 项问题，见上" % failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
