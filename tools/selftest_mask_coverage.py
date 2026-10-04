# -*- coding: utf-8 -*-
"""自检：输入掩膜的阈值把多少"肉眼可见"的角色排除在可点范围之外。

为什么测这个：修复"对齐窗口永不过期"之后，拖动失效就只剩一个可能原因 ——
按下的那一点不在输入掩膜里（`setMask` 同时裁输入），于是 `dragging` 起不来。

掩膜来自**降采样后**的帧做 alpha 阈值（`MASK_ALPHA_MIN = 16`）。素材的"透明"背景
其实是 alpha 1~8，所以理论上 16 这个阈值正好把背景排除、把角色保留。但降采样会把
细笔画（发梢、鳍边、裙褶）的 alpha 平均下去，于是"看着是角色"的地方可能落到阈值之下。

**测法要点**：两个阈值必须在**同一张缩放后的图**上比较，否则坐标映射会把结论带偏。
第一版是拿"掩膜包围盒"去映射原始帧的坐标，而包围盒对应的是**角色内容边界**而不是
整帧，映射整个错位，测出来的 72.8% 是假的。

    python tools/selftest_mask_coverage.py
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from PyQt5.QtCore import Qt                                       # noqa: E402
from PyQt5.QtWidgets import QApplication                          # noqa: E402

from config import load, pet_configs                              # noqa: E402
from frames import FrameStore                                     # noqa: E402
from main import build_app                                        # noqa: E402
from pet import PetWindow, MASK_ALPHA_MIN                         # noqa: E402

FAILED = []
# 眼见的角色下限：素材背景是 alpha 1~8
VISIBLE_ALPHA = 8


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label, ("  " + detail) if detail else ""))
    if not ok:
        FAILED.append(label)


def threshold(image, minimum):
    """按 alpha 阈值数"置位"的点（Format_ARGB32）。"""
    width, height = image.width(), image.height()
    stride = image.bytesPerLine()
    pointer = image.constBits()
    pointer.setsize(stride * height)
    raw = bytes(pointer)
    try:
        import numpy as np
        array = np.frombuffer(raw, dtype=np.uint8).reshape(height, stride)
        alpha = array[:, :width * 4].reshape(height, width, 4)[:, :, 3]
        return int((alpha > minimum).sum())
    except ImportError:
        return sum(1 for y in range(height) for x in range(width)
                   if raw[y * stride + x * 4 + 3] > minimum)


def main():
    app = build_app([])
    config = load()
    entries = pet_configs(config)
    store = FrameStore(keep=8)
    window = PetWindow(entries[0], store)
    window.show()

    print()
    print("  掩膜阈值 MASK_ALPHA_MIN = %d；肉眼可见的下限取 alpha > %d"
          % (MASK_ALPHA_MIN, VISIBLE_ALPHA))
    print()

    samples = []
    deadline = time.monotonic() + 22.0
    while time.monotonic() < deadline and len(samples) < 12:
        app.processEvents()
        frame = window.animator.current_frame()
        if frame is not None and getattr(window, "mask_stats", None):
            samples.append(frame)
        time.sleep(0.4)

    if not samples:
        print("  **没能采到「掩膜已算好且有帧」的瞬间**")
        return 1

    print("  %-4s %-22s %-10s %-10s %-10s %s"
          % ("#", "动画", "可见点", "可点点", "被排除", "排除占比"))
    total_visible = total_strict = 0

    for index, frame in enumerate(samples, 1):
        # 复现 _build_input_bitmap 的缩放：按当前绘制矩形尺寸重采样
        rect = window.sprite_rect()
        margin = 2
        box_w = max(1, int(round(rect.width())) + margin * 2)
        box_h = max(1, int(round(rect.height())))
        scaled = frame.toImage().convertToFormat(4)          # Format_ARGB32
        if scaled.width() != box_w or scaled.height() != box_h:
            scaled = scaled.scaled(box_w, box_h, Qt.IgnoreAspectRatio,
                                   Qt.SmoothTransformation)

        loose = threshold(scaled, VISIBLE_ALPHA)
        strict = threshold(scaled, MASK_ALPHA_MIN)
        excluded = max(0, loose - strict)
        total_visible += loose
        total_strict += strict
        print("  %-4d %-22s %-10d %-10d %-10d %.1f%%"
              % (index, (window.animator.playing.name
                         if window.animator.playing else "")[:20],
                 loose, strict, excluded,
                 (excluded / float(loose) * 100.0) if loose else 0.0))
        window.animator.play(window.animator.playing.name if window.animator.playing else None)

    print()
    print("  汇总")
    print("  " + "=" * 66)
    if total_visible == 0:
        print("  可见点数为 0，无法判断")
        return 1
    kept = total_strict / float(total_visible)
    print("  肉眼可见点 %d，其中在掩膜内 %d（%.1f%%），被阈值排除 %d（%.1f%%）"
          % (total_visible, total_strict, kept * 100.0,
             total_visible - total_strict, (1.0 - kept) * 100.0))

    print()
    check("可点比例 ≥ 90%", kept >= 0.90, "%.1f%%" % (kept * 100.0))
    check("被排除的点少于 10%", (1.0 - kept) < 0.10,
          "%.1f%%" % ((1.0 - kept) * 100.0))

    print()
    if FAILED:
        print("  结论：阈值把可观一部分角色挡在可点范围外 ——")
        print("        用户按在角色上也可能漏，拖动会起不来。")
        print("        可考虑把 MASK_ALPHA_MIN 降到 8，或对掩膜做一次轻微的膨胀。")
        return 1
    print("  全部通过：阈值只排除了边缘的抗锯齿像素，角色主体都可点。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
