#![allow(non_camel_case_types)]
#![allow(non_snake_case)]
#![allow(unused)]

use crate::actor;
use crate::event;
use crate::fix;
use crate::flag;
use crate::math;
use crate::mem;
use crate::player;
use crate::savefile;
use crate::settings;

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
pub struct dAcItem {
    pub base:                    actor::dAcOBase,
    pub itemid:                  u16,
    pub _0:                      [u8; 6],
    pub item_model_ptr:          *mut itemModel,
    pub _1:                      [u8; 1840],
    pub state_mgr:               actor::StateMgr,
    pub _2:                      [u8; 832],
    pub actor_list_element:      u32,
    pub _3:                      [u8; 816],
    pub freestanding_y_offset:   f32,
    pub _4:                      [u8; 32],
    pub rot_increment:           math::Vec3s,
    pub model_rot:               math::Vec3s,
    pub final_determined_itemid: u16,
    pub _5:                      [u8; 9],
    pub prevent_timed_despawn:   u8,
    pub prevent_drop:            u8,
    pub _6:                      [u8; 3],
    pub no_longer_waiting:       u8,
    pub _7:                      [u8; 19],
}
assert_eq_size!([u8; 0x1288], dAcItem);

#[repr(C, packed(1))]
#[derive(Copy, Clone)]
pub struct itemModel {
    pub vtable: *mut itemModelVtable,
}
assert_eq_size!([u8; 0x8], itemModel);

#[repr(C, packed(1))]
#[derive(Copy, Clone)]
pub struct itemModelVtable {
    pub _0:               [u8; 0x28],
    pub set_local_matrix:
        extern "C" fn(item_model_ptr: *mut itemModel, world_matrix: *mut math::Matrix),
}
assert_eq_size!([u8; 0x30], itemModelVtable);

#[repr(C, packed(1))]
#[derive(Copy, Clone)]
pub struct dAcTbox {
    pub base:                         actor::dAcOBase,
    pub mdlAnmChr_c:                  [u8; 0xB8],
    pub _0:                           [u8; 0x12E8],
    pub state_mgr:                    [u8; 0x70],
    pub _1:                           [u8; 0xA8],
    pub dowsing_target:               [u8; 0x28],
    pub goddess_chest_dowsing_target: [u8; 0x28],
    pub register_dowsing_target:      [u8; 0x10],
    pub unregister_dowsing_target:    [u8; 0x10],
    pub _2:                           [u8; 0x40],
    pub anim_completion_amount:       f32,
    pub _3:                           [u8; 0x14],
    pub itemid_0x1ff:                 flag::ITEMFLAGS,
    pub item_model_index:             u16,
    pub chest_opened:                 u8,
    pub spawn_sceneflag:              u8,
    pub set_sceneflag:                u8,
    pub chestflag:                    u8,
    pub unk:                          u8,
    pub chest_subtype:                u8,
    pub _4:                           [u8; 2],
    pub is_chest_opened_related:      u8,
    pub _5:                           [u8; 4],
    pub do_obstructed_check:          bool,
    pub _6:                           [u8; 6],
}
assert_eq_size!([u8; 0x19A8], dAcTbox);

// IMPORTANT: when using vanilla code, the start point must be declared in
// symbols.yaml and then added to this extern block.
extern "C" {
    static PLAYER_PTR: *mut player::dPlayer;

    static s_rng: u32;

    static FILE_MGR: *mut savefile::FileMgr;
    static ROOM_MGR: *mut actor::RoomMgr;
    static HARP_RELATED: *mut event::HarpRelated;

    static DUNGEONFLAG_MGR: *mut flag::DungeonflagMgr;
    static SCENEFLAG_MGR: *mut flag::SceneflagMgr;

    static mut STATIC_DUNGEONFLAGS: [u16; 8];
    static mut CURRENT_STAGE_NAME: [u8; 8];

    static EQUIPPED_SWORD: u8;
    static mut ITEM_GET_BOTTLE_POUCH_SLOT: u32;
    static mut NUMBER_OF_ITEMS: u32;
    static mut ACTORBASE_PARAM2: u32;

    static mut SQUIRRELS_CAUGHT_THIS_PLAY_SESSION: bool;
    static TADTONE_SCENEFLAGS: [u8; 17];

    static RANDOMIZER_SETTINGS: settings::RandomizerSettings;
    static mut dAcOWarp__StateGateOpen: c_void;
    static mut dAcItem__StateGet: actor::ActorState;

    static mut ACTOR_PARAM_POS: *mut math::Vec3f;

    // Functions
    fn debugPrint_128(string: *const c_char, fstr: *const c_char, ...);
    fn sinf(x: f32) -> f32;
    fn cosf(x: f32) -> f32;
    fn getRotFromDegrees(deg: f32) -> u16;
    fn dAcItem__determineFinalItemid(itemid: u64) -> u64;
    fn dAcOmusasabi__stateWaitEnter();
    fn checkParam2OnDestroy(
        param2_s0x18: u8,
        roomid: u32,
        pos: *mut math::Vec3f,
        param_4: u32,
        param_5: *mut c_void,
    ) -> u32;
    fn dRawArcTable_c__getDataFromOarc(
        arc_table: *mut c_void,
        model_name: *const c_char,
        model_path: *const c_char,
    ) -> *mut c_void;
    fn dRawArcTable_c__getArcOrLoadFromDisk(
        arc_table: *mut mem::ArcEntryTable,
        arc_name: *const c_char,
        parent_dir_name: *const c_char,
        heap: *mut mem::Heap,
    ) -> bool;
    fn strcmp(s1: *const c_char, s2: *const c_char) -> i32;

    static ARC_MGR: *mut mem::ArcMgr;
    static WORK2_HEAP: *mut mem::Heap;
}

// ============================================================================
// Lightweight debug slots (readable by Python client via pymem)
// ============================================================================
// Tiny array of u32 values the Python client polls.  No string formatting,
// no memset/memcpy — just volatile u32 writes.  This avoids the binary-size
// increase that the former ring-buffer approach caused, which triggered
// nnrtld/Ryujinx symbol-resolution conflicts.
//
// Layout: 16 × u32 = 64 bytes
//   [0]  magic   0x44530002 ("DS\x00\x02", v2)
//   [1]  seq     write sequence (incremented each hook-46 call)
//   [2]  item_id last item_id passed to hook 46
//   [3]  step    which resolution step succeeded (1-4, 4=fallback)
//   [4]  flags   bit 0 = resolved was null, bit 1 = fallback used
//   [5]  fb_cnt  running count of fallbacks
//   [6]  oarc_diag  bitfield from load_oarc_if_needed:
//          bit 0: WORK2_HEAP non-null
//          bit 1: ARC_MGR non-null
//          bit 2: ARC_MGR entries non-null
//          bit 3: is_oarc_loaded returned true (skip)
//          bit 4: getArcOrLoadFromDisk result for ARC_MGR
//          bit 5: STAGE_ARC_MGR non-null
//          bit 6: getArcOrLoadFromDisk result for stage table
//   [7]  h46_diag  bitfield from hook #46:
//          bit 0: resolved_model_name non-null
//          bit 1: step1 result non-null
//          bit 2: WORK2_HEAP non-null in hook46
//          bit 3: getArcOrLoadFromDisk result in step2
//          bit 4: step2 retry result non-null
//          bit 5: ARC_MGR non-null in hook46
//          bit 6: step3 result non-null
//          bit 7: arc_table == &STAGE_ARC_MGR.entries_table
//   [8]  arc_table_lo   low 32 bits of arc_table ptr (from hook46)
//   [9]  stage_tbl_lo   low 32 bits of &STAGE_ARC_MGR.entries_table
//   [10] spawn_id       spawn_id used in buffer processing
//   [11..15]            reserved

#[no_mangle]
pub static mut AP_DEBUG_SLOTS: [u32; 16] = [
    0x44530002, // magic v2
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
];

/// Write a single debug slot (volatile).
#[inline(always)]
unsafe fn dbg_slot(index: usize, value: u32) {
    core::ptr::write_volatile(AP_DEBUG_SLOTS.as_mut_ptr().add(index), value);
}

// IMPORTANT: when adding functions here that need to get called from the game,
// add `#[no_mangle]` and add a .global *symbolname* to
// additions/rust-additions.asm
#[no_mangle]
pub extern "C" fn give_item(itemid: u8) {
    give_item_with_sceneflag(itemid, 0xFF);
}

#[no_mangle]
pub extern "C" fn give_item_with_sceneflag(itemid: u8, sceneflag: u8) -> *mut dAcItem {
    unsafe {
        // TEMP FIX: ROOM_MGR check disabled due to ASLR relocation issues
        // TODO: Implement proper symbol relocation or dynamic ROOM_MGR lookup
        // if ROOM_MGR.is_null() {
        //     return core::ptr::null_mut();
        // }

        NUMBER_OF_ITEMS = 0;
        ITEM_GET_BOTTLE_POUCH_SLOT = 0xFFFFFFFF;

        let new_itemid = dAcItem__determineFinalItemid(itemid as u64);
        let param1: u32 = (new_itemid as u32) | (sceneflag as u32) << 10 | 0x580000;

        let item_actor: *mut dAcItem = actor::spawn_actor(
            actor::ACTORID::ITEM,
            (*ROOM_MGR).roomid.into(),
            param1,
            core::ptr::null_mut(),
            core::ptr::null_mut(),
            core::ptr::null_mut(),
            0xFFFFFFFF,
        ) as *mut dAcItem;

        if item_actor.is_null() {
            return item_actor;
        }

        ITEM_GET_BOTTLE_POUCH_SLOT = 0xFFFFFFFF;
        NUMBER_OF_ITEMS = 0;

        return item_actor;
    }
}

#[no_mangle]
pub extern "C" fn give_item_with_archipelago_flag(itemid: u8, custom_flag: u16) -> *mut dAcItem {
    unsafe {
        NUMBER_OF_ITEMS = 0;
        ITEM_GET_BOTTLE_POUCH_SLOT = 0xFFFFFFFF;

        let new_itemid = dAcItem__determineFinalItemid(itemid as u64);

        // Decode custom_flag from eventpatchhandler.py encoding:
        // Bits 0-6: flag (0-127)
        // Bits 7-8: scene selector (0-3)
        // Bit 9: flag_space (0=sceneflag, 1=dungeonflag)
        let flag = (custom_flag & 0x7F) as u32;
        let scene_selector = ((custom_flag >> 7) & 0x3) as u32;
        let flag_space = ((custom_flag >> 9) & 0x1) as u32;

        // Re-encode into param2 format expected by unpack_custom_item_params:
        // Bits 8-14: flag (7 bits)
        // Bits 15-16: scene selector (2 bits)
        // Bit 17: flag_space_trigger (1 bit)
        // Bits 18-23: original_itemid (6 bits, encoded stamina fruit/rupee type)
        // Bits 0-7: unused for custom flags

        // Map itemid to original_itemid encoding (reverse of
        // unpack_custom_item_params)
        let original_itemid: u32 = match new_itemid {
            42 => 1, // Stamina Fruit
            2 => 2,  // Green Rupee
            3 => 3,  // Blue Rupee
            4 => 4,  // Red Rupee
            34 => 5, // Rupoor
            _ => 0,  // Other items don't use original_itemid encoding
        };

        let param2: u32 =
            (flag << 8) | (scene_selector << 15) | (flag_space << 17) | (original_itemid << 18);

        // Spawn item with param1 for display, param2 for custom flag
        let param1: u32 = (new_itemid as u32) | 0x180000; // Standard item spawn flags

        // Pass param2 directly to spawn_actor so it gets set atomically
        // via ACTORBASE_PARAM2 within spawn_actor itself.
        // Previously we set ACTORBASE_PARAM2 before calling spawn_actor,
        // but spawn_actor overwrites ACTORBASE_PARAM2 with its parameter.
        let item_actor: *mut dAcItem = actor::spawn_actor(
            actor::ACTORID::ITEM,
            (*ROOM_MGR).roomid.into(),
            param1,
            core::ptr::null_mut(),
            core::ptr::null_mut(),
            core::ptr::null_mut(),
            param2,
        ) as *mut dAcItem;

        if item_actor.is_null() {
            ITEM_GET_BOTTLE_POUCH_SLOT = 0xFFFFFFFF;
            NUMBER_OF_ITEMS = 0;
            return item_actor;
        }

        ITEM_GET_BOTTLE_POUCH_SLOT = 0xFFFFFFFF;
        NUMBER_OF_ITEMS = 0;

        return item_actor;
    }
}

#[no_mangle]
pub extern "C" fn init_appearing_chest_subtype(tbox: *mut dAcTbox) -> *mut dAcTbox {
    unsafe {
        let param1 = (*tbox).base.basebase.members.param1;
        let spawn_sceneflag = (param1 >> 0x14) & 0xFF;

        if spawn_sceneflag != 0xFF && flag::check_local_sceneflag(spawn_sceneflag) == 0 {
            (*tbox).chest_subtype = 0;
        } else {
            (*tbox).chest_subtype = ((param1 >> 4) & 0x3) as u8;
        }

        // Replaced instructions
        asm!("mov w8, #0x1995", "mov w1, #0xFFFFFFFF");
        return tbox;
    }
}

