# -*- coding: utf-8 -*-
"""对话客户端：桌宠主动去问 DSH 侧的模型服务。

方向与 bridge.py 相反——模型只存在于 DSH 里，所以这一侧必须由桌宠"打出去"：

    桌宠  --POST /chat-->  127.0.0.1:8900（dsh-pet-bridge 插件）
          <--{text,image}-- 

插件没装或没起时，请求会失败，这时桌宠回一句自己的台词，而不是静默——用户点了
"聊两句"却什么都不发生，比报错更让人困惑。

**配置归桌宠管**：提示词、记忆轮数、是否配图、可选表情清单都随请求带给插件。
这样改 `config.jsonc` 里的这些字段会真的生效，不必去改 DSH profile 的插件配置——
两处各管一半最容易让人改错地方。
"""

import json
import os
from threading import Thread
from urllib.error import URLError
from urllib.request import Request, urlopen

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MEME_DIR = os.path.join(ROOT, "memes")

DEFAULT_CHAT_PORT = 8900
TIMEOUT = 60


def meme_names():
    """表情包文件名（不含扩展名）——这些就是插件可以挑的键。"""
    if not os.path.isdir(MEME_DIR):
        return []
    return sorted(os.path.splitext(name)[0] for name in os.listdir(MEME_DIR)
                  if name.lower().endswith(".png"))


class ChatClient(object):
    """把提问送到插件，结果通过回调交回 GUI 线程。"""

    def __init__(self, port=DEFAULT_CHAT_PORT, config=None):
        self.port = int(port)
        self.config = config

    def _payload(self, text, kind):
        """把该生效的配置随请求发出去（`kind` 是 chat 或 whisper）。"""
        config = self.config
        payload = {"text": text, "kind": kind, "memes": meme_names()}
        if config is None:
            return payload

        if kind == "whisper":
            payload["system"] = getattr(config, "whisper_prompt", "") or ""
            payload["imageEnabled"] = bool(getattr(config, "whisper_image_enabled", True))
            model = getattr(config, "whisper_model", None) or {}
        else:
            payload["system"] = ""
            payload["imageEnabled"] = bool(getattr(config, "chat_image_enabled", True))
            model = getattr(config, "chat_model", None) or {}

        payload["memoryRounds"] = int(getattr(config, "chat_memory_rounds", 5))
        limit = int(getattr(config, "chat_image_limit", 10))
        if kind == "chat" and limit > 0:
            payload["memes"] = payload["memes"][:limit]
        if isinstance(model, dict):
            payload["provider"] = model.get("provider") or ""
            payload["model"] = model.get("model") or ""
        return payload

    def available(self):
        """插件在不在。不可用时让菜单能提示用户，而不是点了没反应。"""
        try:
            with urlopen("http://127.0.0.1:%d/health" % self.port, timeout=2) as response:
                return json.loads(response.read().decode("utf-8")).get("ok") is True
        except Exception:
            return False

    def ask(self, text, on_done, on_error=None, kind="chat"):
        """异步提问。`on_done(text, image)` 会在后台线程里被调用。"""
        def worker():
            payload = json.dumps(self._payload(text, kind), ensure_ascii=False).encode("utf-8")
            request = Request(
                "http://127.0.0.1:%d/chat" % self.port,
                data=payload,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )
            try:
                with urlopen(request, timeout=TIMEOUT) as response:
                    data = json.loads(response.read().decode("utf-8"))
                on_done(str(data.get("text") or ""), str(data.get("image") or ""))
            except URLError as error:
                if on_error:
                    on_error(str(getattr(error, "reason", error)))
            except Exception as error:
                if on_error:
                    on_error(str(error))

        thread = Thread(target=worker, daemon=True)
        thread.start()
        return thread
