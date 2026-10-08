//! Byte-for-byte mirror of `AP_IPC_ROOT` defined in
//! `sshd-rando-backend/asm/additions/rust-additions/src/ipc.rs`.
//!
//! # Keeping this in sync
//! This crate does NOT read the game's Rust source automatically — the
//! struct layouts here are hand-mirrored copies. If you change field order,
//! size, or add/remove a field in `ipc.rs` (or the sub-structs it wraps in
//! `commands.rs` / `item.rs`), you MUST make the matching change here, or
//! the client will read/write garbage into the game's memory.
//!
//! Field offsets are computed from `size_of` of the preceding fields (see
//! `offsets` module below), matching how the `#[repr(C, packed(1))]` layout
//! lays things out on the Rust-additions side. This means a sub-struct
//! resizing itself is automatically reflected in every offset that comes
//! after it — but the *order* of fields must still be kept in sync by hand.

use std::mem::size_of;

/// 8-byte discovery marker the client scans for exactly once.
pub const AP_IPC_MAGIC: [u8; 8] = *b"SSHDAPI\x01";
pub const AP_IPC_SUPPORTED_VERSION: u16 = 11;

// ─── Sub-structs (mirror commands.rs / item.rs) ────────────────────────────

#[repr(C, packed)]
#[derive(Copy, Clone, Debug, Default)]
pub struct ApFlagRequest {
    pub magic:          [u8; 4],
    pub pending:        u8, // bool, stored as u8 for portable packed layout
    pub flag_type:      u8,
    pub operation:      u8,
    pub _pad0:          u8,
    pub flag_id:        u16,
    pub value:          u16,
    pub scene_index:    u16,
    pub response_ready: u8,
    pub _pad1:          u8,
    pub response_value: u32,
}

#[repr(C, packed)]
#[derive(Copy, Clone, Debug, Default)]
pub struct ApWarpRequest {
    pub magic:          [u8; 4],
    pub pending:        u8,
    pub mode:           u8,
    pub layer:          u8,
    /// Target room (was `_pad0`; 0 = default).
    pub room:           u8,
    pub stage_name:     [u8; 8],
    pub response_ready: u8,
    pub response_code:  u8,
    /// Target entrance (was `_pad1[0]`; 0 = default).
    pub entrance:       u8,
    /// `WARP_FLAG_*` bits (was `_pad1[1]`; 0 = night/trial unspecified).
    pub flags:          u8,
}

#[repr(C, packed)]
#[derive(Copy, Clone, Debug, Default)]
pub struct ApCheckStats {
    pub magic:          [u8; 4],
    pub normal_checked: u16,
    pub normal_total:   u16,
    pub ap_checked:     u16,
    pub ap_total:       u16,
}

pub const ARCHIPELAGO_BUFFER_SIZE: usize = 1024;

/// One slot of the item buffer. The item id is 9 bits wide in the game, so it
/// is split across two bytes: the low byte in `item_id` and the high byte in
/// `item_id_hi`. A slot is pending when `item_id != 0`, so ids whose low byte is
/// 0 (256, 512) can't be delivered. `_reserved` (byte 2) must stay untouched:
/// the Python client's buffer access test writes to it.
#[repr(C, packed)]
#[derive(Copy, Clone, Debug, Default)]
pub struct ArchipelagoItemSlot {
    pub item_id:    u8,
    pub flags:      u8,
    pub _reserved:  u8,
    pub item_id_hi: u8,
}

/// Must match `AP_ITEM_TABLE_MAX` in the game's item.rs (all shuffles + pots
/// + pumpkins + barrels is ~1484 locations).
pub const AP_ITEM_TABLE_MAX: usize = 1536;

#[repr(C, packed)]
#[derive(Copy, Clone, Debug)]
pub struct ApItemInfoEntry {
    pub flag_id:     u16,
    pub item_name:   [u16; 32],
    pub player_name: [u16; 16],
}

impl Default for ApItemInfoEntry {
    fn default() -> Self {
        ApItemInfoEntry {
            flag_id:     0xFFFF,
            item_name:   [0u16; 32],
            player_name: [0u16; 16],
        }
    }
}

