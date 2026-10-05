# -*- coding: utf-8 -*-
"""真实测一次：桌宠运行时，`git checkout` 能不能覆盖正在用的 webm。

为什么非要做真实测试：`probe_webm_locked.py` 已经证明"替换（unlink+rename）会被拒绝"，
但那是我用 `os.replace` **模拟** git 的行为。这一轮已经因为"推断代替实测"错过好几次，
所以这里直接用 **git 自己** 走一遍。

安全性：全程有备份与哈希校验。
  1. 先把目标文件备份到仓库外，并记下 SHA-256；
  2. 改动 1 个字节，让 git 认为它"被修改过"（这样 `git checkout` 才会真去覆盖）；
  3. 跑 `git checkout -- <文件>`，记录它成功还是失败；
  4. **无论成败，最后都用备份还原，并核对哈希与原始一致**。

    python tools/probe_git_pull_while_running.py
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BACKUP = r"E:\dsh\_webm_restore_backup.bin"


def api(path, timeout=4):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8899" + path, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    print()
    print("  真实测试：桌宠运行时 git 能否覆盖正在用的 webm")
    print("  " + "=" * 74)

    debug = api("/debug")
    if debug is None:
        print("  桌宠没在跑 —— 这个测试需要它持有文件。先启动它。")
        return 1
    playing = debug.get("playing")
    if not playing:
        print("  当前没有在播的动画，无法确定哪个文件被持有")
        return 1

    relative = "webm/%s.webm" % playing
    target = os.path.join(ROOT, "webm", playing + ".webm")
    if not os.path.isfile(target):
        print("  找不到 %s" % target)
        return 1

    original_hash = sha256(target)
    original_size = os.path.getsize(target)
    print("  当前在播: %s" % playing)
    print("  目标文件: %s（%d 字节）" % (relative, original_size))
    print("  原始 SHA-256: %s" % original_hash[:32])

    # --- 备份 ---
    shutil.copy2(target, BACKUP)
    print("  已备份到 %s" % BACKUP)

    try:
        # --- 改 1 个字节，让 git 认为文件被改过 ---
        with open(target, "r+b") as handle:
            handle.seek(0)
            first = handle.read(1)
            handle.seek(0)
            handle.write(bytes([first[0] ^ 0x01]))
        print("  已改动 1 个字节（git 现在会认为它被修改）")

        # --- 让 git 覆盖它 ---
        done = subprocess.run(["git", "checkout", "--", relative],
                              cwd=ROOT, capture_output=True, text=True)
        print()
        print("  git checkout 结果")
        print("  " + "-" * 74)
        print("     退出码: %d" % done.returncode)
        if done.stdout.strip():
            print("     stdout: %s" % done.stdout.strip()[:200])
        if done.stderr.strip():
            print("     stderr: %s" % done.stderr.strip()[:300])

        failed = done.returncode != 0
        if failed:
            print()
            print("     **git 覆盖失败了** —— 与推断一致：")
            print("     webm 被 ffmpeg 以『不允许删除共享』的方式打开，git 无法 unlink。")
        else:
            current = sha256(target) if os.path.isfile(target) else "(文件不见了)"
            restored = current == original_hash
            print()
            print("     git 覆盖成功了；内容是否已还原为原始: %s"
                  % ("是" if restored else "**否**"))
    finally:
        # --- 无论成败都还原 ---
        shutil.copy2(BACKUP, target)
        os.remove(BACKUP)
        final_hash = sha256(target)
        final_size = os.path.getsize(target)

    print()
    print("  还原校验")
    print("  " + "=" * 74)
    print("     大小 %d -> %d" % (original_size, final_size))
    print("     哈希 %s" % ("一致 ✓" if final_hash == original_hash
                            else "**不一致** %s" % final_hash[:32]))
    # git 的索引也要回到干净状态
    status = subprocess.run(["git", "status", "--porcelain", "--", relative],
                            cwd=ROOT, capture_output=True, text=True).stdout.strip()
    print("     git status: %s" % (status or "干净 ✓"))
    ok = (final_hash == original_hash and not status)
    print()
    print("  结论: %s" % ("素材完好、仓库干净" if ok else "**需要人工检查**"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
