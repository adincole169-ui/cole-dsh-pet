# 大肥鱼桌宠 + 对话界面背景：一键安装
#
# 做四件事：
#   1. 把「背景 + 启动动画」插件装进 DSH 的 desktop profile
#   2. 建一个独立虚拟环境并装 PyQt5（不污染系统 Python）
#   3. 在桌面建快捷方式
#   4. 登记开机自启（可选，会问；-NonInteractive 时默认不装）
#
# 用法（在解压出来的目录里）：
#     powershell -ExecutionPolicy Bypass -File .\install.ps1
#
# 给「由电脑上的智能体代为安装」用（不弹任何询问、结果机器可读）：
#     powershell -ExecutionPolicy Bypass -File .\install.ps1 -NonInteractive
#
# 只体检、不改动任何东西：
#     powershell -ExecutionPolicy Bypass -File .\install.ps1 -Check
#
# 退出码：0 成功 / 1 环境不满足 / 2 安装过程失败
# 结果文件：本目录下的 install-status.json（ok / exitCode / stage / message）
#
# 注意：本文件里**不要出现反引号**。PowerShell 的注释里反引号仍是转义符，会把行尾
# 换行转义掉，导致解析报出莫名其妙的错误（踩过）。需要引号转义就用 [char]34 拼接。
#
# 本文件必须存为 **UTF-8 with BOM**：Windows PowerShell 5.1 会把无 BOM 的 .ps1 按
# ANSI 解码，中文注释与字符串会断裂（也踩过）。

[CmdletBinding()]
param(
    [string]$PetDir,                      # 桌宠安装到哪（默认 本地应用数据 下的 DshPet）
    [switch]$NoShortcut,
    [switch]$NoAutostart,
    [switch]$SkipBgPlugin,
    [switch]$SkipPyQt,
    [switch]$NonInteractive,
    [switch]$Check
)

$ErrorActionPreference = 'Stop'
$Quote = [char]34
$StatusPath = Join-Path $PSScriptRoot 'install-status.json'

function Say($text) { Write-Host $text }
function Step($text) { Write-Host "  $text" }
function Section($text) { Write-Host ""; Write-Host "=== $text ===" }

# 结果落成 JSON，供智能体读取判断成败（而不是去猜中文输出）。
function Write-Status($ok, $code, $stage, $message, $extra) {
    $payload = [ordered]@{
        ok       = $ok
        exitCode = $code
        stage    = $stage
        message  = $message
        petDir   = $PetDir
        time     = (Get-Date).ToString('s')
    }
    if ($extra) { foreach ($key in $extra.Keys) { $payload[$key] = $extra[$key] } }
    try {
        $payload | ConvertTo-Json -Depth 4 | Set-Content -Path $StatusPath -Encoding UTF8
    } catch { }
    return $payload
}

function Fail($lines, $stage, $code) {
    Write-Host ""
    Write-Host "错误:" -ForegroundColor Red
    foreach ($line in $lines) { Write-Host "  $line" -ForegroundColor Red }
    if (-not $code) { $code = 2 }
    if (-not $stage) { $stage = 'unknown' }
    $status = Write-Status $false $code $stage ($lines | Select-Object -First 1) $null
    Write-Host ""
    Write-Host ("机器可读结果: " + ($status | ConvertTo-Json -Compress))
    Write-Host "状态文件: $StatusPath"
    exit $code
}

$ShareRoot = $PSScriptRoot
if (-not $ShareRoot) { $ShareRoot = Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $PetDir) { $PetDir = Join-Path $env:LOCALAPPDATA 'DshPet' }
$venv = Join-Path $PetDir '.venv'
$venvPy = Join-Path $venv 'Scripts\python.exe'
$venvPyW = Join-Path $venv 'Scripts\pythonw.exe'

