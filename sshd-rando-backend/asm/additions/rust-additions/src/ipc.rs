#![allow(non_camel_case_types)]
#![allow(non_snake_case)]
#![allow(unused)]

//! Consolidated external IPC surface for the host (PC-side) Archipelago
//! client.
//!
//! ─── Why this file exists ───────────────────────────────────────────────
//! Previously, each mailbox (AP_FLAG_REQUEST, AP_WARP_REQUEST,
//! AP_SPAWN_REQUEST, AP_CHEAT_FLAGS, ARCHIPELAGO_ITEM_BUFFER,
//! AP_CHECK_STATS, AP_ITEM_INFO_TABLE) was its own independent `static`,
//! each requiring its own separate memory-signature scan from the external
//! client to locate. That meant 7 scans instead of 1, and 7 separate magic
//! constants to keep in sync.
//!
//! This module wraps all seven into ONE struct (`ApIpcRoot`) with ONE magic
//! value. The external client scans for `AP_IPC_MAGIC` exactly once, and
//! every other mailbox is then a fixed byte offset from that address —
//! computed the same way (from cumulative field sizes) on both sides.
//!
//! The individual sub-structs (`ApFlagRequest`, `ApWarpRequest`,
//! `ApSpawnRequest`, `ApCheatFlags`, `ArchipelagoItemSlot`, `ApCheckStats`,
//! `ApItemInfoTable`) are UNCHANGED — same fields, same order, same size —
//! so nothing about how the game code in commands.rs/item.rs/lyt.rs/
//! event.rs/cheats.rs *uses* them changes, only WHERE they live in memory
//! (as fields of AP_IPC_ROOT instead of standalone statics). Their own
//! `magic` fields are left in place for backward compatibility / defence-
//! in-depth (harmless if unused), but the external client no longer needs
//! to scan for them.
//!
//! ─── IMPORTANT ──────────────────────────────────────────────────────────
//! This layout is mirrored byte-for-byte in the Rust host client (see the
//! `ap-ipc` crate, `src/lib.rs`, in the new `sshd-ap-client` workspace). If
//! you add, remove, reorder, or resize any field here, you MUST update the
//! client's copy to match, or the client will read/write garbage. Run
//! `python assemble.py` and `cargo check` (in rust-additions AND in
//! sshd-ap-client) after any change here, before testing in-game.

use crate::cheats::{ApCheatFlags, ApSpawnRequest};
use crate::commands::{ApFlagRequest, ApWarpRequest};
use crate::item::{ApCheckStats, ApItemInfoTable, ArchipelagoItemSlot, ARCHIPELAGO_BUFFER_SIZE};
use static_assertions::assert_eq_size;

/// One-time discovery marker for the external client. 8 bytes: "SSHDAPI\x01"
/// where the trailing byte is the IPC layout version (bump this if you make
/// a breaking change to `ApIpcRoot`'s layout so old/new clients don't
/// silently misread each other).
pub const AP_IPC_MAGIC: [u8; 8] = *b"SSHDAPI\x01";
pub const AP_IPC_VERSION: u16 = 9;

/// Live BY-VALUE COPY of the player's health and stamina, refreshed every
/// frame by `item::refresh_ipc_addresses()`. Lets the host client detect
/// deaths / stamina exhaustion (DeathLink / BreathLink) without knowing
/// any emulator-specific guest addresses.
///
/// - `current_health` / `health_capacity`: `FileMgr.FA` values (quarter
///   hearts). Both are 0 when no save file is loaded.
/// - `stamina`: `dPlayer.stamina_amount`, resolved with the same per-stage
///   offset overrides `cheats::handle_infinite_stamina` uses (F103, B301). 0
///   whenever `player_valid` is 0.
/// - `save_loaded`: 1 if `FILE_MGR` is non-null.
/// - `player_valid`: 1 if `PLAYER_PTR` is non-null.
#[repr(C, packed(1))]
pub struct ApPlayerVitals {
    pub current_health:  u16,
    pub health_capacity: u16,
    pub stamina:         u32,
    pub save_loaded:     u8,
    pub player_valid:    u8,
}
assert_eq_size!([u8; 10], ApPlayerVitals);

/// One-shot requests from the host client for DeathLink / BreathLink
/// RECEIVES. The client sets a byte to 1; `cheats::handle_link_requests`
/// performs the action and clears it back to 0.
///
/// - `kill_request`: set current health to 0 (kills Link).
/// - `drain_stamina_request`: zero stamina and trigger the exhaustion state.
#[repr(C, packed(1))]
pub struct ApLinkRequests {
    pub kill_request:          u8,
    pub drain_stamina_request: u8,
}
assert_eq_size!([u8; 2], ApLinkRequests);

