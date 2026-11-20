"""Command timeout on the microcontroller (requirement 4-3).

WHEELS OFF THE GROUND. The Pi drives both wheels at 60 rpm for 3 s, sending a command every 50 ms,
then stops sending (as if the Pi program had crashed). The microcontroller notices that commands have
stopped and sets both wheel targets to 0 by itself. Needs the firmware with the command watchdog
(pwm-lab5 commit 666f4a9, 400 ms).

    .venv/bin/python demos/command_timeout.py
"""
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "motor_cal"))
import robot_drive                             # noqa: E402  (talks to the STM32 on the Control Board)

board = robot_drive.Stm32()
while board.row is None:                       # wait for the first telemetry line
    time.sleep(0.05)
print("WHEELS OFF THE GROUND.\n")

print("1) The Pi sends 'drive at 60 rpm' every 50 ms for 3 s ...")
start = time.monotonic()
while time.monotonic() - start < 3.0:
    board.drive(60, 60)
    time.sleep(0.05)

print("2) The Pi stops sending. What the microcontroller reports:\n")
last_command = time.monotonic()
targets_zero_after = None
try:
    while time.monotonic() - last_command < 2.0:
        ms = (time.monotonic() - last_command) * 1000
        left_target = board.row[5] * robot_drive.LEFT_SIGN + 0.0       # + 0.0 turns -0.0 into 0.0
        right_target = board.row[0] * robot_drive.RIGHT_SIGN + 0.0
        (left_rpm, right_rpm), _ = board.wheels()
        left_rpm, right_rpm = left_rpm + 0.0, right_rpm + 0.0
        watchdog = "WATCHDOG TRIPPED" if "WD" in board.flags else ""
        print(f"{ms:5.0f} ms after the last command:  targets {left_target:+4.0f} / {right_target:+4.0f} rpm   "
              f"measured {left_rpm:+6.1f} / {right_rpm:+6.1f} rpm   {watchdog}")
        if targets_zero_after is None and left_target == 0 and right_target == 0:
            targets_zero_after = ms
        time.sleep(0.1)
finally:
    board.close()                              # sends "stop"

if targets_zero_after is None:
    print("\nThe targets did NOT go to 0: this firmware has no command timeout.")
else:
    print(f"\nThe microcontroller stopped driving the motors about {targets_zero_after:.0f} ms after the last command.")
