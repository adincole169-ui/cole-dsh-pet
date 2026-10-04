# -*- coding: utf-8 -*-
"""开机自启：写/删当前用户的 Run 项。

    python tools/autostart.py on      # 注册开机自启
    python tools/autostart.py off     # 取消
    python tools/autostart.py status  # 查看

用 `HKCU\\...\\Run` 而不是启动文件夹快捷方式：前者一个注册表值就能读写与查询，
出问题时也容易一眼看出目标路径对不对。
"""

import os
import sys

try:
    import winreg
except ImportError:  # 非 Windows
    winreg = None

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "DshPet"


def _target():
    """优先用 pythonw（无控制台窗口），找不到就退回 python。"""
    interpreter = sys.executable
    folder = os.path.dirname(interpreter)
    for name in ("pythonw.exe", "python.exe"):
        candidate = os.path.join(folder, name)
        if os.path.exists(candidate):
            interpreter = candidate
            if name == "pythonw.exe":
                break
    # 指向 `run_logged.py` 而不是 `main.py`：前者会把输出与**退出码**写进
    # `logs/pet-run.log`，并在非零退出（崩溃/被杀）时自动重启。直接起 main.py
    # 的话，`pythonw` 下崩溃连 traceback 都留不下——"点一下宠物就没了"当初就是
    # 因为这个查不出原因。
    return '"%s" "%s"' % (interpreter, os.path.join(ROOT, "tools", "run_logged.py"))


def enable():
    if winreg is None:
        return "这个功能只在 Windows 上可用"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, VALUE, 0, winreg.REG_SZ, _target())
    return "已注册开机自启:\n  %s" % _target()


def disable():
    if winreg is None:
        return "这个功能只在 Windows 上可用"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE)
        return "已取消开机自启"
    except FileNotFoundError:
        return "本来就没有注册"


def status():
    if winreg is None:
        return "这个功能只在 Windows 上可用"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as key:
            value, _kind = winreg.QueryValueEx(key, VALUE)
        return "开机自启已启用:\n  %s" % value
    except FileNotFoundError:
        return "开机自启未启用"


def main(argv):
    action = (argv[1] if len(argv) > 1 else "status").lower()
    if action == "on":
        print(enable())
    elif action == "off":
        print(disable())
    else:
        print(status())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
