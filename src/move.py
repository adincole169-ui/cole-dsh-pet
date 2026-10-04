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
    """

    def __init__(self, name, params=None):
        self.name = name
        params = dict(params or {})
        self.min_dist = float(params.get("minDist", 60))
        self.max_dist = float(params.get("maxDist", 240))
        self.margin = float(params.get("margin", 20))
        self.lead_sec = float(params.get("leadSec", 2.0))
        self.tail_sec = float(params.get("tailSec", 2.0))

    def distance(self):
        return random.uniform(self.min_dist, self.max_dist)

    def __repr__(self):
        return "MoveSpec(%r, %s-%s px)" % (self.name, self.min_dist, self.max_dist)
