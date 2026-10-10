#![allow(non_camel_case_types)]
#![allow(non_snake_case)]
#![allow(unused)]

use crate::actor;
use crate::debug;
use crate::flag;
use crate::item;
use crate::math;
use crate::player;
use crate::savefile;

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
pub struct dTgSceneChange {
    pub base:              actor::dAcBase,
    pub mTriggerMatrix:    math::Matrix,
    pub mScenLink:         u8,
    pub mScenType:         u8,
    pub mPathIndex:        u8,
    pub mEnabledSceneflag: u8,
    pub mEnableStoryflag:  u16,
    pub mDisableStoryflag: u16,
    pub unk1:              u8,
    pub unk2:              u8,
    pub unk3:              u8,
    pub unk4:              u8,
    pub mVec:              math::Vec3f,
}
assert_eq_size!([u8; 0x1D8], dTgSceneChange);

// Fi warp stuff
#[repr(C, packed(1))]
#[derive(Copy, Clone)]
pub struct WarpToStartInfo {
    pub stage_name: [u8; 8],
    pub room:       u8,
    pub layer:      u8,
    pub entrance:   u8,
    pub night:      u8,
}
assert_eq_size!([u8; 12], WarpToStartInfo);

// One-shot overrides set by warp_to_stage() for an explicit `/warp ... night=`
// / `trial=` and consumed by handle_er_cases() (which otherwise recomputes
// NEXT_NIGHT / NEXT_TRIAL from the stage name and the night storyflags, and
// would silently discard the requested values). 0xFF = no override.
static mut WARP_NIGHT_OVERRIDE: u8 = 0xFF;
static mut WARP_TRIAL_OVERRIDE: u8 = 0xFF;

// IMPORTANT: when using vanilla code, the start point must be declared in
// symbols.yaml and then added to this extern block.
extern "C" {
    static PLAYER_PTR: *mut player::dPlayer;
    static FILE_MGR: *mut savefile::FileMgr;
    static STORYFLAG_MGR: *mut flag::FlagMgr;
    static STAGE_MGR: *mut actor::dStageMgr;
    static FANFARE_SOUND_MGR: *mut c_void;

    static mut GAME_RELOADER_PTR: *mut actor::GameReloader;

    static mut RESPAWN_TYPE: u8;
    static mut CURRENT_STAGE_NAME: [u8; 8];
    static mut CURRENT_STAGE_SUFFIX: [u8; 4];
    static mut CURRENT_FADE_FRAMES: u16;
    static mut CURRENT_ROOM: u8;
    static mut CURRENT_TRIAL: u8;
    static mut CURRENT_LAYER: u8;
    static mut CURRENT_ENTRANCE: u8;
    static mut CURRENT_NIGHT: u8;
    static mut CURRENT_UNK: u8;
    static mut NEXT_STAGE_NAME: [u8; 8];
    static mut NEXT_STAGE_SUFFIX: [u8; 4];
    static mut NEXT_TRANSITION_FADE_FRAMES: u16;
    static mut NEXT_ROOM: u8;
    static mut NEXT_LAYER: u8;
    static mut NEXT_ENTRANCE: u8;
    static mut NEXT_NIGHT: u8;
    static mut NEXT_TRIAL: u8;
    static mut NEXT_UNK: u8;
    static mut CURRENT_LAYER_COPY: u8;

    static mut ACTOR_PARAM_SCALE: u64;

    // Custom
    static WARP_TO_START_INFO: WarpToStartInfo;
    static mut TRAP_ID: u8;

    // Functions
    fn debugPrint_128(string: *const c_char, fstr: *const c_char, ...);
    fn GameReloader__triggerExit(
        game_reloader: *mut actor::GameReloader,
        current_room: u32,
        exit_index: u32,
        force_night: u32,
        force_trial: u32,
    );
    fn GameReloader__triggerEntrance(
        game_reloader: *mut actor::GameReloader,
        stage_name: *mut [u8; 7],
        room: u32,
        layer: u32,
        entrance: u32,
        forced_night: u32,
        forced_trial: u32,
        transition_type: u32,
        transition_fade_frames: u16,
        unk10: u32,
        unk11: u32,
    );
    fn GameReloader__actuallyTriggerEntrance(
        stage_mgr: *mut actor::dStageMgr,
        room: u8,
        layer: u8,
        entrance: u8,
        forced_night: u32,
        forced_trial: u32,
        transition_type: u32,
        transition_fade_frames: u16,
        param_9: u8,
    );

    fn playFanfareMaybe(soundMgr: *mut c_void, soundIndex: u16) -> u64;
}

