"""Raw serial traffic between the Pi and the microcontroller, like `screen`, but showing both directions.

Every line the microcontroller sends is printed exactly as it arrives ("STM32 ->"), and every line you
type is printed ("Pi    ->") and sent. Telemetry is slowed to 1 line per second so it can be read.

    .venv/bin/python demos/link.py           # type commands yourself (Ctrl-C to quit)
    .venv/bin/python demos/link.py --auto    # a 6 s scripted sequence, then quits (WHEELS OFF THE GROUND):
                                                 # latch position, wheels to 30 rpm, watchdog stop, bad command

Commands to try (the firmware's own list is at the bottom of pwm-lab5 src/main.c):
    d -30 30     both wheels forward at 30 rpm: motor 1 (right wheel) then motor 2 (left wheel). The right motor is
                 mounted mirrored, so its sign is flipped: this is exactly what follow.py's mcu.drive(30, 30) sends.
                 The command watchdog zeroes the targets 400 ms later unless another d arrives
    stop         both targets to 0
    servo open   latch servo; "servo close", or just "servo" for its position
    rate 10      telemetry lines per second (1-50)
    d 4x0 4@0    a corrupted command: refused with ERR
"""
import sys
import threading
import time

import serial

PORT = "/dev/ttyAMA1"                          # the Pi's UART to the Control Board (robot_drive.STM32_PORT)
link = serial.Serial(PORT, 115200, timeout=0.2)
start = time.monotonic()


def show(direction, text):
    print(f"{time.monotonic() - start:7.2f} s   {direction}  {text}", flush=True)


def send(text):
    show("Pi    ->", text)
    link.write((text + "\n").encode())


def print_everything_received():
    while link.is_open:
        try:
            line = link.readline()             # bytes up to and including "\r\n", or b"" after 0.2 s
        except (OSError, serial.SerialException, TypeError):
            return                             # the port was closed on the way out
        if line:
            show("STM32 ->", line.decode(errors="replace").rstrip("\r\n"))


print(f"{PORT} at 115200 baud\n")
threading.Thread(target=print_everything_received, daemon=True).start()
send("rate 1")                                 # 1 telemetry line per second instead of 10

try:
    if "--auto" in sys.argv:
        send("servo")                          # where the latch servo is
        time.sleep(1.5)
        send("rate 5")                         # faster telemetry, to watch the wheels speed up
        for _ in range(8):                     # follow.py sends d 20 times a second; 5 a second here
            send("d -30 30")                   # both wheels forward at 30 rpm, as mcu.drive(30, 30) sends it
            time.sleep(0.2)
        time.sleep(1.2)                        # commands stopped: 400 ms later the watchdog zeroes the targets (WD)
        send("rate 1")
        send("d 4x0 4@0")                      # a corrupted command: refused
        time.sleep(1.5)
    else:
        print("Type a command and press Enter (Ctrl-C to quit).\n")
        for typed in sys.stdin:
            if typed.strip():
                send(typed.strip())
except KeyboardInterrupt:
    pass
finally:
    send("stop")
    send("rate 10")                            # back to the firmware's default
    time.sleep(0.3)
    link.close()