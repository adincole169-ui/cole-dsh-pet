# -*- coding: utf-8 -*-
"""按「真实 pip 安装」量依赖体积 —— 不拿本机 Anaconda 的目录当答案。

为什么要重做：
  * 本机 PyQt5 目录只有 16.5 MB，但那是 **Anaconda** 的布局 —— Qt 的 DLL
    在别处（Library/bin）。真从 pip 装 PyQt5 会带 PyQt5-Qt5 那个大 wheel，
    体积完全不同，拿本机目录报数会严重低估。
  * winget 装的 ffmpeg 整个目录 695 MB（full_build 含 doc/include/lib），
    而**运行时只用到 bin/ 里那几个 exe 和 DLL**。

做法：查 PyPI 的 wheel 体积（下载量 + 解压后量），并对 ffmpeg 分别量
"整个目录"与"bin/ 子目录"。
"""

import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

PROXY = "http://127.0.0.1:7897"
CACHE = r"E:\dsh\_wheelcheck"
PACKAGES = ["PyQt5", "PyQt5-Qt5", "PyQt5-sip", "imageio-ffmpeg"]


def opener():
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))


def wheel_for(name, python_tag="cp38"):
    """找该包**能装上**的 Windows wheel。

    **不能只看最新版**：最新版往往已经不发 cp38 的 wheel 了
    （Python 3.8 已 EOL），于是会误报"没有匹配的 wheel"——实测踩过，
    PyQt5-Qt5 与 PyQt5-sip 都因此漏掉，合计体积直接少了 50 MB。
    正确做法是从新到旧扫版本，取第一个有匹配 wheel 的。
    """
    url = "https://pypi.org/pypi/%s/json" % name
    with opener().open(url, timeout=90) as response:
        data = json.loads(response.read().decode("utf-8"))

    def version_key(text):
        parts = []
        for chunk in text.replace("-", ".").split("."):
            parts.append(int(chunk) if chunk.isdigit() else 0)
        return parts

    candidates = []
    for version, files in data.get("releases", {}).items():
        for file_info in files:
            if file_info.get("packagetype") != "bdist_wheel":
                continue
            filename = file_info["filename"]
            if "win_amd64" not in filename:
                continue
            # 纯 py3 wheel（py3-none-any）对所有 Python 版本通用
            if "py3-none" not in filename and python_tag not in filename:
                continue
            candidates.append((version_key(version), version, filename,
                               file_info["size"], file_info["url"]))
            break
    if not candidates:
        return data["info"]["version"], None
    candidates.sort(reverse=True)
    _key, version, filename, size, url = candidates[0]
    return version, (filename, size, url)


def unpacked_size(url, filename):
    """下载并量解压后的体积。"""
    os.makedirs(CACHE, exist_ok=True)
    target = os.path.join(CACHE, filename)
    if not os.path.isfile(target):
        with opener().open(url, timeout=300) as response:
            with open(target, "wb") as handle:
                shutil.copyfileobj(response, handle)
    total = 0
    with zipfile.ZipFile(target) as archive:
        for info in archive.infolist():
            total += info.file_size
    return total, os.path.getsize(target), target


def folder_mb(path):
    total = 0
    for base, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
    return total / 1048576.0


def main():
    print()
    print("  真实 pip 安装的体积（Windows + CPython 3.8 wheel）")
    print("  " + "=" * 76)
    print("  %-16s %-10s %-12s %-12s %s"
          % ("包", "版本", "下载", "解压后", "说明"))
    print("  " + "-" * 76)
    total_unpacked = 0
    total_download = 0
    needed_unpacked = 0        # 跑桌宠**必需**的那部分（PyQt5 三件套）
    needed_download = 0
    ffmpeg_unpacked = 0        # 可选：imageio-ffmpeg
    ffmpeg_download = 0
    for name in PACKAGES:
        try:
            version, best = wheel_for(name)
        except Exception as error:
            print("  %-16s 查询失败: %s" % (name, error))
            continue
        if not best:
            print("  %-16s %-10s 没有匹配的 win_amd64 wheel" % (name, version))
            continue
        filename, size, url = best
        try:
            unpacked, downloaded, _path = unpacked_size(url, filename)
        except Exception as error:
            print("  %-16s %-10s 下载失败: %s" % (name, version, error))
            continue
        note = ""
        if name == "PyQt5-Qt5":
            note = "Qt 运行库（大头）"
        elif name == "imageio-ffmpeg":
            note = "含一个 ffmpeg 二进制（可选）"
        elif name == "PyQt5":
            note = "Python 绑定"
        elif name == "PyQt5-sip":
            note = "sip 运行库"
        total_unpacked += unpacked
        total_download += downloaded
        if name == "imageio-ffmpeg":
            ffmpeg_unpacked += unpacked
            ffmpeg_download += downloaded
        else:
            needed_unpacked += unpacked
            needed_download += downloaded
        print("  %-16s %-10s %-12s %-12s %s"
              % (name, version, "%.1f MB" % (downloaded / 1048576.0),
                 "%.1f MB" % (unpacked / 1048576.0), note))
    print("  " + "-" * 76)
    print("  %-16s %-10s %-12s %-12s" % ("PyQt5 三件套（必需）", "",
                                         "%.1f MB" % (needed_download / 1048576.0),
                                         "%.1f MB" % (needed_unpacked / 1048576.0)))
    print("  %-16s %-10s %-12s %-12s" % ("imageio-ffmpeg（可选）", "",
                                         "%.1f MB" % (ffmpeg_download / 1048576.0),
                                         "%.1f MB" % (ffmpeg_unpacked / 1048576.0)))
    if os.path.isdir(CACHE):
        shutil.rmtree(CACHE, ignore_errors=True)

    # ffmpeg 的两种口径
    print()
    print("  ffmpeg 的体积（两种口径，差别很大）")
    print("  " + "-" * 76)
    exe = shutil.which("ffmpeg")
    if exe:
        bin_dir = os.path.dirname(exe)
        root_dir = os.path.dirname(os.path.dirname(bin_dir))
        print("  运行时真正需要的 bin/            %6.1f MB" % folder_mb(bin_dir))
        print("  winget full_build 整个目录        %6.1f MB（含 doc/include/lib/presets）"
              % folder_mb(root_dir))
        print("  -> 报「装了 ffmpeg 占多少」要看 bin/：文档与头文件不影响运行")
    print("  或者 pip 装 imageio-ffmpeg        见上表（更小，且随 venv 走）")

    print()
    print("  结论")
    print("  " + "=" * 76)
    print("  **从 GitHub 装一个能跑的桌宠**（ffmpeg 已有）：")
    print("      git clone --depth 1      105.6 MB（工作区 53.3 + .git 52.3）")
    print("      pip install PyQt5          %.1f MB（解压后，三件套）"
          % (needed_unpacked / 1048576.0))
    print("      运行时写盘                 0 MB（stream 模式不留帧）")
    print("      ------------------------------------")
    print("      合计                      约 %.0f MB"
          % (105.6 + needed_unpacked / 1048576.0))
    print()
    print("  **ffmpeg 若系统没有**（二选一）：")
    print("      pip install imageio-ffmpeg %.1f MB（解压后，随 venv 走）"
          % (ffmpeg_unpacked / 1048576.0))
    print("      或 winget install ffmpeg   约 700 MB（gyan.dev 的静态构建，")
    print("                                 单个 exe 就一两百 MB；只用到 bin/）")
    print()
    print("  **对比**：")
    print("      旧方案（cache 模式）       再 +2600 MB，合计约 2.7 GB")
    print("      dsh-pet 上游插件           62.3 MB（还要另下 Electron）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