// IMPORTANT: when adding functions here that need to get called from the game,
// add `#[no_mangle]` and add a .global *symbolname* to
// additions/rust-additions.asm
// When checking/setting stage info in this function be sure to use
// all of the NEXT_* variables as this function gets called right after
// those have been assigned.
#[no_mangle]
pub extern "C" fn handle_er_cases() {
    unsafe {
        // Enforce a max speed after reloading
        // Prevents you running off high ledges from non-vanilla exits
        if (*GAME_RELOADER_PTR).speed_after_reload > 30f32 {
            (*GAME_RELOADER_PTR).speed_after_reload = 30f32;
        }

        // If we're spawning from Sky Keep, but Sky Keep hasn't appeared yet,
        // instead spawn near the statue
        if &NEXT_STAGE_NAME[..5] == b"F000\0"
            && NEXT_ENTRANCE == 53
            && flag::check_storyflag(22) == 0
        {
            NEXT_ENTRANCE = 52
        }

        // // If we're spawning from LMF and it hasn't been raised,
        // // instead spawn in front of where the dungeon entrance would be
        if &NEXT_STAGE_NAME[..5] == b"F300\0" && NEXT_ENTRANCE == 5 && flag::check_storyflag(8) == 0
        {
            NEXT_ENTRANCE = 19;
        }

        // If we're spawning in Lanayru Desert/Mines through the minecart entrance,
        // make sure that a timeshift stone that makes the minecart move is active
        if ((&NEXT_STAGE_NAME[..5] == b"F300\0" && NEXT_ENTRANCE == 2)
            || (&NEXT_STAGE_NAME[..7] == b"F300_1\0" && NEXT_ENTRANCE == 1))
            && (flag::check_global_sceneflag(7, 113) == 0
                && flag::check_global_sceneflag(7, 114) == 0)
        {
            // Unset all other timeshift stones in the scene
            for flag in (115..=124).chain([108, 111]) {
                flag::unset_global_sceneflag(7, flag);
            }
            // Set the last timeshift stone in mines
            flag::set_global_sceneflag(7, 113);
        }

        // The Boko Base Gossip Stone shortcut (F202 -> F200 entrance 5, added
        // in stagepatches.yaml as a bare SCEN warp) bypasses the vanilla
        // escape sequence entirely. If the player leaves through it while
        // still "caught" by the bokoblins, storyflags 160-167 (the per-item
        // Boko Base restrictions, ending with 167 = Swordless) never get
        // cleared by anything else, so their gear stays permanently
        // unusable. Entrance 5 into F200 is unique to this custom stone, so
        // it's safe to force-clear the restriction flags here unconditionally.
        // NOTE: 168 (Boko Base Item Map from Plats) is a permanent unlock and
        // must NOT be cleared here.
        if &NEXT_STAGE_NAME[..5] == b"F200\0" && NEXT_ENTRANCE == 5 {
            for flag in 160..=167 {
                flag::unset_storyflag(flag);
            }
        }

        // If we're about to enter a stage that should have the silent realm effect
        // set it. Otherwise unset it
        if WARP_TRIAL_OVERRIDE != 0xFF {
            // Explicit /warp trial value: honour it as-is (one-shot).
            NEXT_TRIAL = WARP_TRIAL_OVERRIDE;
            WARP_TRIAL_OVERRIDE = 0xFF;
        } else if NEXT_STAGE_NAME[0] == b'S' || &NEXT_STAGE_NAME[..7] == b"D003_8\0" {
            NEXT_TRIAL = 1;
        } else {
            NEXT_TRIAL = 0;
        }

        // Force NEXT_NIGHT to day (storyflag keeps the night state stored)
        // If it should be night time, check if the entrance is valid at night
        // check_storyflag(899) can only be true if natural_night_connections is off
        if WARP_NIGHT_OVERRIDE != 0xFF {
            // Explicit /warp night value: honour it as-is (one-shot), even if
            // the destination wouldn't normally be valid at night.
            NEXT_NIGHT = WARP_NIGHT_OVERRIDE;
            WARP_NIGHT_OVERRIDE = 0xFF;
        } else if (flag::check_storyflag(899) != 0 || NEXT_NIGHT == 1) {
            // (debug prints removed to keep .text under 0x712e0bd000)
            if next_stage_is_valid_at_night() {
                NEXT_NIGHT = 1;
            } else {
                NEXT_NIGHT = 0;
            }
        } else {
            NEXT_NIGHT = 0;
        }

        // Stop trap music. If health is zero, this gets handled
        // already and this would cut off the game over music instead
        if (TRAP_ID == 2 || TRAP_ID == 3) && (*FILE_MGR).FA.current_health != 0 {
            playFanfareMaybe(FANFARE_SOUND_MGR, 0xFFFF);
        }

        // Replaced code sets these
        (*GAME_RELOADER_PTR).item_to_use_after_reload = 0xFF;
        (*GAME_RELOADER_PTR).beedle_shop_spawn_state = 0;
        (*GAME_RELOADER_PTR).action_index = 0xFF;
    }
}

