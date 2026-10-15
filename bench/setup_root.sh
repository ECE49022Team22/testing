#!/usr/bin/env bash
# One-time root setup for the benchmark. Run:  sudo ./setup_root.sh   then reboot.
#  1. Update the bootloader EEPROM: rp1-pio-uart (LiDAR on pin 15) needs PIO interrupts,
#     which the Dec 2025 bootloader doesn't provide ("No PIO interrupts - old EEPROM?").
#  2. Make the LiDAR UART and GPS PPS overlays permanent (runtime dtoverlay is lost on reboot).
#  3. Let the dialout group read /dev/ppsN (root-only by default) so the GPS worker can time PPS.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }

rpi-eeprom-update -a

CFG=/boot/firmware/config.txt
cp -n "$CFG" "$CFG.bak-bench" || true
add() { grep -qxF "$1" "$CFG" || { echo "$1" >> "$CFG"; echo "added to config.txt: $1"; }; }
tail -c1 "$CFG" | read -r _ || echo >> "$CFG"
grep -qx '\[all\]' <(tail -n 20 "$CFG" | grep '^\[' | tail -n1) || echo '[all]' >> "$CFG"
add 'dtoverlay=rp1-pio-uart,rx_pin=22,tx_pin=27'
add 'dtoverlay=pps-gpio,gpiopin=18'

echo 'KERNEL=="pps[0-9]*", GROUP="dialout", MODE="0660"' > /etc/udev/rules.d/99-pps-dialout.rules
echo "wrote /etc/udev/rules.d/99-pps-dialout.rules"

echo
echo "Done. Reboot now:  sudo reboot"
