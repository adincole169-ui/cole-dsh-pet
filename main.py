# -*- coding: utf-8 -*-
"""入口：启动桌宠。

    pythonw main.py                      # 正常启动（无控制台窗口）
    python  main.py --status             # 打印配置与素材状态
    python  main.py --anim 吃白饭 --hold 8   # 只播一个动画，8 秒后退出（自检用）
    python  main.py --predecode          # 预解码全部常用动画后退出（CI/预热用）

多开
----
`config.jsonc` 的 `pets` 数组里有几只就开几个窗口，各自有独立的大小与位置；
`display` 为 `none` 的会被跳过。用 pythonw 启动才不会带控制台窗口。
"""

import json
import os
import sys
from urllib.request import urlopen

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "src"))

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QApplication

from config import load, pet_configs, pet_configs_for_species, species_names
from frames import FrameStore
from pet import PetWindow


def _pick_species(argv):
    """`--pet <种类名>`：走 `pet/<名字>-config.json` 的覆盖层。"""
    if "--pet" in argv:
        try:
            return argv[argv.index("--pet") + 1]
        except IndexError:
            return None
    return None


def _status():
    sys.path.insert(0, os.path.join(HERE, "tools"))
    import asset_pipeline
    config = load()
    species = _pick_species(sys.argv)
    entries = pet_configs_for_species(config, species) if species else pet_configs(config)
    names = species_names()
    print("可用种类: %s" % (", ".join(names) if names else "(无，放 pet/<名字>-config.json 即可新增)"))
    if species:
        print("当前种类: %s" % species)
    print("配置里的宠物: %d 只" % len(entries))
    for pet_config in entries:
        # 内部物种名（name）与给用户看的名字（displayName）**都打出来**：
        # 两者不一致时最容易出的错就是"任务栏/通知里显示的不是我预期的名字"。
        print("  %s (id=%s, 显示名=%s, size=%s, display=%s)"
              % (pet_config.name, pet_config.id, pet_config.display_name,
                 pet_config.size, pet_config.display))
    first = entries[0] if entries else None
    if first is not None:
        print("动画分类: %s" % ", ".join(first.groups()))
        for group in ("idle", "clicks", "drag", "turn"):
            actions = first.actions(group)
            print("  %-7s %2d 个: %s" % (group, len(actions), ", ".join(actions[:4]) or "(空)"))
        moves = first.animations.get("moves") or {}
        names = [item.get("name") if isinstance(item, dict) else item
                 for item in (moves.get("actions") or [])]
        print("  moves   %2d 个: %s" % (len(names), ", ".join(names)))
        events = first.animations.get("events") or {}
        for group, value in events.items():
            print("  events.%-10s %d 个" % (group, len(value) if isinstance(value, list) else 0))
    print("素材: %d 个 webm，帧缓存 %.1f MB"
          % (len(asset_pipeline.list_animations()), asset_pipeline.cache_size() / 1048576.0))
    return 0


def _predecode(entries, store):
    """解码"一定会用到"的动画，消除首次播放的卡顿。

    用同步接口是有意的：这里是启动阶段的预解码，没有界面要响应；运行中的动画切换
    走的是 `FrameStore.request()` 的后台路径。
    """
    names = []
    for pet_config in entries:
        for group in ("idle", "clicks", "drag", "turn"):
            names.extend(pet_config.actions(group))
        for group in ("workStatus", "whisper", "balance"):
            names.extend(pet_config.event_animations(group))
        for spec in pet_config.move_specs():
            names.append(spec.name)
    unique = [n for n in dict.fromkeys(names) if n]
    for name in unique:
        store.animation(name)
    return unique


def build_app(argv):
    """创建 QApplication，并**在创建之前**打开高 DPI 缩放。

    顺序是硬约束：`AA_EnableHighDpiScaling` 必须在 `QApplication(...)` 之前设置，
    否则不生效。这台机器 DPI 是 144（150%），不生效时 Qt 会把屏幕报成 2560x1600、
    dpr=1.00（真实是 1707x1067），于是所有按"屏幕几何"算出来的位置都偏出可见区域
    —— 宠物就是这么"经常消失"的。生效后 Qt 报 1280x800、dpr=2.00，与物理屏一致。
    """
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(argv)
    app.setQuitOnLastWindowClosed(False)
    return app


