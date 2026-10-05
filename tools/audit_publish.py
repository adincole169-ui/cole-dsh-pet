# -*- coding: utf-8 -*-
"""发布前审计：确认将要提交的内容**不含**素材与私人数据。

为什么不用 PowerShell 数：`git diff --name-only` 会把含中文的路径**加引号并转义**
（`"frames/\345\210\235..."`），PowerShell 拿到就会报"路径中具有非法字符"，既刷屏又
统计不准。改用 `git status --porcelain -z`（NUL 分隔、不转义）在 Python 里解析。

    python tools/audit_publish.py
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 绝不能出现在仓库里的目录/文件。
#
# 两个目录**有意不在**这个列表里：
#   * `webm/` —— 按上游许可（素材允许开源使用），106 个 webm 随仓库分发，
#     使用者 clone 下来就能解码使用（见 README 的快速开始）；
#   * `assets/` 与 `memes/` —— 体积很小（共约 790 KB）且 `assets/icon.ico`
#     **运行必需**：缺了它窗口与任务栏就没有图标，而且代码不会报错。
#     曾经把整个 `assets/` 排除掉，结果从 GitHub 装的人"图标是没有的"。
#     （`assets/icon-full.*` 是孤儿文件，明确排除，见 .gitignore）
#
# 这里排除的是"体积大且可由 webm 重新生成"的东西，以及私人数据。
FORBIDDEN_DIRS = ["frames", "logs", "dist", ".venv",
                  "__pycache__", "frames_old_480", ".decode-staging"]
FORBIDDEN_SUFFIX = [".zip", ".bak", ".pyc"]

# 期望随仓库分发的素材数量（用来确认没漏、没混进别的东西）
EXPECTED_WEBM = 106
EXPECTED_ICONS = 4          # icon.ico / icon.png / icon-head.ico / icon-head.png
EXPECTED_MEMES = 8
# 明确不该出现的孤儿文件
FORBIDDEN_FILES = ["assets/icon-full.ico", "assets/icon-full.png"]

# 文件**名/路径**里不该出现的本机痕迹。同样从字符码拼，避免本文件自己含这些字符串
# （否则审计脚本每次都会命中自己，真正的泄露反而被噪音淹没）。
PATH_MARKERS = [
    "".join(chr(code) for code in (0x38, 0x36, 0x31, 0x37, 0x33)),   # Windows 用户名
    "ana" + "conda",                                                 # 发行版名
]


def git(args):
    done = subprocess.run(["git"] + args, cwd=ROOT, capture_output=True)
    return done.returncode, done.stdout


def tracked_files():
    """所有被 git 跟踪（已暂存）的文件。用 -z 避免路径转义。"""
    code, out = git(["status", "--porcelain", "-z"])
    if code != 0:
        return None
    files = []
    for chunk in out.decode("utf-8", "replace").split("\0"):
        if len(chunk) > 3:
            # 形如 "A  path" 或 "?? path"
            files.append(chunk[3:])
    return files


def main():
    files = tracked_files()
    if files is None:
        print("  无法读取 git 状态（这不是 git 仓库？）")
        return 1

    staged = [name for name in files if not name.startswith("??")]
    untracked = [name for name in files if name.startswith("??")]
    committed_mode = "--committed" in sys.argv

    print("  暂存区文件数: %d" % len(staged))
    print("  未跟踪文件数: %d" % len(untracked))

    # 模式选择：
    #   --committed  显式要求时，一律审计 HEAD 里已提交的文件
    #   默认         审计暂存区；若暂存区为空则退回 HEAD（"都已经提交了"的常见场景）
    if committed_mode or not staged:
        # -z + core.quotePath=false 两个都要：
        #   * `-z` 用 NUL 分隔，避开"路径含空格/换行"的转义；
        #   * `core.quotePath=false` 让**非 ASCII 路径原样输出**。
        # 少了后者时，git 会把中文名写成 `"webm/\344\270\211..."` 这种带引号的
        # 八进制转义 —— 于是后面 `os.path.isfile()` 全部落空，106 个 webm 的体积
        # 一个都统计不到（实测总量从 52 MB 变成 0.6 MB，500 MB 的护栏形同虚设）。
        code, out = git(["-c", "core.quotePath=false", "ls-tree", "-r", "-z",
                         "--name-only", "HEAD"])
        committed = [line for line in out.decode("utf-8", "replace").split("\0") if line]
        if committed:
            if not committed_mode and not staged:
                code, latest = git(["log", "-1", "--format=%h %s"])
                print("  （暂存区为空 —— 改为审计已提交内容）")
                print("  最新提交: %s" % latest.decode("utf-8", "replace").strip())
            staged = committed
            print("  审计目标: HEAD 的 %d 个文件" % len(staged))
        elif not staged:
            print()
            print("  暂存区为空，且 HEAD 里没有文件（还没提交过）。")
            print("  先 git add 再审计。")
            return 0
    print()

    bad = []
    for name in staged:
        cleaned = name.strip('"')
        head = cleaned.split("/")[0]
        if head in FORBIDDEN_DIRS:
            bad.append((cleaned, "在禁止目录 %s/" % head))
            continue
        if any(cleaned.lower().endswith(suffix) for suffix in FORBIDDEN_SUFFIX):
            bad.append((cleaned, "后缀不该出现"))
            continue
        if any(marker in cleaned for marker in PATH_MARKERS):
            bad.append((cleaned, "含私人信息"))

    if bad:
        print("  **以下内容不该进仓库（%d 个）**：" % len(bad))
        for name, reason in bad[:20]:
            print("     %-52s %s" % (name[:52], reason))
        if len(bad) > 20:
            print("     ...还有 %d 个" % (len(bad) - 20))
        print()
        print("  请检查 .gitignore 是否生效。")
        return 1

    print("  干净：审计范围内不含素材、缓存、分发产物或私人数据")

    # 逐文件搜敏感词（本机用户名、解释器绝对路径等）。
    # 这几个词**不直接写成字面量**：否则检查器自己就会命中自己，每次审计都留两条
    # 噪音，真正的泄露反而被淹没。用户名从字符码拼出来，文件里就不含它了。
    print()
    print("  == 敏感词扫描 ==")
    words = [
        # 本机 Windows 用户名（从字符码拼，避免本文件含它）
        "".join(chr(code) for code in (0x38, 0x36, 0x31, 0x37, 0x33)),
        "D:" + os.sep + "python",                                          # 解释器路径
        "E:" + os.sep + "dsh",                                             # 开发目录
        "ana" + "conda",                                                   # 发行版名
    ]
    print("     检查 %d 个模式" % len(words))
    hits = []
    for name in staged:
        path = os.path.join(ROOT, name.strip('"'))
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="ignore") as handle:
                text = handle.read()
        except Exception:
            continue
        for word in words:
            if word in text:
                hits.append((name.strip('"'), word))
    if hits:
        print("     **%d 处命中**：" % len(hits))
        for name, word in hits[:15]:
            print("        %-44s 命中 %s" % (name[:44], word))
        print("     含本机用户名/解释器绝对路径的文件不该发布，请改掉。")
    else:
        print("     无命中")

    # 按顶层目录统计，让人一眼看清仓库构成
    print()
    print("  == 仓库构成 ==")
    groups = {}
    for name in staged:
        cleaned = name.strip('"')
        head = cleaned.split("/")[0] if "/" in cleaned else "(根目录)"
        groups[head] = groups.get(head, 0) + 1
    for head, count in sorted(groups.items(), key=lambda item: -item[1]):
        print("     %-22s %d 个文件" % (head, count))

    # webm / 图标 / 表情包都是**有意**随仓库分发的，这里确认数量符合预期
    webm_count = groups.get("webm", 0)
    icon_count = groups.get("assets", 0)
    meme_count = groups.get("memes", 0)
    size_problem = False
    print()
    print("  == 随仓库分发的素材 ==")
    print("     webm 动画 : %d 个（期望 %d）" % (webm_count, EXPECTED_WEBM))
    if webm_count == 0:
        print("        提示：没有 webm —— 使用者得自己去上游取素材（见 ASSETS.md）")
    elif webm_count != EXPECTED_WEBM:
        print("        **数量与预期不符**，请确认是不是漏了或多加了文件")
        size_problem = True
    else:
        print("        与预期一致")

    print("     图标      : %d 个（期望 %d）" % (icon_count, EXPECTED_ICONS))
    if icon_count == 0:
        print("        **一个图标都没有** —— 窗口与任务栏会没有图标，且代码不报错。")
        print("        生成: python tools/make_icon.py")
        size_problem = True
    elif icon_count != EXPECTED_ICONS:
        print("        **数量与预期不符**（期望 icon.ico / icon.png / "
              "icon-head.ico / icon-head.png 四个）")
        size_problem = True
    else:
        print("        与预期一致")

    print("     表情包    : %d 个（期望 %d）" % (meme_count, EXPECTED_MEMES))
    if meme_count == 0:
        print("        提示：没有表情包 —— 碎碎念配图功能会静默地退化成无图")
    elif meme_count != EXPECTED_MEMES:
        print("        **数量与预期不符**（生成: python tools/make_memes.py）")
        size_problem = True
    else:
        print("        与预期一致")

    # 孤儿文件不该混进来
    tracked_names = set(name.strip('"') for name in staged)
    strays = [path for path in FORBIDDEN_FILES if path in tracked_names]
    if strays:
        print()
        print("  **不该出现的孤儿文件**：%s" % ", ".join(strays))
        print("     它们不被任何代码引用，也不由当前工具生成（见 .gitignore）")
        size_problem = True

    total = 0
    for name in staged:
        path = os.path.join(ROOT, name.strip('"'))
        if os.path.isfile(path):
            total += os.path.getsize(path)
    print()
    print("  合计体积: %.1f MB（%d 个文件）" % (total / 1048576.0, len(staged)))
    if total > 500 * 1048576:
        print("     提示：超过 500 MB —— 对 git 仓库偏大，确认一下是不是误加了 frames/")
        size_problem = True
    return 1 if size_problem else 0


if __name__ == "__main__":
    sys.exit(main())
