# -*- coding: utf-8 -*-
"""自检：表情包只允许从 `memes/` 加载，越界路径必须被拒。

背景（原先的实现确实能被利用）
------------------------------
`PetWindow._load_image()` 原本是：

    if os.path.isabs(name_or_path) and os.path.exists(name_or_path):
        candidates.append(name_or_path)          # 任意绝对路径都直接 QPixmap(...)

于是 `POST /say {"image": "C:/.../某张图.png"}` 能让桌宠加载并显示机器上任意一张图。
攻击者**读不回**那张图（它只画在用户屏幕上，回包永远 `{ok:true}`），所以不是直接泄露；
但配合伪造的文字就能做出很唬人的假通知 —— 不必要的攻击面。

合法调用方（DSH 插件）**只发表情包名字**，从不发路径，所以收紧无损失。

这个自检验四件事：
  1. 正常表情名照常能加载；
  2. 绝对路径被拒（哪怕文件真的存在）；
  3. `..` 逃逸被拒；
  4. `memes/` 之外的相对路径也被拒。

    python tools/selftest_image_scope.py
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

FAILED = []


def check(label, ok, detail=""):
    if isinstance(detail, (list, tuple)):
        detail = " / ".join(str(x) for x in detail if x)
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label,
                         ("  " + str(detail)) if detail else ""))
    if not ok:
        FAILED.append(label)


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PyQt5.QtWidgets import QApplication                 # noqa: F401
        from PyQt5.QtGui import QPixmap
    except ImportError as error:
        print("  需要 PyQt5: %s" % error)
        return 1

    from config import load, pet_configs
    from frames import FrameStore
    from main import build_app
    from pet import PetWindow

    app = build_app([sys.argv[0]])
    pet_config = pet_configs(load())[0]
    store = FrameStore(keep=2)
    window = PetWindow(pet_config, store)
    window.show()
    app.processEvents()

    print()
    print("  自检：表情包只能从 memes/ 加载")
    print("  " + "=" * 74)

    memes = os.path.join(ROOT, "memes")
    names = sorted(n[:-4] for n in os.listdir(memes) if n.endswith(".png"))
    check("memes/ 里有表情包", bool(names), "、".join(names[:4]))

    # --- 1. 正常名字要能用 ---
    if names:
        pixmap = window._load_image(names[0])
        check("按名字加载（%s）" % names[0],
              pixmap is not None and not pixmap.isNull())
        pixmap = window._load_image(names[0] + ".png")
        check("按文件名加载（%s.png）" % names[0],
              pixmap is not None and not pixmap.isNull())

    # --- 2. 绝对路径要拒绝（而且在 memes/ 之外也真实存在，避免"因为文件不存在所以拒绝"的假通过）---
    outside_dir = tempfile.mkdtemp(prefix="dsh-pet-outside-")
    outside_file = os.path.join(outside_dir, "secret.png")
    from PyQt5.QtGui import QColor
    probe = QPixmap(8, 8)
    # 必须用 QColor：这个 PyQt5（5.9）的 `fill()` 不接受 int，
    # 直接 `fill(0xFF00FF)` 会报 "unexpected type 'int'"。
    probe.fill(QColor(255, 0, 255))
    saved = probe.save(outside_file, "PNG")
    check("造了一张 memes/ 之外的真实图片（避免假通过）", saved and os.path.isfile(outside_file),
          outside_file)

    if saved:
        pixmap = window._load_image(outside_file)
        check("**绝对路径被拒**（文件真的存在也拒）", pixmap is None,
              "加载成功 = 越界" if pixmap is not None else "")

        # 带 .png 后缀的绝对路径也不能例外
        pixmap = window._load_image(outside_file[:-4])
        check("绝对路径（不带后缀）也被拒", pixmap is None)

    # --- 3. `..` 逃逸要拒绝 ---
    if saved:
        relative_escape = os.path.join("..", "..", os.path.basename(outside_dir),
                                       "secret.png").replace("\\", "/")
        pixmap = window._load_image(relative_escape)
        check("`..` 相对逃逸被拒", pixmap is None, relative_escape)

        # 直接写 `../` 开头
        pixmap = window._load_image("../memes/../config.jsonc")
        check("`../` 形式的越界被拒", pixmap is None)

    # --- 4. memes/ 之外的绝对路径（项目自己的文件）也要拒 ---
    project_file = os.path.join(ROOT, "assets", "icon.png")
    if os.path.isfile(project_file):
        pixmap = window._load_image(project_file)
        check("项目内但不在 memes/ 的绝对路径也被拒", pixmap is None,
              "assets/icon.png" if pixmap is not None else "")

    # 清理
    try:
        if saved:
            os.remove(outside_file)
        os.rmdir(outside_dir)
    except OSError:
        pass
    window.close()

    print()
    print("  结论")
    print("  " + "=" * 74)
    if FAILED:
        for item in FAILED:
            print("     [失败] %s" % item)
        return 1
    print("     [OK] 表情名照常可用；绝对路径、`..` 逃逸、memes/ 之外一律拒绝")
    return 0


if __name__ == "__main__":
    sys.exit(main())
