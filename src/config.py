# -*- coding: utf-8 -*-
"""配置解析：读取 dsh-pet 风格的 `config.jsonc`（允许 // 与 /* */ 注释）。

本程序是 dsh-pet 功能的独立重实现，配置格式沿用它的分层模型，这样它自带的
`config.jsonc` 可以直接拿来用：

    实例层（pets[]，每只独立）    name / id / size / display / position / 各项开关
    全局默认（本文件顶层）        physics / confineToScreen / eventsRefreshSec / 模型与提示词
    条目层（每个条目一份）        animations / animationWeights / workStatusTexts / memes / whisperPrompt

合并口径与它一致：**顶层字段是整段替换**，不做深合并。
"""

import json
import os
import re

from move import REFERENCE_WIDTH, MoveSpec

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONFIG_PATH = os.path.join(ROOT, "config.jsonc")
# **用户个人配置层**（层级最高）。
#
# 它**不进 git**（`.gitignore` 排除），所以 `git pull` 永远不会因为它产生冲突 ——
# 这正是加它的目的：使用者把"我自己改的那些"写在这里，仓库里那份 `config.jsonc`
# 保持干净，更新时不必解冲突。
#
# 格式与 `config.jsonc` 完全一致（JSONC，允许注释），合并语义也是**整段替换**：
# 这里写了 `pets` 就整段盖掉主配置的 `pets`。
# 模板见仓库里的 `config.user.example.jsonc`。
CONFIG_USER_PATH = os.path.join(ROOT, "config.user.jsonc")

DEFAULTS = {
    "size": 462,
    "display": "both",
    "position": {"corner": "top-right", "marginX": 24, "marginY": 100},
    "physics": {
        "gravity": 1400,
        "restitution": 0.78,
        "groundFriction": 2.5,
        "ceilingBounce": True,
        "throwPower": 1.0,
        "petCollision": False,
    },
    "confineToScreen": True,
    "animationWeights": {"idle": 10, "turn": 5, "move": 5},
    "eventsRefreshSec": {"balance": 1800, "whisper": 300},
}


def strip_comments(text):
    """去掉 JSONC 的行注释与块注释。

    字符串里的 `//` 不能被误删，所以按字符扫一遍，跟踪是否在字符串内。
    """
    out = []
    index = 0
    length = len(text)
    in_string = False
    while index < length:
        char = text[index]
        if in_string:
            out.append(char)
            if char == "\\" and index + 1 < length:
                out.append(text[index + 1])
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < length:
            nxt = text[index + 1]
            if nxt == "/":
                index = text.find("\n", index)
                if index < 0:
                    break
                continue
            if nxt == "*":
                end = text.find("*/", index + 2)
                index = length if end < 0 else end + 2
                continue
        out.append(char)
        index += 1
    # 允许尾随逗号
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def load(path=CONFIG_PATH):
    """读取主配置，并叠加**用户个人层**。

    用户层是 `config.user.jsonc`（**不进 git**，见 .gitignore）。加它是为了让
    "使用者改了配置"这件事**不再与 `git pull` 冲突**：仓库里那份 `config.jsonc`
    始终是干净的，个人改动写在另一个文件里，两边互不干扰。

    层级（低 → 高）：`config.jsonc` → `config.user.jsonc` → 种类文件
    → （种类路径下）再叠一次 `config.user.jsonc`。最后那一步见
    `pet_configs_for_species()` 的注释。

    传自定义 `path` 时**不叠**用户层 —— 那是测试/实验用的，不该被本机配置污染。
    """
    base = _read_jsonc(path, "config.jsonc")
    if path != CONFIG_PATH:
        return base
    user = load_user()
    return _merged(base, user) if user else base


def load_user():
    """读取用户个人配置层 `config.user.jsonc`。

    不存在就返回 `{}`（绝大多数人不需要它）。解析失败**抛错而不是忽略**：
    静默忽略会让人以为"我的配置没生效是程序的问题"，而真实原因是 JSON 写错了。
    """
    if not os.path.exists(CONFIG_USER_PATH):
        return {}
    return _read_jsonc(CONFIG_USER_PATH, "config.user.jsonc")


