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
static NULL_UTF16: [u16; 1] = [0u16; 1];

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

#[inline(always)]
fn normalize_text_arg_ptr(arg: *const c_void) -> *const c_void {
    if arg.is_null() {
        NULL_UTF16.as_ptr() as *const c_void
    } else {
        arg
    }
}

#[inline(always)]
unsafe fn set_string_arg_safe(text_mgr: *mut lyt::TextMgr, arg: *const c_void, arg_num: u32) {
    set_string_arg(text_mgr, normalize_text_arg_ptr(arg), arg_num);
}

/// Called every frame from `main_loop_inject`.
///
/// Handles two retry paths:
///   1. If `lookup_ap_item_index` failed in cmd 81, retry here (the table may
///      have become visible to the JIT since the last attempt).
///   2. Re-apply saved text pointers to TextMgrs.  This covers both the
///      "text_mgr was null" case AND the normal success case — cmd 81 always
///      schedules this so the correct text is continuously written throughout
///      the delay window, right up until the textbox opens.
pub fn apply_pending_ap_string_args() {
    unsafe {
        // ── Retry path A: table lookup ──────────────────────────────────
        if PENDING_AP_LOOKUP {
            let mut flag_id = PENDING_AP_FLAG_ID;

            // If cmd 81 couldn't find the flag_id (was 0xFFFF), re-read
            // the static each frame — setup_traps (in stateWait*GetDemoUpdate)
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
                        set_string_arg_safe(GLOBAL_TEXT_MGR, ip, 0);
                        set_string_arg_safe(GLOBAL_TEXT_MGR, pp, 1);
                    }
                    if !LYT_MSG_WINDOW.is_null() {
                        let text_mgr = (*LYT_MSG_WINDOW).text_mgr;
                        if !text_mgr.is_null() {
                            set_string_arg_safe(text_mgr, ip, 0);
                            set_string_arg_safe(text_mgr, pp, 1);
                            PENDING_AP_STRING_ARGS = false; // also clears
                                                            // mode-B
                        } else {
                            // Lookup worked but text_mgr still null → mode B
                            PENDING_AP_ITEM_PTR = ip;
                            PENDING_AP_PLAYER_PTR = pp;
                            PENDING_AP_STRING_ARGS = true;
                        }
                    } else {
                        // Layout torn down — defer to mode B
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
            if !LYT_MSG_WINDOW.is_null() {
                let text_mgr = (*LYT_MSG_WINDOW).text_mgr;
                if !text_mgr.is_null() {
                    set_string_arg_safe(text_mgr, PENDING_AP_ITEM_PTR, 0);
                    set_string_arg_safe(text_mgr, PENDING_AP_PLAYER_PTR, 1);
                    PENDING_AP_STRING_ARGS = false;
                }
            }
        }
    }
}

