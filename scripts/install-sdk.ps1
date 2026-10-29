$ErrorActionPreference = 'Stop'
$sdkVersion = '10.0.403'
$sdkDir = Join-Path $env:LOCALAPPDATA 'RemindAtDone.Build/dotnet'
$sdkZip = Join-Path $env:TEMP "rad-dotnet-$sdkVersion.zip"
if (-not (Test-Path (Join-Path $sdkDir "sdk/$sdkVersion"))) {
    Invoke-WebRequest "https://builds.dotnet.microsoft.com/dotnet/Sdk/$sdkVersion/dotnet-sdk-$sdkVersion-win-x64.zip" -OutFile $sdkZip -UseBasicParsing
    $expected = '7a114c318fa7f1d9822991b534b2814d0e78386ceda816b371f5141acefe741d87ccb606ede06cadac8f9ac5070e32b708a67bbd1619ff5e5a7858a27874ef48'
    if ((Get-FileHash $sdkZip -Algorithm SHA512).Hash.ToLowerInvariant() -ne $expected) { throw 'SDK checksum mismatch' }
    New-Item -ItemType Directory -Force $sdkDir | Out-Null
    Expand-Archive -LiteralPath $sdkZip -DestinationPath $sdkDir -Force
    Remove-Item -LiteralPath $sdkZip
}
& (Join-Path $sdkDir 'dotnet.exe') --version
