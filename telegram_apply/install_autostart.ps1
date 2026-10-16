# Starts the job dashboard + public link automatically every time you log in to Windows.
# Install:   powershell -ExecutionPolicy Bypass -File telegram_apply\install_autostart.ps1
# Remove:    Unregister-ScheduledTask -TaskName JobDashboard -Confirm:$false
$root = Split-Path -Parent $PSScriptRoot
$python = (Get-Command python).Source
$cmd = "Set-Location -LiteralPath '$root'; & '$python' -W ignore -m telegram_apply.live *>> 'telegram_apply\live.log'"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -Command `"$cmd`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName "JobDashboard" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "Installed: the dashboard will start at every login. Start it now with: Start-ScheduledTask -TaskName JobDashboard"
