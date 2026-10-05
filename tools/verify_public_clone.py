# -*- coding: utf-8 -*-
"""「朋友视角」端到端验证：匿名克隆仓库，检查拿到什么、能不能直接跑。

为什么必须做这一关：本地一切正常**不代表**别人 clone 下来也能跑。真正的风险是
"某样东西只存在于我这台机器上"——比如帧缓存没进仓库、某个依赖只在本地有、
某个文件被 .gitignore 意外排除。这次改动又把"准备步骤"从"跑一次解码"变成了
"什么都不用做"，所以更要确认这条路真的通。

做法：
  1. 匿名 clone 到仓库外的一个临时目录（不带任何凭据、不看本地工作区）
  2. 逐项核对应该有的东西（webm / 图标 / 表情包 / 元数据 / 源码）
  3. 确认**不该有**的东西确实不在（frames / logs / 私人文件）
  4. 真的把它跑起来（换个端口，不影响正在运行的那只）
  5. 检查它的启动日志里有没有报错

    python tools/verify_public_clone.py
"""

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLONE = r"E:\dsh\_fresh-clone-test"
REPO = "https://github.com/adincole169-ui/cole-dsh-pet.git"
RAW = "https://raw.githubusercontent.com/adincole169-ui/cole-dsh-pet/main/"
PROXY = "http://127.0.0.1:7897"

# 必须存在（陌生人 clone 下来就该有）
REQUIRED = [
    ("main.py", "启动入口"),
    ("requirements.txt", "运行依赖清单"),
    ("config.jsonc", "配置"),
    ("webm-meta.json", "帧数元数据（流式模式算循环长度要用）"),
    ("src/pet.py", "窗口与绘制"),
    ("src/frames.py", "帧来源"),
    ("src/stream_frames.py", "流式解码"),
    ("assets/icon.ico", "图标（缺了窗口与任务栏就没图标，且不报错）"),
    ("plugins/dsh-pet-bridge/package.json", "DSH 联动插件"),
    ("README.md", "说明"),
    ("ASSETS.md", "素材来源与许可"),
    ("LICENSE", "许可"),
]
# 绝不能有
FORBIDDEN = ["frames", "logs", "dist", ".venv", "config.jsonc.bak-高清演示"]

FAILURES = []


def force_rmtree(path):
    """删目录，能应付 Windows 上 git 对象文件的只读位。

    踩过：`shutil.rmtree(path, ignore_errors=True)` 遇到只读文件会**静默失败**，
    目录还留着，下一次 `git clone` 直接报
    `destination path already exists and is not an empty directory` ——
    而错误信息完全指向别处（看起来像 clone 的问题，其实是上次没删干净）。
    标准做法是在 onerror 回调里先清掉只读属性再删。
    """
    import stat
    if not os.path.isdir(path):
        return True

    def onerror(function, target, _exc_info):
        try:
            os.chmod(target, stat.S_IWRITE)
            function(target)
        except Exception:
            pass

    shutil.rmtree(path, onerror=onerror)
    return not os.path.isdir(path)


def check(label, ok, detail=""):
    # detail 可能是 list（比如从输出里筛出来的行），统一转成字符串
    if isinstance(detail, (list, tuple)):
        detail = " / ".join(str(item) for item in detail if item)
    detail = str(detail)
    print("  %s %s%s" % ("[OK]  " if ok else "[失败]", label,
                         ("  " + detail) if detail else ""))
    if not ok:
        FAILURES.append(label)


def count(directory, suffix):
    if not os.path.isdir(directory):
        return 0
    return len([n for n in os.listdir(directory) if n.endswith(suffix)])


