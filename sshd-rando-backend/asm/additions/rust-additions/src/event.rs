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

    #[allow(clashing_extern_declarations)]
    static PLAYER_PTR: *mut u8;

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
    tick_fi_cant_drop();
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
                    let entry_ptr =
                        core::ptr::addr_of!(crate::ipc::AP_IPC_ROOT.item_info_table.entries[idx]);
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
            // param2 holds the item id in bits 0-8; the patcher may put trap bits above
            // that (bits 11-14), so mask to the 9-bit id instead of using the raw value.
            let itemid: u16 = event_flow_element.param2 & 0x1FF;
            let custom_flag = event_flow_element.param4 as u8;
            give_item_with_sceneflag(itemid, custom_flag);
        },
        // Set global flag for Archipelago custom flag detection
        // param1 = flag index (0-127), param2 = actual scene index (6, 13, 16, or 19)
        // param4 = flag_space_trigger (0 = sceneflag, 1 = dungeonflag)
        80 => set_global_sceneflag_for_ap(event_flow_element),
        // Set string args for Archipelago Item (216) textbox.
        81 => set_ap_item_string_args(actor_event_flow_mgr),
        // Is a Fi "can't drop down" message pending? (result 0 = no, 1 = yes)
        82 => fi_cant_drop_check(actor_event_flow_mgr),
        // Is the pending message a no-Sailcloth one? (0 = no statue, 1 = Sailcloth).
        // Re-checks the Sailcloth itemflag live, so a stale cache can't win.
        84 => fi_cant_drop_is_sailcloth(actor_event_flow_mgr),
        // Bit `param1` of the no-Sailcloth text variant (0..=6), so the flow can
        // pick one of the 7 texts with plain 0/1 switches.
        85 => fi_cant_drop_variant_bit(actor_event_flow_mgr, event_flow_element.param1),
        // Fi message finished: mark the request done (no void-out)
        83 => fi_cant_drop_finish(),
        _ => (),
    }

    // The replaced instructions (ldrh w8, [x1, #0xa]; mov w21, #1) are now
    // executed by the ASM wrapper `_ce_wrapper` in the landing pad, AFTER
    // this function's epilogue. This prevents the compiler from clobbering
    // w21 (a callee-saved register) in the epilogue — which would break all
    // type-3 event flows.
}

// ---------------------------------------------------------------------------
// Fi "can't drop down" message (light pillar with no droppable Bird Statue).
//
// The vanilla player update (FUN_7100a69ccc) only asks the Fi alert chooser
// while certain gates pass, and on the Loftwing they don't. We never start a
// Fi event ourselves (no event vtable, no Fi controller pokes). Instead we
// make the game's own update do it, using only the plain byte
// FI_CANT_DROP_PENDING:
//   1. The pillar hook calls start_fi_cant_drop_event(), which only sets the
//      byte to REQUESTED. Nothing else happens in the hook: no void-out, no
//      scene change, the player just stays in the sky.
//   2. While REQUESTED, fi_cant_drop_gate_pending() (landingpad 104, called by
//      two patched loads of player+0x41d) makes the bird gate pass and sends
//      the sky branch down the ordinary no-target path, and
//      fi_proactive_alert_override() (103) turns the chooser's answer into
//      alert 6000, so the game starts ordinary_sword_sprit itself.
//   3. The patched 006-8KenseiNormal flow (eventpatches.yaml, index 2) asks
//      command 82 whether a message is pending (REQUESTED -> SHOWING), shows
//      the custom text, then runs command 83 (SHOWING -> DONE).
//   4. tick_fi_cant_drop() (main loop) returns to IDLE once DONE and starts
//      the cooldown, and is the safety net: if the event never starts
//      (REQUESTED too long) or never finishes (SHOWING too long) it gives up
//      the same way. The no-statue message never voids out; the no-Sailcloth
//      message does, from the main loop, once the text is done or timed out.
//      Every path ends back at IDLE, so a request can never leak onto Skyloft.
//
// Everything here is a plain static byte/counter and integer math: no
// absolute-address reads, no &'static slices or pointer tables (they would be
// absolute pointers in the raw-patched blob).
// ---------------------------------------------------------------------------

