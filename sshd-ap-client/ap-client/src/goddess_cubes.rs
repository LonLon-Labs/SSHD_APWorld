//! Goddess cube location-check detection (decoupled goddess cubes only).
//!
//! Ported from `SSHDClient.py`'s `check_goddess_cube_flags`. When the
//! `decouple_goddess_cubes_and_chests` option is on, each goddess cube is
//! its own AP location that holds a randomized item. Striking a cube with
//! a Skyward Strike sets that cube's *vanilla* storyflag (227-256; the
//! apworld sends the mapping as `goddess_cube_story_flags` in slot_data),
//! so a location is checked as soon as its storyflag reads back as set.
//!
//! # How flags are read
//! Like `beedle_shop.rs`, this asks the game via a `flag_request`
//! (STORYFLAG, GET) round trip rather than computing a byte offset locally,
//! so the game's own `flag.rs` decides where the flag lives (saved copy and
//! runtime copy alike). No stage gate is needed: cube storyflags are plain
//! persistent booleans, so they can be trusted from anywhere as long as a
//! save file is loaded.
//!
//! # Semantics
//! A flag that is already set counts as checked, on the very first poll and
//! every poll after. That recovers cubes struck while the client wasn't
//! running or connected, matching the Python client (and the "recover on
//! first poll" behaviour of `CustomFlagPoller`). The caller's
//! `already_checked` filter keeps locations the server already knows about
//! from being re-reported.
//!
//! # Throttling
//! Every `flag_request` blocks the worker for at least one game frame, so
//! reading all 27 cubes every tick would stall it. Instead each `poll()`
//! call (itself rate-limited to `POLL_INTERVAL`) checks only the next
//! `BATCH_SIZE` not-yet-checked cubes, walking round-robin through them.
//! Cubes that have been detected are never read again.

use std::collections::{HashMap, HashSet};
use std::time::{Duration, Instant};

use ap_ipc::{offsets, FLAG_TYPE_STORYFLAG, SCENE_INDEX_CURRENT};
use process_memory::{MemError, ProcessMemory};

use crate::flag_request_get;

/// Minimum time between batches.
const POLL_INTERVAL: Duration = Duration::from_millis(500);
/// Cubes read per batch (one `flag_request` round trip each).
const BATCH_SIZE: usize = 6;

/// Offset of `ApPlayerVitals.save_loaded` within `AP_IPC_ROOT`: it follows
/// `current_health: u16`, `health_capacity: u16` and `stamina: u32`.
const SAVE_LOADED_OFFSET: usize = offsets::PLAYER_VITALS + 2 + 2 + 4;

pub struct GoddessCubePoller {
    /// AP location code -> storyflag id, sorted by location code so the
    /// round-robin order is stable.
    flags:       Vec<(i64, u16)>,
    /// Location codes already detected as struck; never read again.
    detected:    HashSet<i64>,
    /// Round-robin position into `flags`.
    cursor:      usize,
    last_poll:   Option<Instant>,
}

impl GoddessCubePoller {
    pub fn new(flags: HashMap<i64, u16>) -> Self {
        let mut flags: Vec<(i64, u16)> = flags.into_iter().collect();
        flags.sort_unstable();
        GoddessCubePoller { flags, detected: HashSet::new(), cursor: 0, last_poll: None }
    }

    pub fn location_count(&self) -> usize {
        self.flags.len()
    }

    /// Returns newly-checked AP location codes. Does nothing unless a save
    /// file is loaded (the game's flag manager isn't valid before that).
    pub fn poll(
        &mut self,
        mem: &mut impl ProcessMemory,
        root_addr: usize,
        already_checked: &impl Fn(i64) -> bool,
    ) -> Result<Vec<i64>, MemError> {
        if self.flags.is_empty() {
            return Ok(Vec::new());
        }
        if let Some(last) = self.last_poll {
            if last.elapsed() < POLL_INTERVAL {
                return Ok(Vec::new());
            }
        }

        let save_loaded = mem.read_bytes(root_addr + SAVE_LOADED_OFFSET, 1)?;
        if save_loaded.first().copied().unwrap_or(0) == 0 {
            return Ok(Vec::new());
        }
        self.last_poll = Some(Instant::now());

        self.poll_batch(already_checked, |storyflag| {
            let value = flag_request_get(mem, root_addr, FLAG_TYPE_STORYFLAG, storyflag, SCENE_INDEX_CURRENT)?;
            Ok(value != 0)
        })
    }

