# -*- coding: utf-8 -*-
"""自检：右键「和我说句话」（`PetWindow.open_chat`）的界面路径。

为什么单独测：`ChatClient` 本身有覆盖（`selftest_standalone.py`、
`selftest_config_wiring.py`），但**界面那一层从来没被测过**——它第一句就是
`QInputDialog.getText(...)`，会阻塞等人输入，自动化里跑不起来。

这里用替换 `QInputDialog` 的办法把输入框变成"预先给好的答复"，于是四条分支
（正常提问 / 用户取消 / 输入空白 / 连不上服务）都能自动化。

    python tools/selftest_open_chat.py
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from PyQt5.QtWidgets import QInputDialog            # noqa: E402

from config import load, pet_configs                # noqa: E402
from frames import FrameStore                       # noqa: E402
from main import build_app                          # noqa: E402
from pet import PetWindow                           # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label,
                         ("  " + detail) if detail else ""))
    if not ok:
        FAILED.append(label)


def pump(app, window, seconds, step=0.033):
    for _ in range(max(1, int(seconds / step))):
        window.animator._tick()
        window.tick()
        window._repaint()
        app.processEvents()


def main(argv):
    app = build_app([argv[0]])
    config = pet_configs(load())[0]
    window = PetWindow(config, FrameStore(keep=4))
    window.show()
    # 这里**不能**断开 `mood_signal`：`open_chat` 的完成回调正是通过它投递回答的，
    # 断掉就永远收不到（第一版这么干，结果误判成"没拿到回答"）。
    # 也不需要断开：桥服务只在 `main()` 里启动，本测试直接建窗口，
    # 进程里没有 HTTP 服务，实时插件推不进来。
    idle = (config.actions("idle") or ["待机呼吸休闲"])[0]
    window.store.animation(idle)
    window.animator.play(idle, loop=True)
    pump(app, window, 0.3)

    original_get_text = QInputDialog.getText
    answer = {"text": "", "ok": False}

    def fake_get_text(*_args, **_kwargs):
        return answer["text"], answer["ok"]

    QInputDialog.getText = staticmethod(fake_get_text)
    try:
        print("  -- 用户取消（ok=False）不提问 --")
        answer.update(text="", ok=False)
        window.bubble = None
        window.open_chat()
        check("取消后不出现等待气泡", window.bubble is None,
              "bubble=%r" % (window.bubble,))

        print("  -- 输入全空白也不提问 --")
        answer.update(text="   \n  ", ok=True)
        window.bubble = None
        window.open_chat()
        check("空白输入后不出现等待气泡", window.bubble is None,
              "bubble=%r" % (window.bubble,))

        print("  -- 正常提问：先出等待气泡，再拿到回答 --")
        answer.update(text="你好呀", ok=True)
        window.open_chat()
        first = window.bubble[0] if window.bubble else None
        check("立刻出现等待气泡", bool(first), "bubble=%r" % (first,))
        # 等模型（真实调用，可能要几十秒）
        seen = {first}
        deadline = time.time() + 75
        while time.time() < deadline:
            pump(app, window, 0.2)
            if window.bubble:
                seen.add(window.bubble[0])
            if first and window.bubble and window.bubble[0] != first:
                break
        final = window.bubble[0] if window.bubble else None
        print("      气泡文本经历了: %r" % (sorted(seen),))
        check("拿到了回答（不再是等待气泡）",
              bool(final) and final != first, "final=%r" % (final,))
        if final:
            print("      回答: %s" % final)

        print("  -- 连不上服务时给提示而不是静默 --")
        bad = PetWindow(pet_configs(load())[0], FrameStore(keep=2))
        bad.chat_port = 59998            # 没人监听的端口
        bad.open_chat()
        note = bad.bubble[0] if bad.bubble else None
        check("探不到服务时出了提示气泡", bool(note), "bubble=%r" % (note,))
        bad.close()
    finally:
        QInputDialog.getText = original_get_text

    window.close()
    print("失败 %d 项" % len(FAILED) if FAILED else "全部通过")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
