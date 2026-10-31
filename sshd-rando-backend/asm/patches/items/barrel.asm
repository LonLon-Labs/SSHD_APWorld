; Barrel shuffle: route every barrel break through the pot landingpad stub
; (jumptable.asm, landingpad index 108 -> pot_spawn_custom_item in item.rs, which
; gets a barrel branch driven by a position-keyed table).
;
; dAcOBarrel_c (actor 0x209) reaches checkParam2OnDestroy (Ghidra 0x7100b8fbe4)
; from three places. Register state at each call matches the pot call sites:
; x19 = barrel actor (the stub passes it as a sixth argument), w0 = params2 top
; byte (vanilla drop id), w1 = room id, x2 = actor pos, w3 = 0, x4 = pointer to a
; zeroed u16 on the stack. Runtime address = Ghidra address + 0x4000.
;
;   1. Main break routine (Ghidra FUN_7100716388, call at 0x7100716a48).
;   2. Timed destroy (function at Ghidra 0x7100715a5c, call at 0x7100715ae0).
;   3. Rebirth respawn (function at Ghidra 0x7100715c70, call at 0x7100715ca8).
;
; Sites 1 and 2 are guarded by a "has a drop" byte at actor+0x135f (0 for the
; 207 barrels with drop mode 2/3, which drop nothing in vanilla). The guard
; branch is NOPed so every barrel reaches the stub; the Rust barrel branch
; re-checks actor+0x135f itself and only falls back to checkParam2OnDestroy when
; the barrel is not in the table and the byte is non-zero, so unpatched barrels
; keep their vanilla behavior.
;
; Bomb barrels (type 1, the exploding Sand Sea barrels) are deliberately NOT
; shuffled: their explosion branch never reaches the drop call, and they are not
; table entries. The quest barrels (Normal, henya mode <= 1) ARE shuffled: they
; can be broken before or after the quest.

; Site 1: guard `cbz w8, <skip drop>` (was E8 01 00 34) -> nop
.offset 0x710071aa10
nop

; Site 1: drop call
.offset 0x710071aa48
bl 0x7100659c10

; Site 2: guard `cbz w8, <skip drop>` (was E8 01 00 34) -> nop
.offset 0x7100719aa8
nop

; Site 2: drop call
.offset 0x7100719ae0
bl 0x7100659c10

; Site 3: rebirth drop call (no guard)
.offset 0x7100719ca8
bl 0x7100659c10
