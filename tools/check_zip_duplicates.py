# -*- coding: utf-8 -*-
"""检查 zip 里有没有**重复条目**。

为什么单独查这个：用 `zipfile.ZipFile(mode='a')` 往已有的 zip 里追加重名文件时，
**旧条目不会被替换**，zip 里会留下两份同名条目（实测触发过
`UserWarning: Duplicate name`）。这种 zip 是坏的——解压工具取哪一份取决于实现，
有的取第一个（旧内容）、有的取最后一个，用户拿到的可能是没更新的文件。

所以打包必须**从零生成**，不能靠追加重写。

    python tools/check_zip_duplicates.py [zip路径 ...]
"""

import collections
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT = [
    os.path.join(ROOT, "dist", "dsh-pet-update.zip"),
    os.path.join(ROOT, "dist", "dsh-pet-share.zip"),
]


def main(argv):
    targets = argv[1:] or [p for p in DEFAULT if os.path.exists(p)]
    if not targets:
        print("  没有可检查的 zip")
        return 0

    failed = 0
    for path in targets:
        print("  %s" % path)
        if not os.path.exists(path):
            print("     文件不存在")
            failed += 1
            continue
        with zipfile.ZipFile(path) as archive:
            names = [name.replace("\\", "/") for name in archive.namelist()]
        counter = collections.Counter(names)
        duplicates = {name: count for name, count in counter.items() if count > 1}
        if duplicates:
            failed += 1
            print("     **有 %d 个重复条目**" % len(duplicates))
            for name, count in list(duplicates.items())[:10]:
                print("        %s  x%d" % (name, count))
        else:
            print("     无重复条目（%d 个文件）" % len(names))
    print()
    print("  检查 %d 个 zip，%d 个有问题" % (len(targets), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
