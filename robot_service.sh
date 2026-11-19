#!/bin/bash
# What the cosmo-robot service runs at boot (installed by setup_robot_service.sh): follow.py --app, which reads the
# sensors, drives, serves the control page on :8100 and talks to the web app. Driving starts DISABLED every time.
#
# Settings: ~/.config/cosmo_robot.env
#   ROBOT_API_TOKEN=...                              the robot token (same as in Vercel)
#   COSMO_FLAGS="--avoid --speed 0.8 --no-video"     optional: follow.py flags (these are the defaults)
#
# ~/motor_cal/STOP stops the robot as always; while it exists this waits instead of starting again.
set -u
cd "$(dirname "$(readlink -f "$0")")" || exit 1
COSMO_FLAGS="--avoid --speed 0.8 --no-video"
ENV_FILE="$HOME/.config/cosmo_robot.env"
# shellcheck source=/dev/null
[ -f "$ENV_FILE" ] && . "$ENV_FILE"

if [ -e "$HOME/motor_cal/STOP" ]; then
    echo "$HOME/motor_cal/STOP exists: waiting for it to be removed before starting"
    while [ -e "$HOME/motor_cal/STOP" ]; do sleep 2; done
fi
echo "starting: nav/follow.py --app $COSMO_FLAGS"
# shellcheck disable=SC2086
exec .venv/bin/python -u nav/follow.py --app $COSMO_FLAGS
