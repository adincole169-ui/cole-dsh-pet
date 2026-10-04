# -*- coding: utf-8 -*-
"""字节级验证：本地 webm 是否与 PC2005-cloud/dsh-pet 仓库里的完全相同。

做法：git 的 blob 哈希 = sha1("blob <字节数>\\0" + 文件内容)，是**纯内容**哈希，
与仓库无关。所以只要把上游某个文件的 blob sha 与本地算出来的对比，
就能断定"是同一个文件"，不用真的下载。

需要：上游 tree 的 JSON（含每个文件的 sha）。从 GitHub API 取，或读本地缓存。

    python tools/verify_asset_origin.py
"""

import hashlib
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WEBM = os.path.join(ROOT, "webm")
UPSTREAM_TREE_API = ("https://api.github.com/repos/PC2005-cloud/dsh-pet/"
                     "git/trees/HEAD?recursive=1")
CACHE = os.path.join(HERE, "_upstream_tree.json")
PROXY = os.environ.get("DSH_PROXY", "http://127.0.0.1:7897")


def git_blob_hash(path):
    """算 git 的 blob 哈希：sha1(b"blob <len>\\0" + content)。"""
    size = os.path.getsize(path)
    digest = hashlib.sha1()
    digest.update(("blob %d\0" % size).encode("ascii"))
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1 << 20)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def fetch_tree():
    if os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as handle:
            return json.load(handle)
    handler = urllib.request.ProxyHandler({"http": PROXY, "https": PROXY})
    opener = urllib.request.build_opener(handler)
    request = urllib.request.Request(UPSTREAM_TREE_API,
                                     headers={"User-Agent": "dsh-pet-verify"})
    with opener.open(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    with open(CACHE, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    return payload


def main():
    if not os.path.isdir(WEBM):
        print("  找不到 %s" % WEBM)
        return 1
    try:
        tree = fetch_tree()
    except Exception as error:
        print("  取上游 tree 失败: %s" % error)
        print("  （可先用浏览器下载 tree JSON 存到 %s）" % CACHE)
        return 1

    # 上游 assets/webm/ 下的文件 -> {文件名: sha}
    upstream = {}
    for item in tree.get("tree", []):
        path = item.get("path", "")
        if path.startswith("dsh-pet/assets/webm/") and path.endswith(".webm"):
            upstream[os.path.basename(path)] = item.get("sha")

    print()
    print("  上游 dsh-pet/assets/webm/ 里的动画: %d 个" % len(upstream))
    local_names = sorted(name for name in os.listdir(WEBM) if name.endswith(".webm"))
    print("  本地 webm/:                        %d 个" % len(local_names))

    same_names = [name for name in local_names if name in upstream]
    only_local = [name for name in local_names if name not in upstream]
    only_upstream = [name for name in upstream if name not in local_names]
    print()
    print("  文件名对照")
    print("     两边都有 : %d" % len(same_names))
    print("     只有本地 : %d %s" % (len(only_local), only_local[:3]))
    print("     只有上游 : %d %s" % (len(only_upstream), only_upstream[:3]))

    print()
    print("  内容比对（git blob 哈希，抽查 8 个）")
    print("  " + "-" * 62)
    same = 0
    checked = 0
    for name in same_names[:8]:
        path = os.path.join(WEBM, name)
        local_hash = git_blob_hash(path)
        upstream_hash = upstream[name]
        match = local_hash == upstream_hash
        if match:
            same += 1
        checked += 1
        print("     %-28s %s" % (name[:26], "一致" if match else "**不同**"))
        if not match:
            print("        本地   %s" % local_hash)
            print("        上游   %s" % upstream_hash)

    print()
    print("  结论")
    print("  " + "=" * 62)
    if checked and same == checked:
        print("     抽查的 %d 个文件**逐字节相同**。" % checked)
        print("     即：本地 webm 就是 PC2005-cloud/dsh-pet 的 assets/webm/。")
        print()
        print("     因此正确出处是：")
        print("       动画素材 —— PC2005-cloud/dsh-pet（MIT 代码；素材允许开源使用、")
        print("                   禁止商用、二创须署名）")
        print("       与 gmskywalker/deepseek-fat-fish-codex-pet 无关。")
    else:
        print("     有文件不同（%d/%d 相同）——来源需要进一步核实。" % (same, checked))
    return 0


if __name__ == "__main__":
    sys.exit(main())