#[repr(C, packed)]
#[derive(Copy, Clone, Debug)]
pub struct ApItemInfoTable {
    pub magic:   [u8; 4],
    pub count:   u16,
    pub _pad:    u16,
    pub entries: [ApItemInfoEntry; AP_ITEM_TABLE_MAX],
}

impl Default for ApItemInfoTable {
    fn default() -> Self {
        ApItemInfoTable {
            magic:   [0; 4],
            count:   0,
            _pad:    0,
            entries: [ApItemInfoEntry::default(); AP_ITEM_TABLE_MAX],
        }
    }
}

#[repr(C, packed)]
#[derive(Copy, Clone, Debug, Default)]
pub struct ApSpawnRequest {
    pub magic:        [u8; 4],
    pub request:      u8,
    pub _pad0:        [u8; 1],
    pub actorid:      u16,
    pub actor_param1: u32,
    pub actor_param2: u32,
    pub oarc_name:    [u8; 32],
}

#[repr(C, packed)]
#[derive(Copy, Clone, Debug)]
pub struct ApCheatFlags {
    pub magic:                   [u8; 4],
    pub moon_jump:               u8,
    pub hovercraft:              u8,
    pub _pad:                    [u8; 2],
    pub hover_vel_y_bits:        u32,
    pub infinite_health:         u8,
    pub infinite_stamina:        u8,
    pub infinite_ammo:           u8,
    pub infinite_bugs:           u8,
    pub infinite_materials:      u8,
    pub infinite_shield:         u8,
    pub infinite_skyward_strike: u8,
    pub infinite_rupees:         u8,
    pub infinite_loftwing:       u8,
    pub no_electric_stun:        u8,
    pub spawn_demise_request:    u8,
    pub _pad2:                   [u8; 1],
    pub speed_multiplier_bits:   u32,
    pub no_enemy_damage:         u8,
}

impl Default for ApCheatFlags {
    fn default() -> Self {
        ApCheatFlags {
            magic:                   [0; 4],
            moon_jump:               0,
            hovercraft:              0,
            _pad:                    [0; 2],
            hover_vel_y_bits:        0x3FECCCCD, // 1.85f32
            infinite_health:         0,
            infinite_stamina:        0,
            infinite_ammo:           0,
            infinite_bugs:           0,
            infinite_materials:      0,
            infinite_shield:         0,
            infinite_skyward_strike: 0,
            infinite_rupees:         0,
            infinite_loftwing:       0,
            no_electric_stun:        0,
            spawn_demise_request:    0,
            _pad2:                   [0; 1],
            speed_multiplier_bits:   0,
            no_enemy_damage:         0,
        }
    }
}

/// Live by-value copy of the player's health and stamina (IPC version 8+),
/// refreshed every frame by the game. `stamina` already accounts for the
/// per-stage offset overrides (F103, B301), so the client just reads it.
#[repr(C, packed)]
#[derive(Copy, Clone, Debug, Default)]
pub struct ApPlayerVitals {
    /// Quarter hearts; 0 when no save file is loaded.
    pub current_health:  u16,
    pub health_capacity: u16,
    pub stamina:         u32,
    /// 1 if the game's FILE_MGR is non-null (a save file is loaded).
    pub save_loaded:     u8,
    /// 1 if the game's PLAYER_PTR is non-null (Link exists in this scene).
    pub player_valid:    u8,
}

// ─── Root struct ────────────────────────────────────────────────────────
// Field order MUST match `ApIpcRoot` in rust-additions/src/ipc.rs exactly.

/// One-shot DeathLink/BreathLink RECEIVE requests: the client writes 1, the
/// game performs the action and clears the byte back to 0.
#[repr(C, packed)]
#[derive(Copy, Clone, Debug, Default)]
pub struct ApLinkRequests {
    /// Set current health to 0.
    pub kill_request:          u8,
    /// Zero stamina and trigger the exhaustion state.
    pub drain_stamina_request: u8,
}

