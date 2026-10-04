# -*- coding: utf-8 -*-
"""实测"读取 QImage 像素字节"的正确写法。

背景：`QImage.bits()` / `constBits()` 返回的都是 `sip.voidptr`，直接 `bytes(...)`
会报 `IndexError: sip.voidptr object has an unknown size`，而先 `setsize()` 再切片
赋值又会报 `ValueError: cannot modify the size of a sip.voidptr object`。
后一个异常发生在 Qt 事件回调里没人接住，进程会带致命码退出——这就是"点一下就没了"。

这里把几种写法都跑一遍，选出真正可用的那条。

    python tools/probe_image_bytes.py
"""

import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from PyQt5.QtGui import QImage
from PyQt5.QtWidgets import QApplication

app = QApplication([])


def make(width, height):
    """造一张已知内容的 ARGB 图：左上角不透明红，其余全透明。"""
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(0)
    for y in range(2):
        for x in range(2):
            image.setPixelColor(x, y, image.pixelColor(x, y).fromRgb(255, 0, 0, 255))
    return image


def check(label, func):
    try:
        result = func()
    except Exception as error:
        print("  FAIL %-46s %s: %s" % (label, type(error).__name__, error))
        return None
    print("  OK   %-46s -> %s" % (label, result if not isinstance(result, bytes) else "%d 字节" % len(result)))
    return result


for width, height in ((4, 4), (320, 180), (333, 209)):
    print("=== QImage %dx%d (bytesPerLine=%d) ==="
          % (width, height, make(width, height).bytesPerLine()))
    image = make(width, height)

    def via_const_bits_setsize(img=image):
        pointer = img.constBits()
        pointer.setsize(img.byteCount())
        return bytes(pointer)

    def via_bits_setsize(img=image):
        pointer = img.bits()
        pointer.setsize(img.byteCount())
        return bytes(pointer)

    def via_bits_slice_assign(img=image):
        # 这是原实现：先建空图再写指针
        target = QImage(img.width(), img.height(), QImage.Format_Grayscale8)
        pointer = target.bits()
        pointer.setsize(target.byteCount())
        pointer[:] = bytes(target.byteCount())
        return b"ok"

    check("bytes(constBits()) 直接读", lambda img=image: bytes(img.constBits()))
    check("constBits() + setsize + bytes", via_const_bits_setsize)
    check("bits() + setsize + bytes", via_bits_setsize)
    check("bits() + setsize + 切片赋值（原实现）", via_bits_slice_assign)

    def construct_from_bytes(img=image):
        pointer = img.constBits()
        pointer.setsize(img.byteCount())
        data = bytes(pointer)
        rebuilt = QImage(data, img.width(), img.height(), img.bytesPerLine(),
                         QImage.Format_ARGB32)
        return rebuilt.copy()

    check("从 bytes 构造 QImage（推荐）", construct_from_bytes)
    print()
