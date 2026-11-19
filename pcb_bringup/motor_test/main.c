/* PCB motor bring-up, STM32F091RCT6, 8 MHz HSI, no libraries, no UART.
 * The Pi talks to this over SWD through a mailbox at the start of RAM (see motor.sh).
 * SAFE BY DEFAULT: outputs are off at boot; the motors run only while the Pi writes ARM_KEY and keeps changing
 * `seq`. No new seq for 200 ms -> duty ramps to 0 and the arm is cleared. Duty is capped at MAX_TICKS.
 *   Motor 1: PWM PA6 (TIM3_CH1), DIR PB0, encoder PA15/PB3 (TIM2)
 *   Motor 2: PWM PA7 (TIM3_CH2), DIR PB2, encoder PA8/PA9  (TIM1)
 *   LEDs: PA5 D8 alive blink, PB12 D9 armed, PB14 D11 a motor is being driven
 * Duty unit: 1 tick = 0.25 % (20 kHz PWM, 400 ticks per period). */
#include <stdint.h>
#define REG(a) (*(volatile uint32_t *)(a))
#define RCC_AHBENR  REG(0x40021014u)
#define RCC_APB2ENR REG(0x40021018u)
#define RCC_APB1ENR REG(0x4002101Cu)
#define GPIOA 0x48000000u
#define GPIOB 0x48000400u
#define MODER(g) REG((g) + 0x00u)
#define BSRR(g)  REG((g) + 0x18u)
#define AFRL(g)  REG((g) + 0x20u)
#define AFRH(g)  REG((g) + 0x24u)
#define TIM1 0x40012C00u
#define TIM2 0x40000000u
#define TIM3 0x40000400u
#define CR1(t)   REG((t) + 0x00u)
#define SMCR(t)  REG((t) + 0x08u)
#define EGR(t)   REG((t) + 0x14u)
#define CCMR1(t) REG((t) + 0x18u)
#define CCER(t)  REG((t) + 0x20u)
#define CNT(t)   REG((t) + 0x24u)
#define ARR(t)   REG((t) + 0x2Cu)
#define CCR1(t)  REG((t) + 0x34u)
#define CCR2(t)  REG((t) + 0x38u)
#define SYST_CSR REG(0xE000E010u)
#define SYST_RVR REG(0xE000E014u)
#define SYST_CVR REG(0xE000E018u)
#define ARM_KEY   0x41524D21u
#define DIR_KEY   0x44495200u    /* dirforce: key | level, DIR1 test with PWM at exactly 0 */
#define FW_VERSION 3u
#define MAX_TICKS 120            /* 30 % */
#define WATCHDOG_MS 200u
#define SLEW_MS   5u             /* one tick per 5 ms: 0 to 30 % in 0.6 s */

struct mailbox {                 /* at 0x20000000 */
    volatile uint32_t magic;     /* 00 firmware present */
    volatile uint32_t seq;       /* 04 Pi: change it at least every 200 ms */
    volatile int32_t  cmd1;      /* 08 Pi: motor 1 duty, ticks, signed */
    volatile int32_t  cmd2;      /* 0C Pi: motor 2 */
    volatile uint32_t arm;       /* 10 Pi: ARM_KEY to allow motion */
    volatile uint32_t ms;        /* 14 uptime */
    volatile int32_t  enc1;      /* 18 counts */
    volatile int32_t  enc2;      /* 1C */
    volatile int32_t  out1;      /* 20 duty being applied */
    volatile int32_t  out2;      /* 24 */
    volatile uint32_t trips;     /* 28 watchdog stops */
    volatile uint32_t inputs;    /* 2C bit0 PA15, 1 PB3, 2 PA8, 3 PA9 (raw encoder levels) */
    volatile uint32_t dirforce;  /* 30 Pi: DIR_KEY | level; refused while armed or a motor is being driven */
    volatile uint32_t version;   /* 34 */
    volatile uint32_t edges[4];  /* 38 level changes seen at 1 kHz: A1, B1, A2, B2 */
    volatile uint32_t both[2];   /* 48 samples where A and B changed together: motor 1, motor 2 */
};
#define MB ((struct mailbox *)0x20000000u)

