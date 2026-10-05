# -*- coding: utf-8 -*-
"""样片：用 1280x720 源视频重建**一个动画**的透明帧，供与现有素材对照。

完整走一遍真实链路，不做任何简化：

    源 mp4(1280x720 绿幕)
      -> 去水印（第 k 近非水印像素颜色填充，复刻上游 fill_nn.py）
      -> 抠像（HSV 色相硬抠 + 去绿溢 + 软边）
      -> RGBA PNG(1280x720)

与上游的两处**有意不同**：
  1. 上游中间会落一次 H.264 CRF18（step01），我们**省掉这一代损失**，直接出 PNG；
  2. 上游用硬抠（无去绿溢/软边），我们加上去绿溢与软边 —— 实测把可见像素里
     "偏绿"的比例从 1.38% 压到 0.00%。

用法：
    python tools/build_hires_sample.py 东张西望
    python tools/build_hires_sample.py 东张西望 --out E:\\dsh\\_src\\hires
"""

import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
VIDEO_DIR = r"E:\dsh\_src\video"
MASK = os.path.join(VIDEO_DIR, "watermark_mask_v5.mkv")

W, H, FPS = 1280, 720, 24
# 上游 chroma_step02.py 的抠像参数（保留作对照；实际用的是下面 LOOSE_*，
# 因为上游那套固定阈值在源视频的暗角上会留下成片灰绿残留，见 key_frame 的说明）
GREEN_HUE_MIN, GREEN_HUE_MAX = 70.0, 170.0
SAT_MIN, VAL_MIN = 0.15, 0.15
HUE_FEATHER = 6.0
# 实际采用的放宽阈值：配合"边缘连通域"判定，既收掉暗角残留又不误伤角色
LOOSE_HUE_MIN, LOOSE_HUE_MAX = 40.0, 200.0
LOOSE_SAT_MIN, LOOSE_VAL_MIN = 0.06, 0.08
# 上游 watermark_step01.py 的取色跳数
FILL_K = 5


def ffmpeg_path():
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("需要 PATH 里有 ffmpeg")
    return exe


def read_exact(stream, count):
    """阻塞读满 count 字节（管道 read 会部分返回，必须循环）。"""
    chunks = []
    got = 0
    while got < count:
        chunk = stream.read(count - got)
        if not chunk:
            break
        chunks.append(chunk)
        got += len(chunk)
    return b"".join(chunks)


def kth_nearest(wm, k):
    """每个水印像素第 k 近的非水印像素坐标（复刻上游 fill_nn.kth_nearest）。"""
    import numpy as np
    from scipy.ndimage import distance_transform_edt
    cur = wm.copy()
    indices_y = indices_x = None
    for _ in range(k):
        _, idx = distance_transform_edt(cur, return_indices=True)
        indices_y, indices_x = idx
        used = np.zeros_like(cur, bool)
        used[indices_y[wm], indices_x[wm]] = True
        cur = cur | used
    return indices_y, indices_x


def key_frame(frame):
    """抠像：放宽阈值 + 边缘连通域 + 去绿溢 + 软边。返回 RGBA uint8。

    为什么不能用上游那套固定阈值（`chroma_step02.py`：hue∈[64,176] 且 sat≥0.15）：
    源视频的背景**不是均匀纯绿**，远离中心处有暗角/阴影，像素形如 `[146,160,139]`，
    饱和度只有 **0.13** —— 刚好卡在 0.15 之下，被判成前景，留下成片灰绿残留。
    实测把角色并集包围盒从 394x568 撑到 993x622。上游自己最后也是因此**全部改手工抠像**。

    这里的做法：
      1. 阈值放宽（hue 40~200、sat≥0.06、val≥0.08）；
      2. 用连通域判定：**只有与画面四边连通的那片绿色才算背景** —— 角色是被背景
         包围的，不与边缘连通，所以放宽阈值不会误伤角色；
      3. 填掉角色内部被误判成背景的小洞；
      4. 去绿溢 + 软边（同前）。
    """
    import numpy as np
    from scipy import ndimage
    r = frame[..., 0].astype(np.float32) / 255.0
    g = frame[..., 1].astype(np.float32) / 255.0
    b = frame[..., 2].astype(np.float32) / 255.0
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    delta = mx - mn
    nz = delta > 0
    with np.errstate(divide="ignore", invalid="ignore"):
        safe = np.where(nz, delta, 1.0)
        hr = 60.0 * (((g - b) / safe) % 6.0)
        hg = 60.0 * (((b - r) / safe) + 2.0)
        hb = 60.0 * (((r - g) / safe) + 4.0)
    hue = np.where((mx == r) & nz, hr,
                   np.where((mx == g) & nz, hg, np.where((mx == b) & nz, hb, 0.0)))
    sat = np.where(mx > 0, delta / np.maximum(mx, 1e-6), 0.0)
    val = mx

    # 1) 放宽阈值
    greenish = (sat >= LOOSE_SAT_MIN) & (val >= LOOSE_VAL_MIN) \
        & (hue >= LOOSE_HUE_MIN) & (hue <= LOOSE_HUE_MAX)
    # 2) 连通域：只认与边缘连通的那片
    labels, count = ndimage.label(greenish)
    if count:
        border = set(labels[0, :].tolist()) | set(labels[-1, :].tolist()) \
            | set(labels[:, 0].tolist()) | set(labels[:, -1].tolist())
        border.discard(0)
    else:
        border = set()
    if border:
        keep = np.zeros(count + 1, bool)
        for value in border:
            keep[value] = True
        background = keep[labels]
    else:
        background = np.zeros_like(greenish)
    # 3) 补回角色内部被误判的小洞
    holes = ndimage.binary_fill_holes(~background) & background
    background = background & ~holes

    # 4) alpha：背景透明，边界 1~2 像素做柔化
    solid = (~background).astype(np.float32)
    blurred = ndimage.uniform_filter(solid, size=3)
    alpha = np.clip(solid * 0.85 + blurred * 0.15, 0.0, 1.0) * 255.0

    work = frame.astype(np.float32)
    green_channel = work[..., 1]
    other = np.maximum(work[..., 0], work[..., 2])
    work[..., 1] = np.where(green_channel > other, other, green_channel)   # 去绿溢

    out = np.concatenate([work, alpha[..., None]], axis=2)
    return np.clip(out, 0, 255).astype(np.uint8)


