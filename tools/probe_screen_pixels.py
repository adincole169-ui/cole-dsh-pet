# -*- coding: utf-8 -*-
"""实测：桌宠真正画到设备像素上的东西，与源帧差多少。

前面的比较都是"我们的 PNG 缓存帧 vs 直接解 webm"，那只覆盖到磁盘上的文件。
但用户看的是**屏幕**，中间还有 Qt 的绘制：`drawPixmap(sprite_rect, pixmap, pixmap.rect())`
配 `SmoothPixmapTransform`，而窗口是 320 逻辑 px、dpr=2 —— 设备像素 640。

如果这里存在**额外的一次重采样**（例如先缩到 320 逻辑、再被 backing store 放大回 640），
那画面会比磁盘上的帧更糊，而且这个损失和调色板无关、也解释得通"很明显不如"。

做法：把 PetWindow 真正 render 到一个设备像素级的 QImage 上，取出角色所在区域，
与源帧逐像素比较。同时报告：
  * 窗口逻辑尺寸 / 设备像素尺寸 / dpr
  * 绘制矩形（sprite_rect）与源帧尺寸的关系
  * render 出来的像素 vs 源帧的差异

    python tools/probe_screen_pixels.py 东张西望
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "logs", "screen-pixels.png")


def main():
    argv = sys.argv[1:]
    animation = argv[0] if argv and not argv[0].startswith("-") else "东张西望"
    sys.path.insert(0, os.path.join(ROOT, "src"))
    sys.path.insert(0, ROOT)

    try:
        import numpy as np
        from PyQt5.QtCore import QPoint, Qt
        from PyQt5.QtGui import QImage, QPainter, QPixmap
        from PyQt5.QtWidgets import QApplication
    except ImportError as error:
        print("  需要 PyQt5 + numpy: %s" % error)
        return 1

    from config import load, pet_configs
    from frames import FrameStore
    from main import build_app
    from pet import PetWindow

    app = build_app([])
    config = load()
    entries = pet_configs(config)
    store = FrameStore(keep=4)
    window = PetWindow(entries[0], store)
    window.show()

    # 让它播我们指定的动画并稳定下来
    window.animator.play(animation, loop=True)
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)

    dpr = float(window.devicePixelRatioF())
    sprite = window.sprite_rect()
    print()
    print("  桌宠的显示链路实测（%s）" % animation)
    print("  " + "=" * 74)
    print("  窗口逻辑尺寸 : %d x %d" % (window.width(), window.height()))
    print("  devicePixelRatio : %.2f" % dpr)
    print("  窗口设备像素 : %d x %d"
          % (int(round(window.width() * dpr)), int(round(window.height() * dpr))))
    print("  sprite_rect  : x=%.1f y=%.1f  w=%.1f h=%.1f  （逻辑）"
          % (sprite.left(), sprite.top(), sprite.width(), sprite.height()))
    print("  即设备像素   : w=%.0f h=%.0f"
          % (sprite.width() * dpr, sprite.height() * dpr))

    frame = window.animator.current_frame()
    if frame is None:
        print("  取不到当前帧")
        return 1
    print("  当前帧尺寸   : %d x %d" % (frame.width(), frame.height()))
    target_w = sprite.width() * dpr
    if abs(target_w - frame.width()) < 1.5:
        print("  -> **源帧与绘制设备宽度一致（1:1，无重采样）**")
    else:
        print("  -> **存在缩放**：源 %d -> 设备 %.0f（比例 %.3f）"
              % (frame.width(), target_w, target_w / frame.width()))

    # 真正 render 一遍到设备像素
    image = QImage(int(round(window.width() * dpr)),
                   int(round(window.height() * dpr)),
                   QImage.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    window.render(painter, QPoint(0, 0))
    painter.end()

    raw = image.convertToFormat(QImage.Format_RGBA8888)
    pointer = raw.constBits()
    pointer.setsize(raw.bytesPerLine() * raw.height())
    rendered = np.frombuffer(bytes(pointer), np.uint8).reshape(
        raw.height(), raw.bytesPerLine() // 4, 4)[:, :raw.width(), :]

    source_pixmap = QPixmap(os.path.join(ROOT, "frames", animation, "0031.png"))
    source = QImage(source_pixmap.toImage()).convertToFormat(QImage.Format_RGBA8888)
    sp = source.constBits()
    sp.setsize(source.bytesPerLine() * source.height())
    source_array = np.frombuffer(bytes(sp), np.uint8).reshape(
        source.height(), source.bytesPerLine() // 4, 4)[:, :source.width(), :]

    # 把渲染结果里角色所在的区域抠出来：sprite_rect 的设备坐标
    x0 = int(round(sprite.left() * dpr))
    y0 = int(round(sprite.top() * dpr))
    x1 = min(rendered.shape[1], x0 + source_array.shape[1])
    y1 = min(rendered.shape[0], y0 + source_array.shape[0])
    region = rendered[y0:y1, x0:x1]
    height = min(region.shape[0], source_array.shape[0])
    width = min(region.shape[1], source_array.shape[1])
    if height < 8 or width < 8:
        print("  渲染区域太小，无法比较")
        return 1
    a = region[:height, :width].astype(np.int16)
    b = source_array[:height, :width].astype(np.int16)

    both = (a[..., 3] > 16) & (b[..., 3] > 16)
    print()
    print("  屏幕像素 vs 源帧（仅两者都可见的 %d 个像素）" % int(both.sum()))
    if both.any():
        diff = np.abs(a[..., :3] - b[..., :3])[both]
        print("     RGB 平均差 : %.2f / 255" % diff.mean())
        print("     RGB 最大差 : %d / 255" % diff.max())
        print("     差 > 8 的比例: %.2f%%" % (100.0 * (diff > 8).mean()))
        if diff.mean() < 1.0:
            print("  -> 绘制本身**几乎没有损失**（差异远小于调色板造成的 2.70）")
        else:
            print("  -> 绘制引入了可见差异，值得进一步查")

    # 视觉：把渲染出来的角色与源帧并排（同一尺度）
    tile_w, tile_h = width, height
    sheet = QImage(tile_w * 2 + 20, tile_h, QImage.Format_RGB32)
    sheet.fill(0xFF14161C)
    painter = QPainter(sheet)
    a_image = QImage(a.astype(np.uint8).tobytes(), width, height,
                     width * 4, QImage.Format_RGBA8888)
    b_image = QImage(b[:height, :width].astype(np.uint8).tobytes(), width, height,
                     width * 4, QImage.Format_RGBA8888)
    # 灰底合成
    for index, src_image in enumerate((b_image, a_image)):
        canvas = QImage(width, height, QImage.Format_RGB32)
        canvas.fill(0xFF34383F)
        p2 = QPainter(canvas)
        p2.drawImage(0, 0, src_image)
        p2.end()
        painter.drawImage(10 + index * (tile_w + 10), 0, canvas)
    painter.end()
    sheet.save(OUT)
    print()
    print("  对照图: %s（左=源帧 右=实际渲染，同尺度不放大）"
          % os.path.relpath(OUT, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
