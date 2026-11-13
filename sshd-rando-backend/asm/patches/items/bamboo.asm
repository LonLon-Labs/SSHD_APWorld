; Small tree (Bamboo) shuffle: game-side hooks for dAcObamboo_c (OBJ_BAMBOO, 0x1AF).
; Ghidra addresses + 0x4000 = runtime addresses (same convention as grass.asm).
; Rust side: item.rs, bamboo_cut_drop_hook (landingpad #121) and bamboo_fall_start_hook
; (landingpad #122). The position table is written by asmpatchhandler (BAMBOO_TABLE_*).
;
; A. Landing drop (Ghidra 0x7100706F28, runtime 0x710070AF28). The Exec function of the
; Fall state runs this `bl` in its landing block. The stub calls the Rust hook first
; (it may write the drop request word at Ghidra 0x7102C23190), then runs the displaced
; `bl` (the vanilla drop fetch 0x7100FA9874, runtime 0x7100FAD874) with x0/x1 intact, so
; the vanilla fetch sees the request. The original return address is 0x710070AF2C.
.offset 0x710070af28
b 0x7100659ff0

; B. Fall start (Fall state init, Ghidra 0x7100706BE4, runtime 0x710070ABE4). Displaced
; instruction: mov w8, #7. The stub records the tree's start position before any physics
; moves it, then replays the displaced instruction and returns to runtime 0x710070ABE8.
.offset 0x710070abe4
b 0x710065a020

; ---- Stub A (landing drop). x19 = tree actor (callee-saved in the Exec function).
; Only x0/x1 are live across the Rust call (they are the inputs of the vanilla fetch).
.offset 0x7100659ff0
stp x29, x30, [sp, #-16]!
stp x0, x1, [sp, #-16]!
mov x0, x19
mov w8, #121
bl additions_jumptable
ldp x0, x1, [sp], #16
ldp x29, x30, [sp], #16
bl 0x7100fad874
movz x30, #0xAF2C
movk x30, #0x0070, lsl #16
movk x30, #0x0071, lsl #32
b 0x710070af2c

; ---- Stub B (fall start). x0 = tree actor at function entry.
.offset 0x710065a020
stp x29, x30, [sp, #-16]!
stp x0, x1, [sp, #-16]!
mov w8, #122
bl additions_jumptable
ldp x0, x1, [sp], #16
ldp x29, x30, [sp], #16
mov w8, #7
b 0x710070abe8
