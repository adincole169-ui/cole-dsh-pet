# -*- coding: utf-8 -*-
"""自检：给用户看的名字必须一致，且不能是内部物种名。

为什么需要它：用户报"任务栏里显示的是蓝毛小女仆"。根因是窗口标题用的是
`config.name`——那是**内部物种名**，同时还是素材目录与物种配置的键
（`frames\\<name>\\`、`pet\\<name>-config.json`）。而托盘提示又硬编了另一个字符串，
通知里甚至还有第三个常量。同一只宠物在三处名字都不一样。

现在统一到 `config.displayName`（不写则退回物种名），本自检钉住三件事：
  1. `displayName` 能被配置读到，并且**实例值优先于全局值**；
  2. 窗口标题、托盘提示、通知标题都用同一个名字；
  3. 名字**不等于**内部物种名时，前两处必须用的是 displayName 而不是 name。

    python tools/selftest_display_name.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from config import PetConfig                  # noqa: E402
from frames import FrameStore                 # noqa: E402
from main import build_app                    # noqa: E402
from pet import PetWindow                     # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label,
                         ("  " + detail) if detail else ""))
    if not ok:
        FAILED.append(label)


def main(argv):
    app = build_app([argv[0]])

    print("  -- displayName 的取值优先级 --")
    # 实例值优先
    entry = PetConfig({"name": "蓝毛小女仆", "displayName": "大肥鱼"})
    check("实例 displayName 生效", entry.display_name == "大肥鱼",
          "display_name=%r" % entry.display_name)
    check("内部物种名不受影响", entry.name == "蓝毛小女仆",
          "name=%r" % entry.name)

    # 退回全局
    global_cfg = PetConfig({"name": "夜猫", "displayName": "全局名"},
                           {"displayName": "全局名"}) if False else None
    from config import PetConfig as PC
    entry2 = PC({"name": "夜猫"}, {"displayName": "全局名"})
    check("实例没写时用全局 displayName", entry2.display_name == "全局名",
          "display_name=%r" % entry2.display_name)

    # 都没有则退回物种名
    entry3 = PC({"name": "夜猫"})
    check("两处都没写时退回物种名", entry3.display_name == "夜猫",
          "display_name=%r" % entry3.display_name)

    # 空白字符串也算"没写"
    entry4 = PC({"name": "夜猫", "displayName": "   "})
    check("displayName 是空白时退回物种名", entry4.display_name == "夜猫",
          "display_name=%r" % entry4.display_name)

    print("  -- 窗口与托盘用同一个名字 --")
    from config import load, pet_configs
    config = pet_configs(load())[0]
    window = PetWindow(config, FrameStore(keep=2))
    title = window.windowTitle()
    method = window.display_name()
    check("窗口标题 == display_name()", title == method,
          "title=%r  display_name()=%r" % (title, method))
    check("窗口标题不是内部物种名", title != config.name,
          "title=%r  config.name=%r" % (title, config.name))
    check("窗口标题非空", bool(title.strip()))
    check("托盘提示以同一个名字开头", window.tray.toolTip().startswith(method),
          "tooltip=%r" % window.tray.toolTip())

    print("  -- 通知用的是显示名 --")
    sent = []
    import pet as pet_module
    original_notify = pet_module.notify
    original_watch = pet_module.user_is_watching
    pet_module.notify = lambda t, m: sent.append((t, m))
    pet_module.user_is_watching = lambda: False
    try:
        window._last_notify = 0.0
        window._maybe_notify("测试消息")
        check("通知标题 == 显示名", bool(sent) and sent[0][0] == method,
              "sent=%r" % (sent,))
    finally:
        pet_module.notify = original_notify
        pet_module.user_is_watching = original_watch

    window.close()
    print("失败 %d 项" % len(FAILED) if FAILED else "全部通过")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