#[no_mangle]
pub extern "C" fn spawn_appeared_chest(tbox: *mut dAcTbox) -> *mut dAcTbox {
    unsafe {
        let w9_bkp: u32;
        asm!("mov {0:w}, w9", out(reg) w9_bkp);
        asm!("mov x19, {0:x}", in(reg) tbox);

        if 0.910 > (*tbox).anim_completion_amount && (*tbox).anim_completion_amount > 0.905 {
            let mut new_param1 = (*tbox).base.basebase.members.param1;

            let current_pos = (*tbox).base.members.base.pos;
            let new_pos: *mut math::Vec3f = &mut math::Vec3f {
                x: current_pos.x,
                y: current_pos.y,
                z: current_pos.z,
            } as *mut math::Vec3f;

            let current_rot = (*tbox).base.members.base.rot;
            let new_rot: *mut math::Vec3s = &mut math::Vec3s {
                x: 0xFF00 | (*tbox).set_sceneflag as u16,
                y: current_rot.y,
                z: (((*tbox).chestflag as u16) << 9) | ((*tbox).itemid_0x1ff as u16),
            } as *mut math::Vec3s;

            let new_scale: *mut math::Vec3f = &mut math::Vec3f {
                x: 1.0,
                y: 1.0,
                z: 1.0,
            } as *mut math::Vec3f;

            actor::spawn_actor(
                actor::ACTORID::TBOX,
                (*ROOM_MGR).roomid.into(),
                new_param1,
                new_pos,
                new_rot,
                new_scale,
                (*tbox).base.members.base.param2,
            );
        }

        asm!("ldr w8, [{0:x}, #0x1988]", in(reg) tbox);
        asm!("mov w9, {0:w}", in(reg) w9_bkp);
        return tbox;
    }
}

#[no_mangle]
pub extern "C" fn hide_appearing_chest(tbox: *mut dAcTbox) {
    unsafe {
        (*tbox).base.members.base.pos.y -= 10000.0;
    }
}

#[no_mangle]
pub extern "C" fn handle_crest_hit_give_item(crest_actor: *mut actor::dAcOSwSwordBeam) {
    unsafe {
        // Reset position so that we don't void out before getting the items
        let position = math::Vec3f {
            x: 0.0,
            y: 0.0,
            z: 304.0,
        };
        (*PLAYER_PTR).obj_base_members.base.pos = position;

        // Goddess Sword Reward
        if flag::check_local_sceneflag(50) == 0 {
            let goddess_sword_reward: u8 =
                ((*crest_actor).base.basebase.members.param1 >> 0x18) as u8;
            give_item(goddess_sword_reward);
            flag::set_local_sceneflag(50);
        }
        if (EQUIPPED_SWORD < 2) {
            return;
        }

        // Longsword Reward
        if flag::check_local_sceneflag(51) == 0 {
            let longsword_reward: u8 = ((*crest_actor).base.basebase.members.param1 >> 0x10) as u8;
            give_item(longsword_reward);
            flag::set_local_sceneflag(51);
        }
        if (EQUIPPED_SWORD < 3) {
            return;
        }

        // White Sword Reward
        if flag::check_local_sceneflag(52) == 0 {
            let whitesword_reward: u8 = ((*crest_actor).base.members.base.param2 >> 0x18) as u8;
            give_item(whitesword_reward);
            flag::set_local_sceneflag(52);
        }
    }
}

#[no_mangle]
pub extern "C" fn handle_custom_item_get(item_actor: *mut dAcItem) -> u16 {
    const BK_TO_FLAGINDEX: [usize; 7] = [
        12,  // AC BK - item id 25
        15,  // FS BK - item id 26
        18,  // SSH BK - item id 27
        255, // unused, shouldn't happen
        11,  // SVT BK - item id 29
        14,  // ET - item id 30
        17,  // LMF - item id 31
    ];

    const SK_TO_FLAGINDEX: [usize; 7] = [
        11, // SVT SK - item id 200
        17, // LMF SK - item id 201
        12, // AC SK - item id 202
        15, // FS SK - item id 203
        18, // SSH SK - item id 204
        20, // SK SK - item id 205
        9,  // Caves SK - item id 206
    ];

    const MAP_TO_FLAGINDEX: [usize; 7] = [
        11, // SVT MAP - item id 207
        14, // ET MAP - item id 208
        17, // LMF MAP - item id 209
        12, // AC MAP - item id 210
        15, // FS MAP - item id 211
        18, // SSH MAP - item id 212
        20, // SK MAP - item id 213
    ];

    unsafe {
        let itemid = (*item_actor).itemid;

        let mut dungeon_item_mask = 0;

        if (itemid >= 25 && itemid <= 27) || (itemid >= 29 && itemid <= 31) {
            dungeon_item_mask = 0x80; // boss keys
        }

        if dungeon_item_mask == 0 {
            if itemid >= 200 && itemid <= 206 {
                dungeon_item_mask = 0x0F; // small keys
            }
        }

        if dungeon_item_mask == 0 {
            if itemid >= 207 && itemid <= 213 {
                dungeon_item_mask = 0x02; // maps
            }
        }

        if dungeon_item_mask != 0 {
            let current_scene_index = (*DUNGEONFLAG_MGR).sceneindex as usize;
            let mut dungeon_item_scene_index = 0xFF;

            if dungeon_item_mask == 0x80 {
                dungeon_item_scene_index = BK_TO_FLAGINDEX[(itemid - 25) as usize];
            }

            if dungeon_item_mask == 0x0F {
                dungeon_item_scene_index = SK_TO_FLAGINDEX[(itemid - 200) as usize];
            }

            if dungeon_item_mask == 0x02 {
                dungeon_item_scene_index = MAP_TO_FLAGINDEX[(itemid - 207) as usize];
            }

            // Set the local flag if the item is in its vanilla scene.
            if current_scene_index == dungeon_item_scene_index {
                if dungeon_item_mask != 0x0F {
                    STATIC_DUNGEONFLAGS[0] |= dungeon_item_mask;
                } else {
                    let mut current_key_count = STATIC_DUNGEONFLAGS[1] & 0xF;
                    let mut obtained_key_count = (STATIC_DUNGEONFLAGS[1] >> 4) & 0xF;
                    current_key_count += 1;
                    obtained_key_count += 1;
                    STATIC_DUNGEONFLAGS[1] = (obtained_key_count << 4) | current_key_count;
                }
            }
            // Otherwise, set the global flag.
            if dungeon_item_mask != 0x0F {
                (*FILE_MGR).FA.dungeonflags[dungeon_item_scene_index][0] |= dungeon_item_mask;
            } else {
                let mut current_key_count =
                    (*FILE_MGR).FA.dungeonflags[dungeon_item_scene_index][1] & 0xF;
                let mut obtained_key_count =
                    ((*FILE_MGR).FA.dungeonflags[dungeon_item_scene_index][1] >> 4) & 0xF;
                current_key_count += 1;
                obtained_key_count += 1;
                (*FILE_MGR).FA.dungeonflags[dungeon_item_scene_index][1] =
                    (obtained_key_count << 4) | current_key_count;
            }
        }

        // Get necessary params for setting a custom flag if this item has one
        let unpacked_params = unpack_custom_item_params(item_actor);
        let flag = unpacked_params.flag;
        let sceneindex = unpacked_params.sceneindex;
        let flag_space_trigger = unpacked_params.flag_space_trigger;
        let original_itemid = unpacked_params.original_itemid;

        if flag != 0x7F {
            // Use different flag spaces depending on the value of the
            // flag_space_trigger
            match flag_space_trigger {
                0 => flag::set_global_sceneflag(sceneindex as u16, flag as u16),
                1 => flag::set_global_dungeonflag(sceneindex as u16, flag as u16),
                _ => {},
            }
        }

        // Track the custom flag for item 216 (Archipelago Item) pickups
        // so the event flow can look up item name + player name
        let itemid = (*item_actor).itemid;
        if itemid == 216 && flag != 0x7F {
            let scene_raw: u32 = match sceneindex {
                6 => 0,
                13 => 1,
                16 => 2,
                19 => 3,
                _ => 0,
            };
            let computed_flag_id = (flag & 0x7F) | (scene_raw << 7) | (flag_space_trigger << 9);
            // Volatile write ensures the store is committed immediately
            // before the game triggers the 003_216 event flow.
            core::ptr::write_volatile(
                core::ptr::addr_of_mut!(LAST_AP_ITEM_FLAG_ID),
                computed_flag_id as u16,
            );
        }

        return (*item_actor).final_determined_itemid;
    }
}

#[repr(C)]
pub struct UnpackedParams {
    pub flag:               u32,
    pub sceneindex:         u32,
    pub flag_space_trigger: u32,
    pub original_itemid:    u32,
}

// Unpacks our custom item params into separate variables
#[no_mangle]
pub extern "C" fn unpack_custom_item_params(item_actor: *mut dAcItem) -> UnpackedParams {
    unsafe {
        let param2: u32 = (*item_actor).base.members.base.param2;
        let flag: u32 = (param2 & (0x00007F00)) >> 8;
        let mut sceneindex: u32 = (param2 & (0x00018000)) >> 15;
        let flag_space_trigger: u32 = (param2 & (0x00020000)) >> 17;
        let mut original_itemid: u32 = (param2 & (0x00FC0000)) >> 18;

        // Transform the scene index into one of the unused ones
        match sceneindex {
            0 => sceneindex = 6,
            1 => sceneindex = 13,
            2 => sceneindex = 16,
            3 => sceneindex = 19,
            _ => {},
        }

        // Transform the original_itemid into its proper itemid
        match original_itemid {
            1 => original_itemid = 42, // Stamina Fruit
            2 => original_itemid = 2,  // Green Rupee
            3 => original_itemid = 3,  // Blue Rupee
            4 => original_itemid = 4,  // Red Rupee
            5 => original_itemid = 34, // Rupoor
            _ => {},
        }

        return UnpackedParams {
            flag,
            sceneindex,
            flag_space_trigger,
            original_itemid,
        };
    }
}

#[no_mangle]
pub extern "C" fn check_and_modify_item_actor(item_actor: *mut dAcItem) {
    unsafe {
        // Get necessary params for checking if this item has a custom flag
        let unpacked_params = unpack_custom_item_params(item_actor);
        let flag = unpacked_params.flag;
        let sceneindex = unpacked_params.sceneindex;
        let flag_space_trigger = unpacked_params.flag_space_trigger;
        let original_itemid = unpacked_params.original_itemid;

        // Don't do anything for conveyor spawned stamina fruit in LMF
        let current_item = (*item_actor).base.basebase.members.param1 & 0x1FF;
        if current_item == 42 && &CURRENT_STAGE_NAME[..4] == b"D300" {
            (*item_actor).base.basebase.members.param1 |= 0x200;
            return;
        }

        // Make sure stamina fruits in the Sealed Spiral don't change during boss rush
        // Also make sure that collecting the fruit doesn't set the custom flag either
        if (&CURRENT_STAGE_NAME[..5] == b"F401\0"
            && flag::check_storyflag(530) != 0
            && original_itemid == 42)
        {
            (*item_actor).base.basebase.members.param1 &= !0x1FF;
            (*item_actor).base.basebase.members.param1 |= 0x22A; // 0x200 + 42
            (*item_actor).base.members.base.param2 = 0xFFFFFFFF;
            return;
        }

        // Don't give a textbox for the specified items, otherwise, force a textbox
        match current_item {
            // Green | Blue | Red Rupee | Heart, Arrows | Bombs, Stamina, Tears, Light Fruit | Seeds
            // | Uncommon | Rare Treasure | Bugs | Treasures
            2 | 3 | 4 | 6..=8 | 40..=47 | 57 | 60 | 63 | 64 | 141..=152 | 161..=176 => {
                (*item_actor).base.basebase.members.param1 |= 0x200;
            },
            _ => {
                (*item_actor).base.basebase.members.param1 &= !0x200u32;
            },
        }

        // Despawn the item if it's one of the stamina fruit on LMF that
        // shouldn't exist until the dungeon has been raised. Actors are
        // identified by Z position
        let zPos: f32 = (*item_actor).base.members.base.pos.z;
        if (&CURRENT_STAGE_NAME[..5] == b"F300\0"
            && flag::check_storyflag(8) == 0 // LMF is not raised
            && (zPos == 46.531517028808594 || zPos == 105.0 || zPos == 3495.85009765625))
        {
            // Set itemid to 0 which despawns it later in the init function
            (*item_actor).base.basebase.members.param1 &= !0x1FF;
        }

        // Don't spawn randomized items in silent realms while also in boss rush
        // Items 42 -> 47 are the 4 tears, stamina fruits, and light fruits
        if &CURRENT_STAGE_NAME[..1] == b"S"
            && flag::check_storyflag(531) != 0
            && !(42..=47).contains(&current_item)
        {
            // Set itemid to 0 which despawns it later in the init function
            (*item_actor).base.basebase.members.param1 &= !0x1FF;
        }

        // Check if the flag is on
        let mut flag_is_on = 0;
        match flag_space_trigger {
            0 => flag_is_on = flag::check_global_sceneflag(sceneindex as u16, flag as u16),
            1 => flag_is_on = flag::check_global_dungeonflag(sceneindex as u16, flag as u16),
            _ => {},
        }

        // If we have a custom flag and it's been set, revert this item back to what
        // it originally was
        if flag != 0x7F && flag_is_on != 0 {
            (*item_actor).base.basebase.members.param1 &= !0x1FF;
            (*item_actor).base.basebase.members.param1 |= original_itemid;
            // Set bit 9 for no textbox
            (*item_actor).base.basebase.members.param1 |= 0x200;
        // Otherwise, if we have a custom flag, potentially fix
        // the horizontal offset if necessary
        } else if (flag != 0x7F) {
            fix_freestanding_item_horizontal_offset(item_actor);
        }

        // Fix the y offset if necessary
        fix_freestanding_item_y_offset(item_actor);

        // Replaced Code
        if (((*item_actor).base.basebase.members.param1 >> 10) & 0xFF) == 0xFF {
            asm!("mov x19, #1");
            asm!("cmp x19, #1");
        }
        asm!("mov x19, {0}", in(reg) item_actor);
    }
}

