# -*- coding: utf-8 -*-
"""对比不同缓存宽度在实际显示尺寸下的清晰度损失。

判断"够不够清晰"不能靠感觉，所以这里做两件事：
  1. 把同一帧分别从 400 / 480 / 640 放大到实际显示尺寸，量与原生的平均像素差；
  2. 输出一张三联对比图，肉眼也能看。

    python tools/compare_sharpness.py
"""

import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from PIL import Image

WEBM = os.path.join(ROOT, "webm", "待机呼吸休闲.webm")
DISPLAY_WIDTH = 640          # size 320 逻辑 x dpr 2 = 物理 640
CANDIDATES = (400, 480, 640)


def extract_native():
    """用 ffmpeg 取一帧**原生分辨率**作为基准。"""
    import subprocess
    out = os.path.join(ROOT, "logs", "_native.png")
    subprocess.run([ "ffmpeg", "-y", "-v", "error", "-c:v", "libvpx-vp9",
                     "-i", WEBM, "-frames:v", "1", "-pix_fmt", "rgba", out],
                   capture_output=True)
    return Image.open(out).convert("RGBA")


def main():
    native = extract_native()
    print("  原生帧: %s" % (native.size,))

    rows = []
    for width in CANDIDATES:
        height = int(round(native.height * width / float(native.width)))
        cached = native.resize((width, height), Image.LANCZOS)
        shown = cached.resize((DISPLAY_WIDTH,
                               int(round(height * DISPLAY_WIDTH / float(width)))),
                              Image.LANCZOS)
        reference = native.resize(shown.size, Image.LANCZOS)
        # 平均绝对误差（只算两边都不透明的像素，边缘不算）
        diff = 0
        count = 0
        for y in range(0, shown.height, 3):
            for x in range(0, shown.width, 3):
                a = shown.getpixel((x, y))
                b = reference.getpixel((x, y))
                if a[3] > 200 and b[3] > 200:
                    diff += sum(abs(a[i] - b[i]) for i in range(3)) / 3.0
                    count += 1
        row = {"width": width, "mean_diff": diff / max(1, count), "image": shown}
        rows.append(row)
        print("  缓存 %3d 宽 -> 显示 %d 宽: 平均像素差 %.2f / 255" % (width, DISPLAY_WIDTH, row["mean_diff"]))

    # 三联对比图
    sheet = Image.new("RGBA", (DISPLAY_WIDTH * len(rows) + 10 * (len(rows) - 1),
                               rows[0]["image"].height), (40, 44, 56, 255))
    x = 0
    for row in rows:
        sheet.paste(row["image"], (x, 0), row["image"])
        x += row["image"].width + 10
    out = os.path.join(ROOT, "logs", "sharpness.png")
    sheet.convert("RGB").save(out, "PNG")
    print("  已存 %s（左→右: %s）" % (out, " / ".join(str(r["width"]) for r in rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
