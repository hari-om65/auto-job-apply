# Copy your private files (never in Git) from this PC to the server.
#   powershell -ExecutionPolicy Bypass -File deploy\push_secrets.ps1 -Server 203.0.113.5 -Key $env:USERPROFILE\.ssh\jobserver
param([Parameter(Mandatory=$true)][string]$Server, [string]$Key = "$env:USERPROFILE\.ssh\jobserver", [string]$User = "root")
$root = Split-Path -Parent $PSScriptRoot
$files = @("config\telegram_apply.py", "telegram_apply\base_resume.pdf", "telegram_apply\tg_session.session",
           "telegram_apply\ui_settings.json", "telegram_apply\dashboard_password.txt", "telegram_apply\llm_cache.jsonl")
foreach ($f in $files) {
    $src = Join-Path $root $f
    if (Test-Path $src) {
        $dest = "/opt/auto-job-apply/" + ($f -replace "\\", "/")
        scp -i $Key -o StrictHostKeyChecking=accept-new $src "${User}@${Server}:$dest"
    }
}
ssh -i $Key "${User}@${Server}" "chown -R jobs:jobs /opt/auto-job-apply && systemctl restart dashboard"
Write-Host "Done. Now sign in once to Google and LinkedIn on the server (deploy/README.md, step 4)."
