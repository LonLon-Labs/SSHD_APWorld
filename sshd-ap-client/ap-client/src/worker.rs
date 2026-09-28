//! Background worker that bridges the (blocking) emulator-attach /
//! AP_IPC-scan / Archipelago-connection loop to the Iced GUI.
//!
//! # Why the actual work runs on a `std::thread`, not the async task
//! `Subscription::run`/`iced::stream::channel` schedule their closure as
//! a task on Iced's async executor (smol-based here — see the
//! `async-executor`/`async-io` deps this workspace pulls in, not
//! tokio). An async task is expected to yield control via genuine
//! `.await` points; it is NOT expected to call `std::thread::sleep` or
//! any other blocking syscall, because doing so can leave the executor
//! stuck inside that one task's poll forever, unable to deliver
//! anything it already produced — which is exactly what happened the
//! first time this was written with the loop below living directly in
//! an `async fn`: the window rendered fine (rendering is independent),
//! but not even the very first, unconditional log line ever arrived.
//!
//! So the actual attach/scan/poll loop (`run_blocking`, below) is a
//! perfectly ordinary, fully synchronous function running on its own
//! `std::thread::spawn`'d thread, exactly as if this were the
//! `--headless` CLI. It talks to the async world through two channels:
//! commands in via a `futures::channel::mpsc::Receiver<WorkerInput>`
//! (`try_recv` is non-blocking and safe to poll from a plain thread, so
//! nothing changes there), and events out via an
//! `UnboundedSender<WorkerEvent>` (`unbounded_send` is a plain
//! synchronous, non-blocking call — safe from any thread, no executor
//! needed). The `subscription()` closure itself does nothing but
//! forward those events into `output.send(...).await`, which is the
//! only piece of this that actually needs to be async.
//!
//! # One persistent loop, two independent activities
//! Like Archipelago's own Python client, this does NOT wait for the
//! user to press Connect before it starts doing anything: emulator
//! discovery (find the process, attach, scan for `AP_IPC_ROOT`) starts
//! the instant the app launches and keeps retrying forever in the
//! background, completely independent of whether there's an
//! Archipelago server connection yet.
//!
//! The Archipelago server connection is the only thing gated behind a
//! `Connect` command (from the GUI's button, or from the `/connect`
//! command typed into the bar). It's otherwise independent of emulator
//! state — you could in principle be talking to the AP server before
//! the emulator is even found, though nothing gets delivered in-game
//! until it is.
//!
//! Item delivery, all four location-check mechanisms (`locations.rs`'s
//! custom flags, `goddess_chests.rs`, `beedle_shop.rs`,
//! `boss_defeats.rs`), and `check_stats` reporting only run once BOTH
//! sides are ready (emulator attached AND fully connected to the AP
//! server, i.e. `Event::Connected` seen) — this mirrors `main.rs`'s
//! `run_headless` poll loop exactly, just reporting through channel
//! sends instead of `println!`/`eprintln!`.
//!
//! # Command bar
//! `WorkerInput::Command` handles one line typed into the GUI's
//! persistent command bar. `/`-prefixed text is a local command
//! (a small subset of what `SSHDClientCommandProcessor` supports in the
//! Python client — see `handle_command`); anything else, `!`-prefixed
//! server commands included, is sent to the Archipelago server as a
//! chat message via `Client::say`, unmodified — the server, not this
//! client, is what interprets `!hint` and friends.
//!
//! NOTE: like the rest of this workspace (see README.md), this has not
//! been compiled anywhere with a GUI-capable target available, so build
//! it (`cargo build`) and fix whatever comes up before trusting it.
//!
//! # Two log destinations, mirroring the Python client
//! `SSHDClient.py` had a separate, more verbose console/log window
//! alongside its curated main GUI window. This client reproduces that
//! split using the plain terminal/console window this process already
//! opens on Windows alongside the GUI (it's a normal console-subsystem
//! binary):
//! - `log!` sends a `WorkerEvent::Log`, which both lands in the GUI's
//!   own scrolling log panel AND gets echoed to that terminal (see
//!   `gui.rs`'s `push_log`, the single place that echo happens). Use
//!   this for what a player actually wants to see without leaving the
//!   GUI: location checks found, Archipelago server chat/print (which
//!   covers `!hint` and other command replies), connect/disconnect
//!   status, and this app's own command-bar feedback (`handle_command`).
//! - `vlog!` prints straight to stdout — the terminal only, never the
//!   GUI panel. Use this for everything else: emulator discovery,
//!   AP_IPC_ROOT scanning, per-tick poll/IPC errors, item-buffer
//!   bookkeeping, slot_data mapping counts — detail a player doesn't
//!   need cluttering the GUI but that's still useful when troubleshooting
//!   from the terminal.
//! So the terminal ends up showing everything (curated + verbose), and
//! the GUI panel shows only the curated subset — same as before.

use std::collections::{HashMap, HashSet};
use std::thread;
use std::time::{Duration, Instant};

use ap_ipc::{offsets, AP_IPC_MAGIC, AP_IPC_SUPPORTED_VERSION};
use archipelago_rs::{BounceOptions, Connection, ConnectionOptions, DeathLinkOptions, Error, Event};
use iced::futures::channel::mpsc;
use iced::futures::{SinkExt, StreamExt};
use iced::stream;
use iced::Subscription;
use process_memory::{ProcessMemory, SUPPORTED_EMULATOR_NAMES};

#[cfg(target_os = "linux")]
use process_memory::linux::{find_process_by_names, LinuxProcessMemory as Backend};
#[cfg(target_os = "windows")]
use process_memory::windows::{find_process_by_names, WindowsProcessMemory as Backend};

use crate::actorid;
use crate::beedle_shop::BeedleShopPoller;
use crate::boss_defeats;
use crate::cheat_sync;
use crate::go_mode;
use crate::ipc_requests;
use crate::stages;
use crate::colors::{self, LogSpan};
use crate::delivery::{self, DeliveryTracker};
use crate::goddess_chests::GoddessChestPoller;
use crate::item_info;
use crate::items;
use crate::links::{self, LinkMonitor, LinkSignal};
use crate::locations::{ApItemInfo, CustomFlagPoller, SlotData};

/// Commands the GUI sends into the running worker thread.
#[derive(Debug, Clone)]
pub enum WorkerInput {
    Connect { server: String, slot: String, password: Option<String> },
    Disconnect,
    /// One line typed into the command bar, unmodified — see
    /// `handle_command` for how it's interpreted.
    Command(String),
    /// Drop the current emulator attachment and search again from scratch
    /// (`/rescan`). Only ever produced by `handle_command`.
    RescanEmulator,
}

/// Events the worker thread sends back out to the GUI.
#[derive(Debug, Clone)]
pub enum WorkerEvent {
    /// Sent exactly once, right after the stream starts. Carries the
    /// sender the GUI should hold onto and use for every subsequent
    /// `WorkerInput`.
    Ready(mpsc::Sender<WorkerInput>),
    /// A short, current-state line ("Looking for an emulator...",
    /// "Connected", "Error: ..."). Meant for a single status label.
    Status(String),
    /// A line for the scrolling log/console.
    Log(String),
    /// A server message (item sends, chat, hints, ...) as per-part colored
    /// spans. See `colors.rs`.
    Print(Vec<LogSpan>),
    /// Latest `check_stats` mailbox contents.
    Stats { checked: u16, total: u16 },
    /// The Archipelago connection reached `Event::Connected`.
    Connected,
    /// The AP connection ended (error, or the user hit Disconnect).
    Disconnected,
    /// Something went wrong with the AP connection.
    Error(String),
}

/// Where `run_blocking` (and everything it calls) sends events — a
/// plain, synchronous, thread-safe sender. No executor/async context
/// required to use it, which is the whole point.
type EventSink = mpsc::UnboundedSender<WorkerEvent>;

fn send(output: &EventSink, event: WorkerEvent) {
    let _ = output.unbounded_send(event);
}

macro_rules! log {
    ($output:expr, $($arg:tt)*) => {{ send($output, WorkerEvent::Log(format!($($arg)*))); }};
}

/// Console-only line: printed directly to stdout (this process's plain
/// terminal/console window) but never sent to the GUI's own curated log
/// panel — use for verbose/internal detail (emulator discovery, per-tick
/// poll diagnostics, item-buffer bookkeeping) that would just be noise
/// there. Safe to call from this thread directly (no channel/GUI needed)
/// since `println!` locks stdout internally and this is a plain OS
/// thread. See `gui.rs`'s `push_log` for where curated (`log!`) lines
/// get their own echo to the same terminal — together these two give
/// the terminal window everything, and the GUI panel only the curated
/// subset, mirroring the Python client's separate, more verbose console
/// window.
macro_rules! vlog {
    ($($arg:tt)*) => {{ println!($($arg)*); }};
}

