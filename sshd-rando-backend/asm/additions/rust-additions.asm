; Start using subsdk8 0x500 bytes into the .text section
; 1st 0x500 bytes are left to make sure none of the subsdk setup is mangled
; The next 0x1000 bytes are reserved for the landingpad
; The next 0x500 bytes are reserved for additions not written in rust

; Custom rust functions need to be defined so that they can be correctly linked
; to the function calls in additions-landingpad.asm. Defining one of the rust
; symbols seems to define all of the rest which is nice ^^
.offset 0x712e0a7000
.global main_loop_inject
.type main_loop_inject, @function

; ---------------------------------------------------------------------------
; Infinite Silent Realm Time: asm stubs, reached from the trampolines in
; patches/rando_changes/silent-realm-infinite-time.asm.
;
; Addresses in this file are link addresses. The game runs at a different base,
; so any absolute game address written here must be the guest address:
;     guest = link - 0x7100000000 + 0x8500000
; Only PC-relative references (adrp, adr, ldr literal) are safe to use for
; symbols; the jumps back into the game below use the guest value.
;
; The cheat flag is cheat_flags.infinite_silent_realm_time in AP_IPC_ROOT,
; which is AP_IPC_ROOT + 104 + 23 = AP_IPC_ROOT + 0x7F.
;
; The siren object (dTgSiren_c, pointer in dTgSiren_c__sInstance) keeps its
; trial countdown in its Timekeeper: mCountingUp (running) at +0x3A0 and
; mCountingDown (direction) at +0x3A4. The countdown only subtracts while
; running == 1 and direction == 1.
;
; silent_clock_guard runs at the entry of the countdown function (link
; 0x7100e978c4, guest 0x93978c4) and clears running before the body runs.
;
; silent_rearm_guard runs at the entry of the chase re-arm function (link
; 0x7100e98ee8, guest 0x9398ee8). That function sets mTime = 0 and running = 1
; for the siren object, so with the cheat on it returns 0 for the siren object
; without doing anything.

; Countdown guard. x0 = dTgSiren object.
.global silent_clock_guard
silent_clock_guard:
stp x0, x30, [sp, #-16]!
adrp x9, AP_IPC_ROOT
add x9, x9, :lo12:AP_IPC_ROOT
ldrb w10, [x9, #0x7F]
cbz w10, 1f
adrp x9, dTgSiren_c__sInstance
add x9, x9, :lo12:dTgSiren_c__sInstance
ldr x9, [x9]
cmp x0, x9
b.ne 1f
ldr w10, [x0, #0x3A0]
cmp w10, #1
b.ne 1f
ldr w10, [x0, #0x3A4]
cmp w10, #1
b.ne 1f
str wzr, [x0, #0x3A0]
1:
ldp x0, x30, [sp], #16
; replaced instructions (link 0x7100e978c4..0x7100e978cc)
sub sp, sp, #0xa0
str x25, [sp, #0x50]
stp x24, x23, [sp, #0x60]
stp x22, x21, [sp, #0x70]
; continue at link 0x7100e978d4 = guest 0x93978d4
movz x16, #0x78d4
movk x16, #0x0939, lsl #16
br x16

; Chase re-arm guard. x0 = timekeeper owner (the dTgSiren object).
.global silent_rearm_guard
silent_rearm_guard:
stp x0, x30, [sp, #-16]!
adrp x9, AP_IPC_ROOT
add x9, x9, :lo12:AP_IPC_ROOT
ldrb w10, [x9, #0x7F]
cbz w10, 2f
adrp x9, dTgSiren_c__sInstance
add x9, x9, :lo12:dTgSiren_c__sInstance
ldr x9, [x9]
cmp x0, x9
b.ne 2f
; siren object with the cheat on: do not re-arm the timer
ldp x0, x30, [sp], #16
mov x0, #0
ret
2:
ldp x0, x30, [sp], #16
; link 0x7100e98ee8: adrp x8, <page of the siren pointer>. Same page as the
; original instruction produces at runtime, since the symbol is in that page.
adrp x8, dTgSiren_c__sInstance
; link 0x7100e98eec: ldr x8, [x8, #0xa70]  (the siren pointer)
ldr x8, [x8, #0xa70]
; link 0x7100e98ef0: cbz x8, 0x7100e98f3c
cbz x8, 3f
; link 0x7100e98ef4: adrp x9, <same page>
adrp x9, dTgSiren_c__sInstance
; continue at link 0x7100e98ef8 = guest 0x9398ef8
movz x16, #0x8ef8
movk x16, #0x0939, lsl #16
br x16
3:
; branch taken: link 0x7100e98f3c = guest 0x9398f3c
movz x16, #0x8f3c
movk x16, #0x0939, lsl #16
br x16
