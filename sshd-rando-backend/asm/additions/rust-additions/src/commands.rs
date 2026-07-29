#![allow(non_camel_case_types)]
#![allow(non_snake_case)]
#![allow(unused)]

use crate::entrance;
use crate::flag;
use crate::traps;
use core::ffi::c_char;
use static_assertions::assert_eq_size;

// repr(C) prevents rust from reordering struct fields.
// packed(1) prevents rust from aligning structs to the size of the largest
// field.
// Using u64 or 64bit pointers forces structs to be 8-byte aligned.
// The vanilla code seems to be 4-byte aligned. To make extra sure, used
// packed(1) to force the alignment to match what you define.
// Always add an assert_eq_size!() macro after defining a struct to ensure it's
// the size you expect it to be.

//////////////////////
// ADD STRUCTS HERE //
//////////////////////

// ─── AP_FLAG_REQUEST ───────────────────────────────────────────────────
// New. Backs the /flag command (get/set/unset story/scene/item/dungeon
// flags). Python locates this struct by scanning for magic bytes
// "FL\x00\x01". This layout must stay in sync with AP_FLAG_REQUEST_STRUCT
// in SSHDClient.py.
//
// Layout (packed, little-endian, 20 bytes total):
//   +0  magic [u8; 4]       — "FL\x00\x01"
//   +4  pending bool        — 1 = new request for us to process; we clear
//                             it back to 0 as soon as we pick it up
//   +5  flag_type u8        — 0=storyflag, 1=sceneflag, 2=itemflag,
//                             3=dungeonflag
//   +6  operation u8        — 0=get, 1=set, 2=unset
//   +7  _pad0 u8
//   +8  flag_id u16         — story/item/scene/dungeon flag id
//   +10 value u16           — value to write: 0/1 for a boolean flag, or
//                             N for a counter (e.g. DEKU_SEED_COUNTER)
//   +12 scene_index u16     — sceneflag/dungeonflag only; 0xFFFF means
//                             "current/local scene"
//   +14 response_ready bool — we set this to 1 once response_value holds
//                             a valid result
//   +15 _pad1 u8
//   +16 response_value u32  — result of get, or the flag's new value
//                             after set/unset
#[repr(C, packed(1))]
pub struct ApFlagRequest {
    pub magic:          [u8; 4],
    pub pending:        bool,
    pub flag_type:      u8,
    pub operation:      u8,
    pub _pad0:          u8,
    pub flag_id:        u16,
    pub value:          u16,
    pub scene_index:    u16,
    pub response_ready: bool,
    pub _pad1:          u8,
    pub response_value: u32,
}
assert_eq_size!([u8; 20], ApFlagRequest);

#[no_mangle]
pub static mut AP_FLAG_REQUEST: ApFlagRequest = ApFlagRequest {
    magic:          [0x46, 0x4C, 0x00, 0x01], // "FL\x00\x01"
    pending:        false,
    flag_type:      0,
    operation:      0,
    _pad0:          0,
    flag_id:        0,
    value:          0,
    scene_index:    0xFFFF,
    response_ready: false,
    _pad1:          0,
    response_value: 0,
};

// ─── AP_WARP_REQUEST ───────────────────────────────────────────────────
// Backs the /warp command. Python locates this struct by scanning for
// magic bytes "WR\x00\x01". This layout must stay in sync with
// AP_WARP_REQUEST_STRUCT in SSHDClient.py.
//
// Layout (packed, little-endian, 20 bytes total):
//   +0  magic [u8; 4]        — "WR\x00\x01"
//   +4  pending bool         — 1 = new request for us to process; we clear
//                              it back to 0 as soon as we pick it up
//   +5  mode u8              — 0 = warp to start (Fi warp), 1 = warp to
//                              an explicit stage
//   +6  layer u8             — target layer for mode=1; 0xFF = unspecified
//                              (treated as 0). Unused for mode=0.
//   +7  _pad0 u8
//   +8  stage_name [u8; 8]   — ASCII stage code, null-padded (e.g.
//                              "F000\0\0\0\0"). Unused for mode=0.
//   +16 response_ready bool  — we set this to 1 once response_code is valid
//   +17 response_code u8     — 0 = ok, 1 = failed (null pointers / invalid
// mode)   +18 _pad1 [u8; 2]
#[repr(C, packed(1))]
pub struct ApWarpRequest {
    pub magic:          [u8; 4],
    pub pending:        bool,
    pub mode:           u8,
    pub layer:          u8,
    pub _pad0:          u8,
    pub stage_name:     [u8; 8],
    pub response_ready: bool,
    pub response_code:  u8,
    pub _pad1:          [u8; 2],
}
assert_eq_size!([u8; 20], ApWarpRequest);

