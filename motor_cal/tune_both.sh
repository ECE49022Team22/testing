#!/bin/bash
cd ~/motor_cal
for m in 1 2; do
  echo "===== motor $m"
  ~/testing/.venv/bin/python -u ~/pwm-lab5/motor_autotune.py --motor $m --log autotune_m$m.csv
  echo "exit $?"
done
echo "ALL DONE"
