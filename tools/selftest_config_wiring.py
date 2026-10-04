# -*- coding: utf-8 -*-
"""自检：`config.jsonc` 里的开关是否**真的生效**。

写这个脚本的原因：这几个开关曾经只是被解析成属性、没有任何代码读它们——用户在配置
里关掉碎碎念，插件照样每 5 分钟推一句；关掉工作状态，宠物照样跟着会话切动画。这种
"改了不生效"只看代码很难发现，所以这里逐个开关**做对照**：开着与关掉，行为必须不同。

    python tools/selftest_config_wiring.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from config import PetConfig, load, pet_configs
from frames import FrameStore
from main import build_app
from pet import PetWindow

FAILED = []


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label, ("  " + detail) if detail else ""))
    if not ok:
        FAILED.append(label)


def make_window(app, overrides):
    """按主配置派生出窗口，`overrides` 用来改开关。"""
    base = load()
    entry = dict((base.get("pets") or [{}])[0])
    entry.update(overrides)
    config = PetConfig(entry, base)
    store = FrameStore(keep=3)
    window = PetWindow(config, store)
    window.show()
    window.animator.play((config.actions("idle") or ["待机呼吸休闲"])[0], loop=True)
    for _ in range(6):
        window.animator._tick()
        window._repaint()
        app.processEvents()
    return window


def main(argv):
    app = build_app([argv[0]])

    # --- workStatusEnabled：关掉后不该跟着 mood 切动画 ---
    on = make_window(app, {"workStatusEnabled": True})
    on.apply_mood("thinking")
    for _ in range(4):
        on.animator._tick()
        app.processEvents()
    on_name = on.animator.playing.name if on.animator.playing else None
    on.close()

    off = make_window(app, {"workStatusEnabled": False})
    off.apply_mood("thinking")
    for _ in range(4):
        off.animator._tick()
        app.processEvents()
    off_name = off.animator.playing.name if off.animator.playing else None
    off.close()

    check("workStatusEnabled=false 时不再切工作状态动画",
          on_name != off_name and "工作状态" not in (off_name or ""),
          "开=%s  关=%s" % (on_name, off_name))

    # --- balanceEnabled：关掉后分档不该有任何表现 ---
    usage_off = make_window(app, {"balanceEnabled": False})
    applied = usage_off.apply_usage(3, "测试")
    check("balanceEnabled=false 时忽略用量分档", applied is False)
    usage_off.close()

    usage_on = make_window(app, {"balanceEnabled": True})
    applied = usage_on.apply_usage(3, "测试")
    check("balanceEnabled=true 时执行用量分档", applied is True)
    usage_on.close()

    # --- whisperEnabled：关掉后连周期触发都不做 ---
    whisper_off = make_window(app, {"whisperEnabled": False})
    before = whisper_off.bubble
    whisper_off.whisper_now(announce=False)
    check("whisperEnabled=false 时 whisper_now 直接返回",
          whisper_off.bubble is before, "bubble=%s" % (whisper_off.bubble,))
    whisper_off.close()

    # --- notificationsEnabled / 其余字段是否被解析 ---
    config = PetConfig({"id": "t"}, load())
    for field in ("notificationsEnabled", "balanceEnabled", "whisperEnabled",
                  "workStatusEnabled", "fixedEnabled"):
        check("PetConfig 暴露 %s" % field, hasattr(config, field))
    for field in ("chat_memory_rounds", "chat_image_enabled", "chat_image_limit",
                  "whisper_image_enabled", "whisper_model", "chat_model"):
        check("PetConfig 暴露 %s" % field, hasattr(config, field))

    # --- 对话客户端会把配置带进请求 ---
    from chat import ChatClient, meme_names
    client = ChatClient(59999, PetConfig({"chatMemoryRounds": 3, "chatImageEnabled": False}, load()))
    payload = client._payload("你好", "chat")
    check("对话请求带上 memoryRounds", payload.get("memoryRounds") == 3,
          "=%s" % payload.get("memoryRounds"))
    check("对话请求带上 imageEnabled", payload.get("imageEnabled") is False)
    check("对话请求带上可用表情清单", isinstance(payload.get("memes"), list),
          "%d 个" % len(payload.get("memes") or []))
    check("表情清单与实际文件一致", len(payload.get("memes") or []) == len(meme_names()),
          "目录 %d 个" % len(meme_names()))

    print("失败 %d 项" % len(FAILED) if FAILED else "全部通过")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