#[no_mangle]
pub extern "C" fn next_stage_is_valid_at_night() -> bool {
    unsafe {
        if (&NEXT_STAGE_NAME[..5] == b"D000\0" || // Waterfall Cave
            &NEXT_STAGE_NAME[..5] == b"S000\0" || // The Goddess's Silent Realm
            (
                &NEXT_STAGE_NAME[..2] == b"F0"      && // Non-surface stage
                &NEXT_STAGE_NAME[..6] != b"F010r\0" && // Not Isle of Songs (works but looks weird)
                &NEXT_STAGE_NAME[..6] != b"F019r\0"    // Not Bamboo Island (Peater disappears?)
                // &NEXT_STAGE_NAME[..6] != b"F004r\0" // Not Bazaar (works but Sparrot isn't there)
            ))
        {
            return true;
        }
    }

    return false;
}

// When checking stage info in this function be sure to use
// all of the CURRENT_* variables
#[no_mangle]
pub extern "C" fn handle_er_action_states() {
    unsafe {
        // Prevent x14 getting clobbered. The vanilla game code does this at
        // 0x7100e10bd8 but that's too late. This is needed to allow this
        // function to call other functions (like flag::check_itemflag).
        asm!("mov x22, x14");

        if &CURRENT_STAGE_NAME[..5] == b"F210\0" && CURRENT_ENTRANCE == 0 {
            // Force the player to be diving when loading into the Mogma Turf skydive
            // entrance. Ensures the player always has access to the skydive chest (and
            // other pillars).
            (*GAME_RELOADER_PTR).action_index = 0x13;

            // By default, the game sets the respawn info at the top of the fall into Mogma
            // Turf. If the player dies due to the fall (either due to low health or OHKO),
            // they then respawn at the top of the fall but not in the diving state. This
            // can cause an infinite death loop if the player doesn't have the sailcloth.
            if flag::check_itemflag(flag::ITEMFLAGS::SAILCLOTH) == 0 {
                (*GAME_RELOADER_PTR).prevent_set_respawn_info = 1;
            }
        }

        // Replaced code sets this
        ACTOR_PARAM_SCALE = 0;
    }
}

