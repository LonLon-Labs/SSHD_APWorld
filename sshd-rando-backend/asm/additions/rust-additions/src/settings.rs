#![allow(non_camel_case_types)]
#![allow(non_snake_case)]
#![allow(unused)]

use crate::debug;

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

#[repr(C, packed(1))]
#[derive(Copy, Clone)]
pub struct RandomizerSettings {
    pub skip_harp_playing:         u8,
    pub sky_keep_beaten_sceneflag: i8,
    pub cutoff_game_over_music:    u8,
    pub archipelago_item_model:    u8, /* 0=letter, 1=archipelago_logo,
                                        * 2=unofficial_archipelago_logo */
    pub goddess_chest_unlock_mode: u8, /* 0 = vanilla (cube gated), 1 = unlocked after
                                        * Goddess Sword, 2 = unlocked from start. Modes 1
                                        * and 2 gate the chests on storyflag 95 */
    pub bird_statues_need_unlock:  u8, /* 1 = flying up from a statue also needs its
                                        * unlock flag (scene 6), see
                                        * lyt::require_sailcloth_and_loftwing_to_fly_to_sky */
    pub triforce_door_pieces:      u8, /* 1 or 2 = the Temple of Hylia door opens once this many
                                        * Triforce pieces are owned
                                        * (flag::handle_triforce_door_flag);
                                        * 0 = nothing to do */
    pub _pad:                      [u8; 1],
    pub ap_seed:                   [u8; 8], // u64 LE, 0 = unknown
    pub ap_slot_name:              [u16; 17], // UTF-16, null terminated
}
assert_eq_size!([u8; 50], RandomizerSettings);

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
