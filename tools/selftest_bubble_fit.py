# -*- coding: utf-8 -*-
"""自检：气泡必须**装得下它的文字**，并且**随宠物尺寸缩放**。

用户报的两件事：

  1. "气泡的大小始终是固定的，而不是和桌宠的大小一样可以调节"
     —— 气泡的字号/配图/边距原先全是写死常量，而宠物用 `size_px` 缩放；
  2. "气泡无法包括所有文字" —— 文字溢出气泡（甚至被挤出窗口）。

这个自检对**多种尺寸 × 多段文字 × 有无配图**逐个验证四条：

  A. 水平装得下：左边距 + 配图 + 间隙 + 最宽一行 + 右边距 <= 气泡宽；
  B. 垂直装得下：行数 × 行高 + 上下边距 <= 气泡高；
  C. 气泡完整落在窗口内（`_draw_bubble` 的 box_y 钳位不会把它挤出去）；
  D. 缩放生效：尺寸翻倍时，气泡高度/宽度与字号都明显变大（近似等比）。

判据全部基于 `bubble_layout()` —— 绘制与算留白**共用同一份排版**，
所以"布局满足不变量"就等于"画出来装得下"。

    python tools/selftest_bubble_fit.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

FAILED = []


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label,
                         ("  " + str(detail)) if detail else ""))
    if not ok:
        FAILED.append(label)


TEXTS = [
    ("短", "好"),
    ("中", "主人桌面好乱呀"),
    ("长", "窗外的云软绵绵的，好想咬一口呀，可是主人还在忙，那我就先自己玩一会儿吧"),
    ("超长", "这是一句特别长的话" * 8),
]


def main():
    from PyQt5.QtWidgets import QApplication

    from config import load, pet_configs
    from frames import FrameStore
    from main import build_app
    from pet import PetWindow

    app = build_app([sys.argv[0]])
    pet_config = pet_configs(load())[0]
    store = FrameStore(keep=2)
    window = PetWindow(pet_config, store)
    window.show()
    for _ in range(20):
        app.processEvents()

    print()
    print("  自检：气泡装得下文字，且随宠物尺寸缩放")
    print("  " + "=" * 74)

    summary = []
    for size in (160, 320, 480):
        window.size_px = size
        window._resize_window()
        app.processEvents()
        for label, text in TEXTS:
            for has_image in (False, True):
                layout = window.bubble_layout(text, has_image)
                box_w = layout["box_w"]
                box_h = layout["box_h"]
                need_w = (layout["text_pad"] + layout["sticker"]
                          + layout["gap"] + layout["text_w"] + layout["text_pad"])
                need_h = layout["line_h"] * len(layout["lines"]) + layout["pad_y"]
                tag = "size=%d %s%s" % (size, label,
                                        "+图" if has_image else "")
                check("%s 水平装得下" % tag, need_w <= box_w + 1,
                      "需要 %d / 气泡 %d" % (need_w, box_w))
                check("%s 垂直装得下" % tag, need_h <= box_h + 1,
                      "需要 %d / 气泡 %d" % (need_h, box_h))

                # C：真摆放一次，确认气泡完整落在窗口里
                window.bubble_image = None
                window.say(text, None, 5.0)
                app.processEvents()
                rect = window.bubble_rect
                inside = (rect is not None and rect.top() >= -0.5
                          and rect.bottom() <= window.height() + 0.5
                          and rect.left() >= -0.5
                          and rect.right() <= window.width() + 0.5)
                check("%s 气泡在窗口内" % tag, inside,
                      "bubble=%s window=%dx%d"
                      % ("(%d,%d %dx%d)" % (rect.left(), rect.top(),
                                            rect.width(), rect.height())
                         if rect is not None else None,
                         window.width(), window.height()))
                # D：**掩膜必须已经包含气泡**。`setMask` 同时裁掉绘制，所以掩膜没跟上
                # 的那一帧，文字会被切掉。这里查掩膜的包围盒是否盖住气泡矩形
                # （必要条件；足以抓住"气泡出现后第一帧掩膜还是旧的"这个真实成因）。
                stats = getattr(window, "mask_stats", None) or {}
                mask_rect = stats.get("rect")
                covered = False
                if rect is not None and mask_rect:
                    covered = (mask_rect[0] <= rect.left() + 1
                               and mask_rect[1] <= rect.top() + 1
                               and mask_rect[0] + mask_rect[2] >= rect.right() - 1
                               and mask_rect[1] + mask_rect[3] >= rect.bottom() - 1)
                check("%s 掩膜已包含气泡（否则第一帧会切掉文字）" % tag, covered,
                      "bubble=%s mask=%s"
                      % ("(%d,%d %dx%d)" % (rect.left(), rect.top(),
                                            rect.width(), rect.height())
                         if rect is not None else None, mask_rect))
                # E：**画字用的字体必须与量尺寸用的那份一致**。
                #
                # 这是"气泡装不下文字"的真正成因（原版一直如此）：量的时候用
                # `QFont(FONT_FAMILY, 9)`，画的时候却用画笔画笔当前字体（应用默认），
                # 实测后者宽 20%，文字就越出气泡。这条断言值钱在于它的失效**看不出来**：
                # 两边代码都正常，只有渲染出来才知道。`_draw_bubble` 会把实际用到的字体
                # 记在 `bubble_font_used` 上。
                used = getattr(window, "bubble_font_used", None)
                want = layout["font"]
                font_ok = (used is not None
                           and used.family() == want.family()
                           and used.pointSize() == want.pointSize())
                check("%s 画字字体 == 量尺寸字体" % tag, font_ok,
                      "实际 %s %spt / 期望 %s %spt"
                      % (used.family() if used else None,
                         used.pointSize() if used else None,
                         want.family(), want.pointSize()))
                window.clear_bubble()
                app.processEvents()
            summary.append((size, label, box_w, box_h))

    # D：缩放是否生效（比较 size=160 与 size=480 的同一段文字）
    print()
    print("  ---- 缩放对照（同一段『长』文字、无配图）----")
    by_key = {}
    for size in (160, 320, 480):
        window.size_px = size
        window._resize_window()
        layout = window.bubble_layout(TEXTS[2][1], False)
        by_key[size] = layout
        print("     size=%-4d 字号=%2d 气泡 %dx%d 行数=%d 行高=%d"
              % (size, layout["font"].pointSize(), layout["box_w"],
                 layout["box_h"], len(layout["lines"]), layout["line_h"]))
    small, big = by_key[160], by_key[480]
    ratio = 480.0 / 160.0
    got_h = big["box_h"] / float(max(1, small["box_h"]))
    got_font = big["font"].pointSize() / float(max(1, small["font"].pointSize()))
    check("尺寸 ×3 时气泡高度明显变大（近似等比）",
          got_h > ratio * 0.6, "高度比 %.2f（尺寸比 %.2f）" % (got_h, ratio))
    check("尺寸 ×3 时字号也变大",
          got_font > 1.5, "字号比 %.2f" % got_font)
    check("尺寸 ×3 时气泡宽度也变大",
          big["box_w"] > small["box_w"], "%d -> %d" % (small["box_w"], big["box_w"]))

    window.close()
    store.close()

    print()
    print("  结论")
    print("  " + "=" * 74)
    if FAILED:
        for item in FAILED:
            print("     [失败] %s" % item)
        print()
        print("  共 %d 项失败" % len(FAILED))
        return 1
    print("     [OK] 各尺寸下气泡都装得下文字，且随宠物尺寸缩放")
    return 0


if __name__ == "__main__":
    sys.exit(main())
