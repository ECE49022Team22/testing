#!/bin/bash
# Ping the phone hotspot every 2 s so it sees traffic and stays up; log only state changes,
# plus a once-a-minute internet check. Stop with: pkill -f hotspot_keepalive.sh
GW=172.20.10.1
LOG=~/motor_cal/hotspot_keepalive.log
last=""; n=0
echo "$(date '+%F %T') keepalive started (gateway $GW)" >> "$LOG"
while true; do
  if ping -c 1 -W 2 -I wlan0 "$GW" > /dev/null 2>&1; then s="up"; else s="DOWN ($(nmcli -t -f STATE device show wlan0 2>/dev/null | head -1 | cut -d: -f2))"; fi
  [ "$s" != "$last" ] && echo "$(date '+%F %T') hotspot $s" >> "$LOG" && last="$s"
  n=$((n + 1))
  if [ $((n % 30)) -eq 0 ]; then
    ping -c 1 -W 3 -I wlan0 8.8.8.8 > /dev/null 2>&1 && inet="ok" || inet="FAIL"
    echo "$(date '+%F %T') minute check: hotspot $s, internet $inet" >> "$LOG"
  fi
  sleep 2
done
