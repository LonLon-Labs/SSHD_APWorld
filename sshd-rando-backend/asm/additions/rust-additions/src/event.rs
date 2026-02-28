#![allow(non_camel_case_types)]
#![allow(non_snake_case)]
#![allow(unused)]

use crate::actor;
use crate::debug;
use crate::entrance;
use crate::fix;
use crate::flag;
use crate::input;
use crate::item;
use crate::lyt;
use crate::minigame;
use crate::savefile;
use crate::traps;

use core::arch::asm;
use core::ffi::{c_char, c_void};
use static_assertions::assert_eq_size;

// repr(C) prevents rust from reordering struct fields.
// packed(1) prevents rust from aligning structs to the size of the largest
// field.

// Using u64 or 64bit pointers forces structs to be 8-byte aligned.
// The vanilla code seems to be 4-byte aligned. To make extra sure, used
// packed(1) to force the alignment to match what you define.

// Always add an assert_eq_size!() macro after defining a struct to ensure it's
// the size you expect it to be.

// Event
#[repr(C, packed(1))]
#[derive(Copy, Clone)]
pub struct EventMgr {
    pub _0:             [u8; 0x10],
    pub event_owner:    [u8; 0x18],
    pub linked_actor:   [u8; 0x18],
    pub _1:             [u8; 8],
    pub actual_event:   Event,
    pub _2:             [u8; 0x160],
    pub event:          Event,
    pub probably_state: u32,
    pub state_flags:    u32,
    pub skipflag:       u16,
    pub _3:             [u8; 14],
}
assert_eq_size!([u8; 0x260], EventMgr);

#[repr(C, packed(1))]
#[derive(Copy, Clone)]
pub struct Event {
    pub vtable:         u64,
    pub eventid:        u32,
    pub event_flags:    u32,
    pub roomid:         i32,
    pub tool_dataid:    i32,
    pub event_name:     [u8; 32],
    pub event_zev_data: u64,
    pub callbackFn1:    u64,
    pub callbackFn2:    u64,
}
assert_eq_size!([u8; 0x50], Event);

// Harp stuff
// Not sure what this stuff is all about
// Used to keep vanilla checks for isPlayingHarp (see SD for more details)
#[repr(C, packed(1))]
#[derive(Copy, Clone)]
pub struct HarpRelated {
    pub unk:                                 [u8; 0x30],
    pub some_check_for_continuous_strumming: u64,
    pub unk1:                                [u8; 0x22],
    pub some_other_harp_thing:               u8,
}

// Event Flow stuff
#[repr(C, packed(1))]
#[derive(Copy, Clone)]
pub struct ActorEventFlowMgr {
    pub vtable:                     u64,
    pub msbf_info:                  u64,
    pub current_flow_index:         u32,
    pub _0:                         [u8; 12],
    pub result_from_previous_check: u32,
    pub current_text_label_name:    [u8; 32],
    pub _1:                         [u8; 12],
    pub next_flow_delay_timer:      u32,
    pub another_flow_element:       EventFlowElement,
    pub _2:                         [u8; 12],
}
assert_eq_size!([u8; 0x70], ActorEventFlowMgr);

#[repr(C, packed(1))]
#[derive(Copy, Clone)]
pub struct EventFlowElement {
    pub typ:     u8,
    pub subtype: u8,
    pub pad:     u16,
    pub param2:  u16, // 6.5 hrs went into finding out that these are reversed ...
    pub param1:  u16,
    pub next:    u16,
    pub param3:  u16,
    pub param4:  u16,
    pub param5:  u16,
}
// Long story, turns out that the game stores param1 and 2 in a single u32
// field. This works fine in SD, however, HD has the reverse endianness. So,
// these two params2 get reversed and that's how I lost over 6 hours of my life
// ;-;
assert_eq_size!([u8; 0x10], EventFlowElement);