/// Per-session state for the four location-check mechanisms plus item
/// delivery — everything that needs a full reset on each new `Connect`,
/// bundled so `start_connection` can reset it in one assignment instead
/// of a growing parameter list.
struct SyncState {
    /// Crash-safe item delivery position + in-flight tracking (see delivery.rs).
    delivery:             DeliveryTracker,
    location_poller:      Option<CustomFlagPoller>,
    goddess_chest_poller: Option<GoddessChestPoller>,
    // Beedle's shop needs no slot_data (its 10-entry table is hardcoded),
    // so it's always present rather than an `Option`.
    beedle_poller:        BeedleShopPoller,
    // Cheat toggles from slot_data, kept around (rather than only being
    // used once at `Event::Connected`) so they can be applied on a LATER
    // tick once the emulator is found, if it wasn't found yet at the
    // moment `Event::Connected` fired -- the AP_IPC_ROOT scan can take a
    // little while, and there's no reason a slow-to-attach emulator
    // should mean cheats silently never get applied for the whole
    // session. `None` once cheats have been successfully applied (or if
    // no `Event::Connected` has arrived yet this session).
    pending_cheat_slot_data: Option<SlotData>,
    // AP item-info entries (item/player names for textbox display) from
    // slot_data, kept around for the same reason as
    // `pending_cheat_slot_data` above -- retried on a later tick if the
    // emulator wasn't found yet at `Event::Connected`. `None` once
    // successfully written (or if no `Event::Connected` has arrived yet
    // this session).
    pending_item_info: Option<std::collections::HashMap<u16, ApItemInfo>>,
    // The item-info map for the CURRENT connection, kept for the whole
    // session (unlike `pending_item_info`, which is cleared once written)
    // so it can be periodically refreshed, re-written after the emulator
    // re-attaches, and verified against what's actually in game memory.
    item_info_live: Option<std::collections::HashMap<u16, ApItemInfo>>,
    item_info_last_refresh: Instant,
    // Set after every successful (re)write; the next tick reads the table
    // back from the game and logs whether it actually landed.
    item_info_verify_pending: bool,
    // Client tags we've told the server about (mirrors Python's
    // `ctx.tags`). `archipelago_rs` doesn't expose the client's own tags,
    // and `update_connection` REPLACES them, so `/deathlink` and
    // `/breathlink` toggle membership here and resend the whole set.
    active_tags: HashSet<String>,
    // Server hint messages seen this session, for `/hints`. Each entry is
    // (key, full text) where key is the text minus its trailing
    // "(found)"/"(not found)" status, so a status change replaces the old
    // entry instead of adding a duplicate.
    hints: Vec<(String, String)>,
    // Watches Link's health/stamina (via AP_IPC_ROOT.player_vitals) and
    // guards against echoing our own DeathLink/BreathLink back at us.
    link_monitor: LinkMonitor,
}

impl SyncState {
    fn new() -> Self {
        SyncState {
            delivery:             DeliveryTracker::new(),
            location_poller:      None,
            goddess_chest_poller: None,
            beedle_poller:        BeedleShopPoller::new(),
            pending_cheat_slot_data: None,
            pending_item_info: None,
            item_info_live: None,
            item_info_last_refresh: Instant::now(),
            item_info_verify_pending: false,
            active_tags: HashSet::from(["AP".to_string()]),
            hints: Vec::new(),
            link_monitor: LinkMonitor::new(),
        }
    }
}

/// The `Subscription` the GUI adds in its `subscription()` method. Runs
/// for the whole lifetime of the app. Everything here is non-blocking:
/// it spawns the real worker thread once, then just forwards whatever
/// that thread sends into `output.send(...).await`.
pub fn subscription() -> Subscription<WorkerEvent> {
    Subscription::run(|| {
        stream::channel(100, |mut output| async move {
            let (input_tx, input_rx) = mpsc::channel::<WorkerInput>(32);
            let (event_tx, mut event_rx) = mpsc::unbounded::<WorkerEvent>();

            if output.send(WorkerEvent::Ready(input_tx)).await.is_err() {
                return;
            }

            thread::spawn(move || run_blocking(input_rx, event_tx));

            while let Some(event) = event_rx.next().await {
                if output.send(event).await.is_err() {
                    break;
                }
            }
        })
    })
}

