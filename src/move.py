# -*- coding: utf-8 -*-
"""移动规格：一条"带真实位移的动画"的参数。

单独成一个模块，是为了让配置层（`config.py`）也能构造它。放到 `animator.py` 里
会拖进 PyQt，而配置解析在命令行/自检场景下不该需要 Qt。
"""

import random

# 移动距离的**基准宠物宽度**（逻辑 px）。
#
# `config.jsonc` 里 minDist/maxDist 是"以基准宠物宽为准"写的，运行时按
# `实际 size / 这个值` 等比缩放 —— 小宠物挪小步、大宠物挪大步，步长才与人物大小匹配。
# 上游 dsh-pet 的默认 size 就是 462，本项目的 `PET_DEFAULT_SIZE` 也取同一个值。
#
# 踩过：这个缩放**一直只写在文档里、代码里没有**。于是 size=320 的宠物仍按 462 的
# 步长走，步长偏大 `462/320 - 1 ≈ 44%`，看起来像"滑过去"而不是"走"。
REFERENCE_WIDTH = 462.0


class MoveSpec(object):
    """来自配置 `animations.moves.actions[]` 的一条移动动画。

    `leadSec` 是"真正开始位移"的时刻，`tailSec` 是"停止位移"的时刻——两者之间
    才是走路的区间，这样动画的前导与收尾动作不会让窗口凭空滑动。

    `speedScale` 是**速度系数**（默认 1.0，即走路速度）。用途是让"部分动作也能
    有位移，但慢一点"：把那个动作放进 `moves.actions`，给较短的 `minDist/maxDist`
    与小于 1 的 `speedScale`，它就会慢慢挪，而不是像走路那样快。

    `scale` 是**尺寸缩放**（由 `config.move_specs()` 按 `size / REFERENCE_WIDTH`
    传来）。它只作用在距离上：`margin`（贴边安全距）是屏幕几何、不随宠物大小变，
    所以不缩放。
    """

    def __init__(self, name, params=None, scale=1.0):
        self.name = name
        params = dict(params or {})
        try:
            self.scale = float(scale) if float(scale) > 0 else 1.0
        except (TypeError, ValueError):
            self.scale = 1.0
        self.min_dist = float(params.get("minDist", 60)) * self.scale
        self.max_dist = float(params.get("maxDist", 240)) * self.scale
        # 贴边安全距不缩放：它是"别把角色贴到屏幕边上"的余量，与宠物大小无关
        self.margin = float(params.get("margin", 20))
        self.lead_sec = float(params.get("leadSec", 2.0))
        self.tail_sec = float(params.get("tailSec", 2.0))
        # 速度系数：0.3 = "以走路速度的 30% 慢慢挪"。负数无意义，钳到 0。
        try:
            self.speed_scale = max(0.0, float(params.get("speedScale", 1.0)))
        except (TypeError, ValueError):
            self.speed_scale = 1.0

    def distance(self):
        return random.uniform(self.min_dist, self.max_dist)

    def __repr__(self):
        return "MoveSpec(%r, %s-%s px, speed x%.2f, scale %.2f)" % (
            self.name, self.min_dist, self.max_dist, self.speed_scale, self.scale)
