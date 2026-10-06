# -*- coding: utf-8 -*-
"""自检：动画**加载失败**之后不能定格、也不能起线程风暴。

补丁（cole-dsh-pet-fix.patch）指出的两个问题，我已在本机核实成立：

  1. `FrameStore.failed` 信号**定义了却没有任何接收者**（我 grep 过全仓库确认）。
     于是取不到帧的当前段永远等不到接帧：`Playing.advance()` 在没有帧时不推进时间，
     `done` 永不置位 —— **动物永久定格在上一段的最后一帧**。
  2. `Animator._heal()` 每 tick（33 ms）调一次 `store.request(name)`，而失败的名字
     没有冷却期 —— 等于**每秒新开约 30 个线程**。

修法：加载失败进冷却期（60 秒）+ 把 `failed` 接到 `Animator.on_failed()`。
这个自检守住三件事：

  * 失败一次之后 `is_failed()` 为真、`_loading` 已摘干净；
  * 冷却期内**反复请求不再新开线程**（数 `threading.active_count()`）；
  * 当前段失败时，动画链会**换到下一段**而不是停在那里。

    python tools/selftest_anim_failure.py
"""

import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

FAILED = []


def check(label, ok, detail=""):
    if isinstance(detail, (list, tuple)):
        detail = " / ".join(str(x) for x in detail if x)
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label,
                         ("  " + str(detail)) if detail else ""))
    if not ok:
        FAILED.append(label)


BOGUS = "这个动画根本不存在-自检专用"


def main():
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])          # noqa: F841

    import frames as frames_mod
    from frames import FrameStore, FAILED_COOLDOWN_SEC

    print()
    print("  自检：动画加载失败之后不能定格、也不能起线程风暴")
    print("  " + "=" * 74)
    check("存在冷却期常量", FAILED_COOLDOWN_SEC > 0, "%.0f 秒" % FAILED_COOLDOWN_SEC)
    check("不存在的动画名确实没有对应 webm",
          not os.path.exists(os.path.join(ROOT, "webm", BOGUS + ".webm")))

    # --- 1. FrameStore：失败 -> 冷却 -> 不再重试 -------------------------- #
    store = FrameStore(keep=2, source="stream")

    # 等失败信号走完（worker 线程 -> 信号 -> GUI 线程）
    store.request(BOGUS)
    deadline = time.time() + 20
    while time.time() < deadline and not store.is_failed(BOGUS):
        app.processEvents()
        time.sleep(0.05)

    check("失败之后 is_failed() 为真", store.is_failed(BOGUS))
    check("失败之后 `_loading` 已摘干净", not store.is_loading(BOGUS),
          sorted(store._loading))

    # --- 2. 冷却期内反复请求：不能再新开线程 ----------------------------- #
    time.sleep(0.3)                       # 让上一轮的 worker 彻底退出
    before_threads = threading.active_count()
    before_failures = store.stream_failures
    peak_threads = before_threads
    for _ in range(40):
        store.request(BOGUS)              # 相当于 `_heal()` 每 tick 调一次
        # **每次都要采样**：worker 线程很快就退出，只看循环前后的快照抓不到风暴
        # （第一版就是这么写的，结果撤掉修复它照样通过 —— 一条永远不会失败的断言
        # 比没有断言更糟，因为它会让人以为这里被守住了）。
        peak_threads = max(peak_threads, threading.active_count())
        app.processEvents()
    time.sleep(1.0)
    after_threads = threading.active_count()
    after_failures = store.stream_failures

    check("冷却期内反复请求 40 次不再新开线程",
          peak_threads <= before_threads,
          "线程数峰值 %d（起点 %d，结束 %d）"
          % (peak_threads, before_threads, after_threads))
    check("冷却期内不再重复计失败次数（说明真的没再试）",
          after_failures == before_failures,
          "streamFailures %d -> %d" % (before_failures, after_failures))

    # --- 3. 冷却期到点后允许再试一次 -------------------------------------- #
    store._failed[BOGUS] = time.monotonic() - FAILED_COOLDOWN_SEC - 1
    check("冷却期到点后 is_failed() 变回假（允许再试）", not store.is_failed(BOGUS))
    # 立刻再请求一次应当会重新尝试（失败次数 +1）
    before = store.stream_failures
    store.request(BOGUS)
    deadline = time.time() + 20
    while time.time() < deadline and store.stream_failures == before:
        app.processEvents()
        time.sleep(0.05)
    check("到点之后再请求会重新尝试（说明不是永久拉黑）",
          store.stream_failures > before,
          "streamFailures %d -> %d" % (before, store.stream_failures))
    store.close()

    # --- 4. Animator：当前段失败要换下一段，而不是定格 -------------------- #
    print()
    print("  动画链：当前段取不到帧时必须换下一段")
    print("  " + "-" * 74)

    class FakePlay(object):
        def __init__(self, name, animation=None):
            self.name = name
            self.animation = animation
            self.elapsed = 0.0
            self.done = False
            self.crossfade = 0
            self.loop = True

        @property
        def ready(self):
            return self.animation is not None

        @property
        def duration(self):
            return 3.0

        def advance(self, _dt):
            pass

    class StubStore(object):
        """只实现 Animator 用到的那几个方法。"""

        def __init__(self, good):
            self.good = good
            self.failed = set()
            self.requests = []

        def has(self, name):
            return name in self.good

        def peek(self, name):
            return self.good.get(name)

        def is_loading(self, _name):
            return False

        def is_failed(self, name):
            return name in self.failed

        def request(self, name):
            self.requests.append(name)
            if name not in self.good:
                self.failed.add(name)

        def pin(self, _name):
            pass

        def retain(self, _name, keep=2):
            pass

    class StubConfig(object):
        # `next_auto()` 会读 `config.animations["categories"]`（顶层字典）
        animations = {}

        def actions(self, group):
            return ["好动画"] if group == "idle" else []

        def event_animations(self, _group):
            return []

        def move_specs(self):
            return []

        # `next_auto()` 按权重挑段，会调用 `weight_of(group)`（**只收组名一个参数**；
        # 我第一版多写了一个 name 参数，报 `weight_of() missing 1 required positional
        # argument: 'name'` —— 用替身做测试时最容易漏的一类依赖）。
        def weight_of(self, group):
            return 1.0

    from animator import Animator
    stub = StubStore({"好动画": FakePlay("好动画", animation=object())})
    anim = Animator(stub, StubConfig(), None)

    anim.play(BOGUS, loop=True)          # 播一个取不到帧的动画
    check("当前段是那个坏动画", anim.playing is not None and anim.playing.name == BOGUS,
          anim.playing.name if anim.playing else None)

    # 连着 tick 若干次（模拟真实循环）
    for _ in range(5):
        anim._tick()

    check("坏动画没有把动画链卡住（playing 已经换掉）",
          anim.playing is None or anim.playing.name != BOGUS,
          anim.playing.name if anim.playing else None)

    print()
    print("  结论")
    print("  " + "=" * 74)
    if FAILED:
        for item in FAILED:
            print("     [失败] %s" % item)
        return 1
    print("     [OK] 失败进冷却期、不再新开线程；当前段失败会换下一段，不定格")
    return 0


if __name__ == "__main__":
    sys.exit(main())
