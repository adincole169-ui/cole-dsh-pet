# -*- coding: utf-8 -*-
"""生成表情包：用**角色自己的脸**，而不是外挂的占位圆脸。

为什么换：原来的 `memes/*.png` 是用 Qt 画的彩色圆底 + 符号 + 文字，画风和角色完全
不搭（用户原话"换成更贴合的"）。角色本人的立绘就在素材里，直接裁头肩特写即可。

裁切要点：素材是 640×360 的横图，角色站在中间。"头肩"大约是**角色高度的 62%**，
以角色水平中心为准的方形区域。这个比例是看效果调的——45% 会切到头顶，78% 会把
围裙也卷进来。

    python tools/make_memes.py
"""

import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "memes")
sys.path.insert(0, HERE)

# 判定"实心"的 alpha 阈值（这套素材的透明是低 alpha，不能用 0）
ALPHA_MIN = 16
# 裁切框用**固定的参考构型**（待机帧）来定，而不是逐帧各算一次。
# 逐帧算的坑：像"原地小憩沉眠"这种角色躺下的动画，包围盒和站姿差得很远，按比例算出来
# 的框会把脸切到边上（实测八张里三张是歪的）。统一用站姿的框，只换表情。
REFERENCE_ANIMATION = "待机呼吸休闲"
# 角色在方框里占的比例（0.92 = 四周留一点边）
CONTENT_FILL = 0.92
# 输出边长：气泡里画成约 40px，96 足够清晰又不占体积
SIZE = 96

# (表情名, 取帧的动画, 取第几帧, 额外偏移(右,下))
# 偏移只给"角色在该动画里站位与待机不同"的几项——统一裁切框保证了构图一致，但个别
# 动作（回头、躺下）本身就不在待机的站位上，需要单独挪一下，否则脸会切到边上。
MEMES = [
    ("开心", "点击回应-开心跃动", 40, (0, 0)),
    ("害羞", "点击回应-害羞惊讶", 40, (0, 0)),
    ("生气", "点击回应-傲娇生气", 40, (58, 12)),
    ("笑", "点击回应-挠痒咯咯笑", 40, (0, 0)),
    ("挥手", "点击回应-元气挥手", 40, (0, 0)),
    # 帧号是挑过的：`工作状态-垂头叹气冒汗` 从第 60 帧起画师会叠一个**红叉失败标记**，
    # 所以取第 30 帧（同一个表情，没有那个标记）。
    ("无语", "工作状态-垂头叹气冒汗", 30, (18, 0)),
    ("得意", "工作状态-雀跃庆祝", 40, (0, 0)),
    ("困", "原地小憩沉眠", 60, (86, 18)),
]


def frames_of(animation):
    """取一个动画的已解码帧路径（需要时先解码）。"""
    import asset_pipeline as ap
    if not ap.is_cached(animation):
        ap.build(animation)
    return ap.cached_frames(animation)


def content_box(image):
    """按 alpha **阈值**求角色包围盒（不能用 `getbbox()` 的默认阈值 0）。"""
    probe = image.resize((160, max(1, int(image.height * 160 / float(image.width)))),
                         Image.NEAREST)
    box = probe.getchannel("A").point(lambda v: 255 if v > ALPHA_MIN else 0).getbbox()
    if box is None:
        return None
    scale = image.width / float(probe.width)
    return (int(box[0] * scale), int(box[1] * scale),
            int(box[2] * scale), int(box[3] * scale))


def face_box(image):
    """给出一个**统一尺寸的方形裁切框**，内容为角色全身（不裁脸）。

    为什么不做脸部裁切：试过三种定位方式都不稳——固定框 + 手调偏移（八张里三张歪）、
    按包围盒比例切（切到头顶）、按最暗像素找眼睛（回头/躺下的帧找不到）。
    根因是**各动画里角色的站位与姿态差别很大**，任何"按比例推脸"的做法都会漏。

    改成"整只角色装进方框"：构图永远不歪，可动作本身就是表情（挥手、雀跃、趴睡都
    看得懂），而且缩到 96px 依然清楚。`CONTENT_FILL` 控制角色占方框的比例。
    """
    box = content_box(image)
    if box is None:
        return None
    left, top, right, bottom = box
    side = max(8, int(max(right - left, bottom - top) / CONTENT_FILL))
    centre_x = (left + right) // 2
    centre_y = (top + bottom) // 2
    x0 = max(0, min(image.width - side, centre_x - side // 2))
    y0 = max(0, min(image.height - side, centre_y - side // 2))
    # 再夹一次：`min(image.height - side, ...)` 在 side 大于图片高度时会给出负数，
    # 那会让 crop 越界（实测出现过一个红叉占位图）。
    x0 = max(0, x0)
    y0 = max(0, y0)
    x1 = min(image.width, x0 + side)
    y1 = min(image.height, y0 + side)
    return (x0, y0, x1, y1)


def reference_box():
    """参考框仅用于打日志对比；实际裁切由 `face_box` 自动定位。"""
    paths = frames_of(REFERENCE_ANIMATION)
    with Image.open(paths[0]) as raw:
        return face_box(raw.convert("RGBA"))


def main():
    os.makedirs(OUT, exist_ok=True)
    box = reference_box()
    if box is None:
        print("算不出参考裁切框，中止")
        return 1
    print("  统一裁切框: %s（边长 %d）" % (box, box[2] - box[0]))

    made = []
    for name, animation, index, _nudge in MEMES:
        try:
            paths = frames_of(animation)
        except Exception as error:
            print("  跳过 %s（%s）" % (name, error))
            continue
        if not paths:
            print("  跳过 %s（没有帧）" % name)
            continue
        path = paths[min(index, len(paths) - 1)]
        with Image.open(path) as raw:
            image = raw.convert("RGBA")
        # 每张图**自己定位脸**，不再用固定框 + 手调偏移（那样一张张试不完）
        crop = face_box(image)
        if crop is None:
            print("  跳过 %s（定位不到脸）" % name)
            continue
        image.crop(crop).resize((SIZE, SIZE), Image.LANCZOS).save(
            os.path.join(OUT, "%s.png" % name), "PNG")
        made.append(name)
        print("  %-6s <- %-22s[%3d]  框=%s" % (name, animation, index, crop))

    # 清掉不再使用的旧占位图（它们是彩色圆脸，与角色画风不搭）
    keep = {("%s.png" % name) for name in made}
    for entry in sorted(os.listdir(OUT)):
        if entry.endswith(".png") and entry not in keep:
            os.remove(os.path.join(OUT, entry))
            print("  删除旧图 %s" % entry)

    if made:
        # 只拼图、不写文字：PIL 的默认字体不支持中文，而在图里画标签不是重点
        # （名字按顺序就是 MEMES 的顺序）。
        sheet = Image.new("RGB", (len(made) * (SIZE + 8), SIZE), (40, 44, 56))
        for i, name in enumerate(made):
            with Image.open(os.path.join(OUT, "%s.png" % name)) as face:
                tile = face.convert("RGBA")
            sheet.paste(tile, (i * (SIZE + 8), 0), tile)
        sheet.save(os.path.join(ROOT, "logs", "memes.png"))
        print("  对比图: logs/memes.png（顺序: %s）" % " / ".join(made))
    print("共生成 %d 张表情包" % len(made))
    return 0 if made else 1


if __name__ == "__main__":
    sys.exit(main())
