# Runs inside OpenOCD. Mailbox layout: see main.c.  Nothing here halts the CPU.
set MB 0x20000000
set KEY 0x41524D21
set CPR 751.8
proc s32 {v} { set v [expr {$v + 0}]; expr {$v >= 0x80000000 ? $v - 0x100000000 : $v} }
proc st {} { global MB; return [read_memory [expr {$MB + 0x14}] 32 7] }
proc bits {v} { format "A1=%d B1=%d A2=%d B2=%d" [expr {$v&1}] [expr {($v>>1)&1}] [expr {($v>>2)&1}] [expr {($v>>3)&1}] }
proc status {} {
    global MB
    set m [read_memory $MB 32 1]
    if {$m != 0x4D4F5431} { echo "motor firmware NOT running (magic=[format 0x%x $m])"; return }
    lassign [st] ms e1 e2 o1 o2 trips inp
    echo "uptime [expr {$ms/1000.0}] s | enc1 [s32 $e1] enc2 [s32 $e2] | duty ticks [s32 $o1] [s32 $o2] | watchdog stops $trips | [bits $inp]"
}
# No motion: print counts and raw encoder levels, for turning the wheels by hand.
proc watch {sec} {
    set end [expr {[clock milliseconds] + 1000*$sec}]
    set last ""
    while {[clock milliseconds] < $end} {
        lassign [st] ms e1 e2 o1 o2 trips inp
        set now "enc1 [s32 $e1]  enc2 [s32 $e2]  [bits $inp]"
        if {$now ne $last} { echo $now; set last $now }
        sleep 100
    }
    echo "final: $last"
}
# Drive for sec seconds with signed duty ticks (1 tick = 0.25 %), then ramp down and disarm.
proc drive {t1 t2 sec} {
    global MB KEY CPR
    set seq [expr {[clock milliseconds] & 0xFFFFFF}]
    mww [expr {$MB+0x08}] [expr {$t1 & 0xFFFFFFFF}]
    mww [expr {$MB+0x0C}] [expr {$t2 & 0xFFFFFFFF}]
    mww [expr {$MB+0x04}] [incr seq]
    mww [expr {$MB+0x10}] $KEY
    set t0 [clock milliseconds]; set settle [expr {$t0 + 900}]; set end [expr {$t0 + int(1000*$sec)}]
    set a ""
    while {[clock milliseconds] < $end} {
        mww [expr {$MB+0x04}] [incr seq]
        if {$a eq "" && [clock milliseconds] >= $settle} { set a [st]; set ta [clock milliseconds] }
        sleep 30
    }
    set b [st]; set tb [clock milliseconds]
    mww [expr {$MB+0x10}] 0; mww [expr {$MB+0x08}] 0; mww [expr {$MB+0x0C}] 0
    sleep 800
    set dt [expr {($tb-$ta)/1000.0}]
    set d1 [expr {[s32 [lindex $b 1]]-[s32 [lindex $a 1]]}]; set d2 [expr {[s32 [lindex $b 2]]-[s32 [lindex $a 2]]}]
    echo [format "duty M1 %+5.1f%%  M2 %+5.1f%%  ->  M1 %+6d counts %+6.1f RPM | M2 %+6d counts %+6.1f RPM" [expr {$t1*.25}] [expr {$t2*.25}] $d1 [expr {$d1/$CPR/$dt*60}] $d2 [expr {$d2/$CPR/$dt*60}]]
}
# DIR1 trace: toggle DIR1 every 5 s at 1 tick (0.25 % duty: the motor won't move), for a multimeter on J6 pin 2.
proc dirtest {sec} {
    global MB KEY
    set seq [expr {[clock milliseconds] & 0xFFFFFF}]
    mww [expr {$MB+0x04}] [incr seq]; mww [expr {$MB+0x10}] $KEY
    set t0 [clock milliseconds]; set phase -1
    while {[clock milliseconds] - $t0 < 1000*$sec} {
        set p [expr {(([clock milliseconds]-$t0)/5000) & 1}]
        if {$p != $phase} {
            set phase $p
            mww [expr {$MB+0x08}] [expr {($p ? 1 : -1) & 0xFFFFFFFF}]
            mww [expr {$MB+0x04}] [incr seq]; sleep 60; mww [expr {$MB+0x04}] [incr seq]
            echo "t=[expr {([clock milliseconds]-$t0)/1000}]s DIR1 commanded [expr {$p ? {LOW} : {HIGH}}], PB0 reads [expr {[read_memory 0x48000410 32 1] & 1}]"
        }
        mww [expr {$MB+0x04}] [incr seq]; sleep 40
    }
    mww [expr {$MB+0x10}] 0; mww [expr {$MB+0x08}] 0; sleep 100
    echo FINISHED
}
# DIR1 test with PWM at exactly zero: never arms. Toggles every 5 s; firmware drops it if the Pi stops.
proc dirzero {sec} {
    global MB
    set seq [expr {[clock milliseconds] & 0xFFFFFF}]; set t0 [clock milliseconds]; set phase -1
    while {[clock milliseconds] - $t0 < 1000*$sec} {
        set p [expr {(([clock milliseconds]-$t0)/5000) & 1}]
        mww [expr {$MB+0x04}] [incr seq]
        if {$p != $phase} {
            set phase $p
            mww [expr {$MB+0x30}] [expr {0x44495200 | ($p ? 0 : 1)}]; sleep 20; mww [expr {$MB+0x04}] [incr seq]
            set arm [expr {[read_memory [expr {$MB+0x10}] 32 1]+0}]
            lassign [read_memory 0x40000434 32 2] c1 c2
            echo "t=[expr {([clock milliseconds]-$t0)/1000}]s DIR1 [expr {$p ? {LOW} : {HIGH}}] | PB0 reads [expr {[read_memory 0x48000410 32 1] & 1}] | armed $arm | PWM CCR [expr {$c1+0}] [expr {$c2+0}]"
            if {$arm != 0 || $c1 != 0 || $c2 != 0} { echo "ABORT: PWM not zero"; break }
        }
        sleep 40
    }
    mww [expr {$MB+0x30}] 0; sleep 50; echo FINISHED
}
proc edges {} {
    lassign [read_memory 0x20000038 32 6] a1 b1 a2 b2 x1 x2
    echo "edges so far: M1 A=[expr {$a1+0}] B=[expr {$b1+0}] together=[expr {$x1+0}] | M2 A=[expr {$a2+0}] B=[expr {$b2+0}] together=[expr {$x2+0}]"
}
# No motion: report every change of the two suspect encoder inputs (motor 1 A, motor 2 B).
proc livewatch {sec} {
    set t0 [clock milliseconds]; set last ""
    echo "WATCHING"
    while {[clock milliseconds]-$t0 < 1000*$sec} {
        lassign [read_memory 0x20000038 32 4] a1 b1 a2 b2
        set v [expr {[read_memory 0x2000002c 32 1]+0}]
        set now "M1_A=[expr {$v&1}] (changes [expr {$a1+0}])  M2_B=[expr {($v>>3)&1}] (changes [expr {$b2+0}])"
        if {$now ne $last} { echo "t=[expr {([clock milliseconds]-$t0)/1000}]s $now"; set last $now }
        sleep 50
    }
    echo FINISHED
}
