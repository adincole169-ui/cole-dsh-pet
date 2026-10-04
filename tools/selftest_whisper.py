# -*- coding: utf-8 -*-
"""自检：桌宠自己的碎碎念通路（`ChatClient` → 插件 → 气泡）。

为什么单独测这个：插件侧单独调用是好的（能返回台词与表情），但用户点右键"没有反应"。
差别只能在桌宠这一侧的代码路径上——请求体的构造、回调的触发、气泡的更新。所以这里
**不绕过它**，直接用 `ChatClient` 发请求，然后看 `on_done` 有没有被调用、气泡有没有变。

    python tools/selftest_whisper.py
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from chat import ChatClient, meme_names
from config import load, pet_configs

FAILED = []


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label, ("  " + detail) if detail else ""))
    if not ok:
        FAILED.append(label)


def main():
    config = pet_configs(load())[0]
    port = int(config.position.get("chatPort") or 8900)

    print("  配置: whisperEnabled=%s  prompt=%d 字  表情=%d 个"
          % (getattr(config, "whisperEnabled", None),
             len(getattr(config, "whisper_prompt", "") or ""), len(meme_names())))

    client = ChatClient(port, config)
    check("能探到模型服务", client.available())

    # 先看请求体长什么样——字段名错一个就会让插件按默认值处理
    payload = client._payload("说一句碎碎念。", "whisper")
    print("  请求体字段: %s" % ", ".join(sorted(payload.keys())))
    check("请求体带 kind=whisper", payload.get("kind") == "whisper")
    check("请求体带 system 提示词", bool(payload.get("system")))
    check("请求体带表情清单", bool(payload.get("memes")))

    result = {}
    started = time.time()
    client.ask("说一句碎碎念。", lambda text, image: result.update(done=(text, image)),
               lambda reason: result.update(error=reason), kind="whisper")

    for _ in range(60):
        if result:
            break
        time.sleep(0.5)
    elapsed = time.time() - started

    print("  %.1fs 后回调: %s" % (elapsed, result or "（没有任何回调）"))
    check("on_done 或 on_error 被调用", bool(result))
    if "done" in result:
        text, image = result["done"]
        check("拿到了台词", bool(text.strip()), "text=%r" % text)
        print("  台词: %s" % text)
        print("  配图: %s" % (image or "（无）"))
    if "error" in result:
        print("  错误: %s" % result["error"])

    print("失败 %d 项" % len(FAILED) if FAILED else "全部通过")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
