# -*- coding: utf-8 -*-
"""自检：用户配置层 `config.user.jsonc` 是否真的生效、且优先级正确。

为什么要有这一层（也是这个自检要守住的承诺）
--------------------------------------------
使用者改过 `config.jsonc` 之后，`git pull` 就会冲突 —— 因为那是**被 git 跟踪**的文件。
所以加了一个**不进 git** 的用户层：个人改动写在那里，仓库里那份主配置保持干净，
更新时不必解冲突。

要守住三件事：
  1. **生效**：用户层写了什么，`load()` 出来的就是什么；
  2. **优先级**：config.jsonc  →  config.user.jsonc  →  种类文件
     →（选了种类时）再叠一次 config.user.jsonc（**用户层最终优先**）；
  3. **不进 git**：`.gitignore` 里必须有它，且模板 `config.user.example.jsonc`
     必须在仓库里（否则使用者不知道格式）。

自检会**临时创建** `config.user.jsonc` 再删掉，全程不动 `config.jsonc`。

    python tools/selftest_user_config.py
"""

import io
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

USER = os.path.join(ROOT, "config.user.jsonc")
FAILED = []


def check(label, ok, detail=""):
    if isinstance(detail, (list, tuple)):
        detail = " / ".join(str(x) for x in detail if x)
    print("  %s %s%s" % ("OK  " if ok else "FAIL", label,
                         ("  " + str(detail)) if detail else ""))
    if not ok:
        FAILED.append(label)


def main():
    from config import (CONFIG_PATH, CONFIG_USER_PATH, load, load_user,
                        pet_configs, pet_configs_for_species)

    print()
    print("  自检：用户配置层 config.user.jsonc")
    print("  " + "=" * 74)

    if os.path.exists(USER):
        print("  **本机已存在 config.user.jsonc** —— 自检会临时覆盖它，先停下。")
        print("  请先备份/移走它再跑本自检。")
        return 1

    # --- 0. 静态：路径、模板、gitignore ---
    check("CONFIG_USER_PATH 指向 config.user.jsonc",
          os.path.basename(CONFIG_USER_PATH) == "config.user.jsonc", CONFIG_USER_PATH)
    check("模板 config.user.example.jsonc 在仓库里",
          os.path.isfile(os.path.join(ROOT, "config.user.example.jsonc")))
    ignored = subprocess.run(["git", "check-ignore", "-q", "config.user.jsonc"],
                             cwd=ROOT, capture_output=True).returncode == 0
    check("config.user.jsonc 被 .gitignore 排除（这样 pull 才不会冲突）", ignored)
    tracked = subprocess.run(["git", "ls-files", "config.user.jsonc"],
                             cwd=ROOT, capture_output=True, text=True).stdout.strip()
    check("config.user.jsonc 没有被 git 跟踪", not tracked, tracked)

    # --- 1. 不存在时应当是无害的 ---
    check("不存在时 load_user() 返回空", load_user() == {}, load_user())
    base = load()
    check("不存在时 load() 仍能读到主配置", bool(base.get("pets")), "pets=%d" % len(base.get("pets") or []))

    try:
        # --- 2. 生效 ---
        with io.open(USER, "w", encoding="utf-8") as handle:
            handle.write(
                "{\n"
                "  // 自检临时写入\n"
                "  \"confineToScreen\": true,\n"
                "  \"frameSource\": \"cache\",\n"
                "  \"physics\": { \"gravity\": 1234 }\n"
                "}\n")
        user = load_user()
        check("写进去之后 load_user() 读得到", user.get("frameSource") == "cache", user)
        merged = load()
        check("load() 叠加了用户层（frameSource）",
              merged.get("frameSource") == "cache", merged.get("frameSource"))
        check("load() 叠加了用户层（confineToScreen）",
              merged.get("confineToScreen") is True, merged.get("confineToScreen"))
        check("整段替换语义（physics 被整段盖掉）",
              merged.get("physics") == {"gravity": 1234}, merged.get("physics"))
        check("没写的顶层字段保留主配置的值",
              bool(merged.get("pets")) and bool(merged.get("animations")),
              "pets=%d animations=%s" % (len(merged.get("pets") or []),
                                         bool(merged.get("animations"))))

        # 用户层改的 physics 要真的进 PetConfig
        pets = pet_configs(merged)
        check("用户层的 physics 进了 PetConfig",
              pets[0].physics.get("gravity") == 1234, pets[0].physics)

        # --- 3. 优先级：用户层要盖过种类文件 ---
        species = None
        for name in ("夜猫",):
            if os.path.isfile(os.path.join(ROOT, "pet", "%s-config.json" % name)):
                species = name
                break
        if species:
            from config import load_species
            overlay = load_species(species)
            # **只能挑标量键**（str/bool/int/float）来覆盖。
            # 踩过：这里原先随手取了 `sorted(overlay.keys())[0]`，而它恰好是
            # `animationWeights`（字典）—— 把字典覆盖成字符串之后 `PetConfig.__init__`
            # 直接崩在 `_merged(DEFAULTS["animationWeights"], "字符串")` 上，
            # 报错还指向 `_merged` 内部，看起来像 config.py 的问题。
            scalar_keys = [k for k, v in overlay.items()
                           if isinstance(v, (bool, str, int, float))]
            if scalar_keys:
                key = scalar_keys[0]
                with io.open(USER, "w", encoding="utf-8") as handle:
                    handle.write("{\n  \"%s\": \"__USER_WINS__\"\n}\n" % key)
                pet_configs_for_species(load(), species)   # 不该抛异常
                active = load().get(key)
                check("用户层在种类之后仍生效（覆盖种类文件的 %s）" % key,
                      active == "__USER_WINS__", active)
                # 反向确认：去掉用户层时应回到种类文件的值
                os.remove(USER)
                without = load().get(key)
                check("去掉用户层后回到种类文件的值（%s）" % key,
                      without != "__USER_WINS__", without)
            else:
                print("  （种类文件 %s 里没有标量键，跳过优先级检查）" % species)
        else:
            print("  （没有种类文件，跳过优先级检查）")

        # --- 4. 解析失败必须报错，不能静默忽略 ---
        with io.open(USER, "w", encoding="utf-8") as handle:
            handle.write("{ 这不是合法 JSON }\n")
        raised = False
        try:
            load()
        except RuntimeError as error:
            raised = "config.user.jsonc" in str(error)
        check("JSON 写错时报错并指明是哪个文件（不静默忽略）", raised)

    finally:
        if os.path.exists(USER):
            os.remove(USER)
        # 确认清干净了
        check("自检结束后 config.user.jsonc 已删除（没留下痕迹）",
              not os.path.exists(USER))
        after = load()
        check("删掉之后配置回到主配置的值",
              after.get("frameSource") != "cache" or "frameSource" not in (base or {}),
              after.get("frameSource"))

    print()
    if FAILED:
        print("  失败 %d 项：%s" % (len(FAILED), "、".join(FAILED)))
        return 1
    print("  全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
