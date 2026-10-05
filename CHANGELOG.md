# 变更日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

**怎么看这个文件**：想知道"更新之后会有什么变化、值不值得更新"就看这里；
想知道"**具体怎么更新**"看 [UPDATE.md](UPDATE.md)。

---

## [未发布]

### 计划中
- 看情况：把 `stream` 模式下的 webm 占用问题彻底解决（目前更新素材前必须先退出桌宠，
  原因见 [UPDATE.md](UPDATE.md) 的「为什么必须先退出桌宠」）

---

## [1.0.0] - 2026-10-06

第一个公开版本。功能上对齐 [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet)，
但**自研实现**（当初动手时本机 DSH 是 `0.1.0-rc.7`，而原插件要求 `^0.2.0-rc.1`，装不上）。

### 核心功能

- **透明无边框桌宠**：常驻置顶、不占任务栏、多显示器可用、关机重启后位置保留
- **DSH 会话联动**：把会话事件映射到六档工作状态动画 + 气泡文案
  （思考 / 忙碌 / 完成 / 等待授权 / 出错 / 空闲）
- **碎碎念**：按周期让桌宠说一句，可用当前对话的模型
- **余额/用量分档**：按额度切动画，拿不到余额时退回会话用量
- **点击回应、拖拽抛掷、物理（重力/恢复系数/地面摩擦）**
- **右键菜单**：自由活动 / 原地待着、走走看、换种类、设置、对话
- **多宠物与「种类」覆盖层**：`pet/<名字>-config.json` 加一个新种类不必碰主配置

### 素材与帧来源

- **随仓库附带 106 个 webm 动画源**（51.8 MB，与上游逐字节相同，已核实）
- **默认 `frameSource: "stream"`**：运行时用 ffmpeg 流式解码，**磁盘上不留任何帧**
  - 实测：起 ffmpeg 到首帧 **94 ms**，首帧之后每帧 **0.6 ms**（24fps 预算 41.7 ms，余量约 70 倍）
  - 有界环形缓冲（16 帧 ≈ 14 MB/动画）+ **按消费位置背压**（生产者比消费者快 70 倍，
    只按缓冲容量限流会把消费者要的帧覆盖掉）
  - 与旧的预解码 PNG 缓存**逐像素相同**（实测最大差 0/255）
  - **clone 下来直接就能跑，不需要任何准备步骤**
- 可选 `frameSource: "cache"`：预解码成 PNG（约 2.6 GB），零解码延迟
- 图标与表情包随仓库分发（`assets/` 4 个、`memes/` 8 个）——
  缺了图标界面只静默少功能，所以必须进仓库

### 更新机制

- **`config.user.jsonc`**：不进 git 的个人配置层，让"我改过配置"不再与 `git pull` 冲突
- **`tools/pull.ps1`**：一条命令 —— 检查本地改动 → 停桌宠 → `git pull` →
  依赖变了才重装 → 重启
- **`UPDATE.md`**：三种拿到项目的方式（git clone / ZIP / 分享包）各自的更新办法

### 修掉的关键问题（都是实测定位的）

| 问题 | 后果 | 根因 |
|---|---|---|
| 拖不动宠物、松手后回出生点 | 完全没法用 | `_place_initial()` 每次重建掩膜都刷新"启动窗口"，导致它永不过期 |
| 从 GitHub 装起来**图标是没有的** | 静默少功能 | 整个 `assets/` 被 `.gitignore` 排除，而 `make_icon()` 只写 stderr |
| 自由活动时**所有动作都在慢慢滑** | 看着像"不该动的也在动" | `gravity: 0` 时宠物永远落不到地面 → `grounded` 恒为 False → **水平摩擦永不执行**，残余速度只靠撞墙衰减 |
| 移动动作撞墙后贴着墙走完全程 | 卡在墙边 | `move_vx` 在 `start_move()` 里定死，撞墙不跟着变 |
| 步长与宠物大小不匹配（偏大 44%） | 像"滑过去"而不是"走" | 配置注释说按 `size/462` 缩放，**代码里没做** |
| 画面不如上游清晰 | 可见画质损失 | 256 色调色板量化（每帧只剩 249 色，而参考 4217 色），却只省 2.3% 磁盘 |
| `*-status.json` 带 BOM | **智能体读不了** | PowerShell 5.1 的 `Set-Content -Encoding UTF8` 会写 BOM，而 Python/Node 的 JSON 解析器拒收 |
| 运行时 `git pull` 更新素材失败 | 报 `Invalid argument` | `stream` 模式下 ffmpeg 一直开着 webm，不允许删除共享 |

### 测试

- **39 个自检脚本**（28 个 `selftest_*` + 11 个 `verify_*`），
  用 `python tools\run_selftests.py` 一键跑（默认跑其中 31 个；
  其余需要联网或打包产物，列表见脚本里的 `SLOW_OR_ENV`）
- 关键自检都做过**反向验证**（把修复撤掉，确认它真的会失败）：
  `selftest_settle_window` / `selftest_no_drift` / `selftest_wall_turnaround` /
  `selftest_runtime_files`
- 端到端验证：`verify_public_clone.py`（匿名克隆后能不能直接跑）、
  `verify_clone_icon_loads.py`（克隆后图标真的能加载，不是只看文件在不在）、
  `verify_remote_icons.py`（远程图标与本机逐字节比对）

> **关于 DSH 联动插件**：`plugins/dsh-pet-bridge/` 只有 `package.json` 与
> `lib/index.js`，**没有任何 Node 测试**。（README 早先写的"6 个 Node 测试"
> 是遗留的错误说法，已经改掉 —— 这类没量过的数字正是最容易长期错下去的东西。）

### 已知限制

- 只支持 **Windows**（依赖 Windows 的文件共享语义与 `CREATE_NO_WINDOW`）
- **运行时需要 ffmpeg**（`stream` 模式）；没装会自动退回 `cache` 模式并在 stderr 说明
- 更新素材前**必须先退出桌宠**（webm 被 ffmpeg 占用）
- 只有单个作者、没有 CI；靠自检脚本守回归

---

[未发布]: https://github.com/adincole169-ui/cole-dsh-pet/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/adincole169-ui/cole-dsh-pet/releases/tag/v1.0.0
