# -*- coding: utf-8 -*-
"""改进抠像：把"灰绿背景残留"也去掉。

问题（实测）
-----------
上游 `chroma_step02.py` 的判据是 HSV：hue∈[64,176] 且 **sat≥0.15** 且 val≥0.15
就判为背景。但源视频的背景**不是均匀的纯绿**：远离中心处有暗角/阴影，
像素长这样 —— `[146,160,139]`，饱和度只有 **0.13**，刚好卡在阈值下，
于是被判成"前景"，留下成片的灰绿残留。实测残留占不透明像素的 1%~5%，
把角色并集包围盒从 394x568 撑到 993x622。

这也解释了上游为什么最终**全部改手工抠像**：他们的自动路线同样有这毛病。

改进思路
--------
阈值放松（hue 放宽、sat 降到 0.06）+ **连通域判定**：

    背景 = 「绿相且低饱和」**且** 与画面边缘连通的那一片
    前景 = 其余（角色是**被背景包围**的，不与边缘连通）

这样既能收掉暗角残留，又不会误伤角色身上偶尔出现的灰绿（例如深色阴影里
混进一点绿）。这一步用 `scipy.ndimage.label` 做，很快。

    python tools/probe_key_v2.py 东张西望      # 抽出几帧做对照
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
VIDEO_DIR = r"E:\dsh\_src\video"
MASK = os.path.join(VIDEO_DIR, "watermark_mask_v5.mkv")
W, H = 1280, 720
OUT = os.path.join(ROOT, "logs", "key-v2-compare.png")

# 上游参数（用于对照）
V1_HUE = (64.0, 176.0)
V1_SAT, V1_VAL = 0.15, 0.15
# 改进参数：色相放宽，饱和度大幅降低，交给连通域去挡误伤
V2_HUE = (40.0, 200.0)
V2_SAT, V2_VAL = 0.06, 0.08


def ffmpeg_path():
    import shutil
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("需要 PATH 里有 ffmpeg")
    return exe


def read_frame(index):
    import numpy as np
    done = subprocess.run(
        [ffmpeg_path(), "-v", "error", "-i", os.path.join(VIDEO_DIR, "东张西望.mp4"),
         "-vf", "select=eq(n\\,%d)" % index, "-vsync", "0", "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    return np.frombuffer(done.stdout[:W * H * 3], np.uint8).reshape(H, W, 3).astype(np.int16)


def hsv(frame):
    import numpy as np
    f = frame.astype(np.float32) / 255.0
    r, g, b = f[..., 0], f[..., 1], f[..., 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    delta = mx - mn
    nz = delta > 0
    with np.errstate(divide="ignore", invalid="ignore"):
        safe = np.where(nz, delta, 1.0)
        hr = 60.0 * (((g - b) / safe) % 6.0)
        hg = 60.0 * (((b - r) / safe) + 2.0)
        hb = 60.0 * (((r - g) / safe) + 4.0)
    hue = np.where((mx == r) & nz, hr, np.where((mx == g) & nz, hg,
                                                np.where((mx == b) & nz, hb, 0.0)))
    sat = np.where(mx > 0, delta / np.maximum(mx, 1e-6), 0.0)
    return hue, sat, mx


def key_v1(frame):
    import numpy as np
    hue, sat, val = hsv(frame)
    return (sat >= V1_SAT) & (val >= V1_VAL) & (hue >= V1_HUE[0]) & (hue <= V1_HUE[1])


def key_v2(frame):
    """放宽阈值 + 只把"与边缘连通"的那片判为背景。"""
    import numpy as np
    from scipy import ndimage
    hue, sat, val = hsv(frame)
    greenish = (sat >= V2_SAT) & (val >= V2_VAL) & (hue >= V2_HUE[0]) & (hue <= V2_HUE[1])
    labels, count = ndimage.label(greenish)
    if count == 0:
        return np.zeros_like(greenish)
    # 找出与画面四边接触的连通域 —— 那些才是背景
    border = set(labels[0, :].tolist()) | set(labels[-1, :].tolist()) \
        | set(labels[:, 0].tolist()) | set(labels[:, -1].tolist())
    border.discard(0)
    if not border:
        return np.zeros_like(greenish)
    keep = np.zeros(count + 1, bool)
    for value in border:
        keep[value] = True
    background = keep[labels]
    # 填掉角色内部的空洞（角色是实心的，误判成背景的小洞要补回来）
    filled = ndimage.binary_fill_holes(~background) & background
    return background & ~filled


def stats(mask, label):
    import numpy as np
    ys, xs = np.where(~mask)          # 非背景 = 前景
    if not len(xs):
        print("  %-6s 前景为空" % label)
        return
    print("  %-6s 背景占比 %5.1f%%   前景包围盒 x %d..%d  y %d..%d  (%dx%d)"
          % (label, 100.0 * mask.sum() / mask.size, xs.min(), xs.max(), ys.min(), ys.max(),
             xs.max() - xs.min() + 1, ys.max() - ys.min() + 1))


def main():
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        print("  需要 numpy + Pillow")
        return 1
    if not os.path.exists(os.path.join(VIDEO_DIR, "东张西望.mp4")):
        print("  找不到源视频")
        return 1

    print()
    print("  抠像 v1（上游阈值）vs v2（放宽 + 边缘连通域）")
    print("  " + "=" * 74)
    tiles = []
    for index in (30, 120, 200):
        frame = read_frame(index)
        m1 = key_v1(frame)
        m2 = key_v2(frame)
        print()
        print("  第 %d 帧" % index)
        stats(m1, "v1")
        stats(m2, "v2")

        # 把前景（角色）涂成原色、背景涂成洋红，方便一眼看出残留
        def render(mask):
            out = np.zeros((H, W, 3), np.uint8)
            out[..., 0] = 200
            out[..., 1] = 40
            out[..., 2] = 160
            fg = ~mask
            out[fg] = np.clip(frame[fg], 0, 255).astype(np.uint8)
            return out

        tiles.append(("第%d帧 v1 上游" % index, render(m1)))
        tiles.append(("第%d帧 v2 改进" % index, render(m2)))

    # 拼图：每行两张，只取画面中间偏右那一片（残留最明显的地方）
    crop = (240, 40, 1240, 700)
    cw, ch = 400, 264
    sheet = Image.new("RGB", (cw * 2 + 30, ch * len(tiles) // 2 + 20), (20, 22, 28))
    for k, (_label, image) in enumerate(tiles):
        row, col = divmod(k, 2)
        tile = Image.fromarray(image).crop(crop).resize((cw, ch), Image.LANCZOS)
        sheet.paste(tile, (10 + col * (cw + 10), 10 + row * ch))
    out = OUT
    sheet.save(out)
    print()
    print("  对照图: %s" % os.path.relpath(out, ROOT))
    print("     每两行一组：上=第N帧上游阈值  下=第N帧改进  左/右为同一帧的两半")
    return 0


if __name__ == "__main__":
    sys.exit(main())
