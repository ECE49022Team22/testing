MEMORY { FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 256K }
SECTIONS {
  .text : { KEEP(*(.isr_vector)) *(.text*) *(.rodata*) } > FLASH
  /DISCARD/ : { *(.ARM.*) *(.comment) }
}
