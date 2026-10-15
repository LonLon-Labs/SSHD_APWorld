; File select slot name display hooks (see apseed_ui.rs). Stubs are at the end of
; jumptable.asm (0x7100659c20 - 0x7100659c80), landingpad indices 109-111.
;
; Offsets are runtime addresses (Ghidra address + 0x4000).

; File select state function FUN_7100c14ad0 (Ghidra), right after the
; prologue: replaces `ldr w8, [x0, #0x29e8]`. Tracks the cursor.
.offset 0x7100c18af0
bl 0x7100659c20

; Get-text-by-label FUN_7100db7770 (Ghidra), right after the prologue and the
; argument moves: replaces `mov x22, x1`. Notes whether the lookup is for the
; file select captions.
.offset 0x7100dbb790
bl 0x7100659c40

; Label getter FUN_7100db7770 (Ghidra), shared epilogue: replaces `mov x0, x19`
; (x19 = the string pointer it returns). Lets the file select caption be swapped
; for the hovered save's slot name.
.offset 0x7100dbb9a0
bl 0x7100659c68