/// The one persistent, fully synchronous loop described in the module
/// docs above. Runs on its own `std::thread`.
fn run_blocking(mut input: mpsc::Receiver<WorkerInput>, output: EventSink) {
    // Emulator side: `None` while searching; `Some((mem, root_addr))` once
    // attached and `AP_IPC_ROOT` has been found.
    let mut emulator: Option<(Backend, usize)> = None;
    // Prevents re-logging "still searching" every ~16ms tick; reset
    // whenever the search outcome changes.
    let mut emulator_search_logged = false;

    // Archipelago side: `None` until a `Connect` (button or command)
    // arrives; `ap_connected` only flips true once `Event::Connected`
    // is actually seen (a fresh `Connection` isn't connected yet).
    let mut connection: Option<Connection<SlotData>> = None;
    let mut ap_connected = false;
    let mut sync = SyncState::new();
    // This client's slot name, used by `colors.rs` to highlight "you"
    // differently from other players in server messages.
    let mut own_name = String::new();
    // AP location codes already reported to the server (via
    // mark_checked) by ANY of the four check mechanisms, so none of them
    // re-poll or re-report something another one already handled.
    let mut reported_locations: HashSet<i64> = HashSet::new();

    vlog!("Looking for a supported emulator ({SUPPORTED_EMULATOR_NAMES:?})...");

    loop {
        // ── Drain any commands from the GUI ──────────────────────────
        while let Ok(input_msg) = input.try_recv() {
            match input_msg {
                WorkerInput::Connect { server, slot, password } => {
                    own_name = slot.clone();
                    start_connection(
                        server,
                        slot,
                        password,
                        &mut connection,
                        &mut ap_connected,
                        &mut sync,
                        &mut reported_locations,
                        &output,
                    );
                },
                WorkerInput::Disconnect => {
                    do_disconnect(&mut connection, &mut ap_connected, &output);
                },
                WorkerInput::RescanEmulator => {
                    emulator = None;
                    emulator_search_logged = false;
                },
                WorkerInput::Command(text) => {
                    if let Some(follow_up) = handle_command(
                        &text,
                        &mut connection,
                        ap_connected,
                        &mut emulator,
                        &mut sync,
                        &reported_locations,
                        &output,
                    ) {
                        match follow_up {
                            WorkerInput::RescanEmulator => {
                                emulator = None;
                                emulator_search_logged = false;
                            },
                            WorkerInput::Connect { server, slot, password } => {
                                own_name = slot.clone();
                                start_connection(
                                    server,
                                    slot,
                                    password,
                                    &mut connection,
                                    &mut ap_connected,
                                    &mut sync,
                                    &mut reported_locations,
                                    &output,
                                );
                            },
                            WorkerInput::Disconnect => {
                                do_disconnect(&mut connection, &mut ap_connected, &output);
                            },
                            WorkerInput::Command(_) => {}, // handle_command never returns this
                        }
                    }
                },
            }
        }

        // ── Emulator discovery (always running, independent of AP) ───
        if emulator.is_none() {
            if let Some(pid) = find_process_by_names(SUPPORTED_EMULATOR_NAMES) {
                match Backend::attach(pid as _) {
                    Ok(mut mem) => {
                        vlog!("Found emulator process (pid {pid}). Attaching...");
                        vlog!(
                            "Scanning for AP_IPC_ROOT (one scan, no NSO-header math, no per-mailbox magics)..."
                        );
                        match mem.pattern_scan_unique(&AP_IPC_MAGIC) {
                            Ok(root_addr) => {
                                vlog!("Found AP_IPC_ROOT at {root_addr:#x}");
                                match mem.read_bytes(root_addr + offsets::VERSION, 2) {
                                    Ok(bytes) => {
                                        let version = u16::from_le_bytes(bytes.try_into().unwrap());
                                        if version != AP_IPC_SUPPORTED_VERSION {
                                            log!(
                                                &output,
                                                "WARNING: game reports AP_IPC layout version {version}, \
                                                 this client expects {AP_IPC_SUPPORTED_VERSION}."
                                            );
                                        }
                                    },
                                    Err(e) => log!(&output, "WARNING: failed to read AP_IPC version: {e}"),
                                }
                                // A (re)attach means the game may have restarted with a
                                // blank table -- queue a fresh write of the item info.
                                if ap_connected {
                                    if let Some(live) = sync.item_info_live.as_ref() {
                                        sync.pending_item_info = Some(live.clone());
                                        sync.item_info_verify_pending = true;
                                    }
                                }
                                // Fresh game process: anything not in its save is gone.
                                sync.delivery.game_lost();
                                emulator = Some((mem, root_addr));
                                emulator_search_logged = false;
                            },
                            Err(e) => {
                                if !emulator_search_logged {
                                    vlog!(
                                        "AP_IPC_ROOT not found yet ({e}) — is Skyward Sword HD running \
                                         with the mod loaded?"
                                    );
                                    emulator_search_logged = true;
                                }
                            },
                        }
                    },
                    Err(e) => {
                        if !emulator_search_logged {
                            vlog!("Found a supported emulator process but failed to attach: {e}");
                            emulator_search_logged = true;
                        }
                    },
                }
            } else if !emulator_search_logged {
                vlog!(
                    "No supported emulator found ({SUPPORTED_EMULATOR_NAMES:?}). Please start your emulator."
                );
                emulator_search_logged = true;
            }
        } else if let Some((mem, root_addr)) = emulator.as_mut() {
            // Cheap liveness check — if this fails, assume the emulator
            // closed (or the game/mod isn't there anymore) and go back
            // to searching.
            if mem.read_bytes(*root_addr, 1).is_err() {
                log!(&output, "WARNING: Lost connection to the emulator. Searching again...");
                sync.delivery.game_lost();
                emulator = None;
                emulator_search_logged = false;
            }
        }

        // ── Archipelago connection events ────────────────────────────
        if let Some(conn) = connection.as_mut() {
            for event in conn.update() {
                match event {
                    Event::Connected => {
                        send(&output, WorkerEvent::Status("Connected".to_string()));
                        log!(&output, "[AP] Connected.");
                        ap_connected = true;
                        send(&output, WorkerEvent::Connected);
                        // Tags the slot options ask for (DeathLink / BreathLink).
                        let mut want_tags: Vec<&'static str> = Vec::new();
                        if let Some(client) = conn.client() {
                            let slot_data = client.slot_data();

                            let custom_flags = slot_data.custom_flag_to_location.clone();
                            vlog!(
                                "[AP] Loaded {} custom-flag location mappings from slot_data.",
                                custom_flags.len()
                            );
                            sync.location_poller = Some(CustomFlagPoller::new(custom_flags));

                            let goddess_chests = slot_data.goddess_chest_scene_flags.clone();
                            vlog!(
                                "[AP] Loaded {} goddess chest location mappings from slot_data.",
                                goddess_chests.len()
                            );
                            sync.goddess_chest_poller = Some(GoddessChestPoller::new(goddess_chests));

                            // Seed `reported_locations` with whatever the server already
                            // knows we've checked (e.g. from a previous session). Without
                            // this, each poller's own "recover pre-existing progress on the
                            // first poll" logic (see e.g. BeedleShopPoller::poll) treats
                            // those same locations as newly checked all over again and
                            // re-reports them via `mark_checked`, even though the server
                            // already has them -- this is what was causing already-checked
                            // Beedle's Airshop purchases to get "re-found" on every
                            // reconnect.
                            let already_known: Vec<i64> =
                                client.checked_locations().map(|loc| loc.id()).collect();
                            vlog!(
                                "[AP] Server already knows {} location(s) are checked.",
                                already_known.len()
                            );
                            reported_locations.extend(already_known);

                            // Stash a clone of slot_data so cheats can be (re)applied on
                            // a later tick once the emulator is found, if it isn't found
                            // yet right this instant -- the AP_IPC_ROOT scan can take a
                            // little while, and there's no reason a slow-to-attach
                            // emulator should mean cheats silently never get applied for
                            // the whole session. See the "Sync with the game" section
                            // below, which retries this every tick until it succeeds.
                            sync.pending_cheat_slot_data = Some(slot_data.clone());
                            let game_item_info = slot_data.item_info_for_game();
                            sync.pending_item_info = Some(game_item_info.clone());
                            sync.item_info_live = Some(game_item_info);
                            sync.item_info_last_refresh = Instant::now();
                            sync.item_info_verify_pending = true;
                            // Fresh connection: restart the link monitor's grace period.
                            sync.link_monitor = LinkMonitor::new();
                            if slot_data.option_death_link != 0 {
                                want_tags.push("DeathLink");
                            }
                            if slot_data.option_breath_link != 0 {
                                want_tags.push("BreathLink");
                            }
                            if let Some((mem, root_addr)) = emulator.as_mut() {
                                match cheat_sync::apply_cheat_flags(mem, *root_addr, slot_data) {
                                    Ok(active) => {
                                        if !active.is_empty() {
                                            vlog!(
                                                "[AP] Active cheats from slot_data: {}",
                                                active.join(", ")
                                            );
                                        }
                                        sync.pending_cheat_slot_data = None;
                                    },
                                    Err(e) => log!(
                                        &output,
                                        "[IPC] failed to apply cheat flags from slot_data: {e}"
                                    ),
                                }

                                match item_info::write_item_info_table(
                                    mem,
                                    *root_addr,
                                    &slot_data.item_info_for_game(),
                                ) {
                                    Ok(count) => {
                                        vlog!(
                                            "[AP] Wrote {count} AP item info entries for \
                                             textbox display."
                                        );
                                        sync.pending_item_info = None;
                                    },
                                    Err(e) => log!(
                                        &output,
                                        "[IPC] failed to write AP item info table: {e}"
                                    ),
                                }
                            } else {
                                vlog!(
                                    "[AP] Emulator not found yet -- slot_data cheat toggles \
                                     and AP item info will be applied as soon as it's found."
                                );
                            }
                        }
                        // Load the stored "safe" delivery index; item delivery waits for it.
                        if let Some(client) = conn.client_mut() {
                            sync.delivery.begin(client);
                        }
                        if !want_tags.is_empty() {
                            for t in &want_tags {
                                sync.active_tags.insert(t.to_string());
                            }
                            if let Some(client) = conn.client_mut() {
                                match client.update_connection(
                                    None,
                                    Some(sync.active_tags.iter().map(|t| t.as_str())),
                                ) {
                                    Ok(()) => log!(&output, "[AP] Enabled tags from slot options: {}", want_tags.join(", ")),
                                    Err(e) => log!(&output, "[AP] Failed to enable link tags: {e}"),
                                }
                            }
                        }
                    },
                    Event::DeathLink { source, cause, .. } => {
                        let alias = conn
                            .client()
                            .map(|c| c.this_player().alias().to_string())
                            .unwrap_or_default();
                        // Ignore our own DeathLink (echo) and anything while the tag is off.
                        if sync.active_tags.contains("DeathLink")
                            && source != alias
                            && source != own_name
                            && !sync.link_monitor.death_sent_recently()
                        {
                            let why = cause.unwrap_or_else(|| format!("{source} died."));
                            log!(&output, "[DeathLink] {why}");
                            match emulator.as_mut() {
                                Some((mem, root_addr)) => match links::request_kill(mem, *root_addr) {
                                    Ok(()) => sync.link_monitor.note_kill_requested(),
                                    Err(e) => log!(&output, "[DeathLink] failed to kill Link: {e}"),
                                },
                                None => log!(&output, "[DeathLink] emulator not attached; can't kill Link."),
                            }
                        }
                    },
                    Event::Bounce { tags, data, .. } => {
                        let is_breath = tags
                            .as_ref()
                            .is_some_and(|t| t.iter().any(|x| x.as_str() == "BreathLink"));
                        if is_breath && sync.active_tags.contains("BreathLink") {
                            let alias = conn
                                .client()
                                .map(|c| c.this_player().alias().to_string())
                                .unwrap_or_default();
                            let field = |k: &str| {
                                data.as_ref().and_then(|d| d.get(k)).and_then(|v| v.as_str()).map(str::to_string)
                            };
                            let source = field("source").unwrap_or_else(|| "Someone".to_string());
                            if source != alias && source != own_name && !sync.link_monitor.breath_sent_recently() {
                                let why = field("cause").unwrap_or_else(|| format!("{source} ran out of breath."));
                                log!(&output, "[BreathLink] {why}");
                                match emulator.as_mut() {
                                    Some((mem, root_addr)) => match links::request_drain(mem, *root_addr) {
                                        Ok(()) => sync.link_monitor.note_drain_requested(),
                                        Err(e) => log!(&output, "[BreathLink] failed to drain stamina: {e}"),
                                    },
                                    None => log!(&output, "[BreathLink] emulator not attached; can't drain stamina."),
                                }
                            }
                        }
                    },
                    Event::Print(print) => {
                        let print_spans = colors::print_to_spans(&print, &own_name);
                        // Remember server hint messages for `/hints`.
                        let plain: String = print_spans.iter().map(|s| s.text.as_str()).collect();
                        if plain.starts_with("[Hint]") {
                            record_hint(&mut sync.hints, plain);
                        }
                        let mut spans = vec![LogSpan::plain("[AP] ")];
                        spans.extend(print_spans);
                        send(&output, WorkerEvent::Print(spans));
                    },
                    Event::Error(err) => {
                        // `Error::Elsewhere` is a placeholder archipelago_rs uses when the
                        // real error has already been stashed in `Connection::state()`
                        // (see `Connection::update`'s docs) -- printing `err` directly
                        // here is exactly how "a full error is available elsewhere" ends
                        // up in the log/GUI instead of the actual connection failure.
                        // Fetch the real error from the connection's state in that case;
                        // for the non-fatal, recoverable errors that already carry the
                        // real error (e.g. `Error::ProtocolError`), use it as-is.
                        let message = if matches!(err, Error::Elsewhere) {
                            conn.err().to_string()
                        } else {
                            err.to_string()
                        };
                        log!(&output, "[AP] Error: {message}");
                        send(&output, WorkerEvent::Error(message));
                    },
                    _ => {},
                }
            }
        }

        // ── Sync with the game, only once both sides are ready ───────
        if ap_connected {
            if let (Some((mem, root_addr)), Some(conn)) = (emulator.as_mut(), connection.as_mut()) {
                let root_addr = *root_addr;

                // Retry applying cheat toggles from slot_data if they couldn't be
                // applied yet (the emulator wasn't found/attached at the moment
                // `Event::Connected` fired, or the write failed transiently). Runs
                // every tick until it succeeds, then `pending_cheat_slot_data` is
                // cleared so this becomes a no-op for the rest of the session.
                if let Some(slot_data) = sync.pending_cheat_slot_data.take() {
                    match cheat_sync::apply_cheat_flags(mem, root_addr, &slot_data) {
                        Ok(active) => {
                            if !active.is_empty() {
                                vlog!("[AP] Active cheats from slot_data: {}", active.join(", "));
                            }
                        },
                        Err(e) => {
                            vlog!("[IPC] failed to apply cheat flags from slot_data: {e}");
                            // Put it back so the next tick retries.
                            sync.pending_cheat_slot_data = Some(slot_data);
                        },
                    }
                }

                // Same retry pattern as `pending_cheat_slot_data` above, for the
                // AP item-info table (see `item_info.rs`).
                if let Some(item_info_map) = sync.pending_item_info.take() {
                    match item_info::write_item_info_table(mem, root_addr, &item_info_map) {
                        Ok(count) => {
                            vlog!("[AP] Wrote {count} AP item info entries for textbox display.");
                        },
                        Err(e) => {
                            vlog!("[IPC] failed to write AP item info table: {e}");
                            sync.pending_item_info = Some(item_info_map);
                        },
                    }
                }

                // Item-info table upkeep, once the initial write has succeeded
                // (`pending_item_info` is None): verify it landed, then mirror the
                // Python client's ~5 s count refresh so a stale/zero count can't
                // linger and turn every textbox back into the generic fallback.
                if sync.pending_item_info.is_none() {
                    if let Some(live) = sync.item_info_live.as_ref() {
                        if !live.is_empty() {
                            if sync.item_info_verify_pending {
                                sync.item_info_verify_pending = false;
                                match item_info::verify_item_info_table(mem, root_addr, live) {
                                    Ok(r) => {
                                        log!(
                                            &output,
                                            "[AP] Item info in game: count={}, {}/{} entries match \
                                             ({}/{} Beedle's Airshop).",
                                            r.count_in_game,
                                            r.matched,
                                            r.expected,
                                            r.beedle_matched,
                                            r.beedle_expected
                                        );
                                        if !r.missing_sample.is_empty() {
                                            vlog!(
                                                "[AP] Item info missing/mismatched flag ids (sample): {:?}",
                                                r.missing_sample
                                            );
                                        }
                                    },
                                    Err(e) => vlog!("[IPC] item info verify failed: {e}"),
                                }
                            } else if sync.item_info_last_refresh.elapsed() >= Duration::from_secs(5) {
                                sync.item_info_last_refresh = Instant::now();
                                match item_info::refresh_item_info_table(mem, root_addr, live) {
                                    Ok(true) => {
                                        vlog!("[AP] Item info count in game was wrong -- re-wrote the table.");
                                        sync.item_info_verify_pending = true;
                                    },
                                    Ok(false) => {},
                                    Err(e) => vlog!("[IPC] item info refresh failed: {e}"),
                                }
                            }
                        }
                    }
                }

                // Item delivery -- crash-safe, paced, resumable (see delivery.rs).
                if let Some(client) = conn.client_mut() {
                    if let Some(line) = sync.delivery.poll_load(client) {
                        if line.gui {
                            log!(&output, "{}", line.text);
                        } else {
                            vlog!("{}", line.text);
                        }
                    }
                }
                let tick = match conn.client() {
                    Some(client) => sync.delivery.tick(mem, root_addr, client.received_items()),
                    None => delivery::Tick::default(),
                };
                for line in tick.logs {
                    if line.gui {
                        log!(&output, "{}", line.text);
                    } else {
                        vlog!("{}", line.text);
                    }
                }
                if let Some(value) = tick.persist {
                    if let Some(client) = conn.client_mut() {
                        if let Err(e) = sync.delivery.persist(client, value) {
                            log!(&output, "[Delivery] Failed to save delivery index {value}: {e}");
                        }
                    }
                }

                // DeathLink / BreathLink SENDING: watch Link's health/stamina and
                // send one bounce per event (see links.rs for the latching and
                // echo suppression). The monitor is polled even with the tags off
                // so its latches stay current; signals are only sent when enabled.
                match sync.link_monitor.poll(mem, root_addr) {
                    Ok(signals) => {
                        for signal in signals {
                            let tag = match signal {
                                LinkSignal::Death => "DeathLink",
                                LinkSignal::Breath => "BreathLink",
                            };
                            if !sync.active_tags.contains(tag) {
                                continue;
                            }
                            let Some(client) = conn.client_mut() else { continue };
                            let alias = client.this_player().alias().to_string();
                            let place = links::stage_display_name(&sync.link_monitor.stage_code);
                            match signal {
                                LinkSignal::Death => {
                                    let cause = format!("{alias} died in {place}.");
                                    match client.death_link(DeathLinkOptions::new().cause(cause.clone())) {
                                        Ok(()) => {
                                            sync.link_monitor.note_death_sent();
                                            log!(&output, "[DeathLink] Sent: {cause}");
                                        },
                                        Err(e) => log!(&output, "[DeathLink] send failed: {e}"),
                                    }
                                },
                                LinkSignal::Breath => {
                                    let cause = format!("{alias} ran out of breath in {place}.");
                                    let now = std::time::SystemTime::now()
                                        .duration_since(std::time::UNIX_EPOCH)
                                        .map(|d| d.as_secs_f64())
                                        .unwrap_or(0.0);
                                    let data = serde_json::json!({
                                        "time": now,
                                        "source": alias,
                                        "cause": cause,
                                    });
                                    match client.bounce(data, BounceOptions::new().tags(["BreathLink"])) {
                                        Ok(()) => {
                                            sync.link_monitor.note_breath_sent();
                                            log!(&output, "[BreathLink] Sent: {cause}");
                                        },
                                        Err(e) => log!(&output, "[BreathLink] send failed: {e}"),
                                    }
                                },
                            }
                        }
                    },
                    Err(e) => vlog!("[IPC] link monitor poll failed: {e}"),
                }

                // All four location-check mechanisms, unioned/deduped
                // and reported to the server in one `mark_checked` call
                // — same pattern as `main.rs`'s `run_headless`.
                let mut newly_checked_all: Vec<i64> = Vec::new();
                let already_checked = |code: i64| reported_locations.contains(&code);

                if let Some(poller) = sync.location_poller.as_mut() {
                    match poller.poll(mem, root_addr, &already_checked) {
                        Ok(codes) => newly_checked_all.extend(codes),
                        Err(e) => vlog!("[IPC] custom-flag location poll failed: {e}"),
                    }
                }
                if let Some(poller) = sync.goddess_chest_poller.as_mut() {
                    match poller.poll(mem, root_addr, &already_checked) {
                        Ok(codes) => newly_checked_all.extend(codes),
                        Err(e) => vlog!("[IPC] goddess chest poll failed: {e}"),
                    }
                }
                match sync.beedle_poller.poll(mem, root_addr, &already_checked) {
                    Ok(codes) => newly_checked_all.extend(codes),
                    Err(e) => vlog!("[IPC] Beedle's shop poll failed: {e}"),
                }
                match boss_defeats::poll(mem, root_addr, &already_checked) {
                    Ok(codes) => newly_checked_all.extend(codes),
                    Err(e) => vlog!("[IPC] boss defeat poll failed: {e}"),
                }

                if !newly_checked_all.is_empty() {
                    newly_checked_all.sort_unstable();
                    newly_checked_all.dedup();
                    log!(&output, "[AP] {} location(s) checked: {newly_checked_all:?}", newly_checked_all.len());
                    for &code in &newly_checked_all {
                        reported_locations.insert(code);
                    }
                    if let Some(client) = conn.client_mut() {
                        if let Err(e) = client.mark_checked(newly_checked_all) {
                            log!(&output, "[AP] mark_checked failed: {e}");
                        }
                    }
                }

                if let Ok((checked, total)) = crate::read_check_stats(mem, root_addr) {
                    send(&output, WorkerEvent::Stats { checked, total });
                }
            }
        }

        thread::sleep(Duration::from_millis(16)); // ~60 Hz, matching the game's frame rate — fine
                                                   // here, this is a real OS thread, not an async task.
    }
}