/// Live by-value copy of the current/next stage-loading state (IPC version
/// 9+), refreshed every frame by the game. Mirrors `ApStageInfo` in ipc.rs.
#[repr(C, packed)]
#[derive(Copy, Clone, Debug, Default)]
pub struct ApStageInfo {
    pub stage_name:                   [u8; 8],
    pub stage_suffix:                 [u8; 4],
    pub fade_frames:                  u16,
    pub room:                         u8,
    pub layer:                        u8,
    pub entrance:                     u8,
    pub night:                        u8,
    pub trial:                        u8,
    pub unk:                          u8,
    pub layer_copy:                   u8,
    pub respawn_type:                 u8,
    pub next_stage_name:              [u8; 8],
    pub next_stage_suffix:            [u8; 4],
    pub next_fade_frames:             u16,
    pub next_room:                    u8,
    pub next_layer:                   u8,
    pub next_entrance:                u8,
    pub next_night:                   u8,
    pub next_trial:                   u8,
    pub next_unk:                     u8,
    /// 1 if the game's STAGE_MGR is non-null.
    pub stage_mgr_valid:              u8,
    /// `dStageMgr.set_in_actually_trigger_entrance`.
    pub in_actually_trigger_entrance: u8,
}

/// Live by-value copy of the extended custom flag pages (IPC version 10+):
/// `FileMgr.FA.sceneflags[26..30]` and `FileMgr.FA.dungeonflags[26..30]`,
/// 4 pages x 8 u16 = 64 bytes each. Page `n` is custom flag group 1,
/// selector `n`. Mirrors `ApExtFlags` in ipc.rs.
#[repr(C, packed)]
#[derive(Copy, Clone, Debug)]
pub struct ApExtFlags {
    pub sceneflags:   [u8; 64],
    pub dungeonflags: [u8; 64],
}

impl Default for ApExtFlags {
    fn default() -> Self {
        ApExtFlags { sceneflags: [0; 64], dungeonflags: [0; 64] }
    }
}

#[repr(C, packed)]
#[derive(Copy, Clone, Debug)]
pub struct ApIpcRoot {
    pub magic:           [u8; 8],
    pub version:         u16,
    pub _pad0:           [u8; 6],
    pub flag_request:    ApFlagRequest,
    pub warp_request:    ApWarpRequest,
    pub spawn_request:   ApSpawnRequest,
    pub cheat_flags:     ApCheatFlags,
    pub check_stats:     ApCheckStats,

    // Live BY-VALUE COPIES (refreshed every frame by rust-additions'
    // item::refresh_ipc_addresses()) of the save file's
    // FileMgr.FA.sceneflags / .dungeonflags (`[[u16; 8]; 26]` = 416 bytes
    // each). Lets the client batch-read these arrays directly for
    // custom-flag location-check polling instead of one flag_request
    // round trip per flag.
    //
    // IMPORTANT: these are COPIES, not pointers/offsets. An earlier
    // revision of this file instead published a relative offset (from
    // AP_IPC_ROOT's own guest address) that the client would add onto
    // whatever HOST address it found AP_IPC_ROOT at -- that assumes the
    // guest's ENTIRE memory is one flat, linearly-mapped region in the
    // host process, which measurably doesn't hold: a real Ryujinx session
    // produced short-reads for a target ~650 MB from AP_IPC_ROOT even
    // with only one (correctly-found) AP_IPC_ROOT address to work from.
    // Copying the data BY VALUE into AP_IPC_ROOT's own memory sidesteps
    // the whole class of problem, since that memory is always reachable
    // (it's the same memory this client already reads/writes reliably
    // for item_buffer/check_stats/etc.).
    pub sceneflags:   [u8; 416],
    pub dungeonflags: [u8; 416],

    // Live BY-VALUE COPY (see above) of FileMgr.FA.tboxflags
    // (`[[u8; 4]; 26]`, 104 bytes) — committed chest-open flags, used for
    // goddess chest location checks.
    pub tboxflags: [u8; 104],

