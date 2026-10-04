# -*- coding: utf-8 -*-
"""检查 `.ps1` 文件：BOM 是否正确、能否被 PowerShell 解析、有没有反引号。

为什么需要它：Windows PowerShell 5.1 会把**无 BOM** 的 `.ps1` 按 ANSI 解码，
中文一多就字符串断裂，报出的语法错误**指向无关的行**（例如 `Unexpected token '}'`），
很难联想到编码。而编辑工具每次保存都会**去掉 BOM**。所以改完 `.ps1` 必须查一遍。

    python tools/check_ps1.py tools/install.ps1 tools/uninstall.ps1 tools/build_package.ps1
    python tools/check_ps1.py            # 不带参数则自动检查 tools 下所有 .ps1

退出码：0 全部通过；1 有问题。**可以直接放进任何提交前的检查里。**
"""

import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BOM = b"\xef\xbb\xbf"


def check_bom(path):
    with open(path, "rb") as handle:
        head = handle.read(3)
    return head == BOM


def fix_bom(path):
    """补上 BOM（以 UTF-8 读入，再以带 BOM 的 UTF-8 写出）。"""
    with open(path, "rb") as handle:
        raw = handle.read()
    if raw.startswith(BOM):
        return False
    text = raw.decode("utf-8")
    with open(path, "wb") as handle:
        handle.write(BOM + text.encode("utf-8"))
    return True


def find_backticks(path):
    """返回带反引号的行号。注释里的反引号也会把行尾换行转义掉，所以一律算问题。"""
    hits = []
    with open(path, encoding="utf-8-sig") as handle:
        for number, line in enumerate(handle, 1):
            if "`" in line:
                hits.append(number)
    return hits


def parse_with_powershell(path):
    """交给 Windows PowerShell 真正解析一次，返回错误列表。"""
    script = (
        "$err = $null; "
        "[System.Management.Automation.Language.Parser]::ParseFile('%s', [ref]$null, [ref]$err) > $null; "
        "if ($err) { $err | ForEach-Object { \"$($_.Extent.StartLineNumber):$($_.Message)\" } }"
        % path.replace("'", "''")
    )
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=60)
    except Exception as error:
        return ["无法调用 PowerShell: %s" % error]
    output = (done.stdout or "").strip()
    return [line for line in output.splitlines() if line.strip()] if output else []


def main(argv):
    targets = argv[1:]
    if not targets:
        targets = sorted(glob.glob(os.path.join(HERE, "*.ps1")))
    if not targets:
        print("  没有找到 .ps1 文件")
        return 0

    failed = 0
    for target in targets:
        path = target if os.path.isabs(target) else os.path.join(ROOT, target)
        if not os.path.exists(path):
            path = target
        name = os.path.basename(path)
        if not os.path.exists(path):
            print("  %-22s 文件不存在" % name)
            failed += 1
            continue

        problems = []

        # 1. BOM
        had = check_bom(path)
        if not had:
            fixed = fix_bom(path)
            problems.append("缺少 UTF-8 BOM（PowerShell 5.1 会按 ANSI 读，中文会断裂）"
                            + ("——已自动补上" if fixed else ""))
            had = True

        # 2. 反引号
        backticks = find_backticks(path)
        if backticks:
            problems.append("第 %s 行有反引号（会把行尾换行转义掉）"
                            % ", ".join(str(n) for n in backticks))

        # 3. 真正解析
        errors = parse_with_powershell(path)
        if errors:
            problems.append("解析失败: %s" % " | ".join(errors[:3]))

        if problems:
            failed += 1
            print("  [问题] %s" % name)
            for item in problems:
                print("         %s" % item)
        else:
            print("  [OK]   %s  (BOM=%s, 无反引号, 解析通过)"
                  % (name, "有" if had else "无"))

    print()
    print("  通过 %d / %d" % (len(targets) - failed, len(targets)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
