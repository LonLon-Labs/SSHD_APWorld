; Trampolines for the Infinite Silent Realm Time cheat. The code they jump to is in
; additions/rust-additions.asm (silent_clock_guard, silent_rearm_guard).
;
; Each trampoline replaces the first four instructions (16 bytes) of its game
; function with adrp + add + br, using a PC-relative address to the stub. An
; absolute link address written as a literal would be wrong at runtime: the game
; is loaded at a different base than the link addresses (guest = link -
; 0x7100000000 + 0x8500000), so only PC-relative references survive.

; Countdown function entry (Ghidra 0x7100e938c4).
.offset 0x7100e978c4
adrp x16, silent_clock_guard
add x16, x16, :lo12:silent_clock_guard
br x16
nop

; Chase re-arm function entry (Ghidra 0x7100e94ee8).
.offset 0x7100e98ee8
adrp x16, silent_rearm_guard
add x16, x16, :lo12:silent_rearm_guard
br x16
nop
