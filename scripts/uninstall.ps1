param(
    [string]$CodexHome = $(if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $env:USERPROFILE '.codex' })
)
$ErrorActionPreference = 'Stop'
$skillTarget = [IO.Path]::GetFullPath((Join-Path $CodexHome 'skills/remind-at-done'))
$instructions = Join-Path $CodexHome 'AGENTS.md'
if (Test-Path -LiteralPath $instructions) {
    $old = [IO.File]::ReadAllText($instructions)
    $next = [regex]::Replace($old, '(?s)<!-- remind-at-done:start -->.*?<!-- remind-at-done:end -->', '')
    [IO.File]::WriteAllText($instructions, $next, (New-Object Text.UTF8Encoding($false)))
}
if (Test-Path -LiteralPath (Join-Path $skillTarget 'installation.json')) {
    $metadata = Get-Content -Raw -LiteralPath (Join-Path $skillTarget 'installation.json') | ConvertFrom-Json
    $appExe = [IO.Path]::GetFullPath((Join-Path $metadata.app 'RemindAtDone.exe'))
    Get-Process RemindAtDone -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $appExe } | Stop-Process
    $expectedParent = [IO.Path]::GetFullPath((Join-Path $CodexHome 'skills'))
    if ((Split-Path $skillTarget -Parent) -ne $expectedParent) { throw 'Unexpected skill path.' }
    Remove-Item -LiteralPath $skillTarget -Recurse -Force
}
$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$runValue = (Get-ItemProperty -LiteralPath $runKey -Name 'RemindAtDone' -ErrorAction SilentlyContinue).RemindAtDone
if ($runValue -and $metadata -and $runValue -eq ('"' + $appExe + '"')) {
    Remove-ItemProperty -LiteralPath $runKey -Name 'RemindAtDone'
}
Write-Output 'Integration removed and app stopped. History/settings and app files are retained in LOCALAPPDATA/RemindAtDone; delete them manually if no longer needed.'
