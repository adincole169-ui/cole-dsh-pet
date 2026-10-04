# -*- coding: utf-8 -*-
"""自检：`audit_gaps.py` 第 5 节（配置字段是否真的被使用）的检测能力。

为什么需要它：这一节本身就是在防"配置项被解析了却没人读"（`fixedEnabled` 就是这么
漏了很久的）。而它第一版写错了——只查 camelCase 名字，`config.chat_image_enabled`
这类 snake_case 属性访问全被漏掉，于是把 5 个**确实在用**的字段误报成"未接"。
所以这里正反两面都测：真字段要认出来，假字段要报出来。

    python tools/selftest_audit_fields.py
"""

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

FAILED = []


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label,
                         ("  " + detail) if detail else ""))
    if not ok:
        FAILED.append(label)


def load_sources():
    files = []
    for folder in (os.path.join(ROOT, "src"), ROOT):
        for entry in sorted(os.listdir(folder)):
            if not entry.endswith(".py") or entry == "audit_gaps.py":
                continue
            path = os.path.join(folder, entry)
            if os.path.abspath(path) == os.path.abspath(
                    os.path.join(ROOT, "src", "config.py")):
                continue
            files.append((entry, io.open(path, encoding="utf-8").read()))
    return files


def used(field, files):
    """与 `audit_gaps.py` 第 5 节同一套判定规则。"""
    for _name, text in files:
        for candidate in (field, re.sub(r"(?<!^)(?=[A-Z])", "_", field).lower()):
            for pattern in (r"getattr\([^)]*['\"]%s['\"]" % candidate,
                            r"['\"]%s['\"]\s*[,)]" % candidate,
                            r"\.%s\b" % candidate,
                            r"config\.get\(['\"]%s['\"]" % candidate):
                if re.search(pattern, text):
                    return True
    return False


def main():
    files = load_sources()
    print("  扫描了 %d 个源码文件（不含 config.py）" % len(files))

    print("  -- 真字段必须被认出来（否则会误报「未接」）--")
    for field in ("fixedEnabled", "notificationsEnabled", "whisperEnabled",
                  "workStatusEnabled", "balanceEnabled", "chatImageEnabled",
                  "whisperImageEnabled", "chatMemoryRounds", "whisperModel", "chatModel"):
        check("%s 被识别为已使用" % field, used(field, files))

    print("  -- 假字段必须报「未使用」（否则漏报）--")
    check("不存在的字段报未使用", not used("thisFieldDoesNotExistAtAll", files))

    print("  -- snake_case 属性访问也要能被认出来 --")
    # `chat.image_enabled` 走的是 `config.chat_image_enabled`，只查 camelCase 会漏
    check("chatImageEnabled（代码里是 chat_image_enabled）",
          used("chatImageEnabled", files))

    print("失败 %d 项" % len(FAILED) if FAILED else "全部通过")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
