# -*- coding: utf-8 -*-
"""动画状态机：动画链、播放、交叉淡化、以及"真实位移"的移动动画。

对应 dsh-pet 的行为模型：

* **动画链**——一段播完按权重选下一段，首尾相接（默认 idle 10 / turn 5 / move 5，
  再加上各分类自己的权重）；同一段不会连续播两次。
* **移动动画**——`moves.actions` 里的条目带 `leadSec` / `tailSec`：前导秒数是"真正
  开始位移"的时刻，收尾秒数是"停止位移"的时刻，中间才是行走。播放移动动画时窗口
  按朝向匀速前进。
* **转向**——朝目标方向先播 `turn` 动画，再进入移动。
* **点击回应 / 拖拽反馈**——一次性动画，播完回到链上。
* **工作状态**——由外部事件（DSH 会话事件）驱动，覆盖当前播放。
"""

import math
import random

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from move import MoveSpec

FPS_FALLBACK = 24.0

# 移动动画的基准速度（px/秒）。
#
# 每个动作可以用 `moves.actions[].params.speedScale` 在此基础上调快慢 —— 那条
# 路径就是"部分动作也可以有位移，但速度慢一点"（见 move.MoveSpec.speed_scale）。
#
# **注意**：`config.jsonc` 里 `moves` 那段的注释说 minDist/maxDist 会"运行时按
# 实际size/462 等比缩放"，但代码里**没有这回事** —— `MoveSpec.distance()` 返回的
# 就是原始像素、`config.move_specs()` 也不做缩放。所以那个说法目前是错的；
# 本常量同理，是绝对像素而不是按尺寸归一的。要真的按宠物大小缩放，得在这里
# （以及 distance 那一侧）乘上 `config.size / 462.0`。
MOVE_SPEED = 120.0


class Playing(object):
    """当前正在播放的一段动画。

    `animation` 可能暂时为 None：动画名已经定了，但帧还在后台加载。这时继续画
    `fallback` 里的旧帧，所以切换过程中画面不会空——先切状态、后到位，而不是
    反过来让界面等 IO（第一版就是同步等，结果每次切状态都僵半秒）。

    `outgoing` 是交叉淡化用的"上一层"：切换时把上一段的最后一帧快照垫在下面，
    新段叠上去淡入。**不能只让新段自己淡入**——旧段瞬间消失 + 新段从 0 开始，
    中间会出现一段两头都近乎全透明的空档，看起来就是"短暂消失"。
    """

    def __init__(self, animation, loop=False, crossfade=180, name="", fallback=None,
                 outgoing=None):
        self.name = name or (animation.name if animation else "")
        self.animation = animation
        self.fallback = fallback
        self.outgoing = outgoing          # 上一段的最后一帧 QPixmap（可 None）
        self.elapsed = 0.0
        self.loop = loop
        self.crossfade = crossfade        # 毫秒
        self.done = False

    @property
    def ready(self):
        return self.animation is not None

    @property
    def ready(self):
        return self.animation is not None

    @property
    def fps(self):
        source = self.source
        return source.fps if source is not None else FPS_FALLBACK

    @property
    def duration(self):
        source = self.source
        return source.duration if source is not None else 0.0

    @property
    def source(self):
        """真正提供帧的对象（自己的，或加载期间的顶替动画）。"""
        return self.animation if self.animation is not None else self.fallback

    def frame(self):
        """当前该画的那一帧。

        依次尝试：自己的帧 → 加载期间的顶替动画 → **交叉淡化垫层**。
        最后一档是必须的：请求 A 之后立刻切到 B 时，B 既没加载完、上一段也可能不存在
        （比如刚启动），这时如果返回 None，画面上就真的什么都没有了。
        """
        source = self.source
        if source is not None and len(source):
            return source.frame(self.frame_index())
        return self.outgoing

    def frame_index(self):
        source = self.source
        if source is None or not len(source):
            return 0
        index = int(self.elapsed * source.fps)
        if self.loop:
            return index % len(source)
        return min(index, len(source) - 1)

    def advance(self, dt):
        # 帧没到位就不推进时间，否则动画会在还没显示出来时就被判定播完
        if self.animation is None:
            return
        self.elapsed += dt
        if not self.loop and self.elapsed >= self.duration:
            self.done = True


