# -*- coding: utf-8 -*-
"""自检：显示环境变化时，桌宠必须被拉回**当前**屏幕的可用区内。

起因：实测踩过一次 —— 桌宠以为屏幕只有 1280×720（真实 2560×1440），于是
"只能放在左上角、右边和下面都放不了"，**重启才恢复**。根因是启动时读到的屏幕参数
在显示环境变化后没有被纠正，而进程里**没有任何显示器变化监听**。

这条修复（`_bind_display_changes` / `_on_display_changed`）验三件事：

  A. **接线**：把应用的 `screenAdded` / `screenRemoved` 信号 emit 一次，
     处理函数必须被调用（否则"监听了"只是句空话）；
  B. **出界要拉回**：把宠物挪到可用区外，处理函数必须把它移回区内；
  C. **区内不许动**：宠物本来就在可用区内时，处理函数**不能**移动它
     （否则用户摆好的位置会被无谓地挪走 —— 这类"修一个 bug 引入另一个"要挡住）。

    python tools/selftest_display_change.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

FAILED = []


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label,
                         ("  " + str(detail)) if detail else ""))
    if not ok:
        FAILED.append(label)


def main():
    from PyQt5.QtWidgets import QApplication

    from config import load, pet_configs
    from frames import FrameStore
    from main import build_app
    from pet import PetWindow

    app = build_app([sys.argv[0]])
    pet_config = pet_configs(load())[0]
    store = FrameStore(keep=2)
    window = PetWindow(pet_config, store)
    window.show()
    for _ in range(20):
        app.processEvents()

    print()
    print("  自检：显示环境变化时把宠物拉回可用区")
    print("  " + "=" * 74)

    area = window.current_screen_area()
    print("  当前可用区: (%d,%d) %dx%d   窗口 %dx%d"
          % (area.x(), area.y(), area.width(), area.height(),
             window.width(), window.height()))

    # --- A. 接线：只 emit 应用级信号，宠物必须被拉回 ------------------------ #
    # 第一版这里是自己再调一次 `_bind_display_changes()` 并数调用次数 —— 那只能证明
    # "这个方法本身能把线接上"，**证明不了 `__init__` 真的接过**。改成端到端：
    # 摆到界外，然后**只**发信号，看它有没有被拉回来。
    window.pos_x = float(area.right() + 300)
    window.pos_y = float(area.bottom() + 300)
    emitted = True
    try:
        app.screenAdded.emit(app.primaryScreen())
        app.processEvents()
    except Exception as error:
        emitted = False
        print("      注意：无法 emit screenAdded（%s）—— 跳过 A" % error)
    if emitted:
        pulled = (window.pos_x + window.width() <= area.right() + 1
                  and window.pos_y + window.height() <= area.bottom() + 1)
        check("A. 只发信号（__init__ 里接的线）就能把宠物拉回", pulled,
              "落点 (%.0f, %.0f)" % (window.pos_x, window.pos_y))
    else:
        check("A. 只发信号就能把宠物拉回", False, "无法 emit")

    # --- B. 出界必须拉回 --------------------------------------------------- #
    # 放到"右侧外 + 下方外"（就是那次事故的位置形态）
    window.pos_x = float(area.right() + 200)
    window.pos_y = float(area.bottom() + 200)
    window._on_display_changed()
    inside_b = (area.left() - 1 <= window.pos_x
                and window.pos_x + window.width() <= area.right() + 1
                and area.top() - 1 <= window.pos_y
                and window.pos_y + window.height() <= area.bottom() + 1)
    check("B. 出界后被拉回可用区内", inside_b,
          "落点 (%.0f, %.0f)" % (window.pos_x, window.pos_y))

    # 左侧/上方出界也要能拉回
    window.pos_x = float(area.left() - 500)
    window.pos_y = float(area.top() - 500)
    window._on_display_changed()
    inside_b2 = (window.pos_x >= area.left() - 1 and window.pos_y >= area.top() - 1)
    check("B2. 左上出界也被拉回", inside_b2,
          "落点 (%.0f, %.0f)" % (window.pos_x, window.pos_y))

    # --- C. 区内不许动 ----------------------------------------------------- #
    window.pos_x = float(area.left() + 120)
    window.pos_y = float(area.top() + 90)
    before = (window.pos_x, window.pos_y)
    window._on_display_changed()
    after = (window.pos_x, window.pos_y)
    check("C. 本来在区内时**不移动**（不打扰用户摆好的位置）",
          abs(after[0] - before[0]) < 0.5 and abs(after[1] - before[1]) < 0.5,
          "(%.0f,%.0f) -> (%.0f,%.0f)" % (before + after))

    window.close()
    store.close()

    print()
    print("  结论")
    print("  " + "=" * 74)
    if FAILED:
        for item in FAILED:
            print("     [失败] %s" % item)
        print()
        print("  共 %d 项失败" % len(FAILED))
        return 1
    print("     [OK] 信号已接上；出界会拉回；区内不动")
    print("     [提醒] 真实的「改缩放 / 拔插显示器」要在真机上确认 —— 无头环境")
    print("            没法改变显示配置，这里验的是处理逻辑本身。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
