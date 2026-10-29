param(
    [string]$StartedAt,
    [string]$CompletedAt,
    [string]$State,
    [switch]$RootTask
)
$ErrorActionPreference = 'Stop'
$result = @{ eligible = $false; elapsed_seconds = $null; reason = 'not_completed_main_task' }
if ($RootTask -and $State -eq 'completed') {
    $start = [DateTimeOffset]::MinValue
    $end = [DateTimeOffset]::MinValue
    $zone = 'T.*(Z|[+-]\d{2}:\d{2})$'
    if ($StartedAt -notmatch $zone -or $CompletedAt -notmatch $zone -or
        -not [DateTimeOffset]::TryParse($StartedAt, [ref]$start) -or
        -not [DateTimeOffset]::TryParse($CompletedAt, [ref]$end)) {
        $result.reason = 'unknown_time'
    } elseif ($end -lt $start) {
        $result.reason = 'reversed_time'
    } else {
        $result.elapsed_seconds = ($end - $start).TotalSeconds
        $result.eligible = $result.elapsed_seconds -gt 300
        $result.reason = if ($result.eligible) { 'eligible' } else { 'at_most_300_seconds' }
    }
}
$result | ConvertTo-Json -Compress
