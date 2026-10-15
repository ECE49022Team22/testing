/**
  ******************************************************************************
  * @file    main.c
  * @author  Weili An, Niraj Menon
  * @date    Jan 31 2024
  * @brief   ECE 362 Lab 5 Student template
  ******************************************************************************
*/

/*******************************************************************************/

// Fill out your username, otherwise your completion code will have the 
// wrong username!
const char* username = "jyasuumi";

/*******************************************************************************/ 

#include "stm32f0xx.h"
#include <math.h>   // for M_PI
#include <stdio.h>  // snprintf
#include <stdlib.h> // strtod
#include <string.h> // strncmp

void nano_wait(int);

// 16-bits per digit.
// The most significant 8 bits are the digit number.
// The least significant 8 bits are the segments to illuminate.
uint16_t msg[8] = { 0x0000,0x0100,0x0200,0x0300,0x0400,0x0500,0x0600,0x0700 };
extern const char font[];
// Print an 8-character string on the 8 digits
void print(const char str[]);
// Print a floating-point value.
void printfloat(float f);

void autotest(void);

//============================================================================
// PWM Lab Functions
//============================================================================
void setup_tim3(void) {
    RCC->APB1ENR |= RCC_APB1ENR_TIM3EN; // enable TIM3 clock
    RCC->AHBENR |= RCC_AHBENR_GPIOCEN; // enable GPIOC clock

    GPIOC->MODER &= ~0xFF000;
    GPIOC->MODER |=  0xAA000; // configure PC6-9 as alternate function (10) 

    // configure GPIO to select AF0 (0x0)
    GPIOC->AFR[0] &= ~GPIO_AFRL_AFRL6;
    GPIOC->AFR[0] &= ~GPIO_AFRL_AFRL7;
    GPIOC->AFR[1] &= ~GPIO_AFRH_AFRH0;
    GPIOC->AFR[1] &= ~GPIO_AFRH_AFRH1;


    TIM3->PSC = 48000 - 1; // 48 MHZ to 1KHz
    TIM3->ARR = 1000 - 1; // 1KHz to 1Hz

    // counting direction: 0=up, 1=down
    TIM3->CR1 &= ~TIM_CR1_DIR;

    // configure TIM3 for PWM mode 1 (110) for all 4 channels
    TIM3->CCMR1 &=  ~TIM_CCMR1_OC1M_0; 
    TIM3->CCMR1 |= TIM_CCMR1_OC1M_1 | TIM_CCMR1_OC1M_2;

    TIM3->CCMR1 &=  ~TIM_CCMR1_OC2M_0; 
    TIM3->CCMR1 |= TIM_CCMR1_OC2M_1 | TIM_CCMR1_OC2M_2;

    TIM3->CCMR2 &= ~TIM_CCMR2_OC3M_0;
    TIM3->CCMR2 |= TIM_CCMR2_OC3M_1 | TIM_CCMR2_OC3M_2;

    TIM3->CCMR2 &= ~TIM_CCMR2_OC4M_0;
    TIM3->CCMR2 |= TIM_CCMR2_OC4M_1 | TIM_CCMR2_OC4M_2;

    // CCR Value from 0 to 1000
    TIM3->CCR1 = 800;
    TIM3->CCR2 = 600;
    TIM3->CCR3 = 400;
    TIM3->CCR4 = 200;

    // enable the four channel outputs
    TIM3->CCER |= TIM_CCER_CC1E | TIM_CCER_CC2E | TIM_CCER_CC3E | TIM_CCER_CC4E;

    // enable tim3
    TIM3->CR1 |= TIM_CR1_CEN;

}

//============================================================================
// UART-controlled PWM duty cycle
// The host sends a duty cycle in percent as a text line (e.g. "40\n") over
// USART5 (PC12 = TX, PD2 = RX, 115200 8N1) and the STM32 sets the duty cycle
// of PC9 (TIM3 CH4). Names are prefixed to avoid clashing with autotest.o.
//============================================================================
#define CMD_MAX 24

// USART5 runs on DMA instead of polling RDR/TDR. Not on interrupts: autotest.o already defines
// USART3_8_IRQHandler (shared by USART3-8). DMA1 ch1 = RX (circular), ch2 = TX (one shot per buffer).
#define U5_RX_SIZE 128
#define U5_TX_SIZE 256
static volatile char u5_rx[U5_RX_SIZE];
static uint32_t u5_rx_tail;
static char u5_tx[2][U5_TX_SIZE];        // double buffer: one being sent, one being filled
static int u5_tx_cur;                    // index of the buffer being filled
static int u5_tx_fill;                   // bytes queued in it
volatile uint32_t u5_overruns;           // ORE events, reported in telemetry if nonzero

static void uart5_dma_init(void) {
    RCC->AHBENR |= RCC_AHBENR_DMA1EN;
    DMA1->CSELR = (DMA1->CSELR & ~(DMA_CSELR_C1S | DMA_CSELR_C2S))
                  | DMA1_CSELR_CH1_USART5_RX | DMA1_CSELR_CH2_USART5_TX;

    DMA1_Channel1->CCR = 0;
    DMA1_Channel1->CPAR = (uint32_t)&USART5->RDR;
    DMA1_Channel1->CMAR = (uint32_t)u5_rx;
    DMA1_Channel1->CNDTR = U5_RX_SIZE;
    DMA1_Channel1->CCR = DMA_CCR_MINC | DMA_CCR_CIRC | DMA_CCR_PL_1;   // 8-bit, periph -> mem
    DMA1_Channel1->CCR |= DMA_CCR_EN;

    DMA1_Channel2->CCR = 0;
    DMA1_Channel2->CPAR = (uint32_t)&USART5->TDR;
    DMA1_Channel2->CCR = DMA_CCR_MINC | DMA_CCR_DIR | DMA_CCR_PL_0;   // 8-bit, mem -> periph
}

