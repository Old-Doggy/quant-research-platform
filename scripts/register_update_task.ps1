param(
    [string]$RequestFile,
    [string]$ResultFile,
    [string]$TaskName = 'QuantResearchDailyUpdate',
    [switch]$Enable,
    [switch]$Remove
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    return
}
if (-not $Enable) {
    Write-Output '配置模板已就绪。尚未安装或启用计划任务；明确启用时传入 -Enable。'
    return
}
if (-not $RequestFile -or -not $ResultFile) {
    throw '启用时需要 RequestFile 和 ResultFile'
}
$requestPath = (Resolve-Path -LiteralPath $RequestFile).Path
$resultPath = [System.IO.Path]::GetFullPath($ResultFile)
if ($requestPath.Contains('"') -or $resultPath.Contains('"')) {
    throw '任务参数路径不能包含双引号'
}
$arguments = '-m portfolio_app.update_cli --request "{0}" --result "{1}"' -f $requestPath, $resultPath
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument $arguments -WorkingDirectory $projectRoot
# Windows task time uses the host timezone. Translate the Shanghai daily close window.
$zone = [TimeZoneInfo]::FindSystemTimeZoneById('China Standard Time')
$localNow = Get-Date
$shanghaiToday = [TimeZoneInfo]::ConvertTime($localNow, $zone).Date.AddHours(18).AddMinutes(30)
$hostTime = [TimeZoneInfo]::ConvertTime($shanghaiToday, $zone, [TimeZoneInfo]::Local)
$trigger = New-ScheduledTaskTrigger -Daily -At $hostTime
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description '量化研究平台：指定范围日频数据更新' -Force