#[no_mangle]
pub extern "C" fn activation_checks_for_goddess_walls() -> bool {
    unsafe {
        // Replaced code
        if (*HARP_RELATED).some_check_for_continuous_strumming == 0
            || (*HARP_RELATED).some_other_harp_thing != 0
        {
            // Additional check for BotG
            if flag::check_itemflag(flag::ITEMFLAGS::BALLAD_OF_THE_GODDESS) == 1 {
                return true;
            }
        }

        return false;
    }
}

#[no_mangle]
pub extern "C" fn give_squirrel_item(musasabi_tag: *mut actor::dTgMusasabi) {
    unsafe {
        if SQUIRRELS_CAUGHT_THIS_PLAY_SESSION && (*musasabi_tag).unused == 0 {
            let itemid: u8 = ((*musasabi_tag).base.members.param2 & 0xFF) as u8;
            let sceneflag: u8 = ((*musasabi_tag).base.members.param2 >> 8 & 0xFF) as u8;

            if sceneflag != u8::MAX && flag::check_local_sceneflag(sceneflag as u32) == 0 {
                give_item_with_sceneflag(itemid, sceneflag);
            } else {
                give_item(flag::ITEMFLAGS::RED_RUPEE as u8);
            }

            // Keep track of if the item has alreeady been given
            (*musasabi_tag).unused = 1;
        }

        SQUIRRELS_CAUGHT_THIS_PLAY_SESSION = false;

        // Replaced instructions
        let current_action: player::PLAYER_ACTIONS = (*PLAYER_PTR).current_action;

        if current_action != player::PLAYER_ACTIONS::FREE_FALL
            && current_action != player::PLAYER_ACTIONS::USING_SAILCLOTH
        {
            (*musasabi_tag).has_spawned_squirrels = false;
        }
    }
}

#[no_mangle]
pub extern "C" fn tgreact_spawn_custom_item(
    mut param2_s0x18: u8,
    roomid: u32,
    pos: *mut math::Vec3f,
    param_4: u32,
    param_5: *mut c_void,
) -> u32 {
    unsafe {
        let tgreact: *mut actor::dAcOBase;
        asm!("mov {0:x}, x19", out(reg) tgreact);

        let tgreact_param1: u32 = (*tgreact).basebase.members.param1;
        let param2 = (*tgreact).members.base.param2;

        if (param2 >> 8) & 0x3FF != 0x3FF {
            let flag: u32 = (param2 & (0x00007F00)) >> 8;

            let mut sceneindex: u32 = (param2 & (0x00018000)) >> 15;
            match sceneindex {
                0 => sceneindex = 6,
                1 => sceneindex = 13,
                2 => sceneindex = 16,
                3 => sceneindex = 19,
                _ => {},
            }

            let flag_space_trigger: u32 = (param2 & (0x00020000)) >> 17;

            // Check if the flag is on
            let mut flag_is_on = 0;
            match flag_space_trigger {
                0 => flag_is_on = flag::check_global_sceneflag(sceneindex as u16, flag as u16),
                1 => flag_is_on = flag::check_global_dungeonflag(sceneindex as u16, flag as u16),
                _ => {},
            }

            let new_itemid = dAcItem__determineFinalItemid(((tgreact_param1 >> 8) & 0xFF) as u64);

            // If the tgreact would give hearts in vanilla and the randomized item is a
            // heart, behave like the flag has already been set. This allows 3
            // hearts to spawn instead
            if flag_is_on == 0 && (((param2 >> 24) & 0xFF) != 6 || new_itemid != 6) {
                let item_actor_param1: u32 = (new_itemid as u32) | 0xFF1FFE00;

                let mut actor_pos = (*tgreact).members.base.pos;
                let actor_pos_ptr: *mut math::Vec3f = &mut actor_pos as *mut math::Vec3f;

                let mut facing_angle = (*tgreact).members.base.rot.y;

                if facing_angle == 0 {
                    facing_angle = (*PLAYER_PTR).obj_base_members.base.rot.y - 0x8000;
                }

                let mut item_rot = math::Vec3s {
                    x: 0,
                    y: facing_angle,
                    z: 0,
                };
                let item_rot_ptr: *mut math::Vec3s = &mut item_rot as *mut math::Vec3s;

                let trapid = (param2 >> 19) & 0xF;

                let item_actor: *mut dAcItem = actor::spawn_actor(
                    actor::ACTORID::ITEM,
                    roomid,
                    item_actor_param1,
                    actor_pos_ptr,
                    item_rot_ptr,
                    core::ptr::null_mut(),
                    0xFF00000F | (param2 & 0x3FF00) | (trapid << 4),
                ) as *mut dAcItem;

                let mut forward_speed = 0.0;
                let mut velocity_y = 0.0;

                if (param2 >> 18) & 1 == 1 {
                    forward_speed = 12.0;
                    velocity_y = 19.5;
                }

                // Give items that are normally Deku Seeds a bit of an extra push xD
                if ((param2 >> 24) & 0xFF) == 0x0D {
                    forward_speed += 2.0;
                    velocity_y += 3.0;
                }

                (*item_actor).base.members.forward_speed = forward_speed;
                (*item_actor).base.members.velocity.x = 0.0;
                (*item_actor).base.members.velocity.y = velocity_y;
                (*item_actor).base.members.velocity.z = 0.0;
                (*item_actor).prevent_timed_despawn = 1;
                param2_s0x18 = 0xFF;
                (*tgreact).members.base.param2 |= 0x3FF00;
            }
        }

        if param2_s0x18 == 0xFF {
            return 1; // force hidden item jingle to play
        }

        if flag::check_local_sceneflag(tgreact_param1 & 0xFF) == 0 {
            flag::set_local_sceneflag(tgreact_param1 & 0xFF);

            return checkParam2OnDestroy(param2_s0x18, roomid, pos, param_4, param_5);
        }

        return 0;
    }
}

#[no_mangle]
pub extern "C" fn academy_bell_give_custom_item() {
    unsafe {
        let bell_actor: *mut actor::dAcObell;
        asm!("mov {0:x}, x19", out(reg) bell_actor);

        let itemid = (*bell_actor).base.basebase.members.param1 & 0xFF;
        let param1 = 0x19FC00 | itemid; // item will set sceneflag 127 on collection
        asm!("mov w1, {0:w}", in(reg) param1);

        // Replaced instructions
        asm!("mov w4, #0xFFFFFFFF", "mov w5, wzr");
    }
}

#[no_mangle]
pub extern "C" fn check_bucha_local_sceneflag(flag: u32) -> u16 {
    unsafe {
        if &CURRENT_STAGE_NAME[..5] == b"F100\0" {
            return flag::check_local_sceneflag(flag);
        }
        return 1;
    }
}

#[no_mangle]
pub extern "C" fn check_stage_on_bucha_interaction(param1: u64) -> u64 {
    unsafe {
        if &CURRENT_STAGE_NAME[..5] != b"F100\0" {
            asm!("add lr, lr, #0x234");
        }

        // Replaced intructions
        asm!(
            "mov x19, {0:x}",
            "mov w8, #0x2651",
            in(reg) param1,
        );
        return param1;
    }
}

#[no_mangle]
pub extern "C" fn fix_bottle_items_from_npcs(param1: u64, param2: u64, param3: u32) {
    unsafe {
        if flag::check_storyflag(894) == 0 {
            ITEM_GET_BOTTLE_POUCH_SLOT = 0xFFFFFFFF;
        }

        // Replaced instructions
        asm!("mov w0, #0x281", "mov w3, #2", "mov x1, {0:x}", "mov w2, {1:w}", in(reg) param2, in(reg) param3);
    }
}

#[no_mangle]
pub extern "C" fn rotate_freestanding_items(item_actor: *mut dAcItem) {
    unsafe {
        let mut degrees = 1.5f32;

        // If is trap
        if ((*item_actor).base.members.base.param2 >> 4) & 0xF != 0xF {
            degrees = -1.5;
        }

        // Spin items if not a stamina or light fruit
        if (*item_actor).itemid != 42 && (*item_actor).itemid != 47 {
            (*item_actor).rot_increment.x = getRotFromDegrees(degrees);
        }
    }
}

#[no_mangle]
pub extern "C" fn fix_freestanding_item_y_offset(item_actor: *mut dAcItem) {
    unsafe {
        let actor_param1 = (*item_actor).base.basebase.members.param1;

        if (*item_actor).itemid != 42 {
            let mut use_default_scaling = false;
            let mut y_offset = 0.0f32;
            let item_rot = (*item_actor).base.members.base.rot;

            // Item id
            match dAcItem__determineFinalItemid((actor_param1 & 0x1FF).into()) {
                // Sword + Sailcloth | Harp | Digging Mitts | Scattershot | Beedle's Insect Cage | Ancient Flower | Sot | Songs
                9..=15 | 16 | 56 | 105 | 159 | 166 | 180 | 186..=193 => y_offset = 20.0,
                // Bow | Iron Bow | Sacred Bow | Sea Chart | Wooden Shield | Hylian Shield
                19 | 90 | 91 | 98 | 116 | 125 => y_offset = 23.0,
                // Clawshots | Spiral Charge | Mogma Mitts | Life Tree Seedling
                20 | 21 | 99 | 197 => y_offset = 25.0,
                // AC BK | FS BK
                25 | 26 => y_offset = 30.0,
                // SSH BK, ET Key, SVT BK, ET BK | Amber Tablet
                27..=30 | 99 | 179 => y_offset = 24.0,
                // LMF BK
                31 => y_offset = 27.0,
                // Crystal Pack | 5 Bombs | Single Crystal | Beetle | Pouch | Pouch Expansion | Small Bomb Bag | Big Bug Net | Eldin Ore
                35 | 40 | 48 | 53 | 112 | 113 | 134 | 140 | 165 => y_offset = 18.0,
                // Bellows | Bug Net | Bomb Bag
                49 | 71 | 92 => y_offset = 26.0,
                36          // Glittering Spores
                | 52        // Slingshot
                | 54        // Bottle of Water
                | 55        // Mushroom Spores
                | 65        // Guardian Potion
                | 66        // Guardian Potion+
                | 68        // Water Dragon's Scale
                | 70        // Bug Medal
                | 74        // Sacred Water
                | 78        // Heart Potion
                | 79        // Heart Potion+
                | 81        // Heart Potion++
                | 84        // Stamina Potion
                | 85        // Stamina Potion+
                | 86        // Air Potion
                | 87        // Air Potion+
                | 88        // Fairy in a Bottle
                | 100..=104 // Medals
                | 108..=111 // Wallets
                | 114       // Life Medal
                | 126       // Revitalizing Potion
                | 127       // Revitalizing Potion+
                | 153       // Empty Bottle
                | 161..=164 // Treasures
                | 167..=170 // Treasures
                | 172..=174 // Treasures
                | 178       // Ruby Tablet
                | 194       // Revitalizing Potion++
                | 195       // Hot Pumpkin Soup
                | 196       // Cold Pumpkin Soup
                | 198       // Life Tree Fruit
                | 199 => y_offset = 16.0,
                // 10 Deku Seeds
                60 => {
                    y_offset = 15.0;
                    use_default_scaling = true;
                },
                // Beetle Upgrades
                75..=77 => y_offset = 10.0,
                // Heart Container
                93 => use_default_scaling = true,
                // Triforces
                95..=97 => {
                    y_offset = 24.0;
                    use_default_scaling = true;
                },
                // Seed Satchel | Golden Skull
                128 | 175 => y_offset = 14.0,
                // Map | Quiver | Whip | Emerald Tablet | Maps
                50 | 131 | 137 | 177 | 207..=213 => y_offset = 19.0,
                // Earrings
                138 => y_offset = 6.0,
                // Letter | Monster Horn | Archipelago Item
                158 | 171 | 216 => y_offset = 12.0,
                // Rattle
                160 => {
                    y_offset = 5.0;
                    use_default_scaling = true;
                },
                // Goddess Plume
                176 => y_offset = 17.0,
                // 10 Bombs | 5 Deku Seeds
                41 | 57 => use_default_scaling = true,
                // Heart | 10 Arrows
                6 | 8 => use_default_scaling = true,
                _ => y_offset = 0.0,
            }

            // Only apply the offset if the item isn't tilted
            if item_rot.x < 0x2000 || item_rot.x > 0xE000 {
                (*item_actor).freestanding_y_offset = y_offset;
            }

            if use_default_scaling {
                (*item_actor).base.members.base.rot.y |= 1;
            } else {
                (*item_actor).base.members.base.rot.y &= 0xFFFE;
            }
        }
    }
}

