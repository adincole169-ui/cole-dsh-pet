# 更新指南

> 给**已经装过 / 已经下载过**这个项目的人看的。第一次安装见 [README](README.md)。

---

## 先确认你当初是怎么拿到的

三种方式，更新方式完全不同。不确定就看目录里有没有 `.git` 文件夹：

```powershell
Test-Path .\.git      # True = 用 git clone 拿的
```

| 当初怎么拿的 | 怎么更新 | 麻烦程度 |
|---|---|---|
| **`git clone`** | `git pull`（或一条命令的 `tools\pull.ps1`） | 最简单 |
| **下载 ZIP** | 只能重新下载整个 ZIP | 麻烦，建议改用 clone |
| **装了分享包**（`install.ps1` 装的） | 用更新补丁里的 `update.ps1` | 包提供者给你 |

---

## 情况一：`git clone` 拿的（推荐做法）

### 一条命令

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\pull.ps1
```

它会依次做：**检查本地改动 → 停桌宠 → `git pull` → 依赖变了才重装 → 重启桌宠**。
先看看它会做什么、不改动任何东西：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\pull.ps1 -DryRun
```

### 手动做（知道每一步在干什么）

```powershell
# ① 先退出桌宠   ← 必须！见下面「为什么」
# ② 拉取
git pull
# ③ 只有 requirements.txt 变过才需要这步
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
# ④ 重启桌宠
.\.venv\Scripts\python.exe -X utf8 main.py
```

---

## ⚠️ 为什么必须先退出桌宠

**不停掉的话 `git pull` 会失败。** 实测：

```
$ git checkout -- webm/工作状态-忙碌点按.webm
error: unable to unlink old 'webm/工作状态-忙碌点按.webm': Invalid argument
```

原因是默认的 `frameSource: "stream"` 模式下，**每个在用的动画都挂着一个常驻 ffmpeg
进程，它把 `webm/<动画>.webm` 一直开着读**（`-stream_loop -1` 让它无限循环）。
Windows 上被别的进程打开、且**不允许删除共享**的文件无法被替换，而 `git pull`
更新素材走的正是"删除 + 重建"。

两点补充：

* 注意报错是 **`Invalid argument`** 而不是权限错误 —— 很容易让人去查文件权限，
  其实是"宠物还开着"；
* **代码文件不受影响**（Windows 上 Python 不独占 `.py`）。只有被 ffmpeg 持有的
  `webm/*.webm` 会挡住。

反正代码是**启动时加载**的，不重启就不会生效，所以"先退出"不算额外负担。

---

## 情况二：下载 ZIP 拿的

ZIP 里**没有 git 历史**，所以无法增量更新。两条路：

**A. 重新下载整个 ZIP**（约 52 MB），解压后覆盖旧目录 —— 但**要保留你自己的东西**：

```
必须保留（不要被覆盖）：
  config.user.jsonc     ← 你的个人配置（见下）
  .venv\                ← Python 虚拟环境，重装很慢
  logs\                 ← 无所谓，可以覆盖
  frames\               ← 只有 cache 模式才有；删了下次播放会重新生成
```

**B. 改用 `git clone`**（推荐）—— 以后一条命令就能更新：

```powershell
git clone https://github.com/adincole169-ui/cole-dsh-pet.git
# 把你的 config.user.jsonc 复制过去，然后：
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

---

## 情况三：装了分享包的

分享包的提供者会给你一个**更新补丁**目录，里面是 `update.ps1`：

```powershell
powershell -ExecutionPolicy Bypass -File .\update.ps1
# 只看不动：
powershell -ExecutionPolicy Bypass -File .\update.ps1 -DryRun
```

它会替换变动文件、不动虚拟环境、不动桌面快捷方式、不动 DSH 插件。

---

## 我改过配置，`git pull` 冲突了怎么办

**从今以后不会冲突了** —— 把个人改动写到 **`config.user.jsonc`** 里。

### 它是什么

一个**不进 git** 的配置文件（`.gitignore` 已排除），层级最高。仓库里那份
`config.jsonc` 保持原样，所以 `git pull` 永远碰不到你的个人改动。

### 怎么开始用

```powershell
Copy-Item config.user.example.jsonc config.user.jsonc
```

模板里每一项都有注释，**只写你要改的那几项**即可。

### 合并规则：整段替换

和 `config.jsonc` 一致 —— **顶层字段整段替换，不做深合并**。
也就是说你写了 `"physics": { "gravity": 0 }`，整个 `physics` 段就被它替换掉，
没写的字段取 `config.py` 里的内置默认值。**要改某一项就整段抄过来再改。**

### 层级优先级（低 → 高）

```
config.jsonc  →  config.user.jsonc  →  pet/<种类>-config.json
              →  （选了种类时）再叠一次 config.user.jsonc
```

最后一步是故意的：**"我个人改的"优先于"某个种类的预设"**。

### 已经改乱了怎么办

```powershell
# 看看自己改了什么
git diff config.jsonc

# 把那些改动搬到 config.user.jsonc，然后把主配置还原
git checkout -- config.jsonc
```

### 确认它生效了

```powershell
python main.py --status
```

会打印 `用户配置层: 有（config.user.jsonc，N 个顶层字段）`。

**JSON 写错会直接报错并拒绝启动**（不会静默忽略）—— 这是有意的：
静默忽略会让人以为"配置没生效是程序的 bug"。

---

## 更新后要检查什么

```powershell
# 素材与帧来源是否正常
python main.py --status

# 完整自检（约 3 分钟）
python tools\run_selftests.py
```

如果桌宠起不来，日志在 `logs\pet-run.log`：

```powershell
Get-Content .\logs\pet-run.log -Tail 40
```

---

## 关于帧缓存（`frames/`）

* 默认 **`frameSource: "stream"`**：运行时流式解码，**磁盘上不留帧**，
  所以更新时不用管 `frames/`（它根本不存在）；
* 若你改成了 **`"cache"`**：`frames/` 约 2.6 GB，且**不进 git**，更新不会碰它。
  但如果上游素材（`webm/`）变了，旧缓存会继续被用 —— 想强制重建：

```powershell
python tools\setup_assets.py --all --jobs 6 --force
```

---

## 常见问题

**Q：`git pull` 报 `Your local changes would be overwritten`？**
A：你改过被 git 跟踪的文件。把个人配置搬进 `config.user.jsonc`，或
`git stash` → `git pull` → `git stash pop`。

**Q：`git pull` 报 `unable to unlink old ...`？**
A：桌宠还在跑。先退出它（见上面「为什么必须先退出桌宠」）。

**Q：更新完桌宠没变化？**
A：代码是启动时加载的，**必须重启**。`tools\pull.ps1` 会自动重启。

**Q：想回到某个旧版本？**
A：`git log --oneline` 看提交号，然后 `git checkout <提交号>`（回去用
`git checkout main`）。注意这会让工作区处于分离头指针状态。