// IMPORTANT: when using vanilla code, the start point must be declared in
// symbols.yaml and then added to this extern block.
extern "C" {
    // Custom symbols
    static mut TRAP_ID: u8;

    static STORYFLAG_MGR: *mut flag::FlagMgr;
    static LYT_MSG_WINDOW: *mut lyt::dLytMsgWindow;
    static GLOBAL_TEXT_MGR: *mut lyt::TextMgr;
    static FILE_MGR: *mut savefile::FileMgr;

    static mut CURRENT_STAGE_NAME: [u8; 8];

    static mut GODDESS_SWORD_RES: [u8; 0xA0000];
    static mut TRUE_MASTER_SWORD_RES: [u8; 0xA0000];

    // Vanilla functions
    fn set_string_arg(text_mgr: *mut lyt::TextMgr, arg: *const c_void, arg_num: u32);

    // Functions
    fn debugPrint_128(string: *const c_char, fstr: *const c_char, ...);
    fn parseBRRES(res_data: u64);
}

// IMPORTANT: when adding functions here that need to get called from the game,
// add `#[no_mangle]` and add a .global *symbolname* to
// additions/rust-additions.asm

// ---------------------------------------------------------------------------
// Pending / retry state for AP string args (cmd 81).
//
// There are TWO independent failure modes that can cause the first item-216
// pickup to show fallback text:
//
//   A) Table lookup fails — `lookup_ap_item_index` returns MAX because the
//      emulator's JIT hasn't yet made the cross-process memory writes visible
//      (the Python client writes AP_ITEM_INFO_TABLE via pymem).
//      Fix: retry the lookup every frame from the main loop.
//
//   B) TextMgr not ready — `LYT_MSG_WINDOW.text_mgr` is null on the very
//      first textbox of a session, so `set_string_arg` can't write there.
//      Fix: save the pointers and retry once text_mgr appears.
//
// Both retries are handled in `apply_pending_ap_string_args`, called every
// frame from `main_loop_inject`.
// ---------------------------------------------------------------------------

/// Flag ID whose lookup should be retried (mode A).
static mut PENDING_AP_FLAG_ID: u16 = 0xFFFF;
/// Whether a lookup retry is pending.
static mut PENDING_AP_LOOKUP: bool = false;

/// Resolved pointers for deferred TextMgr write (mode B).
static mut PENDING_AP_ITEM_PTR: *const c_void = core::ptr::null();
static mut PENDING_AP_PLAYER_PTR: *const c_void = core::ptr::null();
/// Whether a TextMgr write is pending.
static mut PENDING_AP_STRING_ARGS: bool = false;

/// Diagnostic text buffers — shown in the item-216 textbox when the
/// AP_ITEM_INFO_TABLE lookup fails, displaying the flag_id and table
/// count so the user can see exactly what went wrong.
static mut DBG_ITEM_TEXT: [u16; 32] = [0u16; 32];
static mut DBG_PLAYER_TEXT: [u16; 16] = [0u16; 16];

/// Format a `u16` value as decimal digits into a UTF-16 buffer.
/// Returns the number of u16 characters written.
fn fmt_u16_dec(buf: &mut [u16], val: u16) -> usize {
    if val == 0 {
        if !buf.is_empty() {
            buf[0] = b'0' as u16;
        }
        return 1.min(buf.len());
    }
    let mut tmp = [0u16; 5]; // max 65535 = 5 digits
    let mut n = val;
    let mut len = 0usize;
    while n > 0 && len < 5 {
        tmp[len] = (n % 10) as u16 + b'0' as u16;
        n /= 10;
        len += 1;
    }
    let w = len.min(buf.len());
    for i in 0..w {
        buf[i] = tmp[len - 1 - i];
    }
    w
}

/// Write an ASCII byte slice into a u16 buffer (one byte per u16).
/// Returns the number of u16 characters written.
fn write_ascii(buf: &mut [u16], s: &[u8]) -> usize {
    let w = s.len().min(buf.len());
    for i in 0..w {
        buf[i] = s[i] as u16;
    }
    w
}