/// State byte: 0 = idle, 1 = requested (set at the pillar, waiting for the
/// game to start the Fi event), 2 = the flow is showing the text, 3 = text
/// finished (the next main-loop tick returns to idle and starts the cooldown).
static mut FI_CANT_DROP_PENDING: u8 = 0;
/// Frames spent in the current non-idle state (used for the text timeout).
static mut FI_CANT_DROP_FRAMES: u16 = 0;
/// Frames left during which no new request may start. Set whenever a request
/// ends (message done or timeout) because the player may still be inside the
/// pillar trigger, and the pillar hook calls start_fi_cant_drop_event() every
/// frame. Only counts down while idle.
static mut FI_CANT_DROP_COOLDOWN: u16 = 0;
/// 2.5 s at 60 fps.
const FI_CANT_DROP_COOLDOWN_FRAMES: u16 = 150;

const FI_CANT_DROP_IDLE: u8 = 0;

/// Master switch for the Fi debug logging/dumps. Off: no log output.
const FI_DEBUG: bool = false;

/// Why the message was requested; selects the text the flow shows.
pub const FI_REASON_NO_STATUE: u8 = 1;
pub const FI_REASON_NO_SAILCLOTH: u8 = 2;
/// Flow result values 2..=9 are the eight no-Sailcloth text variants. Index 2
/// (variant 3, the backflip joke) is the rare one.
const FI_SAILCLOTH_FIRST_RESULT: u8 = 2;
const FI_SAILCLOTH_RARE_VARIANT: u8 = 2;
const FI_SAILCLOTH_COMMON_VARIANTS: u8 = 6;
/// Free-running frame counter (bumped every main-loop tick) used as the random
/// seed when a request starts. Plain integer math only.
static mut FI_RNG_COUNTER: u32 = 0;
static mut FI_CANT_DROP_REASON: u8 = FI_REASON_NO_STATUE;

/// True if the pending/last Fi "can't drop down" message is one of the
/// no-Sailcloth variants (flow results 2..=8). Those void the player out once
/// the message is done (or timed out); the no-statue message never does.
fn fi_cant_drop_reason_is_sailcloth() -> bool {
    let reason = unsafe { core::ptr::read_volatile(core::ptr::addr_of!(FI_CANT_DROP_REASON)) };
    reason >= FI_SAILCLOTH_FIRST_RESULT
}

/// Picks the flow result for a no-Sailcloth message: 1% the rare variant
/// (Text 3), 33% Text 1, otherwise one of the other eight with equal chance.
fn fi_pick_sailcloth_result() -> u8 {
    let mut x = unsafe { core::ptr::read_volatile(core::ptr::addr_of!(FI_RNG_COUNTER)) }
        .wrapping_mul(2654435761)
        | 1;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    let roll = x % 100;
    let variant = if roll == 0 {
        FI_SAILCLOTH_RARE_VARIANT
    } else if roll <= 33 {
        // Text 1 (variant 0)
        0
    } else {
        // Variants 1, 3, 4, 5, 6, 7, 8, 9 (skipping Text 1 and the rare Text 3).
        // Plain integer math, no tables.
        let n = ((x / 100) % 8) as u8;
        if n == 0 {
            1
        } else {
            n + 2
        }
    };
    FI_SAILCLOTH_FIRST_RESULT + variant
}
const FI_CANT_DROP_REQUESTED: u8 = 1;
const FI_CANT_DROP_SHOWING: u8 = 2;
const FI_CANT_DROP_DONE: u8 = 3;

/// Give up on the textbox flow after this many frames (30 s at 60 fps).
const FI_CANT_DROP_SHOW_TIMEOUT_FRAMES: u16 = 1800;
/// Give up waiting for the game to start the Fi event after this many frames
/// (3 s at 60 fps) and go back to idle (cooldown starts, no void-out).
const FI_CANT_DROP_REQUEST_TIMEOUT_FRAMES: u16 = 180;

#[inline(always)]
fn fi_cant_drop_state() -> u8 {
    unsafe { core::ptr::read_volatile(core::ptr::addr_of!(FI_CANT_DROP_PENDING)) }
}

#[inline(always)]
fn fi_cant_drop_set_state(state: u8) {
    unsafe {
        core::ptr::write_volatile(core::ptr::addr_of_mut!(FI_CANT_DROP_PENDING), state);
        core::ptr::write_volatile(core::ptr::addr_of_mut!(FI_CANT_DROP_FRAMES), 0);
    }
}

#[inline(always)]
fn fi_cant_drop_start_cooldown() {
    unsafe {
        core::ptr::write_volatile(
            core::ptr::addr_of_mut!(FI_CANT_DROP_COOLDOWN),
            FI_CANT_DROP_COOLDOWN_FRAMES,
        );
    }
}

/// True while a Fi "can't drop down" message is requested or being shown.
pub fn fi_cant_drop_in_progress() -> bool {
    fi_cant_drop_state() != FI_CANT_DROP_IDLE
}

