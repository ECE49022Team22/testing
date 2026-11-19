#!/bin/bash
# Read the STM32's state without halting it. Run from this folder (~/testing/pcb_bringup, also reachable as ~/pcb_bringup).
exec timeout 15 openocd -f pi_swd.cfg -f target/stm32f0x.cfg -c "reset_config none" -c init -c "echo SYSCFG_CFGR1_MEMMODE" -c "mdw 0x40010000" -c "echo MODER_A_B" -c "mdw 0x48000000" -c "mdw 0x48000400" -c "echo ODR_A_B" -c "mdw 0x48000014" -c "mdw 0x48000414" -c "sleep 120" -c "mdw 0x48000014" -c "mdw 0x48000414" -c "sleep 170" -c "mdw 0x48000014" -c "mdw 0x48000414" -c shutdown 2>&1
