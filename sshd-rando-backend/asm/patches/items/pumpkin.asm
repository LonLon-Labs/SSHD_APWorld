; Pumpkin shuffle: a patched pumpkin drops its randomized item on every break,
; not only when the break routine takes its "drop" branch.
;
; dAcPumpkin_c's break routine (Ghidra FUN_7100af5a7c, runtime = Ghidra +
; 0x4000) has two branches, chosen by a set of player/game-state flags:
;
;   drop branch (flags unusual, e.g. a sword hit):
;     calls checkParam2OnDestroy with the vanilla drop id (top byte of params2)
;     -> hooked at runtime 0x7100af9e38 below.
;
;   delete branch (flags normal, e.g. a thrown pumpkin):
;     sets the params2 top byte to 0xFF and deletes the actor without calling
;     the drop function, so a thrown pumpkin never drops anything.
;     -> hooked at runtime 0x7100af9d98 below, which runs the same drop
;        through the pot landingpad before the delete.
;
; Both hooks call pot_spawn_custom_item (landingpad 108, pot.asm / jumptable.asm),
; which looks the pumpkin up by position in the patcher-written table.
; Passing w3 = 2 tells Rust this is the delete branch, so when the custom drop
; doesn't happen it must not fall back to the vanilla drop (the delete branch
; never dropped anything vanilla).
;
; Register state at the drop-branch call matches the pot call sites: x19 = the
; pumpkin actor, w0 = params2 top byte (vanilla drop id), w1 = room id,
; x2 = actor pos, w3 = 1, x4 = pointer to a zeroed u16 on the stack.

; Drop branch: replace the checkParam2OnDestroy call (Ghidra 0x7100af5e38).
.offset 0x7100af9e38
bl 0x7100659c10

; Delete branch: replace `ldr w8, [x19, #0x12c]` (Ghidra 0x7100af5d98) with a
; branch to the stub below. The stub reloads w8 and returns to the original
; `orr w8, w8, #0xff000000` at runtime 0x7100af9d9c.
.offset 0x7100af9d98
b 0x7100659cc0

; Delete-branch stub (free space after the speed-target-scale stub, which ends
; at 0x7100659cc0). Clobbers x0-x4, x8 and the stack slot at sp+0x20, which the
; original branch also uses.
.offset 0x7100659cc0
strh wzr, [sp, #0x20]
add x4, sp, #0x20
ldr w8, [x19, #0x12c]
lsr w0, w8, #0x18
ldrsb w1, [x19, #0x17c]
add x2, x19, #0x144
mov w3, #2
stp x29, x30, [sp, #-16]!
bl 0x7100659c10
ldp x29, x30, [sp], #16
ldr w8, [x19, #0x12c]
b 0x7100af9d9c