/// Live BY-VALUE COPY of the current/next stage-loading state, refreshed
/// every frame by `entrance::refresh_stage_info()` (called from
/// `item::refresh_ipc_addresses()`). Backs the client's `/stage_info`.
///
/// - `stage_name` .. `respawn_type`: the CURRENT_* globals (+ RESPAWN_TYPE).
/// - `next_*`: the NEXT_* globals (the pending/last requested transition).
/// - `stage_mgr_valid`: 1 if STAGE_MGR is non-null.
/// - `in_actually_trigger_entrance`:
///   `dStageMgr.set_in_actually_trigger_entrance`.
#[repr(C, packed(1))]
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
    pub stage_mgr_valid:              u8,
    pub in_actually_trigger_entrance: u8,
}
assert_eq_size!([u8; 44], ApStageInfo);

#[repr(C, packed(1))]
pub struct ApIpcRoot {
    /// External client scans for this ONCE to find everything below.
    pub magic:   [u8; 8],
    pub version: u16,
    pub _pad0:   [u8; 6],

    // ── Request/response mailboxes (Python writes request, Rust writes
    //    response / clears the one-shot flag) ──
    pub flag_request:  ApFlagRequest,
    pub warp_request:  ApWarpRequest,
    pub spawn_request: ApSpawnRequest,

    // ── Python-write (continuous config) / Rust-read every frame ──
    pub cheat_flags: ApCheatFlags,

    // ── Rust-write / Python-read ──
    pub check_stats: ApCheckStats,

    // ── Rust-write / Python-read: live BY-VALUE COPIES of the save file's
    //    sceneflags/dungeonflags arrays (FileMgr.FA.sceneflags/
    //    .dungeonflags, both `[[u16; 8]; 26]` = 416 bytes), refreshed
    //    every frame by item::refresh_ipc_addresses(). Lets the client
    //    batch-read these arrays directly (mirroring the old Python
    //    client's efficient scene-batch-read approach for custom-flag
    //    location checks) instead of issuing one flag_request round trip
    //    per flag.
    //
    //    IMPORTANT: these are COPIES, not pointers/offsets. An earlier
    //    revision of this file instead published a relative offset (from
    //    AP_IPC_ROOT's own guest address) that the client would add onto
    //    whatever HOST address it found AP_IPC_ROOT at -- that assumes
    //    the guest's ENTIRE memory is one flat, linearly-mapped region in
    //    the host process, which measurably doesn't hold: a real Ryujinx
    //    session produced short-reads for a target ~650 MB from
    //    AP_IPC_ROOT even with only one (correctly-found) AP_IPC_ROOT
    //    address to work from, meaning the assumption fails long before
    //    "which alias to pick" ever becomes the issue. Copying the data
    //    BY VALUE into AP_IPC_ROOT's own memory sidesteps the whole class
    //    of problem: AP_IPC_ROOT's own memory is always reachable (it's
    //    the exact memory the client pattern-scanned for and already
    //    reads/writes into directly for item_buffer/check_stats/etc.), so
    //    there is no separate pointer to resolve at all. The cost is
    //    ~940 bytes memcpy'd once per frame across these four fields,
    //    which is trivial.
    pub sceneflags:   [u8; 416],
    pub dungeonflags: [u8; 416],

    // ── Rust-write / Python-read: live BY-VALUE COPY (see above) of
    //    FileMgr.FA.tboxflags (`[[u8; 4]; 26]`, 104 bytes) — the
    //    persistent, committed chest-open flags used for goddess chest
    //    location checks. Refreshed every frame alongside the two fields
    //    above.
    pub tboxflags: [u8; 104],

    // ── Rust-write / Python-read: live BY-VALUE COPY (see above) of
    //    STATIC_TBOXFLAGS (`[u8; 4]`) — the in-RAM working copy of
    //    tboxflags for whichever scene is CURRENTLY loaded, updated the
    //    instant a chest opens (before that scene's 4 bytes get committed
    //    into FA.tboxflags above, which typically only happens on leaving
    //    the room). Paired with `current_scene_index` below so the
    //    client knows which scene this 4-byte buffer belongs to. Reading
    //    this alongside `tboxflags` gives goddess chest checks
    //    near-instant detection, mirroring the old Python client's
    //    dual-read (FA.tboxflags + STATIC_TBOXFLAGS) approach.
    pub static_tboxflags: [u8; 4],

    // ── Rust-write / Python-read: current scene index (same indexing as
    //    FA.sceneflags/FA.tboxflags), refreshed every frame alongside the
    //    addresses above. 0xFFFF until the save file is loaded / no scene
    //    is current.
    pub current_scene_index: u16,

    // ── Rust-write / Python-read: the current stage code (mirrors
    //    CURRENT_STAGE_NAME), ASCII, null-padded (e.g. b"F002r\0\0\0" for
    //    Beedle's Airshop). Refreshed every frame alongside the fields
    //    above. Unlike the `*_addr` fields, this is copied BY VALUE rather
    //    than by pointer, so the client can read it directly with no
    //    host/guest address translation needed. All zero until the game
    //    has loaded a stage. Lets the client gate stage-specific polling
    //    (e.g. Beedle's Airshop purchase detection) on the player's
    //    actual location, the same way the old Python client's
    //    `current_stage` did.
    pub current_stage_name: [u8; 8],

