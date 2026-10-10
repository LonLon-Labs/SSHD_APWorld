#![allow(non_camel_case_types)]
#![allow(non_snake_case)]
#![allow(unused)]

// File select screen: show the hovered save file's own Archipelago slot name
// in the caption line (SYS_CAPTION_01) and in the "start this quest?" dialog
// caption (SYS_CAPTION_04), instead of the rando hash.
//
// How it works (addresses are Ghidra addresses, patches use Ghidra + 0x4000;
// the hooks are in patches/rando_changes/apseed-slot-name.asm):
//   1. apseed_ui_fs_hook runs every frame inside the file select state
//      function FUN_7100c14ad0. When the cursor (scene data +0x5dd8) changes
//      it picks the name to show (HOVER_NAME) and calls FUN_7100bcb7b4(ui, 0),
//      the function that fetches the caption label (ui+0x9e8) and pushes it to
//      the text boxes. Nothing else re-fetches the caption on a cursor move,
//      and the dirty flag (+0xa58) store is conditional (tbz on a vtable call
//      result at 0x7100c172fc) and is never reached on this screen, so the
//      refresh is driven directly.
//   2. apseed_ui_label_hook (entry of the label getter FUN_7100db7770) notes
//      whether the lookup is for one of the two captions.
//   3. apseed_ui_label_ret_hook (shared epilogue of FUN_7100db7770,
//      0x7100db79a0) swaps the returned string for HOVER_NAME. The getter's
//      output buffer is native-endian UTF-16 (the epilogue code compares it
//      with ldrh against 0x000A), so HOVER_NAME is plain little-endian u16
//      text, NUL terminated.

use crate::savefile;

use core::ffi::{c_char, c_void};

extern "C" {
    /// Pointer to a struct whose +0x138 is the UI text manager.
    static UI_ROOT_PTR: *const u8;
    /// FUN_7100bcb7b4(ui, which). which = 0 updates the caption text boxes.
    fn FileSelectText__update(ui: *mut u8, which: u32);
}

// File select scene object (param_1 of FUN_7100c14ad0).
const FS_STATE: usize = 0x29E8;
const FS_STATE_MENU: i32 = 0; // file menu, cursor moves freely
const FS_SCENE_DATA: usize = 0x638;
const SCENE_CURSOR: usize = 0x5DD8; // i32: 0-3 = file, -1 = none, others = buttons

// UI manager = *(UI_ROOT_PTR + 0x138).
const UI_TEXT_MGR: usize = 0x138;
const UI_LAYOUT: usize = 0xB8; // layout object the text boxes are looked up in

/// Main loop frames without a file select hook call before the screen counts
/// as left and the override is dropped.
const FS_TIMEOUT: u32 = 10;

/// True while HOVER_NAME should replace the caption.
static mut HOVER_ACTIVE: bool = false;
/// Name to show: native-endian UTF-16, NUL terminated (17 chars + NUL).
static mut HOVER_NAME: [u16; 18] = [0; 18];
static mut LAST_CURSOR: i32 = i32::MIN;
/// Counts down once per main loop frame; refilled by every hook call.
static mut FS_ALIVE: u32 = 0;
/// Set by the label getter's entry hook: this lookup is one of the captions.
static mut LOOKUP_IS_CAPTION: bool = false;

/// Cursor value -> save manager slot index (identical).
fn cursor_to_slot(cursor: i32) -> Option<usize> {
    if (0..savefile::SLOT_COUNT as i32).contains(&cursor) {
        Some(cursor as usize)
    } else {
        None
    }
}

/// Name a slot should show: its own stored name, else the installed patch's.
fn name_for_slot(slot: usize) -> [u16; 17] {
    if let Some(data) = savefile::slot_ap_save_data(slot) {
        let name = data.slot_name;
        if data.magic == savefile::AP_SAVE_MAGIC && name[0] != 0 {
            return name;
        }
    }
    savefile::patched_slot_name()
}

