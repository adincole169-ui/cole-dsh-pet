# -*- coding: utf-8 -*-
"""带日志的启动包装：把桌宠的退出码与全部输出留下。

为什么需要它：用 `pythonw` 启动时 stderr 无处可去，于是"进程突然不见了"只留下
一份干净截断的 `watch.log`，什么线索都没有。这个包装用 `python`（不是 pythonw）
起子进程，把 stdout / stderr 重定向到文件，并在退出后记录退出码——**异常退出与
正常退出（退出码 0）一眼可分**。

    pythonw tools/run_logged.py            # 日常启动，日志在 logs/pet-run.log

以后桌宠再"消失"，先看这个日志的最后几行。
"""

import io
import json
import os
import re
import subprocess
import sys
import time
from urllib.request import Request, urlopen

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOG = os.path.join(ROOT, "logs", "pet-run.log")

# 日志自动清理：超过 LIMIT 就只保留尾部 KEEP。
# 为什么不是直接删掉：这些日志的用途就是"桌宠消失后看最后几行"，清空等于把线索
# 一起丢了。所以按"**保留最近的、丢掉更早的**"处理。
LOG_LIMIT = 1024 * 1024      # 1 MB
LOG_KEEP = 256 * 1024        # 裁到 256 KB
# 需要一起管的日志（都放在 logs/ 下）
# drag.log 是拖动诊断（每次用户拖动一行），量很小但也要一起裁，免得长期累积。
LOG_PATTERNS = ("pet-run.log", "watch.log", "whisper-steps.log", "drag.log",
                "crash*.txt", "out*.txt")


def trim_log(path, limit=LOG_LIMIT, keep=LOG_KEEP):
    """把超大的日志裁成"只保留尾部 keep 字节"。返回是否发生了裁剪。

    按**字节**截取再对齐到行首：这样不用把整个文件读进内存，也不依赖行长度。
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        return False
    if size <= limit:
        return False
    try:
        with open(path, "rb") as handle:
            handle.seek(max(0, size - keep))
            handle.readline()                       # 丢掉可能被截断的半行
            tail = handle.read()
        with open(path, "wb") as handle:
            handle.write(("==== 日志超过 %d KB，已自动清理（保留最近 %d KB）====\n"
                          % (limit // 1024, keep // 1024)).encode("utf-8"))
            handle.write(tail)
        return True
    except OSError:
        return False


def trim_all_logs():
    """启动时把所有相关日志都裁一遍。"""
    import glob
    trimmed = []
    for pattern in LOG_PATTERNS:
        for path in glob.glob(os.path.join(ROOT, "logs", pattern)):
            if trim_log(path):
                trimmed.append(os.path.basename(path))
    return trimmed


def bring_to_front(port, timeout=4):
    """已有实例在跑时，把它搬到屏幕正中并抬到最前。

    原先这种情况下包装层只是**静默退出**（"已有一只在运行，本次不启动"），于是用户
    双击启动图标什么都看不到——从代码看是"正常退出"，从用户看就是"点了没反应"。
    用户点启动图标的真实意图是"让我看到它"，所以这里改成把它叫到前面来。
    """
    payload = json.dumps({"center": True}).encode("utf-8")
    request = Request("http://127.0.0.1:%d/place" % port, data=payload,
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8")).get("ok") is True
    except Exception as error:
        sys.stderr.write("dsh-pet: 无法把它叫到前面: %s\n" % error)
        return False


def main(argv):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    # 启动时先清理一次（上一次运行可能攒下很大的日志）
    trimmed = trim_all_logs()
    if trimmed:
        sys.stderr.write("dsh-pet: 已清理日志 %s\n" % ", ".join(trimmed))

    # 端口与 main.py 用的是同一个配置来源
    port = 8899
    try:
        handle_config = io.open(os.path.join(ROOT, "config.jsonc"), encoding="utf-8")
        text = handle_config.read()
        handle_config.close()
        match = re.search(r'"bridge"\s*:\s*\{[^}]*"port"\s*:\s*(\d+)', text)
        if match:
            port = int(match.group(1))
    except Exception:
        pass

    # 子进程要用 **pythonw.exe**，不能用 python.exe：
    # python.exe 是控制台子系统程序，从 pythonw 启动它时 Windows 会**分配一个控制台
    # 窗口**（用户会看到桌面上多出一个终端）。pythonw.exe 没有控制台，而输出照样
    # 能重定向到文件——我们要的是 stderr 的内容，不是控制台。
    interpreter = sys.executable
    folder = os.path.dirname(interpreter)
    for name in ("pythonw.exe", "python.exe"):
        candidate = os.path.join(folder, name)
        if os.path.exists(candidate):
            interpreter = candidate
            if name == "pythonw.exe":
                break

    command = [interpreter, "-X", "utf8", os.path.join(ROOT, "main.py")] + argv[1:]
    handle = io.open(LOG, "a", encoding="utf-8")

    # CREATE_NO_WINDOW 兜底：即使解释器是控制台程序，也不会弹出窗口
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    attempts = 0
    while True:
        attempts += 1
        handle.write("\n==== 启动 %s（第 %d 次）====\n"
                     % (time.strftime("%Y-%m-%d %H:%M:%S"), attempts))
        handle.write("命令: %s\n" % " ".join(command))
        handle.flush()

        process = subprocess.Popen(command, cwd=ROOT, stdout=handle,
                                   stderr=subprocess.STDOUT,
                                   creationflags=creationflags)
        code = process.wait()
        # 运行期间桌宠的 stderr 一直在往这个文件写，所以**退出后**是检查大小的时机。
        # 裁之前必须先关闭句柄：子进程把 stdout 挂在同一个句柄上，且 Windows 上
        # 打开着的文件不能这样截断重写。
        handle.flush()
        handle.close()
        try:
            if os.path.getsize(LOG) > LOG_LIMIT:
                trim_log(LOG)
        except OSError:
            pass
        handle = io.open(LOG, "a", encoding="utf-8")
        handle.write("==== 退出 %s，退出码 %s ====\n"
                     % (time.strftime("%H:%M:%S"), code))

        if code == 0:
            # 退出码 0 有两种可能：用户主动退出，或"已有实例所以没启动"。
            # 后者时把已有那只叫到前面来——用户点图标是想看到它，不该什么都没发生。
            if bring_to_front(port):
                handle.write("（已有一只在运行：已把它搬到屏幕正中并抬到最前）\n")
            else:
                handle.write("（退出码 0：主动退出，不重启）\n")
            handle.flush()
            break

        handle.write("（非零退出：崩溃或被终止，3 秒后自动重启）\n")
        handle.flush()
        time.sleep(3)

    handle.close()
    return code


if __name__ == "__main__":
    # `--trim-logs`：只清理日志然后退出。给它一个独立入口，是为了让"清理"这件事
    # 能被自检直接调用和验证，而不是只能靠"启动一次桌宠"来间接测。
    if len(sys.argv) > 1 and sys.argv[1] == "--trim-logs":
        names = trim_all_logs()
        print("已清理: %s" % (", ".join(names) if names else "（没有超限的日志）"))
        sys.exit(0)
    sys.exit(main(sys.argv))
