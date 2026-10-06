# -*- coding: utf-8 -*-
"""探针：**动作切换的瞬间，屏幕会不会什么都没有**。

用户观察：降内存的改动之后，"动作变化时桌宠会消失一瞬"。

`paintEvent` 的判断逻辑是这样的（照抄自 src/pet.py）：

    outgoing = animator.outgoing_frame()      # 垫层 = 上一段的最后一帧
    alpha    = animator.fade_alpha()
    ready    = playing is not None and playing.ready
    if outgoing is not None and ready and alpha < 1.0:
        painter.setOpacity(1.0); 画 outgoing        # 先满不透明地铺上垫层
    painter.setOpacity(alpha); 画 current_frame()   # 新段再淡入

所以"什么都看不见"只有两种可能：

  A. `current_frame()` 返回 None，**且**上面那条垫层分支没走（outgoing 为 None，或 ready 为假）；
  B. alpha ≈ 0（新段刚切成、还在淡入起点），**且**没有垫层。

这个探针就找这两种时刻：连续切换动画，逐帧采样，统计"会看不见"的帧数与它们
出现在切换之后的第几帧。

    python tools/probe_switch_blank.py
"""

import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def sample(anim):
    """返回 (动画名, ready, 有帧吗, alpha, 有垫层吗, 会看见吗)。

    **判据必须与 `paintEvent` 保持一致**：这里抄的是它当前的条件 ——
    垫层在「新段正在淡入」或「这一帧还没有」时都会画。第一版这里抄的是**改之前**
    的条件（要求 ready），于是改完 `paintEvent` 之后探针仍然报"看不见"，
    看起来像修复无效 —— 实际是探针没跟上。
    """
    playing = anim.playing
    frame = anim.current_frame()
    alpha = anim.fade_alpha()
    outgoing = anim.outgoing_frame()
    ready = bool(playing.ready) if playing else False
    underlay_drawn = (outgoing is not None
                      and (frame is None or (ready and alpha < 1.0)))
    visible = (frame is not None and alpha > 0.02) or underlay_drawn
    return (playing.name if playing else None, ready, frame is not None,
            alpha, outgoing is not None, visible)


def main():
    from config import load, pet_configs
    from frames import FrameStore
    from main import build_app
    from pet import PetWindow

    app = build_app([sys.argv[0]])
    pet_config = pet_configs(load())[0]
    store = FrameStore(keep=6)
    window = PetWindow(pet_config, store)
    window.show()

    names = list(pet_config.actions("idle") or []) + list(pet_config.actions("clicks") or [])
    if len(names) < 3:
        print("  动画太少，无法测切换")
        return 1

    # 预热：让第一段就绪（否则一开始的空白是正常的加载期）
    store.request(names[0])
    deadline = time.time() + 20
    while time.time() < deadline:
        app.processEvents()
        if store.has(names[0]):
            break
        time.sleep(0.05)

    print()
    print("  探针：切换动画时会不会出现「什么都看不见」的帧")
    print("  " + "=" * 74)
    print("  参与切换的动画: %s" % "、".join(names[:4]))

    blank = []
    switches = 0
    for round_index in range(8):
        target = names[round_index % len(names)]
        window.animator.play(target, loop=True)
        switches += 1
        for offset in range(40):
            window.animator._tick()
            app.processEvents()
            name, ready, has_frame, alpha, has_underlay, visible = sample(window.animator)
            if not visible:
                blank.append((target, offset, name, ready, has_frame,
                              round(alpha, 2), has_underlay))
            time.sleep(1.0 / 60.0)

    print()
    print("  共切换 %d 次，采样 %d 帧" % (switches, switches * 40))
    print("  **会看不见的帧: %d**" % len(blank))
    if blank:
        print()
        print("  %-14s %-6s %-20s %-6s %-6s %-6s %s"
              % ("切到", "第几帧", "当时动画", "ready", "有帧", "alpha", "有垫层"))
        for row in blank[:20]:
            print("  %-14s %-6d %-20s %-6s %-6s %-6s %s"
                  % (row[0][:14], row[1], str(row[2])[:20], row[3],
                     "是" if row[4] else "**否**", row[5], "是" if row[6] else "**否**"))
        if len(blank) > 20:
            print("  …… 另有 %d 帧" % (len(blank) - 20))

        # 归类：是"没有帧"还是"透明且没有垫层"
        no_frame = [b for b in blank if not b[4]]
        transparent = [b for b in blank if b[4] and not b[6]]
        print()
        print("  归类：")
        print("    没有帧可画        : %d 帧" % len(no_frame))
        print("    有帧但 alpha≈0 且无垫层: %d 帧" % len(transparent))
        if no_frame:
            print("    -> 首帧还没解码出来（加载中），且垫层也没有")
        if transparent:
            print("    -> 新段刚切换、alpha 从 0 起，而垫层为空")

    window.close()
    store.close()
    print()
    return 1 if blank else 0


if __name__ == "__main__":
    sys.exit(main())
