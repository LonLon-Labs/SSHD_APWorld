; Fi "can't drop down" message when stepping into a light pillar with no
; droppable Bird Statue.
;
; The pillar hook (voidout_near_skyloft_or_light_pillars_without_sailcloth,
; name kept for the landingpad symbol; it no longer voids out) is also used for
; the no-Sailcloth case (SCEN types 5 and 9). It
; only sets the plain byte FI_CANT_DROP_PENDING. The vanilla player update
; (FUN_7100a69ccc) asks the Fi proactive alert chooser (FUN_7100dc0600) every
; frame whether Fi should speak. This replaces that one call with a stub that
; runs the vanilla chooser and then, if the byte is set, returns alert id
; 6000 ("ordinary_sword_sprit"). The game then starts that Fi event itself, and
; the patched 006-8KenseiNormal flow (eventpatches.yaml) uses custom command 82
; to show the custom text and command 83 to mark the message finished. There is
; no void-out; a ~10 s cooldown stops the message re-triggering at once.
;
; Only this call site is hooked; the other caller of the chooser (0x7100cb1378 in
; Ghidra) is untouched. The stub lives in jumptable.asm (index 103 in the landingpad).
;
; ADDRESSES: .offset values in this file are runtime addresses = Ghidra + 0x4000.
; The Ghidra address is given in each comment. The bl targets (0x7100659b20 etc.)
; are stubs in jumptable.asm, which is also written in runtime addresses.
; Ghidra 0x7100a6a20c
.offset 0x7100a6e20c
bl 0x7100659b20

; The vanilla player update only reaches the chooser call above when the "bird
; gate" passes (player+0x41d == 3, or == 2 with a target at +0x5518), which
; never holds on the Loftwing without a lock-on. These two loads of
; player+0x41d are replaced by a stub (jumptable.asm, landingpad index 104)
; that returns 3 while a Fi request is pending and the real value otherwise:
;   Ghidra 0x7100a6a078 (runtime 0x7100a6e078): feeds the `cmp #3; b.eq` bird
;                 gate, so it passes.
;   Ghidra 0x7100a6a320 (runtime 0x7100a6e320): feeds the `cmp #2` that picks the
;                 F020 sky branch (fays_sky_talk, needs a target), so the ordinary
;                 no-target path at Ghidra 0x7100a6a374 runs instead.
; Both originals are `ldrb w8, [x20, #0x41d]`.
.offset 0x7100a6e078
bl 0x7100659b58

.offset 0x7100a6e320
bl 0x7100659b58

; DEBUG: counts entries of the player update
; (replaces `mov w8, #0x73b0` at the top of FUN_7100a69ccc; stub in jumptable.asm).
; Ghidra 0x7100a69ce8
.offset 0x7100a6dce8
bl 0x7100659b80

; DEBUG: wraps the game's own event request call so
; the request, its result and the event manager state get logged. Replaces
; `bl 0x7100b70290` (FUN_7100b70290, the event manager's request function) at
; Ghidra 0x7100a6a770. The stub (jumptable.asm, 0x7100659bd0) calls the real
; function at its runtime address 0x7100b74290 and returns its result.
; Ghidra 0x7100a6a770
.offset 0x7100a6e770
bl 0x7100659bd0

; FUN_7100a69ccc runs every frame in the sky (the entry counter shows it), so no
; extra call is needed from the main loop. It only stops being called once the
; player leaves the flight state (the Loftwing drop-in case, which is handled
; separately).