void uart5_init(void) {
    RCC->AHBENR |= RCC_AHBENR_GPIOCEN | RCC_AHBENR_GPIODEN;

    // PC12 = USART5_TX, PD2 = USART5_RX, both alternate function 2
    GPIOC->MODER &= ~GPIO_MODER_MODER12;
    GPIOC->MODER |= GPIO_MODER_MODER12_1;
    GPIOD->MODER &= ~GPIO_MODER_MODER2;
    GPIOD->MODER |= GPIO_MODER_MODER2_1;
    GPIOC->AFR[1] &= ~GPIO_AFRH_AFRH4;
    GPIOC->AFR[1] |= 0x2 << 16;
    GPIOD->AFR[0] &= ~GPIO_AFRL_AFRL2;
    GPIOD->AFR[0] |= 0x2 << 8;

    RCC->APB1ENR |= RCC_APB1ENR_USART5EN;
    USART5->CR1 &= ~USART_CR1_UE;
    USART5->CR1 &= ~(USART_CR1_M0 | USART_CR1_M1 | USART_CR1_PCE | USART_CR1_OVER8);
    USART5->CR2 &= ~USART_CR2_STOP;
    USART5->BRR = 0x1A1; // 48 MHz / 115200 = 417
    USART5->CR3 |= USART_CR3_DMAR | USART_CR3_DMAT;
    USART5->CR1 |= USART_CR1_TE | USART_CR1_RE;
    USART5->CR1 |= USART_CR1_UE;
    while ((USART5->ISR & (USART_ISR_TEACK | USART_ISR_REACK)) != (USART_ISR_TEACK | USART_ISR_REACK))
        ;
    uart5_dma_init();
}

// Bytes received but not yet read. RX runs in circular DMA mode, so the hardware stores every byte
// even while the main loop is busy (e.g. formatting telemetry); before, a byte that arrived during
// a blocking print overran RDR and was lost, dropping that command.
// Returns 1 and stores the next byte in *c, or 0 if nothing is waiting.
static int uart5_getc(char *c) {
    if (USART5->ISR & USART_ISR_ORE) {   // can't happen with DMA keeping up; counted in case it does
        USART5->ICR = USART_ICR_ORECF;
        u5_overruns++;
    }
    uint32_t head = U5_RX_SIZE - DMA1_Channel1->CNDTR;
    if (head >= U5_RX_SIZE)
        head = 0;
    if (u5_rx_tail == head)
        return 0;
    *c = u5_rx[u5_rx_tail];
    u5_rx_tail = (u5_rx_tail + 1) % U5_RX_SIZE;
    return 1;
}

// Start sending the buffer being filled if the TX DMA channel is idle. Call often (the main loops
// do); uart5_puts() calls it too.
static void uart5_tx_pump(void) {
    if (u5_tx_fill == 0)
        return;
    if ((DMA1_Channel2->CCR & DMA_CCR_EN) && DMA1_Channel2->CNDTR != 0)
        return;                          // previous buffer still going out
    DMA1_Channel2->CCR &= ~DMA_CCR_EN;
    DMA1_Channel2->CMAR = (uint32_t)u5_tx[u5_tx_cur];
    DMA1_Channel2->CNDTR = u5_tx_fill;
    DMA1_Channel2->CCR |= DMA_CCR_EN;
    u5_tx_cur ^= 1;                      // fill the other buffer while this one is sent
    u5_tx_fill = 0;
}

// Queue one byte; only waits if a whole buffer is queued behind the one being sent.
static void uart5_putc(char c) {
    while (u5_tx_fill >= U5_TX_SIZE)
        uart5_tx_pump();
    u5_tx[u5_tx_cur][u5_tx_fill++] = c;
}

// Queue a string and return without waiting for it to be sent.
static void uart5_puts(const char *s) {
    while (*s)
        uart5_putc(*s++);
    uart5_tx_pump();
}

// Sets the duty cycle of PC9 (TIM3 CH4); the other channels are untouched.
// Returns the duty (%) actually produced after rounding to a whole timer count.
double pc9_set_duty(double pct) {
    uint32_t period = TIM3->ARR + 1;
    TIM3->CCR4 = (uint32_t)(period * pct / 100.0 + 0.5);
    return 100.0 * TIM3->CCR4 / period;
}

void pwm_uart_loop(void) {
    char line[CMD_MAX];
    int n = 0;

    for (;;) {
        uart5_tx_pump();
        char c;
        if (!uart5_getc(&c))
            continue;
        if (c != '\r' && c != '\n') {
            if (n < CMD_MAX - 1)
                line[n] = c;
            n++; // keep counting so an over-long line is rejected, not truncated
            continue;
        }

        if (n == 0)
            continue; // blank line, or the \n of a \r\n pair
        if (n > CMD_MAX - 1) {
            n = 0;
            uart5_puts("ERR line too long\r\n");
            continue;
        }
        line[n] = '\0';
        n = 0;

        char *end;
        double duty = strtod(line, &end);
        while (*end == ' ' || *end == '\t')
            end++;
        if (end == line || *end != '\0' || !(duty >= 0.0 && duty <= 100.0)) {
            uart5_puts("ERR need a number from 0 to 100 (%)\r\n");
            continue;
        }

        char reply[48];
        snprintf(reply, sizeof reply, "OK PC9 duty %.1f%%\r\n", pc9_set_duty(duty));
        uart5_puts(reply);
    }
}

