; Pot sanity: replace the checkParam2OnDestroy calls that drop a pot's vanilla
; item so patched pots drop their randomized item instead (see
; pot_spawn_custom_item in item.rs). The stub is in jumptable.asm (landingpad
; index 108). Both call sites have the actor in x19 and the vanilla arguments in
; w0-x4 (w0 = param2 top byte, w1 = room id, x2 = position, w3 = 0, x4 = rot.y
; copy); the stub passes x19 as a sixth argument.

; Shared object base-class update (Ghidra 0x7100ec645c). This is the drop path
; for almost every pot: 314 of 318 pots have param1 bits 14-15 set, which keeps
; them out of dAcOtubo_c's Rebirth state. It runs for many actor types, so the
; Rust side checks the actor id. The caller tests bit 0 of the result.
.offset 0x7100eca45c
bl 0x7100659c10

; dAcOtubo_c Rebirth state init (Ghidra 0x71009b56a4), the 4 pots in D301
; with param1 bits 14-15 clear. The result is ignored here.
.offset 0x71009b96a4
bl 0x7100659c10
