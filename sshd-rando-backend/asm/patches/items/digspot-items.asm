; Always set digspot sceneflag, even if it's not a key piece.
.offset 0x71008eed2c
nop
nop

.offset 0x71008ef8a8 ; dAcOsoil::update
ldrb w0, [x19, #0x12C] ; load 00 00 00 FF from param2 (the patched itemid)

.offset 0x71008ed32c ; dAcOsoil::stateSoilUpdate
ldrb w0, [x19, #0x12C] ; load 00 00 00 FF from param2 (the patched itemid)


; handle traps
.offset 0x71008ef93c ; dAcOsoil::update
mov w8, #53
bl additions_jumptable

; Use spawnRandoItemWithParams to preserve bit 9 so the item goes through
; the rando init path and handle_custom_item_get sets the custom flag.
.offset 0x71008ef944 ; dAcOsoil::update - spawn item call
bl dAcItem__spawnRandoItemWithParams

.offset 0x71008ed3c0
mov w8, #53
bl additions_jumptable

; Same fix for stateSoilUpdate path
.offset 0x71008ed3c8 ; dAcOsoil::stateSoilUpdate - spawn item call
bl dAcItem__spawnRandoItemWithParams
