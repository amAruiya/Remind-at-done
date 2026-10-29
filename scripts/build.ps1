param([string]$Output = 'output/release', [switch]$SelfContained)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$sdk = Join-Path $env:LOCALAPPDATA 'RemindAtDone.Build/dotnet/dotnet.exe'
if (-not (Test-Path -LiteralPath $sdk)) { $sdk = (Get-Command dotnet).Source }
$destination = [IO.Path]::GetFullPath((Join-Path $repo $Output))
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:DOTNET_NOLOGO = '1'
Push-Location $repo
try {
    $contained = if ($SelfContained) { 'true' } else { 'false' }
    foreach ($project in @('RemindAtDone', 'rad')) {
        & $sdk publish "src/$project/$project.csproj" -c Release -r win-x64 --self-contained $contained -o $destination --nologo
        if ($LASTEXITCODE -ne 0) { throw "Build failed: $project" }
    }
    $skillDestination = Join-Path $destination 'skills'
    New-Item -ItemType Directory -Force $skillDestination | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $repo 'skills') | Copy-Item -Destination $skillDestination -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'install.ps1'), (Join-Path $PSScriptRoot 'uninstall.ps1') -Destination $destination
    Copy-Item -LiteralPath (Join-Path $repo 'README.md') -Destination $destination
    $docsDestination = Join-Path $destination 'docs'
    New-Item -ItemType Directory -Force $docsDestination | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $repo 'docs') | Copy-Item -Destination $docsDestination -Recurse -Force
    Write-Output $destination
} finally { Pop-Location }