//============================================================================
// Closed-loop PID motor speed control
//
// Hardware: DFRobot DRI0002 (L298N-based, 2 A/channel rated) dual H-bridge,
// channel 2 only. Motor: Pololu #2828, 150:1 gearmotor, 12 V, 64 CPR encoder
// at the motor shaft = 9600 counts/rev at the *output* shaft (64 x 150; the
// Pololu-specified 64 CPR already assumes full quadrature decoding -- do not
// multiply by 4 again). No-load: 67 RPM / 200 mA. Stall (theoretical,
// datasheet extrapolation): 5.5 A / 49 kg*cm -- real units stall well before
// that as they heat up.
//
//   E2 (PWM/enable)  -> PA6  -> TIM3_CH1 (AF1), 1 kHz PWM (the L298N is slow;
//                                DFRobot drives this board at Arduino's ~1 kHz)
//   M2 (direction)   -> PB0  -> plain GPIO output (0 = forward, 1 = reverse,
//                                per the DRI0002/L298N control table)
//   Encoder A (yellow) -> PA15 -> TIM2_CH1 (AF2)
//   Encoder B (white)  -> PB3  -> TIM2_CH2 (AF2)
//   TIM2 runs in hardware quadrature encoder mode (SMS = 011, counts both
//   edges of both channels), so no ISR is needed just to count pulses.
//
// Safety: the DRI0002 is only rated for 2 A/channel, far below the motor's
// 5.5 A theoretical stall current, and there is no current-sense feedback
// wired up -- duty cycle is the only lever available. mc_duty_cap_pct
// below is the duty ceiling (never above MOTOR_DUTY_HARD_MAX regardless of
// what's requested over UART) chosen so that even a full stall can only pull
// roughly cap% of the theoretical 5.5 A stall current. A software stall
// watchdog also force-stops the motor if it asks for max output while
// showing ~zero speed for MOTOR_STALL_TIMEOUT_MS, and every direction
// reversal passes through one tick of zero duty before flipping M2, so the
// H-bridge is never asked to reverse a live current.
//============================================================================
#include <math.h> // fabsf

#define MOTOR_COUNTS_PER_REV   9600.0f  // encoder counts per OUTPUT shaft rev
#define MOTOR_PID_HZ           100      // PID loop rate (TIM14)
#define MOTOR_PID_DT           (1.0f / MOTOR_PID_HZ)
#define MOTOR_RPM_PER_COUNT    (60.0f / (MOTOR_COUNTS_PER_REV * MOTOR_PID_DT))
#define MOTOR_PWM_PERIOD       48000    // TIM3 ARR+1 -> 48 MHz / 48000 = 1 kHz
#define MOTOR_DUTY_HARD_MAX    35.0f    // % duty; absolute ceiling, can't be
                                         // raised over UART (~1.9 A worst case
                                         // if stall current scales with duty)
#define MOTOR_RAMP_RPM_PER_S   80.0f    // soft-start slew rate
#define MOTOR_STALL_RPM        3.0f     // "basically not moving" threshold
#define MOTOR_STALL_TIMEOUT_MS 500

// Tuning starting point only -- NOT pre-tuned for your mechanical load.
// Bring-up procedure: start with Ki = Kd = 0, raise Kp until you see
// sustained oscillation at your target RPM, then back Kp off to ~50-60% of
// that value; raise Ki just enough to kill steady-state RPM error without
// re-introducing oscillation; add a little Kd only if overshoot on step
// changes is a problem. Retune (lower Kp especially) if you add real load.
volatile float mc_Kp = 0.6f;
volatile float mc_Ki = 3.0f;
volatile float mc_Kd = 0.0f;

volatile float mc_duty_cap_pct = 30.0f;  // runtime-adjustable, clamped to MOTOR_DUTY_HARD_MAX
volatile float mc_target_rpm = 0.0f;     // set over UART, signed (+ = forward)
volatile float mc_ramped_rpm = 0.0f;     // soft-start setpoint, updated in the ISR
volatile float mc_measured_rpm = 0.0f;
volatile float mc_output_pct = 0.0f;     // last PID output actually applied
volatile int   mc_fault_stall = 0;       // latched; cleared by a UART command
volatile int   mc_telemetry_due = 0;     // set every few ticks, printed in main loop

// Open-loop test mode ("open <pct>" over UART): drives a fixed duty with the
// PID bypassed, for telling a dead drive path apart from a dead encoder. The
// stall watchdog can't help here (a dead encoder looks like a stall), so the
// run is time-limited instead and the duty is still clamped to the cap.
#define MOTOR_OPEN_LOOP_MS     5000
volatile float mc_open_pct = 0.0f;
volatile int   mc_open_ms_left = 0;

static float mc_integral = 0.0f;
static float mc_prev_error = 0.0f;
static int32_t mc_last_count = 0;
static int mc_forward = 1;               // direction currently applied to M2
static uint32_t mc_stall_ms = 0;
static int mc_tick = 0;

void setup_motor_pwm(void) {
    RCC->APB1ENR |= RCC_APB1ENR_TIM3EN;
    RCC->AHBENR |= RCC_AHBENR_GPIOAEN;

    GPIOA->MODER &= ~GPIO_MODER_MODER6;
    GPIOA->MODER |= GPIO_MODER_MODER6_1;     // AF mode
    GPIOA->AFR[0] &= ~GPIO_AFRL_AFRL6;
    GPIOA->AFR[0] |= 0x1 << (6 * 4);         // AF1 = TIM3_CH1

    TIM3->PSC = 0;
    TIM3->ARR = MOTOR_PWM_PERIOD - 1;        // 48 MHz / 48000 = 1 kHz (fits TIM3's 16 bits)
    TIM3->CR1 &= ~TIM_CR1_DIR;

    TIM3->CCMR1 &= ~TIM_CCMR1_OC1M_0;
    TIM3->CCMR1 |= TIM_CCMR1_OC1M_1 | TIM_CCMR1_OC1M_2; // PWM mode 1

    TIM3->CCR1 = 0;                          // start at 0% -- motor off
    TIM3->CCER |= TIM_CCER_CC1E;
    TIM3->CR1 |= TIM_CR1_CEN;
}

