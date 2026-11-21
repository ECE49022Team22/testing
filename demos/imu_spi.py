"""IMU over SPI (requirement 5-2).

Reads the IMU's gyroscope over SPI and prints, twice a second, how many samples arrived, the turn rate,
and the heading change since the start. Turn the robot by hand and watch the heading follow.

    .venv/bin/python demos/imu_spi.py        # runs for 20 s
    .venv/bin/python demos/imu_spi.py 60     # runs for 60 s
"""
import math
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "motor_cal"))
import robot_drive                            
SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0

sensor = robot_drive.Imu()
sensor.start()
time.sleep(0.5)
print("Turn the robot by hand. Twice a second:\n")

start = time.monotonic()
last_print = start
samples = 0
last_sample_time = sensor.t
try:
    while time.monotonic() - start < SECONDS:
        if sensor.t != last_sample_time:       # a new gyro sample arrived
            samples += 1
            last_sample_time = sensor.t
        now = time.monotonic()
        if now - last_print >= 0.5:
            print(f"{samples / (now - last_print):5.0f} samples/s   turn rate {math.degrees(sensor.gz):+7.1f} deg/s   "
                  f"heading change {math.degrees(sensor.yaw):+7.1f} deg")
            samples = 0
            last_print = now
        time.sleep(0.002)
except KeyboardInterrupt:
    pass
finally:
    sensor.close()
