# 给 AI 智能体的安装说明

你（智能体）正在一台 **Windows 10/11** 电脑上，用户下载并解压了这个包，
希望你代为安装「大肥鱼桌宠」+「DSH 对话界面背景」。

**请按下面的顺序做，不要跳过校验步骤。** 全程不需要问用户任何问题——
所有需要用户拍板的事（开机自启、是否摘插件）都已经设计成"默认不做"。

---

## 0. 先看清包里有什么

```
dsh-pet-share\
  AGENTS.md          <- 本文件
  install.ps1        <- 安装
  uninstall.ps1      <- 卸载
  安装说明.md         <- 给人看的说明（你不用读）
  install-status.json     安装结果（运行 install.ps1 后生成）
  profile-plugin\    DSH 的「背景 + 启动动画」插件
  pet\               桌宠本体（Python，已带 2GB 帧素材）
```

**先判断包是否完整**（解压可能不完整）：

```powershell
Test-Path .\pet\main.py            # 必须 True
Test-Path .\pet\frames             # True = 自带帧素材（无需 ffmpeg/Pillow）
(Get-ChildItem .\pet\frames -Directory).Count   # 正常值 106
```

如果 `frames` 不存在或动画数明显少于 106，告诉用户**解压不完整**，
不要继续安装（否则首次播动画会卡 20 秒且需要额外装 ffmpeg）。

---

## 1. 确认前置条件

桌宠是 Python 程序，需要 **Python 3.8+**；装 PyQt5 需要联网。

```powershell
# DSH 是否至少启动过一次（要找得到 profile 目录）
Test-Path "$env:USERPROFILE\.dsh\profiles\desktop"

# 有没有可用的 Python
py -c "import sys; print(sys.version_info[:3])" 2>$null
python -c "import sys; print(sys.version_info[:3])" 2>$null
```

* DSH profile 不存在 → 让用户**先启动一次 DeepSeek Harness**，再继续。
* 没有 Python ≥3.8 → 让用户装 Python（勾选 *Add python.exe to PATH*），
  然后**重新打开 PowerShell**（PATH 才会更新），再继续。

---

## 2. 安装（非交互）

在**解压出来的那个目录**里运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -NonInteractive
```

`-NonInteractive` 保证它**不会停下来等输入**（否则你会卡住）。它还会：

* 把桌宠装到 `%LOCALAPPDATA%\DshPet`
* 在那个目录里建独立虚拟环境 `.venv` 并装 PyQt5（**不动系统 Python**）
* 在桌面建「大肥鱼」快捷方式
* **不**登记开机自启（那是用户该决定的，脚本会说明怎么手动加）

### 退出码

| 码 | 含义 | 你该做什么 |
|---|---|---|
| 0 | 成功 | 进第 3 步校验 |
| 1 | 环境不满足 | 看输出里的提示（缺 Python / 缺 DSH profile），转告用户 |
| 2 | 安装过程失败 | 看输出里的错误（最常见是 PyQt5 下载失败 → 网络/代理问题） |

### 机器可读的结果

不要靠解析中文输出判断成败，读这个文件：

```
install-status.json
```

形如：

```json
{"ok":true,"exitCode":0,"stage":"done","message":"安装完成",
 "petDir":"C:\\Users\\xxx\\AppData\\Local\\DshPet",
 "venv":"...\\.venv","python":"3.8","hasFrames":true,
 "smokeTest":true,"shortcut":"...\\大肥鱼.lnk","autostart":false,"bgPlugin":true}
```

**判据：`"ok": true`。** 另外重点看 `smokeTest`——它为 `false` 说明桌宠装上了
但起不来，要把脚本输出里的报错转告用户。

---

## 3. 校验

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Check
```

这是**只读体检**，不改任何东西。它逐项检查 DSH profile、虚拟环境、PyQt5、
桌宠主体、帧素材、背景插件及登记、启动包装，并打印结论。
退出码 0 = 全部就绪；1 = 有缺项（输出里会列出 `problems`）。

如果想更直接地验证桌宠能不能跑起来：

```powershell
& "$env:LOCALAPPDATA\DshPet\.venv\Scripts\python.exe" -X utf8 "$env:LOCALAPPDATA\DshPet\main.py" --status
```

应当打印出宠物种类、配置、动画分类统计（退出码 0）。

---

## 4. 启动桌宠

```powershell
Start-Process -FilePath "$env:USERPROFILE\Desktop\大肥鱼.lnk"
```

如果快捷方式不存在（安装时带了 `-NoShortcut`），直接这样起：

```powershell
Start-Process -FilePath "$env:LOCALAPPDATA\DshPet\.venv\Scripts\pythonw.exe" `
  -ArgumentList '-X','utf8',"$env:LOCALAPPDATA\DshPet\main.py" `
  -WorkingDirectory "$env:LOCALAPPDATA\DshPet"
```

启动后约 2 秒，这个本地接口应当有应答：

```powershell
Invoke-RestMethod http://127.0.0.1:8899/health
# 期望: {"ok":true,"mood":"idle",...}
```

没有应答就去读日志（正常退出与崩溃在里面分得很清楚）：

```powershell
Get-Content "$env:LOCALAPPDATA\DshPet\logs\pet-run.log" -Tail 30
```

---

## 5. 最后告诉用户这两件事

1. **背景 + 启动动画要重启 DSH 才生效** —— 那个插件**不会热重载**。
   这是必须由用户做的事（重启应用），你无法代劳。
2. 桌宠的配置在 `%LOCALAPPDATA%\DshPet\config.jsonc`（JSONC，带注释），
   改完重启桌宠生效。

---

## 你可以安全忽略的

* `安装说明.md` 是给人看的，内容与上面重叠。
* 桌宠目录里的 `README.md` 是**开发者文档**（架构与踩坑记录），不用读。
* 桌宠监听 `127.0.0.1:8899`（供 DSH 投递状态）、`127.0.0.1:8900` 是 DSH 侧插件的
  端口。杀毒软件可能对"监听本地端口 + 写注册表自启项 + 建桌面快捷方式"报警，
  这些行为都是它正常工作所必需的。

## 卸载（如果用户改主意）

```powershell
powershell -ExecutionPolicy Bypass -File .\uninstall.ps1 -NonInteractive
```

非交互模式下它会**默认保留**背景插件（摘插件该由用户决定）。它也会移除
桌面快捷方式和开机自启项——如果用户想留着 DSH 的背景，只卸载桌宠即可。
