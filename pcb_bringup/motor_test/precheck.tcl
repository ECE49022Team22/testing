# Link sanity, then: are the PWM lines held low from outside? (they float during reset/flash)
proc rd {a} { expr {[read_memory $a 32 1] + 0} }
echo "IDCODE [format 0x%08x [rd 0x40015800]]  flash [expr {[read_memory 0x1FFFF7CC 16 1]+0}] KB  RDP/OBR [format 0x%08x [rd 0x4002201C]]"
status
if {[rd 0x20000010] != 0 || [s32 [lindex [st] 3]] != 0 || [s32 [lindex [st] 4]] != 0} { echo "PRECHECK FAIL: not idle"; shutdown; return }
set M 0x48000000; set P 0x4800000C; set I 0x48000010
set m0 [rd $M]; set p0 [rd $P]
mww $P [expr {($p0 & ~0xF000) | 0x5000}]
mww $M [expr {$m0 & ~0xF000}]
set a [rd $I]; set b [rd $I]; set c [rd $I]
mww $M $m0; mww $P $p0
set v [expr {$a | $b | $c}]
echo "restored MODERA=[format 0x%08x [rd $M]] PUPDRA=[format 0x%08x [rd $P]]"
echo "PWM lines under a brief weak pull-up: PWM1(PA6)=[expr {($v>>6)&1}] PWM2(PA7)=[expr {($v>>7)&1}]"
echo [expr {($v & 0xC0) == 0 ? "PRECHECK PASS" : "PRECHECK FAIL: a PWM line is not held low"}]