    // Live BY-VALUE COPY (see above) of STATIC_TBOXFLAGS (`[u8; 4]`) — the
    // in-RAM working copy of tboxflags for whichever scene is CURRENTLY
    // loaded, updated the instant a chest opens (before that scene's 4
    // bytes get committed into FA.tboxflags above, which typically only
    // happens on leaving the room). Paired with `current_scene_index`
    // below so the client knows which scene this 4-byte buffer belongs
    // to. Reading this alongside `tboxflags` is what gives goddess chest
    // checks near-instant detection, mirroring how the Python client read
    // both `FA.tboxflags` and `STATIC_TBOXFLAGS`.
    pub static_tboxflags: [u8; 4],

    // Current scene index (same indexing as FA.sceneflags/FA.tboxflags),
    // refreshed every frame alongside the addresses above. 0xFFFF until
    // the save file is loaded / no scene is current.
    pub current_scene_index: u16,

    // Current stage code, ASCII, null-padded (e.g. b"F002r\0\0\0" for
    // Beedle's Airshop), refreshed every frame. Unlike the `*_addr` fields
    // this is copied BY VALUE on the game side, so it can be read directly
    // with no host/guest address translation. All zero until a stage is
    // loaded. Lets pollers (e.g. `beedle_shop.rs`) gate on the player's
    // actual location.
    pub current_stage_name: [u8; 8],

    pub item_buffer:     [ArchipelagoItemSlot; ARCHIPELAGO_BUFFER_SIZE],
    pub item_info_table: ApItemInfoTable,

    // Live player health/stamina copy (IPC version 8+). Appended at the end
    // so every earlier offset is unchanged.
    pub player_vitals: ApPlayerVitals,

    // One-shot DeathLink/BreathLink receive requests (IPC version 8+).
    pub link_requests: ApLinkRequests,

    // Live stage-loading state (IPC version 9+). Appended at the end.
    pub stage_info: ApStageInfo,

    // Extended custom flag pages, group 1 (IPC version 10+). Appended at the end.
    pub ext_flags: ApExtFlags,
}

impl Default for ApIpcRoot {
    fn default() -> Self {
        ApIpcRoot {
            magic:           AP_IPC_MAGIC,
            version:         AP_IPC_SUPPORTED_VERSION,
            _pad0:           [0; 6],
            flag_request:    ApFlagRequest::default(),
            warp_request:    ApWarpRequest::default(),
            spawn_request:   ApSpawnRequest::default(),
            cheat_flags:     ApCheatFlags::default(),
            check_stats:     ApCheckStats::default(),
            sceneflags: [0u8; 416],
            dungeonflags: [0u8; 416],
            tboxflags: [0u8; 104],
            static_tboxflags: [0u8; 4],
            current_scene_index: 0xFFFF,
            current_stage_name: [0u8; 8],
            item_buffer:     [ArchipelagoItemSlot::default(); ARCHIPELAGO_BUFFER_SIZE],
            item_info_table: ApItemInfoTable::default(),
            player_vitals:   ApPlayerVitals::default(),
            link_requests:   ApLinkRequests::default(),
            stage_info:      ApStageInfo::default(),
            ext_flags:       ApExtFlags::default(),
        }
    }
}

/// Field offsets within `ApIpcRoot`, in bytes. Computed from `size_of` of
/// the preceding fields — automatically correct if a sub-struct's SIZE
/// changes, but relies on field ORDER matching `ipc.rs` on the game side.
pub mod offsets {
    use super::*;

