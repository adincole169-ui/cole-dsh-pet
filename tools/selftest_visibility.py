# -*- coding: utf-8 -*-
"""自检：长时间运行下宠物会不会"消失"。

"消失"在代码层面有几种完全不同的原因，症状却一样（看不见），所以这里把每一种都
单独采出来，而不是只看一个"可见/不可见"布尔：

  * 窗口跑到屏幕外（位置/几何越界）
  * 窗口被隐藏（isVisible 变 False）
  * 没有可画的帧（动画还在后台加载，或加载失败）
  * 窗口尺寸变成 0（缩放/气泡算出负值）

    python tools/selftest_visibility.py [秒数]
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)   # main.py 在项目根目录

from PyQt5.QtWidgets import QApplication

from config import load, pet_configs
from frames import FrameStore
from pet import PetWindow
from main import build_app  # 复用入口的 High-DPI 设置，否则屏幕几何会报错

FAILED = []


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label, ("  " + detail) if detail else ""))
    if not ok:
        FAILED.append(label)


def main(argv):
    seconds = float(argv[1]) if len(argv) > 1 else 40.0
    app = build_app([argv[0]])
    entries = pet_configs(load())
    store = FrameStore(keep=6)
    window = PetWindow(entries[0], store)
    window.show()

    area = QApplication.primaryScreen().availableGeometry()
    samples = []
    offscreen = hidden = frameless = zerodim = 0
    start = time.time()
    ticks = 0

    while time.time() - start < seconds:
        app.processEvents()
        window.tick()
        ticks += 1

        left, top = window.x(), window.y()
        width, height = window.width(), window.height()
        right, bottom = left + width, top + height
        visible = window.isVisible()
        frame = window.animator.current_frame()

        # 完全落在可用区域之外才算"跑出屏幕"；压边不算
        outside = (right <= area.left() or left >= area.right()
                   or bottom <= area.top() or top >= area.bottom())
        sample = {
            "t": round(time.time() - start, 1),
            "pos": (left, top),
            "size": (width, height),
            "visible": visible,
            "frame": frame is not None,
            "anim": window.animator.playing.name if window.animator.playing else None,
            "ready": bool(window.animator.playing.ready) if window.animator.playing else False,
            "loading": len(store.stats()["loading"]),
        }
        samples.append(sample)
        if outside:
            offscreen += 1
        if not visible:
            hidden += 1
        if frame is None:
            frameless += 1
        if width <= 0 or height <= 0:
            zerodim += 1

        # 每 10 个采样换一个状态，覆盖"加载中"这条最容易出问题的路径
        if ticks % 10 == 0:
            window.animator.next_auto()
        time.sleep(0.02)

    total = len(samples)
    print("  采样 %d 次 / %.0f 秒" % (total, seconds))
    print("  --- 异常计数 ---")
    check("没有跑出屏幕", offscreen == 0, "%d/%d 次越界" % (offscreen, total))
    check("窗口始终可见", hidden == 0, "%d/%d 次不可见" % (hidden, total))
    check("尺寸始终有效", zerodim == 0, "%d/%d 次零尺寸" % (zerodim, total))
    print("  --- 无帧占比（区分『加载中』与『加载失败』）---")
    ratio = frameless / float(total or 1)
    print("    无帧占比 %.1f%%（%d/%d）" % (ratio * 100, frameless, total))
    longest = 0
    run = 0
    for sample in samples:
        run = run + 1 if not sample["frame"] else 0
        longest = max(longest, run)
    print("    最长连续无帧: %d 次采样" % longest)

    if samples:
        print("  --- 抽样 ---")
        for index in (0, total // 4, total // 2, (3 * total) // 4, total - 1):
            sample = samples[index]
            print("    t=%-5s pos=%-14s size=%-10s vis=%-5s frame=%-5s anim=%s"
                  % (sample["t"], sample["pos"], sample["size"], sample["visible"],
                     sample["frame"], sample["anim"]))

    # 运行时出现的名称要能真的取到帧，否则就是"状态已切、画面没有"
    missing = sorted({s["anim"] for s in samples if s["anim"] and not s["ready"]})
    if missing:
        print("  --- 采样期间未就绪的动画 ---")
        for name in missing:
            print("    %s" % name)

    window.close()
    print("失败 %d 项" % len(FAILED) if FAILED else "全部通过")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
