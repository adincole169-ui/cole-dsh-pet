# 大肥鱼桌宠 + 对话界面背景：卸载
#
# 做三件事：
#   1. 关掉正在跑的桌宠
#   2. 移除桌宠目录、桌面快捷方式、开机自启
#   3. 从 DSH profile 里摘掉背景插件登记（可选，会问）
#
# 用法：
#     powershell -ExecutionPolicy Bypass -File .\uninstall.ps1
#     powershell -ExecutionPolicy Bypass -File .\uninstall.ps1 -NonInteractive
#
# 默认**不动** DSH profile 里的其它配置——只删本安装程序登记的那几行。
#
# 本文件必须存为 UTF-8 with BOM（否则 Windows PowerShell 5.1 会按 ANSI 读，中文断裂）。

[CmdletBinding()]
param(
    [string]$PetDir,
    [switch]$KeepBgPlugin,
    [switch]$Yes,
    # 非交互：不弹任何 Read-Host（否则智能体会卡在等输入）。
    # 语义等同于 -Yes，但另外**默认保留**背景插件——摘插件是用户的决定，
    # 不该由智能体替用户拍板；要摘就显式去掉 -KeepBgPlugin 并加 -NonInteractive:$false。
    [switch]$NonInteractive
)

$ErrorActionPreference = 'Continue'

function Step($text) { Write-Host "  $text" }
function Section($text) { Write-Host ""; Write-Host "=== $text ===" }

if (-not $PetDir) { $PetDir = Join-Path $env:LOCALAPPDATA 'DshPet' }
if ($NonInteractive) { $Yes = $true }

Write-Host ""
Write-Host "大肥鱼桌宠  卸载程序"
Write-Host "  桌宠目录: $PetDir"
if ($NonInteractive) { Write-Host "  模式:     非交互（默认保留背景插件）" }

if (-not $Yes) {
    $answer = Read-Host "确认卸载？[y/N]"
    if ($answer -notmatch '^[yY]') { Write-Host "已取消"; exit 0 }
}

# ----------------------------------------------------------------- 1. 停掉进程
Section "1/3 停止运行中的桌宠"
$killed = 0
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and ($_.CommandLine -like "*$PetDir*") } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Step "已停止 PID $($_.ProcessId)"
        $killed++
    }
# 顺带把监听桥端口的那个也停掉（有些启动方式命令行里没有完整路径）
$conn = Get-NetTCPConnection -LocalPort 8899 -State Listen -ErrorAction SilentlyContinue
if ($conn) {
    foreach ($owner in ($conn.OwningProcess | Select-Object -Unique)) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$owner" -ErrorAction SilentlyContinue
        if ($proc -and $proc.Name -like 'python*') {
            Stop-Process -Id $owner -Force -ErrorAction SilentlyContinue
            Step "已停止占用 8899 端口的 PID $owner"
            $killed++
        }
    }
}
if ($killed -eq 0) { Step "没有正在运行的桌宠" }

# ----------------------------------------------------------------- 2. 清理文件
Section "2/3 移除目录与快捷方式"
if (Test-Path $PetDir) {
    Remove-Item $PetDir -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path $PetDir) { Step "删除失败（可能还被占用），请手动删: $PetDir" }
    else { Step "已删除 $PetDir" }
} else {
    Step "目录不存在，跳过"
}

$lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) '大肥鱼.lnk'
if (Test-Path $lnk) { Remove-Item $lnk -Force; Step "已删除桌面快捷方式" }

$run = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$existing = (Get-ItemProperty -Path $run -Name 'DshPet' -ErrorAction SilentlyContinue).DshPet
if ($existing) {
    Remove-ItemProperty -Path $run -Name 'DshPet' -ErrorAction SilentlyContinue
    Step "已移除开机自启"
}

# ----------------------------------------------------------------- 3. 背景插件
Section "3/3 背景 + 启动动画插件"
if ($KeepBgPlugin) {
    Step "已跳过（-KeepBgPlugin）"
} elseif ($NonInteractive) {
    # 非交互时**默认保留**背景插件：摘不摘是用户的决定，不该由智能体替他拍板。
    # 注意这里不能沿用 -Yes，否则会变成"自动回答 y"（那正是第一版的错法）。
    Step "非交互模式：保留背景插件（想摘请手动运行并回答 y）"
} else {
    if (-not $Yes) {
        $answer = Read-Host "  也从 DSH 里移除背景插件吗？[y/N]"
    } else {
        $answer = 'y'
    }
    if ($answer -match '^[yY]') {
        $bgDir = Join-Path $env:USERPROFILE '.dsh\profiles\node_modules\dsh-profile-bg'
        if (Test-Path $bgDir) { Remove-Item $bgDir -Recurse -Force; Step "已删除插件目录" }

        # 摘掉 patch 里本安装程序追加的那一段（只删我们加的那几行）
        $patch = Join-Path $env:USERPROFILE '.dsh\profiles\desktop\cordis.patch.yml'
        if (Test-Path $patch) {
            $lines = Get-Content $patch -Encoding UTF8
            $kept = New-Object System.Collections.Generic.List[string]
            $skipping = $false
            foreach ($line in $lines) {
                if ($line -match '由 install\.ps1 追加') { $skipping = $true; continue }
                if ($skipping) {
                    # 这一段最多到 name: dsh-profile-bg 为止
                    if ($line -match 'name:\s*dsh-profile-bg') { $skipping = $false }
                    continue
                }
                $kept.Add($line)
            }
            Set-Content -Path $patch -Value $kept -Encoding UTF8
            Step "已从 cordis.patch.yml 摘掉登记（其它配置未动）"
        }
        Step "背景插件要**重启 DSH** 才真正失效"
    } else {
        Step "保留背景插件"
    }
}

Write-Host ""
Write-Host "卸载完成。"
Write-Host ""
exit 0
