# -*- coding: utf-8 -*-
"""对比两种请求体在插件上的返回，定位"桌宠发就没词"的差异。

先前的观察：手动构造的请求体能拿到台词，而桌宠自己的 `ChatClient` 拿到空文本。
两者唯一的差别是请求体字段的内容（提示词、表情清单、imageEnabled 等），所以这里
把两边都打出来直接比对。

    python tools/probe_whisper_payload.py
"""

import io
import json
import sys
import time
from urllib.request import Request, urlopen

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

HERE = "E:/dsh/pet"
sys.path.insert(0, HERE + "/src")
from chat import ChatClient, meme_names  # noqa: E402
from config import load, pet_configs     # noqa: E402

PORT = 8900


def raw_call(payload, label):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request("http://127.0.0.1:%d/chat" % PORT, data=body,
                      headers={"Content-Type": "application/json; charset=utf-8"})
    started = time.time()
    try:
        with urlopen(request, timeout=90) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as error:
        print("  %-10s 失败: %s" % (label, error))
        return None
    print("  %-10s %.1fs  text=%r  error=%r  image=%r"
          % (label, time.time() - started, data.get("text"), data.get("error"),
             data.get("image")))
    return data


config = pet_configs(load())[0]
pet_payload = ChatClient(PORT, config)._payload("说一句碎碎念。", "whisper")

# A：完全照抄桌宠的请求体
raw_call(dict(pet_payload), "桌宠原样")

# B：换掉提示词（短一点的）
short = dict(pet_payload)
short["system"] = "说一句20字以内的碎碎念。"
raw_call(short, "短提示词")

# C：去掉表情清单
no_memes = dict(pet_payload)
no_memes["memes"] = []
raw_call(no_memes, "无表情")

# D：既短又无表情
both = dict(pet_payload)
both["system"] = "说一句20字以内的碎碎念。"
both["memes"] = []
raw_call(both, "短+无表情")

print()
print("  桌宠提示词实际内容:")
print("   ", pet_payload.get("system"))
print("  表情清单:", pet_payload.get("memes"))
print("  表情目录实际:", meme_names())
