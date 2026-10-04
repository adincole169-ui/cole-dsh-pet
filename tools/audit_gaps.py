# -*- coding: utf-8 -*-
"""盘点当前实现与配置/文档之间的缺口。

用户问"还有哪些问题"时，答案必须来自核实而不是记忆，所以这里把三类事对一遍：
  1. 配置里有、但没有任何代码引用的字段（改了不生效）；
  2. DEVNOTES 里与代码不符的描述；
  3. 未实现或未验证的功能点。

    python tools/audit_gaps.py
"""

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

# 这些顶层键是给别的东西（或纯文档）用的，不算缺口
IGNORE = {
    "schemaVersion", "packageVersion",
    # `memes` 里的键是表情名，只在 JSON 里出现、由插件按名字用——代码不会按名字
    # 引用某个具体表情，所以这里不算缺口。
    "Ciallo",
}


def read(path):
    with io.open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def all_python_source():
    chunks = []
    for root, _dirs, files in os.walk(os.path.join(ROOT, "src")):
        for name in files:
            if name.endswith(".py"):
                chunks.append(read(os.path.join(root, name)))
    for name in ("main.py",):
        chunks.append(read(os.path.join(ROOT, name)))
    return "\n".join(chunks)


def main():
    config_text = read(os.path.join(ROOT, "config.jsonc"))
    source = all_python_source()

    keys = sorted(set(re.findall(r'^\s*"([A-Za-z][A-Za-z0-9]*)"\s*:', config_text, re.M)))
    missing = []
    for key in keys:
        if key in IGNORE:
            continue
        camel = key[0].lower() + key[1:]
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower()
        if key not in source and camel not in source and snake not in source:
            missing.append(key)

    print("=== 1. 配置里有、代码从未引用的字段（改了不生效）===")
    if missing:
        for key in missing:
            print("  - %s" % key)
    else:
        print("  （无）")

    print()
    print("=== 2. DEVNOTES 里的配置生效说明 ===")
    # 开发文档已从 README.md 改名成 DEVNOTES.md（README 现在是公开门面，
    # 面向使用者；踩坑记录这类开发内容归 DEVNOTES）。
    readme = read(os.path.join(ROOT, "DEVNOTES.md"))
    # 只在"声明"里找，跳过我自己写的那段"这句是错的"的更正说明——
    # 否则改正说明本身会被当成遗留问题，每次审计都误报。
    claims = []
    for line in readme.splitlines():
        if line.lstrip().startswith(">"):
            continue          # 引用块里的是更正说明
        if "重载配置" in line or "每次切动画都读" in line:
            if "那是错的" in line or "之前这里写着" in line:
                continue
            claims.append(line.strip())
    if claims:
        for line in claims:
            print("  - %s" % line[:90])
    else:
        print("  （未发现过时声明）")

    print()
    print("=== 3. 未实现 / 未验证的功能 ===")
    checks = [
        ("physics.petCollision（宠物互撞）", "petCollision" in source and
         "confine" in source and "def _collide" in source),
        ("通知开关（notificationsEnabled）", "notificationsEnabled" in source),
        ("对话轮数读宠物配置（chatMemoryRounds）", "chatMemoryRounds" in source),
        ("配图开关（chatImageEnabled / whisperImageEnabled）",
         "chatImageEnabled" in source and "whisperImageEnabled" in source),
        ("模型指定（whisperModel / chatModel）",
         "whisperModel" in source and "chatModel" in source),
        ("工作状态开关（workStatusEnabled）", "workStatusEnabled" in source),
        ("用量分档开关（balanceEnabled）", "balanceEnabled" in source),
        ("碎碎念开关（whisperEnabled）", "whisperEnabled" in source),
    ]
    for label, present in checks:
        print("  [%s] %s" % ("已接" if present else "未接", label))

    print()
    print("=== 4. 帧缓存占用 ===")
    try:
        import asset_pipeline
        names = asset_pipeline.list_animations()
        cached = [n for n in names if asset_pipeline.is_cached(n)]
        size = asset_pipeline.cache_size() / 1048576.0
        print("  已缓存 %d/%d 个动画，占用 %.0f MB" % (len(cached), len(names), size))
        print("  （按需解码：用到哪个才生成哪个；`tools/asset_pipeline.py clean` 可整体清空）")
    except Exception as error:
        print("  查询失败: %s" % error)

    print()
    print("=== 5. 配置字段是否**真的被使用**（不只是被解析）===")
    # 第 1 节只查"字段名有没有出现在代码里"，而 `config.py` 里那行 `setattr(...)`
    # 本身就满足它——所以 `fixedEnabled` 明明没人读，却一直显示"已接"。
    # 这里改查"**在 config.py 之外**有没有人用"，并且要排除掉只是一串字符串
    # （例如 `("fixedEnabled", False)` 这种解析表）的情况。
    import re as _re
    source_files = []
    for folder in (os.path.join(ROOT, "src"), ROOT):
        for entry in sorted(os.listdir(folder)):
            if entry.endswith(".py"):
                path = os.path.join(folder, entry)
                if os.path.abspath(path) == os.path.abspath(os.path.join(ROOT, "src", "config.py")):
                    continue
                if entry in ("audit_gaps.py",):
                    continue
                try:
                    source_files.append((entry, io.open(path, encoding="utf-8").read()))
                except Exception:
                    pass

    fields = ["fixedEnabled", "notificationsEnabled", "whisperEnabled",
              "workStatusEnabled", "balanceEnabled", "chatImageEnabled",
              "whisperImageEnabled", "chatMemoryRounds", "whisperModel", "chatModel"]
    # 配置键是 camelCase，而 `PetConfig` 把它挂成 snake_case 属性，代码里按属性访问。
    # 只查 camelCase 会把"确实用了"的字段误报成未接（第一版就误报了 5 项）。
    def snake(name):
        return _re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()

    unused = []
    for field in fields:
        names = {field, snake(field)}
        used_anywhere = False
        for name, text in source_files:
            for candidate in names:
                for pattern in (r'getattr\([^)]*[\'"]%s[\'"]' % candidate,
                                r'[\'"]%s[\'"]\s*[,)]' % candidate,
                                r'\.%s\b' % candidate,
                                r'config\.get\([\'"]%s[\'"]' % candidate):
                    if _re.search(pattern, text):
                        used_anywhere = True
                        break
                if used_anywhere:
                    break
            if used_anywhere:
                break
        if not used_anywhere:
            unused.append(field)
    if unused:
        for field in unused:
            print("  [未接] %s —— 改了不会有任何效果" % field)
    else:
        print("  （所有字段都在 config.py 之外被真正读取）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
