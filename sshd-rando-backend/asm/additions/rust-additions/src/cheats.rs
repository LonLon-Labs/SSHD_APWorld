#![allow(non_camel_case_types)]
#![allow(non_snake_case)]
#![allow(unused)]

use crate::flag;
use crate::input;
use crate::player;
use crate::savefile;
use crate::traps;
use core::ffi::c_char;
use core::ptr::{addr_of, read_unaligned};
use static_assertions::assert_eq_size;

// ─── Extern symbols ──────────────────────────────────────────────────────

extern "C" {
    static PLAYER_PTR: *mut player::dPlayer;
    static FILE_MGR: *mut savefile::FileMgr;
    static mut CURRENT_STAGE_NAME: [u8; 8];
}

// ─── Cheat enable flags (written by Python client via /cheat toggle)
// ─────────
//
// Python locates this struct at runtime by scanning for magic bytes
// "CF\x00\x01". Offsets within the struct:
//   +0   magic                [u8; 4]  — "CF\x00\x01"
//   +4   moon_jump            bool     — Y-button moon jump
//   +5   hovercraft           bool     — X + L-stick hovercraft
//   +6   _pad                 [u8; 2]  — alignment padding
//   +8   hover_vel_y_bits     u32      — f32 bits: lower-clamp for hover vel_y
//   +12  infinite_health      bool
//   +13  infinite_stamina     bool
//   +14  infinite_ammo        bool
//   +15  infinite_bugs        bool
//   +16  infinite_materials   bool
//   +17  infinite_shield      bool
//   +18  infinite_skyward_strike bool
//   +19  infinite_rupees      bool
//   +20  infinite_loftwing    bool
//   +21  no_electric_stun     bool
//   +22  spawn_demise_request bool     — one-shot trigger from /sapwn_demise
//   +23  _pad2                [u8; 1]
//   +24  speed_multiplier_bits u32     — f32 bits; 0 or 0x3F800000 = disabled
//   +28  no_enemy_damage      bool     — blocks enemy damage + knockback
// reactions

#[repr(C, packed(1))]
pub struct ApCheatFlags {
    pub magic:                   [u8; 4], // +0  "CF\x00\x01" — Python magic scan key
    pub moon_jump:               bool,    // +4  toggled by /cheat moon_jump
    pub hovercraft:              bool,    // +5  toggled by /cheat hovercraft
    pub _pad:                    [u8; 2], // +6..7 alignment
    pub hover_vel_y_bits:        u32,     // +8  f32 bits for hover sustain clamp
    pub infinite_health:         bool,    // +12
    pub infinite_stamina:        bool,    // +13
    pub infinite_ammo:           bool,    // +14
    pub infinite_bugs:           bool,    // +15
    pub infinite_materials:      bool,    // +16
    pub infinite_shield:         bool,    // +17
    pub infinite_skyward_strike: bool,    // +18
    pub infinite_rupees:         bool,    // +19
    pub infinite_loftwing:       bool,    // +20
    pub no_electric_stun:        bool,    // +21
    pub spawn_demise_request:    bool,    // +22 one-shot manual spawn trigger
    pub _pad2:                   [u8; 1], // +23 alignment
    pub speed_multiplier_bits:   u32,     // +24 f32 bits; 0 or 0x3F800000 = disabled
    pub no_enemy_damage:         bool,    // +28 blocks enemy damage + knockback
}
assert_eq_size!([u8; 29], ApCheatFlags);

// The live instance of this struct now lives at AP_IPC_ROOT.cheat_flags
// (see ipc.rs) instead of a standalone static, so the external client
// only needs ONE scan (for AP_IPC_ROOT.magic) to find every mailbox,
// this one included.

