# -*- coding: utf-8 -*-
"""帧存储：按需准备动画、缓存 QPixmap、提供给绘制层。

**两种帧来源**（由 `FrameStore(source=...)` 选，默认取 `default_source()`）：

* `"stream"` —— 运行时用 ffmpeg 流式解码 webm，**磁盘上不留帧**。一个动画一个常驻
  ffmpeg 进程，`-stream_loop -1` 无限循环，有界环形缓冲 + 按消费位置背压。
  代价是首次播放要等约 94 ms（起 ffmpeg 到首帧），需要 ffmpeg。
* `"cache"` —— 把 webm 预解码成 `frames/<名>/*.png` 再读（历史方案）。
  零延迟，但本机要有 2.6 GB 缓存，且首次使用某个动画要等约 13 秒解码。

两者产出**逐像素相同**的画面（实测最大差 0/255），所以绘制层不需要区分。

三层结构，各自解决一个具体问题：

* **准备层**：stream 模式起 ffmpeg；cache 模式让 asset_pipeline 生成 PNG 帧；
* **准备到内存**：读 241 张 PNG 需要 300–600 ms，**绝不能放在 GUI 线程里**——第一版
  就是同步读，结果每次切状态界面都要僵住半秒，连健康检查都显示"还在播上一个动画"。
  因此缓存未命中时由**后台线程**准备，完成后经 `loaded` 信号切回 GUI 线程；
* **内存层**：按 LRU 淘汰，因为 106 个动画全常驻要几 GB。**淘汰时必须释放**
  （stream 模式要杀掉那个 ffmpeg 进程，否则进程泄漏）。

后台线程与 GUI 线程之间只交换"动画名"：QPixmap 在 GUI 线程里构造（QPixmap 不是
线程安全的）；stream 模式的读帧线程只产 QImage（QImage 可以跨线程）。
"""

import os
import sys
import time
from collections import deque
from threading import Lock, Thread

from PyQt5.QtCore import QObject, Qt, pyqtSignal

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import asset_pipeline  # noqa: E402
import stream_frames  # noqa: E402

# 默认帧来源。`"stream"` 让磁盘占用归零；ffmpeg 不可用时自动退回 `"cache"`。
DEFAULT_SOURCE = "stream"

# 加载失败后多久之内不再重试（秒）。够长，免得坏名字/缺文件刷屏；也不是永久，
# 这样用户补上 webm 之后不必重启桌宠。
FAILED_COOLDOWN_SEC = 60.0


def default_source():
    """按环境决定默认帧来源。"""
    if DEFAULT_SOURCE != "stream":
        return DEFAULT_SOURCE
    return "stream" if stream_frames.available() else "cache"


class Animation(object):
    """一个动画的帧，**惰性**构造 QPixmap。

    实测数据决定了这个设计：从磁盘读 241 张 PNG 并构造 QPixmap 要 **2.5 秒**，
    而 ffmpeg 解码整段只用 0.4 秒。也就是说瓶颈不在解码，而在"一次性造 241 个
    QPixmap"。所以这里只保存路径，真正要画哪一帧才构造哪一帧——播完一轮之后
    全部帧自然都在缓存里了，而任何时刻都不需要一次付出 2.5 秒。
    """

    def __init__(self, name, paths, fps=24.0):
        self.name = name
        self.paths = list(paths)
        self.fps = float(fps) if fps else 24.0
        self.duration = len(self.paths) / self.fps if self.paths else 0.0
        self._pixmaps = {}

    def __len__(self):
        return len(self.paths)

    @property
    def frames(self):
        """已构造的帧（只用于统计；绘制请用 `frame()`）。"""
        return [self._pixmaps[key] for key in sorted(self._pixmaps)]

    def frame(self, index):
        if not self.paths:
            return None
        index = max(0, min(len(self.paths) - 1, int(index)))
        pixmap = self._pixmaps.get(index)
        if pixmap is None:
            from PyQt5.QtGui import QPixmap
            pixmap = QPixmap(self.paths[index])
            self._pixmaps[index] = pixmap
        return pixmap

    @property
    def width(self):
        pixmap = self.frame(0)
        return pixmap.width() if pixmap is not None else 0

    @property
    def height(self):
        pixmap = self.frame(0)
        return pixmap.height() if pixmap is not None else 0