# =============================================================== -Check 模式
# 只体检。给"安装完核实一下"和"排查问题"用，不碰任何文件。
if ($Check) {
    Section "体检（不修改任何东西）"
    $problems = New-Object System.Collections.Generic.List[string]

    $dshProfile = Join-Path $env:USERPROFILE '.dsh\profiles\desktop'
    if (Test-Path $dshProfile) { Step "OK   DSH profile 存在" }
    else { Step "缺失 DSH profile: $dshProfile"; $problems.Add('dsh-profile') }

    if (Test-Path $venvPy) { Step "OK   虚拟环境存在: $venv" }
    else { Step "缺失虚拟环境: $venv"; $problems.Add('venv') }

    if (Test-Path $venvPy) {
        $probe = & $venvPy -c "import PyQt5.QtCore as c; print(c.PYQT_VERSION_STR)" 2>&1
        if ($LASTEXITCODE -eq 0) { Step "OK   PyQt5 可用（$probe）" }
        else { Step "PyQt5 不可用: $probe"; $problems.Add('pyqt5') }
    }

    if (Test-Path (Join-Path $PetDir 'main.py')) { Step "OK   桌宠主体存在" }
    else { Step "缺失桌宠主体: $PetDir"; $problems.Add('pet') }

    $frames = Join-Path $PetDir 'frames'
    if (Test-Path $frames) {
        $n = (Get-ChildItem $frames -Directory -ErrorAction SilentlyContinue).Count
        Step "OK   帧素材存在（$n 个动画）"
    } else {
        Step "提示 没有帧素材：首次播新动画要现场解码（需 ffmpeg + Pillow）"
    }

    $bg = Join-Path $env:USERPROFILE '.dsh\profiles\node_modules\dsh-profile-bg'
    if (Test-Path $bg) { Step "OK   背景插件已安装" }
    else { Step "提示 背景插件未安装（-SkipBgPlugin 或还没装）" }

    $patch = Join-Path $dshProfile 'cordis.patch.yml'
    if ((Test-Path $patch) -and ((Get-Content $patch -Raw -Encoding UTF8) -match 'dsh-profile-bg')) {
        Step "OK   背景插件已在 profile 里登记"
    } else {
        Step "提示 背景插件未登记到 cordis.patch.yml"
    }

    # 桌宠此刻是否在跑
    $running = $false
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:8899/health' -TimeoutSec 3
        if ($health.ok) { $running = $true }
    } catch { }
    if ($running) { Step "OK   桌宠正在运行（127.0.0.1:8899 有应答）" }
    else { Step "提示 桌宠当前没在运行" }

    if (Test-Path (Join-Path $PetDir 'tools\run_logged.py')) { Step "OK   启动包装存在" }
    else { Step "缺失 tools\run_logged.py"; $problems.Add('wrapper') }

    $ok = ($problems.Count -eq 0)
    $checkCode = 0
    $checkMessage = '体检通过'
    if (-not $ok) {
        $checkCode = 1
        $checkMessage = '缺少: ' + ($problems -join ', ')
    }
    # 哈希字面量不能写在 $(...) 里当参数，也不要用反引号续行（本文件里两者都踩过）
    $checkExtra = [ordered]@{ running = $running; problems = @($problems) }
    $status = Write-Status $ok $checkCode 'check' $checkMessage $checkExtra
    Write-Host ""
    Write-Host ("机器可读结果: " + ($status | ConvertTo-Json -Compress))
    Write-Host "状态文件: $StatusPath"
    exit $checkCode
}

Say ""
Say "大肥鱼桌宠 + 对话界面背景  安装程序"
Say "  包目录:     $ShareRoot"
Say "  桌宠将装到: $PetDir"
if ($NonInteractive) { Say "  模式:       非交互（不会询问，默认不装开机自启）" }

# ----------------------------------------------------------------- 环境检查
Section "环境检查"

$dshProfile = Join-Path $env:USERPROFILE '.dsh\profiles\desktop'
if (-not (Test-Path $dshProfile)) {
    Fail @(
        "找不到 DSH 的 desktop profile：",
        "  $dshProfile",
        "请先启动过一次 DeepSeek Harness，再运行本安装程序。"
    ) 'env' 1
}
Step "找到 DSH profile: $dshProfile"

# 找 Python：优先 py 启动器，其次 PATH 里的 python
$pythonExe = $null
$pythonVersion = $null
foreach ($candidate in @('py', 'python', 'python3')) {
    $found = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($found) {
        try {
            $version = & $found.Source -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($version -and [version]$version -ge [version]'3.8') {
                $pythonExe = $found.Source
                $pythonVersion = $version
                Step "找到 Python $version（$pythonExe）"
                break
            }
        } catch { }
    }
}
if (-not $pythonExe) {
    Fail @(
        "找不到 Python 3.8 或更高版本。",
        "",
        "请先安装 Python（安装时勾选 Add python.exe to PATH）：",
        "  https://www.python.org/downloads/",
        "",
        "装完关掉并重新打开 PowerShell，再运行本脚本。"
    ) 'env' 1
}

# ----------------------------------------------------------------- 1. 背景插件
Section "1/4 安装「背景 + 启动动画」插件"

