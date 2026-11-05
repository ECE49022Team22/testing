#!/bin/bash
cd ~/motor_cal
PY=~/testing/.venv/bin/python
echo "===== B: feedforward"; $PY -u turnmap.py --label B_ff --ratios 0.5 0.25 0 -0.25 --set "kf 0.46" "ks 4"
[ -e STOP ] && exit
sleep 2
echo "===== C: feedforward + Kp 0.3"; $PY -u turnmap.py --label C_ff_kp --ratios 0.5 0.25 0 -0.25 --set "kf 0.46" "ks 4" "kp 0.3"
echo ALL DONE
