# -*- coding: utf-8 -*-
"""打印"推送前"的确切状态与下一步命令，供用户照做。

不是复述记忆，而是读当前仓库得出：
  * 分支名、提交数、文件数、工作区是否干净
  * 是否已配远程、提交作者是谁
  * 凭据助手配置

    python tools/next_steps.py
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser("~")


def git(args):
    done = subprocess.run(["git"] + args, cwd=ROOT, capture_output=True)
    return (done.returncode,
            done.stdout.decode("utf-8", "replace").strip(),
            done.stderr.decode("utf-8", "replace").strip())


def main():
    branch = git(["branch", "--show-current"])[1] or "(未知)"
    commits = git(["rev-list", "--count", "HEAD"])[1]
    tracked = len(git(["ls-files"])[1].splitlines())
    dirty = git(["status", "--porcelain"])[1]
    author = git(["log", "-1", "--format=%an <%ae>"])[1]
    remote = git(["remote", "-v"])[1]
    helper = git(["config", "--get", "credential.helper"])[1]
    user_name = git(["config", "user.name"])[1]
    user_email = git(["config", "user.email"])[1]

    print()
    print("  当前仓库状态")
    print("  " + "=" * 58)
    print("     位置      : %s" % ROOT)
    print("     分支      : %s" % branch)
    print("     提交数    : %s" % commits)
    print("     跟踪文件  : %d 个" % tracked)
    print("     工作区    : %s" % ("有未提交改动" if dirty else "干净"))
    print("     现有作者  : %s" % author)
    print("     git 身份  : %s <%s>" % (user_name or "(未设)", user_email or "(未设)"))
    print("     远程      : %s" % (remote.replace("\n", " | ") if remote else "未配置"))
    print("     凭据助手  : %s" % (helper or "(未配置)"))

    print()
    print("  已经有这些凭据吗")
    print("  " + "=" * 58)
    for label, path in (("SSH 私钥 id_ed25519", os.path.join(HOME, ".ssh", "id_ed25519")),
                        ("SSH 私钥 id_rsa", os.path.join(HOME, ".ssh", "id_rsa")),
                        ("保存的 git 凭据", os.path.join(HOME, ".git-credentials"))):
        print("     %-22s %s" % (label, "有" if os.path.exists(path) else "没有"))

    print()
    print("  下一步（照抄，把 <...> 换成你自己的）")
    print("  " + "=" * 58)
    if not remote:
        print("     ① 先去 https://github.com/new 建一个**空**仓库")
        print("        —— 不要勾 Add README / .gitignore / license")
        print()
        print("     ② 改成你自己的提交身份并重写作者：")
        print('        git config user.name  "<你的名字>"')
        print('        git config user.email "<你的邮箱>"')
        print('        git rebase --root --exec "git commit --amend --reset-author --no-edit"')
        print()
        print("     ③ 关联远程并推送：")
        print("        git remote add origin https://github.com/<用户名>/<仓库名>.git")
        print("        git push -u origin main")
    else:
        print("     远程已配置。直接推：")
        print("        git push -u origin %s" % branch)
        if "dsh-pet contributor" in author:
            print()
            print("     注意：作者还是占位身份，想改就执行：")
            print('        git config user.name  "<你的名字>"')
            print('        git config user.email "<你的邮箱>"')
            print('        git rebase --root --exec "git commit --amend --reset-author --no-edit"')

    print()
    print("  推完怎么自查")
    print("  " + "=" * 58)
    print("     git log --format=\"%h %an <%ae> %s\"     # 作者应是你自己")
    print("     git ls-remote --heads origin             # 远程已有 main")
    print("     仓库网页的文件列表里不该有 webm/ frames/ assets/ memes/")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