#[no_mangle]
pub extern "C" fn custom_event_commands(
    actor_event_flow_mgr: *mut ActorEventFlowMgr,
    p_event_flow_element: *const EventFlowElement,
) {
    let event_flow_element = unsafe { &*p_event_flow_element };
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
            if !LYT_MSG_WINDOW.is_null() {
                let text_mgr = (*LYT_MSG_WINDOW).text_mgr;
                if !text_mgr.is_null() {
                    (*text_mgr).numeric_args[0] = tadtone_groups_left;
                }
            }

            // Set result from previous check to number of tadtones left. If this is 0, it
            // will show the item give textbox for collecting all the tadtones.
            (*actor_event_flow_mgr).result_from_previous_check = tadtone_groups_left;
        },
        76 => minigame::boss_rush_backup_flags(event_flow_element.param1),
        77 => minigame::boss_rush_restore_flags(),
        78 => unsafe {
            let sceneindex = event_flow_element.param1;

            // Reconciled upstream change safely here:
            if !LYT_MSG_WINDOW.is_null() && !(*LYT_MSG_WINDOW).text_mgr.is_null() {
                (*(*LYT_MSG_WINDOW).text_mgr).numeric_args[1] =
                    1 + (((*FILE_MGR).FA.dungeonflags[sceneindex as usize][1] >> 4) & 0xF) as u32;
            }
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
        80 => set_global_sceneflag_for_ap(event_flow_element),
        // Set string args for Archipelago Item (216) textbox.
        81 => set_ap_item_string_args(actor_event_flow_mgr),
        _ => (),
    }

    // The replaced instructions (ldrh w8, [x1, #0xa]; mov w21, #1) are now
    // executed by the ASM wrapper `_ce_wrapper` in the landing pad, AFTER
    // this function's epilogue. This prevents the compiler from clobbering
    // w21 (a callee-saved register) in the epilogue — which would break all
    // type-3 event flows.
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
/// Reads LAST_AP_ITEM_FLAG_ID (set in setup_traps / cmd 80) and looks up
/// item name + player name in the AP_ITEM_INFO_TABLE (written by the Python
/// client on connect).
///
/// **Defence-in-depth:** The function FIRST writes fallback text
/// ("Archipelago Item" / "another player") to both TextMgrs, clearing any
/// stale string_args left over from a previous textbox.  Then it attempts
/// the table lookup and overwrites with the real text on success.  This
/// guarantees the worst case is the generic fallback, never a previous
/// item's text.
///
/// A short delay is ALWAYS added before the textbox opens (5 frames on
/// success, 20 on failure).  During this window the per-frame retry loop
/// (`apply_pending_ap_string_args`) keeps re-applying the resolved text
/// pointers to TextMgrs, so by the time the textbox renders, the correct
/// strings are guaranteed to be in place.
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
fn set_ap_item_string_args(actor_event_flow_mgr: *mut ActorEventFlowMgr) {
    unsafe {
        // ── STEP 1: Write fallback text FIRST ────────────────────────
        // Always clobber both TextMgrs with safe defaults before doing
        // anything else.  This guarantees that even if the lookup below
        // fails (or succeeds with a stale flag_id for any unforeseen
        // reason), the textbox will never display a PREVIOUS item's
        // name / player name.  It will show "Archipelago Item" /
        // "another player" at worst.
        {
            let mut p = 0usize;
            p += write_ascii(&mut DBG_ITEM_TEXT[p..], b"Archipelago Item");
            if p < 32 {
                DBG_ITEM_TEXT[p] = 0;
            }

            let mut q = 0usize;
            q += write_ascii(&mut DBG_PLAYER_TEXT[q..], b"another player");
            if q < 16 {
                DBG_PLAYER_TEXT[q] = 0;
            }

            let fallback_item = DBG_ITEM_TEXT.as_ptr() as *const c_void;
            let fallback_player = DBG_PLAYER_TEXT.as_ptr() as *const c_void;

            if !GLOBAL_TEXT_MGR.is_null() {
                set_string_arg_safe(GLOBAL_TEXT_MGR, fallback_item, 0);
                set_string_arg_safe(GLOBAL_TEXT_MGR, fallback_player, 1);
            }
            if !LYT_MSG_WINDOW.is_null() {
                let tm = (*LYT_MSG_WINDOW).text_mgr;
                if !tm.is_null() {
                    set_string_arg_safe(tm, fallback_item, 0);
                    set_string_arg_safe(tm, fallback_player, 1);
                }
            }
        }

        // ── STEP 2: Attempt table lookup and overwrite with real text ──
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
            (
                DBG_ITEM_TEXT.as_ptr() as *const c_void,
                DBG_PLAYER_TEXT.as_ptr() as *const c_void,
            )
        };

        // ── STEP 3: Always delay the textbox ────────────────────────────
        // Adding a short delay before the textbox opens gives the
        // per-frame retry loop (`apply_pending_ap_string_args`) a window
        // to re-apply the resolved text to TextMgrs.  This acts as the
        // "short sleep" that makes the display near-100 % reliable:
        //   - On success (10 frames / ~167 ms @60fps): barely noticeable, but the
        //     retry loop re-writes the correct pointers every frame until the textbox
        //     fires, guarding against any intermediate processing that might clear
        //     string_args.
        //   - On failure (40 frames / ~667 ms @60fps): gives the retry loop enough
        //     time to find the real data in the table and patch it in before the
        //     textbox opens.
        if !actor_event_flow_mgr.is_null() {
            (*actor_event_flow_mgr).next_flow_delay_timer = if idx != usize::MAX { 10 } else { 40 };
        }

        // Overwrite both TextMgrs with the resolved (or fallback) text.
        if !GLOBAL_TEXT_MGR.is_null() {
            set_string_arg_safe(GLOBAL_TEXT_MGR, item_ptr, 0);
            set_string_arg_safe(GLOBAL_TEXT_MGR, player_ptr, 1);
        }

        // Write to the message-window layout's TextMgr if available.
        let text_mgr = if !LYT_MSG_WINDOW.is_null() {
            (*LYT_MSG_WINDOW).text_mgr
        } else {
            core::ptr::null_mut()
        };
        if !text_mgr.is_null() {
            set_string_arg_safe(text_mgr, item_ptr, 0);
            set_string_arg_safe(text_mgr, player_ptr, 1);
        }

        // ── Reset LAST_AP_ITEM_FLAG_ID after use ────────────────────────
        // This prevents the STALE value problem: without the reset, the
        // next item-216 pickup could see the PREVIOUS item's flag_id if
        // setup_traps hasn't written yet.
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

        // Always schedule the deferred re-apply so the per-frame retry
        // loop keeps writing the resolved (or fallback) pointers to
        // TextMgrs throughout the delay window.  This ensures the
        // textbox opens with the correct text even if:
        //   - text_mgr was null initially but appears during the delay,
        //   - some intermediate engine processing cleared string_args,
        //   - retry path A resolves the real data mid-delay.
        PENDING_AP_ITEM_PTR = item_ptr;
        PENDING_AP_PLAYER_PTR = player_ptr;
        PENDING_AP_STRING_ARGS = true;
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