def existing_instance(port):
    """已经在跑的那只桌宠（没有则 None）。

    单一实例的判据是**显示服务端口**而不是进程名：端口只有一个，谁先绑上谁就是那只
    活着的。这样"开机自启"和"双击桌面图标"同时发生时，第二个进程会发现自己绑不上
    端口而安静退出，而不是又开出一只一模一样的桌宠。
    """
    try:
        with urlopen("http://127.0.0.1:%d/health" % port, timeout=2) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def check_assets():
    """启动前自检：有没有可用的动画素材。返回一份"体检报告"字典。

    **为什么必须有这一关**：仓库里**不包含**动画素材（版权原因，见 README 的
    "素材与许可"），别人 clone 下来若直接运行，缺素材时程序会在 Qt 回调里抛异常，
    以 `0xC0000409` 静默闪退——**没有任何提示**，看起来就是"项目坏了"。
    与其让人去猜，不如在开窗之前先说清楚缺什么、去哪拿。

    判据只看**文件系统**，不依赖任何运行时状态，所以既快又不会因为别的问题误报。
    """
    root = os.path.dirname(os.path.abspath(__file__))
    frames_dir = os.path.join(root, "frames")
    webm_dir = os.path.join(root, "webm")

    webm = 0
    if os.path.isdir(webm_dir):
        webm = len([name for name in os.listdir(webm_dir) if name.endswith(".webm")])

    # 帧缓存：只数到一个就够（25423 个全数会很慢），但要区分"目录在"与"里面有东西"
    cached = 0
    if os.path.isdir(frames_dir):
        for name in os.listdir(frames_dir):
            folder = os.path.join(frames_dir, name)
            if not os.path.isdir(folder):
                continue
            for entry in os.listdir(folder):
                if entry.endswith(".png"):
                    cached += 1
                    break
            if cached >= 3:          # 够判断"非空"了，不必数完
                break

    return {"webm": webm, "cached": cached}


def report_missing_assets(info):
    """素材缺失时给一段可照做的说明。"""
    lines = [
        "",
        "=" * 68,
        "  大肥鱼桌宠：没有找到动画素材，无法启动",
        "=" * 68,
        "",
        "  当前状态：",
        "     webm 源素材 : %d 个" % info["webm"],
        "     解码帧缓存  : %d 个动画" % info["cached"],
        "",
        "  本仓库**不包含**动画素材（版权归原作者，见 README 的「素材与许可」）。",
        "  你需要自己准备一份，二选一：",
        "",
        "  ① 只要看效果（拿现成素材）",
        "     从上游仓库取透明动画，放进 webm/ 目录：",
        "       https://github.com/gmskywalker/deepseek-fat-fish-codex-pet",
        "",
        "  ② 用自己的素材（推荐，完全属于你）",
        "     把任意透明背景的动画（webm / PNG 序列）放进 frames/<动画名>/",
        "     PNG 命名从 0001.png 开始，再改 config.jsonc 指向你的名字。",
        "",
        "  放好之后启动时若不流畅，先跑一次预解码（需 ffmpeg）：",
        "     python main.py --predecode",
        "",
        "  想确认素材是否就绪：",
        "     python main.py --status",
        "",
        "=" * 68,
        "",
    ]
    sys.stderr.write("\n".join(lines))


def _trim_own_logs():
    """清理桌宠**自己**写的日志。

    包装层 `run_logged.py` 会在启动/退出时清理 `logs/` 下的文件，但碎碎念逐步流水是
    桌宠进程内直接追加的，包装层管不到。这里复用同一套裁剪规则，避免两处各写一份。
    """
    try:
        # `tools` 目录在模块顶部已经加进 sys.path（见文件开头的 sys.path.insert）
        from run_logged import trim_all_logs
        trim_all_logs()
    except Exception as error:
        # 清理失败不该影响桌宠启动——它只是个维护动作。
        # 这里**不能**静默吞掉：先前正是"异常被 except 吃掉"让我把
        # "日志为空"误读成"函数没被调用"，白查了一轮。
        sys.stderr.write("dsh-pet: 日志清理跳过: %s\n" % error)


