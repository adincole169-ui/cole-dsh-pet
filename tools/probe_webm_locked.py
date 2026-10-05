# -*- coding: utf-8 -*-
"""实测：桌宠运行时，webm 素材是否被占用 —— 也就是 `git pull` 能不能覆盖它们。

为什么值得测：**流式模式（新）让这个问题第一次出现**。
`stream` 模式下每个在用的动画都挂着一个常驻 ffmpeg，它把 `webm/<动画>.webm`
**一直开着读**（`-stream_loop -1` 让它无限循环）。而 Windows 上"被别的进程打开、
且没共享写权限"的文件**无法被替换** —— `git pull` 更新素材时会报
`error: unable to unlink old ...: Permission denied`，而那个报错看起来像权限问题，
很难联想到"是宠物还开着"。

对比：旧的 `cache` 模式只在解码那一瞬间读 webm，之后不再持有 —— 所以这个坑是新引入的。

做法：对每个 `webm/*.webm` 试着以 **r+b** 打开（只打开、不写入、不截断，因此不会
破坏内容）。被占用会抛 PermissionError。

    python tools/probe_webm_locked.py
"""

import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WEBM = os.path.join(ROOT, "webm")


def api(path, timeout=4):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8899" + path, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def main():
    print()
    print("  实测：运行时 webm 是否被占用（决定 git pull 能否覆盖素材）")
    print("  " + "=" * 74)

    health = api("/health")
    if health is None:
        print("  桌宠没在跑 —— 无法验证。先启动它再跑本脚本。")
        return 1

    debug = api("/debug") or {}
    cached = debug.get("cached") or []
    playing = debug.get("playing")
    names = list(dict.fromkeys([playing] + cached)) if playing else list(cached)
    print("  桌宠在跑；当前在播「%s」，内存里还持有 %d 个动画" % (playing, len(cached)))
    print()

    # 先看正在播的那个（最可能被占用）
    locked = []
    free = []
    for name in names:
        if not name:
            continue
        path = os.path.join(WEBM, name + ".webm")
        if not os.path.isfile(path):
            continue
        try:
            # r+b：只打开，不写、不截断。被占用会抛 PermissionError
            with open(path, "r+b"):
                pass
            free.append(name)
        except PermissionError:
            locked.append(name)
        except OSError as error:
            locked.append("%s（%s）" % (name, error.__class__.__name__))

    print("  %-24s %s" % ("正在用的动画", "文件可否被覆盖"))
    print("  " + "-" * 74)
    for name in names:
        if not name:
            continue
        mark = "**被占用（无法覆盖）**" if name in locked else "可覆盖"
        print("  %-24s %s" % (name[:24], mark))

    print()
    print("  结论（第一层：能否以写入方式打开）")
    print("  " + "=" * 74)
    print("     被占用的动画 %d 个，可覆盖 %d 个" % (len(locked), len(free)))
    if not locked:
        print("     -> 只说明 ffmpeg 允许**写入共享**（SHARE_WRITE）。")
        print("        **但这还不够** —— git 覆盖文件用的是**替换**（unlink + rename），")
        print("        那需要的是**删除共享**（SHARE_DELETE），是另一个标志位。")

    # --- 第二层：真正的替换操作 ---
    # `git pull` 更新文件走的是"删掉旧的、换上新的"，所以必须单独验 SHARE_DELETE。
    # 用 os.replace(同内容临时文件, 原文件)：字节完全相同，因此**不会破坏素材**，
    # 但走的是和 git 一样的"替换"路径。
    print()
    print("  第二层：真正的替换操作（等价于 git 覆盖文件）")
    print("  " + "-" * 74)
    import shutil
    import tempfile
    replaced = []
    blocked = []
    for name in names:
        if not name:
            continue
        path = os.path.join(WEBM, name + ".webm")
        if not os.path.isfile(path):
            continue
        before = os.path.getsize(path)
        handle, temp = tempfile.mkstemp(suffix=".webm", dir=WEBM)
        os.close(handle)
        try:
            shutil.copyfile(path, temp)          # 同内容副本
            os.replace(temp, path)               # 替换（git 的路径）
            after = os.path.getsize(path)
            if before == after:
                replaced.append(name)
            else:
                blocked.append("%s（大小变了 %d->%d）" % (name, before, after))
        except PermissionError:
            blocked.append(name)
            try:
                os.remove(temp)
            except OSError:
                pass
        except OSError as error:
            blocked.append("%s（%s）" % (name, error.__class__.__name__))
            try:
                os.remove(temp)
            except OSError:
                pass

    print("     可被替换 %d 个，被拒绝 %d 个" % (len(replaced), len(blocked)))
    if blocked:
        for item in blocked[:6]:
            print("       **%s**" % item)

    print()
    print("  最终结论")
    print("  " + "=" * 74)
    if blocked:
        print("     **桌宠运行时，正在使用的 webm 无法被替换。**")
        print("     `git pull` 更新这些素材时会报：")
        print("       error: unable to unlink old 'webm/xxx.webm': Permission denied")
        print("     那个报错看起来像权限问题，很难联想到「宠物还开着」。")
        print()
        print("     **正确做法：先退出桌宠 -> git pull -> 再启动。**")
    else:
        print("     **桌宠运行时也能安全替换 webm** —— ffmpeg 以共享方式打开输入文件，")
        print("     允许删除/替换（SHARE_DELETE）。所以 `git pull` 不会被挡住；")
        print("     ffmpeg 手里那个句柄继续读旧数据，宠物照常播到重启为止。")
        print()
        print("     不过仍然建议更新前退出桌宠：")
        print("       * 代码是启动时加载的，不重启不会生效；")
        print("       * 更新到一半时素材新旧混着，画面可能不连贯。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