    /// The batching/bookkeeping half of `poll()`, split out so it can be
    /// tested without a real process: `read_flag` answers "is this
    /// storyflag set?".
    fn poll_batch(
        &mut self,
        already_checked: &impl Fn(i64) -> bool,
        mut read_flag: impl FnMut(u16) -> Result<bool, MemError>,
    ) -> Result<Vec<i64>, MemError> {
        let mut newly_checked = Vec::new();
        let total = self.flags.len();
        let mut examined = 0;
        let mut visited = 0;

        // Walk at most one full lap, reading up to BATCH_SIZE unchecked cubes.
        while visited < total && examined < BATCH_SIZE {
            let (location_code, storyflag) = self.flags[self.cursor];
            self.cursor = (self.cursor + 1) % total;
            visited += 1;

            if self.detected.contains(&location_code) {
                continue;
            }
            if already_checked(location_code) {
                // The server (or another poller) already has this one.
                self.detected.insert(location_code);
                continue;
            }

            examined += 1;
            if read_flag(storyflag)? {
                self.detected.insert(location_code);
                newly_checked.push(location_code);
            }
        }

        Ok(newly_checked)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn poller(pairs: &[(i64, u16)]) -> GoddessCubePoller {
        GoddessCubePoller::new(pairs.iter().copied().collect())
    }

    #[test]
    fn set_flag_is_reported_once() {
        let mut p = poller(&[(100, 227), (101, 228)]);
        let never = |_: i64| false;

        let first = p.poll_batch(&never, |flag| Ok(flag == 228)).unwrap();
        assert_eq!(first, vec![101]);

        // The flag is still set on the next batch, but the location was
        // already reported: it must not be read or reported again.
        let mut reads = Vec::new();
        let second = p
            .poll_batch(&never, |flag| {
                reads.push(flag);
                Ok(flag == 228)
            })
            .unwrap();
        assert!(second.is_empty());
        assert!(!reads.contains(&228), "detected cube must not be re-read");
    }

    #[test]
    fn nothing_reported_when_no_flag_set() {
        let mut p = poller(&[(100, 227), (101, 228)]);
        let out = p.poll_batch(&|_| false, |_| Ok(false)).unwrap();
        assert!(out.is_empty());
    }

    #[test]
    fn server_known_locations_are_skipped_without_reading() {
        let mut p = poller(&[(100, 227)]);
        let known = |code: i64| code == 100;
        let out = p.poll_batch(&known, |_| panic!("already-checked cube must not be read")).unwrap();
        assert!(out.is_empty());
    }

    #[test]
    fn batches_walk_round_robin_through_all_cubes() {
        // 27 cubes, only the last one is struck: it must be found within
        // ceil(27 / BATCH_SIZE) batches.
        let pairs: Vec<(i64, u16)> = (0..27).map(|i| (1000 + i as i64, 227 + i as u16)).collect();
        let mut p = poller(&pairs);
        let last_flag = 227 + 26;
        let mut found = Vec::new();
        for _ in 0..(27 / BATCH_SIZE + 1) {
            found.extend(p.poll_batch(&|_| false, |f| Ok(f == last_flag)).unwrap());
        }
        assert_eq!(found, vec![1026]);
    }

    #[test]
    fn empty_poller_reports_nothing() {
        let mut p = poller(&[]);
        assert_eq!(p.location_count(), 0);
        assert!(p.poll_batch(&|_| false, |_| Ok(true)).unwrap().is_empty());
    }
}
