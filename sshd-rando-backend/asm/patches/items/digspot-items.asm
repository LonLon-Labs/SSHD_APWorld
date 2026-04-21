; Always set digspot sceneflag, even if it's not a key piece.
.offset 0x71008eed2c
nop
nop

.offset 0x71008ef8a8 ; dAcOsoil::update
ldrb w0, [x19, #0x12F] ; load itemid from param2 bits 24-31

.offset 0x71008ed32c ; dAcOsoil::stateSoilUpdate
ldrb w0, [x19, #0x12F] ; load itemid from param2 bits 24-31


; handle traps
.offset 0x71008ef93c ; dAcOsoil::update
mov w8, #53
bl additions_jumptable

; The vanilla spawnItemWithParams at 0x71004eba84 has a rando patch that
; forces bit 9 on (orr w19, w1, #0x200).  This makes the spawned item go
; through the rando init path so handle_custom_item_get picks up the
; custom flag propagated by spawned_actor_traps.
; We must NOT replace this call with spawnRandoItemWithParams because that
; function preserves bit 9 instead of forcing it, and dAcOsoil doesn't
; set bit 9 in param1 — so the item would skip rando init entirely.

.offset 0x71008ed3c0
mov w8, #53
bl additions_jumptable