def _read_jsonc(path, label):
    """读一个 JSONC 文件。三个配置层共用，避免三份重复的解析代码。"""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        raw = handle.read()
    try:
        parsed = json.loads(strip_comments(raw))
    except ValueError as error:
        raise RuntimeError("%s 解析失败: %s" % (label, error))
    return parsed if isinstance(parsed, dict) else {}


def _merged(base, override):
    """整段替换语义的合并：override 里出现的键整段覆盖 base。"""
    result = dict(base)
    for key, value in (override or {}).items():
        result[key] = value
    return result


class PetConfig(object):
    """一只宠物的完整配置：品种条目 + 全局默认 + 实例覆盖。"""

    def __init__(self, entry=None, global_config=None):
        entry = dict(entry or {})
        global_config = dict(global_config or {})

        self.id = str(entry.get("id") or "main")
        self.name = str(entry.get("name") or self.id)
        # **给用户看的名字**，与 `name` 分开。
        # `name` 是内部物种名，同时是素材目录/物种配置的键（`pet/<name>-config.json`），
        # 改它会连带影响那些地方；而"任务栏叫什么、通知里叫什么叫"是纯粹的面子问题。
        # 早先窗口标题直接用 `name`，于是任务栏里显示的是"蓝毛小女仆"而不是用户叫的
        # "大肥鱼"。实例值优先，其次全局，最后退回物种名。
        # 注意 `or` 对空白字符串不生效（`'   '` 是真值），所以显式 strip 后再判断。
        candidate = str(entry.get("displayName")
                        or global_config.get("displayName") or "").strip()
        self.display_name = candidate or self.name
        self.size = int(entry.get("size") or DEFAULTS["size"])
        self.display = str(entry.get("display") or DEFAULTS["display"])
        self.position = _merged(DEFAULTS["position"], entry.get("position"))

        # 实例级开关。**这些必须真的被读**，否则改了配置却毫无效果——曾经这四项
        # 只被解析成属性、没有任何代码引用，等于摆设（`whisperEnabled=false` 也照
        # 样碎碎念、`workStatusEnabled=false` 也照样跟着会话切动画）。
        for key, default in (("balanceEnabled", False), ("whisperEnabled", False),
                             ("workStatusEnabled", True), ("fixedEnabled", False),
                             ("notificationsEnabled", True)):
            setattr(self, key, bool(entry.get(key, default)))

        # 功能字段（同样要接线，否则改了不起作用）。实例值优先，其次全局，最后默认。
        self.chat_memory_rounds = int(entry.get("chatMemoryRounds")
                                      or global_config.get("chatMemoryRounds") or 5)
        self.chat_image_enabled = bool(entry.get("chatImageEnabled",
                                                 global_config.get("chatImageEnabled", True)))
        self.chat_image_limit = int(entry.get("chatImageLimit")
                                    or global_config.get("chatImageLimit") or 10)
        self.whisper_image_enabled = bool(entry.get("whisperImageEnabled",
                                                    global_config.get("whisperImageEnabled", True)))
        self.whisper_model = entry.get("whisperModel") or global_config.get("whisperModel") or {}
        self.chat_model = entry.get("chatModel") or global_config.get("chatModel") or {}

        # 全局默认（实例可覆盖）
        self.physics = _merged(DEFAULTS["physics"], global_config.get("physics"))
        self.confine_to_screen = bool(global_config.get("confineToScreen", DEFAULTS["confineToScreen"]))
        self.refresh = _merged(DEFAULTS["eventsRefreshSec"], global_config.get("eventsRefreshSec"))

        # 条目层：动画与权重、工作状态文案
        self.animations = global_config.get("animations") or {}
        self.animation_weights = _merged(DEFAULTS["animationWeights"],
                                         global_config.get("animationWeights"))
        self.work_status_texts = global_config.get("workStatusTexts") or []
        self.whisper_prompt = global_config.get("whisperPrompt") or ""
        self.memes = global_config.get("memes") or {}

    # -- 动画查询 ------------------------------------------------------------ #
    def actions(self, group):
        """某个分类下的动画名列表。分类形如 idle / clicks / workStatus / balance / 中文自定义分类。"""
        entry = self.animations.get(group)
        if isinstance(entry, list):
            return [item for item in entry if isinstance(item, str)]
        if isinstance(entry, dict):
            result = []
            for key, value in entry.items():
                if isinstance(value, list):
                    result.extend(item for item in value if isinstance(item, str))
                elif isinstance(value, str):
                    result.append(value)
            return result
        return []

    def groups(self):
        return sorted(self.animations.keys())

    def weight_of(self, group):
        return float(self.animation_weights.get(group, 1.0))

    def move_specs(self):
        """`animations.moves.actions[]` 解析成 MoveSpec 列表。

        **距离要按宠物尺寸缩放**：配置里的 minDist/maxDist 是以「基准宠物宽
        `move.REFERENCE_WIDTH`（462）」写的，这里按 `实际 size / 462` 换算 ——
        小宠物挪小步、大宠物挪大步。这个缩放原先只写在 `config.jsonc` 的注释里、
        代码里没有，于是 size=320 的宠物仍按 462 的步长走（偏大约 44%）。
        """
        entry = self.animations.get("moves") or {}
        actions = entry.get("actions") if isinstance(entry, dict) else None
        try:
            width = float(self.size)
        except (TypeError, ValueError):
            width = 0.0
        scale = (width / REFERENCE_WIDTH) if width > 0 else 1.0
        specs = []
        for item in actions or []:
            if isinstance(item, str):
                specs.append(MoveSpec(item, scale=scale))
            elif isinstance(item, dict) and item.get("name"):
                specs.append(MoveSpec(item["name"], item.get("params"), scale=scale))
        return specs

    def event_animations(self, group):
        events = self.animations.get("events") or {}
        names = events.get(group) if isinstance(events, dict) else None
        return names if isinstance(names, list) else []


