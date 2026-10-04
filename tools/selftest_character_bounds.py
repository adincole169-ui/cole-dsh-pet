# -*- coding: utf-8 -*-
"""自检：窗口贴屏幕边时，贴住的必须是**角色**，而不是窗口两侧的透明留白。

用户报"大肥鱼不能放到屏幕最右侧，已经是最右了但没到边"。

实测根因（`size=320` 逻辑）：
    帧 640x360 里角色 bbox 约 226x256，只占画面宽的 35%
    窗口 320 逻辑 -> 掩膜包围盒 [108, 32, 105, 133]
    角色可见宽仅 105 逻辑像素，左右各约 107 是**透明留白**

物理层原先用 `self.width()` 贴边，等于把留白贴到屏幕边，角色于是停在离边
约 107px 处。本自检钉住：

  1. 留白确实存在（前提成立，否则测试没意义）；
  2. 撞右墙后**角色右边缘**贴屏幕右边；
  3. 撞左墙后**角色左边缘**贴屏幕左边；
  4. 初始位置按 corner 落在右下角，margin 量的是角色边到屏幕边。

    python tools/selftest_character_bounds.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from main import build_app                                # noqa: E402
from config import load, pet_configs                      # noqa: E402
from frames import FrameStore                             # noqa: E402
from pet import PetWindow                                 # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label,
                         ("  " + detail) if detail else ""))
    if not ok:
        FAILED.append(label)


def main(argv):
    app = build_app([argv[0]])
    config = pet_configs(load())[0]
    store = FrameStore(keep=3)
    window = PetWindow(config, store)
    window.show()
    # 关掉"启动期按角色自动对齐"：本自检自己调 _place_initial 并断言几何，
    # 若让自动对齐在启动窗口期内插一脚，断言就会读到被它改过的位置。
    window._user_took_over()

    # 必须加载真实画面并算过掩膜，否则拿不到角色的实际边界
    name = "点击回应-开心跃动"
    store.animation(name)
    window.animator.play(name, loop=True)
    window.animator._tick()
    window._resize_window()
    window._apply_input_mask()
    app.processEvents()

    area = app.primaryScreen().availableGeometry()
    inset_left, inset_right = window.character_insets()
    stats = window.mask_stats or {}
    print("  屏幕: %d,%d %dx%d    窗口: %dx%d"
          % (area.x(), area.y(), area.width(), area.height(),
             window.width(), window.height()))
    print("  掩膜包围盒: %s" % (stats.get("rect"),))
    print("  角色左右留白: left=%.1f  right=%.1f   角色宽=%.1f"
          % (inset_left, inset_right, window.width() - inset_left - inset_right))
    print()

    check("角色左右确有留白（bug 的前提成立）",
          inset_left > 5.0 and inset_right > 5.0,
          "left=%.1f right=%.1f" % (inset_left, inset_right))

    # --- 撞右墙 ---
    window.pos_x = 999999.0
    window.vx = 0.0
    window.mode = "still"
    window._manual_move = False
    window.step_physics()
    character_right = window.pos_x + window.width() - inset_right
    check("撞右墙后**角色**右边缘贴屏幕右边",
          abs(character_right - area.right()) <= 1.5,
          "角色右=%.1f 屏幕右=%d 差=%.1f"
          % (character_right, area.right(), area.right() - character_right))
    print("       （窗口右边缘 = %.1f，允许超出屏幕 %.1f）"
          % (window.pos_x + window.width(),
             window.pos_x + window.width() - area.right()))

    # --- 撞左墙 ---
    window.pos_x = -999999.0
    window.vx = 0.0
    window.step_physics()
    character_left = window.pos_x + inset_left
    check("撞左墙后**角色**左边缘贴屏幕左边",
          abs(character_left - area.left()) <= 1.5,
          "角色左=%.1f 屏幕左=%d 差=%.1f"
          % (character_left, area.left(), character_left - area.left()))

    # --- 初始位置 ---
    window._place_initial()
    margin_x = int(config.position.get("marginX", 24))
    margin_y = int(config.position.get("marginY", 100))
    corner = str(config.position.get("corner", ""))
    gap_x = area.right() - (window.pos_x + window.width() - inset_right)
    check("初始位置：角色右边距 == marginX",
          abs(gap_x - margin_x) <= 1.5,
          "实测 %.1f 期望 %d" % (gap_x, margin_x))
    gap_y = area.bottom() - (window.pos_y + window.height())
    check("初始位置：垂直在底部（corner 含 bottom）",
          "bottom" in corner and abs(gap_y - margin_y) <= 1.5,
          "corner=%s 离底=%.1f 期望 %d" % (corner, gap_y, margin_y))
    check("初始位置：横向在右侧（corner 含 right）",
          "right" in corner and gap_x >= 0, "corner=%s gap=%.1f" % (corner, gap_x))

    # --- 居中也要按角色 ---
    window.place({})
    character_center = (window.pos_x + inset_left
                        + (window.width() - inset_left - inset_right) / 2.0)
    check("「屏幕正中」居中的是角色而不是窗口",
          abs(character_center - (area.left() + area.width() / 2.0)) <= 2.0,
          "角色中心=%.1f 屏幕中心=%.1f"
          % (character_center, area.left() + area.width() / 2.0))

    window.close()
    print()
    print("失败 %d 项" % len(FAILED) if FAILED else "全部通过")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
