"""Closed-loop wheel speed control (requirement 4-2).

WHEELS OFF THE GROUND. The Pi sends a wheel speed target; the microcontroller measures the wheel speed
from the encoders and adjusts the motor duty cycle (PI control) until the measured speed matches.

Steps mode (default): steps through several targets, 3 s each, and says how fast each wheel got there.
Hold mode: holds one speed for 30 s. Press a hand on a tyre: the duty goes UP while the speed stays put.

    .venv/bin/python demos/speed_control.py             # steps: 60, 120, 60, 0, -60, 0 rpm
    .venv/bin/python demos/speed_control.py hold 60     # hold 60 rpm for 30 s
"""
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "motor_cal"))
import robot_drive                             # noqa: E402  (talks to the STM32 on the Control Board)

if len(sys.argv) > 1 and sys.argv[1] == "hold":
    TARGETS = [float(sys.argv[2]) if len(sys.argv) > 2 else 60.0]
    SECONDS_EACH = 30.0
else:
    TARGETS = [60, 120, 60, 0, -60, 0]
    SECONDS_EACH = 3.0


def close_enough(measured, target):
    """Within 15 % of the target (or 3 rpm of it, for a target of 0)."""
    return abs(measured - target) <= max(0.15 * abs(target), 3.0)


board = robot_drive.Stm32()
while board.row is None:                       # wait for the first telemetry line
    time.sleep(0.05)
print("WHEELS OFF THE GROUND. Columns: time, target, measured speed of each wheel, motor duty of each wheel.\n")

try:
    for target in TARGETS:
        print(f"--- new target: {target:+.0f} rpm on both wheels ---")
        step_start = time.monotonic()
        last_print = -1.0                               # print the first line at once
        reached_after = None

        while time.monotonic() - step_start < SECONDS_EACH:
            board.drive(target, target)                     # resend every 50 ms (the board stops if commands stop)
            t = time.monotonic() - step_start

            (left_rpm, right_rpm), _ = board.wheels()
            left_rpm, right_rpm = left_rpm + 0.0, right_rpm + 0.0         # + 0.0 turns -0.0 into 0.0
            left_duty = board.row[7] * robot_drive.LEFT_SIGN + 0.0     # % duty, from the board's telemetry
            right_duty = board.row[2] * robot_drive.RIGHT_SIGN + 0.0

            if reached_after is None and close_enough(left_rpm, target) and close_enough(right_rpm, target):
                reached_after = t
            if t - last_print >= 0.25:
                print(f"{t:4.1f} s   target {target:+5.0f}   left {left_rpm:+6.1f}   right {right_rpm:+6.1f} rpm   "
                      f"duty left {left_duty:+5.1f} %   right {right_duty:+5.1f} %")
                last_print = t
            time.sleep(0.05)

        if reached_after is None:
            print(f"    -> did not get within 15 % of {target:+.0f} rpm\n")
        else:
            print(f"    -> both wheels within 15 % of {target:+.0f} rpm after {reached_after:.2f} s\n")
except KeyboardInterrupt:
    print()
finally:
    board.close()                              # sends "stop"
