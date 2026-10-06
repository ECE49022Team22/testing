#!/usr/bin/env bash
# Make the Raspberry Pi's USB-C port act as a USB Ethernet adapter (g_ether), so a laptop
# plugged into it can SSH in with no other network.
#
#   sudo bash setup_usb_gadget.sh             # set up (takes effect after a reboot)
#   sudo bash setup_usb_gadget.sh --uninstall # undo
#
# After rebooting with a laptop on the USB-C port:  ssh sdteam22@192.168.77.1
#
# What it changes (each file is backed up first, eth0/Wi-Fi and the running system are not touched):
#   config.txt   appends "dtoverlay=dwc2,dr_mode=peripheral" in its own [all] block. UART/serial lines are
#                verified unchanged afterwards, otherwise the original is restored.
#   cmdline.txt  adds "modules-load=dwc2,g_ether" (stays one line).
#   modprobe     fixed MAC addresses for usb0, so the laptop sees the same adapter every boot.
#   NetworkManager profile "usb-gadget" bound to usb0 only: static 192.168.77.1/24, and the Pi hands the
#                laptop an address by DHCP (no gateway or DNS, so the laptop keeps using its Wi-Fi for internet).
#                IPv6 link-local is on too, as a fallback.
set -euo pipefail

IFACE=usb0
CON_NAME=usb-gadget
PI_ADDR=192.168.77.1/24
OVERLAY='dtoverlay=dwc2,dr_mode=peripheral'
MARKER='# USB gadget (virtual Ethernet on USB-C), added by setup_usb_gadget.sh'
MODPROBE_CONF=/etc/modprobe.d/usb-gadget-mac.conf
DNSMASQ_CONF=/etc/NetworkManager/dnsmasq-shared.d/80-usb-gadget-no-route.conf
# NetworkManager's stock 85-nm-unmanaged.rules marks every gadget netdev unmanaged, so without this
# override usb0 never gets the profile below (no 192.168.77.1, no DHCP for the laptop).
UDEV_RULE=/etc/udev/rules.d/86-usb-gadget-nm-managed.rules

