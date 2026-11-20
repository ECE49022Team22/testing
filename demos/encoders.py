"""Wheel encoders (requirement 4-1).

Turn a drive wheel by hand, forward and backward. The microcontroller counts encoder edges and the
script shows the count and the number of wheel turns for each wheel. Nothing is driven.

    .venv/bin/python demos/encoders.py        # Ctrl-C to stop
"""
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "motor_cal"))
import robot_drive                             # noqa: E402  (talks to the STM32 on the Control Board)

COUNTS_PER_TURN = 751.8                        # 7 pulses x 4 edges x 26.85:1 gearbox = counts per wheel turn

board = robot_drive.Stm32()
while board.row is None:                       # wait for the first telemetry line
    time.sleep(0.05)

(_, _), (left_start, right_start) = board.wheels()
print("Turn a wheel by hand (forward = positive). Ctrl-C to stop.\n")

try:
    while True:
        (left_rpm, right_rpm), (left_count, right_count) = board.wheels()
        left = left_count - left_start
        right = right_count - right_start
        print(f"\rleft wheel: {left:+7.0f} counts = {left / COUNTS_PER_TURN:+6.2f} turns ({left_rpm + 0.0:+5.1f} rpm)    "
              f"right wheel: {right:+7.0f} counts = {right / COUNTS_PER_TURN:+6.2f} turns ({right_rpm + 0.0:+5.1f} rpm)",
              end="", flush=True)
        time.sleep(0.1)
except KeyboardInterrupt:
    print()
finally:
    board.close()