def single_pet(config=None):
    """从配置里取第一只宠物；没有就返回一份默认配置。"""
    config = config if config is not None else load()
    pets = config.get("pets") or []
    entry = pets[0] if pets and isinstance(pets[0], dict) else {}
    return PetConfig(entry, config)


def pet_configs(config=None):
    """配置里的全部宠物（多开）。

    `pets` 为空时返回一只默认配置——配置缺 `pets` 也要能跑起来，而不是显示空白。
    `display: none` 的条目会被过滤掉。
    """
    config = config if config is not None else load()
    entries = config.get("pets") or []
    result = [PetConfig(entry, config) for entry in entries if isinstance(entry, dict)]
    result = [item for item in result if item.display != "none"]
    if not result:
        result = [PetConfig({}, config)]
    return result


# ---------------------------------------------------------------- 种类扩展 --
SPECIES_DIR = os.path.join(ROOT, "pet")


def species_names():
    """`pet/<名字>-config.json` 里的全部种类名。"""
    if not os.path.isdir(SPECIES_DIR):
        return []
    names = []
    for entry in sorted(os.listdir(SPECIES_DIR)):
        if entry.endswith("-config.json"):
            names.append(entry[: -len("-config.json")])
    return names


def load_species(name):
    """读取一个种类的配置覆盖层。

    层级（与 dsh-pet 一致，**整段替换**）：种类文件顶层 → 全局 config.jsonc。
    这样加一个新种类只需在 `pet/` 放一个 JSON，不必碰主配置。
    """
    path = os.path.join(SPECIES_DIR, "%s-config.json" % name)
    return _read_jsonc(path, "种类配置 %s" % name)


def pet_configs_for_species(config, species):
    """按种类名挑选宠物：种类文件里的 `pets` 优先，否则回退到主配置。

    **用户层最后再叠一次**：`load()` 里已经叠过，但种类文件在那之后覆盖了它 ——
    而"我个人改的那一项"应当比"某个种类的预设"更优先。漏掉这一步的症状是
    "选了种类之后，我自己的配置就不生效了"。
    """
    overlay = load_species(species)
    merged = dict(config or {})
    if overlay:
        merged.update(overlay)
    user = load_user()
    if user:
        merged.update(user)
    entries = merged.get("pets") or []
    result = [PetConfig(entry, merged) for entry in entries if isinstance(entry, dict)]
    result = [item for item in result if item.display != "none"]
    if not result:
        result = [PetConfig({}, merged)]
    return result