pub fn reload_current_stage() {
    unsafe {
        if GAME_RELOADER_PTR.is_null() || FILE_MGR.is_null() {
            return;
        }

        item::reset_ap_item_receive_batch();

        // Only skip autosave when we are on F000 layer 28.
        let is_f000 = &CURRENT_STAGE_NAME[..5] == b"F000\0";
        let should_autosave = !(is_f000 && CURRENT_LAYER == 28);

        if should_autosave {
            // Mark this transition as an autosave-triggering reload.
            (*FILE_MGR).FA.is_auto_save = 1;
            (*GAME_RELOADER_PTR).is_reloading = 1;
        }

        // Stage names are stored as 8 bytes in globals, while the vanilla
        // trigger API takes a pointer to a 7-byte stage name buffer.
        let stage_name_ptr = (&mut CURRENT_STAGE_NAME as *mut [u8; 8]).cast::<[u8; 7]>();

        GameReloader__triggerEntrance(
            GAME_RELOADER_PTR,
            stage_name_ptr,
            CURRENT_ROOM.into(),
            CURRENT_LAYER.into(),
            CURRENT_ENTRANCE.into(),
            CURRENT_NIGHT.into(),
            CURRENT_TRIAL.into(),
            0,
            0xF,
            0,
            0xFF,
        );
    }
}

/// Refreshes `AP_IPC_ROOT.stage_info` with a by-value copy of the current
/// and next stage-loading state. Called once per frame from
/// `item::refresh_ipc_addresses()`; backs the client's `/stage_info`.
///
/// `dStageMgr` is mostly opaque here (only `set_in_actually_trigger_entrance`
/// is mapped), so the stage/room/layer/entrance/night/trial/fade values come
/// from the CURRENT_*/NEXT_* globals that STAGE_MGR's reload path writes.
/// STAGE_MGR itself contributes whether it exists and whether an entrance
/// trigger is in progress.
pub fn refresh_stage_info() {
    use core::ptr::{addr_of, read_volatile};

    unsafe {
        let stage_mgr_valid = !STAGE_MGR.is_null();
        let in_actually_trigger_entrance = if stage_mgr_valid {
            read_volatile(addr_of!((*STAGE_MGR).set_in_actually_trigger_entrance))
        } else {
            0
        };

        crate::ipc::AP_IPC_ROOT.stage_info = crate::ipc::ApStageInfo {
            stage_name: read_volatile(addr_of!(CURRENT_STAGE_NAME)),
            stage_suffix: read_volatile(addr_of!(CURRENT_STAGE_SUFFIX)),
            fade_frames: read_volatile(addr_of!(CURRENT_FADE_FRAMES)),
            room: read_volatile(addr_of!(CURRENT_ROOM)),
            layer: read_volatile(addr_of!(CURRENT_LAYER)),
            entrance: read_volatile(addr_of!(CURRENT_ENTRANCE)),
            night: read_volatile(addr_of!(CURRENT_NIGHT)),
            trial: read_volatile(addr_of!(CURRENT_TRIAL)),
            unk: read_volatile(addr_of!(CURRENT_UNK)),
            layer_copy: read_volatile(addr_of!(CURRENT_LAYER_COPY)),
            respawn_type: read_volatile(addr_of!(RESPAWN_TYPE)),
            next_stage_name: read_volatile(addr_of!(NEXT_STAGE_NAME)),
            next_stage_suffix: read_volatile(addr_of!(NEXT_STAGE_SUFFIX)),
            next_fade_frames: read_volatile(addr_of!(NEXT_TRANSITION_FADE_FRAMES)),
            next_room: read_volatile(addr_of!(NEXT_ROOM)),
            next_layer: read_volatile(addr_of!(NEXT_LAYER)),
            next_entrance: read_volatile(addr_of!(NEXT_ENTRANCE)),
            next_night: read_volatile(addr_of!(NEXT_NIGHT)),
            next_trial: read_volatile(addr_of!(NEXT_TRIAL)),
            next_unk: read_volatile(addr_of!(NEXT_UNK)),
            stage_mgr_valid: stage_mgr_valid as u8,
            in_actually_trigger_entrance,
        };
    }
}

