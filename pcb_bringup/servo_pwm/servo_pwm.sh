#!/bin/bash
# Standard (PWM) latch servo on the team PCB, driven by servo_pwm firmware over SWD from the Pi.
#   servo_pwm.sh closed | open      slow move to a saved position (positions.json)
#   servo_pwm.sh goto <name>        any saved position
#   servo_pwm.sh us <microseconds>  slow move to a pulse width (clamped 1000..2100)
#   servo_pwm.sh status             current pulse width
#   servo_pwm.sh off                stop pulses (servo stays put, unpowered hold)
# Moves ramp 1 us every 30 ms (~0.1 deg per us, so 30 deg takes ~9 s): slow moves avoid supply sag/jerks.
cd "$(dirname "$0")/.."
ocd() { pgrep -x openocd >/dev/null && { echo "ERROR: OpenOCD already running"; exit 1; }
        timeout 60 openocd -f pi_swd.cfg -f target/stm32f0x.cfg -c "reset_config none" -c init -c "$1" -c shutdown 2>&1 | grep -E "^(OK|ERROR|now)"; }
CHECK='if {[read_memory 0x20000000 32 1] != 0x4D575053} { echo "ERROR: servo_pwm firmware not running (flash servo_pwm/servo_pwm.elf)"; shutdown; return }'
move() { t=$1; [ "$t" -lt 1000 ] && t=1000; [ "$t" -gt 2100 ] && t=2100
  ocd "$CHECK; set cur [expr {[read_memory 0x20000008 32 1]+0}]; if {\$cur == 0} { set cur $t }; set s [expr {$t > \$cur ? 1 : -1}]; for {set u \$cur} {\$s > 0 ? \$u <= $t : \$u >= $t} {incr u \$s} { mww 0x20000004 \$u; sleep 30 }; mww 0x20000004 $t; sleep 100; echo \"OK moved \$cur -> [expr {[read_memory 0x20000008 32 1]+0}] us\""; }
pos() { python3 -c "import json,sys; print(json.load(open('servo_pwm/positions.json'))[sys.argv[1]])" "$1" 2>/dev/null; }
case "$1" in
  closed|open) move "$(pos "$1")" ;;
  goto) t=$(pos "$2"); [ -n "$t" ] || { echo "ERROR: no position '$2'"; exit 1; }; move "$t" ;;
  us) move "$2" ;;
  status) ocd "$CHECK; echo \"now [expr {[read_memory 0x20000008 32 1]+0}] us (0 = no pulses)\"" ;;
  off) ocd "$CHECK; mww 0x20000004 0; sleep 50; echo \"OK pulses off\"" ;;
  *) sed -n 2,8p "$0"; exit 2 ;;
esac