/// Drops any pending/showing Fi "can't drop down" request (used when the
/// player is voided out early, e.g. dismounting the Loftwing near Skyloft
/// without the Sailcloth). Does not void out itself.
pub fn fi_cant_drop_abort() {
    fi_cant_drop_set_state(FI_CANT_DROP_IDLE);
    fi_cant_drop_start_cooldown();
    fi_force_player_449(false);
}

/// Requests the Fi "can't drop down" message. Only sets a plain byte (see the
/// header comment). Safe to call every frame while the player stays in the
/// pillar: it does nothing while a request is already active or cooling down.
/// Never voids the player out.
pub fn start_fi_cant_drop_event() -> bool {
    start_fi_cant_drop_event_with(FI_REASON_NO_STATUE)
}

/// Same as start_fi_cant_drop_event(), but picks which Fi text the flow shows
/// (FI_REASON_NO_STATUE or FI_REASON_NO_SAILCLOTH).
pub fn start_fi_cant_drop_event_with(reason: u8) -> bool {
    let cooling =
        unsafe { core::ptr::read_volatile(core::ptr::addr_of!(FI_CANT_DROP_COOLDOWN)) } != 0;
    if fi_cant_drop_state() == FI_CANT_DROP_REQUESTED
        && reason == FI_REASON_NO_SAILCLOTH
        && !fi_cant_drop_reason_is_sailcloth()
    {
        // The Sailcloth text always wins: a no-statue request that the game
        // has not started showing yet is upgraded to a Sailcloth one.
        unsafe {
            core::ptr::write_volatile(
                core::ptr::addr_of_mut!(FI_CANT_DROP_REASON),
                fi_pick_sailcloth_result(),
            );
        }
        return true;
    }
    if fi_cant_drop_state() == FI_CANT_DROP_IDLE && !cooling {
        let reason = if reason == FI_REASON_NO_SAILCLOTH {
            fi_pick_sailcloth_result()
        } else {
            reason
        };
        unsafe {
            core::ptr::write_volatile(core::ptr::addr_of_mut!(FI_CANT_DROP_REASON), reason);
        }
        fi_cant_drop_set_state(FI_CANT_DROP_REQUESTED);
        fi_clear_player_alert_cooldown();
        fi_force_player_449(true); // EXPERIMENT, see FI_FORCE_PLAYER_449
                                   // DEBUG (remove after the sky test)
        if FI_DEBUG {
            debug::debug_print_num(c"fi REQUESTED %d".as_ptr(), 1);
        }
    }
    true
}

/// The player update FUN_7100a69ccc only asks the Fi chooser once the plain
/// byte player+0x63de (a 5-frame cooldown) has counted down to 0, and it only
/// counts down on passes that get that far. In a pillar the player update
/// stops being called a few frames after the request (the player leaves the
/// flight state), so the chooser would never be reached. Clearing this one
/// plain player byte while a request is pending lets the very next pass ask
/// the chooser. Reads PLAYER_PTR, null-checked; writes one byte, no Fi
/// controller fields.
fn fi_clear_player_alert_cooldown() {
    unsafe {
        let p = PLAYER_PTR;
        if !p.is_null() {
            core::ptr::write_volatile(p.add(0x63DE), 0u8);
        }
    }
}

/// EXPERIMENT (decide after the sky test). The event manager's request
/// function FUN_7100b70290 silently returns 0 (request dropped) when the
/// request has flag bit 0 set (ours does: 0x100001) and bit 5 of the plain
/// player byte player+0x449 is clear. The game still sets Fi+0x1174 = 1
/// afterwards, so a dropped request looks like a successful one. While a
/// request is pending this sets that one bit (and restores it afterwards).
/// If the first sky test shows `fi REQ ret 0` with bit 5 clear, this is the
/// blocker; if the return is already 1, set this to false.
const FI_FORCE_PLAYER_449: bool = true;

static mut FI_449_SAVED: u8 = 0;
static mut FI_449_FORCED: bool = false;

