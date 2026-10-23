[CmdletBinding()]
param(
    [ValidateSet('help', 'screen', 'finalize', 'verify', 'test', 'docs', 'check-docs')]
    [string]$Action = 'help',
    [string]$PythonPath,
    [string]$Output,
    [ValidateRange(1, 100000)]
    [int]$Sample = 30,
    [int]$Seed = 20261023,
    [string]$Reviews,
    [ValidateRange(1, 100000)]
    [int]$Count = 10,
    [string]$Run
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$scriptPath = Join-Path $projectRoot '03_程序\csds_screen.py'
if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
    throw "找不到程序：$scriptPath。请把启动脚本放在项目根目录。"
}

# 跳过可能打开商店的 WindowsApps 占位入口，优先使用明确指定的解释器。
$candidates = [System.Collections.Generic.List[string]]::new()
if ($PythonPath) {
    if (-not [System.IO.Path]::IsPathRooted($PythonPath)) {
        $PythonPath = Join-Path $projectRoot $PythonPath
    }
    $candidates.Add($PythonPath)
} else {
    $systemPython = Get-Command python -ErrorAction SilentlyContinue
    if ($systemPython -and $systemPython.Source -notlike '*\WindowsApps\*') {
        $candidates.Add($systemPython.Source)
    }
    $bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (Test-Path -LiteralPath $bundledPython -PathType Leaf) {
        $candidates.Add($bundledPython)
    }
}

$python = $null
foreach ($candidate in $candidates) {
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
    try {
        $version = & $candidate -c 'import sys; print(sys.version.split()[0]); sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0) {
            $python = $candidate
            break
        }
    } catch {
        continue
    }
}
if (-not $python) {
    throw '没有找到可用的 Python 3.10+。请用 -PythonPath 指定 python.exe 的完整路径；无需修改项目代码。'
}

Write-Host "项目目录：$projectRoot"
Write-Host "Python：$python"

switch ($Action) {
    'help' {
        Write-Host ('运行筛选：& "{0}" -Action screen' -f $PSCommandPath)
        Write-Host ('人工标注后导出：& "{0}" -Action finalize -Count 10' -f $PSCommandPath)
        Write-Host ('核对历史文件：& "{0}" -Action verify -Run "04_实验记录/02_第二次筛选_v0.2"' -f $PSCommandPath)
        Write-Host ('检查程序：& "{0}" -Action test' -f $PSCommandPath)
        Write-Host '输出目录不填时自动新建；所有相对路径都从项目根目录计算。'
        Write-Host ('更新状态和目录：& "{0}" -Action docs' -f $PSCommandPath)
        Write-Host ('检查项目说明：& "{0}" -Action check-docs' -f $PSCommandPath)
        exit 0
    }
    'docs' {
        $invokeArgs = @((Join-Path $projectRoot '03_程序\更新项目说明.py'))
    }
    'check-docs' {
        $invokeArgs = @((Join-Path $projectRoot '03_程序\检查项目说明.py'))
    }
    'test' {
        $testDir = Join-Path $projectRoot '03_程序'
        $invokeArgs = @('-m', 'unittest', 'discover', '-s', $testDir, '-p', 'test_*.py', '-v')
    }
    'screen' {
        $invokeArgs = @($scriptPath, 'screen', '--sample', "$Sample", '--seed', "$Seed")
        if ($Output) { $invokeArgs += @('--output', $Output) }
    }
    'finalize' {
        $invokeArgs = @($scriptPath, 'finalize', '--n', "$Count", '--seed', "$Seed")
        if ($Reviews) { $invokeArgs += @('--reviews', $Reviews) }
        if ($Output) { $invokeArgs += @('--output', $Output) }
    }
    'verify' {
        if (-not $Run) { throw '请用 -Run 指定需要检查的实验文件夹。' }
        $invokeArgs = @($scriptPath, 'verify', '--run', $Run)
    }
}

$env:PYTHONIOENCODING = 'utf-8'
& $python @invokeArgs
exit $LASTEXITCODE