/// Starts a new Archipelago connection and resets the per-session state
/// that goes with it. Shared by the GUI's Connect button and a typed
/// `/connect` command so the two can't leave `ap_connected`/the sync
/// state out of sync with each other.
fn start_connection(
    server: String,
    slot: String,
    password: Option<String>,
    connection: &mut Option<Connection<SlotData>>,
    ap_connected: &mut bool,
    sync: &mut SyncState,
    reported_locations: &mut HashSet<i64>,
    output: &EventSink,
) {
    send(output, WorkerEvent::Status(format!("Connecting to {server}...")));
    log!(output, "Connecting to Archipelago server {server} as '{slot}'...");
    *connection = Some(Connection::new(
        server,
        slot.as_str(),
        Some("Skyward Sword HD"),
        password.map(|p| ConnectionOptions::new().password(p)).unwrap_or_else(ConnectionOptions::new),
    ));
    *ap_connected = false;
    *sync = SyncState::new();
    reported_locations.clear();
}

/// Ends the current Archipelago connection, if any. Shared by the GUI's
/// Disconnect button and a typed `/disconnect` command. Leaves `sync`/
/// `reported_locations` as-is — they get a full reset in
/// `start_connection` on the next `Connect` regardless.
fn do_disconnect(connection: &mut Option<Connection<SlotData>>, ap_connected: &mut bool, output: &EventSink) {
    if connection.take().is_some() {
        log!(output, "Disconnected.");
        send(output, WorkerEvent::Status("Not connected".to_string()));
        send(output, WorkerEvent::Disconnected);
    }
    *ap_connected = false;
}

