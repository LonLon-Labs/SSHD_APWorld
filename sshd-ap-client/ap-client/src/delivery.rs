//! Crash-safe delivery of received items into the game's `item_buffer`.
//!
//! # The problem this solves
//! The game only "keeps" a delivered item once the save file containing it
//! is written, and SSHD autosaves on stage transitions. Before this module
//! the client remembered its position in the received-item list in memory
//! only, and counted an item as delivered the moment it was written into the
//! buffer. So after a crash + autosave reload (or a client restart) it
//! started again from item 0 and re-gave everything, including the half the
//! save already had.
//!
//! # How it works now (mirrors `SSHDClient.py`'s "safe" delivery index)
//! - `safe_index`: every received-item index below it is known to be in the
//!   save file. It is persisted in Archipelago DataStorage under
//!   `sshd_rs_{seed}_{slot}_delivery_index` and loaded on connect. Nothing is
//!   delivered until that load succeeds (falling back to 0 on a failed load
//!   is exactly what re-gave everything).
//! - Each item written to the buffer remembers which slot it went to. When
//!   the game empties the slot, that item is *consumed* (in the game, but not
//!   necessarily saved yet).
//! - A stage load autosaves, so everything that was consumed at least
//!   `SAFE_AGE` before the load began becomes safe and `safe_index` advances +
//!   is persisted. A "stage load" is either a stage-name change OR Link
//!   vanishing from the world for a moment and coming back. The second case is
//!   what a same-stage reload (Left Stick + R + Y, which forces an autosave)
//!   looks like: the stage name never changes, so those reloads used to be
//!   missed and `safe_index` stayed stuck (e.g. at 47), which is why a restart
//!   after a crash re-gave every item. The advance is only *confirmed* once
//!   Link has been back in the world for `CONFIRM_DELAY`, so a crash in the
//!   middle of a load never counts as saved.
//! - If the save is unloaded (title screen / soft reset) or the emulator is
//!   re-attached, unsaved items are gone from the game: delivery rewinds to
//!   `safe_index` and any leftover buffer slots are cleared, so only the
//!   missing items are given again.
//! - Only `MAX_IN_FLIGHT` items sit in the buffer at once, so a crash or
//!   reload never happens with hundreds of items queued in the game.
//!
//! Limitation: if only the *client* is restarted while the game keeps
//! running, items the game consumed since its last autosave are given again
//! (the client can't know the game still has them). Use
//! `/set_delivery_index <n>` to correct that if it matters.
//!
//! NOTE: like the rest of this workspace, not compiled where it was written.

use std::collections::{HashMap, HashSet, VecDeque};
use std::time::{Duration, Instant};

use ap_ipc::{offsets, ApPlayerVitals, ARCHIPELAGO_BUFFER_SIZE};
use archipelago_rs::{Client, ReceivedItem};
use process_memory::{MemError, ProcessMemory};

use crate::items;
use crate::locations::SlotData;

/// Max items sitting in the game's buffer, unconsumed, at any moment.
pub const MAX_IN_FLIGHT: usize = 8;
/// An item consumed less than this long before a stage load began is not
/// trusted to have made it into that load's autosave.
const SAFE_AGE: Duration = Duration::from_secs(3);
/// After a stage load, Link must be back in the world this long before the
/// autosave is trusted (a crash mid-load must not count as saved).
const CONFIRM_DELAY: Duration = Duration::from_secs(2);
/// Link must be missing from the world at least this long for it to count as
/// a stage load (filters out one-frame blips that are not a real load).
const MIN_LOAD_GAP: Duration = Duration::from_millis(300);
const LOAD_TIMEOUT: Duration = Duration::from_secs(15);
const LOAD_RETRY: Duration = Duration::from_secs(3);
const STALL_NOTICE: Duration = Duration::from_secs(10);
const SLOT_SIZE: usize = std::mem::size_of::<ap_ipc::ArchipelagoItemSlot>();

type GetRx = oneshot::Receiver<Result<HashMap<String, serde_json::Value>, archipelago_rs::Error>>;

enum Load {
    Idle,
    Pending { rx: GetRx, since: Instant },
    RetryAt(Instant),
    Ready,
}

