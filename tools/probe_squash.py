# -*- coding: utf-8 -*-
"""查 `squash` 静止时是不是**恰好 1.0** —— 不是的话，每帧都在重采样。

`drawPixmap(sprite_rect, pixmap, pixmap.rect())` 里 sprite_rect 的尺寸是
`width * squash` × `height / squash`。只有当 squash **正好 1.0** 时，
源矩形与目标矩形才是同一个尺度、Qt 才会走位块传送；只要它偏一点点
（例如 0.9997），就变成"缩放"，配上 `SmoothPixmapTransform` 就是一次
双线性重采样 —— **每帧都做**，画面持续性地略微发糊。

而 squash 是弹簧式逼近 1.0 的（`squash += (target - squash) * 10*DT`），
理论上永远到不了，只是越来越近。所以要实测它静止时到底是多少。

    python tools/probe_squash.py
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def main():
    sys.path.insert(0, os.path.join(ROOT, "src"))
    sys.path.insert(0, ROOT)
    try:
        from PyQt5.QtWidgets import QApplication                     # noqa: F401
    except ImportError as error:
        print("  需要 PyQt5: %s" % error)
        return 1

    from config import load, pet_configs
    from frames import FrameStore
    from main import build_app
    from pet import PetWindow

    app = build_app([])
    config = load()
    entries = pet_configs(config)
    store = FrameStore(keep=4)
    window = PetWindow(entries[0], store)
    window.show()

    print()
    print("  实测 squash 的静止值（%d 秒采样）" % 8)
    print("  " + "=" * 70)
    samples = []
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        app.processEvents()
        samples.append((window.squash, window.squash_target))
        time.sleep(0.05)

    if not samples:
        print("  没采到样本")
        return 1
    squashes = [s[0] for s in samples]
    targets = [s[1] for s in samples]
    biggest = max(abs(v - 1.0) for v in squashes)
    print("  squash       : 最小 %.6f  最大 %.6f  平均 %.6f"
          % (min(squashes), max(squashes), sum(squashes) / len(squashes)))
    print("  squash_target: 最小 %.6f  最大 %.6f"
          % (min(targets), max(targets)))
    print("  离 1.0 最远       : %.6f（即 %.4f%%）" % (biggest, biggest * 100))

    # 有多少比例的采样点"不恰好是 1.0"
    off = [v for v in squashes if v != 1.0]
    print("  不等于 1.0 的采样点: %d / %d（%.1f%%）"
          % (len(off), len(squashes), 100.0 * len(off) / len(squashes)))

    print()
    print("  判读")
    print("  " + "-" * 70)
    if not off:
        print("  squash 恒为 1.0 —— 绘制走的是位块传送，没有额外重采样。")
    elif biggest < 0.002:
        print("  squash 与 1.0 的偏差在 %.4f%% 以内 —— 尺寸上几乎是 1:1，" % (biggest * 100))
        print("  但严格说不等于 1.0，Qt 仍可能判定为缩放而做一次重采样。")
        print("  修法：在 step_physics 里当 |squash-1| < 0.002 时直接吸附到 1.0。")
    else:
        print("  **squash 明显偏离 1.0**（最大 %.2f%%）—— 每帧都在缩放重采样，" % (biggest * 100))
        print("  这会让画面持续偏软。修法同上：接近 1.0 时吸附。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
