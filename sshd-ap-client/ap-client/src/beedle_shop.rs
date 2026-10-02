//! Beedle's Airshop purchase detection.
//!
//! Ported from `SSHDClient.py`'s `check_beedle_shop_storyflags`. These
//! storyflags can't be decoded by reading raw bytes — some nearby flag IDs
//! are multi-bit counters rather than plain booleans, and only
//! `rust-additions`' own `flag.rs` knows which is which — so this asks the
//! game via a `flag_request` (STORYFLAG, GET) round trip instead of
//! computing an offset locally, using the shared `flag_request_get` helper
//! in `main.rs` (the same mechanism `commands.rs::handle_flag_request`
//! implements on the game side).
//!
//! # Stage gate
//! These storyflags can only be trusted while the player is actually
//! standing in Beedle's Airshop (stage `F002r`) — `AP_IPC_ROOT.current_
//! stage_name` (mirrored from the game's `CURRENT_STAGE_NAME`) is what the
//! Python client's `current_stage` used to gate on; reading them from
//! anywhere else has produced false "already purchased" detections (see
//! the mailbox's own docs on why some of these flag IDs can't be trusted
//! from just anywhere). So this poller does nothing at all — no reads, no
//! reports, not even on its very first call — unless the player is
//! currently in the shop, and a location is only ever reported when its
//! flag is OBSERVED to flip from 0 to 1 while standing there. A purchase
//! made before this client connected (or while it wasn't running) is
//! simply picked up the next time the player happens to be in the shop —
//! it establishes a 1-baseline then, without reporting it as a fresh
//! check.

use std::time::{Duration, Instant};

use ap_ipc::{offsets, FLAG_TYPE_STORYFLAG, SCENE_INDEX_CURRENT};
use process_memory::{MemError, ProcessMemory};

use crate::flag_request_get;

/// Beedle's Airshop's stage code, ASCII, matching how
/// `AP_IPC_ROOT.current_stage_name` is null-padded to 8 bytes.
const BEEDLE_AIRSHOP_STAGE: &[u8] = b"F002r\0\0\0";

/// storyflag_num -> AP location code. Built from `SOLD_OUT_STORYFLAGS`
/// (shop index -> storyflag_num) joined with `SHOP_INDEX_TO_LOCATION`
/// (shop index -> location name) joined with `LOCATION_TABLE` (location
/// name -> code) in the Python client; the two intermediate tables are
/// small and static, so the joined result is just hardcoded here.
///
/// IMPORTANT: the first element of each tuple is the real storyflag
/// number (`SOLD_OUT_STORYFLAGS`'s *value*), NOT the shop index
/// (`SOLD_OUT_STORYFLAGS`'s *key*, which is what `SHOP_INDEX_TO_LOCATION`
/// and the comments below key off of). An earlier version of this table
/// mixed the two up and hardcoded the shop index (20-29) here instead --
/// since those low numbers happen to be real (but unrelated) storyflags
/// that never flip while shopping, every `flag_request_get` below always
/// came back 0 and no Beedle's Airshop purchase was ever detected.
pub const BEEDLE_STORYFLAG_TO_LOCATION: &[(u16, i64)] = &[
    (942, 2773113), // 300 Rupee Item (shop index 20)
    (943, 2773114), // 600 Rupee Item (shop index 21)
    (944, 2773115), // 1200 Rupee Item (shop index 22)
    (814, 2773116), // 800 Rupee Item (shop index 26)
    (813, 2773117), // 1600 Rupee Item (shop index 23)
    (937, 2773118), // First 100 Rupee Item (shop index 24)
    (938, 2773119), // Second 100 Rupee Item (shop index 28)
    (939, 2773120), // Third 100 Rupee Item (shop index 29)
    (940, 2773121), // 50 Rupee Item (shop index 25)
    (941, 2773122), // 1000 Rupee Item (shop index 27)
];

const POLL_INTERVAL: Duration = Duration::from_secs(3);

pub struct BeedleShopPoller {
    previous:  std::collections::HashMap<u16, u8>,
    last_poll: Option<Instant>,
}

impl BeedleShopPoller {
    pub fn new() -> Self {
        BeedleShopPoller { previous: std::collections::HashMap::new(), last_poll: None }
    }

    /// Returns newly-checked AP location codes. Does nothing at all unless
    /// the player is currently standing in Beedle's Airshop -- a location is
    /// only ever reported when its flag is observed to flip from 0 to 1
    /// while in the shop. A flag that's already 1 the first time it's
    /// observed (e.g. purchased in an earlier session) just establishes the
    /// baseline; it is NOT reported, since nothing changed while we were
    /// watching.
    pub fn poll(
        &mut self,
        mem: &mut impl ProcessMemory,
        root_addr: usize,
        already_checked: impl Fn(i64) -> bool,
    ) -> Result<Vec<i64>, MemError> {
        let stage_name = mem.read_bytes(root_addr + offsets::CURRENT_STAGE_NAME, 8)?;
        let in_shop = stage_name == BEEDLE_AIRSHOP_STAGE;
        if !in_shop {
            return Ok(Vec::new());
        }
        if let Some(last) = self.last_poll {
            if last.elapsed() < POLL_INTERVAL {
                return Ok(Vec::new());
            }
        }
        self.last_poll = Some(Instant::now());

        let mut newly_checked = Vec::new();
        for &(storyflag_num, location_code) in BEEDLE_STORYFLAG_TO_LOCATION {
            if already_checked(location_code) {
                continue;
            }

            let value = flag_request_get(
                mem,
                root_addr,
                FLAG_TYPE_STORYFLAG,
                storyflag_num,
                SCENE_INDEX_CURRENT,
            )?;
            let bit = if value != 0 { 1u8 } else { 0u8 };

            if let Some(0) = self.previous.insert(storyflag_num, bit) {
                if bit == 1 {
                    newly_checked.push(location_code);
                }
            }
        }

        Ok(newly_checked)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn table_has_ten_unique_storyflags_and_locations() {
        let mut flags: Vec<u16> = BEEDLE_STORYFLAG_TO_LOCATION.iter().map(|&(f, _)| f).collect();
        let mut codes: Vec<i64> = BEEDLE_STORYFLAG_TO_LOCATION.iter().map(|&(_, c)| c).collect();
        flags.sort();
        flags.dedup();
        codes.sort();
        codes.dedup();
        assert_eq!(flags.len(), 10);
        assert_eq!(codes.len(), 10);
        assert_eq!(BEEDLE_STORYFLAG_TO_LOCATION.len(), 10);
    }
}
