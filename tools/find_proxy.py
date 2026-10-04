# -*- coding: utf-8 -*-
"""找出本机可用的代理端口，并给出 git 该配什么。

现象：`git ls-remote https://github.com/...` 报 `Recv failure: Connection was reset`，
而机器上跑着 clash-verge / verge-mihomo —— 典型的"有代理但 git 没走代理"。

本脚本不猜端口，而是：
  1. 读系统代理设置（注册表 Internet Settings）；
  2. 实测常见本地代理端口（7890/7897/10809/1080/8080 等）哪一个在监听；
  3. 用找到的端口实际请求一次 GitHub，确认真的能用；
  4. 打印该给 git 配的命令。

    python tools/find_proxy.py
"""

import os
import socket
import sys
import urllib.error
import urllib.request

CANDIDATES = [7890, 7897, 7891, 10809, 10808, 1080, 8080, 8118, 20171, 33210]


def listening(port, host="127.0.0.1", timeout=0.4):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def read_system_proxy():
    """读 Windows 的 Internet Settings（不依赖 winreg 以外的东西）。"""
    try:
        import winreg
    except ImportError:
        return None
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
        enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
        if not enable:
            return None
        server, _ = winreg.QueryValueEx(key, "ProxyServer")
        return server
    except Exception:
        return None


def try_github(port):
    """用指定端口请求一次 GitHub API，返回 (成功, 说明)。"""
    proxy = "http://127.0.0.1:%d" % port
    handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    opener = urllib.request.build_opener(handler)
    request = urllib.request.Request(
        "https://api.github.com/rate_limit",
        headers={"User-Agent": "dsh-pet-proxy-check"})
    try:
        with opener.open(request, timeout=15) as response:
            return True, "HTTP %d" % response.status
    except urllib.error.HTTPError as error:
        # 有 HTTP 响应就说明连通了（403 多半是代理出口被限流或需要认证）
        return True, "HTTP %d（能连通，但被拒绝）" % error.code
    except Exception as error:
        return False, str(error)[:80]


def main():
    print()
    print("  代理排查")
    print("  " + "=" * 58)

    system = read_system_proxy()
    print("    系统代理(Internet Settings): %s" % (system if system else "未启用"))

    print()
    print("  正在探测常见本地代理端口")
    print("  " + "-" * 58)
    alive = []
    for port in CANDIDATES:
        if listening(port):
            alive.append(port)
            print("     %-6d 在监听" % port)
        else:
            print("     %-6d 无" % port)

    if not alive:
        print()
        print("  **没有发现本地代理端口。**")
        print("  如果 clash-verge 用的是别的端口，请打开它的界面看「端口」设置，")
        print("  或者把端口填进下面的命令里。")
        return 1

    print()
    print("  实测哪个端口能连上 GitHub")
    print("  " + "-" * 58)
    working = None
    for port in alive:
        ok, detail = try_github(port)
        print("     %-6d %s  %s" % (port, "可用" if ok else "不可用", detail))
        if ok and working is None:
            working = port

    print()
    print("  " + "=" * 58)
    if working:
        print("  可用端口: %d" % working)
        print()
        print("  给 git 配上（只影响 git，不动系统设置）：")
        print("     git config --global http.proxy  http://127.0.0.1:%d" % working)
        print("     git config --global https.proxy http://127.0.0.1:%d" % working)
        print()
        print("  推完之后想撤掉：")
        print("     git config --global --unset http.proxy")
        print("     git config --global --unset https.proxy")
    else:
        print("  有端口在监听，但都连不上 GitHub。")
        print("  可能是代理规则没把 github.com 走代理，或出口被限流。")
        print("  建议：在 clash-verge 里把规则切到「全局」，或确认 github.com 命中代理规则。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
