#!/bin/bash
# Retry the SWD connection (up to ~30 s), then toggle PA15's pull for 120 s.
cd "$(dirname "$0")"
for i in $(seq 1 15); do
  timeout 140 openocd -f pi_swd.cfg -f target/stm32f0x.cfg -c "reset_config none" -c init -f motor_test/pulltoggle.tcl -c "pulltoggle 120" -c shutdown > pulltoggle.log 2>&1
  grep -q FINISHED pulltoggle.log && exit 0
  grep -q "^t=" pulltoggle.log && exit 1
  echo "attempt $i: no SWD connection" >> pulltoggle_attempts.log
  sleep 2
done
