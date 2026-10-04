# -*- coding: utf-8 -*-
"""诊断工具链：Python / PyQt5 / numpy / 素材是否齐备，以及这次跑在哪个解释器上。

为什么做成脚本而不是临时命令行：本项目里反复因为**在 PowerShell 里内联 Python 代码**
而踩引号转义的坑（中文、嵌套引号、`$(...)`、反引号），至少 6 次。规则是：
凡是超过一行的 Python/PowerShell 代码，一律**先写成文件再执行**。

    python tools/doctor.py
    python tools/doctor.py --full      # 顺便校验帧素材完整性（较慢）
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def ok(label, detail=""):
    print("  [OK]   %-34s %s" % (label, detail))


def warn(label, detail=""):
    print("  [警告] %-34s %s" % (label, detail))


def bad(label, detail=""):
    print("  [缺失] %-34s %s" % (label, detail))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="顺便校验帧素材")
    args = parser.parse_args()

    print("=== 解释器 ===")
    print("  Python %s" % sys.version.split()[0])
    print("  解释器 %s" % sys.executable)
    print("  项目根 %s" % ROOT)

    print()
    print("=== 运行时依赖 ===")
    try:
        import PyQt5.QtCore as core
        ok("PyQt5", "%s (Qt %s)" % (core.PYQT_VERSION_STR, core.QT_VERSION_STR))
        major, minor = (int(x) for x in core.PYQT_VERSION_STR.split(".")[:2])
        if major != 5:
            bad("PyQt5 主版本", "需要 5.x，当前 %d.x（PyQt6 改了若干 API）" % major)
        elif minor < 15:
            warn("PyQt5 是较老的小版本", "已在 5.9 与 5.15 上验证，若出问题优先试 5.15")
    except ImportError as error:
        bad("PyQt5", "必需：pip install PyQt5  (%s)" % error)

    try:
        import numpy
        ok("numpy", "%s（可选，缺了会退回纯 Python 实现）" % numpy.__version__)
    except ImportError:
        warn("numpy", "未安装：掩膜计算会变慢，但功能正常")

    try:
        import PIL
        ok("Pillow", "%s（只在解码素材时需要）" % PIL.__version__)
    except ImportError:
        warn("Pillow", "未安装：仅在你需要从 webm 重新解码帧时才要")

    ffmpeg = None
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(folder, "ffmpeg.exe")
        if os.path.exists(candidate):
            ffmpeg = candidate
            break
    if ffmpeg:
        ok("ffmpeg", ffmpeg)
    else:
        warn("ffmpeg", "不在 PATH 里：仅重新解码素材时需要")

    print()
    print("=== 素材 ===")
    frames = os.path.join(ROOT, "frames")
    webm = os.path.join(ROOT, "webm")
    if os.path.isdir(frames):
        animations = [d for d in os.listdir(frames)
                      if os.path.isdir(os.path.join(frames, d)) and not d.startswith("_")]
        count = sum(len(os.listdir(os.path.join(frames, d))) for d in animations)
        ok("帧缓存", "%d 个动画 / %d 个文件" % (len(animations), count))
        if args.full:
            broken = []
            for name in animations:
                folder = os.path.join(frames, name)
                pngs = [f for f in os.listdir(folder) if f.endswith(".png")]
                if len(pngs) < 200:
                    broken.append("%s(%d 帧)" % (name, len(pngs)))
            if broken:
                bad("帧完整性", "可能不完整: %s" % ", ".join(broken[:6]))
            else:
                ok("帧完整性", "每个动画都有 200 帧以上")
    else:
        bad("帧缓存 frames/", "缺失：首次播动画需现场解码（要 ffmpeg + Pillow）")

    if os.path.isdir(webm):
        ok("webm 源素材", "%d 个文件（仅重新解码时需要）" % len(os.listdir(webm)))
    else:
        warn("webm 源素材", "缺失：无法自行重新解码帧")

    for name in ("assets/icon.ico", "assets/icon.png", "memes", "config.jsonc", "main.py"):
        path = os.path.join(ROOT, name.replace("/", os.sep))
        if os.path.exists(path):
            ok(name)
        else:
            bad(name)

    print()
    print("=== 结论 ===")
    try:
        import PyQt5  # noqa: F401
        print("  可以运行：python main.py")
    except ImportError:
        print("  还不能运行：先装 PyQt5")
    return 0


if __name__ == "__main__":
    sys.exit(main())