#[no_mangle]
pub static mut AP_WARP_REQUEST: ApWarpRequest = ApWarpRequest {
    magic:          [0x57, 0x52, 0x00, 0x01], // "WR\x00\x01"
    pending:        false,
    mode:           0,
    layer:          0xFF,
    _pad0:          0,
    stage_name:     [0u8; 8],
    response_ready: false,
    response_code:  0,
    _pad1:          [0u8; 2],
};

const WARP_MODE_START: u8 = 0;
const WARP_MODE_STAGE: u8 = 1;

// Flag type discriminants — must match FLAG_TYPES in SSHDClient.py
const FLAG_TYPE_STORYFLAG: u8 = 0;
const FLAG_TYPE_SCENEFLAG: u8 = 1;
const FLAG_TYPE_ITEMFLAG: u8 = 2;
const FLAG_TYPE_DUNGEONFLAG: u8 = 3;

// Operation discriminants — must match FLAG_OPS in SSHDClient.py
const FLAG_OP_GET: u8 = 0;
const FLAG_OP_SET: u8 = 1;
const FLAG_OP_UNSET: u8 = 2;

// Sentinel meaning "use the current/local scene" for sceneflag/dungeonflag.
const SCENE_INDEX_CURRENT: u16 = 0xFFFF;

// IMPORTANT: when using vanilla code, the start point must be declared in
// symbols.yaml and then added to this extern block.
extern "C" {
    // Functions
    fn debugPrint_128(string: *const c_char, fstr: *const c_char, ...);
}

// IMPORTANT: when adding functions here that need to get called from the game,
// add `#[no_mangle]` and add a .global *symbolname* to
// additions/rust-additions.asm

////////////////////////
// ADD FUNCTIONS HERE //
////////////////////////

// ─── Flag get / set / unset ────────────────────────────────────────────
// Backs the /flag command. We never guess whether an ID is a boolean flag
// or a multi-bit counter — we just call the real FlagMgr functions in
// flag.rs, which already know.

/// Processes at most one AP_FLAG_REQUEST per call (one-shot, same pattern
/// as the spawn-request handlers above).
pub fn handle_flag_request() {
    unsafe {
        if !AP_FLAG_REQUEST.pending {
            return;
        }
        // Clear first so this is one-shot even if we return early below.
        AP_FLAG_REQUEST.pending = false;
        AP_FLAG_REQUEST.response_ready = false;

        let flag_type = AP_FLAG_REQUEST.flag_type;
        let operation = AP_FLAG_REQUEST.operation;
        let flag_id = AP_FLAG_REQUEST.flag_id;
        let value = AP_FLAG_REQUEST.value;
        let scene_index = AP_FLAG_REQUEST.scene_index;

        let result: u32 = match flag_type {
            FLAG_TYPE_STORYFLAG => handle_storyflag(operation, flag_id, value),
            FLAG_TYPE_ITEMFLAG => handle_itemflag(operation, flag_id, value),
            FLAG_TYPE_SCENEFLAG => handle_sceneflag(operation, flag_id, scene_index),
            FLAG_TYPE_DUNGEONFLAG => handle_dungeonflag(operation, flag_id, scene_index),
            _ => 0,
        };

        AP_FLAG_REQUEST.response_value = result;
        AP_FLAG_REQUEST.response_ready = true;
    }
}

/// Storyflags: flag.rs already takes raw u16 ids directly (no enum), and
/// set_storyflag_or_counter_to_value already does the right thing for both
/// booleans and counters. We treat value<=1 as "boolean set" (matches
/// vanilla set_storyflag semantics) and anything else as an explicit
/// counter value.
fn handle_storyflag(operation: u8, flag_id: u16, value: u16) -> u32 {
    match operation {
        FLAG_OP_GET => flag::check_storyflag(flag_id),
        FLAG_OP_SET => {
            if value <= 1 {
                flag::set_storyflag(flag_id);
            } else {
                flag::set_storyflag_or_counter_to_value(flag_id, value);
            }
            flag::check_storyflag(flag_id)
        },
        FLAG_OP_UNSET => {
            flag::unset_storyflag(flag_id);
            flag::check_storyflag(flag_id)
        },
        _ => 0,
    }
}

