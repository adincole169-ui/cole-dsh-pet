# -*- coding: utf-8 -*-
"""找回大肥鱼：看不见它的时候双击这个。

为什么需要它
------------
Qt 的分层透明窗口偶尔会**合成失败**：窗口对象还在、还在 Z 序顶部、还能收到点击
（`WindowFromPoint` 会返回它），但屏幕上画出来是透明的——看起来就是"宠物不见了"。
这时只要让它重新显示一次，通常就恢复了，不需要重启进程。

用 Python 而不是 .bat + PowerShell：批处理里的引号转义和中文注释混在一起极易写坏
（这个脚本的前一版就是这么坏的）。Python 里这些都是普通字符串。

双击本文件；它不会留下控制台窗口（.pyw 用 pythonw 运行）。
"""

import json
import os
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8899


def call(path, payload=None, timeout=4):
    url = "http://127.0.0.1:%d%s" % (PORT, path)
    if payload is None:
        with urlopen(url, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    body = json.dumps(payload).encode("utf-8")
    request = Request(url, data=body, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def find_interpreter():
    """优先 pythonw（无控制台窗口）。"""
    folder = os.path.dirname(sys.executable)
    for name in ("pythonw.exe", "python.exe"):
        candidate = os.path.join(folder, name)
        if os.path.exists(candidate):
            return candidate
    return sys.executable


def start_pet():
    """启动桌宠。

    要走 `tools/run_logged.py` 而不是 `main.py`：前者才带崩溃日志与自动重启。
    直接起 main.py 的话，`pythonw` 下崩溃不留任何痕迹——"点一下就没了"当初就是
    因为这个查不出原因，不该在恢复路径上又留一个同样的缺口。
    """
    interpreter = find_interpreter()
    creation = 0x00000008 | 0x00000200 if hasattr(subprocess, "DETACHED_PROCESS") else 0
    wrapper = os.path.join(HERE, "tools", "run_logged.py")
    target = wrapper if os.path.exists(wrapper) else os.path.join(HERE, "main.py")
    subprocess.Popen([interpreter, "-X", "utf8", target],
                     cwd=HERE, creationflags=creation,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    try:
        health = call("/health")
    except (URLError, OSError):
        print("大肥鱼没有在运行，正在启动…")
        start_pet()
        for _ in range(20):
            time.sleep(1)
            try:
                health = call("/health")
                break
            except (URLError, OSError):
                continue
        else:
            print("启动后仍未响应，请手动运行 main.py 看看报错。")
            return 1
        print("已启动。")
        return 0

    # 已经在跑：搬到屏幕正中并抬到最前
    try:
        call("/place", {"center": True})
        time.sleep(0.5)
        health = call("/health")
    except (URLError, OSError) as error:
        print("搬动失败（服务在但请求出错）：%s" % error)
        return 1

    print("已把大肥鱼搬回屏幕正中（当前动作：%s，状态：%s）"
          % (health.get("playing"), health.get("mood")))
    print("如果还是看不到，运行这段排查：")
    print("  python tools\\probe_window.py <pid>   # 有没有窗口")
    print("  python tools\\probe_hit.py  800 900 <pid>  # 那块像素归谁")
    return 0


if __name__ == "__main__":
    sys.exit(main())
