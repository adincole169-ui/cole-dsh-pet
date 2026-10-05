# -*- coding: utf-8 -*-
"""诊断 selftest_crossfade 的"基线不可见"：逐环打印，看是哪一步断的。

判据链：store.animation(名) → _cache 里有 → play() 后 playing.animation 非空
        → frame_index() 取到 → StreamAnimation.frame() 返回非 None → window.grab() 有 alpha

    python tools/probe_crossfade_baseline.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)


def mean_alpha(window):
    image = window.grab().toImage()
    total = count = 0
    for y in range(2, image.height(), 3):
        for x in range(2, image.width(), 3):
            alpha = image.pixelColor(x, y).alpha()
            if alpha > 8:
                total += alpha
                count += 1
    return (total / float(count)) if count else 0.0


def main():
    from config import load, pet_configs
    from frames import FrameStore
    from main import build_app
    from pet import PetWindow

    app = build_app([sys.argv[0]])
    entries = pet_configs(load())
    store = FrameStore(keep=6)
    print()
    print("  诊断交叉淡化基线（帧来源 %s）" % store.source)
    print("  " + "=" * 72)

    window = PetWindow(entries[0], store)
    window.show()
    app.processEvents()

    candidates = []
    events = entries[0].animations.get("events") or {}
    for names in events.values():
        candidates.extend(names or [])
    candidates.extend(entries[0].actions("clicks"))
    candidates = [n for n in dict.fromkeys(candidates)][:3]

    for name in candidates:
        animation = store.animation(name)
        status = "None" if animation is None else "%d 帧 fps=%s" % (
            len(animation), getattr(animation, "fps", "?"))
        print("  store.animation(%-20s) -> %s" % (name[:20], status))

    target = candidates[0]
    print()
    print("  目标: %s" % target)
    cached = store.peek(target)
    print("     store.peek 拿到        : %s" % ("是" if cached is not None else "**否**"))
    if cached is not None:
        pixmap = cached.frame(0)
        print("     animation.frame(0)     : %s"
              % ("%dx%d" % (pixmap.width(), pixmap.height()) if pixmap else "**None**"))

    window.animator.play(target, loop=True)
    playing = window.animator.playing
    print("     playing.name           : %s" % (playing.name if playing else None))
    print("     playing.animation 非空 : %s"
          % ("是" if (playing and playing.animation is not None) else "**否**"))
    for step in range(8):
        window.animator._tick()
        app.processEvents()
    if playing:
        print("     playing.elapsed        : %.3f" % playing.elapsed)
        print("     frame_index()          : %d" % playing.frame_index())
        current = playing.frame()
        print("     playing.frame()        : %s"
              % ("%dx%d" % (current.width(), current.height()) if current else "**None**"))
    print("     animator.current_frame : %s"
          % ("有" if window.animator.current_frame() is not None else "**无**"))
    print("     window.grab() 平均alpha: %.1f" % mean_alpha(window))
    print("     window 尺寸/可见        : %dx%d vis=%s"
          % (window.width(), window.height(), window.isVisible()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