fn fi_force_player_449(on: bool) {
    if !FI_FORCE_PLAYER_449 {
        return;
    }
    unsafe {
        // Idle fast path: never touch the player unless we forced the bit.
        if !on && !core::ptr::read_volatile(core::ptr::addr_of!(FI_449_FORCED)) {
            return;
        }
        let p = PLAYER_PTR;
        if p.is_null() {
            return;
        }
        let q = p.add(0x449);
        let cur = core::ptr::read_volatile(q);
        if on {
            if !core::ptr::read_volatile(core::ptr::addr_of!(FI_449_FORCED)) {
                core::ptr::write_volatile(core::ptr::addr_of_mut!(FI_449_SAVED), cur);
                core::ptr::write_volatile(core::ptr::addr_of_mut!(FI_449_FORCED), true);
                // DEBUG (remove after the sky test)
                if FI_DEBUG {
                    debug::debug_print_num(c"fi 449 orig %x".as_ptr(), cur as usize);
                }
            }
            core::ptr::write_volatile(q, cur | 0x20);
        } else if core::ptr::read_volatile(core::ptr::addr_of!(FI_449_FORCED)) {
            let saved = core::ptr::read_volatile(core::ptr::addr_of!(FI_449_SAVED));
            core::ptr::write_volatile(q, (cur & !0x20) | (saved & 0x20));
            core::ptr::write_volatile(core::ptr::addr_of_mut!(FI_449_FORCED), false);
        }
    }
}

/// Alert id of Fi's "ordinary_sword_sprit" event. The patched
/// 006-8KenseiNormal flow (eventpatches.yaml) shows the custom text for it.
const FI_ALERT_ORDINARY_SWORD_SPRIT: u32 = 6000;

/// Landingpad index 103. Replaces the result of the vanilla Fi proactive alert
/// chooser (see the stub in jumptable.asm). Takes and returns the plain alert
/// id; reads only the state byte. While a request is pending the game is told
/// to start ordinary_sword_sprit itself, so no event is built or started here.
#[no_mangle]
pub extern "C" fn fi_proactive_alert_override(alert: u32) -> u32 {
    // DEBUG (remove after the sky test)
    unsafe {
        let p = core::ptr::addr_of_mut!(FI_DBG_CHOOSER_HITS);
        let n = core::ptr::read_volatile(p).saturating_add(1);
        core::ptr::write_volatile(p, n);
        if FI_DEBUG && n <= 3 && fi_cant_drop_state() == FI_CANT_DROP_REQUESTED {
            debug::debug_print_num(c"fi chooser hit #%d".as_ptr(), n as usize);
        }
    }
    if fi_cant_drop_state() == FI_CANT_DROP_REQUESTED {
        FI_ALERT_ORDINARY_SWORD_SPRIT
    } else {
        alert
    }
}

/// Landingpad index 104. Returns 1 while the game should be made to run the Fi
/// event, else 0 (see the header comment and the stub in jumptable.asm).
#[no_mangle]
pub extern "C" fn fi_cant_drop_gate_pending() -> u32 {
    let pending = (fi_cant_drop_state() == FI_CANT_DROP_REQUESTED) as u32;
    // DEBUG (remove after the sky test): count calls made while pending.
    if pending != 0 {
        unsafe {
            let p = core::ptr::addr_of_mut!(FI_DBG_GATE_HITS);
            let n = core::ptr::read_volatile(p).saturating_add(1);
            core::ptr::write_volatile(p, n);
            if FI_DEBUG && n <= 2 {
                debug::debug_print_num(c"fi gate hit #%d".as_ptr(), n as usize);
            }
        }
    }
    pending
}

// DEBUG (remove after the sky test): number of hooked request calls seen.
static mut FI_DBG_REQ_CALLS: u16 = 0;

/// DEBUG (remove after the sky test). Landingpad index 106: runs just BEFORE
/// the player update's call to the event manager's request function
/// FUN_7100b70290 (stub at 0x7100659bd0, patched at 0x7100a6e770).
/// x0 = Fi object, x1 = the request struct. Prints exactly what that function
/// tests: request priority (+8), request flags (+0xc), request name (+0x18),
/// manager current id (mgr+0x50), manager lock byte (mgr+0x24d) and
/// player+0x449. Only the first 6 calls print.
#[no_mangle]
pub extern "C" fn fi_dbg_request_pre(fi: *const u8, req: *const u8) {
    if !FI_DEBUG {
        return;
    }
    unsafe {
        let p = core::ptr::addr_of_mut!(FI_DBG_REQ_CALLS);
        let n = core::ptr::read_volatile(p).saturating_add(1);
        core::ptr::write_volatile(p, n);
        if n > 6 {
            return;
        }
        debug::debug_print_num(c"fi REQ call #%d".as_ptr(), n as usize);
        if !req.is_null() {
            debug::debug_print_num(
                c"fi REQ prio %d".as_ptr(),
                core::ptr::read_volatile(req.add(8) as *const u32) as usize,
            );
            debug::debug_print_num(
                c"fi REQ flags %x".as_ptr(),
                core::ptr::read_volatile(req.add(0xC) as *const u32) as usize,
            );
            debug::debug_print_str(c"fi REQ name %s".as_ptr(), req.add(0x18) as *const c_char);
        }
        let mgr = core::ptr::read_volatile(core::ptr::addr_of!(DAT_710182ded8));
        if !mgr.is_null() {
            debug::debug_print_num(
                c"fi REQ pre m50 %x".as_ptr(),
                core::ptr::read_volatile(mgr.add(0x50) as *const u32) as usize,
            );
            debug::debug_print_num(
                c"fi REQ pre m24d %x".as_ptr(),
                core::ptr::read_volatile(mgr.add(0x24D)) as usize,
            );
        }
        let pl = PLAYER_PTR as *const u8;
        if !pl.is_null() {
            debug::debug_print_num(
                c"fi REQ pre 449 %x".as_ptr(),
                core::ptr::read_volatile(pl.add(0x449)) as usize,
            );
        }
        debug::debug_print_num(c"fi REQ pre fi==pl %d".as_ptr(), (fi == pl) as usize);
    }
}

