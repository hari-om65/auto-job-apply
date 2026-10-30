# Run the dashboard on a free Oracle Cloud server (works with your PC off)

The dashboard, its schedules, the "Apply to a job now" box and all your logins live on the server. Open it from any
phone at a permanent address `https://<ip-with-dashes>.sslip.io`. Cost: $0 on Oracle's Always Free tier (a card is
needed to sign up, as identity check; you are not charged while you stay on Always Free resources).
Any other Ubuntu 22.04/24.04 server with 2 GB+ RAM also works (Hetzner, DigitalOcean...).

## 1. Create the free server (Oracle Cloud console)
1. Sign up at https://signup.cloud.oracle.com (pick a home region near you, e.g. Mumbai or Hyderabad; it cannot be changed).
2. **Compute -> Instances -> Create instance**
   - Image: **Canonical Ubuntu 24.04** (or 22.04)
   - Shape: **Ampere VM.Standard.A1.Flex**, 2 OCPU + 12 GB memory (Always Free covers up to 4 OCPU / 24 GB in total).
     If it says "out of capacity", try again later or another availability domain, or use **VM.Standard.E2.1.Micro**
     (AMD, 1 GB, also free; the setup adds swap so Chrome fits, but it is slow).
   - Networking: keep "Assign a public IPv4 address" on.
   - SSH keys: "Generate a key pair for me" -> **Save private key** to `C:\Users\<you>\.ssh\jobserver` (keep it secret).
3. Open the web ports: on the instance page click the **subnet -> Default security list -> Add ingress rules**:
   source CIDR `0.0.0.0/0`, TCP, destination port `80`; add a second one for `443`.
4. Note the instance's **Public IP address**.

## 2. Install everything (one command)
From PowerShell on your PC:
```
ssh -i $env:USERPROFILE\.ssh\jobserver ubuntu@<ip>
curl -fsSL https://raw.githubusercontent.com/hari-om65/auto-job-apply/main/deploy/setup_ubuntu.sh | sudo bash
```
It installs Chrome (Chromium on ARM), a virtual screen, the app from GitHub, https and services that restart on their own
(also after a server reboot). At the end it prints your dashboard address.

## 3. Copy your private files from the PC (in a new PowerShell window, from the project folder)
```
powershell -ExecutionPolicy Bypass -File deploy\push_secrets.ps1 -Server <ip>
```
Copies your config, resume, settings, dashboard password and history. Nothing private goes through GitHub.

## 4. Log in to Telegram on the server (in the SSH window)
```
cd /opt/auto-job-apply && sudo -u jobs .venv/bin/python -m telegram_apply.login
```
Enter your phone number and the code Telegram sends you. (A separate login from the PC's, so neither gets logged out.)

## 5. Sign in to Google and LinkedIn once (the server has no screen, so you look at its virtual desktop)
```
ssh -i $env:USERPROFILE\.ssh\jobserver -L 6080:localhost:6080 ubuntu@<ip>       # keep this window open
sudo -u jobs bash /opt/auto-job-apply/deploy/login_desktop.sh
```
Open http://localhost:6080/vnc.html on your PC and click Connect. Then, in the SSH window:
```
cd /opt/auto-job-apply && sudo -u jobs env DISPLAY=:99 JA_SERVER=1 .venv/bin/python -m telegram_apply.google_login            # Google
cd /opt/auto-job-apply && sudo -u jobs env DISPLAY=:99 JA_SERVER=1 .venv/bin/python -m telegram_apply.google_login linkedin   # LinkedIn
```
Sign in in the browser window you see, close it, press Enter in SSH. These logins are saved on the server's disk
(`telegram_apply/chrome_profile`), not in GitHub, and survive restarts.

## 6. Use it
Open the address from step 2 on any phone; log in with `admin` + the password from `telegram_apply\dashboard_password.txt`.
Tick **Watch the channels** and use **Apply to a job now** whenever you like.

**Turn the PC version off** so both do not apply to the same jobs:
`Unregister-ScheduledTask -TaskName JobDashboard -Confirm:$false`

## Later
- Update to the newest code: `sudo -u jobs git -C /opt/auto-job-apply pull && sudo systemctl restart dashboard`
- Live log: `journalctl -u dashboard -f`
- Oracle may reclaim Always Free instances that sit almost completely idle for 7 days; watch mode keeps it busy enough.
- Google and LinkedIn may ask for extra verification when you sign in from a data-centre address, and LinkedIn can
  restrict accounts that apply from one. Start with Dry run on and a small volume.
