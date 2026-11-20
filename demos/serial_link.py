"""Serial link between the Pi and the microcontroller (requirements 4-4 and the UART link).

Shows one command and its reply, counts commands and telemetry lines over 5 s, and shows that a
corrupted command is refused. Nothing moves: every command is "drive at 0 rpm".

    .venv/bin/python demos/serial_link.py
"""
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "motor_cal"))
import robot_drive                             # noqa: E402  (talks to the STM32 on the Control Board, UART 115200 baud)

board = robot_drive.Stm32()
while board.row is None:                       # wait for the first telemetry line
    time.sleep(0.05)

print("1) One command and its reply:")
print("   Pi sends:            d 0 0")
print(f"   microcontroller says: {board.command('d 0 0', expect='OK target')}\n")

print("2) Telemetry the microcontroller sends back (latest line):")
g = board.row
print(f"   motor 1 (right wheel): target {g[0]:.1f} rpm, measured {g[1]:.1f} rpm, duty {g[2]:.1f} %, encoder count {g[4]:.0f}")
print(f"   motor 2 (left wheel):  target {g[5]:.1f} rpm, measured {g[6]:.1f} rpm, duty {g[7]:.1f} %, encoder count {g[9]:.0f}")
print(f"   fault flags: '{board.flags.strip() or 'none'}'\n")

print("3) Commands and telemetry over 5 s (Pi sends a command every 50 ms):")
replies_before = board.replies_dropped + len(board.replies)
sent, telemetry_lines, last_t = 0, 0, board.t
start = time.monotonic()
next_send = start
while time.monotonic() - start < 5.0:
    if time.monotonic() >= next_send:
        board.drive(0, 0)
        sent += 1
        next_send += 0.05
    if board.t != last_t:                      # a new telemetry line arrived
        telemetry_lines += 1
        last_t = board.t
    time.sleep(0.002)
time.sleep(0.2)                                # let the last replies arrive
acked = board.replies_dropped + len(board.replies) - replies_before
print(f"   commands sent: {sent} ({sent / 5:.0f} per second), acknowledged: {acked}")
print(f"   telemetry lines received: {telemetry_lines} ({telemetry_lines / 5:.0f} per second)\n")

print("4) A corrupted command:")
print("   Pi sends:            d 4x0 4@0")
print(f"   microcontroller says: {board.command('d 4x0 4@0')}")
g = board.row
print(f"   wheel targets afterwards: {g[0]:.1f} and {g[5]:.1f} rpm (unchanged)")

board.close()
