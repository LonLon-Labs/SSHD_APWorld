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
//! - On a stage transition the game autosaves, so everything that was
//!   consumed at least `SAFE_AGE` before the transition becomes safe and
//!   `safe_index` advances + is persisted.
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

use std::collections::{HashMap, VecDeque};
use std::time::{Duration, Instant};

use ap_ipc::{offsets, ApPlayerVitals, ARCHIPELAGO_BUFFER_SIZE};
use archipelago_rs::{Client, ReceivedItem};
use process_memory::{MemError, ProcessMemory};

use crate::items;
use crate::locations::SlotData;

/// Max items sitting in the game's buffer, unconsumed, at any moment.
pub const MAX_IN_FLIGHT: usize = 8;
/// An item consumed less than this long before a stage transition is not
/// trusted to have made it into that transition's autosave.
const SAFE_AGE: Duration = Duration::from_secs(5);
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
    needs_buffer_clear: bool,
    last_progress: Instant,
    stall_logged: bool,
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
            needs_buffer_clear: true,
            last_progress: Instant::now(),
            stall_logged: false,
        }
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
        self.needs_buffer_clear = true;
        self.last_progress = Instant::now();
        self.stall_logged = false;
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

        // Stage transition => autosave => sufficiently old consumed items are safe.
        let stage_raw = mem.read_bytes(root_addr + offsets::CURRENT_STAGE_NAME, 8)?;
        let mut stage = [0u8; 8];
        stage.copy_from_slice(&stage_raw);
        if stage[0] != 0 && stage != self.last_stage {
            if self.last_stage[0] != 0 {
                let safe = self
                    .prefix_history
                    .iter()
                    .rev()
                    .find(|&&(t, _)| now.duration_since(t) >= SAFE_AGE)
                    .map(|&(_, p)| p);
                if let Some(p) = safe {
                    if p > self.safe_index {
                        out.verbose(format!("[Delivery] Autosave on stage change: items 0..{p} are now safe."));
                        self.safe_index = p;
                        out.persist = Some(p);
                    }
                }
                while self.prefix_history.len() > 1 && now.duration_since(self.prefix_history[1].0) >= SAFE_AGE {
                    self.prefix_history.pop_front();
                }
            }
            self.last_stage = stage;
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

            let ap_code = item.item().id();
            let Some(original_id) = items::original_id_for_ap_code(ap_code) else {
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
                item_id:   original_id,
                flags:     0,
                _reserved: [0, 0],
            });
            mem.write_bytes(buffer_addr + slot * SLOT_SIZE, &raw)?;
            buffer[slot * SLOT_SIZE] = original_id;
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
                 stage). Walk through a door / change stage to receive more."
            ));
        }
        Ok(())
    }
}
