; Speed multiplier: scale the walking-speed TARGET instead of the speed value.
;
; The movement function FUN_7100a4cf40 (Ghidra; runtime = Ghidra + 0x4000) keeps
; Link's forward speed in dPlayer+0x64E8 (x21 + 0x4B8 with x21 = dPlayer+0x6030)
; and accelerates it toward a per-state target held in s9: 13.0 by default,
; 23.0 or 34.5 for the faster states. Every path reaches the instruction
; `ldr s0, [x21, #0x4b8]` at Ghidra 0x7100a4d058 with s9 already set, so that
; one site is where the target can be scaled.
;
; The old cheat multiplied the speed value itself each frame. The game reads
; and updates that same value, so the boost compounded every frame. Scaling
; the target instead leaves acceleration and clamping to the game.
;
; Hook: the instruction at 0x7100a51058 becomes `bl` to the stub below. The stub
; saves lr, passes s9 to the landingpad (index 113 -> speed_target_scale_hook in
; cheats.rs), writes the returned scaled target back to s9, then repeats the
; replaced `ldr s0` and returns to the instruction after the site. Only x8 and
; s0 are clobbered, and x8 is dead there (it is reloaded by adrp at the next
; instruction).

; Stub, in the free space after the landingpad stub for index 112.
.offset 0x7100659ca0
stp x29, x30, [sp, #-16]!
fmov s0, s9
mov w8, #113
bl additions_jumptable
fmov s9, s0
ldp x29, x30, [sp], #16
ldr s0, [x21, #0x4b8] ; replaced instruction
ret

; Patch site: Ghidra 0x7100a4d058 + 0x4000.
.offset 0x7100a51058
bl 0x7100659ca0
