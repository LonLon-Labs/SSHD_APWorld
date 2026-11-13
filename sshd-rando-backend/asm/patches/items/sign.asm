; Sign shuffle: game-side hooks for dAcKanban_c (BZS object "Kanban").
; Ghidra addresses + 0x4000 = runtime addresses (same convention as bamboo.asm).
; Both hooks call into item.rs and use the sign table written by asmpatchhandler (SIGN_TABLE_*).
;
; 1. Wait update (landingpad #124, sign_wait_hook). Drops the sign's item on the rising edge
;    of the hit flag (+0xA00 bit 0). This is the path that works in game.
;    Ghidra 0x71004EF804 -> runtime 0x71004F3804. Displaced instruction: stp x20, x19, [sp, #-0x20]!
;    Return to 0x71004F3808.
.offset 0x71004f3804
b 0x710065a0a0

; Stub (Wait update). x0 = sign actor on entry; x0/x1 are saved around the Rust call.
.offset 0x710065a0a0
stp x29, x30, [sp, #-16]!
stp x0, x1, [sp, #-16]!
mov w8, #124
bl additions_jumptable
ldp x0, x1, [sp], #16
ldp x29, x30, [sp], #16
stp x20, x19, [sp, #-0x20]!
b 0x71004f3808

; 2. PullOut init (landingpad #123, sign_cut_hook). Not seen firing in game. Kept as a backup:
;    the granted list in item.rs stops a double spawn if it ever does.
;    Ghidra 0x71004EFDA8 -> runtime 0x71004F3DA8. Displaced instruction: stp x20, x19, [sp, #-0x20]!
;    Return to 0x71004F3DAC.
.offset 0x71004f3da8
b 0x710065a040

; Stub (PullOut init). x0 = sign actor on entry.
.offset 0x710065a040
stp x29, x30, [sp, #-16]!
stp x0, x1, [sp, #-16]!
mov w8, #123
bl additions_jumptable
ldp x0, x1, [sp], #16
ldp x29, x30, [sp], #16
stp x20, x19, [sp, #-0x20]!
b 0x71004f3dac
