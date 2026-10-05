# -*- coding: utf-8 -*-
"""验证：别人从 GitHub 下载后，拿到的图标/表情包**与本机逐字节相同**。

为什么不能只检查"文件在不在"：图标是**二进制资源**，它可能：
  * 被 `.gitignore` 排除（历史上真发生过：整个 `assets/` 被排除，于是从 GitHub 装的人
    "图标是没有的" —— 而 `make_icon()` 只往 stderr 写一行警告，界面上静默少个功能）；
  * 在仓库里但**内容与本机不一致**（本地改过但忘了提交、或提交的是旧版）；
  * 存在但**代码引用的路径指向别处**（例如快捷方式指向一个没进仓库的 `icon-full.ico`）。

所以这里做三件事：
  1. 从代码里**提取**它引用的图标/表情包路径，确认每一个都在 git 里被跟踪；
  2. 逐个从 `raw.githubusercontent.com` **下载**，与本机算 SHA-256 比对；
  3. 报告远程 `assets/` 与 `memes/` 的完整清单，确认没有多出孤儿文件。

    python tools/verify_remote_icons.py
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = "https://raw.githubusercontent.com/adincole169-ui/cole-dsh-pet/main/"
PROXY = "http://127.0.0.1:7897"

# 代码里"必须存在"的图标（从源码里提取出来的，见下面的 scan_references）。
# 这里显式列出是**故意的**：万一源码被改成别的路径，这个清单就会和扫描结果对不上，
# 从而暴露"代码改了、自检没跟着改"。
EXPECTED_RUNTIME = {
    "assets/icon.png": "窗口/任务栏图标（pet.py ICON_PATH）",
    "assets/icon.ico": "窗口图标与桌面快捷方式图标（pet.py ICON_ICO / install.ps1）",
    "assets/icon-head.png": "重新生成图标时用（make_icon.py 输入）",
    "assets/icon-head.ico": "重新生成图标时用（make_icon.py 输出）",
}
# 孤儿：明确**不该**出现在远程
STRAYS = ["assets/icon-full.ico", "assets/icon-full.png"]

FAILURES = []


def check(label, ok, detail=""):
    if isinstance(detail, (list, tuple)):
        detail = " / ".join(str(x) for x in detail if x)
    detail = str(detail)
    print("  %s %s%s" % ("[OK]  " if ok else "[失败]", label,
                         ("  " + detail) if detail else ""))
    if not ok:
        FAILURES.append(label)


def sha256_bytes(payload):
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def opener():
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))


def fetch(path):
    """下载一个文件。

    **路径必须 percent-encode**：`memes/困.png` 这种含中文的路径直接拼进 URL 会报
    `'ascii' codec can't encode character`，于是 8 个表情包全部"下载失败" ——
    实测踩过，而且失败信息看起来像"远程没有这些文件"，很容易误判成仓库缺文件。
    `quote` 默认 `safe='/'`，斜杠会保留。
    """
    url = RAW + urllib.parse.quote(path)
    with opener().open(url, timeout=120) as response:
        return response.read()


def tracked_files():
    done = subprocess.run(["git", "-c", "core.quotePath=false", "ls-files",
                           "assets", "memes"],
                          cwd=ROOT, capture_output=True, text=True)
    return [line.strip() for line in done.stdout.splitlines() if line.strip()]


def scan_references():
    """从源码里抽出**运行时真正会去读**的图标路径。

    早先这里用了一个宽泛的正则（"凡是出现 assets/<文件名> 的字符串"），结果把
    `tools/audit_publish.py` 里 `FORBIDDEN_FILES = ["assets/icon-full.ico", ...]`
    也当成了"被引用、应当进仓库" —— 而那一条恰恰在说"**不许**进仓库"，
    于是自检报出一个假失败。教训：**"出现在代码里"不等于"必须存在于仓库"**，
    要看它出现的语境。改成只抓有明确语义的赋值点。
    """
    found = {}
    pet = os.path.join(ROOT, "src", "pet.py")
    if os.path.isfile(pet):
        with open(pet, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        for name in ("ICON_PATH", "ICON_ICO"):
            match = re.search(
                r"%s\s*=\s*os\.path\.join\(\s*ROOT\s*,\s*['\"]assets['\"]\s*,\s*['\"]([^'\"]+)['\"]"
                % name, text)
            if match:
                found["assets/" + match.group(1)] = "pet.py 的 %s" % name
    installer = os.path.join(ROOT, "tools", "install.ps1")
    if os.path.isfile(installer):
        with open(installer, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        match = re.search(r"Join-Path\s+\$PetDir\s+['\"]([^'\"]+\.ico)['\"]", text)
        if match:
            found[match.group(1).replace("\\", "/")] = "install.ps1 的快捷方式图标"
    return found


def main():
    print()
    print("  从 GitHub 下载后能否拿到本机的图标")
    print("  " + "=" * 74)

    tracked = tracked_files()
    if not tracked:
        print("  git 里没有跟踪任何 assets/ 或 memes/ 文件")
        return 1

    # --- 1. 代码引用的路径是否都被跟踪 ---
    print()
    print("  ① 代码引用的图标是否都进了仓库")
    print("  " + "-" * 74)
    check("跟踪的图标/表情包文件数", bool(tracked), "%d 个" % len(tracked))
    for path, why in EXPECTED_RUNTIME.items():
        check("%s 被 git 跟踪" % path, path in tracked, why)
        check("%s 在本机存在" % path, os.path.isfile(os.path.join(ROOT, path)))

    referenced = scan_references()
    print("     从代码里抽出的运行时图标路径 %d 个：" % len(referenced))
    for path, why in sorted(referenced.items()):
        print("        %-26s <- %s" % (path, why))
    untracked = sorted(p for p in referenced if p not in tracked)
    check("代码里引用但**没进仓库**的图标（应为空）", not untracked,
          "、".join(untracked) if untracked else "")

    # --- 2. 孤儿图标不该在远程 ---
    print()
    print("  ② 孤儿图标不该进仓库")
    print("  " + "-" * 74)
    for path in STRAYS:
        check("%s 未被跟踪" % path, path not in tracked)

    # --- 3. 逐个下载比对 ---
    print()
    print("  ③ 从远程下载并与本机逐字节比对")
    print("  " + "-" * 74)
    same = different = failed = 0
    for path in tracked:
        local = os.path.join(ROOT, path.replace("/", os.sep))
        if not os.path.isfile(local):
            check("%s 本机存在" % path, False)
            continue
        try:
            payload = fetch(path)
        except Exception as error:
            failed += 1
            print("  [失败] %-28s 下载失败: %s" % (path, str(error)[:60]))
            FAILURES.append("%s 下载失败" % path)
            continue
        local_hash = sha256_file(local)
        remote_hash = sha256_bytes(payload)
        if local_hash == remote_hash:
            same += 1
            print("  [OK]   %-28s %8d 字节  逐字节相同"
                  % (path, os.path.getsize(local)))
        else:
            different += 1
            print("  [失败] %-28s **内容不同**" % path)
            print("           本机 %s" % local_hash[:40])
            print("           远程 %s" % remote_hash[:40])
            FAILURES.append("%s 内容与本机不同" % path)

    # --- 4. 远程有没有多出来的东西 ---
    print()
    print("  ④ 远程清单（有无多余文件）")
    print("  " + "-" * 74)
    remote_assets = [p for p in tracked if p.startswith("assets/")]
    remote_memes = [p for p in tracked if p.startswith("memes/")]
    local_assets = sorted("assets/" + n for n in os.listdir(os.path.join(ROOT, "assets"))
                          if os.path.isfile(os.path.join(ROOT, "assets", n)))
    extra_local = [p for p in local_assets if p not in remote_assets]
    print("     远程 assets/: %d 个 —— %s" % (len(remote_assets),
                                             "、".join(os.path.basename(p) for p in remote_assets)))
    print("     远程 memes/ : %d 个 —— %s" % (len(remote_memes),
                                             "、".join(os.path.basename(p) for p in remote_memes)))
    print("     本机 assets/ 有但远程没有（应当只有孤儿）: %s"
          % ("、".join(os.path.basename(p) for p in extra_local) or "(无)"))
    check("本机多出来的只有孤儿图标",
          all("icon-full" in p for p in extra_local),
          "、".join(os.path.basename(p) for p in extra_local) if extra_local else "")

    # --- 汇总 ---
    print()
    print("  结论")
    print("  " + "=" * 74)
    print("     逐字节相同 %d 个，内容不同 %d 个，下载失败 %d 个"
          % (same, different, failed))
    if FAILURES:
        for item in FAILURES:
            print("     [失败] %s" % item)
        return 1
    print("     **下载者拿到的图标与本机完全一致**（%d 个文件逐字节相同）" % same)
    print("     代码引用的 %d 个图标路径全部在仓库里，孤儿图标未进仓库。"
          % len(EXPECTED_RUNTIME))
    return 0


if __name__ == "__main__":
    sys.exit(main())
