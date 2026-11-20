"""Payload latch (requirements 11-3 and 11-4).

The Pi tells the microcontroller to open the latch, then to close it. The microcontroller drives the
latch servo with a PWM signal (moving it slowly, so the supply doesn't dip) and reports the servo
position back over the serial link.

    .venv/bin/python demos/latch.py
"""
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "motor_cal"))
import robot_drive                             # noqa: E402  (talks to the STM32 on the Control Board)

board = robot_drive.Stm32()
time.sleep(0.5)

try:
    for action, done in (("open", "open (unlocked)"), ("close", "closed (locked)")):
        print(f"Pi sends: servo {action}")
        reply = board.servo(action)             # {"cur": pulse now in us, "target": pulse it is moving to}
        if reply is None:
            print("   no reply from the microcontroller")
            break
        while reply["cur"] != reply["target"]:
            print(f"   servo pulse {reply['cur']} us, moving to {reply['target']} us")
            time.sleep(0.5)
            reply = board.servo("") or reply    # "servo" with no argument = report the position
        print(f"   latch {done}: microcontroller reports {reply['cur']} us\n")
        time.sleep(2.0)
finally:
    board.close()
