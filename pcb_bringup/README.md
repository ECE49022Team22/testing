# Team PCB bring-up from the Raspberry Pi (18–19 Nov 2026)

Tools and test firmware used to bring up the STM32F091RCT6 on the team PCB (`ECE49022Team22/delivery-robot-pcb`)
with no ST-LINK and no USB serial adapter: the Pi programs, resets and inspects the STM32 over SWD from its own GPIO,
and talks to the motor firmware on UART1. Wiring is in `../WIRING.md` (**Team PCB** section).
This folder is also reachable as `~/pcb_bringup` (a link).

## Connections used
| Pi pin | Function | PCB |
|---|---|---|
| 36 (GPIO16) | SWDIO | J1 pin 4 |
| 38 (GPIO20) | SWCLK | J1 pin 2 |
| 40 (GPIO21) | NRST, open-drain | J1 pin 5 |
| 34 | GND | J1 pin 3 |
| 1 | 3V3, powers the STM32 (PCB LDO not fitted) | J1 pin 1 |
| 27 / 28 / 30 | UART1 TX / RX / GND, `/dev/ttyAMA1` | J13 pins 1 / 2 / 3 |

## Files
| File | What |
|---|---|
| `pi_swd.cfg` | OpenOCD: `linuxgpiod` SWD on GPIO16/20 (chip 0) |
| `pi_srst.cfg` | adds NRST on GPIO21. This OpenOCD rejects `-open-drain` on `adapter gpio srst`; open-drain comes from `reset_config ... srst_open_drain` |
| `flash.sh [file.elf]` | flash + verify, then an option-byte reload (no option bytes change): a chip that was blank otherwise stays in the ROM bootloader after a pin reset, because the empty-flash check only reruns at power-up or on that reload. Default: the heartbeat |
| `state.sh` | read GPIO / SYSCFG state without halting |
| `heartbeat/` | first test: double-pulse on LEDs D8 (PA5), D9 (PB12), D11 (PB14) |
| `motor_test/` | motor/encoder test firmware with a RAM mailbox at 0x20000000, driven over SWD (no UART needed). Off at boot; runs only while the Pi keeps writing a fresh `seq` (200 ms watchdog); duty capped at 30 % |
| `motor.sh status \| watch \| m1 \| m2 \| both` | drives `motor_test` (15 % default, forward 3 s, reverse 3 s) |
| `motor_test/*.tcl` | `motor.tcl` (status, drive, edge counts, DIR tests), `precheck.tcl` (PWM lines held low before any flash), `pull.tcl` / `encpull.tcl` / `pulltoggle.tcl` (weak-pull tests that find shorts and open joints) |
| `servo_pwm/` | standard (PWM) latch servo test firmware: PB10 as TIM2_CH3 through U8, pulse width from an SWD mailbox, no pulses at boot; `servo_pwm.sh open|closed|us <n>|status|off` (ramped moves) and `positions.json` (closed 1700 µs, open 2050 µs). Superseded by the latch support in the motor firmware (`servo …` over the UART), which uses TIM15 because TIM2 is encoder 1 there |
| `servo_probe.tcl`, `servo_move.tcl` | read-only servo probe and single moves for the `servo` firmware (`~/servo`, branch `pcb-usart3`); day-to-day use is `~/servo/tools/pi/servo.sh` |

Built `.elf` files and logs are not committed (`.gitignore`): `motor_test/build.sh`, `heartbeat/build.sh`, the motor
firmware (`~/pwm-lab5`, branch `pcb-usart2`, `pio run`) and the servo firmware (`~/servo`, `make`) rebuild them.

## What was found and fixed
1. **SWD works over three wires.** IDCODE 0x10006442 (STM32F091, 256 KB), no read protection. NRST verified with the
   reset-cause flag (PINRSTF).
2. **DIR1 held at 3.3 V on the board:** a solder bridge on U6 (pins 5–6) tied a motor 1 line to 3.3 V, so motor 1 only
   ran one way (and PB0 was sinking ~25 mA when driven low). Removed; DIR1 and DIR2 now follow weak pulls with their
   wires off, and both motors reverse. The test firmware now leaves DIR pins undriven unless a motor is commanded.
3. **Encoders counting ~0 while spinning:** each encoder had one dead channel (motor 1 A, motor 2 B), and a quadrature
   counter with one channel cancels to ~0. The weak-pull test showed PA15 and PA9 weren't driven by U9/U10 →
   **open joints at STM32 pin 50 and U10 pin 4**, reflowed. Motor 2's encoder then had no power: its cable put the
   encoder's 5 V on J15 pin 2 (GND), fixed; and an extra encoder-2-ground-to-battery wire created a ground loop,
   removed. Both encoders then gave clean quadrature (≈ 25 RPM at 15 % duty, correct sign flip, no crosstalk).
4. **Encoder sign** on the PCB is opposite to the Nucleo wiring: `pwm-lab5` `pcb-usart2` turns the TI1 inversion off.
5. **Pi ↔ STM32 UART:** Pi UART1 (pins 27/28) is the only free full UART on the header (UART0 has the GPS and a dead
   TX pin, UART2 the LiDAR, UART3 the IMU's SPI pins, UART4 the RTCM output). `config.txt`: `dtoverlay=uart1-pi5`,
   `force_eeprom_read=0`. The motor firmware's host link moved from USART5 (PC12/PD2) to USART2 (PA2/PA3). Verified:
   commands acknowledged 5/5 in 3 ms, telemetry streaming; open-loop runs ±15 % on both motors read +25/−24 and
   +22/−24 RPM with the right sign.
6. **IMU:** P1 moved from Pi pin 1 (now the STM32's 3.3 V) to pin 31; `imu.py` drives GPIO6 high before reset. The IMU
   is now mounted upside down; `imu.py` (`MOUNT_UPSIDE_DOWN`) converts readings to the robot frame.
7. **Servo (Hiwonder HTS-30HS, ID 1):** on PB10 (USART3 half-duplex) through U8 with DIR on PB11; the `servo` repo's
   firmware was ported (its bench wiring used PA9, which is encoder 2 B on the PCB). ID/position/12.6 V/33–38 °C reads
   with no timeouts. Latch positions: **closed = 1000**, **open = 854** (`~/servo/tools/pi/positions.json`).

## Still to do
- Merge the servo driver into the motor firmware (only one firmware runs at a time now).
- A command timeout in the motor firmware (it keeps the last target if the Pi goes quiet) before driving on the ground.
- Point `motor_cal/robot_drive.py` and the motor tools at `/dev/ttyAMA1` (they still default to `/dev/ttyUSB0`).
- First closed-loop speed test on the PCB (open-loop and encoder signs are verified).
- IMU turn-direction check (turn the robot left by hand: heading should increase).
