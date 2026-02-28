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
        // Set global sceneflag for Archipelago custom flag detection
        // param1 = flag index (0-127), param2 = actual scene index (6, 13, 16, or 19)
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

/// Set global sceneflag for Archipelago custom flag detection.
///
/// Encodes the flag index and scene index into a compact 10-bit ID and stores
/// it in `LAST_AP_ITEM_FLAG_ID` so the textbox can look up the correct AP item
/// info.
///
/// # Why this is a separate function
/// Same reasoning as `set_ap_item_string_args` – keeps register pressure in
/// `custom_event_commands` low so the compiler doesn't touch x21.
#[inline(never)]
fn set_global_sceneflag_for_ap(event_flow_element: &EventFlowElement) {
    unsafe {
        let flag_index = event_flow_element.param1 as u16;
        let scene_index = event_flow_element.param2 as u16;
        flag::set_global_sceneflag(scene_index, flag_index);

        let scene_raw: u32 = match scene_index {
            6 => 0,
            13 => 1,
            16 => 2,
            19 => 3,
            _ => 0,
        };
        let computed_flag_id = (flag_index as u32 & 0x7F) | (scene_raw << 7);
        item::LAST_AP_ITEM_FLAG_ID = computed_flag_id as u16;
    }
}

/// Set string args for Archipelago Item (216) textbox.
///
/// Reads LAST_AP_ITEM_FLAG_ID (set in handle_custom_item_get) and looks up
/// item name + player name in the AP_ITEM_INFO_TABLE (written by the Python
/// client on connect).
///
/// **Both `GLOBAL_TEXT_MGR` and `LYT_MSG_WINDOW.text_mgr` are written**
/// because the message-window layout may re-create or reassign its `text_mgr`
/// pointer when the first textbox of a session opens.  By writing to both
/// TextMgrs (the global one that the engine always keeps initialised, and the
/// per-layout one that subsequent textboxes use), the correct item / player
/// name appears even for the very first AP item collected.
///
/// # Why this is a separate function
/// `custom_event_commands` ends with an inline asm block that sets `w21`
/// (x21), which is a **callee-saved register** in AArch64. If the compiler
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
        let flag_id = item::LAST_AP_ITEM_FLAG_ID;
        let idx = item::lookup_ap_item_index(flag_id);

        // Fallback strings for when the Python client hasn't written the table yet
        static UNKNOWN_ITEM: [u16; 17] = [
            b'A' as u16,
            b'r' as u16,
            b'c' as u16,
            b'h' as u16,
            b'i' as u16,
            b'p' as u16,
            b'e' as u16,
            b'l' as u16,
            b'a' as u16,
            b'g' as u16,
            b'o' as u16,
            b' ' as u16,
            b'I' as u16,
            b't' as u16,
            b'e' as u16,
            b'm' as u16,
            0,
        ];
        static UNKNOWN_PLAYER: [u16; 15] = [
            b'a' as u16,
            b'n' as u16,
            b'o' as u16,
            b't' as u16,
            b'h' as u16,
            b'e' as u16,
            b'r' as u16,
            b' ' as u16,
            b'p' as u16,
            b'l' as u16,
            b'a' as u16,
            b'y' as u16,
            b'e' as u16,
            b'r' as u16,
            0,
        ];

        let (item_ptr, player_ptr): (*const c_void, *const c_void) = if idx != usize::MAX {
            let entry_ptr = core::ptr::addr_of!(item::AP_ITEM_INFO_TABLE.entries[idx]);
            (
                core::ptr::addr_of!((*entry_ptr).item_name) as *const c_void,
                core::ptr::addr_of!((*entry_ptr).player_name) as *const c_void,
            )
        } else {
            (
                UNKNOWN_ITEM.as_ptr() as *const c_void,
                UNKNOWN_PLAYER.as_ptr() as *const c_void,
            )
        };

        // Write to GLOBAL_TEXT_MGR using the vanilla set_string_arg function.
        // This is the same pattern used by all other custom text-setting code
        // (dungeon info, help menu, etc.) and is always initialised by the
        // time items can be collected.  Critically, it remains valid even
        // before the first textbox opens, fixing the "first AP item shows
        // default text" bug.
        if !GLOBAL_TEXT_MGR.is_null() {
            set_string_arg(GLOBAL_TEXT_MGR, item_ptr, 0);
            set_string_arg(GLOBAL_TEXT_MGR, player_ptr, 1);
        }

        // Also write to the message-window layout's own TextMgr if available.
        // After the first textbox has been shown this pointer is stable, so
        // writing here ensures subsequent items keep working even if the
        // textbox renderer reads from this TextMgr instead of the global one.
        let text_mgr = (*LYT_MSG_WINDOW).text_mgr;
        if !text_mgr.is_null() {
            set_string_arg(text_mgr, item_ptr, 0);
            set_string_arg(text_mgr, player_ptr, 1);
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
