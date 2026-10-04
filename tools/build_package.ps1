# 大肥鱼桌宠 + 对话界面背景：打包脚本
#
# 把两样东西组装成一个可分发的目录，并压成 zip：
#
#   dsh-pet-share\
#     install.ps1          一键安装（建虚拟环境、装 PyQt5、装插件、建快捷方式）
#     uninstall.ps1        卸载
#     安装说明.md          给使用者的说明
#     profile-plugin\      「背景 + 启动动画」插件（纯 JS，自包含）
#     pet\                 桌宠本体（Python，带已解码的帧）
#
# 用法（在本项目的 tools 目录下）：
#     powershell -ExecutionPolicy Bypass -File .\build_package.ps1
#     powershell -ExecutionPolicy Bypass -File .\build_package.ps1 -SkipFrames
#     powershell -ExecutionPolicy Bypass -File .\build_package.ps1 -OutputRoot D:\out
#
# 注意：本文件里**不要出现反引号**。PowerShell 的注释里反引号仍然是转义符，
# 会把行尾的换行转义掉，导致解析报出莫名其妙的 "Unexpected token '}'"（踩过）。
#
# 关于帧：桌宠的 frames 目录是 webm 用 ffmpeg 解出来的 PNG（约 2.6 GB）。
# 带上它，使用者就不需要 ffmpeg、也不需要 Pillow —— 运行时只依赖 PyQt5。
# 不带的话包只有几十 MB，但对方首次播某动画要现场解码（每个约 20-30 秒），
# 还得自己装 ffmpeg 并放进 PATH。
#
# ⚠️ 素材授权：帧与 webm 都来自上游同人仓库，该仓库**未授予再分发权**
#    （见项目根的 ASSETS.md）。打**带素材**的包去分发之前，请先确认你有权分发。
#
# 默认输出到**项目根目录下的 dist\**（不是写死的绝对路径，换台机器也能用）。

[CmdletBinding()]
param(
    # 留空则用 <项目根>\dist
    [string]$OutputRoot = '',
    [string]$FolderName = 'dsh-pet-share',
    [switch]$SkipFrames,
    [switch]$SkipZip
)

$ErrorActionPreference = 'Stop'

$PetRoot = Split-Path -Parent $PSScriptRoot
if (-not $OutputRoot) { $OutputRoot = Join-Path $PetRoot 'dist' }
$Stage = Join-Path $OutputRoot $FolderName

function Step($text) { Write-Host "  $text" }
function Section($text) { Write-Host ""; Write-Host "=== $text ===" }
# 避免用格式串的**对齐**写法（如 {1,8:N1}）这种：Windows PowerShell 5.1 不支持，
# 会报 "Unexpected token '{'"（实测踩过）。自己补空格更稳。
function Pad($text, $width) {
    $s = [string]$text
    if ($s.Length -lt $width) { $s = ' ' * ($width - $s.Length) + $s }
    return $s
}
function Mb($bytes) { return [math]::Round($bytes / 1MB, 1) }
function Gb($bytes) { return [math]::Round($bytes / 1GB, 2) }

Section "准备输出目录"
if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
New-Item -ItemType Directory -Path $Stage -Force | Out-Null
Step "输出目录: $Stage"

# ----------------------------------------------------------------- 1. 背景插件
Section "1/4 复制背景 + 启动动画插件"
$bgSource = Join-Path $env:USERPROFILE '.dsh\profiles\node_modules\dsh-profile-bg'
if (-not (Test-Path $bgSource)) {
    throw "找不到 $bgSource —— 背景插件没装在这个 profile 里，无法打包"
}
$bgTarget = Join-Path $Stage 'profile-plugin'
Copy-Item $bgSource $bgTarget -Recurse -Force
$bgSize = (Get-ChildItem $bgTarget -Recurse -File | Measure-Object Length -Sum).Sum
Step "已复制 dsh-profile-bg（$(Mb $bgSize) MB）—— 启动视频与背景图都以 base64 内嵌，无外部依赖"

# ----------------------------------------------------------------- 2. 桌宠本体
Section "2/4 复制桌宠本体"
$petTarget = Join-Path $Stage 'pet'
New-Item -ItemType Directory -Path $petTarget -Force | Out-Null

# 需要带的
$includeFiles = @('main.py', 'config.jsonc', 'README.md', 'requirements.txt')

# **不要放进包里的**（用户明确要求：使用指南只留在开发目录）。
# 这里显式排除，而不是靠"恰好不在上面的清单里"——意图写出来才不会被后人误加。
$excludeFiles = @('使用指南.md', 'AGENTS.md', 'requirements-dev.txt')
foreach ($name in $excludeFiles) {
    $source = Join-Path $PetRoot $name
    if (Test-Path $source) { Step "  排除 $name（按设计不随包分发）" }
}

foreach ($name in $includeFiles) {
    if ($excludeFiles -contains $name) { continue }
    $source = Join-Path $PetRoot $name
    if (Test-Path $source) { Copy-Item $source $petTarget -Force; Step "  $name" }
}
foreach ($name in @('src', 'tools', 'assets', 'memes', 'pet', 'plugins')) {
    $source = Join-Path $PetRoot $name
    if (Test-Path $source) {
        Copy-Item $source (Join-Path $petTarget $name) -Recurse -Force
        Step "  $name\ (含 $((Get-ChildItem $source -Recurse -File -ErrorAction SilentlyContinue).Count) 个文件)"
    }
}

