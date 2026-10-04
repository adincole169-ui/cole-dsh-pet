# -*- coding: utf-8 -*-
"""查一个进程在 Windows 上到底有没有顶层窗口、位置在哪。

Qt 的 `isVisible()` 只说"我没隐藏自己"，**不代表窗口真的在屏幕上**：分层/透明窗口
在 CreateWindow 失败、被 DWM 丢弃或从未 ShowWindow 时，Qt 侧依然会报可见。
所以判断"宠物在不在"必须落到 Win32 的窗口枚举上。

    python tools/probe_window.py <pid>
"""

import ctypes
import ctypes.wintypes as wintypes
import sys

user32 = ctypes.windll.user32

EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def describe(hwnd):
    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    style = user32.GetWindowLongW(hwnd, -16)   # GWL_STYLE
    exstyle = user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
    return {
        "hwnd": hwnd,
        "title": buffer.value,
        "visible": bool(user32.IsWindowVisible(hwnd)),
        "iconic": bool(user32.IsIconic(hwnd)),
        "rect": (rect.left, rect.top, rect.right, rect.bottom),
        "size": (rect.right - rect.left, rect.bottom - rect.top),
        "topmost": bool(exstyle & 0x00000008),      # WS_EX_TOPMOST
        "layered": bool(exstyle & 0x00080000),      # WS_EX_LAYERED
        "toolwindow": bool(exstyle & 0x00000080),   # WS_EX_TOOLWINDOW
        "style": hex(style & 0xFFFFFFFF),
        "exstyle": hex(exstyle & 0xFFFFFFFF),
    }


def main(argv):
    target = int(argv[1]) if len(argv) > 1 else 0
    if not target:
        print("用法: probe_window.py <pid>")
        return 2

    found = []

    def callback(hwnd, _param):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == target:
            found.append(describe(hwnd))
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)

    print("PID %d 的顶层窗口: %d 个" % (target, len(found)))
    for info in found:
        print("  hwnd=%s 标题=%r" % (info["hwnd"], info["title"]))
        print("    可见=%s 最小化=%s 置顶=%s 分层=%s 工具窗=%s"
              % (info["visible"], info["iconic"], info["topmost"],
                 info["layered"], info["toolwindow"]))
        print("    物理矩形=%s 尺寸=%s" % (info["rect"], info["size"]))
        print("    style=%s exstyle=%s" % (info["style"], info["exstyle"]))
    if not found:
        print("  **没有任何顶层窗口** —— 进程活着，但屏幕上没有它的窗口")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