#[no_mangle]
pub extern "C" fn fix_freestanding_item_horizontal_offset(item_actor: *mut dAcItem) {
    unsafe {
        // If the item is facing sideways, apply a horizontal offset (i.e. stamina
        // fruit on walls) and rotate the item if necessary
        let item_rot = (*item_actor).base.members.base.rot;
        if item_rot.x > 0x2000 && item_rot.x < 0xE000 {
            let actor_param1 = (*item_actor).base.basebase.members.param1;
            let mut h_offset = 0.0f32;
            let mut angle_change_x = 0u16;
            let mut angle_change_y = 0u16;
            let mut angle_change_z = 0u16;

            // Item id
            match actor_param1 & 0x1FF {
                // Rupees
                2 | 3 | 4 | 32 | 33 | 34 => h_offset = 20.0,
                // Progressive Sword
                9..=14 => {
                    h_offset = 7.0;
                    angle_change_x = 0xD900;
                    angle_change_y = 0xF400;
                    angle_change_z = 0xF600;
                },
                // Goddess's Harp | All Songs
                16 | 186..=193 => {
                    h_offset = 17.0;
                    angle_change_x = 0x0800;
                    angle_change_y = 0x2500;
                    angle_change_z = 0x0800;
                },
                // Progressive Bow
                19 | 90 | 91 => h_offset = 17.0,
                // Clawshots
                20 => {
                    h_offset = 25.0;
                    angle_change_x = 0x0500;
                    angle_change_y = 0x2400;
                },
                // Spiral Charge
                21 => {
                    h_offset = 27.0;
                    angle_change_y = 0x3000;
                    angle_change_z = 0x0300;
                },
                // AC BK
                25 => {
                    h_offset = 50.0;
                    angle_change_x = 0xEF00;
                },
                // FS BK | SVT BK
                26 | 29 => h_offset = 40.0,
                // SSH BK
                27 => h_offset = 47.0,
                // Key Piece
                28 => {
                    h_offset = 10.0;
                    angle_change_x = 0x0800;
                    angle_change_y = 0x2000;
                    angle_change_z = 0x0800;
                },
                // ET BK
                30 => h_offset = 60.0,
                // LMF BK | Small Seed Satchel | Whip
                31 | 128 | 137 => h_offset = 25.0,
                // Gratitude Crystal Pack | Single Crystal
                35 | 48 => h_offset = 28.0,
                // 5 Bombs | 10 Bombs
                40 | 41 => {
                    h_offset = 20.0;
                    angle_change_y = 0x1600;
                },
                // Gust Bellows
                49 => {
                    h_offset = 35.0;
                    angle_change_x = 0x1100;
                    angle_change_z = 0x2000;
                },
                // Progressive Slingshot
                52 | 105 => {
                    h_offset = 30.0;
                    angle_change_x = 0x1000;
                    angle_change_z = 0x1000;
                },
                // Progressive Beetle
                53 | 75..=77 => {
                    h_offset = 40.0;
                    angle_change_x = 0xE000;
                    angle_change_y = 0xCB00;
                    angle_change_z = 0xB000;
                },
                // Progressive Mitts
                56 | 99 => {
                    h_offset = 45.0;
                    angle_change_y = 0xE800;
                },
                // Water Dragon Scale | Sea Chart
                68 | 98 => h_offset = 15.0,
                // Bug Medal | Life Medal
                70 | 114 => {
                    h_offset = 15.0;
                    angle_change_x = 0x0A80;
                },
                // Progressive Bug Net
                71 | 140 => {
                    h_offset = 30.0;
                    angle_change_x = 0x1000;
                    angle_change_y = 0xE800;
                    angle_change_z = 0x2000;
                },
                // Bomb Bag
                92 => h_offset = 45.0,
                // Heart Container | Progressive Pouch | Life Tree Fruit
                93 | 112 | 113 | 198 => h_offset = 35.0,
                // Heart Piece
                94 => h_offset = 40.0,
                // Triforce Pieces
                95..=97 => h_offset = 75.0,
                // Heart Medal | Rupee Medal | Treasure Medal | Potion Medal | Cursed Medal
                100..=104 => {
                    h_offset = 15.0;
                    angle_change_y = 0x4000;
                    angle_change_z = 0x0A00;
                },
                36          // Glittering Spores
                | 54        // Bottle of Water
                | 55        // Mushroom Spores
                | 65        // Guardian Potion
                | 66        // Guardian Potion+
                | 74        // Sacred Water
                | 78        // Heart Potion
                | 79        // Heart Potion+
                | 81        // Heart Potion++
                | 84        // Stamina Potion
                | 85        // Stamina Potion+
                | 86        // Air Potion
                | 87        // Air Potion+
                | 88        // Fairy in a Bottle
                | 108..=111 // Wallets
                | 126       // Revitalizing Potion
                | 127       // Revitalizing Potion+
                | 153       // Empty Bottle
                | 163       // Tumbleweed
                | 194       // Revitalizing Potion++
                | 195       // Hot Pumpkin Soup
                | 196       // Cold Pumpkin Soup
                | 199 => h_offset = 20.0, // Extra Wallet
                // Wooden Shield | Hylian Shield
                116 | 125 => {
                    h_offset = 25.0;
                    angle_change_x = 0x0800;
                    angle_change_y = 0x2400;
                    angle_change_z = 0x1000;
                },
                // Small Quiver
                131 => {
                    h_offset = 25.0;
                    angle_change_x = 0x1000;
                    angle_change_z = 0x1000;
                },
                // Small Bomb Bag
                134 => h_offset = 30.0,
                // Fireshield Earrings
                138 => h_offset = 20.0,
                // Cawlin's Letter | Archipelago Item
                158 | 216 => {
                    h_offset = 15.0;
                    angle_change_y = 0x2000;
                },
                // Beedle's Insect Cage
                159 => {
                    h_offset = 40.0;
                    angle_change_y = 0x2000;
                },
                // Rattle
                160 => {
                    h_offset = 25.0;
                    angle_change_y = 0xE000;
                },
                // Seeds | All Treasures
                57 | 60 | 63 | 64 | 165..=176 => h_offset = 25.0,
                // Tablets
                177..=179 => {
                    h_offset = 10.0;
                    angle_change_x = 0x0800;
                    angle_change_y = 0x2000;
                    angle_change_z = 0x0800;
                },
                // Stone of Trials
                180 => {
                    h_offset = 20.0;
                    angle_change_x = 0x0800;
                    angle_change_y = 0x2000;
                    angle_change_z = 0x0800;
                },
                // Small Keys
                1 | 200..=206 => {
                    h_offset = 5.0;
                    angle_change_x = 0x0C00;
                    angle_change_y = 0x1000;
                    angle_change_z = 0x0600;
                },
                // Maps
                50 | 207..=213 => {
                    h_offset = 30.0;
                    angle_change_x = 0x0800;
                    angle_change_y = 0x1000;
                    angle_change_z = 0x0800;
                },
                _ => h_offset = 0.0,
            }

            // Use trigonometry to figure out the horizontal offsets
            // Assume items are tilted on the x rotation and turned with the
            // y rotation to get whatever angle they have. If they're rotated with z
            // change it accordingly
            let mut facing_angle = item_rot.y;
            if facing_angle == 0 {
                facing_angle = 0 - item_rot.z;
                (*item_actor).base.members.base.rot.y = facing_angle;
                (*item_actor).base.members.base.rot.z = 0;
            }
            let facing_angle_radians: f32 = (facing_angle as f32 / 65535_f32) * 2.0 * 3.14159;
            let xOffset = sinf(facing_angle_radians) * h_offset;
            let zOffset = cosf(facing_angle_radians) * h_offset;
            (*item_actor).base.members.base.pos.x += xOffset;
            (*item_actor).base.members.base.pos.z += zOffset;
            (*item_actor).base.members.base.rot.x = 0;
            (*item_actor).base.members.base.rot.x += angle_change_x;
            (*item_actor).base.members.base.rot.y += angle_change_y;
            (*item_actor).base.members.base.rot.z += angle_change_z;
        }
    }
}

#[no_mangle]
pub extern "C" fn check_and_open_trial_gates(collected_item: flag::ITEMFLAGS) {
    unsafe {
        // Don't try to open any trial gates if the setting isn't on
        if RANDOMIZER_SETTINGS.skip_harp_playing == 0 {
            return;
        }

        // Return early if we aren't collecting any relevant items
        let relevant_items = [
            flag::ITEMFLAGS::GODDESS_HARP,
            flag::ITEMFLAGS::FARORE_COURAGE,
            flag::ITEMFLAGS::NAYRU_WISDOM,
            flag::ITEMFLAGS::DIN_POWER,
            flag::ITEMFLAGS::FARON_SONG_OF_THE_HERO_PART,
            flag::ITEMFLAGS::SONG_OF_THE_HERO,
        ];
        if !relevant_items.iter().any(|&item| item == collected_item) {
            return;
        }

        let mut open_trial_gate = false;
        // If we have the Goddess Harp and the appropriate song, set
        // the scene flag for the trial gate being open. If we're in
        // the scene index where the trial is, try to find the trial gate actor and
        // open it.
        if flag::check_itemflag(flag::ITEMFLAGS::GODDESS_HARP) == 1 {
            if flag::check_itemflag(flag::ITEMFLAGS::FARORE_COURAGE) == 1 {
                flag::set_global_sceneflag(1, 17);
                if (*SCENEFLAG_MGR).sceneindex == 1 {
                    open_trial_gate = true;
                }
            }
            if flag::check_itemflag(flag::ITEMFLAGS::NAYRU_WISDOM) == 1 {
                flag::set_global_sceneflag(7, 91);
                if (*SCENEFLAG_MGR).sceneindex == 7 {
                    open_trial_gate = true;
                }
            }
            if flag::check_itemflag(flag::ITEMFLAGS::DIN_POWER) == 1 {
                flag::set_global_sceneflag(4, 70);
                if (*SCENEFLAG_MGR).sceneindex == 4 {
                    open_trial_gate = true;
                }
            }
            if flag::check_itemflag(flag::ITEMFLAGS::SONG_OF_THE_HERO) == 1 {
                flag::set_global_sceneflag(0, 69);
                if (*SCENEFLAG_MGR).sceneindex == 0 {
                    open_trial_gate = true;
                }
            }
        }

        // Open the trial gate if we're potentially on the same stage as the one that
        // we're opening
        if open_trial_gate {
            // Try to find the trial gate actor
            let mut trial_gate_actor =
                actor::find_actor_by_type(actor::ACTORID::OBJ_WARP, core::ptr::null_mut())
                    as *mut actor::dAcOWarp;
            // If it exists, change it's state to open
            if !trial_gate_actor.is_null() {
                ((*(*trial_gate_actor).state_mgr.vtable).change_state)(
                    &mut (*trial_gate_actor).state_mgr as *mut actor::StateMgr,
                    &mut dAcOWarp__StateGateOpen as *mut c_void,
                );
            }
        }
    }
}

#[no_mangle]
pub extern "C" fn after_item_collection_hook(collected_item: flag::ITEMFLAGS) -> flag::ITEMFLAGS {
    unsafe {
        fix::fix_ammo_counts(collected_item);
        check_and_open_trial_gates(collected_item);

        // Replaced code
        asm!("mov w8, {0:w}", in(reg) ((collected_item as u16) - 2));

        return collected_item;
    }
}

