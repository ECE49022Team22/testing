#!/usr/bin/env bash
# Run receive_demo.py in the background (detached tmux session) so it keeps receiving and logging
# after your SSH session closes. Everything goes to logs/cellular_log.txt.
#
#   ./cellular_logger.sh start    # start (restarts itself 5 s after a crash)
#   ./cellular_logger.sh status   # running? + last 5 log lines
#   ./cellular_logger.sh view     # follow the log live (Ctrl-C stops viewing, not logging)
#   ./cellular_logger.sh attach   # see the live console (detach: Ctrl-b then d)
#   ./cellular_logger.sh stop
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

SESSION=cellular
LOG=logs/cellular_log.txt
running() { tmux has-session -t "$SESSION" 2>/dev/null; }

case "${1:-}" in
    start)
        if running; then echo "already running (./cellular_logger.sh attach to see it)"; exit 0; fi
        mkdir -p logs
        shift
        # "$*" passes extra options through, e.g. ./cellular_logger.sh start --interval 2
        tmux new-session -d -s "$SESSION" \
            "while true; do .venv/bin/python receive_demo.py --log $LOG $*; echo 'receiver exited; restarting in 5 s'; sleep 5; done"
        sleep 3
        echo "started; logging to $PWD/$LOG"
        tail -n 5 "$LOG" 2>/dev/null || true
        ;;
    stop)
        if running; then
            tmux send-keys -t "$SESSION" C-c  # let the receiver write its "stopped" line
            sleep 1
            tmux kill-session -t "$SESSION" 2>/dev/null || true  # Ctrl-C usually ends it already
            echo "stopped"
        else
            echo "not running"
        fi
        ;;
    status)
        if running; then echo "running"; else echo "NOT running"; fi
        tail -n 5 "$LOG" 2>/dev/null || echo "(no log yet)"
        ;;
    view)   tail -n 30 -F "$LOG" ;;
    attach) tmux attach -t "$SESSION" ;;
    *)      sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
