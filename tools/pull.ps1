# 大肥鱼桌宠：一键更新（给 git clone 下来的使用者）
#
# 作用：停桌宠 -> git pull -> 按需重装依赖 -> 重启桌宠，一条命令走完。
#
# 用法（在仓库目录里）：
#     powershell -ExecutionPolicy Bypass -File .\tools\pull.ps1
#
# 只看看会做什么、不实际改动：
#     powershell -ExecutionPolicy Bypass -File .\tools\pull.ps1 -DryRun
#
# 不自动重启桌宠（更新完自己手动起）：
#     powershell -ExecutionPolicy Bypass -File .\tools\pull.ps1 -NoRestart
#
# 退出码：0 成功 / 1 前置条件不满足 / 2 更新过程失败 / 3 更新成功但有需要人工处理的事
# 结果文件：本目录下的 pull-status.json（ok / exitCode / stage / message）
#
# ============================================================================
# 为什么需要它：**必须先退出桌宠才能更新素材**
# ============================================================================
# 【stream 模式】下每个在用的动画都挂着一个常驻 ffmpeg，它把 webm 一直开着读。
# 实测（tools/probe_git_pull_while_running.py）：
#     $ git checkout -- webm/xxx.webm
#     error: unable to unlink old 'webm/xxx.webm': Invalid argument
# 注意报错是 **Invalid argument** 而不是权限错误 —— 很容易让人去查文件权限，
# 其实是"宠物还开着"。所以这个脚本第一件事就是停桌宠。
# （代码文件不受影响，Windows 上 Python 不独占 .py；只有 webm 会挡住。）
#
# 注意：本文件里**不要出现反引号**（注释里的反引号也会转义行尾换行）。
# 本文件必须存为 **UTF-8 with BOM**，否则 Windows PowerShell 5.1 会把中文读成乱码。

