param(
    [string]$TaskName = "MLB-Pitch-Analytics-Daily-Update",
    [string]$DailyAt = "06:30"
)

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$updateScript = Join-Path $PSScriptRoot "run_daily_update.ps1"
$powerShellPath = (Get-Command powershell.exe -ErrorAction Stop).Source
$actionArguments = "-NoProfile -ExecutionPolicy Bypass -File `"$updateScript`""
$action = New-ScheduledTaskAction -Execute $powerShellPath -Argument $actionArguments -WorkingDirectory $repoRoot
$triggerTime = [DateTime]::Today.Add([TimeSpan]::Parse($DailyAt))
$trigger = New-ScheduledTaskTrigger -Daily -At $triggerTime
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Refresh 2025-2026 MLB Statcast data and rebuild the local analytics dashboard." `
    -Force | Out-Null

$task = Get-ScheduledTask -TaskName $TaskName
$info = Get-ScheduledTaskInfo -TaskName $TaskName
[pscustomobject]@{
    TaskName = $task.TaskName
    State = $task.State
    Enabled = $task.Settings.Enabled
    NextRunTime = $info.NextRunTime
    Action = $task.Actions.Execute
    Arguments = $task.Actions.Arguments
}
