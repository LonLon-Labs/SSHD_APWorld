; Hide the stamina / air gauge while infinite stamina is on.
;
; The stamina wheel and air meter are both drawn by dLytMeterGanbariGauge_c.
; Its execute() is Ghidra 0x7100cce9c0 (runtime = Ghidra + 0x4000, same as
; speed-target-scale.asm). The Rust side is ganbari_gauge_execute_hook in
; lyt.rs, which clears the owner pane's visible bit while infinite stamina is on.
;
; Hook: execute() starts with `sub sp, sp, #0x90`. The patch site is a plain `b`
; (not `bl`) so x30 keeps the real return address, since execute() saves it
; with its prologue. The stub saves x30 and x0, calls the landingpad with
; index 114 (ganbari_gauge_execute_hook), restores everything, runs the
; displaced instruction, and branches back to execute()+4.

; Stub, in free space after the pumpkin delete-branch stub (0x7100659cc0, ~48 bytes).
.offset 0x7100659d00
stp x29, x30, [sp, #-16]!
str x0, [sp, #-16]!
mov w8, #114
bl additions_jumptable
ldr x0, [sp], #16
ldp x29, x30, [sp], #16
sub sp, sp, #0x90 ; replaced instruction (execute() entry)
b 0x7100cd29c4 ; back to execute()+4

; Patch site: execute() entry, Ghidra 0x7100cce9c0 + 0x4000.
.offset 0x7100cd29c0
b 0x7100659d00