#[no_mangle]
pub extern "C" fn warp_to_start() -> bool {
    unsafe {
        // Don't warp if in boss rush
        if flag::check_storyflag(530) != 0 || flag::check_storyflag(531) != 0 {
            return false;
        }

        let start_info = &*(&WARP_TO_START_INFO as *const WarpToStartInfo);

        // Make sure the night storyflag remains in-sync with the actual time of day
        if start_info.night == 0 {
            flag::unset_storyflag(737);
        } else {
            flag::set_storyflag(737);
        }

        GameReloader__actuallyTriggerEntrance(
            STAGE_MGR,
            start_info.room,
            start_info.layer,
            start_info.entrance,
            start_info.night.into(),
            0,
            0,
            0xF,
            0xFF,
        );

        (*STAGE_MGR).set_in_actually_trigger_entrance = 0;

        NEXT_STAGE_NAME = (*start_info).stage_name;
        NEXT_ROOM = (*start_info).room;
        NEXT_LAYER = (*start_info).layer;
        NEXT_ENTRANCE = (*start_info).entrance;
        NEXT_NIGHT = (*start_info).night;

        if (*GAME_RELOADER_PTR).reload_trigger == 0x2BF {
            (*GAME_RELOADER_PTR).reload_trigger = 5;
        }

        // Just to be extra safe (fixes some issues with Fi warp)
        handle_er_cases();
        return true;
    }
}

/// Warp directly to an arbitrary stage. Backs the client's
/// `/warp <stage> [layer] [room] [entrance] [night] [trial]` (anything other
/// than `/warp start`, which reuses warp_to_start() above — the same path
/// Fi's in-game warp uses).
///
/// Mirrors reload_current_stage()'s call into GameReloader__triggerEntrance,
/// but targets an explicit destination instead of the CURRENT_* globals.
/// `room` and `entrance` are passed straight through (0 = the old default).
/// `night` / `trial` are `None` when the client didn't specify them: night
/// then defaults to day and trial to the usual Silent-Realm detection by
/// stage name. When specified they override the values handle_er_cases()
/// would otherwise compute (see WARP_NIGHT_OVERRIDE / WARP_TRIAL_OVERRIDE).
/// (`/warp F000 28` warps you to the title screen and probably crashes the
/// game — layer 28 isn't a real gameplay layer, it's exactly what you asked
/// for.)
pub fn warp_to_stage(
    mut stage_name: [u8; 8],
    layer: u8,
    room: u8,
    entrance: u8,
    night: Option<bool>,
    trial: Option<bool>,
) -> bool {
    unsafe {
        if GAME_RELOADER_PTR.is_null() || FILE_MGR.is_null() {
            return false;
        }

        item::reset_ap_item_receive_batch();

        // Same autosave-skip rule as reload_current_stage(): don't trigger
        // an autosave landing on the title screen (F000 layer 28).
        let is_f000 = &stage_name[..5] == b"F000\0";
        let should_autosave = !(is_f000 && layer == 28);
        if should_autosave {
            (*FILE_MGR).FA.is_auto_save = 1;
            (*GAME_RELOADER_PTR).is_reloading = 1;
        }

        // Same silent-realm trial detection handle_er_cases() uses for
        // NEXT_TRIAL, so warping straight into a Silent Realm stage doesn't
        // leave the trial state stale. An explicit trial value wins.
        let auto_trial = stage_name[0] == b'S' || &stage_name[..7] == b"D003_8\0";
        let forced_trial: u32 = trial.unwrap_or(auto_trial).into();
        let forced_night: u32 = night.unwrap_or(false).into();

        // Keep the night storyflag in sync with the requested time of day
        // (same as warp_to_start), and make handle_er_cases() honour the
        // explicit values instead of recomputing them.
        if let Some(night) = night {
            if night {
                flag::set_storyflag(737);
            } else {
                flag::unset_storyflag(737);
            }
            WARP_NIGHT_OVERRIDE = night as u8;
        }
        if let Some(trial) = trial {
            WARP_TRIAL_OVERRIDE = trial as u8;
        }

        // Stage names are stored as 8 bytes, while the vanilla trigger API
        // takes a pointer to a 7-byte stage name buffer (same trick
        // reload_current_stage() uses on CURRENT_STAGE_NAME).
        let stage_name_ptr = (&mut stage_name as *mut [u8; 8]).cast::<[u8; 7]>();

        GameReloader__triggerEntrance(
            GAME_RELOADER_PTR,
            stage_name_ptr,
            room.into(),
            layer.into(),
            entrance.into(),
            forced_night,
            forced_trial,
            0,    // transition_type
            0xF,  // transition_fade_frames
            0,    // unk10
            0xFF, // unk11
        );

        // The overrides are one-shot and normally consumed by
        // handle_er_cases() during the call above; clear any leftovers so a
        // later, unrelated transition can't pick them up.
        WARP_NIGHT_OVERRIDE = 0xFF;
        WARP_TRIAL_OVERRIDE = 0xFF;

        true
    }
}