void setup_motor_dir(void) {
    RCC->AHBENR |= RCC_AHBENR_GPIOBEN;
    GPIOB->MODER &= ~GPIO_MODER_MODER0;
    GPIOB->MODER |= GPIO_MODER_MODER0_0;     // general-purpose output
    GPIOB->BSRR = 1 << (0 + 16);             // start LOW = forward, motor off via CCR1=0
    mc_forward = 1;
}

void setup_encoder(void) {
    RCC->APB1ENR |= RCC_APB1ENR_TIM2EN;
    RCC->AHBENR |= RCC_AHBENR_GPIOAEN | RCC_AHBENR_GPIOBEN;

    // PA15 = TIM2_CH1 (AF2), PB3 = TIM2_CH2 (AF2); weak pull-ups as a
    // defensive default in case the encoder board doesn't supply its own.
    GPIOA->MODER &= ~GPIO_MODER_MODER15;
    GPIOA->MODER |= GPIO_MODER_MODER15_1;
    GPIOA->PUPDR &= ~GPIO_PUPDR_PUPDR15;
    GPIOA->PUPDR |= GPIO_PUPDR_PUPDR15_0;
    GPIOA->AFR[1] &= ~GPIO_AFRH_AFRH7;
    GPIOA->AFR[1] |= 0x2 << 28;              // AF2, pin15 = AFR[1] nibble 7

    GPIOB->MODER &= ~GPIO_MODER_MODER3;
    GPIOB->MODER |= GPIO_MODER_MODER3_1;
    GPIOB->PUPDR &= ~GPIO_PUPDR_PUPDR3;
    GPIOB->PUPDR |= GPIO_PUPDR_PUPDR3_0;
    GPIOB->AFR[0] &= ~GPIO_AFRL_AFRL3;
    GPIOB->AFR[0] |= 0x2 << 12;              // AF2, pin3 = AFR[0] nibble 3

    TIM2->CCMR1 &= ~(TIM_CCMR1_CC1S | TIM_CCMR1_CC2S);
    TIM2->CCMR1 |= TIM_CCMR1_CC1S_0 | TIM_CCMR1_CC2S_0; // map CH1/CH2 to TI1/TI2
    TIM2->CCMR1 |= (0x3 << 4) | (0x3 << 12);            // light input filter on both
    TIM2->CCER &= ~(TIM_CCER_CC1P | TIM_CCER_CC2P);     // non-inverted; flip if
                                                          // measured direction is backwards
    TIM2->SMCR &= ~TIM_SMCR_SMS;
    TIM2->SMCR |= TIM_SMCR_SMS_1 | TIM_SMCR_SMS_0;      // encoder mode 3 (both edges, both ch)
    TIM2->ARR = 0xFFFFFFFF;
    TIM2->CNT = 0;
    TIM2->CR1 |= TIM_CR1_CEN;
    mc_last_count = 0;
}

void init_motor_pid_timer(void) {
    RCC->APB1ENR |= RCC_APB1ENR_TIM14EN;
    TIM14->PSC = 48000 - 1;                  // 48 MHz -> 1 kHz tick
    TIM14->ARR = (1000 / MOTOR_PID_HZ) - 1;  // 1 kHz -> MOTOR_PID_HZ
    TIM14->DIER |= TIM_DIER_UIE;
    TIM14->CR1 |= TIM_CR1_CEN;
    NVIC->ISER[0] |= 1 << TIM14_IRQn;
}

void setup_motor_control(void) {
    setup_motor_pwm();
    setup_motor_dir();
    setup_encoder();
    init_motor_pid_timer();
}

void TIM14_IRQHandler(void) {
    TIM14->SR &= ~TIM_SR_UIF;

    // --- measure speed from the encoder ---
    int32_t count = (int32_t)TIM2->CNT;
    int32_t delta = count - mc_last_count;
    mc_last_count = count;
    mc_measured_rpm = delta * MOTOR_RPM_PER_COUNT;

    // --- soft-start: slew the working setpoint toward the commanded one ---
    float max_step = MOTOR_RAMP_RPM_PER_S * MOTOR_PID_DT;
    float diff = mc_target_rpm - mc_ramped_rpm;
    if (diff > max_step) diff = max_step;
    if (diff < -max_step) diff = -max_step;
    mc_ramped_rpm += diff;

    // --- PID ---
    float cap = mc_duty_cap_pct;
    if (cap > MOTOR_DUTY_HARD_MAX) cap = MOTOR_DUTY_HARD_MAX;
    if (cap < 0.0f) cap = 0.0f;

    float error = mc_ramped_rpm - mc_measured_rpm;
    mc_integral += error * MOTOR_PID_DT;
    float i_term = mc_Ki * mc_integral;
    if (i_term > cap)  { i_term = cap;  mc_integral = (mc_Ki != 0.0f) ? cap / mc_Ki : 0.0f; }
    if (i_term < -cap) { i_term = -cap; mc_integral = (mc_Ki != 0.0f) ? -cap / mc_Ki : 0.0f; }
    float derivative = (error - mc_prev_error) / MOTOR_PID_DT;
    mc_prev_error = error;

    float output = mc_Kp * error + i_term + mc_Kd * derivative;

    int open_loop = mc_open_ms_left > 0;
    if (open_loop) {
        output = mc_open_pct;
        mc_integral = 0.0f;                  // don't carry windup back into closed loop
        mc_open_ms_left -= (1000 / MOTOR_PID_HZ);
        if (mc_open_ms_left <= 0)
            mc_open_pct = 0.0f;
    }

    if (output > cap)  output = cap;
    if (output < -cap) output = -cap;
    mc_output_pct = output;

    // --- apply to hardware, with a dead tick at 0 duty on every reversal ---
    if (mc_fault_stall) {
        TIM3->CCR1 = 0;
    } else {
        int want_forward = (output >= 0.0f);
        if (want_forward != mc_forward) {
            TIM3->CCR1 = 0;
            GPIOB->BSRR = want_forward ? (1 << (0 + 16)) : (1 << 0);
            mc_forward = want_forward;
        } else {
            float mag = fabsf(output);
            TIM3->CCR1 = (uint32_t)(mag / 100.0f * MOTOR_PWM_PERIOD + 0.5f);
        }
    }

    // --- stall watchdog: pinned at the cap but not actually turning ---
    // (skipped in open-loop test mode, which is time-limited instead)
    if (!mc_fault_stall && !open_loop) {
        int pinned = fabsf(output) >= (cap - 1.0f) && cap > 0.0f;
        int not_moving = fabsf(mc_measured_rpm) < MOTOR_STALL_RPM;
        if (pinned && not_moving) {
            mc_stall_ms += (1000 / MOTOR_PID_HZ);
            if (mc_stall_ms >= MOTOR_STALL_TIMEOUT_MS) {
                mc_fault_stall = 1;
                TIM3->CCR1 = 0;
                mc_target_rpm = 0.0f;
                mc_ramped_rpm = 0.0f;
                mc_integral = 0.0f;
            }
        } else {
            mc_stall_ms = 0;
        }
    }

    if (++mc_tick >= (MOTOR_PID_HZ / 10)) {  // ~10 Hz telemetry
        mc_tick = 0;
        mc_telemetry_due = 1;
    }
}

