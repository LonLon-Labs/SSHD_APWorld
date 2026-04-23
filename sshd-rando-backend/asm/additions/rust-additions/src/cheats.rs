#![allow(non_camel_case_types)]
#![allow(non_snake_case)]
#![allow(unused)]

use crate::input;
use crate::player;
use static_assertions::assert_eq_size;

// ─── Extern symbols
// ──────────────────────────────────────────────────────────

extern "C" {
    static PLAYER_PTR: *mut player::dPlayer;
}

// ─── Cheat enable flags (written by Python client via /cheat toggle)
// ─────────
//
// Python locates this struct at runtime by scanning for magic bytes
// "CF\x00\x01". Offsets within the struct:
//   +0  magic           [u8; 4]  — "CF\x00\x01"
//   +4  moon_jump       bool     — enable Y-button moon jump
//   +5  hovercraft      bool     — enable X + L-stick hovercraft
//   +6  _pad            [u8; 2]  — alignment padding
//   +8  hover_vel_y_bits u32     — f32 bits: lower-clamp for hover vel_y
//                                  0x00000000 = 0.0 (stock stable hover)
//                                  Set via /cheat hovercraft <value>

#[repr(C, packed(1))]
pub struct ApCheatFlags {
    pub magic:            [u8; 4], // "CF\x00\x01" — Python magic scan key
    pub moon_jump:        bool,    // +4 toggled by /cheat moon_jump
    pub hovercraft:       bool,    // +5 toggled by /cheat hovercraft
    pub _pad:             [u8; 2], // +6..7 alignment
    pub hover_vel_y_bits: u32,     // +8 f32 bits for hover sustain clamp
}
assert_eq_size!([u8; 12], ApCheatFlags);

#[no_mangle]
pub static mut AP_CHEAT_FLAGS: ApCheatFlags = ApCheatFlags {
    magic:            [0x43, 0x46, 0x00, 0x01], // "CF\x00\x01"
    moon_jump:        false,
    hovercraft:       false,
    _pad:             [0u8; 2],
    hover_vel_y_bits: 0x3FECCCCDu32, // 1.85f32 — cancels gravity at 60 Hz
};

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
            let vel_y = (*PLAYER_PTR).obj_base_members.velocity.y; // player+0x1EC
            if vel_y <= 0.0f32 {
                (*PLAYER_PTR).obj_base_members.velocity.y = 105.0f32; // 0x42D20000
            } else {
                (*PLAYER_PTR).obj_base_members.velocity.y = 35.0f32; // 0x420C0000
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

        // ── L-stick up → forward ────────────────────────────────────────────
        if input::check_button_held_down(input::BUTTON_INPUTS::LEFT_STICK_UP) {
            *speed_ptr = 50.0f32; // 0x42480000
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