/// Handles one line typed into the command bar. `/`-prefixed text is a
/// local command; anything else (including `!`-prefixed server
/// commands) is sent to the Archipelago server as a chat message via
/// `Client::say` — the server, not this client, interprets `!hint` and
/// friends.
///
/// Returns a follow-up `WorkerInput` for the caller's drain loop to
/// apply through the exact same `Connect`/`Disconnect` handling a
/// button press gets, rather than duplicating (and risking drifting
/// from) that logic here.
fn handle_basic_command(
    text: &str,
    connection: &mut Option<Connection<SlotData>>,
    ap_connected: bool,
    output: &EventSink,
) -> Option<WorkerInput> {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return None;
    }

    if trimmed == "/help" {
        log!(output, "Local commands: /connect <server> <slot> [password], /disconnect, /help.");
        log!(output, "Anything else is sent to the server as chat — including \"!\" server commands like !hint.");
        return None;
    }

    if trimmed == "/disconnect" {
        return Some(WorkerInput::Disconnect);
    }

    if let Some(rest) = trimmed.strip_prefix("/connect") {
        let mut parts = rest.split_whitespace();
        let (Some(server), Some(slot)) = (parts.next(), parts.next()) else {
            log!(output, "Usage: /connect <server> <slot> [password]");
            return None;
        };
        let password = parts.next().map(str::to_string);
        return Some(WorkerInput::Connect { server: server.to_string(), slot: slot.to_string(), password });
    }

    if trimmed.starts_with('/') {
        log!(output, "Unknown command: {trimmed}. Try /help.");
        return None;
    }

    if !ap_connected {
        log!(output, "Not connected to a server — nothing to send \"{trimmed}\" to.");
        return None;
    }
    match connection.as_mut().and_then(|c| c.client_mut()) {
        Some(client) => {
            if let Err(e) = client.say(trimmed.to_string()) {
                log!(output, "Failed to send message: {e}");
            }
        },
        None => log!(output, "Not connected to a server — nothing to send \"{trimmed}\" to."),
    }
    None
}

// ═══════════════════════════════════════════════════════════════════════════
// Command bar: the SSHD-specific commands from `SSHDClientCommandProcessor`
// in SSHDClient.py (plus the handful of inherited CommonClient ones that
// only need data this client already has).
// ═══════════════════════════════════════════════════════════════════════════

const FLAG_TYPES: &[(&str, u8)] = &[
    ("storyflag", ap_ipc::FLAG_TYPE_STORYFLAG),
    ("sceneflag", ap_ipc::FLAG_TYPE_SCENEFLAG),
    ("itemflag", ap_ipc::FLAG_TYPE_ITEMFLAG),
    ("dungeonflag", ap_ipc::FLAG_TYPE_DUNGEONFLAG),
];

const FLAG_OPS: &[(&str, u8)] = &[
    ("get", ap_ipc::FLAG_OP_GET),
    ("set", ap_ipc::FLAG_OP_SET),
    ("unset", ap_ipc::FLAG_OP_UNSET),
];

/// Max lines `/received`, `/missing`, `/checked` print before summarizing
/// (the GUI log only keeps the last 500 lines anyway).
const LIST_LINE_CAP: usize = 200;

/// Full command dispatcher. `/`-prefixed text whose first word is one of
/// the commands below is handled here; everything else (`/connect`,
/// `/disconnect`, unknown `/` commands, and plain/`!` chat) falls through
/// to `handle_basic_command`.
fn handle_command(
    text: &str,
    connection: &mut Option<Connection<SlotData>>,
    ap_connected: bool,
    emulator: &mut Option<(Backend, usize)>,
    sync: &mut SyncState,
    reported_locations: &HashSet<i64>,
    output: &EventSink,
) -> Option<WorkerInput> {
    let trimmed = text.trim();
    let Some(body) = trimmed.strip_prefix('/') else {
        return handle_basic_command(text, connection, ap_connected, output);
    };
    let mut tokens = body.split_whitespace();
    let name = tokens.next().unwrap_or("").to_lowercase();
    let args: Vec<&str> = tokens.collect();

    match name.as_str() {
        "help" => cmd_help(output),
        "sshd" => cmd_sshd(connection, ap_connected, emulator, reported_locations, output),
        "rescan" => {
            log!(output, "Starting rescan...");
            return Some(WorkerInput::RescanEmulator);
        },
        "flush_item_datastorage" => cmd_flush_item_datastorage(&args, connection, ap_connected, sync, output),
        "set_delivery_index" => cmd_set_delivery_index(&args, connection, ap_connected, sync, output),
        "cheats" => cmd_cheats(emulator, output),
        "cheat" => cmd_cheat(&args, emulator, output),
        "hints" => cmd_hints(sync, output),
        "deathlink" => cmd_toggle_tag("DeathLink", connection, ap_connected, sync, output),
        "breathlink" => cmd_toggle_tag("BreathLink", connection, ap_connected, sync, output),
        "spawn_actor" => cmd_spawn_actor(&args, emulator, output),
        "spawn_demise" => cmd_spawn_demise(emulator, output),
        "flag" => cmd_flag(&args, emulator, output),
        "warp" => cmd_warp(&args, emulator, output),
        "go_mode" => cmd_go_mode(connection, ap_connected, emulator, reported_locations, output),
        "received" => cmd_received(connection, ap_connected, output),
        "missing" => cmd_location_list(false, connection, ap_connected, output),
        "checked" => cmd_location_list(true, connection, ap_connected, output),
        "players" => cmd_players(connection, ap_connected, output),
        _ => return handle_basic_command(text, connection, ap_connected, output),
    }
    None
}

fn cmd_help(output: &EventSink) {
    log!(output, "=== Commands ===");
    for line in [
        "/connect <server> <slot> [password], /disconnect — manage the server connection",
        "/sshd — client status (emulator, server, checks)",
        "/rescan — re-scan for the emulator and AP_IPC_ROOT",
        "/flush_item_datastorage confirm — re-give every item you've ever received (local and remote)",
        "/set_delivery_index <n> — declare items 0..n already in your save (re-give n onward); no arg shows status",
        "/cheats — show cheat status;  /cheat <name> — toggle;  /cheat hovercraft <velocity>",
        "/hints — hints seen this session",
        "/deathlink, /breathlink — toggle those tags",
        "/spawn_actor <ACTORID name|id> [param1] [oarc], /spawn_demise — spawn an actor",
        "/flag <storyflag|sceneflag|itemflag|dungeonflag> <get|set|unset> <id|all> [value_or_scene]",
        "/warp start  |  /warp <stage name or id> [layer]",
        "/go_mode — victory requirements and whether you have them",
        "/received, /missing, /checked, /players — multiworld info",
    ] {
        log!(output, "  {line}");
    }
    log!(output, "Anything else is sent to the server as chat — including \"!\" commands like !hint.");
}

/// Returns the attached emulator's memory and `AP_IPC_ROOT` address, or
/// logs a hint and returns `None` if there isn't one yet.
fn require_emulator<'a>(
    emulator: &'a mut Option<(Backend, usize)>,
    output: &EventSink,
) -> Option<(&'a mut Backend, usize)> {
    match emulator.as_mut() {
        Some((mem, root_addr)) => Some((mem, *root_addr)),
        None => {
            log!(output, "Not attached to the emulator yet. Start the game with the mod loaded (or try /rescan).");
            None
        },
    }
}

/// Python-style `int(text, 0)`: optional sign, then `0x`/`0o`/`0b` prefixes
/// or plain decimal.
fn parse_int_auto(text: &str) -> Option<i64> {
    let t = text.trim();
    let (neg, t) = match t.strip_prefix('-') {
        Some(rest) => (true, rest),
        None => (false, t.strip_prefix('+').unwrap_or(t)),
    };
    let v = if let Some(h) = t.strip_prefix("0x").or_else(|| t.strip_prefix("0X")) {
        i64::from_str_radix(h, 16).ok()?
    } else if let Some(o) = t.strip_prefix("0o").or_else(|| t.strip_prefix("0O")) {
        i64::from_str_radix(o, 8).ok()?
    } else if let Some(b) = t.strip_prefix("0b").or_else(|| t.strip_prefix("0B")) {
        i64::from_str_radix(b, 2).ok()?
    } else {
        t.parse::<i64>().ok()?
    };
    Some(if neg { -v } else { v })
}

