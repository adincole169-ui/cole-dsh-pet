# -*- coding: utf-8 -*-
"""核对 GitHub 上的内容：修复是否真的在远程，以及有没有混进不该有的东西。

只看"本地 == 远程的提交号"不够 —— 那只说明两边指向同一个提交，不说明提交里
真的有修复。所以要**直接读远程对象**（`git show origin/main:<路径>`）来验证。

判据必须走 **AST**，不能用子串匹配：修复后的注释里正好引用了旧写法
（`# 早先在这里写 self._placed_at = ...`），朴素匹配会把注释当成代码，
报出假失败（第一版就是这样）。

    python tools/verify_remote_fix.py
"""

import ast
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git(args):
    done = subprocess.run(["git", "-c", "core.quotePath=false"] + args,
                          cwd=ROOT, capture_output=True)
    return done.returncode, done.stdout.decode("utf-8", "replace")


def remote_file(path):
    code, out = git(["show", "origin/main:%s" % path])
    return out if code == 0 else None


def find_function(tree, name, class_name=None):
    """按名字找函数节点；给了 class_name 就只在那个类里找。"""
    if class_name:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                            and item.name == name:
                        return item
        return None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def self_attribute_writes(function_node, attribute):
    """函数体里对 `self.<attribute>` 的赋值（只看真实代码，注释天然被排除）。"""
    found = []
    for node in ast.walk(function_node):
        if not isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if (isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "self"
                    and target.attr == attribute):
                found.append(getattr(node, "lineno", 0))
    return found


def attribute_uses(tree, attribute):
    """整个模块里 `self.<attribute>` 出现的行号（真实代码）。"""
    lines = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and node.attr == attribute
                and isinstance(node.value, ast.Name) and node.value.id == "self"):
            lines.append(getattr(node, "lineno", 0))
    return lines


def calls_of(tree, dotted):
    """模块里调用 `X.y()` 的行号（用于数 primaryScreen 的真实调用）。"""
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "availableGeometry":
                target = node.func.value
                if (isinstance(target, ast.Call)
                        and isinstance(target.func, ast.Attribute)
                        and isinstance(target.func.value, ast.Name)
                        and target.func.value.id == dotted[0]
                        and target.func.attr == dotted[1]):
                    lines.append(getattr(node, "lineno", 0))
    return lines


FAILED = []


def check(label, ok, detail=""):
    print("  %s %-46s %s" % ("OK  " if ok else "FAIL", label, detail))
    if not ok:
        FAILED.append(label)


def main():
    print()
    print("  核对 GitHub 上的内容")
    print("  " + "=" * 70)

    _code, local = git(["rev-parse", "HEAD"])
    _code, remote = git(["rev-parse", "origin/main"])
    local, remote = local.strip(), remote.strip()
    _code, subject = git(["log", "-1", "--format=%h %s", "origin/main"])
    print("  本地 HEAD   : %s" % local[:12])
    print("  远程 main   : %s" % remote[:12])
    print("  远程最新提交: %s" % subject.strip()[:60])
    print()
    check("本地与远程指向同一个提交", local == remote,
          "" if local == remote else "**不一致**")

    source = remote_file("src/pet.py")
    if source is None:
        check("远程能读到 src/pet.py", False)
        return 1
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        check("远程 src/pet.py 语法可解析", False, str(error))
        return 1

    # --- 修复一：对齐窗口 ---
    print()
    print("  修复一：启动对齐窗口会过期")
    init = find_function(tree, "__init__", "PetWindow")
    place = find_function(tree, "_place_initial", "PetWindow")
    settle = find_function(tree, "_settle_initial_placement", "PetWindow")
    took_over = find_function(tree, "_user_took_over", "PetWindow")

    check("_settle_deadline 在 __init__ 里被设置",
          bool(init) and bool(self_attribute_writes(init, "_settle_deadline")))
    check("_place_initial() 不再写 _placed_at",
          bool(place) and not self_attribute_writes(place, "_placed_at"),
          "写了第 %s 行" % self_attribute_writes(place, "_placed_at") if place else "没有该函数")
    check("_settle_initial_placement() 读 _settle_deadline",
          bool(settle) and bool(attribute_uses(settle, "_settle_deadline")))
    check("_user_took_over() 清掉 _settle_deadline",
          bool(took_over) and bool(self_attribute_writes(took_over, "_settle_deadline")))
    check("模块里已无 _placed_at 的真实引用",
          not attribute_uses(tree, "_placed_at"),
          "第 %s 行" % attribute_uses(tree, "_placed_at") if attribute_uses(tree, "_placed_at") else "")

    # --- 修复二：多显示器 ---
    print()
    print("  修复二：按宠物所在屏幕计算")
    check("存在模块级 screen_area_for()",
          find_function(tree, "screen_area_for") is not None)
    check("存在方法 current_screen_area()",
          find_function(tree, "current_screen_area", "PetWindow") is not None)
    primary = calls_of(tree, ("QApplication", "primaryScreen"))
    # 允许的两处都是"启动最早期还没位置"的兜底：screen_area_for 的末行、
    # current_screen_area 的提前返回。除此之外不该再有。
    check("primaryScreen 只剩 2 处（都是启动兜底）", len(primary) == 2,
          "实为 %d 处，第 %s 行" % (len(primary), primary))

    # --- 新增的测试与工具 ---
    print()
    wanted = [
        "tools/selftest_settle_window.py",
        "tools/selftest_clickable_area.py",
        "tools/check_without_numpy.py",
        "tools/verify_no_placement_drift.py",
        "tools/verify_remote_fix.py",
        "tools/asset_pipeline.py",
        "tools/setup_assets.py",
        "tools/verify_asset_origin.py",
        "ASSETS.md",
        "requirements-assets.txt",
    ]
    _code, tracked = git(["ls-tree", "-r", "--name-only", "origin/main"])
    tracked_set = set(line for line in tracked.splitlines() if line)
    missing = [path for path in wanted if path not in tracked_set]
    check("新增的测试/工具/文档都已在远程", not missing,
          "缺 %s" % missing if missing else "%d 项齐" % len(wanted))

    print()
    bad_dirs = [name for name in tracked_set
                if name.split("/")[0] in ("frames", "assets", "memes", "logs", "dist")]
    bad_temp = [name for name in tracked_set
                if os.path.basename(name) in ("_commit_msg.txt", "_msg2.txt",
                                              "_msg3.txt", "_msg4.txt")]
    webm = [name for name in tracked_set if name.startswith("webm/")]

    check("不含 frames/assets/memes/logs/dist", not bad_dirs,
          str(bad_dirs[:3]) if bad_dirs else "")
    check("不含临时提交信息文件", not bad_temp, str(bad_temp) if bad_temp else "")
    check("随仓库分发的 webm 是 106 个", len(webm) == 106, "实为 %d" % len(webm))
    check("远程文件总数合理", 190 <= len(tracked_set) <= 220,
          "%d 个" % len(tracked_set))

    print()
    readme = remote_file("README.md") or ""
    assets = remote_file("ASSETS.md") or ""
    check("README 顶部有原作者署名", "PC2005-cloud/dsh-pet" in readme[:600])
    check("ASSETS.md 记录了素材出处与许可",
          "PC2005-cloud/dsh-pet" in assets and "禁止商用" in assets)

    print()
    print("  结论")
    print("  " + "=" * 70)
    if FAILED:
        print("  %d 项没通过：" % len(FAILED))
        for label in FAILED:
            print("     %s" % label)
        return 1
    print("  GitHub 上的内容已包含全部修复，且不含不该有的文件。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
