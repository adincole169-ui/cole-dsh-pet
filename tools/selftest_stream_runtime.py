# -*- coding: utf-8 -*-
"""实机验证 stream 模式：起桌宠 → 看是否持续有帧 → 数 ffmpeg 进程与 CPU → 收干净。

这是换帧来源之后最关键的一关。前面各层都单独测过了
（tools/probe_stream_loop.py 验证循环与像素、src/stream_frames.py 自检验证缓冲），
但只有把桌宠真正跑起来才能确认：

  1. 动画链正常轮换（不是卡在一个动画上不动）
  2. **每一秒都画得出帧**（`--watch` 日志的 frame=True）—— 这是"宠物不会消失"的判据
  3. **ffmpeg 进程数有界** —— 环形缓冲/淘汰没做好就会一路泄漏
  4. **CPU 占用可接受**（顺带把收益量化出来）
  5. 日志里没有"准备失败 / 取不到帧"
  6. 退出后**没有 ffmpeg 残留**

用 **psutil** 而不是起 shell：本机的 Python 子进程 PATH 里**没有 pwsh**
（实测 FileNotFoundError），而 `powershell.exe` 有；psutil 更干净，还能读命令行
（"只杀桌宠自己的进程"要靠它）与 CPU 时间。

    python tools/selftest_stream_runtime.py            # 默认观察 22 秒
    python tools/selftest_stream_runtime.py --seconds 40
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PYTHONW = r"D:\python\anaconda\pythonw.exe"
WATCH_LOG = os.path.join(ROOT, "logs", "watch.log")
RUN_LOG = os.path.join(ROOT, "logs", "pet-run.log")
HEALTH = "http://127.0.0.1:8899/health"
DEBUG = "http://127.0.0.1:8899/debug"
PET_MATCH = re.compile(r"main\.py|run_logged", re.IGNORECASE)
FFMPEG_NAMES = ("ffmpeg.exe", "ffmpeg")


def processes():
    import psutil
    found = []
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            found.append((process.info["pid"], process.info["name"] or "",
                          " ".join(process.info["cmdline"] or [])))
        except Exception:
            continue
    return found


def pet_pids():
    """**只**匹配桌宠自己的进程，不做全量杀 python。"""
    return [pid for pid, _name, cmd in processes() if cmd and PET_MATCH.search(cmd)]


def ffmpeg_pids():
    return [pid for pid, name, _cmd in processes()
            if name.lower() in FFMPEG_NAMES]


def cpu_seconds(pids):
    import psutil
    total = 0.0
    for pid in pids:
        try:
            process = psutil.Process(pid)
            times = process.cpu_times()
            total += times.user + times.system
        except Exception:
            continue
    return total


def kill_pids(pids):
    import psutil
    for pid in pids:
        try:
            psutil.Process(pid).kill()
        except Exception:
            pass


def api(url, timeout=4):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def main():
    argv = sys.argv[1:]
    seconds = int(argv[argv.index("--seconds") + 1]) if "--seconds" in argv else 22
    try:
        import psutil                                                # noqa: F401
    except ImportError:
        print("  需要 psutil：pip install psutil")
        return 1

    print()
    print("  stream 模式实机自检（观察 %d 秒）" % seconds)
    print("  " + "=" * 74)

    # 清场
    kill_pids(pet_pids())
    time.sleep(2)
    leftover = ffmpeg_pids()
    if leftover:
        print("  启动前有 %d 个 ffmpeg 残留，清掉" % len(leftover))
        kill_pids(leftover)
        time.sleep(1)

    for path in (WATCH_LOG, RUN_LOG):
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass

    started = time.time()
    process = subprocess.Popen(
        [PYTHONW, "-X", "utf8", os.path.join(ROOT, "tools", "run_logged.py"), "--watch"],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("  已启动桌宠（包装 PID %d）" % process.pid)

    ready = None
    deadline = time.time() + 40
    while time.time() < deadline:
        if api(HEALTH) is not None:
            ready = time.time() - started
            break
        time.sleep(0.4)
    if ready is None:
        print("  **40 秒内 /health 无应答** —— 启动失败，日志尾部：")
        if os.path.isfile(RUN_LOG):
            with open(RUN_LOG, "r", encoding="utf-8", errors="replace") as handle:
                for line in handle.readlines()[-15:]:
                    print("     " + line.rstrip())
        kill_pids(pet_pids())
        return 1
    print("  /health 就绪（%.1f 秒）" % ready)

    # CPU 基线
    base_pet_cpu = cpu_seconds(pet_pids())
    base_ff_cpu = cpu_seconds(ffmpeg_pids())
    base_wall = time.time()

    print()
    print("  %-5s %-22s %-7s %-7s %-7s %-7s %s"
          % ("秒", "正在播", "cached", "loading", "reloads", "ffmpeg", "帧"))
    print("  " + "-" * 74)

    seen = []
    max_ffmpeg = 0
    debug_failures = 0
    frame_seen = None
    for index in range(seconds):
        data = api(DEBUG)
        count = len(ffmpeg_pids())
        max_ffmpeg = max(max_ffmpeg, count)
        # 从 --watch 日志读"这一秒有没有画出帧"
        drawn = None
        if os.path.isfile(WATCH_LOG):
            try:
                with open(WATCH_LOG, "r", encoding="utf-8", errors="replace") as handle:
                    tail = handle.readlines()[-1:]
                if tail and "frame=" in tail[0]:
                    drawn = "frame=True" in tail[0]
            except OSError:
                pass
        if drawn is not None:
            frame_seen = drawn if frame_seen is None else (frame_seen or drawn)
        if data:
            playing = data.get("playing")
            if playing and (not seen or seen[-1] != playing):
                seen.append(playing)
            print("  %-5d %-22s %-7d %-7d %-7d %-7d %s"
                  % (index + 1, (playing or "-")[:22],
                     len(data.get("cached") or []),
                     len(data.get("loading") or []),
                     data.get("reloads") or 0, count,
                     "有" if drawn else ("?" if drawn is None else "**无**")))
        else:
            debug_failures += 1
            print("  %-5d **/debug 无应答**" % (index + 1))
        time.sleep(1)

    wall = time.time() - base_wall
    pet_cpu = cpu_seconds(pet_pids()) - base_pet_cpu
    ff_cpu = cpu_seconds(ffmpeg_pids()) - base_ff_cpu

    # 统计 --watch 里的 frame=True/False
    frame_true = frame_false = 0
    if os.path.isfile(WATCH_LOG):
        with open(WATCH_LOG, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if "frame=True" in line:
                    frame_true += 1
                elif "frame=False" in line:
                    frame_false += 1

    failures = []
    if os.path.isfile(RUN_LOG):
        with open(RUN_LOG, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if any(key in line for key in ("准备失败", "取不到帧", "起流失败",
                                               "流式失败", "Traceback", "Error")):
                    failures.append(line.rstrip())

    print()
    print("  结果")
    print("  " + "=" * 74)
    print("     观察时长           : %.0f 秒" % wall)
    print("     轮换到的动画       : %d 个 —— %s"
          % (len(seen), "、".join(seen[:8]) or "(无)"))
    print("     --watch 画帧统计   : frame=True %d 次，frame=False %d 次"
          % (frame_true, frame_false))
    print("     /debug 无应答      : %d 次" % debug_failures)
    print("     ffmpeg 进程峰值    : %d" % max_ffmpeg)
    print("     CPU 占用           : 桌宠 %.1f%%（%.2f 秒 / %.0f 秒），"
          "ffmpeg 合计 %.1f%%（%.2f 秒）"
          % (100.0 * pet_cpu / wall, pet_cpu, wall,
             100.0 * ff_cpu / wall, ff_cpu))
    print("     失败日志           : %d 条" % len(failures))
    for line in failures[:5]:
        print("        " + line[:100])

    print()
    print("  正在停止桌宠 ...")
    kill_pids(pet_pids())
    time.sleep(3)
    residue = ffmpeg_pids()
    print("  退出后残留 ffmpeg  : %d" % len(residue))

    # **断言零磁盘占用**：stream 模式的承诺就是"不留帧"。早期 `_load_sync` 漏改
    # 的时候，自检跑完会在 frames/ 里偷偷留下 564 MB —— 而桌宠本体看起来完全正常，
    # 只有这一条能抓住它。所以必须断言，不能只打印。
    cache_dir = os.path.join(ROOT, "frames")
    cache_files = 0
    cache_bytes = 0
    if os.path.isdir(cache_dir):
        for base, _dirs, files in os.walk(cache_dir):
            for name in files:
                cache_files += 1
                try:
                    cache_bytes += os.path.getsize(os.path.join(base, name))
                except OSError:
                    pass
    print("  零磁盘占用         : frames/ %s（%d 个文件，%.1f MB）"
          % ("不存在" if not os.path.isdir(cache_dir) else "存在",
             cache_files, cache_bytes / 1048576.0))

    print()
    print("  判读")
    print("  " + "-" * 74)
    problems = []
    if frame_true == 0:
        problems.append("**从没画出过帧** —— 宠物会是不可见的")
    elif frame_false > max(3, frame_true // 5):
        problems.append("frame=False 偏多（%d 次），可能有断帧" % frame_false)
    if not seen:
        problems.append("**没有轮换过任何动画** —— 状态机没跑起来")
    if max_ffmpeg > 8:
        problems.append("**ffmpeg 进程峰值 %d 个** —— 超出预期（缓冲/淘汰可能有问题）"
                        % max_ffmpeg)
    if failures:
        problems.append("日志里有 %d 条失败" % len(failures))
    if residue:
        problems.append("**退出后残留 %d 个 ffmpeg** —— 进程没收干净" % len(residue))
    if cache_files:
        problems.append("**frames/ 里出现了 %d 个文件（%.1f MB）** —— "
                        "有入口绕过了流式路径去解码写盘（查 FrameStore._load_sync）"
                        % (cache_files, cache_bytes / 1048576.0))

    if problems:
        for item in problems:
            print("     [问题] " + item)
        print()
        print("  结论: 有 %d 项需要处理" % len(problems))
        return 1
    print("     [OK] 帧持续可见、动画正常轮换、ffmpeg 进程有界、退出无残留")
    print("     [OK] 零磁盘占用：frames/ 不存在，缓存没有偷偷被建回来")
    print("     [OK] CPU：桌宠 %.1f%% + ffmpeg %.1f%%" % (
        100.0 * pet_cpu / wall, 100.0 * ff_cpu / wall))
    print()
    print("  结论: 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