class FrameStore(QObject):
    """动画的内存缓存 + 后台加载入口。"""

    # 一个动画在后台加载完成（参数为动画名）
    loaded = pyqtSignal(str)
    # 后台加载失败（参数为动画名）
    failed = pyqtSignal(str)

    def __init__(self, keep=4, parent=None, source=None):
        super(FrameStore, self).__init__(parent)
        self._cache = {}          # name -> Animation / StreamAnimation
        self._order = []          # LRU 顺序，最旧在前
        self._keep = max(1, keep)
        self._loading = set()
        self._disk_ready = set()  # 帧已经躺在磁盘上的动画
        self._pinned = set()      # 正在播放、不能淘汰的动画
        # 按**钉入顺序**记录，`retain()` 靠它裁掉最旧的。用 set 不行——set 不保序。
        self._pin_order = deque()
        # stream 模式：后台线程造好的流对象，等 GUI 线程来接手
        self._streams = {}
        self._stream_lock = Lock()
        self.source = source or default_source()
        self._warm_names = set()
        self.hits = 0
        self.misses = 0
        self.reloads = 0
        self.stream_failures = 0
        # 加载失败的动画：name -> 失败时刻（time.monotonic()）。冷却期内 `request()`
        # 不再重试 —— 否则 `_heal()` 每 33 ms 就重新排一次队，每秒新开约 30 个线程 ✗
        self._failed = {}
        # `loaded` 一到就把动画登记进 `_cache`：这样 `request()` 之后的
        # `peek()` 立刻能拿到，预热（`warm()`）也靠它生效。
        # `finish_load` 是幂等的，动画那边的 `on_loaded` 再调一次也无害。
        self.loaded.connect(self._register_loaded)
        self.failed.connect(self._register_failed)

    def pin(self, name):
        """钉住一个动画：它是当前正在播的，淘汰它会让画面直接没帧。"""
        if name:
            self._pinned.add(name)

    def unpin(self, name):
        self._pinned.discard(name)

    def retain(self, name, keep=2):
        """钉住 `name`，并只保留最近 `keep` 个钉子（按钉入顺序）。

        为什么需要它：`play()` 每换一段都会 `pin()`，但原先**从不 `unpin()`**，
        于是 `_pinned` 无限增长，`_touch()` 里"跳过 pinned"的淘汰保护逐渐失效——
        内存里的动画只增不减（实测常驻 500MB 以上）。

        保留 2 个（当前 + 上一段）而不是 1 个：交叉淡化要用上一段的最后一帧，
        立刻解钉可能在淡化那一两百毫秒里被淘汰掉。

        **必须用有序结构**：`set` 不保序，早先按"非 name 的先解"裁剪，结果把**最近**
        的几个解掉了、反而留下最旧的一个（实测 `retain('C')` 之后留下的是 `A`）。
        """
        if not name:
            return
        if name in self._pin_order:
            self._pin_order.remove(name)
        self._pin_order.append(name)
        while len(self._pin_order) > max(1, keep):
            self._pin_order.popleft()
        self._pinned = set(self._pin_order)

    # -- 查询 ---------------------------------------------------------------- #
    def has(self, name):
        return name in self._cache

    def peek(self, name):
        """只取已缓存的内存动画，不做任何 IO。"""
        animation = self._cache.get(name)
        if animation is not None:
            self._touch(name)
        return animation

    def is_loading(self, name):
        return name in self._loading

    def is_failed(self, name):
        """最近加载失败过、还在冷却期内（期间不重试）。"""
        at = self._failed.get(name)
        if at is None:
            return False
        if time.monotonic() - at >= FAILED_COOLDOWN_SEC:
            self._failed.pop(name, None)      # 冷却结束，允许再试一次
            return False
        return True

    # -- 取用 ---------------------------------------------------------------- #
    def animation(self, name):
        """同步取一个动画（**会阻塞**，只在启动预解码/自检里用）。

        普通的动画切换请用 `request()`，否则会把界面冻住。
        """
        return self._load_sync(name)

    def request(self, name):
        """请求一个动画；已缓存的直接返回，否则后台加载并返回当前可用的最佳选择。

        先查"是否正在加载"再查缓存：正在加载说明这个动画**已经接单**，此时若回退到
        别的动画并让状态机重排，就会把它反复重新排队（实测 reloads 会一路涨而永远
        接不上），所以这个顺序是必须的。
        """
        if not name:
            return None
        if name in self._loading:
            return self._best_fallback()
        cached = self.peek(name)
        if cached is not None:
            return cached
        if self.is_failed(name):
            # 冷却期内不重试：直接给兜底帧。**这一条很重要** —— `Animator._heal()`
            # 每 tick（33 ms）都会调到这里，不加冷却的话一个加载失败的动画会每秒
            # 新开约 30 个线程，白烧 CPU 还刷屏。
            return self._best_fallback()
        self._start_background(name)
        return self._best_fallback()

    def _best_fallback(self):
        """加载期间拿来顶替的帧：最近用过、且已经就绪的那个动画。"""
        for fallback in reversed(self._order):
            if fallback in self._cache:
                return self._cache[fallback]
        return None

    def _start_background(self, name):
        if name in self._loading or name in self._cache:
            return
        self._loading.add(name)

        def worker():
            ok = True
            try:
                if self.source == "stream":
                    ok = self._prepare_stream(name)
                else:
                    self._ensure_on_disk(name)
            except Exception as error:
                sys.stderr.write("dsh-pet: 准备失败 %s: %s\n" % (name, error))
                ok = False
            # **`_loading` 不在这里摘。** 要等 GUI 线程的 `_register_loaded` /
            # `_register_failed` 处理完再摘 —— 否则在"摘掉了、还没登记进 `_cache`"
            # 这段空档里，`_heal()` 会再起一个 worker，多出一个没人接手的 ffmpeg。
            if ok:
                self.loaded.emit(name)
            else:
                self.stream_failures += 1
                sys.stderr.write("dsh-pet: 取不到帧 %s\n" % name)
                self.failed.emit(name)

        Thread(target=worker, daemon=True).start()

    def _prepare_stream(self, name):
        """在**后台线程**里起一个流并等首帧就绪。

        等首帧放在后台是必须的：实测起 ffmpeg 到首帧要 94 ms，放 GUI 线程里就是
        每次切动画都卡一下（和当初"同步读 241 张 PNG 僵半秒"是同一类错误）。

        探测/起流失败时**回退到磁盘缓存**（如果那份还在）：这样即使某台机器上
        ffmpeg 有问题，只要之前解过码就还能用，不会变成"宠物不见了"。
        """
        with self._stream_lock:
            # 已经解好的也算成功：否则"流没了但 cache 里有"会被当成失败，
            # 白白进冷却期。
            if name in self._streams or name in self._cache:
                return True
        info = stream_frames.webm_info(name)
        if not info:
            if asset_pipeline.is_cached(name):
                self._ensure_on_disk(name)
                return True
            sys.stderr.write("dsh-pet: 没有这个动画: %s\n" % name)
            return False
        animation = None
        try:
            animation = stream_frames.StreamAnimation(name, info)
            if not animation.wait_first(6.0):
                reason = animation.error or "首帧超时"
                animation.close()
                if asset_pipeline.is_cached(name):
                    sys.stderr.write("dsh-pet: 流式失败(%s)，回退到磁盘缓存 %s\n"
                                     % (reason, name))
                    self._ensure_on_disk(name)
                    return True
                sys.stderr.write("dsh-pet: 流式失败 %s: %s\n" % (name, reason))
                return False
        except Exception as error:
            if animation is not None:
                animation.close()
            if asset_pipeline.is_cached(name):
                self._ensure_on_disk(name)
                return True
            sys.stderr.write("dsh-pet: 起流失败 %s: %s\n" % (name, error))
            return False
        with self._stream_lock:
            self._streams[name] = animation
        return True

    def _register_loaded(self, name):
        """`loaded` 一到就登记进 `_cache`（GUI 线程）。"""
        try:
            self.finish_load(name)
        finally:
            # 登记完才摘 `_loading`（见 worker 里的说明），并清掉可能存在的失败记录。
            self._loading.discard(name)
            self._failed.pop(name, None)

    def _register_failed(self, name):
        """`failed` 到达（GUI 线程）：记下失败时刻，冷却期内不再重试。"""
        self._loading.discard(name)
        self._failed[name] = time.monotonic()

    def finish_load(self, name):
        """在 **GUI 线程**里把后台准备好的东西登记成一个动画对象。"""
        if name in self._cache:
            return self._cache[name]
        if self.source == "stream":
            with self._stream_lock:
                animation = self._streams.pop(name, None)
            if animation is not None:
                self._cache[name] = animation
                self._touch(name)
                self.reloads += 1
                return animation
        paths = asset_pipeline.cached_frames(name)
        if not paths:
            return None
        animation = Animation(name, paths)
        self._cache[name] = animation
        self._touch(name)
        self.reloads += 1
        return animation

    @staticmethod
    def _release(animation):
        """淘汰/清空时必须释放：stream 模式要杀掉那个 ffmpeg 进程。

        漏掉这一步的后果是**进程泄漏** —— 每换一个动画留一个 ffmpeg，
        聊一会儿就有几十个。所以这里用鸭子类型判断，不依赖具体类。
        """
        closer = getattr(animation, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                pass

    # -- 内部 ---------------------------------------------------------------- #
    def _ensure_on_disk(self, name):
        if name in self._disk_ready or asset_pipeline.is_cached(name):
            self._disk_ready.add(name)
            return
        asset_pipeline.build(name)
        self._disk_ready.add(name)

    def _load_sync(self, name):
        """同步取一个动画（**会阻塞**，只在启动预解码/自检里用）。

        **stream 模式下也必须走 `_prepare_stream`**：早先这里只调
        `_ensure_on_disk`，于是流式模式下任何 `store.animation(name)` 都会去
        **解码写盘** —— 自检里 8 个动画就写出 560 MB 缓存，而且每个要等约 13 秒
        （实测 selftest_crossfade 因此从 0.3 秒涨到 114 秒）。流式模式的"零磁盘占用"
        会被这一处悄悄破坏。
        """
        if name in self._cache:
            self.hits += 1
            self._touch(name)
            return self._cache[name]
        self.misses += 1
        try:
            if self.source == "stream":
                if not self._prepare_stream(name):
                    return None
            else:
                self._ensure_on_disk(name)
        except Exception as error:
            sys.stderr.write("dsh-pet: 准备失败 %s: %s\n" % (name, error))
            return None
        return self.finish_load(name)
    def _touch(self, name):
        if name in self._order:
            self._order.remove(name)
        self._order.append(name)
        over = len(self._order) - self._keep
        if over <= 0:
            return
        # 从最旧的开始淘汰，但跳过被钉住的（正在播放的那个）
        index = 0
        while over > 0 and index < len(self._order):
            candidate = self._order[index]
            if candidate in self._pinned:
                index += 1
                continue
            self._order.pop(index)
            self._release(self._cache.pop(candidate, None))
            over -= 1

    # -- 批量 ---------------------------------------------------------------- #
    def warm(self, names):
        """**非阻塞**地把最可能最先用到的几个动画起好流。

        用在启动时：这样宠物出现时帧已经就绪，不必先空白约 100 ms 再显示。
        cache 模式下就是普通的预解码。
        """
        for name in list(names or [])[:2]:
            if name and name not in self._cache and name not in self._loading:
                if name in self._warm_names:
                    continue
                self._warm_names.add(name)
                self._start_background(name)

    def preload(self, names):
        """让帧"准备好"（stream 模式只预热最前面一两个，其余按需）。

        cache 模式原本是"只保证帧在磁盘上（不造 QPixmap，那要几秒）"。
        stream 模式不需要落盘，所以这里退化成启动预热。
        """
        if self.source == "stream":
            self.warm(names)
            return
        for name in names:
            if name in self._cache:
                continue
            try:
                self._ensure_on_disk(name)
            except Exception as error:
                sys.stderr.write("dsh-pet: 预解码失败 %s: %s\n" % (name, error))
            self.finish_load(name)

    def clear(self):
        for animation in list(self._cache.values()):
            self._release(animation)
        self._cache.clear()
        self._order = []
        with self._stream_lock:
            pending = list(self._streams.values())
            self._streams.clear()
        for animation in pending:
            self._release(animation)

    def close(self):
        """退出时收干净：杀掉所有还在跑的 ffmpeg。"""
        self.clear()
        stream_frames.kill_all()

    def stats(self):
        return {
            "source": self.source,
            "cached": list(self._order),
            "hits": self.hits,
            "misses": self.misses,
            "reloads": self.reloads,
            "streamFailures": self.stream_failures,
            "loading": sorted(self._loading),
            # 冷却期内不再重试的动画：排查"某个动作一直不播"时看这个
            "failed": sorted(self._failed),
        }