#[no_mangle]
pub extern "C" fn resolve_progressive_item_models(
    mut model_name: *const c_char,
    item_id: u16,
    arc_or_model: u8,
) -> *const c_char {
    unsafe {
        // Deal with unique archive names
        if arc_or_model == 1 {
            model_name = match item_id {
                214 => c"Onp".as_ptr(),
                215 => c"DesertRobot".as_ptr(),
                216 => c"GetKobunALetter".as_ptr(),
                _ => model_name,
            };

            if item_id == 112 {
                if flag::check_itemflag(flag::ITEMFLAGS::ADVENTURE_POUCH) == 0 {
                    model_name = c"GetPouchA".as_ptr();
                } else {
                    model_name = c"GetPouchB".as_ptr();
                }
            }
        // Deal with unique model names
        } else if arc_or_model == 2 {
            model_name = match item_id {
                // Randomly pick which of the two tadtone models is used for fun :p
                214 if (s_rng & 1) == 0 => c"OnpA".as_ptr(),
                214 => c"OnpB".as_ptr(),
                215 => c"DesertRobot".as_ptr(),
                216 => c"GetKobunALetter".as_ptr(),
                _ => model_name,
            };

            if item_id == 112 {
                if flag::check_itemflag(flag::ITEMFLAGS::ADVENTURE_POUCH) == 0 {
                    model_name = c"GetPorchA".as_ptr();
                } else {
                    model_name = c"GetPorchB".as_ptr();
                }
            }
        }

        match item_id {
            // Progressive Sword — always use Practice Sword model.
            // Also handle individual sword tier IDs (9, 11-14) that
            // determineFinalItemid may resolve to — these have oarc=null
            // in items.yaml so their game-table arc names may not exist
            // in Object/NX.  Using GetSwordA (which IS in Object/NX)
            // ensures a valid model is always available.
            10 | 9 | 11 | 12 | 13 | 14 => {
                return c"GetSwordA".as_ptr();
            },
            // Progressive Bow + individual tiers
            19 | 90 | 91 => {
                if flag::check_itemflag(flag::ITEMFLAGS::BOW) == 0 {
                    return c"GetBowA".as_ptr();
                }
                if flag::check_itemflag(flag::ITEMFLAGS::IRON_BOW) == 0 {
                    return c"GetBowB".as_ptr();
                }
                return c"GetBowC".as_ptr();
            },
            // Progressive Slingshot + Scattershot
            52 | 105 => {
                if flag::check_itemflag(flag::ITEMFLAGS::SLINGSHOT) == 0 {
                    return c"GetPachinkoA".as_ptr();
                }
                return c"GetPachinkoB".as_ptr();
            },
            // Progressive Beetle + individual tiers
            53 | 75 | 76 | 77 => {
                if flag::check_itemflag(flag::ITEMFLAGS::BEETLE) == 0 {
                    return c"GetBeetleA".as_ptr();
                }
                if flag::check_itemflag(flag::ITEMFLAGS::HOOK_BEETLE) == 0 {
                    return c"GetBeetleB".as_ptr();
                }
                if flag::check_itemflag(flag::ITEMFLAGS::QUICK_BEETLE) == 0 {
                    return c"GetBeetleC".as_ptr();
                }
                return c"GetBeetleD".as_ptr();
            },
            // Progressive Mitts + Mogma Mitts
            56 | 99 => {
                if flag::check_itemflag(flag::ITEMFLAGS::DIGGING_MITTS) == 0 {
                    return c"GetMoleGloveA".as_ptr();
                }
                return c"GetMoleGloveB".as_ptr();
            },
            // Progressive Bug Net + Big Bug Net
            71 | 140 => {
                if flag::check_itemflag(flag::ITEMFLAGS::BUG_NET) == 0 {
                    return c"GetNetA".as_ptr();
                }
                return c"GetNetB".as_ptr();
            },
            // Progressive Wallet + individual tiers
            108 | 109 | 110 | 111 => {
                if flag::check_itemflag(flag::ITEMFLAGS::MEDIUM_WALLET) == 0 {
                    return c"GetPurseB".as_ptr();
                }
                if flag::check_itemflag(flag::ITEMFLAGS::BIG_WALLET) == 0 {
                    return c"GetPurseC".as_ptr();
                }
                if flag::check_itemflag(flag::ITEMFLAGS::GIANT_WALLET) == 0 {
                    return c"GetPurseD".as_ptr();
                }
                return c"GetPurseE".as_ptr();
            },
            _ => {
                return model_name;
            },
        }
    }
}

// ============================================================================
// Runtime OARC loading for Archipelago items
// ============================================================================
//
// When AP delivers an item via the memory buffer, the player can be in ANY
// stage.  The item's OARC (Object ARChive containing its 3D model) may not
// be loaded because it's stage-specific.
//
// Esme's solution: call dRawArcTable_c__getArcOrLoadFromDisk() at runtime to
// load the OARC from romfs/Object/NX before spawning the item actor.  The
// rando build already places all item OARCs into Object/NX, so they're
// available on disk.  The game has the prefer_modreplace_for_general_arcs
// hook that also checks ModReplace automatically.
//
// Items with oarc=null in items.yaml are already in ObjectPack (globally
// loaded) and don't need this — they just work.

/// Check if an OARC is already loaded in the ARC_MGR table.
unsafe fn is_oarc_loaded(oarc_name: *const c_char) -> bool {
    if ARC_MGR.is_null() {
        return false;
    }
    let entries_ptr = (*ARC_MGR).entries_table.entries;
    if entries_ptr.is_null() {
        return false;
    }
    let entries = &*entries_ptr;
    for entry in entries.iter() {
        if entry.arc_name[0] == 0 {
            break; // End of populated entries
        }
        if strcmp(oarc_name, entry.arc_name.as_ptr()) == 0 && entry.ref_count >= 1 {
            return true;
        }
    }
    false
}

/// Load a single OARC from Object/NX into both the global ARC_MGR table
/// and the current stage's arc table.  dAcItem::init only queries the
/// STAGE table, so having the OARC in ARC_MGR alone is not sufficient.
///
/// Writes diagnostic bits to AP_DEBUG_SLOTS[6] (oarc_diag).
unsafe fn load_oarc_if_needed(oarc_name: *const c_char) {
    let mut diag: u32 = 0;

    // bit 0: WORK2_HEAP non-null  (set by caller ensure_ap, but verify here)
    if !WORK2_HEAP.is_null() {
        diag |= 1 << 0;
    }

    // Load into ARC_MGR (global table) for general availability.
    let already_loaded = is_oarc_loaded(oarc_name);
    if already_loaded {
        diag |= 1 << 3;
    } // bit 3: already loaded

    if !already_loaded {
        if !ARC_MGR.is_null() {
            diag |= 1 << 1; // bit 1: ARC_MGR non-null
            let entries_ptr = (*ARC_MGR).entries_table.entries;
            if !entries_ptr.is_null() {
                diag |= 1 << 2; // bit 2: entries non-null
                let arc_table = &mut (*ARC_MGR).entries_table as *mut mem::ArcEntryTable;
                let ok = dRawArcTable_c__getArcOrLoadFromDisk(
                    arc_table,
                    oarc_name,
                    c"Object/NX".as_ptr(),
                    WORK2_HEAP,
                );
                if ok {
                    diag |= 1 << 4;
                } // bit 4: ARC_MGR load result
            }
        }
    }

    // Also load into the STAGE table.
    if !mem::STAGE_ARC_MGR.is_null() {
        diag |= 1 << 5; // bit 5: STAGE_ARC_MGR non-null
        let stage_table = &mut (*mem::STAGE_ARC_MGR).entries_table as *mut mem::ArcEntryTable;
        let ok2 = dRawArcTable_c__getArcOrLoadFromDisk(
            stage_table,
            oarc_name,
            c"Object/NX".as_ptr(),
            WORK2_HEAP,
        );
        if ok2 {
            diag |= 1 << 6;
        } // bit 6: stage load result
    }

    dbg_slot(6, diag);

    // Write STAGE_ARC_MGR entries table address for comparison with hook #46
    if !mem::STAGE_ARC_MGR.is_null() {
        let stage_tbl_ptr =
            &mut (*mem::STAGE_ARC_MGR).entries_table as *mut mem::ArcEntryTable as usize;
        dbg_slot(9, stage_tbl_ptr as u32); // low 32 bits
    }
}

/// Pre-load OARCs needed for an AP item into both ARC_MGR's global table
/// AND the current stage's arc table.  Called BEFORE spawn_actor() so the
/// OARC model data is available when dAcItem::init runs.
///
/// dAcItem::init queries the STAGE table (not ARC_MGR) to find model data.
/// If the OARC isn't in the stage table, init fails silently and the item
/// actor never displays.  Loading into both tables ensures availability
/// regardless of which table a given code path queries.
///
/// This table is derived from sshd-rando-backend/data/items.yaml.
/// For progressive items, we load ALL tier OARCs so the correct model is
/// available regardless of which tier the player is at.
/// Items not listed here are ObjectPack-native (already loaded globally).
unsafe fn ensure_ap_item_oarcs_loaded(item_id: u16) {
    if WORK2_HEAP.is_null() {
        return; // Safety: can't load without heap
    }
    match item_id {
        // Progressive Sword (Practice Sword model) + individual tiers
        10 | 9 | 11 | 12 | 13 | 14 => {
            load_oarc_if_needed(c"GetSwordA".as_ptr());
        },
        // Goddess's Harp + song items
        16 | 186 | 187 | 188 | 189 | 190 | 191 | 192 | 193 => {
            load_oarc_if_needed(c"GetHarp".as_ptr());
        },
        // Progressive Bow — load all tiers + individual tier ids
        19 | 90 | 91 => {
            load_oarc_if_needed(c"GetBowA".as_ptr());
            load_oarc_if_needed(c"GetBowB".as_ptr());
            load_oarc_if_needed(c"GetBowC".as_ptr());
        },
        // Clawshots
        20 => {
            load_oarc_if_needed(c"GetHookShot".as_ptr());
        },
        // Spiral Charge
        21 => {
            load_oarc_if_needed(c"GetBirdStatue".as_ptr());
        },
        // Boss keys
        25 => {
            load_oarc_if_needed(c"GetKeyBoss2A".as_ptr());
        },
        26 => {
            load_oarc_if_needed(c"GetKeyBoss2B".as_ptr());
        },
        27 => {
            load_oarc_if_needed(c"GetKeyBoss2C".as_ptr());
        },
        28 => {
            load_oarc_if_needed(c"GetKeyKakera".as_ptr());
        },
        29 => {
            load_oarc_if_needed(c"GetKeyBossA".as_ptr());
        },
        30 => {
            load_oarc_if_needed(c"GetKeyBossB".as_ptr());
        },
        31 => {
            load_oarc_if_needed(c"GetKeyBossC".as_ptr());
        },
        // Gust Bellows
        49 => {
            load_oarc_if_needed(c"GetVacuum".as_ptr());
        },
        // Progressive Slingshot + Scattershot
        52 | 105 => {
            load_oarc_if_needed(c"GetPachinkoA".as_ptr());
            load_oarc_if_needed(c"GetPachinkoB".as_ptr());
        },
        // Progressive Beetle + individual tiers
        53 | 75 | 76 | 77 => {
            load_oarc_if_needed(c"GetBeetleA".as_ptr());
            load_oarc_if_needed(c"GetBeetleB".as_ptr());
            load_oarc_if_needed(c"GetBeetleC".as_ptr());
            load_oarc_if_needed(c"GetBeetleD".as_ptr());
        },
        // Progressive Mitts + Mogma Mitts
        56 | 99 => {
            load_oarc_if_needed(c"GetMoleGloveA".as_ptr());
            load_oarc_if_needed(c"GetMoleGloveB".as_ptr());
        },
        // 10 Deku Seeds
        60 => {
            load_oarc_if_needed(c"GetSeedSet".as_ptr());
        },
        // Bottles/potions
        65 | 66 => {
            load_oarc_if_needed(c"GetBottleMuteki".as_ptr());
        },
        // Water Dragon's Scale
        68 => {
            load_oarc_if_needed(c"GetUroko".as_ptr());
        },
        // Medals (Bug, Heart, Rupee, Treasure, Potion, Cursed, Life)
        70 | 100 | 101 | 102 | 103 | 104 | 114 => {
            load_oarc_if_needed(c"GetMedal".as_ptr());
        },
        // Progressive Bug Net + Big Bug Net
        71 | 140 => {
            load_oarc_if_needed(c"GetNetA".as_ptr());
            load_oarc_if_needed(c"GetNetB".as_ptr());
        },
        // Sacred Water
        74 => {
            load_oarc_if_needed(c"GetBottleHoly".as_ptr());
        },
        // Heart Potion / Heart Potion Plus
        78 | 79 => {
            load_oarc_if_needed(c"GetBottleKusuri".as_ptr());
        },
        // Heart Potion Plus Plus
        81 => {
            load_oarc_if_needed(c"GetBottleKusuriS".as_ptr());
        },
        // Stamina Potion / Plus
        84 | 85 => {
            load_oarc_if_needed(c"GetBottleGuts".as_ptr());
        },
        // Air Potion / Plus
        86 | 87 => {
            load_oarc_if_needed(c"GetBottleAir".as_ptr());
        },
        // Bomb Bag
        92 => {
            load_oarc_if_needed(c"GetBombBag".as_ptr());
        },
        // Heart Container
        93 => {
            load_oarc_if_needed(c"GetHeartUtuwa".as_ptr());
            load_oarc_if_needed(c"PutHeartUtuwa".as_ptr());
        },
        // Triforce pieces
        95 | 96 | 97 => {
            load_oarc_if_needed(c"PutTriForceSingle".as_ptr());
            load_oarc_if_needed(c"GetTriForceSingle".as_ptr());
        },
        // Sea Chart
        98 => {
            load_oarc_if_needed(c"GetMapSea".as_ptr());
        },
        // Progressive Wallet + individual tiers
        108 | 109 | 110 | 111 => {
            load_oarc_if_needed(c"GetPurseB".as_ptr());
            load_oarc_if_needed(c"GetPurseC".as_ptr());
            load_oarc_if_needed(c"GetPurseD".as_ptr());
            load_oarc_if_needed(c"GetPurseE".as_ptr());
        },
        // Progressive Pouch / Pouch Expansion
        112 | 113 => {
            load_oarc_if_needed(c"GetPouchA".as_ptr());
            load_oarc_if_needed(c"GetPouchB".as_ptr());
        },
        // Wooden Shield
        116 => {
            load_oarc_if_needed(c"GetShieldWood".as_ptr());
        },
        // Hylian Shield
        125 => {
            load_oarc_if_needed(c"GetShieldHylia".as_ptr());
        },
        // Revitalizing Potion / Plus
        126 | 127 => {
            load_oarc_if_needed(c"GetBottleRepair".as_ptr());
        },
        // Small Seed Satchel
        128 => {
            load_oarc_if_needed(c"GetSpareSeedA".as_ptr());
        },
        // Small Quiver
        131 => {
            load_oarc_if_needed(c"GetSpareQuiverA".as_ptr());
        },
        // Small Bomb Bag
        134 => {
            load_oarc_if_needed(c"GetSpareBombBagA".as_ptr());
        },
        // Whip
        137 => {
            load_oarc_if_needed(c"GetWhip".as_ptr());
        },
        // Fireshield Earrings
        138 => {
            load_oarc_if_needed(c"GetEarring".as_ptr());
        },
        // Cawlin's Letter + Archipelago Item
        158 | 216 => {
            load_oarc_if_needed(c"GetKobunALetter".as_ptr());
        },
        // Beedle's Insect Cage
        159 => {
            load_oarc_if_needed(c"GetTerryCage".as_ptr());
        },
        // Rattle
        160 => {
            load_oarc_if_needed(c"GetGaragara".as_ptr());
            load_oarc_if_needed(c"PutGaragara".as_ptr());
        },
        // Tumbleweed
        163 => {
            load_oarc_if_needed(c"GetSozaiC".as_ptr());
        },
        // Ancient Flower
        166 => {
            load_oarc_if_needed(c"GetSozaiF".as_ptr());
        },
        // Dusk Relic
        168 => {
            load_oarc_if_needed(c"GetSozaiH".as_ptr());
        },
        // Monster Horn
        171 => {
            load_oarc_if_needed(c"GetSozaiL".as_ptr());
        },
        // Blue Bird Feather
        174 => {
            load_oarc_if_needed(c"GetSozaiN".as_ptr());
        },
        // Golden Skull
        175 => {
            load_oarc_if_needed(c"GetSozaiO".as_ptr());
        },
        // Goddess Plume
        176 => {
            load_oarc_if_needed(c"GetSozaiP".as_ptr());
        },
        // Tablets
        177 => {
            load_oarc_if_needed(c"GetSekibanMapA".as_ptr());
        },
        178 => {
            load_oarc_if_needed(c"GetSekibanMapB".as_ptr());
        },
        179 => {
            load_oarc_if_needed(c"GetSekibanMapC".as_ptr());
        },
        // Stone of Trials
        180 => {
            load_oarc_if_needed(c"GetSirenKey".as_ptr());
        },
        // Revitalizing Potion Plus Plus
        194 => {
            load_oarc_if_needed(c"GetBottleRepairS".as_ptr());
        },
        // Pumpkin Soup
        195 | 196 => {
            load_oarc_if_needed(c"GetBottlePumpkin".as_ptr());
        },
        // Life Tree Seedling
        197 => {
            load_oarc_if_needed(c"GetSeedLife".as_ptr());
        },
        // Life Tree Fruit
        198 => {
            load_oarc_if_needed(c"GetFruitB".as_ptr());
        },
        // Extra Wallet
        199 => {
            load_oarc_if_needed(c"GetSparePurse".as_ptr());
        },
        // Tadtones
        214 => {
            load_oarc_if_needed(c"Onp".as_ptr());
        },
        // Scrapper
        215 => {
            load_oarc_if_needed(c"DesertRobot".as_ptr());
        },
        // Groose Trap
        251 => {
            load_oarc_if_needed(c"RivalCmnAnm".as_ptr());
            load_oarc_if_needed(c"RivalNpcAnm".as_ptr());
        },
        // ObjectPack-native items (rupees, hearts, arrows, keys, maps, shields, etc.)
        _ => {},
    }
}

