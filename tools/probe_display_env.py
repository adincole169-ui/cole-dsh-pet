# -*- coding: utf-8 -*-
"""诊断：这个程序到底能"适配"多少种显示环境。

用户问："现在的版本是可以适配任何显示环境吗"。这个问题有三层，每层都能量：

  ① **Windows 眼里的显示模式**（`EnumDisplaySettings`）—— 权威值；
  ② **本进程看到的**（`GetSystemMetrics` 与 Qt 的 QScreen）—— 被 DPI 虚拟化时会与 ①不同；
  ③ **进程的 DPI 感知级别**（`GetProcessDpiAwareness`）：
        0 = UNAWARE        —— Windows 会把整个窗口**拉伸**显示（发虚），
                              并且给进程一个**虚拟化过的小坐标空间**；
        1 = SYSTEM_AWARE   —— 只在登录时感知 DPI，跨屏拖动时可能错位；
        2 = PER_MONITOR    —— 每块屏各自正确。

①与②不一致、或 ③不为 2，就说明"换一个缩放/分辨率的环境"时会有问题 ——
那正是"以为屏幕只有 1280×720、宠物只能放在左上角"那次事故的成因。

    python tools/probe_display_env.py
"""

import ctypes
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

# 注意：**不要**设 `QT_QPA_PLATFORM=offscreen`。第一版设了，于是 Qt 报的是它自己的
# 默认 800x600，凭空多出两条"与真实模式不一致"的假差异。这个诊断要看的正是
# "Qt 在**真实**平台上看到什么"。

AWARENESS = {
    0: "UNAWARE（Windows 拉伸窗口显示，坐标空间被虚拟化）",
    1: "SYSTEM_AWARE（只在登录时感知 DPI，跨屏可能错位）",
    2: "PER_MONITOR_AWARE（每块屏各自正确）",
}


def windows_mode():
    """Windows 认为的当前显示模式（宽, 高, 刷新率）。"""
    class DEVMODE(ctypes.Structure):
        _fields_ = [("dmDeviceName", ctypes.c_wchar * 32),
                    ("dmSpecVersion", ctypes.c_ushort),
                    ("dmDriverVersion", ctypes.c_ushort),
                    ("dmSize", ctypes.c_ushort),
                    ("dmDriverExtra", ctypes.c_ushort),
                    ("dmFields", ctypes.c_ulong),
                    ("dmOrientation", ctypes.c_short),
                    ("dmPaperSize", ctypes.c_short),
                    ("dmPaperLength", ctypes.c_short),
                    ("dmPaperWidth", ctypes.c_short),
                    ("dmScale", ctypes.c_short),
                    ("dmCopies", ctypes.c_short),
                    ("dmDefaultSource", ctypes.c_short),
                    ("dmPrintQuality", ctypes.c_short),
                    ("dmColor", ctypes.c_short),
                    ("dmDuplex", ctypes.c_short),
                    ("dmYResolution", ctypes.c_short),
                    ("dmTTOption", ctypes.c_short),
                    ("dmCollate", ctypes.c_short),
                    ("dmFormName", ctypes.c_wchar * 32),
                    ("dmLogPixels", ctypes.c_ushort),
                    ("dmBitsPerPel", ctypes.c_ulong),
                    ("dmPelsWidth", ctypes.c_ulong),
                    ("dmPelsHeight", ctypes.c_ulong),
                    ("dmDisplayFlags", ctypes.c_ulong),
                    ("dmDisplayFrequency", ctypes.c_ulong),
                    ("dmICMMethod", ctypes.c_ulong),
                    ("dmICMIntent", ctypes.c_ulong),
                    ("dmMediaType", ctypes.c_ulong),
                    ("dmDitherType", ctypes.c_ulong),
                    ("dmReserved1", ctypes.c_ulong),
                    ("dmReserved2", ctypes.c_ulong),
                    ("dmPanningWidth", ctypes.c_ulong),
                    ("dmPanningHeight", ctypes.c_ulong)]
    devmode = DEVMODE()
    devmode.dmSize = ctypes.sizeof(DEVMODE)
    ENUM_CURRENT_SETTINGS = -1
    ok = ctypes.windll.user32.EnumDisplaySettingsW(None, ENUM_CURRENT_SETTINGS,
                                                   ctypes.byref(devmode))
    if not ok:
        return None
    return (devmode.dmPelsWidth, devmode.dmPelsHeight, devmode.dmDisplayFrequency)


def system_metrics():
    """本进程看到的"屏幕尺寸"。

    **绝不能先调 `SetProcessDPIAware()`** —— 第一版就在这里调了，等于把要测的东西
    改掉了：UNAWARE 进程本来会被虚拟化成一个更小的坐标空间（正是"宠物以为屏幕只有
    1280×720"的成因），一调就看不出来了。
    """
    user32 = ctypes.windll.user32
    return (user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))


