# -*- coding: utf-8 -*-
"""移动规格：一条"带真实位移的动画"的参数。

单独成一个模块，是为了让配置层（`config.py`）也能构造它。放到 `animator.py` 里
会拖进 PyQt，而配置解析在命令行/自检场景下不该需要 Qt。
"""

import random


class MoveSpec(object):
    """来自配置 `animations.moves.actions[]` 的一条移动动画。

    `leadSec` 是"真正开始位移"的时刻，`tailSec` 是"停止位移"的时刻——两者之间
    才是走路的区间，这样动画的前导与收尾动作不会让窗口凭空滑动。

    `speedScale` 是**速度系数**（默认 1.0，即走路速度）。用途是让"部分动作也能
    有位移，但慢一点"：把那个动作放进 `moves.actions`，给较短的 `minDist/maxDist`
    与小于 1 的 `speedScale`，它就会慢慢挪，而不是像走路那样快。
    """

    def __init__(self, name, params=None):
        self.name = name
        params = dict(params or {})
        self.min_dist = float(params.get("minDist", 60))
        self.max_dist = float(params.get("maxDist", 240))
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
        return "MoveSpec(%r, %s-%s px, speed x%.2f)" % (
            self.name, self.min_dist, self.max_dist, self.speed_scale)
