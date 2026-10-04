# -*- coding: utf-8 -*-
"""问 Windows：某个屏幕坐标上，最顶层的窗口是谁的。

这是区分"宠物被别的窗口压住"和"宠物窗口是透明的"最直接的判据：
`WindowFromPoint` 返回的是**真正会收到该点点击**的那个窗口。

    python tools/probe_hit.py <x> <y> [期望的pid]
"""

import ctypes
import sys

user32 = ctypes.windll.user32


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def title_of(hwnd):
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def pid_of(hwnd):
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def root_of(hwnd):
    """一路向上取顶层窗口（GA_ROOT = 2）。"""
    return user32.GetAncestor(hwnd, 2) or hwnd


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    x, y = int(argv[1]), int(argv[2])
    expect = int(argv[3]) if len(argv) > 3 else None

    point = POINT(x, y)
    hwnd = user32.WindowFromPoint(point)
    print("  屏幕点 (%d, %d)" % (x, y))
    if not hwnd:
        print("  该点没有任何窗口")
        return 0

    top = root_of(hwnd)
    info = []
    for label, handle in (("命中窗口", hwnd), ("顶层窗口", top)):
        info.append((label, handle, title_of(handle), pid_of(handle)))
        print("  %s: hwnd=%s pid=%s 标题=%r" % (label, handle, pid_of(handle), title_of(handle)))

    if expect is not None:
        if pid_of(top) == expect:
            print("  => 该点最顶层就是目标进程（宠物能收到这里的点击）")
        else:
            print("  => 该点被 pid=%s 挡着，**不是**宠物（pid=%s）"
                  % (pid_of(top), expect))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