/// One line for the caller to log. `gui` lines go to the GUI panel too;
/// the rest are terminal-only (like `vlog!`).
pub struct Line {
    pub gui:  bool,
    pub text: String,
}

#[derive(Default)]
pub struct Tick {
    pub logs:    Vec<Line>,
    /// New safe index to write to DataStorage (the caller does it: that needs
    /// the mutable client, which is borrowed while items are being read).
    pub persist: Option<usize>,
}

impl Tick {
    fn gui(&mut self, text: String) {
        self.logs.push(Line { gui: true, text });
    }
    fn verbose(&mut self, text: String) {
        self.logs.push(Line { gui: false, text });
    }
}

pub struct DeliveryTracker {
    key:  Option<String>,
    load: Load,
    /// All received indices below this are in the save file.
    safe_index: usize,
    /// Next received index to hand to the game.
    next_index: usize,
    /// buffer slot -> received index, for items written but not yet consumed.
    in_flight: HashMap<usize, usize>,
    /// (when, consumed-prefix): every index below the prefix had been
    /// consumed by `when`. The prefix only ever grows.
    prefix_history: VecDeque<(Instant, usize)>,
    /// Last NON-EMPTY stage name seen.
    last_stage: [u8; 8],
    last_save_loaded: bool,
    /// Was Link present in the world (PLAYER_PTR non-null) last tick?
    last_player_valid: bool,
    /// When Link most recently disappeared from the world (a load in progress).
    invalid_since: Option<Instant>,
    /// Start of the earliest stage load whose autosave we haven't confirmed yet.
    pending_load: Option<Instant>,
    /// Since when Link has been continuously back in the world after that load.
    stable_since: Option<Instant>,
    /// One-shot message for the next tick (set when the game was lost).
    notice: Option<String>,
    needs_buffer_clear: bool,
    last_progress: Instant,
    stall_logged: bool,
    /// Locations whose item the game hands out itself when they are checked
    /// (decoupled Goddess Cubes). Own-world items from these are never queued,
    /// or they would arrive a second time when the server echoes them back.
    native_locations: HashSet<i64>,
    /// This client's own slot number, to tell own-world items from other players'.
    own_slot: i64,
}

impl DeliveryTracker {
    pub fn new() -> Self {
        DeliveryTracker {
            key: None,
            load: Load::Idle,
            safe_index: 0,
            next_index: 0,
            in_flight: HashMap::new(),
            prefix_history: VecDeque::new(),
            last_stage: [0; 8],
            last_save_loaded: false,
            last_player_valid: false,
            invalid_since: None,
            pending_load: None,
            stable_since: None,
            notice: None,
            needs_buffer_clear: true,
            last_progress: Instant::now(),
            stall_logged: false,
            native_locations: HashSet::new(),
            own_slot: -1,
        }
    }

    /// Declare the locations the game gives items for natively, plus our own
    /// slot. Kept across rewinds; reset by creating a new tracker per connection.
    pub fn set_native_locations(&mut self, locations: HashSet<i64>, own_slot: i64) {
        self.native_locations = locations;
        self.own_slot = own_slot;
    }

    pub fn is_ready(&self) -> bool {
        matches!(self.load, Load::Ready)
    }

    pub fn safe_index(&self) -> usize {
        self.safe_index
    }

    pub fn next_index(&self) -> usize {
        self.next_index
    }

    pub fn in_flight_count(&self) -> usize {
        self.in_flight.len()
    }

    /// Called on every `Event::Connected`: forget local state and request the
    /// stored safe index from the server.
    pub fn begin(&mut self, client: &mut Client<SlotData>) {
        *self = DeliveryTracker::new();
        let key = format!("sshd_rs_{}_{}_delivery_index", client.seed_name(), client.this_player().name());
        let rx = client.get([key.clone()]);
        self.key = Some(key);
        self.load = Load::Pending { rx, since: Instant::now() };
    }