fn cmd_sshd(
    connection: &mut Option<Connection<SlotData>>,
    ap_connected: bool,
    emulator: &mut Option<(Backend, usize)>,
    reported_locations: &HashSet<i64>,
    output: &EventSink,
) {
    match emulator.as_mut() {
        Some((mem, root_addr)) => {
            let root_addr = *root_addr;
            log!(output, "Emulator: attached (AP_IPC_ROOT at {root_addr:#x})");
            match crate::read_check_stats(mem, root_addr) {
                Ok((checked, total)) => log!(output, "In-game check stats: {checked}/{total}"),
                Err(e) => log!(output, "In-game check stats: unreadable ({e})"),
            }
        },
        None => log!(output, "Emulator: not attached (still searching)"),
    }
    let slot = connection
        .as_ref()
        .and_then(|c| c.client())
        .map(|client| client.this_player().alias().to_string());
    match (ap_connected, slot) {
        (true, Some(slot)) => log!(output, "Archipelago: connected as {slot}"),
        (true, None) => log!(output, "Archipelago: connected"),
        (false, _) => log!(output, "Archipelago: not connected"),
    }
    log!(output, "Locations reported to the server this session: {}", reported_locations.len());
}

fn cmd_flush_item_datastorage(
    args: &[&str],
    connection: &mut Option<Connection<SlotData>>,
    ap_connected: bool,
    sync: &mut SyncState,
    output: &EventSink,
) {
    if !ap_connected {
        log!(output, "Not connected/authenticated to an Archipelago server yet.");
        return;
    }
    // This client keeps its delivery index in memory only (there is no
    // DataStorage key to flush), so "flush" means: reset the index to 0 and
    // ask the server to resend everything (local finds and other players'
    // items alike). archipelago_rs clears and refills its received list on
    // that reply, so nothing is delivered twice. Start-inventory items
    // (location -2) are still skipped since they're already in the save.
    // Requires an explicit `confirm` since it re-gives every item.
    if args.first().map(|a| a.to_lowercase()).as_deref() != Some("confirm") {
        log!(output, "This re-requests every item you've ever received (local and remote) and re-delivers ALL of them.");
        log!(output, "That can duplicate progressive items already in your save. If you really want that, run: /flush_item_datastorage confirm");
        return;
    }
    let Some(client) = connection.as_mut().and_then(|c| c.client_mut()) else {
        log!(output, "Not connected/authenticated to an Archipelago server yet.");
        return;
    };
    log!(output, "[FlushDataStorage] Resetting delivery index (was {}) and requesting a full item re-sync...", sync.delivery.safe_index());
    let value = sync.delivery.set_index(0);
    if let Err(e) = sync.delivery.persist(client, value) {
        log!(output, "[FlushDataStorage] Failed to save the reset delivery index: {e}");
    }
    match client.sync() {
        Ok(()) => log!(output, "[FlushDataStorage] Re-sync requested; items will be re-queued shortly."),
        Err(e) => log!(output, "[FlushDataStorage] Failed to request re-sync: {e}"),
    }
}

/// `/set_delivery_index [n]`: with no argument, shows item-delivery status.
/// With `n`, declares that received items 0..n are already in your save and
/// everything from item n on should be (re)delivered. Use it to correct the
/// position if the client was restarted while the game kept running.
fn cmd_set_delivery_index(
    args: &[&str],
    connection: &mut Option<Connection<SlotData>>,
    ap_connected: bool,
    sync: &mut SyncState,
    output: &EventSink,
) {
    if !ap_connected {
        log!(output, "Not connected/authenticated to an Archipelago server yet.");
        return;
    }
    let Some(client) = connection.as_mut().and_then(|c| c.client_mut()) else {
        log!(output, "Not connected/authenticated to an Archipelago server yet.");
        return;
    };
    let total = client.received_items().len();
    let Some(arg) = args.first() else {
        log!(
            output,
            "Delivery: {} of {total} received item(s) safe in your save; next to deliver is #{}; {} in the game's buffer{}.",
            sync.delivery.safe_index(),
            sync.delivery.next_index(),
            sync.delivery.in_flight_count(),
            if sync.delivery.is_ready() { "" } else { " (still loading stored index)" }
        );
        log!(output, "Usage: /set_delivery_index <n> — items 0..n are already in your save; n onward get delivered.");
        return;
    };
    let Some(n) = parse_int_auto(arg).filter(|n| *n >= 0 && (*n as usize) <= total) else {
        log!(output, "WARNING: '{arg}' must be a number between 0 and {total}.");
        return;
    };
    let value = sync.delivery.set_index(n as usize);
    match sync.delivery.persist(client, value) {
        Ok(()) => log!(output, "[Delivery] Delivery index set to {value}; items from #{value} on will be delivered."),
        Err(e) => log!(output, "[Delivery] Failed to save delivery index: {e}"),
    }
}

fn cmd_cheats(emulator: &mut Option<(Backend, usize)>, output: &EventSink) {
    let Some((mem, root_addr)) = require_emulator(emulator, output) else { return };
    let flags = match cheat_sync::read_cheat_flags(mem, root_addr) {
        Ok(f) => f,
        Err(e) => {
            log!(output, "Couldn't read cheat flags: {e}");
            return;
        },
    };
    log!(output, "=== Cheat Status ===");
    for &name in cheat_sync::TOGGLEABLE_CHEAT_NAMES {
        let on = cheat_sync::get_cheat_field(&flags, name).unwrap_or(0) != 0;
        log!(output, "  {:<20} {}", name, if on { "ON" } else { "off" });
    }
    // Copy packed fields to locals before formatting (taking a reference
    // to a packed field is not allowed).
    let speed_bits = flags.speed_multiplier_bits;
    let hover_bits = flags.hover_vel_y_bits;
    let speed = f32::from_bits(speed_bits);
    let normal = if speed == 1.0 || speed == 0.0 { " (normal)" } else { "" };
    log!(output, "  {:<20} {:.1}x{}", "speed", speed, normal);
    log!(output, "  {:<20} {:.4}", "hovercraft velocity", f32::from_bits(hover_bits));
    log!(output, "Use /cheat <name> to toggle. Names: {}", cheat_sync::TOGGLEABLE_CHEAT_NAMES.join(", "));
}

fn cmd_cheat(args: &[&str], emulator: &mut Option<(Backend, usize)>, output: &EventSink) {
    let all_names: Vec<&str> = cheat_sync::TOGGLEABLE_CHEAT_NAMES.to_vec();
    let name = args.first().map(|a| a.to_lowercase()).unwrap_or_default();
    if name.is_empty() {
        log!(output, "Usage: /cheat <name>  — toggle a cheat on/off");
        log!(output, "       /cheat hovercraft <velocity>  — set sustain velocity (1.85 = stable hover)");
        log!(output, "Available: {}", all_names.join(", "));
        return;
    }
    if !cheat_sync::TOGGLEABLE_CHEAT_NAMES.contains(&name.as_str()) {
        log!(output, "WARNING: Unknown cheat '{name}'. Available: {}", all_names.join(", "));
        return;
    }
    let Some((mem, root_addr)) = require_emulator(emulator, output) else { return };

    // /cheat hovercraft <value> — set sustain velocity without toggling.
    if name == "hovercraft" {
        if let Some(value) = args.get(1) {
            match value.parse::<f32>() {
                Ok(velocity) => match cheat_sync::set_hovercraft_velocity(mem, root_addr, velocity) {
                    Ok(()) => log!(output, "Hovercraft sustain velocity set to {velocity} (0.0 = no drift)"),
                    Err(e) => log!(output, "Failed to set hovercraft velocity: {e}"),
                },
                Err(_) => log!(output, "WARNING: Invalid velocity '{value}'. Usage: /cheat hovercraft <float>"),
            }
            return;
        }
    }

    let current = match cheat_sync::read_cheat_flags(mem, root_addr) {
        Ok(flags) => cheat_sync::get_cheat_field(&flags, &name).unwrap_or(0),
        Err(e) => {
            log!(output, "Couldn't read cheat flags: {e}");
            return;
        },
    };
    let new_value = if current != 0 { 0 } else { 1 };
    match cheat_sync::toggle_cheat_field(mem, root_addr, &name, new_value) {
        Ok(Some(v)) => log!(output, "Cheat '{name}' is now {}", if v != 0 { "ON" } else { "OFF" }),
        Ok(None) => log!(output, "WARNING: Unknown cheat '{name}'."),
        Err(e) => log!(output, "Failed to toggle cheat '{name}': {e}"),
    }
}

/// Records a `[Hint]` print, replacing an earlier entry for the same hint
/// (the server re-sends it with a changed "(found)" status).
fn record_hint(hints: &mut Vec<(String, String)>, text: String) {
    let key = text
        .trim_end()
        .trim_end_matches("(not found)")
        .trim_end_matches("(found)")
        .trim_end()
        .to_string();
    match hints.iter_mut().find(|(k, _)| *k == key) {
        Some(entry) => entry.1 = text,
        None => hints.push((key, text)),
    }
}

fn cmd_hints(sync: &SyncState, output: &EventSink) {
    if sync.hints.is_empty() {
        log!(output, "No hints received yet.");
        return;
    }
    log!(output, "=== Hints ({}) ===", sync.hints.len());
    for (_, text) in &sync.hints {
        log!(output, "{text}");
    }
}

