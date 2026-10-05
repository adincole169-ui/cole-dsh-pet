# -*- coding: utf-8 -*-
"""串行跑全部自检/校验脚本，汇总通过情况。

**必须串行**：多个自检都要起桌宠实例、抢 127.0.0.1:8899，并行会互相干扰。
每个脚本给一个超时（默认 120 秒），超时算失败并继续下一个。

    python tools/run_selftests.py                  # 跑全部
    python tools/run_selftests.py --only selftest_settle_window selftest_fade
    python tools/run_selftests.py --list
    python tools/run_selftests.py --exclude whisper_live standalone push
"""

import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PYTHON = sys.executable
DEFAULT_TIMEOUT = 120
# 需要联网/克隆/打包的测试天然更慢，给它们单独的预算。
# 踩过：`verify_public_clone` 要 clone 两次（还跑一遍桌宠），实测 87~130 秒浮动，
# 用默认 120 秒会随网络状况随机"超时失败"——那种失败看起来像代码问题，
# 但重跑一次就过，纯属噪声。
PER_TEST_TIMEOUT = {
    "verify_public_clone": 420,
    "verify_clone_icon_loads": 420,
    "verify_remote_icons": 300,
    "verify_update_zip": 300,
    "verify_fresh_clone": 300,
    "verify_asset_origin": 300,
    "selftest_whisper_live": 300,
}

# 这些需要真实环境/联网/打包产物，默认不跑（可用 --only 单独跑）
SLOW_OR_ENV = ("selftest_whisper_live", "selftest_standalone", "verify_push",
               "verify_remote_fix", "verify_upstream_webm", "verify_update_zip",
               "verify_fresh_clone", "check_ps1")


def discover():
    names = []
    for entry in sorted(os.listdir(HERE)):
        if not entry.endswith(".py"):
            continue
        if entry.startswith("selftest_") or entry.startswith("verify_"):
            if entry in ("selftest_stream_runtime.py",):
                continue          # 这个自己会起桌宠、跑得久，单独跑
            names.append(entry[:-3])
    return names


def main():
    argv = sys.argv[1:]
    if "--list" in argv:
        for name in discover():
            print("  %s" % name)
        return 0

    names = discover()
    if "--only" in argv:
        wanted = argv[argv.index("--only") + 1:]
        names = [n for n in names if any(w in n for w in wanted)]
    for key in argv:
        if key.startswith("--exclude="):
            for word in key.split("=", 1)[1].split(","):
                names = [n for n in names if word not in n]
    if "--all" not in argv:
        names = [n for n in names if n not in SLOW_OR_ENV]

    print()
    print("  批量自检：%d 个脚本（串行）" % len(names))
    print("  " + "=" * 74)
    results = []
    started_all = time.time()
    for index, name in enumerate(names):
        path = os.path.join(HERE, name + ".py")
        limit = PER_TEST_TIMEOUT.get(name, DEFAULT_TIMEOUT)
        started = time.time()
        try:
            done = subprocess.run([PYTHON, "-X", "utf8", path], cwd=ROOT,
                                  capture_output=True, text=True,
                                  timeout=limit)
            code = done.returncode
            output = (done.stdout or "") + (done.stderr or "")
        except subprocess.TimeoutExpired:
            code = -9
            output = "超时 %d 秒" % limit
        elapsed = time.time() - started
        results.append((name, code, elapsed, output))
        mark = "[通过]" if code == 0 else "[失败]"
        print("  %2d/%2d %s %-38s %5.1f 秒"
              % (index + 1, len(names), mark, name, elapsed))

    passed = [r for r in results if r[1] == 0]
    failed = [r for r in results if r[1] != 0]
    print()
    print("  汇总")
    print("  " + "=" * 74)
    print("     通过 %d / %d，用时 %.1f 秒" % (len(passed), len(results),
                                              time.time() - started_all))
    if failed:
        print()
        print("  失败明细")
        print("  " + "-" * 74)
        for name, code, elapsed, output in failed:
            print("  --- %s（退出码 %s）---" % (name, code))
            lines = [line for line in output.splitlines()
                     if line.strip() and not line.startswith("  [OK]")]
            for line in lines[-14:]:
                print("      " + line[:150])
            print()
        print("  结论: 有 %d 个失败" % len(failed))
        return 1
    print("  结论: 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