    /// Drives the DataStorage load. Returns a message worth logging, if any.
    pub fn poll_load(&mut self, client: &mut Client<SlotData>) -> Option<Line> {
        let key = self.key.clone()?;
        match std::mem::replace(&mut self.load, Load::Idle) {
            Load::Idle => {
                let rx = client.get([key]);
                self.load = Load::Pending { rx, since: Instant::now() };
                None
            },
            Load::RetryAt(when) => {
                if Instant::now() >= when {
                    let rx = client.get([key]);
                    self.load = Load::Pending { rx, since: Instant::now() };
                } else {
                    self.load = Load::RetryAt(when);
                }
                None
            },
            Load::Pending { rx, since } => match rx.try_recv() {
                Ok(Ok(map)) => {
                    let stored = map.get(&key).and_then(|v| v.as_u64()).unwrap_or(0) as usize;
                    self.safe_index = stored;
                    self.next_index = stored;
                    self.load = Load::Ready;
                    self.needs_buffer_clear = true;
                    Some(Line {
                        gui:  true,
                        text: format!(
                            "[Delivery] Items 0..{stored} are already in your save; delivery resumes at item #{stored}."
                        ),
                    })
                },
                Ok(Err(e)) => {
                    self.load = Load::RetryAt(Instant::now() + LOAD_RETRY);
                    Some(Line {
                        gui:  true,
                        text: format!("[Delivery] Couldn't read stored delivery index ({e}); retrying..."),
                    })
                },
                Err(oneshot::TryRecvError::Empty) => {
                    if since.elapsed() > LOAD_TIMEOUT {
                        self.load = Load::RetryAt(Instant::now());
                        Some(Line {
                            gui:  true,
                            text: "[Delivery] Timed out reading stored delivery index; retrying...".into(),
                        })
                    } else {
                        self.load = Load::Pending { rx, since };
                        None
                    }
                },
                Err(oneshot::TryRecvError::Disconnected) => {
                    self.load = Load::RetryAt(Instant::now() + LOAD_RETRY);
                    None
                },
            },
            Load::Ready => {
                self.load = Load::Ready;
                None
            },
        }
    }

    /// Writes `value` to DataStorage as the new safe index.
    pub fn persist(&self, client: &mut Client<SlotData>, value: usize) -> Result<(), archipelago_rs::Error> {
        match &self.key {
            Some(key) => client.set(key.clone(), serde_json::json!(value), false),
            None => Ok(()),
        }
    }

    /// The game this tracker was watching is gone or replaced (emulator
    /// (re)attached): unsaved items are lost, so start over from the safe index.
    pub fn game_lost(&mut self) {
        let unsaved = self.next_index.saturating_sub(self.safe_index);
        if self.is_ready() && unsaved > 0 {
            self.notice = Some(format!(
                "[Delivery] The game went away with {unsaved} item(s) not confirmed in a save. Items 0..{} \
                 are confirmed saved; delivery will resume from item #{} once the game is back and a save is loaded. \
                 (If your autosave already had more than that, use /set_delivery_index <n> to skip ahead.)",
                self.safe_index, self.safe_index
            ));
        }
        self.rewind();
    }

    /// Manually set the delivery position. The caller must persist the
    /// returned value.
    pub fn set_index(&mut self, index: usize) -> usize {
        self.safe_index = index;
        self.rewind();
        index
    }

    fn rewind(&mut self) {
        self.next_index = self.safe_index;
        self.in_flight.clear();
        self.prefix_history.clear();
        self.last_stage = [0; 8];
        self.last_save_loaded = false;
        self.last_player_valid = false;
        self.invalid_since = None;
        self.pending_load = None;
        self.stable_since = None;
        self.needs_buffer_clear = true;
        self.last_progress = Instant::now();
        self.stall_logged = false;
    }

    /// A stage load whose autosave is now trusted (Link has been back in the
    /// world for `CONFIRM_DELAY`): everything consumed at least `SAFE_AGE`
    /// before the load *began* is in the save.
    fn confirm_load(&mut self, began: Instant, out: &mut Tick) {
        self.pending_load = None;
        self.stable_since = None;
        let safe = self
            .prefix_history
            .iter()
            .rev()
            .find(|&&(t, _)| began.saturating_duration_since(t) >= SAFE_AGE)
            .map(|&(_, p)| p);
        if let Some(p) = safe {
            if p > self.safe_index {
                out.gui(format!("[Delivery] Stage (re)loaded and autosaved: items 0..{p} are now safe."));
                self.safe_index = p;
                out.persist = Some(p);
            }
        }
        while self.prefix_history.len() > 1
            && began.saturating_duration_since(self.prefix_history[1].0) >= SAFE_AGE
        {
            self.prefix_history.pop_front();
        }
    }