    pub const MAGIC: usize = 0;
    pub const VERSION: usize = 8;
    pub const FLAG_REQUEST: usize = 16;
    pub const WARP_REQUEST: usize = FLAG_REQUEST + size_of::<ApFlagRequest>();
    pub const SPAWN_REQUEST: usize = WARP_REQUEST + size_of::<ApWarpRequest>();
    pub const CHEAT_FLAGS: usize = SPAWN_REQUEST + size_of::<ApSpawnRequest>();
    pub const CHECK_STATS: usize = CHEAT_FLAGS + size_of::<ApCheatFlags>();
    pub const SCENEFLAGS: usize = CHECK_STATS + size_of::<ApCheckStats>();
    pub const DUNGEONFLAGS: usize = SCENEFLAGS + 416;
    pub const TBOXFLAGS: usize = DUNGEONFLAGS + 416;
    pub const STATIC_TBOXFLAGS: usize = TBOXFLAGS + 104;
    pub const CURRENT_SCENE_INDEX: usize = STATIC_TBOXFLAGS + 4;
    pub const CURRENT_STAGE_NAME: usize = CURRENT_SCENE_INDEX + 2;
    pub const ITEM_BUFFER: usize = CURRENT_STAGE_NAME + 8;
    pub const ITEM_INFO_TABLE: usize =
        ITEM_BUFFER + size_of::<[ArchipelagoItemSlot; ARCHIPELAGO_BUFFER_SIZE]>();
    pub const PLAYER_VITALS: usize = ITEM_INFO_TABLE + size_of::<ApItemInfoTable>();
    pub const LINK_REQUESTS: usize = PLAYER_VITALS + size_of::<ApPlayerVitals>();
    pub const STAGE_INFO: usize = LINK_REQUESTS + size_of::<ApLinkRequests>();
    pub const EXT_FLAGS: usize = STAGE_INFO + size_of::<ApStageInfo>();
    pub const TOTAL_SIZE: usize = EXT_FLAGS + size_of::<ApExtFlags>();

    pub fn item_buffer_slot(index: usize) -> usize {
        ITEM_BUFFER + index * size_of::<ArchipelagoItemSlot>()
    }
}

// ─── Flag/warp command protocol constants (mirror commands.rs) ─────────────

pub const FLAG_TYPE_STORYFLAG: u8 = 0;
pub const FLAG_TYPE_SCENEFLAG: u8 = 1;
pub const FLAG_TYPE_ITEMFLAG: u8 = 2;
pub const FLAG_TYPE_DUNGEONFLAG: u8 = 3;

pub const FLAG_OP_GET: u8 = 0;
pub const FLAG_OP_SET: u8 = 1;
pub const FLAG_OP_UNSET: u8 = 2;

pub const SCENE_INDEX_CURRENT: u16 = 0xFFFF;

pub const WARP_MODE_START: u8 = 0;
pub const WARP_MODE_STAGE: u8 = 1;

/// `ApWarpRequest.flags` bits (mirror commands.rs).
/// Night value to use (only honoured if `WARP_FLAG_NIGHT_SET` is also set).
pub const WARP_FLAG_NIGHT: u8 = 1 << 0;
/// The night value was explicitly specified.
pub const WARP_FLAG_NIGHT_SET: u8 = 1 << 1;
/// Trial value to use (only honoured if `WARP_FLAG_TRIAL_SET` is also set).
pub const WARP_FLAG_TRIAL: u8 = 1 << 2;
/// The trial value was explicitly specified.
pub const WARP_FLAG_TRIAL_SET: u8 = 1 << 3;

/// Decodes the custom flag ID encoding used for the majority of location
/// checks (see `decode_custom_flag` in the game's `item.rs`, which this
/// mirrors bit-for-bit):
///
/// - bits 0-6 (`0x7F`): flag number within the scene's flag array (0-127)
/// - bits 7-8 (`0x180`): which of 4 dedicated "custom flag" pages (0-3)
/// - bit 9 (`0x200`): 0 = sceneflag, 1 = dungeonflag
/// - bit 10 (`0x400`): 0 = group 0, 1 = group 1 (extended pages)
///
/// Group 0's pages are save-file scene indices 6, 13, 16, 19 (the only
/// indices no stage uses). Group 1's pages are indices 26-29, reserved
/// padding in the save file's flag arrays that no stage maps to; they are
/// NOT inside `ApIpcRoot.sceneflags`/`.dungeonflags` (26 indices) but in
/// `ApIpcRoot.ext_flags`.
pub mod custom_flag {
    /// Real save-file scene indices the 2-bit selector maps to in group 0.
    pub const SCENE_INDEX_MAP: [u16; 4] = [6, 13, 16, 19];
    /// First save-file scene index of group 1; selector `n` is `26 + n`.
    pub const GROUP1_FIRST_SCENE_INDEX: u16 = 26;
    /// Group bit in a full custom flag ID.
    pub const GROUP1_BIT: u16 = 0x400;

