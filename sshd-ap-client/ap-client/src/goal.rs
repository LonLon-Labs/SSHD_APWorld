//! Goal (victory) detection.
//!
//! The old Python client detected the goal from stage transitions
//! (B400 -> F404 etc.), which breaks when cutscenes are skipped. This polls
//! a storyflag instead:
//! - Goal 0 (Defeat Demise): `DEMISE_DEFEATED_STORYFLAG`, an otherwise unused
//!   storyflag that rust-additions sets the moment BLastBoss (B400) enters
//!   its "End" (death) state (`flag.rs::demise_defeated_hook`).
//! - Goal 1 (Defeat Ghirahim 3): vanilla storyflag 486.
//! - Goal 2 (Defeat Horde): vanilla storyflag 134.
//!
//! Like `beedle_shop.rs` this asks the game via a `flag_request` GET, which
//! costs about a frame per call, so it's throttled.

use std::time::{Duration, Instant};

use ap_ipc::{FLAG_TYPE_STORYFLAG, SCENE_INDEX_CURRENT};
use process_memory::{MemError, ProcessMemory};

use crate::flag_request_get;

/// AP location code of the "goal" event location (same as SSHDClient.py's
/// `_GOAL_LOC_CODE`).
pub const GOAL_LOCATION_CODE: i64 = 2773238;

/// Set by the game when Demise is killed. MUST match `DEMISE_DEFEATED_STORYFLAG`
/// in rust-additions' flag.rs. Marked "Unused" in the flag spreadsheet; it sits
/// right after "Talking to Fi in Demise fight after dying" (783).
pub const DEMISE_DEFEATED_STORYFLAG: u16 = 784;

const GHIRAHIM_3_DEFEATED_STORYFLAG: u16 = 486;
const HORDE_DEFEATED_STORYFLAG: u16 = 134;

const POLL_INTERVAL: Duration = Duration::from_secs(1);

/// The storyflag that means "goal reached" for the slot's `option_goal`
/// (0 = Demise, 1 = Ghirahim 3, 2 = Horde; anything else behaves like 0).
pub fn goal_storyflag(goal_type: i64) -> u16 {
    match goal_type {
        1 => GHIRAHIM_3_DEFEATED_STORYFLAG,
        2 => HORDE_DEFEATED_STORYFLAG,
        _ => DEMISE_DEFEATED_STORYFLAG,
    }
}

pub fn goal_name(goal_type: i64) -> &'static str {
    match goal_type {
        1 => "Ghirahim 3",
        2 => "Horde",
        _ => "Demise",
    }
}

#[derive(Default)]
pub struct GoalPoller {
    last_poll: Option<Instant>,
}

impl GoalPoller {
    pub fn new() -> Self {
        GoalPoller { last_poll: None }
    }

    /// True when the goal storyflag is currently set. Throttled to one game
    /// round trip per `POLL_INTERVAL`; returns `false` in between.
    pub fn poll(
        &mut self,
        mem: &mut impl ProcessMemory,
        root_addr: usize,
        goal_type: i64,
    ) -> Result<bool, MemError> {
        if let Some(last) = self.last_poll {
            if last.elapsed() < POLL_INTERVAL {
                return Ok(false);
            }
        }
        self.last_poll = Some(Instant::now());
        let value = flag_request_get(
            mem,
            root_addr,
            FLAG_TYPE_STORYFLAG,
            goal_storyflag(goal_type),
            SCENE_INDEX_CURRENT,
        )?;
        Ok(value != 0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn goal_flag_per_goal_type() {
        assert_eq!(goal_storyflag(0), DEMISE_DEFEATED_STORYFLAG);
        assert_eq!(goal_storyflag(1), 486);
        assert_eq!(goal_storyflag(2), 134);
        assert_eq!(goal_storyflag(99), DEMISE_DEFEATED_STORYFLAG);
    }
}