/// `/deathlink` and `/breathlink`: toggles the tag and resends the full
/// tag set. While a tag is on, the main loop sends a link when Link's
/// health/stamina hits 0 and applies incoming links in game (see `links.rs`).
fn cmd_toggle_tag(
    tag: &str,
    connection: &mut Option<Connection<SlotData>>,
    ap_connected: bool,
    sync: &mut SyncState,
    output: &EventSink,
) {
    let Some(client) = connection.as_mut().and_then(|c| c.client_mut()).filter(|_| ap_connected) else {
        log!(output, "Not connected to a server yet.");
        return;
    };
    let enabled = !sync.active_tags.contains(tag);
    let mut tags = sync.active_tags.clone();
    if enabled {
        tags.insert(tag.to_string());
    } else {
        tags.remove(tag);
    }
    match client.update_connection(None, Some(tags.iter().map(|t| t.as_str()))) {
        Ok(()) => {
            sync.active_tags = tags;
            log!(output, "{tag} is now {}", if enabled { "ON" } else { "OFF" });
        },
        Err(e) => log!(output, "Failed to update tags: {e}"),
    }
}

fn cmd_spawn_actor(args: &[&str], emulator: &mut Option<(Backend, usize)>, output: &EventSink) {
    let Some(&actor_token) = args.first() else {
        log!(output, "Usage: /spawn_actor <ACTORID name|id> [param1] [oarc]");
        log!(output, "Example: /spawn_actor B_LASTBOSS 0xFFFFFFC0 BLasBos");
        return;
    };
    let actor_map = actorid::load_actorid_map();
    let Some(actor_id) = actorid::resolve_actor_id(&actor_map, actor_token) else {
        if actor_map.is_empty() {
            log!(output, "WARNING: Unknown ACTORID '{actor_token}', and actor.rs couldn't be found for name lookups — use a numeric id.");
        } else {
            log!(output, "WARNING: Unknown ACTORID '{actor_token}'. Use a valid ACTORID enum name or numeric id.");
        }
        return;
    };
    spawn_actor_resolved(actor_id, &actor_map, args, emulator, output);
}

/// Compatibility alias for `/spawn_actor B_LASTBOSS 0xFFFFFFC0 BLasBos`.
fn cmd_spawn_demise(emulator: &mut Option<(Backend, usize)>, output: &EventSink) {
    /// `B_LASTBOSS`'s value in rust-additions' `actor.rs` at the time this
    /// was written; only used if `actor.rs` can't be found at runtime.
    const B_LASTBOSS_FALLBACK: u16 = 0x14D;
    let actor_map = actorid::load_actorid_map();
    let actor_id = actorid::resolve_actor_id(&actor_map, "B_LASTBOSS").unwrap_or(B_LASTBOSS_FALLBACK);
    let args = ["B_LASTBOSS", "0xFFFFFFC0", "BLasBos"];
    spawn_actor_resolved(actor_id, &actor_map, &args, emulator, output);
}

fn spawn_actor_resolved(
    actor_id: u16,
    actor_map: &HashMap<String, u16>,
    args: &[&str],
    emulator: &mut Option<(Backend, usize)>,
    output: &EventSink,
) {
    let mut param1: u32 = 0xFFFF_FFFF;
    let mut oarc = args.get(2).map(|s| s.to_string()).unwrap_or_default();
    if let Some(p1) = args.get(1) {
        match parse_int_auto(p1) {
            Some(v) => param1 = (v & 0xFFFF_FFFF) as u32,
            None => {
                // If param1 is omitted, allow /spawn_actor <id> <oarc>.
                if oarc.is_empty() {
                    oarc = p1.to_string();
                } else {
                    log!(output, "WARNING: Invalid param1 '{p1}'. Use decimal or 0x-prefixed hex.");
                    return;
                }
            },
        }
    }
    let mut oarc = oarc.trim().to_string();
    if oarc.is_empty() {
        let boss = actorid::resolve_actor_id(actor_map, "B_LASTBOSS").unwrap_or(0x14D);
        if actor_id == boss {
            oarc = "BLasBos".to_string();
        }
    }

    let Some((mem, root_addr)) = require_emulator(emulator, output) else { return };
    match ipc_requests::spawn_request(mem, root_addr, actor_id, param1, 0xFFFF_FFFF, &oarc) {
        Ok(()) => {
            let oarc_text = if oarc.is_empty() { String::new() } else { format!(", OARC '{oarc}'") };
            log!(output, "Spawn request sent: actor={actor_id:#06x}, param1={param1:#010x}{oarc_text}.");
        },
        Err(e) => log!(output, "WARNING: Could not send spawn request: {e}"),
    }
}

fn cmd_flag(args: &[&str], emulator: &mut Option<(Backend, usize)>, output: &EventSink) {
    let type_names: Vec<&str> = FLAG_TYPES.iter().map(|(n, _)| *n).collect();
    let op_names: Vec<&str> = FLAG_OPS.iter().map(|(n, _)| *n).collect();

    let flag_type = args.first().map(|a| a.to_lowercase()).unwrap_or_default();
    let operation = args.get(1).map(|a| a.to_lowercase()).unwrap_or_default();
    let flag_id_str = args.get(2).copied().unwrap_or("");
    let extra_str = args.get(3).copied().unwrap_or("");

    if flag_type.is_empty() || operation.is_empty() || flag_id_str.is_empty() {
        log!(output, "Usage: /flag <storyflag|sceneflag|itemflag|dungeonflag> <get|set|unset> <id|all> [value_or_scene]");
        log!(output, "  storyflag/itemflag: optional 4th arg is a VALUE (for counter flags, e.g. /flag itemflag set 0x1ED 99)");
        log!(output, "  sceneflag/dungeonflag: optional 4th arg is a SCENE INDEX (default: current scene)");
        log!(output, "Types: {}", type_names.join(", "));
        log!(output, "Ops:   {}", op_names.join(", "));
        return;
    }
    let Some(&(_, type_code)) = FLAG_TYPES.iter().find(|(n, _)| *n == flag_type) else {
        log!(output, "WARNING: Unknown flag type '{flag_type}'. Available: {}", type_names.join(", "));
        return;
    };
    let Some(&(_, op_code)) = FLAG_OPS.iter().find(|(n, _)| *n == operation) else {
        log!(output, "WARNING: Unknown operation '{operation}'. Available: {}", op_names.join(", "));
        return;
    };

    // --- "all" keyword ---
    if flag_id_str.eq_ignore_ascii_case("all") {
        let mut value: i64 = if operation == "set" { 1 } else { 0 };
        if !extra_str.is_empty() {
            match parse_int_auto(extra_str) {
                Some(v) => value = v,
                None => {
                    log!(output, "WARNING: Invalid value '{extra_str}'. Use decimal or 0x-prefixed hex.");
                    return;
                },
            }
        }
        let Some((mem, root_addr)) = require_emulator(emulator, output) else { return };
        set_all_flags(mem, root_addr, &flag_type, type_code, op_code, value as u16, output);
        return;
    }

    // --- Single flag ---
    let Some(flag_id) = parse_int_auto(flag_id_str) else {
        log!(output, "WARNING: Invalid flag id '{flag_id_str}'. Use decimal or 0x-prefixed hex.");
        return;
    };
    let mut value: i64 = if operation == "set" { 1 } else { 0 };
    let mut scene_index: u16 = ap_ipc::SCENE_INDEX_CURRENT;
    if !extra_str.is_empty() {
        let Some(extra) = parse_int_auto(extra_str) else {
            log!(output, "WARNING: Invalid value/scene '{extra_str}'. Use decimal or 0x-prefixed hex.");
            return;
        };
        if flag_type == "storyflag" || flag_type == "itemflag" {
            value = extra;
        } else {
            scene_index = extra as u16;
        }
    }

    let Some((mem, root_addr)) = require_emulator(emulator, output) else { return };
    match ipc_requests::flag_request(mem, root_addr, type_code, op_code, flag_id as u16, value as u16, scene_index) {
        Ok(result) => {
            let scene_text = if scene_index == ap_ipc::SCENE_INDEX_CURRENT {
                String::new()
            } else {
                format!(" (scene {scene_index})")
            };
            let verb = match operation.as_str() {
                "get" => "=",
                "set" => "set ->",
                _ => "unset ->",
            };
            log!(output, "{flag_type} {flag_id} ({flag_id:#X}){scene_text} {verb} {result}");
        },
        Err(e) => log!(
            output,
            "WARNING: Flag request failed or timed out ({e}). Ensure the emulator is connected and the game \
             is running with the mod loaded."
        ),
    }
}

/// `/flag <type> <op> all [value]`: one request per flag (storyflags
/// 0..2048, itemflags 0..1024, scene/dungeon flags 26 scenes x 128).
/// Blocks this worker thread for the duration (each request takes about a
/// game frame), so server events pause until it finishes. Setting flags
/// indiscriminately can break game progression.
fn set_all_flags(
    mem: &mut Backend,
    root_addr: usize,
    flag_type_name: &str,
    type_code: u8,
    op_code: u8,
    value: u16,
    output: &EventSink,
) {
    let plan: Vec<(u16, u16)> = match flag_type_name {
        "storyflag" => (0..2048u16).map(|id| (id, ap_ipc::SCENE_INDEX_CURRENT)).collect(),
        "itemflag" => (0..1024u16).map(|id| (id, ap_ipc::SCENE_INDEX_CURRENT)).collect(),
        "sceneflag" | "dungeonflag" => {
            (0..26u16).flat_map(|scene| (0..128u16).map(move |id| (id, scene))).collect()
        },
        other => {
            log!(output, "WARNING: Unsupported flag type for 'all': {other}");
            return;
        },
    };
    log!(
        output,
        "Running {} {flag_type_name} requests (value {value}). This blocks the client for a bit \
         and can break game progression...",
        plan.len()
    );
    for (i, (flag_id, scene)) in plan.iter().enumerate() {
        if let Err(e) = ipc_requests::flag_request(mem, root_addr, type_code, op_code, *flag_id, value, *scene) {
            log!(output, "WARNING: Stopped at {flag_type_name} {flag_id} (scene {scene}): {e}");
            return;
        }
        if i % 500 == 499 {
            vlog!("  {flag_type_name} progress: {}/{}", i + 1, plan.len());
        }
    }
    log!(output, "Finished processing all {flag_type_name}s (value {value}).");
}

