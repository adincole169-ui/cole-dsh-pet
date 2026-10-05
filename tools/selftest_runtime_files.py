# -*- coding: utf-8 -*-
"""自检：运行时真正需要的文件**必须在仓库里**。

为什么需要它：曾经把 `assets/` 整个排除在 `.gitignore` 外（当时把它当成"可由 webm
重新生成的派生物"），结果从 GitHub 装的人"图标是没有的"——`pet.py` 的 `make_icon()`
在图标缺失时退回空 `QIcon`，窗口和任务栏就都没图标，而**代码不会报错**。
图标又不是"解码帧"那种大件，它只有一百多 KB、而且是运行必需的。

教训：判断"某个文件该不该进仓库"时，不能只看它是不是派生物，还要看**运行时要不要它**。
这条自检就是把这件事变成机器可查的。

做法（而不是手写一份清单，那份清单迟早跟代码脱节）：
  用 AST 扫 `src/` 与 `main.py` 里所有 `os.path.join(<ROOT>, "a", "b", ...)` 的常量，
  得到"代码引用了哪些项目内路径"，再逐个验证存在性。

分类规则：
  * `logs/` 下的 —— 运行时自己创建，不要求存在；
  * `frames/` 下的 —— 可选（可由 webm 解码生成，`tools/setup_assets.py`）；
  * 其余 —— **必须存在**，缺一个就失败。

    python tools/selftest_runtime_files.py
"""

import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

SOURCES = ["main.py"] + ["src/" + name for name in sorted(os.listdir(os.path.join(ROOT, "src")))
                         if name.endswith(".py")]
# 这些"根变量名"代表项目根目录
ROOT_NAMES = {"ROOT", "HERE", "BASE_DIR", "PROJECT_ROOT"}
# 运行时自己创建的目录，不要求预先存在
RUNTIME_DIRS = ("logs",)
# 可选：可由 webm 生成（缺了不算错，但会在报告里提示）
OPTIONAL_DIRS = ("frames",)


def is_os_path_join(node):
    """判断是不是 `os.path.join(...)`。

    注意 AST 的形状：`os.path.join` 的 func 是
    `Attribute(attr='join', value=Attribute(attr='path', value=Name('os')))` ——
    也就是 `node.func.value` 是 **`os.path` 这个 Attribute 节点**，不是 `Name('os')`。
    第一版就是在这里判断错，扫出来 0 个路径、自检"全部通过"（假通过）。
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != "join":
        return False
    inner = func.value
    if not isinstance(inner, ast.Attribute) or inner.attr != "path":
        return False
    return isinstance(inner.value, ast.Name) and inner.value.id == "os"


def join_path(node):
    """把 `os.path.join(ROOT, "assets", "icon.ico")` 解析成 "assets/icon.ico"。

    含变量（路径是算出来的）时返回 None —— 静态判断不了，跳过。
    """
    if not is_os_path_join(node):
        return None
    if not node.args:
        return None
    first = node.args[0]
    if not (isinstance(first, ast.Name) and first.id in ROOT_NAMES):
        return None
    parts = []
    for arg in node.args[1:]:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            parts.append(arg.value)
        else:
            return None
    if not parts:
        return None
    return "/".join(parts)


def scan():
    """返回 {相对路径: 引用它的文件列表}。"""
    found = {}
    for relative in SOURCES:
        path = os.path.join(ROOT, relative)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as handle:
            try:
                tree = ast.parse(handle.read())
            except SyntaxError:
                continue
        for node in ast.walk(tree):
            joined = join_path(node)
            if joined:
                found.setdefault(joined, []).append(relative)
    return found


def classify(relative):
    head = relative.split("/")[0]
    if head in RUNTIME_DIRS:
        return "runtime"
    if head in OPTIONAL_DIRS:
        return "optional"
    return "required"


def main():
    referenced = scan()
    print()
    print("  检查运行时需要的文件（清单从代码里提取，不是手写的）")
    print("  " + "=" * 70)
    print("  %-42s %-9s %s" % ("路径", "分类", "状态"))

    required_missing = []
    optional_missing = []
    runtime_paths = []
    present = 0

    for relative in sorted(referenced):
        kind = classify(relative)
        full = os.path.join(ROOT, relative.replace("/", os.sep))
        exists = os.path.exists(full)
        if kind == "runtime":
            runtime_paths.append(relative)
            state = "运行时创建"
        elif exists:
            present += 1
            state = "存在"
        elif kind == "optional":
            optional_missing.append(relative)
            state = "缺（可选）"
        else:
            required_missing.append(relative)
            state = "**缺失**"
        print("  %-42s %-9s %s" % (relative, kind, state))

    print()
    print("  汇总")
    print("  " + "=" * 70)
    print("  代码引用的项目内路径: %d 个（其中运行时创建 %d 个）"
          % (len(referenced), len(runtime_paths)))
    print("  已存在: %d" % present)
    if optional_missing:
        print("  可选缺失（可由 webm 生成）: %s" % ", ".join(optional_missing))
        print("     提示：跑 python tools/setup_assets.py 补齐")

    print()
    if required_missing:
        print("  结论：**有 %d 个运行时必需的文件不在仓库里**：" % len(required_missing))
        for relative in required_missing:
            print("     %s   （被 %s 引用）"
                  % (relative, ", ".join(referenced[relative])))
        print()
        print("  这些文件必须提交进仓库 —— 缺了不会报错，只会静默地少功能")
        print("  （例如缺 assets/icon.ico 就是「窗口没有图标」）。")
        print("  若确实不该进仓库，请把它加进本脚本的 RUNTIME_DIRS / OPTIONAL_DIRS 并写明理由。")
        return 1

    print("  全部通过：运行时必需的文件都在。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
