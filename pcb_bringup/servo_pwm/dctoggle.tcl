# Diagnostic: PB10 as a plain output, high/low every 5 s (U8 DIR stays high: A->B), for tracing with a multimeter.
# Restores PB10 to TIM2_CH3 (low, no pulses) at the end.
proc dctoggle {sec} {
    mww 0x20000004 0
    set m [expr {[read_memory 0x48000400 32 1] + 0}]
    mww 0x48000400 [expr {($m & ~(3 << 20)) | (1 << 20)}]
    set t0 [clock milliseconds]; set ph -1
    while {[clock milliseconds] - $t0 < 1000*$sec} {
        set p [expr {(([clock milliseconds]-$t0)/5000) & 1}]
        if {$p != $ph} {
            set ph $p
            mww 0x48000418 [expr {$p ? (1 << 26) : (1 << 10)}]
            echo "t=[expr {([clock milliseconds]-$t0)/1000}]s PB10 [expr {$p ? {LOW} : {HIGH}}] (reads [expr {([read_memory 0x48000410 32 1]>>10)&1}]) DIR(PB11)=[expr {([read_memory 0x48000410 32 1]>>11)&1}]"
        }
        sleep 50
    }
    mww 0x48000418 [expr {1 << 26}]
    set m [expr {[read_memory 0x48000400 32 1] + 0}]
    mww 0x48000400 [expr {($m & ~(3 << 20)) | (2 << 20)}]
    echo FINISHED
}
