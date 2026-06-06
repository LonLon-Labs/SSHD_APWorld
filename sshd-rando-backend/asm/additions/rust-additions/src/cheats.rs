#![allow(non_camel_case_types)]
#![allow(non_snake_case)]
#![allow(unused)]

use crate::flag;
use crate::input;
use crate::player;
use crate::savefile;
use static_assertions::assert_eq_size;

// ─── Extern symbols
// ──────────────────────────────────────────────────────────

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
//   +22  _pad2                [u8; 2]
//   +24  speed_multiplier_bits u32     — f32 bits; 0 or 0x3F800000 = disabled

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
    pub _pad2:                   [u8; 2], // +22..23 alignment
    pub speed_multiplier_bits:   u32,     // +24 f32 bits; 0 or 0x3F800000 = disabled
}
assert_eq_size!([u8; 28], ApCheatFlags);

#[no_mangle]
pub static mut AP_CHEAT_FLAGS: ApCheatFlags = ApCheatFlags {
    magic:                   [0x43, 0x46, 0x00, 0x01], // "CF\x00\x01"
    moon_jump:               false,
    hovercraft:              false,
    _pad:                    [0u8; 2],
    hover_vel_y_bits:        0x3FECCCCDu32, // 1.85f32 — cancels gravity at 60 Hz
    infinite_health:         false,
    infinite_stamina:        false,
    infinite_ammo:           false,
    infinite_bugs:           false,
    infinite_materials:      false,
    infinite_shield:         false,
    infinite_skyward_strike: false,
    infinite_rupees:         false,
    infinite_loftwing:       false,
    no_electric_stun:        false,
    _pad2:                   [0u8; 2],
    speed_multiplier_bits:   0u32,
};

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

// ─── Public API
// ──────────────────────────────────────────────────────────────

