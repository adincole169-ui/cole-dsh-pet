# -*- coding: utf-8 -*-
"""自检：桌宠的本机服务（127.0.0.1:8899）必须挡住**浏览器发起的**请求。

为什么这是真问题（不是理论）
----------------------------
只绑回环地址**挡不住浏览器** —— 你打开的任何网页都能
`fetch('http://127.0.0.1:8899/say', ...)`。于是：

  * `/say` `/mood`  让桌宠显示任意文字（伪造通知、钓鱼）；
  * `/place` `/anim` 把宠物挪出屏幕、控制它的动作；
  * `/whisper`      触发一次模型调用（烧余额）。

而且**加 CORS 头没用**：攻击者不需要读响应，只要请求被执行就够；跨域 POST 在浏览器
眼里常是"简单请求"，**不发预检**，请求直接就出去了。也不能靠检查 Content-Type
（简单请求会被降级成 `text/plain`）。

判据改成"**这个请求是不是浏览器发起的**"：浏览器的请求一定带 `Sec-Fetch-Site`
（现代浏览器对**所有**请求都加，而且是 forbidden header，页面 JS 无法伪造）或
`Origin`；本机的 Python / Node 脚本两个都不带。

这个自检用**真的起一个 HTTP 服务**发真的请求（不是直接调方法），因为要验的正是
"HTTP 头长什么样"这件事。

    python tools/selftest_bridge_security.py
"""

import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

FAILED = []


def check(label, ok, detail=""):
    if isinstance(detail, (list, tuple)):
        detail = " / ".join(str(x) for x in detail if x)
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label,
                         ("  " + str(detail)) if detail else ""))
    if not ok:
        FAILED.append(label)


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class FakeAnimator(object):
    playing = None
    work_status = None
    facing = 1

    def play(self, *_args, **_kwargs):
        return True

    def set_work_status(self, _status):
        pass

    def set_work_status_by_anim(self, *_args):
        pass


def build_fake_pet():
    """一个最小的假桌宠：只提供 HTTP 层真正会碰到的属性。"""
    from PyQt5.QtCore import QObject, pyqtSignal

    class FakePet(QObject):
        mood_signal = pyqtSignal(str, dict)

        def __init__(self):
            super(FakePet, self).__init__()
            self.mood = "idle"
            self.animator = FakeAnimator()
            self.size_px = 320
            self.top_pad = 33
            self.mode = "roam"
            self._manual_move = False
            self.pos_x = 0.0
            self.pos_y = 0.0
            self.bubble = None
            self.mask_stats = {"window": [320, 180]}
            self.whisper_log = []
            self.emitted = []
            self.mood_signal.connect(self._remember)

        def _remember(self, kind, payload):
            self.emitted.append((kind, payload))

        def width(self):
            return 320

        def height(self):
            return 213

        def use_gravity(self):
            return False

    return FakePet()


def request(port, path, body=None, headers=None, method=None):
    """发一个原始请求，返回 (状态码, 响应体)。"""
    url = "http://127.0.0.1:%d%s" % (port, path)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")
    except Exception as error:
        return -1, str(error)


