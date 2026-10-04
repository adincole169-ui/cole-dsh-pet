# 打包「更新补丁」：给已经装过旧版本的人用。
#
# 产物结构：
#     dsh-pet-update\
#       update.ps1          更新脚本（覆盖变动文件 + 备份配置 + 校验）
#       更新说明.md          改了什么的说明
#       payload\            变动文件，按目标路径摆放
#         config.jsonc
#         main.py
#         README.md
#         src\pet.py
#         src\config.py
#         frames\...        全部 106 个动画的原生 640 帧
#       dsh-pet-update.zip
#
# 与 build_package.ps1 的区别：那个出**完整包**（含 .venv 之外的运行所需一切、
# install.ps1、profile-plugin），这个只出**差异**（只够更新已装的桌宠）。
#
# 用法：
#     powershell -ExecutionPolicy Bypass -File .\build_update.ps1
#     powershell -ExecutionPolicy Bypass -File .\build_update.ps1 -SkipFrames   # 只打代码部分（快速验证）
#
# 注意：本文件必须存为 UTF-8 with BOM；不要用反引号。

[CmdletBinding()]
param(
    # 留空则用 <项目根>\dist
    [string]$OutputRoot = '',
    [string]$FolderName = 'dsh-pet-update',
    [switch]$SkipFrames,
    [switch]$SkipZip
)

$ErrorActionPreference = 'Stop'
$Quote = [char]34

function Say($text) { Write-Host $text }
function Step($text) { Write-Host "  $text" }
function Section($text) { Write-Host ""; Write-Host "=== $text ===" }

$PetRoot = Split-Path -Parent $PSScriptRoot
if (-not $OutputRoot) { $OutputRoot = Join-Path $PetRoot 'dist' }
$Stage = Join-Path $OutputRoot $FolderName
$Payload = Join-Path $Stage 'payload'
$ZipPath = Join-Path $OutputRoot ($FolderName + '.zip')

Say ""
Say "大肥鱼桌宠：打包更新补丁"
Say "  源目录:   $PetRoot"
Say "  输出目录: $Stage"

# ----------------------------------------------------------------- 准备输出
Section "1/4 准备输出目录"
if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
New-Item -ItemType Directory -Path $Payload -Force | Out-Null
Step "已清空并重建"

# ----------------------------------------------------------------- 代码文件
Section "2/4 复制变动的代码文件"

# 这些是自上次发布后改动过的（用 tools\compare_package.py 核对过）
$changed = @(
    @{ source = 'config.jsonc'; target = 'config.jsonc' },
    @{ source = 'main.py';      target = 'main.py' },
    @{ source = 'README.md';    target = 'README.md' },
    @{ source = 'src\pet.py';   target = 'src\pet.py' },
    @{ source = 'src\config.py'; target = 'src\config.py' }
)
foreach ($item in $changed) {
    $from = Join-Path $PetRoot $item.source
    $to = Join-Path $Payload $item.target
    if (-not (Test-Path $from)) { Step ("缺少 " + $item.source); continue }
    $toDir = Split-Path $to -Parent
    if (-not (Test-Path $toDir)) { New-Item -ItemType Directory -Path $toDir -Force | Out-Null }
    Copy-Item $from $to -Force
    $kb = [math]::Round((Get-Item $to).Length / 1KB, 1)
    Step ((($item.source).PadRight(18)) + "$kb KB")
}

# 附带自检脚本（README 里引用了它们，方便对方自查）
$selftests = @('selftest_display_name.py', 'selftest_character_bounds.py',
               'selftest_still_mode.py', 'check_syntax.py', 'doctor.py')
$toolsTarget = Join-Path $Payload 'tools'
New-Item -ItemType Directory -Path $toolsTarget -Force | Out-Null
foreach ($name in $selftests) {
    $from = Join-Path $PSScriptRoot $name
    if (Test-Path $from) { Copy-Item $from $toolsTarget -Force; Step "tools\$name" }
}

# ----------------------------------------------------------------- 帧素材
Section "3/4 帧素材"
if ($SkipFrames) {
    Step "已跳过（-SkipFrames）：补丁里不含帧素材，装完画面不会变清晰"
} else {
    $source = Join-Path $PetRoot 'frames'
    $target = Join-Path $Payload 'frames'
    if (-not (Test-Path $source)) {
        Step "源目录没有 frames\，跳过"
    } else {
        New-Item -ItemType Directory -Path $target -Force | Out-Null
        $copied = 0
        Get-ChildItem $source -Directory | Where-Object { -not $_.Name.StartsWith('_') } | ForEach-Object {
            $destination = Join-Path $target $_.Name
            New-Item -ItemType Directory -Path $destination -Force | Out-Null
            Get-ChildItem $_.FullName -File | ForEach-Object { Copy-Item $_.FullName $destination -Force }
            $copied++
            if ($copied % 20 -eq 0) { Step "已复制 $copied 个动画..." }
        }
        $files = (Get-ChildItem $target -Recurse -File).Count
        $size = (Get-ChildItem $target -Recurse -File | Measure-Object Length -Sum).Sum
        Step "已复制 $copied 个动画、$files 个 PNG，$([math]::Round($size / 1GB, 2)) GB"
    }
}

# ----------------------------------------------------------------- 脚本与说明
Section "4/4 更新脚本与说明"
foreach ($name in @('update.ps1', '更新说明.md', '更新.cmd')) {
    $from = Join-Path $PSScriptRoot $name
    if (Test-Path $from) {
        Copy-Item $from $Stage -Force
        Step $name
    } else {
        Step "缺少 $name"
    }
}

# ----------------------------------------------------------------- 汇总
Section "汇总"
$totalFiles = (Get-ChildItem $Stage -Recurse -File).Count
$totalSize = (Get-ChildItem $Stage -Recurse -File | Measure-Object Length -Sum).Sum
Say ("  总大小 {0} GB，{1} 个文件" -f [math]::Round($totalSize / 1GB, 2), $totalFiles)
foreach ($folder in (Get-ChildItem $Stage -Directory)) {
    $size = (Get-ChildItem $folder.FullName -Recurse -File | Measure-Object Length -Sum).Sum
    Say ("    {0,-14} {1} MB" -f $folder.Name, [math]::Round($size / 1MB, 1))
}

if (-not $SkipZip) {
    Section "压缩"
    if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
    Step "正在压缩（GB 级别，需要几分钟）..."
    Compress-Archive -Path (Join-Path $Stage '*') -DestinationPath $ZipPath -CompressionLevel Optimal
    $zipSize = (Get-Item $ZipPath).Length
    Step ("完成: {0}（{1} GB）" -f $ZipPath, [math]::Round($zipSize / 1GB, 2))
}

Say ""
Say "更新补丁已就绪。发给已装过旧版本的人，让他们解压后运行："
Say "  powershell -ExecutionPolicy Bypass -File .\update.ps1"
Say ""
