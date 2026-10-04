# -*- coding: utf-8 -*-
"""重新生成更新补丁 zip，并安全替换旧文件。

为什么要单独写：直接删旧的会撞上 `PermissionError: [WinError 32] 另一个程序正在使用
此文件`（实测被 SearchIndexer / 杀软扫大文件时会这样）。

做法：
  1. 先把新 zip 生成到**另一个文件名**（不碰被锁的旧文件）；
  2. 再重试删掉旧文件并改名回来（给几分钟窗口）；
  3. 万一一直锁着，就**保留新文件**并明确告诉用户改名，而不是把旧的删掉。

    python tools/rebuild_update_zip.py
"""

import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STAGE = os.path.join(ROOT, "dist", "dsh-pet-update")
TARGET = os.path.join(ROOT, "dist", "dsh-pet-update.zip")
TEMP = os.path.join(ROOT, "dist", "dsh-pet-update.new.zip")
RETRY_SECONDS = 180
RETRY_INTERVAL = 10


def build_temp():
    print("  == 1. 生成新 zip 到临时名 ==")
    print("     %s" % TEMP)
    result = subprocess.run(
        [sys.executable, "-X", "utf8", os.path.join(HERE, "make_zip.py"), STAGE, TEMP],
        capture_output=True, text=True)
    for line in (result.stdout or "").splitlines()[-4:]:
        print("     %s" % line)
    if result.returncode != 0:
        print("     生成失败: %s" % (result.stderr or "")[-400:])
        return False
    return os.path.exists(TEMP)


def replace_target():
    print()
    print("  == 2. 替换旧 zip（最多等 %d 秒）==" % RETRY_SECONDS)
    started = time.time()
    attempt = 0
    while time.time() - started < RETRY_SECONDS:
        attempt += 1
        try:
            if os.path.exists(TARGET):
                os.remove(TARGET)
            shutil.move(TEMP, TARGET)
            print("     第 %d 次尝试成功（等待了 %.0f 秒）"
                  % (attempt, time.time() - started))
            return True
        except PermissionError as error:
            print("     第 %d 次失败（仍被占用），%.0f 秒后重试..."
                  % (attempt, RETRY_INTERVAL))
            time.sleep(RETRY_INTERVAL)
        except Exception as error:
            print("     第 %d 次出现意外错误: %s" % (attempt, error))
            time.sleep(RETRY_INTERVAL)
    return False


def main():
    if not os.path.isdir(STAGE):
        print("  找不到补丁目录 %s" % STAGE)
        return 1
    if not build_temp():
        return 1

    if replace_target():
        print()
        print("  完成: %s  (%.2f GB)"
              % (TARGET, os.path.getsize(TARGET) / 1073741824.0))
        return 0

    print()
    print("  **旧 zip 一直被别人占用，没能替换。**")
    print("  新 zip 已留在: %s" % TEMP)
    print("  内容与目录 %s 一致。" % STAGE)
    print("  你可以稍后手动改名（先关掉可能占用它的程序）：")
    print("     Remove-Item '%s'" % TARGET)
    print("     Rename-Item '%s' 'dsh-pet-update.zip'" % TEMP)
    return 1


if __name__ == "__main__":
    sys.exit(main())
