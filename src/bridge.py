# -*- coding: utf-8 -*-
"""本机联动桥：桌宠自己起一个小 HTTP 服务，DSH 侧的插件往里投状态与台词。

为什么是"桌宠起服务、插件来投"而不是反过来
--------------------------------------------
桌宠必须在**没有任何 DSH 插件**时也能独立运行（用户可能没装、或装的是旧版本）。
让桌宠持有服务端，插件只是可选的发送方，这个方向天然满足这个约束：

    DSH 插件（host 半）  --POST-->  http://127.0.0.1:<port>/mood
    桌宠                 <--200--   {ok:true}

服务只绑回环地址，不对外暴露。

接口
----
    GET  /health              -> {ok, mood, status, playing}
    POST /mood                {"mood": "...", "text": "...", "image": "图片路径或名称"}
    POST /say                 {"text": "...", "image": "..."}   只说话，不改工作状态
    POST /anim                {"name": "动画名", "loop": true}   直接点播一个动画

`mood` 取值直接对应 dsh-pet 的工作状态档位：thinking / busy / filing / roaming /
celebrating / sighing，以及 idle（回到自由活动）。
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

DEFAULT_PORT = 8899


def make_handler(pet):
    """构造请求处理器。回调都通过 pet 的信号回到 GUI 线程，不在 HTTP 线程里碰界面。"""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "dsh-pet-bridge/1"

        def log_message(self, *_args):
            pass

        def _reply(self, code, payload=None):
            body = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _body(self):
            try:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                data = json.loads(raw.decode("utf-8") or "{}")
                return data if isinstance(data, dict) else {}
            except Exception:
                return None

        def do_GET(self):
            path = self.path.split("?")[0].rstrip("/") or "/"
            if path == "/health":
                self._reply(200, {
                    "ok": True,
                    "mood": pet.mood,
                    "playing": pet.animator.playing.name if pet.animator.playing else None,
                    "workStatus": pet.animator.work_status,
                })
            elif path == "/whisperlog":
                # 碎碎念每一步的流水（POST 侧写入）。排查"点了没反应"时看这个。
                self._reply(200, {"ok": True, "log": list(pet.whisper_log)})
            elif path == "/debug":
                # 动画切换涉及"请求 → 后台加载 → 接上"三步，出问题时必须能看到
                # 每一步的状态，否则只能看到"还在播上一个"这一种症状。
                playing = pet.animator.playing
                self._reply(200, {
                    "ok": True,
                    "playing": playing.name if playing else None,
                    "ready": bool(playing.ready) if playing else False,
                    "workStatus": pet.animator.work_status,
                    "cached": pet.store.stats()["cached"],
                    "loading": pet.store.stats()["loading"],
                    "reloads": pet.store.stats()["reloads"],
                    "bubble": pet.bubble[0] if pet.bubble else None,
                    # 尺寸与输入掩膜：用来确认"占用区域"到底缩到多小
                    "sizePx": pet.size_px,
                    "window": [pet.width(), pet.height()],
                    "gravity": pet.use_gravity(),
                    # 位置与模式：验证"原地待着"到底有没有生效，必须看这两个——
                    # 只看窗口尺寸会误判（气泡会让尺寸变化，但位置未必动）。
                    "pos": [round(pet.pos_x, 1), round(pet.pos_y, 1)],
                    "mode": getattr(pet, "mode", None),
                    "manualMove": bool(getattr(pet, "_manual_move", False)),
                    "mask": pet.mask_stats,
                    "topPad": int(pet.top_pad),
                })
            else:
                self._reply(404)

        def do_POST(self):
            path = self.path.split("?")[0].rstrip("/") or "/"
            data = self._body()
            if data is None:
                self._reply(400)
                return

            if path == "/mood":
                node = pet.mood_signal
                node.emit("mood", {
                    "mood": str(data.get("mood") or "idle"),
                    "text": data.get("text") if isinstance(data.get("text"), str) else "",
                    "image": data.get("image") if isinstance(data.get("image"), str) else "",
                })
                self._reply(200, {"ok": True})
                return

            if path == "/say":
                node = pet.mood_signal
                node.emit("say", {
                    "text": data.get("text") if isinstance(data.get("text"), str) else "",
                    "image": data.get("image") if isinstance(data.get("image"), str) else "",
                    "seconds": data.get("seconds") if isinstance(data.get("seconds"), (int, float)) else None,
                })
                self._reply(200, {"ok": True})
                return

            if path == "/usage":
                # 用量分档（原设计是余额分档，当前 DSH 无余额接口，见 pet.apply_usage）
                tier = data.get("tier")
                if not isinstance(tier, (int, float)):
                    self._reply(400, {"ok": False, "error": "需要 tier"})
                    return
                node = pet.mood_signal
                node.emit("usage", {
                    "tier": int(tier),
                    "text": data.get("text") if isinstance(data.get("text"), str) else "",
                })
                self._reply(200, {"ok": True})
                return

            if path == "/mode":
                # 切换"自由活动 / 原地待着"。加它主要是为了让**实机**也能被验证：
                # 这个 bug（原地待着却还在走）只有一只真窗口能复现，光靠自检不够。
                # 顺带也方便脚本化操作。
                mode = "still" if str(data.get("mode", "")).lower() in ("still", "固定", "原地") else "roam"
                pet.mood_signal.emit("mode", {"mode": mode})
                self._reply(200, {"ok": True, "mode": mode})
                return

            if path == "/whisper":
                # 让运行中的这只**自己**走一次碎碎念，并把它内部的每一步记下来。
                # 我在独立进程里测是通的，但用户那只不出气泡——差别只能在"这一只
                # 进程的内部状态"上，所以必须让它自己报告，而不是我在外面推断。
                node = pet.mood_signal
                node.emit("whisper", {"announce": bool(data.get("announce", True))})
                self._reply(200, {"ok": True})
                return

            if path == "/place":
                # 恢复用：把宠物搬回屏幕内并（可选）改尺寸。
                # "看不见"的时候，最有用的是能一条命令把它挪到屏幕正中，
                # 而不是靠猜它去了哪儿。
                node = pet.mood_signal
                node.emit("place", {
                    "x": data.get("x") if isinstance(data.get("x"), (int, float)) else None,
                    "y": data.get("y") if isinstance(data.get("y"), (int, float)) else None,
                    "size": data.get("size") if isinstance(data.get("size"), (int, float)) else None,
                    "center": bool(data.get("center")),
                })
                self._reply(200, {"ok": True})
                return

            if path == "/anim":
                name = data.get("name")
                if not isinstance(name, str) or not name:
                    self._reply(400, {"ok": False, "error": "需要 name"})
                    return
                node = pet.mood_signal
                node.emit("anim", {"name": name, "loop": bool(data.get("loop"))})
                self._reply(200, {"ok": True})
                return

            self._reply(404)

    return Handler


def start(pet, port=DEFAULT_PORT):
    """启动桥服务；端口被占时返回 None（桌宠照常运行，只是没有联动）。"""
    try:
        server = ThreadingHTTPServer(("127.0.0.1", int(port)), make_handler(pet))
    except OSError as error:
        sys.stderr.write("dsh-pet: 联动端口 %s 不可用（%s），桌宠继续独立运行\n" % (port, error))
        return None
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.4}, daemon=True)
    thread.start()
    return server
