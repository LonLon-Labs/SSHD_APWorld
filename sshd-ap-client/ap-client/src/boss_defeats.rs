//! Boss defeat location-check detection.
//!
//! Ported from `SSHDClient.py`'s `check_boss_defeat_flags`. Unlike the
//! custom-flag mechanism, these are ordinary vanilla sceneflags at fixed,
//! known (scene, byte, bit) triples — a static table, no slot_data needed.
//! Reuses the same `AP_IPC_ROOT.sceneflags` live copy that `locations.rs`
//! already reads for custom flags.
//!
//! No transition tracking needed here (matching the Python client): once
//! set, a flag stays set for the rest of the file, so a plain "is it set"
//! check together with `checked_locations`/`sent_locations` bookkeeping
//! upstream is enough — no false-positive risk from re-triggering.
//!
//! NOTE: Demise's defeat is intentionally not covered by this table (see
//! the Python client's comment) — it's tracked via a stage transition
//! elsewhere, not ported here.

use ap_ipc::offsets;
use process_memory::{MemError, ProcessMemory};

/// (ap_location_code, scene_index, sceneflag_number)
///
/// The flag number is the HeartCo actor's params1 bits 8-15. Scene flags are
/// stored as little-endian u16 words (flag >> 4 picks the word, flag & 0xF the
/// bit), so the byte/mask is derived in `flag_byte_and_mask`. The old table
/// had the byte index swapped (XOR 1) for every boss, so this fallback never
/// fired; Earth Temple (0x38, scene 14) and Ancient Cistern (0x4D, scene 12)
/// were confirmed in game with `/flag sceneflag get`.
const BOSS_DEFEAT_FLAGS: &[(i64, usize, u16)] = &[
    (2773700, 11, 0x66), // Skyview Temple - Defeat Boss
    (2773729, 14, 0x38), // Earth Temple - Defeat Boss
    (2773774, 17, 0x7E), // Lanayru Mining Facility - Defeat Boss
    (2773798, 12, 0x4D), // Ancient Cistern - Defeat Boss
    (2773818, 18, 0x55), // Sandship - Defeat Boss
    (2773848, 15, 0x7C), // Fire Sanctuary - Defeat Boss
];

/// Byte offset within a scene's 16 flag bytes, and bit mask, for a scene flag
/// number in the game's little-endian u16 layout.
fn flag_byte_and_mask(flag: u16) -> (usize, u8) {
    let byte = ((flag >> 4) as usize) * 2 + ((flag >> 3) & 1) as usize;
    (byte, 1u8 << (flag & 7))
}

const SCENEFLAGS_BYTES: usize = 26 * 8 * 2; // [[u16; 8]; 26], read as raw bytes

/// Every AP location code this module can report. Used by the check-count
/// reporting so these locations are included in the in-game totals.
pub fn location_codes() -> impl Iterator<Item = i64> {
    BOSS_DEFEAT_FLAGS.iter().map(|&(code, ..)| code)
}

/// Returns AP location codes for any boss(es) newly detected as defeated.
/// `already_checked` should be the caller's set of location codes already
/// known-checked (e.g. from `sent_locations`/`checked_locations`
/// upstream) so this doesn't re-report every poll — this module has no
/// internal state of its own, matching the Python client's stateless
/// "just check if it's set" approach for these six locations.
pub fn poll(
    mem: &mut impl ProcessMemory,
    root_addr: usize,
    already_checked: impl Fn(i64) -> bool,
) -> Result<Vec<i64>, MemError> {
    let sceneflags = mem.read_bytes(root_addr + offsets::SCENEFLAGS, SCENEFLAGS_BYTES)?;

    let mut newly_checked = Vec::new();
    for &(loc_code, scene_idx, flag) in BOSS_DEFEAT_FLAGS {
        if already_checked(loc_code) {
            continue;
        }
        let (byte_off, mask) = flag_byte_and_mask(flag);
        let flat_offset = scene_idx * 16 + byte_off;
        if flat_offset >= sceneflags.len() {
            continue;
        }
        if sceneflags[flat_offset] & mask != 0 {
            newly_checked.push(loc_code);
        }
    }
    Ok(newly_checked)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn table_has_six_unique_locations() {
        let mut codes: Vec<i64> = BOSS_DEFEAT_FLAGS.iter().map(|&(c, ..)| c).collect();
        codes.sort();
        codes.dedup();
        assert_eq!(codes.len(), 6);
        assert_eq!(BOSS_DEFEAT_FLAGS.len(), 6);
    }

    #[test]
    fn flag_byte_and_mask_is_little_endian_u16() {
        assert_eq!(flag_byte_and_mask(0x38), (0x7, 0x01)); // Earth Temple
        assert_eq!(flag_byte_and_mask(0x4D), (0x9, 0x20)); // Ancient Cistern
        assert_eq!(flag_byte_and_mask(0x66), (0xC, 0x40)); // Skyview
        assert_eq!(flag_byte_and_mask(0x7C), (0xF, 0x10)); // Fire Sanctuary
    }

    #[test]
    fn location_codes_lists_every_boss() {
        assert_eq!(location_codes().count(), BOSS_DEFEAT_FLAGS.len());
        assert!(location_codes().any(|c| c == 2773700));
    }
}
