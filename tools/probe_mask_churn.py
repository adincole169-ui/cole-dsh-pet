# -*- coding: utf-8 -*-
"""探针：掩膜**多久重建一次**（Windows 区域变更的频率）。

背景：`_apply_input_mask()` 由每帧的 `_repaint()` 调用，而它原来用
`frame.cacheKey()` 做 key —— 于是**每一帧**都 `setMask()`，也就是每秒最多 24 次
**Windows 区域变更**。区域变更会触发整窗重绘，是"画面闪烁"的直接来源。

改成"按量化后的角色包围盒"判断之后，只有轮廓明显移动时才重建。这个探针数一下
实际的 `setMask` 次数，以及**留白（insets）是否取到了真实值**（不是退化的 0）。

    python tools/probe_mask_churn.py
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main():
    from config import load, pet_configs
    from frames import FrameStore
    from main import build_app
    from pet import PetWindow

    app = build_app([sys.argv[0]])
    pet_config = pet_configs(load())[0]
    store = FrameStore(keep=3)
    window = PetWindow(pet_config, store)
    window.show()

    # 统计 setMask 次数（包一层）
    calls = {"n": 0}
    original = window.setMask

    def counting_set_mask(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    window.setMask = counting_set_mask

    # 等首帧
    deadline = time.time() + 20
    while time.time() < deadline:
        app.processEvents()
        if window.mask_stats:
            break
        time.sleep(0.05)

    print()
    print("  探针：掩膜重建频率（= Windows 区域变更次数）")
    print("  " + "=" * 74)

    frames = 120
    calls["n"] = 0
    started = time.time()
    for _ in range(frames):
        window._repaint()
        app.processEvents()
        time.sleep(1.0 / 60.0)
    elapsed = time.time() - started

    rate = calls["n"] / elapsed if elapsed else 0
    print("  %d 帧 / %.2f 秒   实际 setMask 次数 = %d   （%.1f 次/秒）"
          % (frames, elapsed, calls["n"], rate))
    print("  对照：改之前是**每帧一次**，即约 %.1f 次/秒" % (frames / elapsed))

    # 留白是不是真实值（不是退化的 0）
    left, right = window.wall_insets()
    l_now, r_now = window.character_insets()
    print()
    print("  当前帧留白 (%.0f, %.0f)；墙壁用的稳定留白 (%.0f, %.0f)"
          % (l_now, r_now, left, right))

    window.close()
    store.close()

    print()
    problems = []
    if rate > frames / elapsed * 0.6:
        problems.append("setMask 仍然接近每帧一次（%.1f 次/秒）—— 量化没生效" % rate)
    else:
        print("  OK   区域变更次数明显低于每帧一次")
    if left <= 1.0 and right <= 1.0 and (l_now > 1.0 or r_now > 1.0):
        problems.append("墙壁留白取成了退化值 0（当前帧明明是 %.0f/%.0f）—— "
                        "角色将永远到不了屏幕边" % (l_now, r_now))
    elif left <= 1.0 and right <= 1.0:
        print("  注意 本平台掩膜不生效，留白本身就是 0（offscreen 的已知限制）")
    else:
        print("  OK   墙壁留白取到了真实值（角色能贴到屏幕边）")

    print()
    if problems:
        for item in problems:
            print("     [问题] %s" % item)
        return 1
    print("  结论：掩膜按需重建；墙壁留白不是退化值。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
