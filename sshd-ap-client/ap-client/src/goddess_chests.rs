//! Goddess chest location-check detection.
//!
//! Ported from `SSHDClient.py`'s `check_goddess_chest_flags`. Goddess
//! chests can't use the "custom flag" mechanism (writing to their spawn
//! params would corrupt the storyflag gate that makes them appear), so
//! instead we poll the *vanilla* tboxflag the game sets when a chest is
//! physically opened.
//!
//! # Instant detection
//! Like the Python client, this reads TWO sources every poll and ORs them
//! together:
//! - `FA.tboxflags` (`AP_IPC_ROOT.tboxflags`, a live by-value copy) — the
//!   persistent, committed save-file copy, 104 bytes covering all 26
//!   scenes. Only updated when the game commits that scene's buffer
//!   (typically on leaving the room), so alone it lags behind the moment
//!   a chest opens.
//! - `STATIC_TBOXFLAGS` (`AP_IPC_ROOT.static_tboxflags`, paired with
//!   `AP_IPC_ROOT.current_scene_index`) — the in-RAM working copy for
//!   only the *currently loaded* scene (4 bytes), updated the instant a
//!   chest opens, before that commit happens. Since it only covers one
//!   scene at a time, it's only consulted for chests whose `scene_index`
//!   matches `current_scene_index`; chests in other scenes fall back to
//!   whatever `FA.tboxflags` already has for them.
//!
//! Both `tboxflags`/`static_tboxflags` read back as all-zero and
//! `current_scene_index` as its `Default` 0xFFFF sentinel (see
//! `ap_ipc::ApIpcRoot`) until the save file is loaded, which this handles
//! the same as "nothing checked yet" — no special-casing needed.

use std::collections::HashMap;

use ap_ipc::offsets;
use process_memory::{MemError, ProcessMemory};

const TBOXFLAGS_BYTES: usize = 26 * 4; // [[u8; 4]; 26]
const STATIC_TBOXFLAGS_BYTES: usize = 4; // [u8; 4], current scene only
const NO_CURRENT_SCENE: u16 = 0xFFFF;

pub struct GoddessChestPoller {
    /// location_code -> (scene_index, chestflag)
    flags:       HashMap<i64, (u16, u8)>,
    previous:    HashMap<i64, u8>,
    initialized: bool,
}

impl GoddessChestPoller {
    pub fn new(flags: HashMap<i64, (u16, u8)>) -> Self {
        GoddessChestPoller { flags, previous: HashMap::new(), initialized: false }
    }

    /// Returns newly-checked AP location codes, same "recovered on first
    /// poll" semantics as `CustomFlagPoller::poll`.
    pub fn poll(
        &mut self,
        mem: &mut impl ProcessMemory,
        root_addr: usize,
        already_checked: &impl Fn(i64) -> bool,
    ) -> Result<Vec<i64>, MemError> {
        if self.flags.is_empty() {
            return Ok(Vec::new());
        }

        let tboxflags = mem.read_bytes(root_addr + offsets::TBOXFLAGS, TBOXFLAGS_BYTES)?;

        // Instant-detection path: the in-RAM working copy for whichever
        // scene is currently loaded, updated the instant a chest opens
        // rather than on scene-exit commit (see module docs).
        let static_tboxflags =
            mem.read_bytes(root_addr + offsets::STATIC_TBOXFLAGS, STATIC_TBOXFLAGS_BYTES)?;
        let current_scene_index = crate::read_u16(mem, root_addr + offsets::CURRENT_SCENE_INDEX)?;

        let is_first_poll = !self.initialized;
        let mut newly_checked = Vec::new();

        for (&location_code, &(scene_index, chestflag)) in &self.flags {
            let within_block = (chestflag % 32) as usize;
            let bit_shift = within_block % 8;

            let flat_byte_offset = scene_index as usize * 4 + within_block / 8;
            let mut bit = if flat_byte_offset < tboxflags.len() {
                (tboxflags[flat_byte_offset] >> bit_shift) & 1
            } else {
                0
            };

            // OR in the instant, in-RAM copy — but only when it's actually
            // for this chest's scene (and a scene is actually loaded),
            // since `static_tboxflags` only ever covers whichever one
            // scene is currently loaded.
            if bit == 0 && current_scene_index != NO_CURRENT_SCENE && scene_index == current_scene_index {
                let static_byte_offset = within_block / 8;
                if static_byte_offset < static_tboxflags.len() {
                    bit |= (static_tboxflags[static_byte_offset] >> bit_shift) & 1;
                }
            }

            let previous = self.previous.insert(location_code, bit);
            if already_checked(location_code) {
                continue;
            }
            match previous {
                None if is_first_poll && bit == 1 => newly_checked.push(location_code),
                Some(0) if bit == 1 => newly_checked.push(location_code),
                _ => {},
            }
        }

        self.initialized = true;
        Ok(newly_checked)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bit_math_matches_python_reference() {
        // chestflag=5 -> within_block=5, byte 0, bit 5; scene_index=3 ->
        // flat_byte_offset = 3*4 + 0 = 12.
        let chestflag: u8 = 5;
        let scene_index: u16 = 3;
        let within_block = (chestflag % 32) as usize;
        let flat_byte_offset = scene_index as usize * 4 + within_block / 8;
        let bit_shift = within_block % 8;
        assert_eq!(flat_byte_offset, 12);
        assert_eq!(bit_shift, 5);

        // chestflag=40 -> within_block=8 (40%32), byte 1, bit 0.
        let chestflag: u8 = 40;
        let within_block = (chestflag % 32) as usize;
        assert_eq!(within_block, 8);
        assert_eq!(within_block / 8, 1);
        assert_eq!(within_block % 8, 0);
    }

    /// Mirrors the OR-combination logic in `poll()` directly against the
    /// bit math, without needing a `ProcessMemory` fake: a chest whose
    /// scene matches `current_scene_index` should be detected from
    /// `static_tboxflags` alone, even when the (not-yet-committed)
    /// `tboxflags` byte for that scene is still all zero.
    #[test]
    fn static_buffer_detects_before_commit() {
        let scene_index: u16 = 5;
        let chestflag: u8 = 3; // within_block=3 -> byte 0, bit 3
        let current_scene_index: u16 = 5;

        let tboxflags = [0u8; TBOXFLAGS_BYTES];
        let mut static_tboxflags = [0u8; STATIC_TBOXFLAGS_BYTES];
        // Chest opened this frame: only the static/working copy knows yet.
        static_tboxflags[0] = 0b0000_1000;

        let within_block = (chestflag % 32) as usize;
        let bit_shift = within_block % 8;
        let flat_byte_offset = scene_index as usize * 4 + within_block / 8;
        let mut bit = (tboxflags[flat_byte_offset] >> bit_shift) & 1;
        assert_eq!(bit, 0, "not committed yet, so the FA copy alone shouldn't see it");

        if bit == 0 && scene_index == current_scene_index {
            let static_byte_offset = within_block / 8;
            bit |= (static_tboxflags[static_byte_offset] >> bit_shift) & 1;
        }
        assert_eq!(bit, 1, "the static/working-copy buffer should catch it instantly");

        // Sanity: a chest in a DIFFERENT scene must not be affected by
        // this scene's static buffer.
        let other_scene_index: u16 = 6;
        let mut other_bit = (tboxflags[other_scene_index as usize * 4] >> bit_shift) & 1;
        if other_bit == 0 && other_scene_index == current_scene_index {
            other_bit |= (static_tboxflags[0] >> bit_shift) & 1;
        }
        assert_eq!(other_bit, 0);
    }
}
