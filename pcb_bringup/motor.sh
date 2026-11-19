#!/bin/bash
# status | watch [sec] | m1 [ticks] | m2 [ticks] | both [ticks]    (1 tick = 0.25 % duty; default 60 = 15 %; firmware cap 120 = 30 %)
cd "$(dirname "$0")"
c=${1:-status}; n=${2:-}
case $c in
  status) T="status";;
  watch) T="status; watch ${n:-10}; status";;
  m1) t=${n:-60}; T="drive $t 0 3; sleep 500; drive -$t 0 3; status";;
  m2) t=${n:-60}; T="drive 0 $t 3; sleep 500; drive 0 -$t 3; status";;
  both) t=${n:-60}; T="drive $t $t 3; sleep 500; drive -$t -$t 3; status";;
  *) sed -n 2p "$0"; exit 2;;
esac
exec timeout 45 openocd -f pi_swd.cfg -f target/stm32f0x.cfg -c "reset_config none" -c init -f motor_test/motor.tcl -c "$T" -c shutdown 2>&1 | grep -vE "^(Open On|Licensed|For bug|\s+http|Info |none sep|shutdown|Warn)"