def main():
    try:
        from PyQt5.QtWidgets import QApplication                 # noqa: F401
        from bridge import DEFAULT_PORT, MAX_BODY, make_handler  # noqa: F401
    except ImportError as error:
        print("  需要 PyQt5: %s" % error)
        return 1

    from PyQt5.QtWidgets import QApplication
    from bridge import MAX_BODY, make_handler

    app = QApplication.instance() or QApplication([])            # noqa: F841
    pet = build_fake_pet()
    port = free_port()
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(pet))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.3)

    print()
    print("  自检：本机服务必须挡住浏览器发起的请求")
    print("  " + "=" * 74)
    print("  监听 127.0.0.1:%d（临时端口，测试完关闭）" % port)

    try:
        # --- 1. 合法调用方必须照常工作（否则防护会把自己的通路挡掉）-------- #
        print()
        print("  ① 合法调用方（本机脚本，不带 Origin/Sec-Fetch）")
        print("  " + "-" * 74)
        code, _body = request(port, "/health")
        check("GET /health 正常", code == 200, "状态码 %s" % code)
        code, _body = request(port, "/say", {"text": "你好"},
                              {"Content-Type": "application/json; charset=utf-8"})
        check("POST /say 正常（带 JSON Content-Type）", code == 200, "状态码 %s" % code)
        # **必须让 Qt 投递一次跨线程信号**：HTTP 线程 emit、主线程接收，Qt 用的是
        # **队列连接**，不跑事件循环的话回调永远不会被调用 —— 实测就因此假失败过
        # （"假桌宠收到了 /say 的内容"报 FAIL，而其实是信号还排在队列里）。
        app.processEvents()
        # 插件的 node:http 就是这样发的：有 Content-Type、没有 Origin
        check("假桌宠收到了 /say 的内容",
              any(kind == "say" and payload.get("text") == "你好"
                  for kind, payload in pet.emitted),
              pet.emitted)

        # --- 2. 浏览器发起的请求必须被拒 ---------------------------------- #
        print()
        print("  ② 浏览器发起的请求（必须 403）")
        print("  " + "-" * 74)
        # **按浏览器真实发出的组合测**：浏览器一定**同时**带 `Sec-Fetch-Site`、
        # `Sec-Fetch-Dest`、`Sec-Fetch-Mode` 三个。
        #
        # 这里**故意不测"只带 Sec-Fetch-Mode"**：实测（tools/probe_request_headers.mjs）
        # Node 自己的 fetch（undici）也会发 `sec-fetch-mode`，所以它不能当判据 ——
        # 拿它当判据会误伤合法的本机调用方（自检就会大面积失败）。而单个 mode 也不是
        # 浏览器能发出的请求，测它等于测一个不存在的攻击面。
        browser_cases = [
            ("Origin（跨域 fetch 必带）", {"Origin": "https://evil.example"},
             "/say", {"text": "钓鱼文字"}),
            ("Sec-Fetch-Site: cross-site", {"Sec-Fetch-Site": "cross-site"},
             "/say", {"text": "钓鱼文字"}),
            ("Sec-Fetch-Dest: image（<img> 攻击）", {"Sec-Fetch-Dest": "image"},
             "/place", {"x": 0, "y": 0}),
            ("浏览器真实的三件套（site+dest+mode）",
             {"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Dest": "empty",
              "Sec-Fetch-Mode": "cors"},
             "/say", {"text": "钓鱼文字"}),
            ("Origin 打 /mood", {"Origin": "https://ad.example"},
             "/mood", {"mood": "busy", "text": "假通知"}),
            ("Origin 打 /whisper（会烧余额）", {"Origin": "https://evil.example"},
             "/whisper", {}),
        ]
        for label, headers, path, body in browser_cases:
            merged = dict(headers)
            merged["Content-Type"] = "application/json; charset=utf-8"
            code, _body = request(port, path, body, merged)
            check("%s -> %s" % (label, path), code == 403, "状态码 %s" % code)

        # 浏览器发起的 **GET** 也要挡住（<img> / <script> 这类）
        code, _body = request(port, "/health", None, {"Sec-Fetch-Site": "cross-site"},
                              method="GET")
        check("带 Sec-Fetch 的 GET /health", code == 403, "状态码 %s" % code)

        # 反面：**Node 自己的 fetch 只带 sec-fetch-mode**，那是合法调用方，不该被拒。
        # 这一条是"防护别把自己的通路挡掉"的守门测试。
        code, _body = request(port, "/say", {"text": "合法"},
                              {"Sec-Fetch-Mode": "cors",
                               "Content-Type": "application/json; charset=utf-8"})
        check("只带 Sec-Fetch-Mode（Node fetch 就是这样）**放行**",
              code == 200, "状态码 %s" % code)

        # --- 3. 关键：被拒的请求**不能产生副作用** ------------------------ #
        print()
        print("  ③ 被拒的请求不得产生任何副作用")
        print("  " + "-" * 74)
        app.processEvents()
        before = len(pet.emitted)
        request(port, "/say", {"text": "绝不该出现"},
                {"Origin": "https://evil.example",
                 "Content-Type": "application/json; charset=utf-8"})
        request(port, "/mood", {"mood": "busy", "text": "假通知"},
                {"Origin": "https://evil.example",
                 "Content-Type": "application/json; charset=utf-8"})
        app.processEvents()
        check("被拒之后假桌宠没有收到任何信号", len(pet.emitted) == before,
              "信号数 %d -> %d" % (before, len(pet.emitted)))

        # --- 4. Host 头必须是回环地址（DNS rebinding）--------------------- #
        print()
        print("  ④ Host 头必须是回环地址（挡 DNS rebinding）")
        print("  " + "-" * 74)
        code, _body = request(port, "/say", {"text": "rebind"},
                              {"Host": "evil.example",
                               "Content-Type": "application/json; charset=utf-8"})
        check("Host: evil.example 被拒", code == 403, "状态码 %s" % code)
        for host in ("127.0.0.1:%d" % port, "localhost:%d" % port):
            code, _body = request(port, "/say", {"text": "ok"}, {"Host": host,
                                  "Content-Type": "application/json; charset=utf-8"})
            check("Host: %s 放行" % host, code == 200, "状态码 %s" % code)

        # --- 5. 请求体上限 ------------------------------------------------- #
        print()
        print("  ⑤ 请求体上限（防内存耗尽）")
        print("  " + "-" * 74)
        check("MAX_BODY 是个不大的值", 0 < MAX_BODY <= 1024 * 1024, MAX_BODY)
        huge = {"text": "x" * (MAX_BODY + 1024)}
        code, _body = request(port, "/say", huge,
                              {"Content-Type": "application/json; charset=utf-8"})
        check("超过 %d 字节的 body 被拒" % MAX_BODY, code == 400, "状态码 %s" % code)

        # --- 6. nosniff ----------------------------------------------------- #
        print()
        print("  ⑥ 响应头不应让浏览器猜类型")
        print("  " + "-" * 74)
        raw = urllib.request.urlopen("http://127.0.0.1:%d/health" % port, timeout=8)
        check("带 X-Content-Type-Options: nosniff",
              (raw.headers.get("X-Content-Type-Options") or "").lower() == "nosniff",
              raw.headers.get("X-Content-Type-Options"))
        raw.close()

    finally:
        server.shutdown()
        server.server_close()

    print()
    print("  结论")
    print("  " + "=" * 74)
    if FAILED:
        for item in FAILED:
            print("     [失败] %s" % item)
        print()
        print("  共 %d 项失败" % len(FAILED))
        return 1
    print("     [OK] 合法调用方照常工作；浏览器发起的请求、非回环 Host、超大 body 全部被拒")
    print("     [OK] 被拒的请求没有产生任何副作用（信号数没变）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
