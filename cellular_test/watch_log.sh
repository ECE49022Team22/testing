#!/bin/bash
# Live, color-coded view of the cellular receiver log, for watching on the Pi's own screen.
#   ./watch_log.sh            (in a terminal)
#   ./watch_log.sh --open     (opens an lxterminal window on the Pi's desktop, e.g. from ssh)
cd "$(dirname "$0")"
LOG=logs/cellular_log.txt

if [ "$1" = "--open" ]; then
    export XDG_RUNTIME_DIR=/run/user/$(id -u) WAYLAND_DISPLAY=wayland-0
    setsid lxterminal --title="Cellular log" --geometry=140x40 -e "$PWD/watch_log.sh" >/dev/null 2>&1 &
    exit 0
fi

printf '\e]0;Cellular log\a'
echo "Watching $PWD/$LOG  (Ctrl-C to close)"
echo "green = command received/ok   red = error/crash   yellow = session closed   grey = heartbeat"
echo
tail -n 30 -F "$LOG" | awk -W interactive '
    /crashed|"ok": false|error/   { c = "\033[1;31m" }
    /received:|-> \[|"ok": true/  { c = "\033[1;32m" }
    /session not open|connected-closed|disconnected/ { c = "\033[33m" }
    /heartbeat:.*session open/    { c = "\033[36m" }
    /receiver start|=====/        { if (!/crashed/) c = "\033[1;35m" }
    /raw:/                        { c = "\033[2m" }
    { print c $0 "\033[0m"; c = ""; fflush() }
'
