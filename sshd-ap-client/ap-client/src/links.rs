//! DeathLink / BreathLink support.
//!
//! # Sending
//! `LinkMonitor::poll` watches the live player vitals the game mirrors into
//! `AP_IPC_ROOT.player_vitals` every frame (health from the save file,
//! stamina from the player struct) and reports a `LinkSignal` on the frame
//! either value drops from above 0 to exactly 0. The caller then sends the
//! Bounce packet (`Client::death_link` / `Client::bounce`).
//!
//! Each signal fires exactly ONCE per event: it is latched until the value
//! goes back above 0 (respawn / stamina regenerating), so sitting at 0 for
//! many frames never re-sends.
//!
//! False positives are filtered the same way `SSHDClient.py` did:
//! - nothing fires during the first 10 s after connecting,
//! - nothing fires while no save is loaded or health capacity reads 0
//!   (the save area is zeroed on save-and-quit, dropping health AND stamina
//!   to 0 without a real death),
//! - stamina readings are ignored while Link doesn't exist and for a short
//!   settle window after a stage change (the stamina offset differs per
//!   stage, so the first reads after a load can be garbage).
//!
//! # Not echoing
//! When a link is RECEIVED we ask the game to kill Link / drain stamina
//! (`request_kill` / `request_drain`). That causes a 1 -> 0 edge which must
//! not be sent back out as a new link, so `note_kill_requested` /
//! `note_drain_requested` arm a one-shot suppression that swallows exactly
//! that next edge (and expires after `SUPPRESS_WINDOW` in case the game
//! never acted on the request, so a later REAL death isn't swallowed).
//! Received links whose source is our own name, or that arrive right after
//! we sent one, are ignored outright.

use std::time::{Duration, Instant};

use ap_ipc::offsets;
use process_memory::{MemError, ProcessMemory};

/// No link is ever sent this soon after connecting.
const CONNECT_GRACE: Duration = Duration::from_secs(10);
/// Ignore stamina edges this long after a stage change.
const STAGE_SETTLE: Duration = Duration::from_millis(1500);
/// How long a one-shot echo suppression stays armed.
const SUPPRESS_WINDOW: Duration = Duration::from_secs(10);
/// Received links this soon after we sent one are treated as our own echo.
const SENT_ECHO_WINDOW: Duration = Duration::from_secs(3);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LinkSignal {
    /// Health just dropped to 0.
    Death,
    /// Stamina just dropped to 0.
    Breath,
}

pub struct LinkMonitor {
    connected_at:         Instant,
    last_health:          Option<u16>,
    last_stamina:         Option<u32>,
    death_latched:        bool,
    breath_latched:       bool,
    suppress_death_until: Option<Instant>,
    suppress_breath_until: Option<Instant>,
    last_stage:           [u8; 8],
    stage_settle_until:   Option<Instant>,
    last_sent_death:      Option<Instant>,
    last_sent_breath:     Option<Instant>,
    /// Current stage code (e.g. "F000"), for cause text.
    pub stage_code:       String,
}

impl LinkMonitor {
    pub fn new() -> Self {
        LinkMonitor {
            connected_at:          Instant::now(),
            last_health:           None,
            last_stamina:          None,
            death_latched:         false,
            breath_latched:        false,
            suppress_death_until:  None,
            suppress_breath_until: None,
            last_stage:            [0; 8],
            stage_settle_until:    None,
            last_sent_death:       None,
            last_sent_breath:      None,
            stage_code:            String::new(),
        }
    }

    /// Call right after a DeathLink is actually sent.
    pub fn note_death_sent(&mut self) {
        self.last_sent_death = Some(Instant::now());
    }

    /// Call right after a BreathLink is actually sent.
    pub fn note_breath_sent(&mut self) {
        self.last_sent_breath = Some(Instant::now());
    }

    /// True if we sent a DeathLink moments ago (a received one is our echo).
    pub fn death_sent_recently(&self) -> bool {
        self.last_sent_death.is_some_and(|t| t.elapsed() < SENT_ECHO_WINDOW)
    }

    /// True if we sent a BreathLink moments ago (a received one is our echo).
    pub fn breath_sent_recently(&self) -> bool {
        self.last_sent_breath.is_some_and(|t| t.elapsed() < SENT_ECHO_WINDOW)
    }

    /// Call after asking the game to kill Link for a received DeathLink.
    /// Only arms suppression if Link is currently alive (otherwise no 1 -> 0
    /// edge will follow and the flag would just linger).
    pub fn note_kill_requested(&mut self) {
        if self.last_health.is_some_and(|h| h > 0) {
            self.suppress_death_until = Some(Instant::now() + SUPPRESS_WINDOW);
        }
    }

