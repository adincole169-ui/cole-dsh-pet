# -*- coding: utf-8 -*-
"""发布进度检查：远程配置、凭据、以及本地是否已有可用的 GitHub 仓库信息。

目标要求"创建远程仓库并推送"。这一步需要账号凭据，所以先把**当前到底缺什么**
核实清楚，而不是靠记忆。

    python tools/git_publish_status.py
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser("~")


def git(args):
    done = subprocess.run(["git"] + args, cwd=ROOT, capture_output=True)
    return done.returncode, done.stdout.decode("utf-8", "replace").strip(), \
        done.stderr.decode("utf-8", "replace").strip()


def main():
    print("  == 仓库状态 ==")
    for label, args in (("当前分支", ["branch", "--show-current"]),
                        ("提交数", ["rev-list", "--count", "HEAD"]),
                        ("最新提交", ["log", "-1", "--format=%h %s"]),
                        ("提交作者", ["log", "-1", "--format=%an <%ae>"]),
                        ("跟踪文件数", ["ls-files"]),
                        ("工作区", ["status", "--porcelain"])):
        code, out, _err = git(args)
        if label == "跟踪文件数":
            out = str(len(out.splitlines())) if out else "0"
        if label == "工作区":
            out = out if out else "干净"
        print("     %-12s %s" % (label, out))

    print()
    print("  == 远程仓库 ==")
    code, out, _err = git(["remote", "-v"])
    if out:
        for line in out.splitlines():
            print("     %s" % line)
    else:
        print("     **没有配置任何远程** —— 这是推送前必须补的一步")

    # 上游跟踪分支
    code, out, _err = git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    print("     上游分支: %s" % (out if code == 0 else "（未设置）"))

    print()
    print("  == 凭据情况 ==")
    checks = [
        ("git-credentials 文件", os.path.join(HOME, ".git-credentials")),
        ("SSH 私钥 id_ed25519", os.path.join(HOME, ".ssh", "id_ed25519")),
        ("SSH 私钥 id_rsa", os.path.join(HOME, ".ssh", "id_rsa")),
        ("SSH 公钥 id_ed25519.pub", os.path.join(HOME, ".ssh", "id_ed25519.pub")),
        ("Git Credential Manager 配置", None),
    ]
    for label, path in checks:
        if path is None:
            code, out, _err = git(["config", "--get", "credential.helper"])
            print("     %-28s %s" % (label, out if out else "（未配置）"))
        else:
            print("     %-28s %s" % (label, "存在" if os.path.exists(path) else "没有"))

    print()
    print("  == 环境变量里有没有令牌 ==")
    found = [name for name in os.environ
             if any(key in name.upper() for key in ("GITHUB", "GH_TOKEN", "GIT_TOKEN"))]
    if found:
        for name in found:
            value = os.environ[name]
            print("     %s = %s...(%d 字符)" % (name, value[:4], len(value)))
    else:
        print("     没有 GITHUB_TOKEN / GH_TOKEN 之类的变量")

    print()
    print("  == 结论 ==")
    if not git(["remote"])[1]:
        print("     缺**远程地址**：需要你在 GitHub 建一个空仓库，把地址给我；")
        print("     或者你自己执行 PUSH.md 里的命令。")
    if not any(os.path.exists(os.path.join(HOME, ".ssh", name))
               for name in ("id_ed25519", "id_rsa")) \
            and not os.path.exists(os.path.join(HOME, ".git-credentials")):
        print("     缺**凭据**：本机没有 SSH 密钥、也没有保存的 git 凭据，")
        print("     所以首次推送必须由你完成一次授权（浏览器登录或 Personal Access Token）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
