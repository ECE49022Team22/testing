# Read-only probe of the Hiwonder bus servo through the servo firmware's RAM mailbox (host_mailbox.h, version 4).
proc rd {a} { expr {[read_memory $a 32 1] + 0} }
proc s32 {v} { expr {$v >= 0x80000000 ? $v - 0x100000000 : $v} }
set MB 0
foreach {base} {0x20000000 0x20001000 0x20002000 0x20003000 0x20004000 0x20005000 0x20006000 0x20007000} {
    set words [read_memory $base 32 1024]
    for {set i 0} {$i < 1023} {incr i} {
        if {[lindex $words $i] == 0x53525643 && [lindex $words [expr {$i+1}]] == 4} { set MB [expr {$base + 4*$i}]; break }
    }
    if {$MB} break
}
if {!$MB} { echo "servo mailbox NOT found (firmware not running?)"; shutdown; return }
echo "mailbox at [format 0x%08x $MB], heartbeat [rd [expr {$MB+8}]] ms"
proc w {i v} { global MB; mww [expr {$MB + 4*$i}] $v }
proc r {i} { global MB; rd [expr {$MB + 4*$i}] }
proc bytes {addr lenaddr} { set n [expr {[read_memory $lenaddr 8 1]+0}]; if {$n == 0} {return "(none)"}; set o {}; foreach b [read_memory $addr 8 $n] { lappend o [format %02X $b] }; return [join $o " "] }
proc cmd {type id label} {
    set seq [expr {[r 8] + 1}]
    w 3 $type; w 4 $id; w 5 0; w 6 0; w 7 $seq
    set t0 [clock milliseconds]
    while {[r 8] != $seq && [clock milliseconds] - $t0 < 1000} { sleep 5 }
    set st [r 9]; set stname [lindex {OK ERROR BUSY TIMEOUT} $st]
    echo "$label: status $stname | sent [bytes [r 20] [r 21]] | reply [bytes [r 22] [r 23]]"
    return $st
}
if {[cmd 4 254 "READ ID (broadcast 0xFE)"] == 0} {
    set id [r 13]; echo "  servo ID = $id"
    if {[cmd 5 $id "READ ALL (id $id)"] == 0} {
        echo "  position [s32 [r 10]] (0..1000 counts), input [format %.2f [expr {[r 11]/1000.0}]] V, temperature [r 12] C"
    }
}
echo "counters: tx_ok [r 14] tx_err [r 15] rx_ok [r 16] rx_timeout [r 17] rx_bad [r 18] retries [r 19]"
echo "pins: PB10 mode [expr {([rd 0x48000400]>>20)&3}] AF [expr {([rd 0x48000424]>>8)&0xF}] level [expr {([rd 0x48000410]>>10)&1}] | PB11 (DIR) mode [expr {([rd 0x48000400]>>22)&3}] out [expr {([rd 0x48000414]>>11)&1}] | USART3 CR1 [format 0x%x [rd 0x40004800]] CR3 [format 0x%x [rd 0x40004808]] BRR [rd 0x4000480C]"
