# -*- coding: utf-8 -*-
"""帧存储：按需解码动画、缓存 QPixmap、提供给绘制层。

三层结构，各自解决一个具体问题：

* **磁盘层**（asset_pipeline）：webm → PNG 帧，只在某个动画第一次用到时生成；
* **磁盘到内存**：读 241 张 PNG 需要 300–600 ms，**绝不能放在 GUI 线程里**——第一版
  就是同步读，结果每次切状态界面都要僵住半秒，连健康检查都显示"还在播上一个动画"。
  因此当缓存未命中时由**后台线程**加载，加载完成后经 `loaded` 信号切回 GUI 线程；
* **内存层**：按 LRU 淘汰，因为 106 个动画全常驻要几 GB。

后台线程与 GUI 线程之间只交换"动画名"，QPixmap 在 GUI 线程里构造（QPixmap 不是
线程安全的，跨线程只能传路径）。
"""

import os
import sys
from collections import deque
from threading import Thread

from PyQt5.QtCore import QObject, Qt, pyqtSignal

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import asset_pipeline  # noqa: E402


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

    def __init__(self, keep=4, parent=None):
        super(FrameStore, self).__init__(parent)
        self._cache = {}          # name -> Animation
        self._order = []          # LRU 顺序，最旧在前
        self._keep = max(1, keep)
        self._loading = set()
        self._disk_ready = set()  # 帧已经躺在磁盘上的动画
        self._pinned = set()      # 正在播放、不能淘汰的动画
        # 按**钉入顺序**记录，`retain()` 靠它裁掉最旧的。用 set 不行——set 不保序。
        self._pin_order = deque()
        self.hits = 0
        self.misses = 0
        self.reloads = 0

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
            try:
                self._ensure_on_disk(name)
                ok = True
            except Exception as error:
                sys.stderr.write("dsh-pet: 解码失败 %s: %s\n" % (name, error))
                ok = False
            self._loading.discard(name)
            if ok:
                self.loaded.emit(name)
            else:
                self.failed.emit(name)

        Thread(target=worker, daemon=True).start()

    def finish_load(self, name):
        """在 **GUI 线程**里把后台准备好的路径登记成一个惰性动画。"""
        if name in self._cache:
            return self._cache[name]
        paths = asset_pipeline.cached_frames(name)
        if not paths:
            return None
        animation = Animation(name, paths)
        self._cache[name] = animation
        self._touch(name)
        self.reloads += 1
        return animation

    # -- 内部 ---------------------------------------------------------------- #
    def _ensure_on_disk(self, name):
        if name in self._disk_ready or asset_pipeline.is_cached(name):
            self._disk_ready.add(name)
            return
        asset_pipeline.build(name)
        self._disk_ready.add(name)

    def _load_sync(self, name):
        if name in self._cache:
            self.hits += 1
            self._touch(name)
            return self._cache[name]
        self.misses += 1
        try:
            self._ensure_on_disk(name)
        except Exception as error:
            sys.stderr.write("dsh-pet: 解码失败 %s: %s\n" % (name, error))
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
            self._cache.pop(candidate, None)
            over -= 1

    # -- 批量 ---------------------------------------------------------------- #
    def preload(self, names):
        """只保证帧在磁盘上（不造 QPixmap，那要几秒）。"""
        for name in names:
            if name in self._cache:
                continue
            try:
                self._ensure_on_disk(name)
            except Exception as error:
                sys.stderr.write("dsh-pet: 预解码失败 %s: %s\n" % (name, error))
            self.finish_load(name)

    def clear(self):
        self._cache.clear()
        self._order = []

    def stats(self):
        return {
            "cached": list(self._order),
            "hits": self.hits,
            "misses": self.misses,
            "reloads": self.reloads,
            "loading": sorted(self._loading),
        }