/// Called every frame from `main_loop_inject`.
///
/// Handles two retry paths:
///   1. If `lookup_ap_item_index` failed in cmd 81, retry here (the table may
///      have become visible to the JIT since the last attempt).
///   2. If the lookup succeeded but `LYT_MSG_WINDOW.text_mgr` was null, write
///      the saved pointers once text_mgr appears.
pub fn apply_pending_ap_string_args() {
    unsafe {
        // ── Retry path A: table lookup ──────────────────────────────────
        if PENDING_AP_LOOKUP {
            let mut flag_id = PENDING_AP_FLAG_ID;

            // If cmd 81 couldn't find the flag_id (was 0xFFFF), re-read
            // the static each frame — handle_custom_item_get (in stateGet)
            // will have written it by the time this retry fires.
            if flag_id == 0xFFFF {
                flag_id = core::ptr::read_volatile(core::ptr::addr_of!(item::LAST_AP_ITEM_FLAG_ID));
                if flag_id != 0xFFFF {
                    PENDING_AP_FLAG_ID = flag_id; // cache resolved value
                }
            }

            if flag_id != 0xFFFF {
                let idx = item::lookup_ap_item_index(flag_id);
                if idx != usize::MAX {
                    // Lookup succeeded — resolve pointers and write to both
                    // TextMgrs immediately.
                    let entry_ptr = core::ptr::addr_of!(item::AP_ITEM_INFO_TABLE.entries[idx]);
                    let ip = core::ptr::addr_of!((*entry_ptr).item_name) as *const c_void;
                    let pp = core::ptr::addr_of!((*entry_ptr).player_name) as *const c_void;

                    if !GLOBAL_TEXT_MGR.is_null() {
                        set_string_arg(GLOBAL_TEXT_MGR, ip, 0);
                        set_string_arg(GLOBAL_TEXT_MGR, pp, 1);
                    }
                    let text_mgr = (*LYT_MSG_WINDOW).text_mgr;
                    if !text_mgr.is_null() {
                        set_string_arg(text_mgr, ip, 0);
                        set_string_arg(text_mgr, pp, 1);
                        PENDING_AP_STRING_ARGS = false; // also clears mode-B
                    } else {
                        // Lookup worked but text_mgr still null → mode B
                        PENDING_AP_ITEM_PTR = ip;
                        PENDING_AP_PLAYER_PTR = pp;
                        PENDING_AP_STRING_ARGS = true;
                    }

                    // Reset after successful retry (prevent stale values)
                    core::ptr::write_volatile(
                        core::ptr::addr_of_mut!(item::LAST_AP_ITEM_FLAG_ID),
                        0xFFFFu16,
                    );
                    PENDING_AP_LOOKUP = false;
                }
                // else: still not found → keep retrying next frame
            }
        }

        // ── Retry path B: deferred TextMgr write ───────────────────────
        if PENDING_AP_STRING_ARGS {
            let text_mgr = (*LYT_MSG_WINDOW).text_mgr;
            if !text_mgr.is_null() {
                set_string_arg(text_mgr, PENDING_AP_ITEM_PTR, 0);
                set_string_arg(text_mgr, PENDING_AP_PLAYER_PTR, 1);
                PENDING_AP_STRING_ARGS = false;
            }
        }
    }
}