// Python locates this struct by scanning for magic bytes "SA\x00\x01".
// Layout (packed):
//   +0   magic                 [u8; 4]  — "SA\x00\x01"
//   +4   request               bool     — one-shot spawn trigger
//   +5   _pad0                 [u8; 1]
//   +6   actorid               u16      — ACTORID value
//   +8   actor_param1          u32
//   +12  actor_param2          u32
//   +16  oarc_name             [u8; 32] — null-terminated ASCII, optional
#[repr(C, packed(1))]
pub struct ApSpawnRequest {
    pub magic:        [u8; 4],
    pub request:      bool,
    pub _pad0:        [u8; 1],
    pub actorid:      u16,
    pub actor_param1: u32,
    pub actor_param2: u32,
    pub oarc_name:    [u8; 32],
}
assert_eq_size!([u8; 48], ApSpawnRequest);

// The live instance of this struct now lives at AP_IPC_ROOT.spawn_request
// (see ipc.rs) instead of a standalone static, for the same reason as
// ApCheatFlags above.

// Loftwing (dBird) pointer obtained each frame via the player vtable.
// Only valid while current_action == ON_BIRD; cleared when dismounted.
// Exposed as pub so CE can read the address (subsdk8_base + symbol_offset).
pub static mut MY_BIRD_PTR: *mut player::dBird = core::ptr::null_mut();

// Byte offset of the spiral-charge field from the START of the dBird struct.
// usize::MAX = not yet discovered.  Once any candidate write succeeds, this
// is set and reused for all future frames and stages without needing the
// player-relative candidate table (which varies by build/heap layout).
static mut CHARGE_FIELD_DBIRD_OFFSET: usize = usize::MAX;

// Tracks whether X was held on the previous frame so we can fire the
// takeoff kick exactly once when X is first pressed.
static mut PREV_X_HELD: bool = false;

// Turn throttle counter.  The turn step fires once every TURN_INTERVAL frames
// so the player gets discrete, controllable angular increments rather than a
// continuous blur at 60 Hz.  At 60 Hz, interval=6 → 10 steps/sec.
static mut TURN_FRAME: u8 = 0;
const TURN_INTERVAL: u8 = 6;

// Health value captured every frame the player is NOT in an enemy hit/
// knockback reaction.  When no_enemy_damage is enabled and the player then
// enters one of those reaction states, this cached value is written back so
// the single hit that triggered the reaction is undone regardless of how
// much damage it dealt.
static mut PRE_HIT_HEALTH: u16 = 0;

// ─── Public API ──────────────────────────────────────────────────────────

pub fn handle_moon_jump() {
    unsafe {
        if !crate::ipc::AP_IPC_ROOT.cheat_flags.moon_jump {
            return;
        }
        if PLAYER_PTR.is_null() {
            return;
        }

        if input::check_button_held_down(input::BUTTON_INPUTS::Y_BUTTON) {
            let mut target_vel: f32;

            if input::check_button_held_down(input::BUTTON_INPUTS::R_BUTTON) {
                if input::check_button_held_down(input::BUTTON_INPUTS::L_BUTTON) {
                    if input::check_button_held_down(input::BUTTON_INPUTS::ZR_BUTTON) {
                        target_vel = 500.0;
                    } else {
                        target_vel = 250.0;
                    }
                } else {
                    target_vel = 100.0;
                }
            } else {
                target_vel = 35.0;
            }

            let current_vel_y = (*PLAYER_PTR).obj_base_members.velocity.y;

            if current_vel_y <= 0.0f32 {
                (*PLAYER_PTR).obj_base_members.velocity.y = target_vel.max(105.0f32);
            } else if current_vel_y < target_vel {
                (*PLAYER_PTR).obj_base_members.velocity.y = target_vel;
            }
        }
    }
}

