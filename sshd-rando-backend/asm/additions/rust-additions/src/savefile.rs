#![allow(non_camel_case_types)]
#![allow(non_snake_case)]
#![allow(unused)]

use crate::debug;
use crate::math;

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

// FileMgr/SaveFile stuff
#[repr(C, packed(1))]
#[derive(Copy, Clone)]
pub struct FileMgr {
    pub all_save_files: u64,
    pub save_tails:     u64,
    pub FA:             SaveFile,
    pub FB:             SaveFile,
    pub _0:             [u8; 36],
    pub amiibo_pos:     math::Vec3f,
    pub amiibo_stage:   u64,
    pub _1:             [u8; 8740],
    pub game_options:   u8,
    pub _2:             [u8; 793],
    pub prevent_commit: bool,
    pub _3:             u8,
}
assert_eq_size!([u8; 52488], FileMgr);

#[repr(C, packed(1))]
#[derive(Copy, Clone)]
pub struct SaveFile {
    pub save_time:                 u64, // size is a guess
    pub unk:                       u64,
    pub _0:                        [u8; 1968],
    pub pouch_items:               [i32; 8],
    pub item_check_items:          [i32; 60],
    pub padding_maybe:             u32,
    pub player_name:               [u16; 8],
    pub storyflags:                [u16; 128],
    pub itemflags:                 [u16; 64],
    // The save file reserves 0x1000 bytes (256 indexes of 8 u16) for each of the
    // dungeonflag and sceneflag arrays, but the game only ever uses indexes 0-25.
    // Indexes 26-29 are exposed here for the Archipelago extended custom flag
    // group (see GROUP1_FIRST_SCENE_INDEX in item.rs). Keep the total size of
    // each array + its padding at 4096 bytes.
    pub dungeonflags:              [[u16; 8]; 30],
    pub _1:                        [u8; 3568],
    // Archipelago seed/slot block, stored in the unused tail of the dungeonflag
    // array's 0x1000 byte reservation (indexes 253-255, never used by the game).
    pub ap_save_data:              ApSaveData,
    pub sceneflags:                [[u16; 8]; 30],
    pub _2:                        [u8; 0xE20],
    pub tboxflags:                 [[u8; 4]; 26],
    pub _3:                        [u8; 0x498],
    pub enemy_kill_counters:       [u16; 100],
    pub hit_by_enemy_counters:     [u16; 100],
    pub tempflags:                 [u16; 4],
    pub zoneflags:                 [[u16; 4]; 63],
    pub stage_object_flags:        [u16; 4096],
    pub _4:                        [u8; 14],
    pub health_capacity:           u16,
    pub some_health_related_thing: u16,
    pub current_health:            u16,
    pub _5:                        [u8; 148],
    pub skykeep_room_layout:       [u8; 9],
    pub unk21413:                  u8,
    pub unk21414:                  u8,
    pub current_layer:             u8,
    pub unk21416:                  u8,
    pub unk21417:                  u8,
    pub unk21418:                  u8,
    pub current_entrance:          u8,
    pub unk21420:                  u8,
    pub is_new_file:               bool,
    pub selected_b_wheel_slot:     u8,
    pub unk21423:                  u8,
    pub selected_pouch_slot:       u8,
    pub shield_pouch_slot:         u8,
    pub selected_dowsing_slot:     u8,
    pub unk21427:                  u8,
    pub current_night:             u8,
    pub is_auto_save:              u8,
    pub unkfiller5:                [u8; 10],
}
assert_eq_size!([u8; 21440], SaveFile);

/// Seed and slot name of the multiworld a save file belongs to. Written when
/// a new file is created (see flag::handle_startflags).
#[repr(C, packed(1))]
#[derive(Copy, Clone)]
pub struct ApSaveData {
    pub magic:     [u8; 4], // b"APSD"
    pub seed:      [u8; 8], // u64 LE
    pub slot_name: [u16; 17],
    pub _pad:      [u8; 2],
}
assert_eq_size!([u8; 48], ApSaveData);

pub const AP_SAVE_MAGIC: [u8; 4] = *b"APSD";

// IMPORTANT: when using vanilla code, the start point must be declared in
// symbols.yaml and then added to this extern block.
extern "C" {
    static FILE_MGR: *mut FileMgr;
    static RANDOMIZER_SETTINGS: crate::settings::RandomizerSettings;

    // Functions
    fn debugPrint_128(string: *const c_char, fstr: *const c_char, ...);
}

