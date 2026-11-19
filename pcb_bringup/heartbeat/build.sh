#!/bin/sh
set -e
cd "$(dirname "$0")"
B="$HOME/.platformio/packages/toolchain-gccarmnoneeabi/bin/arm-none-eabi"
"$B-gcc" -mcpu=cortex-m0 -mthumb -Os -Wall -Wextra -ffreestanding -nostdlib -Wl,-T,link.ld -Wl,--build-id=none -o heartbeat.elf main.c
"$B-size" heartbeat.elf
