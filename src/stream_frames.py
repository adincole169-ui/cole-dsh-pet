# -*- coding: utf-8 -*-
"""流式帧来源：运行时用 ffmpeg 解码 webm，**磁盘上不留任何帧**。

为什么要有它
------------
上游 dsh-pet 让浏览器/Electron 的 `<video>` 直接播透明 VP9 的 webm：GPU 解码、
不落盘，所以整个插件只有 62 MB。我们做不到那个 —— Qt 的 `QVideoWidget` 是不透明
的原生窗口，**不合成 VP9 的独立 alpha 流**（本机的 PyQt5 5.9.2 连 QtMultimedia
都没有），所以历史上只能把每个动画解成 241 张 PNG，于是本机多出 2.68 GB 缓存。

但"不解码"不是唯一出路：**可以运行时流式解码，不写磁盘**。实测（tools/probe_stream_decode.py）：

    起 ffmpeg 到拿到第一帧   94 ms
    首帧之后每帧            0.6 ms      （24fps 的预算是 41.7 ms，余量约 70 倍）

而且验证过（tools/probe_stream_loop.py）：
  * `-stream_loop -1` 在带 alpha 的 VP9 上可用，第 241 帧与第 0 帧**逐字节相同**
    —— 所以循环播放不需要重起进程，一个 ffmpeg 可以一直转；
  * 流式解出来的像素与原来的 PNG 缓存**逐像素完全相同**（最大差 0/255）
    —— 换帧来源不会改变画面。

设计要点
--------
* **一个动画一个常驻 ffmpeg 进程**，`-stream_loop -1` 让它无限循环。
* **有界环形缓冲 + 按消费位置背压**：生产者读到"比消费位置多 LOOKAHEAD 帧"就停。
  这样内存上限是固定的（`LOOKAHEAD × 900KB`），而不是整段 217 MB。
  背压**必须挂钩消费位置**，只按"缓冲满没满"是不够的 —— 生产者比消费者快 70 倍，
  只按缓冲容量它会一口气跑到第 200 帧，然后消费者要的第 10 帧早已被覆盖。
* **只传 QImage，不传 QPixmap**：QPixmap 不是线程安全的，只能在 GUI 线程造。
  读帧线程产 QImage，`frame()` 在 GUI 线程转 QPixmap 并缓存最近一张。
* **进程必须收干净**：模块级登记所有存活进程，`close()` / `atexit` / 析构都会杀，
  并用 `CREATE_NO_WINDOW` 避免弹出控制台黑框。
"""

import atexit
import os
import shutil
import subprocess
import sys
import threading
import time

from PyQt5.QtGui import QImage, QPixmap

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

WEBM_DIR = os.path.join(ROOT, "webm")
META_PATH = os.path.join(ROOT, "webm-meta.json")

# 预读多少帧。生产者比消费者快约 70 倍，所以不需要很大；
# 留一点余量是为了系统负载高时也不会断帧。16 帧 ≈ 14 MB/动画。
LOOKAHEAD = 16
# 消费位置**之后**再保留几帧：给 `frame()` 的"取最近邻帧"兜底用。
# 再多就是白占内存。内存上限 ≈ (LOOKAHEAD + KEEP_BEHIND) 帧。
KEEP_BEHIND = 4

# Windows 下不要弹出控制台窗口（否则每起一个 ffmpeg 就闪一个黑框）
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# --- 存活进程登记：保证任何退出路径都不留 ffmpeg 僵尸 ------------------------- #
_LIVE = set()
_LIVE_LOCK = threading.Lock()


def _register(process):
    with _LIVE_LOCK:
        _LIVE.add(process)


def _unregister(process):
    with _LIVE_LOCK:
        _LIVE.discard(process)


def kill_all():
    """杀掉所有还活着的 ffmpeg。`atexit` 与 `FrameStore.clear()` 都会调它。"""
    with _LIVE_LOCK:
        alive = list(_LIVE)
        _LIVE.clear()
    for process in alive:
        _terminate(process)


atexit.register(kill_all)


def _terminate(process):
    if process is None:
        return
    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
    except Exception:
        pass
    finally:
        try:
            if process.stdout is not None:
                process.stdout.close()
        except Exception:
            pass


def ffmpeg_path():
    """找 ffmpeg：PATH 优先，其次 imageio-ffmpeg 自带的。找不到返回 None。"""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def available():
    """流式模式能不能用（ffmpeg 在不在）。"""
    return ffmpeg_path() is not None


# --- 元数据：帧数/帧率/尺寸 ---------------------------------------------------- #
_META = None
_META_LOCK = threading.Lock()
_PROBED = {}


