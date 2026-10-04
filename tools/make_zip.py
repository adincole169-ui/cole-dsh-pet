# -*- coding: utf-8 -*-
"""从补丁目录**从零**生成 zip。

为什么不用现成工具：
  * `Compress-Archive`：慢，且早先发现它会把中文名写坏（本次实测 2.5GB 要数分钟）；
  * `tar.exe -a`（bsdtar）：快，但**把中文文件名写成了乱码**
    （实测 `更新.cmd` 在 zip 里变成 `╕ⁿ╨┬.cmd`），解压出来名字就不对了；
  * 往已有 zip 里**追加**：会留下同名重复条目，解压取哪份不确定（坏的）。

Python 的 `zipfile` 会以 UTF-8 写文件名并置 UTF-8 标志位，中文名可靠。

    python tools/make_zip.py                     # 默认打更新补丁
    python tools/make_zip.py <源目录> <输出zip>
"""

import os
import sys
import time
import zipfile

# 默认值从**项目根**推出来，不写死绝对路径（换台机器也能用）
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SOURCE = os.path.join(ROOT, "dist", "dsh-pet-update")
DEFAULT_OUTPUT = os.path.join(ROOT, "dist", "dsh-pet-update.zip")


def main(argv):
    source = argv[1] if len(argv) > 1 else DEFAULT_SOURCE
    output = argv[2] if len(argv) > 2 else DEFAULT_OUTPUT

    if not os.path.isdir(source):
        print("  找不到源目录 %s" % source)
        return 1
    if os.path.exists(output):
        os.remove(output)

    # 收集文件：顶层用目录名（解压后得到 source 同名的文件夹）
    parent = os.path.dirname(source.rstrip(os.sep))
    root_name = os.path.basename(source.rstrip(os.sep))
    files = []
    for base, _dirs, names in os.walk(source):
        for name in names:
            full = os.path.join(base, name)
            relative = os.path.relpath(full, parent).replace(os.sep, "/")
            files.append((full, relative))
    files.sort(key=lambda item: item[1])

    total = sum(os.path.getsize(full) for full, _ in files)
    print("  源目录: %s" % source)
    print("  文件数: %d   总大小: %.2f GB" % (len(files), total / 1073741824.0))
    print("  输出:   %s" % output)
    print()

    started = time.time()
    written = 0
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        for full, relative in files:
            archive.write(full, relative)
            written += 1
            if written % 5000 == 0:
                elapsed = time.time() - started
                done = sum(os.path.getsize(f) for f, _ in files[:written])
                speed = done / max(0.001, elapsed) / 1048576.0
                print("      %6d/%d  %.1f 分钟  %.0f MB/s"
                      % (written, len(files), elapsed / 60.0, speed))

    elapsed = time.time() - started
    size = os.path.getsize(output)
    print()
    print("  完成: %.2f GB，用时 %.1f 分钟" % (size / 1073741824.0, elapsed / 60.0))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
