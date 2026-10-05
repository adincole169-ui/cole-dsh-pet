# -*- coding: utf-8 -*-
"""排除"尺度不同"的干扰，验证清晰度提升是否真实。

问题：我先前那个样片**漏了归一化步骤**（上游 normalize_step03.py 会把角色统一成
身高 900/画布 2160x1215/脚底距底 100，再缩 3.375 倍发布）。于是样片里的角色
比最终形态大 6%、高 22 像素 —— 拿它跟现有帧比"谁更锐"是不公平的，因为放大本身
就会增加高频能量。

本脚本做**尺度对齐后**的比较：
  1. 逐帧量出 现有帧 与 新帧 的角色包围盒
  2. 把新帧缩放/平移，使它的角色包围盒与现有帧**对齐**（按高度缩放、按"水平中心 +
     底边"对齐）
  3. 在这个统一尺度下比较两者，并用**高频能量**（拉普拉斯方差）给一个客观数字
  4. 同时保存对齐后的对照图

如果尺度对齐后新帧仍然明显更锐，提升才是真的（来自"没有 VP9 损失 + 没有调色板
量化"），而不是放大带来的错觉。

    python tools/probe_sharpness_aligned.py 东张西望
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
NEW_DIR = r"E:\dsh\_src\hires640\东张西望\raw"
OLD_DIR = os.path.join(ROOT, "frames", "东张西望")
SAMPLES = ["0031.png", "0060.png", "0120.png", "0180.png"]
BACKGROUND = (52, 56, 68)


def bbox(alpha):
    import numpy as np
    ys, xs = np.where(alpha > 16)
    if not len(xs):
        return None
    return (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))


def high_frequency_energy(image):
    """拉普拉斯方差：越大说明高频（细节/边缘）越多。只统计角色可见区域。"""
    import numpy as np
    gray = np.asarray(image.convert("L"), np.float32)
    alpha = np.asarray(image.convert("RGBA").getchannel("A"), np.float32) / 255.0
    # 3x3 拉普拉斯
    kernel = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], np.float32)
    h, w = gray.shape
    out = np.zeros((h - 2, w - 2), np.float32)
    for dy in range(3):
        for dx in range(3):
            weight = kernel[dy, dx]
            if weight:
                out += weight * gray[dy:dy + h - 2, dx:dx + w - 2]
    mask = alpha[1:h - 1, 1:w - 1] > 0.5
    if not mask.any():
        return 0.0
    return float(out[mask].var())


def flatten(image):
    from PIL import Image
    canvas = Image.new("RGB", image.size, BACKGROUND)
    canvas.paste(image, (0, 0), image)
    return canvas


def main():
    argv = sys.argv[1:]
    animation = argv[0] if argv and not argv[0].startswith("-") else "东张西望"
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        print("  需要 numpy + Pillow")
        return 1

    print()
    print("  尺度对齐后的清晰度比较：%s" % animation)
    print("  " + "=" * 72)
    print("  %-10s %-22s %-22s %s" % ("帧", "现有角色盒", "新角色盒(对齐前)", "缩放比"))
    aligned_pairs = []
    for name in SAMPLES:
        old_path = os.path.join(OLD_DIR, name)
        new_path = os.path.join(NEW_DIR, name)
        if not (os.path.exists(old_path) and os.path.exists(new_path)):
            continue
        old = Image.open(old_path).convert("RGBA")
        new = Image.open(new_path).convert("RGBA")
        ob = bbox(np.asarray(old.getchannel("A")))
        nb = bbox(np.asarray(new.getchannel("A")))
        if not ob or not nb:
            continue
        old_h = ob[3] - ob[1] + 1
        new_h = nb[3] - nb[1] + 1
        factor = old_h / float(new_h)
        print("  %-10s %-22s %-22s %.3f"
              % (name, "%d..%d / %d..%d" % (ob[0], ob[2], ob[1], ob[3]),
                 "%d..%d / %d..%d" % (nb[0], nb[2], nb[1], nb[3]), factor))

        # 把新帧缩放，使角色高度与现有帧一致；再平移，使"水平中心 + 底边"对齐
        scaled = new.resize((max(1, int(round(new.width * factor))),
                             max(1, int(round(new.height * factor)))), Image.LANCZOS)
        sb = tuple(int(round(v * factor)) for v in nb)
        old_cx = (ob[0] + ob[2]) / 2.0
        new_cx = (sb[0] + sb[2]) / 2.0
        dx = int(round(old_cx - new_cx))
        dy = ob[3] - sb[3]
        aligned = Image.new("RGBA", old.size, (0, 0, 0, 0))
        aligned.paste(scaled, (dx, dy), scaled)
        aligned_pairs.append((name, old, aligned))

    if not aligned_pairs:
        print("  没有可比较的帧")
        return 1

    print()
    print("  高频能量（拉普拉斯方差，只统计角色不透明区域；越大越锐）")
    print("  " + "-" * 72)
    print("  %-10s %-16s %-16s %s" % ("帧", "现有", "新(尺度对齐)", "提升"))
    ratios = []
    for name, old, aligned in aligned_pairs:
        e_old = high_frequency_energy(old)
        e_new = high_frequency_energy(aligned)
        ratio = e_new / e_old if e_old else 0.0
        ratios.append(ratio)
        print("  %-10s %-16.1f %-16.1f %.2f 倍" % (name, e_old, e_new, ratio))

    average = sum(ratios) / len(ratios)
    print()
    print("  结论")
    print("  " + "=" * 72)
    print("  平均高频能量比: %.2f 倍（尺度已对齐，排除了「放大带来更锐」的错觉）" % average)
    if average >= 1.25:
        print("  **提升是真实的**：即使显示尺寸不变，新素材也明显更锐。")
        print("  来源：摆脱上游的 VP9 CRF32 有损编码 + 摆脱我们自己的 256 色调色板量化。")
    elif average >= 1.08:
        print("  有提升，但幅度中等。")
    else:
        print("  提升不明显 —— 那么「只换素材不改尺寸」不值得做，只有放大显示才有意义。")

    # 对齐后的并排图
    panel_w, panel_h = 360, 202
    zoom = (215, 40, 430, 205)
    zoom_w, zoom_h = 360, 300
    rows = []
    name, old, aligned = aligned_pairs[0]
    rows.append(("现有 640（1:1）", flatten(old)))
    rows.append(("新（尺度对齐到现有）", flatten(aligned)))
    sheet = Image.new("RGB", (panel_w + zoom_w + 40, (panel_h + 26) * len(rows) + 10),
                      (20, 22, 28))
    for k, (_label, image) in enumerate(rows):
        y = 5 + k * (panel_h + 26)
        sheet.paste(image.resize((panel_w, panel_h), Image.LANCZOS), (10, y + 18))
        sheet.paste(image.crop(zoom).resize((zoom_w, zoom_h), Image.NEAREST),
                    (panel_w + 28, y + 18))
    out = os.path.join(ROOT, "logs", "sharpness-aligned.png")
    sheet.save(out)
    print()
    print("  对齐后的对照图: %s（%s，上=现有 下=新）"
          % (os.path.relpath(out, ROOT), name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
