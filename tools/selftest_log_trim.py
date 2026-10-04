# -*- coding: utf-8 -*-
"""自检：日志自动清理。

为什么需要它：`--watch` 模式下 `logs/watch.log` 每秒一行，**没有任何上限**；桌宠长期
运行时会一直长。但清理不能简单清空——这些日志的用途正是"桌宠消失后看最后几行"，
清空等于把线索一起丢掉。所以规则是"**保留最近的、丢掉更早的**"，这个自检就钉住它。

     python tools/selftest_log_trim.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import run_logged as R                          # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label,
                         ("  " + detail) if detail else ""))
    if not ok:
        FAILED.append(label)


def make_log(path, lines):
    with open(path, "w", encoding="utf-8") as handle:
        for index in range(lines):
            handle.write("第 %06d 行 测试内容，用来把文件撑大\n" % index)


def main():
    path = os.path.join(ROOT, "logs", "_trimtest.log")

    print("  -- 超限时说裁就裁 --")
    make_log(path, 40000)
    before = os.path.getsize(path)
    changed = R.trim_log(path)
    after = os.path.getsize(path)
    check("超过 1 MB 会被裁剪", changed, "%.2f MB -> %.0f KB" % (before / 1048576.0, after / 1024.0))
    check("裁到 256 KB 以内", after < R.LOG_LIMIT, "%.0f KB" % (after / 1024.0))
    with open(path, encoding="utf-8") as handle:
        body = handle.read()
    check("保留的是**最新**内容（末行仍在）", "第 039999 行" in body)
    check("更早的内容已被丢弃（首行不在了）", "第 000000 行" not in body)
    check("留下了清理说明", "已自动清理" in body)

    print("  -- 幂等 --")
    check("未超限时不动它", not R.trim_log(path))

    print("  -- 小文件不受影响 --")
    keep = os.path.join(ROOT, "logs", "_smalltest.log")
    make_log(keep, 10)
    small = os.path.getsize(keep)
    R.trim_log(keep)
    check("小文件内容原样保留", os.path.getsize(keep) == small)
    os.remove(keep)

    print("  -- 入口 trim_all_logs 会扫到这些文件名 --")
    # 造一个符合命名规则、且超限的文件，确认批量入口能处理它。
    # 这一条覆盖的是"包装层/桌宠启动时调用的那个入口"，而不只是 trim_log 本身。
    bulk = os.path.join(ROOT, "logs", "watch.log")
    backup = None
    if os.path.exists(bulk):
        backup = bulk + ".selftest-bak"
        os.replace(bulk, backup)
    make_log(bulk, 40000)
    names = R.trim_all_logs()
    check("批量入口处理了 watch.log", "watch.log" in names, "names=%r" % (names,))
    check("批量入口把它裁到阈值内", os.path.getsize(bulk) < R.LOG_LIMIT,
          "%.0f KB" % (os.path.getsize(bulk) / 1024.0))
    os.remove(bulk)
    if backup:
        os.replace(backup, bulk)

    os.remove(path)
    print("失败 %d 项" % len(FAILED) if FAILED else "全部通过")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
