"""Payload latch (requirements 11-3, 11-4):  .venv/bin/python demos/latch.py open|close"""
import argparse, time, serial

p = argparse.ArgumentParser(); 

p.add_argument("action", choices=["open", "close"])

action = p.parse_args().action


link = serial.Serial("/dev/ttyAMA1", 115200, timeout=0.5)        # the Pi's UART to the STM32
link.reset_input_buffer()

print(f"Pi    -> servo {action}")
link.write(f"servo {action}\n".encode())

t = time.monotonic()
while time.monotonic() - t < 1.0:                                 # skip telemetry lines, print the reply
    line = link.readline().decode(errors="replace").strip()
    if line.startswith(("OK", "ERR")):
        print(f"STM32 -> {line}"); break
