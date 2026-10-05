# 大肥鱼桌宠（DSH 版）

> **本项目是基于 [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet) 的
> 二次创作。** 动画素材版权归原作者，**禁止商用**；按原作者要求，在此附上其仓库地址。
> 详见 [ASSETS.md](ASSETS.md)。

一只住在 Windows 桌面上的透明小女仆：无边框、常驻置顶、不占任务栏，
会和 [DeepSeek Harness](https://github.com/deepseek-ai) 的会话状态联动 ——
你让它干活它切"忙碌"，干完它蹦一下，出错它叹口气，余额少了它皱眉。

**状态**：个人项目，已在 Windows 10/11 + PyQt5 5.9.2 / 5.15.11 上实测通过
（16 个 Python 自检 + 6 个 Node 测试全绿）。

> **关于动画素材**：本仓库**已附带** 106 个 webm 动画源（51.8 MB，来自
> [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet)，
> 与上游逐字节相同，已核实）。该项目的许可是「素材允许开源使用、禁止商用、二创须署名」。
> **clone 下来就能直接跑**：默认 `frameSource: "stream"` 在播放时用 ffmpeg 流式解码，
> **磁盘上不留任何帧**。想换成预解码的 PNG 帧（零解码延迟、约 2.6 GB）见
> [快速开始](#快速开始)。

---

## 目录

- [它是什么](#它是什么)
- [功能](#功能)
- [快速开始](#快速开始)
- [配置](#配置)
- [更新](#更新)
- [架构](#架构)
- [素材与许可](#素材与许可)
- [开发](#开发)
- [已知取舍](#已知取舍)

---

## 它是什么

一个用 **PyQt5** 写的 Windows 桌面宠物，**不依赖 Electron**，与本项目附带的
DSH 插件配合，把 DSH 的会话状态变成宠物的动作与气泡。

特色在于**联动**：不是单纯的动画播放器，而是把"DSH 在干什么"映射成宠物的表情：

| DSH 里发生的事 | 宠物的反应 |
|---|---|
| 一轮开始、正在思考 | 思考冒泡 |
| 调用工具 | 忙碌点按 |
| 工具返回、正在整理 | 清点归档 |
| 一轮干完 | 雀跃庆祝 |
| 出错 | 垂头叹气冒汗 |
| 余额分档 | 钱袋满溢 → 金袋叮当 → 钱袋如常 → 数金皱眉 → 袋空如洗 → 分文不剩 |
| 你不在看 DSH 时干完活 | 弹一条系统通知 |

---

## 功能

**交互**

- **单击**：随机播一个回应动作，带弹性挤压反馈
- **拖动**：切到"被拖拽悬空"动作跟着手走
- **甩出去**：按方向与速度抛出，撞墙反弹、落地回弹
- **右键菜单**：走走看 / 点一下 / 聊两句 / 现在碎碎念 / 动作点播 / 大小 / 模式 / 回到初始位置 / 总在最前 / 退出

**桌宠本身**

- 透明无边框、常驻置顶、不占任务栏按钮、不抢焦点
- **输入区域按角色实际轮廓裁剪**：四周透明处点击会穿透到下层窗口，不挡你操作
- 内置**物理**：重力、地面摩擦、反弹、Q 弹挤压（可关）
- **自由活动 / 原地待着**两种模式；后者不自动走开
- 尺寸 240–640 px 可调，改完立刻生效
- **系统通知**：你不在看 DSH 时干完活会弹一条（带 90 秒限流）

**与 DSH 联动**

- 工作状态 6 档、余额 6 档、碎碎念 3 档，共 15 个联动动画
- **碎碎念**：每隔一段时间自己说一句，内容由模型生成，配表情包
- **对话**：右键「聊两句…」，记住最近 5 轮上下文，回答 40 字以内
- **余额**：优先读账户余额分档；拿不到时才退回会话用量
- **忙状态看门狗**：`tools` 调用后若一直没收到结果，90 秒后自动解除忙碌
  （否则宠物会永久卡在一个动作上）

**健壮性**

- 单一实例：按显示服务端口判定，重复启动会安静退出而不是开出第二只
- 不在底部时**不会**被重力拽走；`gravity: 0` 时停在放下它的地方
- 缺素材时启动前给**可照做的说明**再退出，不闪退
- 帧按 LRU 淘汰 + 钉住正在播的，内存有上界（约 150 MB RSS）
- 日志自动裁剪（保留最近的，而不是全删）

---

## 快速开始

### 前置

- Windows 10/11
- **Python 3.8+**（[下载](https://www.python.org/downloads/)，安装时勾选 *Add python.exe to PATH*）
- 想用联动功能的话：装好 [DeepSeek Harness](https://github.com/deepseek-ai) 并至少启动过一次

### 一、建环境

```powershell
git clone <本仓库地址>
cd <仓库目录>

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 二、素材：不需要任何准备步骤

本仓库**已附带 106 个 webm 动画源**（`webm/`，51.8 MB），**clone 下来就能直接跑** ——
不再需要"先解码一遍"。

播放时有两条路（`config.jsonc` 的 `frameSource`，默认 `"auto"`）：

| 值 | 做法 | 磁盘占用 | 首次播放 | 需要 ffmpeg |
|---|---|---|---|---|
| `"stream"`（默认，推荐） | 播放时用 ffmpeg **流式解码** webm，不落盘 | **0** | 约 94 ms | **是** |
| `"cache"` | 预先解码成 `frames/<动画名>/*.png` | 约 2.6 GB | 0（但首次要等约 13 秒解码） | 只在解码时 |
| `"auto"` | 有 ffmpeg 就 stream，否则 cache | 视情况 | 视情况 | — |

**两条路产出的画面逐像素完全相同**（实测最大差 0/255），只是"磁盘空间换运行时解码"的取舍。

> **`stream` 模式需要 ffmpeg。** 两条路：
> * 你已经装了（`ffmpeg -version` 能跑）→ 直接用，无需额外操作；
> * 没装 → `winget install Gyan.FFmpeg`，或装 `imageio-ffmpeg`（带一个 ffmpeg 进来）：
>
>   ```powershell
>   .\.venv\Scripts\python.exe -m pip install -r requirements-assets.txt
>   ```
>
>   没装也会正常跑 —— 会自动退回 `cache` 模式并在 stderr 说明，只是需要先解码。

<details>
<summary>如果你更想用 <code>cache</code> 模式（零解码延迟，但要 2.6 GB）</summary>

```powershell
# 1) config.jsonc 里把 "frameSource" 改成 "cache"
# 2) 解码全部 106 个动画（并行，16 核实测约 10 分钟；串行要 48 分钟）
.\.venv\Scripts\python.exe -X utf8 tools\setup_assets.py
```

`setup_assets.py` 会检查素材与解码器、然后并行解码全部动画并实时报进度。先看它要做什么：

```powershell
.\.venv\Scripts\python.exe -X utf8 tools\setup_assets.py --check
```

> **解码用的 ffmpeg**：PATH 里优先，其次 `imageio-ffmpeg` 自带的（较老的 4.2.2，
> 对某些目录写文件会失败；`asset_pipeline` 里做了临时目录兜底，已实测**解出的帧与
> 新版 ffmpeg 逐像素一致**）。流式模式不受这个坑影响 —— 它走管道、不写文件。

</details>

### 三、启动

```powershell
.\.venv\Scripts\python.exe -X utf8 main.py
```

想确认素材与解码器状态：

```powershell
.\.venv\Scripts\python.exe -X utf8 main.py --check-assets
```

### 四、装上 DSH 联动插件（可选）

把 `plugins/dsh-pet-bridge/` 复制到你的 DSH profile 的 `node_modules/` 下，
再在 `cordis.patch.yml` 里登记：

```yaml
- insert:
    - id: pet-bridge
      name: dsh-pet-bridge
      config:
        petPort: 8899
        selfPort: 8900
        memoryRounds: 5
        balanceCacheSec: 60
        busyWatchdogSec: 90
```

**插件不会热重载，改完要完全重启 DSH。**

### 常用命令行参数

| 参数 | 作用 |
|---|---|
| `--status` | 打印配置、**帧来源**与素材统计后退出（不启动、不校验素材） |
| `--check-assets` | 检查素材是否就绪（判据随 `frameSource` 而变） |
| `--predecode` | **仅 `cache` 模式**：预解码常用动画后退出（约 26 个） |
| `--predecode --all` | **仅 `cache` 模式**：预解码**全部** 106 个动画 |
| `--predecode --jobs N` | 指定并行度（默认按 CPU 核数自动决定 2~6；实测 6 路约 4.7 倍速） |
| `--pet <名字>` | 用一个「种类」覆盖层启动（见 `pet/夜猫-config.json`） |
| `--anim <名字>` | 直接播指定动画 |
| `--watch` | 每秒记一行位置/可见性/动画名，用于排查"宠物不见了" |
| `--force` | 跳过单一实例检查（自检脚本用） |
| `--allow-multi` | 允许多开 |

`stream` 模式下 `--predecode` 是**空操作**（会直接告诉你不需要预解码）。
只有切到 `cache` 模式才需要：

```powershell
python tools/setup_assets.py            # 自动并行度
python tools/setup_assets.py --jobs 8   # 指定并行度
python tools/setup_assets.py --check    # 只检查
```

---

## 配置

`config.jsonc`（**JSONC，带注释**），改完重启生效。

**分层规则**：顶层字段**整段替换**，不做深合并——与
[PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet) 的口径一致。
「种类」覆盖层（`pet/<名字>-config.json`）同理：只写要改的字段即可。

最常用的几项：

```jsonc
{
  "size": 320,                    // 默认尺寸（逻辑 px）
  "gravity": 0,                   // 0 = 不要重力，停在放下它的地方
  "pets": [{
    "name": "蓝毛小女仆",          // 内部物种名（素材目录与配置的键，别随便改）
    "displayName": "大肥鱼",       // 给用户看的名字（任务栏/托盘/通知）
    "fixedEnabled": false,        // true = 启动即"原地待着"
    "whisperEnabled": true,       // 自动碎碎念
    "workStatusEnabled": true,    // 跟着 DSH 会话状态切动画
    "balanceEnabled": true,       // 用余额驱动 余额-* 动画
    "notificationsEnabled": true, // 系统通知
    "position": {
      "corner": "bottom-right",   // 初始落点：四角之一
      "marginX": 24,              // 量的是**角色**边缘到屏幕边缘的距离
      "marginY": 90               // 调大就不会被任务栏压住
    }
  }]
}
```

配置项都在文件里带注释，想改哪个搜名字即可。

### 换一个角色 / 种类

`pet/夜猫-config.json` 是一个完整的「另一种种类」示例（更轻的物理、左下角、
收窄的动作池、换一套说话口气），可以直接照它改。

**注意**：`name` 是内部物种名，同时是素材目录与配置的键；
`displayName` 才是给用户看的名字。两者分开是有意的——见
[DEVNOTES.md](DEVNOTES.md) 第 20 条。

---

## 更新

**已经装过 / 下载过的人看 [UPDATE.md](UPDATE.md)。**

一句话版本（`git clone` 拿的）：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\pull.ps1
```

它做四件事：**检查本地改动 → 停桌宠 → `git pull` → 依赖变了才重装 → 重启**。

> ⚠️ **必须先停桌宠**：`stream` 模式下 ffmpeg 一直开着 `webm/*.webm`，
> 不停掉的话 `git pull` 会报 `unable to unlink old ...: Invalid argument`
> （注意是 `Invalid argument` 而不是权限错误，很容易查错方向）。

**个人配置请写进 `config.user.jsonc`**（复制 `config.user.example.jsonc` 开始）：
它**不进 git**，所以 `git pull` 永远不会因为"你改过配置"而冲突。

---

## 架构

```
main.py                 启动、命令行、预解码、素材自检
src/
  pet.py                窗口绘制、物理、输入掩膜、气泡、通知（约 1300 行）
  animator.py           当前播放、交叉淡化、移动规格、状态机
  frames.py             帧来源（stream 流式解码 / cache 预解码 PNG）、LRU + 钉住
  stream_frames.py      流式解码：常驻 ffmpeg + 环形缓冲 + 按消费位置背压
  config.py             JSONC 解析、分层合并（主配置 → 用户层 → 种类覆盖）
  bridge.py             本地 HTTP 显示服务（127.0.0.1:8899）
  chat.py / notify.py / move.py
plugins/dsh-pet-bridge/ DSH 插件：把会话事件推给桌宠（127.0.0.1:8900）
tools/                  素材流水线、图标/表情包生成、自检、探针、打包
pet/                    「种类」覆盖层示例
```

### 联动是怎么接上的

桌宠**自己持有显示服务**（`127.0.0.1:8899`），DSH 插件往里推状态；
插件同时在 `127.0.0.1:8900` 提供 `/chat` 供桌宠反查模型。
两边都是普通 HTTP + JSON，所以：

- DSH 没开时桌宠照常工作（只是没有联动）
- 关掉 `workStatusEnabled` 就退化成普通桌宠

### 关键实现取舍

- **帧预解码成 PNG**：素材的透明通道藏在**第二路 VP9 alpha 流**里，每次播放现解
  太慢（约 20–31 秒/动画）。所以首次解码后缓存，用 LRU + 钉住控制内存。
- **不用 `setMask` 做视觉裁剪，但用它做输入裁剪**：`setMask` 同时限制输入与绘制，
  正好用来让透明处的点击穿透。代价是边缘是 1bpp 硬裁——细节见 DEVNOTES。
- **两个独立 30fps 时钟**：动画/移动一个，物理/气泡一个。

---

## 素材与许可

> **本项目是基于 [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet) 的二次创作。**
> 动画素材版权归原作者，**禁止商用**。本条署名按原作者对二创作品的要求，
> 须出现在介绍、展示、分发本项目的所有地方。

完整说明见 **[ASSETS.md](ASSETS.md)**，这里是要点：

| 内容 | 来源 | 许可 |
|---|---|---|
| **动画素材** | [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet) 的 `dsh-pet/assets/webm/` | 素材**允许开源使用**、**禁止商用**、**二创须署名** |
| 功能设计与配置格式 | 同上 | 代码 MIT |
| 本仓库的代码与文档 | 本项目 | [MIT](LICENSE) |

**素材是本项目原样使用的**：106 个 webm 与上游同名同内容（抽查逐字节相同，
可用 `python tools/verify_asset_origin.py` 复核）。

**为什么不把解码帧提交进 git**：解码后有 **2.6 GB / 25423 个文件**，不适合放进仓库
历史。所以本仓库分发的是 **51.8 MB 的 webm 源**（`webm/`，106 个）。

**而且现在默认根本不解码**：`frameSource: "stream"` 在播放时用 ffmpeg 流式解码，
磁盘上不留帧（实测起流到首帧 94 ms、首帧后每帧 0.6 ms，24fps 的预算 41.7 ms）。
所以要 2.6 GB 帧缓存的那套只是 `"cache"` 模式的备选，不是必经之路。

**但图标与表情包是随仓库分发的**（`assets/` 4 个、`memes/` 8 个，合计约 790 KB）：
它们虽然也是从 webm 生成的派生物，但 `assets/icon.ico` 是**运行必需**的——
缺了它窗口与任务栏就没有图标，而且代码**不会报错**，只是静默地少一个功能。
所以判断一个文件该不该进仓库，不能只看"是不是派生物"，还要看"运行时要不要它"。
`tools/selftest_runtime_files.py` 会把这件事变成机器可查的。

`.gitignore` 只排除 `frames/`（体积大且可再生成）。

**与 gmskywalker/deepseek-fat-fish-codex-pet 无关**：早期文档曾把素材出处误写成那个
仓库。核对后确认那是**另一个** DeepSeek 大肥鱼同人作品（单张图集、88 格、约 10 个状态），
本项目**没有使用它的任何文件**。详见 [ASSETS.md](ASSETS.md) 第三节。

「大肥鱼 / 鲸鱼娘」是 **DeepSeek 的社区二创形象**，官方从未发布过拟人形象。
相关权利归各自权利方所有。本项目与 DeepSeek 官方、OpenAI、Codex 均无隶属或授权关系。

**换成你自己的素材很容易**：这套框架与具体角色无关，`config.jsonc` 里指向哪些动画名
就用哪些。换掉之后本项目在素材上就不再是二创。详见
[ASSETS.md](ASSETS.md) 的「怎么准备素材」。

---

## 开发

### 目录

```
DEVNOTES.md            开发笔记：22 条踩过的坑（含现象、原因、修法）
使用指南.md            面向使用者的功能说明
tools/                 素材流水线 / 生成器 / 自检 / 探针 / 打包
```

**建议先读 [DEVNOTES.md](DEVNOTES.md)**——那里记录了几乎所有非显而易见的约束
（高 DPI 属性必须在 `QApplication` 之前设置、掩膜必须包含气泡、`sip.voidptr`
的错误用法会让进程无声退出、窗口矩形 ≠ 角色占位 等等）。

### 自检

```powershell
# 一条命令校验全部语法（.py / .ps1 / .js / .json）
python tools/check_syntax.py

# 环境与依赖体检
python tools/doctor.py

# 帧素材完整性（每个动画都有帧、首帧宽度正确）
python tools/check_frames.py

# 单个自检
python tools/selftest_still_mode.py          # 原地待着模式
python tools/selftest_character_bounds.py    # 贴边按角色而不是窗口
python tools/selftest_display_name.py        # 显示名一致性
python tools/selftest_memory_bound.py        # 内存有上界
python tools/audit_gaps.py                   # 配置里"配了却不生效"的字段
```

### 打包分发

```powershell
# 完整包（含素材，供全新安装）
powershell -ExecutionPolicy Bypass -File tools\build_package.ps1

# 更新补丁（供已装旧版的人更新）
powershell -ExecutionPolicy Bypass -File tools\build_update.ps1
```

> **注意**：分发**带素材的包**之前，请先确认你有权分发那些素材——
> 本仓库的默认假设是**没有**（见 ASSETS.md）。

---

## 已知取舍

- **内存约 150 MB**：帧按 LRU 淘汰，内存里保留最近几个动画。
- **磁盘 2.56 GB（25423 个 PNG）**：这是"播放要流畅"与"体积"之间的取舍。
  不想占这么多可以把 `TARGET_WIDTH` 调小，代价是画面变软。
- **放大时会软**：素材原生 640×360，放大显示就是插值，无法避免。
- **背景插件不含在内**：本项目只含桌宠与联动插件；"对话界面背景 + 启动动画"
  是另一个自研插件，未包含在此仓库。
- **平台**：只测过 Windows。物理与掩膜里有 Windows 专有调用
  （`GetForegroundWindow`、`QueryFullProcessImageNameW`），换平台需要替换。

---

## 致谢

- [PC2005-cloud](https://github.com/PC2005-cloud) —— **动画素材**与功能设计、
  配置格式的参考来源。本项目是基于
  [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet) 的二次创作。

## 许可

- **本项目代码与文档**：[MIT](LICENSE)
- **动画素材**：版权归 [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet)
  原作者所有；**允许开源使用、禁止商用、二创须署名**。详见 [ASSETS.md](ASSETS.md)

**本项目禁止用于商业用途。**
