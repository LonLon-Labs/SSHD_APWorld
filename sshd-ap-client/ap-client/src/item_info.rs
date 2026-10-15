//! Writes the AP item-info table (item name + owning player, keyed by
//! custom-flag id) into `AP_IPC_ROOT.item_info_table`, ported from
//! `SSHDClient.py`'s `_write_ap_item_info_table`.
//!
//! This is what lets the game show "You found a(n) Green Rupee for
//! ShipOfHarkinianPlayer!" for a location whose item belongs to another
//! player, instead of the generic "Archipelago Item" / "another player"
//! placeholder. Without this, `item_info_table` keeps every entry at its
//! all-zero/`0xFFFF`-sentinel default forever (nothing else populates
//! it), so the game always falls back to the generic text.
//!
//! Call `write_item_info_table` once per connection, right after
//! `Event::Connected` (same timing as `cheat_sync::apply_cheat_flags`) --
//! both `main.rs`'s `run_headless` and `worker.rs` call this so the two
//! don't drift.
//!
//! Two more helpers cover what the Python client did continuously:
//! - `verify_item_info_table` reads the table back out of game memory and
//!   reports how many expected entries are actually there (including the
//!   Beedle's Airshop ones, whose keys have bit 15 set) -- lets us tell
//!   "the data never reached the game" apart from "the game never looked
//!   it up".
//! - `refresh_item_info_table` is the Python client's every-~5-seconds
//!   `_refresh_ap_item_info_count`: it re-writes the table's `count`
//!   field so a stale-zero copy can't linger, and does a full re-write if
//!   the count in the game doesn't match what we expect.
//!
//! # Write ordering
//! Entries are written BEFORE the table's `count` field, matching the
//! Python client exactly: the game's lookup only scans `entries[0..count]`,
//! so writing entries first (while `count` is still whatever it was
//! before -- 0, on a fresh connection) guarantees the game can never
//! observe a non-zero count paired with still-empty/sentinel entries.
//!
//! # Entry order
//! The table holds at most `AP_ITEM_TABLE_MAX` (512) entries. Entries are
//! written in a deterministic order -- Beedle's Airshop entries (bit 15
//! set) first, then ascending flag id -- so if a huge seed ever exceeds the
//! cap, what gets dropped is predictable (highest custom flags) rather
//! than depending on `HashMap` iteration order.

use std::collections::HashMap;

use ap_ipc::offsets;
use process_memory::{MemError, ProcessMemory};

use crate::locations::ApItemInfo;

/// Flag ids with this bit set are Beedle's Airshop entries
/// (`0x8000 | sold_out_storyflag`), matching `__init__.py` and
/// `shop.rs::handle_shop_traps`.
pub const BEEDLE_FLAG_BIT: u16 = 0x8000;

/// Encodes `s` as UTF-16, truncated to fit `N` `u16`s with room left over
/// for a trailing null, and null-pads the rest -- mirrors the Python
/// client's `.encode('utf-16-le')[:...].ljust(..., b'\x00')`. The result
/// is always null-terminated as long as `s` doesn't need every slot.
fn encode_utf16_fixed<const N: usize>(s: &str) -> [u16; N] {
    let mut buf = [0u16; N];
    for (slot, unit) in buf.iter_mut().zip(s.encode_utf16()).take(N - 1) {
        *slot = unit;
    }
    buf
}

/// Decodes a null-terminated (or full) UTF-16 buffer back to a `String`.
fn decode_utf16_fixed(buf: &[u16]) -> String {
    let end = buf.iter().position(|&u| u == 0).unwrap_or(buf.len());
    String::from_utf16_lossy(&buf[..end])
}

/// Writes every `(flag_id -> item/player name)` entry from `item_info`
/// (i.e. `SlotData::ap_item_info`) into `AP_IPC_ROOT.item_info_table`,
/// then the table's `count` field last (see module doc). Returns the
/// number of entries written, capped at `ap_ipc::AP_ITEM_TABLE_MAX` (512)
/// -- same cap the table itself has.
pub fn write_item_info_table(
    mem: &mut impl ProcessMemory,
    root_addr: usize,
    item_info: &HashMap<u16, ApItemInfo>,
) -> Result<usize, MemError> {
    let table_addr = root_addr + offsets::ITEM_INFO_TABLE;
    let entry_size = std::mem::size_of::<ap_ipc::ApItemInfoEntry>();
    // Entries start after magic[4] + count(u16) + _pad(u16) = 8 bytes.
    let entries_addr = table_addr + 8;

    // Beedle entries first, then ascending flag id (see module doc).
    let mut sorted: Vec<(&u16, &ApItemInfo)> = item_info.iter().collect();
    sorted.sort_by_key(|(id, _)| (**id & BEEDLE_FLAG_BIT == 0, **id));

    let count = sorted.len().min(ap_ipc::AP_ITEM_TABLE_MAX);
    for (i, (&flag_id, info)) in sorted.into_iter().take(count).enumerate() {
        let entry = ap_ipc::ApItemInfoEntry {
            flag_id,
            item_name: encode_utf16_fixed(&info.item),
            player_name: encode_utf16_fixed(&info.player),
        };
        mem.write_bytes(entries_addr + i * entry_size, &ap_ipc::bytes::write(&entry))?;
    }

    // Count last -- see module doc for why the order matters.
    mem.write_bytes(table_addr + 4, &(count as u16).to_le_bytes())?;

    Ok(count)
}

