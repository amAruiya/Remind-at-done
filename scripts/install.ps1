param(
    [string]$CodexHome = $(if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' }),
    [string]$CodexExe,
    [string]$Destination = (Join-Path $env:LOCALAPPDATA 'RemindAtDone/app')
)
$ErrorActionPreference = 'Stop'
$CodexHome = [IO.Path]::GetFullPath($CodexHome)
if ($CodexHome.Length -gt ([IO.Path]::GetPathRoot($CodexHome)).Length) {
    $CodexHome = $CodexHome.TrimEnd([char[]]@('\','/'))
}
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'rad.exe'))) { throw 'Run install.ps1 from a published release directory.' }
if (-not $CodexExe) {
    $status = & codex app-server daemon version | ConvertFrom-Json
    $CodexExe = $status.managedCodexPath
}
if (-not (Test-Path -LiteralPath $CodexExe -PathType Leaf)) { throw 'Pass -CodexExe with the actual codex.exe path.' }
$destinationFull = [IO.Path]::GetFullPath($Destination)
$installedExe = Join-Path $destinationFull 'RemindAtDone.exe'
Get-Process RemindAtDone -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $installedExe } | Stop-Process
New-Item -ItemType Directory -Force $destinationFull | Out-Null
if ($destinationFull -ne $PSScriptRoot) {
    Get-ChildItem -LiteralPath $PSScriptRoot | Copy-Item -Destination $destinationFull -Recurse -Force
}
& (Join-Path $destinationFull 'rad.exe') register --home $CodexHome --codex $CodexExe
if ($LASTEXITCODE -ne 0) { throw 'Instance registration failed.' }
$skillTarget = Join-Path $CodexHome 'skills/remind-at-done'
if ((Test-Path -LiteralPath $skillTarget) -and -not (Test-Path -LiteralPath (Join-Path $skillTarget 'installation.json'))) {
    throw 'An unrelated remind-at-done skill already exists; it was not overwritten.'
}
New-Item -ItemType Directory -Force $skillTarget | Out-Null
Get-ChildItem -LiteralPath (Join-Path $destinationFull 'skills/remind-at-done') | Copy-Item -Destination $skillTarget -Recurse -Force
$utf8 = New-Object Text.UTF8Encoding($false)
$metadata = @{ rad = (Join-Path $destinationFull 'rad.exe'); app = $destinationFull } | ConvertTo-Json
[IO.File]::WriteAllText((Join-Path $skillTarget 'installation.json'), $metadata, $utf8)
$instructions = Join-Path $CodexHome 'AGENTS.md'
$old = if (Test-Path -LiteralPath $instructions) { [IO.File]::ReadAllText($instructions) } else { '' }
$markerStart = '<!-- remind-at-done:start -->'
$markerEnd = '<!-- remind-at-done:end -->'
$block = $markerStart + "`r`n" + '主任务准备最终答复前，读取 ' + (Join-Path $skillTarget 'SKILL.md') + '，按其规则判断是否通知。子代理不投递。' + "`r`n" + $markerEnd
if ($old.Contains($markerStart)) {
    $next = [regex]::Replace($old, '(?s)<!-- remind-at-done:start -->.*?<!-- remind-at-done:end -->', [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $block })
} else { $next = $old + "`r`n" + $block + "`r`n" }
[IO.File]::WriteAllText($instructions, $next, $utf8)
& (Join-Path $destinationFull 'rad.exe') start
if ($LASTEXITCODE -ne 0) { throw 'App launch failed.' }
Write-Output 'Installed. Login startup remains opt-in. New Codex tasks load the finishing instruction.'
