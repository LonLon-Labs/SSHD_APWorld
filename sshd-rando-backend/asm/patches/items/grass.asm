; Grass shuffle: game-side hooks for dTgMassObj_c (grass patches).
; Ghidra addresses + 0x4000 = runtime addresses.
; Rust side: item.rs, grass_patch_begin_hook / grass_spawn_skip_hook /
; grass_blade_init_hook / grass_cut_drop_hook (landingpads #117, #118, #116, #115).
; Blade value at blade base + 0x38 (instance + 0x24); patch params2 at +0x12C.
; The blade base is x8 at the blade site and x24 at the cut site (instance - 0x14).

; A. dTgMassObj_c::actorPostCreate entry (Ghidra 0x7100e75c14, runtime 0x7100e79c14).
; Displaced instruction: sub sp, sp, #0x1c0. The stub saves x30 because the
; prologue has not saved it yet.
.offset 0x7100e79c14
b 0x7100659e40

; B. spawnSingleGrass entry (Ghidra 0x7100e7c604, runtime 0x7100e80604).
; x0 = the patch. The hook loads this patch's own item before its blades are made.
; Displaced instruction: ldr x8, [x0, #0x58]. Returns false for a collected
; patch so its blades are never created.
.offset 0x7100e80604
b 0x7100659ec0

; C. Blade creation (Ghidra 0x7100e7c74c, runtime 0x7100e8074c).
; Replaces `str s0, [x8, #0x38]` (x8 = blade base). The original store runs in
; the stub, then the Rust hook overwrites the slot with the patch value.
.offset 0x7100e8074c
b 0x7100659d20

; D. checkForHit cut branch (Ghidra 0x7100e7b428, runtime 0x7100e7f428).
; Replaces `bl checkParam2OnDestroy`. x24 = blade base at this call site.
.offset 0x7100e7f428
bl 0x7100659e20

; E. checkForHit drop gate (Ghidra 0x7100e7a178, runtime 0x7100e7e178).
; `tbnz w8, #1` sends a cut whose object has bit 1 of [x22 + 0x3D] set to the path
; that never reaches the cut drop call (landingpad #115). NOP it so every cut
; reaches the drop call. grass_cut_drop_hook returns the vanilla drop for any
; patch that is not shuffled, so vanilla behaviour is kept for those.
.offset 0x7100e7e178
nop

; ---- Stubs ----

; C stub (landingpad #116). Preserves x0-x17 around the call. The float store
; comes first; the scratch d-registers are dead here (no float reads after it).
.offset 0x7100659d20
str s0, [x8, #0x38]
stp x29, x30, [sp, #-16]!
stp x0, x1, [sp, #-16]!
stp x2, x3, [sp, #-16]!
stp x4, x5, [sp, #-16]!
stp x6, x7, [sp, #-16]!
stp x8, x9, [sp, #-16]!
stp x10, x11, [sp, #-16]!
stp x12, x13, [sp, #-16]!
stp x14, x15, [sp, #-16]!
stp x16, x17, [sp, #-16]!
mov x0, x8
mov w8, #116
bl additions_jumptable
ldp x16, x17, [sp], #16
ldp x14, x15, [sp], #16
ldp x12, x13, [sp], #16
ldp x10, x11, [sp], #16
ldp x8, x9, [sp], #16
ldp x6, x7, [sp], #16
ldp x4, x5, [sp], #16
ldp x2, x3, [sp], #16
ldp x0, x1, [sp], #16
ldp x29, x30, [sp], #16
b 0x7100e80750

; D stub (landingpad #115). Tail-calls the Rust hook with x5 = blade base, so the
; hook returns straight to the caller (lr is the return address of the bl at D).
.offset 0x7100659e20
mov x5, x24
mov w8, #115
b additions_jumptable

; A stub (landingpad #117). Saves x0-x7 and x30, calls the Rust hook with
; x0 = patch actor, then replays `sub sp, sp, #0x1c0` and goes back to entry+4.
.offset 0x7100659e40
stp x29, x30, [sp, #-16]!
stp x0, x1, [sp, #-16]!
stp x2, x3, [sp, #-16]!
stp x4, x5, [sp, #-16]!
stp x6, x7, [sp, #-16]!
mov w8, #117
bl additions_jumptable
ldp x6, x7, [sp], #16
ldp x4, x5, [sp], #16
ldp x2, x3, [sp], #16
ldp x0, x1, [sp], #16
ldp x29, x30, [sp], #16
sub sp, sp, #0x1c0
b 0x7100e79c18

; B stub (landingpad #118). The Rust hook returns 1 to skip (w9 keeps the result
; because x0 is restored after the call). Otherwise replays `ldr x8, [x0, #0x58]`
; and goes back to the cbz at spawnSingleGrass+4.
; Return codes: 0 = normal, 1 = skip and report failure (caller stops),
; 2 = report success without creating blades (caller continues).
.offset 0x7100659ec0
stp x29, x30, [sp, #-16]!
stp x0, x1, [sp, #-16]!
stp x2, x3, [sp, #-16]!
stp x4, x5, [sp, #-16]!
stp x6, x7, [sp, #-16]!
mov w8, #118
bl additions_jumptable
mov w9, w0
ldp x6, x7, [sp], #16
ldp x4, x5, [sp], #16
ldp x2, x3, [sp], #16
ldp x0, x1, [sp], #16
ldp x29, x30, [sp], #16
cmp w9, #2
b.eq 0x7100659f20
cbnz w9, 0x7100659f10
ldr x8, [x0, #0x58]
b 0x7100e80608

; B skip path: spawnSingleGrass returns false (w0 = 0), so the caller stops.
.offset 0x7100659f10
mov w0, wzr
ret

; B success-no-op path (return code 2): spawnSingleGrass returns true (w0 = 1)
; without touching the grass-kind pool, so the candidate loop keeps running.
.offset 0x7100659f20
mov w0, #1
ret
