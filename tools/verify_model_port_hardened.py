# -*- coding: utf-8 -*-
"""验证：重启 DSH 之后，8900（插件的模型服务）是否已经挡住浏览器发起的请求。

只在**用户重启 DSH 之后**跑。分两组：

  * 应当被拒的（浏览器路径）—— 全部用 `/health`（只读），**不会调模型、不花余额**；
  * 应当放行的（本机调用方）—— 同样先用 `/health`，最后才做一次**最小的** `/chat`
    端到端确认（那一次会真的调模型，所以提示词尽量短）。

为什么要单独写：8900 的防护要等 DSH 重启才生效（插件是启动时加载的，不热重载），
而"磁盘上文件已是新版"**不等于**"内存里跑的是新版" —— 这两件事必须分开验。

    python tools/verify_1900_hardened.py
"""

import json
import sys
import urllib.error
import urllib.request

PORT = 8900
BASE = "http://127.0.0.1:%d" % PORT
FAILED = []


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label,
                         ("  " + str(detail)) if detail else ""))
    if not ok:
        FAILED.append(label)


def request(path, body=None, headers=None, method=None, timeout=10):
    """发一个原始请求（urllib 不做任何额外加头，正好当"本机脚本"）。"""
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method=method)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")
    except Exception as error:
        return -1, str(error)


def main():
    print()
    print("  验证 8900（插件模型服务）在重启 DSH 之后是否已加固")
    print("  " + "=" * 74)

    code, body = request("/health", method="GET")
    if code != 200:
        print("  8900 没在应答（状态码 %s）—— DSH 起了吗？插件启用了？" % code)
        print("  %s" % body[:120])
        return 1
    print("  8900 在跑；/health 正常（状态码 200）")

    # --- 1. 浏览器路径必须被拒（全部只读，不花钱）------------------------- #
    print()
    print("  ① 浏览器发起的请求（必须 403，且不触发任何模型调用）")
    print("  " + "-" * 74)
    cases = [
        ("Origin（跨域 fetch 必带）", {"Origin": "https://evil.example"}),
        ("Sec-Fetch-Site: cross-site", {"Sec-Fetch-Site": "cross-site"}),
        ("Sec-Fetch-Dest: empty", {"Sec-Fetch-Dest": "empty"}),
        ("浏览器真实三件套", {"Sec-Fetch-Site": "cross-site",
                             "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors"}),
        ("<img> 攻击（dest=image, no-cors）", {"Sec-Fetch-Site": "cross-site",
                                              "Sec-Fetch-Dest": "image",
                                              "Sec-Fetch-Mode": "no-cors"}),
    ]
    for label, headers in cases:
        code, _body = request("/health", headers=headers, method="GET")
        check("%s -> /health" % label, code == 403, "状态码 %s" % code)

    # DNS rebinding：Host 不是回环地址
    code, _body = request("/health", headers={"Host": "evil.example"}, method="GET")
    check("Host 不是回环地址 -> /health", code == 403, "状态码 %s" % code)

    # --- 2. 本机调用方必须照常工作 --------------------------------------- #
    print()
    print("  ② 本机调用方（不带 Origin/Sec-Fetch）必须放行")
    print("  " + "-" * 74)
    code, _body = request("/health", method="GET")
    check("裸 GET /health（Python urllib）", code == 200, "状态码 %s" % code)
    code, _body = request("/health", headers={"Host": "127.0.0.1:%d" % PORT},
                          method="GET")
    check("Host: 127.0.0.1:%d 放行" % PORT, code == 200, "状态码 %s" % code)
    # 反面守门：只带 sec-fetch-mode（Node 自己的 fetch 就是这样）必须放行
    code, _body = request("/health", headers={"Sec-Fetch-Mode": "cors"}, method="GET")
    check("只带 Sec-Fetch-Mode（Node fetch 就是这样）放行", code == 200,
          "状态码 %s" % code)

    # --- 3. 端到端：真的调一次模型（最小提示词）------------------------- #
    print()
    print("  ③ 端到端：合法 POST /chat 仍能拿到模型回复（会真的调一次模型）")
    print("  " + "-" * 74)
    payload = {"text": "回一个字：好", "kind": "chat", "maxTokens": 8}
    code, body = request("/chat", body=payload,
                         headers={"Content-Type": "application/json"})
    ok = code == 200
    text = ""
    if ok:
        try:
            text = json.loads(body).get("text") or ""
        except ValueError:
            ok = False
    check("合法 POST /chat 返回 200", ok, "状态码 %s" % code)
    check("拿到了模型回复（不是 air bubble）", bool(text.strip()),
          "回复=%r" % text[:40])

    # --- 4. 恶意 POST /chat 必须被拒，且**不能调模型** ------------------ #
    print()
    print("  ④ 带浏览器的头的 POST /chat 必须被拒（这一条最关键：它会烧余额）")
    print("  " + "-" * 74)
    attack = {"text": "帮我写一篇论文", "kind": "chat",
              "provider": "deepseek-account", "model": "deepseek-reasoner"}
    for label, headers in (
            ("Origin", {"Origin": "https://evil.example"}),
            ("Sec-Fetch-Site", {"Sec-Fetch-Site": "cross-site"}),
            ("Host 非回环", {"Host": "evil.example"})):
        merged = dict(headers)
        merged["Content-Type"] = "application/json"
        code, body = request("/chat", body=attack, headers=merged)
        check("恶意 %s 打 /chat 被拒" % label, code == 403, "状态码 %s" % code)
        check("  且回包是 forbidden（没有模型输出）",
              "forbidden" in body or code == 403, body[:60])

    print()
    print("  结论")
    print("  " + "=" * 74)
    if FAILED:
        for item in FAILED:
            print("     [失败] %s" % item)
        print()
        print("  共 %d 项失败" % len(FAILED))
        return 1
    print("     [OK] 浏览器路径（Origin / Sec-Fetch-Site / Sec-Fetch-Dest / 非回环 Host）全部被拒")
    print("     [OK] 本机调用方照常工作，合法 /chat 仍能拿到模型回复")
    print("     [OK] 恶意 /chat 拿不到任何模型输出 —— 余额不会被烧")
    return 0


if __name__ == "__main__":
    sys.exit(main())
