# -*- coding: utf-8 -*-
"""自检：没有 DSH 时桌宠能不能独立运行。

设计上是"桌宠自己持有显示服务，插件只是可选的发送方"，所以 DSH 不存在时应当：
动画照常播、物理照常跑、跨屏漫游照常；只有"碎碎念/对话"这类要用模型的功能应当
**明确告诉你连不上**，而不是静默没反应。

这里不去动真正的 DSH，而是把桌宠的对话端口指到一个**没人监听**的端口，等价于
"DSH 没开"。

    python tools/selftest_standalone.py
"""

import os
import sys

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
    config = load()
    entry = pet_configs(config)[0]
    # 指向一个几乎不可能有人监听的端口 == 模拟"DSH 没开"
    entry.position = dict(entry.position or {})
    entry.position["chatPort"] = 59999

    store = FrameStore(keep=4)
    window = PetWindow(entry, store)
    window.show()
    print("  对话端口指向 59999（等价于 DSH 没开）")

    # 1) 动画链能自己跑起来
    for _ in range(40):
        window.animator._tick()
        window.tick()
        app.processEvents()
    playing = window.animator.playing
    check("动画链自转", playing is not None, "当前 %s" % (playing.name if playing else None))
    check("能画出帧", window.animator.current_frame() is not None)

    # 2) 物理能自己跑（重力/漫游不依赖任何外部服务）
    before = (window.x(), window.y())
    for _ in range(40):
        window.tick()
        app.processEvents()
    check("物理在推进", (window.x(), window.y()) != before or window.animator.playing is not None)

    # 3) 点击回应、大小、菜单都能用
    check("点击回应可播", window.animator.play_click())
    window.set_size(320)
    app.processEvents()
    check("改大小可用", window.size_px == 320, "%dx%d" % (window.width(), window.height()))
    check("菜单已建立", window.menu is not None and len(window.menu.actions()) > 0,
          "%d 项" % len(window.menu.actions()))

    # 4) 依赖模型的功能必须"明确报错"，而不是静默
    window.chat_client = None
    window.say("", None, 1.0)
    from chat import ChatClient
    client = ChatClient(59999)
    check("探不到模型服务", client.available() is False)

    reached = {}
    client.ask("测试", lambda text, image: reached.setdefault("done", text),
               lambda reason: reached.setdefault("error", reason))
    for _ in range(60):
        app.processEvents()
        if reached:
            break
        import time
        time.sleep(0.1)
    check("连不上时走错误分支（不静默）", "error" in reached,
          "回调=%s" % (list(reached.keys()),))

    window.close()
    print("失败 %d 项" % len(FAILED) if FAILED else "全部通过")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