#[no_mangle]
pub extern "C" fn custom_event_commands(
    actor_event_flow_mgr: *mut ActorEventFlowMgr,
    p_event_flow_element: *const EventFlowElement,
) {
    let mut event_flow_element = unsafe { &*p_event_flow_element };
    match event_flow_element.param3 {
        // Fi Warp
        70 => unsafe {
            (*actor_event_flow_mgr).result_from_previous_check = entrance::warp_to_start() as u32
        },
        // Get trap type
        71 => unsafe {
            if TRAP_ID != u8::MAX {
                (*actor_event_flow_mgr).result_from_previous_check = 1;
            } else {
                (*actor_event_flow_mgr).result_from_previous_check = 0;
            }
        },
        72 => traps::update_traps(),
        73 => fix::set_skyloft_thunderhead_sceneflag(),
        74 => flag::increment_tadtone_counter(),
        75 => unsafe {
            let tadtone_groups_left = 17 - flag::check_storyflag(953);

            // Set numeric arg 0 to number of tadtones left. This will display the number
            // of remaining tadtones in the textbox for the item give.
            (*(*LYT_MSG_WINDOW).text_mgr).numeric_args[0] = tadtone_groups_left;

            // Set result from previous check to number of tadtones left. If this is 0, it
            // will show the item give textbox for collecting all the tadtones.
            (*actor_event_flow_mgr).result_from_previous_check = tadtone_groups_left;
        },
        76 => minigame::boss_rush_backup_flags(event_flow_element.param1),
        77 => minigame::boss_rush_restore_flags(),
        78 => unsafe {
            let sceneindex = event_flow_element.param1;

            (*(*LYT_MSG_WINDOW).text_mgr).numeric_args[1] =
                1 + (((*FILE_MGR).FA.dungeonflags[sceneindex as usize][1] >> 4) & 0xF) as u32;
        },
        // Give item with custom sceneflag (for Archipelago)
        79 => unsafe {
            use crate::item::give_item_with_sceneflag;
            let itemid = (event_flow_element.param2 & 0xFF) as u8;
            let custom_flag = event_flow_element.param4 as u8;
            give_item_with_sceneflag(itemid, custom_flag);
        },
        // Set global flag for Archipelago custom flag detection
        // param1 = flag index (0-127), param2 = actual scene index (6, 13, 16, or 19)
        // param4 = flag_space_trigger (0 = sceneflag, 1 = dungeonflag)
        //
        // IMPORTANT: The body is in a separate #[inline(never)] function to keep
        // register pressure low in this function. The asm epilogue below sets w21
        // (a callee-saved register). If the compiler needs x21 for local variables,
        // it will save/restore x21 in the prologue/epilogue, UNDOING the
        // "mov w21, #1" replaced instruction and breaking ALL type3 event flows.
        80 => set_global_sceneflag_for_ap(event_flow_element),
        // Set string args for Archipelago Item (216) textbox.
        // (Same #[inline(never)] reasoning as above.)
        81 => set_ap_item_string_args(),
        _ => (),
    }

    unsafe {
        asm!(
            "mov x0, {0:x}",
            "mov x1, {1:x}",
            // Replaced instructions
            "ldrh w8, [x1, #0xa]",
            "mov w21, #1",
            in(reg) actor_event_flow_mgr,
            in(reg) p_event_flow_element,
        );
    }
}

/// Set global flag for Archipelago custom flag detection.
///
/// Encodes the flag index, scene index, and flag space into a compact 10-bit
/// ID and stores it in `LAST_AP_ITEM_FLAG_ID` so the textbox can look up the
/// correct AP item info.
///
/// param1 = flag index (0-127)
/// param2 = actual scene index (6, 13, 16, or 19)
/// param4 = flag_space_trigger (0 = sceneflag, 1 = dungeonflag)
///
/// # Why this is a separate function
/// Same reasoning as `set_ap_item_string_args` – keeps register pressure in
/// `custom_event_commands` low so the compiler doesn't touch x21.
#[inline(never)]
fn set_global_sceneflag_for_ap(event_flow_element: &EventFlowElement) {
    unsafe {
        let flag_index = event_flow_element.param1 as u16;
        let scene_index = event_flow_element.param2 as u16;
        let flag_space_trigger = event_flow_element.param4 as u32;

        // Use different flag spaces depending on the value of flag_space_trigger
        match flag_space_trigger {
            0 => flag::set_global_sceneflag(scene_index, flag_index),
            1 => flag::set_global_dungeonflag(scene_index, flag_index),
            _ => flag::set_global_sceneflag(scene_index, flag_index),
        }

        let scene_raw: u32 = match scene_index {
            6 => 0,
            13 => 1,
            16 => 2,
            19 => 3,
            _ => 0,
        };
        let computed_flag_id =
            (flag_index as u32 & 0x7F) | (scene_raw << 7) | (flag_space_trigger << 9);
        // Volatile write so the store is committed immediately.
        core::ptr::write_volatile(
            core::ptr::addr_of_mut!(item::LAST_AP_ITEM_FLAG_ID),
            computed_flag_id as u16,
        );
    }
}

