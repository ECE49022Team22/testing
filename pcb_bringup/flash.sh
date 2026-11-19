#!/bin/bash
# Flash the PCB's STM32F091 from the Pi 5 over SWD and start it.  Usage: ./flash.sh [firmware.elf]
# Wiring: pin 34 GND, pin 36 GPIO16 SWDIO, pin 38 GPIO20 SWCLK, pin 40 GPIO21 NRST. The board has its own 3.3 V.
set -e
cd "$(dirname "$0")"
ELF="${1:-heartbeat/heartbeat.elf}"
# The stock reset events try to change the adapter speed, which linuxgpiod can't do: blank them.
# Finish with an option-byte reload (no option bytes change): on a chip that was blank, a pin reset alone
# stays in the ROM bootloader, because the empty-flash check is only redone at power-up or on this reload.
timeout 90 openocd -f pi_swd.cfg -f pi_srst.cfg -f target/stm32f0x.cfg \
  -c "stm32f0x.cpu configure -event reset-start {} -event reset-init {}" \
  -c init -c "reset halt" -c "flash write_image erase $ELF" -c "verify_image $ELF" \
  -c "mww 0x40022004 0x45670123" -c "mww 0x40022004 0xCDEF89AB" \
  -c "mww 0x40022008 0x45670123" -c "mww 0x40022008 0xCDEF89AB" \
  -c "catch {mww 0x40022010 0x2200}" -c "sleep 100" -c shutdown
