# One small move: read position, move to target over dur ms, read back. Uses the same mailbox as servo_probe.tcl.
proc rd {a} { expr {[read_memory $a 32 1] + 0} }
proc s32 {v} { expr {$v >= 0x80000000 ? $v - 0x100000000 : $v} }
set MB 0
foreach base {0x20000000 0x20001000 0x20002000 0x20003000} {
    set words [read_memory $base 32 1024]
    for {set i 0} {$i < 1023} {incr i} { if {[lindex $words $i] == 0x53525643 && [lindex $words [expr {$i+1}]] == 4} { set MB [expr {$base + 4*$i}]; break } }
    if {$MB} break
}
if {!$MB} { echo "servo mailbox NOT found"; shutdown; return }
proc w {i v} { global MB; mww [expr {$MB + 4*$i}] $v }
proc r {i} { global MB; rd [expr {$MB + 4*$i}] }
proc cmd {type id pos dur} {
    set seq [expr {[r 8] + 1}]; w 3 $type; w 4 $id; w 5 $pos; w 6 $dur; w 7 $seq
    set t0 [clock milliseconds]; while {[r 8] != $seq && [clock milliseconds] - $t0 < 1000} { sleep 5 }
    return [r 9]
}
proc pos {} { if {[cmd 1 1 0 0] == 0} { return [s32 [r 10]] } else { return "read failed" } }
set before [pos]
echo "before: $before"
if {![string is integer -strict $before]} { echo "not moving: no position"; shutdown; return }
set target [expr {$before + $STEP}]
if {$target < 0 || $target > 1000} { set asked $target; set target [expr {$target < 0 ? 0 : 1000}]; echo "asked $asked, capped at the end of the range: $target" }
echo "MOVE to $target over $DUR ms: status [lindex {OK ERROR BUSY TIMEOUT} [cmd 0 1 $target $DUR]]"
sleep [expr {$DUR + 600}]
echo "after: [pos] (target $target)"