pub fn handle_hovercraft() {
    unsafe {
        if !crate::ipc::AP_IPC_ROOT.cheat_flags.hovercraft {
            PREV_X_HELD = false;
            return;
        }
        if PLAYER_PTR.is_null() {
            PREV_X_HELD = false;
            return;
        }

        let x_held = input::check_button_held_down(input::BUTTON_INPUTS::X_BUTTON);
        if !x_held {
            PREV_X_HELD = false;
            return;
        }

        let vel_y = (*PLAYER_PTR).obj_base_members.velocity.y;
        let hover_floor = f32::from_bits(crate::ipc::AP_IPC_ROOT.cheat_flags.hover_vel_y_bits);
        if !PREV_X_HELD {
            if vel_y > -5.0f32 {
                (*PLAYER_PTR).obj_base_members.velocity.y = hover_floor + 100.0f32;
            } else {
                (*PLAYER_PTR).obj_base_members.velocity.y = hover_floor;
            }
        } else if vel_y < hover_floor {
            (*PLAYER_PTR).obj_base_members.velocity.y = hover_floor;
        }
        PREV_X_HELD = true;

        let speed_ptr = (PLAYER_PTR as *mut u8).add(0x64E8) as *mut f32;
        *speed_ptr = 0.0f32;

        if input::check_button_held_down(input::BUTTON_INPUTS::LEFT_STICK_DOWN) {
            *speed_ptr = -22.9995f32;
        }

        if input::check_button_held_down(input::BUTTON_INPUTS::LEFT_STICK_UP) {
            if input::check_button_held_down(input::BUTTON_INPUTS::R_BUTTON) {
                if input::check_button_held_down(input::BUTTON_INPUTS::L_BUTTON) {
                    if input::check_button_held_down(input::BUTTON_INPUTS::ZR_BUTTON) {
                        if input::check_button_held_down(input::BUTTON_INPUTS::ZL_BUTTON) {
                            *speed_ptr = 1000.0f32;
                        } else {
                            *speed_ptr = 500.0f32;
                        }
                    } else {
                        *speed_ptr = 250.0f32;
                    }
                } else {
                    *speed_ptr = 100.0f32;
                }
            } else {
                *speed_ptr = 50.0f32;
            }
        }

        TURN_FRAME = TURN_FRAME.wrapping_add(1);
        let do_turn = TURN_FRAME >= TURN_INTERVAL;
        if do_turn {
            TURN_FRAME = 0;
        }
        if do_turn && input::check_button_held_down(input::BUTTON_INPUTS::LEFT_STICK_LEFT) {
            let rot_hi_ptr = (PLAYER_PTR as *mut u8).add(0x13F);
            let copy_hi_ptr = (PLAYER_PTR as *mut u8).add(0x1D7);
            let new_hi = (*rot_hi_ptr).wrapping_add(0x0A);
            *rot_hi_ptr = new_hi;
            *copy_hi_ptr = new_hi;
        }

        if do_turn && input::check_button_held_down(input::BUTTON_INPUTS::LEFT_STICK_RIGHT) {
            let rot_hi_ptr = (PLAYER_PTR as *mut u8).add(0x13F);
            let copy_hi_ptr = (PLAYER_PTR as *mut u8).add(0x1D7);
            let new_hi = (*rot_hi_ptr).wrapping_sub(0x0A);
            *rot_hi_ptr = new_hi;
            *copy_hi_ptr = new_hi;
        }
    }
}

pub fn handle_infinite_health() {
    unsafe {
        if !crate::ipc::AP_IPC_ROOT.cheat_flags.infinite_health {
            return;
        }
        if FILE_MGR.is_null() {
            return;
        }
        let cap = (*FILE_MGR).FA.health_capacity;
        if cap > 0 {
            (*FILE_MGR).FA.current_health = cap;
        }
    }
}

pub fn handle_infinite_stamina() {
    unsafe {
        if !crate::ipc::AP_IPC_ROOT.cheat_flags.infinite_stamina {
            return;
        }
        if PLAYER_PTR.is_null() {
            return;
        }
        let stage = &CURRENT_STAGE_NAME[..5];
        let stamina_ptr: *mut u32 = if stage == b"F103\0" {
            (PLAYER_PTR as *mut u8).offset(-0x7FA8isize) as *mut u32
        } else if stage == b"B301\0" {
            (PLAYER_PTR as *mut u8).add(0x5CD8) as *mut u32
        } else {
            core::ptr::addr_of_mut!((*PLAYER_PTR).stamina_amount)
        };
        *stamina_ptr = 1_000_000;
        (*PLAYER_PTR).stamina_recovery_timer = 0;
        (*PLAYER_PTR).something_we_use_for_stamina = 0;
    }
}