// Host UART command loop, reusing uart5_init()/uart5_putc()/uart5_puts()
// from the PC9 PWM demo above (USART5, PC12=TX/PD2=RX, 115200 8N1).
//
// Commands (one per line):
//   <number>      set target RPM, signed, e.g. "40" or "-40"
//   cap <number>  set the runtime duty-cycle cap in %, clamped to
//                 MOTOR_DUTY_HARD_MAX regardless of what's asked for
//   open <pct>    open-loop test: fixed duty (signed), PID and stall watchdog
//                 bypassed, auto-stops after MOTOR_OPEN_LOOP_MS
//   reset         clear a latched stall fault
//   stop          equivalent to "0", also ends an open-loop test
void motor_uart_loop(void) {
    char line[CMD_MAX];
    int n = 0;
    uart5_puts("Motor PID ready. Send a target RPM, 'open <pct>', 'cap <pct>', 'reset', or 'stop'.\r\n");

    for (;;) {
        if (mc_telemetry_due) {
            mc_telemetry_due = 0;
            char t[112];
            snprintf(t, sizeof t, "tgt=%.1f meas=%.1f duty=%.1f%% cap=%.1f%% cnt=%ld%s%s",
                      mc_target_rpm, mc_measured_rpm, mc_output_pct, mc_duty_cap_pct,
                      (long)(int32_t)TIM2->CNT,
                      mc_open_ms_left > 0 ? " OPEN" : "",
                      mc_fault_stall ? " FAULT:STALL" : "");
            uart5_puts(t);
            if (u5_overruns) {
                snprintf(t, sizeof t, " ORE=%lu", (unsigned long)u5_overruns);
                uart5_puts(t);
            }
            uart5_puts("\r\n");
        }

        uart5_tx_pump();
        char c;
        if (!uart5_getc(&c))
            continue;
        if (c != '\r' && c != '\n') {
            if (n < CMD_MAX - 1)
                line[n] = c;
            n++;
            continue;
        }
        if (n == 0)
            continue;
        if (n > CMD_MAX - 1) {
            n = 0;
            uart5_puts("ERR line too long\r\n");
            continue;
        }
        line[n] = '\0';
        n = 0;

        // accept "Open 25", " reset", etc.: drop leading blanks, lowercase
        char *p = line;
        while (*p == ' ' || *p == '\t')
            p++;
        memmove(line, p, strlen(p) + 1);
        for (char *q = line; *q; q++)
            if (*q >= 'A' && *q <= 'Z')
                *q += 'a' - 'A';

        if (strncmp(line, "reset", 5) == 0) {
            mc_fault_stall = 0;
            mc_stall_ms = 0;
            uart5_puts("OK fault cleared\r\n");
            continue;
        }
        if (strncmp(line, "stop", 4) == 0) {
            mc_open_ms_left = 0;
            mc_open_pct = 0.0f;
            mc_target_rpm = 0.0f;
            uart5_puts("OK target 0 RPM\r\n");
            continue;
        }
        if (strncmp(line, "open", 4) == 0) {
            char *end;
            double v = strtod(line + 4, &end);
            if (end == line + 4 || !(v >= -100.0 && v <= 100.0)) {
                uart5_puts("ERR need 'open <-100..100>'\r\n");
                continue;
            }
            if (mc_fault_stall) {
                uart5_puts("ERR stall fault latched, send 'reset' first\r\n");
                continue;
            }
            mc_target_rpm = 0.0f;
            mc_ramped_rpm = 0.0f;
            mc_open_pct = (float)v;
            mc_open_ms_left = MOTOR_OPEN_LOOP_MS;
            char reply[64];
            snprintf(reply, sizeof reply, "OK open-loop %.1f%% for %d ms (clamped to cap)\r\n",
                      v, MOTOR_OPEN_LOOP_MS);
            uart5_puts(reply);
            continue;
        }
        if (strncmp(line, "cap", 3) == 0) {
            char *end;
            double v = strtod(line + 3, &end);
            if (end == line + 3 || !(v >= 0.0 && v <= 100.0)) {
                uart5_puts("ERR need 'cap <0-100>'\r\n");
                continue;
            }
            mc_duty_cap_pct = (float)(v > MOTOR_DUTY_HARD_MAX ? MOTOR_DUTY_HARD_MAX : v);
            char reply[48];
            snprintf(reply, sizeof reply, "OK cap %.1f%% (hard max %.0f%%)\r\n",
                      mc_duty_cap_pct, (double)MOTOR_DUTY_HARD_MAX);
            uart5_puts(reply);
            continue;
        }

        char *end;
        double rpm = strtod(line, &end);
        while (*end == ' ' || *end == '\t')
            end++;
        if (end == line || *end != '\0') {
            uart5_puts("ERR unknown command; send a target RPM, 'open <pct>', 'cap <pct>', 'reset', or 'stop'\r\n");
            continue;
        }
        mc_open_ms_left = 0;                 // a speed command ends any open-loop test
        mc_open_pct = 0.0f;
        mc_target_rpm = (float)rpm;
        char reply[48];
        snprintf(reply, sizeof reply, "OK target %.1f RPM\r\n", mc_target_rpm);
        uart5_puts(reply);
    }
}

