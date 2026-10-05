# -*- coding: utf-8 -*-
"""把提交历史里的作者/提交者邮箱换掉，**完整保留时间戳**。

为什么不用 `git rebase --reset-author`：那会把作者时间重置成"现在"，历史时间线就没了。
为什么不用 `git filter-branch --env-filter`：那条要在 shell 里传一段脚本，
在本项目的 PowerShell 环境下引号必然出问题（见工作区规则 1）。

所以这里直接操作 git 对象：commit 对象就是一段文本

    tree <sha>
    parent <sha>
    author Name <email> <时间戳> <时区>
    committer Name <email> <时间戳> <时区>

    <提交信息>

把邮箱那一小段**按字节**替换掉、重新写成一个新对象即可。父提交必须**从旧到新**
依次换成新对象，最后把分支指向新的头。

安全措施：
  * 改写前把原来的头存进 `refs/backup/<分支>-pre-email-rewrite`，随时可退回；
  * 只动 author/committer 的邮箱，不碰提交信息、时间、树、父关系；
  * 改写后逐项核对（邮箱全换、时间未变、树未变）。

    python tools/rewrite_author_email.py                       # 只看会发生什么
    python tools/rewrite_author_email.py --apply               # 真的改写
    python tools/rewrite_author_email.py --apply --old X --new Y
"""

import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OLD = "adincole169@gmail.com"
DEFAULT_NEW = "adincole169-ui@users.noreply.github.com"


def git(args, data=None):
    done = subprocess.run(["git"] + args, cwd=ROOT, input=data,
                          capture_output=True)
    if done.returncode != 0:
        raise RuntimeError("git %s 失败: %s"
                           % (" ".join(args), done.stderr.decode("utf-8", "replace")[:300]))
    return done.stdout


def current_branch():
    out = git(["rev-parse", "--abbrev-ref", "HEAD"]).decode("utf-8", "replace").strip()
    return out


def read_commit(sha):
    return git(["cat-file", "commit", sha])


def split_header(raw):
    """把 commit 对象拆成 (头部行列表, 提交信息字节)。"""
    marker = raw.find(b"\n\n")
    if marker < 0:
        return raw.split(b"\n"), b""
    header = raw[:marker].split(b"\n")
    message = raw[marker + 2:]
    return header, message


def parse_identity(line):
    """从 `author Name <email> 1234 +0800` 里取出 (名字, 邮箱, 时间戳, 时区)。"""
    match = re.match(rb"^(author|committer) (.*) <(.*)> (\d+ [+-]\d{4})$", line)
    if not match:
        return None
    return (match.group(1).decode(), match.group(2).decode(),
            match.group(3).decode(), match.group(4).decode())


def build_identity(kind, name, email, when):
    return ("%s %s <%s> %s" % (kind, name, email, when)).encode("utf-8")


def main():
    argv = sys.argv[1:]
    apply_changes = "--apply" in argv
    old = argv[argv.index("--old") + 1] if "--old" in argv else DEFAULT_OLD
    new = argv[argv.index("--new") + 1] if "--new" in argv else DEFAULT_NEW

    branch = current_branch()
    if branch in ("HEAD", "", "(no branch)"):
        print("  当前不在分支上（detached HEAD），先切回分支再跑")
        return 1

    old_head = git(["rev-parse", "HEAD"]).decode().strip()
    commits = git(["rev-list", "--reverse", "HEAD"]).decode().split()
    print()
    print("  重写提交身份邮箱")
    print("  " + "=" * 70)
    print("  分支    : %s" % branch)
    print("  提交数  : %d" % len(commits))
    print("  原邮箱  : %s" % old)
    print("  新邮箱  : %s" % new)
    print("  原 HEAD : %s" % old_head[:12])
    print()

    # 先只统计，不改
    affected = 0
    for sha in commits:
        header, _message = split_header(read_commit(sha))
        for line in header:
            if line.startswith((b"author ", b"committer ")):
                parsed = parse_identity(line)
                if parsed and parsed[2] == old:
                    affected += 1
    print("  含原邮箱的作者/提交者行: %d" % affected)
    if affected == 0:
        print("  没有需要改的 —— 可能已经改过了。")
        return 0
    if not apply_changes:
        print()
        print("  这是**预演**。确认无误后加 --apply 真正改写。")
        return 0

    # 备份原来的头
    backup_ref = "refs/backup/%s-pre-email-rewrite" % branch
    git(["update-ref", backup_ref, old_head])
    print()
    print("  已备份原 HEAD -> %s" % backup_ref)

    mapping = {}
    for index, sha in enumerate(commits, 1):
        raw = read_commit(sha)
        header, message = split_header(raw)
        out_lines = []
        for line in header:
            if line.startswith(b"tree "):
                out_lines.append(line)
                continue
            if line.startswith(b"parent "):
                old_parent = line.split(b" ", 1)[1].decode().strip()
                new_parent = mapping.get(old_parent, old_parent)
                out_lines.append(("parent %s" % new_parent).encode())
                continue
            if line.startswith((b"author ", b"committer ")):
                parsed = parse_identity(line)
                if parsed is None:
                    out_lines.append(line)
                    continue
                kind, name, email, when = parsed
                if email == old:
                    email = new
                out_lines.append(build_identity(kind, name, email, when))
                continue
            out_lines.append(line)

        payload = b"\n".join(out_lines) + b"\n\n" + message
        new_sha = git(["hash-object", "-t", "commit", "-w", "--stdin"],
                      data=payload).decode().strip()
        mapping[sha] = new_sha
        if index % 4 == 0 or index == len(commits):
            print("     已重写 %d/%d" % (index, len(commits)))

    new_head = mapping[old_head]
    git(["update-ref", "refs/heads/%s" % branch, new_head, old_head])
    print()
    print("  分支 %s: %s -> %s" % (branch, old_head[:12], new_head[:12]))

    # --- 核对 ---
    print()
    print("  核对")
    print("  " + "-" * 70)
    authors = git(["log", "--format=%ae"]).decode().split()
    emails = sorted(set(authors))
    print("  现在的邮箱: %s" % ", ".join(emails))
    ok_email = old not in emails and new in emails
    print("  旧邮箱已消失: %s" % ("是" if old not in emails else "**否**"))

    # 时间与树必须逐提交一致
    def fingerprint(rev):
        out = git(["log", "--format=%H|%at|%ct|%T", rev]).decode().splitlines()
        return [line.split("|", 1)[1] for line in out if line]

    before = fingerprint(backup_ref)
    after = fingerprint("HEAD")
    same = before == after
    print("  时间与树逐提交一致: %s（%d 个提交）" % ("是" if same else "**否**", len(after)))
    if not same:
        for index, (a, b) in enumerate(zip(before, after)):
            if a != b:
                print("     第 %d 个不同: %s vs %s" % (index + 1, a, b))
                break

    print()
    if ok_email and same:
        print("  成功。下一步：")
        print("     git push --force-with-lease")
        print("  确认远程无误后可以删掉备份引用：")
        print("     git update-ref -d %s" % backup_ref)
        return 0
    print("  **核对没过，请用备份引用退回**：")
    print("     git update-ref refs/heads/%s %s" % (branch, old_head))
    return 1


if __name__ == "__main__":
    sys.exit(main())