// Helper function to get fallback models for items without defined models.
// Returns an ObjectPack archive name that is guaranteed to be loaded in every
// stage.  Used as the last-resort fallback when the item's real OARC is not
// available.  We intentionally use only GetRupee here because it is the one
// archive that is unconditionally present in ObjectPack across all stages.
// Attempting to use other archive names (even ones that "should" be in
// ObjectPack) risks a null model pointer if the game's internal naming
// doesn't match our assumption.
fn get_fallback_model_for_item(_item_id: u16) -> *const c_char {
    c"GetRupee".as_ptr()
}

// Legacy flag — no longer drives model resolution logic but kept so
// other code can check whether the current item originated from AP.
static mut AP_FORCE_FALLBACK_MODEL: bool = false;

// Set by hook #46 when it falls back to GetRupee brres data.
// Checked by hook #47 to also return "GetRupee" model name.
// Without this, a mismatch (GetRupee brres + item's real model name)
// causes invisible items because the model name isn't in GetRupee.
static mut AP_HOOK46_USED_FALLBACK: bool = false;

#[no_mangle]
pub extern "C" fn get_arc_model_from_item(
    arc_table: *mut c_void,
    arc_name: *const c_char,
    item_id: u16,
) -> *mut c_void {
    unsafe {
        // Reset the hook-mismatch flag for this item's init cycle.
        AP_HOOK46_USED_FALLBACK = false;

        // Debug slots: record call
        let seq = core::ptr::read_volatile(AP_DEBUG_SLOTS.as_ptr().add(1));
        dbg_slot(1, seq.wrapping_add(1));
        dbg_slot(2, item_id as u32);
        dbg_slot(3, 0); // step not yet determined
        dbg_slot(4, 0); // flags reset

        // Diagnostic: record arc_table pointer and compare with STAGE_ARC_MGR
        let mut h46_diag: u32 = 0;
        dbg_slot(8, arc_table as usize as u32); // low 32 bits of arc_table

        if !mem::STAGE_ARC_MGR.is_null() {
            let stage_tbl_ptr =
                &mut (*mem::STAGE_ARC_MGR).entries_table as *mut mem::ArcEntryTable as *mut c_void;
            dbg_slot(9, stage_tbl_ptr as usize as u32);
            if arc_table == stage_tbl_ptr {
                h46_diag |= 1 << 7; // bit 7: tables match
            }
        }

        // Resolve the arc name through progressive item logic.
        let resolved_model_name = resolve_progressive_item_models(arc_name, item_id, 1);

        if !resolved_model_name.is_null() {
            h46_diag |= 1 << 0; // bit 0: resolved non-null
        }

        // If resolution returned null, use GetRupee fallback.
        if resolved_model_name.is_null() {
            dbg_slot(3, 4); // step 4 = fallback
            dbg_slot(4, 0x3); // flags: resolved_null | fallback
            dbg_slot(7, h46_diag);
            let fb = core::ptr::read_volatile(AP_DEBUG_SLOTS.as_ptr().add(5));
            dbg_slot(5, fb.wrapping_add(1));
            let fallback_model = get_fallback_model_for_item(item_id);
            return dRawArcTable_c__getDataFromOarc(
                arc_table,
                fallback_model,
                c"g3d/model.brres".as_ptr(),
            );
        }

        // 1. Try the stage's arc table
        let result = dRawArcTable_c__getDataFromOarc(
            arc_table,
            resolved_model_name,
            c"g3d/model.brres".as_ptr(),
        );
        if !result.is_null() {
            h46_diag |= 1 << 1; // bit 1: step1 non-null
            dbg_slot(3, 1); // step 1 = stage table hit
            dbg_slot(7, h46_diag);
            return result;
        }

        // 2. Stage table didn't have it — try loading from Object/NX
        if !WORK2_HEAP.is_null() {
            h46_diag |= 1 << 2; // bit 2: WORK2_HEAP non-null
            let stage_table = arc_table as *mut mem::ArcEntryTable;
            let load_ok = dRawArcTable_c__getArcOrLoadFromDisk(
                stage_table,
                resolved_model_name,
                c"Object/NX".as_ptr(),
                WORK2_HEAP,
            );
            if load_ok {
                h46_diag |= 1 << 3;
            } // bit 3: disk load result

            let result2 = dRawArcTable_c__getDataFromOarc(
                arc_table,
                resolved_model_name,
                c"g3d/model.brres".as_ptr(),
            );
            if !result2.is_null() {
                h46_diag |= 1 << 4; // bit 4: step2 retry non-null
                dbg_slot(3, 2); // step 2 = loaded from disk
                dbg_slot(7, h46_diag);
                return result2;
            }
        }

        // 3. ARC_MGR fallback
        if !ARC_MGR.is_null() {
            h46_diag |= 1 << 5; // bit 5: ARC_MGR non-null
            let arc_mgr_table =
                &mut (*ARC_MGR).entries_table as *mut mem::ArcEntryTable as *mut c_void;
            let result3 = dRawArcTable_c__getDataFromOarc(
                arc_mgr_table,
                resolved_model_name,
                c"g3d/model.brres".as_ptr(),
            );
            if !result3.is_null() {
                h46_diag |= 1 << 6; // bit 6: step3 non-null
                dbg_slot(3, 3); // step 3 = ARC_MGR hit
                dbg_slot(7, h46_diag);
                return result3;
            }
        }

        // 4. GetRupee fallback
        dbg_slot(3, 4); // step 4 = fallback
        dbg_slot(4, 0x2); // flags: fallback (resolved was not null)
        dbg_slot(7, h46_diag);
        let fb = core::ptr::read_volatile(AP_DEBUG_SLOTS.as_ptr().add(5));
        dbg_slot(5, fb.wrapping_add(1));
        AP_HOOK46_USED_FALLBACK = true;
        let fallback_model = get_fallback_model_for_item(item_id);
        return dRawArcTable_c__getDataFromOarc(
            arc_table,
            fallback_model,
            c"g3d/model.brres".as_ptr(),
        );
    }
}

#[no_mangle]
pub extern "C" fn get_item_model_name_ptr(
    model_name: *const c_char,
    item_id: u16,
) -> *const c_char {
    unsafe {
        // If hook #46 fell back to GetRupee brres data, the model name MUST
        // also be "GetRupee" — otherwise the game tries to find e.g.
        // "GetSwordA" inside GetRupee's brres, which fails silently and
        // the item actor becomes invisible.
        if AP_HOOK46_USED_FALLBACK {
            AP_HOOK46_USED_FALLBACK = false;

            // Replaced code still needs to execute
            asm!("mov x1, {0:x}", in(reg) item_id);
            asm!("cmp x1, #0x1C");

            return c"GetRupee".as_ptr();
        }

        // Resolve progressive model names.  We pass model_name even if null —
        // for individual progressive tiers (e.g., id=13 Master Sword) the game's
        // item table has model=null, but resolve_progressive_item_models returns
        // the correct model name (e.g., "GetSwordA") via its match arms.
        let resolved_model_name = resolve_progressive_item_models(model_name, item_id, 2);

        // Replaced code still needs to execute
        asm!("mov x1, {0:x}", in(reg) item_id);
        asm!("cmp x1, #0x1C");

        // If still null after resolution, use fallback.
        if resolved_model_name.is_null() {
            return get_fallback_model_for_item(item_id);
        }

        return resolved_model_name;
    }
}

// Applys a fixed value for the scale of a model in dAcItem::update
#[no_mangle]
pub extern "C" fn change_model_scale(item_actor: *mut dAcItem, world_matrix: *mut math::Matrix) {
    unsafe {
        let mut scale = match (*item_actor).final_determined_itemid {
            214 => 0.5f32, // Tadtone
            215 => 0.3f32, // Scrapper
            _ => 1.0f32,
        };

        (*item_actor).base.members.base.scale.x *= scale;
        (*item_actor).base.members.base.scale.y *= scale;
        (*item_actor).base.members.base.scale.z *= scale;

        // Change Tadtone height during item get
        if (*item_actor).itemid == 214 {
            let current_player_action = (*PLAYER_PTR).current_action;

            if current_player_action == player::PLAYER_ACTIONS::ITEM_GET {
                (*world_matrix).yw += -20.0;
            }
        }

        // Replaced code
        // Safety check: skip if item_model_ptr is null (model failed to load)
        if !(*item_actor).item_model_ptr.is_null() {
            ((*(*(*item_actor).item_model_ptr).vtable).set_local_matrix)(
                (*item_actor).item_model_ptr,
                world_matrix,
            );
        }
    }
}

// This specifically happens after item scaling stuff has been determined so
// there isn't weird inconsistencies between items that have textboxes and
// those that don't
#[no_mangle]
pub extern "C" fn force_traps_to_have_textboxes(item_actor: *mut dAcItem) {
    unsafe {
        // If the item isn't a trap and it's a minor item, don't force a textbox
        if ((*item_actor).base.members.base.param2 >> 4) & 0xF != 0xF
            && (*item_actor).final_determined_itemid != 42
        {
            (*item_actor).base.basebase.members.param1 &= !0x200u32;
        }
    }
}