static int32_t clamp(int32_t v) { return v > MAX_TICKS ? MAX_TICKS : v < -MAX_TICKS ? -MAX_TICKS : v; }
static int32_t slew(int32_t out, int32_t target) {       /* passes through 0 before changing direction */
    if (out > 0 && target <= 0) return out - 1;
    if (out < 0 && target >= 0) return out + 1;
    return out < target ? out + 1 : out > target ? out - 1 : out;
}
static void led(uint32_t g, uint32_t bit, int on) { BSRR(g) = on ? bit : bit << 16; }
static void encoder(uint32_t t, uint32_t arr) {
    ARR(t) = arr;
    CCMR1(t) = 0x3131u;          /* TI1/TI2 inputs, 1 us filter */
    CCER(t) = 1u << 1;           /* invert TI1: same sign as the Nucleo firmware (MOTOR_ENC_INVERT 1) */
    SMCR(t) = 3u;                /* quadrature, x4 */
    CNT(t) = 0;
    CR1(t) = 1u;
}
void Reset_Handler(void) {
    MB->cmd1 = 0; MB->cmd2 = 0; MB->arm = 0; MB->seq = 0; MB->ms = 0; MB->enc1 = 0; MB->enc2 = 0;
    MB->out1 = 0; MB->out2 = 0; MB->trips = 0; MB->inputs = 0; MB->dirforce = 0; MB->version = FW_VERSION;
    for (int i = 0; i < 4; i++) MB->edges[i] = 0;
    MB->both[0] = 0; MB->both[1] = 0;
    RCC_AHBENR |= (1u << 17) | (1u << 18);
    RCC_APB1ENR |= 3u;           /* TIM2, TIM3 */
    RCC_APB2ENR |= 1u << 11;     /* TIM1 */
    (void)RCC_APB2ENR;

    /* outputs low first: PWM pins as plain low GPIOs until the timer is running at 0 duty */
    BSRR(GPIOA) = ((1u << 5) | (1u << 6) | (1u << 7)) << 16;
    BSRR(GPIOB) = ((1u << 0) | (1u << 2) | (1u << 12) | (1u << 14)) << 16;
    MODER(GPIOA) = (MODER(GPIOA) & ~((3u << 10) | (3u << 12) | (3u << 14))) | (1u << 10) | (1u << 12) | (1u << 14);
    /* PB0/PB2 (DIR) stay inputs until a motor is commanded: on 18 Nov DIR1 was found tied high off-chip, and
     * holding it low into that sinks more than a GPIO should. */
    MODER(GPIOB) = (MODER(GPIOB) & ~((3u << 0) | (3u << 4) | (3u << 24) | (3u << 28)))
                 | (1u << 24) | (1u << 28);

    ARR(TIM3) = 399u; CCR1(TIM3) = 0; CCR2(TIM3) = 0;    /* 8 MHz / 400 = 20 kHz */
    CCMR1(TIM3) = 0x6868u;       /* PWM mode 1, preload */
    CCER(TIM3) = 0x11u;
    EGR(TIM3) = 1u;
    CR1(TIM3) = 0x81u;
    AFRL(GPIOA) = (AFRL(GPIOA) & ~(0xFFu << 24)) | (0x11u << 24);        /* PA6, PA7 = AF1 */
    MODER(GPIOA) = (MODER(GPIOA) & ~((3u << 12) | (3u << 14))) | (2u << 12) | (2u << 14);

    encoder(TIM2, 0xFFFFFFFFu);
    encoder(TIM1, 0xFFFFu);
    AFRH(GPIOA) = (AFRH(GPIOA) & ~(0xFu | (0xFu << 4) | (0xFu << 28))) | 2u | (2u << 4) | (2u << 28);   /* PA8, PA9, PA15 */
    AFRL(GPIOB) = (AFRL(GPIOB) & ~(0xFu << 12)) | (2u << 12);            /* PB3 */
    MODER(GPIOA) = (MODER(GPIOA) & ~((3u << 16) | (3u << 18) | (3u << 30))) | (2u << 16) | (2u << 18) | (2u << 30);
    MODER(GPIOB) = (MODER(GPIOB) & ~(3u << 6)) | (2u << 6);

    SYST_RVR = 8000u - 1u; SYST_CVR = 0; SYST_CSR = 5u;
    MB->magic = 0x4D4F5431u;

    uint32_t ms = 0, last_seq = 0, last_change = 0;
    int32_t out1 = 0, out2 = 0;
    uint16_t last1 = 0; int32_t enc2 = 0;
    uint32_t prev_in = 0; int have_in = 0;
    for (;;) {
        while (!(SYST_CSR & (1u << 16))) { }
        ms++; MB->ms = ms;
        uint32_t s = MB->seq;
        if (s != last_seq) { last_seq = s; last_change = ms; }
        int armed = MB->arm == ARM_KEY;
        if (armed && ms - last_change > WATCHDOG_MS) { MB->arm = 0; MB->trips = MB->trips + 1; armed = 0; }
        int32_t t1 = armed ? clamp(MB->cmd1) : 0, t2 = armed ? clamp(MB->cmd2) : 0;
        if (!armed) { out1 = slew(out1, 0); out2 = slew(out2, 0); }      /* also ramps down, every tick */
        else if (ms % SLEW_MS == 0) { out1 = slew(out1, t1); out2 = slew(out2, t2); }
        uint32_t f = MB->dirforce;
        int fresh = ms - last_change <= WATCHDOG_MS;
        int dir_test = (f & ~1u) == DIR_KEY && fresh && !armed && out1 == 0 && out2 == 0;
        if (f && !fresh) MB->dirforce = 0;
        BSRR(GPIOB) = dir_test ? ((f & 1u) ? 1u << 0 : 1u << 16)
                               : (out1 < 0 ? 1u << 0 : 1u << 16);        /* DIR1: low = forward */
        BSRR(GPIOB) = out2 < 0 ? 1u << 2 : 1u << 18;                     /* DIR2 */
        uint32_t md = MODER(GPIOB) & ~((3u << 0) | (3u << 4));           /* DIR driven only while in use */
        if (t1 != 0 || out1 != 0 || dir_test) md |= 1u << 0;
        if (t2 != 0 || out2 != 0) md |= 1u << 4;
        MODER(GPIOB) = md;
        CCR1(TIM3) = (uint32_t)(out1 < 0 ? -out1 : out1);
        CCR2(TIM3) = (uint32_t)(out2 < 0 ? -out2 : out2);
        uint16_t c1 = (uint16_t)CNT(TIM1);
        enc2 += (int16_t)(uint16_t)(c1 - last1); last1 = c1;
        MB->enc1 = (int32_t)CNT(TIM2); MB->enc2 = enc2;
        MB->out1 = out1; MB->out2 = out2;
        uint32_t a = REG(GPIOA + 0x10u), b = REG(GPIOB + 0x10u);
        uint32_t in = ((a >> 15) & 1u) | (((b >> 3) & 1u) << 1) | (((a >> 8) & 1u) << 2) | (((a >> 9) & 1u) << 3);
        MB->inputs = in;
        if (have_in) {
            uint32_t x = in ^ prev_in;
            for (int i = 0; i < 4; i++) if (x & (1u << i)) MB->edges[i] = MB->edges[i] + 1;
            if ((x & 3u) == 3u) MB->both[0] = MB->both[0] + 1;
            if ((x & 12u) == 12u) MB->both[1] = MB->both[1] + 1;
        }
        prev_in = in; have_in = 1;
        led(GPIOA, 1u << 5, (ms & 1023u) < 80u);
        led(GPIOB, 1u << 12, armed);
        led(GPIOB, 1u << 14, out1 != 0 || out2 != 0);
    }
}
void Default_Handler(void) {                                             /* fault: outputs off, stay here */
    CCR1(TIM3) = 0; CCR2(TIM3) = 0;
    for (;;) { }
}
__attribute__((section(".isr_vector"), used))
const void *const vectors[16] = {
    (void *)0x20008000u, Reset_Handler, Default_Handler, Default_Handler,
    0, 0, 0, 0, 0, 0, 0, Default_Handler, 0, 0, Default_Handler, Default_Handler,
};
