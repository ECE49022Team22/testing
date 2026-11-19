/* PCB bring-up heartbeat for the STM32F091RCT6, no libraries.
 * Double pulse once a second on all three LEDs (active high, 681 ohm to GND):
 *   LQFP pin 21 PA5  LED_USER    D8
 *   LQFP pin 33 PB12 LED_PI_LINK D9
 *   LQFP pin 35 PB14 LED_MOTOR   D11
 * Runs on the reset-default 8 MHz HSI. PA13/PA14 (SWD) are left alone. */
#include <stdint.h>
#define REG(a) (*(volatile uint32_t *)(a))
#define RCC_AHBENR   REG(0x40021014u)
#define GPIOA_MODER  REG(0x48000000u)
#define GPIOA_BSRR   REG(0x48000018u)
#define GPIOB_MODER  REG(0x48000400u)
#define GPIOB_BSRR   REG(0x48000418u)
#define SYST_CSR     REG(0xE000E010u)
#define SYST_RVR     REG(0xE000E014u)
#define SYST_CVR     REG(0xE000E018u)
#define PA5  (1u << 5)
#define PB12 (1u << 12)
#define PB14 (1u << 14)

static void delay_ms(uint32_t ms) { while (ms--) while (!(SYST_CSR & (1u << 16))) { } }
static void leds(int on) {
    GPIOA_BSRR = on ? PA5 : PA5 << 16;
    GPIOB_BSRR = on ? (PB12 | PB14) : (PB12 | PB14) << 16;
}
void Reset_Handler(void) {
    RCC_AHBENR |= (1u << 17) | (1u << 18);                     /* GPIOA, GPIOB clocks */
    (void)RCC_AHBENR;
    leds(0);
    GPIOA_MODER = (GPIOA_MODER & ~(3u << 10)) | (1u << 10);
    GPIOB_MODER = (GPIOB_MODER & ~((3u << 24) | (3u << 28))) | (1u << 24) | (1u << 28);
    SYST_RVR = 8000u - 1u; SYST_CVR = 0; SYST_CSR = 5u;        /* 1 ms ticks from the 8 MHz core clock */
    for (;;) {
        leds(1); delay_ms(120); leds(0); delay_ms(120);
        leds(1); delay_ms(120); leds(0); delay_ms(640);
    }
}
void Default_Handler(void) { for (;;) { } }
__attribute__((section(".isr_vector"), used))
const void *const vectors[16] = {
    (void *)0x20008000u, Reset_Handler, Default_Handler, Default_Handler,
    0, 0, 0, 0, 0, 0, 0, Default_Handler, 0, 0, Default_Handler, Default_Handler,
};
