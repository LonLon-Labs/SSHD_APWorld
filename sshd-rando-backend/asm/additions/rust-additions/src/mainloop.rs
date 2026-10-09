#![allow(non_camel_case_types)]
#![allow(non_snake_case)]
#![allow(unused)]

use crate::actor;
use crate::apseed_ui;
use crate::cheats;
use crate::color;
use crate::commands;
use crate::debug;
use crate::entrance;
use crate::event;
use crate::fix;
use crate::flag;
use crate::input;
use crate::item;
use crate::mem;
use crate::settings;
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

#[repr(C, packed(1))]
#[derive(Copy, Clone)]
pub struct ReloadColorFader {
    pub _0:             [u8; 0x14],
    pub current_state:  u32,
    pub unk:            u32,
    pub previous_state: u32,
    pub _1:             [u8; 0x65],
    pub other_state:    u8,
}
assert_eq_size!([u8; 0x86], ReloadColorFader);

// IMPORTANT: when using vanilla code, the start point must be declared in
// symbols.yaml and then added to this extern block.
extern "C" {
    static BOOT_PTR: *mut c_void;
    static mut RESPAWN_TYPE: u8;
    static dSystem: *mut c_void;
    static reload_color_fader: *mut ReloadColorFader;
    static RANDOMIZER_SETTINGS: settings::RandomizerSettings;
    static CURRENT_STAGE_NAME: [u8; 8];
    static CURRENT_LAYER: u8;

    // Functions
    fn debugPrint_128(string: *const c_char, fstr: *const c_char, ...);
    fn do_soft_reset(fader: *mut ReloadColorFader);
}

// IMPORTANT: when adding functions here that need to get called from the game,
// add `#[no_mangle]` and add a .global *symbolname* to
// additions/rust-additions.asm

// Storyflag that gates every Goddess Chest when the chests are unlocked
// independently of their cubes (matches GODDESS_CHEST_UNLOCK_STORYFLAG in
// checkpatchhandler.py).
const GODDESS_CHEST_UNLOCK_STORYFLAG: u16 = 95;
// Story flag set when obtaining the Goddess Sword (Progressive Sword 2).
const GODDESS_SWORD_STORYFLAG: u16 = 907;

/// "Unlocked after Goddess Sword" mode: the moment the Goddess Sword
/// storyflag (907) becomes set, set the Goddess Chest unlock flag (95). This
/// is edge-triggered (not mirrored every frame), so afterwards the client can
/// still write 95 to 0 to deactivate the chests and 1 to activate them again.
/// The first frame observed only records the current state, so loading a save
/// that already has 907 set doesn't overwrite what that save has stored for
/// 95.
static mut GODDESS_SWORD_SEEN: u8 = 0; // 0 = unknown, 1 = unset, 2 = set

// Last observed state of the Goddess Chest unlock flag (95), so a change made
// by anything (client /flag command, the sword hook below, ...) is noticed.
static mut GODDESS_CHEST_FLAG_SEEN: u8 = 0; // 0 = unknown, 1 = unset, 2 = set

// Goddess Chests only exist in these stages (see GODDESS_STAGE_TO_SCENE in
// stagepatchhandler.py).
fn current_stage_has_goddess_chests() -> bool {
    unsafe {
        // F000 layer 28 is the title screen, not gameplay.
        if CURRENT_LAYER == 28 {
            return false;
        }
        &CURRENT_STAGE_NAME[..5] == b"F000\0"
            || &CURRENT_STAGE_NAME[..5] == b"F020\0"
            || &CURRENT_STAGE_NAME[..5] == b"F023\0"
            || &CURRENT_STAGE_NAME[..6] == b"F004r\0"
    }
}

fn handle_goddess_chest_unlock_flag() {
    unsafe {
        // 0 = vanilla (chests gated by their cubes): flag 95 doesn't matter.
        if RANDOMIZER_SETTINGS.goddess_chest_unlock_mode == 0 {
            return;
        }

        // "Unlocked after Goddess Sword" mode: set 95 when 907 gets set.
        if RANDOMIZER_SETTINGS.goddess_chest_unlock_mode == 1 {
            let sword_set = flag::check_storyflag(GODDESS_SWORD_STORYFLAG) != 0;
            if sword_set && GODDESS_SWORD_SEEN == 1 {
                flag::set_storyflag(GODDESS_CHEST_UNLOCK_STORYFLAG);
            }
            GODDESS_SWORD_SEEN = if sword_set { 2 } else { 1 };
        }

        // A Goddess Chest only evaluates its unlock flag when it is created,
        // so when 95 changes while a stage with goddess chests is loaded,
        // update the chests that already exist in place (anim frame + state)
        // so they appear / disappear right away, without reloading the stage.
        // Changes seen while not in such a stage (title screen, save loading,
        // other stages) need nothing: the chests read 95 when they are created.
        let chests_unlocked = flag::check_storyflag(GODDESS_CHEST_UNLOCK_STORYFLAG) != 0;
        let new_state = if chests_unlocked { 2 } else { 1 };
        if GODDESS_CHEST_FLAG_SEEN != 0
            && GODDESS_CHEST_FLAG_SEEN != new_state
            && current_stage_has_goddess_chests()
        {
            actor::refresh_goddess_chests(chests_unlocked);
        }
        GODDESS_CHEST_FLAG_SEEN = new_state;
    }
}