void setup_tim1(void) {
    // Generally the steps are similar to those in setup_tim3
    // except we will need to set the MOE bit in BDTR.
    // Be sure to do so ONLY after enabling the RCC clock to TIM1.
    RCC->APB2ENR |= RCC_APB2ENR_TIM1EN;      
    RCC->AHBENR |= RCC_AHBENR_GPIOAEN;
    
    // configure PA8-11 for alternate function mode;
    GPIOA->MODER &= ~0xFF0000;
    GPIOA->MODER |= 0xAA0000;

    // select AF2 for PA8-11
    GPIOA->AFR[1] &= ~GPIO_AFRH_AFRH0;
    GPIOA->AFR[1] &= ~GPIO_AFRH_AFRH1;
    GPIOA->AFR[1] &= ~GPIO_AFRH_AFRH2;
    GPIOA->AFR[1] &= ~GPIO_AFRH_AFRH3;

    GPIOA->AFR[1] |= 0x2;
    GPIOA->AFR[1] |= 0x2 << 4;
    GPIOA->AFR[1] |= 0x2 << 8;
    GPIOA->AFR[1] |= 0x2 << 12;

    // enable MOE bit 
    TIM1->BDTR |= TIM_BDTR_MOE;  
    TIM1->PSC = 1 - 1;
    TIM1->ARR = 2400 - 1;

    // counting direction: 0=up, 1=down
    TIM1->CR1 &= ~TIM_CR1_DIR; // default to 0 "up" so this can be ommitted

    // configure TIM3 for PWM mode 1 (110) for all 4 channels
    TIM1->CCMR1 &=  ~TIM_CCMR1_OC1M_0; 
    TIM1->CCMR1 |= TIM_CCMR1_OC1M_1 | TIM_CCMR1_OC1M_2;

    TIM1->CCMR1 &=  ~TIM_CCMR1_OC2M_0; 
    TIM1->CCMR1 |= TIM_CCMR1_OC2M_1 | TIM_CCMR1_OC2M_2;

    TIM1->CCMR2 &= ~TIM_CCMR2_OC3M_0;
    TIM1->CCMR2 |= TIM_CCMR2_OC3M_1 | TIM_CCMR2_OC3M_2;

    TIM1->CCMR2 &= ~TIM_CCMR2_OC4M_0;
    TIM1->CCMR2 |= TIM_CCMR2_OC4M_1 | TIM_CCMR2_OC4M_2;
    
    // channel 4 of tim1, enable output compare preload enable
    TIM1->CCMR2 |= TIM_CCMR2_OC4PE;

    // enable the four channel outputs
    TIM1->CCER |= TIM_CCER_CC1E | TIM_CCER_CC2E | TIM_CCER_CC3E | TIM_CCER_CC4E;

    // enable tim1
    TIM1->CR1 |= TIM_CR1_CEN;
}

int getrgb(void);

// Helper function for you
// Accept a byte in BCD format and convert it to decimal
uint8_t bcd2dec(uint8_t bcd) {
    // Lower digit
    uint8_t dec = bcd & 0xF;

    // Higher digit
    dec += 10 * (bcd >> 4);
    return dec;
}

void setrgb(int rgb) {
    uint8_t b = bcd2dec(rgb & 0xFF);
    uint8_t g = bcd2dec((rgb >> 8) & 0xFF);
    uint8_t r = bcd2dec((rgb >> 16) & 0xFF);

    // TODO: Assign values to TIM1->CCRx registers
    // Remember these are all percentages
    // Also, LEDs are on when the corresponding PWM output is low
    // so you might want to invert the numbers.
    TIM1->CCR1 = (100 - r) * 24;
    TIM1->CCR2 = (100 - g) * 24;
    TIM1->CCR3 = (100 - b) * 24;
}



//============================================================================
// Lab 4 code
// Add in your functions from previous lab
//============================================================================

// Part 3: Analog-to-digital conversion for a volume level.
// uint32_t volume = 2400;
int volume = 2400;

// Variables for boxcar averaging.
#define BCSIZE 32
int bcsum = 0;
int boxcar[BCSIZE];
int bcn = 0;

void dialer(void);

// Parameters for the wavetable size and expected synthesis rate.
#define N 1000
#define RATE 20000
short int wavetable[N];
int step0 = 0;
int offset0 = 0;
int step1 = 0;
int offset1 = 0;

