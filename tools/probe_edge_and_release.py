# -*- coding: utf-8 -*-
"""探针：① 松开时的"消失一瞬"是什么在变；② 墙壁边界到底挡在哪。

用户反馈（在换成 grabMouse 之后）：
  * 按下不闪了 ✓
  * **松开还是会消失一瞬** ✗
  * **依旧无法到达屏幕侧边缘** ✗

两件事分别量：

  ① 松开前后，窗口的**几何**（size / pos）与**动画名**有没有突变？
     松手会 `next_auto()` 换段，而不同动画的精灵尺寸不同 → `_resize_window()`
     会改窗口大小并搬位置。若在那一瞬间"窗口已经变了、但新帧还没画上"，
     看起来就是消失一瞬。
  ② 把宠物强行推到屏幕外，跑一次 `step_physics()`，看它被挡在哪个 x
     —— 那就是**实际的**墙壁边界；再和屏幕边界比，看差多少。

    python tools/probe_edge_and_release.py
"""

import os
import sys
import time

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

    wanted = list(pet_config.actions("drag") or []) + list(pet_config.actions("idle") or [])
    for name in wanted:
        store.request(name)
    deadline = time.time() + 20
    while time.time() < deadline:
        app.processEvents()
        if all(store.has(n) for n in wanted):
            break
        time.sleep(0.05)

    def mouse(kind, pos):
        return QMouseEvent(kind, QPoint(*pos), QPoint(*pos), Qt.LeftButton,
                           Qt.LeftButton, Qt.NoModifier)

    print()
    print("  探针：松开瞬间的几何变化 / 墙壁的实际边界")
    print("  " + "=" * 74)

    # ---------------- ① 松开瞬间 ---------------- #
    print()
    print("  ① 松开前后：窗口几何与动画")
    print("  " + "-" * 74)
    centre = (window.width() // 2, window.height() // 2)
    window.mousePressEvent(mouse(QEvent.MouseButtonPress, centre))
    app.processEvents()
    for i in range(6):
        window.mouseMoveEvent(mouse(QEvent.MouseMove, (centre[0] + 15 * i, centre[1])))
        app.processEvents()

    def snap(tag, rows):
        anim = window.animator
        playing = anim.playing
        rows.append((tag, window.width(), window.height(),
                     round(window.pos_x, 1), round(window.pos_y, 1),
                     (playing.name if playing else None),
                     bool(playing.ready) if playing else False,
                     anim.current_frame() is None))

    rows = []
    snap("松开前", rows)
    window.mouseReleaseEvent(mouse(QEvent.MouseButtonRelease,
                                  (centre[0] + 120, centre[1])))
    snap("松开瞬间", rows)
    for i in range(5):
        app.processEvents()
        snap("松开后+%d" % (i + 1), rows)
    # 再多推几帧（换段会触发窗口尺寸重算）
    for i in range(20):
        app.processEvents()
        time.sleep(0.01)
    snap("0.2秒后", rows)

    print("  %-11s %-11s %-16s %-22s %6s %6s" %
          ("时刻", "窗口尺寸", "位置", "动画", "ready", "无帧"))
    for tag, w, h, x, y, name, ready, noframe in rows:
        print("  %-11s %-11s %-16s %-22s %6s %6s"
              % (tag, "%dx%d" % (w, h), "(%.0f,%.0f)" % (x, y),
                 str(name)[:22], ready, "是" if noframe else "—"))

    # ---------------- ② 墙壁边界 ---------------- #
    print()
    print("  ② 墙壁的实际边界（把宠物推出去，看它被挡在哪）")
    print("  " + "-" * 74)
    area = window.current_screen_area()
    left, right = window.wall_insets()
    print("  屏幕可用区: (%d,%d) %dx%d" % (area.left(), area.top(),
                                          area.width(), area.height()))
    print("  wall_insets(): 左 %.0f / 右 %.0f   （窗口宽 %d）"
          % (left, right, window.width()))

    window.mode = "roam"
    # 推到最左
    window.pos_x = -10000.0
    window.vx = 0.0
    window.step_physics()
    landing_left = window.pos_x
    # 推到最右
    window.pos_x = 10000.0
    window.vx = 0.0
    window.step_physics()
    landing_right = window.pos_x

    expect_left = area.left() - left
    expect_right = area.right() - window.width() + right
    print()
    print("  最左落点 %.1f（按 wall_insets 应为 %.1f，屏幕左缘 %d）"
          % (landing_left, expect_left, area.left()))
    print("  最右落点 %.1f（按 wall_insets 应为 %.1f，屏幕右缘 %d）"
          % (landing_right, expect_right, area.right()))
    print()
    print("  **角色**能贴到哪：")
    l_inset, r_inset = window.character_insets()
    print("    角色左缘 = 窗口左缘 + 当前帧留白 %.0f  ->  最左时角色左缘 = %.1f"
          % (l_inset, landing_left + l_inset))
    print("    角色右缘 = 窗口右缘 - 当前帧留白 %.0f  ->  最右时角色右缘 = %.1f"
          % (r_inset, landing_right + window.width() - r_inset))

    # 拖动能不能到边：模拟把光标拖到屏幕最左
    print()
    print("  ③ 拖动能不能把窗口带到屏幕左缘之外（模拟光标贴屏幕最左）")
    print("  " + "-" * 74)
    window.pos_x, window.pos_y = 400.0, 300.0
    window.mousePressEvent(mouse(QEvent.MouseButtonPress, (160, 90)))
    app.processEvents()
    for i in range(30):
        # 光标一路往左走到 0（globalPos 是绝对坐标）
        window.mouseMoveEvent(mouse(QEvent.MouseMove, (max(0, 300 - 12 * i), 300)))
        app.processEvents()
    drag_x = window.pos_x
    print("  光标拖到 x=0 后，窗口 pos_x = %.1f" % drag_x)
    print("  （对比：屏幕左缘 %d，按留白允许到 %.1f）" % (area.left(), expect_left))
    window.mouseReleaseEvent(mouse(QEvent.MouseButtonRelease, (0, 300)))
    app.processEvents()
    after_release = window.pos_x
    window.step_physics()
    after_physics = window.pos_x
    print("  松开后 pos_x = %.1f；跑一帧物理后 = %.1f" % (after_release, after_physics))
    if abs(after_physics - after_release) > 8:
        print("  **松开后位置被搬动了 %.1f px** —— 这就是「往里闪」"
              % abs(after_physics - after_release))

    window.close()
    store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