def _load_meta():
    global _META
    with _META_LOCK:
        if _META is not None:
            return _META
        data = {}
        if os.path.isfile(META_PATH):
            try:
                import json
                with open(META_PATH, "r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                if isinstance(loaded, dict):
                    data = loaded
            except (ValueError, OSError):
                data = {}
        _META = data
        return _META


def probe_webm(webm):
    """动态探测（元数据里没有的动画才走这里，约 0.2 秒）。"""
    with _META_LOCK:
        if webm in _PROBED:
            return _PROBED[webm]
    exe = shutil.which("ffprobe")
    if not exe:
        return None
    try:
        done = subprocess.run(
            [exe, "-v", "error", "-select_streams", "v:0", "-count_frames",
             "-show_entries", "stream=nb_read_frames,width,height,r_frame_rate",
             "-of", "default=noprint_wrappers=1", webm],
            capture_output=True, text=True, timeout=120)
    except Exception:
        return None
    info = {}
    for line in done.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            info[key.strip()] = value.strip()
    frames = info.get("nb_read_frames") or ""
    if not frames.isdigit() or int(frames) <= 0:
        return None
    rate = info.get("r_frame_rate") or "24/1"
    try:
        if "/" in rate:
            numerator, denominator = rate.split("/", 1)
            fps = float(numerator) / float(denominator)
        else:
            fps = float(rate)
    except (TypeError, ValueError):
        fps = 24.0
    result = {"frames": int(frames), "fps": round(fps, 6),
              "width": int(info.get("width") or 0),
              "height": int(info.get("height") or 0)}
    with _META_LOCK:
        _PROBED[webm] = result
    return result


def webm_info(name):
    """拿一个动画的帧信息；元数据优先，缺失时动态探测。"""
    webm = os.path.join(WEBM_DIR, name + ".webm")
    if not os.path.isfile(webm):
        return None
    meta = _load_meta().get(name)
    if isinstance(meta, dict) and meta.get("frames"):
        info = {"frames": int(meta["frames"]),
                "fps": float(meta.get("fps") or 24.0),
                "width": int(meta.get("width") or 640),
                "height": int(meta.get("height") or 360)}
        # 指纹对不上说明 webm 被换过了，重新探测
        if meta.get("bytes") in (None, os.path.getsize(webm)):
            return info
    probed = probe_webm(webm)
    if probed:
        return {"frames": probed["frames"], "fps": probed["fps"] or 24.0,
                "width": probed["width"] or 640, "height": probed["height"] or 360}
    return None


class StreamAnimation(object):
    """一个动画的帧，来自一个常驻的 ffmpeg 进程。

    接口与 `frames.Animation` 一致（`name` / `fps` / `duration` / `__len__` /
    `width` / `height` / `frame(index)`），所以绘制层不需要区分两者。
    """

    def __init__(self, name, info, lookahead=LOOKAHEAD, exe=None):
        self.name = name
        self.webm = os.path.join(WEBM_DIR, name + ".webm")
        self.fps = float(info.get("fps") or 24.0)
        self._count = int(info["frames"])
        self._width = int(info.get("width") or 640)
        self._height = int(info.get("height") or 360)
        self.duration = self._count / self.fps if self.fps else 0.0
        self._lookahead = max(2, int(lookahead))
        self._bytes_per_frame = self._width * self._height * 4

        self._frames = {}           # index -> QImage
        self._seq = {}              # index -> 写入那一帧时的**绝对序号**（用来淘汰旧帧）
        self._lock = threading.Lock()
        # **消费位置必须是绝对序号（跨圈累加），不能是取模后的帧号。**
        #
        # 踩过：原先 `_position` 存的是帧号（0.._count-1），而 `_written` 是累计写入
        # 序号，两者在 `ahead = self._written - self._position` 里直接相减 —— 量纲不一致。
        # 第一圈还没露馅，第二圈起 `_written` 已经涨到 2*_count 以上，`ahead` 恒大于
        # lookahead，**背压永远不放行**；而那时整段动画又刚好都在内存里，于是表面看
        # 不出问题，实际是"生产者已经死了、靠整段缓存撑着"。
        self._position = 0          # 消费端最近的**绝对**位置
        self._written = 0           # 生产端累计写入序号
        self._stop = threading.Event()
        self._first = threading.Event()
        self._error = None
        self._process = None
        self._thread = None
        self._closed = False

        self._last_index = -1
        self._last_pixmap = None

        self._exe = exe or ffmpeg_path()
        if not self._exe:
            raise RuntimeError("找不到 ffmpeg")
        self._thread = threading.Thread(target=self._run, name="stream-" + name)
        self._thread.daemon = True
        self._thread.start()

    # -- 接口 ---------------------------------------------------------------- #
    def __len__(self):
        return self._count

    @property
    def width(self):
        return self._width

    @property
    def height(self):
        return self._height

    @property
    def frames(self):
        """已就绪的帧（只用于统计）。"""
        with self._lock:
            return [self._frames[key] for key in sorted(self._frames)]

    def frame(self, index):
        """取某一帧（**GUI 线程调用**）。还没读到就返回 None。

        返回 None 是刻意的：`Playing.frame()` 会据此回退到上一段的最后一帧
        （`outgoing`），所以"流还没起来"不会画出空白。

        但**精确那一帧没到、而附近有帧**时，取最近的一帧顶一下，而不是返回 None：
        界面卡了很久之后 `elapsed` 会一下跳到底，请求的帧号离生产位置很远，
        这时若回退到 `outgoing`，画面上会突然出现**别的动作**；给一个同动画的邻帧
        就自然得多，而且下一 tick 就会纠正回来。距离限制在 `_lookahead` 之内，
        避免拿到上一圈的陈旧帧。
        """
        if self._count <= 0:
            return None
        wanted = max(0, min(self._count - 1, int(index)))
        with self._lock:
            # 背压与生产位置都按"消费者**想要**的位置"走。这里把帧号换算成**绝对**
            # 位置，而且**只往前**：ffmpeg 是顺序流（`-stream_loop -1`），回不去。
            # 想要一个更早的帧（例如重新从第 0 帧开始播）就等它下一圈转回来 ——
            # 生产者比实时快约 70 倍，一圈也就几百毫秒，期间由下面的邻帧兜底。
            # 若允许往回退，`_written - _position` 会远大于 lookahead，背压永远不放行。
            delta = (wanted - self._position % self._count) % self._count
            self._position += delta
            image = self._frames.get(wanted)
            served = wanted
            if image is None and self._frames:
                best = None
                best_distance = None
                for key in self._frames:
                    distance = abs(key - wanted)
                    distance = min(distance, self._count - distance)
                    if best_distance is None or distance < best_distance:
                        best, best_distance = key, distance
                if best_distance is not None and best_distance <= self._lookahead:
                    image = self._frames[best]
                    served = best
        if image is None:
            return None
        if served == self._last_index and self._last_pixmap is not None:
            return self._last_pixmap
        pixmap = QPixmap.fromImage(image)
        self._last_index = served
        self._last_pixmap = pixmap
        return pixmap

    def wait_first(self, timeout=6.0):
        """等第一帧就绪。后台线程用它决定要不要报 loaded。"""
        return self._first.wait(timeout)

    @property
    def error(self):
        return self._error

    def close(self):
        """停掉读帧线程与 ffmpeg 进程。可重复调用。"""
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        # **先杀进程、再等线程。** 读线程可能正阻塞在 `stdout.read()` 上，只有进程退出
        # 才会返回；反过来做会让调用方（淘汰发生在 **GUI 线程**）白等最多 3 秒。
        process = self._process
        _terminate(process)
        _unregister(process)
        thread = self._thread
        if (thread is not None and thread.is_alive()
                and thread is not threading.current_thread()):
            thread.join(timeout=1)
        self._process = None
        with self._lock:
            self._frames.clear()
            self._seq.clear()
        self._last_pixmap = None
        self._last_index = -1

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    # -- 生产者 -------------------------------------------------------------- #
    def _run(self):
        try:
            command = [self._exe, "-v", "error", "-stream_loop", "-1",
                       "-c:v", "libvpx-vp9", "-i", self.webm,
                       "-f", "rawvideo", "-pix_fmt", "rgba", "-"]
            self._process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
            _register(self._process)
            stream = self._process.stdout
            while not self._stop.is_set():
                with self._lock:
                    ahead = self._written - self._position
                if ahead >= self._lookahead:
                    # 背压：等消费者往前走。用 wait 而不是 sleep，close() 能立刻唤醒。
                    self._stop.wait(0.004)
                    continue
                data = self._read_exactly(stream, self._bytes_per_frame)
                if data is None:
                    break
                image = QImage(data, self._width, self._height,
                               self._width * 4, QImage.Format_RGBA8888).copy()
                with self._lock:
                    slot = self._written % self._count
                    self._frames[slot] = image
                    self._seq[slot] = self._written
                    self._written += 1
                    # **淘汰落在消费位置之后太远的帧。**
                    #
                    # 踩过：`_frames` 只写不删，跑满一圈（帧号覆盖 0.._count-1 全部槽位）
                    # 之后整段动画都留在内存里。实测（tools/probe_stream_memory.py）：
                    # 118 帧的动画跑 2.3 圈后 `_frames` 有 118 条、RSS 涨 92 MB
                    # （单帧 0.88 MB × 118 = 104 MB）；而更长的那批 241 帧 = 217 MB/动画，
                    # `keep=6` 就是 1.3 GB。加淘汰之后上限 ≈ (LOOKAHEAD + KEEP_BEHIND) 帧。
                    floor = self._position - KEEP_BEHIND
                    for key in [k for k, seq in self._seq.items() if seq < floor]:
                        self._seq.pop(key, None)
                        self._frames.pop(key, None)
                self._first.set()
        except Exception as error:
            self._error = error
        finally:
            if self._process is not None and self._process.poll() is not None:
                # 进程自己退了（解码失败等），把错误记下来
                if self._error is None and self._written == 0:
                    self._error = RuntimeError(
                        "ffmpeg 提前退出，返回码 %s" % self._process.returncode)
            self._stop.set()
            self._first.set()          # 别让等首帧的线程一直挂着

    @staticmethod
    def _read_exactly(stream, size):
        buffer = bytearray()
        while len(buffer) < size:
            try:
                chunk = stream.read(size - len(buffer))
            except Exception:
                return None
            if not chunk:
                return None
            buffer.extend(chunk)
        return bytes(buffer)


def smoke_test(name="待机呼吸休闲", frames=40):
    """自检用：起一个流，量"顺序播放会不会断帧"，再收干净。返回 (ok, 说明)。

    **必须先有 QApplication**：`frame()` 里会 `QPixmap.fromImage()`，
    而没有 QGuiApplication 时 Qt 会直接中止进程（连报错都不给，表现为"没输出"）。

    量的是**真实访问模式**：播放是顺序的（每 41.7 ms 前进一帧），生产者比它快约 70 倍，
    所以顺序取帧**不应该需要等**。脚本对每一帧最多重试 20 次 × 5 ms，统计重试情况。
    """
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])             # noqa: F841
    info = webm_info(name)
    if not info:
        return False, "拿不到 %s 的帧信息" % name
    if not available():
        return False, "找不到 ffmpeg"
    animation = None
    try:
        animation = StreamAnimation(name, info)
        if not animation.wait_first(6.0):
            return False, "6 秒内没等到第一帧（%s）" % (animation.error or "无报错")

        total = min(frames, len(animation))
        stalls = 0
        worst = 0
        for index in range(total):
            tries = 0
            while animation.frame(index) is None and tries < 20:
                time.sleep(0.005)
                tries += 1
            if tries >= 20:
                return False, "第 %d 帧等了 100 ms 还没到" % index
            if tries:
                stalls += 1
                worst = max(worst, tries)

        # 远距离跳帧：有界缓冲只能顺序供给，跳过去要等生产者读过来。
        # 这在真实播放里只会在"界面卡了很久、elapsed 一下跳到底"时发生，
        # 返回 None 让 Playing 回退到上一帧即可，不会画空白。这里如实量一下要等多久。
        jump_started = time.perf_counter()
        target = len(animation) - 1
        jump_ok = False
        while time.perf_counter() - jump_started < 2.0:
            if animation.frame(target) is not None:
                jump_ok = True
                break
            time.sleep(0.01)
        jump_ms = (time.perf_counter() - jump_started) * 1000.0

        pixel = animation.frame(target if jump_ok else 0)
        return True, ("%d 帧元数据；顺序取 %d 帧：%d 帧需重试（最多 %d 次×5ms）；"
                      "远跳第 %d 帧 %s（%.0f ms）；尺寸 %dx%d"
                      % (len(animation), total, stalls, worst, target,
                         "成功" if jump_ok else "2 秒内未到", jump_ms,
                         pixel.width() if pixel else 0,
                         pixel.height() if pixel else 0))
    except Exception as error:
        return False, "%s: %s" % (type(error).__name__, error)
    finally:
        if animation is not None:
            animation.close()


if __name__ == "__main__":
    sys.stdout.write("\n  流式帧来源自检\n  " + "=" * 60 + "\n")
    exe = ffmpeg_path()
    sys.stdout.write("  ffmpeg: %s\n" % (exe or "**找不到**"))
    if not exe:
        sys.exit(1)
    ok, message = smoke_test()
    sys.stdout.write("  %s %s\n\n" % ("[OK]  " if ok else "[失败]", message))
    sys.exit(0 if ok else 1)