//============================================================================
// enable_ports()
//============================================================================
void enable_ports(void)
{
    RCC->AHBENR |= RCC_AHBENR_GPIOBEN;
    RCC->AHBENR |= RCC_AHBENR_GPIOCEN;

    GPIOB->MODER |= 0x155555;
    GPIOC->MODER |= 0x5500;
    // Open drain config
    GPIOC->OTYPER |= 0xF0;
    // Pull down high
    GPIOC->PUPDR |= 0x55;
}

//============================================================================
// setup_dma() + enable_dma()
//============================================================================
void setup_dma(void)
{
    RCC->AHBENR |= RCC_AHBENR_DMA1EN;                // enable rcc clock to the DMA controller
    DMA1_Channel5->CCR &= !DMA_CCR_EN;               // clear enable bit
    DMA1_Channel5->CMAR = (uint32_t)msg;             // src address
    DMA1_Channel5->CPAR = (uint32_t)(&(GPIOB->ODR)); // dest address
    DMA1_Channel5->CNDTR = 0x8;                      // number of data
    DMA1_Channel5->CCR |= DMA_CCR_DIR;               // Direction for copying from memory to peripheral
    DMA1_Channel5->CCR |= DMA_CCR_MINC;              // Memory incrememnt enable
    DMA1_Channel5->CCR |= DMA_CCR_MSIZE_0;           // Memory size 16 bit
    DMA1_Channel5->CCR |= DMA_CCR_PSIZE_0;           // Periperal size 16 bit
    DMA1_Channel5->CCR |= DMA_CCR_CIRC;              // tells the transfer to keep going after completion
}

void enable_dma(void)
{
    // NVIC->ISER[0] = 1 << DMA1_Channel4_5_IRQn;
    DMA1_Channel5->CCR |= DMA_CCR_EN;
}


//============================================================================
// init_tim15()
//============================================================================
void init_tim15(void)
{
    RCC->APB2ENR |= RCC_APB2ENR_TIM15EN; // enable clock for tim15
    TIM15->DIER |= TIM_DIER_UDE;         // UDE triggers DMA requests on interrrupts
    TIM15->PSC = 48 - 1;                 // prescales clock to 1MHz
    TIM15->ARR = 1000 - 1;               // scales clock to 1 KHz
    TIM15->CR1 |= TIM_CR1_CEN;
    NVIC->ISER[0] |= 1 << TIM15_IRQn;
}


//=============================================================================
// Part 2: Debounced keypad scanning.
//=============================================================================

uint8_t col; // the column being scanned

void drive_column(int);   // energize one of the column outputs
int  read_rows();         // read the four row inputs
void update_history(int col, int rows); // record the buttons of the driven column
char get_key_event(void); // wait for a button event (press or release)
char get_keypress(void);  // wait for only a button press event.
float getfloat(void);     // read a floating-point number from keypad
void show_keys(void);     // demonstrate get_key_event()

//============================================================================
// The Timer 7 ISR
//============================================================================
void TIM7_IRQHandler(void)
{
    TIM7->SR &= ~TIM_SR_UIF; // acknowledge interrupt
    int rows = read_rows();
    update_history(col, rows);
    col = (col + 1) & 3;
    drive_column(col);
}

//============================================================================
// init_tim7()
//============================================================================
void init_tim7(void)
{
    RCC->APB1ENR |= RCC_APB1ENR_TIM7EN;
    TIM7->PSC = 48 - 1;
    TIM7->ARR = 1000 - 1;
    TIM7->CR1 |= TIM_CR1_CEN;
    TIM7->DIER |= TIM_DIER_UIE;
    NVIC->ISER[0] |= 1 << TIM7_IRQn;
}


//============================================================================
// setup_adc()
//============================================================================

void setup_adc(void)
{
    // GPIO config
    RCC->AHBENR |= RCC_AHBENR_GPIOAEN;
    GPIOA->MODER |= 0xC; // 11 for analog

    RCC->APB2ENR |= RCC_APB2ENR_ADCEN; // enable clock to the ADC peripheral
    RCC->CR2 |= RCC_CR2_HSI14ON;       // turn on 14MHz clock
    while (!(RCC->CR2 & RCC_CR2_HSI14RDY))
        ;                    // wait for 14MHz clock to be ready
    ADC1->CR |= ADC_CR_ADEN; // enable ADC
    while (!(ADC1->ISR & ADC_ISR_ADRDY))
        ;             // wait for ADC to be ready
    // ADC1->CHSELR = 0; // deactivate the other channels
    ADC1->CHSELR |= ADC_CHSELR_CHSEL1;
    while (!(ADC1->ISR & ADC_ISR_ADRDY))
        ;
}

//============================================================================
// Timer 2 ISR
//============================================================================
// Write the Timer 2 ISR here.  Be sure to give it the right name.
void TIM2_IRQHandler(void)
{
    TIM2->SR &= ~TIM_SR_UIF; // acknowledge interrupt
    ADC1->CR |= ADC_CR_ADSTART;
    while(!(ADC1->ISR & ADC_ISR_EOC));
    bcsum -= boxcar[bcn];
    // boxcar[bcn] = ADC1->DR;
    bcsum += boxcar[bcn] = ADC1->DR;
    bcn += 1;
    if (bcn >= BCSIZE)
    {
        bcn = 0;
    }
    volume = bcsum / BCSIZE;
}

//============================================================================
// init_tim2()
//============================================================================
void init_tim2(void)
{
    RCC->APB1ENR |= RCC_APB1ENR_TIM2EN;
    TIM2->PSC = 48 - 1;
    TIM2->ARR = 100000 - 1;
    TIM2->CR1 |= TIM_CR1_CEN;        // enable counter
    TIM2->DIER |= TIM_DIER_UIE;      // enable interuptEN
    NVIC->ISER[0] |= 1 << TIM2_IRQn; // enable interrupt in NVIC
    NVIC_SetPriority(TIM2_IRQn, 3);
}