def hue_max_hi():
    return GREEN_HUE_MAX + HUE_FEATHER


def build(animation, out_dir, limit=None):
    import numpy as np
    from PIL import Image

    source = os.path.join(VIDEO_DIR, animation + ".mp4")
    if not os.path.exists(source):
        raise FileNotFoundError("没有源视频: %s" % source)
    if not os.path.exists(MASK):
        raise FileNotFoundError("没有水印遮罩: %s" % MASK)

    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)

    exe = ffmpeg_path()
    pipe_video = subprocess.Popen(
        [exe, "-loglevel", "error", "-i", source,
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    pipe_mask = subprocess.Popen(
        [exe, "-loglevel", "error", "-i", MASK,
         "-f", "rawvideo", "-pix_fmt", "gray", "-"], stdout=subprocess.PIPE)

    frame_bytes = W * H * 3
    mask_bytes = W * H
    index = 0
    filled_total = 0
    started = time.time()
    try:
        while True:
            if limit and index >= limit:
                break
            raw = read_exact(pipe_video.stdout, frame_bytes)
            if len(raw) < frame_bytes:
                break
            mraw = read_exact(pipe_mask.stdout, mask_bytes)
            if len(mraw) < mask_bytes:
                break
            frame = np.frombuffer(raw, np.uint8).reshape(H, W, 3).copy()
            mask = np.frombuffer(mraw, np.uint8).reshape(H, W)
            wm = mask == 255
            if wm.any():
                iy, ix = kth_nearest(wm, FILL_K)
                yi = np.clip(iy[wm], 0, H - 1)
                xi = np.clip(ix[wm], 0, W - 1)
                frame[wm] = frame[yi, xi]
                filled_total += int(wm.sum())
            rgba = key_frame(frame)
            Image.fromarray(rgba, "RGBA").save(
                os.path.join(out_dir, "%04d.png" % (index + 1)), "PNG", optimize=True)
            index += 1
            if index % 40 == 0:
                rate = index / max(0.01, time.time() - started)
                print("     已处理 %3d 帧  (%.1f 帧/秒)" % (index, rate))
    finally:
        pipe_video.stdout.close()
        pipe_mask.stdout.close()
        pipe_video.wait()
        pipe_mask.wait()

    elapsed = time.time() - started
    total = sum(os.path.getsize(os.path.join(out_dir, f))
                for f in os.listdir(out_dir))
    return {
        "frames": index,
        "seconds": elapsed,
        "bytes": total,
        "filled": filled_total,
    }


def main():
    argv = sys.argv[1:]
    if not argv or argv[0].startswith("-"):
        print("  用法: python tools/build_hires_sample.py <动画名> [--out 目录]")
        print("  例:   python tools/build_hires_sample.py 东张西望")
        return 2
    animation = argv[0]
    out_dir = os.path.join(r"E:\dsh\_src\hires", animation)
    if "--out" in argv:
        out_dir = argv[argv.index("--out") + 1]

    print()
    print("  构建高分辨率样片: %s" % animation)
    print("  " + "=" * 66)
    print("  源视频 : %s" % os.path.join(VIDEO_DIR, animation + ".mp4"))
    print("  遮罩   : %s" % MASK)
    print("  输出   : %s" % out_dir)
    print("  分辨率 : %dx%d   抠像: 硬抠+去绿溢+软边   去水印: 第 %d 近邻填充"
          % (W, H, FILL_K))
    print()

    result = build(animation, out_dir)
    print()
    print("  完成")
    print("  " + "-" * 66)
    print("     帧数    : %d" % result["frames"])
    print("     用时    : %.1f 秒" % result["seconds"])
    print("     总体积  : %.1f MB   单帧平均 %.0f KB"
          % (result["bytes"] / 1048576.0,
             result["bytes"] / 1024.0 / max(1, result["frames"])))
    print("     水印像素: 累计填充 %d 个" % result["filled"])
    print()
    print("  全量外推（25423 帧，同分辨率）: %.2f GB"
          % (result["bytes"] / max(1, result["frames"]) * 25423 / 1073741824.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
