# Weak internal pulls on the four encoder inputs (still in timer AF mode). A pin really driven by U9/U10 ignores them;
# a disconnected pin follows them. Restores the pull registers afterwards.
proc rd {a} { expr {[read_memory $a 32 1] + 0} }
set PA 0x4800000C; set PB 0x4800040C
set pa0 [rd $PA]; set pb0 [rd $PB]
set chans {{M1_A PA15 A 15} {M1_B PB3 B 3} {M2_A PA8 A 8} {M2_B PA9 A 9}}
foreach c $chans {
  lassign $c name pin port n
  set reg [expr {$port eq "A" ? $PA : $PB}]; set base [expr {$port eq "A" ? $pa0 : $pb0}]; set idr [expr {$port eq "A" ? 0x48000010 : 0x48000410}]
  set res {}
  foreach {lab v} {down 2 up 1} {
    mww $reg [expr {($base & ~(3 << (2*$n))) | ($v << (2*$n))}]; sleep 30
    set hi 0; for {set i 0} {$i < 20} {incr i} { if {[rd $idr] & (1 << $n)} {incr hi} }
    lappend res "pull-$lab: high $hi/20"
  }
  mww $reg $base
  echo "$name ($pin): [join $res {, }]"
}
echo "restored PUPDRA=[format 0x%08x [rd $PA]] (was [format 0x%08x $pa0]) PUPDRB=[format 0x%08x [rd $PB]] (was [format 0x%08x $pb0])"