#[no_mangle]
pub extern "C" fn fix_sky_keep_exit(
    game_reloader: *mut actor::GameReloader,
    stage_name: *mut [u8; 7],
    room: u32,
    layer: u32,
    entrance: u32,
    forced_night: u32,
    forced_trial: u32,
    transition_type: u32,
    mut transition_fade_frames: u16,
    unk10: u32,
    mut unk11: u32,
) {
    unsafe {
        if &(*stage_name)[..5] == b"F000\0" {
            // Use bzs exit when leaving the dungeon (makes ER work properly)
            GameReloader__triggerExit(game_reloader, 0, 1, 2, 2);
        } else {
            // Replaced instructions
            transition_fade_frames = 0xF;
            unk11 = 0xFF;
            GameReloader__triggerEntrance(
                game_reloader,
                stage_name,
                room,
                layer,
                entrance,
                forced_night,
                forced_trial,
                transition_type,
                transition_fade_frames,
                unk10,
                unk11,
            );
        }
    }
}

#[no_mangle]
pub extern "C" fn require_sword_to_enter_trial_gate() -> bool {
    unsafe {
        let scen_link: u8;
        asm!("ldrb {0:w}, [x23, #0x4]", out(reg) scen_link);

        if scen_link == 0xFF || flag::check_itemflag(flag::ITEMFLAGS::PRACTICE_SWORD) == 0 {
            return false;
        }

        return true;
    }
}

#[no_mangle]
pub extern "C" fn require_sword_to_enter_sacred_realm(
    sceneflag_mgr: *mut c_void,
    roomid: u32,
    sceneflag: u32,
) -> bool {
    if flag::check_itemflag(flag::ITEMFLAGS::PRACTICE_SWORD) == 0
        || flag::check_local_sceneflag(sceneflag) != 0
    {
        return false;
    }
    return true;
}

#[no_mangle]
pub extern "C" fn allow_saving_respawn_info_on_new_file_start() {
    unsafe {
        // Storyflag 1201 is the "can use amiibo" flag.
        // This is used as a check for setting the respawn info and forcing an
        // autosave when starting a new game file.
        if flag::check_storyflag(1201) == 0 {
            (*GAME_RELOADER_PTR).prevent_set_respawn_info = 0;
        }

        // Replaced instructions
        CURRENT_STAGE_NAME = *b"\0\0\0\0\0\0\0\0";
        CURRENT_ROOM = 0;
    }
}

#[no_mangle]
pub extern "C" fn allow_autosave_on_new_file_start(param1: u64) -> u64 {
    unsafe {
        let mut w21: u32;
        asm!("mov {0:w}, w21", out(reg) w21);

        // If flag 1201 isn't set, this must be the 1st time loading a new game file.
        // Exclude layer 28 so the game doesn't autosave on the titlescreen.
        if flag::check_storyflag(1201) == 0 && CURRENT_LAYER != 28 {
            flag::set_storyflag(1201);
            // Commit the flag so that the game doesn't autosave when loading an autosave
            // made when starting a new game file.
            ((*(*STORYFLAG_MGR).funcs).do_commit)(STORYFLAG_MGR);
            w21 = 0;
            asm!("mov w8, #1");
        } else if &CURRENT_STAGE_NAME[..5] == b"F210\0"
            && CURRENT_ENTRANCE == 0
            && flag::check_itemflag(flag::ITEMFLAGS::SAILCLOTH) == 0
        {
            asm!("mov w8, #0");
        } else if (*GAME_RELOADER_PTR).is_reloading != 0 {
            // vanilla case
            asm!("mov w8, #1");
        } else {
            asm!("mov w8, #0");
        }

        asm!("mov w21, {0:w}", in(reg) w21);

        return param1;
    }
}

