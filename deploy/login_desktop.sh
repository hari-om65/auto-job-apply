#!/usr/bin/env bash
# Run on the server as user "jobs" when you need to sign in to Google / LinkedIn in the server's Chrome.
# Shows the server's virtual desktop in your browser through an SSH tunnel (nothing is exposed publicly):
#   on your PC:  ssh -L 6080:localhost:6080 jobs@YOUR_SERVER_IP
#   then open:   http://localhost:6080/vnc.html
export DISPLAY=:99
pkill x11vnc 2>/dev/null; pkill websockify 2>/dev/null
x11vnc -display :99 -localhost -nopw -forever -shared -bg -quiet
websockify -D --web /usr/share/novnc 6080 localhost:5900
echo "Desktop ready. In your browser open http://localhost:6080/vnc.html (after: ssh -L 6080:localhost:6080 jobs@SERVER)."
echo "Now run, in the SSH session:  cd /opt/auto-job-apply && sudo -u jobs env DISPLAY=:99 JA_SERVER=1 .venv/bin/python -m telegram_apply.google_login [linkedin]"
