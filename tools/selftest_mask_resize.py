# -*- coding: utf-8 -*-
"""自检：输入掩膜在各种**尺寸变化**下都必须能重建。

这是针对一个真实崩溃写的回归测试。原先用户"点一下宠物就没了"，日志（用带日志的
启动包装才拿到）是：

    File "src\pet.py", line 352, in _build_input_bitmap
        bits[:] = solid
    ValueError: cannot modify the size of a sip.voidptr object
    退出码 3221226505   (0xC0000409)

根因是 `sip.voidptr` 的用法：不调用 `setsize()` 直接读会报 unknown size，而尺寸
变化时用 `byteCount()` 可能拿到 0，于是 `setsize(0)` 之后写入就抛上面那个异常。
异常发生在 Qt 事件回调里没人接住，进程直接带致命码退出。

这个脚本把"尺寸会变"的路径全部走一遍：有无气泡（窗口高度不同）、不同挤压量
（掩膜矩形宽度不同）、不同动画（帧尺寸不同）。

    python tools/selftest_mask_resize.py
"""

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from config import load, pet_configs
from frames import FrameStore
from main import build_app
from pet import PetWindow

FAILED = []


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label, ("  " + detail) if detail else ""))
    if not ok:
        FAILED.append(label)


def main(argv):
    app = build_app([argv[0]])
    config = pet_configs(load())[0]
    store = FrameStore(keep=4)
    window = PetWindow(config, store)
    window.show()

    names = list((config.animations.get("events") or {}).get("workStatus") or [])[:2]
    names += config.actions("clicks")[:2]
    names += [(config.actions("idle") or ["待机呼吸休闲"])[0]]
    for name in names:
        store.animation(name)

    sizes = set()
    errors = []
    cases = 0
    for name in names:
        window.animator.play(name, loop=True)
        for squash in (0.88, 1.0, 1.18, 1.35):
            for bubble in (None, ("这是一句用来撑高窗口的测试气泡文字", 20.0)):
                cases += 1
                try:
                    window.squash = squash
                    if bubble:
                        window.say(bubble[0], None, bubble[1])
                    else:
                        window.clear_bubble()
                    window._mask_key = None          # 强制重建，模拟尺寸变化
                    window.animator._tick()
                    window._repaint()
                    app.processEvents()
                    region = window.mask()
                    if region is None or region.isEmpty():
                        errors.append("%s squash=%.2f bubble=%s: 掩膜为空"
                                      % (name, squash, bool(bubble)))
                    else:
                        rect = region.boundingRect()
                        sizes.add((window.width(), window.height(),
                                   rect.width(), rect.height()))
                except Exception:
                    errors.append("%s squash=%.2f bubble=%s" % (name, squash, bool(bubble)))
                    traceback.print_exc()
            window.clear_bubble()
            window.squash = 1.0

    print("  共跑了 %d 组尺寸组合，出现 %d 种窗口/掩膜尺寸" % (cases, len(sizes)))
    check("没有任何一组抛异常", not errors,
          "；".join(errors[:3]) if errors else "")
    check("掩膜尺寸确实随窗口变化（说明真的在重建）", len(sizes) > 3,
          "%d 种" % len(sizes))
    for item in sorted(sizes)[:5]:
        print("      窗口 %dx%d -> 掩膜 %dx%d" % item)

    window.close()
    print("失败 %d 项" % len(FAILED) if FAILED else "全部通过")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