/// DEBUG (remove after the sky test). Landingpad index 107: runs just AFTER
/// FUN_7100b70290 returned (x0 = its result: 0 = dropped by a check, 1 = ok,
/// which also covers "ignored because mgr+0x50 <= our priority").
#[no_mangle]
pub extern "C" fn fi_dbg_request_post(ret: u32) {
    if !FI_DEBUG {
        return;
    }
    unsafe {
        if core::ptr::read_volatile(core::ptr::addr_of!(FI_DBG_REQ_CALLS)) > 6 {
            return;
        }
        debug::debug_print_num(c"fi REQ ret %d".as_ptr(), ret as usize);
        let mgr = core::ptr::read_volatile(core::ptr::addr_of!(DAT_710182ded8));
        if !mgr.is_null() {
            debug::debug_print_num(
                c"fi REQ post m50 %x".as_ptr(),
                core::ptr::read_volatile(mgr.add(0x50) as *const u32) as usize,
            );
            debug::debug_print_str(
                c"fi REQ pending %s".as_ptr(),
                mgr.add(0x60) as *const c_char,
            );
        }
    }
}

/// DEBUG (remove after the sky test). Frames 1..=12 of REQUESTED, one packed
/// line plus the manager id per frame, so the frame where Fi+0x1174 is
/// cleared (or the manager starts the event) is visible.
/// "fi tick" value = frame<<24 | F1174<<16 | (mgr+0x248 != 0)<<12 |
/// player+0x449 bit 5 <<8 | (chooser hits & 0xff).  F1174 reads ff if the Fi
/// object pointer is null.
fn fi_dbg_tick(frames: u16) {
    if !FI_DEBUG {
        return;
    }
    unsafe {
        let pl = PLAYER_PTR as *const u8;
        if pl.is_null() {
            return;
        }
        let fi = core::ptr::read_volatile(pl.add(0x53C8) as *const u64) as *const u8;
        let f1174 = if fi.is_null() {
            0xFFusize
        } else {
            core::ptr::read_volatile(fi.add(0x1174)) as usize
        };
        let mgr = core::ptr::read_volatile(core::ptr::addr_of!(DAT_710182ded8));
        let (m248, m50) = if mgr.is_null() {
            (0usize, 0usize)
        } else {
            (
                (core::ptr::read_volatile(mgr.add(0x248) as *const u32) != 0) as usize,
                core::ptr::read_volatile(mgr.add(0x50) as *const u32) as usize,
            )
        };
        let b449 = ((core::ptr::read_volatile(pl.add(0x449)) >> 5) & 1) as usize;
        let hits = core::ptr::read_volatile(core::ptr::addr_of!(FI_DBG_CHOOSER_HITS)) as usize;
        let v =
            ((frames as usize) << 24) | (f1174 << 16) | (m248 << 12) | (b449 << 8) | (hits & 0xFF);
        debug::debug_print_num(c"fi tick %x".as_ptr(), v);
        debug::debug_print_num(c"fi tickm50 %x".as_ptr(), m50);
    }
}

// DEBUG (remove after the sky test)
static mut FI_DBG_STATE_HITS: u16 = 0;
static mut FI_DBG_ENTRY_PENDING: u16 = 0;
static mut FI_DBG_GATE_HITS: u16 = 0;
static mut FI_DBG_CHOOSER_HITS: u16 = 0;
static mut FI_DBG_ENTRY_HITS: u16 = 0;

