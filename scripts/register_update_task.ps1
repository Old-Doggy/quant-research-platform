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
# The worker decides the Shanghai window; hourly wakeups survive host DST changes.
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Hours 1)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Description '量化研究平台：指定范围日频数据更新' -Force