pub fn handle_infinite_ammo() {
    unsafe {
        if !crate::ipc::AP_IPC_ROOT.cheat_flags.infinite_ammo {
            return;
        }

        let mut bomb_capacity = 9;
        if !FILE_MGR.is_null() {
            let pouch = read_unaligned(addr_of!((*FILE_MGR).FA.pouch_items));
            for &pouch_val in pouch.iter() {
                let item_id = (pouch_val & 0xFF) as u8;
                match item_id {
                    0x5C => bomb_capacity += 0,
                    0x86 => bomb_capacity += 5,
                    0x87 => bomb_capacity += 10,
                    0x88 => bomb_capacity += 15,
                    _ => {},
                }
            }
        }

        flag::set_itemflag_or_counter_to_value(flag::ITEMFLAGS::BOMB_COUNTER, bomb_capacity as u16);
        flag::set_itemflag_or_counter_to_value(flag::ITEMFLAGS::ARROW_COUNTER, 20);
        flag::set_itemflag_or_counter_to_value(flag::ITEMFLAGS::DEKU_SEED_COUNTER, 20);
    }
}

pub fn handle_infinite_bugs() {
    unsafe {
        if !crate::ipc::AP_IPC_ROOT.cheat_flags.infinite_bugs {
            return;
        }
        for id in 0x8Du16..=0x98u16 {
            flag::set_itemflag_raw(id);
        }
    }
}

pub fn handle_infinite_materials() {
    unsafe {
        if !crate::ipc::AP_IPC_ROOT.cheat_flags.infinite_materials {
            return;
        }
        for id in 0xA1u16..=0xB0u16 {
            flag::set_itemflag_raw(id);
        }
    }
}

pub fn handle_infinite_shield() {
    unsafe {
        if !crate::ipc::AP_IPC_ROOT.cheat_flags.infinite_shield {
            return;
        }
        if PLAYER_PTR.is_null() || FILE_MGR.is_null() {
            return;
        }
        (*PLAYER_PTR).shield_burn_timer = 0;
        let slot = (*FILE_MGR).FA.shield_pouch_slot;
        if slot < 8 {
            let pouch_val = (*FILE_MGR).FA.pouch_items[slot as usize];
            let item_id = (pouch_val & 0xFF) as u8;
            if item_id >= 0x74 && item_id <= 0x7D {
                let repaired = item_id as i32 | (0x30 << 16);
                if pouch_val != repaired {
                    (*FILE_MGR).FA.pouch_items[slot as usize] = repaired;
                }
            }
        }
    }
}

pub fn handle_infinite_skyward_strike() {
    unsafe {
        if !crate::ipc::AP_IPC_ROOT.cheat_flags.infinite_skyward_strike {
            return;
        }
        if PLAYER_PTR.is_null() {
            return;
        }
        if (*PLAYER_PTR).skyward_strike_timer > 0 {
            (*PLAYER_PTR).skyward_strike_timer = 300;
        }
    }
}

pub fn handle_infinite_rupees() {
    unsafe {
        if !crate::ipc::AP_IPC_ROOT.cheat_flags.infinite_rupees {
            return;
        }
        flag::set_itemflag_or_counter_to_value(flag::ITEMFLAGS::RUPEE_COUNTER, 9999);
    }
}