die() { printf '\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }
info() { printf '\033[32m==>\033[0m %s\n' "$*"; }

[ "$(id -u)" -eq 0 ] || die "run as root: sudo bash $0"
grep -q 'Raspberry Pi' /proc/device-tree/model 2>/dev/null || die "not a Raspberry Pi"

# 1. Find the boot partition.
if [ -f /boot/firmware/config.txt ]; then
    BOOT=/boot/firmware
elif [ -f /boot/config.txt ]; then
    BOOT=/boot
else
    die "can't find config.txt in /boot/firmware or /boot"
fi
CONFIG=$BOOT/config.txt
CMDLINE=$BOOT/cmdline.txt
[ -f "$CMDLINE" ] || die "can't find $CMDLINE"
info "boot files: $CONFIG, $CMDLINE"

serial_lines() { grep -inE 'uart|serial|console|enable_uart' "$1" || true; }

if [ "${1:-}" = "--uninstall" ]; then
    info "removing the gadget overlay from $CONFIG"
    cp -a "$CONFIG" "$CONFIG.pre-usb-gadget-uninstall.$(date +%Y%m%d-%H%M%S)"
    # Delete our marker, the [all] line right after it, and the overlay line.
    sed -i "\|^$MARKER\$|{N;N;d}" "$CONFIG"
    info "removing modules-load from $CMDLINE"
    cp -a "$CMDLINE" "$CMDLINE.pre-usb-gadget-uninstall.$(date +%Y%m%d-%H%M%S)"
    sed -i -E 's/ modules-load=dwc2,g_ether( |$)/\1/; s/(modules-load=[^ ]*),dwc2,g_ether/\1/' "$CMDLINE"
    rm -f "$MODPROBE_CONF" "$DNSMASQ_CONF" "$UDEV_RULE"
    nmcli connection delete "$CON_NAME" >/dev/null 2>&1 || true
    info "done; reboot to apply"
    exit 0
fi

STAMP=$(date +%Y%m%d-%H%M%S)
cp -a "$CONFIG" "$CONFIG.pre-usb-gadget.$STAMP"
cp -a "$CMDLINE" "$CMDLINE.pre-usb-gadget.$STAMP"
info "backups: $CONFIG.pre-usb-gadget.$STAMP, $CMDLINE.pre-usb-gadget.$STAMP"

# 2. Device tree overlay. Appended in a fresh [all] block so it can't land inside a [cm4]/[pi5]/... section,
#    and nothing existing is edited.
SERIAL_BEFORE=$(serial_lines "$CONFIG")
if grep -qxF "$OVERLAY" "$CONFIG"; then
    info "overlay already present"
else
    [ -n "$(tail -c1 "$CONFIG")" ] && echo >>"$CONFIG"  # file didn't end with a newline
    printf '\n%s\n[all]\n%s\n' "$MARKER" "$OVERLAY" >>"$CONFIG"
    info "added: $OVERLAY"
fi
if [ "$(serial_lines "$CONFIG")" != "$SERIAL_BEFORE" ]; then
    cp -a "$CONFIG.pre-usb-gadget.$STAMP" "$CONFIG"
    die "UART/serial lines in config.txt changed; restored the backup"
fi
info "UART/serial lines unchanged:"
printf '%s\n' "$SERIAL_BEFORE" | sed 's/^/      /'

# 3. Kernel command line: must stay a single line. Merge into an existing modules-load= if there is one.
LINE=$(head -n1 "$CMDLINE" | tr -d '\r\n')
if [[ $LINE =~ (^|[[:space:]])modules-load=([^[:space:]]*) ]]; then
    MODS=${BASH_REMATCH[2]}
    NEW=$MODS
    for m in dwc2 g_ether; do [[ ,$NEW, == *,$m,* ]] || NEW=$NEW,$m; done
    LINE=${LINE/modules-load=$MODS/modules-load=$NEW}
else
    LINE="$LINE modules-load=dwc2,g_ether"
fi
printf '%s\n' "$LINE" >"$CMDLINE"
if [ "$(wc -l <"$CMDLINE")" -ne 1 ] || ! grep -q 'root=' "$CMDLINE"; then
    cp -a "$CMDLINE.pre-usb-gadget.$STAMP" "$CMDLINE"
    die "cmdline.txt check failed; restored the backup"
fi
info "cmdline.txt: $(cat "$CMDLINE")"

# Fixed MACs (locally administered) so the laptop doesn't see a "new" network adapter on every boot.
cat >"$MODPROBE_CONF" <<'EOF'
# Added by setup_usb_gadget.sh: stable MAC addresses for the USB Ethernet gadget.
options g_ether dev_addr=02:22:22:00:00:01 host_addr=02:22:22:00:00:02
EOF
info "wrote $MODPROBE_CONF"

# 4. Network profile. Only ever applies to usb0; the existing eth0 connection (and this SSH session) is untouched.
command -v nmcli >/dev/null || die "NetworkManager (nmcli) not found"
if systemctl is-enabled --quiet rpi-usb-gadget-ics.service 2>/dev/null; then
    printf '\033[33mWARNING: rpi-usb-gadget-ics.service is enabled and will fight over usb0. Disable it with: sudo rpi-usb-gadget off\033[0m\n'
fi
cat >"$UDEV_RULE" <<EOF
# Added by setup_usb_gadget.sh: let NetworkManager manage the USB Ethernet gadget (overrides 85-nm-unmanaged.rules).
SUBSYSTEM=="net", ACTION=="add|change|move", ENV{INTERFACE}=="$IFACE", ENV{NM_UNMANAGED}="0"
EOF
info "wrote $UDEV_RULE"
if [ -e "/sys/class/net/$IFACE" ]; then  # gadget already loaded: apply now too
    udevadm control --reload
    udevadm trigger --action=change "/sys/class/net/$IFACE"
    nmcli device set "$IFACE" managed yes || true
fi
mkdir -p "$(dirname "$DNSMASQ_CONF")"
cat >"$DNSMASQ_CONF" <<'EOF'
# Added by setup_usb_gadget.sh. The Pi has no internet to share over USB: don't send the laptop a default
# gateway or DNS server, or the laptop may try to route its traffic through the Pi.
dhcp-option=option:router
dhcp-option=option:dns-server
EOF
nmcli connection delete "$CON_NAME" >/dev/null 2>&1 || true
nmcli connection add type ethernet ifname "$IFACE" con-name "$CON_NAME" \
    connection.autoconnect yes \
    ipv4.method shared \
    ipv4.addresses "$PI_ADDR" \
    ipv4.never-default yes \
    ipv6.method link-local >/dev/null
info "NetworkManager profile '$CON_NAME': $IFACE = $PI_ADDR, DHCP for the laptop, IPv6 link-local"

cat <<EOF

Done. Nothing is active yet: reboot to apply ("sudo reboot"). Ethernet keeps working after the reboot.
Then plug a laptop into the Pi's USB-C port and run:   ssh $SUDO_USER@${PI_ADDR%/*}
Check on the Pi with:   ip addr show $IFACE ; nmcli device status

POWER: the USB-C port is now also the Pi's ONLY power input. A laptop port gives a Pi 5 much less than its
27 W supply (often 0.9-3 A), and the Notecard's radio bursts already cause undervoltage on a 3 A supply.
Use a laptop USB-C port (not USB-A), and run "vcgencmd get_throttled" (0x0 = fine) during the test.
EOF
