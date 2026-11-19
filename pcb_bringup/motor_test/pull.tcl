# With the motors idle (DIR pins are inputs), apply weak pulls and see whether something external holds each DIR line.
set P 0x4800040C; set I 0x48000410
proc rd {a} { expr {[read_memory $a 32 1] + 0} }
lassign [st] ms e1 e2 o1 o2 tr inp
echo "before: armed=[format 0x%x [rd 0x20000010]] out1=[s32 $o1] out2=[s32 $o2] MODERB=[format 0x%08x [rd 0x48000400]]"
if {[rd 0x20000010] != 0 || [s32 $o1] != 0 || [s32 $o2] != 0 || ([rd 0x48000400] & 0x33) != 0} { echo "NOT IDLE, aborting"; shutdown; return }
set p0 [rd $P]
foreach {name pin} {DIR1(PB0) 0 DIR2(PB2) 2} {
  set s [expr {2*$pin}]
  foreach {lab v} {pull-down 2 pull-up 1} {
    mww $P [expr {($p0 & ~(3<<$s)) | ($v<<$s)}]; sleep 30
    set hi 0; for {set i 0} {$i<20} {incr i} { if {[rd $I] & (1<<$pin)} {incr hi} }
    echo "$name weak $lab: reads high $hi/20"
  }
  mww $P $p0
}
echo "restored PUPDR=[format 0x%08x [rd $P]] (was [format 0x%08x $p0])"