#[no_mangle]
pub extern "C" fn get_custom_freestanding_item_scale() -> f32 {
    // dAcItem->freestandingModelScale gets bound to different functions depending
    // on the itemid during dAcItem::init. The function for "small" items gets
    // patched to call this function.
    //
    // However, these functions literally just return a float. They don't have any
    // references to the item actor they are being used for. Through some
    // Ghidra wizardry, it is know that the item actor of interest is stored
    // either in x19 or x20. So, this function first assumes that x19 is correct.
    // It checks for the actorid field to verify that x19 holds an item actor.
    // If this check fails, the item actor must be in x20 so that gets used
    // instead.
    //
    // After all this, the item id can then be used to return unique freestanding
    // item scales for each item. That this works at all is ridiculous...
    unsafe {
        let mut actorid: u16;
        asm!("ldrh {0:w}, [x19, #0x10]", out(reg) actorid);

        let item_actor: *mut dAcItem;
        if actorid == 641 {
            asm!("mov {0:x}, x19", out(reg) item_actor);
        } else {
            asm!("mov {0:x}, x20", out(reg) item_actor);
        }

        // Just to be extra safe
        if item_actor.is_null() {
            return 1.0;
        }

        return match (*item_actor).final_determined_itemid {
            40 => 1.5, // 5 Bombs
            // Tumbleweed, Ancient Flower, Dusk Relic, Blue Bird Feather, Goddess Plume
            60 | 163 | 166 | 168 | 174 | 176 => 2.0,
            _ => 1.0,
        };
    }
}

#[no_mangle]
pub extern "C" fn get_silent_realm_item_glow_color(item_id: u32) -> u32 {
    unsafe {
        // Only proceed if in a silent realm and we're not currently in the process of
        // receiving the spirit vessel or the trial reward
        let current_action = (*PLAYER_PTR).current_action;
        if CURRENT_STAGE_NAME[0] == b'S'
            && current_action != player::PLAYER_ACTIONS::RECEIVE_GODDESS_FRUIT
            && current_action != player::PLAYER_ACTIONS::SPIRIT_VESSEL_CHEST_EXIT
        {
            // Return the proper tear subtype depending on the passed in item
            match item_id {
                // Item is a tear, return expected subtype
                43..=46 => return ((CURRENT_STAGE_NAME[1] as u32) + 3) & 3,

                // Item is stamina fruit | light fruit | dusk relic, return 4 for no
                // glow
                42 | 47 | 168 => return 4,

                // For all other cases, return the subtype for the opposite color from the expected
                // one for this realm
                _ => return ((CURRENT_STAGE_NAME[1] as u32) + 1) & 3,
            }
        }
    }
    return 4;
}

#[no_mangle]
pub extern "C" fn give_tadtone_random_item(tadtone_actor: *const actor::dAcOClef) {
    unsafe {
        let itemid = (*tadtone_actor).base.members.base.rot.z & 0xFF;
        let tadtone_group_index: u8 =
            ((((*tadtone_actor).base.basebase.members.param1 >> 3) & 0x1F) - 1) as u8;

        give_item_with_sceneflag(
            itemid as u8,
            TADTONE_SCENEFLAGS[tadtone_group_index as usize],
        );
    }
}

#[no_mangle]
pub extern "C" fn spawn_tree_of_life_item() -> *mut dAcItem {
    let tree_actor: *mut actor::dAcOBase;

    unsafe {
        // Safety check: Don't try to spawn item if ROOM_MGR is not initialized
        if ROOM_MGR.is_null() {
            return core::ptr::null_mut();
        }

        asm!("mov {0:x}, x19", out(reg) tree_actor);

        let tree_param1 = (*tree_actor).basebase.members.param1;

        // Adjust item spawn height so it's not stuck in a tree branch ^^'
        (*ACTOR_PARAM_POS).y -= 80.0;

        NUMBER_OF_ITEMS = 0;
        ITEM_GET_BOTTLE_POUCH_SLOT = 0xFFFFFFFF;

        let item_actor: *mut dAcItem = actor::spawn_actor(
            actor::ACTORID::ITEM,
            (*ROOM_MGR).roomid.into(),
            0xFF9C0200 | (52 << 10) | (tree_param1 >> 24),
            ACTOR_PARAM_POS,
            core::ptr::null_mut(),
            core::ptr::null_mut(),
            // The tree actor already has param2 setup correctly.
            (*tree_actor).members.base.param2,
        ) as *mut dAcItem;

        ITEM_GET_BOTTLE_POUCH_SLOT = 0xFFFFFFFF;
        NUMBER_OF_ITEMS = 0;

        return item_actor;
    }
}

#[no_mangle]
pub extern "C" fn setup_gossip_stone_item_params(
    roomid: u32,
    mut param1: u32,
    actor_pos: *mut math::Vec3f,
    actor_rot: *mut math::Vec3s, // unused, redefined later
    mut param2: u32,
    hrphint_actor: *mut actor::dAcOBase,
) -> *mut dAcItem {
    unsafe {
        let sceneflag: u32 = (*hrphint_actor).basebase.members.param1 & 0xFF;
        let trapid: u32 = (*hrphint_actor).members.base.param2 & 0xF;
        let itemid: u32 = ((*hrphint_actor).members.base.param2 >> 4) & 0xFF;

        param1 = 0x180000u32 | (sceneflag << 10) | itemid;
        param2 &= 0xFFFFFF0F;
        param2 |= trapid << 4;

        // Redefine actor_rot
        // Can't use the vanilla rot on the stack as, unfathomably, this causes the
        // item not to spawn at all
        let mut actor_rot = (*hrphint_actor).members.base.rot;
        let actor_rot_ptr = &mut actor_rot as *mut math::Vec3s;

        let item_actor: *mut dAcItem = actor::spawn_actor(
            actor::ACTORID::ITEM,
            roomid,
            param1,
            actor_pos,
            actor_rot_ptr,
            core::ptr::null_mut(),
            param2,
        ) as *mut dAcItem;

        (*item_actor).prevent_timed_despawn = 1;

        return item_actor;
    }
}

// Archipelago item receiving system
// Buffer structure: 16 slots, 4 bytes each
// Byte 0: Item ID (0 = empty slot)
// Byte 1: Flags (0x01 = show animation, 0x02 = play jingle)
// Bytes 2-3: Reserved
const ARCHIPELAGO_BUFFER_SIZE: usize = 16;

#[repr(C, packed(1))]
#[derive(Copy, Clone)]
pub struct ArchipelagoItemSlot {
    item_id:   u8,
    flags:     u8,
    _reserved: [u8; 2],
}
assert_eq_size!([u8; 4], ArchipelagoItemSlot);

// Static buffer for Archipelago item queue
// This will be written to by the Python client and read by the game
// Magic signature at the start: "AP" in ASCII (0x4150), followed by version
// 0x0001 This allows Python to find the real buffer by searching for this
// signature Format: [magic_high, magic_low, version_high, version_low,
// ...actual slots...]
#[no_mangle]
pub static mut ARCHIPELAGO_ITEM_BUFFER: [ArchipelagoItemSlot; ARCHIPELAGO_BUFFER_SIZE] = [
    // First slot contains magic signature: "AP\x00\x01"
    ArchipelagoItemSlot {
        item_id:   0x41,         // 'A'
        flags:     0x50,         // 'P'
        _reserved: [0x00, 0x01], // Version
    },
    // Remaining slots for actual items (15 slots)
    ArchipelagoItemSlot {
        item_id:   0,
        flags:     0,
        _reserved: [0, 0],
    },
    ArchipelagoItemSlot {
        item_id:   0,
        flags:     0,
        _reserved: [0, 0],
    },
    ArchipelagoItemSlot {
        item_id:   0,
        flags:     0,
        _reserved: [0, 0],
    },
    ArchipelagoItemSlot {
        item_id:   0,
        flags:     0,
        _reserved: [0, 0],
    },
    ArchipelagoItemSlot {
        item_id:   0,
        flags:     0,
        _reserved: [0, 0],
    },
    ArchipelagoItemSlot {
        item_id:   0,
        flags:     0,
        _reserved: [0, 0],
    },
    ArchipelagoItemSlot {
        item_id:   0,
        flags:     0,
        _reserved: [0, 0],
    },
    ArchipelagoItemSlot {
        item_id:   0,
        flags:     0,
        _reserved: [0, 0],
    },
    ArchipelagoItemSlot {
        item_id:   0,
        flags:     0,
        _reserved: [0, 0],
    },
    ArchipelagoItemSlot {
        item_id:   0,
        flags:     0,
        _reserved: [0, 0],
    },
    ArchipelagoItemSlot {
        item_id:   0,
        flags:     0,
        _reserved: [0, 0],
    },
    ArchipelagoItemSlot {
        item_id:   0,
        flags:     0,
        _reserved: [0, 0],
    },
    ArchipelagoItemSlot {
        item_id:   0,
        flags:     0,
        _reserved: [0, 0],
    },
    ArchipelagoItemSlot {
        item_id:   0,
        flags:     0,
        _reserved: [0, 0],
    },
    ArchipelagoItemSlot {
        item_id:   0,
        flags:     0,
        _reserved: [0, 0],
    },
];

// Player actions during which we must NOT deliver an Archipelago item.
// Values match BUSY_PLAYER_ACTIONS in ItemSystemIntegration.py.
const BUSY_ACTIONS: [player::PLAYER_ACTIONS; 16] = [
    player::PLAYER_ACTIONS::DIE,                         // 0x4A
    player::PLAYER_ACTIONS::REVIVE,                      // 0x4B
    player::PLAYER_ACTIONS::INTERACT,                    // 0x58
    player::PLAYER_ACTIONS::USING_DOOR,                  // 0x6E
    player::PLAYER_ACTIONS::USE_DDOOR,                   // 0x6F
    player::PLAYER_ACTIONS::ZEV_EVENT_MAYBE,             // 0x77
    player::PLAYER_ACTIONS::ITEM_GET,                    // 0x78
    player::PLAYER_ACTIONS::RELATED_TO_NEW_SWORD_IN_CS_, // 0x7B
    player::PLAYER_ACTIONS::OPEN_CHEST,                  // 0x7D
    player::PLAYER_ACTIONS::SWORD_IN_DIAL,               // 0x86
    player::PLAYER_ACTIONS::ON_BIRD,                     // 0x8A
    player::PLAYER_ACTIONS::RECEIVE_GODDESS_FRUIT,       // 0x91
    player::PLAYER_ACTIONS::SLEEPING,                    // 0x93
    player::PLAYER_ACTIONS::PLACE_TABLET,                // 0xAF
    player::PLAYER_ACTIONS::ENTER_GODDESS_WALL,          // 0xB4
    player::PLAYER_ACTIONS::EXIT_GODDESS_WALL,           // 0xB6
];

/// Returns true if the player is currently in a "busy" action and must not
/// receive an Archipelago item right now.
#[inline]
fn player_is_busy() -> bool {
    unsafe {
        if PLAYER_PTR.is_null() {
            return true; // No player yet — treat as busy
        }
        let action = core::ptr::read_volatile(core::ptr::addr_of!((*PLAYER_PTR).current_action));
        for &busy in &BUSY_ACTIONS {
            if action == busy {
                return true;
            }
        }
        false
    }
}

// ── Stage-transition cooldown ──────────────────────────────────────────
//
// When the game loads a new stage, there is a window (several hundred
// milliseconds) during which the room/actor/heap infrastructure is not
// fully initialised.  If we try to spawn an item actor during that
// window the spawn silently fails or produces a broken actor — the
// buffer slot gets consumed but the player never sees the item.
//
// We detect stage changes by comparing CURRENT_STAGE_NAME to a cached
// copy and impose a cooldown of STAGE_COOLDOWN_FRAMES (~1–2 s at
// 30/60 fps) before processing any buffer items.  This gives the
// engine enough time to finish loading rooms, OARCs and heaps.

/// Frames to wait after a stage transition before delivering items.
const STAGE_COOLDOWN_FRAMES: u32 = 90;

/// Maximum frames a single buffer slot will be retried before giving up
/// and clearing it (the Python direct-flag fallback ensures inventory
/// correctness regardless).
const MAX_RETRY_FRAMES: u32 = 300;

static mut AP_LAST_STAGE: [u8; 8] = [0u8; 8];
static mut AP_STAGE_COOLDOWN: u32 = 0;

/// Per-slot retry counters — one for each buffer slot (excluding slot 0
/// which holds the magic signature).
static mut AP_SLOT_RETRIES: [u32; ARCHIPELAGO_BUFFER_SIZE] = [0u32; ARCHIPELAGO_BUFFER_SIZE];