// DEBUG (remove after the sky test): globals tested by the early-outs of
// FUN_7100a69ccc (declared in symbols.yaml).
extern "C" {
    static DAT_7102bf98fe: u8;
    static DAT_710182ded8: *const u8;
    static DAT_710192fb58: u64;
    static DAT_710166cc10: i32;
}

/// DEBUG (remove after the sky test). Landingpad index 105: called from the
/// entry of FUN_7100a69ccc (stub in jumptable.asm) to count how often the
/// player update runs while the request is pending.
#[no_mangle]
pub extern "C" fn fi_dbg_entry() {
    // Counts unconditionally (also while idle) so it can be checked on Skyloft.
    unsafe {
        let p = core::ptr::addr_of_mut!(FI_DBG_ENTRY_HITS);
        core::ptr::write_volatile(p, core::ptr::read_volatile(p).saturating_add(1));
        if fi_cant_drop_state() == FI_CANT_DROP_REQUESTED {
            let q = core::ptr::addr_of_mut!(FI_DBG_ENTRY_PENDING);
            let n = core::ptr::read_volatile(q).saturating_add(1);
            core::ptr::write_volatile(q, n);
            if FI_DEBUG && n <= 3 {
                debug::debug_print_num(c"fi entry pending #%d".as_ptr(), n as usize);
            }
        }
    }
}

// DEBUG (remove after the sky test): frame counter for the idle entry print.
static mut FI_DBG_IDLE_FRAMES: u16 = 0;

// DEBUG (remove after the sky test): while idle, prints the unconditional
// entry count every 300 frames so it can be read on plain Skyloft.
fn fi_dbg_idle_print() {
    unsafe {
        let fp = core::ptr::addr_of_mut!(FI_DBG_IDLE_FRAMES);
        let f = core::ptr::read_volatile(fp).wrapping_add(1);
        core::ptr::write_volatile(fp, f);
        if FI_DEBUG && f % 300 == 0 {
            debug::debug_print_num(
                c"fi idle entryhits %d".as_ptr(),
                core::ptr::read_volatile(core::ptr::addr_of!(FI_DBG_ENTRY_HITS)) as usize,
            );
        }
    }
}

