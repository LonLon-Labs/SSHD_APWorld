; Grass RNG determinism for dTgMassObj_c (grass patches).
;
; Problem: grass candidate and blade jitter draw from the global LCG state at
; DAT_71016883e0 (read as [x23, #0x3e0] / [x11, #0x3e0]). Many other game functions
; also advance that state, so the blade count and placement for the same patch
; differ between loads.
;
; Fix: at each confirmed read site, replace the state load with a branch to a stub
; that derives the value from the position the draw is for. Stubs use only x16/x17
; (IP scratch), so live registers are preserved. No pointer is hashed, because heap
; addresses change between loads.
;
; ADDRESSES ARE RUNTIME (Ghidra + 0x4000), same convention as grass.asm.
;   Site A: Ghidra 0x7100e7c294 -> runtime 0x7100e80294  (ldr w8, [x23,#0x3e0])
;   Site B: Ghidra 0x7100e7c45c -> runtime 0x7100e8045c  (ldr w8, [x23,#0x3e0])
;   Site C: Ghidra 0x7100e7c698 -> runtime 0x7100e80698  (ldr w12, [x11,#0x3e0])
;
; Sites A and B are the candidate-jitter draws in FUN_7100e7c1ac, which decide the
; blade count. Site C is the per-blade jitter in FUN_7100e7c604.
;
; NOT COVERED: FUN_7100e789e8 (cut/hit check, cosmetic) and the inline reads in
; actorPostCreate (believed cosmetic per-blade init). Verify with the two-load test.
;
; Stub addresses are in the 0x7100659xxx patch stub area. Existing grass stubs end at
; 0x7100659f18. The build's overlap check covers the whole patches/ group, so any
; collision with another patch file fails the build rather than silently patching.

; ---- Site A ----
.offset 0x7100e80294
b 0x7100659f40

; ---- Site B ----
.offset 0x7100e8045c
b 0x7100659f80

; ---- Site C ----
.offset 0x7100e80698
b 0x7100659fc0

; ---- Stub A ----
.offset 0x7100659f40
fmov w16, s14
fmov w17, s10
eor w16, w16, w17, lsl #13
eor w16, w16, w16, lsr #17
eor w16, w16, w16, lsl #5
eor w16, w16, w17, ror #11
eor w16, w16, w16, lsr #15
eor w16, w16, w16, lsl #7
mov w8, w16
b 0x7100e80298

; ---- Stub B ----
.offset 0x7100659f80
fmov w16, s14
fmov w17, s10
eor w16, w16, w17, lsl #13
eor w16, w16, w16, lsr #17
eor w16, w16, w16, lsl #5
eor w16, w16, w17, ror #11
eor w16, w16, w16, lsr #15
eor w16, w16, w16, lsl #7
mov w8, w16
b 0x7100e80460

; ---- Stub C ----
.offset 0x7100659fc0
ldr w16, [x2]
ldr w17, [x2, #8]
eor w16, w16, w17, lsl #13
eor w16, w16, w16, lsr #17
eor w16, w16, w16, lsl #5
ldr w17, [x2, #4]
eor w16, w16, w17, ror #11
eor w16, w16, w16, lsr #15
eor w16, w16, w16, lsl #7
mov w12, w16
b 0x7100e8069c

; ---- Site D (inline candidate loop in actorPostCreate) ----
; Ghidra 0x7100e774f0 = runtime 0x7100e7b4f0. This is `ldr w8, [x26, #0x3e0]`, the
; global LCG read of the inline candidate/blade placement loop. Found by decompiling
; FUN_7100e75c14: it is not covered by sites A-C above. The stub below calls the
; hash routine (landingpad index 120, grass_inline_rng_hook) through
; additions_jumptable, then returns to the instruction after the site.
.offset 0x7100e7b4f0
b 0x7100659f68

; Site D stub. Fits in the free gap between stub A (0x7100659f40) and stub B
; (0x7100659f80). Saves lr, sets w8 = hash via the landingpad, returns to
; runtime 0x7100e7b4f4 (the instruction after the site).
.offset 0x7100659f68
stp x29, x30, [sp, #-16]!
mov w8, #120
bl additions_jumptable
ldp x29, x30, [sp], #16
b 0x7100e7b4f4
