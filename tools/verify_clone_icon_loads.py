# -*- coding: utf-8 -*-
"""端到端验证：从 GitHub 全新克隆后，图标**真的能被加载**（不只是文件在）。

与 `verify_remote_icons.py` 的分工：
  * 那个查"文件在不在、内容是否逐字节相同"（静态）；
  * 这个查"跑起来之后图标到底加载成功没有"（动态）。

为什么要分开：文件存在但**内容坏了/尺寸对不上**时，`make_icon()` 会走到兜底分支
（`.png` 兜底，或两个都缺时返回空 QIcon）。而空 QIcon 的效果是"窗口和任务栏都没有
图标"，界面上完全看不出原因 —— 只有 stderr 那一行能区分。所以这里必须**看 stderr**，
不能只看文件在不在。

顺带验证安装脚本那条路径：桌面快捷方式的图标取自 `assets/icon.ico`（install.ps1），
所以也确认那个文件在克隆里。

    python tools/verify_clone_icon_loads.py
"""

import os
import re
import shutil
import stat
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLONE = r"E:\dsh\_icon-clone-test"
REPO = "https://github.com/adincole169-ui/cole-dsh-pet.git"
PROXY = "http://127.0.0.1:7897"
WARNING = "找不到图标"

FAILURES = []


def check(label, ok, detail=""):
    if isinstance(detail, (list, tuple)):
        detail = " / ".join(str(x) for x in detail if x)
    detail = str(detail)
    print("  %s %s%s" % ("[OK]  " if ok else "[失败]", label,
                         ("  " + detail) if detail else ""))
    if not ok:
        FAILURES.append(label)


def force_rmtree(path):
    import stat as stat_module
    if not os.path.isdir(path):
        return True

    def onerror(function, target, _exc_info):
        try:
            os.chmod(target, stat_module.S_IWRITE)
            function(target)
        except Exception:
            pass

    shutil.rmtree(path, onerror=onerror)
    return not os.path.isdir(path)


def pythonw_for(executable):
    candidate = os.path.join(os.path.dirname(executable), "pythonw.exe")
    return candidate if os.path.isfile(candidate) else executable


def main():
    print()
    print("  端到端：全新克隆后图标能否真的加载")
    print("  " + "=" * 74)

    env = dict(os.environ, HTTP_PROXY=PROXY, HTTPS_PROXY=PROXY)
    if not force_rmtree(CLONE):
        check("清理旧克隆目录", False, CLONE)
        return 1
    done = subprocess.run(["git", "-c", "credential.helper=", "clone", "--depth", "1",
                           REPO, CLONE],
                          capture_output=True, text=True, env=env, cwd=r"E:\dsh",
                          timeout=600)
    check("全新克隆", done.returncode == 0, (done.stderr or "").strip()[:120])
    if done.returncode != 0:
        return 1

    # 用**克隆里那份**代码跑，不是本机这份
    python = sys.executable
    icon_ico = os.path.join(CLONE, "assets", "icon.ico")
    icon_png = os.path.join(CLONE, "assets", "icon.png")
    check("克隆里有 assets/icon.ico（快捷方式图标源）", os.path.isfile(icon_ico))
    check("克隆里有 assets/icon.png（窗口图标兜底）", os.path.isfile(icon_png))

    # 跑起来，只跑一个动画后自动退出；把 stderr 抓下来看有没有告警
    print()
    print("     用克隆里那份启动桌宠（--force --anim --hold 6）...")
    process = subprocess.Popen(
        [python, "-X", "utf8", os.path.join(CLONE, "main.py"),
         "--force", "--anim", "待机呼吸休闲", "--hold", "6"],
        cwd=CLONE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        out, err = process.communicate(timeout=180)
    except subprocess.TimeoutExpired:
        process.kill()
        out, err = process.communicate()
    combined = (out or "") + (err or "")

    print()
    warnings = [line for line in combined.splitlines() if WARNING in line]
    check("启动过程没有「找不到图标」告警", not warnings,
          warnings[0][:110] if warnings else "（stderr 干净）")
    check("进程正常退出", process.returncode == 0, "退出码 %s" % process.returncode)

    # 直接测"加载"这一步：用克隆里的代码 + 克隆里的资源，问 QIcon 拿到没有
    print()
    print("     直接验证图标加载（不看界面，看 QIcon 的返回）...")
    probe = (
        "import os, sys\n"
        "sys.path.insert(0, os.path.join(%r, 'src'))\n"
        "sys.path.insert(0, %r)\n"
        "from PyQt5.QtWidgets import QApplication\n"
        "from PyQt5.QtGui import QIcon\n"
        "app = QApplication([])\n"
        "import pet\n"
        "icon = pet.make_icon()\n"
        "print('ICON_PATH_EXISTS', os.path.exists(pet.ICON_PATH))\n"
        "print('ICON_ICO_EXISTS', os.path.exists(pet.ICON_ICO))\n"
        "print('ICON_NULL', icon.isNull())\n"
        "print('ICON_SIZES', len(icon.availableSizes()))\n"
        "print('ICON_SIZE_LIST', [ (s.width(), s.height()) for s in icon.availableSizes() ][:8])\n"
        % (CLONE, CLONE)
    )
    done = subprocess.run([python, "-X", "utf8", "-c", probe], cwd=CLONE,
                          capture_output=True, text=True, timeout=180)
    output = (done.stdout or "") + (done.stderr or "")
    values = {}
    for line in output.splitlines():
        if " " in line:
            key, value = line.split(" ", 1)
            values[key.strip()] = value.strip()
    print("        " + "  ".join("%s=%s" % (k, v) for k, v in values.items())
          if values else "        （没有拿到结果）")
    check("QIcon 不为空（否则窗口/任务栏无图标）",
          values.get("ICON_NULL") == "False", output.strip()[-120:])
    check("QIcon 至少含一个尺寸", values.get("ICON_SIZES", "0") not in ("0", ""),
          "尺寸数 %s" % values.get("ICON_SIZES"))
    sizes = values.get("ICON_SIZE_LIST", "")
    check("QIcon 含多尺寸（.ico 生效，而不是退化成单张 .png）",
          sizes.count("(") >= 2, sizes)

    print()
    force_rmtree(CLONE)
    print("  结论")
    print("  " + "=" * 74)
    if FAILURES:
        for item in FAILURES:
            print("     [失败] %s" % item)
        return 1
    print("     [OK] 全新克隆 → 图标文件齐全 → QIcon 加载成功且含多尺寸")
    print("     [OK] 启动 stderr 里没有「找不到图标」告警")
    print("          （即：别人装起来和本机看到的是同一个图标）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