/// What `verify_item_info_table` found in game memory.
#[derive(Debug, Clone)]
pub struct VerifyReport {
    /// The `count` field as currently stored in the game.
    pub count_in_game:    u16,
    /// How many entries we expect (`item_info.len()`, capped at 512).
    pub expected:         usize,
    /// Expected entries present in the game with the right item name.
    pub matched:          usize,
    /// How many of the expected entries are Beedle's Airshop ones.
    pub beedle_expected:  usize,
    /// How many of those are present in the game with the right item name.
    pub beedle_matched:   usize,
    /// Up to 5 expected flag ids that were missing or mismatched.
    pub missing_sample:   Vec<u16>,
}

/// Reads the table back out of game memory and compares it against
/// `item_info`. Read-only.
pub fn verify_item_info_table(
    mem: &mut impl ProcessMemory,
    root_addr: usize,
    item_info: &HashMap<u16, ApItemInfo>,
) -> Result<VerifyReport, MemError> {
    let table_addr = root_addr + offsets::ITEM_INFO_TABLE;
    let entry_size = std::mem::size_of::<ap_ipc::ApItemInfoEntry>();

    let count_raw = mem.read_bytes(table_addr + 4, 2)?;
    let count_in_game = u16::from_le_bytes([count_raw[0], count_raw[1]]);
    let n = (count_in_game as usize).min(ap_ipc::AP_ITEM_TABLE_MAX);

    let mut in_game: HashMap<u16, String> = HashMap::new();
    if n > 0 {
        let raw = mem.read_bytes(table_addr + 8, n * entry_size)?;
        for chunk in raw.chunks_exact(entry_size) {
            let entry: ap_ipc::ApItemInfoEntry = ap_ipc::bytes::read(chunk);
            // Copy out of the packed struct before touching the fields.
            let flag_id = entry.flag_id;
            let name = entry.item_name;
            in_game.insert(flag_id, decode_utf16_fixed(&name));
        }
    }

    let mut report = VerifyReport {
        count_in_game,
        expected: item_info.len().min(ap_ipc::AP_ITEM_TABLE_MAX),
        matched: 0,
        beedle_expected: 0,
        beedle_matched: 0,
        missing_sample: Vec::new(),
    };

    let mut ids: Vec<&u16> = item_info.keys().collect();
    ids.sort();
    for &flag_id in ids {
        let is_beedle = flag_id & BEEDLE_FLAG_BIT != 0;
        if is_beedle {
            report.beedle_expected += 1;
        }
        let want = decode_utf16_fixed(&encode_utf16_fixed::<32>(&item_info[&flag_id].item));
        if in_game.get(&flag_id) == Some(&want) {
            report.matched += 1;
            if is_beedle {
                report.beedle_matched += 1;
            }
        } else if report.missing_sample.len() < 5 {
            report.missing_sample.push(flag_id);
        }
    }

    Ok(report)
}

/// The Python client's periodic `_refresh_ap_item_info_count`. Re-writes
/// the table's `count` field; if the count currently in the game doesn't
/// match what we expect, re-writes the whole table instead. Returns
/// `true` if a full re-write happened.
pub fn refresh_item_info_table(
    mem: &mut impl ProcessMemory,
    root_addr: usize,
    item_info: &HashMap<u16, ApItemInfo>,
) -> Result<bool, MemError> {
    let table_addr = root_addr + offsets::ITEM_INFO_TABLE;
    let expected = item_info.len().min(ap_ipc::AP_ITEM_TABLE_MAX);

    let count_raw = mem.read_bytes(table_addr + 4, 2)?;
    let in_game = u16::from_le_bytes([count_raw[0], count_raw[1]]) as usize;

    if in_game != expected {
        write_item_info_table(mem, root_addr, item_info)?;
        return Ok(true);
    }

    mem.write_bytes(table_addr + 4, &(expected as u16).to_le_bytes())?;
    Ok(false)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn encode_utf16_fixed_truncates_and_leaves_room_for_null() {
        // "hello" is 5 units; into a 4-slot buffer, only 3 fit (N - 1),
        // and the last slot stays 0 as the null terminator.
        let buf: [u16; 4] = encode_utf16_fixed("hello");
        assert_eq!(buf, [b'h' as u16, b'e' as u16, b'l' as u16, 0]);
    }

    #[test]
    fn encode_utf16_fixed_null_pads_short_strings() {
        let buf: [u16; 4] = encode_utf16_fixed("hi");
        assert_eq!(buf, [b'h' as u16, b'i' as u16, 0, 0]);
    }

    #[test]
    fn decode_round_trips_encode() {
        let buf: [u16; 32] = encode_utf16_fixed("Green Rupee");
        assert_eq!(decode_utf16_fixed(&buf), "Green Rupee");
    }

    #[test]
    fn beedle_entries_sort_before_custom_flags() {
        let mut ids = vec![5u16, 0x8000 | 942, 261, 0x8000 | 813];
        ids.sort_by_key(|id| (*id & BEEDLE_FLAG_BIT == 0, *id));
        assert_eq!(ids, vec![0x8000 | 813, 0x8000 | 942, 5, 261]);
    }

    #[test]
    fn entry_and_table_sizes_match_ap_ipc_layout() {
        // Guards the `+ 8` / `entry_size` arithmetic above against
        // silently drifting if ap-ipc's struct layout ever changes.
        assert_eq!(std::mem::size_of::<ap_ipc::ApItemInfoEntry>(), 98);
    }
}
