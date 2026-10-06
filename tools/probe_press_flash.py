# -*- coding: utf-8 -*-
"""探针：按下 / 松开的那一瞬间，画面到底"没东西"还是"半透明"？

用户报："鼠标左键点下去的时候会消失一瞬，松开的时候也会。"

两个候选原因，本探针直接量：

  A. **真的没帧**：`Animator.current_frame()` 返回 None → 窗口什么都不画 = 彻底消失；
  B. **透明度≈0 且没有垫层**：`fade_alpha()` 从 0 起淡入，而 `playing.outgoing`（上一段
     的最后一帧）是 None → 整帧透明 = 看起来也是"消失一瞬"。

还要量一下按下时的**位置跳动**（换动画会让 `character_insets()` 变化）：

  C. 按下/松开前后 `pos_x` 有没有被搬走（用户报的"到边缘往里闪"）。

    python tools/probe_press_flash.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main():
    from PyQt5.QtCore import QEvent, QPoint, Qt
    from PyQt5.QtGui import QMouseEvent

    from config import load, pet_configs
    from frames import FrameStore
    from main import build_app
    from pet import PetWindow

    app = build_app([sys.argv[0]])
    pet_config = pet_configs(load())[0]
    store = FrameStore(keep=6)
    window = PetWindow(pet_config, store)
    window.show()

    # **必须等动画真的加载完**（流式解码在后台线程里跑，需要真实时间）。
    # 第一版只 `processEvents()` 了 200 次（几乎不耗时），动画还停在"加载中"，
    # 于是每个采样都是 "无帧" —— 那是**测法的产物**，不是缺陷。
    wanted = list(pet_config.actions("drag") or []) + list(pet_config.actions("idle") or [])
    for name in wanted:
        store.request(name)
    import time as _time
    deadline = _time.time() + 20
    while _time.time() < deadline:
        app.processEvents()
        if wanted and all(store.has(n) for n in wanted):
            break
        _time.sleep(0.05)
    app.processEvents()
    missing = [n for n in wanted if not store.has(n)]
    print()
    print("  预热：%d/%d 个动画已加载%s"
          % (len(wanted) - len(missing), len(wanted),
             ("（缺：%s）" % "、".join(missing[:3])) if missing else ""))

    def mouse(kind, pos):
        return QMouseEvent(kind, QPoint(*pos), QPoint(*pos), Qt.LeftButton,
                           Qt.LeftButton, Qt.NoModifier)

    def sample(tag, log):
        anim = window.animator
        playing = anim.playing
        frame = anim.current_frame()
        log.append({
            "tag": tag,
            "anim": playing.name if playing else None,
            "ready": bool(playing.ready) if playing else False,
            "frame_none": frame is None,
            "alpha": anim.fade_alpha(),
            "outgoing_none": (playing.outgoing is None) if playing else True,
            "x": window.pos_x,
        })

    centre = (window.width() // 2, window.height() // 2)
    print()
    print("  探针：按下 / 松开瞬间的画面与位置")
    print("  " + "=" * 74)

    # --- 按下 --- #
    log = []
    sample("按下前", log)
    window.mousePressEvent(mouse(QEvent.MouseButtonPress, centre))
    sample("按下瞬间", log)
    for i in range(6):
        app.processEvents()
        sample("按下后+%d帧" % (i + 1), log)

    # --- 拖动一小段 --- #
    for i in range(6):
        window.mouseMoveEvent(mouse(QEvent.MouseMove, (centre[0] + 20 * i,
                                                       centre[1])))
    # --- 松开 --- #
    sample("松开前", log)
    window.mouseReleaseEvent(mouse(QEvent.MouseButtonRelease, (centre[0] + 120,
                                                              centre[1])))
    sample("松开瞬间", log)
    for i in range(6):
        app.processEvents()
        sample("松开后+%d帧" % (i + 1), log)

    print("  %-12s %-22s %6s %7s %7s %10s %8s"
          % ("时刻", "动画", "ready", "无帧", "alpha", "无垫层", "x"))
    for row in log:
        print("  %-12s %-22s %6s %7s %7.2f %10s %8.0f"
              % (row["tag"], str(row["anim"])[:22], row["ready"],
                 "是" if row["frame_none"] else "—", row["alpha"],
                 "是" if row["outgoing_none"] else "—", row["x"]))

    # --- 判定 --- #
    print()
    print("  判定")
    print("  " + "-" * 74)
    problems = []

    no_frame = [r for r in log if r["frame_none"]]
    if no_frame:
        problems.append("有 %d 个采样**完全没有帧**（真消失）：%s"
                        % (len(no_frame), "、".join(r["tag"] for r in no_frame)))
    else:
        print("  OK   全程都有帧可画（不是「真的没东西」）")

    invisible = [r for r in log if r["alpha"] < 0.35 and r["outgoing_none"]]
    if invisible:
        problems.append("有 %d 个采样 alpha<0.35 且**没有垫层**（整帧透明，看起来也是消失）：%s"
                        % (len(invisible), "、".join(r["tag"] for r in invisible)))
    else:
        print("  OK   没有出现「低透明度且无垫层」的情况")

    # --- 位置跳动只在"按下瞬间"与"松开瞬间"量 --- #
    # 拖动本身当然会移动窗口（那是目的），所以**不能**把整段采样的 x 拿来比 ——
    # 第一版就是这么比的，把故意拖的 120 px 报成了"换动画时被搬动"。
    press_x = log[[r["tag"] for r in log].index("按下前")]["x"]
    press_after = log[[r["tag"] for r in log].index("按下后+6帧")]["x"]
    # 拖动阶段的位置变化是预期的，这里只比"按下前后"与"松开前后"
    release_x = log[[r["tag"] for r in log].index("松开前")]["x"]
    release_after = log[[r["tag"] for r in log].index("松开后+6帧")]["x"]
    jump_press = abs(press_after - press_x)
    jump_release = abs(release_after - release_x)
    if max(jump_press, jump_release) > 8:
        problems.append("按下后被搬动 %.0f px、松开后被搬动 %.0f px —— 换动画时位置在跳"
                        % (jump_press, jump_release))
    else:
        print("  OK   按下/松开前后位置稳定（%.0f px / %.0f px）"
              % (jump_press, jump_release))

    window.close()
    store.close()

    print()
    if problems:
        for item in problems:
            print("     [问题] %s" % item)
        return 1
    print("  结论：按下/松开没有量到「消失」或位置跳动。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
