; Pumpkin shuffle: replace the checkParam2OnDestroy call in dAcPumpkin_c's break
; routine (Ghidra FUN_7100af5a7c) with the pot landingpad stub (jumptable.asm,
; landingpad index 108), so a patched pumpkin drops its randomized item instead
; of the vanilla one (see pot_spawn_custom_item in item.rs, which also accepts
; the PUMPKIN actor id).
;
; Register state at the call matches the pot call sites: x19 = the pumpkin actor
; (the stub passes it as a sixth argument), w0 = params2 top byte (vanilla drop
; id), w1 = room id, x2 = actor pos, w3 = 1, x4 = pointer to a zeroed u16 on the
; stack. The runtime address is the Ghidra address + 0x4000 (same as pots).
;
; UNVERIFIED: this call sits in the branch of the break routine that runs when
; the game-state globals (DAT_710182ded8 etc.) are in an unusual state. The
; other branch sets the params2 top byte to 0xFF and deletes the actor without
; dropping anything. pot_spawn_custom_item logs "pumpkin drop hook" when it
; sees a pumpkin, to check whether this hook fires during normal play.

.offset 0x7100af9e38
bl 0x7100659c10