# webm 源素材（52MB）**只在需要现场解码时才有用**。带了帧的话它纯属占地方，
# 所以默认不带；需要的人可以把它放进 pet\webm\ 再自行重建帧。
if ($SkipFrames) {
    $webm = Join-Path $PetRoot 'webm'
    if (Test-Path $webm) {
        Copy-Item $webm (Join-Path $petTarget 'webm') -Recurse -Force
        Step "  webm\（因为没带帧，所以带上它供自行解码）"
    }
}

# 工具脚本里只有运行时需要的留着；自检与一次性诊断不带（它们会在别人机器上失败，
# 反而让人以为装坏了）。run_logged.py 必须留——快捷方式就是指向它的。
$toolsKeep = @('run_logged.py', 'asset_pipeline.py', 'make_icon.py', 'make_memes.py')
Get-ChildItem (Join-Path $petTarget 'tools') -File -ErrorAction SilentlyContinue |
    Where-Object { $toolsKeep -notcontains $_.Name } |
    ForEach-Object { Remove-Item $_.FullName -Force }
Step "  已精简 tools\（只留运行时需要的 $(($toolsKeep | Where-Object { Test-Path (Join-Path $petTarget "tools\$_") }).Count) 个）"

# 清掉桌宠自带的运行痕迹，别把私人数据发出去。
# **放在复制 frames 之前**：早先把帧的复制放在这之前，结果连 logs / __pycache__ 一起
# 复制了过去，汇总时的大小也就对不上（实测误报过一次）。
Section "3/4 清理私人数据"
foreach ($junk in @('logs', '.venv')) {
    $path = Join-Path $petTarget $junk
    if (Test-Path $path) { Remove-Item $path -Recurse -Force; Step "  已移除 pet\$junk" }
}
Get-ChildItem $petTarget -Recurse -File -Include '*.pyc' -ErrorAction SilentlyContinue |
    Remove-Item -Force
Get-ChildItem $petTarget -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force
Step "  已清理 __pycache__ / *.pyc / logs"

# ----------------------------------------------------------------- 4. 帧素材
Section "4/4 帧素材（放在最后，避免连日志一起复制）"
$framesSource = Join-Path $PetRoot 'frames'
$framesTarget = Join-Path $petTarget 'frames'
if ($SkipFrames) {
    $frameSize = (Get-ChildItem $framesSource -Recurse -File -ErrorAction SilentlyContinue |
                  Measure-Object Length -Sum).Sum
    Step "已跳过（-SkipFrames）：使用者需自备 ffmpeg 与 Pillow 自行解码"
    Step "  源包 frames\ 约 $(Gb $frameSize) GB"
} elseif (Test-Path $framesSource) {
    # 逐个动画目录复制，跳过 _probe 之类的临时目录
    New-Item -ItemType Directory -Path $framesTarget -Force | Out-Null
    $copied = 0
    Get-ChildItem $framesSource -Directory | Where-Object { $_.Name -notlike '_*' } |
        ForEach-Object {
            Copy-Item $_.FullName (Join-Path $framesTarget $_.Name) -Recurse -Force
            $copied++
        }
    $n = (Get-ChildItem $framesTarget -Recurse -File).Count
    $sz = (Get-ChildItem $framesTarget -Recurse -File | Measure-Object Length -Sum).Sum
    Step "  已复制 $copied 个动画、$n 个 PNG，$(Gb $sz) GB —— 使用者无需 ffmpeg / Pillow"
} else {
    Step "  警告：源目录没有 frames\，包会不自足"
}

# 安装与卸载脚本放在包根目录。AGENTS.md 是给"由电脑上的智能体代为安装"用的：
# 它写成"可直接执行的步骤 + 机器可读的判据"，比给人看的说明更适合智能体。
foreach ($name in @('install.ps1', 'uninstall.ps1', '安装说明.md', 'AGENTS.md')) {
    $source = Join-Path $PSScriptRoot $name
    if (Test-Path $source) { Copy-Item $source $Stage -Force; Step "  $name" }
    else { Step "  缺少 $name（稍后补）" }
}

# ----------------------------------------------------------------- 汇总 / 打包
Section "汇总"
$total = (Get-ChildItem $Stage -Recurse -File | Measure-Object Length -Sum).Sum
$count = (Get-ChildItem $Stage -Recurse -File).Count
Step "总大小 $(Gb $total) GB，$count 个文件"
Get-ChildItem $Stage -Directory | ForEach-Object {
    $s = (Get-ChildItem $_.FullName -Recurse -File | Measure-Object Length -Sum).Sum
    Step ("  " + $_.Name.PadRight(16) + (Pad (Mb $s) 10) + " MB")
}

if (-not $SkipZip) {
    Section "压缩"
    $zip = Join-Path $OutputRoot "$FolderName.zip"
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Step "正在压缩（2GB 级别，需要几分钟）..."
    Compress-Archive -Path $Stage -DestinationPath $zip -CompressionLevel Optimal
    Step "完成: $zip（$(Gb (Get-Item $zip).Length) GB）"
}

Write-Host ""
Write-Host "打包完成。把整个 '$FolderName' 目录（或那个 zip）发给对方即可。"
Write-Host "对方解压后双击 install.ps1，或在 PowerShell 里运行它。"
