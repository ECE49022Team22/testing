# Robot wiring and pinout (as of 16 Nov 2026)

Everything connected to the Raspberry Pi 5 and the STM32 motor controller, for rebuilding the robot as it ran on
16 Nov (MSEE / WALC / Lambertus routes). Sources: the Pi's live state (`/boot/firmware/config.txt`, `pinctrl`,
`i2cdetect`, `lsusb`, `/dev/serial/by-id`) checked on 16 Nov, plus the drivers' own wiring notes (`imu.py`,
`lidar.py`, `GEM1305_CONFIG.md`, `CELLULAR.md`, `pwm-lab5/PWM_PINOUT.md`, `pwm-lab5/MOTOR_PID.md`).

**Status key:** ✅ checked on the running Pi (pin function / device answering) · 📄 from the docs or code only
(the Pi can't see that wire) · ❓ not documented anywhere; check by eye and fill in.

## Overview

```
                         ┌──────────────────────── Raspberry Pi 5 ────────────────────────┐
 STL-27L LiDAR ──TX──────► pin 29  UART2 RX   /dev/ttyAMA2   921600                         │
 GEM1305 GPS  ──TX──────► pin 10  UART0 RX   /dev/ttyAMA0   230400  (NMEA)                 │
              ◄─RX─────── pin 32  UART4 TX   /dev/ttyAMA4   230400  (RTCM corrections)     │
              ──PPS─────► pin 12  GPIO18     /dev/pps0                                     │
 BNO085 IMU   ◄═SPI═════► pins 19/21/23 + CS 24, INT 22, RST 18, WAKE 16   /dev/spidev0.0   │
 Notecarrier X (Notecard) ◄═I2C═► pins 3/5   /dev/i2c-1 @ 0x17  (cellular)                  │
 USB camera (global shutter) ═USB═► /dev/video0                                            │
 FTDI FT232R  ═USB═► /dev/ttyUSB0 ──────┐                                                   │
 ST-LINK/V2   ═USB═► (programming) ──┐  │                                                   │
                         └───────────┼──┼───────────────────────────────────────────────────┘
                                     │  │ 115200 8N1
                         ┌───────────▼──▼──── STM32F091 (Nucleo-F091RC) ──────────┐
                         │ SWD          PD2 RX ◄─ FTDI TX     PC12 TX ─► FTDI RX   │
                         │ PA6 PWM1, PB0 DIR1 ─► MDD20A ch1 ─► motor 1 (RIGHT wheel)│
                         │ PA7 PWM2, PB2 DIR2 ─► MDD20A ch2 ─► motor 2 (LEFT wheel) │
                         │ PA15/PB3 ◄─ encoder 1     PA8/PA9 ◄─ encoder 2           │
                         └──────────────────────────────────────────────────────────┘
                           MDD20A VB+/VB− ◄── 12 V battery
```

## Raspberry Pi 5: 40-pin header

Pin 1 is the corner pin nearest the SD card end, on the inside row (square pad). Odd pins are the inside row,
even pins the outside (board-edge) row.

| pin | function | connected to | | pin | function | connected to |
|---:|---|---|---|---:|---|---|
| 1 | 3V3 | ❓ | | 2 | **5V** | **LiDAR 5V** 📄 |
| 3 | **GPIO2 SDA1** | **Notecarrier SDA** ✅ | | 4 | 5V | ❓ (GPS 5V? see GPS) |
| 5 | **GPIO3 SCL1** | **Notecarrier SCL** ✅ | | 6 | **GND** | **LiDAR GND** 📄 |
| 7 | GPIO4 TXD2 | claimed by UART2, **unused** ✅ | | 8 | GPIO14 TXD0 | **dead pin, don't use** (never drives) |
| 9 | GND | ❓ | | 10 | **GPIO15 RXD0** | **GPS TX** (NMEA in) ✅ |
| 11 | GPIO17 | free | | 12 | **GPIO18** | **GPS PPS** ✅ |
| 13 | GPIO27 | free | | 14 | GND | ❓ |
| 15 | GPIO22 | free | | 16 | **GPIO23** out | **IMU P0 (WAKE)** ✅ |
| 17 | **3V3** | **IMU VIN** 📄 | | 18 | **GPIO24** out | **IMU RST** ✅ |
| 19 | **GPIO10 MOSI** | **IMU DI** ✅ | | 20 | **GND** | **IMU GND** 📄 |
| 21 | **GPIO9 MISO** | **IMU SDA (SPI data out)** ✅ | | 22 | **GPIO25** in | **IMU INT** ✅ |
| 23 | **GPIO11 SCLK** | **IMU SCL (SPI clock)** ✅ | | 24 | **GPIO8** out | **IMU CS** (plain GPIO) ✅ |
| 25 | GND | ❓ | | 26 | GPIO7 | free |
| 27 | ID_SD | reserved | | 28 | ID_SC | reserved |
| 29 | **GPIO5 RXD2** | **LiDAR TX** ✅ | | 30 | GND | ❓ |
| 31 | GPIO6 | free | | 32 | **GPIO12 TXD4** | **GPS RX** (RTCM out) ✅ |
| 33 | GPIO13 RXD4 | claimed by UART4, **unused** ✅ | | 34 | GND | ❓ |
| 35 | GPIO19 | free | | 36 | GPIO16 | free |
| 37 | GPIO26 | free | | 38 | GPIO20 | free |
| 39 | GND | ❓ | | 40 | GPIO21 | free |

"✅" on a signal pin means the Pi has that pin in the right function and the device on it answered on 16 Nov
(LiDAR 9.9 scans/s, GPS 52 lines/s + PPS, IMU 100 Hz, Notecard at 0x17); it can't prove which ground pin each
device uses. Grounds (❓) and the GPS / Notecarrier power wires need checking by eye.

## Each device

### LiDAR: LDROBOT STL-27L (`motor_cal/lidar.py`)
| LiDAR | Pi | |
|---|---|---|
| 5V | pin 2 | 📄 |
| GND | pin 6 | 📄 |
| TX | pin 29 (GPIO5, UART2 RXD) → `/dev/ttyAMA2`, 921600 baud | ✅ |
| RX | not connected (the LiDAR needs no commands) | |

Mounted with its 0° mark **271.5°** from the robot's front (`FRONT_DEG` in `nav/local_nav.py`). Needs
`dtoverlay=uart2-pi5`.

### GPS: Allystar GEM1305, RTK (`ntrip_rtk.py`, `gem1305_cfg.py`, `GEM1305_CONFIG.md`)
6-pin 1.25 mm connector, pin 1 to 6: **GND / NC / PPS / RX / TX / 5V**.

| GEM1305 | Pi | Linux | |
|---|---|---|---|
| TX | pin 10 (GPIO15, UART0 RXD) | `/dev/ttyAMA0`, 230400 | ✅ NMEA in |
| RX | **pin 32** (GPIO12, UART4 TXD) | `/dev/ttyAMA4`, 230400 | ✅ RTCM corrections out |
| PPS | pin 12 (GPIO18) | `/dev/pps0` (`pps@12`) | ✅ |
| 5V | ❓ pin 4? | | ❓ |
| GND | ❓ | | ❓ |

**Pin 8 (UART0 TX) is dead on this Pi**: it never leaves 3.3 V (found 5 Nov). That's why corrections go out on
UART4. The RX wire must go to the RX of the **same** GEM1305 connector whose TX goes to pin 10. Antenna: the GPS
antenna on its coax ❓ (where it's mounted). Needs `dtparam=uart0=on`, `dtoverlay=uart4-pi5`,
`dtoverlay=pps-gpio,gpiopin=18`. NTRIP login is in `~/.config/ntrip.json` (not in git).

### IMU: BNO085 over SPI (`imu.py`)
| BNO085 | Pi | |
|---|---|---|
| VIN | pin 17 (3V3) | 📄 |
| GND | pin 20 | 📄 |
| SCL (= SPI SCK) | pin 23 (GPIO11) | ✅ |
| SDA (= SPI MISO) | pin 21 (GPIO9) | ✅ |
| DI (= SPI MOSI) | pin 19 (GPIO10) | ✅ |
| CS | pin 24 (GPIO8, driven as a plain GPIO) | ✅ |
| INT | pin 22 (GPIO25) | ✅ |
| RST | pin 18 (GPIO24) | ✅ |
| P0 (WAKE) | pin 16 (GPIO23, held high through reset) | ✅ |

The breakout's PS0/PS1 straps must select **SPI** ❓ (solder jumpers on the board). Needs `dtoverlay=spi0-0cs`
(SPI0 without kernel chip-selects, so GPIO8 is free as a GPIO). `CELLULAR.md` mentions the IMU on I2C at 0x4A:
**that's out of date**. It moved to SPI, and nothing answers at 0x4A now.

### Cellular: Blues Notecard on a Notecarrier X (`cellular_test/`, `CELLULAR.md`)
| Notecarrier | Pi | |
|---|---|---|
| SDA | pin 3 (GPIO2) | ✅ answers at **0x17** on `/dev/i2c-1` |
| SCL | pin 5 (GPIO3) | ✅ |
| GND | a Pi GND pin ❓ | |
| VBAT | **~4.2 V**, not from the Pi's 3.3 V pin (see `CELLULAR.md` power notes) ❓ source | |

I2C runs at **50 kHz** (`dtparam=i2c_arm_baudrate=50000`, for the long wires). Also on the bus: an
**unidentified device at 0x6a** ❓. Auto-starts at boot (`crontab -l`: `cellular_logger.sh start`).

### Camera: USB global-shutter camera
USB (ID `32e4:0234`) → `/dev/video0`, MJPG 640×480 at 30 fps. **Mounted upside down**: the code rotates
frames 180°. Which USB port: ❓ (any).

### STM32 link: FTDI FT232R USB-serial
USB on the Pi (serial `A50285BI`, so `/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A50285BI-if00-port0` →
`/dev/ttyUSB0`) ✅. Serial side, 115200 8N1 📄:

| FTDI | STM32 (Nucleo) |
|---|---|
| RX | PC12 (USART5 TX) |
| TX | PD2 (USART5 RX) |
| GND | Nucleo GND |

### STM32 programmer: ST-LINK/V2
USB (ID `0483:3748`) ✅. Used to flash `pwm-lab5` (PlatformIO). Which board it's wired to (the Nucleo's SWD
header) ❓.

## STM32F091 (Nucleo-F091RC) → motors (`~/pwm-lab5`, branch `mdd20a-pg27`)

| signal | STM32 pin | Nucleo header | to |
|---|---|---|---|
| PWM1 | PA6 (TIM3_CH1, 20 kHz) | D12 | MDD20A PWM1 |
| DIR1 | PB0 (0 = forward) | A3 | MDD20A DIR1 |
| Encoder 1 A (yellow) | PA15 (TIM2_CH1) | CN7-17 | motor 1 encoder |
| Encoder 1 B (green) | PB3 (TIM2_CH2) | D3 | motor 1 encoder |
| PWM2 | PA7 (TIM3_CH2, 20 kHz) | D11 / CN10-15 | MDD20A PWM2 |
| DIR2 | PB2 (0 = forward) | CN10-22 (Morpho only) | MDD20A DIR2 |
| Encoder 2 A | PA8 (TIM1_CH1) | D7 / CN9-8 | motor 2 encoder |
| Encoder 2 B | PA9 (TIM1_CH2) | D8 / CN5-1 | motor 2 encoder |
| Encoder power red / black | 5V / GND | CN6 | both encoders |
| MDD20A signal GND | GND | | MDD20A |

- **Motors:** AndyMark PG27 (26.85:1, ~198 RPM no-load) on Cytron MDD20A channels M1A/M1B and M2A/M2B; the driver's
  VB+/VB− from the **12 V** battery. The MDD20A has **no reverse-polarity protection**.
- **Wheel mapping:** motor 1 = **right** wheel (+ rolls the robot backward, so the code sends it reversed);
  motor 2 = **left** wheel (+ rolls it forward).
- Encoder inputs are 5 V tolerant only with the pull-ups **off** (`MOTOR_ENC_PULLUPS 0`).
- All grounds (Nucleo, MDD20A, encoders, FTDI, Pi) are common.

## Power

| what | from | |
|---|---|---|
| Motors (MDD20A VB+/VB−) | 12 V battery | 📄 |
| Raspberry Pi 5 | USB-C (negotiates 3000 mA) from a separate regulator / supply ❓ | 📄 / ❓ |
| LiDAR, IMU | Pi header (5 V pin 2, 3.3 V pin 17) | 📄 |
| GPS | 5 V ❓ | |
| Notecarrier | ~4.2 V on VBAT ❓ source | |
| Nucleo | USB (ST-LINK) or the 5 V rail ❓ | |

The Pi **browns out under motor load** (`vcgencmd get_throttled` = `0x50000` on 16 Nov) and the STM32 has
reset with it. The STM32 also has **no command watchdog** yet: if the Pi dies, it keeps the last speed target.

## Software side, needed for this wiring

`/boot/firmware/config.txt` (active lines): `dtparam=uart0=on`, `dtoverlay=uart2-pi5`, `dtoverlay=uart4-pi5`,
`dtoverlay=pps-gpio,gpiopin=18`, `dtparam=i2c_arm=on`, `dtparam=i2c_arm_baudrate=50000`, `dtoverlay=spi0-0cs`,
`dtoverlay=nospi10`.

## Quick checks after rewiring

```
ls /dev/ttyAMA0 /dev/ttyAMA2 /dev/ttyAMA4 /dev/ttyUSB0 /dev/spidev0.0 /dev/video0   # all should exist
pinctrl get 2-25          # GPIO2/3 SDA1/SCL1, 4/5 TXD2/RXD2, 9-11 SPI0, 12/13 TXD4/RXD4, 14/15 TXD0/RXD0, 18 input
i2cdetect -y 1            # 17 (Notecard), 6a (unidentified)
cat /sys/class/pps/pps0/assert                         # count goes up once a second (GPS PPS)
.venv/bin/python motor_cal/lidar.py                    # ~10 scans/s, 0 CRC errors
.venv/bin/python imu.py                                # ~100 Hz, accel z ~9.8
```
