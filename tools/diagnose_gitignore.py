# -*- coding: utf-8 -*-
"""诊断 .gitignore 为什么没生效。

现象：`git add -A` 之后暂存区里有 25543 个素材文件（frames/、webm/、assets/、memes/），
说明 .gitignore 里的规则没有起作用。

这个脚本把 git 自己看到的东西打出来，而不是靠猜：
  1. .gitignore 文件本身的内容与编码（前几字节是否 BOM）；
  2. `git check-ignore -v` 对几个关键路径的判定（它会说明是**哪条规则**匹配的）；
  3. `git status --porcelain` 里这些目录是否被列成未跟踪。

    python tools/diagnose_gitignore.py
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git(args):
    done = subprocess.run(["git"] + args, cwd=ROOT, capture_output=True)
    return done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")


def main():
    path = os.path.join(ROOT, ".gitignore")
    print("  == .gitignore 文件本身 ==")
    if not os.path.exists(path):
        print("     **文件不存在**")
        return 1
    with open(path, "rb") as handle:
        raw = handle.read()
    print("     大小: %d 字节" % len(raw))
    print("     前 4 字节: %s" % " ".join("%02X" % byte for byte in raw[:4]))
    if raw.startswith(b"\xef\xbb\xbf"):
        print("     **有 UTF-8 BOM** —— git 会把第一条规则读成 `\\xef\\xbb\\xbf# ...`，")
        print("       通常不至于让整个文件失效，但仍是隐患。")
    # 只看规则行（跳过注释与空行）
    rules = [line.strip() for line in raw.decode("utf-8-sig").splitlines()
             if line.strip() and not line.strip().startswith("#")]
    print("     规则条数: %d" % len(rules))
    print("     前 8 条: %s" % ", ".join(rules[:8]))

    print()
    print("  == git 版本与仓库根 ==")
    for args in (["--version"], ["rev-parse", "--show-toplevel"],
                 ["config", "core.excludesfile"]):
        code, out, err = git(args)
        value = (out or err).strip() or "(空)"
        print("     git %-28s -> %s" % (" ".join(args), value))

    print()
    print("  == git check-ignore 的判定 ==")
    targets = ["frames", "frames/三球抛接/0001.png", "webm/东张西望.webm",
               "assets/icon.ico", "memes/开心.png", "logs", "dist"]
    for target in targets:
        code, out, err = git(["check-ignore", "-v", target])
        if code == 0:
            print("     [被忽略] %-32s 规则: %s" % (target, out.strip()))
        elif code == 1:
            print("     [**未忽略**] %-28s （没有任何规则匹配！）" % target)
        else:
            print("     [错误 %d] %-28s %s" % (code, target, err.strip()[:90]))

    print()
    print("  == git status 里这些目录的状态 ==")
    code, out, err = git(["status", "--porcelain", "--untracked-files=normal"])
    lines = [line for line in out.splitlines()
             if any(key in line for key in ("frames", "webm", "assets", "memes"))]
    if lines:
        print("     git status 提到了它们（前 5 行）：")
        for line in lines[:5]:
            print("       %s" % line[:100])
        print("     注意：如果显示 `?? frames/`，说明**整个目录未被忽略**。")
    else:
        print("     git status 没提到它们（已被忽略）")

    print()
    print("  == 结论 ==")
    code, out, _ = git(["check-ignore", "-v", "frames"])
    if code == 0:
        print("     frames/ 已被忽略 —— 若暂存区里仍有它，请 git reset 后重新 add。")
    else:
        print("     frames/ **没有被忽略** —— .gitignore 规则没匹配上。")
        print("     可能原因：规则写在文件末尾但路径匹配方式不对，或文件未被 git 读取。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
