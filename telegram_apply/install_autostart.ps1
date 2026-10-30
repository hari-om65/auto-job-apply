# Keeps the job dashboard + public link running: starts it at login and checks every 5 minutes, so if it ever stops
# (crash, sleep, lost internet) it comes back by itself - no PC restart needed. Only one copy runs at a time.
# Install:   powershell -ExecutionPolicy Bypass -File telegram_apply\install_autostart.ps1
# Remove:    Unregister-ScheduledTask -TaskName JobDashboard -Confirm:$false
$root = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python).Source
$cmd = "Set-Location -LiteralPath '$root'; & '$python' -W ignore -m telegram_apply.live *>> 'telegram_apply\live.log'"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -Command `"$cmd`""
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$every5min = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -MultipleInstances IgnoreNew -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName "JobDashboard" -Action $action -Trigger @($atLogon, $every5min) -Settings $settings -Force | Out-Null
Write-Host "Installed: the dashboard starts at login and is restarted within 5 minutes if it ever stops."
Write-Host "Start it now with: Start-ScheduledTask -TaskName JobDashboard"
