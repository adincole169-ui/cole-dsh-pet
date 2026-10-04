# 素材来源与许可 / Asset Provenance & Licensing

**一句话**：本仓库只包含**代码**。所有动画美术素材都**没有**随仓库分发，请自行准备。

---

## 为什么素材不在仓库里

两个原因，任何一条都足够：

1. **授权**：动画素材来自第三方同人仓库，它**没有正式开源许可证**（GitHub 上
   `license` 为 `null`），只有一份「同人作品声明」，声明了个人非商业使用，
   **但没有授予再分发权**。把素材打进本仓库再发布，属于未获授权的再分发。
2. **体积**：素材解码后是 **25423 个 PNG / 2.56 GB**，远超 GitHub 的合理范围
   （单文件 100 MB 上限、仓库建议 1 GB 以内）。

所以本仓库的 `.gitignore` **显式排除** `webm/`、`frames/`、`assets/`、`memes/`。

---

## 一、动画素材来源（必须标注）

| 项目 | 说明 |
|---|---|
| **仓库** | [gmskywalker/deepseek-fat-fish-codex-pet](https://github.com/gmskywalker/deepseek-fat-fish-codex-pet) |
| **作者** | [@gmskywalker](https://github.com/gmskywalker) |
| **内容** | 「DeepSeek 大肥鱼」Codex V2 无损 RGBA 动画图集 |
| **规格** | `spritesheet.webp`，1536×2288，8 列 × 11 行，单格 192×208，`spriteVersionNumber: 2` |
| **许可** | **无开源许可证**（`license: null`）；README 内含「同人作品声明」：非官方、非商业、仅供个人桌面定制与技术学习，**不授予商业使用权，亦未授予再分发权** |

该仓库的原始声明（节选自其 README）：

> This is an unofficial, non-commercial fan-made desktop-pet package. It is not
> affiliated with DeepSeek, OpenAI, Codex, or other rights holders. Names, logos,
> and recognizable designs belong to their respective owners. This repository is
> intended for personal desktop customization and technical learning; it does not
> grant commercial rights to any underlying intellectual property.

> 本项目为非官方、非商业同人桌宠……本仓库仅用于个人桌面定制与技术学习，
> 不授予对任何底层知识产权的商业使用权。

**本项目如何使用它**：`tools/asset_pipeline.py` 用 ffmpeg 把上游图集/透明动画解码成
PNG 序列帧。这只是**本地转换**，不改变素材的权利归属，也**不代表获得授权**。

---

## 二、功能设计与配置格式参考

| 项目 | 说明 |
|---|---|
| **仓库** | [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet) |
| **作者** | [@PC2005-cloud](https://github.com/PC2005-cloud) |
| **作用** | 桌面宠物的**功能设计**与 `config.jsonc` 的**分层配置模型**参考来源 |
| **许可** | 代码 **MIT**；其素材标注禁商用、二创需署名 |
| **npm 包** | https://www.npmjs.com/package/dsh-pet |

本项目的 `config.jsonc` 沿用它的分层合并口径（**顶层字段整段替换，不做深合并**），
菜单结构与状态机设计也参考了它。代码是**独立实现**，没有复制其源码。

---

## 三、角色形象

「大肥鱼 / 鲸鱼娘」是 **DeepSeek 的社区二创形象**，DeepSeek 官方**从未发布过**
拟人形象。相关名称、标识与可识别形象的权利归各自权利方所有。

---

## 四、本仓库自己的东西

以下内容由本项目自行编写，适用根目录 [LICENSE](LICENSE)（MIT）：

- `main.py`、`src/` 下全部代码
- `tools/` 下全部工具脚本
- `config.jsonc` 的结构与默认值、`pet/夜猫-config.json` 示例
- 全部文档（README、使用指南、安装说明、AGENTS.md 等）
- `plugins/dsh-pet-bridge/`（DSH 联动插件）

---

## 五、怎么自己准备素材

先跑这条命令，它会**按你当前的实际情况**给出指引（缺什么、两条路各怎么做、
依赖装了没有）：

```powershell
python tools/fetch_assets.py
```

下面是同样的内容，供直接阅读。

### 方式 A：拿现成素材（快速看效果）

从上面第一个仓库取图集，然后本地转成帧。**你自己取、自己用，属于你的个人使用**；
请不要把取来的素材再提交到本仓库或其它公开仓库。

```powershell
# 1. 把上游的 spritesheet.webp 放到 webm/ 或直接解出 PNG
# 2. 解码成帧（需要 ffmpeg；调色板量化需要 Pillow）
python tools/asset_pipeline.py build-all
```

放好之后：

```powershell
python main.py --check-assets    # 确认素材就绪
python main.py --predecode       # 预解码，消除首次播放的卡顿
python main.py                   # 启动
```

### 方式 B：做你自己的角色（推荐，完全属于你）

这套框架**与具体角色无关**——`config.jsonc` 里指向哪些动画名，就用哪些素材。
换角色只要两步：

1. **准备素材**，放进 `frames/<动画名>/`，PNG 从 `0001.png` 开始命名
   （透明背景；也可以用 `webm/` 放透明 VP9 再解码）
2. **改配置**，在 `config.jsonc` 里把这些名字填进
   `idle` / `clicks` / `drag` / `turn` / `moves` / `categories` / `events`

`pet/夜猫-config.json` 是一个完整的「另一种种类」示例，可以直接照它改。

任何名字在素材里不存在时，播放会**自动退回自由活动**，不会崩——所以可以边加素材边试。

### 方式 C：只做一两个动作先跑起来

最少只要一段待机动画就能启动：把 PNG 放进 `frames/待机呼吸休闲/`，
`config.jsonc` 里 `idle` 指向它即可。其余动作缺失只会让它少些花样。

---

## 六、如果你的项目要用别人的素材

请自己去联系原作者取得**书面许可**，并把许可声明放进仓库。本项目**不代为授权**，
也不对你使用上游素材的行为负责。
