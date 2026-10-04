# -*- coding: utf-8 -*-
"""自检：系统通知的触发条件与限流。

为什么单独测：这条功能**曾经是静默失效的**——触发条件写成"窗口先获得焦点、再失去
焦点"，而桌宠窗口带 `WA_ShowWithoutActivating`，本来就极少拿到焦点，于是通知永远
不弹，而开关看起来又是"已接"的。所以这里必须把"什么情况下该弹/不该弹"钉死。

     python tools/selftest_notify.py
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

import pet as P                                    # noqa: E402
from config import load, pet_configs               # noqa: E402
from frames import FrameStore                      # noqa: E402
from main import build_app                         # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label,
                         ("  " + detail) if detail else ""))
    if not ok:
        FAILED.append(label)


def main(argv):
    app = build_app([argv[0]])
    config = pet_configs(load())[0]
    window = P.PetWindow(config, FrameStore(keep=2))
    window.show()

    # 拦截真正的 toast：这里只关心"该不该弹"，不关心 PowerShell
    sent = []
    P.notify = lambda title, message: sent.append((title, message))

    print("  -- 前台判断 --")
    watching = P.user_is_watching()
    print("     当前前台是否 DSH: %s" % watching)
    check("user_is_watching 返回布尔值", isinstance(watching, bool))

    print("  -- 该弹的时候弹 --")
    window._last_notify = 0.0
    original = P.user_is_watching
    P.user_is_watching = lambda pet_name="": False      # 假装用户在看别处
    sent.clear()
    fired = window._maybe_notify("测试一")
    check("用户没看 DSH 时会弹", fired and len(sent) == 1, "sent=%d" % len(sent))

    print("  -- 不该弹的时候不弹 --")
    P.user_is_watching = lambda pet_name="": True       # 假装用户在看着
    window._last_notify = 0.0
    sent.clear()
    fired = window._maybe_notify("测试二")
    check("用户正看着 DSH 时不弹", (not fired) and not sent)

    print("  -- 限流 --")
    P.user_is_watching = lambda pet_name="": False
    window._last_notify = time.monotonic()
    sent.clear()
    fired = window._maybe_notify("测试三")
    check("冷却期内不重复弹", (not fired) and not sent,
          "冷却 %ss" % P.NOTIFY_COOLDOWN)
    window._last_notify = time.monotonic() - P.NOTIFY_COOLDOWN - 1
    sent.clear()
    fired = window._maybe_notify("测试四")
    check("冷却期过后可以弹", fired and len(sent) == 1)

    print("  -- 开关 --")
    window.config.notificationsEnabled = False
    window._last_notify = 0.0
    sent.clear()
    fired = window._maybe_notify("测试五")
    check("notificationsEnabled=false 时不弹", (not fired) and not sent)
    window.config.notificationsEnabled = True

    print("  -- 状态挂钩 --")
    P.user_is_watching = lambda pet_name="": False
    window._last_notify = 0.0
    sent.clear()
    window.apply_mood("celebrating", "")
    check("celebrating（干完了）会通知", len(sent) == 1, "sent=%r" % (sent,))
    window._last_notify = 0.0
    sent.clear()
    window.apply_mood("busy", "")
    check("busy（忙碌）不通知（避免刷屏）", not sent)
    window._last_notify = 0.0
    sent.clear()
    window.apply_mood("sighing", "")
    check("sighing（出错了）会通知", len(sent) == 1, "sent=%r" % (sent,))

    P.user_is_watching = original
    print("失败 %d 项" % len(FAILED) if FAILED else "全部通过")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