def main():
    app = build_app(sys.argv)

    config = load()
    bridge_config = config.get("bridge") if isinstance(config.get("bridge"), dict) else {}
    port = bridge_config.get("port") if isinstance(bridge_config.get("port"), int) else 8899

    # 已经有活着的实例就不开新窗。`--allow-multi` 可强制再开（多开测试用）；
    # `--force` 给自检脚本；`--predecode` 只是解码素材、根本不开窗，也不该被挡。
    alive = existing_instance(port)
    if (alive is not None
            and not {"--allow-multi", "--force", "--predecode"} & set(sys.argv)):
        sys.stderr.write("dsh-pet: 已有一只在运行（mood=%s），本次不启动\n" % alive.get("mood"))
        return 0

    # 素材自检：放在单一实例判断**之后**——否则第二次双击时会先报"缺素材"，
    # 而真实原因只是"已经有一只活着"。
    # `--status` 不需要这一关（它要能报告"0 个素材"，见它的输出）。
    if "--status" not in sys.argv and "--predecode" not in sys.argv:
        info = check_assets()
        if info["cached"] == 0 and info["webm"] == 0:
            report_missing_assets(info)
            return 1
        if "--check-assets" in sys.argv:
            print("素材就绪：%d 个 webm，%d 个动画已有解码帧"
                  % (info["webm"], info["cached"]))
            return 0

    species = _pick_species(sys.argv)
    if species:
        entries = pet_configs_for_species(config, species)
    else:
        entries = pet_configs(config)
    # 桌宠自己写的日志（碎碎念逐步流水）也要清理：这几行是**进程内**追加的，
    # 包装层 run_logged.py 管不到它。放在启动时，不必新增定时器。
    _trim_own_logs()
    store = FrameStore(keep=6)
    pets = []
    for pet_config in entries:
        if pet_config.display == "none":
            continue
        window = PetWindow(pet_config, store)
        window.show()
        pets.append(window)
    if not pets:
        # 配置里一只可显示的都没有时，至少给一只，否则用户看到的是"什么都没发生"
        window = PetWindow(entries[0], store) if entries else None
        if window is not None:
            window.show()
            pets.append(window)
    if not pets:
        return 1

    def preload():
        _predecode(entries, store)

    if "--predecode" in sys.argv:
        names = _predecode(entries, store)
        print("预解码 %d 个动画" % len(names))
        return 0

    QTimer.singleShot(200, preload)

    # --watch：每秒记一行位置/可见性，用来定位"宠物不见了"这类问题。
    # 用户报"消失"时，猜原因没用——日志能直接区分"移出屏幕""被隐藏""没有帧"。
    if "--watch" in sys.argv:
        import time as _time
        watch_path = os.path.join(HERE, "logs", "watch.log")

        def watch():
            window = pets[0]
            area = QApplication.primaryScreen().availableGeometry()
            with open(watch_path, "a", encoding="utf-8") as handle:
                handle.write("%s pos=(%d,%d) size=%dx%d vis=%s frame=%s anim=%s loading=%d\n"
                             % (_time.strftime("%H:%M:%S"), window.x(), window.y(),
                                window.width(), window.height(), window.isVisible(),
                                window.animator.current_frame() is not None,
                                window.animator.playing.name if window.animator.playing else None,
                                len(store.stats()["loading"])))
                handle.write("           screen=%dx%d+%d+%d\n"
                             % (area.width(), area.height(), area.x(), area.y()))

        watcher = QTimer()
        watcher.timeout.connect(watch)
        watcher.start(1000)
        watch()

    # 联动桥：桌宠自己持有显示服务，DSH 插件只是可选的发送方。
    # 端口被占时返回 None，桌宠继续独立运行。
    import bridge
    started = bridge.start(pets[0], port)
    if started is None and alive is None:
        # 端口绑定失败但不是"已有实例在跑"，说明端口被别的程序占了——
        # 这时要说出来，否则用户会以为"联动没生效"却查不到原因。
        sys.stderr.write("dsh-pet: 端口 %s 被占用，联动已停用（桌宠本体不受影响）\n" % port)

    if "--anim" in sys.argv:
        try:
            name = sys.argv[sys.argv.index("--anim") + 1]
        except IndexError:
            name = None
        if name:
            for window in pets:
                window.animator.play(name, loop=True)
    # --hold <秒>：保持窗口一段时间后自动退出，给自检脚本留出截图窗口
    if "--hold" in sys.argv:
        try:
            seconds = float(sys.argv[sys.argv.index("--hold") + 1])
        except (IndexError, ValueError):
            seconds = 8.0
        QTimer.singleShot(int(seconds * 1000), app.quit)
    elif "--anim" in sys.argv:
        QTimer.singleShot(2500, app.quit)

    return app.exec_()


if __name__ == "__main__":
    if "--status" in sys.argv:
        sys.exit(_status())
    sys.exit(main())
