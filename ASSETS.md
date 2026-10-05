# 素材来源与许可 / Asset Provenance & Licensing

> **本项目是基于 [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet) 的二次创作。**
> 按该项目的要求，凡介绍、展示或分发本项目的地方，都必须附上原作者地址：
> **<https://github.com/PC2005-cloud/dsh-pet>**

---

## 一、动画素材：来自 PC2005-cloud/dsh-pet

| 项目 | 说明 |
|---|---|
| **仓库** | [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet) |
| **作者** | [@PC2005-cloud](https://github.com/PC2005-cloud) |
| **素材位置** | `dsh-pet/assets/webm/` |
| **内容** | **106 个透明动画**（VP9 + 第二路 alpha 流，640×360，每段 10.04 秒 / 241 帧 @24fps） |
| **npm 包** | <https://www.npmjs.com/package/dsh-pet> |
| **提示词** | `prompts/桌面宠物 10 秒动作提示词.md`（约 291 KB） |

### 已核实：是同一批文件

本项目 `webm/` 里的 106 个文件与上游 `dsh-pet/assets/webm/` 的**文件名完全一致**，
且抽查的文件**逐字节相同**（用 git blob 哈希比对——那是与仓库无关的纯内容哈希）：

```
上游 dsh-pet/assets/webm/   106 个
本地 webm/                  106 个
抽查 10 个                  全部逐字节相同
```

核对脚本：`python tools/verify_asset_origin.py`

### 上游的许可声明（原文）

```
## 许可

- 代码：MIT
- 素材（动画/提示词/源视频）：允许开源使用，禁止商用
- 二次创作（二创）约定：基于本项目的衍生 / 改版 / 换皮作品，在**任何介绍、展示、
  分发该作品的地方**，须附上原作者 GitHub 地址：
  https://github.com/PC2005-cloud/dsh-pet
```

### 这对本项目意味着什么

| 条款 | 本项目的对应做法 |
|---|---|
| 素材允许**开源使用** | 本项目是开源项目；随仓库分发素材属于该许可允许的范围 |
| **禁止商用** | 本项目**不得用于商业用途**，也不得把素材用于商业产品 |
| **二创须署名** | 本项目在 README、本文件、以及任何分发处都附上原作者地址 |

> **说明**：随仓库分发的是 **51.8 MB 的 webm 源**（`webm/`，106 个）以及
> **图标与表情包**（`assets/` 4 个、`memes/` 8 个，合计约 790 KB）。
> 只有解码后的帧（`frames/`，2.56 GB / 25423 个文件）不进仓库——它太大，
> 而且可以用 `python tools/setup_assets.py` 一条命令重新生成。
>
> 图标与表情包虽然也是从 webm 生成的派生物，但 `assets/icon.ico` 是**运行必需**的：
> 缺了它窗口与任务栏就没有图标，而代码不会报错、只是静默地少一个功能。
> 判断一个文件该不该进仓库，要看"运行时要不要它"，不能只看"是不是派生物"。

---

## 二、功能设计与配置格式：同样来自 dsh-pet

本项目的 `config.jsonc` 沿用 dsh-pet 的分层合并口径（**顶层字段整段替换，不做深合并**），
菜单结构、状态机、工作状态与余额分档等设计也参考了它。

本项目的 Python 代码是**独立实现**（PyQt5 重写），没有复制 dsh-pet 的源码。

---

## 三、与 gmskywalker/deepseek-fat-fish-codex-pet 的关系：**没有关系**

早期版本的本文档曾把动画素材的出处误写成
[gmskywalker/deepseek-fat-fish-codex-pet](https://github.com/gmskywalker/deepseek-fat-fish-codex-pet)，
**那是错的**。事实对比：

| | gmskywalker 的仓库 | 本项目 |
|---|---|---|
| 交付形态 | **1 张图集** `spritesheet.webp`（1536×2288，8 列 × 11 行 = 88 格） | **106 个独立 webm**，每个 241 帧 |
| 动画状态 | 其 README 列 10 个状态（idle / running / waving / jumping 等） | 106 个动画 |
| 帧的形态 | 每状态约 8 格（静态姿势） | 每段 241 帧补间 |

本项目**没有使用**该仓库的任何文件。两者只是**同一个角色形象（DeepSeek 大肥鱼）的
不同同人作品**——可以理解为"同类项目"，但不是来源。

如果你看重该仓库里的某些内容（例如更高分辨率的原画），那是**另一条独立的授权链**，
需要单独取得许可，不能与本项目的授权混为一谈。

---

## 四、角色形象

「大肥鱼 / 鲸鱼娘」是 **DeepSeek 的社区二创形象**，DeepSeek 官方**从未发布过**
拟人形象。相关名称、标识与可识别形象的权利归各自权利方所有。

本项目与 DeepSeek 官方、OpenAI、Codex 及其它权利方**均无隶属或授权关系**。

---

## 五、本仓库自己的东西

以下内容由本项目自行编写，适用根目录 [LICENSE](LICENSE)（MIT）：

- `main.py`、`src/` 下全部代码
- `tools/` 下全部工具脚本
- `config.jsonc` 的结构与默认值、`pet/夜猫-config.json` 示例
- 全部文档（README、使用指南、安装说明、AGENTS.md、DEVNOTES.md 等）
- `plugins/dsh-pet-bridge/`（DSH 联动插件）

注意：**这是"本项目代码"的许可，不覆盖素材**。素材的许可见上面第一节。

---

## 六、怎么准备素材

**本仓库已附带 106 个 webm 源**（`webm/`，51.8 MB），**clone 下来就能直接跑** ——
默认是 `stream` 模式（`config.jsonc` 的 `frameSource`），播放时用 ffmpeg 流式解码，
**磁盘上不留帧**，不需要任何准备步骤：

```powershell
python -X utf8 main.py
```

它需要 ffmpeg 在 PATH 里（或装 `imageio-ffmpeg`，见 `requirements-assets.txt`）。
没装也不会坏：会自动退回 `cache` 模式并在 stderr 说明。

### 如果你想用 `cache` 模式（预解码成 PNG，约 2.6 GB）

把 `config.jsonc` 的 `frameSource` 改成 `"cache"`，然后解码一次：

```powershell
python tools/setup_assets.py          # 并行解码全部动画，约 10 分钟
python tools/setup_assets.py --check  # 只检查依赖与进度
```

解码后的帧在 `frames/`，**不进 git** —— 它可由 webm 随时重新生成。
**两种模式产出的画面逐像素相同**（实测最大差 0/255），区别只在磁盘、依赖与首帧延迟。

### 方式 A：重新取上游素材（本仓库已附带，一般用不到）

只在你想**换成更新版**的上游素材时才需要：

1. 从 [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet) 取
   `dsh-pet/assets/webm/` 下的 webm，或装它的 npm 包
2. 覆盖本项目的 `webm/`
3. 刷新帧数元数据（`stream` 模式需要它来算循环长度；缺了会自动探测但慢一点）：

```powershell
python tools/build_webm_meta.py
python main.py
```

`cache` 模式则改成重新解码：

```powershell
python tools/setup_assets.py --force   # 强制重解
python main.py
```

**再次提醒**：这样用素材属于上游许可的「开源使用」，**禁止商用**，
并且你分发时也要保留对 <https://github.com/PC2005-cloud/dsh-pet> 的署名。

### 方式 B：做你自己的角色（推荐，权利最干净）

这套框架与具体角色无关——`config.jsonc` 里指向哪些动画名就用哪些素材。
换成你自己的素材后，本项目在素材上就不再是二创，那部分权利全归你。

1. 准备透明背景的动画，放进 `frames/<动画名>/`（PNG 从 `0001.png` 起命名），
   或 `webm/<动画名>.webm`（透明 VP9）
2. 在 `config.jsonc` 里把这些名字填进
   `idle` / `clicks` / `drag` / `turn` / `moves` / `categories` / `events`

`pet/夜猫-config.json` 是一个完整的「另一种种类」示例，可以直接照它改。
任何名字在素材里不存在时，播放会**自动退回自由活动**，不会崩。

---

## 七、如果你要二次分发

请把下面这条**放在显眼处**（README 开头、发布页说明、安装向导等）：

> 本项目基于 [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet) 二次创作，
> 动画素材版权归原作者，禁止商用。

这是上游二创条款的硬性要求：**任何介绍、展示、分发该作品的地方**都要附上原作者地址。
