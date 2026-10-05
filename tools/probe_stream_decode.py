# -*- coding: utf-8 -*-
"""测"运行时流式解码"（最接近上游做法）的可行性与开销。

上游是 `<video>` 直接播 webm，**不落盘任何帧**。我们做不到那个（Qt 不合并 VP9 的
独立 alpha 流），但可以做得**接近**：

    播放某个动画时现场起一个 ffmpeg，把 rawvideo RGBA 帧从管道读进内存，
    转成 QImage 直接贴图 —— 磁盘上只留 52 MB 的 webm，**缓存归零**。

要量的就是它到底行不行：
  1. **启动延迟**：从起 ffmpeg 到拿到第一帧要多久（决定"切动画会不会卡一下"）
  2. **解码吞吐**：能不能跟上 24fps（每帧预算 41.7 ms）
  3. **CPU 占用**：常驻播放时的负载
  4. **随机跳帧**：交叉淡化需要"上一段的最后一帧"，流式解码能不能拿到

    python tools/probe_stream_decode.py 东张西望
"""

import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
W, H = 640, 360
FRAME_BYTES = W * H * 4


def ffmpeg_path():
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("需要 PATH 里有 ffmpeg")
    return exe


def stream_once(webm, frames_to_read):
    """起一次 ffmpeg，读若干帧，返回 (首帧耗时, 读满耗时, 实际帧数)。"""
    command = [ffmpeg_path(), "-v", "error", "-c:v", "libvpx-vp9",
               "-i", webm, "-f", "rawvideo", "-pix_fmt", "rgba", "-"]
    started = time.perf_counter()
    process = subprocess.Popen(command, stdout=subprocess.PIPE)
    first = None
    count = 0
    try:
        while count < frames_to_read:
            buffer = b""
            while len(buffer) < FRAME_BYTES:
                chunk = process.stdout.read(FRAME_BYTES - len(buffer))
                if not chunk:
                    break
                buffer += chunk
            if len(buffer) < FRAME_BYTES:
                break
            count += 1
            if first is None:
                first = time.perf_counter() - started
    finally:
        try:
            process.stdout.close()
        except Exception:
            pass
        process.terminate()
        try:
            process.wait(timeout=10)
        except Exception:
            process.kill()
    elapsed = time.perf_counter() - started
    return first, elapsed, count


def main():
    argv = sys.argv[1:]
    animation = argv[0] if argv and not argv[0].startswith("-") else "东张西望"
    webm = os.path.join(ROOT, "webm", animation + ".webm")
    if not os.path.exists(webm):
        print("  找不到 %s" % webm)
        return 1

    print()
    print("  流式解码实测（%s）" % animation)
    print("  " + "=" * 74)
    print("  每帧 %dx%d RGBA = %.1f KB（内存里的裸帧）" % (W, H, FRAME_BYTES / 1024.0))

    # 连起 3 次，看启动延迟的稳定度
    print()
    print("  ① 启动延迟（起 ffmpeg 到拿到第一帧）")
    print("  " + "-" * 74)
    firsts = []
    for index in range(3):
        first, elapsed, count = stream_once(webm, 8)
        firsts.append(first)
        print("     第 %d 次: 首帧 %.0f ms   读 8 帧共 %.0f ms   （%.1f ms/帧）"
              % (index + 1, first * 1000, elapsed * 1000,
                 (elapsed - first) * 1000 / max(1, count - 1)))
    print("     首帧平均 %.0f ms" % (sum(firsts) / len(firsts) * 1000))

    # 吞吐：读满整段
    first, elapsed, count = stream_once(webm, 241)
    print()
    print("  ② 吞吐（读满整段 241 帧）")
    print("  " + "-" * 74)
    print("     实际读到 %d 帧，总耗时 %.0f ms" % (count, elapsed * 1000))
    if count > 1:
        per_frame = (elapsed - first) * 1000 / (count - 1)
        print("     首帧后每帧 %.1f ms（24fps 的预算是 41.7 ms）" % per_frame)
        if per_frame < 41.7:
            print("     -> **跟得上实时播放**（余量 %.0f 倍）" % (41.7 / per_frame))
            print("        整段解完只要 %.1f 秒，而动画本身要放 10 秒 —— 完全可以"
                  % elapsed)
            print("        可以预解码下一段来掩盖启动延迟。")
        else:
            print("     -> **跟不上实时**，只能预解码。")

    print()
    print("  ③ 与现有方案对比")
    print("  " + "-" * 74)
    print("     现有（解成 PNG 缓存）: 磁盘 2.68 GB   切换动画 0 延迟")
    print("     流式（本次实测）      : 磁盘 0         切换动画 首帧约 %.0f ms" % (sum(firsts) / len(firsts) * 1000))
    print("     上游（<video>）       : 磁盘 0         切换动画 更短（解码器常驻）")
    print()
    print("  ④ 代价")
    print("  " + "-" * 74)
    print("     * 运行时需要 ffmpeg（现在只需要 PyQt5）—— 可用 pip 的 imageio-ffmpeg 兜底")
    print("     * 每次切换动画都要起一个进程（约 %.0f ms 开销）" % (sum(firsts) / len(firsts) * 1000))
    print("     * 交叉淡化要「上一段的最后一帧」：流式下要么留着那个进程，")
    print("       要么把最后一帧留在内存里（一张图，代价可忽略）")
    print("     * 无法随机跳帧 —— 但桌宠只顺序播放，不需要")
    return 0


if __name__ == "__main__":
    sys.exit(main())