/// Set string args for Archipelago Item (216) textbox.
///
/// Reads LAST_AP_ITEM_FLAG_ID (set in handle_custom_item_get) and looks up
/// item name + player name in the AP_ITEM_INFO_TABLE (written by the Python
/// client on connect).
///
/// If the lookup fails (table not yet visible to the JIT), **diagnostic text
/// is shown in the textbox** (e.g. "f=123 c=0" / "MISS") so the user can
/// see exactly what went wrong, AND `PENDING_AP_LOOKUP` is set so
/// `apply_pending_ap_string_args` retries every frame until the lookup
/// succeeds.
///
/// # Why this is a separate function
/// `custom_event_commands` ends with an inline asm block that sets `w21`
/// (x21), which is a **callee-saved register** in AArch64.  If the compiler
/// allocates x21 for local variables, the function epilogue will restore x21
/// _after_ the asm block, undoing the `mov w21, #1` replaced instruction and
/// breaking every type3 event flow in the game.
///
/// By isolating the heavy logic here, `custom_event_commands` stays small
/// enough that the compiler only needs x19/x20 (for the two function
/// parameters), keeping x21 untouched.
#[inline(never)]
fn set_ap_item_string_args() {
    unsafe {
        // Read LAST_AP_ITEM_FLAG_ID.  For freestanding/chest items this is
        // set by setup_traps() at the beginning of stateWait*GetDemoUpdate
        // (BEFORE the event system fires).  For NPC-given items, cmd 80
        // sets it in the same event flow.  Either way, the value should be
        // available by the time we get here.
        let flag_id_ptr = core::ptr::addr_of!(item::LAST_AP_ITEM_FLAG_ID);
        let flag_id = core::ptr::read_volatile(flag_id_ptr);

        let idx = item::lookup_ap_item_index(flag_id);

        let (item_ptr, player_ptr): (*const c_void, *const c_void) = if idx != usize::MAX {
            // ── Success: use the table entry ────────────────────────────
            let entry_ptr = core::ptr::addr_of!(item::AP_ITEM_INFO_TABLE.entries[idx]);
            (
                core::ptr::addr_of!((*entry_ptr).item_name) as *const c_void,
                core::ptr::addr_of!((*entry_ptr).player_name) as *const c_void,
            )
        } else {
            // ── Failure: build diagnostic text shown in the textbox ─────
            let count_val =
                core::ptr::read_volatile(core::ptr::addr_of!(item::AP_ITEM_INFO_TABLE.count));

            let mut p = 0usize;
            p += write_ascii(&mut DBG_ITEM_TEXT[p..], b"f=");
            p += fmt_u16_dec(&mut DBG_ITEM_TEXT[p..], flag_id);
            p += write_ascii(&mut DBG_ITEM_TEXT[p..], b" c=");
            p += fmt_u16_dec(&mut DBG_ITEM_TEXT[p..], count_val);
            if p < 32 {
                DBG_ITEM_TEXT[p] = 0;
            }

            let mut q = 0usize;
            q += write_ascii(&mut DBG_PLAYER_TEXT[q..], b"MISS");
            if q < 16 {
                DBG_PLAYER_TEXT[q] = 0;
            }

            (
                DBG_ITEM_TEXT.as_ptr() as *const c_void,
                DBG_PLAYER_TEXT.as_ptr() as *const c_void,
            )
        };

        // Write to GLOBAL_TEXT_MGR (always initialised at this point).
        if !GLOBAL_TEXT_MGR.is_null() {
            set_string_arg(GLOBAL_TEXT_MGR, item_ptr, 0);
            set_string_arg(GLOBAL_TEXT_MGR, player_ptr, 1);
        }

        // Write to the message-window layout's TextMgr if available.
        let text_mgr = (*LYT_MSG_WINDOW).text_mgr;
        if !text_mgr.is_null() {
            set_string_arg(text_mgr, item_ptr, 0);
            set_string_arg(text_mgr, player_ptr, 1);
        }

        // ── Reset LAST_AP_ITEM_FLAG_ID after use ────────────────────────
        // This prevents the STALE value problem: without the reset, the
        // next item-216 pickup would see the PREVIOUS item's flag_id if
        // setup_traps / handle_custom_item_get hasn't written yet.
        if idx != usize::MAX {
            core::ptr::write_volatile(
                core::ptr::addr_of_mut!(item::LAST_AP_ITEM_FLAG_ID),
                0xFFFFu16,
            );
        }

        // If the lookup failed, schedule main-loop retry so the correct
        // text can be patched in once the flag / table becomes visible.
        if idx == usize::MAX {
            PENDING_AP_FLAG_ID = flag_id;
            PENDING_AP_LOOKUP = true;
        } else {
            PENDING_AP_LOOKUP = false;
        }

        // If text_mgr was null, schedule deferred write.
        if text_mgr.is_null() {
            PENDING_AP_ITEM_PTR = item_ptr;
            PENDING_AP_PLAYER_PTR = player_ptr;
            PENDING_AP_STRING_ARGS = true;
        } else {
            PENDING_AP_STRING_ARGS = false;
        }
    }
}

