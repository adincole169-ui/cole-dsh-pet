# -*- coding: utf-8 -*-
"""把上游的预览 GIF 与我们的帧放在一起看，搞清"为什么他的预览看起来更清晰"。

已查明预览 GIF 只有 **220x124**（12fps、120 帧），远比我们的 640x360 小。
所以"他有更高分辨率"不成立。那就要看**观感**差异来自哪里：

  可能一：它是由 1280x720 的源**大幅降采样**得到的（5.8 倍），
          降采样会带来极强的超采样效果 —— 边缘干净、几乎没有锯齿；
  可能二：它在页面上以**很小的尺寸**显示，小图天然显得"实"；
  可能三：GIF 只有 256 色，但它在小尺寸下反而不明显。

本脚本把三种东西并排（都缩到同一显示尺寸）：
    A 上游预览 GIF 的某一帧（220 -> 放大到目标尺寸）
    B 我们的帧（640 -> 缩到同一尺寸）
    C 我们的帧 1:1（不缩）
再看谁更"实"。

    python tools/probe_preview_gif.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GIF = r"E:\dsh\_gif\preview.gif"
OURS = os.path.join(ROOT, "frames", "待机呼吸休闲", "0031.png")
OUT = os.path.join(ROOT, "logs", "preview-compare.png")
BACKGROUND = (52, 56, 68)


def flatten(image, size=None):
    from PIL import Image
    if size and image.size != size:
        image = image.resize(size, Image.LANCZOS)
    canvas = Image.new("RGB", image.size, BACKGROUND)
    canvas.paste(image, (0, 0), image)
    return canvas


def main():
    try:
        from PIL import Image, ImageSequence
    except ImportError:
        print("  需要 Pillow")
        return 1
    if not os.path.isfile(GIF):
        print("  没有 %s（先下载上游预览 GIF）" % GIF)
        return 1
    if not os.path.isfile(OURS):
        print("  没有 %s" % OURS)
        return 1

    with Image.open(GIF) as handle:
        frames = [frame.convert("RGBA") for frame in ImageSequence.Iterator(handle)]
    print()
    print("  上游预览 GIF: %d 帧，单帧 %s" % (len(frames), frames[0].size))
    with Image.open(OURS) as raw:
        ours = raw.convert("RGBA")
    print("  我们的帧    : %s" % (ours.size,))

    # 三者都放到 "预览 GIF 的 4 倍" 这个尺寸上比较（在屏幕上相当于放大看）
    target = (frames[0].width * 4, frames[0].height * 4)
    panels = [
        ("A 上游预览 GIF 放大 4 倍", flatten(frames[len(frames) // 2], target)),
        ("B 我们的帧 缩到同一尺寸", flatten(ours, target)),
    ]
    # 另外单独给一张我们的 1:1（按比例缩到同一高度）
    scale = target[1] / float(ours.height)
    panels.append(("C 我们的帧 1:1（等比缩到同高）",
                   flatten(ours, (int(ours.width * scale), target[1]))))

    gap = 14
    width = sum(p[1].width for p in panels) + gap * (len(panels) + 1)
    height = target[1] + 30
    sheet = Image.new("RGB", (width, height), (20, 22, 28))
    x = gap
    for _label, image in panels:
        sheet.paste(image, (x, 15))
        x += image.width + gap
    sheet.save(OUT)
    print()
    print("  对照图: %s" % os.path.relpath(OUT, ROOT))
    print("     左=预览 GIF（放大 4 倍）  中=我们的帧缩到同一尺寸  右=我们的帧 1:1")
    print()
    print("  判读要点")
    print("  " + "-" * 68)
    print("  * 左图若显得更'实'，是因为它由 1280 源**降采样 5.8 倍**——超采样把")
    print("    锯齿和压缩噪声都抹平了；而它的实际信息量只有 220x124。")
    print("  * 中图是同样尺寸下的公平比较：我们用同一个 640 webm 缩下去，")
    print("    如果中图与左图接近，说明差异纯粹来自'降采样倍数'，不是我们有损失。")
    print("  * 右图是桌宠实际显示的样子（1:1）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
