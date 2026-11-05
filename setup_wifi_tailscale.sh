#!/bin/bash
# One-time setup so the robot's Pi joins the phone hotspot and Tailscale on every boot, with no one at the Pi.
#
#   sudo ./setup_wifi_tailscale.sh "<hotspot name>"          (asks for the password, hidden)
#   sudo TS_AUTHKEY=tskey-... ./setup_wifi_tailscale.sh "<hotspot name>"   (no browser login)
#
# Safe to re-run: it replaces the "robot-hotspot" profile and skips Tailscale steps already done.
set -euo pipefail

[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
SSID=${1:?usage: sudo $0 \"<hotspot name>\" [password]}
PSK=${2:-}
if [ -z "$PSK" ]; then
    read -rsp "Password for \"$SSID\": " PSK; echo
fi
[ ${#PSK} -ge 8 ] || { echo "WPA passwords are at least 8 characters"; exit 1; }

echo "== Wi-Fi: profile robot-hotspot -> \"$SSID\""
nmcli radio wifi on
nmcli connection delete robot-hotspot >/dev/null 2>&1 || true
# Saved even if the hotspot is off right now; NetworkManager joins it whenever it appears.
# autoconnect-retries 0 = keep retrying forever (the default gives up after 4 failures until reboot).
# powersave 2 = off: Wi-Fi power saving adds 100+ ms ping spikes and drops idle SSH sessions.
nmcli connection add type wifi ifname wlan0 con-name robot-hotspot ssid "$SSID" \
    wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PSK" \
    connection.autoconnect yes connection.autoconnect-priority 100 connection.autoconnect-retries 0 \
    802-11-wireless.powersave 2 ipv4.method auto ipv6.method auto >/dev/null
chmod 600 /etc/NetworkManager/system-connections/robot-hotspot.nmconnection
echo "   saved. Trying to connect now (fine if the hotspot is off; it will join on its own later)..."
nmcli --wait 20 connection up robot-hotspot 2>&1 | sed 's/^/   /' || true

echo "== Tailscale"
if ! command -v tailscale >/dev/null; then
    curl -fsSL https://tailscale.com/install.sh | sh
fi
systemctl enable --now tailscaled
if tailscale status >/dev/null 2>&1; then
    echo "   already logged in:"; tailscale ip -4 | sed 's/^/   /'
elif [ -n "${TS_AUTHKEY:-}" ]; then
    tailscale up --auth-key "$TS_AUTHKEY"
else
    echo "   Open the link below on your phone or laptop and sign in to approve this Pi (one time only):"
    tailscale up
fi

echo
echo "== Result"
nmcli -t -f NAME,DEVICE connection show --active | sed 's/^/   active: /'
tailscale ip -4 2>/dev/null | sed 's/^/   tailscale IPv4: /' || true
echo "   In the Tailscale admin console, open this machine's menu and choose \"Disable key expiry\","
echo "   or it will drop off the tailnet in 180 days until someone logs in again."