#[no_mangle]
pub extern "C" fn check_tadtone_counter_before_song_event(
    tadtone_minigame_actor: *mut actor::dTgClefGame,
) -> *mut actor::dTgClefGame {
    let collected_tadtone_groups = flag::check_storyflag(953);
    let vanilla_tadtones_completed_flag = flag::check_storyflag(18);

    let mut should_play_cutscene = false;

    // If we've collected all 17 tadtone groups and haven't played the cutscene
    // yet, then play the cutscene
    if collected_tadtone_groups == 17 && vanilla_tadtones_completed_flag == 0 {
        should_play_cutscene = true;

        unsafe {
            (*tadtone_minigame_actor).delay_before_starting_event = 0;
        }
    }

    unsafe { asm!("mov w1, {0:w}", in(reg) should_play_cutscene as u32) };
    return tadtone_minigame_actor;
}

#[no_mangle]
pub extern "C" fn set_boko_base_restricted_sword_flag_before_event(param1: *mut c_void) {
    unsafe {
        if &CURRENT_STAGE_NAME[..7] == b"F201_2\0" {
            flag::set_storyflag(167);
        }
    }

    // Replaced instructions
    unsafe {
        asm!("mov x0, {0:x}", "mov w8, #1", "strb w8, [x0, #0xb5a]", in(reg) param1);
    }
}

#[repr(C, packed(1))]
#[derive(Copy, Clone)]
pub struct unkstruct {
    pub unk0x0:  *mut c_void,
    pub unk0x8:  *mut c_void,
    pub unk0x10: extern "C" fn(*mut c_void, u32, u32),
}

#[no_mangle]
pub extern "C" fn remove_vanilla_tms_sword_pull_textbox(param1: *mut *mut unkstruct) {
    unsafe {
        ((*(*param1)).unk0x10)(param1 as *mut c_void, 0xFF, 3);
    }

    // Sets tboxflag 9 in sceneindex 5 (Boko Base / VS)
    flag::set_global_tboxflag(5, 9);

    // The vanilla textbox eventflow unsets these flags.
    flag::unset_storyflag(167); // Restricted sword
    flag::set_local_sceneflag(44);
}

#[no_mangle]
pub extern "C" fn fix_boko_base_sword_model(
    mut res_data: *mut c_void,
    mut model_name: *const c_char,
    sword_type: u8,
) {
    unsafe {
        if sword_type == 1 {
            res_data = TRUE_MASTER_SWORD_RES.as_ptr() as *mut c_void;
            model_name = c"EquipSwordMaster".as_ptr();
        } else {
            res_data = GODDESS_SWORD_RES.as_ptr() as *mut c_void;
            model_name = c"EquipSwordB".as_ptr();
        }

        asm!("mov x0, {0:x}", in(reg) res_data);
        asm!("mov x1, {0:x}", in(reg) model_name);
    }
}
