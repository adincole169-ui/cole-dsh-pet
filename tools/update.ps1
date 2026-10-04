# 大肥鱼桌宠：更新补丁
#
# 作用：把本补丁里的变动文件覆盖到**已安装的桌宠目录**。
#       只替换 4 个代码文件 + 全部帧素材，不动虚拟环境、不动桌面快捷方式、不动 DSH 插件。
#
# 用法（在本目录里）：
#     powershell -ExecutionPolicy Bypass -File .\update.ps1
#
# 非交互（给智能体用，不会停下来等输入）：
#     powershell -ExecutionPolicy Bypass -File .\update.ps1 -NonInteractive
#
# 只看看会做什么、不实际改动：
#     powershell -ExecutionPolicy Bypass -File .\update.ps1 -DryRun
#
# 退出码：0 成功 / 1 找不到要更新的桌宠 / 2 更新过程失败
# 结果文件：本目录下的 update-status.json（ok / exitCode / stage / message）
#
# 注意：本文件里**不要出现反引号**（注释里的反引号也会转义行尾换行）。
# 本文件必须存为 **UTF-8 with BOM**，否则 Windows PowerShell 5.1 会把中文读成乱码。

[CmdletBinding()]
param(
    [string]$PetDir,          # 已安装的桌宠目录；默认自动探测
    [switch]$NonInteractive,  # 不弹任何询问
    [switch]$DryRun           # 只报告，不改动
)

$ErrorActionPreference = 'Stop'
$Quote = [char]34
$StatusPath = Join-Path $PSScriptRoot 'update-status.json'
$Pad = ' '

function Say($text) { Write-Host $text }
function Step($text) { Write-Host "  $text" }
function Section($text) { Write-Host ""; Write-Host "=== $text ===" }

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
    exit $code
}

# ----------------------------------------------------------------- 找桌宠目录
function Find-PetDir {
    # 1. 显式传入
    if ($PetDir -and (Test-Path (Join-Path $PetDir 'main.py'))) { return $PetDir }

    # 2. 常规安装位置
    $default = Join-Path $env:LOCALAPPDATA 'DshPet'
    if (Test-Path (Join-Path $default 'main.py')) { return $default }

    # 3. 从正在运行的桌宠进程的命令行里找（用户可能装在别处）
    try {
        $procs = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue
        foreach ($proc in $procs) {
            if (-not $proc.CommandLine) { continue }
            $match = [regex]::Match($proc.CommandLine, '"?([A-Za-z]:\\[^"]*?)\\main\.py')
            if ($match.Success -and (Test-Path (Join-Path $match.Groups[1].Value 'main.py'))) {
                return $match.Groups[1].Value
            }
        }
    } catch { }

    return $null
}

Say ""
Say "大肥鱼桌宠  更新补丁"
Say "  补丁目录: $PSScriptRoot"

$PetDir = Find-PetDir
if (-not $PetDir) {
    Fail @(
        "找不到已安装的桌宠（需要目录里有 main.py）。",
        "",
        "已查找的位置：",
        "  * 命令行传入的 -PetDir",
        "  * $env:LOCALAPPDATA\DshPet",
        "  * 正在运行的桌宠进程的命令行",
        "",
        "请显式指定，例如：",
        "  powershell -ExecutionPolicy Bypass -File .\update.ps1 -PetDir " + $Quote + "D:\某处\DshPet" + $Quote
    ) 'locate' 1
}
Step "找到桌宠: $PetDir"

if ($DryRun) { Step "模式: 预演（不会改动任何文件）" }
elseif ($NonInteractive) { Step "模式: 非交互" }

# ----------------------------------------------------------------- 版本检查
Section "1/4 检查当前版本"

$currentConfig = Join-Path $PetDir 'config.jsonc'
$hasDisplayName = $false
if (Test-Path $currentConfig) {
    $text = Get-Content $currentConfig -Raw -Encoding UTF8
    if ($text -match 'displayName') { $hasDisplayName = $true }
}
if ($hasDisplayName) {
    Step "config.jsonc 里已有 displayName（可能已经更新过）"
} else {
    Step "config.jsonc 里没有 displayName —— 是旧版本，需要更新"
}

$sampleFrame = Get-ChildItem (Join-Path $PetDir 'frames') -Recurse -Filter '0001.png' -ErrorAction SilentlyContinue |
    Select-Object -First 1
$frameWidth = 0
if ($sampleFrame) {
    $bytes = [System.IO.File]::ReadAllBytes($sampleFrame.FullName)
    # PNG IHDR 的宽在偏移 16..20（大端）
    $frameWidth = [int]$bytes[16] * 16777216 + [int]$bytes[17] * 65536 + [int]$bytes[18] * 256 + [int]$bytes[19]
    Step "帧素材宽度: $frameWidth px（目标 640）"
} else {
    Step "找不到帧素材（frames 目录为空或不存在）"
}

# ----------------------------------------------------------------- 二、停进程
Section "2/4 停止正在运行的桌宠"

$stopped = 0
if (-not $DryRun) {
    Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -like "*$PetDir*" } |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            Step "已停止 PID $($_.ProcessId)"
            $stopped++
        }
}
if ($stopped -eq 0) { Step "没有正在运行的桌宠（或已预演跳过）" }

