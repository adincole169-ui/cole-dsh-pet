# -*- coding: utf-8 -*-
"""看当前有几只在跑（**正确的过滤条件**）。

为什么要单独写一个：我用 `cmdline 里含 'main.py' 或 'run_logged'` 去数，
结果把自己**工具调用**的进程也数了进去 —— DSH 的 `dsh-subprocess-local` 助手、
powershell、以及我那条 `python -c` 的命令行文本里都含有 "main.py"，
于是 2 只被数成 6 只，还误报成"越积越多"。

正确的判据是**看解释器与脚本路径**，而不是在整条命令行里搜关键字：

    pythonw.exe  -X utf8  E:\\dsh\\pet\\tools\\run_logged.py  --watch
    pythonw.exe  -X utf8  E:\\dsh\\pet\\main.py               --watch

    python tools/probe_pet_instances.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

SCRIPT_MAIN = os.path.join(ROOT, "main.py").lower()
SCRIPT_WRAP = os.path.join(HERE, "run_logged.py").lower()

# 只有这两个解释器才会是我们的进程；DSH 助手是 "DeepSeek Harness.exe"，
# 工具外壳是 powershell.exe —— 按**进程名**先把它们排掉。
OUR_NAMES = ("pythonw.exe", "python.exe")


def main():
    try:
        import psutil
    except ImportError:
        print("  需要 psutil")
        return 1

    found = []
    for proc in psutil.process_iter(["pid", "ppid", "name", "cmdline",
                                     "create_time", "memory_info"]):
        try:
            name = (proc.info["name"] or "").lower()
            if name not in OUR_NAMES:
                continue
            cmd = [c for c in (proc.info["cmdline"] or [])]
            lowered = [c.lower() for c in cmd]
            if SCRIPT_MAIN in lowered:
                kind = "桌宠 main.py"
            elif SCRIPT_WRAP in lowered:
                kind = "包装 run_logged"
            else:
                continue
            found.append((kind, proc.info))
        except Exception:
            pass

    print()
    print("  当前运行中的桌宠进程（按脚本路径判定，不是搜关键字）")
    print("  " + "=" * 74)
    for kind, info in sorted(found, key=lambda x: x[0]):
        print("  %-16s PID %-7d PPID %-7d RSS %4.0f MB"
              % (kind, info["pid"], info["ppid"],
                 info["memory_info"].rss / 1048576))

    pets = [f for f in found if f[0].startswith("桌宠")]
    wraps = [f for f in found if f[0].startswith("包装")]

    # ffmpeg：stream 模式下**每个已加载的动画各一个**，`keep=6` 所以最多 6 个左右
    ffmpeg = []
    for proc in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            if (proc.info["name"] or "").lower() == "ffmpeg.exe":
                ffmpeg.append(proc.info)
        except Exception:
            pass

    total_mb = sum(i["memory_info"].rss for _k, i in found) / 1048576.0
    total_mb += sum(i["memory_info"].rss for i in ffmpeg) / 1048576.0

    print()
    print("  汇总")
    print("  " + "=" * 74)
    print("  桌宠进程: %d 只（期望 1）" % len(pets))
    print("  包装层  : %d 个（期望 1）" % len(wraps))
    print("  ffmpeg  : %d 个（stream 模式下每个已加载动画一个，keep=6 上限约 6）"
          % len(ffmpeg))
    print("  合计内存: %.0f MB" % total_mb)

    bad = len(pets) != 1
    print()
    if bad:
        print("  结论：**桌宠进程数不是 1**，需要清理（注意 `run_logged.py` 是看门狗：")
        print("        只杀 main.py 的话它会把子进程重新拉起来）。")
        return 1
    print("  结论：**正常**（1 只桌宠 + 1 个包装层）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