    /// Advances delivery by one poll tick.
    pub fn tick(&mut self, mem: &mut impl ProcessMemory, root_addr: usize, received: &[ReceivedItem]) -> Tick {
        let mut out = Tick::default();
        if !self.is_ready() {
            return out;
        }
        if let Err(e) = self.tick_inner(mem, root_addr, received, &mut out) {
            out.verbose(format!("[Delivery] memory error: {e}"));
        }
        out
    }

    fn tick_inner(
        &mut self,
        mem: &mut impl ProcessMemory,
        root_addr: usize,
        received: &[ReceivedItem],
        out: &mut Tick,
    ) -> Result<(), MemError> {
        let now = Instant::now();
        let buffer_addr = root_addr + offsets::ITEM_BUFFER;

        if let Some(text) = self.notice.take() {
            out.gui(text);
        }

        let vitals_raw = mem.read_bytes(root_addr + offsets::PLAYER_VITALS, std::mem::size_of::<ApPlayerVitals>())?;
        let vitals: ApPlayerVitals = ap_ipc::bytes::read(&vitals_raw);
        let save_loaded = vitals.save_loaded != 0;

        // Save unloaded (title screen / soft reset / reload from disk):
        // everything consumed since the last autosave is gone from the game.
        if self.last_save_loaded && !save_loaded {
            let unsaved = self.next_index.saturating_sub(self.safe_index);
            self.rewind();
            if unsaved > 0 {
                out.gui(format!(
                    "[Delivery] Save unloaded; {unsaved} item(s) since the last autosave will be re-delivered from item #{}.",
                    self.safe_index
                ));
            }
        }
        self.last_save_loaded = save_loaded;

        let mut buffer = mem.read_bytes(buffer_addr, ARCHIPELAGO_BUFFER_SIZE * SLOT_SIZE)?;

        // Clear leftovers (previous client session / a rewind). Slot 0 is a
        // reserved sentinel and is never touched.
        if self.needs_buffer_clear {
            let leftover = (1..ARCHIPELAGO_BUFFER_SIZE).filter(|&i| buffer[i * SLOT_SIZE] != 0).count();
            if leftover > 0 {
                mem.write_bytes(buffer_addr + SLOT_SIZE, &vec![0u8; (ARCHIPELAGO_BUFFER_SIZE - 1) * SLOT_SIZE])?;
                for b in &mut buffer[SLOT_SIZE..] {
                    *b = 0;
                }
                out.verbose(format!("[Delivery] Cleared {leftover} leftover item slot(s) from the game buffer."));
            }
            self.needs_buffer_clear = false;
        }

        // Which in-flight items has the game consumed?
        let before = self.in_flight.len();
        self.in_flight.retain(|&slot, _| buffer[slot * SLOT_SIZE] != 0);
        if self.in_flight.len() != before {
            self.last_progress = now;
            self.stall_logged = false;
        }
        let prefix = self.in_flight.values().copied().min().unwrap_or(self.next_index);
        if self.prefix_history.back().map(|&(_, p)| p) != Some(prefix) {
            self.prefix_history.push_back((now, prefix));
        }

        // Stage load => autosave => sufficiently old consumed items are safe.
        // A load shows up as (a) the stage name changing and/or (b) Link
        // vanishing from the world for a moment and coming back. (b) is the
        // ONLY signal a same-stage reload (Left Stick + R + Y) gives: the
        // name stays the same, which is why those reloads used to be missed.
        let player_valid = vitals.player_valid != 0;
        let stage_raw = mem.read_bytes(root_addr + offsets::CURRENT_STAGE_NAME, 8)?;
        let mut stage = [0u8; 8];
        stage.copy_from_slice(&stage_raw);

        let mut load_began: Option<Instant> = None;
        if stage[0] != 0 && stage != self.last_stage && self.last_stage[0] != 0 {
            load_began = Some(now);
        }
        if save_loaded {
            if self.last_player_valid && !player_valid {
                self.invalid_since.get_or_insert(now);
            }
            if player_valid {
                if let Some(gone_at) = self.invalid_since.take() {
                    if now.duration_since(gone_at) >= MIN_LOAD_GAP {
                        load_began = Some(load_began.map_or(gone_at, |t| t.min(gone_at)));
                    }
                }
            }
        } else {
            self.invalid_since = None;
        }
        if stage[0] != 0 {
            self.last_stage = stage;
        }
        self.last_player_valid = player_valid;

        if let Some(began) = load_began {
            // Keep the EARLIEST unconfirmed load: it is the conservative one.
            self.pending_load = Some(self.pending_load.map_or(began, |t| t.min(began)));
            self.stable_since = None;
        }
        if let Some(began) = self.pending_load {
            if player_valid && save_loaded && stage[0] != 0 {
                let since = *self.stable_since.get_or_insert(now);
                if now.duration_since(since) >= CONFIRM_DELAY {
                    self.confirm_load(began, out);
                }
            } else {
                self.stable_since = None;
            }
        }

        // Nothing is delivered while no save is loaded (it would be lost).
        if !save_loaded {
            return Ok(());
        }

        // Feed the buffer, a few items at a time.
        while self.in_flight.len() < MAX_IN_FLIGHT && self.next_index < received.len() {
            let index = self.next_index;
            let item = &received[index];

            // Start-inventory items are baked into the save already.
            if item.location().id() == -2 {
                out.verbose(format!(
                    "[AP] Received item #{index}: {} → start-inventory item, already in save file, skipping delivery",
                    item.item()
                ));
                self.next_index += 1;
                continue;
            }

            // Own-world items from locations the game already gave natively
            // (decoupled Goddess Cubes play the item-get animation themselves).
            if self.native_locations.contains(&item.location().id())
                && item.sender().slot() as i64 == self.own_slot
            {
                out.verbose(format!(
                    "[AP] Received item #{index}: {} → given natively by the game at its location, skipping delivery",
                    item.item()
                ));
                self.next_index += 1;
                continue;
            }

            let ap_code = item.item().id();
            // Progressive items the game can't tier on its own (Progressive
            // Loftwing: Loftwing -> Spiral Charge) are resolved here from how
            // many copies were received before this one. Start-inventory
            // copies count too: they are already in the save as earlier tiers.
            let prior_copies = if ap_code == items::PROGRESSIVE_LOFTWING_CODE {
                received[..index].iter().filter(|r| r.item().id() == ap_code).count()
            } else {
                0
            };
            let Some(original_id) = items::progressive_tier_original_id(ap_code, prior_copies) else {
                out.verbose(format!(
                    "[AP] Received item #{index}: {} → event-only or unknown AP code {ap_code}, not deliverable via item_buffer",
                    item.item()
                ));
                self.next_index += 1;
                continue;
            };

            let Some(slot) = (1..ARCHIPELAGO_BUFFER_SIZE).find(|&i| buffer[i * SLOT_SIZE] == 0) else {
                break; // buffer full; can't happen with MAX_IN_FLIGHT, but be safe
            };
            let raw = ap_ipc::bytes::write(&ap_ipc::ArchipelagoItemSlot {
                item_id:    (original_id & 0xFF) as u8,
                flags:      0,
                _reserved:  0,
                item_id_hi: (original_id >> 8) as u8,
            });
            mem.write_bytes(buffer_addr + slot * SLOT_SIZE, &raw)?;
            // Byte 0 is the "pending" marker; original_id is never 0 mod 256
            // (items::original_id_for_ap_code rejects 256).
            buffer[slot * SLOT_SIZE] = (original_id & 0xFF) as u8;
            if self.in_flight.is_empty() {
                self.last_progress = now;
                self.stall_logged = false;
            }
            self.in_flight.insert(slot, index);
            out.verbose(format!(
                "[AP] Received item #{index}: {} → queued (game item id {original_id})",
                item.item()
            ));
            self.next_index += 1;
        }

        // The game only hands out a limited batch of items per stage load.
        if !self.in_flight.is_empty() && !self.stall_logged && self.last_progress.elapsed() > STALL_NOTICE {
            self.stall_logged = true;
            let waiting = self.in_flight.len() + received.len().saturating_sub(self.next_index);
            out.gui(format!(
                "[Delivery] {waiting} item(s) are waiting for the game (it hands out a limited batch per \
                 stage). Walk through a door / change stage (or reload with Left Stick + R + Y) to receive more."
            ));
        }
        Ok(())
    }
}
