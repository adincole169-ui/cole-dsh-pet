# -*- coding: utf-8 -*-
"""引导使用者为桌宠准备素材。

本仓库**不含**动画素材（版权原因，见 ASSETS.md），所以 clone 下来跑不起来是正常的。
这个脚本把"接下来该做什么"讲清楚，并在可能的情况下直接帮他做。

两条路：
  A. 用自己的素材（推荐，完全属于你）
     把透明动画放进 frames/<动画名>/ 或 webm/ 即可 —— 脚本只做检查与提示。
  B. 从上游取现成素材（仅供你个人使用，不要提交进仓库）
     上游是 gmskywalker/deepseek-fat-fish-codex-pet，图集 1536x2288。
     转成帧需要 ffmpeg；调色板量化需要 Pillow。

    python tools/fetch_assets.py            # 检查现状 + 打印指引
    python tools/fetch_assets.py --check    # 只检查
"""

import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UPSTREAM = "https://github.com/gmskywalker/deepseek-fat-fish-codex-pet"
SHEET_PATH = "deepseek-fat-fish/spritesheet.webp"


def survey():
    """看一眼现在有什么。"""
    webm_dir = os.path.join(ROOT, "webm")
    frames_dir = os.path.join(ROOT, "frames")

    webm = []
    if os.path.isdir(webm_dir):
        webm = sorted(name for name in os.listdir(webm_dir) if name.endswith(".webm"))

    animations = {}
    if os.path.isdir(frames_dir):
        for name in sorted(os.listdir(frames_dir)):
            folder = os.path.join(frames_dir, name)
            if not os.path.isdir(folder):
                continue
            count = len([f for f in os.listdir(folder) if f.endswith(".png")])
            if count:
                animations[name] = count

    return webm, animations


def main():
    check_only = "--check" in sys.argv
    webm, animations = survey()

    print()
    print("  大肥鱼桌宠：素材准备引导")
    print("  " + "=" * 62)
    print()
    print("  == 你现在有什么 ==")
    print("     webm/ 里的透明动画 : %d 个" % len(webm))
    print("     frames/ 里的解码帧  : %d 个动画" % len(animations))
    if animations:
        sample = list(animations.items())[:3]
        print("        例如: %s"
              % ", ".join("%s(%d 帧)" % (name, count) for name, count in sample))

    if webm or animations:
        print()
        print("  已经有素材了。检查一下能不能跑：")
        print("     python main.py --check-assets")
        if webm and not animations:
            print()
            print("  提示：有 webm 但没有解码帧 —— 首次播放会现场解码，每个约 20-30 秒。")
            print("  建议先预解码（需要 ffmpeg 在 PATH 里）：")
            print("     python main.py --predecode")
        return 0

    print()
    print("  == 结论：还没有任何素材 ==")
    print()
    print("  本仓库只含代码 —— 素材的版权与授权情况见 ASSETS.md。")
    print("  下面两条路选一条。")
    print()

    print("  【A】用自己的素材（推荐，完全属于你）")
    print("  " + "-" * 60)
    print("     把任意透明背景的动画放成下面任一形式：")
    print()
    print("       frames/<动画名>/0001.png, 0002.png, ...    # PNG 序列，最快")
    print("       webm/<动画名>.webm                          # 透明 VP9，需 ffmpeg 解码")
    print()
    print("     然后改 config.jsonc，把名字填进 idle / clicks / drag / turn /")
    print("     moves / categories / events。")
    print()
    print("     最少一个就够启动：把 PNG 放进 frames/待机呼吸休闲/，")
    print("     config.jsonc 的 idle 指向它。其它动作缺失只会少些花样，不会崩。")
    print()
    print("     参考 pet/夜猫-config.json —— 那是一个完整的「另一种种类」示例。")
    print()

    print("  【B】从上游取现成素材（仅供个人使用）")
    print("  " + "-" * 60)
    print("     上游仓库: %s" % UPSTREAM)
    print("     素材文件: %s" % SHEET_PATH)
    print("     规格    : 1536x2288 无损 RGBA 图集，8 列 x 11 行，单格 192x208")
    print()
    print("     ⚠️ 该仓库**没有开源许可证**，只在 README 里声明了非商业、个人使用，")
    print("        **未授予再分发权**。所以：")
    print("          * 你可以自己取来自己用；")
    print("          * 但**不要**把取来的素材提交到本仓库或任何公开仓库；")
    print("          * 也不要把带素材的包公开分发。")
    print()
    print("     步骤：")
    print("       1. 从上面仓库下载 %s" % SHEET_PATH)
    print("       2. 放进本目录的 webm/ （或用 ffmpeg 解成 PNG 放进 frames/）")
    print("       3. 检查：  python main.py --check-assets")
    print("       4. 预解码：python main.py --predecode     # 消除首次播放卡顿")
    print("       5. 启动：  python main.py")
    print()

    print("  == 依赖 ==")
    print("     运行时 : 只需要 PyQt5（见 requirements.txt）")
    print("     解码素材: 需要 ffmpeg 在 PATH 里；量化需要 Pillow")
    ffmpeg = shutil.which("ffmpeg")
    print("     ffmpeg : %s" % (ffmpeg if ffmpeg else "**没找到** —— 需要装并加进 PATH"))
    try:
        import PIL                                       # noqa: F401
        print("     Pillow : 已安装")
    except ImportError:
        print("     Pillow : 未安装（pip install Pillow）")

    print()
    print("  " + "=" * 62)
    print("  想确认随时可以跑：python tools/fetch_assets.py --check")
    print()
    if check_only:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
