# -*- coding: utf-8 -*-
"""生成桌面快捷方式用的图标（`assets/icon.ico` / `icon.png`）。

关键点是**去掉留白**。素材帧是 640×360，角色只占中间一小块；早期版本直接按正方形
裁切就完事，结果角色只占画布 35% 宽、43% 高——Windows 把它缩到 32×32 显示时，
角色本身只剩十来个像素，看起来"图标很小"。

所以这里分三步：
  1. 用 alpha 包围盒裁到**紧贴角色**；
  2. 按 `FILL` 的比例放大，留一点点内边距（太满会显得挤）；
  3. 输出 ico 的多档尺寸——Windows 会按显示需求挑合适的一档。

    python tools/make_icon.py
"""

import os
import subprocess
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ASSETS = os.path.join(ROOT, "assets")
SOURCE = os.path.join(ROOT, "webm", "待机呼吸休闲.webm")
FRAME = os.path.join(ROOT, "logs", "_icon-frame.png")

# 角色占画布的比例。0.94 表示四周只留 3% 内边距——比原来的 35% 大了近三倍
FILL = 0.94
SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]

# 判定"实心"的 alpha 阈值。**不能用 getbbox() 的默认阈值 0**：这套素材的"透明"
# 是很低的 alpha（背景 1–8、角色很高），阈值 0 会把整张 640×360 都算成有内容，
# 于是裁切形同虚设（第一次生成就是这么失败的：角色仍只占 35%）。
ALPHA_MIN = 16
# 找包围盒时先缩到显示尺寸再按阈值判定：640×360 逐像素在 Python 里太慢，
# 而包围盒本来也不需要像素级精度。
PROBE_WIDTH = 160


def content_box(image, alpha_min=ALPHA_MIN):
    """按 alpha **阈值**求非透明包围盒，返回原图坐标下的 (left, top, right, bottom)。"""
    probe = image.resize(
        (PROBE_WIDTH, max(1, int(round(image.height * PROBE_WIDTH / float(image.width))))),
        Image.NEAREST)
    mask = probe.getchannel("A").point(lambda value: 255 if value > alpha_min else 0)
    box = mask.getbbox()
    if box is None:
        return None
    scale = image.width / float(probe.width)
    return (int(box[0] * scale), int(box[1] * scale),
            int(box[2] * scale), int(box[3] * scale))


def extract_frame():
    """从素材里取一帧（带透明通道，必须用 libvpx 的 VP9 解码器）。"""
    os.makedirs(os.path.dirname(FRAME), exist_ok=True)
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-c:v", "libvpx-vp9", "-i", SOURCE,
         "-frames:v", "1", "-pix_fmt", "rgba", FRAME],
        capture_output=True)
    if result.returncode != 0:
        raise RuntimeError("ffmpeg 提取失败: %s" % result.stderr.decode("utf-8", "replace")[:200])
    return Image.open(FRAME).convert("RGBA")


def build_icon(image, head_only=False, prefix="icon"):
    box = content_box(image)
    if box is None:
        raise RuntimeError("这一帧没有任何达到阈值的像素（alpha 阈值 %d）" % ALPHA_MIN)

    if head_only:
        # 头部特写：小尺寸图标里全身像必然很小，头肩特写才看得清。
        # 从角色顶部往下取 PART 比例的高度。这个值是看效果调的，不是算出来的：
        # 0.52 时下巴会被切掉，0.70 才能把整张脸和肩颈一起收进来。
        part = 0.70
        box = (box[0], box[1], box[2], box[1] + max(1, int((box[3] - box[1]) * part)))

    cropped = image.crop(box)
    print("  %s 裁切后角色尺寸: %s（原图 %s）" % (prefix, cropped.size, image.size))

    # 放大的同时保持长宽比：短边决定整体缩放，长边居中
    side = int(round(max(cropped.size) / FILL))
    scale = side / float(max(cropped.size))
    scaled = cropped.resize(
        (max(1, int(round(cropped.width * scale))), max(1, int(round(cropped.height * scale)))),
        Image.LANCZOS)

    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(scaled, ((side - scaled.width) // 2, (side - scaled.height) // 2), scaled)

    # 统一到 256，再导出多档
    master = canvas.resize((256, 256), Image.LANCZOS)
    master.save(os.path.join(ASSETS, "%s.png" % prefix), "PNG")
    master.save(os.path.join(ASSETS, "%s.ico" % prefix), sizes=SIZES)

    box2 = content_box(master)
    if box2:
        print("  %s 角色占画布: %.0f%% 宽 / %.0f%% 高"
              % (prefix, 100.0 * (box2[2] - box2[0]) / 256.0,
                 100.0 * (box2[3] - box2[1]) / 256.0))
    return master


def main():
    if not os.path.exists(SOURCE):
        print("找不到素材: %s" % SOURCE)
        return 1
    image = extract_frame()
    # 正式图标：全身像（信息完整）
    build_icon(image, head_only=False, prefix="icon")
    # 备选图标：头肩特写（小尺寸下更大更清楚）——供对比选择
    build_icon(image, head_only=True, prefix="icon-head")
    os.remove(FRAME)

    # 对比图：把两种构图在真实显示尺寸下并排画出来
    full = Image.open(os.path.join(ASSETS, "icon.png")).convert("RGBA")
    head = Image.open(os.path.join(ASSETS, "icon-head.png")).convert("RGBA")
    rows = [(256, 64, 48, 32, 16)]
    sheet = Image.new("RGB", (470, 300), (58, 62, 74))
    for row, name, src in ((0, "全身", full), (1, "头肩", head)):
        x = 0
        for size in rows[0]:
            tile = src.resize((size, size), Image.LANCZOS)
            sheet.paste(tile, (x, row * 150 + (140 - size)), tile)
            x += size + 10
    sheet.save(os.path.join(ROOT, "logs", "icon-compare.png"))
    print("  已生成 assets/icon.*（全身）与 assets/icon-head.*（头肩）")
    print("  对比图: logs/icon-compare.png（上=全身，下=头肩）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