    pub struct Decoded {
        /// `true` = dungeonflag, `false` = sceneflag — matches
        /// `FLAG_TYPE_DUNGEONFLAG` / `FLAG_TYPE_SCENEFLAG` in this crate.
        pub is_dungeonflag: bool,
        /// `true` = group 1 (extended pages, read from `ext_flags`).
        pub group1:         bool,
        /// Flag number (0-127) — this is the `flag_id` to pass to
        /// `check_global_sceneflag`/`check_global_dungeonflag` (and
        /// therefore to a `flag_request` with the matching `FLAG_TYPE_*`).
        pub flag_num:       u16,
        /// Real save-file scene index (6/13/16/19, or 26-29 for group 1) —
        /// the `scene_index` to pass alongside `flag_num` above.
        pub scene_index:    u16,
        /// Which u16 within the scene's `[u16; 8]` array holds this flag —
        /// only needed if reading the batch scene arrays directly rather
        /// than through a flag_request.
        pub array_index:    usize,
        /// Which bit (0-15) within that u16 — same caveat as above.
        pub bit_index:      u32,
    }

    pub fn decode(flag_id: u16) -> Decoded {
        let flag_num = flag_id & 0x7F;
        let scene_selector = ((flag_id >> 7) & 0x03) as usize;
        let is_dungeonflag = ((flag_id >> 9) & 0x01) != 0;
        let group1 = flag_id & GROUP1_BIT != 0;
        let scene_index = if group1 {
            GROUP1_FIRST_SCENE_INDEX + scene_selector as u16
        } else {
            SCENE_INDEX_MAP[scene_selector]
        };
        Decoded {
            is_dungeonflag,
            group1,
            flag_num,
            scene_index,
            array_index: (flag_num / 16) as usize,
            bit_index:   (flag_num % 16) as u32,
        }
    }
}

/// Safe byte-level (de)serialization helpers. These avoid ever taking a
/// reference into an externally-sourced, potentially-misaligned buffer —
/// all reads/writes go through `read_unaligned`/`write_unaligned`-style
/// byte copies.
pub mod bytes {
    use super::*;

    /// Reinterpret a same-sized byte slice as a `T` by value (copy out, no
    /// reference into `buf` is ever taken). Panics if `buf.len() !=
    /// size_of::<T>()`.
    pub fn read<T: Copy>(buf: &[u8]) -> T {
        assert_eq!(buf.len(), size_of::<T>(), "buffer size mismatch for read::<T>()");
        unsafe { std::ptr::read_unaligned(buf.as_ptr() as *const T) }
    }

