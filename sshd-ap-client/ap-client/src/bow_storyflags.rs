//! Keeps the Progressive Bow storyflags in line with the bow item flags.
//!
//! The randomizer's `003-ItemGet` event flow picks the bow textbox from three
//! storyflags, not from the item flags:
//!
//! | tier        | item flag (given) | storyflag (textbox) |
//! |-------------|-------------------|---------------------|
//! | Bow         | 19                | 957                 |
//! | Iron Bow    | 90                | 945                 |
//! | Sacred Bow  | 91                | 946                 |
//!
//! Buffer delivery (this client) never sets those storyflags, so a save with a
//! stale storyflag (or one written by any other path) shows "Iron Bow" for a
//! first bow even though the item is the Bow. Storyflag 954 is NOT used here:
//! the randomizer sets it when Fi's required-dungeons text is shown
//! (eventpatches.yaml, 006-8KenseiNormal), so the bow tiers use 957, which no
//! vanilla or randomizer code uses. The bow item flags are cumulative
//! (owning Sacred also sets 19 and 90), so each storyflag is simply "is the
//! matching item flag set?". This module reads all six flags and writes only
//! the ones that disagree.
//!
//! Runs from the worker loop while a save for this seed is loaded, at most
//! once per `CHECK_INTERVAL`. The first check happens as soon as the save
//! becomes usable, so a stale storyflag is cleared before a bow can be
//! delivered into that save.

use std::time::{Duration, Instant};

use ap_ipc::{FLAG_OP_GET, FLAG_OP_SET, FLAG_OP_UNSET, FLAG_TYPE_ITEMFLAG, FLAG_TYPE_STORYFLAG, SCENE_INDEX_CURRENT};
use process_memory::{MemError, ProcessMemory};

use crate::ipc_requests;

/// (item flag, textbox storyflag) for Bow, Iron Bow and Sacred Bow.
const BOW_TIERS: [(u16, u16); 3] = [
    (19, 957), // Bow
    (90, 945), // Iron Bow
    (91, 946), // Sacred Bow
];

/// How often the flags are re-checked while a save is loaded.
const CHECK_INTERVAL: Duration = Duration::from_secs(2);

/// Throttle for `reconcile`. Owned by the worker's per-connection state.
pub struct BowStoryflagSync {
    next_check: Instant,
}

impl BowStoryflagSync {
    pub fn new() -> Self {
        BowStoryflagSync { next_check: Instant::now() }
    }

    /// Call every poll tick while the loaded save belongs to this seed.
    /// Does nothing until `CHECK_INTERVAL` has passed since the last check.
    /// Returns a log line when at least one storyflag was changed.
    pub fn poll(&mut self, mem: &mut impl ProcessMemory, root_addr: usize) -> Result<Option<String>, MemError> {
        let now = Instant::now();
        if now < self.next_check {
            return Ok(None);
        }
        self.next_check = now + CHECK_INTERVAL;
        reconcile(mem, root_addr)
    }
}

/// Reads the bow item flags and textbox storyflags and writes any storyflag
/// that disagrees with its item flag. Returns a summary line if anything
/// changed. Returns `Err` if a flag round trip to the game times out, in which
/// case the caller should just try again on the next interval.
pub fn reconcile(mem: &mut impl ProcessMemory, root_addr: usize) -> Result<Option<String>, MemError> {
    let mut changes: Vec<String> = Vec::new();

    for &(item_flag, story_flag) in BOW_TIERS.iter() {
        let owned = read_flag(mem, root_addr, FLAG_TYPE_ITEMFLAG, item_flag)? != 0;
        let story_set = read_flag(mem, root_addr, FLAG_TYPE_STORYFLAG, story_flag)? != 0;

        if owned == story_set {
            continue;
        }

        let op = if owned { FLAG_OP_SET } else { FLAG_OP_UNSET };
        ipc_requests::flag_request(mem, root_addr, FLAG_TYPE_STORYFLAG, op, story_flag, 0, SCENE_INDEX_CURRENT)?;
        changes.push(format!(
            "storyflag {story_flag} {} (bow item flag {item_flag} is {})",
            if owned { "set" } else { "cleared" },
            if owned { "set" } else { "clear" },
        ));
    }

    if changes.is_empty() {
        Ok(None)
    } else {
        Ok(Some(format!("[BowFlags] Fixed textbox flags: {}.", changes.join("; "))))
    }
}

fn read_flag(mem: &mut impl ProcessMemory, root_addr: usize, flag_type: u8, flag_id: u16) -> Result<u32, MemError> {
    ipc_requests::flag_request(mem, root_addr, flag_type, FLAG_OP_GET, flag_id, 0, SCENE_INDEX_CURRENT)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tiers_match_the_randomizer_tables() {
        // ITEM_ITEMFLAGS[PROGRESSIVE_BOW] and ITEM_STORYFLAGS[PROGRESSIVE_BOW]
        // in sshd-rando-backend/constants/itemconstants.py.
        assert_eq!(BOW_TIERS, [(19, 957), (90, 945), (91, 946)]);
    }
}
