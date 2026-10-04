# -*- coding: utf-8 -*-
"""一条命令校验语法：Python / PowerShell / JavaScript 都能查。

配合工作区规则「先写成文件，再执行」使用——**写完之后先过这一关**，
再拿去执行，就不会在"引号被吃掉 / 文件缺 BOM"这类问题上反复浪费轮次。

    python tools/check_syntax.py                      # 查全项目
    python tools/check_syntax.py tools/install.ps1    # 查指定文件
    python tools/check_syntax.py --staged             # 只查最近 5 分钟改动的（写完后自查用）

各类文件的检查内容：
  .py   ast.parse（语法）
  .ps1  UTF-8 BOM + 无反引号 + 交给 PowerShell 真正解析（见 check_ps1.py）
  .js   node --check（工作区里的插件与测试都是 ESM）
  .json  能否解析（config.jsonc 是 JSONC，单独按去注释处理）

退出码：0 全部通过；1 有问题。
"""

import argparse
import ast
import glob
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SKIP_DIRS = {"frames", "webm", "logs", "node_modules", ".venv", ".git", "__pycache__",
             "memes", "assets", "plugins", "pet"}
BOM = b"\xef\xbb\xbf"


def collect(explicit, staged):
    if explicit:
        return [os.path.abspath(p) for p in explicit]
    found = []
    cutoff = time.time() - 300 if staged else None
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if not name.endswith((".py", ".ps1", ".js", ".mjs", ".json", ".jsonc")):
                continue
            path = os.path.join(folder, name)
            if staged and os.path.getmtime(path) < cutoff:
                continue
            found.append(path)
    return sorted(found)


def check_python(path):
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    try:
        ast.parse(source, path)
    except SyntaxError as error:
        return ["SyntaxError 第 %s 行: %s" % (error.lineno, error.msg)]
    return []


def check_powershell(path):
    problems = []
    with open(path, "rb") as handle:
        raw = handle.read()
    if not raw.startswith(BOM):
        # 直接补上：这时它才是能用的脚本
        text = raw.decode("utf-8")
        with open(path, "wb") as handle:
            handle.write(BOM + text.encode("utf-8"))
        problems.append("缺少 UTF-8 BOM —— 已自动补上（补了才算通过）")
    with open(path, encoding="utf-8-sig") as handle:
        for number, line in enumerate(handle, 1):
            if "`" in line:
                problems.append("第 %d 行有反引号（会转义行尾换行）" % number)
    script = (
        "$err = $null; "
        "[System.Management.Automation.Language.Parser]::ParseFile('%s', [ref]$null, [ref]$err) > $null; "
        "if ($err) { $err | ForEach-Object { \"$($_.Extent.StartLineNumber):$($_.Message)\" } }"
        % path.replace("'", "''")
    )
    try:
        done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                              capture_output=True, text=True, timeout=60)
        output = (done.stdout or "").strip()
        if output:
            problems.append("PowerShell 解析失败: %s" % " | ".join(output.splitlines()[:2]))
    except Exception as error:
        problems.append("无法调用 PowerShell: %s" % error)
    return problems


def check_javascript(path):
    try:
        done = subprocess.run(["node", "--check", path], capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        return []          # 没装 node 就跳过，不当失败
    except Exception as error:
        return ["无法调用 node: %s" % error]
    if done.returncode != 0:
        line = (done.stderr or "").strip().splitlines()
        return ["node --check 失败: %s" % (line[-1] if line else "未知错误")]
    return []


def strip_jsonc(text):
    """去掉 JSONC 的注释，但要**忽略字符串内部**的 `//` 与 `/* */`。

    早先用两条正则粗暴删除，结果把字符串里的 `//`（例如某个路径或 URL）也删了，
    于是明明合法的文件报出 "Expecting value"（实测踩过）。用状态机才靠得住。
    """
    out = []
    index = 0
    length = len(text)
    in_string = False
    escaped = False
    while index < length:
        char = text[index]
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "/":
            while index < length and text[index] != "\n":
                index += 1
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "*":
            index += 2
            while index + 1 < length and not (text[index] == "*" and text[index + 1] == "/"):
                index += 1
            index += 2
            continue
        out.append(char)
        index += 1
    # 顺手去掉注释留下的空行尾逗号问题：JSON 允许尾逗号吗？不允许，所以再清一次
    cleaned = "".join(out)
    cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)
    return cleaned


def check_json(path):
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    if path.endswith(".jsonc"):
        text = strip_jsonc(text)
    try:
        json.loads(text)
    except Exception as error:
        return ["JSON 解析失败: %s" % error]
    return []


CHECKS = {".py": check_python, ".ps1": check_powershell, ".js": check_javascript,
          ".mjs": check_javascript, ".json": check_json, ".jsonc": check_json}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="*")
    parser.add_argument("--staged", action="store_true",
                        help="只查最近 5 分钟内改动过的文件（写完立即自查用）")
    parser.add_argument("--quiet", action="store_true", help="只打印有问题的")
    args = parser.parse_args()

    targets = collect(args.files, args.staged)
    if not targets:
        print("  没有需要检查的文件")
        return 0

    failed = 0
    for path in targets:
        extension = os.path.splitext(path)[1].lower()
        checker = CHECKS.get(extension)
        if checker is None:
            continue
        try:
            problems = checker(path)
        except Exception as error:
            problems = ["检查时出错: %s" % error]
        relative = os.path.relpath(path, ROOT)
        if problems:
            failed += 1
            print("  [问题] %s" % relative)
            for item in problems:
                print("         %s" % item)
        elif not args.quiet:
            print("  [OK]   %s" % relative)

    print()
    print("  检查 %d 个文件，%d 个有问题" % (len(targets), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