    /// Turn a `T` into its raw bytes for writing back to process memory.
    pub fn write<T: Copy>(value: &T) -> Vec<u8> {
        let mut out = vec![0u8; size_of::<T>()];
        unsafe {
            std::ptr::write_unaligned(out.as_mut_ptr() as *mut T, *value);
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sub_struct_sizes_match_game_side() {
        // These mirror the `assert_eq_size!` checks in commands.rs / item.rs
        // on the game side. If these fail, something in this file has
        // drifted from the Rust-additions layout.
        assert_eq!(size_of::<ApFlagRequest>(), 20);
        assert_eq!(size_of::<ApWarpRequest>(), 20);
        assert_eq!(size_of::<ApSpawnRequest>(), 48);
        assert_eq!(size_of::<ApCheatFlags>(), 29);
        assert_eq!(size_of::<ApCheckStats>(), 12);
        assert_eq!(size_of::<ArchipelagoItemSlot>(), 4);
        assert_eq!(size_of::<ApItemInfoEntry>(), 98);
        assert_eq!(size_of::<ApItemInfoTable>(), 8 + 98 * 1536);
        assert_eq!(size_of::<ApPlayerVitals>(), 10);
        assert_eq!(size_of::<ApLinkRequests>(), 2);
        assert_eq!(size_of::<ApStageInfo>(), 44);
        assert_eq!(size_of::<ApExtFlags>(), 128);
    }

    #[test]
    fn root_offsets_and_total_size() {
        assert_eq!(offsets::MAGIC, 0);
        assert_eq!(offsets::VERSION, 8);
        assert_eq!(offsets::FLAG_REQUEST, 16);
        assert_eq!(offsets::WARP_REQUEST, 36);
        assert_eq!(offsets::SPAWN_REQUEST, 56);
        assert_eq!(offsets::CHEAT_FLAGS, 104);
        assert_eq!(offsets::CHECK_STATS, 133);
        assert_eq!(offsets::SCENEFLAGS, 145);
        assert_eq!(offsets::DUNGEONFLAGS, 561);
        assert_eq!(offsets::TBOXFLAGS, 977);
        assert_eq!(offsets::STATIC_TBOXFLAGS, 1081);
        assert_eq!(offsets::CURRENT_SCENE_INDEX, 1085);
        assert_eq!(offsets::CURRENT_STAGE_NAME, 1087);
        assert_eq!(offsets::ITEM_BUFFER, 1095);
        assert_eq!(offsets::ITEM_INFO_TABLE, 1095 + 4 * 1024);
        assert_eq!(offsets::PLAYER_VITALS, 1095 + 4 * 1024 + 8 + 98 * 1536);
        assert_eq!(offsets::LINK_REQUESTS, 1095 + 4 * 1024 + 8 + 98 * 1536 + 10);
        assert_eq!(offsets::STAGE_INFO, 1095 + 4 * 1024 + 8 + 98 * 1536 + 10 + 2);
        assert_eq!(offsets::EXT_FLAGS, 1095 + 4 * 1024 + 8 + 98 * 1536 + 10 + 2 + 44);
        assert_eq!(offsets::TOTAL_SIZE, 1095 + 4 * 1024 + 8 + 98 * 1536 + 10 + 2 + 44 + 128);
        assert_eq!(size_of::<ApIpcRoot>(), offsets::TOTAL_SIZE);
    }

    #[test]
    fn custom_flag_decode_matches_python_reference() {
        // flag_num=5, scene_selector=2 (-> scene 16), sceneflag
        let flag_id: u16 = 5 | (2 << 7);
        let d = custom_flag::decode(flag_id);
        assert!(!d.is_dungeonflag);
        assert!(!d.group1);
        assert_eq!(d.flag_num, 5);
        assert_eq!(d.scene_index, 16);
        assert_eq!(d.array_index, 0);
        assert_eq!(d.bit_index, 5);

        // group 1: selector 3 (-> scene 29), dungeonflag, flag_num=100
        let flag_id: u16 = 100 | (3 << 7) | (1 << 9) | custom_flag::GROUP1_BIT;
        let d = custom_flag::decode(flag_id);
        assert!(d.group1);
        assert!(d.is_dungeonflag);
        assert_eq!(d.scene_index, 29);
        assert_eq!(d.flag_num, 100);

        // flag_num=100 (array_index=6, bit=4), scene_selector=0 (-> scene 6), dungeonflag
        let flag_id: u16 = 100 | (0 << 7) | (1 << 9);
        let d = custom_flag::decode(flag_id);
        assert!(d.is_dungeonflag);
        assert_eq!(d.flag_num, 100);
        assert_eq!(d.scene_index, 6);
        assert_eq!(d.array_index, 6);
        assert_eq!(d.bit_index, 4);
    }

    #[test]
    fn roundtrip_flag_request() {
        let req = ApFlagRequest {
            magic:          [0; 4],
            pending:        1,
            flag_type:      FLAG_TYPE_STORYFLAG,
            operation:      FLAG_OP_SET,
            _pad0:          0,
            flag_id:        42,
            value:          1,
            scene_index:    SCENE_INDEX_CURRENT,
            response_ready: 0,
            _pad1:          0,
            response_value: 0,
        };
        let raw = bytes::write(&req);
        let back: ApFlagRequest = bytes::read(&raw);
        let flag_id = back.flag_id; // copy out of the packed struct first —
        let operation = back.operation; // taking `&packed.field` is UB-unsafe
        assert_eq!(flag_id, 42);
        assert_eq!(operation, FLAG_OP_SET);
    }
}
