# Toggle PA15's weak pull every 5 s (PA9 stays pulled up), to find the PA15 leg with a meter.
proc pulltoggle {sec} {
    set a [expr {[read_memory 0x4800000C 32 1] & ~((3<<30)|(3<<18))}]
    set t0 [clock milliseconds]; set ph -1
    while {[clock milliseconds]-$t0 < 1000*$sec} {
        set p [expr {(([clock milliseconds]-$t0)/5000) & 1}]
        if {$p != $ph} {
            set ph $p
            mww 0x4800000C [expr {$a | (($p ? 2 : 1) << 30) | (1 << 18)}]; sleep 20
            echo "t=[expr {([clock milliseconds]-$t0)/1000}]s PA15 pull [expr {$p ? {DOWN} : {UP}}], STM32 reads [expr {([read_memory 0x48000010 32 1]>>15)&1}]"
        }
        sleep 50
    }
    mww 0x4800000C [expr {$a | (1<<30) | (1<<18)}]
    echo FINISHED
}