/// Returns true if we are still in the post-stage-transition cooldown
/// and should NOT process buffer items this frame.
#[inline]
fn ap_stage_cooldown_active() -> bool {
    unsafe {
        // Detect stage change.
        let cur = core::ptr::read_volatile(core::ptr::addr_of!(CURRENT_STAGE_NAME));
        if cur != AP_LAST_STAGE {
            AP_LAST_STAGE = cur;
            AP_STAGE_COOLDOWN = STAGE_COOLDOWN_FRAMES;
        }
        if AP_STAGE_COOLDOWN > 0 {
            AP_STAGE_COOLDOWN -= 1;
            return true;
        }
        false
    }
}

#[no_mangle]
pub extern "C" fn archipelago_check_item_buffer() {
    unsafe {
        // Wait for the stage to finish loading before we attempt any spawns.
        if ap_stage_cooldown_active() {
            return;
        }

        // Check each slot in the buffer
        // Skip slot 0 which contains the magic signature
        for i in 1..ARCHIPELAGO_BUFFER_SIZE {
            // Use volatile read because Python writes to this buffer via
            // cross-process WriteProcessMemory.  Without volatile the
            // compiler could hoist or elide loads across frames.
            let slot_ptr = ARCHIPELAGO_ITEM_BUFFER.as_mut_ptr().add(i);
            let item_id_val = core::ptr::read_volatile(core::ptr::addr_of!((*slot_ptr).item_id));

            // Skip empty slots
            if item_id_val == 0 {
                continue;
            }

            // Item pending — check if the player is in a state where we can
            // safely deliver it.  If not, leave the slot and retry next frame.
            if player_is_busy() {
                return;
            }

            // Safety: skip if PLAYER_PTR is null.
            if PLAYER_PTR.is_null() {
                return;
            }

            // Resolve progressive items (e.g., Progressive Bow → Iron Bow)
            // to their concrete tier based on the player's current inventory
            // so the correct OARC model is loaded and the right item actor
            // is spawned.
            let item_id = item_id_val as u64;
            let final_id = dAcItem__determineFinalItemid(item_id) as u16;

            NUMBER_OF_ITEMS = 0;
            ITEM_GET_BOTTLE_POUCH_SLOT = 0xFFFFFFFF;

            // Use the resolved item ID for spawning so the game's item
            // table can look up the correct OARC and model.
            let spawn_id = if final_id > 0 {
                final_id as u32
            } else {
                item_id_val as u32
            };
            let param1: u32 = spawn_id | (0xFFu32 << 10) | 0x580000;

            // Debug: record spawn_id for diagnostics
            dbg_slot(10, spawn_id);

            // Pre-load the item's OARCs into ARC_MGR's global table.
            // The on-demand loader in get_arc_model_from_item (hook #46)
            // will load into the stage's own table when the model is first
            // queried during dAcItem::init.
            //
            // Load with BOTH the original base id (for progressive item
            // match arms) AND the resolved spawn_id (for individual tier
            // match arms, e.g., item 13 Master Sword → falls to sword arm).
            ensure_ap_item_oarcs_loaded(item_id_val as u16);
            if spawn_id as u16 != item_id_val as u16 {
                ensure_ap_item_oarcs_loaded(spawn_id as u16);
            }

            AP_FORCE_FALLBACK_MODEL = true;

            let player_pos_ptr = core::ptr::addr_of_mut!((*PLAYER_PTR).obj_base_members.base.pos);

            let item_actor: *mut dAcItem = actor::spawn_actor(
                actor::ACTORID::ITEM,
                (*ROOM_MGR).roomid.into(),
                param1,
                player_pos_ptr,
                core::ptr::null_mut(),
                core::ptr::null_mut(),
                0xFFFFFFFF,
            ) as *mut dAcItem;

            AP_FORCE_FALLBACK_MODEL = false;

            ITEM_GET_BOTTLE_POUCH_SLOT = 0xFFFFFFFF;
            NUMBER_OF_ITEMS = 0;

            if !item_actor.is_null() {
                // Clear bit 9 to allow textbox display for AP items.
                (*item_actor).base.basebase.members.param1 &= !0x200u32;
                (*item_actor).prevent_timed_despawn = 1;
                (*item_actor).no_longer_waiting = 1;

                // Spawn succeeded — clear the buffer slot and reset retries.
                core::ptr::write_volatile(core::ptr::addr_of_mut!((*slot_ptr).item_id), 0u8);
                core::ptr::write_volatile(core::ptr::addr_of_mut!((*slot_ptr).flags), 0u8);
                (*slot_ptr)._reserved = [0, 0];
                AP_SLOT_RETRIES[i] = 0;
            } else {
                // Spawn returned null — increment retry counter.
                // If we've retried too many times, give up and clear the
                // slot.  The Python client's DirectFlags fallback will
                // ensure the item is not lost (it writes save-file flags
                // after its own timeout).
                AP_SLOT_RETRIES[i] += 1;
                if AP_SLOT_RETRIES[i] >= MAX_RETRY_FRAMES {
                    core::ptr::write_volatile(core::ptr::addr_of_mut!((*slot_ptr).item_id), 0u8);
                    core::ptr::write_volatile(core::ptr::addr_of_mut!((*slot_ptr).flags), 0u8);
                    (*slot_ptr)._reserved = [0, 0];
                    AP_SLOT_RETRIES[i] = 0;
                }
            }

            // Only process one item per frame to avoid overwhelming the game
            break;
        }
    }
}

/// Set dungeon-specific flags for boss keys, small keys, and maps.
/// Replicates the dungeon item logic from handle_custom_item_get() so
/// that AP-delivered dungeon items update both local and global dungeon
/// flags immediately, without needing the item actor's stateGet flow.
unsafe fn ap_set_dungeon_item_flags(itemid: u16) {
    const BK_TO_FLAGINDEX: [usize; 7] = [
        12,  // AC BK - item id 25
        15,  // FS BK - item id 26
        18,  // SSH BK - item id 27
        255, // unused (item id 28 = Key Piece, not a boss key)
        11,  // SVT BK - item id 29
        14,  // ET BK - item id 30
        17,  // LMF BK - item id 31
    ];

    const SK_TO_FLAGINDEX: [usize; 7] = [
        11, // SVT SK - item id 200
        17, // LMF SK - item id 201
        12, // AC SK - item id 202
        15, // FS SK - item id 203
        18, // SSH SK - item id 204
        20, // SK SK - item id 205
        9,  // Caves SK - item id 206
    ];

    const MAP_TO_FLAGINDEX: [usize; 7] = [
        11, // SVT MAP - item id 207
        14, // ET MAP - item id 208
        17, // LMF MAP - item id 209
        12, // AC MAP - item id 210
        15, // FS MAP - item id 211
        18, // SSH MAP - item id 212
        20, // SK MAP - item id 213
    ];

    let mut dungeon_item_mask: u16 = 0;

    if (itemid >= 25 && itemid <= 27) || (itemid >= 29 && itemid <= 31) {
        dungeon_item_mask = 0x80; // boss keys
    }
    if dungeon_item_mask == 0 && itemid >= 200 && itemid <= 206 {
        dungeon_item_mask = 0x0F; // small keys
    }
    if dungeon_item_mask == 0 && itemid >= 207 && itemid <= 213 {
        dungeon_item_mask = 0x02; // maps
    }

    if dungeon_item_mask == 0 {
        return; // Not a dungeon item
    }

    let current_scene_index = (*DUNGEONFLAG_MGR).sceneindex as usize;
    let dungeon_item_scene_index: usize;

    if dungeon_item_mask == 0x80 {
        dungeon_item_scene_index = BK_TO_FLAGINDEX[(itemid - 25) as usize];
    } else if dungeon_item_mask == 0x0F {
        dungeon_item_scene_index = SK_TO_FLAGINDEX[(itemid - 200) as usize];
    } else {
        dungeon_item_scene_index = MAP_TO_FLAGINDEX[(itemid - 207) as usize];
    }

    if dungeon_item_scene_index == 0xFF {
        return; // Invalid index (e.g., Key Piece at id 28)
    }

    // Set the local flag if the player is in the dungeon right now.
    if current_scene_index == dungeon_item_scene_index {
        if dungeon_item_mask != 0x0F {
            STATIC_DUNGEONFLAGS[0] |= dungeon_item_mask;
        } else {
            let mut current_key_count = STATIC_DUNGEONFLAGS[1] & 0xF;
            let mut obtained_key_count = (STATIC_DUNGEONFLAGS[1] >> 4) & 0xF;
            current_key_count += 1;
            obtained_key_count += 1;
            STATIC_DUNGEONFLAGS[1] = (obtained_key_count << 4) | current_key_count;
        }
    }

    // Always set the global (save file) flag.
    if dungeon_item_mask != 0x0F {
        (*FILE_MGR).FA.dungeonflags[dungeon_item_scene_index][0] |= dungeon_item_mask;
    } else {
        let mut current_key_count = (*FILE_MGR).FA.dungeonflags[dungeon_item_scene_index][1] & 0xF;
        let mut obtained_key_count =
            ((*FILE_MGR).FA.dungeonflags[dungeon_item_scene_index][1] >> 4) & 0xF;
        current_key_count += 1;
        obtained_key_count += 1;
        (*FILE_MGR).FA.dungeonflags[dungeon_item_scene_index][1] =
            (obtained_key_count << 4) | current_key_count;
    }
}

// Get the address of the Archipelago buffer for the Python client
#[no_mangle]
pub extern "C" fn get_archipelago_buffer_address() -> *mut ArchipelagoItemSlot {
    unsafe { ARCHIPELAGO_ITEM_BUFFER.as_mut_ptr() }
}

// ============================================================================
// Archipelago Check Statistics (for help text pages 0a, 0b, 0c)
// Written by the Python client, read by Rust (lyt.rs) for help menu display.
// ============================================================================

#[repr(C, packed(1))]
pub struct ApCheckStats {
    pub magic:          [u8; 4], // "CS\x00\x01" — signature for Python to find
    pub normal_checked: u16,
    pub normal_total:   u16,
    pub ap_checked:     u16,
    pub ap_total:       u16,
}
assert_eq_size!([u8; 12], ApCheckStats);

#[no_mangle]
pub static mut AP_CHECK_STATS: ApCheckStats = ApCheckStats {
    magic:          [0x43, 0x53, 0x00, 0x01], // "CS\x00\x01"
    normal_checked: 0,
    normal_total:   0,
    ap_checked:     0,
    ap_total:       0,
};

// ============================================================================
// Archipelago Item Info Table (for item 216 textbox — item name + player name)
// Written once by the Python client on connect; read by Rust when item 216
// event flow triggers to inject dynamic text into the textbox.
// ============================================================================

pub const AP_ITEM_TABLE_MAX: usize = 512;

#[repr(C, packed(1))]
#[derive(Copy, Clone)]
pub struct ApItemInfoEntry {
    pub flag_id:     u16,       // custom_flag_id (matches Python encoding)
    pub item_name:   [u16; 32], // UTF-16 item name  (null-terminated)
    pub player_name: [u16; 16], // UTF-16 player name (null-terminated)
}
assert_eq_size!([u8; 98], ApItemInfoEntry);

const EMPTY_AP_ENTRY: ApItemInfoEntry = ApItemInfoEntry {
    flag_id:     0xFFFF,
    item_name:   [0u16; 32],
    player_name: [0u16; 16],
};

#[repr(C, packed(1))]
pub struct ApItemInfoTable {
    pub magic:   [u8; 4], // "IT\x00\x01"
    pub count:   u16,     // number of valid entries
    pub _pad:    u16,
    pub entries: [ApItemInfoEntry; AP_ITEM_TABLE_MAX],
}
assert_eq_size!([u8; 8 + 98 * 512], ApItemInfoTable);

#[no_mangle]
pub static mut AP_ITEM_INFO_TABLE: ApItemInfoTable = ApItemInfoTable {
    magic:   [0x49, 0x54, 0x00, 0x01], // "IT\x00\x01"
    count:   0,
    _pad:    0,
    entries: [EMPTY_AP_ENTRY; AP_ITEM_TABLE_MAX],
};

// Tracks which item-216 location was most recently picked up.
// Set in handle_custom_item_get(); read in the custom event command.
#[no_mangle]
pub static mut LAST_AP_ITEM_FLAG_ID: u16 = 0xFFFF;

/// Look up the table index for a given custom_flag_id.
/// Returns the index into AP_ITEM_INFO_TABLE.entries, or usize::MAX if not
/// found.
///
/// Uses volatile reads for `count` and `flag_id` because the Python client
/// writes this table via cross-process memory writes
/// (pymem/WriteProcessMemory) and the emulator's JIT may otherwise cache stale
/// values from the initial zeroed static.
pub fn lookup_ap_item_index(flag_id: u16) -> usize {
    unsafe {
        let count_ptr = core::ptr::addr_of!(AP_ITEM_INFO_TABLE.count);
        let count = core::ptr::read_volatile(count_ptr) as usize;
        let limit = if count < AP_ITEM_TABLE_MAX {
            count
        } else {
            AP_ITEM_TABLE_MAX
        };
        for i in 0..limit {
            let flag_ptr = core::ptr::addr_of!(AP_ITEM_INFO_TABLE.entries[i].flag_id);
            if core::ptr::read_volatile(flag_ptr) == flag_id {
                return i;
            }
        }
        usize::MAX
    }
}
