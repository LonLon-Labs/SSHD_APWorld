; Never show Fi text for low health
; NOTE: addresses in the .asm files are runtime addresses = Ghidra + 0x4000.
; 0x7100dc4724 here is 0x7100dc0724 in Ghidra (the vtable call in FUN_7100dc0600,
; the Fi proactive alert chooser).
.offset 0x7100dc4724
mov w0, #1

; Never show Fi text for full wallet
; (0x7100dc0810 in Ghidra)
.offset 0x7100dc4810
mov w0, #1