// DEBUG (remove after the sky test): prints the player bytes the gates in
// FUN_7100a69ccc test, plus how often the gate stub / chooser hook ran.
fn fi_debug_dump() {
    if !FI_DEBUG {
        return;
    }
    unsafe {
        let p = PLAYER_PTR as *const u8;
        if p.is_null() {
            return;
        }
        let b = |o: usize| core::ptr::read_volatile(p.add(o)) as usize;
        let h = |o: usize| core::ptr::read_volatile(p.add(o) as *const u16) as usize;
        let w = |o: usize| core::ptr::read_volatile(p.add(o) as *const u32) as usize;
        debug::debug_print_num(
            c"fi entryhits %d".as_ptr(),
            core::ptr::read_volatile(core::ptr::addr_of!(FI_DBG_ENTRY_HITS)) as usize,
        );
        debug::debug_print_num(
            c"fi entrypending %d".as_ptr(),
            core::ptr::read_volatile(core::ptr::addr_of!(FI_DBG_ENTRY_PENDING)) as usize,
        );
        debug::debug_print_num(
            c"fi forcedcalls %d".as_ptr(),
            core::ptr::read_volatile(core::ptr::addr_of!(FI_DBG_STATE_HITS)) as usize,
        );
        debug::debug_print_num(c"fi 6034 %x".as_ptr(), w(0x6034));
        debug::debug_print_num(c"fi 5470lo %x".as_ptr(), w(0x5470));
        debug::debug_print_num(
            c"fi g98fe %d".as_ptr(),
            core::ptr::read_volatile(core::ptr::addr_of!(DAT_7102bf98fe)) as usize,
        );
        let mgr = core::ptr::read_volatile(core::ptr::addr_of!(DAT_710182ded8));
        if mgr.is_null() {
            debug::debug_print_num(c"fi ded8 null %d".as_ptr(), 0);
        } else {
            debug::debug_print_num(
                c"fi ded8+248 %x".as_ptr(),
                core::ptr::read_volatile(mgr.add(0x248) as *const u32) as usize,
            );
        }
        debug::debug_print_num(
            c"fi fb58 %x".as_ptr(),
            core::ptr::read_volatile(core::ptr::addr_of!(DAT_710192fb58)) as usize,
        );
        debug::debug_print_num(
            c"fi cc10 %d".as_ptr(),
            core::ptr::read_volatile(core::ptr::addr_of!(DAT_710166cc10)) as usize,
        );
        debug::debug_print_num(
            c"fi gatehits %d".as_ptr(),
            core::ptr::read_volatile(core::ptr::addr_of!(FI_DBG_GATE_HITS)) as usize,
        );
        debug::debug_print_num(
            c"fi chooserhits %d".as_ptr(),
            core::ptr::read_volatile(core::ptr::addr_of!(FI_DBG_CHOOSER_HITS)) as usize,
        );
        debug::debug_print_num(c"fi 41d %d".as_ptr(), b(0x41D));
        debug::debug_print_num(c"fi 63de %d".as_ptr(), b(0x63DE));
        debug::debug_print_num(c"fi 460 %x".as_ptr(), w(0x460));
        debug::debug_print_num(c"fi 458 %x".as_ptr(), w(0x458));
        debug::debug_print_num(c"fi 454 %x".as_ptr(), b(0x454));
        debug::debug_print_num(c"fi 642e %x".as_ptr(), h(0x642E));
        debug::debug_print_num(c"fi 6428 %x".as_ptr(), h(0x6428));
        debug::debug_print_num(c"fi 6404 %x".as_ptr(), h(0x6404));
        debug::debug_print_num(c"fi 466 %x".as_ptr(), b(0x466));
        debug::debug_print_num(c"fi 3f50 %x".as_ptr(), w(0x3F50));
        debug::debug_print_num(c"fi 73b0 %d".as_ptr(), b(0x73B0));
        // The event-start path (0x7100a6a29c on) uses x24 = fi_obj + 0x1174 as its
        // "already started" byte and sets it after the request, not player+0x73b0.
        let fi = core::ptr::read_volatile(p.add(0x53C8) as *const u64) as *const u8;
        if fi.is_null() {
            debug::debug_print_num(c"fi fiobj null %d".as_ptr(), 0);
        } else {
            debug::debug_print_num(
                c"fi F1174 %x".as_ptr(),
                core::ptr::read_volatile(fi.add(0x1174)) as usize,
            );
            debug::debug_print_num(
                c"fi F1170 %x".as_ptr(),
                core::ptr::read_volatile(fi.add(0x1170) as *const u32) as usize,
            );
            debug::debug_print_num(
                c"fi F115c %x".as_ptr(),
                core::ptr::read_volatile(fi.add(0x115C) as *const u32) as usize,
            );
            debug::debug_print_num(
                c"fi F1508 %x".as_ptr(),
                core::ptr::read_volatile(fi.add(0x1508) as *const u32) as usize,
            );
            debug::debug_print_num(
                c"fi Fe70 %x".as_ptr(),
                core::ptr::read_volatile(fi.add(0xE70) as *const u16) as usize,
            );
        }
        // Bit 5 of player+0x63f0 is what the game tests at 0x7100a6a294.
        debug::debug_print_num(c"fi 63f0 %x".as_ptr(), b(0x63F0));
        // What the event manager's request function tests (see fi_dbg_request_pre).
        debug::debug_print_num(c"fi 449 %x".as_ptr(), b(0x449));
        let mgr2 = core::ptr::read_volatile(core::ptr::addr_of!(DAT_710182ded8));
        if !mgr2.is_null() {
            debug::debug_print_num(
                c"fi m50 %x".as_ptr(),
                core::ptr::read_volatile(mgr2.add(0x50) as *const u32) as usize,
            );
            debug::debug_print_num(
                c"fi m24d %x".as_ptr(),
                core::ptr::read_volatile(mgr2.add(0x24D)) as usize,
            );
            debug::debug_print_str(c"fi mname %s".as_ptr(), mgr2.add(0x60) as *const c_char);
        }
    }
}