/// Direct translation of:
///
///   [Y for moon jump]
///   80000008                           ; if Y held
///   540F0000 0623E86C                  ; reg15 = f32[player+0x1EC]  (vel_y)
///   04000000 0623E86C 420C0000         ; f32[player+0x1EC] = 35.0   (sustain)
///   C045F400 00000000                  ; if reg15 (old vel_y) <= 0.0:
///   04000000 0623E86C 42D20000         ;   f32[player+0x1EC] = 105.0  (kick)
///   20000000                           ; end inner conditional
///   20000000                           ; end outer (Y held) conditional
pub fn handle_moon_jump() {
    unsafe {
        if !AP_CHEAT_FLAGS.moon_jump {
            return;
        }
        if PLAYER_PTR.is_null() {
            return;
        }

        if input::check_button_held_down(input::BUTTON_INPUTS::Y_BUTTON) {
            let mut target_vel: f32;

            // ── Turbo Logic (Vertical) ──────────────────────────────────────
            if input::check_button_held_down(input::BUTTON_INPUTS::R_BUTTON) {
                if input::check_button_held_down(input::BUTTON_INPUTS::L_BUTTON) {
                    if input::check_button_held_down(input::BUTTON_INPUTS::ZR_BUTTON) {
                        // L + R + ZR: Super Rocket
                        target_vel = 500.0;
                    } else {
                        // L + R: Rocket
                        target_vel = 250.0;
                    }
                } else {
                    // R: Fast ascent
                    target_vel = 100.0;
                }
            } else {
                // Standard Moon Jump sustain
                target_vel = 35.0;
            }

            let current_vel_y = (*PLAYER_PTR).obj_base_members.velocity.y;

            // vel_y <= 0 means on the ground or falling — apply a kick strong
            // enough to break surface contact (at least 105.0, or the turbo
            // target if that's already higher).
            // vel_y > 0 means already airborne — sustain at target_vel.
            if current_vel_y <= 0.0f32 {
                (*PLAYER_PTR).obj_base_members.velocity.y = target_vel.max(105.0f32);
            } else if current_vel_y < target_vel {
                (*PLAYER_PTR).obj_base_members.velocity.y = target_vel;
            }
        }
    }
}
/// Direct translation of:
///
///   [X hover craft mode, use Lstick to move]
///
///   ; ── Always while X is held
/// ──────────────────────────────────────────────   80000004
/// ; if X held   540F0000 0623E86C                  ; reg15 =
/// f32[player+0x1EC]  (vel_y)   04000000 0623E86C 40A00000         ;
/// f32[player+0x1EC] = 5.0    (sustain)   04000000 06244B68 00000000         ;
/// f32[player+0x64E8] = 0.0   (speed_override = stop)   C045F400 00000000
/// ; if reg15 (old vel_y) <= 0.0:   04000000 0623E86C 42D20000         ;
/// f32[player+0x1EC] = 105.0  (gravity kick)   20000000
/// ; end inner conditional   20000000                           ; end outer (X
/// held) conditional
///
///   ; ── X + L-stick down → move backward ─────────────────────────────────
///   80080004                           ; if X + L-stick-down held
///   04000000 06244B68 C1B7FEFA         ; f32[player+0x64E8] = -22.9995
/// (back)   20000000                           ; end conditional
///
///   ; ── X + L-stick up → move forward ────────────────────────────────────
///   80020004                           ; if X + L-stick-up held
///   04000000 06244B68 42480000         ; f32[player+0x64E8] = 50.0  (forward)
///   20000000                           ; end conditional
///
///   ; ── X + L-stick left → turn left ──────────────────────────────────────
///   80010004                           ; if X + L-stick-left held
///   580F0000 0623E7BF                  ; reg15 = u8[player+0x13F]  (rot.y
/// high byte)   910FF100 0000000A                  ; reg15 += 0x0A
///   A1F00400 0623E7BF                  ; u8[player+0x13F]  = reg15  (rot.y
/// high byte)   A1F00400 0623E857                  ; u8[player+0x1D7]  = reg15
/// (rot_copy.y high byte)   20000000                           ; end
/// conditional
///
///   ; ── X + L-stick right → turn right ────────────────────────────────────
///   80040004                           ; if X + L-stick-right held
///   580F0000 0623E7BF                  ; reg15 = u8[player+0x13F]  (rot.y
/// high byte)   911FF100 0000000A                  ; reg15 -= 0x0A
///   A1F00400 0623E7BF                  ; u8[player+0x13F]  = reg15
///   A1F00400 0623E857                  ; u8[player+0x1D7]  = reg15
///   20000000                           ; end conditional
///
/// Field paths (verified against assert_eq_size offsets):
///   player+0x1EC  = obj_base_members.velocity.y
///   player+0x64E8 = speed_override  (outside dPlayer struct boundary 0x64DC,
///                                    raw pointer write required)
///   player+0x13E  = obj_base_members.base.rot.y  (u16)
///   player+0x13F  = high byte of rot.y
///   player+0x1D6  = obj_base_members.rot_copy.y  (u16)
///   player+0x1D7  = high byte of rot_copy.y
pub fn handle_hovercraft() {
    unsafe {
        if !AP_CHEAT_FLAGS.hovercraft {
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

        // ── Vertical velocity management ────────────────────────────────────
        //
        // The Atmosphere cheat fired infrequently, so its 5.0/105.0 conditional
        // worked by averaging over many physics frames.  We run at 60 Hz, so
        // the conditional causes visible jitter (105 kick triggers every few
        // frames as gravity pulls vel_y back to ≤ 0) and drift (any positive
        // sustain value overshoots the gravity constant).
        //
        // Strategy: lower-clamp vel_y to hover_vel_y (default 0.0).
        //   • vel_y < hover_vel_y  →  snap up to hover_vel_y (stops the fall)
        //   • vel_y ≥ hover_vel_y  →  leave it alone (moon jump / jump decay
        //                              naturally; no extra upward force added)
        //
        // This produces zero drift at hover_vel_y = 0.0 because we never write
        // a positive value during steady-state float.  Set hover_vel_y > 0 via
        // "/cheat hovercraft <value>" for a controlled slow rise.
        //
        // First frame only: kick to 105.0 so the player lifts off the ground
        // (ground contact keeps vel_y near 0, the clamp alone can't escape it).
        // handle_moon_jump() runs before us in main_loop_inject, so if Y is
        // also held it already wrote ≥ 35; our first-frame kick is then a no-op
        // because the clamp sees vel_y ≥ 0 already.
        let vel_y = (*PLAYER_PTR).obj_base_members.velocity.y;
        let hover_floor = f32::from_bits(AP_CHEAT_FLAGS.hover_vel_y_bits);
        if !PREV_X_HELD {
            // First frame X pressed.
            // Near the ground vel_y is close to 0 (physics holds it there).
            // A modest escape kick of hover_floor + 20 is enough to break
            // surface contact without rocket-launching the player.
            //
            // When genuinely falling vel_y is deeply negative (can be -300+).
            // Writing 105 there would shoot the player 2800+ units upward.
            // Instead, just clamp to hover_floor to stop the fall in place.
            if vel_y > -5.0f32 {
                // On ground or barely airborne — gentle liftoff kick
                (*PLAYER_PTR).obj_base_members.velocity.y = hover_floor + 100.0f32;
            } else {
                // Falling — stop momentum cleanly, no upward launch
                (*PLAYER_PTR).obj_base_members.velocity.y = hover_floor;
            }
        } else if vel_y < hover_floor {
            // Steady hover: clamp from below — never add upward force above floor
            (*PLAYER_PTR).obj_base_members.velocity.y = hover_floor;
        }
        PREV_X_HELD = true;

        // Zero out speed_override so the player is stationary horizontally
        // unless a directional L-stick block below overrides it.
        // speed_override lives at player+0x64E8, which is 8 bytes past the end
        // of the typed dPlayer struct (0x64DC), so use a raw byte-offset write.
        let speed_ptr = (PLAYER_PTR as *mut u8).add(0x64E8) as *mut f32;
        *speed_ptr = 0.0f32;

        // ── L-stick down → backward ─────────────────────────────────────────
        if input::check_button_held_down(input::BUTTON_INPUTS::LEFT_STICK_DOWN) {
            *speed_ptr = -22.9995f32; // 0xC1B7FEFA
        }

        // ── L-stick up → forward (with turbo) ──────────────────────────
        if input::check_button_held_down(input::BUTTON_INPUTS::LEFT_STICK_UP) {
            if input::check_button_held_down(input::BUTTON_INPUTS::R_BUTTON) {
                if input::check_button_held_down(input::BUTTON_INPUTS::L_BUTTON) {
                    if input::check_button_held_down(input::BUTTON_INPUTS::ZR_BUTTON) {
                        if input::check_button_held_down(input::BUTTON_INPUTS::ZL_BUTTON) {
                            // L+R+ZL+ZR turbo: go ludicrously fast
                            *speed_ptr = 1000.0f32;
                        } else {
                            // L+R+ZR turbo: go too fast
                            *speed_ptr = 500.0f32;
                        }
                    } else {
                        // L+R turbo: go really really fast
                        *speed_ptr = 250.0f32;
                    }
                } else {
                    // R turbo: go really fast
                    *speed_ptr = 100.0f32;
                }
            } else {
                // Standard hover speed
                *speed_ptr = 50.0f32;
            }
        }

        // ── L-stick left → turn left ────────────────────────────────────────
        // The cheat operates on the high byte of the u16 rot.y (+0x13E) and
        // its mirror rot_copy.y (+0x1D6).  Adding 0x0A to the high byte equals
        // adding 0x0A00 = 2560 u16 units (~14°) per step.
        // Throttled to once every TURN_INTERVAL frames for controllable steps.
        TURN_FRAME = TURN_FRAME.wrapping_add(1);
        let do_turn = TURN_FRAME >= TURN_INTERVAL;
        if do_turn {
            TURN_FRAME = 0;
        }
        if do_turn && input::check_button_held_down(input::BUTTON_INPUTS::LEFT_STICK_LEFT) {
            let rot_hi_ptr = (PLAYER_PTR as *mut u8).add(0x13F); // rot.y high byte
            let copy_hi_ptr = (PLAYER_PTR as *mut u8).add(0x1D7); // rot_copy.y high byte
            let new_hi = (*rot_hi_ptr).wrapping_add(0x0A);
            *rot_hi_ptr = new_hi;
            *copy_hi_ptr = new_hi;
        }

        // ── L-stick right → turn right ──────────────────────────────────────
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
        if !AP_CHEAT_FLAGS.infinite_health {
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
        if !AP_CHEAT_FLAGS.infinite_stamina {
            return;
        }
        if PLAYER_PTR.is_null() {
            return;
        }
        // Stamina field shifts in certain stages; use the same stage-keyed
        // offsets as the Python client (relative to PLAYER_PTR base address).
        let stage = &CURRENT_STAGE_NAME[..5];
        let stamina_ptr: *mut u32 = if stage == b"F103\0" {
            // Flooded Faron Woods — stamina at player_base - 0x7FA8
            (PLAYER_PTR as *mut u8).offset(-0x7FA8isize) as *mut u32
        } else if stage == b"B301\0" {
            // Tentalus boss — stamina at player_base + 0x5CD8
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
        if !AP_CHEAT_FLAGS.infinite_ammo {
            return;
        }
        flag::set_itemflag_or_counter_to_value(flag::ITEMFLAGS::ARROW_COUNTER, 20);
        flag::set_itemflag_or_counter_to_value(flag::ITEMFLAGS::BOMB_COUNTER, 20);
        flag::set_itemflag_or_counter_to_value(flag::ITEMFLAGS::DEKU_SEED_COUNTER, 20);
    }
}

pub fn handle_infinite_bugs() {
    unsafe {
        if !AP_CHEAT_FLAGS.infinite_bugs {
            return;
        }
        // Boolean itemflags 0x8D..=0x98 (FARON_GRASSHOPPER through STARRY_FIREFLY)
        for id in 0x8Du16..=0x98u16 {
            flag::set_itemflag_raw(id);
        }
    }
}

pub fn handle_infinite_materials() {
    unsafe {
        if !AP_CHEAT_FLAGS.infinite_materials {
            return;
        }
        // Boolean itemflags 0xA1..=0xB0 (HORNET_LAVAE through GODDESS_PLUME)
        for id in 0xA1u16..=0xB0u16 {
            flag::set_itemflag_raw(id);
        }
    }
}

pub fn handle_infinite_shield() {
    unsafe {
        if !AP_CHEAT_FLAGS.infinite_shield {
            return;
        }
        if PLAYER_PTR.is_null() || FILE_MGR.is_null() {
            return;
        }
        // Zero the shield burn timer so the shield never degrades
        (*PLAYER_PTR).shield_burn_timer = 0;
        // Restore durability in the pouch item slot so it shows as fully repaired
        let slot = (*FILE_MGR).FA.shield_pouch_slot;
        if slot < 8 {
            let pouch_val = (*FILE_MGR).FA.pouch_items[slot as usize];
            let item_id = (pouch_val & 0xFF) as u8;
            // Shield item IDs: 0x74 (Wooden Shield) through 0x7D (Hylian Shield)
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
        if !AP_CHEAT_FLAGS.infinite_skyward_strike {
            return;
        }
        if PLAYER_PTR.is_null() {
            return;
        }
        // Keep the timer at 300 whenever it is positive (sword is being charged
        // or is already charged).  Writing 300 while the timer is 0 would force
        // the charge animation to start even when the player isn't swinging.
        if (*PLAYER_PTR).skyward_strike_timer > 0 {
            (*PLAYER_PTR).skyward_strike_timer = 300;
        }
    }
}

pub fn handle_infinite_rupees() {
    unsafe {
        if !AP_CHEAT_FLAGS.infinite_rupees {
            return;
        }
        flag::set_itemflag_or_counter_to_value(flag::ITEMFLAGS::RUPEE_COUNTER, 9999);
    }
}

pub fn handle_infinite_loftwing() {
    unsafe {
        if !AP_CHEAT_FLAGS.infinite_loftwing {
            MY_BIRD_PTR = core::ptr::null_mut();
            return;
        }
        if PLAYER_PTR.is_null() {
            MY_BIRD_PTR = core::ptr::null_mut();
            return;
        }

        // Obtain the live dBird pointer via the player vtable.  This is
        // reliable across all builds because get_riding_actor (vtable+0x448)
        // resolves the actual actor pointer from the game engine regardless of
        // where the heap placed the dBird struct this session.
        //
        // IMPORTANT: get_riding_actor dereferences an internal sub-pointer that
        // is only initialised while the player action is ON_BIRD.  Guard here to
        // prevent a null-pointer crash when the player is on foot.
        let action = (*PLAYER_PTR).current_action;
        if action != player::PLAYER_ACTIONS::ON_BIRD {
            MY_BIRD_PTR = core::ptr::null_mut();
            return;
        }

        // Transmute: the vtable declaration omits the return type, but the
        // function actually returns *mut dBird.
        let get_bird_fn: extern "C" fn(*mut player::dPlayer) -> *mut player::dBird =
            core::mem::transmute((*(*PLAYER_PTR).vtable).get_riding_actor);
        let bird_ptr = get_bird_fn(PLAYER_PTR);
        MY_BIRD_PTR = bird_ptr;

        if bird_ptr.is_null() {
            return;
        }

        let bird_start = bird_ptr as usize;
        let bird_end = bird_start + core::mem::size_of::<player::dBird>();

        // Fast path: once we have identified the intra-dBird offset (either
        // from a prior candidate hit or from a previous session frame), use it
        // directly.  The charge field is at a fixed C++ struct offset in the
        // game binary, so it is constant across all heap layouts and stages.
        if CHARGE_FIELD_DBIRD_OFFSET != usize::MAX {
            let charge_ptr = (bird_start + CHARGE_FIELD_DBIRD_OFFSET) as *mut u32;
            let current = *charge_ptr;
            if current <= 3 {
                *charge_ptr = 3;
            }
            return;
        }

        // Discovery path: try empirically-known player-relative candidates.
        // dBird lands at different positions relative to dPlayer across emulator
        // builds, so multiple candidates are needed.  F023 (Thunderhead) has a
        // single reliable candidate and will typically seed the offset before
        // the player spends time in F020 (The Sky).
        // Only write when the candidate address is inside dBird (bounds-checked)
        // so stale offsets cannot corrupt unrelated memory.
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
                    // Cache the offset: all future frames skip the candidate
                    // table and use bird_ptr + CHARGE_FIELD_DBIRD_OFFSET.
                    CHARGE_FIELD_DBIRD_OFFSET = cand_addr - bird_start;
                }
            }
        }
    }
}

pub fn handle_no_electric_stun() {
    unsafe {
        if !AP_CHEAT_FLAGS.no_electric_stun {
            return;
        }
        if PLAYER_PTR.is_null() {
            return;
        }
        (*PLAYER_PTR).shock_effect_timer = 0;
        // Override the electric damage/stunlock actions with a generic hit
        // so the player is staggered briefly but not locked in the stun loop.
        let action = (*PLAYER_PTR).current_action;
        if action == player::PLAYER_ACTIONS::DAMAGE_ELECTRIC
            || action == player::PLAYER_ACTIONS::ELECTRICUTED_MAYBE
        {
            (*PLAYER_PTR).current_action = player::PLAYER_ACTIONS::HIT_BY_ENEMY;
        }
    }
}

pub fn handle_speed_multiplier() {
    unsafe {
        let mult_bits = AP_CHEAT_FLAGS.speed_multiplier_bits;
        // 0 = not configured; 0x3F800000 = 1.0 (identity) — both mean disabled
        if mult_bits == 0 || mult_bits == 0x3F800000u32 {
            return;
        }
        if PLAYER_PTR.is_null() {
            return;
        }
        let multiplier = f32::from_bits(mult_bits);
        let speed = (*PLAYER_PTR).obj_base_members.forward_speed;
        // Only apply in the normal movement speed range to prevent runaway
        // multiplication if the game or another system already modified speed.
        if speed > 0.1f32 && speed < 200.0f32 {
            (*PLAYER_PTR).obj_base_members.forward_speed = speed * multiplier;
        }
    }
}