def main():
    print()
    print("  「朋友视角」端到端验证")
    print("  " + "=" * 76)

    # --- 0. 匿名确认仓库已公开 ---
    #
    # **不要用 GitHub API**：匿名限额只有 60 次/小时，连续跑几次就 403，
    # 于是"仓库是否公开"这一项会假失败（实测踩过）。改用两件朋友真正会做的事：
    #   * `git ls-remote` **带空白凭据助手**（`-c credential.helper=`），
    #     私有仓库会要认证并失败，公开仓库直接成功；
    #   * 拉一个文件，看 HTTP 状态。
    print()
    print("  ① 匿名访问（不带任何凭据）")
    print("  " + "-" * 76)
    env = dict(os.environ, HTTP_PROXY=PROXY, HTTPS_PROXY=PROXY)
    done = subprocess.run(["git", "-c", "credential.helper=", "ls-remote",
                           "--heads", REPO],
                          capture_output=True, text=True, env=env, timeout=120)
    check("匿名 git ls-remote 成功（私有仓库会要认证）",
          done.returncode == 0 and "refs/heads/main" in (done.stdout or ""),
          (done.stdout or done.stderr or "").strip()[:120])
    try:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
        with opener.open(RAW + "README.md", timeout=60) as response:
            payload = response.read()
        check("匿名拉取 raw 文件成功", response.status == 200 and len(payload) > 1000,
              "README.md %d 字节" % len(payload))
    except Exception as error:
        check("匿名拉取 raw 文件成功", False, str(error))

    # --- 1. 全新克隆 ---
    print()
    print("  ② 全新匿名克隆")
    print("  " + "-" * 76)
    if not force_rmtree(CLONE):
        check("清理上次的克隆目录", False, "删不掉，请手动删 %s" % CLONE)
        return 1
    started = time.time()
    done = subprocess.run(
        ["git", "-c", "credential.helper=", "clone", "--depth", "1",
         REPO, CLONE],
        capture_output=True, text=True, env=env, cwd=r"E:\dsh")
    if done.returncode != 0:
        check("git clone", False, (done.stderr or "").strip()[:200])
        return 1
    check("git clone（--depth 1）", True, "用时 %.1f 秒" % (time.time() - started))

    # --- 2. 该有的东西在不在 ---
    print()
    print("  ③ 该有的东西")
    print("  " + "-" * 76)
    for name, why in REQUIRED:
        path = os.path.join(CLONE, name.replace("/", os.sep))
        check(name, os.path.isfile(path), why if not os.path.isfile(path) else "")
    webm = count(os.path.join(CLONE, "webm"), ".webm")
    icons = count(os.path.join(CLONE, "assets"), "")
    memes = count(os.path.join(CLONE, "memes"), ".png")
    check("webm 动画数", webm == 106, "实际 %d" % webm)
    check("assets 图标数", icons >= 4, "实际 %d" % icons)
    check("memes 表情包数", memes >= 8, "实际 %d" % memes)

    # --- 3. 不该有的东西 ---
    print()
    print("  ④ 不该有的东西")
    print("  " + "-" * 76)
    for name in FORBIDDEN:
        path = os.path.join(CLONE, name)
        check("没有 %s" % name, not os.path.exists(path))

    # --- 4. 能不能直接跑（无需任何准备步骤）---
    print()
    print("  ⑤ 直接跑（不跑任何解码/准备命令）")
    print("  " + "-" * 76)
    python = sys.executable
    done = subprocess.run([python, "-X", "utf8", os.path.join(CLONE, "main.py"),
                           "--status"],
                          capture_output=True, text=True, cwd=CLONE, timeout=180)
    output = done.stdout + done.stderr
    ok = done.returncode == 0
    source_line = ""
    for line in output.splitlines():
        if "帧来源" in line:
            source_line = line.strip()
    check("--status 能跑", ok, source_line)
    check("识别为 stream 模式", "stream" in source_line, source_line)
    check("看到 106 个 webm",
          "可用 webm: 106" in output,
          [l.strip() for l in output.splitlines() if "webm" in l][:1])

    # **必须带 `--force`**：单一实例守卫在素材自检**之前**（这是有意的，见 main.py），
    # 所以本机另有一只桌宠在跑时，不带 --force 的 `--check-assets` 会走"已有一只在运行"
    # 那条早退路径并返回 0 —— 断言就变成了空断言（实测踩过：输出是
    # "已有一只在运行，本次不启动"，却被判为通过）。
    done = subprocess.run([python, "-X", "utf8", os.path.join(CLONE, "main.py"),
                           "--force", "--check-assets"],
                          capture_output=True, text=True, cwd=CLONE, timeout=180)
    output = (done.stdout or "") + (done.stderr or "")
    check("--check-assets 真的检查了素材",
          done.returncode == 0 and "素材就绪" in output,
          output.strip().splitlines()[-1][:120] if output.strip() else "无输出")

    # 真的启动一只，播一个动画，10 秒后自动退出
    print()
    print("     启动桌宠本体（--anim + --hold，10 秒后自动退出）...")
    process = subprocess.Popen(
        [python, "-X", "utf8", os.path.join(CLONE, "main.py"),
         "--force", "--anim", "待机呼吸休闲", "--hold", "10"],
        cwd=CLONE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        out, err = process.communicate(timeout=120)
    except subprocess.TimeoutExpired:
        process.kill()
        out, err = process.communicate()
    combined = (out or "") + (err or "")
    fatal = [line for line in combined.splitlines()
             if any(key in line for key in ("Traceback", "准备失败", "取不到帧",
                                            "起流失败", "流式失败", "Error"))]
    check("桌宠能启动并播放", process.returncode == 0 and not fatal,
          "退出码 %s" % process.returncode)
    if fatal:
        for line in fatal[:5]:
            print("        " + line[:130])
    # 端口被占是预期的（本机还有一只在跑），不算失败
    port_note = [line for line in combined.splitlines() if "端口" in line]
    if port_note:
        print("        （%s —— 预期，本机另有一只占着 8899）" % port_note[0].strip()[:60])

    # --- 5. 克隆下来没有偷偷生成帧缓存 ---
    print()
    print("  ⑥ 跑完之后有没有偷偷写盘")
    print("  " + "-" * 76)
    frames_path = os.path.join(CLONE, "frames")
    check("frames/ 仍然不存在（流式模式零磁盘占用）",
          not os.path.isdir(frames_path))

    # --- 汇总 ---
    print()
    print("  结论")
    print("  " + "=" * 76)
    if FAILURES:
        for item in FAILURES:
            print("     [失败] %s" % item)
        print()
        print("  共 %d 项失败" % len(FAILURES))
        return 1
    print("     [OK] 匿名可克隆、素材齐全、无需任何准备步骤即可运行、零磁盘占用")
    print()
    print("  克隆目录（验证完可删）: %s" % CLONE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
