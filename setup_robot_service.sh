#!/bin/bash
# Make the robot start its program at every boot: a systemd service, cosmo-robot, running robot_service.sh
# (follow.py --app). It connects to the web app, serves the control page on :8100, restarts itself if it stops, and
# resumes a delivery that was in progress. Driving starts DISABLED: enable it on the page once the robot is somewhere safe.
#
#   sudo bash setup_robot_service.sh               install, enable at boot, start now
#   sudo bash setup_robot_service.sh --uninstall   stop, disable, remove
#
# It also removes the old "@reboot ... cellular_logger.sh" crontab line (the Notecard receiver, no longer used);
# the crontab is backed up first. Safe to re-run.
set -euo pipefail

[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
RUN_USER=${SUDO_USER:?run with sudo from the robot user, not as root}
HOME_DIR=$(getent passwd "$RUN_USER" | cut -d: -f6)
REPO=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
UNIT=/etc/systemd/system/cosmo-robot.service
ENV_FILE="$HOME_DIR/.config/cosmo_robot.env"

if [ "${1:-}" = "--uninstall" ]; then
    systemctl disable --now cosmo-robot 2>/dev/null || true
    rm -f "$UNIT"
    systemctl daemon-reload
    echo "removed cosmo-robot.service (crontab and $ENV_FILE left as they are)"
    exit 0
fi

[ -x "$REPO/.venv/bin/python" ] || { echo "no $REPO/.venv: set up the Python venv first"; exit 1; }
chmod +x "$REPO/robot_service.sh"

echo "== token: $ENV_FILE"
if ! grep -q '^ROBOT_API_TOKEN=.' "$ENV_FILE" 2>/dev/null; then
    read -rsp "Robot token (ROBOT_API_TOKEN, same value as in Vercel): " TOKEN; echo
    [ -n "$TOKEN" ] || { echo "no token given"; exit 1; }
    install -d -o "$RUN_USER" -g "$RUN_USER" -m 700 "$HOME_DIR/.config"
    echo "ROBOT_API_TOKEN=$TOKEN" >> "$ENV_FILE"
fi
chown "$RUN_USER:$RUN_USER" "$ENV_FILE"
chmod 600 "$ENV_FILE"
echo "   ok. To change follow.py's flags, add COSMO_FLAGS=\"...\" to that file (defaults: robot_service.sh)"

echo "== old Notecard autostart (crontab)"
if crontab -u "$RUN_USER" -l 2>/dev/null | grep -q 'cellular_logger.sh'; then
    BACKUP="$HOME_DIR/crontab.backup.$(date +%Y%m%d_%H%M%S)"
    crontab -u "$RUN_USER" -l > "$BACKUP"
    chown "$RUN_USER:$RUN_USER" "$BACKUP"
    grep -v 'cellular_logger.sh' "$BACKUP" | crontab -u "$RUN_USER" -
    echo "   removed the cellular_logger.sh line (backup: $BACKUP)"
else
    echo "   none"
fi

echo "== service: $UNIT"
cat > "$UNIT" <<EOF
[Unit]
Description=Cosmo delivery robot: follow.py --app (web app link, control page :8100)
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
User=$RUN_USER
WorkingDirectory=$REPO
ExecStart=$REPO/robot_service.sh
Restart=always
RestartSec=5
# Ctrl-C: follow.py stops the motors and writes its log before exiting
KillSignal=SIGINT
TimeoutStopSec=20
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now cosmo-robot
sleep 3
systemctl --no-pager --lines=8 status cosmo-robot || true

echo
echo "== Done. It starts at every boot, with driving DISABLED."
echo "   control page:  http://<pi>:8100/  (Tailscale: http://$(tailscale ip -4 2>/dev/null | head -1 || echo '<tailscale ip>'):8100/)"
echo "   live output:   journalctl -u cosmo-robot -f"
echo "   stop / start:  sudo systemctl stop cosmo-robot   /   sudo systemctl start cosmo-robot"
echo "   Stop it before running anything else that uses the motors, GPS or LiDAR (demo, follow.py local, motor_cal)."
