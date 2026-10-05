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
    POST /mood                {"mood": "...", "text": "...", "image": "memes/ 下的表情名"}
    POST /say                 {"text": "...", "image": "memes/ 下的表情名"}   只说话，不改工作状态
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

# 请求体上限。`_body()` 会按 Content-Length 一次性读进内存，不设上限的话
# 一个巨大的 Content-Length 就能把桌宠的内存吃满（本机脚本或网页都能发）。
MAX_BODY = 64 * 1024


def make_handler(pet):
    """构造请求处理器。回调都通过 pet 的信号回到 GUI 线程，不在 HTTP 线程里碰界面。"""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "dsh-pet-bridge/1"

        def log_message(self, *_args):
            pass

        # ---- 安全闸门 ------------------------------------------------------ #
        #
        # **只绑回环地址挡不住浏览器。** 浏览器里的 JavaScript 可以直接访问
        # 127.0.0.1 —— 你打开的任何网页（钓鱼站、被植入的恶意广告、论坛里的 XSS）
        # 都能 `fetch('http://127.0.0.1:8899/say', ...)`。后果：
        #
        #   * `/say` `/mood` —— 让桌宠显示任意文字（伪造通知、钓鱼）；
        #   * `/place` `/anim` —— 把宠物挪出屏幕、控制它的动作；
        #   * `/whisper` —— 触发一次模型调用（烧余额）。
        #
        # 插件的 8900 端口更严重：它的 `/chat` 会**用你登录 DSH 的账号调用模型**，
        # 提示词还由那个网页决定。
        #
        # **为什么"加 CORS 头"不管用**：攻击者根本不需要读响应，只要请求**被执行**
        # 就够。而且跨域 POST 在浏览器眼里常常是"简单请求"，**不发预检**，
        # 请求直接就出去了。所以不能靠 CORS，也不能靠检查 Content-Type
        # （浏览器会把简单请求的 Content-Type 降级成 text/plain）。
        #
        # 判据是"**这个请求是不是浏览器发起的**"。实测（tools/probe_request_headers.mjs）
        # 各客户端真实发出的头：
        #
        #   node:http.request（插件投状态）  Origin=无  Sec-Fetch-*=无
        #   Python urllib（chat.py 问插件）   Origin=无  Sec-Fetch-*=无
        #   Node fetch（自检用）             Origin=无  Sec-Fetch-*=**sec-fetch-mode**
        #   浏览器（跨域 fetch / <img> / 表单）Origin=有  Sec-Fetch-*=site,dest,mode
        #
        # 所以**只看 `Sec-Fetch-Site` / `Sec-Fetch-Dest` / `Origin`，不看 `Sec-Fetch-Mode`**：
        # `sec-fetch-mode` 是唯一连 Node 的 fetch（undici）也会发的，拿它当判据会
        # 误伤合法的本机调用方（实测过：自检大面积失败）；而浏览器**必定同时带
        # site 与 dest**，所以排除 mode 一点覆盖都不少。
        BROWSER_HEADERS = ("origin", "sec-fetch-site", "sec-fetch-dest")

        def _is_browser_request(self):
            for key in self.headers.keys():
                if key.lower() in self.BROWSER_HEADERS:
                    return True
            return False

        def _host_ok(self):
            """Host 必须是回环地址 —— 挡 DNS rebinding（纵深防御）。

            攻击者把自己的域名解析到 127.0.0.1，页面就能
            `fetch('http://evil.example:8899/...')` —— 浏览器会把请求发到本机，
            而 `Host` 是 `evil.example`。上面那条闸门已经能挡住现代浏览器的这条路，
            这一条是万一那条被绕开时的第二道。
            """
            host = (self.headers.get("Host") or "").split(":")[0].strip("[]").lower()
            return host in ("", "127.0.0.1", "localhost", "::1")

        def _guard(self):
            """返回 True = 已经拒掉、调用方要立刻 return。

            **拒绝时留一行日志**：这属于安全事件，用户应该有机会知道
            "有网页在试着操控我的桌宠"。日志会自动裁剪，不必担心涨大。
            """
            if self._is_browser_request():
                sys.stderr.write(
                    "dsh-pet: 拒绝了一个浏览器发起的请求 %s（Origin/Sec-Fetch 存在）—— "
                    "可能有网页在尝试操控桌宠\n" % self.path.split("?")[0])
                self._reply(403, {"ok": False, "error": "forbidden"})
                return True
            if not self._host_ok():
                sys.stderr.write(
                    "dsh-pet: 拒绝了一个 Host 不是回环地址的请求 %s（Host=%s）—— "
                    "可能是 DNS rebinding\n"
                    % (self.path.split("?")[0], self.headers.get("Host")))
                self._reply(403, {"ok": False, "error": "forbidden"})
                return True
            return False

        def _reply(self, code, payload=None):
            body = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            # 明确不让浏览器猜类型：万一有人用 <script src> 指过来，
            # nosniff 能让它不去把 JSON 当脚本执行。
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if body:
                self.wfile.write(body)

        def _drain(self, count):
            """把最多 count 字节的请求体读掉丢掉（有上限，内存仍然可控）。

            **为什么要丢**：如果直接不看 body 就回包并关连接，客户端此时还在写，
            它拿到的是一个连接重置（RST）而不是状态码 —— 于是"请求被拒"在调用方
            看来成了"网络坏了"，极难排查。丢掉的部分有上限，所以不会因为大 body
            吃满内存。
            """
            remaining = min(count, MAX_BODY * 4)
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)

        def _body(self):
            """读请求体。超过 MAX_BODY、或 Content-Length 不合法都返回 None。"""
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                return {}
            try:
                length = int(raw_length)
            except (TypeError, ValueError):
                return None
            if length < 0:
                return None
            if length > MAX_BODY:
                self._drain(length)
                return None
            try:
                raw = self.rfile.read(length) if length else b"{}"
                data = json.loads(raw.decode("utf-8") or "{}")
                return data if isinstance(data, dict) else {}
            except Exception:
                return None

        def do_GET(self):
            if self._guard():
                return
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
            if self._guard():
                return
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
