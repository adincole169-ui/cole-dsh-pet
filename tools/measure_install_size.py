# -*- coding: utf-8 -*-
"""量清楚「从 GitHub 安装使用」到底占多少磁盘。

分四笔账，缺一笔就会给出误导性的数字：

  ① 克隆        —— 工作区（素材+代码）+ .git（历史对象）
  ② Python 依赖 —— PyQt5（必需）；numpy/Pillow 只有自检与解码工具用
  ③ ffmpeg      —— stream 模式运行时需要；要么系统已有，要么装 imageio-ffmpeg
  ④ 运行时写盘  —— stream 模式应该**恒为 0**（这才是这次改动省下来的）

对比：cache 模式还要额外 2.6 GB 的 frames/。

    python tools/measure_install_size.py
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLONE = r"E:\dsh\_size-test"
REPO = "https://github.com/adincole169-ui/cole-dsh-pet.git"
PROXY = "http://127.0.0.1:7897"


def force_rmtree(path):
    import stat
    if not os.path.isdir(path):
        return

    def onerror(function, target, _exc_info):
        try:
            os.chmod(target, stat.S_IWRITE)
            function(target)
        except Exception:
            pass

    shutil.rmtree(path, onerror=onerror)


def folder_mb(path):
    total = 0
    if not os.path.isdir(path):
        return 0.0
    for base, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
    return total / 1048576.0


def count_files(path):
    total = 0
    for _base, _dirs, files in os.walk(path):
        total += len(files)
    return total


def main():
    env = dict(os.environ, HTTP_PROXY=PROXY, HTTPS_PROXY=PROXY)
    print()
    print("  从 GitHub 安装使用：磁盘占用实测")
    print("  " + "=" * 74)

    # --- ① 克隆 ---
    print()
    print("  ① 克隆（git clone）")
    print("  " + "-" * 74)
    results = {}
    for label, extra in (("--depth 1", ["--depth", "1"]), ("完整历史", [])):
        force_rmtree(CLONE)
        done = subprocess.run(["git", "-c", "credential.helper=", "clone"]
                              + extra + [REPO, CLONE],
                              capture_output=True, text=True, env=env, cwd=r"E:\dsh")
        if done.returncode != 0:
            print("  %-12s 克隆失败: %s" % (label, (done.stderr or "").strip()[:120]))
            continue
        work = folder_mb(CLONE) - folder_mb(os.path.join(CLONE, ".git"))
        git = folder_mb(os.path.join(CLONE, ".git"))
        results[label] = (work, git)
        print("  %-12s 工作区 %6.1f MB   .git %6.1f MB   合计 %6.1f MB（%d 个文件）"
              % (label, work, git, work + git, count_files(CLONE)))
    force_rmtree(CLONE)

    # 工作区里都是什么
    if results:
        print()
        print("     工作区构成（以完整历史那次为准，按目录）")
        force_rmtree(CLONE)
        subprocess.run(["git", "-c", "credential.helper=", "clone", "--depth", "1",
                        REPO, CLONE], capture_output=True, env=env, cwd=r"E:\dsh")
        entries = []
        for name in sorted(os.listdir(CLONE)):
            if name == ".git":
                continue
            path = os.path.join(CLONE, name)
            if os.path.isdir(path):
                entries.append((folder_mb(path), name + "/", count_files(path)))
            else:
                entries.append((os.path.getsize(path) / 1048576.0, name, 1))
        entries.sort(reverse=True)
        for size, name, files in entries[:10]:
            print("       %7.1f MB  %-22s %d 个文件" % (size, name, files))
        force_rmtree(CLONE)

    # --- ② Python 依赖 ---
    print()
    print("  ② Python 依赖（pip 装到 site-packages 的体积）")
    print("  " + "-" * 74)
    try:
        import PyQt5
        pyqt_path = os.path.dirname(PyQt5.__file__)
        print("  PyQt5        %7.1f MB   %s" % (folder_mb(pyqt_path), pyqt_path))
        try:
            from PyQt5 import QtCore
            print("               Qt 版本 %s" % QtCore.QT_VERSION_STR)
        except Exception:
            pass
    except ImportError:
        print("  PyQt5        没装")
    for module, label in (("numpy", "numpy（可选）"), ("PIL", "Pillow（可选）"),
                          ("scipy", "scipy（可选，仅自检/工具用）")):
        try:
            imported = __import__(module)
            path = os.path.dirname(imported.__file__)
            print("  %-12s %7.1f MB" % (label, folder_mb(path)))
        except ImportError:
            print("  %-12s 没装" % label)

    # --- ③ ffmpeg ---
    print()
    print("  ③ ffmpeg（stream 模式运行时需要）")
    print("  " + "-" * 74)
    exe = shutil.which("ffmpeg")
    if exe:
        print("  系统已装     %s" % exe)
        print("               （已经装了就**不额外占空间**；本机这个是 winget 装的）")
        parent = os.path.dirname(exe)
        print("               它所在目录 %6.1f MB（ffmpeg/ffprobe/ffplay 等）"
              % folder_mb(parent))
    else:
        print("  系统没有")
    try:
        import imageio_ffmpeg
        path = os.path.dirname(imageio_ffmpeg.__file__)
        print("  imageio-ffmpeg %5.1f MB  %s" % (folder_mb(path), path))
    except ImportError:
        print("  imageio-ffmpeg 没装（装的话约 62 MB，含一个 ffmpeg 二进制）")

    # --- ④ 运行时写盘 ---
    print()
    print("  ④ 运行时写盘")
    print("  " + "-" * 74)
    frames = os.path.join(ROOT, "frames")
    print("  stream 模式  %s" % ("0（frames/ 不存在）" if not os.path.isdir(frames)
                                 else "**%.1f MB**（存在 frames/，说明是 cache 模式）"
                                 % folder_mb(frames)))
    print("  cache 模式   约 2600 MB（25423 个 PNG）")
    print("  日志         几 MB 以内，且会自动裁剪（logs/）")

    # --- 汇总 ---
    print()
    print("  汇总")
    print("  " + "=" * 74)
    if results:
        work, git = results.get("--depth 1") or results.get("完整历史")
        print("  最小安装（clone --depth 1 + PyQt5，ffmpeg 已有）：")
        print("     克隆 工作区     %7.1f MB" % work)
        print("     克隆 .git       %7.1f MB" % git)
        print("     PyQt5           %7.1f MB"
              % (folder_mb(os.path.dirname(__import__("PyQt5").__file__))
                 if "PyQt5" in sys.modules or _has("PyQt5") else 0))
        print("     运行时          0 MB")
        print("     ------------------------------------")
        print("     合计            约 %.0f MB" % (work + git + _pyqt_mb()))
    print()
    print("  对比旧方案（cache 模式）：再 + %.0f MB 的 frames/，合计约 %.1f GB"
          % (2600, (work + git + _pyqt_mb() + 2600) / 1024.0 if results else 0))
    return 0


def _has(name):
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def _pyqt_mb():
    try:
        import PyQt5
        return folder_mb(os.path.dirname(PyQt5.__file__))
    except ImportError:
        return 0.0


if __name__ == "__main__":
    sys.exit(main())
