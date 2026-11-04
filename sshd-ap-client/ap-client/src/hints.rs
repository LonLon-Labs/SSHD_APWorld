//! Hint logic that doesn't depend on the Archipelago connection or the game:
//! the Fi Notes order, the random gossip-stone pick, and the hint-point check.
//!
//! Which notes exist is stored in the save: one custom flag per progression or
//! useful location (see `SlotData::note_flags`). This module only remembers the
//! order this session hinted them in, so the newest note is shown first.

use std::collections::HashSet;
use std::time::{SystemTime, UNIX_EPOCH};

use crate::locations::HintPoolEntry;

/// One Fi note: a progression or useful location in your world, and the save
/// flag that records it.
#[derive(Debug, Clone, serde::Deserialize)]
pub struct NoteFlag {
    pub flag_id: u16,
    pub location_id: i64,
    pub location: String,
    pub item: String,
    pub receiver: String,
}

/// Fi Notes ordering and the visit state for the current session.
///
/// `order` holds location IDs oldest first, as this session hinted them. Notes
/// set before this session (after a reload) have no entry and follow in flag
/// order. `served` holds the notes this visit has already served, so each note
/// is served at most once per visit and a repeated request can't loop.
#[derive(Debug, Default, Clone)]
pub struct FiNotes {
    order: Vec<i64>,
    served: HashSet<i64>,
}

impl FiNotes {
    pub fn new() -> Self {
        Self::default()
    }

    /// Records that `location_id` was hinted this session. A repeat moves it to
    /// the newest position.
    pub fn record(&mut self, location_id: i64) {
        self.order.retain(|&id| id != location_id);
        self.order.push(location_id);
    }

    /// Starts a new visit: nothing has been served yet.
    pub fn start_visit(&mut self) {
        self.served.clear();
    }

    /// Returns the index into `notes` (newest first) of the first note this visit
    /// hasn't served, and marks it served. `None` once every note has been served.
    pub fn take_next(&mut self, notes: &[NoteFlag]) -> Option<usize> {
        let index = notes.iter().position(|n| !self.served.contains(&n.location_id))?;
        self.served.insert(notes[index].location_id);
        Some(index)
    }

    /// Whether any note in `notes` is still unserved this visit. Used to set the
    /// "more notes follow" flag (see worker.rs `serve_fi_note`).
    pub fn has_unserved(&self, notes: &[NoteFlag]) -> bool {
        notes.iter().any(|n| !self.served.contains(&n.location_id))
    }

    /// Orders `notes` newest first. Notes hinted this session come first, newest
    /// first; the rest follow in the order given.
    pub fn ordered<'a>(&self, notes: &'a [NoteFlag]) -> Vec<&'a NoteFlag> {
        let mut out: Vec<&NoteFlag> = notes.iter().collect();
        out.sort_by_key(|note| match self.order.iter().rposition(|&id| id == note.location_id) {
            Some(pos) => (0usize, usize::MAX - pos),
            None => (1usize, 0usize),
        });
        out
    }
}

/// Picks a random hint candidate that is not in `excluded` (locations that
/// are already checked or already hinted this session). Returns `None` when
/// nothing is left, which the stone reports as "no more hints available".
///
/// `seed` only varies the choice; the caller passes something that changes
/// between talks (see `fresh_seed`) so repeated talks don't return the same
/// hint. A simple xorshift is enough here, so no RNG crate is needed.
pub fn pick_hint<'a>(
    pool: &'a [HintPoolEntry],
    excluded: &HashSet<i64>,
    seed: u64,
) -> Option<&'a HintPoolEntry> {
    let available: Vec<&HintPoolEntry> = pool
        .iter()
        .filter(|entry| !excluded.contains(&entry.location_id))
        .collect();
    if available.is_empty() {
        return None;
    }
    let index = (xorshift64(seed) % available.len() as u64) as usize;
    Some(available[index])
}

/// Whether the player can afford one hint. The balance must be at least the
/// cost, which matches the server's rule.
pub fn can_afford(balance: i64, points_per_hint: u64) -> bool {
    balance >= points_per_hint as i64
}

/// Seed for `pick_hint`: the clock mixed with a counter, so two talks in the
/// same nanosecond still differ.
pub fn fresh_seed(counter: u64) -> u64 {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos() as u64)
        .unwrap_or(0);
    nanos ^ counter.wrapping_mul(0x9E37_79B9_7F4A_7C15)
}

fn xorshift64(mut x: u64) -> u64 {
    // Zero is a fixed point for xorshift, so avoid it.
    if x == 0 {
        x = 0x2545_F491_4F6C_DD1D;
    }
    x ^= x << 13;
    x ^= x >> 7;
    x ^= x << 17;
    x
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entry(id: i64) -> HintPoolEntry {
        HintPoolEntry {
            player: format!("P{id}"),
            player_id: 1,
            location: format!("Loc {id}"),
            location_id: id,
        }
    }

    fn note(id: i64) -> NoteFlag {
        NoteFlag {
            flag_id: id as u16,
            location_id: id,
            location: String::new(),
            item: String::new(),
            receiver: String::new(),
        }
    }

    #[test]
    fn fi_notes_newest_session_hints_first() {
        let mut notes = FiNotes::new();
        notes.record(10);
        notes.record(20);
        notes.record(10); // hinted again: now the newest
        let flagged = [note(5), note(10), note(20), note(30)];
        let ids: Vec<i64> = notes.ordered(&flagged).iter().map(|n| n.location_id).collect();
        assert_eq!(ids, vec![10, 20, 5, 30]);
    }

    #[test]
    fn fi_notes_each_note_served_once_per_visit() {
        let mut notes = FiNotes::new();
        let list = [note(1), note(2)];
        assert_eq!(notes.take_next(&list), Some(0));
        assert_eq!(notes.take_next(&list), Some(1));
        assert_eq!(notes.take_next(&list), None);
        notes.start_visit();
        assert_eq!(notes.take_next(&list), Some(0));
    }

    #[test]
    fn pick_hint_skips_excluded_and_runs_out() {
        let pool = vec![entry(1), entry(2), entry(3)];
        let excluded: HashSet<i64> = [1, 2].into_iter().collect();
        for seed in 0..50u64 {
            let picked = pick_hint(&pool, &excluded, seed).expect("one left");
            assert_eq!(picked.location_id, 3);
        }
        let all: HashSet<i64> = [1, 2, 3].into_iter().collect();
        assert!(pick_hint(&pool, &all, 7).is_none());
        assert!(pick_hint(&[], &HashSet::new(), 7).is_none());
    }

    #[test]
    fn pick_hint_varies_with_seed() {
        let pool: Vec<HintPoolEntry> = (1..=20).map(entry).collect();
        let none = HashSet::new();
        let picks: HashSet<i64> = (0..40u64)
            .map(|s| pick_hint(&pool, &none, s).unwrap().location_id)
            .collect();
        assert!(picks.len() > 5, "seeds should spread picks across the pool");
    }

    #[test]
    fn xorshift_never_sticks_at_zero() {
        assert_ne!(xorshift64(0), 0);
        assert_ne!(xorshift64(xorshift64(0)), 0);
    }

    #[test]
    fn affordability_matches_server_rule() {
        assert!(can_afford(5, 5));
        assert!(can_afford(6, 5));
        assert!(!can_afford(4, 5));
        assert!(can_afford(0, 0));
        assert!(!can_afford(-1, 0), "hint debt must not count as affordable");
    }
}
