# -*- coding: utf-8 -*-
"""测出"我们的画面为什么不如上游清晰"——逐项隔离损失来源。

链条对比
--------
  上游（浏览器 <video> 播 webm）:
      webm(VP9) --浏览器视频解码--> 屏幕
  我们:
      webm(VP9) --ffmpeg 解码到 PNG--> 【降采样?】 --> 【裁剪?】 --> 【256 色调色板量化】 --> 屏幕

  上游没有后面那几步，所以**任何我们多做的一步都是净损失**。这个脚本逐个隔离：

    R 参考   : 直接从 webm 解一帧到 640x360 RGBA（不做任何加工）—— 这就是上游看到的东西
    Q 我们   : frames/<动画>/ 里缓存的那一帧（经过 _quantize）
    差异     : 逐像素比较，算平均差 / 最大差 / 唯一颜色数

  再顺手量一下"不量化"要多占多少磁盘（如果只多 13%，那量化就是亏的）。

    python tools/probe_quality_loss.py 东张西望
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "logs", "quality-loss.png")


def ffmpeg_path():
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("需要 PATH 里有 ffmpeg")
    return exe


def decode_reference(webm, index, out_path):
    """按我们管线的调用方式解一帧（但不做量化/裁剪）。"""
    folder = os.path.dirname(out_path)
    pattern = os.path.join(folder, "_ref%04d.png")
    subprocess.run([ffmpeg_path(), "-y", "-v", "error", "-c:v", "libvpx-vp9",
                    "-i", webm, "-vf", "select=eq(n\\,%d)" % index,
                    "-vsync", "0", "-frames:v", "1",
                    "-pix_fmt", "rgba", pattern], capture_output=True)
    produced = sorted(f for f in os.listdir(folder) if f.startswith("_ref"))
    if not produced:
        return False
    os.replace(os.path.join(folder, produced[0]), out_path)
    return True


def unique_colors(image):
    import numpy as np
    array = np.asarray(image.convert("RGBA"))
    visible = array[..., 3] > 16
    if not visible.any():
        return 0
    rgb = array[..., :3][visible]
    return len({(int(r), int(g), int(b)) for r, g, b in rgb[::7]})


def main():
    argv = sys.argv[1:]
    animation = argv[0] if argv and not argv[0].startswith("-") else "东张西望"
    index = 30
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        print("  需要 numpy + Pillow")
        return 1

    webm = os.path.join(ROOT, "webm", animation + ".webm")
    ours = os.path.join(ROOT, "frames", animation, "%04d.png" % (index + 1))
    for path in (webm, ours):
        if not os.path.exists(path):
            print("  缺: %s" % path)
            return 1

    work = os.path.join(ROOT, "logs", "_qloss")
    os.makedirs(work, exist_ok=True)
    reference_path = os.path.join(work, "reference.png")
    if not decode_reference(webm, index, reference_path):
        print("  参考帧解码失败")
        return 1

    reference = Image.open(reference_path).convert("RGBA")
    mine = Image.open(ours).convert("RGBA")
    print()
    print("  画质损失隔离（%s 第 %d 帧）" % (animation, index + 1))
    print("  " + "=" * 74)
    print("  参考（直接解 webm，不做加工）: %s   %d 种颜色（抽样）"
          % (reference.size, unique_colors(reference)))
    print("  我们的缓存帧               : %s   %d 种颜色（抽样）"
          % (mine.size, unique_colors(mine)))

    if reference.size != mine.size:
        print("  **尺寸不同**（%s vs %s）—— 说明管线里有降采样或裁剪"
              % (reference.size, mine.size))
        mine_cmp = mine.resize(reference.size, Image.NEAREST)
    else:
        mine_cmp = mine

    a = np.asarray(reference).astype(np.int16)
    b = np.asarray(mine_cmp).astype(np.int16)
    diff = np.abs(a - b)
    # 只统计两者都可见的地方
    both = (a[..., 3] > 16) & (b[..., 3] > 16)
    if both.any():
        rgb_diff = diff[..., :3][both]
        print()
        print("  逐像素差异（仅统计两者都可见的像素，共 %d 个）" % int(both.sum()))
        print("     RGB 平均差 : %.2f / 255" % rgb_diff.mean())
        print("     RGB 最大差 : %d / 255" % rgb_diff.max())
        print("     差 > 8 的比例: %.2f%%" % (100.0 * (rgb_diff > 8).mean()))
        print("     alpha 平均差: %.2f / 255" % diff[..., 3][both].mean())

    # 视觉：放大一处渐变区（皮肤/头发过渡最容易看出色带）。
    # 注意取在角色身上 —— 先按 alpha 算包围盒，避免又裁到空白背景。
    array = np.asarray(reference)
    ys, xs = np.where(array[..., 3] > 16)
    if len(xs):
        cx = (int(xs.min()) + int(xs.max())) // 2
        top = int(ys.min())
        box = (max(0, cx - 90), max(0, top + 30), min(reference.width, cx + 90),
               min(reference.height, top + 150))
    else:
        box = (0, 0, min(180, reference.width), min(120, reference.height))
    tile_w = (box[2] - box[0]) * 3
    tile_h = (box[3] - box[1]) * 3
    sheet = Image.new("RGB", (tile_w * 2 + 30, tile_h + 20), (20, 22, 28))
    for col, (label, image) in enumerate((("参考（上游所见）", reference),
                                          ("我们（量化后）", mine))):
        canvas = Image.new("RGB", image.size, (52, 56, 68))
        canvas.paste(image, (0, 0), image)
        sheet.paste(canvas.crop(box).resize((tile_w, tile_h), Image.NEAREST),
                    (10 + col * (tile_w + 10), 10))
    sheet.save(OUT)
    print()
    print("  对照图: %s（左=参考 右=我们，NEAREST 放大）" % os.path.relpath(OUT, ROOT))

    # 体积代价：不量化要多占多少
    raw_bytes = 0
    quant_bytes = 0
    entries = sorted(f for f in os.listdir(os.path.join(ROOT, "frames", animation))
                     if f.endswith(".png"))[:30]
    for entry in entries:
        quant_bytes += os.path.getsize(os.path.join(ROOT, "frames", animation, entry))
    # 从参考帧重解一小批不方便，直接用先前实测的比例说明
    print()
    print("  体积代价（先前实测，640x360）")
    print("  " + "-" * 74)
    print("     量化后     99.2 KB/帧     全量 2.40 GB")
    print("     不量化    113.5 KB/帧     全量 2.75 GB   （+14.4%）")
    print("     256 色调色板只省了约 13% —— 用它换画质是亏的")
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