pub fn handle_infinite_loftwing() {
    unsafe {
        if !crate::ipc::AP_IPC_ROOT.cheat_flags.infinite_loftwing {
            MY_BIRD_PTR = core::ptr::null_mut();
            return;
        }
        if PLAYER_PTR.is_null() {
            MY_BIRD_PTR = core::ptr::null_mut();
            return;
        }

        let action = (*PLAYER_PTR).current_action;
        if action != player::PLAYER_ACTIONS::ON_BIRD {
            MY_BIRD_PTR = core::ptr::null_mut();
            return;
        }

        let get_bird_fn: extern "C" fn(*mut player::dPlayer) -> *mut player::dBird =
            core::mem::transmute((*(*PLAYER_PTR).vtable).get_riding_actor);
        let bird_ptr = get_bird_fn(PLAYER_PTR);
        MY_BIRD_PTR = bird_ptr;

        if bird_ptr.is_null() {
            return;
        }

        let bird_start = bird_ptr as usize;
        let bird_end = bird_start + core::mem::size_of::<player::dBird>();

        if CHARGE_FIELD_DBIRD_OFFSET != usize::MAX {
            let charge_ptr = (bird_start + CHARGE_FIELD_DBIRD_OFFSET) as *mut u32;
            let current = *charge_ptr;
            if current <= 3 {
                *charge_ptr = 3;
            }
            return;
        }

        let stage = &CURRENT_STAGE_NAME[..5];
        let candidates: &[isize] = if stage == b"F020\0" {
            &[-0xB57E6isize, -0x8B24Eisize]
        } else if stage == b"F023\0" {
            &[-0x37A2Eisize]
        } else {
            return;
        };
        for &offset in candidates {
            let cand_addr = (PLAYER_PTR as isize + offset) as usize;
            if cand_addr >= bird_start && cand_addr + 4 <= bird_end {
                let charge_ptr = cand_addr as *mut u32;
                let current = *charge_ptr;
                if current <= 3 {
                    *charge_ptr = 3;
                    CHARGE_FIELD_DBIRD_OFFSET = cand_addr - bird_start;
                }
            }
        }
    }
}

pub fn handle_no_electric_stun() {
    unsafe {
        if !crate::ipc::AP_IPC_ROOT.cheat_flags.no_electric_stun {
            return;
        }
        if PLAYER_PTR.is_null() {
            return;
        }
        (*PLAYER_PTR).shock_effect_timer = 0;
        let action = (*PLAYER_PTR).current_action;
        if action == player::PLAYER_ACTIONS::DAMAGE_ELECTRIC
            || action == player::PLAYER_ACTIONS::ELECTRICUTED_MAYBE
        {
            (*PLAYER_PTR).current_action = player::PLAYER_ACTIONS::HIT_BY_ENEMY;
        }
    }
}

pub fn handle_no_enemy_damage() {
    unsafe {
        if !crate::ipc::AP_IPC_ROOT.cheat_flags.no_enemy_damage {
            return;
        }

        if PLAYER_PTR.is_null() || FILE_MGR.is_null() {
            return;
        }

        (*PLAYER_PTR).damage_cooldown = u16::MAX;
        (*PLAYER_PTR).shock_effect_timer = 0;

        let action = (*PLAYER_PTR).current_action;
        let in_enemy_hit_reaction = action == player::PLAYER_ACTIONS::HIT_BY_ENEMY
            || action == player::PLAYER_ACTIONS::SMALL_DAMAGE
            || action == player::PLAYER_ACTIONS::KNOCK_BACK
            || action == player::PLAYER_ACTIONS::DAMAGE_ELECTRIC
            || action == player::PLAYER_ACTIONS::ELECTRICUTED_MAYBE
            || action == player::PLAYER_ACTIONS::RECOVER;

        if !in_enemy_hit_reaction {
            PRE_HIT_HEALTH = (*FILE_MGR).FA.current_health;
            return;
        }

        (*PLAYER_PTR).current_action = player::PLAYER_ACTIONS::IDLE;

        (*PLAYER_PTR).obj_base_members.velocity.x = 0.0;
        (*PLAYER_PTR).obj_base_members.velocity.z = 0.0;

        if action == player::PLAYER_ACTIONS::DAMAGE_ELECTRIC
            || action == player::PLAYER_ACTIONS::ELECTRICUTED_MAYBE
        {
            (*PLAYER_PTR).obj_base_members.velocity.y = 105.0;
        }

        if PRE_HIT_HEALTH > 0 {
            (*FILE_MGR).FA.current_health = PRE_HIT_HEALTH;
        }
    }
}

