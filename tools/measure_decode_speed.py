# -*- coding: utf-8 -*-
"""实测：解码到底有多费事，以及并行能提速多少。

背景：如果随仓库附带 webm（方案 B），用户 clone 之后仍然要**解码成 PNG** 才能流畅播放。
单线程实测约 31 秒/动画，106 个就是 55 分钟 —— 这是方案 B 的主要摩擦。

本脚本量三件事：
  1. 本机 CPU 核数（决定并行上限）
  2. 串行解码 N 个动画的耗时
  3. 并行解码同样 N 个的耗时（用独立 ffmpeg 进程）

**会临时移走并还原缓存**（先备份再还原，避免上次那种"把动画清空"的事故）。

    python tools/measure_decode_speed.py
"""

import os
import shutil
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import asset_pipeline as pipeline                        # noqa: E402

# 挑几个体积中等的动画来测（避免挑到最特殊的）
SAMPLES = ["东张西望", "吃汤圆", "摇扇纳凉", "撸猫", "放风筝", "吹气球"]
BACKUP_SUFFIX = ".speedtest"


def decode_one(name):
    """解码一个动画，返回 (名字, 秒数, 帧数)。**自己负责备份/还原**。"""
    cache = pipeline.cache_dir(name)
    backup = cache + BACKUP_SUFFIX
    if os.path.isdir(backup):
        shutil.rmtree(backup)
    if os.path.isdir(cache):
        shutil.move(cache, backup)
    started = time.time()
    try:
        pipeline.build(name, width=pipeline.TARGET_WIDTH, force=True)
        count = len(pipeline.cached_frames(name))
        return name, time.time() - started, count
    finally:
        if os.path.isdir(cache):
            shutil.rmtree(cache)
        if os.path.isdir(backup):
            shutil.move(backup, cache)


def main():
    cores = os.cpu_count() or 1
    print()
    print("  环境")
    print("  " + "=" * 60)
    print("     CPU 逻辑核数: %d" % cores)
    print("     TARGET_WIDTH: %d" % pipeline.TARGET_WIDTH)
    print("     样本动画数  : %d" % len(SAMPLES))
    print()

    print("  串行解码")
    print("  " + "-" * 60)
    serial = []
    for name in SAMPLES:
        _name, seconds, count = decode_one(name)
        serial.append(seconds)
        print("     %-14s %5.1f 秒  (%d 帧)" % (name, seconds, count))
    serial_avg = statistics.mean(serial)
    print("     平均: %.1f 秒/动画" % serial_avg)

    workers = min(6, max(2, cores // 2))
    print()
    print("  并行解码（%d 个 worker）" % workers)
    print("  " + "-" * 60)
    started = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(decode_one, SAMPLES))
    wall = time.time() - started
    for name, seconds, count in results:
        print("     %-14s 该进程耗时 %5.1f 秒" % (name, seconds))
    parallel_avg = wall / len(SAMPLES)
    print("     墙钟总耗时: %.1f 秒 -> 摊到每个动画 %.1f 秒" % (wall, parallel_avg))

    print()
    print("  结论")
    print("  " + "=" * 60)
    speedup = serial_avg / parallel_avg if parallel_avg else 0
    print("     串行 %.1f 秒/动画  ->  并行(%d) %.1f 秒/动画   提速 %.1f 倍"
          % (serial_avg, workers, parallel_avg, speedup))
    print()
    print("     全量 106 个动画：")
    print("       串行  约 %.0f 分钟" % (serial_avg * 106 / 60.0))
    print("       并行  约 %.0f 分钟" % (parallel_avg * 106 / 60.0))
    print("     只解常用（约 26 个，`--predecode` 的范围）：")
    print("       并行  约 %.0f 分钟" % (parallel_avg * 26 / 60.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
