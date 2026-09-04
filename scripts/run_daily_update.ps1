param(
    [ValidateRange(0, 14)]
    [int]$RefreshDays = 3
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$logDirectory = Join-Path $repoRoot "logs"
$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
$statusPath = Join-Path $logDirectory "daily_update_status.json"
$lockPath = Join-Path $logDirectory "daily_update.lock"
$startedAt = [DateTime]::UtcNow
$transcriptStarted = $false
$lock = $null

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python environment not found: $pythonPath"
}

try {
    $lock = [System.IO.File]::Open(
        $lockPath,
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
} catch {
    Write-Output "Another MLB daily update is already running; this invocation will exit without overlap."
    exit 0
}

try {
    $logPath = Join-Path $logDirectory ("daily_update_{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))
    Start-Transcript -Path $logPath -Append | Out-Null
    $transcriptStarted = $true
    Set-Location -LiteralPath $repoRoot

    & $pythonPath "run_pipeline.py" --mode full --refresh-days $RefreshDays
    if ($LASTEXITCODE -ne 0) {
        throw "MLB pipeline failed with exit code $LASTEXITCODE."
    }

    & (Join-Path $PSScriptRoot "build_dashboard.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "Dashboard build failed with exit code $LASTEXITCODE."
    }

    $status = [ordered]@{
        status = "success"
        started_at_utc = $startedAt.ToString("o")
        finished_at_utc = [DateTime]::UtcNow.ToString("o")
        refresh_days = $RefreshDays
        dashboard = "dashboard/dist/index.html"
    }
    $status | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8
    Write-Output "Daily MLB update completed successfully."
} catch {
    $status = [ordered]@{
        status = "failed"
        started_at_utc = $startedAt.ToString("o")
        finished_at_utc = [DateTime]::UtcNow.ToString("o")
        refresh_days = $RefreshDays
        error = $_.Exception.Message
    }
    $status | ConvertTo-Json | Set-Content -LiteralPath $statusPath -Encoding utf8
    Write-Error $_
    exit 1
} finally {
    if ($transcriptStarted) {
        Stop-Transcript | Out-Null
    }
    if ($lock) {
        $lock.Dispose()
    }
}