/// Itemflags: ITEMFLAGS is a #[repr(u16)] enum with big numeric gaps between
/// named variants, so transmuting an arbitrary raw id into it would be UB
/// for any unlisted id. We use the *_raw functions added to flag.rs instead,
/// which call straight into the FlagMgr function pointers without touching
/// the enum at all — this covers boolean itemflags (e.g. bug flags
/// 0x8D-0x98) and counters (e.g. DEKU_SEED_COUNTER = 0x1ED) identically.
fn handle_itemflag(operation: u8, flag_id: u16, value: u16) -> u32 {
    let result = match operation {
        FLAG_OP_GET => return flag::check_itemflag_raw(flag_id),
        FLAG_OP_SET => {
            if value <= 1 {
                flag::set_itemflag_raw(flag_id);
            } else {
                flag::set_itemflag_or_counter_to_value_raw(flag_id, value);
            }
            flag::check_itemflag_raw(flag_id)
        },
        FLAG_OP_UNSET => {
            flag::unset_itemflag_raw(flag_id);
            flag::check_itemflag_raw(flag_id)
        },
        _ => 0,
    };
    // set_flag/unset_flag/set_flag_or_counter_to_value only write the
    // uncommitted copy — commit so the get_flag_or_counter readback above
    // (and any other reader) sees the change immediately.
    flag::commit_itemflags();
    result
}

/// Sceneflags: 0xFFFF scene_index means "the room the player is standing in
/// right now" (local sceneflag funcs), anything else targets that scene
/// directly regardless of where the player currently is (global sceneflag
/// funcs, same ones handle_startflags uses).
fn handle_sceneflag(operation: u8, flag_id: u16, scene_index: u16) -> u32 {
    if scene_index == SCENE_INDEX_CURRENT {
        match operation {
            FLAG_OP_GET => flag::check_local_sceneflag(flag_id as u32) as u32,
            FLAG_OP_SET => {
                flag::set_local_sceneflag(flag_id as u32);
                flag::check_local_sceneflag(flag_id as u32) as u32
            },
            FLAG_OP_UNSET => {
                flag::unset_local_sceneflag(flag_id as u32);
                flag::check_local_sceneflag(flag_id as u32) as u32
            },
            _ => 0,
        }
    } else {
        match operation {
            FLAG_OP_GET => flag::check_global_sceneflag(scene_index, flag_id) as u32,
            FLAG_OP_SET => {
                flag::set_global_sceneflag(scene_index, flag_id);
                flag::check_global_sceneflag(scene_index, flag_id) as u32
            },
            FLAG_OP_UNSET => {
                flag::unset_global_sceneflag(scene_index, flag_id);
                flag::check_global_sceneflag(scene_index, flag_id) as u32
            },
            _ => 0,
        }
    }
}

/// Dungeonflags: unlike sceneflags, flag.rs exposes no "local/current room"
/// variant for dungeonflags today — every call is keyed by an explicit
/// scene index. If the Python client didn't supply one (0xFFFF), we fall
/// back to scene 0 rather than silently doing nothing; callers who care
/// about a specific dungeon should always pass a scene index explicitly
/// (e.g. `/flag dungeonflag get 3 12`).
fn handle_dungeonflag(operation: u8, flag_id: u16, scene_index: u16) -> u32 {
    let scene = if scene_index == SCENE_INDEX_CURRENT {
        0
    } else {
        scene_index
    };
    match operation {
        FLAG_OP_GET => flag::check_global_dungeonflag(scene, flag_id) as u32,
        FLAG_OP_SET => {
            flag::set_global_dungeonflag(scene, flag_id);
            flag::check_global_dungeonflag(scene, flag_id) as u32
        },
        FLAG_OP_UNSET => {
            flag::unset_global_dungeonflag(scene, flag_id);
            flag::check_global_dungeonflag(scene, flag_id) as u32
        },
        _ => 0,
    }
}

/// Processes at most one AP_WARP_REQUEST per call (one-shot, same pattern
/// as the spawn/flag request handlers).
pub fn handle_warp_request() {
    unsafe {
        if !AP_WARP_REQUEST.pending {
            return;
        }
        // Clear first so this is one-shot even if we return early below.
        AP_WARP_REQUEST.pending = false;
        AP_WARP_REQUEST.response_ready = false;

        let ok = match AP_WARP_REQUEST.mode {
            WARP_MODE_START => entrance::warp_to_start(),
            WARP_MODE_STAGE => {
                let layer = if AP_WARP_REQUEST.layer == 0xFF {
                    0
                } else {
                    AP_WARP_REQUEST.layer
                };
                entrance::warp_to_stage(AP_WARP_REQUEST.stage_name, layer)
            },
            _ => false,
        };

        AP_WARP_REQUEST.response_code = if ok { 0 } else { 1 };
        AP_WARP_REQUEST.response_ready = true;
    }
}