/// Fills HOVER_NAME for `slot`; control characters are dropped so the text
/// parser cannot see escape codes.
unsafe fn set_hover(slot: usize) {
    let name = name_for_slot(slot);
    let mut out = [0u16; 18];
    let mut n = 0;
    for c in name.iter() {
        if *c == 0 {
            break;
        }
        if *c < 0x20 {
            continue;
        }
        out[n] = *c;
        n += 1;
    }
    HOVER_NAME = out;
    HOVER_ACTIVE = n > 0;
}

unsafe fn text_mgr() -> *mut u8 {
    if UI_ROOT_PTR.is_null() {
        return core::ptr::null_mut();
    }
    let ui = (UI_ROOT_PTR.add(UI_TEXT_MGR) as *const u64).read_unaligned() as *mut u8;
    if ui.is_null() {
        return core::ptr::null_mut();
    }
    // The caption text boxes are looked up in the layout; no layout yet means
    // the screen is still being built.
    if (ui.add(UI_LAYOUT) as *const u64).read_unaligned() == 0 {
        return core::ptr::null_mut();
    }
    ui
}

/// Re-runs the caption fetch + text box update.
unsafe fn refresh_caption() {
    let ui = text_mgr();
    if ui.is_null() {
        return;
    }
    FileSelectText__update(ui, 0);
}

unsafe fn cstr_eq(string: *const c_char, expected: &[u8]) -> bool {
    for (i, e) in expected.iter().enumerate() {
        if *(string as *const u8).add(i) != *e {
            return false;
        }
    }
    true
}

/// Called every main loop frame (mainloop::main_loop_inject).
pub fn tick() {
    unsafe {
        if FS_ALIVE == 0 {
            return;
        }
        FS_ALIVE -= 1;
        if FS_ALIVE == 0 {
            // File select was left: stop overriding captions elsewhere and
            // start fresh next time.
            HOVER_ACTIVE = false;
            LAST_CURSOR = i32::MIN;
            LOOKUP_IS_CAPTION = false;
        }
    }
}

/// Landingpad 109: inside the file select state function FUN_7100c14ad0,
/// right after its prologue. `this` is the file select scene object.
#[no_mangle]
pub extern "C" fn apseed_ui_fs_hook(this: *const u8) {
    if this.is_null() {
        return;
    }
    unsafe {
        FS_ALIVE = FS_TIMEOUT;

        let state = (this.add(FS_STATE) as *const i32).read_unaligned();
        if state != FS_STATE_MENU {
            return;
        }
        let scene = (this.add(FS_SCENE_DATA) as *const u64).read_unaligned() as *const u8;
        if scene.is_null() {
            return;
        }
        let cursor = (scene.add(SCENE_CURSOR) as *const i32).read_unaligned();
        if cursor == LAST_CURSOR {
            return;
        }
        LAST_CURSOR = cursor;

        match cursor_to_slot(cursor) {
            Some(slot) => set_hover(slot),
            None => HOVER_ACTIVE = false,
        }
        refresh_caption();
    }
}

/// Landingpad 110: entry of the label getter FUN_7100db7770 (after the
/// argument moves). `label` is the label C string.
#[no_mangle]
pub extern "C" fn apseed_ui_label_hook(msg_file_index: u32, label: *const c_char) {
    unsafe {
        // 01 = file select caption, 04 = the "start this quest?" dialog; both are
        // where add_rando_hash puts the rando hash (text indices 66 / 69).
        LOOKUP_IS_CAPTION = HOVER_ACTIVE
            && !label.is_null()
            && (cstr_eq(label, b"SYS_CAPTION_01\0") || cstr_eq(label, b"SYS_CAPTION_04\0"));
    }
}

/// Landingpad 111: shared epilogue of FUN_7100db7770. `result` is the pointer
/// the getter is about to return (its formatted string buffer, or 0 when the
/// caller supplied its own buffer). Returns the pointer to hand back instead.
#[no_mangle]
pub extern "C" fn apseed_ui_label_ret_hook(result: *const u16) -> *const u16 {
    unsafe {
        let is_caption = LOOKUP_IS_CAPTION;
        LOOKUP_IS_CAPTION = false;
        if is_caption && HOVER_ACTIVE && !result.is_null() {
            return core::ptr::addr_of!(HOVER_NAME) as *const u16;
        }
    }
    result
}