__all__ = ["Animator", "Playing", "MoveSpec"]


class Animator(QObject):
    """驱动当前播放、并把"该移动了"翻译成速度信号。"""

    # (vx, 是否处于位移中)
    moved = pyqtSignal(float, bool)
    finished = pyqtSignal(str)

    def __init__(self, store, config, parent=None):
        super(Animator, self).__init__(parent)
        self.store = store
        self.config = config
        self.playing = None
        self.facing = 1
        self.move = None          # 当前移动规格
        self.move_left = 0.0      # 还要走多远
        self.move_vx = 0.0
        # 是否允许自动走开（"原地待着"模式会关掉）。见 `movement_allowed()`。
        self._movement_allowed = True
        self.recent = []          # 最近播过的动画名，避免连播
        self.work_status = None   # 由 DSH 事件驱动的覆盖态
        # 最近一次实际画出去的帧：切换时拿它当交叉淡化的垫层
        self.last_frame = None

        self.clock = QTimer(self)
        self.clock.timeout.connect(self._tick)
        self.clock.start(33)
        self._last = 0.0

    # -- 供外部驱动 ---------------------------------------------------------- #
    def _tick(self):
        dt = 0.033
        if self.playing is None:
            self.next_auto()
            return
        self._heal()
        self.playing.advance(dt)

        # 位移：移动动画的前导秒数之后、收尾秒数之前才是真正在走
        walking = False
        if self.move is not None:
            elapsed = self.playing.elapsed
            duration = self.playing.duration
            if elapsed >= self.move.lead_sec and (duration - elapsed) > self.move.tail_sec:
                if self.move_left > 0.0:
                    step = self.move_vx * dt
                    self.move_left -= abs(step)
                    walking = True
                else:
                    walking = False
            if (elapsed >= duration - self.move.tail_sec) or self.move_left <= 0.0:
                pass
        self.moved.emit(self.move_vx if walking else 0.0, walking)

        if self.playing.done:
            name = self.playing.name
            finished_move = self.move is not None
            self.playing = None
            self.move = None
            self.move_vx = 0.0
            self.finished.emit(name)
            if finished_move or True:
                self.next_auto()

    # -- 选择下一段 ---------------------------------------------------------- #
    def _pick(self, names):
        """按权重/随机挑一个，尽量不和刚播过的重复。"""
        candidates = [n for n in names if n and self.store.has(n) or n]
        if not candidates:
            return None
        pool = [n for n in candidates if n not in self.recent[-2:]] or candidates
        return random.choice(pool)

    def next_auto(self):
        """动画链：idle / turn / move / 分类随机动作，按权重挑。"""
        if self.work_status:
            names = self._work_names(self.work_status)
            if names:
                self.play(self._pick(names), loop=True, crossfade=200)
                return

        weights = []
        idle = self.config.actions("idle")
        if idle:
            weights.append((self.config.weight_of("idle"), "idle", idle))
        # `turn`（配置里是独立的 actions.turn，如「东张西望」）也要进池子。
        # 原先漏了它：文档字符串写着"idle / turn / move / 分类"，代码里却没有 turn，
        # 而唯一会播它的 `face()` 又没有任何调用点——结果「东张西望」永远不播。
        turn = self.config.actions("turn")
        if turn:
            weights.append((self.config.weight_of("turn"), "turn", turn))
        for category in self.config.animations.get("categories") or []:
            if not isinstance(category, dict):
                continue
            group = category.get("id") or "?"
            actions = category.get("actions") or []
            if actions:
                weights.append((float(category.get("weight", 1)), group, actions))
        moves = self._move_specs()
        # "原地待着"模式下**不把移动档加进权重池**：这样它永远不会自己走开。
        # 注意只拦"自动挑选"这一层——右键菜单的「走走看」是用户主动点的，走
        # `start_move()` 直接调用，不受这里影响。
        if moves and self.movement_allowed():
            weights.append((self.config.weight_of("move"), "move", [m.name for m in moves]))

        if not weights:
            return
        total = sum(max(0.0, w) for w, _g, _a in weights)
        if total <= 0:
            return
        roll = random.uniform(0, total)
        upto = 0.0
        for weight, group, actions in weights:
            upto += max(0.0, weight)
            if roll <= upto:
                if group == "move":
                    spec = random.choice(moves)
                    self.start_move(spec)
                else:
                    self.play(self._pick(actions), loop=False, crossfade=180)
                return

    def _move_specs(self):
        """移动规格来自配置层，这里只做转发（避免两处各解析一遍）。"""
        return self.config.move_specs()

    def movement_allowed(self):
        """是否允许**自动**走开（对应右键菜单的「原地待着」）。

        由 `PetWindow` 在切换模式时调用 `set_movement_allowed()` 设置。默认允许，
        所以没有窗口来设（例如自检里单独用 Animator）时行为不变。
        """
        return self._movement_allowed

    def set_movement_allowed(self, allowed):
        """设置是否允许自动移动；关掉时**立刻终止正在进行的移动**。"""
        self._movement_allowed = bool(allowed)
        if not self._movement_allowed:
            self.move = None
            self.move_left = 0.0
            self.move_vx = 0.0
            # 还要把已经交代给物理层的速度收回来，否则它会靠惯性继续飘
            self.moved.emit(0.0, False)

    def _work_names(self, status):
        events = self.config.animations.get("events") or {}
        names = events.get(status) if isinstance(events, dict) else None
        return names if isinstance(names, list) else []

    # -- 播放控制 ------------------------------------------------------------ #
    def play(self, name, loop=False, crossfade=180):
        """切换动画。已缓存的立即生效，未缓存的转后台加载并先播旧帧。"""
        if not name:
            return False
        cached = self.store.peek(name)
        # 出现顺序：正在播的 → 该段自己的备份帧。这样"刚接上但上一段就是它"的
        # 情况不会退化成完全没有垫层。
        previous = self.last_frame
        if previous is None and self.playing is not None:
            previous = self.playing.frame()
        fallback = self.playing.animation if self.playing else None
        if fallback is None and self.playing is not None:
            fallback = self.playing.source
        self.playing = Playing(cached, loop=loop, crossfade=crossfade,
                               name=name, fallback=None if cached else fallback,
                               outgoing=previous)
        # 钉住正在播的动画：被 LRU 淘汰掉的话，画面会直接没帧。
        # **换段时要解掉更早的钉子**：原先只 pin 不 unpin，`_pinned` 会一直增长，
        # 淘汰逻辑（`_touch` 里跳过 pinned）逐渐失效，内存里的动画只增不减。
        # 保留最近两个（当前 + 上一段）是故意的：交叉淡化要用上一段的最后一帧，
        # 立刻解钉可能在淡化那一两百毫秒里被淘汰。
        #
        # 注意 `previous` 必须在**重新赋值 self.playing 之前**取——第一版写在了后面，
        # 读到的已经是新名字，等于没生效。
        self.store.retain(name, 2)
        if cached is None and not self.store.is_loading(name):
            # 后台加载；完成时经 store.loaded → on_loaded 接上。
            # 已在加载中就不要重复排队——重复排队会让"接上"这一步永远等不到。
            self.store.request(name)
        self.recent.append(name)
        del self.recent[:-4]
        return True

    def on_loaded(self, name):
        """后台加载完成：若这正是当前等待的动画，就把它接上。"""
        if self.playing is None or self.playing.name != name or self.playing.ready:
            return
        animation = self.store.finish_load(name)
        if animation is None:
            return
        self.playing.animation = animation
        # 接上之后从这一段的开头开始计时，否则等待加载耗掉的时间会吃掉动画开头
        self.playing.elapsed = 0.0

    def _heal(self):
        """让"没帧可画"的当前段自愈。

        一种真实会发生的顺序：请求 A（后台开始加载）→ 立刻又切到 B → A 加载完成，
        但此时 `playing.name` 已经是 B，于是 `on_loaded` 直接返回，A 白白加载完、
        B 又没人接，当前段就永久没有帧——画面上就是"宠物不见了"。

        这里兜住它：当前段迟迟没有帧，就重新请求一次（`request` 对已在加载的名字
        是幂等的），或直接把已经就绪的动画接上。
        """
        if self.playing is None or self.playing.ready:
            return
        name = self.playing.name
        if not name:
            self.next_auto()
            return
        cached = self.store.peek(name)
        if cached is not None:
            self.playing.animation = cached
            self.playing.elapsed = 0.0
            return
        if not self.store.is_loading(name):
            self.store.request(name)

    def start_move(self, spec):
        """开始一段带真实位移的移动动画。

        速度 = `MOVE_SPEED` × 朝向 × `spec.speed_scale`。`speedScale` 让"部分动作
        也能有位移、但慢一点"成为可能：给它 0.3，那个动作就慢慢挪而不是快步走。
        """
        self.move = spec
        self.move_left = spec.distance()
        self.move_vx = MOVE_SPEED * self.facing * getattr(spec, "speed_scale", 1.0)
        if self.play(spec.name, loop=False, crossfade=140):
            return True
        self.move = None
        return False

    def play_click(self):
        names = self.config.actions("clicks")
        name = self._pick(names) if names else None
        if name:
            return self.play(name, loop=False, crossfade=80)
        return False

    def play_drag(self):
        names = self.config.actions("drag")
        return self.play(names[0], loop=True, crossfade=100) if names else False

    def set_work_status(self, status):
        """DSH 事件驱动的状态；None 表示回到自由活动。"""
        if status == self.work_status:
            return
        self.work_status = status
        if status is None:
            self.next_auto()
            return
        names = self._work_names(status)
        if names:
            self.play(self._pick(names), loop=True, crossfade=200)

    def set_work_status_by_anim(self, animation_name):
        """直接指定一个动画作为工作状态（桥的 mood 档位就是这么映射的）。"""
        if not animation_name:
            self.set_work_status(None)
            return
        key = "anim:" + animation_name
        if key == self.work_status:
            return
        self.work_status = key
        self.play(animation_name, loop=True, crossfade=200)

    def current_frame(self):
        """当前该画的那一帧，并记住它作为下一次交叉淡化的垫层。"""
        if self.playing is None:
            return None
        frame = self.playing.frame()
        if frame is not None:
            self.last_frame = frame
        return frame

    def outgoing_frame(self):
        """交叉淡化的垫层：上一段的最后一帧（新段已就绪后才用得到）。"""
        if self.playing is None:
            return None
        return self.playing.outgoing

    def fade_alpha(self):
        """当前段的淡入不透明度。

        只有**新段已经就绪**时才从 0 淡入——若新段还在后台加载、画面靠垫层撑着，
        这时再淡出就会把唯一可见的东西也弄没。
        """
        playing = self.playing
        if playing is None or not playing.ready or not playing.crossfade:
            return 1.0
        # 垫层也在时才是"交叉"；没有垫层就从稍高一点开始，避免整帧透明
        floor = 0.0 if playing.outgoing is not None else 0.25
        elapsed_ms = playing.elapsed * 1000.0
        if elapsed_ms >= playing.crossfade:
            return 1.0
        progress = max(0.0, min(1.0, elapsed_ms / float(playing.crossfade)))
        return floor + (1.0 - floor) * progress
