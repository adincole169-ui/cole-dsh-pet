# -*- coding: utf-8 -*-
"""端到端验证"新使用者"的体验：全新检出 -> 一条命令 -> 能跑。

做法：把**仓库里跟踪的文件**导出到一个全新目录（等价于 git clone 的结果，
不含 frames/ 等被忽略的内容），然后在那里跑 `tools/setup_assets.py`，
最后用 `main.py --check-assets` 与 `--status` 确认可用。

这是本目标的核心承诺（"clone → 一条命令 → 约 10 分钟跑起来"）的唯一硬证据。

    python tools/verify_fresh_clone.py            # 完整跑（约 10 分钟 + 2.6 GB）
    python tools/verify_fresh_clone.py --partial  # 只解 3 个动画（快）
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# 默认在系统临时目录下建"模拟 clone"，也可以命令行指定第二个参数
CLONE = os.path.join(tempfile.gettempdir(), "dsh-pet-freshclone")
PYTHON = sys.executable


def export_tracked(target):
    """用 git 列出跟踪文件并复制过去（模拟 clone）。"""
    done = subprocess.run(["git", "-c", "core.quotePath=false", "ls-files"],
                          cwd=ROOT, capture_output=True, text=True)
    files = [line for line in (done.stdout or "").splitlines() if line.strip()]
    if os.path.isdir(target):
        shutil.rmtree(target)
    os.makedirs(target)
    copied = 0
    for relative in files:
        source = os.path.join(ROOT, relative)
        if not os.path.isfile(source):
            continue
        destination = os.path.join(target, relative)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copy2(source, destination)
        copied += 1
    return copied


def run(args, cwd, timeout=7200):
    done = subprocess.run([PYTHON, "-X", "utf8"] + args, cwd=cwd,
                          capture_output=True, text=True, timeout=timeout)
    return done.returncode, (done.stdout or ""), (done.stderr or "")


def main():
    partial = "--partial" in sys.argv

    print()
    print("  端到端验证：模拟全新 clone")
    print("  " + "=" * 66)

    print()
    print("  [1/4] 导出仓库跟踪的文件到 %s" % CLONE)
    copied = export_tracked(CLONE)
    print("        复制 %d 个文件" % copied)
    for name in ("frames", "assets", "memes", "logs"):
        exists = os.path.isdir(os.path.join(CLONE, name))
        print("        %-8s 存在: %s %s" % (name, exists, "" if not exists else "**不该有**"))
    webm = os.path.join(CLONE, "webm")
    webm_count = len([f for f in os.listdir(webm)]) if os.path.isdir(webm) else 0
    print("        webm     %d 个（应当 106）" % webm_count)

    print()
    print("  [2/4] setup_assets.py --check")
    code, out, err = run(["tools/setup_assets.py", "--check"], CLONE, timeout=300)
    for line in out.splitlines():
        if line.strip():
            print("        %s" % line)
    if code != 0:
        print("        **退出码 %d**" % code)
        if err.strip():
            print("        stderr: %s" % err.strip()[:300])
        return 1

    print()
    print("  [3/4] %s" % ("部分解码（3 个动画）" if partial else "完整解码（106 个动画）"))
    if partial:
        # 只解 3 个，直接调 asset_pipeline
        script = (
            "import sys; sys.path.insert(0, 'tools');"
            "import asset_pipeline as p;"
            "names = p.list_animations()[:3];"
            "print('解码', names);"
            "res = p.build_all_parallel(workers=3, names=names,"
            " progress=lambda i,t,n,f: print('  [%d/%d] %s %d 帧' % (i,t,n[:16],f)));"
            "print('结果:', [(n, c) for n, c, e in res])"
        )
        started = time.time()
        code, out, err = run(["-c", script], CLONE, timeout=3600)
        elapsed = time.time() - started
        for line in out.splitlines():
            if line.strip():
                print("        %s" % line)
        if code != 0:
            print("        **失败（退出码 %d）**" % code)
            print("        stderr: %s" % (err or "")[:500])
            return 1
        print("        用时 %.1f 分钟（3 个动画）" % (elapsed / 60.0))
        print("        推算 106 个约 %.1f 分钟" % (elapsed / 60.0 * 106 / 3))
    else:
        started = time.time()
        code, out, err = run(["tools/setup_assets.py"], CLONE, timeout=7200)
        elapsed = time.time() - started
        lines = [line for line in out.splitlines() if line.strip()]
        # 只打印尾部与进度摘要，避免刷屏
        for line in lines[:6]:
            print("        %s" % line)
        print("        ...")
        for line in lines[-8:]:
            print("        %s" % line)
        if code != 0:
            print("        **失败（退出码 %d）**" % code)
            print("        stderr: %s" % (err or "")[:500])
            return 1
        print("        总用时 %.1f 分钟" % (elapsed / 60.0))

    print()
    print("  [4/4] 在新目录里启动检查")
    code, out, err = run(["main.py", "--check-assets"], CLONE, timeout=300)
    for line in out.splitlines():
        if line.strip():
            print("        %s" % line)
    ok_check = code == 0

    code, out, err = run(["main.py", "--status"], CLONE, timeout=300)
    tail = [line for line in out.splitlines() if "素材" in line or "种类" in line]
    for line in tail:
        print("        %s" % line)
    ok_status = code == 0

    print()
    print("  结论")
    print("  " + "=" * 66)
    if ok_check and ok_status:
        print("     全新 clone -> setup_assets -> 可用：**整条路径走通**")
        print("     使用者不需要手动装 ffmpeg（脚本会自动发现），也不需要手动取素材。")
    else:
        print("     有用例失败，见上面的输出。")
    return 0 if (ok_check and ok_status) else 1


if __name__ == "__main__":
    sys.exit(main())