    /// Call after asking the game to drain stamina for a received BreathLink.
    pub fn note_drain_requested(&mut self) {
        if self.last_stamina.is_some_and(|s| s > 0) {
            self.suppress_breath_until = Some(Instant::now() + SUPPRESS_WINDOW);
        }
    }

    /// Reads the vitals and returns any signals that should be SENT this
    /// tick (already filtered for grace period, latching and echo
    /// suppression).
    pub fn poll(
        &mut self,
        mem: &mut impl ProcessMemory,
        root_addr: usize,
    ) -> Result<Vec<LinkSignal>, MemError> {
        let raw = mem.read_bytes(
            root_addr + offsets::PLAYER_VITALS,
            std::mem::size_of::<ap_ipc::ApPlayerVitals>(),
        )?;
        let vitals: ap_ipc::ApPlayerVitals = ap_ipc::bytes::read(&raw);
        let stage_raw = mem.read_bytes(root_addr + offsets::CURRENT_STAGE_NAME, 8)?;
        let mut stage = [0u8; 8];
        stage.copy_from_slice(&stage_raw);

        // Copy packed fields to locals before using them.
        let health = vitals.current_health;
        let capacity = vitals.health_capacity;
        let stamina = vitals.stamina;
        let save_loaded = vitals.save_loaded != 0;
        let player_valid = vitals.player_valid != 0;

        if stage != self.last_stage {
            self.last_stage = stage;
            self.last_stamina = None;
            self.stage_settle_until = Some(Instant::now() + STAGE_SETTLE);
            self.stage_code = stage.iter().take_while(|&&b| b != 0).map(|&b| b as char).collect();
        }

        let mut signals = Vec::new();

        // Save unloaded (title screen, save-and-quit, memory cleared): forget
        // everything so the reload isn't seen as a death/exhaustion.
        if !save_loaded || capacity == 0 {
            self.last_health = None;
            self.last_stamina = None;
            return Ok(signals);
        }

        let in_grace = self.connected_at.elapsed() < CONNECT_GRACE;
        let now = Instant::now();

        // ── Death ────────────────────────────────────────────────────
        if health == 0 {
            let fell = self.last_health.is_some_and(|h| h > 0);
            if fell && !self.death_latched {
                self.death_latched = true;
                let suppressed = self.suppress_death_until.take().is_some_and(|t| now < t);
                if !in_grace && !suppressed {
                    signals.push(LinkSignal::Death);
                }
            }
        } else {
            self.death_latched = false;
        }
        self.last_health = Some(health);

        // ── Stamina exhaustion ───────────────────────────────────────
        let settling = self.stage_settle_until.is_some_and(|t| now < t);
        if !player_valid || settling {
            // Link doesn't exist yet / stage is still loading: the value is
            // meaningless. Start fresh once it settles.
            self.last_stamina = None;
        } else {
            if stamina == 0 {
                let fell = self.last_stamina.is_some_and(|s| s > 0);
                if fell && !self.breath_latched {
                    self.breath_latched = true;
                    let suppressed = self.suppress_breath_until.take().is_some_and(|t| now < t);
                    // Dying also zeroes nothing here, but a dead Link
                    // shouldn't also broadcast exhaustion.
                    if !in_grace && !suppressed && health > 0 {
                        signals.push(LinkSignal::Breath);
                    }
                }
            } else {
                self.breath_latched = false;
            }
            self.last_stamina = Some(stamina);
        }

        Ok(signals)
    }
}

/// Asks the game to kill Link (sets `link_requests.kill_request`).
pub fn request_kill(mem: &mut impl ProcessMemory, root_addr: usize) -> Result<(), MemError> {
    mem.write_bytes(root_addr + offsets::LINK_REQUESTS, &[1u8])
}

/// Asks the game to drain Link's stamina (sets
/// `link_requests.drain_stamina_request`).
pub fn request_drain(mem: &mut impl ProcessMemory, root_addr: usize) -> Result<(), MemError> {
    mem.write_bytes(root_addr + offsets::LINK_REQUESTS + 1, &[1u8])
}

/// Friendly stage name for cause text, falling back to the raw code.
pub fn stage_display_name(code: &str) -> String {
    if code.is_empty() {
        return "Skyloft".to_string();
    }
    crate::stages::STAGE_NAMES
        .iter()
        .find(|(c, _)| *c == code)
        .map(|(_, name)| name.to_string())
        .unwrap_or_else(|| code.to_string())
}
