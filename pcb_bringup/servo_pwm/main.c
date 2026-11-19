/* Standard (PWM) hobby servo test on the team PCB, STM32F091RCT6, 8 MHz HSI, no libraries.
 * Signal: PB10 = TIM2_CH3 (AF2) -> U8 SN74LVC1T45 (DIR = PB11 held high: A->B, 3.3 V in, 5 V out) -> R42 100R
 *         -> J17 pin 3. J17 pin 2 is +12 V (VBAT_SERVO): a 5 V servo must NOT be powered from it.
 * 50 Hz frame, pulse width in microseconds from the RAM mailbox (written by the Pi over SWD):
 *   0x20000000 magic 'SPWM', 0x04 pulse_us (Pi; 0 = no pulses, else clamped to 500..2500), 0x08 applied_us,
 *   0x0C uptime ms. No pulses at boot: the servo isn't driven until the Pi writes a pulse width.
 * LEDs: PA5 D8 alive blink, PB12 D9 pulses on. */
#include <stdint.h>
#define REG(a) (*(volatile uint32_t *)(a))
#define RCC_AHBENR  REG(0x40021014u)
#define RCC_APB1ENR REG(0x4002101Cu)
#define GPIOA 0x48000000u
#define GPIOB 0x48000400u
#define MODER(g) REG((g) + 0x00u)
#define BSRR(g)  REG((g) + 0x18u)
#define AFRH(g)  REG((g) + 0x24u)
#define TIM2 0x40000000u
#define T(o) REG(TIM2 + (o))
#define SYST_CSR REG(0xE000E010u)
#define SYST_RVR REG(0xE000E014u)
#define SYST_CVR REG(0xE000E018u)
struct mb { volatile uint32_t magic, pulse_us, applied_us, ms; };
#define MB ((struct mb *)0x20000000u)

void Reset_Handler(void) {
    MB->pulse_us = 0; MB->applied_us = 0; MB->ms = 0;
    RCC_AHBENR |= (1u << 17) | (1u << 18);
    RCC_APB1ENR |= 1u;                                         /* TIM2 */
    (void)RCC_APB1ENR;
    /* U8 direction first: PB11 high = MCU drives the servo line. PB10 low as a plain output until the timer runs. */
    BSRR(GPIOB) = (1u << 11) | ((1u << 10) << 16) | ((1u << 12) << 16);
    BSRR(GPIOA) = (1u << 5) << 16;
    MODER(GPIOB) = (MODER(GPIOB) & ~((3u << 20) | (3u << 22) | (3u << 24))) | (1u << 20) | (1u << 22) | (1u << 24);
    MODER(GPIOA) = (MODER(GPIOA) & ~(3u << 10)) | (1u << 10);
    T(0x28) = 7u;                                              /* PSC: 8 MHz / 8 = 1 MHz, 1 us ticks */
    T(0x2C) = 19999u;                                          /* ARR: 20 ms frame = 50 Hz */
    T(0x3C) = 0u;                                              /* CCR3 = 0: output stays low (no pulses) */
    T(0x1C) = (6u << 4) | (1u << 3);                           /* CCMR2: OC3 PWM mode 1, preload */
    T(0x20) = 1u << 8;                                         /* CCER: CC3E */
    T(0x14) = 1u;                                              /* EGR: UG */
    T(0x00) = (1u << 7) | 1u;                                  /* CR1: ARPE, CEN */
    AFRH(GPIOB) = (AFRH(GPIOB) & ~(0xFu << 8)) | (2u << 8);    /* PB10 = AF2 (TIM2_CH3) */
    MODER(GPIOB) = (MODER(GPIOB) & ~(3u << 20)) | (2u << 20);
    SYST_RVR = 8000u - 1u; SYST_CVR = 0; SYST_CSR = 5u;
    MB->magic = 0x4D575053u;                                   /* "SPWM" */
    uint32_t ms = 0;
    for (;;) {
        while (!(SYST_CSR & (1u << 16))) { }
        ms++; MB->ms = ms;
        uint32_t p = MB->pulse_us;
        if (p != 0) p = p < 500u ? 500u : (p > 2500u ? 2500u : p);
        T(0x3C) = p;                                           /* takes effect at the next 20 ms frame */
        MB->applied_us = p;
        BSRR(GPIOA) = (ms & 1023u) < 80u ? (1u << 5) : ((1u << 5) << 16);
        BSRR(GPIOB) = p ? (1u << 12) : ((1u << 12) << 16);
    }
}
void Default_Handler(void) { T(0x3C) = 0; for (;;) { } }
__attribute__((section(".isr_vector"), used))
const void *const vectors[16] = {
    (void *)0x20008000u, Reset_Handler, Default_Handler, Default_Handler,
    0, 0, 0, 0, 0, 0, 0, Default_Handler, 0, 0, Default_Handler, Default_Handler,
};
