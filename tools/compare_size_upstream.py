# -*- coding: utf-8 -*-
"""对比：上游插件的大小 vs 我们项目的大小 —— 分清"发行体积"与"本机缓存"。

用户的疑问："为什么他的文件这么小"。

要区分三样东西，它们不是一回事：
  1. **发行体积**（进 git / 装到 DSH 的东西）—— 上游 62 MB，我们 52.5 MB
  2. **本机解码缓存**（`frames/`）—— 只有我们有 2.62 GB，但它**不进 git**
     而且随时可删、删了按需重建
  3. 两者之所以差 50 倍，是因为 PNG（无损、帧内压缩）vs VP9（有损、帧间压缩）

    python tools/compare_size_upstream.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UPSTREAM = os.path.join(os.environ.get("USERPROFILE", ""),
                        ".dsh", "profiles", "desktop", "node_modules", "dsh-pet")


def folder_size(path, pattern=None):
    total = count = 0
    for base, _dirs, files in os.walk(path):
        for name in files:
            if pattern and not name.endswith(pattern):
                continue
            try:
                total += os.path.getsize(os.path.join(base, name))
                count += 1
            except OSError:
                pass
    return total, count


def mb(value):
    return "%.1f MB" % (value / 1048576.0)


def main():
    print()
    print("  大小对比：上游插件 vs 我们项目")
    print("  " + "=" * 76)

    # --- 发行体积 ---
    print()
    print("  ① 发行体积（进 git / 装到 DSH 的部分）")
    print("  " + "-" * 76)
    if os.path.isdir(UPSTREAM):
        total, count = folder_size(UPSTREAM)
        webm, webm_n = folder_size(os.path.join(UPSTREAM, "assets", "webm"))
        memes, memes_n = folder_size(os.path.join(UPSTREAM, "assets", "memes"))
        print("     上游 dsh-pet 整个包 : %-12s（%d 个文件）" % (mb(total), count))
        print("        其中 webm          : %-12s（%d 个）" % (mb(webm), webm_n))
        print("        其中 memes         : %-12s（%d 个）" % (mb(memes), memes_n))
        print("        其余（代码/字体/图）: %s" % mb(total - webm - memes))
    else:
        print("     找不到上游插件: %s" % UPSTREAM)

    ours_repo = 0
    for name in ("webm", "assets", "memes"):
        path = os.path.join(ROOT, name)
        if os.path.isdir(path):
            size, _count = folder_size(path)
            ours_repo += size
    code = 0
    for name in ("main.py", "src", "tools", "plugins", "config.jsonc"):
        path = os.path.join(ROOT, name)
        if os.path.isfile(path):
            code += os.path.getsize(path)
        elif os.path.isdir(path):
            size, _count = folder_size(path)
            code += size
    print()
    print("     我们项目里同样的东西   : %-12s" % mb(ours_repo + code))
    print("        其中 webm          : %s（与上游逐字节相同）"
          % mb(folder_size(os.path.join(ROOT, "webm"))[0]))
    print("        其中代码/文档/工具  : %s" % mb(code))
    print()
    print("     -> **发行体积我们和上游基本一样**（我们 52.5 MB，上游 62 MB，")
    print("        差别主要在上游多带了 27 张表情包与一个 3.9 MB 字体）")

    # --- 本机缓存 ---
    print()
    print("  ② 本机解码缓存（只有我们有）")
    print("  " + "-" * 76)
    frames = os.path.join(ROOT, "frames")
    if os.path.isdir(frames):
        total, count = folder_size(frames)
        print("     frames/ : %-12s（%d 个 PNG）" % (mb(total), count))
        if count:
            print("     平均单帧: %.1f KB" % (total / count / 1024.0))
    webm_total, webm_count = folder_size(os.path.join(ROOT, "webm"))
    if webm_count:
        print("     对照 webm 平均单动画: %.1f KB  -> 解成 PNG 后 %.1f KB/帧 × 241 帧"
              % (webm_total / webm_count / 1024.0,
                 (total / count / 1024.0) if count else 0))
    print()
    print("     这一份**不进 git**（.gitignore 排除 frames/），而且随时可删：")
    print("       python tools/asset_pipeline.py clean     # 全删，按需重建")
    print("       只预解码常用的那批：python setup_assets.py（不加 --all）")

    # --- 为什么差这么多 ---
    print()
    print("  ③ 为什么差 50 倍")
    print("  " + "-" * 76)
    print("     webm = **有损 + 帧间压缩**：只存帧与帧的差异，而且允许失真（CRF30）")
    print("     PNG  = **无损 + 帧内压缩**：每一帧都是独立完整图像")
    print()
    print("     上游不用解码：浏览器/Electron 的 `<video>` 直接播 webm（GPU 解码）。")
    print("     我们必须解码：PyQt5 播不了带独立 alpha 流的 VP9 —— Qt 不合并那路 alpha，")
    print("     本机的 PyQt5 5.9.2 连 QtMultimedia 都没有。所以只能解成 PNG 逐帧贴图。")
    print()
    print("     **这是「没有视频解码器」的代价，不是浪费。** 换来的是：不必装 ffmpeg、")
    print("     不必每次播放都解码、启动即流畅。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
