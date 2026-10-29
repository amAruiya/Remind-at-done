param([Parameter(Mandatory=$true)][string]$Capsule)
$ErrorActionPreference = 'Stop'
try {
    $route = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Capsule)) | ConvertFrom-Json
    $thread = [Guid]::ParseExact($route.thread_id, 'D').ToString()
    $taskDirectory = [IO.Path]::GetFullPath([string]$route.cwd)
    if ($taskDirectory.Length -gt ([IO.Path]::GetPathRoot($taskDirectory)).Length) {
        $taskDirectory = $taskDirectory.TrimEnd([char[]]@('\','/'))
    }
    if (-not (Test-Path -LiteralPath $route.executable -PathType Leaf)) { throw 'Codex executable is missing.' }
    if (-not (Test-Path -LiteralPath $route.cwd -PathType Container)) { throw 'Task working directory is missing.' }
    $env:CODEX_HOME = $route.codex_home
    # Tool subprocesses disable terminal styling. A user-opened Codex view is interactive.
    Remove-Item Env:NO_COLOR -ErrorAction SilentlyContinue
    if ($env:TERM -eq 'dumb') { Remove-Item Env:TERM -ErrorAction SilentlyContinue }
    if ([string]::IsNullOrEmpty($env:COLORTERM)) { Remove-Item Env:COLORTERM -ErrorAction SilentlyContinue }
    Set-Location -LiteralPath $taskDirectory
    & $route.executable resume $thread --cd $taskDirectory
    if ($LASTEXITCODE -ne 0) { Write-Host "Codex resume exited with $LASTEXITCODE. The original thread was not replaced." }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
}
