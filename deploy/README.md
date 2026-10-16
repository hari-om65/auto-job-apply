# Deploy the dashboard on a cloud server (runs without your PC)

Works on a fresh **Ubuntu 22.04/24.04** VPS with at least **2 GB RAM** (Chrome needs it). Examples: Hetzner CX22
(~EUR 4/month), DigitalOcean 2 GB droplet (~$12), any similar plan.

1. **Create the server** (Ubuntu, 2 GB+). Add your SSH public key when creating it.
2. **Install everything** (as root on the server):
   `curl -fsSL https://raw.githubusercontent.com/hari-om65/auto-job-apply/main/deploy/setup_ubuntu.sh | bash`
   It installs Chrome, a virtual display, the app from GitHub, https (Caddy) and services that restart on their own.
   It prints your stable address: `https://<ip-with-dashes>.sslip.io`
3. **Copy your private files** from the PC: `powershell -ExecutionPolicy Bypass -File deploy\push_secrets.ps1 -Server <ip>`
4. **Sign in once** to Google and LinkedIn on the server's Chrome (a server has no screen, so you look at its virtual desktop):
   ```
   ssh -L 6080:localhost:6080 jobs@<ip>          # keep this window open
   bash /opt/auto-job-apply/deploy/login_desktop.sh
   # open http://localhost:6080/vnc.html in your browser, then in the SSH window:
   cd /opt/auto-job-apply && JA_SERVER=1 .venv/bin/python -m telegram_apply.google_login            # Google
   cd /opt/auto-job-apply && JA_SERVER=1 .venv/bin/python -m telegram_apply.google_login linkedin    # LinkedIn
   ```
   Sign in in the Chrome window you see in the browser, close it, press Enter in SSH.
5. Open the dashboard address, log in (`admin` + the password in `telegram_apply/dashboard_password.txt`), set the schedules.

Update later: `sudo -u jobs git -C /opt/auto-job-apply pull && sudo systemctl restart dashboard`
Logs: `journalctl -u dashboard -f`

Caveats: Google and LinkedIn may ask for extra verification when you sign in from a data-centre address, and LinkedIn can
restrict accounts that apply from one. Start with Dry run on and a small volume.