#[no_mangle]
pub extern "C" fn main_loop_inject() -> *mut c_void {
    // Soft-reset button combo
    if (input::check_button_held_down(input::BUTTON_INPUTS::LEFT_STICK_BUTTON)
        && input::check_button_held_down(input::BUTTON_INPUTS::A_BUTTON)
        && input::check_button_held_down(input::BUTTON_INPUTS::R_BUTTON))
    {
        unsafe {
            (*reload_color_fader).other_state = 1;
            (*reload_color_fader).previous_state = (*reload_color_fader).current_state;
            (*reload_color_fader).current_state = 1;
            do_soft_reset(reload_color_fader);
        }
    }

    // Print heap info to debug console
    if (input::check_button_held_down(input::BUTTON_INPUTS::LEFT_STICK_BUTTON)
        && input::check_button_held_down(input::BUTTON_INPUTS::RIGHT_STICK_BUTTON)
        && input::check_button_held_down(input::BUTTON_INPUTS::L_BUTTON)
        && input::check_button_pressed_up(input::BUTTON_INPUTS::R_BUTTON))
    {
        mem::debug_print_all_heap_info();
    }

    // Reload current stage at its current entrance
    if (input::check_button_held_down(input::BUTTON_INPUTS::LEFT_STICK_BUTTON)
        && input::check_button_held_down(input::BUTTON_INPUTS::R_BUTTON)
        && input::check_button_pressed_down(input::BUTTON_INPUTS::Y_BUTTON))
    {
        entrance::reload_current_stage();
    }

    color::handle_colors();

    // Cache story state that hooks can't safely query themselves (see
    // flag::refresh_cached_story_state).
    flag::refresh_cached_story_state();

    // Archipelago - Refresh IPC-exposed addresses (sceneflags/dungeonflags)
    // for the external client's batch location-check polling.
    item::refresh_ipc_addresses();

    // File select slot name display: drop the caption override once the file
    // select screen has been left.
    apseed_ui::tick();

    // Archipelago - Check for items to give from the buffer
    item::archipelago_check_item_buffer();

    // Key Rings / Skeleton Key - re-assert the forced small key counts of the
    // dungeons (4 for a Key Ring, 5 for the Skeleton Key) every frame.
    item::reapply_forced_dungeon_keys();

    // Decoupled Goddess Cubes - give a cube's item (with the item-get
    // animation) once its story flag has been set by striking it.
    item::handle_goddess_cube_items();

    // Bird Statues Give Items - give a statue's item (with the item-get
    // animation) once the statue has been touched.
    item::handle_bird_statue_items();

    // Goddess Chests - in "unlocked after Goddess Sword" mode, mirror the
    // Goddess Sword storyflag (907) into the chest unlock flag (95).
    handle_goddess_chest_unlock_flag();

    // Ensure silent realm vessel state is valid even if gate/event flow paths
    // were skipped by AP progression timing.
    item::archipelago_silent_realm_tear_fix();

    // Archipelago - Apply deferred AP item string args to the layout TextMgr.
    // On the first item-216 pickup of a session, LYT_MSG_WINDOW.text_mgr may
    // be null when cmd 81 fires.  The main loop retries until it's ready.
    event::apply_pending_ap_string_args();

    // Dismounting the Loftwing near Skyloft without the Sailcloth voids out
    // immediately (armed by the SCEN type 5 hook).
    entrance::tick_skyloft_dismount_voidout();

    fix::apply_loftwing_speed_override();
    cheats::handle_moon_jump();
    cheats::handle_hovercraft();
    cheats::handle_infinite_health();
    cheats::handle_infinite_stamina();
    cheats::handle_infinite_ammo();
    cheats::handle_infinite_bugs();
    cheats::handle_infinite_materials();
    cheats::handle_infinite_shield();
    cheats::handle_infinite_skyward_strike();
    cheats::handle_infinite_rupees();
    cheats::handle_infinite_loftwing();
    cheats::handle_no_electric_stun();
    cheats::handle_no_enemy_damage();
    cheats::handle_speed_multiplier();

    // DeathLink / BreathLink receives from the client (runs after the
    // cheats above so a kill isn't undone by infinite health that frame).
    cheats::handle_link_requests();

    // Commands from client
    cheats::handle_spawn_demise_request();
    cheats::handle_spawn_actor_request();
    commands::handle_flag_request();
    commands::handle_warp_request();

    // Runtime Demise trap: spawns configured extras once when entering B400.
    traps::spawn_extra_demise();

    return unsafe { dSystem };
}

#[no_mangle]
pub extern "C" fn activate_back_in_time(param1: *mut c_void) -> *mut c_void {
    // This is patched into the do_soft_reset function
    unsafe {
        if input::check_button_held_down(input::BUTTON_INPUTS::L_BUTTON) {
            RESPAWN_TYPE = 3;
        }

        // Replaced instructions
        asm!("mov x8, {0:x}", in(reg) BOOT_PTR);

        return param1;
    }
}