if ($SkipBgPlugin) {
    Step "已跳过（-SkipBgPlugin）"
} else {
    $source = Join-Path $ShareRoot 'profile-plugin'
    if (-not (Test-Path $source)) {
        Step "包内没有 profile-plugin 目录，跳过"
    } else {
        $target = Join-Path $env:USERPROFILE '.dsh\profiles\node_modules\dsh-profile-bg'
        if (Test-Path $target) { Remove-Item $target -Recurse -Force }
        Copy-Item $source $target -Recurse -Force
        Step "已装到 $target"

        $patch = Join-Path $dshProfile 'cordis.patch.yml'
        $text = ''
        if (Test-Path $patch) { $text = Get-Content $patch -Raw -Encoding UTF8 }
        if ($text -match 'dsh-profile-bg') {
            Step "profile patch 里已登记过，不重复插入"
        } else {
            $block = @(
                "",
                "# ---- 由 install.ps1 追加：对话界面背景 + 启动动画 ----",
                "- insert:",
                "    - id: profile-bg",
                "      name: dsh-profile-bg"
            )
            Add-Content -Path $patch -Value $block -Encoding UTF8
            Step "已在 cordis.patch.yml 末尾登记 profile-bg"
        }
        Step "提示：插件要重启 DSH 才生效（它不会热重载）"
    }
}

# ----------------------------------------------------------------- 2. 桌宠
Section "2/4 安装桌宠本体"
$sourcePet = Join-Path $ShareRoot 'pet'
if (-not (Test-Path $sourcePet)) { Fail @("包内没有 pet 目录，无法安装桌宠") 'pet' 2 }

if (Test-Path $PetDir) {
    Step "目标已存在，先移除旧副本"
    Remove-Item $PetDir -Recurse -Force
}
New-Item -ItemType Directory -Path $PetDir -Force | Out-Null
Step "复制文件到 $PetDir ..."
Copy-Item (Join-Path $sourcePet '*') $PetDir -Recurse -Force
$count = (Get-ChildItem $PetDir -Recurse -File).Count
$sizeMb = [math]::Round((Get-ChildItem $PetDir -Recurse -File |
          Measure-Object Length -Sum).Sum / 1MB, 1)
Step "已复制 $count 个文件，$sizeMb MB"

$framesDir = Join-Path $PetDir 'frames'
$hasFrames = Test-Path $framesDir
if ($hasFrames) {
    Step "帧素材已随包提供 —— 无需 ffmpeg / Pillow"
} else {
    Step "包内没有帧素材。首次播放某个动画时会现场解码（每个约 20 秒），"
    Step "并且需要你自己装 ffmpeg（放进 PATH）与 Pillow："
    Step "    $pythonExe -m pip install Pillow"
}

# ----------------------------------------------------------------- 3. PyQt5
Section "3/4 准备运行环境（独立虚拟环境 + PyQt5）"

if ($SkipPyQt) {
    Step "已跳过（-SkipPyQt）"
    $venvPyW = Join-Path (Split-Path -Parent $pythonExe) 'pythonw.exe'
    if (-not (Test-Path $venvPyW)) { $venvPyW = $pythonExe }
    $venvPy = $pythonExe
    Step "将使用 $venvPyW"
} else {
    Step "创建虚拟环境（不污染系统 Python）..."
    & $pythonExe -m venv $venv
    if (-not (Test-Path $venvPy)) { Fail @("虚拟环境创建失败：$venv") 'venv' 2 }

    Step "安装 PyQt5（需要联网，约 50MB）..."
    & $venvPy -m pip install --quiet --disable-pip-version-check --upgrade pip 2>&1 |
        Where-Object { $_ -match 'ERROR' } | ForEach-Object { Step $_ }
    $req = Join-Path $PetDir 'requirements.txt'
    & $venvPy -m pip install --disable-pip-version-check -r $req 2>&1 |
        Select-String -Pattern 'Successfully|ERROR|already satisfied' |
        ForEach-Object { Step $_.Line.Trim() }
    if ($LASTEXITCODE -ne 0) {
        Fail @(
            "PyQt5 安装失败。常见原因：",
            "  * 没联网（PyQt5 要从 PyPI 下载）",
            "  * 公司代理挡了 pip：设置 HTTP_PROXY / HTTPS_PROXY 后重试",
            "",
            "手工重试命令：",
            "  $venvPy -m pip install PyQt5"
        ) 'pyqt5' 2
    }
    Step "PyQt5 就绪"
}