def dpi_awareness():
    """本进程当前生效的 DPI 感知级别。必须在任何东西改动它之前读。"""
    try:
        value = ctypes.c_int(0)
        ctypes.windll.shcore.GetProcessDpiAwareness(None, ctypes.byref(value))
        return value.value
    except Exception:
        return None


def main():
    print()
    print("  显示环境适配诊断")
    print("  " + "=" * 74)

    mode = windows_mode()
    print("  ① Windows 眼里的显示模式 : %s"
          % ("%dx%d @%dHz" % mode if mode else "(取不到)"))

    # **先读感知级别与虚拟化后的系统尺寸** —— 这两项在任何 Qt/awareness 调用之前读，
    # 否则测到的就不是"桌宠进程实际看到的"了。
    level = dpi_awareness()
    metrics = system_metrics()
    print("  ② 本进程（UNAWARE 时会被虚拟化）")
    print("         GetSystemMetrics     : %dx%d" % metrics)
    print("         DPI 感知级别         : %s"
          % (AWARENESS.get(level, "读不到 (%s)" % level) if level is not None
             else "读不到"))

    # ③ Qt 看到的（**不要**设 offscreen —— 那样 Qt 会报自己的默认 800x600，
    #    第一版就是这么量出一堆假差异的）
    #
    #    **Qt 初始化会改变本进程的 DPI 感知级别**（`QWindowsIntegration` 会去设置它），
    #    所以"初始化前 / 初始化后"要各读一次 —— 只有**初始化后**的那个值才描述
    #    桌宠实际运行时的状态。第一版只读了初始化前那次，于是把桌宠判成了
    #    "UNAWARE"，而它其实不是。
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])      # noqa: F841
    level_after = dpi_awareness()
    metrics_after = system_metrics()
    screens = QApplication.screens()
    print("  ③ Qt 初始化**之后**（这才是桌宠运行时的状态）")
    print("         GetSystemMetrics     : %dx%d" % metrics_after)
    print("         DPI 感知级别         : %s"
          % (AWARENESS.get(level_after, "读不到 (%s)" % level_after)
             if level_after is not None else "读不到"))
    print("  ④ Qt 看到的屏            : %d 块" % len(screens))
    for index, screen in enumerate(screens):
        geo = screen.geometry()
        avail = screen.availableGeometry()
        print("        屏 %d %-14s geometry %dx%d  可用 (%d,%d) %dx%d  DPR %.2f  logicalDpi %.0f"
              % (index, screen.name() or "?", geo.width(), geo.height(),
                 avail.x(), avail.y(), avail.width(), avail.height(),
                 screen.devicePixelRatio(), screen.logicalDotsPerInchX()))

    print()
    print("  判读")
    print("  " + "-" * 74)
    problems = []
    if mode:
        # **只把"Qt 初始化之后"的值当成问题判据。** 初始化前那次读到的
        # 2048x1152 / UNAWARE 是"还没有 Qt"的状态，桌宠运行时并不是那样 ——
        # 第一版把它当成问题报出来，纯属假警报。
        if metrics_after != (mode[0], mode[1]):
            problems.append("Qt 初始化后进程看到的 %dx%d 与真实模式 %dx%d 不一致 —— "
                            "坐标空间被虚拟化（就是「宠物只能放在左上角」那次的成因）"
                            % (metrics_after[0], metrics_after[1], mode[0], mode[1]))
        else:
            print("  OK   （Qt 之后）进程看到的尺寸与真实模式一致")
        if screens:
            geo = screens[0].geometry()
            if (geo.width(), geo.height()) != (mode[0], mode[1]):
                problems.append("Qt 看到的 %dx%d 与真实模式 %dx%d 不一致"
                                % (geo.width(), geo.height(), mode[0], mode[1]))
            else:
                print("  OK   Qt 看到的尺寸与真实模式一致")
    if level_after is not None and level_after != 2:
        problems.append("运行时的 DPI 感知级别不是 PER_MONITOR（当前 %s）—— "
                        "**正在运行时改缩放、或换到另一块不同 DPI 的屏**，进程不会跟上，"
                        "坐标空间会与实际不符（就是「宠物只能放在左上角」那次的成因）；"
                        "重启即恢复" % AWARENESS.get(level_after, level_after))
    elif level_after == 2:
        print("  OK   DPI 感知级别是 PER_MONITOR（每块屏各自正确）")
    if len(screens) < 2:
        print("  ** 注意：当前只有 %d 块屏，多显示器路径**没有被本次诊断覆盖**" % len(screens))

    print()
    if problems:
        for item in problems:
            print("     [问题] %s" % item)
        return 1
    print("  结论：本次环境下的显示参数一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
