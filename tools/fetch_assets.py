# -*- coding: utf-8 -*-
"""引导使用者为桌宠准备素材。

本仓库默认**不附带**动画素材（体积原因，见 ASSETS.md），所以 clone 下来跑不起来
是正常的。这个脚本把"接下来该做什么"讲清楚。

两条路：
  A. 用上游素材（最快）
     本项目用的就是 PC2005-cloud/dsh-pet 的 dsh-pet/assets/webm/（106 个透明动画），
     取来放进 webm/ 即可。该项目的许可：素材允许开源使用、**禁止商用**、二创须署名。
  B. 用自己的素材（推荐，权利最干净）
     把透明动画放进 frames/<动画名>/ 或 webm/<动画名>.webm 即可。

解码需要 ffmpeg；调色板量化需要 Pillow。

    python tools/fetch_assets.py            # 检查现状 + 打印指引
    python tools/fetch_assets.py --check    # 只检查
"""

import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UPSTREAM = "https://github.com/PC2005-cloud/dsh-pet"
UPSTREAM_ASSET_DIR = "dsh-pet/assets/webm/"


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

    print("  【B】用上游素材（最快）")
    print("  " + "-" * 60)
    print("     上游仓库: %s" % UPSTREAM)
    print("     素材位置: %s" % UPSTREAM_ASSET_DIR)
    print("     内容    : 106 个透明动画（VP9 + 第二路 alpha 流，640x360，每段 241 帧）")
    print()
    print("     本项目的 webm/ 与上游同名同内容（抽查逐字节相同，可用")
    print("     tools/verify_asset_origin.py 复核）。")
    print()
    print("     ⚠️ 上游的许可（原文摘要）：")
    print("          * 素材（动画/提示词/源视频）：**允许开源使用**，**禁止商用**；")
    print("          * 二创约定：基于它的衍生/改版/换皮作品，在**任何介绍、展示、")
    print("            分发该作品的地方**，须附上原作者 GitHub 地址。")
    print()
    print("     也就是说：可以用、可以开源分发，但**不能商用**，且必须署名。")
    print("     本项目已在 README 与 ASSETS.md 附上该地址。")
    print()
    print("     步骤：")
    print("       1. 从上面仓库取 %s 下的 webm" % UPSTREAM_ASSET_DIR)
    print("          （或装它的 npm 包：https://www.npmjs.com/package/dsh-pet）")
    print("       2. 放进本目录的 webm/")
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
