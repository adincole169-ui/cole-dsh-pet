# 大肥鱼桌宠（DSH 版）

> **这是开发者文档**（架构、IPC、以及 18 条踩坑记录）。**只是想用的话看
> [安装说明](tools/安装说明.md)** —— 打包发出的 zip 里，那份就放在包根目录。

一只住在 DeepSeek Harness 旁边的透明置顶桌宠：待机呼吸、随机动作、屏幕漫游、
点击 Q 弹、拖拽甩抛反弹、右键点播一百多个手绘动画，并且**跟着 DSH 会话状态切换
工作动画与台词**。

素材（106 个透明动画）来自
[PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet) 的 `dsh-pet/assets/webm/`
（已核实：同名同内容，抽查逐字节相同，见 `tools/verify_asset_origin.py`）。
该项目的许可是「素材允许开源使用、禁止商用、二创须署名」——本项目是它的二创，
所以在 README 与 ASSETS.md 都附上了原作者地址。

**注意**：早期版本的这份文档与 README 曾把素材出处误写成
[gmskywalker/deepseek-fat-fish-codex-pet](https://github.com/gmskywalker/deepseek-fat-fish-codex-pet)，
那是错的；那个仓库与本项目没有关系（它是另一个大肥鱼同人作品，单张图集 88 格）。
更正记录见 [ASSETS.md](ASSETS.md) 第三节。

功能设计对齐 dsh-pet，但**自研实现**——当初动手时本机是 DSH `0.1.0-rc.7`，
而原插件要求 `^0.2.0-rc.1`，装不上。
（现在本机已升到 `0.2.0-rc.2`，两边版本都对得上了，只是实现路线不同。）

运行时依赖 **PyQt5**（必需）；**ffmpeg 在 `stream` 模式下必需**（默认就是它），
`cache` 模式下不需要（帧已解好）；numpy / Pillow 只在自检与解码工具里用。
见 [第 18 条](#18-打包分发两个包一个安装脚本) 与
[帧来源](#帧来源stream-与-cache)。

---

## 快速开始

```powershell
# 启动（双击也可以）
.\启动大肥鱼.bat

# 或者直接跑（用自己环境里的解释器路径）
pythonw.exe -X utf8 main.py
```

装 DSH 联动（可选，但要"跟着对话切状态"就必须要）：

```powershell
# 插件已在 profile 里注册好，重启桌面应用即可
# 手动确认注册项
Get-Content "$env:USERPROFILE\.dsh\profiles\desktop\cordis.patch.yml" | Select-String -Context 0,6 pet-bridge
```

**配置改动都要重启才生效**，两处都一样：

* DSH profile 里的插件配置（`cordis.patch.yml`）→ 重启 DSH；
* 桌宠自己的 `config.jsonc` → 重启桌宠（关掉再双击桌面图标即可）。

> 之前这里写着"桌宠不用重启、右键『重载配置』即可生效"——**那是错的**：
> `PetConfig` 只在启动时构造一次，菜单里也没有「重载配置」这一项。

---

## 功能一览

| 功能 | 说明 |
|---|---|
| **动画链** | 一段播完按权重挑下一段（默认 idle 10 / turn 5 / move 5 + 5 个分类各自权重），同段不连播 |
| **工作状态联动** | DSH 会话事件 → 六档动画 + 文案气泡：思考 / 忙碌 / 清点归档 / 原地踱步 / 雀跃庆祝 / 垂头叹气 |
| **待机与随机动作** | 待机呼吸，以及 5 大分类共 80+ 个动作（小动作、玩耍、吃什么、时节、文字） |
| **屏幕漫游** | 移动动画带 `leadSec`/`tailSec`，只在中间区间真实位移；先探空间不走出屏幕 |
| **点击 / 拖拽 / 甩抛** | 点击有回应动画 + Q 弹挤压；拖拽过阻尼弹簧跟手；甩出抛物线飞行、屏幕边缘反弹、落地摩擦停稳 |
| **点播菜单** | 右键：动作 → 分类 → 具体动画，任意点播；移动类点播会真的走一段 |
| **用量分档 + 气泡** | 每轮结束后按**真实会话用量**（轮次 + 工具步数）分六档，播对应动画并在头顶显示档位与数字 |
| **碎碎念** | 每 5 分钟（可配）让模型生成一句话 + 说话动画 + 气泡 + 表情包配图 |
| **对话** | 右键「聊两句…」输入，带记忆（默认 5 轮）、AI 选表情包配图 |
| **系统通知** | 宠物被切到后台时弹一条 Windows 原生通知 |
| **多开** | `config.jsonc` 的 `pets` 数组里有几只就开几只，各自独立大小与位置 |
| **种类扩展** | `pet/<名字>-config.json` 放一个覆盖层就是一个新种类：独立动作池、大小、位置、文案；`main.py --pet <名字>` 启动 |
| **大小 / 模式 / 置顶** | 右键菜单：240–640 px、自由活动 / 原地待着、总在最前 |
| **自启动** | `python tools\autostart.py on` / `off` / `status` |

---

## 架构

```
main.py                  入口：多开、预解码、联动桥
src/config.py            JSONC 解析 + 分层配置模型（实例 / 全局 / 条目）
src/frames.py            帧存储：磁盘缓存 + 惰性 QPixmap + 后台加载 + LRU
src/animator.py          状态机：动画链、权重、位移、工作状态
src/pet.py               窗口：透明置顶、物理、交互、气泡、菜单、托盘
src/move.py              移动规格（配置层与动画层共用，不依赖 Qt）
src/bridge.py            桌宠自己的 HTTP 服务（收 mood / say / anim）
src/chat.py              对话客户端（主动去问 DSH 插件的模型服务）
src/notify.py            Windows 原生通知（PowerShell，零依赖）
tools/asset_pipeline.py  webm → PNG 帧缓存（`cache` 模式用；**透明通道的关键在这**）
src/stream_frames.py     流式解码（`stream` 模式，默认）：常驻 ffmpeg + 环形缓冲
tools/autostart.py       开机自启
tools/make_memes.py      生成占位表情包
tools/test_bridge_plugin.mjs  插件事件映射测试（mock 上下文）
tools/test_link_e2e.mjs       端到端联动测试（真桌宠）
plugins/dsh-pet-bridge/   DSH 插件的副本（实际安装在 profile 的 node_modules）
```

### 联动是怎么接上的

两边各起一个**只绑回环**的服务，方向刻意相反：

```
桌宠   :8899   <--  插件 POST /mood            状态镜像
插件   :8900   <--  桌宠 POST /chat            模型访问
```

之所以拆开：桌宠必须在**没装任何插件**时也能独立运行，所以它自己持有显示服务，
插件只是可选的发送方；而模型只存在于 DSH 里，所以碎碎念/对话必须由桌宠主动打出去。
两个端口都只听 `127.0.0.1`，不对外暴露。

### 事件 → 状态映射

| DSH 事件 | 状态档位 | 宠物表现 |
|---|---|---|
| `agent/status` → `running` | thinking | 思考冒泡 + "正在认真想下一步呢" |
| `session/event` → `tools/call` | busy | 忙碌点按 |
| `session/event` → `tools/result` | filing | 清点归档（4 秒无新调用则回 thinking） |
| `agent/status` → `idle`（本轮有工具） | celebrating | 雀跃庆祝 + "这一轮搞定啦，真棒！" |
| `agent/error` | sighing | 垂头叹气冒汗 + "这一步好像没跑通呢" |
| `approval/asked` | thinking | 第 0 档文案本就是"需要你确认一下呢"，动画与措辞正好对上 |

### 用量分档：余额优先，拿不到才退回会话用量

原项目按**账户余额**分六档播 `余额-*` 动画。开发时用的 DSH 是 `0.1.0-rc.7`，全库搜过
**没有任何余额 API**，所以当时改成按真实可得的会话用量驱动（`轮次 + 工具步数 / 4`）。
注释里留了一句"将来若拿到余额，只要改 `pickTier()` 的输入"。

**DSH 升级到 `0.2.0-rc.2` 后条件成立**：新增了 `deepseekAccount` 服务，带

```ts
getBalance(client: AccountClientMetadata): Promise<AccountDetails['balance'] | null>
// { status:'ready', value: readonly {currency,balance}[], bonusWallets: [...] } | { status:'failed' }
```

现在插件声明 `inject = ['llm', 'deepseekAccount']`，**优先用真实余额分档**：

```
0 余额-钱袋满溢  ≥ 50 元        3 余额-数金皱眉  5 ~ 10 元
1 余额-金袋叮当  20 ~ 50 元     4 余额-袋空如洗  2 ~ 5 元
2 余额-钱袋如常  10 ~ 20 元     5 余额-分文不剩  < 2 元
```

主钱包与赠送钱包**求和**（`value` + `bonusWallets`）；`balance` 是字符串，要转数字。
以下情况**退回**会话用量分档（不会显示假数据）：未登录 / 查询失败 / 抛异常 / 服务不存在 /
币种不是人民币（阈值是按人民币定的，硬套美元会把 `$40` 判成"分文不剩"）。

查询结果按 `balanceCacheSec`（默认 60 秒）缓存；`/health` 里也会回传真实余额便于核对。

回归自检：`tools/test_balance.mjs`（14 项，覆盖六档边界、双钱包求和、四种失败路径）。

> 踩过的坑：一开始用"一串 `below` 规则 + 高于某值算充足"来分档，边界很容易错位，实测
> 出过"40 元被判成最低档"。改成**显式区间**后一眼可核对。另外**不要用"抠源码再 eval"
> 的方式测纯函数**——把 `const` 批量替换成 `var` 会让数组在赋值前就是 `undefined`，
> 得出完全误导的结论。宁可把函数导出（`apply.balanceTier`）直接测。

### 新增一个宠物种类

```powershell
# 1) 放一个覆盖层，只写要改的字段
notepad pet\我的猫-config.json

# 2) 用那个种类启动
pythonw.exe -X utf8 main.py --pet 我的猫
```

覆盖层里出现的顶层字段会**整段替换**主配置的同名字段（不做深合并，与 dsh-pet 一致）。
`pet/夜猫-config.json` 是一个完整可运行的例子：它有自己的 `pets`（大小 380、左下角）、
自己的物理参数、收窄的动作池和自己的 `whisperPrompt` / `workStatusTexts`。

**换真正的角色**只需把新角色的透明 webm 放进 `webm/`，然后在覆盖层的
`animations` 里用同样的事件名（`idle`/`turn`/`drag`/`clicks`/`moves`/`categories`/`events`）
指向它们——配置里的名字才是引用键，不必和文件名同名。

---

## 踩过的坑（30 条）

前三条都是"看起来该对、实际不对"，而且症状都不指向真正的原因。

### 1. 高 DPI 属性必须在 QApplication **之前**设置

这台机器 DPI 是 144（150% 缩放）。`AA_EnableHighDpiScaling` 若没在
`QApplication(...)` 之前生效，Qt 会把屏幕报成 **2560×1600、`devicePixelRatio=1.00`**，
而真实屏幕是 **1707×1067**。后果是所有按"屏幕几何"算的位置都跑到可见区域之外——
**宠物因此"经常消失"**：它按 1600 的底边算出地面 y=1339，物理上早已在屏幕下方。

修正后 Qt 报 **1280×800、dpr=2.00**，与物理屏一致，宠物稳定站在 y≈539。
入口里的 `build_app()` 专门负责这件事，自检脚本也必须复用它（早期自检用
`QApplication(argv[:1])` 传了错的参数列表，把缩放抵消了，所以一直没发现）。

自查命令：

```powershell
python -X utf8 -c "from PyQt5.QtWidgets import QApplication; from PyQt5.QtCore import Qt; QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True); a=QApplication([]); s=a.primaryScreen(); print(s.geometry().width(), s.geometry().height(), s.devicePixelRatio())"
# 正确输出：1280 800 2.0
```

### 2. 初始位置要跟重力一致，否则宠物会先出现再"掉下去"

`position.corner` 写 `top-*` 时，宠物会先出现在上方，随后被重力拽到屏幕最底并永久
停在那里——看起来同样是"消失"。所以默认配置用 `bottom-*`：初始就站在地面上，
底部留 `marginY` 的余量。真想让它在上面挂着，必须**同时**把 `physics.gravity` 设为 0。

### 3. 透明通道藏在第二路 VP9 流里

素材是 `VP9 + ALPHA_MODE=1` 的 webm。用普通方式抽帧只会得到**全不透明**的画面，
透明区变成黑块。必须让 ffmpeg 显式用 libvpx 的 VP9 解码器，它才会去取那路隐藏的
alpha 并合并成 RGBA：

```
ffmpeg -c:v libvpx-vp9 -i in.webm -pix_fmt rgba out%04d.png
```

`-c:v libvpx-vp9` 必须放在 `-i` **之前**（它是解码器选择，不是编码设置）。

### 4. 一次性构造 241 个 QPixmap 要 2.5 秒

实测：ffmpeg 解码整段动画只要 0.4 秒，而把 241 张 PNG 全变成 QPixmap 要 **2.5 秒**。
第一版是同步加载，表现为"每次切状态界面僵半秒、健康检查显示还在播上一个动画"。
现在 `Animation` 只存路径，**要画哪一帧才构造哪一帧**——建立动画对象 1 ms，逐帧
约 4 ms，远低于 33 ms 的帧预算。

配套的三条保护（都是实测踩出来的）：

* **正在播放的动画被钉住**，LRU 淘汰时跳过它——淘汰掉当前段就是"画面直接没帧"；
* `Animator._heal()`：请求 A → 立刻切到 B → A 加载完但 `playing.name` 已是 B，`on_loaded`
  会直接返回，B 就永久没帧。自愈逻辑会重新请求或接上已就绪的动画（无帧率因此从
  2.4% 降到 0.1%）；
* **交叉淡化要有垫层**。只让新段自己从 `alpha=0` 淡入、而旧段瞬间消失，中间会出现
  一段两头都近乎全透明的空档——**这就是"切换动作时短暂消失"**，而它并不表现为
  "没有帧"，所以早期只看帧有无的检查抓不到。现在上一段的最后一帧作为 `outgoing`
  垫在下面，新段叠上去淡入；没有垫层时淡入给 0.25 的下限；新段还在后台加载时干脆
  不淡化（否则会把唯一可见的垫层也弄没）。

### 诊断"切换时闪一下"

```powershell
python -X utf8 tools\selftest_fade.py        # 判定逻辑（不依赖截图）
python -X utf8 tools\selftest_crossfade.py   # 合成画面的平均 alpha
```

后者量的是**宠物实心像素的平均不透明度**：基线 245.3，切换瞬间最差 234.5，
淡化期间最差 230.6——基本没有凹陷。阈值是 120，低于它就意味着肉眼可见的空档。

### 5. `QBitmap.fromImage` 的隐式转换不能用来做输入掩膜

"让透明区域不挡下层操作"需要给窗口设输入掩膜（`setMask`），位语义是
**白 = 接收鼠标、透明 = 点击穿透**。但在这台机器上（Qt 5.9 / PyQt5 5.9.2）：

| 做法 | 实测结果 |
|---|---|
| `QImage.createAlphaMask()` | 不管取不取反都给**全零**掩膜 → 宠物完全点不到 |
| `convertToFormat(Format_Mono)` | 把一切都当不透明 → 可点比例 0.897，等于没裁 |
| `QBitmap.fromImage(白底图)` | 依赖亮度判断，结果与数据不符（可点比例 0.996） |
| `createMaskFromColor()` | PyQt5 要求 `Qt.MaskMode` 枚举，传 `Qt.color0` 直接报参数类型错 |
| **逐像素按 alpha 阈值填白** | ✅ 可点比例 **0.17**，与素材实心像素占比一致 |

最终实现用了**两步**：`_source_mask()` 按原始帧分辨率逐像素算一次（按帧缓存），
`_build_input_bitmap()` 再把它按**当前绘制矩形**缩放贴上——因为精灵会随 Q 弹挤压被
拉宽，掩膜若按未挤压的尺寸算，超出部分会被裁掉（表现就是"图像显示不全"）。

两个性能上的坑也一并记下：

* 逐像素阈值用 **numpy** 算。同样的 640×360 帧，Python 逐像素循环要 **137 ms**
  （每帧都付，直接掉到 7fps），numpy 只要几毫秒。实测总耗时 **155 ms/帧 → 11.4 ms/帧**。
* 源掩膜缓存必须**固定容量淘汰**，不能"满了就清空"：一个动画 241 帧、每帧 cacheKey
  都不同，清空策略等于永远命中不了。

最终实现是**显式逐像素填充**（`PetWindow._build_input_bitmap`），不走任何隐式转换。
`/debug` 的 `mask.cover` 就是这项的验证指标：接近 1.0 说明没裁，0.17 上下才对。

顺带一个有用的事实：这套素材的"透明"不是 alpha=0，而是**很低的 alpha**——背景是
alpha 1–8（占 83.7%），角色是较高 alpha（约 17%）。阈值取 24 正好分得开；若用
alpha>0 当判据，整张 640×360 都会被算成实心。

### 6. `sip.voidptr` 的用法会让进程**无声退出**（"点一下就没了"）

`QImage.bits()` / `constBits()` 返回的都是 `sip.voidptr`，它自己**不知道缓冲区多大**：

| 写法 | 结果 |
|---|---|
| `bytes(image.constBits())` | `IndexError: sip.voidptr object has an unknown size` |
| 尺寸变化时 `setsize(image.byteCount())` 再切片赋值 | `ValueError: cannot modify the size of a sip.voidptr object` |
| **`constBits()` → `setsize(stride*height)` → `bytes()`** | ✅ 只读，安全 |
| **从字节直接 `QImage(data, w, h, stride, fmt)` 再 `.copy()`** | ✅ 写掩膜用这条 |

危险点在于**异常位置**：它发生在 Qt 的事件回调（`paintEvent` → `_apply_input_mask`）里，
没人接住，于是进程直接带致命码退出：

```
ValueError: cannot modify the size of a sip.voidptr object
退出码 3221226505   (0xC0000409)
```

用户看到的现象是"点一下宠物就没了"。而用 `pythonw` 启动时 stderr 无处可去，
`watch.log` 只会干净地截断——**什么线索都没有**。这就是为什么后来加了
`tools/run_logged.py`：它把输出和**退出码**写进 `logs/pet-run.log`，非零退出还会
自动重启。桌面快捷方式与开机自启现在都指向它。

回归自检：`tools/selftest_mask_resize.py`（40 组"窗口/掩膜尺寸变化"组合，含气泡
撑高窗口与不同挤压量）。

### 7. 插件必须**声明** `llm` 依赖，否则拿不到模型服务

Cordis 只把插件**声明过**的服务挂到它的上下文上。没声明时 `ctx.llm` 会直接抛：

```
Error: cannot get property "llm" without inject
```

声明就一行：

```js
export const inject = ['llm'];
```

症状是"右键碎碎念完全没反应"——插件压根没拿到模型服务，而且这个异常在旧代码里
被静默吞掉，所以只能靠错误回传才看得出来。

### 8. 推理模型会把额度吃光，正文一个字都不剩

`deepseek-flash` 这类推理模型先输出 `reasoning-delta`。把 `maxTokens` 给成 120 时，
推理就把它耗尽，正文只剩零星几个字甚至完全为空。实测：

| maxTokens | 结果 |
|---|---|
| 120 | `text=''`，或只剩两个字（如 `'唔'`、`'桌上的'`） |
| 800 | 完整一句 |

配套两条兜底：

* **只拿到推理内容时，拿它当台词**（截断到 40 字），而不是返回空——否则用户看到的
  是气泡闪一下就恢复原状；
* 过长的输出统一截断（碎碎念 40 字、对话 60 字）并压掉换行，避免气泡里出现奇怪折行。

回归自检：`tools/test_plugin_chat.mjs`（mock 的 `ctx.llm` + **真实 chunk 形状**）、
`tools/selftest_whisper.py`（桌宠自己的 `ChatClient` 全链路）。

### 9. 掩膜必须包含气泡，而 `setMask` 同时裁绘制

`setMask` 不只限制点击，它**同时裁掉绘制**——掩膜里没有的区域连画都画不出来。
所以"碎碎念成功了、模型也返回了台词，但屏幕上没有气泡"的成因就是**气泡没进掩膜**。

三个具体的坑，都是实测出来的：

* **`_apply_input_mask()` 在"没有可画帧"时提前 return** —— 动画还在后台加载时气泡出现，
  掩膜没有重建，仍是旧几何，整块气泡被裁。现在没有帧也按气泡重建。
* **`QPainter.fillRect` 在 `Format_Grayscale8` 画布上完全不生效** —— 填 255 之后该点
  读出来仍是 0，于是"气泡那一条"永远进不了掩膜。改成**用 numpy 直接构造字节**。
* **`QBitmap.fromImage` 的行为因图而异** —— 全白图可用、半白半黑却被整体清零。
  统一走 `Format_Mono` 转换，并实测出位语义：**黑 = 位置位 = 可点，白 = 穿透**。
  用棋盘格图验证过（偶数行白 → 掩膜取奇数行），不靠猜。

还有一条最隐蔽的：**把精灵和气泡合到同一张画布时必须逐点取较大值，不能直接覆盖**。
精灵在气泡那一段是透明的（阈值后为 0），直接赋值会把气泡的"可点"抹掉。症状很特别——
**气泡只有下半部分被遮挡**：掩膜里气泡那块只剩上半 59→30 像素，因为从精灵绘制框顶部
开始的那些透明行把下半截刷成了 0。

另外**空掩膜等于窗口既不可见也点不到**（`clearMask()` 在 Windows 上就是这个结果），
所以任何分支都不能产出空掩膜；没有内容时按整窗可点处理。

回归自检：`tools/selftest_whisper_live.py` 会断言两件事——气泡矩形落在掩膜内，
**并且必须等到真实台词**（只测到占位气泡"……"不算通过，那时测的是占位符的尺寸）。

### 10. 气泡距本体远近：让留白等于气泡高度，不要去猜头顶位置

气泡画在精灵上方的留白区里。最初留白是写死的（配图 58 + 文字 34 = 92），而气泡实际
只有五十来像素，于是中间空出一大段。改成**留白 = 气泡高度 + 余量**，气泡紧贴这段留白
的下沿，距离就必然最小。

中途试过"按帧内透明边比例推算角色头顶在哪一像素"来定位气泡——**这条路是错的**：
精灵帧顶部自带约 31px 透明边（实测占帧高 17.4%~17.8%），推算出来的坐标在渲染里对不上，
气泡一度被夹到窗口顶部。改成"留白跟着气泡走"之后就不需要任何推算了。

`BUBBLE_SINK = 26` 让气泡再往画面里压一点，压进那段透明区，视觉上贴着头发。

### 11. 系统通知不能用焦点事件触发（否则永远不弹）

原来的写法是"窗口**先获得过焦点、再失去焦点**"时通知。但桌宠窗口带
`WA_ShowWithoutActivating`——**它本来就极少拿到焦点**，于是那条通知实际上永远不会弹，
而 `notificationsEnabled` 看起来又是"已接"的：一个静默失效的功能。

现在改成判断**前台窗口的进程名**（`user_is_watching()`，用 `GetForegroundWindow` +
`QueryFullProcessImageNameW`）：前台是 DSH 或桌宠自己时才算"用户在看"，其余情况才值得
打扰。取不到前台进程时**返回"没在看"**（即允许通知）——宁可多弹一条，也不要静默失效。

触发时机也换了：挂在 `apply_mood` 的**一次性状态**上（`celebrating` 干完了 /
`sighing` 出错了），而不是焦点事件。持续状态（思考/忙碌/归档/漫游）不通知，否则刷屏。
再加 `NOTIFY_COOLDOWN = 90` 秒限流。

回归自检：`tools/selftest_notify.py`（8 项，含"该弹/不该弹/限流/开关/状态挂钩"）。

### 12. 日志会自动清理，但按"保留最近的"清

`--watch` 每秒写一行，原先**没有任何上限**。但清理不能直接清空——这些日志的用途正是
"桌宠消失后看最后几行"，清空等于把线索一起丢掉。所以规则是
**超过 1 MB 就只保留尾部 256 KB**（按字节 seek 后对齐到行首，不把整个文件读进内存）。

覆盖 `logs/` 下的 `pet-run.log`、`watch.log`、`whisper-steps.log`、`crash*.txt`：

* 包装层 `run_logged.py` 在**启动时**和**每次子进程退出后**各清一次（裁之前必须先关闭
  句柄——子进程的 stdout 挂在同一个句柄上）；
* 碎碎念流水是桌宠**进程内**追加的，包装层管不到，所以 `main.py` 启动时也调一次。

回归自检：`tools/selftest_log_trim.py`。手工清理：`python tools/run_logged.py --trim-logs`。

### 13. "原地待着"曾经是个纯装饰（配置项没人读）

右键菜单 → 模式 → 原地待着，原先只是 `setattr(self, "mode", k)`，而**代码里没有任何
地方读 `self.mode`**——宠物照样会自己走开。这是本项目第三次出现同一类问题
（前两次是 `whisperEnabled`、`workStatusEnabled`）。同类漏网的还有 `fixedEnabled`：
它只被解析成属性，同样没人读。

现在把两条路统一到 `PetWindow.set_mode()`：

* `Animator.next_auto()` 在"原地待着"时**不把移动档放进权重池**，所以它不会自己走开；
* `PetWindow.on_move()` 拒绝**自动**移动产生的速度；
* `step_physics()` 里对 `self.vx` 再兜一道（惯性、以及别的路径赋的值都会在这里生效）；
* **`fixedEnabled = true` 会作为启动模式**（初始化时就调 `set_mode("still")`）。

**「走走看」不受模式限制**——那是用户主动点的，模式管的是"别自己乱跑"。实现上用
`_manual_move` 标记放行。这个标记的复位有个坑：**不能见到 `walking=False` 就复位**，
因为移动动画有约 2 秒前导（`lead_sec`），前导期间每帧都发 `moved(0, False)`，那样会把
刚置上的标记在第 0 帧抹掉，手动走动依然走不了。要等 `animator.move is None`（真的结束）。

回归自检：`tools/selftest_still_mode.py`（9 项，用**真实位移**判定，不是看标志位）。
它开头会**断开桥信号**与桌宠隔离——因为桌宠在跑时 DSH 会一直推 mood/workStatus，而
工作状态会让 `next_auto()` 直接播工作动画、不走权重池，自检就会莫名其妙地失败
（实测：插件重启后本项报过 1 项失败）。

> 写这个自检时踩了两个坑，都记在测试文件的注释里：① 用"固定 `random.uniform` 返回大数"
> 想让抽取落到移动档，结果抽中的是分类随机动作；② 把 `random.uniform` 固定成 `0.0`，
> 而 `MoveSpec.distance()` **也调用它**，于是每个移动的距离都变成 0 像素——测试把要测的
> 东西自己破坏了，表现为"自由活动也不动"，害我回头查了半天实现。

### 14. `audit_gaps.py` 也要防止自己漏报

`audit_gaps.py` 第 1 节查的是"配置字段名有没有出现在代码里"，而 `config.py` 里那行
`setattr(self, key, ...)` 本身就满足它——所以 `fixedEnabled` 明明没人读却一直显示
"已接"。第 5 节改成查"**在 `config.py` 之外**有没有人真正读取"，并且要同时认
camelCase 配置键与 snake_case 属性名（`chatImageEnabled` ↔ `config.chat_image_enabled`，
只查前者会把 5 个确实在用的字段误报成未接）。

回归自检：`tools/selftest_audit_fields.py`（正反两面：真字段要认出、假字段要报出）。

### 15. `busy` 状态需要一个兜底看门狗，否则宠物会**永久**卡在一个动作上

用户报"停下来只有一个动作，是不是原地模式的问题"。实测**不是**：idle 状态下 40 秒内
播了 3 个不同动作（`吃白饭`、`螃蟹走路`…），池子（1 个 idle + 5 个分类共 83 个动作）
轮换正常。真正的原因是宠物卡在 `workStatus=工作状态-忙碌点按` 再没回 None。

为什么卡住：`sendMood('busy')` 之后，能清掉它的只有

* `tools/result` 的 4 秒衰减（`busyTimer`），或者
* `agent/status idle`

而 `tools/call` 那条只设 busy、**不设定时器**。一轮若以错误/中断结尾，`tools/result`
与 `agent/status idle` 都可能不来，于是永久卡在同一个工作动作上。

修法：`tools/call` 时额外安排一个 `busyWatchdogSec`（默认 90 秒）的兜底，超时且期间没有
状态刷新就退回 idle；而 `clearBusy()`（有真实活动时）会**撤掉**它，避免在正常长任务里误报。
90 秒取得远大于单次工具耗时——它只防"永久卡死"，不打断正常工作。

回归自检：`tools/test_busy_watchdog.mjs`（5 项：进入 busy、无后续事件时兜底回 idle、
有真实活动时撤销、一轮正常结束回到 idle、途中经过 celebrating）。

> 这个自检也踩了一个坑：`agent/status idle` 之后**不会立刻**是 idle——那一轮用过工具，
> 会先走 `celebrating`（`FLASH_MS` = 6 秒）再回 idle。只等 300ms 就断言，会误判成失败。

### 16. 插件的一个 `ReferenceError` 把**整个 DSH 宿主**搞崩了

真实事故。我重构余额分档时把局部的

```js
const balanceTierLabel = (total) => BALANCE_BANDS[balanceTier(total)].label;
```

删掉、只留了导出用的 `apply.balanceTierLabel = ...`，而 `reportUsage` 用的仍是本地名字。
它在 `setTimeout` 回调里抛错，DSH 宿主直接：

```
dsh: fatal load failure: ReferenceError: balanceTierLabel is not defined
    at Timeout.reportUsage (…/dsh-pet-bridge/lib/index.js:381:59)
```

**整个应用崩了**，不只是桌宠掉线。一个装饰性插件不该有这个能力，所以做了两层处理：

1. **修复**：本地 `const` 与导出**两件都要**，不能只留后者；
2. **加防护**：`guard(label, fn)` 把回调包一层，出错只记一行 warn；
   所有事件订阅改走 `safeOn`（内部用 `guard`），所有 `setTimeout` 回调
   （busy 看门狗、一次性状态回落、报用量）也过 `guard`。
   这样**任何插件自身的异常都不可能再拖垮宿主**。

崩溃日志位置（找 DSH 自己的崩溃原因时很有用）：

```
%APPDATA%\@deepseek-ai\dsh-desktop\logs\crash-<时间>-host.log
```

> 为什么先前的测试没抓到它：`tools/test_balance.mjs` 只打 `/health`，那条路走
> `balanceTier`；而 `balanceTierLabel` **只在 `reportUsage` 里用**，那条路要等
> `FLASH_MS + 400ms` 后由 `setTimeout` 触发——**从没被覆盖过**。
> 所以补了 `tools/test_plugin_robustness.mjs`：它真的走一轮、等 `reportUsage` 发出
> `/usage`，并静态检查"没有绕过 guard 的订阅"。教训：**错误处理代码本身也要有测试**，
> 否则它只是"看起来存在的保护"。

### 17. 三类"配了却到不了"的死代码

排查"还有什么已知问题"时系统性查出三处同类问题——**代码/配置在那儿，但没有任何路径能用到它**。
这类问题的共同点：**不报错**，只是行为比预期少一点，很难被注意到。

**① `animations.turn`（「东张西望」）永远不播。**
`next_auto()` 的文档字符串写着"idle / turn / move / 分类随机动作"，但权重池只装了
idle + categories + move，**漏了 turn**；而唯一会播它的 `Animator.face()` 又没有任何
调用点。现在 `turn` 进了池子（权重 5），实测可被抽到。

顺带**没有**把 `face()` 接进转向逻辑：那会让每次改变朝向都插一段约 2 秒的转身动画，
把行走动作打断，体验更差。该方法的意图由"turn 进池子"满足，所以直接删掉了它。

**② `FrameStore.unpin()` 从没被调用 → pin 泄漏 → 内存只增不减。**
`Animator.play()` 每换一段都 `store.pin(name)`，但**从不 unpin**，`_pinned` 无限增长；
而 `_touch()` 淘汰时会"跳过 pinned"，钉子一多淘汰就失效。实测常驻 500MB 以上。
现在 `play()` 走 `store.retain(name, 2)`，只保留最近两个
（当前 + 上一段，后者是交叉淡化要用的垫层）。

> `retain()` 第一版用 `set` 实现，而 **`set` 不保序**——按"非 name 的先解"裁剪，结果
> 把**最近**的几个解掉了、反而留下最旧的（实测 `retain('C')` 之后留下的是 `A`）。
> 改用 `deque` 记录钉入顺序才对。

**③ 两个纯死方法**：`PetWindow._bitmap_from_mask()`（只剩转调 `mask_bitmap` 的兼容包装）
与 `PetWindow.clear_usage()`（无人调用）。已删。

回归自检：
* `tools/selftest_anim_reachability.py`——在**受控随机数**下穷举 `next_auto()` 的分支，
  确认 turn / idle / 各分类 / move（且原地模式下抽不到 move）都可达；
* `tools/selftest_memory_bound.py`——连播多段后内存动画数仍被 `keep` 约束、钉子 ≤ 2；
* `tools/selftest_open_chat.py`——替换 `QInputDialog` 后覆盖对话界面的四条分支。

### 18. 打包分发：两个包，一个安装脚本

目标：把一个 zip 发给别人，对方解压后跑一个脚本就能用。

#### 帧来源变过：现在是"流式解码"，不再必须带 2.6 GB 帧

**2026 年的这次改动**：默认帧来源从"预解码 PNG 缓存"改成**运行时 ffmpeg 流式解码**
（`stream_frames.py`）。理由与数据见 [帧来源](#帧来源stream-与-cache) 一节。

对打包的影响，也因此有了第二种选择：

| | 带帧（`cache` 模式） | 流式（`stream` 模式，新） |
|---|---|---|
| 包大小 | 约 2.1 GB | **约 115 MB**（webm 52 + ffmpeg 62） |
| 对方需要装 | **只要 PyQt5** | PyQt5 + ffmpeg |
| 首次播新动画 | 立刻 | 约 94 ms |
| 磁盘常驻 | 2.6 GB | **0** |
| 画质 | 与流式逐像素相同 | 与带帧逐像素相同 |

**两种模式产出的画面逐像素完全相同**（实测最大差 0/255），所以这是纯粹的
"磁盘空间 / 依赖 / 首帧延迟"三者取舍，不是画质取舍。

`install.ps1` 的 `-SkipFrames` 与默认路径沿用"带帧"（对使用者依赖最少）；
但**源码 clone 的路径（GitHub）现在默认走流式**，不再需要跑解码命令。

#### 兼容性是在隔离环境里实测过的

不能想当然地认为"我这能跑，别人也能"。代码里对版本敏感的写法有几处
（`sip.voidptr.setsize`、1bpp 掩膜的位语义），所以专门建了干净 venv 装
**PyQt5 5.15.11 / Qt 5.15.2**（本机平时跑的是 5.9.2）跑了全部自检：

* 掩膜尺寸变化 / 掩膜位语义 / 交叉淡化 / 可见性 / 点击 / 界面 —— 全部通过
* 原地待着 / 内存有界 / 动画可达性 / 配置接线 / 日志清理 / 审计字段 / 独立运行 / 通知 —— 全部通过
* **numpy 屏蔽后**（模拟没装）掩膜 / 点击 / 内存也全部通过 —— 纯 Python 回退有效

结论：`PyQt5>=5.15,<6`，numpy 可选。`requirements.txt` 里写明了这个理由。

#### 三个真实踩坑

**① `install.ps1` 里的中文会让 Windows PowerShell 5.1 读成乱码。**
`.ps1` 是**无 BOM 的 UTF-8** 时，PS 5.1 按 ANSI 解码，中文字符串直接断裂，报出
"字符串缺少终止符"之类的怪错。解决：三个脚本都存成 **UTF-8 with BOM**。

**② 注释里的反引号仍然是转义符。**
写 `# 避免用 `"{1,8:N1}"` 这种格式` ——PS 会把行尾换行转义掉，于是解析报出
莫名其妙的 `Unexpected token '}'`（指向的是别的行）。解决：注释里不用反引号；
需要引号转义就用 `[char]34` 拼接，而不是反引号。

**③ Windows PowerShell 5.1 不支持格式串的「对齐」写法。**
`"{1,8:N1}" -f $x` 在 PS 5.1 里报 `Unexpected token '{'`。解决：自己用
`PadRight()` 补空格。

**④ 哈希字面量不能写在 `$(...)` 里当命令参数。**
`Write-Status $ok $(if(...){0}else{1}) $x ([ordered]@{a=1})` 会报错，而
`$ErrorActionPreference = 'Stop'` 让脚本**在收尾处静默中止**——症状极具迷惑性：
输出看起来全部正常、连"接下来…"都打印了，但**状态文件没生成、退出码是 -1**。
一旦交给智能体，它就会因为拿不到状态文件而无法判断成败。解决：哈希先赋给变量再传。

**⑤ 编辑工具会去掉 `.ps1` 的 BOM。**
用编辑工具改完脚本后必须**重新补 BOM**，否则又回到坑 ①。再看到
`Unexpected token '}'` 时，第一件事就是查前三个字节是不是 `EF BB BF`。

#### 安装脚本做了什么

1. 检查 DSH profile 是否存在（要先启动过一次 DSH）
2. 找 Python ≥3.8（`py` → `python` → `python3` 依次尝试，并验证版本）
3. 把背景插件复制进 profile 的 `node_modules`，并**在 patch 末尾追加**一行登记
   （幂等：已登记就不重复插；只追加，不动对方已有配置）
4. 把桌宠复制到 `%LOCALAPPDATA%\DshPet`
5. **建独立 venv** 再装 PyQt5（不污染系统 Python），并跑 `--status` 冒烟测试
6. 建桌面快捷方式；开机自启会问（默认不装）

`uninstall.ps1` 对称地做：停进程（按命令行匹配 + 释放 8899 端口）、删目录与快捷方式、
移除自启，并问是否摘掉背景插件（只删它自己追加的那几行）。

> 卸载脚本**无论如何都会清本机的快捷方式与自启**——这是设计意图，但意味着
> 在开发机上测试它会真的删掉自己的快捷方式（我测试时就删了，已恢复）。

#### 怎么打包

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_package.ps1
# 可选： -SkipFrames（不带帧，57MB）  -SkipZip（只组装不压缩）  -OutputRoot <目录>
```

产物是 `dsh-pet-share\`（可直接发）与同名 `.zip`。

#### 没有随包带的东西

* **webm 源素材**（52MB）——带了帧就用不到它；想自行重建帧的人可以把它放进 `pet\webm\`
* **自检脚本与一次性诊断**——它们会在别人机器上因缺少素材/插件而失败，反而让人
  以为装坏了，所以打包时精简掉了（`tools\` 只留 `run_logged.py`、`asset_pipeline.py`、
  `make_icon.py`、`make_memes.py`）

### 19. 让这个包能被「别人的智能体」直接安装

用户问："对方下载好压缩包可以直接交给他电脑上的智能体解决吗？"

**可以，但原始版本会把它卡住**：两个交互式询问（自启、卸载确认）会阻塞等输入，
而且成功与否只能靠解析中文输出。为此做了四件事：

**① `-NonInteractive` 模式。** 不弹任何 `Read-Host`；需要用户拍板的事一律
**默认不做**（不装开机自启、卸载时保留背景插件）——智能体不该替用户决定这些。

**② 机器可读的结果。** 安装会写 `install-status.json`：

```json
{"ok":true,"exitCode":0,"stage":"done","message":"安装完成",
 "venv":"...\\.venv","python":"3.8","hasFrames":true,
 "smokeTest":true,"shortcut":"...","autostart":false,"bgPlugin":true}
```

退出码：**0 成功 / 1 环境不满足 / 2 安装过程失败**。智能体只需判 `ok`，
另外重点看 `smokeTest`（false = 装上了但起不来）。

**③ `-Check` 只读体检。** 逐项核对 DSH profile、venv、PyQt5、桌宠主体、帧素材、
背景插件及登记、启动包装，并报告桌宠此刻是否在运行。安装后核实、排查问题都用它。

**④ 包根目录放一份 `AGENTS.md`**，与给人看的 `安装说明.md` 分开：前者写成
"可直接执行的步骤 + 机器可读的判据"，并明确告诉智能体哪些事必须留给用户
（重启 DSH）、哪些文件不用读。

实测验证过整条智能体路径：

| 步骤 | 结果 |
|---|---|
| `install.ps1 -NonInteractive` | 退出码 **0**，129 秒，全程无询问 |
| 读 `install-status.json` | `ok=true`，`smokeTest=true` |
| 启动装好的桌宠 | `/health` **2 秒**应答 |
| `uninstall.ps1 -NonInteractive` | 退出码 **0**，背景插件如约保留 |

> 测试卸载会真的删掉本机的快捷方式与自启（脚本的设计意图），所以测之前要备份、
> 测完用同样的值恢复——第一次没备份，只能手动补。

### 20. 「内部物种名」与「给用户看的名字」必须分开

用户报："我在任务栏看到的大肥鱼的名字是**蓝毛小女仆**。"

根因：`PetWindow` 的窗口标题直接用了 `config.name`：

```python
self.setWindowTitle(config.name)      # config.jsonc 里的 "name": "蓝毛小女仆"
```

而 `config.name` 是**内部物种名**，同时还是素材目录与物种配置的键
（`frames\<name>\`、`pet\<name>-config.json`）——改它会把那些地方一起带偏。
于是一只宠物出现了**三个名字**：

| 位置 | 之前用的 | 显示成 |
|---|---|---|
| 任务栏 / 窗口标题 | `config.name` | 蓝毛小女仆 |
| 托盘提示 | **硬编字符串** | 大肥鱼桌宠 |
| 系统通知 | **另一个硬编常量** | 大肥鱼 |

修法：配置新增 `displayName`（实例值 → 全局值 → 退回物种名），
任务栏、托盘提示、通知**全部**走 `PetWindow.display_name()`；
`--status` 把两个名字都打出来，方便一眼看出映射对不对。

> 顺带发现：`user_is_watching(pet_name)` 那个参数一直是无效的——传进去的是
> **内部物种名**，而前台判断比的是**进程名**（`pythonw.exe`），永远匹配不上。
> 已去掉这个分支。

回归自检：`tools/selftest_display_name.py`（10 项：四级取值优先级、
窗口标题/托盘/通知三者一致、且都不等于内部物种名）。

> 写这个自检又抓到一个真 bug：`displayName` 写成**空白字符串**时，
> `entry.get("displayName") or ...` 不会退回物种名（`'   '` 是**真值**）。
> 要显式 `strip()` 之后再判断。这条已进自检。

### 21. 把"反复踩的引号/编码坑"变成有约束可查的规则

这个项目里我**至少 6 次**在同一个坑里打转：用 `pwsh` 内联多行 Python 代码做文本替换，
然后被 `SyntaxError: EOF while scanning triple-quoted string literal` 之类的错误绕进去。
根因是**多层引号解析**——PowerShell 先解析一遍，再交给 `python -c` 解析一遍，
中文、嵌套引号、`$(...)`、反引号、`%` 都会在其中一层被吃掉。

修法不是"下次小心点"，而是把它变成**有约束、可自查**的东西：

**① 工作区规则文件 `AGENTS.md`（放在仓库上一级的工作区根目录）。** DSH 会自动加载它，
所以以后每个会话都受约束。
里面有规则的正面/反面例子、判断标准（超过一行 / 含中文 / 含嵌套引号 / 需要文本替换
→ 必须先写成文件），以及"最短排查路径"。

**② 一条命令的语法守卫 `tools/check_syntax.py`。** 按扩展名分别检查：

| 扩展名 | 检查内容 |
|---|---|
| `.py` | `ast.parse` |
| `.ps1` | **UTF-8 BOM**（缺了自动补） + 无反引号 + 真正交给 PowerShell 解析 |
| `.js` / `.mjs` | `node --check` |
| `.json` / `.jsonc` | 能否解析（含 JSONC 注释处理） |

```powershell
python tools/check_syntax.py --staged     # 只查刚改的
python tools/check_syntax.py              # 查全项目（54 个文件，0 问题）
```

**③ 依赖自检 `tools/doctor.py`。** 一条命令报出 Python / PyQt5 / numpy / Pillow / ffmpeg /
帧素材 / 图标 / 配置是否齐备，以及"能不能跑"。装到别人机器上出问题时先跑它。

**④ `tools/check_ps1.py`。** 只管 `.ps1` 的 BOM 与反引号，可单独用。

**⑤ 打包时 `tools/` 走白名单。** `build_package.ps1` 里 `$toolsKeep` 只保留
`run_logged.py` / `asset_pipeline.py` / `make_icon.py` / `make_memes.py` 四个运行时脚本，
其余一律从包里剔掉——自检与一次性诊断脚本在别人机器上会因缺依赖而失败，反而让人以为
装坏了。所以**分发包里没有上面这些自检脚本**，它们只存在于开发目录。
（更新补丁是例外：它额外带上 `doctor.py` / `check_syntax.py` 与 3 个自检，
方便已安装的用户自查，见 `tools/build_update.ps1`。）

**两个守卫都用故意写坏的文件验证过能抓到问题**——否则它们只是"永远通过的摆设"
（这个项目已经吃过"错误处理代码本身没被测"的亏，见第 16 条）。

> **顺带纠正了我自己写错的一条规则。** 我一度把"PS 5.1 不支持格式串对齐
> `"{1,8:N1}"`"写成了规则。实测**这是错的**：`"{0,10:N2}" -f 3.14159` 完全正常。
> 当时那个 `{` 报错的真正原因是**文件缺 BOM** 导致中文被按 ANSI 读成乱码。
> 教训写在规则 6 里：**报错行号看起来没问题时，先怀疑编码 / 引号 / 不可见字符，
> 而不是那一行代码本身；而且一旦把结论写成规则，要回头验证它真的成立。**

### 22. 「窗口矩形」与「角色实际占位」是两回事

用户报两件事：

1. **"不能放在屏幕任意地方，已经是最右侧了但没到屏幕最右边"**
2. **"初始位置给我放到右下角"**

两件事的根因都是**把窗口当成角色**。

#### 实测数据（`size=320` 逻辑）

```
帧素材 640x360，角色只占中间一块：
    点击回应-开心跃动   x=209  226x256  -> 占画面宽 35.3%
    待机呼吸休闲       x=213  213x266  -> 占画面宽 33.3%

窗口 320 逻辑，掩膜包围盒 [108, 32, 105, 133]：
    角色可见宽仅 105 逻辑像素（屏幕 210 物理像素）
    左右各有约 107 逻辑像素是**透明留白**
```

#### 问题 1：贴边贴的是留白

`step_physics` 里用窗口宽度贴屏幕边：

```python
elif self.pos_x + self.width() > area.right():      # 窗口宽 320
    self.pos_x = float(area.right() - self.width())
```

窗口贴住了边，但那圈 107px 的透明留白先碰到了屏幕边，**角色本身**停在离屏幕边
约 107px 处——看起来就是"没放到最右边"。

修法：新增 `character_bounds()` / `character_insets()`，读数取**掩膜的实际包围盒**
（`mask_stats["rect"]`），贴边、居中、初始摆放全部改成按角色算。撞右墙后
窗口右边缘可以超出屏幕（留白被推到屏幕外），角色右边缘正好贴边：

```
撞右墙:  角色右边缘 = 1279 = 屏幕右边缘    （窗口右边缘 = 1386）
```

> **第一版修错了数据源**：`character_bounds()` 用的是 `sprite_rect()`，而那是
> "窗口内的绘制矩形"（每段动画都与窗口等宽），跟角色实际占哪儿无关——算出来的
> 留白恒为 0，自检里"角色确有留白"那一项立刻失败。**掩膜**才是 `setMask` 真正
> 决定"显示什么、哪里能点"的区域，用它才准。

#### 问题 2：`bottom-right` 被摆到了顶部

```python
if "top" in corner or not self.use_gravity():
    y = area.top() + margin_y      # ← corner 是 bottom-right，却走这一支
```

配置里 `corner: "bottom-right"` 配上 `physics.gravity: 0`（本机正是如此），
于是启动时被摆到**右上角**。重力只该决定"随后会不会往下掉"，不该决定"摆在哪一角"。

修法：上下完全按 `corner` 决定；重力只影响之后的物理。

#### 时序陷阱：`_place_initial()` 在 `__init__` 里跑，那时还没有掩膜

`__init__` 调用 `_place_initial()` 时**帧还没加载、掩膜没算过**，`mask_stats` 是
`None`，`character_insets()` 只能退回绘制矩形（留白 = 0）——"按角色贴边"这个修正
等于没生效（实测角色右边缘离屏幕边 117px，而不是 marginX 的 24px）。

修法：`_settle_initial_placement()`——掩膜算好后补一次对齐，并在**启动窗口期**
（`SETTLE_WINDOW_SEC = 4s`）内跟随掩膜修正。需要窗口期是因为不同动画的角色宽度
不同（`mask.rect` 实测在 105~238 之间浮动），只对齐一次仍会偏十几像素。

#### 但"自动对齐"必须能被关掉

这个补丁立刻踩了两个坑：

* **测试被干扰**：`selftest_still_mode.py` 在启动窗口期内反复移动宠物测位移，
  自动对齐把它拽回去，于是"自由活动会走开"变成 0 像素、"原地待着不动"反而有位移
  （3 项失败）。
* **`/place` 被覆盖**：`POST /place {"center":true}` 之后角色中心停在 1203 而不是
  屏幕中心 640——居中刚做完，结算逻辑又把它摆回角落。

修法：`_user_took_over()` 把自动对齐彻底关掉，**用户一碰就永久停止**。
鼠标按下、「走走看」、显式 `/place` 都会调用它；自检也可以直接调它把这段逻辑关掉。

回归自检：`tools/selftest_character_bounds.py`（7 项：留白存在、左右撞墙按角色贴边、
初始位置在右下角且 margin 量的是角色边、居中居的是角色中心）。

### 23. 「启动窗口」的计时**绝不能在对齐时刷新**（否则拖不动宠物）

用户报："没法拖动大肥鱼，拖动时还是停留在原地，松手后就消失了然后又出现在出生点。"

根因是第 22 条那套启动对齐的一个写法错误：`_place_initial()` 结尾写了
`self._placed_at = time.monotonic()`（刷新计时），而 `_settle_initial_placement()`
又调用 `_place_initial()`。**掩膜在播放动画时持续变化、每次变化都会触发一次对齐**
——于是这个"4 秒启动窗口"每次触发都被重新计时，**永远不会结束**。

后果链条：

1. 宠物在每个动画帧都被搬回出生点；
2. 用户按下时若那一点不在角色掩膜里（裙边、发梢、两腿之间都可能），
   `dragging` 起不来 → `mouseMoveEvent` 什么都不做 →"停在原地"；
3. 掩膜继续变化继续搬 →"松手后消失又回到出生点"。

为什么在自己机器上不一定复现：只要**有一次**按下落在角色身上，
`_user_took_over()` 就把它永久关掉了。所以这个 bug 专挑"第一下没抓到"的用户。

修法：截止时刻改成**绝对**的 `_settle_deadline`，只在 `__init__` 首次摆放后设一次；
`_place_initial()` **不准**碰它；过期时置空。全项目只有 4 个写入点
（init 置 None、首次摆放后设截止、`_user_took_over()` 清空、过期清空）。

**回归自检**：`tools/selftest_settle_window.py`。反向验证过：把写法改回"每次续期"，
它必须失败（实测退出码 1，`_settle_deadline=894075.187`）。

教训：凡是"只在启动若干秒内生效"的逻辑，计时起点必须是**不变量**。
用"最近一次动作的时间"当起点，等于把窗口变成"只要还在动就永远有效"。

### 24. 多显示器：`primaryScreen()` 会把副屏上的宠物拽回主屏

`_place_initial` / `ground_line` / `step_physics` / `place` 四处都写死
`QApplication.primaryScreen().availableGeometry()`。

单屏机器上完全看不出问题，接了副屏就暴露：

- 把宠物拖到副屏 → **拖动过程中** `step_physics` 跳过墙壁判定，一切正常；
- **一松手** → 墙壁判定按主屏算，宠物被拽回主屏边角。

用户看到的就是"拖过去，松手就消失、又出现在出生点"。

修法：`screen_area_for(point)`（模块级）+ `PetWindow.current_screen_area()`
（按**窗口中心**判定所在屏幕），四处改用它。启动最早期 `pos_x` 还没赋值，
`current_screen_area()` 退回主屏 —— 全项目只保留 2 处 `primaryScreen()` 兜底。

两个实现细节：

- **不要用 `QApplication.screenAt()`**：它是 Qt 5.10 才有的，而本项目要支持
  PyQt5 5.9.2（Qt 5.9.7）。用遍历 `screens()` 自己找。
- 判定用**窗口中心**而不是左上角：宠物贴边时有一圈透明留白挂在屏幕外，
  但中心一定还在屏内。

**回归自检**：`tools/selftest_clickable_area.py`（角色中心可点、透明四角穿透、
真实拖动确实改变窗口位置）。多屏行为本机只有一块屏，**没法在这里复现**，
需要在双屏机器上实测。

教训：单屏机器上写"屏幕几何"，等于只在一种配置下测过。
凡是取 `primaryScreen()` 的地方，都要问一句"如果宠物在另一块屏上呢"。

### 25. "是不是派生物"不能决定"要不要进仓库"——图标缺了会静默少功能

用户报："GitHub 上发出去的他们用起来图标是没有的。"

根因：打包发布时把整个 `assets/` 目录排除在 `.gitignore` 外，理由是"图标是从
`webm/待机呼吸休闲.webm` 裁出来的派生物，可由 `tools/make_icon.py` 重新生成"。
理由本身没错，但**漏了一个更重要的问题：运行时要不要它**。

`src/pet.py` 的 `make_icon()`：

```python
if os.path.exists(ICON_ICO):        # assets/icon.ico
    ...
if os.path.exists(ICON_PATH):       # assets/icon.png
    return QIcon(ICON_PATH)
return QIcon()                      # 两个都没有 -> 空图标，且不报错
```

于是缺图标的效果是：**窗口和任务栏都没有图标，桌面快捷方式也是白板**
（`install.ps1` 的 `$icon` 指向同一个文件）。而整个程序**不会抛任何异常**，
不写日志、不弹提示 —— 从使用者看就是"这个软件没有图标"，从开发者看一切正常。

修法：
* `assets/`（4 个：`icon.ico` / `icon.png` / `icon-head.ico` / `icon-head.png`）
  与 `memes/`（8 个）**进仓库**，合计约 790 KB，相对于 52 MB 的 webm 可以忽略；
* `assets/icon-full.*` 是孤儿（应用不引用、当前 `make_icon.py` 也不生成），
  单独排除并写进审计的 `FORBIDDEN_FILES`；
* `make_icon()` 在两者都缺时**写一行 stderr 指路**（本项目"不留静默失败"的惯例）。

**回归自检**：`tools/selftest_runtime_files.py`。它不手写清单——那样迟早与代码脱节
——而是用 AST 扫 `src/` 与 `main.py` 里所有 `os.path.join(ROOT, "a", "b")` 常量，
得到"代码引用了哪些项目内路径"，再逐个验证存在性。`logs/` 归为运行时创建、
`frames/` 归为可选，其余**缺一即失败**。已反向验证：临时移走 `assets/icon.ico`
它必须失败（实测退出码 1，并指出被 `src/pet.py` 引用）。

`tools/verify_fresh_clone.py` 也补上了硬期望（`assets`/`memes`/`webm` 必须在、
`frames`/`logs` 必须不在、四个图标文件逐个点名）——原先它只**打印**目录在不在、
没有断言，所以图标缺失一路放行。

教训有两条：

1. **判断文件该不该进仓库，要同时问"运行时要不要它"**，不能只看是不是派生物；
2. **"打印检查结果"不等于"检查"**——没有断言的输出，在出问题时和没检查一样。

### 26. 帧来源改成"运行时流式解码"：磁盘 2.6 GB → 0

**背景**：上游 dsh-pet 让浏览器/Electron 的 `<video>` 直接播透明 VP9 的 webm，
GPU 解码、不落盘，所以整个插件只有 62 MB。我们做不到——Qt 的 `QVideoWidget`
是**不透明**的原生窗口，不合成 VP9 的独立 alpha 流；本机的 PyQt5 5.9.2 连
QtMultimedia 都没有。所以历史上只能把每个动画解成 241 张 PNG，
于是本机多出 **2.68 GB / 25423 个文件**的帧缓存。

**但"不解码"不是唯一出路**：可以**运行时流式解码，不写磁盘**。

#### 动手前先验证的三件事（都实测过，不是推断）

| 假设 | 结论 |
|---|---|
| `-stream_loop -1` 能用在带 alpha 的 VP9 上 | **能**。读 249 帧，第 241 帧与第 0 帧**逐字节相同** —— 所以循环播放不需要重起进程 |
| 流式像素与磁盘 PNG 缓存一致 | **逐像素相同**（最大差 **0/255**）。换帧来源不改变画面 |
| 帧数能准确拿到 | `ffprobe -count_frames` = 241 = 磁盘 PNG 数。但每次要解码全片（0.2 秒），所以**预生成 `webm-meta.json`**（14 KB，106 个动画）随仓库分发 |

实测开销（`tools/probe_stream_decode.py`）：**起 ffmpeg 到首帧 94 ms，
首帧之后每帧 0.6 ms** —— 24fps 的预算是 41.7 ms，余量约 **70 倍**。

#### 三个设计要点

**① 背压必须挂钩"消费位置"，不能只看缓冲满没满。**
生产者比消费者快 70 倍。若只按"缓冲容量"限流，它会一口气跑到第 200 帧，
而消费者要的第 10 帧**早已被覆盖**。所以生产者每轮检查
`已写序号 - 消费位置 >= LOOKAHEAD` 就等，把内存钉在
`LOOKAHEAD × 900 KB`（16 帧 ≈ 14 MB/动画）而不是整段 217 MB。

**② 只跨线程传 `QImage`，不传 `QPixmap`。**
`QPixmap` 不是线程安全的（而且**没有 QApplication 时创建它会直接中止进程**，
连报错都不给——自检第一版就"没有任何输出"）。读帧线程产 `QImage`，
`frame()` 在 GUI 线程转 `QPixmap` 并缓存最近一张。

**③ 进程必须收干净。**
模块级登记所有存活进程；`close()` / `atexit` / 淘汰 / `clear()` 都会杀；
Windows 上加 `CREATE_NO_WINDOW` 免得每起一个 ffmpeg 就闪一个黑框。
漏掉淘汰那一步的后果是**进程泄漏**：每换一个动画留一个 ffmpeg。

#### 与既有状态机的接法：几乎不用改 `pet.py`

关键发现是 `Playing.frame()` 本来就有这个结构：

```python
source = self.source
if source is not None and len(source):
    return source.frame(self.frame_index())
return self.outgoing          # 上一段的最后一帧
```

所以**在首帧就绪之前不让动画对象进入 store**，就自动复用了现成的
"先切状态、后到位"机制：`play()` 时 `peek` 拿不到 → `playing.animation = None`
→ 继续画上一段（`fallback`）→ 后台线程起流并等首帧 → `loaded` 信号
→ `on_loaded` 接上并把 `elapsed` 归零。绘制层一行没改。

### 27. `_load_sync` 漏改会让"零磁盘占用"**悄悄失效**

换完帧来源、实机跑通、删掉 2.6 GB 缓存都没问题，但跑自检时发现
`selftest_crossfade` 从 **0.3 秒涨到 113.9 秒**，而且 `frames/` 里
**又出现了 564 MB**。

原因：`FrameStore` 有两条取帧入口——`request()`（异步，走 `_start_background`）
和 `animation()`（同步，走 `_load_sync`）。改的时候只把前者分了流，
`_load_sync` 仍然直接调 `_ensure_on_disk()` → `asset_pipeline.build()` →
**解码写盘**。于是任何用 `store.animation(name)` 的地方都会把缓存建回来，
每个动画还要等约 13 秒。

它特别隐蔽的地方在于：**异步路径改对了，桌宠本体跑起来完全正常**
（运行时走的是 `request()`），只有自检和启动预解码这类同步入口会中招。

教训：**改"后端"时要先列出这个类的所有入口**，别只改最显眼那条。
`tools/selftest_stream_runtime.py` 现在会断言"跑完之后 `frames/` 仍不存在"。


### 28. 关掉重力时残余速度**永不衰减** —— 宠物会一直慢慢滑

**现象**（用户报的）："自由活动时其他动作也在动，应该只有跑步散步类才移动。"

一开始我以为是"动作分类"问题，去翻 `moves.actions` 的配置。**实测推翻了它**：
高频采样位置 + 当前动作，发现**所有动作**（含完全不在移动池里的「待机呼吸休闲」）
都在以约 **5.7~7.3 px/s 恒定向右滑**。7.3 px/s ≈ 每分钟 440 像素，肉眼就是"一直在慢慢滑"。
所以根本不是"哪些动作会移动"，而是**一个恒定的背景位移**。

**根因**在 `PetWindow.step_physics()`：

```python
if self.pos_y >= floor:          # ← 重力关时**永远不成立**
    ...
    if self.grounded:
        self.vx -= self.vx * friction * DT   # ← 水平摩擦只写在这里
else:
    self.grounded = False
    # 只衰减 vy，vx 一点都不衰减
```

`gravity: 0` 时宠物停在"放下它的地方"（这是有意的，见 `use_gravity()` 的注释），
那个位置**高于** `ground_line()`，于是 `pos_y >= floor` 永不成立、
`self.grounded` 永远是 False —— **水平摩擦就没机会执行**。
结果：任何残余 `vx`（移动动画的收尾、撞墙反弹、拖拽甩出）都**永不衰减**。

直接证据：注入 `vx = 60` 后跑 5 秒，残留 `vx = -46.80` —— 正好是 `60 × 0.78`
（撞左墙的恢复系数），也就是说**除了撞墙，一点摩擦都没有**。宠物会一直来回弹。

**修法**：在 `else` 分支里、`use_gravity()` 为假时也按 `groundFriction` 衰减 `vx`。
语义上也说得通：关掉重力 = "宠物待在放下它的地方"，那它就是在"停着"。
重力**开着**时不动那一处 —— 那种情况下 `else` 意味着"宠物被抛在空中"，保持水平
速度才是对的（抛物线）。

**这次踩的两个方法论坑**（都留了注释）：

1. **第一版探针按"整段位移"归因**，于是把上一段移动的残留惯性算到了下一个动作头上
   （记到"工作状态-忙碌点按走了 865 px"）。必须测**瞬时速度**并归因到当时的动作。
   而且当时宠物一直卡在 busy（我在干活，DSH 事件让它保持忙碌），观察到的根本不是
   漫游行为 —— 得先用 `POST /mood {"mood":"idle"}` 把它拉出来。
2. **不能用 `/anim` 接口验证"移动类动作仍然会移动"**：那个端点直接调
   `animator.play(name)`，**不经过 `start_move()`**，所以本来就不位移。实测就踩了
   （三个移动动作 dx 全是 0，差点以为功能被修坏）。必须走真实路径
   `start_move()` → `_tick` 发 `moved` → `on_move` 置 vx → `step_physics` 推 `pos_x`。

配套两个自检（**配对，缺一不可**）：
  * `tools/selftest_no_drift.py` —— 不该动的必须纹丝不动；
  * `tools/selftest_move_translates.py` —— 该动的必须真的走完那段距离。
    只测前者很容易把"宠物再也不会走"当成修好了。

### 29. 移动动作撞墙后会**贴着墙走完全程**

**（本条的问题已修，保留记录是为了留下判据与诊断方法。）**

`start_move()` 里 `move_vx = MOVE_SPEED × facing` 是**一次性定死**的。撞墙时
`step_physics` 会把 `self.vx` 取反（`-vx × restitution`）并翻转 `animator.facing`，
但 `move_vx` 不会跟着变 —— 下一帧 `_tick` 又按原来的方向发 `moved(move_vx, True)`，
`on_move` 又把 `vx` 设回原方向。于是宠物**贴在墙上把 `move_left` 耗完**。

逐帧日志（`tools/probe_move_trace.py`）——修复前：

```text
帧 60   elapsed 2.01 >= lead 2.0 → 开始走，vx=110.1，pos_x 递增
帧 65   pos_x=1063.8（窗口宽 320，右边缘 1384 > 屏幕 1279）→ 已贴右墙
帧 66   vx 翻成 -85.9（110.1 × 0.78），此后 pos_x 恒为 1066.0 不再变
```

**修法**：新增 `Animator.steer_move(direction)`，按"墙在哪边"**显式**给方向
（而不是简单取反 —— 取反依赖 `move_vx` 当前的符号，而撞墙可能是被别的东西推的）。
`step_physics` 的两处撞墙判定各调一次。修复后同一段日志：

```text
帧 66   撞墙 → vx = -85.9，pos_x 被钳在 1066.0
帧 67   vx = -110.1（已掉头），pos_x = 1062.4 开始回落
帧 68+  一路向左走完剩下的距离
```

`steer_move` 里带一个 **0.3 秒的最小间隔**：若宠物被夹在很窄的空间里，每帧掉头
会变成抖动；限流之后它是"来回踱步"而不是抽搐。

配套自检 `tools/selftest_wall_turnaround.py`：把宠物贴着右墙开始走，统计
"**声明在走（|vx|>1）但位置丝毫没动**"的最长连续帧数。
**反向验证过**（临时撤掉 `steer_move` 再跑）：修复前最长 **14 帧**、只离开 30 px；
修复后最长 **1 帧**、离开 97~188 px。

### 30. 「按宠物尺寸缩放步长」只写在文档里，代码里没有

`config.jsonc` 的 `moves` 段一直写着 minDist/maxDist "以基准宠物宽 462px 为准，
运行时按 实际size/462 等比缩放"，但 `MoveSpec.distance()` 与 `config.move_specs()`
**都没有做任何缩放** —— 也就是说 size=320 的宠物仍按 462 的步长走，
**步长偏大约 44%**，看起来像"滑过去"而不是"走"。

**修法**：`move.REFERENCE_WIDTH = 462.0`；`MoveSpec(name, params, scale=...)` 把它
乘在 min/max 距离上；`config.move_specs()` 按 `self.size / REFERENCE_WIDTH` 传进去。
**`margin` 不缩放** —— 它是"别把角色贴到屏幕边上"的余量，属于屏幕几何，与宠物大小无关。

本机 size=320 → 缩放 0.6926：螃蟹走路 60-240 → **42-166**、原地漂浮踏步 40-120 →
**28-83**、原地左转奔跑 120-320 → **83-222**。

教训和 [第 25 条](#25-是不是派生物不能决定要不要进仓库图标缺了会静默少功能) 是同一类：
**文档里写了、代码里没做，而且症状是"手感不对"这种没人会去查文档的东西。**
发现它的路径也不是读文档，而是为了修另一个问题去量真实距离，才对不上。

### 诊断"宠物不见了"

启动时加 `--watch`，会每秒往 `logs/watch.log` 记一行位置/可见性/动画名：

```powershell
pythonw -X utf8 main.py --watch
```

`tools/selftest_visibility.py` 也能长时间跑，分别统计"移出屏幕 / 被隐藏 / 零尺寸 /
无帧"四类异常——这四种症状一样但原因完全不同，只看"可见/不可见"是查不出来的。

### 诊断"拖不动宠物"

`logs/drag.log`：用户每完成一次"按下 → 松手"就记一行。

```text
10-05 02:45:19 press=收到 moved=152 window=(1011,513)->(952,479) settle=已关闭 anim=被鼠标拖拽悬空反馈
```

判读方式——两种原因**现象一样但处置完全不同**，只看现象分不出来：

| 日志表现 | 含义 | 查什么 |
|---|---|---|
| **连这一行都没有** | 按下根本没到桌宠 | 窗口掩膜（`setMask` 同时裁输入）、是否有别的置顶窗口吃掉点击、那一点是否落在角色透明区 |
| **有这一行，但 `window` 位移约 0** | 按到了，窗口没跟着动 | 自动对齐是否还在生效（`settle=` 字段）、拖动中 `setMask` 是否打断了鼠标抓取 |
| `moved` 很大但 `window` 位移为 0 | 光标在动、窗口没动 | 同上；`moved` 量的是光标位移 |

这个日志在长期排查里比"看现象猜"便宜得多——所以它是**常开**的（量很小，
`run_logged.trim_all_logs()` 会一起裁）。

---

## 配置

`config.jsonc` 沿用 dsh-pet 的分层模型（**顶层字段整段替换，不做深合并**）：

- **实例层** `pets[]`：`name` / `id` / `size` / `display`（`web`/`desktop`/`both`/`none`）/ `position`（`corner`/`marginX`/`marginY`）/ 各功能开关
- **全局层**（本文件顶层）：`physics`、`confineToScreen`、`eventsRefreshSec`、`whisperPrompt`、`chatModel`…
- **条目层**：`animations`（`idle`/`turn`/`moves`/`drag`/`clicks`/`categories`/`events`）、`animationWeights`、`workStatusTexts`、`memes`

物理参数：`gravity` 1400、`restitution` 0.78、`groundFriction` 2.5、`ceilingBounce`、`throwPower`。

### 换成自己的美术

- **动画**：`webm/<动画名>.webm` 放透明 webm，配置里引用那个名字即可。
  `stream` 模式下**不需要任何后续步骤**（帧信息缺失时会自动用 ffprobe 探测一次）；
  `cache` 模式下 `frames/` 可以整体删掉，下次播放会重新生成。
  新增一批 webm 后建议跑一次 `python tools/build_webm_meta.py` 把帧数元数据补齐
  （省掉运行时 0.2 秒/动画的探测）。
- **表情包**：`memes/<名字>.png`，名字要和 `tools/make_memes.py` 或插件里的列表对得上。
- 想要更高/更低清晰度：这只影响 `cache` 模式的帧缓存大小。改
  `tools/asset_pipeline.py` 的 `TARGET_WIDTH`，然后
  `python tools/asset_pipeline.py clean` 再重新生成。当前值 **640**：

  | 值 | 全量帧缓存 | 按 640 显示时 |
  |---|---|---|
  | **640（当前，= 素材原生）** | **约 2.6 GB** | **1:1，最清晰** |
  | 480（曾用过） | 约 1.5 GB | 放大 1.33 倍，肉眼几乎无差 |
  | 320 | 约 0.7 GB | 放大 2 倍，明显发糊 |

  **`stream` 模式不受这张表影响**：它按 webm 原生分辨率解码，磁盘始终为 0。
  改完记得同步 `tools/setup_assets.py` 与 README 里的体积说法。
- **表情包**：`memes/<名字>.png`。图片清单由桌宠读目录得到并随请求发给插件，所以
  加一张图不用改插件。

---

## 许可与来源

> 完整的、已核实的说明见 [ASSETS.md](ASSETS.md)。这里是摘要。

| 内容 | 来源 | 许可 |
|---|---|---|
| **106 个动画素材** | [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet) 的 `dsh-pet/assets/webm/` | 素材**允许开源使用**、**禁止商用**、**二创须署名** |
| 功能设计与配置格式 | 同上 | 代码 MIT |
| 本程序代码（PyQt5 重写） | 自研 | [MIT](LICENSE) |

- 本项目是基于 dsh-pet 的**二次创作**，分发时**必须在显眼处**附上
  <https://github.com/PC2005-cloud/dsh-pet>。
- **禁止商用。**
- 与 [gmskywalker/deepseek-fat-fish-codex-pet](https://github.com/gmskywalker/deepseek-fat-fish-codex-pet)
  **没有关系**——早期版本误标过，更正记录见 [ASSETS.md](ASSETS.md) 第三节。

「大肥鱼 / 鲸鱼娘」是 DeepSeek 的社区二创形象，官方从未发布过拟人形象。
