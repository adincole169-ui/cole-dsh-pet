# -*- coding: utf-8 -*-
"""检查全透明像素的 RGB 是什么颜色。

为什么关键：PNG 存的是**非预乘** RGBA。Qt 用 `SmoothPixmapTransform` 缩放时会对
RGBA 四个通道一起插值 —— 如果全透明像素的 RGB 仍是**绿色**，那绿色就会被插进边缘，
**显示时才出现绿边**（素材本身看着没绿）。这解释了"定量测出 0 个偏绿像素，
但用户眼睛看到绿幕残留"。

Q 弹挤压（squash）、切换动画的交叉淡化都会触发缩放，所以这种绿边是动态出现的。
"""

import os
import sys

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def look(path, label):
    if not os.path.isfile(path):
        print("  %-30s 文件不存在" % label)
        return
    image = Image.open(path).convert("RGBA")
    array = np.asarray(image)
    alpha = array[..., 3]
    transparent = alpha == 0
    if transparent.sum() == 0:
        print("  %-30s 没有全透明像素" % label)
        return
    rgb = array[..., :3][transparent].astype(np.int16)
    mean = rgb.mean(axis=0)
    green = rgb[:, 1]
    other = np.maximum(rgb[:, 0], rgb[:, 2])
    greenish = int((green > other + 16).sum())
    print("  %-30s 全透明 %7d   平均 RGB=(%5.1f,%5.1f,%5.1f)   绿色主导 %5.1f%%"
          % (label, int(transparent.sum()), mean[0], mean[1], mean[2],
             100.0 * greenish / transparent.sum()))


def main():
    print()
    print("  全透明区域的 RGB 是什么颜色（决定缩放时会不会泛绿）")
    print("  " + "=" * 88)
    look(os.path.join(ROOT, "frames", "东张西望", "0031.png"), "现有 640（上游手工抠像）")
    look(r"E:\dsh\_src\hires\东张西望\0031.png", "我的高清版（v2 抠像）")
    look(os.path.join(ROOT, "frames", "待机呼吸休闲-高清", "0031.png"), "装进桌宠的高清待机")
    look(os.path.join(ROOT, "frames", "待机呼吸休闲", "0031.png"), "现有 640 待机")
    print()
    print("  判读：若「我的高清版」绿色主导比例很高，而「现有」很低，")
    print("        那绿边就是**缩放时插值透明像素的绿色 RGB** 造成的，")
    print("        修法是给透明区域做 **alpha bleed**（把角色边缘的颜色向外扩散填充），")
    print("        而不是继续调抠像阈值。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
