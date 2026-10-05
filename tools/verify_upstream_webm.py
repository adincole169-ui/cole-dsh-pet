# -*- coding: utf-8 -*-
"""现场确认：我们的 webm 与上游 PC2005-cloud/dsh-pet 的是否仍然逐字节相同。

用户说"直接使用上游的动作、不再自己修改" —— 先把这个前提确认清楚：
如果本来就相同，那就什么都不用搬；如果上游更新过某几个动画，才需要同步。

做法：从上游 raw 地址下载几个动画，算 SHA-256 与本地比。不走 GitHub API
（那个会限流），raw 地址稳定。

    python tools/verify_upstream_webm.py            # 抽查 4 个
    python tools/verify_upstream_webm.py --count 8  # 抽查 8 个
"""

import hashlib
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WEBM = os.path.join(ROOT, "webm")
RAW = "https://raw.githubusercontent.com/PC2005-cloud/dsh-pet/main/dsh-pet/assets/webm/"
PROXY = os.environ.get("DSH_PROXY", "http://127.0.0.1:7897")


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(name, destination):
    url = RAW + name
    command = ["curl.exe", "-sSL", "--fail", "--max-time", "120",
               "--proxy", PROXY, "-o", destination, url]
    done = subprocess.run(command, capture_output=True)
    return done.returncode == 0 and os.path.exists(destination)


def main():
    argv = sys.argv[1:]
    count = int(argv[argv.index("--count") + 1]) if "--count" in argv else 4
    if not os.path.isdir(WEBM):
        print("  找不到 %s" % WEBM)
        return 1

    local = sorted(f for f in os.listdir(WEBM) if f.endswith(".webm"))
    print()
    print("  现场比对：本地 webm vs 上游 dsh-pet/assets/webm")
    print("  " + "=" * 72)
    print("  本地动画数: %d" % len(local))

    # 均匀挑几个，跨不同分类
    step = max(1, len(local) // count)
    picks = local[::step][:count]
    temp = os.path.join(ROOT, "logs", "_upstream_check")
    os.makedirs(temp, exist_ok=True)

    same = 0
    different = []
    failed = []
    for name in picks:
        destination = os.path.join(temp, name)
        if not download(name, destination):
            failed.append(name)
            print("  %-26s 下载失败" % name[:26])
            continue
        local_hash = sha256(os.path.join(WEBM, name))
        remote_hash = sha256(destination)
        if local_hash == remote_hash:
            same += 1
            print("  %-26s 逐字节相同" % name[:26])
        else:
            different.append(name)
            print("  %-26s **不同**" % name[:26])
            print("        本地 %s" % local_hash[:32])
            print("        上游 %s" % remote_hash[:32])
        os.remove(destination)
    try:
        os.rmdir(temp)
    except OSError:
        pass

    print()
    print("  结论")
    print("  " + "=" * 72)
    print("  抽查 %d 个：相同 %d，不同 %d，下载失败 %d"
          % (len(picks), same, len(different), len(failed)))
    if different:
        print("  **上游有动画更新过**，需要同步这些：%s" % ", ".join(different))
        print("  同步方式：从上游 raw 直接下载覆盖 webm/，再")
        print("            python tools/asset_pipeline.py build <名字> 重新解码")
    elif failed:
        print("  有下载失败的，结论不完整 —— 建议重跑")
    else:
        print("  本地素材与上游**完全一致**，无需搬运。")
        print("  也就是说：现在的仓库用的就是上游原版动作，没有做任何修改。")
    return 1 if different else 0


if __name__ == "__main__":
    sys.exit(main())
