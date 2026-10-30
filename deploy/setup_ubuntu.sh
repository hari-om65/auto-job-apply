#!/usr/bin/env bash
# One-time setup of the job dashboard on a fresh Ubuntu 22.04/24.04 server (run as root). x86 or ARM (Oracle Cloud free).
#   curl -fsSL https://raw.githubusercontent.com/hari-om65/auto-job-apply/main/deploy/setup_ubuntu.sh | sudo bash
set -euo pipefail
REPO="https://github.com/hari-om65/auto-job-apply.git"
APP=/opt/auto-job-apply
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y curl wget git ca-certificates gnupg python3 python3-venv python3-pip python3-tk python3-dev \
  scrot xvfb x11vnc novnc websockify fluxbox xdotool xterm fonts-liberation unzip ufw \
  debian-keyring debian-archive-keyring apt-transport-https software-properties-common

# Small servers (1 GB, e.g. Oracle's free AMD micro): swap so Chrome does not run out of memory
if [ "$(awk '/MemTotal/ {print $2}' /proc/meminfo)" -lt 3000000 ] && ! swapon --show | grep -q /swapfile; then
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q /swapfile /etc/fstab || echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi

# The pipeline drives a real, signed-in browser: Google Chrome on x86, Chromium on ARM (Chrome has no ARM Linux build)
if [ "$(dpkg --print-architecture)" = "amd64" ]; then
  if ! command -v google-chrome-stable >/dev/null; then
    wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
    apt-get install -y /tmp/chrome.deb
  fi
else
  # Ubuntu's own chromium is a snap, which cannot use a profile outside the home folder: use the xtradeb .deb build
  add-apt-repository -y ppa:xtradeb/apps
  apt-get update && apt-get install -y chromium chromium-driver   # the app finds this chromedriver by itself
fi

# Caddy: automatic https for a free, stable hostname <ip>.sslip.io
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update && apt-get install -y caddy
fi

id jobs >/dev/null 2>&1 || useradd -m -s /bin/bash jobs
if [ -d "$APP/.git" ]; then sudo -u jobs git -C "$APP" pull --ff-only; else git clone "$REPO" "$APP" && chown -R jobs:jobs "$APP"; fi
sudo -u jobs bash -c "cd $APP && python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -r requirements.txt"
mkdir -p "$APP/telegram_apply/output" "$APP/all excels" && chown -R jobs:jobs "$APP"

cat > /etc/systemd/system/xvfb.service <<UNIT
[Unit]
Description=Virtual display for the job dashboard's Chrome
[Service]
ExecStart=/usr/bin/Xvfb :99 -screen 0 1600x1000x24 -nolisten tcp
Restart=always
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/fluxbox.service <<UNIT
[Unit]
Description=Window manager on the virtual display
After=xvfb.service
Requires=xvfb.service
[Service]
User=jobs
Environment=DISPLAY=:99
ExecStart=/usr/bin/fluxbox
Restart=always
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/dashboard.service <<UNIT
[Unit]
Description=Job dashboard (Telegram + LinkedIn pipelines)
After=xvfb.service network-online.target
Requires=xvfb.service
[Service]
User=jobs
WorkingDirectory=$APP
Environment=DISPLAY=:99 JA_SERVER=1 PYTHONIOENCODING=utf-8 HOME=/home/jobs
ExecStart=$APP/.venv/bin/python -W ignore -m telegram_apply.web
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT

IP=$(curl -s https://api.ipify.org)
HOST="$(echo "$IP" | tr . -).sslip.io"
cat > /etc/caddy/Caddyfile <<CADDY
$HOST {
    reverse_proxy 127.0.0.1:5055
}
CADDY

if iptables -S INPUT | grep -q -- "-j REJECT"; then
  # Oracle Cloud images ship their own iptables rules ending in REJECT (ufw would fight them): allow web traffic first
  for port in 80 443; do
    iptables -C INPUT -p tcp --dport $port -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -p tcp --dport $port -j ACCEPT
  done
  netfilter-persistent save
else
  ufw allow OpenSSH >/dev/null; ufw allow 80,443/tcp >/dev/null; ufw --force enable >/dev/null
fi
systemctl daemon-reload
systemctl enable --now xvfb fluxbox dashboard caddy
systemctl restart caddy

echo
echo "DONE. Dashboard URL: https://$HOST   (login: admin / the password in $APP/telegram_apply/dashboard_password.txt)"
echo "Next: copy your private files with deploy/push_secrets.ps1, then sign in once to Google and LinkedIn (see deploy/README.md)."