/// Per-frame (main loop): times the request out and finishes it. No void-out.
/// Always ends back at IDLE.
fn tick_fi_cant_drop() {
    unsafe {
        let c = core::ptr::addr_of_mut!(FI_RNG_COUNTER);
        core::ptr::write_volatile(c, core::ptr::read_volatile(c).wrapping_add(1));
    }
    let state = fi_cant_drop_state();
    if state != FI_CANT_DROP_REQUESTED {
        fi_force_player_449(false);
    }
    if state == FI_CANT_DROP_IDLE {
        unsafe {
            let c = core::ptr::addr_of_mut!(FI_CANT_DROP_COOLDOWN);
            let v = core::ptr::read_volatile(c);
            if v != 0 {
                core::ptr::write_volatile(c, v - 1);
            }
        }
        fi_dbg_idle_print(); // DEBUG (remove after the sky test)
        return;
    }
    if state == FI_CANT_DROP_DONE {
        // No Sailcloth: the message is shown first, then the player voids out
        // (same as the old behavior when dropping down without the Sailcloth).
        let sailcloth = fi_cant_drop_reason_is_sailcloth();
        fi_cant_drop_set_state(FI_CANT_DROP_IDLE);
        fi_cant_drop_start_cooldown();
        if sailcloth {
            entrance::voidout_now();
        }
        return;
    }
    let limit = if state == FI_CANT_DROP_REQUESTED {
        FI_CANT_DROP_REQUEST_TIMEOUT_FRAMES
    } else {
        FI_CANT_DROP_SHOW_TIMEOUT_FRAMES
    };
    unsafe {
        if state == FI_CANT_DROP_REQUESTED {
            fi_clear_player_alert_cooldown();
            fi_force_player_449(true);
        }
        let frames_ptr = core::ptr::addr_of_mut!(FI_CANT_DROP_FRAMES);
        let frames = core::ptr::read_volatile(frames_ptr).saturating_add(1);
        core::ptr::write_volatile(frames_ptr, frames);
        // DEBUG (remove after the sky test)
        if state == FI_CANT_DROP_REQUESTED && frames <= 12 {
            fi_dbg_tick(frames);
        }
        // DEBUG (remove after the sky test)
        if state == FI_CANT_DROP_REQUESTED
            && (frames == 2 || frames == 10 || frames == 30 || frames == 90 || frames == 150)
        {
            fi_debug_dump();
        }
        if frames >= limit {
            // Safety net: if the Fi event never started or never finished, a
            // no-Sailcloth request still voids the player out so they can't
            // be left hanging at the drop.
            let sailcloth = fi_cant_drop_reason_is_sailcloth();
            fi_cant_drop_set_state(FI_CANT_DROP_IDLE);
            fi_cant_drop_start_cooldown();
            if sailcloth {
                entrance::voidout_now();
            }
        }
    }
}

#[inline(never)]
fn fi_cant_drop_check(actor_event_flow_mgr: *mut ActorEventFlowMgr) {
    unsafe {
        let pending = fi_cant_drop_state() == FI_CANT_DROP_REQUESTED;
        if pending {
            // Flow is showing the text now; switch to the text timeout.
            fi_cant_drop_set_state(FI_CANT_DROP_SHOWING);
        }
        (*actor_event_flow_mgr).result_from_previous_check = pending as u32;
    }
}

/// Custom command 84. Result 1 if the pending message is a no-Sailcloth one.
/// Runs inside the event flow, where the flag getters are safe, so the
/// Sailcloth itemflag is checked live: if the player has no Sailcloth the
/// message is always upgraded to a Sailcloth one, whatever the hook decided.
#[inline(never)]
fn fi_cant_drop_is_sailcloth(actor_event_flow_mgr: *mut ActorEventFlowMgr) {
    unsafe {
        if !fi_cant_drop_reason_is_sailcloth()
            && flag::check_itemflag(flag::ITEMFLAGS::SAILCLOTH) == 0
        {
            core::ptr::write_volatile(
                core::ptr::addr_of_mut!(FI_CANT_DROP_REASON),
                fi_pick_sailcloth_result(),
            );
        }
        (*actor_event_flow_mgr).result_from_previous_check =
            fi_cant_drop_reason_is_sailcloth() as u32;
    }
}

/// Custom command 85. Result = bit `bit` of the no-Sailcloth text variant
/// (reason - 2, i.e. 0..=6 for Text 1..=7).
#[inline(never)]
fn fi_cant_drop_variant_bit(actor_event_flow_mgr: *mut ActorEventFlowMgr, bit: u16) {
    unsafe {
        let reason = core::ptr::read_volatile(core::ptr::addr_of!(FI_CANT_DROP_REASON));
        let variant = reason.saturating_sub(FI_SAILCLOTH_FIRST_RESULT) as u32;
        (*actor_event_flow_mgr).result_from_previous_check = (variant >> (bit as u32 & 7)) & 1;
    }
}

/// Custom command 83. Runs after the text has been shown; marks the request
/// done so tick_fi_cant_drop() returns to idle and starts the cooldown.
#[inline(never)]
fn fi_cant_drop_finish() {
    fi_cant_drop_set_state(FI_CANT_DROP_DONE);
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
            let entry_ptr =
                core::ptr::addr_of!(crate::ipc::AP_IPC_ROOT.item_info_table.entries[idx]);
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
