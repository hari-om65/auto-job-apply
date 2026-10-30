# Copy your private files (never in Git) from this PC to the server, plus your history so already-seen posts are skipped.
#   powershell -ExecutionPolicy Bypass -File deploy\push_secrets.ps1 -Server 203.0.113.5 -User ubuntu -Key $env:USERPROFILE\.ssh\jobserver
# Oracle Cloud and most clouds log you in as "ubuntu" (with sudo); some VPS hosts use "root".
# The Telegram login is NOT copied: one session used from two machines gets logged out, so log in on the server instead.
param([Parameter(Mandatory=$true)][string]$Server, [string]$Key = "$env:USERPROFILE\.ssh\jobserver", [string]$User = "ubuntu")
$root = Split-Path -Parent $PSScriptRoot
$files = @("config\telegram_apply.py", "telegram_apply\base_resume.pdf", "telegram_apply\ui_settings.json",
           "telegram_apply\dashboard_password.txt", "telegram_apply\llm_cache.jsonl", "telegram_apply\state.json",
           "telegram_apply\results.jsonl", "telegram_apply\linkedin_state.json")
$target = "${User}@${Server}"
ssh -i $Key -o StrictHostKeyChecking=accept-new $target "rm -rf /tmp/ja_push && mkdir -p /tmp/ja_push"
foreach ($f in $files) {
    $src = Join-Path $root $f
    if (Test-Path $src) {
        scp -i $Key $src "${target}:/tmp/ja_push/$(($f -replace '\\', '__'))"
    }
}
# move each file to its place in the app folder, owned by the app user
ssh -i $Key $target 'cd /tmp/ja_push && for f in *; do sudo install -o jobs -g jobs -m 600 -D "$f" "/opt/auto-job-apply/${f//__//}"; done; rm -rf /tmp/ja_push; sudo systemctl restart dashboard'
Write-Host "Done. Now log in once on the server: Telegram, then Google and LinkedIn (deploy/README.md, steps 5-6)."
