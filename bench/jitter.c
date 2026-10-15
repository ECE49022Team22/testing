// Scheduling-latency probe, a minimal cyclictest: one thread pinned to each CPU sleeps to an
// absolute deadline every --interval-us and records how late it woke up (in microseconds).
// Runs at normal priority (SCHED_OTHER), like the apps; pass --fifo N to test RT priority.
// Writes {"cpus": {"0": {"hist": [...], "max_us": .., "n": ..}, ...}} to --out on SIGINT/SIGTERM.
#define _GNU_SOURCE
#include <pthread.h>
#include <sched.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define HIST_US 20000   // 1 us buckets up to 20 ms; anything later counts in the last bucket

static volatile sig_atomic_t stop;
static long interval_us = 1000;
static int fifo_prio;

struct probe {
    int cpu;
    long n, max_us;
    double sum_us;
    unsigned hist[HIST_US + 1];
};

static void on_signal(int s) { (void)s; stop = 1; }

static void *run(void *arg) {
    struct probe *p = arg;
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(p->cpu, &set);
    pthread_setaffinity_np(pthread_self(), sizeof set, &set);
    if (fifo_prio) {
        struct sched_param sp = {.sched_priority = fifo_prio};
        if (pthread_setschedparam(pthread_self(), SCHED_FIFO, &sp))
            fprintf(stderr, "[jitter] cpu%d: SCHED_FIFO refused, staying SCHED_OTHER\n", p->cpu);
    }
    struct timespec next, now;
    clock_gettime(CLOCK_MONOTONIC, &next);
    while (!stop) {
        next.tv_nsec += interval_us * 1000;
        while (next.tv_nsec >= 1000000000) { next.tv_nsec -= 1000000000; next.tv_sec++; }
        clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next, NULL);
        clock_gettime(CLOCK_MONOTONIC, &now);
        long lat = ((now.tv_sec - next.tv_sec) * 1000000000L + (now.tv_nsec - next.tv_nsec)) / 1000;
        if (lat < 0) lat = 0;
        p->hist[lat > HIST_US ? HIST_US : lat]++;
        if (lat > p->max_us) p->max_us = lat;
        p->sum_us += lat;
        p->n++;
        if (lat > (long)interval_us * 4) next = now;   // don't fire a burst to catch up
    }
    return NULL;
}

int main(int argc, char **argv) {
    const char *out = NULL;
    for (int i = 1; i < argc - 1; i++) {
        if (!strcmp(argv[i], "--out")) out = argv[++i];
        else if (!strcmp(argv[i], "--interval-us")) interval_us = atol(argv[++i]);
        else if (!strcmp(argv[i], "--fifo")) fifo_prio = atoi(argv[++i]);
    }
    if (!out) { fprintf(stderr, "usage: jitter --out FILE [--interval-us N] [--fifo PRIO]\n"); return 2; }
    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);

    int ncpu = (int)sysconf(_SC_NPROCESSORS_ONLN);
    struct probe *p = calloc(ncpu, sizeof *p);
    pthread_t *th = calloc(ncpu, sizeof *th);
    for (int c = 0; c < ncpu; c++) {
        p[c].cpu = c;
        pthread_create(&th[c], NULL, run, &p[c]);
    }
    char rp[4096];
    snprintf(rp, sizeof rp, "%s.ready", out);
    FILE *r = fopen(rp, "w");
    if (r) fclose(r);
    for (int c = 0; c < ncpu; c++) pthread_join(th[c], NULL);

    FILE *f = fopen(out, "w");
    if (!f) { perror(out); return 1; }
    fprintf(f, "{\"name\": \"jitter\", \"interval_us\": %ld, \"fifo\": %d, \"cpus\": {", interval_us, fifo_prio);
    for (int c = 0; c < ncpu; c++) {
        fprintf(f, "%s\"%d\": {\"n\": %ld, \"max_us\": %ld, \"mean_us\": %.2f, \"hist\": {",
                c ? ", " : "", c, p[c].n, p[c].max_us, p[c].n ? p[c].sum_us / p[c].n : 0.0);
        int first = 1;
        for (int b = 0; b <= HIST_US; b++)
            if (p[c].hist[b]) { fprintf(f, "%s\"%d\": %u", first ? "" : ", ", b, p[c].hist[b]); first = 0; }
        fprintf(f, "}}");
    }
    fprintf(f, "}}\n");
    fclose(f);
    fprintf(stderr, "[jitter] wrote %s\n", out);
    return 0;
}
