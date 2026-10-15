#!/usr/bin/env bash
# Root setup for suggestion 2 (core split) and 7 (performance governor).
# Run:  sudo ./setup_root_cores.sh   then reboot.   Undo: sudo ./setup_root_cores.sh --undo
#
#   core 0     OS, desktop, cellular, USB (camera + FTDI share usb1), Ethernet, SD card, I2C
#   core 1     sensors: IMU, LiDAR, GPS, motor link + their IRQs (SPI, UARTs, GPIO, PPS)
#   cores 2-3  YOLO + camera decode
#
# 1. cmdline.txt: isolcpus=1 (the scheduler puts nothing on core 1 unless it's pinned there) and
#    irqaffinity=0 (every IRQ starts on core 0). This kernel has no rcu_nocbs / nohz_full support.
# 2. robot-cpu-tuning.service, at every boot: performance governor; SPI, PPS and GPIO IRQs to
#    core 1; default affinity for IRQs requested later = core 1, because those are the sensors'
#    (a PL011 UART only requests its IRQ when the port is opened).
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
CMD=/boot/firmware/cmdline.txt
UNIT=/etc/systemd/system/robot-cpu-tuning.service
BIN=/usr/local/sbin/robot-cpu-tuning.sh

if [ "${1:-}" = "--undo" ]; then
    sed -i 's/ isolcpus=1//; s/ irqaffinity=0//' "$CMD"
    systemctl disable --now robot-cpu-tuning.service 2>/dev/null || true
    rm -f "$UNIT" "$BIN"
    systemctl daemon-reload
    echo "undone; reboot to apply"
    exit 0
fi

cp "$CMD" "$CMD.bak-cores"
for arg in isolcpus=1 irqaffinity=0; do
    grep -qw "$arg" "$CMD" || sed -i "1 s/\$/ $arg/" "$CMD"
done
echo "cmdline.txt: $(cat "$CMD")"

cat > "$BIN" <<'EOF'
#!/usr/bin/env bash
# Installed by ~/testing/bench/setup_root_cores.sh. Logs to the journal: journalctl -u robot-cpu-tuning
SENSOR_CPU=1
for g in /sys/devices/system/cpu/cpufreq/policy*/scaling_governor; do echo performance > "$g"; done
echo "governor: $(cat /sys/devices/system/cpu/cpufreq/policy0/scaling_governor)"
printf '%x\n' $((1 << SENSOR_CPU)) > /proc/irq/default_smp_affinity
echo "default IRQ affinity (IRQs requested later, e.g. UARTs on open): cpu$SENSOR_CPU"
# IRQs that already exist at boot and belong to the sensors
grep -E 'spi|pps|pinctrl-rp1|gpio@|\.gpio|serial|ttyAMA' /proc/interrupts | grep -v pwr_button |
while read -r line; do
    irq=${line%%:*}; irq=${irq// /}
    [ -e "/proc/irq/$irq/smp_affinity_list" ] || continue
    if echo "$SENSOR_CPU" > "/proc/irq/$irq/smp_affinity_list" 2>/dev/null; then
        echo "irq $irq -> cpu$SENSOR_CPU: ${line##* }"
    else
        echo "irq $irq: affinity not settable (${line##* })"
    fi
done
EOF
chmod 755 "$BIN"

cat > "$UNIT" <<EOF
[Unit]
Description=Robot CPU tuning: performance governor, sensor IRQs on core 1
After=sysinit.target

[Service]
Type=oneshot
ExecStart=$BIN
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable robot-cpu-tuning.service
echo "installed $UNIT"
echo
echo "Done. Reboot now:  sudo reboot"