fn cmd_warp(args: &[&str], emulator: &mut Option<(Backend, usize)>, output: &EventSink) {
    if args.is_empty() {
        log!(output, "Usage: /warp start");
        log!(output, "       /warp <stage name or stage id> [layer]");
        return;
    }

    let (mode, stage_code, layer, target_desc);
    if args[0].eq_ignore_ascii_case("start") {
        if args.len() > 1 {
            log!(output, "WARNING: /warp start doesn't take a layer argument, ignoring it");
        }
        mode = ap_ipc::WARP_MODE_START;
        stage_code = "";
        layer = 0xFFu8;
        target_desc = "start".to_string();
    } else {
        // Stage names can be multiple words ("Lanayru Mining Facility"); if
        // there's more than one token and the last is a number, it's the
        // optional layer.
        let mut tokens: Vec<&str> = args.to_vec();
        let mut layer_str = "";
        if tokens.len() > 1 && parse_int_auto(tokens[tokens.len() - 1]).is_some() {
            layer_str = tokens.pop().unwrap();
        }
        let target = tokens.join(" ");
        let Some(code) = stages::resolve_stage_code(&target) else {
            log!(
                output,
                "WARNING: Unknown stage '{target}'. Use a stage id (e.g. F000) or a name from the in-game map \
                 (e.g. Skyloft, Lanayru Mining Facility)."
            );
            return;
        };
        let mut layer_val = 0u8;
        if !layer_str.is_empty() {
            let n = parse_int_auto(layer_str).unwrap_or(0);
            if !(0..=255).contains(&n) {
                log!(output, "WARNING: Layer {n} out of range (0-255).");
                return;
            }
            layer_val = n as u8;
        }
        mode = ap_ipc::WARP_MODE_STAGE;
        stage_code = code;
        layer = layer_val;
        target_desc = if layer_str.is_empty() { code.to_string() } else { format!("{code} layer {layer_val}") };
    }

    let Some((mem, root_addr)) = require_emulator(emulator, output) else { return };
    match ipc_requests::warp_request(mem, root_addr, mode, stage_code, layer) {
        Ok(0) => log!(output, "Warping to {target_desc}..."),
        Ok(_) => log!(output, "WARNING: Warp request was rejected by the game (invalid state or destination)."),
        Err(e) => log!(
            output,
            "WARNING: Warp request failed or timed out ({e}). Ensure the emulator is connected and the game \
             is running with the mod loaded."
        ),
    }
}

fn cmd_go_mode(
    connection: &mut Option<Connection<SlotData>>,
    ap_connected: bool,
    emulator: &mut Option<(Backend, usize)>,
    reported_locations: &HashSet<i64>,
    output: &EventSink,
) {
    let Some(client) = connection.as_ref().and_then(|c| c.client()).filter(|_| ap_connected) else {
        log!(output, "Go Mode: no item requirements could be determined yet (connect to a slot first).");
        return;
    };

    // Owned item counts from everything the server has sent us...
    let mut owned: HashMap<String, i64> = HashMap::new();
    let mut seen: HashSet<(i64, i64, i64)> = HashSet::new(); // (location, sender slot, item id)
    for received in client.received_items() {
        *owned.entry(received.item().name().to_string()).or_insert(0) += 1;
        seen.insert((received.location().id(), received.sender().slot() as i64, received.item().id()));
    }

    // ...plus items of ours sitting in locations checked locally that the
    // server hasn't echoed back yet (slot_data's location_to_item_map).
    let own_slot = client.this_player().slot() as i64;
    let mut checked: HashSet<i64> = reported_locations.clone();
    checked.extend(client.checked_locations().map(|l| l.id()));
    let mut local_added = 0;
    for (&location, entry) in &client.slot_data().location_to_item_map {
        if entry.player != own_slot || !checked.contains(&location) {
            continue;
        }
        let code = if entry.item_id >= items::AP_CODE_BASE { entry.item_id } else { items::AP_CODE_BASE + entry.item_id };
        if seen.contains(&(location, own_slot, code)) {
            continue; // already counted from the server's list
        }
        if let Some(name) = items::go_mode_item_name(code) {
            *owned.entry(name.to_string()).or_insert(0) += 1;
            local_added += 1;
        }
    }
    if local_added > 0 {
        vlog!("[Go Mode] Counted {local_added} item(s) from locally checked locations not yet echoed by the server.");
    }

    // Boss-kill storyflags are read through the game (flag_request GET), so
    // this needs the emulator; without it dungeon bosses just count as not
    // defeated.
    let mut emulator_missing_logged = false;
    let mut boss_flag_set = |flag_id: u16| -> bool {
        match emulator.as_mut() {
            Some((mem, root_addr)) => ipc_requests::flag_request(
                mem,
                *root_addr,
                ap_ipc::FLAG_TYPE_STORYFLAG,
                ap_ipc::FLAG_OP_GET,
                flag_id,
                0,
                ap_ipc::SCENE_INDEX_CURRENT,
            )
            .map(|v| v != 0)
            .unwrap_or(false),
            None => {
                if !emulator_missing_logged {
                    emulator_missing_logged = true;
                    log!(output, "(Emulator not attached: dungeon boss progress can't be read.)");
                }
                false
            },
        }
    };

    let (requirements, notes) = go_mode::requirements(client.slot_data(), &owned, &mut boss_flag_set);
    if requirements.is_empty() {
        log!(output, "Go Mode: no item requirements could be determined yet (connect to a slot first).");
        return;
    }
    log!(output, "=== Go Mode Requirements ===");
    // Red: have nothing (0/X with X > 0). Yellow: some. Green: everything
    // (have >= need, which includes 0/0).
    for req in &requirements {
        let color = if req.met() {
            colors::SpanColor::Green
        } else if req.have <= 0 {
            colors::SpanColor::Red
        } else {
            colors::SpanColor::Yellow
        };
        let line = format!(
            "  {} {}: {}/{}",
            if req.met() { "[x]" } else { "[ ]" },
            req.label,
            req.have,
            req.need
        );
        send(output, WorkerEvent::Print(vec![LogSpan::new(line, color)]));
    }
    for note in notes {
        log!(output, "[Go Mode] {note}");
    }
}

fn cmd_received(connection: &mut Option<Connection<SlotData>>, ap_connected: bool, output: &EventSink) {
    let Some(client) = connection.as_ref().and_then(|c| c.client()).filter(|_| ap_connected) else {
        log!(output, "Not connected to a server yet.");
        return;
    };
    let items = client.received_items();
    if items.is_empty() {
        log!(output, "No items received yet.");
        return;
    }
    log!(output, "Received items ({}):", items.len());
    let skipped = items.len().saturating_sub(LIST_LINE_CAP);
    for received in items.iter().skip(skipped) {
        log!(output, "  {}. {} (from {})", received.index() + 1, received.item(), received.sender());
    }
    if skipped > 0 {
        log!(output, "  ...and {skipped} earlier item(s) not shown.");
    }
}

fn cmd_location_list(
    checked: bool,
    connection: &mut Option<Connection<SlotData>>,
    ap_connected: bool,
    output: &EventSink,
) {
    let Some(client) = connection.as_ref().and_then(|c| c.client()).filter(|_| ap_connected) else {
        log!(output, "Not connected to a server yet.");
        return;
    };
    let mut names: Vec<String> = if checked {
        client.checked_locations().map(|l| l.to_string()).collect()
    } else {
        client.unchecked_locations().map(|l| l.to_string()).collect()
    };
    names.sort();
    let label = if checked { "Checked" } else { "Missing" };
    if names.is_empty() {
        log!(output, "No {} locations.", label.to_lowercase());
        return;
    }
    log!(output, "{label} locations ({}):", names.len());
    for name in names.iter().take(LIST_LINE_CAP) {
        log!(output, "  {name}");
    }
    if names.len() > LIST_LINE_CAP {
        log!(output, "  ...and {} more not shown.", names.len() - LIST_LINE_CAP);
    }
}

fn cmd_players(connection: &mut Option<Connection<SlotData>>, ap_connected: bool, output: &EventSink) {
    let Some(client) = connection.as_ref().and_then(|c| c.client()).filter(|_| ap_connected) else {
        log!(output, "Not connected to a server yet.");
        return;
    };
    let mut players: Vec<_> = client.players().filter(|p| p.slot() != 0).collect();
    players.sort_by_key(|p| (p.team(), p.slot()));
    log!(output, "Players ({}):", players.len());
    for p in players {
        log!(output, "  {} {} ({}) — {}", p.slot(), p.alias(), p.name(), p.game());
    }
}