# ----------------------------------------------------------------- 三、覆盖文件
Section "3/4 覆盖变动文件"

$payloadDir = Join-Path $PSScriptRoot 'payload'
if (-not (Test-Path $payloadDir)) { Fail @("补丁里没有 payload 目录") 'payload' 2 }

# 配置先备份（用户可能自己改过）
$backupPath = $null
if (Test-Path $currentConfig) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backupPath = Join-Path $PetDir ("config.jsonc.bak-" + $stamp)
    if (-not $DryRun) {
        Copy-Item $currentConfig $backupPath -Force
        Step "已备份配置 -> $(Split-Path $backupPath -Leaf)"
    } else {
        Step "会备份配置 -> $(Split-Path $backupPath -Leaf)"
    }
}

$files = Get-ChildItem $payloadDir -Recurse -File
$copied = 0
$totalBytes = 0
foreach ($file in $files) {
    $relative = $file.FullName.Substring($payloadDir.Length).TrimStart('\')
    $target = Join-Path $PetDir $relative
    $targetDir = Split-Path $target -Parent
    if (-not $DryRun) {
        if (-not (Test-Path $targetDir)) { New-Item -ItemType Directory -Path $targetDir -Force | Out-Null }
        Copy-Item $file.FullName $target -Force
    }
    $copied++
    $totalBytes += $file.Length
    # 帧素材太多，不逐条打印
    if ($relative -notlike 'frames\*') {
        Step "$relative"
    }
}
$mb = [math]::Round($totalBytes / 1MB, 1)
Step ("帧素材与其它文件共 {0} 个，{1} MB" -f $copied, $mb)

# ----------------------------------------------------------------- 四、校验
Section "4/4 校验"

$ok = $true
$problems = New-Object System.Collections.Generic.List[string]

$newConfig = Join-Path $PetDir 'config.jsonc'
if (Test-Path $newConfig) {
    $text = Get-Content $newConfig -Raw -Encoding UTF8
    if ($text -match 'displayName') { Step "OK   config.jsonc 有 displayName" }
    else { Step "配置里仍没有 displayName"; $ok = $false; $problems.Add('config') }
} else {
    Step "缺少 config.jsonc"; $ok = $false; $problems.Add('config')
}

$sampleFrame = Get-ChildItem (Join-Path $PetDir 'frames') -Recurse -Filter '0001.png' -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($sampleFrame) {
    $bytes = [System.IO.File]::ReadAllBytes($sampleFrame.FullName)
    $width = [int]$bytes[16] * 16777216 + [int]$bytes[17] * 65536 + [int]$bytes[18] * 256 + [int]$bytes[19]
    if ($width -eq 640) { Step "OK   帧素材已是原生 640px" }
    else { Step "帧素材宽度是 $width（期望 640）"; $ok = $false; $problems.Add('frames') }
} else {
    Step "找不到帧素材"; $ok = $false; $problems.Add('frames')
}

$venvPy = Join-Path $PetDir '.venv\Scripts\python.exe'
if ((Test-Path $venvPy) -and (-not $DryRun)) {
    Step "冒烟测试（--status）..."
    $out = & $venvPy -X utf8 (Join-Path $PetDir 'main.py') --status 2>&1
    if ($LASTEXITCODE -eq 0) {
        $line = $out | Where-Object { $_ -match '显示名' } | Select-Object -First 1
        if ($line) { Step "OK   $($line.Trim())" }
        else { Step "OK   --status 通过（但没找到显示名那一行）"; $ok = $false; $problems.Add('displayName') }
    } else {
        Step "警告：--status 返回 $LASTEXITCODE"
        $out | Select-Object -First 6 | ForEach-Object { Step "    $_" }
        $ok = $false
        $problems.Add('status')
    }
} elseif (-not (Test-Path $venvPy)) {
    Step "提示：没有 .venv（可能用系统 Python 装的），跳过冒烟测试"
}

# ----------------------------------------------------------------- 收尾
Section "完成"
if ($DryRun) {
    Say "  这是预演，没有改动任何文件。去掉 -DryRun 才会真正更新。"
} else {
    Say "  桌宠目录: $PetDir"
    if ($backupPath) { Say "  配置备份: $backupPath" }
    Say ""
    Say "接下来："
    Say "  1. 双击桌面上的「大肥鱼」重新启动桌宠"
    Say "  2. 任务栏上应当显示「大肥鱼」"
    Say "  3. 背景插件本次没有改动，不需要重启 DSH"
}
Say ""

$extra = [ordered]@{
    backup   = $backupPath
    files    = $copied
    problems = @($problems)
}
# 不写反引号续行：本文件零反引号是硬规矩（注释里的反引号也会转义行尾换行）。
$finalCode = 0
$finalStage = 'done'
$finalMessage = '更新完成'
if ($DryRun) { $finalStage = 'dry-run' }
if (-not $ok) {
    $finalCode = 1
    $finalStage = 'done'
    $finalMessage = '更新完成但有警告: ' + ($problems -join ', ')
}
$final = Write-Status $ok $finalCode $finalStage $finalMessage $extra
Write-Host ("机器可读结果: " + ($final | ConvertTo-Json -Compress))
Write-Host "状态文件: $StatusPath"
Write-Host ""
if ($ok) { exit 0 } else { exit 1 }
