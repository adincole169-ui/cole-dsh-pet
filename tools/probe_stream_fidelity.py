# -*- coding: utf-8 -*-
"""探针：流式解码**逐帧保真度** —— 修复前后，服务给界面的帧必须一模一样。

用户的要求是"解决内存问题，但**不影响动画播放**"。这句话不能靠推理下结论，
所以这里把"播放"还原成可验证的东西：

  * 对同一段动画、同样的帧号序列，逐个记录**服务出去的帧的像素指纹**；
  * 跑满两圈（这样背压/淘汰都会走到）；
  * 同时记录 `_frames` 条目数与进程 RSS（内存）。

把两次运行的结果存成 JSON 再比对：

    # 修复前
    python tools/probe_stream_fidelity.py before.json
    # 应用修复后
    python tools/probe_stream_fidelity.py after.json
    # 比对
    python tools/probe_stream_fidelity.py --compare before.json after.json

**判据**：`hashes` 必须逐项相同（= 每一帧的像素都一样）。若不同，脚本会指出
第一个不同的帧号，并给出相差的帧数。
"""

import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def frame_hash(pixmap):
    """一帧的像素指纹。优先用 PNG 编码（精确），失败时退回固定网格采样。"""
    try:
        from PyQt5.QtCore import QBuffer, QIODevice
        image = pixmap.toImage()
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        image.save(buf, "PNG")
        data = bytes(buf.data())
        buf.close()
        return hashlib.sha1(data).hexdigest()[:16]
    except Exception:
        # 退回：固定网格采样（够用来发现"帧不一样"，只是不如 PNG 精确）
        image = pixmap.toImage()
        digest = hashlib.sha1()
        width, height = image.width(), image.height()
        for y in range(0, height, max(1, height // 36)):
            for x in range(0, width, max(1, width // 64)):
                digest.update(str(image.pixel(x, y)).encode())
        return digest.hexdigest()[:16]


def rss_mb():
    try:
        import psutil
        return round(psutil.Process().memory_info().rss / 1048576.0, 1)
    except Exception:
        return None


def collect(name, loops=2, pace_ms=6.0):
    from PyQt5.QtWidgets import QApplication
    import stream_frames

    app = QApplication.instance() or QApplication([])      # noqa: F841
    info = stream_frames.webm_info(name)
    if not info:
        raise RuntimeError("拿不到 %s 的元信息" % name)

    anim = stream_frames.StreamAnimation(name, info)
    count = int(info["frames"])

    deadline = time.time() + 10
    while time.time() < deadline and anim.frame(0) is None:
        time.sleep(0.02)

    before_rss = rss_mb()
    hashes = []
    missing = []
    for step in range(count * loops):
        index = step % count
        pixmap = anim.frame(index)
        if pixmap is None:
            missing.append(step)
        else:
            hashes.append(frame_hash(pixmap))
        time.sleep(pace_ms / 1000.0)

    result = {
        "animation": name,
        "frames": count,
        "loops": loops,
        "served": len(hashes),
        "missing": missing[:20],
        "missingCount": len(missing),
        "hashes": hashes,
        "framesHeld": len(getattr(anim, "_frames", {}) or {}),
        "rssBeforeMb": before_rss,
        "rssAfterMb": rss_mb(),
    }
    anim.close()
    time.sleep(0.4)
    return result


def main(argv):
    if "--compare" in argv:
        index = argv.index("--compare")
        left = json.load(open(argv[index + 1], encoding="utf-8"))
        right = json.load(open(argv[index + 2], encoding="utf-8"))
        print()
        print("  逐帧保真度比对")
        print("  " + "=" * 74)
        for label, data in (("以前", left), ("以后", right)):
            print("  %s: 服务 %d 帧、缺 %d 帧、`_frames` %d 条、RSS %s -> %s MB"
                  % (label, data["served"], data["missingCount"],
                     data["framesHeld"], data["rssBeforeMb"], data["rssAfterMb"]))
        print()
        if left["hashes"] == right["hashes"]:
            print("  **每一帧的像素完全一致 ✓** —— 播放没有被影响")
            print("  内存变化: `_frames` %d -> %d 条；RSS 增长 %s -> %s MB"
                  % (left["framesHeld"], right["framesHeld"],
                     round((left["rssAfterMb"] or 0) - (left["rssBeforeMb"] or 0), 1),
                     round((right["rssAfterMb"] or 0) - (right["rssBeforeMb"] or 0), 1)))
            return 0
        common = min(len(left["hashes"]), len(right["hashes"]))
        first = next((i for i in range(common)
                      if left["hashes"][i] != right["hashes"][i]), None)
        diff = sum(1 for i in range(common)
                   if left["hashes"][i] != right["hashes"][i])
        print("  **帧内容不同**：共 %d 帧不同（前 %d 帧里）" % (diff, common))
        if first is not None:
            print("  第一处不同在第 %d 帧（帧号 %d）" % (first, first % left["frames"]))
        return 1

    out = argv[1] if len(argv) > 1 else "stream_fidelity.json"
    import json as _json
    meta_path = os.path.join(ROOT, "webm-meta.json")
    with open(meta_path, encoding="utf-8") as handle:
        meta = _json.load(handle)
    # 挑帧数最多的那个（内存问题在长动画上最明显）
    name = max(meta, key=lambda k: meta[k].get("frames") or 0)

    print()
    print("  流式解码保真度采样：%s" % name)
    print("  " + "=" * 74)
    result = collect(name)
    with open(out, "w", encoding="utf-8") as handle:
        _json.dump(result, handle, ensure_ascii=False)
    print("  帧数 %d，服务 %d 帧，缺 %d 帧" % (result["frames"], result["served"],
                                              result["missingCount"]))
    print("  `_frames` 条目数 %d（帧总数的 %.0f%%）"
          % (result["framesHeld"],
             result["framesHeld"] * 100.0 / max(1, result["frames"])))
    print("  RSS %s -> %s MB" % (result["rssBeforeMb"], result["rssAfterMb"]))
    print("  已写入 %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