[CmdletBinding()]
param(
    [switch]$DryRun,      # 只报告，不改动
    [switch]$NoRestart,   # 更新完不自动重启桌宠
    [string]$Python       # 指定 python.exe；默认自动探测 .venv 或 PATH
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$StatusPath = Join-Path $PSScriptRoot 'pull-status.json'

function Say($text) { Write-Host $text }
function Step($text) { Write-Host "  $text" }
function Section($text) { Write-Host ''; Write-Host "=== $text ===" }

function Write-Status($ok, $code, $stage, $message, $extra) {
    $payload = [ordered]@{
        ok       = $ok
        exitCode = $code
        stage    = $stage
        message  = $message
        repoRoot = $RepoRoot
        dryRun   = [bool]$DryRun
        time     = (Get-Date).ToString('s')
    }
    if ($extra) { foreach ($key in $extra.Keys) { $payload[$key] = $extra[$key] } }
    # **必须写成不带 BOM 的 UTF-8。**
    # 【Set-Content -Encoding UTF8】在 Windows PowerShell 5.1 下会写 BOM，而带 BOM
    # 的 JSON 会被严格解析器拒绝：Python 的 json.load 报
    # "Expecting value: line 1 column 1"，Node 的 JSON.parse 同样失败
    # （只有 PowerShell 自己的 ConvertFrom-Json 容忍它）。
    # 实测踩过：这一行原先就是 Set-Content，生成的 pull-status.json 前三个字节是
    # EF BB BF，被 tools/check_syntax.py 直接判为"不是合法 JSON"。
    $json = $payload | ConvertTo-Json -Depth 4
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($StatusPath, $json, $utf8NoBom)
}

# --- 找桌宠进程（**只匹配 main.py / run_logged**，不做全量杀 python） --------- #
function Get-PetProcesses {
    $found = @()
    $all = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue
    foreach ($item in $all) {
        if ($item.CommandLine -and ($item.CommandLine -match 'main\.py' -or $item.CommandLine -match 'run_logged')) {
            $found += $item
        }
    }
    return $found
}

function Stop-PetProcesses {
    $targets = Get-PetProcesses
    if (-not $targets) { return 0 }
    foreach ($item in $targets) {
        Step ("停止桌宠 PID " + $item.ProcessId)
        Stop-Process -Id $item.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 3
    return $targets.Count
}

function Resolve-Python {
    if ($Python) { return $Python }
    $venv = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (Test-Path $venv) { return $venv }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

# ============================================================================ #
Section '一键更新：大肥鱼桌宠'
if ($DryRun) { Say '  （DryRun：只报告，不做任何改动）' }
Say "  仓库目录: $RepoRoot"

# --- 前置：得是 git 仓库 ---------------------------------------------------- #
if (-not (Test-Path (Join-Path $RepoRoot '.git'))) {
    Say ''
    Say '  这里不是 git 仓库 —— 说明这个项目是**下载 ZIP** 拿到的，没有 git 历史，'
    Say '  无法增量更新。两条路：'
    Say '    * 重新下载整个 ZIP（约 52 MB），用新目录覆盖旧目录，保留自己的配置；'
    Say '    * 或改用 git clone，以后一条命令就能更新。'
    Write-Status $false 1 'precondition' 'not-a-git-repository'
    exit 1
}

Push-Location $RepoRoot
try {
    # --- 1. 先看本地有没有未提交的改动 -------------------------------------- #
    Section '1. 检查本地改动'
    $dirty = & git status --porcelain
    $dirtyList = @($dirty | Where-Object { $_ -and $_.Trim() })
    if ($dirtyList.Count -gt 0) {
        Step ("本地有 " + $dirtyList.Count + " 处未提交改动：")
        foreach ($line in $dirtyList[0..([Math]::Min(9, $dirtyList.Count - 1))]) {
            Step ("  " + $line)
        }
        Say ''
        Say '  **这些改动会挡住 git pull。** 请先自行处理（提交、或 git checkout -- 丢弃），'
        Say '  或者把个人配置改动搬到 config.user.jsonc（它不进 git，永远不会冲突）。'
        Write-Status $false 1 'dirty-worktree' 'local-changes-present'
        exit 1
    }
    Step '工作区干净'

    # --- 2. 停桌宠 ---------------------------------------------------------- #
    Section '2. 停止桌宠'
    $running = Get-PetProcesses
    if (-not $running) {
        Step '桌宠没在运行'
    } else {
        Step ("发现 " + $running.Count + " 个桌宠进程 —— 必须先停掉：")
        Say '    stream 模式下 ffmpeg 一直开着 webm，不停掉的话 git 无法覆盖素材，'
        Say '    会报 "unable to unlink old ...: Invalid argument"。'
        if (-not $DryRun) { Stop-PetProcesses | Out-Null }
        else { Step '（DryRun：不停）' }
    }

    # --- 3. 记下更新前的提交，用来判断依赖有没有变 -------------------------- #
    $beforeHead = (& git rev-parse HEAD).Trim()

    # --- 4. 拉取 ------------------------------------------------------------ #
    Section '3. git pull'
    if ($DryRun) {
        Say '  将要执行: git pull'
        $behind = & git rev-list --count 'HEAD..@{u}' 2>$null
        if ($behind) { Say "  落后远程 $behind 个提交" }
    } else {
        $pullOutput = & git pull 2>&1
        $pullCode = $LASTEXITCODE
        foreach ($line in $pullOutput) { Step $line }
        if ($pullCode -ne 0) {
            Say ''
            Say '  **git pull 失败**（退出码 ' + $pullCode + '）。'
            Say '  如果报的是 unable to unlink old ... 之类，多半是桌宠还在跑；'
            Say '  如果报的是本地改动会被覆盖，见上面第 1 步的提示。'
            Write-Status $false 2 'git-pull' ('exit-code-' + $pullCode)
            exit 2
        }
    }
    $afterHead = (& git rev-parse HEAD).Trim()
    if ($beforeHead -eq $afterHead) { Step '已经是最新（没有新提交）' }
    else { Step ("更新: " + $beforeHead.Substring(0,7) + " -> " + $afterHead.Substring(0,7)) }

    # --- 5. 依赖变了才重装 -------------------------------------------------- #
    Section '4. Python 依赖'
    $py = Resolve-Python
    $reqChanged = $false
    if ($beforeHead -ne $afterHead) {
        $changed = & git diff --name-only $beforeHead $afterHead
        if ($changed -match 'requirements') { $reqChanged = $true }
    }
    if ($reqChanged) {
        Step 'requirements 有变化，需要重装'
        if ($py) {
            if ($DryRun) { Say "  将要执行: $py -m pip install -r requirements.txt" }
            else {
                & $py -m pip install -r (Join-Path $RepoRoot 'requirements.txt')
                if ($LASTEXITCODE -ne 0) {
                    Say '  **pip install 失败** —— 桌宠可能起不来。请检查网络/代理后重试。'
                    Write-Status $false 2 'pip-install' ('exit-code-' + $LASTEXITCODE)
                    exit 2
                }
            }
        } else {
            Say '  **找不到 python** —— 请手动执行: python -m pip install -r requirements.txt'
        }
    } else {
        Step 'requirements 没有变化，跳过'
    }

    # --- 6. 重启 ------------------------------------------------------------ #
    Section '5. 重启桌宠'
    if ($NoRestart) {
        Step '（-NoRestart：请自行启动）'
    } elseif ($DryRun) {
        Step '（DryRun：不启动）'
    } else {
        if (-not $py) {
            Say '  **找不到 python，无法自动重启** —— 请手动启动桌宠。'
        } else {
            $pythonw = Join-Path (Split-Path -Parent $py) 'pythonw.exe'
            if (-not (Test-Path $pythonw)) { $pythonw = $py }
            # 参数用哈希表展开，避免 PowerShell 的行续接反引号（反引号在注释里也会
            # 转义行尾换行，本项目已因此踩过坑，规则里明确禁用）。
            $startArgs = @{
                FilePath         = $pythonw
                ArgumentList     = @('-X', 'utf8', (Join-Path $RepoRoot 'main.py'))
                WorkingDirectory = $RepoRoot
                WindowStyle      = 'Hidden'
            }
            Start-Process @startArgs
            Step '已启动'
            Start-Sleep -Seconds 4
            try {
                $health = Invoke-RestMethod 'http://127.0.0.1:8899/health' -TimeoutSec 4
                Step ("健康检查通过: mood=" + $health.mood + " playing=" + $health.playing)
            } catch {
                Say '  **启动后健康检查没应答** —— 看日志:'
                Say ("    " + (Join-Path $RepoRoot 'logs\pet-run.log'))
            }
        }
    }

    Section '完成'
    Say '  更新已应用。'
    Say '  个人配置请写进 config.user.jsonc（不进 git，永远不会与更新冲突）。'
    Write-Status $true 0 'done' 'updated'
    exit 0
}
finally {
    Pop-Location
}