# 冒烟测试：确认真的能启动（这一步也会验证帧素材可读）
Step "冒烟测试（--status）..."
$statusOut = & $venvPy -X utf8 (Join-Path $PetDir 'main.py') --status 2>&1
$smokeOk = ($LASTEXITCODE -eq 0)
if ($smokeOk) {
    Step "通过: $($statusOut | Select-Object -First 1)"
} else {
    Step "警告：--status 返回 $LASTEXITCODE"
    $statusOut | Select-Object -First 6 | ForEach-Object { Step "    $_" }
}

# ----------------------------------------------------------------- 4. 快捷方式与自启
Section "4/4 桌面快捷方式与开机自启"
$shortcutPath = $null
if ($NoShortcut) {
    Step "已跳过快捷方式（-NoShortcut）"
} else {
    try {
        $desktop = [Environment]::GetFolderPath('Desktop')
        $lnk = Join-Path $desktop '大肥鱼.lnk'
        $shell = New-Object -ComObject WScript.Shell
        $shortcut = $shell.CreateShortcut($lnk)
        $shortcut.TargetPath = $venvPyW
        $shortcut.Arguments = '-X utf8 ' + $Quote + (Join-Path $PetDir 'tools\run_logged.py') + $Quote
        $shortcut.WorkingDirectory = $PetDir
        $icon = Join-Path $PetDir 'assets\icon.ico'
        if (Test-Path $icon) { $shortcut.IconLocation = "$icon,0" }
        $shortcut.Description = '大肥鱼（DSH 联动桌宠）'
        $shortcut.Save()
        $shortcutPath = $lnk
        Step "已创建桌面快捷方式: $lnk"
    } catch {
        Step "快捷方式创建失败（不影响使用）: $($_.Exception.Message)"
    }
}

# 非交互模式**不装自启**：那是需要人做主的决定，不该由智能体替用户拍板。
$autostartSet = $false
if ($NoAutostart -or $NonInteractive) {
    if ($NonInteractive -and -not $NoAutostart) {
        Step "非交互模式：不登记开机自启（想装请手动重跑并回答 y）"
    } else {
        Step "已跳过开机自启（-NoAutostart）"
    }
} else {
    $answer = Read-Host "  要开机自动启动桌宠吗？[y/N]"
    if ($answer -match '^[yY]') {
        $run = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
        $value = $Quote + $venvPyW + $Quote + ' ' + $Quote +
                 (Join-Path $PetDir 'tools\run_logged.py') + $Quote
        Set-ItemProperty -Path $run -Name 'DshPet' -Value $value
        $autostartSet = $true
        Step "已登记开机自启（注册表 HKCU 的 Run 项）"
    } else {
        Step "未登记开机自启（以后想要可重跑本脚本）"
    }
}

# ----------------------------------------------------------------- 收尾
Section "完成"
Say "  桌宠目录: $PetDir"
if (-not $SkipPyQt) { Say "  运行环境: $venv" }
Say ""
Say "接下来："
Say "  1. 桌面上的「大肥鱼」双击即可启动桌宠"
Say "  2. 重启 DSH 让背景 + 启动动画生效（插件不热重载）"
Say "  3. 右键桌宠有菜单：模式、大小、碎碎念、对话、动画点播等"
Say ""
Say "配置在 $PetDir\config.jsonc（JSONC，带注释）。"
Say "卸载就运行同目录下的 uninstall.ps1。"
Say "体检：powershell -ExecutionPolicy Bypass -File .\install.ps1 -Check"
Say ""

# 注意：哈希字面量不能直接写在 $() 里当命令参数（PowerShell 会报错，而且
# $ErrorActionPreference = 'Stop' 会让脚本在收尾处静默中止——表现为"装完了但
# 没生成状态文件、退出码 -1"）。所以先赋给变量再传。本文件里一律不用反引号。
$finalExtra = [ordered]@{
    venv      = $(if ($SkipPyQt) { $null } else { $venv })
    python    = $pythonVersion
    hasFrames = $hasFrames
    smokeTest = $smokeOk
    shortcut  = $shortcutPath
    autostart = $autostartSet
    bgPlugin  = (-not $SkipBgPlugin)
}
$final = Write-Status $true 0 'done' '安装完成' $finalExtra
Write-Host ("机器可读结果: " + ($final | ConvertTo-Json -Compress))
Write-Host "状态文件: $StatusPath"
Write-Host ""
exit 0
