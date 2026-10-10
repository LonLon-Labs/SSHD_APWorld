; Since the additional instruction space is so far away, a jumptable is needed
; to allow branching to this space only using one instruction.
; 
; If you have the space, it is preferred that you don't use this jumptable.
; 
; Ideally, this should only be used when there is no other choice because this
; jumptable is overwriting an actor (dAcNpcSenpaiAMotherLOD_c) that is unused
; in rando.
; 
; For now, only the ctor and init functions are okay to be used. The ctor is
; first and is immediately followed by the init, so the space can be treated
; as one block of code. There are potentially other functions within this
; actor that can be used but more knowledge about this actor is needed before
; they can be used safely.
; 
; dAcNpcSenpaiAMotherLOD_c::ctor starts at:  0x7100659ab0
; dAcNpcSenpaiAMotherLOD_c::init ends at:    0x710065a080
; Total available space (bytes):                  0x5C8
; Total available space (bytes):                   1480 (decimal)
; Total available instructions:                     370 (decimal)
; 
; Please update this:
; Total space used (bytes):                         12C
; Total instructions used:                           35

; startflags
.offset 0x7100659ab0
mov w8, #2
b additions_jumptable

; freestanding item y offset
.offset 0x7100659ab8
mov w8, #4
b additions_jumptable

; Set Stone of Trials placed flag
.offset 0x7100659ac0
mov w8, #8
b additions_jumptable

; Hide spawnable chest after demo appear
; Create dAcTbox::stateDemoAppearLeave function
.offset 0x7100659ac8
mov w8, #36
b additions_jumptable

; End Pumpkin Archery early by hitting the bell
.offset 0x7100659ad0
mov w8, #42
b additions_jumptable

.offset 0x7100659ad8
mov w8, #43
b additions_jumptable

; load custom bzs
.offset 0x7100659ae0
mov w8, #82
b additions_jumptable

; use custom bzs
.offset 0x7100659ae8
mov w8, #83
b additions_jumptable

; Load arcs from romfs/Object/NX where possible
; prefer_object_folder_for_models
.offset 0x7100659af0
mov w8, #95
b additions_jumptable

