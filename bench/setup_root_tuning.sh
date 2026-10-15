#!/usr/bin/env bash
# Root setup for suggestions 3, 5 and 6. Run:  sudo ./setup_root_tuning.sh   then reboot.
#  5. LiDAR moved from pin 15 (PIO UART) to pin 29: swap the rp1-pio-uart overlay for UART2.
#  6. FTDI (STM32 motor link) latency timer 16 ms -> 1 ms, applied whenever the adapter appears.
#  3. Let sdteam22 use SCHED_FIFO (rtprio <= 90) and mlockall without sudo (takes effect at next login).
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }

CFG=/boot/firmware/config.txt
cp "$CFG" "$CFG.bak-tuning"
if grep -q '^dtoverlay=rp1-pio-uart' "$CFG"; then
    sed -i 's/^dtoverlay=rp1-pio-uart.*/dtoverlay=uart2-pi5/' "$CFG"
    echo "config.txt: rp1-pio-uart -> uart2-pi5 (LiDAR on /dev/ttyAMA2)"
elif ! grep -qx 'dtoverlay=uart2-pi5' "$CFG"; then
    echo 'dtoverlay=uart2-pi5' >> "$CFG"
    echo "config.txt: added dtoverlay=uart2-pi5"
fi

cat > /etc/udev/rules.d/99-ftdi-low-latency.rules <<'EOF'
# STM32 motor link: flush received bytes to the host after 1 ms instead of 16 ms
ACTION=="add", SUBSYSTEM=="usb-serial", DRIVER=="ftdi_sio", ATTR{latency_timer}="1"
EOF
echo "wrote /etc/udev/rules.d/99-ftdi-low-latency.rules"
for t in /sys/bus/usb-serial/devices/ttyUSB*/latency_timer; do [ -e "$t" ] && echo 1 > "$t"; done

cat > /etc/security/limits.d/90-robot-rt.conf <<'EOF'
# Real-time scheduling for the robot apps (see ~/testing/rt_tune.py)
sdteam22  -  rtprio   90
sdteam22  -  memlock  unlimited
EOF
echo "wrote /etc/security/limits.d/90-robot-rt.conf"

echo
echo "Done. Reboot now:  sudo reboot"
