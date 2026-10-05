# -*- coding: utf-8 -*-
"""把高分辨率样片**几何归一化**后装进桌宠，供实机对照。

为什么必须先归一化
------------------
上游的链路里还有一步 `normalize_step03.py`：把角色统一成「站立高 900 / 画布
2160x1215 / 脚底距底 100 / 水平居中」，再缩 3.375 倍发布成 640x360。我们的样片
**跳过了这一步**，于是角色比最终形态大 6%、高 22 像素。直接装进去，你看到的是
"角色变大了"，而不是"分辨率变高了" —— 那就白比了。

做法（数据驱动，不去猜上游的站立帧判定）
--------------------------------------
   现有帧的角色并集包围盒 (X0,Y0,X1,Y1)     <- frames/<动画>/
   样片的角色并集包围盒 (x0,y0,x1,y1)       <- hires/<动画>/
   缩放比 s = 2 * (Y1-Y0+1) / (y1-y0+1)     <- 让高清版的角色高度正好是现有的 2 倍
   平移    使高清版的包围盒**中心与底边**落在现有包围盒的 2 倍位置上
   画布 1280x720（即现有 640x360 的 2 倍）

结果：装进去的那 241 帧，除了"分辨率是 2 倍"以外，角色的大小与站位与现有素材
**逐像素对齐**。重启桌宠后把 size 调到 640，就能看到"同样构图、两倍分辨率"的真实差别。

    python tools/install_hires_demo.py 东张西望
    python tools/install_hires_demo.py 东张西望 --remove   # 卸载
"""

import os
import shutil
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HIRES_ROOT = r"E:\dsh\_src\hires"
SUFFIX = "-高清"
CANVAS = (1280, 720)


def union_bbox(folder, step=4, threshold=16):
    import numpy as np
    from PIL import Image
    left = top = 10 ** 9
    right = bottom = -1
    entries = sorted(f for f in os.listdir(folder) if f.endswith(".png"))
    for entry in entries[::step]:
        with Image.open(os.path.join(folder, entry)) as raw:
            alpha = np.asarray(raw.convert("RGBA").getchannel("A"))
        ys, xs = np.where(alpha > threshold)
        if not len(xs):
            continue
        left = min(left, int(xs.min()))
        top = min(top, int(ys.min()))
        right = max(right, int(xs.max()))
        bottom = max(bottom, int(ys.max()))
    if right < 0:
        return None
    return (left, top, right, bottom)


