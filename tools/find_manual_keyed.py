# -*- coding: utf-8 -*-
"""在整机里找"手工抠像的成品"——带 alpha 的 mov，或上游素材链的中间目录。

为什么值得全盘找：上游发布的是 640x360 的 webm，而**手工抠像的原始导出**
（Premiere 的 ProRes 4444 with Alpha）并没有随仓库发布。如果本机留着它，
那就是"高分辨率 + 已手工抠干净"的理想图源 —— 绿描边与分辨率两个问题一起解决，
而且能省掉我们自己的抠像步骤。

搜索目标：
  * `*.mov` / `*.mp4` 里名字含中文动画名的（尤其是体积极大的，ProRes 会很大）
  * 目录名 `pr` / `step01` / `step02` / `step03` / `video` / `main-animation`
  * 任何 `dsh-pet` 的源码检出（里面有 scripts/ 与这些目录）

排除：系统目录、程序安装目录、node_modules、.git。
"""

import os
import sys
import time

ROOTS = [r"E:\dsh", "E:\\", "D:\\", r"C:\Users\86173"]
SKIP = {
    "windows", "$recycle.bin", "system volume information", "program files",
    "program files (x86)", "programdata", "appdata\\local\\temp",
    "node_modules", ".git", "__pycache__", ".venv", "venv", "site-packages",
    "illustrator2022", "photoshop", "adobe", "windowsapps",
    "anaconda", "anaconda3", "miniconda3", "python", "dlls", "lib", "libs",
}
# 素材链的中间目录名（上游用这些）
TARGET_DIRS = {"pr", "step01", "step02", "step03", "video", "main-animation",
               "assets-videos", "dsh-pet"}
VIDEO_EXT = {".mov", ".mp4", ".mkv", ".webm", ".avi"}
NAME_HINT = ("透明", "待机", "东张西望", "三球", "余额", "女仆", "alpha",
             "keyed", "matte", "step02", "step03")
MAX_SECONDS = 300


def main():
    started = time.time()
    found_dirs = []
    found_videos = []
    scanned = 0
    seen = set()

    def walk(base, depth=0):
        nonlocal scanned
        if time.time() - started > MAX_SECONDS:
            return
        if depth > 6:
            return
        try:
            entries = list(os.scandir(base))
        except (PermissionError, OSError):
            return
        for entry in entries:
            if time.time() - started > MAX_SECONDS:
                return
            name = entry.name
            low = name.lower()
            try:
                if entry.is_dir(follow_symlinks=False):
                    if low in SKIP or any(s in entry.path.lower() for s in SKIP):
                        continue
                    if low in TARGET_DIRS:
                        found_dirs.append(entry.path)
                    scanned += 1
                    walk(entry.path, depth + 1)
                elif entry.is_file(follow_symlinks=False):
                    ext = os.path.splitext(low)[1]
                    if ext in VIDEO_EXT:
                        size = entry.stat().st_size
                        # 只要"像是素材"的：体积大，或名字带中文动画名
                        if size > 3 * 1048576 or any(h in name for h in NAME_HINT):
                            if entry.path not in seen:
                                seen.add(entry.path)
                                found_videos.append((entry.path, size))
            except OSError:
                continue

    print()
    print("  全机搜索：手工抠像成品 / 素材链中间产物")
    print("  " + "=" * 76)
    for root in ROOTS:
        if not os.path.isdir(root):
            continue
        print("  扫描 %s ..." % root)
        walk(root)
        if time.time() - started > MAX_SECONDS:
            print("  （已达 %d 秒上限，停止）" % MAX_SECONDS)
            break

    print()
    print("  结果")
    print("  " + "-" * 76)
    print("  扫描目录数: %d" % scanned)
    print()
    if found_dirs:
        print("  **命中素材链相关目录 %d 个**：" % len(found_dirs))
        for path in found_dirs[:20]:
            count = 0
            try:
                count = len(os.listdir(path))
            except OSError:
                pass
            print("     %s  （%d 项）" % (path, count))
    else:
        print("  没有命中 pr/step01/step02/step03/video/main-animation 这类目录")
    print()
    if found_videos:
        found_videos.sort(key=lambda item: -item[1])
        print("  体积较大或名字像素材的视频文件 %d 个，最大的 20 个：" % len(found_videos))
        for path, size in found_videos[:20]:
            print("     %8.1f MB  %s" % (size / 1048576.0, path))
    else:
        print("  没有找到像素材的视频文件")
    print()
    print("  判读")
    print("  " + "-" * 76)
    if found_dirs or found_videos:
        print("  有命中 —— 逐个确认哪些是「手工抠像的透明导出」（.mov + ProRes 4444 + 带 alpha）")
    else:
        print("  没找到。那就只能继续用绿幕源自己抠像。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
