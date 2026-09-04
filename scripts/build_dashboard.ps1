param()

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$nodePath = (Get-Command node -ErrorAction Stop).Source
$pluginPattern = Join-Path $env:USERPROFILE ".codex\plugins\cache\openai-curated-remote\data-analytics\*\scripts\data-app.mjs"
$buildHelper = Get-ChildItem -Path $pluginPattern -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

$dashboardDirectory = Join-Path $repoRoot "dashboard"
if ($buildHelper) {
    & $nodePath $buildHelper.FullName build --project-dir $dashboardDirectory --source
} else {
    $vitePath = Join-Path $dashboardDirectory "node_modules\vite\bin\vite.js"
    if (-not (Test-Path -LiteralPath $vitePath)) {
        throw "Neither the Data app build helper nor the local Vite runtime was found."
    }
    Push-Location -LiteralPath $dashboardDirectory
    try {
        & $nodePath $vitePath build
    } finally {
        Pop-Location
    }
}
if ($LASTEXITCODE -ne 0) {
    throw "Dashboard build failed with exit code $LASTEXITCODE."
}