#[no_mangle]
pub extern "C" fn voidout_near_skyloft_or_light_pillars_without_sailcloth(
    player: *mut player::dPlayer,
    scen_link: u8,
    path_index: u8,
    scen_type: u8,
) {
    unsafe {
        // SCEN type 5 == "landing on skyloft"
        // SCEN type 9 == "entering light pillar"
        // Without the Sailcloth (types 5 and 9) the scene change is suppressed,
        // Fi's randomized "you need the Sailcloth" message is requested, and the
        // player is voided out once it has been shown (see
        // event::tick_fi_cant_drop). That message ALWAYS takes priority over the
        // "no Bird Statue unlocked" one, which is only considered when the
        // player does have the Sailcloth.
        // Game hooks must not call the flag getters (they have faulted here),
        // so the Sailcloth state comes from a cache the main loop refreshes.
        let drop_scen = scen_type == 5 || scen_type == 9;

        if drop_scen && !flag::has_sailcloth_cached() {
            if scen_type == 5 {
                // Near Skyloft without the Sailcloth: arm the dismount void-out
                // (see tick_skyloft_dismount_voidout). Refreshed every frame the
                // player stays in the trigger.
                core::ptr::write_volatile(
                    core::ptr::addr_of_mut!(SKYLOFT_DROP_ARMED),
                    SKYLOFT_DROP_ARMED_FRAMES,
                );
            }
            crate::event::start_fi_cant_drop_event_with(crate::event::FI_REASON_NO_SAILCLOTH);
        } else if scen_type == 9 && crate::lyt::no_droppable_bird_statues(scen_link) {
            // Only sets a plain byte (no event system calls here); the game's
            // own player update then runs Fi's event (see
            // event::start_fi_cant_drop_event_with). This hook can run every frame
            // while the player stands in the trigger, which is fine: repeat
            // requests are ignored while one is active and during the cooldown.
            crate::event::start_fi_cant_drop_event_with(crate::event::FI_REASON_NO_STATUE);
        } else {
            ((*(*player).vtable).trigger_scen_change)(player, scen_link, path_index, scen_type);
        }
    }
}

/// Frames left during which a dismount near Skyloft (SCEN type 5, no
/// Sailcloth) voids the player out. The scen hook refreshes it every frame the
/// player is in the trigger.
static mut SKYLOFT_DROP_ARMED: u8 = 0;
const SKYLOFT_DROP_ARMED_FRAMES: u8 = 30;

/// True if the player has left the Loftwing and is diving/falling/landing
/// (PLAYER_ACTIONS 0x12 DIVE_SKY ..= 0x15 LAND). Plain integer compares only.
fn player_dismounted_loftwing() -> bool {
    unsafe {
        if PLAYER_PTR.is_null() {
            return false;
        }
        let action = core::ptr::read_unaligned(
            core::ptr::addr_of!((*PLAYER_PTR).current_action) as *const u32
        );
        action >= 0x12 && action <= 0x15
    }
}

/// Per-frame (main loop). If the player dismounts the Loftwing while inside
/// the Skyloft landing trigger without the Sailcloth, void out right away
/// instead of waiting for Fi's text to finish.
pub fn tick_skyloft_dismount_voidout() {
    unsafe {
        let armed = core::ptr::read_volatile(core::ptr::addr_of!(SKYLOFT_DROP_ARMED));
        if armed == 0 {
            return;
        }
        core::ptr::write_volatile(core::ptr::addr_of_mut!(SKYLOFT_DROP_ARMED), armed - 1);
        if player_dismounted_loftwing() {
            core::ptr::write_volatile(core::ptr::addr_of_mut!(SKYLOFT_DROP_ARMED), 0);
            crate::event::fi_cant_drop_abort();
            voidout_now();
        }
    }
}

/// Triggers a voidout of the player (same call the vanilla game-over path
/// uses).
pub fn voidout_now() {
    unsafe {
        // Also called from the main loop, where the player may not exist yet.
        if PLAYER_PTR.is_null() {
            return;
        }
        ((*(*PLAYER_PTR).vtable).can_handle_gameover)(PLAYER_PTR, 1, 0, 0);
    }
}
