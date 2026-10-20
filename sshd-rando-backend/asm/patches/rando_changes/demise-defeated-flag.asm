; Set the Demise-defeated storyflag (784) when BLastBoss (B400) enters its
; "End" (death) state, so the Archipelago client can detect victory even if
; the end cutscenes are skipped.
;
; In dAcBlastboss_c's Down state execute (Ghidra 0x71001ef324), the branch at
; Ghidra 0x71001efae8 starts the "End" animation and sets state 0x32. Its first
; real instruction, `mov w8, #0x32` (Ghidra 0x71001efb14, runtime 0x71001f3b14),
; becomes a call to the stub in jumptable.asm, which calls Rust landingpad 112
; and then performs the replaced `mov w8, #0x32`.
.offset 0x71001f3b14
bl 0x7100659c80