def main():
    argv = sys.argv[1:]
    animation = argv[0] if argv and not argv[0].startswith("-") else "东张西望"
    target = os.path.join(ROOT, "frames", animation + SUFFIX)
    if "--remove" in argv:
        if os.path.isdir(target):
            shutil.rmtree(target)
            print("  已卸载 %s" % os.path.relpath(target, ROOT))
        else:
            print("  本来就不存在: %s" % os.path.relpath(target, ROOT))
        return 0

    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        print("  需要 numpy + Pillow")
        return 1

    old_dir = os.path.join(ROOT, "frames", animation)
    new_dir = os.path.join(HIRES_ROOT, animation)
    for path in (old_dir, new_dir):
        if not os.path.isdir(path):
            print("  缺目录: %s" % path)
            return 1

    print()
    print("  几何归一化并安装: %s%s" % (animation, SUFFIX))
    print("  " + "=" * 68)

    old_box = union_bbox(old_dir)
    new_box = union_bbox(new_dir)
    print("  现有帧并集包围盒: x %d..%d  y %d..%d  (%dx%d)"
          % (old_box[0], old_box[2], old_box[1], old_box[3],
             old_box[2] - old_box[0] + 1, old_box[3] - old_box[1] + 1))
    print("  样片并集包围盒  : x %d..%d  y %d..%d  (%dx%d)"
          % (new_box[0], new_box[2], new_box[1], new_box[3],
             new_box[2] - new_box[0] + 1, new_box[3] - new_box[1] + 1))

    old_h = old_box[3] - old_box[1] + 1
    new_h = new_box[3] - new_box[1] + 1
    scale = 2.0 * old_h / new_h
    print("  目标：角色高度 = 现有的 2 倍（%d -> %d）  缩放比 %.4f"
          % (old_h, old_h * 2, scale))

    # 现有包围盒的 2 倍位置（目标画布 1280x720）
    target_cx = (old_box[0] + old_box[2] + 1) * 1.0        # 现有中心的 2 倍
    target_bottom = (old_box[3] + 1) * 2.0                 # 现有底边的 2 倍
    print("  目标：角色中心 x=%.0f   底边 y=%.0f（画布 %dx%d）"
          % (target_cx, target_bottom, CANVAS[0], CANVAS[1]))

    if os.path.isdir(target):
        shutil.rmtree(target)
    os.makedirs(target)

    entries = sorted(f for f in os.listdir(new_dir) if f.endswith(".png"))
    for entry in entries:
        with Image.open(os.path.join(new_dir, entry)) as raw:
            image = raw.convert("RGBA")
        scaled = image.resize((max(1, int(round(image.width * scale))),
                               max(1, int(round(image.height * scale)))),
                              Image.LANCZOS)
        # 缩放后样片的包围盒位置
        sx0 = int(round(new_box[0] * scale))
        sy1 = int(round((new_box[3] + 1) * scale))
        sx_cx = (new_box[0] + new_box[2] + 1) / 2.0 * scale
        dx = int(round(target_cx - sx_cx))
        dy = int(round(target_bottom - sy1))

        # **用 numpy 直接放置，不要用 Image.paste(mask=...)**
        # paste 到全透明画布上时，alpha=0 的位置结果会被写成 (0,0,0,0) ——
        # 也就是把 alpha bleed 好不容易填好的透明区 RGB 又抹成黑色，
        # 于是缩放时边缘被插值成暗色（实测边缘均色 65 -> 26）。
        # 直接赋值能把透明区的 RGB 一并带过来。
        source = np.asarray(scaled)
        canvas = np.zeros((CANVAS[1], CANVAS[0], 4), np.uint8)
        sh, sw = source.shape[0], source.shape[1]
        # 目标区域与画布求交（允许负偏移/超出）
        x0, y0 = max(0, dx), max(0, dy)
        x1, y1 = min(CANVAS[0], dx + sw), min(CANVAS[1], dy + sh)
        if x1 > x0 and y1 > y0:
            canvas[y0:y1, x0:x1] = source[y0 - dy:y1 - dy, x0 - dx:x1 - dx]
        Image.fromarray(canvas, "RGBA").save(os.path.join(target, entry),
                                             "PNG", optimize=True)

    total = sum(os.path.getsize(os.path.join(target, f)) for f in os.listdir(target))
    print()
    print("  已安装 %d 帧 -> %s" % (len(entries), os.path.relpath(target, ROOT)))
    print("  体积 %.1f MB（单帧平均 %.0f KB）"
          % (total / 1048576.0, total / 1024.0 / max(1, len(entries))))

    # 复核：装好之后包围盒是否真的是现有的 2 倍
    check = union_bbox(target, threshold=16)
    print()
    print("  复核")
    print("  " + "-" * 68)
    print("  期望包围盒: x %.0f..%.0f  y %.0f..%.0f"
          % (old_box[0] * 2, (old_box[2] + 1) * 2 - 1,
             old_box[1] * 2, (old_box[3] + 1) * 2 - 1))
    print("  实际包围盒: x %d..%d  y %d..%d"
          % (check[0], check[2], check[1], check[3]))
    dev = max(abs(check[0] - old_box[0] * 2), abs(check[1] - old_box[1] * 2),
              abs(check[2] - ((old_box[2] + 1) * 2 - 1)),
              abs(check[3] - ((old_box[3] + 1) * 2 - 1)))
    print("  最大偏差: %d 像素  %s" % (dev, "OK" if dev <= 3 else "**偏大，需要检查**"))
    print()
    print("  下一步：")
    print("     1. 把 config.jsonc 的 size 从 320 调到 640（让宠物以 1:1 显示这幅大图）")
    print("     2. 重启桌宠")
    print("     3. 播这个名字看效果：  POST /anim  {\"name\": \"%s\"}" % (animation + SUFFIX))
    print("     4. 想对比原版就播：    POST /anim  {\"name\": \"%s\"}" % animation)
    return 0


if __name__ == "__main__":
    sys.exit(main())
