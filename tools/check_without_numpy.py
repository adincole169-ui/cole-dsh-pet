# -*- coding: utf-8 -*-
"""在"没有 numpy"的环境下跑自检 —— 这是**新装用户的默认状态**。

`requirements.txt` 里 numpy 是**注释掉的**（可选依赖），而 `src/pet.py` 有两处
`try: import numpy ... except ImportError:` 的纯 Python 回退（输入掩膜的阈值运算）。
也就是说：从源码装起来的使用者，默认走的是**回退分支**，而那一路平时没人跑。

本脚本造一个 sitecustomize 把 numpy 挡掉，再在子进程里跑自检。不需要真的卸载
numpy，也不污染本机环境。

    python tools/check_without_numpy.py            # 掩膜/点击/位置相关的自检
    python tools/check_without_numpy.py --all      # 全部自检
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BLOCK_DIR = os.path.join(ROOT, ".no-numpy-hook")
PYTHON = sys.executable

# 与掩膜/点击/位置相关的自检 —— 回退分支影响的就是这一片
FOCUSED = [
    "selftest_clickable_area.py",
    "selftest_settle_window.py",
    "selftest_click.py",
    "selftest_mask_resize.py",
    "selftest_character_bounds.py",
    "selftest_fade.py",
    "selftest_still_mode.py",
]

HOOK_SOURCE = '''# 由 tools/check_without_numpy.py 生成：挡住 numpy，复现没有它的环境
import sys


class _Blocker(object):
    def find_module(self, name, path=None):
        return self if name == "numpy" or name.startswith("numpy.") else None

    def find_spec(self, name, path=None, target=None):
        if name == "numpy" or name.startswith("numpy."):
            raise ImportError("numpy blocked by check_without_numpy")
        return None


for _name in list(sys.modules):
    if _name == "numpy" or _name.startswith("numpy."):
        del sys.modules[_name]

sys.meta_path.insert(0, _Blocker())
'''


def make_hook():
    if os.path.isdir(BLOCK_DIR):
        shutil.rmtree(BLOCK_DIR)
    os.makedirs(BLOCK_DIR)
    path = os.path.join(BLOCK_DIR, "sitecustomize.py")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(HOOK_SOURCE)
    return path


def run(args, timeout=1200):
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = BLOCK_DIR + (os.pathsep + existing if existing else "")
    done = subprocess.run([PYTHON, "-X", "utf8"] + args, cwd=ROOT,
                          capture_output=True, text=True, env=env, timeout=timeout)
    return done.returncode, (done.stdout or ""), (done.stderr or "")


def main():
    argv = sys.argv[1:]
    make_hook()

    print()
    print("  在「没有 numpy」的环境下验证（新装用户的默认状态）")
    print("  " + "=" * 66)

    code, out, err = run(["-c", "import numpy"])
    blocked = "ImportError" in err or "blocked by check_without_numpy" in err
    print("  numpy 已被挡住: %s" % ("是" if blocked else "**否**"))
    if not blocked:
        print("  挡住失败，结果不可信：%s" % err[:200])
        return 1

    # 确认回退实现真的被走到，并量一下它的代价
    probe = (
        "import sys, time;"
        "sys.path.insert(0, 'src');"
        "from PyQt5.QtGui import QImage;"
        "from PyQt5.QtWidgets import QApplication;"
        "app = QApplication([]);"
        "import pet;"
        "img = QImage(640, 360, QImage.Format_ARGB32);"
        "img.fill(0xFF00FF00);"
        "win = pet.PetWindow.__new__(pet.PetWindow);"
        "t = time.time();"
        "data = pet.PetWindow._threshold_bytes(win, img);"
        "print('ROUNDTRIP %d %.1f' % (len(data), (time.time() - t) * 1000))"
    )
    code, out, err = run(["-c", probe])
    for line in out.splitlines():
        if line.startswith("ROUNDTRIP"):
            parts = line.split()
            print("  回退实现: %s 字节，单次 %.0f ms（有 numpy 时是几毫秒）"
                  % (parts[1], float(parts[2])))
    if code != 0:
        lines = err.strip().splitlines() or [""]
        print("  **回退实现本身报错**：%s" % lines[-1][:160])
        return 1

    suites = FOCUSED
    if "--all" in argv:
        suites = sorted(name for name in os.listdir(os.path.join(ROOT, "tools"))
                        if name.startswith("selftest_") and name.endswith(".py"))

    print()
    failed = []
    ran = 0
    for name in suites:
        if not os.path.isfile(os.path.join(ROOT, "tools", name)):
            continue
        ran += 1
        try:
            code, out, err = run([os.path.join("tools", name)])
        except subprocess.TimeoutExpired:
            print("  %-32s **超时**" % name)
            failed.append((name, "超时"))
            continue
        ok = code == 0 and "全部通过" in out
        print("  %-32s %s" % (name, "通过" if ok else "**失败**"))
        if not ok:
            tail = [line.strip() for line in out.splitlines() if line.strip()]
            failed.append((name, tail[-1][:80] if tail else "(无输出)"))
            for line in tail[-3:]:
                print("        %s" % line[:92])
            if err.strip():
                print("        stderr: %s" % err.strip().splitlines()[-1][:92])

    print()
    print("  结论")
    print("  " + "=" * 66)
    if failed:
        print("     没有 numpy 时 %d/%d 套自检失败：" % (len(failed), ran))
        for name, verdict in failed:
            print("       %s: %s" % (name, verdict))
        print()
        print("     注意：requirements.txt 默认**不装** numpy，")
        print("     所以从源码装的使用者走的正是这条回退路径。")
    else:
        print("     %d 套全部通过：没有 numpy 时行为与有 numpy 一致（只是慢）。" % ran)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