    // ── Python-write / Rust-read ──
    pub item_buffer:     [ArchipelagoItemSlot; ARCHIPELAGO_BUFFER_SIZE],
    pub item_info_table: ApItemInfoTable,

    // ── Rust-write / Python-read: live player health/stamina copy (see
    //    `ApPlayerVitals`). Appended at the END of the struct so every
    //    earlier field keeps its offset. Added in IPC version 8.
    pub player_vitals: ApPlayerVitals,

    // ── Python-write / Rust-read: one-shot DeathLink/BreathLink receive
    //    requests (see `ApLinkRequests`). Also appended at the end.
    pub link_requests: ApLinkRequests,

    // ── Rust-write / client-read: live stage-loading state (see
    //    `ApStageInfo`). Appended at the END. Added in IPC version 9.
    pub stage_info: ApStageInfo,
}

#[no_mangle]
pub static mut AP_IPC_ROOT: ApIpcRoot = ApIpcRoot {
    magic:   AP_IPC_MAGIC,
    version: AP_IPC_VERSION,
    _pad0:   [0; 6],

    flag_request: ApFlagRequest {
        magic:          [0x46, 0x4C, 0x00, 0x01], /* "FL\x00\x01" (legacy, unused for discovery
                                                   * now) */
        pending:        false,
        flag_type:      0,
        operation:      0,
        _pad0:          0,
        flag_id:        0,
        value:          0,
        scene_index:    0xFFFF,
        response_ready: false,
        _pad1:          0,
        response_value: 0,
    },

    warp_request: ApWarpRequest {
        magic:          [0x57, 0x52, 0x00, 0x01], /* "WR\x00\x01" (legacy, unused for discovery
                                                   * now) */
        pending:        false,
        mode:           0,
        layer:          0xFF,
        _pad0:          0,
        stage_name:     [0u8; 8],
        response_ready: false,
        response_code:  0,
        _pad1:          [0u8; 2],
    },

    spawn_request: ApSpawnRequest {
        magic:        [0x53, 0x41, 0x00, 0x01], // "SA\x00\x01" (legacy, unused for discovery now)
        request:      false,
        _pad0:        [0u8; 1],
        actorid:      0,
        actor_param1: 0xFFFFFFFF,
        actor_param2: 0xFFFFFFFF,
        oarc_name:    [0u8; 32],
    },

    cheat_flags: ApCheatFlags {
        magic:                   [0x43, 0x46, 0x00, 0x01], /* "CF\x00\x01" (legacy, unused for
                                                            * discovery now) */
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
        spawn_demise_request:    false,
        _pad2:                   [0u8; 1],
        speed_multiplier_bits:   0u32,
        no_enemy_damage:         false,
    },

    check_stats: ApCheckStats {
        magic:          [0x43, 0x53, 0x00, 0x01], /* "CS\x00\x01" (legacy, unused for discovery
                                                   * now) */
        normal_checked: 0,
        normal_total:   0,
        ap_checked:     0,
        ap_total:       0,
    },

    sceneflags:          [0u8; 416],
    dungeonflags:        [0u8; 416],
    tboxflags:           [0u8; 104],
    static_tboxflags:    [0u8; 4],
    current_scene_index: 0xFFFF,
    current_stage_name:  [0u8; 8],

    item_buffer: crate::item::EMPTY_ARCHIPELAGO_ITEM_BUFFER,

    item_info_table: ApItemInfoTable {
        magic:   [0x49, 0x54, 0x00, 0x01], // "IT\x00\x01" (legacy, unused for discovery now)
        count:   0,
        _pad:    0,
        entries: [crate::item::EMPTY_AP_ENTRY; crate::item::AP_ITEM_TABLE_MAX],
    },

    player_vitals: ApPlayerVitals {
        current_health:  0,
        health_capacity: 0,
        stamina:         0,
        save_loaded:     0,
        player_valid:    0,
    },

    link_requests: ApLinkRequests {
        kill_request:          0,
        drain_stamina_request: 0,
    },

    stage_info: ApStageInfo {
        stage_name:                   [0; 8],
        stage_suffix:                 [0; 4],
        fade_frames:                  0,
        room:                         0,
        layer:                        0,
        entrance:                     0,
        night:                        0,
        trial:                        0,
        unk:                          0,
        layer_copy:                   0,
        respawn_type:                 0,
        next_stage_name:              [0; 8],
        next_stage_suffix:            [0; 4],
        next_fade_frames:             0,
        next_room:                    0,
        next_layer:                   0,
        next_entrance:                0,
        next_night:                   0,
        next_trial:                   0,
        next_unk:                     0,
        stage_mgr_valid:              0,
        in_actually_trigger_entrance: 0,
    },
};

// Self-check: catches accidental layout drift at compile time. Update this
// number (and tell the client team) if you deliberately resize the struct.
assert_eq_size!(
    [u8; 16
        + 20
        + 20
        + 48
        + 29
        + 12
        + 416
        + 416
        + 104
        + 4
        + 2
        + 8
        + (4 * 1024)
        + (8 + 98 * 512)
        + 10
        + 2
        + 44],
    ApIpcRoot
);