; Chandelier custom flag wrapper
; Reads Archipelago custom_flag from Chandel actor (x19) params2 bits 8-17,
; sets NEXT_CUSTOM_FLAG/NEXT_CUSTOM_FLAG_PENDING so spawned_actor_traps()
; propagates it to the spawned item, then tail-calls dAcItem__spawnRandoItemWithParams.
; Called via bl from chandelier-item.asm in place of bl dAcItem__spawnRandoItemWithParams.
.offset 0x7100659af8
ldr w8, [x19, #0x12C]
ubfx w8, w8, #8, #10
cmp w8, #0x3FF
b.eq 0x7100659b18
adrp x9, NEXT_CUSTOM_FLAG
strh w8, [x9, #0x7c]
mov w8, #1
strb w8, [x9, #0x7e]

.offset 0x7100659b18
b dAcItem__spawnRandoItemWithParams

; Fi proactive alert override (landingpad index 103).
; Called via bl from fi-cant-drop-down.asm in place of the call to the chooser
; FUN_7100dc0600 inside the player update (FUN_7100a69ccc).
; Runs the vanilla chooser, lets Rust replace its alert id, and when the
; replacement is alert 6000 (ordinary_sword_sprit) sets bit 5 of player+0x63f0
; (the caller tests it at 0x7100a6a294). x23 is player+0x637e at the call site,
; so +0x72 is player+0x63f0. Branchless on purpose: no local labels.
.offset 0x7100659b20
stp x29, x30, [sp, #-16]!
bl fiProactiveAlertChooser
mov w8, #103
bl additions_jumptable
mov w9, #6000
ldrb w10, [x23, #0x72]
orr w11, w10, #0x20
cmp w0, w9
csel w10, w11, w10, eq
strb w10, [x23, #0x72]
ldp x29, x30, [sp], #16
ret

; Fi can't-drop gate (landingpad index 104).
; Replaces `ldrb w8, [x20, #0x41d]` at 0x7100a6a078 (bird gate) and 0x7100a6a320
; (F020 sky branch select) in the player update FUN_7100a69ccc. x20 is the
; player there. Rust returns 1 while the Fi request is pending; w8 then reads
; as 3 ("not on bird"), which passes the bird gate and skips the sky branch.
; Otherwise w8 is the real +0x41d. Clobbers w9, w0-w7, w10-w17 and flags only.
.offset 0x7100659b58
stp x29, x30, [sp, #-16]!
mov w8, #104
bl additions_jumptable
ldp x29, x30, [sp], #16
ldrb w8, [x20, #0x41d]
mov w9, #3
cmp w0, #0
csel w8, w9, w8, ne
ret

; DEBUG (remove after the sky test): entry counter for FUN_7100a69ccc (landingpad
; index 105). Replaces `mov w8, #0x73b0` at 0x7100a69ce8; x0 (the player) is
; preserved across the Rust call.
.offset 0x7100659b80
stp x0, x30, [sp, #-16]!
mov w8, #105
bl additions_jumptable
ldp x0, x30, [sp], #16
mov w8, #0x73b0
ret

; DEBUG (remove after the sky test): wrapper around the event manager's request
; function FUN_7100b70290 (runtime 0x7100b74290), called from the Fi event start
; in the player update at Ghidra 0x7100a6a770 (runtime 0x7100a6e770, patched in
; fi-cant-drop-down.asm). Calls landingpad 106 (x0 = Fi object, x1 = request)
; before and 107 (x0 = result) after, and returns the real result in x0. The
; vanilla call's argument registers x0-x2 are saved around the first hook. The
; cbz-free, label-free layout keeps it independent of local labels.
.offset 0x7100659bd0
stp x29, x30, [sp, #-48]!
stp x0, x1, [sp, #16]
str x2, [sp, #32]
mov w8, #106
bl additions_jumptable
ldp x0, x1, [sp, #16]
ldr x2, [sp, #32]
bl 0x7100b74290
str x0, [sp, #40]
mov w8, #107
bl additions_jumptable
ldr x0, [sp, #40]
ldp x29, x30, [sp], #48
ret

; Pot sanity item drop (landingpad index 108).
; Called via bl from pot.asm in place of the call to checkParam2OnDestroy in
; dAcOtubo_c's Rebirth state. x0-x4 are the vanilla call's arguments; the pot
; actor (x19) is passed as a sixth argument in x5. The Rust function returns
; straight to the pot code (b, not bl, so lr is untouched).
.offset 0x7100659c10
mov x5, x19
mov w8, #108
b additions_jumptable

; File select slot name display stubs (apseed_ui.rs, hooks in
; rando_changes/apseed-slot-name.asm).
;
; File select state + cursor (landingpad index 109). Replaces
; `ldr w8, [x0, #0x29e8]` at runtime 0x7100c18af0 (Ghidra 0x7100c14af0, just
; after the prologue of the file select state function FUN_7100c14ad0, so lr is
; already saved). x0 (the file select scene object) is preserved.
.offset 0x7100659c20
stp x0, x30, [sp, #-16]!
mov w8, #109
bl additions_jumptable
ldp x0, x30, [sp], #16
ldr w8, [x0, #0x29e8]
ret

; Label lookup (landingpad index 110). Replaces `mov x22, x1` at runtime
; 0x7100dbb790 (Ghidra 0x7100db7790, after the prologue of FUN_7100db7770).
; x0 (message file index), x1 (label) and x3 are live there and preserved.
.offset 0x7100659c40
stp x0, x1, [sp, #-32]!
stp x3, x30, [sp, #16]
mov w8, #110
bl additions_jumptable
ldp x3, x30, [sp, #16]
ldp x0, x1, [sp], #32
mov x22, x1
ret

; Label getter epilogue (landingpad index 111). Replaces `mov x0, x19` at runtime
; 0x7100dbb9a0 (Ghidra 0x7100db79a0), the epilogue shared by every return path of
; FUN_7100db7770; x19 is the string pointer it returns (0 when the caller gave its
; own buffer). The Rust hook returns the pointer to use in x0. The function's
; real lr is restored from its stack frame right after, so bl clobbering x30 is fine.
.offset 0x7100659c68
stp x19, x30, [sp, #-16]!
mov x0, x19
mov w8, #111
bl additions_jumptable
ldp x19, x30, [sp], #16
ret

; Actually branches to the rust additions landingpad
; additions_jumptable
.offset 0x710065a070 ; uses 10 instructions
b 0x712e0a5500
