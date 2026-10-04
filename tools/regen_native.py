# -*- coding: utf-8 -*-
"""把所有动画重新解码成**原生分辨率**（TARGET_WIDTH=640），并且可以一键回退。

为什么单独写一个脚本而不是用 `asset_pipeline.py build-all`：
`build()` 在已有缓存时会**直接跳过**，所以 `build_all()` 不会重新生成；而要重新生成
就得先删掉 2GB 旧缓存——一旦中途失败，就只剩一堆新旧混杂的目录，且没有退路。
（之前用探针脚本动缓存时已经弄坏过一次，这次不重犯。）

做法：
  * 每个动画先把旧目录**移动**到 `frames_old_480/<名字>`，再生成新的；
  * 全部完成后备份仍然保留，想回退只要跑 `--rollback`；
  * 任何一个失败都不会影响其它动画，也不会留下半成品。

    python tools/regen_native.py             # 重新生成全部
    python tools/regen_native.py --rollback  # 恢复成之前的 480 缓存
    python tools/regen_native.py --status    # 看当前是原生还是旧的
"""

import argparse
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

import asset_pipeline as pipeline               # noqa: E402
from PIL import Image                           # noqa: E402

FRAME_DIR = os.path.join(ROOT, "frames")
BACKUP_DIR = os.path.join(ROOT, "frames_old_480")


def measure(folder):
    """返回 (帧数, 宽, 高)；目录不存在则 (0, 0, 0)。"""
    if not os.path.isdir(folder):
        return 0, 0, 0
    pngs = sorted(f for f in os.listdir(folder) if f.endswith(".png"))
    if not pngs:
        return 0, 0, 0
    with Image.open(os.path.join(folder, pngs[0])) as image:
        return len(pngs), image.width, image.height


def status():
    print("  当前缓存: %s" % FRAME_DIR)
    animations = [d for d in sorted(os.listdir(FRAME_DIR))
                  if os.path.isdir(os.path.join(FRAME_DIR, d))]
    widths = {}
    for name in animations:
        _count, width, _height = measure(os.path.join(FRAME_DIR, name))
        widths.setdefault(width, []).append(name)
    for width, names in sorted(widths.items()):
        print("    宽度 %-5s : %d 个动画  (例如 %s)"
              % (width, len(names), ", ".join(names[:3])))
    if os.path.isdir(BACKUP_DIR):
        print("  备份: %s 存在（可用 --rollback 回退）" % BACKUP_DIR)
    else:
        print("  备份: 无")
    total = sum(os.path.getsize(os.path.join(base, f))
                for base, _d, files in os.walk(FRAME_DIR) for f in files)
    print("  体积: %.2f GB" % (total / 1073741824.0))
    return 0


def rollback():
    if not os.path.isdir(BACKUP_DIR):
        print("  没有备份可回退（%s 不存在）" % BACKUP_DIR)
        return 1
    backups = [d for d in os.listdir(BACKUP_DIR)
               if os.path.isdir(os.path.join(BACKUP_DIR, d))]
    print("  正在回退 %d 个动画..." % len(backups))
    restored = 0
    for name in backups:
        source = os.path.join(BACKUP_DIR, name)
        target = os.path.join(FRAME_DIR, name)
        if os.path.isdir(target):
            shutil.rmtree(target)
        shutil.move(source, target)
        restored += 1
    os.rmdir(BACKUP_DIR) if not os.listdir(BACKUP_DIR) else None
    print("  已恢复 %d 个动画" % restored)
    return 0


def regenerate(width):
    names = pipeline.list_animations()
    if not names:
        print("  找不到任何动画")
        return 1
    os.makedirs(BACKUP_DIR, exist_ok=True)
    print("  目标宽度 = %d（原生），共 %d 个动画" % (width, len(names)))
    print("  旧缓存备份到: %s" % BACKUP_DIR)
    print()

    started = time.time()
    failed = []
    for index, name in enumerate(names, 1):
        target = os.path.join(FRAME_DIR, name)
        backup = os.path.join(BACKUP_DIR, name)
        try:
            # 先把旧的挪走（而不是删）——生成失败就挪回来
            if os.path.isdir(target):
                if os.path.isdir(backup):
                    shutil.rmtree(backup)
                shutil.move(target, backup)
            pipeline.build(name, width=width, force=True)
            count, w, h = measure(target)
            elapsed = time.time() - started
            remaining = (elapsed / index) * (len(names) - index)
            print("  [%3d/%3d] %-24s %3d 帧 %dx%d   已用 %4.1f 分，预计还需 %4.1f 分"
                  % (index, len(names), name, count, w, h,
                     elapsed / 60.0, remaining / 60.0))
        except Exception as error:
            failed.append((name, str(error)))
            print("  [%3d/%3d] %-24s **失败**: %s" % (index, len(names), name, error))
            # 失败则回退这一个
            if os.path.isdir(backup) and not os.path.isdir(target):
                shutil.move(backup, target)

    print()
    print("  完成：%d 个成功，%d 个失败，用时 %.1f 分钟"
          % (len(names) - len(failed), len(failed), (time.time() - started) / 60.0))
    for name, reason in failed:
        print("     失败 %s: %s" % (name, reason))
    if not failed:
        print("  备份保留在 %s —— 不满意就跑 --rollback 回退。" % BACKUP_DIR)
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rollback", action="store_true", help="恢复成之前的缓存")
    parser.add_argument("--status", action="store_true", help="只看当前状态")
    parser.add_argument("--width", type=int, default=pipeline.TARGET_WIDTH,
                        help="目标宽度，默认取 TARGET_WIDTH（当前 %d）"
                             % pipeline.TARGET_WIDTH)
    args = parser.parse_args()

    if args.status:
        return status()
    if args.rollback:
        return rollback()
    return regenerate(args.width)


if __name__ == "__main__":
    sys.exit(main())
