# -*- coding: utf-8 -*-
"""改成公开仓库**之前**的体检：扫密钥、私人信息、意外的大文件。

为什么不能只扫当前文件：**改成公开会把整个历史一起暴露**。某个密钥哪怕在
后面的提交里删掉了，只要它曾经进来过，就仍然躺在历史对象里、谁都能翻出来。

所以这里用 `git grep <全部提交>` 扫**每一个历史版本**，而不是只看 HEAD。

    python tools/audit_before_public.py
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 密钥/凭据类。宁可误报也不要漏报 —— 误报只需要人看一眼，漏报是不可逆的。
SECRET_PATTERNS = [
    ("OpenAI 风格 sk- 密钥", r"sk-[A-Za-z0-9_-]{20,}"),
    ("Anthropic 密钥", r"sk-ant-[A-Za-z0-9_-]{20,}"),
    ("GitHub PAT (ghp_)", r"ghp_[A-Za-z0-9]{30,}"),
    ("GitHub PAT (github_pat_)", r"github_pat_[A-Za-z0-9_]{20,}"),
    ("GitHub OAuth (gho_/ghu_/ghs_)", r"gh[ous]_[A-Za-z0-9]{30,}"),
    ("AWS Access Key", r"AKIA[0-9A-Z]{16}"),
    ("Google API Key", r"AIza[0-9A-Za-z_-]{30,}"),
    ("Slack Token", r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    ("私钥文件内容", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ("JWT", r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\."),
    ("带值的 password", r"password\s*[:=]\s*[\"'][^\"'\s]{6,}[\"']"),
    ("带值的 api_key/apikey", r"api[_-]?key\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']"),
    ("带值的 secret", r"(client_?)?secret\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']"),
    ("带值的 token", r"token\s*[:=]\s*[\"'][A-Za-z0-9_.-]{16,}[\"']"),
    ("Bearer 令牌", r"Bearer\s+[A-Za-z0-9\-._~+/]{20,}"),
]

# 私人信息：会暴露"这是谁的机器"。
PRIVACY_PATTERNS = [
    ("Windows 用户名路径", r"[A-Za-z]:\\Users\\[A-Za-z0-9_.-]+"),
    ("POSIX home 路径", r"/(?:home|Users)/[A-Za-z0-9_.-]+"),
]

# 这些文件类型/名字本身就该看一眼
SUSPICIOUS_NAMES = (".env", ".npmrc", ".pypirc", "id_rsa", "id_ed25519",
                    "credentials", "secrets", ".netrc", "token.json")

MAX_FILE_MB = 20          # 单个跟踪文件超过这个体积要解释一下


def run(args):
    return subprocess.run(args, cwd=ROOT, capture_output=True,
                          text=True, errors="replace")


def all_commits():
    done = run(["git", "rev-list", "--all"])
    return [line.strip() for line in done.stdout.splitlines() if line.strip()]


def grep_history(commits, pattern):
    """在**全部提交**里搜 pattern，返回命中的行（去重、限量）。"""
    command = ["git", "grep", "-I", "-n", "-E", "-e", pattern] + commits
    done = run(command)
    return [line for line in done.stdout.splitlines() if line.strip()]


def grep_head(pattern):
    """只在**最新版本**（HEAD）里搜。

    为什么要分开：**已删掉但历史里还有** 和 **现在还在** 是两种严重程度。
    前者改公开后仍会被翻出来，但通常无害；后者是"现在就露着"，必须处理。
    早先只报一个总数，看到"1 处命中"分不清是哪种，等于没提供可操作的信息。
    """
    done = run(["git", "grep", "-I", "-n", "-E", "-e", pattern, "HEAD"])
    return [line for line in done.stdout.splitlines() if line.strip()]


def main():
    print()
    print("  公开前体检")
    print("  " + "=" * 76)

    commits = all_commits()
    tracked = run(["git", "ls-files"]).stdout.splitlines()
    print("  扫描范围: %d 个提交、%d 个跟踪文件" % (len(commits), len(tracked)))
    if not commits:
        print("  **不是 git 仓库或没有提交**")
        return 1

    problems = []

    # --- 1. 密钥 ---
    print()
    print("  ① 密钥 / 凭据（扫全部历史）")
    print("  " + "-" * 76)
    secret_hits = 0
    for label, pattern in SECRET_PATTERNS:
        hits = grep_history(commits, pattern)
        if hits:
            secret_hits += len(hits)
            print("  [命中] %s —— %d 处" % (label, len(hits)))
            for line in hits[:3]:
                print("        " + line[:130])
    if not secret_hits:
        print("  [OK] 没有命中任何密钥模式")
    else:
        problems.append("发现 %d 处疑似密钥" % secret_hits)

    # --- 2. 私人信息 ---
    print()
    print("  ② 私人信息（会暴露「这是谁的机器」）")
    print("  " + "-" * 76)
    privacy_hits = 0
    privacy_now = 0
    for label, pattern in PRIVACY_PATTERNS:
        hits = grep_history(commits, pattern)
        now = grep_head(pattern)
        if not hits:
            continue
        privacy_hits += len(hits)
        privacy_now += len(now)
        scope = "**最新版本里仍有 %d 处**" % len(now) if now else "只剩历史（最新版本已清）"
        print("  [命中] %s —— 历史 %d 处，%s" % (label, len(hits), scope))
        for line in hits[:5]:
            print("        " + line[:130])
    if not privacy_hits:
        print("  [OK] 没有命中私人路径")
    elif privacy_now:
        print("  （**最新版本里还在**，会被搜索引擎直接收录 —— 建议改掉再公开）")
        problems.append("最新版本里有 %d 处私人路径" % privacy_now)
    else:
        print("  （最新版本已经清干净了，只在历史对象里 —— 不是密钥，通常可以接受。")
        print("    要彻底清掉需要重写历史 + force push，那会改变所有提交哈希；")
        print("    若在意，见 git filter-repo / filter-branch。）")

    # --- 3. 可疑文件名 ---
    print()
    print("  ③ 可疑文件名")
    print("  " + "-" * 76)
    name_hits = [name for name in tracked
                 if os.path.basename(name).lower() in SUSPICIOUS_NAMES
                 or os.path.basename(name).lower().startswith(".env")]
    if name_hits:
        for name in name_hits:
            print("  [命中] %s" % name)
        problems.append("有 %d 个可疑文件名的文件" % len(name_hits))
    else:
        print("  [OK] 没有 .env / .npmrc / 私钥之类的文件名")

    # --- 4. 大文件 ---
    print()
    print("  ④ 意外的大文件（跟踪文件 > %d MB）" % MAX_FILE_MB)
    print("  " + "-" * 76)
    big = []
    for name in tracked:
        path = os.path.join(ROOT, name)
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        if size > MAX_FILE_MB * 1048576:
            big.append((size, name))
    big.sort(reverse=True)
    if big:
        for size, name in big[:10]:
            print("  %8.1f MB  %s" % (size / 1048576.0, name))
        print("  （素材类大文件是预期的；只是确认没有别的东西混进来）")
    else:
        print("  [OK] 没有超过 %d MB 的跟踪文件" % MAX_FILE_MB)

    # --- 5. 身份 ---
    print()
    print("  ⑤ 提交身份（公开后会被搜到）")
    print("  " + "-" * 76)
    identities = run(["git", "log", "--format=%an <%ae>|%cn <%ce>"]).stdout.splitlines()
    unique = sorted(set(identities))
    for line in unique:
        print("  " + line)
    if all("noreply" in line or "users.noreply" in line for line in unique):
        print("  [OK] 全部是 GitHub noreply 地址，没有泄露真实邮箱")
    else:
        print("  **有非 noreply 的邮箱** —— 公开前建议先重写历史")

    # --- 6. 上游署名 ---
    print()
    print("  ⑥ 上游署名（用别人素材必须保留）")
    print("  " + "-" * 76)
    for name in ("README.md", "ASSETS.md", "LICENSE"):
        path = os.path.join(ROOT, name)
        if not os.path.isfile(path):
            print("  [缺失] %s" % name)
            continue
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            text = handle.read()
        has_upstream = "PC2005-cloud" in text
        print("  %-12s 提到 PC2005-cloud: %s" % (name, "是" if has_upstream else "**否**"))

    print()
    print("  结论")
    print("  " + "=" * 76)
    if problems:
        for item in problems:
            print("     [问题] " + item)
        print()
        print("  **先处理上面这些问题，再改公开。**")
        return 1
    print("     [OK] 没有密钥、没有可疑文件、身份是 noreply、署名齐全")
    if privacy_hits:
        print("     [提示] 有 %d 处私人路径（不致命，自行决定）" % privacy_hits)
    print()
    print("  可以放心改成公开。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