pub fn handle_speed_multiplier() {
    unsafe {
        let mult_bits = crate::ipc::AP_IPC_ROOT.cheat_flags.speed_multiplier_bits;
        if mult_bits == 0 || mult_bits == 0x3F800000u32 {
            return;
        }
        if PLAYER_PTR.is_null() {
            return;
        }
        let multiplier = f32::from_bits(mult_bits);
        let speed = (*PLAYER_PTR).obj_base_members.forward_speed;
        if speed > 0.1f32 && speed < 200.0f32 {
            (*PLAYER_PTR).obj_base_members.forward_speed = speed * multiplier;
        }
    }
}

/// Services one-shot DeathLink / BreathLink RECEIVE requests written by the
/// host client into `AP_IPC_ROOT.link_requests`. Each flag is cleared as soon
/// as it is consumed, so it acts exactly once.
pub fn handle_link_requests() {
    unsafe {
        let kill_ptr = core::ptr::addr_of_mut!(crate::ipc::AP_IPC_ROOT.link_requests.kill_request);
        let drain_ptr =
            core::ptr::addr_of_mut!(crate::ipc::AP_IPC_ROOT.link_requests.drain_stamina_request);

        // DeathLink: kill Link by zeroing current health.
        if core::ptr::read_volatile(kill_ptr) != 0 {
            core::ptr::write_volatile(kill_ptr, 0);
            if !FILE_MGR.is_null() && (*FILE_MGR).FA.health_capacity > 0 {
                (*FILE_MGR).FA.current_health = 0;
                // Keep no_enemy_damage's cached value from undoing the kill.
                PRE_HIT_HEALTH = 0;
            }
        }

        // BreathLink: zero stamina and trigger the exhaustion state (same
        // three fields the health trap in traps.rs writes).
        if core::ptr::read_volatile(drain_ptr) != 0 {
            core::ptr::write_volatile(drain_ptr, 0);
            if !PLAYER_PTR.is_null() {
                let stage = &CURRENT_STAGE_NAME[..5];
                let stamina_ptr: *mut u32 = if stage == b"F103\0" {
                    (PLAYER_PTR as *mut u8).offset(-0x7FA8isize) as *mut u32
                } else if stage == b"B301\0" {
                    (PLAYER_PTR as *mut u8).add(0x5CD8) as *mut u32
                } else {
                    core::ptr::addr_of_mut!((*PLAYER_PTR).stamina_amount)
                };
                *stamina_ptr = 0;
                (*PLAYER_PTR).something_we_use_for_stamina = 0x5A;
                (*PLAYER_PTR).stamina_recovery_timer = 64;
            }
        }
    }
}

pub fn handle_spawn_demise_request() {
    unsafe {
        if !crate::ipc::AP_IPC_ROOT.cheat_flags.spawn_demise_request {
            return;
        }

        crate::ipc::AP_IPC_ROOT.cheat_flags.spawn_demise_request = false;
        traps::spawn_demise_manual_current_stage();
    }
}

pub fn handle_spawn_actor_request() {
    unsafe {
        if !crate::ipc::AP_IPC_ROOT.spawn_request.request {
            return;
        }

        crate::ipc::AP_IPC_ROOT.spawn_request.request = false;

        let actorid = crate::ipc::AP_IPC_ROOT.spawn_request.actorid;
        let actor_param1 = crate::ipc::AP_IPC_ROOT.spawn_request.actor_param1;
        let actor_param2 = crate::ipc::AP_IPC_ROOT.spawn_request.actor_param2;
        let oarc_ptr = crate::ipc::AP_IPC_ROOT.spawn_request.oarc_name.as_ptr() as *const c_char;

        traps::spawn_actor_manual_current_stage(actorid, actor_param1, actor_param2, oarc_ptr);
    }
}