//============================================================================
// setup_dac()
//============================================================================
void setup_dac(void)
{
    RCC->AHBENR |= RCC_AHBENR_GPIOAEN;
    GPIOA->MODER |= 0x300;
    RCC->APB1ENR |= RCC_APB1ENR_DACEN;
    DAC1->CR &= ~0x38;
    DAC1->CR |= DAC_CR_TEN1;
    DAC1->CR |= DAC_CR_EN1;
}

//============================================================================
// Timer 6 ISR
//============================================================================
// Write the Timer 6 ISR here.  Be sure to give it the right name.

void TIM6_DAC_IRQHandler(void)
{
    TIM6->SR &= ~TIM_SR_UIF;
    offset0 += step0;
    offset1 += step1;
    if (offset0 >= (N << 16))
    {
        offset0 -= (N << 16);
    }
    if (offset1 >= (N << 16))
    {
        offset1 -= (N << 16);
    }
    int samp = wavetable[offset0 >> 16] + wavetable[offset1 >> 16];
    // samp *= volume;
    // samp = samp >> 17;
    // samp += 2048;
    samp = ((samp * volume)>>18) + 1200; 
    // DAC->DHR12R1 = samp;
    TIM1->CCR4 = samp;
}
//============================================================================
// init_tim6()
//============================================================================
void init_tim6(void)
{
    RCC->APB1ENR |= RCC_APB1ENR_TIM6EN;
    TIM6->PSC = 48 - 1;
    TIM6->ARR = (1000000 / RATE) - 1;
    TIM6->DIER |= TIM_DIER_UIE;
    TIM6->CR1 |= TIM_CR1_CEN;
    // TIM6->CR2 |= TIM_CR2_MMS_1; 
    NVIC->ISER[0] |= 1 << TIM6_DAC_IRQn;
}

//===========================================================================
// init_wavetable()
// Write the pattern for a complete cycle of a sine wave into the
// wavetable[] array.
//===========================================================================
void init_wavetable(void)
{
    for (int i = 0; i < N; i++)
        wavetable[i] = 32767 * sin(2 * M_PI * i / N);
}



//============================================================================
// set_freq()
//============================================================================

void set_freq(int chan, float f)
{
    if (chan == 0)
    {
        if (f == 0.0)
        {
            step0 = 0;
            offset0 = 0;
        }
        else
            step0 = (f * N / RATE) * (1 << 16);
    }
    if (chan == 1)
    {
        if (f == 0.0)
        {
            step1 = 0;
            offset1 = 0;
        }
        else
            step1 = (f * N / RATE) * (1 << 16);
    }
}

//============================================================================
// All the things you need to test your subroutines.
//============================================================================
int main(void) {
    internal_clock();

    // Uncomment autotest to get the confirmation code.
    // autotest();

    // Uncomment only one of MOTOR_PID_DEMO / TEST_UART_PWM / TEST_TIMER3
    // (each loops forever).

    // Closed-loop PID speed control of the Pololu #2828 gearmotor through
    // the DRI0002 H-bridge (E2=PA6, M2=PB0) with encoder feedback
    // (A=PA15, B=PB3). Host interface over USART5, see motor_pid_uart.py.
#define MOTOR_PID_DEMO
#ifdef MOTOR_PID_DEMO
    uart5_init();
    setup_motor_control();
    motor_uart_loop();
#endif

    // PC9 duty cycle set from the host over USART5 (see pwm_uart.py).
// #define TEST_UART_PWM
#ifdef TEST_UART_PWM
    uart5_init();
    setup_tim3();
    pwm_uart_loop();
#endif

    // Demonstrate part 1
// #define TEST_TIMER3
#ifdef TEST_TIMER3
    setup_tim3();
    for(;;) { }
#endif

    // Initialize the display to something interesting to get started.
    msg[0] |= font['E'];
    msg[1] |= font['C'];
    msg[2] |= font['E'];
    msg[3] |= font[' '];
    msg[4] |= font['3'];
    msg[5] |= font['6'];
    msg[6] |= font['2'];
    msg[7] |= font[' '];

    enable_ports();
    setup_dma();
    enable_dma();
    init_tim15();
    init_tim7();
    setup_adc();
    init_tim2();
    init_wavetable();
    init_tim6();

    setup_tim1();
    setrgb(0x001500);

    // demonstrate part 2
#define TEST_TIM1
#ifdef TEST_TIM1
    for(;;) {
        // Breathe in...
        for(float x=1; x<2400; x *= 1.1) {
            TIM1->CCR1 = TIM1->CCR2 = TIM1->CCR3 = 2400-x;
            nano_wait(100000000);
        }
        // ...and out...
        for(float x=2400; x>=1; x /= 1.1) {
            TIM1->CCR1 = TIM1->CCR2 = TIM1->CCR3 = 2400-x;
            nano_wait(100000000);
        }
        // ...and start over.
    }
#endif

    // demonstrate part 3
// #define MIX_TONES
// #ifdef MIX_TONES
//     set_freq(0, 1000);
//     for(;;) {
//         char key = get_keypress();
//         if (key == 'A')
//             set_freq(0,getfloat());
//         if (key == 'B')
//             set_freq(1,getfloat());
//     }
// #endif

    // demonstrate part 4
// #define TEST_SETRGB
// #ifdef TEST_SETRGB
//     for(;;) {
//         char key = get_keypress();
//         if (key == 'A')
//             set_freq(0,getfloat());
//         if (key == 'B')
//             set_freq(1,getfloat());
//         if (key == 'D')
//             setrgb(getrgb());
//     }
// #endif

    // Have fun.
    dialer();
}