// IMPORTANT: when adding functions here that need to get called from the game,
// add `#[no_mangle]` and add a .global *symbolname* to
// additions/rust-additions.asm

////////////////////////
// ADD FUNCTIONS HERE //
////////////////////////

/// Seed the installed patch was generated for (0 = unknown).
pub fn patched_seed() -> u64 {
    unsafe { u64::from_le_bytes(core::ptr::addr_of!(RANDOMIZER_SETTINGS.ap_seed).read_unaligned()) }
}

/// Slot name of the installed patch (UTF-16, NUL padded; all zero = unknown).
pub fn patched_slot_name() -> [u16; 17] {
    unsafe { core::ptr::addr_of!(RANDOMIZER_SETTINGS.ap_slot_name).read_unaligned() }
}

// Save manager buffer layout (see FUN_7100dfcc14): slot i's SaveFile is at
// *all_save_files + i * SLOT_STRIDE + SLOT_SAVEFILE_OFFSET.
pub const SLOT_COUNT: usize = 4;
const SLOT_STRIDE: usize = 0x53C0;
const SLOT_SAVEFILE_OFFSET: usize = 0x20;

/// Reads file `slot`'s APSD block straight from the save manager's buffer of
/// all four saves, without loading the file. The block may not have the APSD
/// magic (empty slot or a save from before per-save seeds).
pub fn slot_ap_save_data(slot: usize) -> Option<ApSaveData> {
    unsafe {
        if FILE_MGR.is_null() || slot >= SLOT_COUNT {
            return None;
        }
        let all = core::ptr::addr_of!((*FILE_MGR).all_save_files).read_unaligned() as *const u8;
        if all.is_null() {
            return None;
        }
        let save_file = all.add(slot * SLOT_STRIDE + SLOT_SAVEFILE_OFFSET);
        let ap_offset = core::mem::offset_of!(SaveFile, ap_save_data);
        Some((save_file.add(ap_offset) as *const ApSaveData).read_unaligned())
    }
}

/// Seed stored in the loaded save file (0 = none stored).
pub fn save_seed() -> u64 {
    unsafe {
        if FILE_MGR.is_null() {
            return 0;
        }
        let data = core::ptr::addr_of!((*FILE_MGR).FA.ap_save_data).read_unaligned();
        if data.magic != AP_SAVE_MAGIC {
            return 0;
        }
        u64::from_le_bytes(data.seed)
    }
}

/// True if the loaded save belongs to the installed patch's seed. Patches
/// without a seed (0) never block anything.
pub fn save_seed_matches() -> bool {
    let patched = patched_seed();
    patched == 0 || save_seed() == patched
}

/// Saves created before per-save seeds existed carry no APSD block. Adopt the
/// installed patch's seed + slot name for them the first time they are in the
/// world, so they keep working. Does nothing for saves that already have a
/// block (even another seed's) or for patches without a seed.
pub fn adopt_patch_seed_if_missing() {
    unsafe {
        if FILE_MGR.is_null() || patched_seed() == 0 {
            return;
        }
        let data = core::ptr::addr_of!((*FILE_MGR).FA.ap_save_data).read_unaligned();
        if data.magic == AP_SAVE_MAGIC {
            return;
        }
        write_save_seed();
    }
}

/// Stamp the installed patch's seed + slot name into the loaded save file.
pub fn write_save_seed() {
    unsafe {
        if FILE_MGR.is_null() {
            return;
        }
        let data = ApSaveData {
            magic:     AP_SAVE_MAGIC,
            seed:      core::ptr::addr_of!(RANDOMIZER_SETTINGS.ap_seed).read_unaligned(),
            slot_name: core::ptr::addr_of!(RANDOMIZER_SETTINGS.ap_slot_name).read_unaligned(),
            _pad:      [0; 2],
        };
        // Skip the write when the block already holds exactly this data:
        // handle_startflags runs repeatedly while a new file is being created.
        let existing = core::ptr::addr_of!((*FILE_MGR).FA.ap_save_data).read_unaligned();
        let (existing_name, new_name) = (existing.slot_name, data.slot_name);
        if existing.magic == data.magic && existing.seed == data.seed && existing_name == new_name {
            return;
        }
        core::ptr::addr_of_mut!((*FILE_MGR).FA.ap_save_data).write_unaligned(data);
    }
}
