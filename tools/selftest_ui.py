# -*- coding: utf-8 -*-
"""自检：多开、气泡高度、缩放、菜单分类。

    python tools/selftest_ui.py

不依赖真实屏幕观感，只验证"能不能开出来、尺寸算得对不对、菜单有没有内容"——
这些是代码层面的错误，而观感必须由人看。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

from PyQt5.QtWidgets import QApplication

from config import PetConfig, load, pet_configs
from frames import FrameStore
from pet import PetWindow

FAILED = []


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label, ("  " + detail) if detail else ""))
    if not ok:
        FAILED.append(label)


def main():
    app = QApplication(sys.argv)
    base = load()
    store = FrameStore(keep=6)

    # --- 多开：用同一份配置派生两只，各自独立大小与位置 --------------------- #
    entries = pet_configs(base)
    first = entries[0]
    second_entry = {"id": "second", "name": "二号", "size": 300,
                    "display": "both", "position": {"corner": "top-left", "marginX": 240}}
    second = PetConfig(second_entry, base)
    check("多开：第二只配置独立", second.id == "second" and second.size == 300,
          "id=%s size=%s" % (second.id, second.size))

    windows = []
    for pet_config in (first, second):
        window = PetWindow(pet_config, store)
        window.show()
        windows.append(window)
    app.processEvents()
    check("多开：两个窗口都建立", len(windows) == 2)
    check("多开：尺寸各自生效",
          windows[0].size_px == first.size and windows[1].size_px == 300,
          "%d / %d" % (windows[0].size_px, windows[1].size_px))
    check("多开：位置各自不同",
          (windows[0].x(), windows[0].y()) != (windows[1].x(), windows[1].y()),
          "(%d,%d) vs (%d,%d)" % (windows[0].x(), windows[0].y(), windows[1].x(), windows[1].y()))

    # --- 气泡：出现时窗口变高，消失时复原且底部不动 ------------------------- #
    window = windows[0]
    base_h = window.height()
    bottom_before = window.y() + window.height()
    window.say("这是一句用来测量高度的气泡文字", "开心", 3.0)
    app.processEvents()
    check("气泡：窗口变高", window.height() > base_h, "%d -> %d" % (base_h, window.height()))
    check("气泡：配图已载入", window.bubble_image is not None)
    check("气泡：底部保持不动", abs((window.y() + window.height()) - bottom_before) <= 4,
          "bottom %d -> %d" % (bottom_before, window.y() + window.height()))
    window.clear_bubble()
    app.processEvents()
    check("气泡：清空后复原", window.height() == base_h, "%d" % window.height())

    # --- 缩放 ---------------------------------------------------------------- #
    window.set_size(520)
    app.processEvents()
    check("大小：切换生效", window.size_px == 520 and window.width() == 520,
          "%dx%d" % (window.width(), window.height()))

    # --- 菜单：分类点播有内容 ------------------------------------------------ #
    categories = base.get("animations", {}).get("categories") or []
    total = sum(len(item.get("actions") or []) for item in categories if isinstance(item, dict))
    check("菜单：分类动作可点播", total > 50, "%d 个动作" % total)
    moves = first.move_specs()
    check("菜单：移动动作有条目", len(moves) >= 1, "%d 条" % len(moves))

    # --- 工作状态映射 -------------------------------------------------------- #
    events = first.animations.get("events") or {}
    tiers = events.get("workStatus") or []
    check("工作状态六档齐全", len(tiers) == 6, "%d 档" % len(tiers))
    check("工作状态文案六组", len(first.work_status_texts) == 6)

    for window in windows:
        window.close()
    print("失败 %d 项" % len(FAILED) if FAILED else "全部通过")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
