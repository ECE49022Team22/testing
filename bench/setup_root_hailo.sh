#!/usr/bin/env bash
# Enable the Pi 5's external PCIe port for the AI HAT+ without relying on its ID EEPROM (pins 27/28),
# and install the Hailo driver/runtime. Run:  sudo ./setup_root_hailo.sh   then reboot.
#
#   dtparam=pciex1       turn the external PCIe connector on (normally done when the firmware reads a
#                        HAT+ EEPROM; this does it unconditionally)
#   dtparam=pciex1_gen=3 PCIe Gen 3 (8 GT/s), what the AI HAT+ normally asks for. If the link is unstable
#                        (dmesg PCIe/AER errors, hailortcli failing), rerun with --gen2.
#   hailo-all            Hailo PCIe kernel driver (DKMS), HailoRT runtime + hailortcli, firmware, examples.
#
# The bootloader EEPROM is left alone: PCIE_PROBE=1 only matters for *booting* from a PCIe device that has
# no HAT+ EEPROM (e.g. NVMe); Linux brings the port up from config.txt by itself.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
GEN=3
[ "${1:-}" = "--gen2" ] && GEN=2

CFG=/boot/firmware/config.txt
cp "$CFG" "$CFG.bak-hailo"
sed -i '/^dtparam=pciex1\(_gen=[0-9]\)\?$/d' "$CFG"      # drop earlier copies, then append under [all]
tail -n 20 "$CFG" | grep '^\[' | tail -n1 | grep -qx '\[all\]' || echo '[all]' >> "$CFG"
echo 'dtparam=pciex1' >> "$CFG"
echo "dtparam=pciex1_gen=$GEN" >> "$CFG"
echo "config.txt: dtparam=pciex1, dtparam=pciex1_gen=$GEN (backup: $CFG.bak-hailo)"

apt-get update
apt-get install -y hailo-all

echo
echo "Done. Reboot now:  sudo reboot"
echo "Then check:  lspci | grep -i hailo ;  ls /dev/hailo0 ;  hailortcli fw-control identify"
