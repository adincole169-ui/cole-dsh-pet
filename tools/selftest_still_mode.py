# -*- coding: utf-8 -*-
"""自检：右键菜单「原地待着」必须真的让它不动。

为什么单独测：用户报过"在原地待着模式下还是会移动"。根因是那个菜单项只做了
`setattr(self, "mode", k)`，而**代码里没有任何地方读 `self.mode`**——一个纯装饰的
开关。同类问题在这个项目里出现过多次（`whisperEnabled`、`workStatusEnabled`、
`fixedEnabled` 都曾经是"改了没效果"），所以这里用真实位移来钉住它。

判定方式：不开窗口画面，直接看**窗口横向位置是否变化**。

    python tools/selftest_still_mode.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

import random                                 # noqa: E402

from config import load, pet_configs          # noqa: E402
from frames import FrameStore                 # noqa: E402
from main import build_app                    # noqa: E402
from pet import PetWindow                     # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label,
                         ("  " + detail) if detail else ""))
    if not ok:
        FAILED.append(label)


def pump(app, window, seconds=1.0, step=0.033):
    """把**真实的两个 30fps 时钟**都推一段。

    程序里有两条独立时钟（都在 33ms）：`Animator.clock -> _tick()` 推进动画与移动，
    `PetWindow.physics_clock -> tick()` 做物理与气泡。自检里没有事件循环替我们跑它们，
    所以必须**两个都调**——只调 `window.tick()` 时动画时钟不走，`moved` 信号永远不会
    发出，会得出"自由活动也不动"的错误结论（我第一版就是这么错的）。
    """
    steps = max(1, int(seconds / step))
    for _ in range(steps):
        window.animator._tick()      # 动画时钟：推进移动、发 moved 信号
        window.tick()                # 物理时钟：积分位置、气泡计时
        window._repaint()
        app.processEvents()


def force_move_pick(window):
    """让 `next_auto()` **必定**挑到移动档。

    前两版都写错了，记在这里免得再犯：
      1. 把 `uniform` 固定成大数想让 roll 落到最后一组 —— 抽中的却是分类随机动作
         （权重池里还有 categories，顺序不由我控制）；
      2. 把 `uniform` 固定成 `0.0` —— 但 `MoveSpec.distance()` **也调用
         `random.uniform`**，于是每个移动的距离都变成 0 像素。测试把要测的东西自己
         破坏了，表现为"自由活动也不动"，害我查了半天实现。
    现在只劫持**第一次**调用（档位抽取），随后的调用（距离计算）放行。
    """
    config = window.config
    original_actions = config.actions
    original_animations = config.animations
    original_uniform = random.uniform
    budget = [1]

    def once(a, b):
        if budget[0] > 0:
            budget[0] -= 1
            return 0.0
        return original_uniform(a, b)

    # 权重池里有四类：idle / turn / categories / move。要让"必定挑到移动档"，
    # **前四类都得清空**——早先只清了 idle 与 categories，漏了 `turn`（东张西望，
    # 权重 5）。它虽然不产生位移，却仍有约 6% 概率被抽中，于是这个自检大约每 15 次
    # 失败 1 次（实测 5 次里错 2 次）。**概率性自检比没有自检更糟**：它会让人怀疑
    # 实现，而真正的问题在测试自己。
    config.actions = lambda key: [] if key in ("idle", "turn") else original_actions(key)
    config.animations = dict(original_animations, categories=[])
    # **必须先把 workStatus 清掉**：`next_auto()` 开头就是
    # `if self.work_status:` → 直接播工作动画并 return，根本走不到权重池。
    # 而桌宠在跑的时候，DSH 插件一直在推实时状态——一旦是忙碌态，这个自检就会
    # 莫名其妙地失败（实测过：插件重启后本项报了 1 项失败）。
    window.animator.work_status = None
    random.uniform = once
    try:
        for _ in range(3):
            window.animator.next_auto()
    finally:
        config.actions = original_actions
        config.animations = original_animations
        random.uniform = original_uniform


def main(argv):
    app = build_app([argv[0]])
    config = pet_configs(load())[0]
    window = PetWindow(config, FrameStore(keep=6))
    window.show()
    # 关掉"启动期按角色自动对齐初始位置"（见 PetWindow._settle_initial_placement）：
    # 本自检在启动窗口期内反复移动宠物测位移，自动对齐会把它拽回角落，
    # 于是"自由活动会走开"变成 0 像素、"原地待着不动"反而有位移（实测过 3 项失败）。
    window._user_took_over()
    # 与**实时插件隔离**：桌宠在跑的时候 DSH 会一直往它推 mood/workStatus，而工作状态
    # 会让 `next_auto()` 直接播工作动画、不走权重池，于是本自检会莫名其妙地失败
    # （实测过：插件重启后就报过 1 项失败）。断开桥信号，让这里只测本进程的逻辑。
    try:
        window.mood_signal.disconnect(window.on_bridge_message)
    except TypeError:
        pass
    name = (config.actions("idle") or ["待机呼吸休闲"])[0]
    window.store.animation(name)
    window.animator.play(name, loop=True)
    # 移动动画必须**先解码**：`start_move()` 内部会 `play()`，未缓存时它转后台加载
    # （首次约 20 秒）并返回 False，移动根本没开始。不预热的话前两项会误判成
    # "自由活动也不动"。
    for spec in config.move_specs():
        window.store.animation(spec.name)
    pump(app, window, 0.4)

    print("  配置: fixedEnabled=%s  move 权重=%.0f  移动规格=%d 个"
          % (getattr(config, "fixedEnabled", None), config.weight_of("move"),
             len(config.move_specs())))

    print("  -- 自由活动：应该会走 --")
    window.set_mode("roam")
    start = window.pos_x
    force_move_pick(window)
    pump(app, window, 3.5)          # 移动动画有 lead_sec（最大 2.0s）前导，必须跑过它
    moved = abs(window.pos_x - start)
    check("自由活动模式下会自动走开", moved > 1.0, "位移 %.0f 像素" % moved)

    print("  -- 原地待着：不许动 --")
    window.set_mode("still")
    # 先人为给一个速度，模拟"切模式时还带着惯性"
    window.vx = 400.0
    start = window.pos_x
    force_move_pick(window)
    pump(app, window, 2.0)
    drift = abs(window.pos_x - start)
    check("原地待着模式下位置不变（含惯性）", drift < 0.5, "位移 %.2f 像素" % drift)

    print("  -- 原地待着：反复触发也不动 --")
    start = window.pos_x
    for _ in range(5):
        force_move_pick(window)
        pump(app, window, 0.3)
    drift = abs(window.pos_x - start)
    check("连续触发 5 次仍然不动", drift < 0.5, "位移 %.2f 像素" % drift)

    print("  -- 手动「走走看」不该被模式挡住 --")
    window.set_mode("still")
    start = window.pos_x
    window.roam()                    # 等价于右键菜单的「走走看」
    pump(app, window, 3.5)          # 同样要跑过 lead_sec
    manual = abs(window.pos_x - start)
    check("原地待着下用户主动点的走动仍生效", manual > 1.0,
          "位移 %.0f 像素（模式只拦自动移动）" % manual)

    print("  -- 切回自由活动要能恢复 --")
    window.set_mode("roam")
    start = window.pos_x
    force_move_pick(window)
    pump(app, window, 3.5)
    back = abs(window.pos_x - start)
    check("切回自由活动后又能走", back > 1.0, "位移 %.0f 像素" % back)

    print("  -- 菜单项与状态一致 --")
    window.set_mode("still")
    check("set_mode 会同步 animator", not window.animator.movement_allowed())
    window.set_mode("roam")
    check("切回后 animator 恢复允许", window.animator.movement_allowed())

    print("  -- fixedEnabled=true 应作为启动模式 --")
    config.fixedEnabled = True
    other = PetWindow(config, FrameStore(keep=2))
    check("fixedEnabled=true 时初始为原地待着", other.mode == "still",
          "mode=%s" % other.mode)
    check("并在 animator 上生效", not other.animator.movement_allowed())
    other.close()

    window.close()
    print("失败 %d 项" % len(FAILED) if FAILED else "全部通过")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
