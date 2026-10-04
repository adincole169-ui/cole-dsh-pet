# -*- coding: utf-8 -*-
"""按约定删除发给朋友用的分发产物（推送成功后执行）。

删除范围（**仅限** E:\\dsh\\_share 之下）：
  * dsh-pet-share.zip  与 dsh-pet-share/    —— 完整分发包
  * dsh-pet-update.zip 与 dsh-pet-update/   —— 更新补丁
  * dsh-pet-update.new.zip                  —— 重建补丁时的残留副本（内容与上者重复）
  * build.log / build2.log                  —— 打包日志

安全措施：**每个路径都先解析成绝对路径并确认它确实在 _share 之下**，
不在就拒绝删除。这类"批量删大文件"的操作一旦路径算错就是灾难，不能只靠手速。

    python tools/cleanup_share.py            # 预演，只报告
    python tools/cleanup_share.py --apply    # 真正删除
"""

import os
import shutil
import sys

SHARE = r"E:\dsh\_share"
TARGETS = [
    "dsh-pet-share.zip",
    "dsh-pet-share",
    "dsh-pet-update.zip",
    "dsh-pet-update",
    "dsh-pet-update.new.zip",
    "build.log",
    "build2.log",
]


def size_of(path):
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for base, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
    return total


def main():
    apply = "--apply" in sys.argv
    share = os.path.abspath(SHARE)
    if not os.path.isdir(share):
        print("  找不到 %s" % share)
        return 1

    print()
    print("  %s" % ("即将删除" if apply else "预演（不会改动任何东西）"))
    print("  范围：仅限 %s 之下" % share)
    print("  " + "=" * 62)

    doomed = []
    for name in TARGETS:
        path = os.path.abspath(os.path.join(share, name))
        # **安全校验**：必须严格位于 share 之下（防止 .. 之类跑出去）
        if not path.startswith(share + os.sep):
            print("  [拒绝] %s —— 不在 _share 之下，跳过" % path)
            continue
        if not os.path.exists(path):
            print("  [跳过] %-26s 不存在" % name)
            continue
        size = size_of(path)
        kind = "目录" if os.path.isdir(path) else "文件"
        doomed.append((path, name, size, kind))
        print("  [删除] %-26s %-4s %8.2f GB" % (name, kind, size / 1073741824.0))

    total = sum(item[2] for item in doomed)
    print("  " + "-" * 62)
    print("  合计: %d 项，%.2f GB" % (len(doomed), total / 1073741824.0))

    if not apply:
        print()
        print("  这是预演。确认无误后加 --apply 真正删除：")
        print("     python tools\\cleanup_share.py --apply")
        return 0

    print()
    removed = 0
    for path, name, _size, kind in doomed:
        try:
            if kind == "目录":
                shutil.rmtree(path)
            else:
                os.remove(path)
            removed += 1
            print("  已删除 %s" % name)
        except Exception as error:
            print("  **删除失败** %s: %s" % (name, error))

    print()
    print("  已删除 %d / %d 项" % (removed, len(doomed)))

    # 报告剩余
    left = os.listdir(share)
    if left:
        print("  _share 下还剩 %d 项:" % len(left))
        for name in sorted(left):
            print("     %s" % name)
    else:
        print("  _share 已空")
    return 0


if __name__ == "__main__":
    sys.exit(main())
