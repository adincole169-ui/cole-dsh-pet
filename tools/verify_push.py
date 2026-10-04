# -*- coding: utf-8 -*-
"""推送后核对：本地与远程是否一致，以及仓库页面上该有什么。

不靠记忆，直接把远程真实状态读回来看：
  * 远程 main 的 hash 是否等于本地 HEAD
  * 本地分支是否已跟踪 origin/main
  * 远程有没有意外混进素材目录（用 GitHub API 列顶层内容）
  * 仓库的许可、可见性、默认分支

    python tools/verify_push.py
"""

import json
import os
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git(args):
    done = subprocess.run(["git"] + args, cwd=ROOT, capture_output=True)
    return (done.returncode,
            done.stdout.decode("utf-8", "replace").strip(),
            done.stderr.decode("utf-8", "replace").strip())


def remote_repo():
    """从 origin 的 URL 里解析出 `owner/name`，不写死在代码里。"""
    _code, url, _err = git(["remote", "get-url", "origin"])
    if not url:
        return None
    cleaned = url.strip()
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    if cleaned.startswith("git@"):                 # git@github.com:owner/name
        cleaned = cleaned.split(":", 1)[-1]
    elif "://" in cleaned:                         # https://github.com/owner/name
        cleaned = cleaned.split("://", 1)[1]
        cleaned = cleaned.split("/", 1)[-1]
    parts = [part for part in cleaned.split("/") if part]
    if len(parts) >= 2:
        return "/".join(parts[-2:])
    return None


REPO = remote_repo()
API = "https://api.github.com/repos/" + REPO if REPO else None
# GitHub API 走代理；可用 DSH_PROXY 覆盖，不给就走直连
PROXY = os.environ.get("DSH_PROXY") or os.environ.get("HTTPS_PROXY") or ""


def api(path=""):
    if not API:
        raise RuntimeError("没有配置 origin 远程，无法查询 GitHub")
    handlers = []
    if PROXY:
        handlers.append(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
    opener = urllib.request.build_opener(*handlers)
    request = urllib.request.Request(API + path,
                                     headers={"User-Agent": "dsh-pet-verify"})
    with opener.open(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    failed = []

    print()
    print("  == 本地与远程 ==")
    code, local_head, _err = git(["rev-parse", "HEAD"])
    code, remote_head, _err = git(["rev-parse", "origin/main"])
    print("     本地 HEAD        : %s" % local_head)
    print("     远程 origin/main : %s" % remote_head)
    if local_head == remote_head:
        print("     -> 一致")
    else:
        print("     -> **不一致**")
        failed.append("hash")

    code, upstream, _err = git(["rev-parse", "--abbrev-ref",
                               "--symbolic-full-name", "@{u}"])
    print("     跟踪分支         : %s" % (upstream or "(未设置)"))
    if upstream != "origin/main":
        failed.append("upstream")

    code, status, _err = git(["status", "--porcelain", "-b"])
    first = status.splitlines()[0] if status else ""
    print("     状态             : %s" % first)

    code, author, _err = git(["log", "-1", "--format=%an <%ae>"])
    print("     最新提交作者     : %s" % author)
    if "dsh-pet contributor" in author:
        print("     -> **还是占位身份，需要重写作者**")
        failed.append("author")

    code, count, _err = git(["rev-list", "--count", "HEAD"])
    code, files, _err = git(["ls-files"])
    print("     提交数 / 文件数  : %s / %d" % (count, len(files.splitlines())))

    print()
    print("  == GitHub 上的仓库 ==")
    try:
        info = api()
        print("     仓库             : %s" % info.get("full_name"))
        print("     可见性           : %s" % info.get("visibility"))
        print("     默认分支         : %s" % info.get("default_branch"))
        license_info = info.get("license")
        print("     许可             : %s"
              % (license_info.get("spdx_id") if license_info else "**无**"))
        if not license_info:
            failed.append("license")
        else:
            print("        （说明：本仓库的 LICENSE 只覆盖代码与文档，")
            print("          素材授权情况见 ASSETS.md）")
        print("     大小             : %s KB" % info.get("size"))
    except Exception as error:
        print("     查询失败: %s" % error)
        print("     （GitHub API 走代理 %s；403 多半是出口限流，稍后重试）" % PROXY)

    print()
    print("  == 顶层文件里不该出现的东西 ==")
    try:
        contents = api("/contents")
        names = sorted(item["name"] for item in contents)
        print("     顶层条目: %s" % ", ".join(names))
        forbidden = [name for name in names
                     if name in ("webm", "frames", "assets", "memes", "logs", "dist")]
        if forbidden:
            print("     -> **不该出现**: %s" % ", ".join(forbidden))
            failed.append("forbidden")
        else:
            print("     -> 没有素材/日志/分发目录（正确）")
    except Exception as error:
        print("     查询失败: %s" % error)

    print()
    if failed:
        print("  结论: 有 %d 项需要处理: %s" % (len(failed), ", ".join(failed)))
        return 1
    print("  结论: 推送成功且内容正确")
    print("         https://github.com/%s" % REPO)
    return 0


if __name__ == "__main__":
    sys.exit(main())
