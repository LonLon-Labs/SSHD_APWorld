//! `sshd-ap-client` — the Rust replacement for `SSHDClient.py` /
//! `process_memory.py`'s memory-interfacing role, now with an Iced GUI.
//!
//! # What this does today
//! 1. Finds a running supported emulator process.
//! 2. Attaches to it and scans ONCE for `ap_ipc::AP_IPC_MAGIC` to find
//!    `AP_IPC_ROOT` — no NSO-header scanning, no per-mailbox magic scans.
//! 3. Opens a connection to an Archipelago server via `archipelago_rs`.
//! 4. Runs a poll loop (intended to run once per "frame", same cadence
//!    idea as the game's own `main_loop_inject`) that:
//!    - drains Archipelago events (received items, prints, connection
//!      state changes),
//!    - applies received items to `item_buffer`,
//!    - polls all four location-check mechanisms (`locations.rs`'s
//!      custom flags, `goddess_chests.rs`, `beedle_shop.rs`,
//!      `boss_defeats.rs`) and unions/dedupes/reports the result,
//!    - reads `check_stats` to report check progress.
//!
//! By default this launches a small Iced GUI (`gui.rs`) — a
//! server/slot/password form, a Connect/Disconnect button, a status +
//! check-count tooltip, a scrolling log, and a persistent command bar —
//! driven by a background worker (`worker.rs`) that runs the steps above
//! and reports back through `WorkerEvent`s instead of `println!`. Pass
//! `--headless` for the original console-only behavior (useful for
//! scripting/testing without a display).
//!
//! # What's NOT done yet (see README.md in this workspace)
//! Everything from `SSHDClient.py`'s automated location/item detection is
//! now ported: item delivery and all four location-check mechanisms
//! (custom flags, goddess chests, Beedle's shop, boss defeats). Hints
//! aren't handled specially, but don't need to be — `!hint` and other
//! server commands go through as ordinary chat via the command bar (see
//! `worker.rs`'s `handle_command`), and the server's response shows up as
//! a normal `Event::Print` log line, same as the Python client's `!`
//! commands. There's no separate general shop mechanism beyond Beedle's
//! Airshop in the Python client to port. A PopTracker bridge was
//! attempted upstream but never finished, and isn't being ported here.

mod actorid;
mod beedle_shop;
mod bird_statues;
mod boss_defeats;
mod cheat_sync;
mod colors;
mod delivery;
mod go_mode;
mod goddess_chests;
mod goddess_cubes;
mod gui;
mod ipc_requests;
mod item_info;
mod items;
mod links;
mod locations;
mod stages;
mod theme;
mod worker;

use std::io::Write;
use std::thread;
use std::time::Duration;
use std::collections::HashSet;

use ap_ipc::{offsets, ApIpcRoot, AP_IPC_SUPPORTED_VERSION};
use archipelago_rs::{BounceOptions, Connection, ConnectionOptions, DeathLinkOptions, Error, Event};
use beedle_shop::BeedleShopPoller;
use goddess_chests::GoddessChestPoller;
use goddess_cubes::GoddessCubePoller;
use links::{LinkMonitor, LinkSignal};
use locations::{CustomFlagPoller, SlotData};
use process_memory::{find_ap_ipc_root, MemError, ProcessMemory, RootSearch, SUPPORTED_EMULATOR_NAMES};

#[cfg(target_os = "linux")]
use process_memory::linux::{find_process_by_names, LinuxProcessMemory as Backend};
#[cfg(target_os = "macos")]
use process_memory::macos::{find_process_by_names, MacOsProcessMemory as Backend};
#[cfg(target_os = "windows")]
use process_memory::windows::{find_process_by_names, WindowsProcessMemory as Backend};

/// Reads a little-endian `u64` from process memory. Shared by every
/// poller module that reads one of `AP_IPC_ROOT`'s exposed addresses
/// (`sceneflags_addr`, `dungeonflags_addr`, `tboxflags_addr`,
/// `static_tboxflags_addr`) — used by both `run_headless` below and
/// `worker.rs`.
pub(crate) fn read_u64(mem: &mut impl ProcessMemory, addr: usize) -> Result<u64, MemError> {
    let bytes = mem.read_bytes(addr, 8)?;
    Ok(u64::from_le_bytes(bytes.try_into().expect("read_bytes returned wrong length")))
}

/// Reads a little-endian `u16` from process memory. Currently only used
/// by `goddess_chests.rs` to read `AP_IPC_ROOT.current_scene_index`
/// (which scene `static_tboxflags`'s 4-byte working copy belongs to).
pub(crate) fn read_u16(mem: &mut impl ProcessMemory, addr: usize) -> Result<u16, MemError> {
    let bytes = mem.read_bytes(addr, 2)?;
    Ok(u16::from_le_bytes(bytes.try_into().expect("read_bytes returned wrong length")))
}

/// Reads a little-endian, signed `i64` from process memory. Used for the
/// `*_addr` fields in `AP_IPC_ROOT` (`sceneflags_addr`, `dungeonflags_addr`,
/// `tboxflags_addr`, `static_tboxflags_addr`), which the game side writes
/// as offsets RELATIVE to `AP_IPC_ROOT`'s own (guest) address rather than
/// absolute pointers -- see `ap_ipc::ApIpcRoot`'s field docs for why.
pub(crate) fn read_i64(mem: &mut impl ProcessMemory, addr: usize) -> Result<i64, MemError> {
    let bytes = mem.read_bytes(addr, 8)?;
    Ok(i64::from_le_bytes(bytes.try_into().expect("read_bytes returned wrong length")))
}

/// Resolves one of `AP_IPC_ROOT`'s `*_addr` fields (a signed offset
/// relative to `AP_IPC_ROOT`'s own guest address, stored at
/// `root_addr + field_offset`) into a HOST address the caller can pass to
/// `ProcessMemory::read_bytes`/`write_bytes`. Returns `None` for the `0`
/// sentinel (save file not loaded yet, or this field hasn't been refreshed
/// by the game side yet) -- 0 is never a real offset, since no target this
/// crate reads is ever located exactly at `AP_IPC_ROOT`'s own address.
/// Shared by `locations.rs`, `goddess_chests.rs`, and `boss_defeats.rs` so
/// the relative-offset -> host-address conversion lives in exactly one
/// place.
pub(crate) fn resolve_ipc_addr(
    mem: &mut impl ProcessMemory,
    root_addr: usize,
    field_offset: usize,
) -> Result<Option<usize>, MemError> {
    let relative = read_i64(mem, root_addr + field_offset)?;
    if relative == 0 {
        return Ok(None);
    }
    Ok(Some((root_addr as i64 + relative) as usize))
}

/// Performs one `flag_request` round trip (write request, wait for
/// `rust-additions` to service it on its next frame, read the response)
/// and returns `response_value`. Shared by `beedle_shop.rs` and both
/// `run_headless` and `worker.rs` — this is the same mechanism
/// `commands.rs::handle_flag_request` implements on the game side.
pub(crate) fn flag_request_get(
    mem: &mut impl ProcessMemory,
    root_addr: usize,
    flag_type: u8,
    flag_id: u16,
    scene_index: u16,
) -> Result<u32, MemError> {
    // The general get/set/unset implementation lives in `ipc_requests.rs`
    // (shared with the `/flag` command); this stays as the GET-only
    // convenience wrapper the location pollers already call.
    ipc_requests::flag_request(mem, root_addr, flag_type, ap_ipc::FLAG_OP_GET, flag_id, 0, scene_index)
}

/// Parsed startup arguments. Supports two forms so this binary works both
/// as a quick manual test tool and as something the Archipelago Launcher
/// can invoke:
/// - Archipelago's standard `CommonClient` convention:
///   `ap-client --connect <server:port> [--name <slot>] [--password <pw>]`
/// - A simpler positional form for manual testing:
///   `ap-client <server:port> <slot-name> [password]`
///
/// None of these are required up front in GUI mode (the default) —
/// whatever's given just pre-fills the connect form (and triggers an
/// auto-connect if both a server and a slot were given). `--headless`
/// skips the GUI and falls back to the original blocking console loop,
/// where a missing server is a hard error and a missing slot name still
/// prompts on stdin.
struct StartupArgs {
    server:   Option<String>,
    slot:     Option<String>,
    password: Option<String>,
    headless: bool,
}

fn parse_args() -> StartupArgs {
    let raw: Vec<String> = std::env::args().skip(1).collect();

    let mut server: Option<String> = None;
    let mut slot: Option<String> = None;
    let mut password: Option<String> = None;
    let mut headless = false;
    let mut positional: Vec<String> = Vec::new();
    let mut iter = raw.into_iter().peekable();
    while let Some(arg) = iter.next() {
        match arg.as_str() {
            "--connect" => server = iter.next(),
            "--name" => slot = iter.next(),
            "--password" => password = iter.next(),
            "--headless" => headless = true,
            other => positional.push(other.to_string()),
        }
    }

    // Fall back to positional form for whatever flags weren't given.
    let server = server.or_else(|| positional.first().cloned());
    let slot = slot.or_else(|| positional.get(1).cloned());
    let password = password.or_else(|| positional.get(2).cloned());

    StartupArgs { server, slot, password, headless }
}

fn main() -> iced::Result {
    colors::enable_ansi();
    let args = parse_args();

    if args.headless {
        run_headless(args);
        return Ok(());
    }

    let auto_connect = args.server.is_some() && args.slot.is_some();
    let flags = gui::Flags {
        server:   args.server.unwrap_or_default(),
        slot:     args.slot.unwrap_or_default(),
        password: args.password.unwrap_or_default(),
        auto_connect,
    };

    iced::application("Skyward Sword HD — Archipelago Client", gui::App::update, gui::App::view)
        .subscription(gui::App::subscription)
        .theme(gui::App::theme)
        .window(iced::window::Settings {
            size: iced::Size::new(702.0, 553.0),
            min_size: Some(iced::Size::new(700.0, 500.0)),
            ..Default::default()
        })
        .run_with(move || gui::App::new(flags))
}

/// The original console-only client, preserved behind `--headless` for
/// scripting/testing without a display. See `worker.rs` for the
/// GUI-driving reimplementation of this same loop.
fn run_headless(args: StartupArgs) {
    let server = args.server.unwrap_or_else(|| {
        eprintln!(
            "usage: ap-client --headless --connect <server:port> [--name <slot>] [--password <pw>]"
        );
        eprintln!("   or: ap-client --headless <server:port> [slot-name] [password]");
        std::process::exit(1);
    });

    let slot_name = args.slot.unwrap_or_else(|| {
        print!("Enter slot name: ");
        std::io::stdout().flush().ok();
        let mut line = String::new();
        std::io::stdin().read_line(&mut line).expect("failed to read slot name from stdin");
        line.trim().to_string()
    });

    let password = args.password;

    println!("Looking for a supported emulator ({SUPPORTED_EMULATOR_NAMES:?})...");
    let pid = loop {
        if let Some(pid) = find_process_by_names(SUPPORTED_EMULATOR_NAMES) {
            break pid;
        }
        print!(".");
        std::io::stdout().flush().ok();
        thread::sleep(Duration::from_secs(1));
    };
    println!("\nFound emulator process (pid {pid}). Attaching...");

    let mut mem = Backend::attach(pid as _).expect("failed to attach to emulator process");

    println!("Looking for AP_IPC_ROOT (guest-RAM mappings first; the first copy the game is actually updating wins)...");
    let mut root_search = RootSearch::new();
    let root_addr = loop {
        match find_ap_ipc_root(&mut mem, &mut root_search) {
            Ok(addr) => break addr,
            Err(e) => {
                eprintln!("  not found yet ({e}) — is Skyward Sword HD running with the mod loaded?");
                thread::sleep(Duration::from_secs(2));
            },
        }
    };
    println!("Found AP_IPC_ROOT at {root_addr:#x}");

    let version = u16::from_le_bytes(
        mem.read_bytes(root_addr + offsets::VERSION, 2)
            .expect("read version")
            .try_into()
            .unwrap(),
    );
    if version != AP_IPC_SUPPORTED_VERSION {
        eprintln!(
            "WARNING: game reports AP_IPC layout version {version}, this client expects \
             {AP_IPC_SUPPORTED_VERSION}. The mailbox layouts may have drifted — update \
             ap-ipc/src/lib.rs to match ipc.rs before trusting anything below."
        );
    }

    println!("Connecting to Archipelago server {server} as '{slot_name}'...");
    let mut connection: Connection<SlotData> = Connection::new(
        server,
        slot_name.as_str(),
        Some("Skyward Sword HD"),
        password
            .map(|p| ConnectionOptions::new().password(p))
            .unwrap_or_else(ConnectionOptions::new),
    );

    // Track how many received items we've already pushed into the game's
    // item_buffer mailbox, mirroring the `index` field on
    // Event::ReceivedItems (see archipelago_rs's synchronization docs).
    let mut next_item_index: usize = 0;

    // Built once slot_data arrives (on Event::Connected) — see locations.rs.
    let mut location_poller: Option<CustomFlagPoller> = None;
    let mut goddess_chest_poller: Option<GoddessChestPoller> = None;
    let mut goddess_cube_poller: Option<GoddessCubePoller> = None;
    // Beedle's shop needs no slot_data (its 10-entry table is hardcoded),
    // so it can be built up front.
    let mut beedle_poller = BeedleShopPoller::new();

    // AP location codes already reported to the server (via mark_checked)
    // by ANY of the four check mechanisms below, so none of them re-poll
    // or re-report something another one already handled.
    let mut reported_locations: HashSet<i64> = HashSet::new();
    let mut loop_tick: u64 = 0;

    // DeathLink / BreathLink state, matching worker.rs: tags the slot asked
    // for (plus any the player enabled some other way, which headless mode
    // has no command bar to do, but keeping the set matches worker.rs's
    // shape) and the health/stamina watcher.
    let mut active_tags: HashSet<String> = HashSet::from(["AP".to_string()]);
    let mut link_monitor = LinkMonitor::new();

    println!("Entering poll loop (Ctrl+C to quit)...");
    loop {
        // ── 1. Drain Archipelago server events ──────────────────────────
        for event in connection.update() {
            match event {
                Event::Connected => {
                    println!("[AP] Connected.");
                    if let Some(client) = connection.client() {
                        let slot_data = client.slot_data();

                        let custom_flags = slot_data.custom_flag_to_location.clone();
                        println!(
                            "[AP] Loaded {} custom-flag location mappings from slot_data.",
                            custom_flags.len()
                        );
                        location_poller = Some(CustomFlagPoller::new(custom_flags));

                        let goddess_chests = slot_data.goddess_chest_scene_flags.clone();
                        println!(
                            "[AP] Loaded {} goddess chest location mappings from slot_data.",
                            goddess_chests.len()
                        );
                        goddess_chest_poller = Some(GoddessChestPoller::new(goddess_chests));

                        let goddess_cubes = slot_data.goddess_cube_story_flags.clone();
                        println!(
                            "[AP] Loaded {} goddess cube location mappings from slot_data.",
                            goddess_cubes.len()
                        );
                        goddess_cube_poller = Some(GoddessCubePoller::new(goddess_cubes));

                        // Seed `reported_locations` with whatever the server already
                        // knows we've checked (e.g. from a previous session), so the
                        // pollers' own "recover pre-existing progress on the first poll"
                        // behavior doesn't re-report (and cause a re-broadcast of)
                        // locations the server already has.
                        let already_known: Vec<i64> =
                            client.checked_locations().map(|loc| loc.id()).collect();
                        println!(
                            "[AP] Server already knows {} location(s) are checked.",
                            already_known.len()
                        );
                        reported_locations.extend(already_known);

                        match cheat_sync::apply_cheat_flags(&mut mem, root_addr, slot_data) {
                            Ok(active) if !active.is_empty() => {
                                println!("[AP] Active cheats from slot_data: {}", active.join(", "));
                            },
                            Ok(_) => {},
                            Err(e) => eprintln!("[IPC] failed to apply cheat flags from slot_data: {e}"),
                        }

                        match item_info::write_item_info_table(&mut mem, root_addr, &slot_data.item_info_for_game()) {
                            Ok(count) => {
                                println!("[AP] Wrote {count} AP item info entries for textbox display.");
                            },
                            Err(e) => eprintln!("[IPC] failed to write AP item info table: {e}"),
                        }

                        // Fresh connection: restart the link monitor's grace period.
                        link_monitor = LinkMonitor::new();
                        let mut want_tags: Vec<&'static str> = Vec::new();
                        if slot_data.option_death_link != 0 {
                            want_tags.push("DeathLink");
                        }
                        if slot_data.option_breath_link != 0 {
                            want_tags.push("BreathLink");
                        }
                        if !want_tags.is_empty() {
                            for t in &want_tags {
                                active_tags.insert(t.to_string());
                            }
                        }
                    }
                    // update_connection needs `client_mut`, so this is a separate
                    // borrow from the `client()` block above.
                    if let Some(client) = connection.client_mut() {
                        if active_tags.len() > 1 {
                            match client.update_connection(None, Some(active_tags.iter().map(|t| t.as_str()))) {
                                Ok(()) => println!("[AP] Enabled tags: {}", active_tags.iter().cloned().collect::<Vec<_>>().join(", ")),
                                Err(e) => eprintln!("[AP] Failed to enable link tags: {e}"),
                            }
                        }
                    }
                },
                Event::DeathLink { source, cause, .. } => {
                    let alias = connection
                        .client()
                        .map(|c| c.this_player().alias().to_string())
                        .unwrap_or_default();
                    if active_tags.contains("DeathLink")
                        && source != alias
                        && source != slot_name
                        && !link_monitor.death_sent_recently()
                    {
                        let why = cause.unwrap_or_else(|| format!("{source} died."));
                        println!("[DeathLink] {why}");
                        match links::request_kill(&mut mem, root_addr) {
                            Ok(()) => link_monitor.note_kill_requested(),
                            Err(e) => eprintln!("[DeathLink] failed to kill Link: {e}"),
                        }
                    }
                },
                Event::Bounce { tags, data, .. } => {
                    let is_breath = tags
                        .as_ref()
                        .is_some_and(|t| t.iter().any(|x| x.as_str() == "BreathLink"));
                    if is_breath && active_tags.contains("BreathLink") {
                        let alias = connection
                            .client()
                            .map(|c| c.this_player().alias().to_string())
                            .unwrap_or_default();
                        let field = |k: &str| {
                            data.as_ref().and_then(|d| d.get(k)).and_then(|v| v.as_str()).map(str::to_string)
                        };
                        let source = field("source").unwrap_or_else(|| "Someone".to_string());
                        if source != alias && source != slot_name && !link_monitor.breath_sent_recently() {
                            let why = field("cause").unwrap_or_else(|| format!("{source} ran out of breath."));
                            println!("[BreathLink] {why}");
                            match links::request_drain(&mut mem, root_addr) {
                                Ok(()) => link_monitor.note_drain_requested(),
                                Err(e) => eprintln!("[BreathLink] failed to drain stamina: {e}"),
                            }
                        }
                    }
                },
                Event::Print(print) => {
                    let spans = colors::print_to_spans(&print, &slot_name);
                    println!("[AP] {}", colors::spans_to_ansi(&spans));
                },
                Event::Error(err) => {
                    // `Error::Elsewhere` is a placeholder used when the real error is
                    // stashed in `Connection::state()` instead -- see worker.rs's
                    // matching fix for the full explanation.
                    let message = if matches!(err, Error::Elsewhere) {
                        connection.err().to_string()
                    } else {
                        err.to_string()
                    };
                    eprintln!("[AP] Error: {message}");
                },
                // Event::ReceivedItems just tells us the list grew; the
                // actual draining happens unconditionally below so that an
                // item_buffer-full retry isn't stuck waiting for another
                // ReceivedItems event that may never come.
                _ => {},
            }
        }

        // ── 1b. Apply any received items not yet queued into item_buffer ──
        // Runs every loop tick (not just when a new ReceivedItems event
        // fires) so a "buffer full" retry actually gets retried.
        if let Some(client) = connection.client() {
            let received_items = client.received_items();
            while next_item_index < received_items.len() {
                let received = &received_items[next_item_index];

                // Precollected / start-inventory items (location id -2,
                // Archipelago's well-known "Server" location) are already
                // baked into the save file by the sshd-rando patches, so
                // they must NOT be delivered again via the item_buffer
                // mailbox -- mirrors SSHDClient.py's `is_start_inventory`
                // check.
                if received.location().id() == -2 {
                    println!(
                        "[AP] Received item #{next_item_index}: {} → start-inventory item, \
                         already in save file, skipping delivery",
                        received.item()
                    );
                    next_item_index += 1;
                    continue;
                }

                let ap_code = received.item().id();
                match items::original_id_for_ap_code(ap_code) {
                    Some(original_id) => {
                        match write_item_to_buffer(&mut mem, root_addr, original_id) {
                            Ok(true) => {
                                println!(
                                    "[AP] Received item #{next_item_index}: {} → queued \
                                     (game item id {original_id})",
                                    received.item()
                                );
                                next_item_index += 1;
                            },
                            Ok(false) => break, // buffer full — retry next tick, don't spam logs
                            Err(e) => {
                                eprintln!(
                                    "[AP] Received item #{next_item_index}: {} → failed to \
                                     write to item_buffer: {e}",
                                    received.item()
                                );
                                break; // retry rather than skip on a transient I/O error
                            },
                        }
                    },
                    None => {
                        // Event-only ID (Game Beatable / Goddess Cubes) or an
                        // unrecognized code — nothing to deliver in-game.
                        println!(
                            "[AP] Received item #{next_item_index}: {} → event-only or \
                             unknown AP code {ap_code}, not deliverable via item_buffer",
                            received.item()
                        );
                        next_item_index += 1;
                    },
                }
            }
        }

        // ── 1c. DeathLink / BreathLink SENDING ────────────────────────────
        // Watches Link's health/stamina and sends one bounce per event; see
        // links.rs for latching and echo suppression. Polled even with both
        // tags off so the latches stay current.
        match link_monitor.poll(&mut mem, root_addr) {
            Ok(signals) => {
                for signal in signals {
                    let tag = match signal {
                        LinkSignal::Death => "DeathLink",
                        LinkSignal::Breath => "BreathLink",
                    };
                    if !active_tags.contains(tag) {
                        continue;
                    }
                    let Some(client) = connection.client_mut() else { continue };
                    let alias = client.this_player().alias().to_string();
                    let place = links::stage_display_name(&link_monitor.stage_code);
                    match signal {
                        LinkSignal::Death => {
                            let cause = format!("{alias} died in {place}.");
                            match client.death_link(DeathLinkOptions::new().cause(cause.clone())) {
                                Ok(()) => {
                                    link_monitor.note_death_sent();
                                    println!("[DeathLink] Sent: {cause}");
                                },
                                Err(e) => eprintln!("[DeathLink] send failed: {e}"),
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
                                    link_monitor.note_breath_sent();
                                    println!("[BreathLink] Sent: {cause}");
                                },
                                Err(e) => eprintln!("[BreathLink] send failed: {e}"),
                            }
                        },
                    }
                }
            },
            Err(e) => eprintln!("[IPC] link monitor poll failed: {e}"),
        }

        // ── 1d. Poll all four location-check mechanisms ──────────────────
        // Each returns AP location codes newly detected as checked; we
        // union them, filter anything already reported (belt-and-braces —
        // each poller already does this internally too), and report the
        // rest to the server in one `mark_checked` call.
        let mut newly_checked_all: Vec<i64> = Vec::new();
        let already_checked = |code: i64| reported_locations.contains(&code);

        if let Some(poller) = location_poller.as_mut() {
            match poller.poll(&mut mem, root_addr, &already_checked) {
                Ok(codes) => newly_checked_all.extend(codes),
                Err(e) => eprintln!("[IPC] custom-flag location poll failed: {e}"),
            }
        }
        if let Some(poller) = goddess_chest_poller.as_mut() {
            match poller.poll(&mut mem, root_addr, &already_checked) {
                Ok(codes) => newly_checked_all.extend(codes),
                Err(e) => eprintln!("[IPC] goddess chest poll failed: {e}"),
            }
        }
        if let Some(poller) = goddess_cube_poller.as_mut() {
            match poller.poll(&mut mem, root_addr, &already_checked) {
                Ok(codes) => newly_checked_all.extend(codes),
                Err(e) => eprintln!("[IPC] goddess cube poll failed: {e}"),
            }
        }
        match beedle_poller.poll(&mut mem, root_addr, &already_checked) {
            Ok(codes) => newly_checked_all.extend(codes),
            Err(e) => eprintln!("[IPC] Beedle's shop poll failed: {e}"),
        }
        match boss_defeats::poll(&mut mem, root_addr, &already_checked) {
            Ok(codes) => newly_checked_all.extend(codes),
            Err(e) => eprintln!("[IPC] boss defeat poll failed: {e}"),
        }

        if !newly_checked_all.is_empty() {
            newly_checked_all.sort_unstable();
            newly_checked_all.dedup();
            println!(
                "[AP] {} location(s) checked: {newly_checked_all:?}",
                newly_checked_all.len()
            );
            for &code in &newly_checked_all {
                reported_locations.insert(code);
            }
            if let Some(client) = connection.client_mut() {
                if let Err(e) = client.mark_checked(newly_checked_all) {
                    eprintln!("[AP] mark_checked failed: {e}");
                }
            }
        }

        // ── 2. Periodic check-count status (~every 5s at 60 Hz) ──────────
        loop_tick = loop_tick.wrapping_add(1);
        // Keep the in-game help menu's check counts current (~2x/second).
        if loop_tick % 30 == 0 {
            if let Some(client) = connection.client() {
                let mut all_checked = reported_locations.clone();
                all_checked.extend(client.checked_locations().map(|l| l.id()));
                let own_slot = client.this_player().slot() as i64;
                if let Err(e) = write_check_stats(&mut mem, root_addr, client.slot_data(), &all_checked, own_slot) {
                    eprintln!("[IPC] failed to write check stats: {e}");
                }
            }
        }
        if loop_tick % 300 == 0 {
            if let Ok((checked, total)) = read_check_stats(&mut mem, root_addr) {
                if total > 0 {
                    println!("[Status] Checks: {checked}/{total}");
                }
            }
        }

        thread::sleep(Duration::from_millis(16)); // ~60 Hz, matching the game's frame rate
    }
}

/// Writes `original_id` into the first empty slot of `AP_IPC_ROOT.item_buffer`
/// (skipping slot 0, which is a reserved sentinel — see `EMPTY_ARCHIPELAGO_
/// ITEM_BUFFER` in item.rs). Returns `Ok(true)` if written, `Ok(false)` if
/// every slot is currently occupied (caller should retry later — the game
/// drains one slot per frame in `archipelago_check_item_buffer`).
///
/// Reads the whole buffer in one call and scans it locally rather than
/// issuing one read per slot (which would be up to 1023 separate
/// ptrace/ReadProcessMemory calls per item on a full buffer). Shared by
/// `run_headless` and `worker.rs`.
pub(crate) fn write_item_to_buffer(
    mem: &mut impl ProcessMemory,
    root_addr: usize,
    original_id: u16,
) -> Result<bool, MemError> {
    let buffer_addr = root_addr + offsets::ITEM_BUFFER;
    let buffer_bytes = mem.read_bytes(
        buffer_addr,
        ap_ipc::ARCHIPELAGO_BUFFER_SIZE * std::mem::size_of::<ap_ipc::ArchipelagoItemSlot>(),
    )?;

    for i in 1..ap_ipc::ARCHIPELAGO_BUFFER_SIZE {
        let slot_offset = i * std::mem::size_of::<ap_ipc::ArchipelagoItemSlot>();
        let current_id = buffer_bytes[slot_offset]; // item_id is the slot's first byte
        if current_id == 0 {
            // The game's item id is 9 bits wide: low byte in `item_id`, high
            // byte in `item_id_hi`. A slot is pending when the low byte is
            // non-zero, which `items::original_id_for_ap_code` guarantees
            // (it never returns 256 or 512).
            let slot = ap_ipc::ArchipelagoItemSlot {
                item_id:    (original_id & 0xFF) as u8,
                flags:      0,
                _reserved:  0,
                item_id_hi: (original_id >> 8) as u8,
            };
            mem.write_bytes(buffer_addr + slot_offset, &ap_ipc::bytes::write(&slot))?;
            return Ok(true);
        }
    }
    Ok(false)
}

/// Shared by `run_headless` and `worker.rs`. Returns `MemError` rather
/// than a boxed error trait object on purpose: the boxed form isn't
/// `Send`, and `worker.rs` holds this call's result across an `.await`
/// point, which requires everything live across it to be `Send` (see the
/// comment on `worker::read_check_stats`'s predecessor for the compile
/// error this caused before).
pub(crate) fn read_check_stats(mem: &mut impl ProcessMemory, root_addr: usize) -> Result<(u16, u16), MemError> {
    let addr = root_addr + offsets::CHECK_STATS;
    let raw = mem.read_bytes(addr, std::mem::size_of::<ap_ipc::ApCheckStats>())?;
    let stats: ap_ipc::ApCheckStats = ap_ipc::bytes::read(&raw);
    // Copy out of the packed struct before doing arithmetic.
    let (normal_checked, normal_total) = (stats.normal_checked, stats.normal_total);
    let (ap_checked, ap_total) = (stats.ap_checked, stats.ap_total);
    Ok((normal_checked.saturating_add(ap_checked), normal_total.saturating_add(ap_total)))
}

/// Port of `SSHDClient.py`'s `_update_ap_check_stats`: writes the location
/// check counts into `AP_IPC_ROOT.check_stats` (after the 4-byte magic) so
/// the game's in-game Help menu (see `lyt.rs` on the game side) can show them.
/// The game only READS this mailbox; if the client never writes it, the help
/// text shows 0/0 everywhere.
///
/// Layout written (little-endian u16 x4): normal_checked, normal_total,
/// ap_checked, ap_total, where "ap" locations are those whose flag appears
/// in `slot_data.ap_item_info` (cross-world items) and "normal" is the rest
/// of `custom_flag_to_location`. `all_checked` should be the union of the
/// server's checked locations and everything we've reported.
///
/// Returns `Ok(None)` (writing nothing) until slot_data has location data,
/// else `Ok(Some((checked, total)))` over all counted locations.
pub(crate) fn write_check_stats(
    mem: &mut impl ProcessMemory,
    root_addr: usize,
    slot_data: &SlotData,
    all_checked: &HashSet<i64>,
    own_slot: i64,
) -> Result<Option<(u16, u16)>, MemError> {
    let Some(counts) = check_counts(slot_data, all_checked, own_slot) else {
        return Ok(None);
    };

    let clamp = |n: usize| n.min(u16::MAX as usize) as u16;
    let mut data = Vec::with_capacity(8);
    for v in [counts.normal_checked, counts.normal_total, counts.ap_checked, counts.ap_total] {
        data.extend_from_slice(&clamp(v).to_le_bytes());
    }
    // +4 skips the magic, which belongs to the game.
    mem.write_bytes(root_addr + offsets::CHECK_STATS + 4, &data)?;

    Ok(Some((clamp(counts.normal_checked + counts.ap_checked), clamp(counts.normal_total + counts.ap_total))))
}

/// The four numbers shown in the in-game help menu.
#[derive(Debug, PartialEq, Eq)]
pub(crate) struct CheckCounts {
    pub normal_checked: usize,
    pub normal_total:   usize,
    pub ap_checked:     usize,
    pub ap_total:       usize,
}

/// Counts every location this client can report: custom-flag locations,
/// goddess chests, decoupled goddess cubes, Beedle's Airshop and boss
/// defeats (deduped by location code, since the sources can overlap).
/// "ap" locations are those holding an item that belongs to another
/// player -- either listed in `ap_item_info` (looked up through its custom
/// flag) or in `location_to_item_map` with an owner other than `own_slot`.
///
/// Returns `None` until slot_data has location data.
pub(crate) fn check_counts(
    slot_data: &SlotData,
    all_checked: &HashSet<i64>,
    own_slot: i64,
) -> Option<CheckCounts> {
    let mut all_codes: HashSet<i64> = slot_data.custom_flag_to_location.values().copied().collect();
    if all_codes.is_empty() {
        return None;
    }
    all_codes.extend(slot_data.goddess_chest_scene_flags.keys().copied());
    all_codes.extend(slot_data.goddess_cube_story_flags.keys().copied());
    all_codes.extend(beedle_shop::BEEDLE_STORYFLAG_TO_LOCATION.iter().map(|&(_, code)| code));
    all_codes.extend(boss_defeats::location_codes());

    let mut ap_codes: HashSet<i64> = slot_data
        .ap_item_info
        .keys()
        .filter_map(|flag_id| slot_data.custom_flag_to_location.get(flag_id).copied())
        .collect();
    ap_codes.extend(
        slot_data
            .location_to_item_map
            .iter()
            .filter(|(_, item)| item.player != own_slot)
            .map(|(&code, _)| code),
    );
    ap_codes.retain(|code| all_codes.contains(code));

    let ap_total = ap_codes.len();
    let ap_checked = ap_codes.iter().filter(|c| all_checked.contains(c)).count();
    let total_checked = all_codes.iter().filter(|c| all_checked.contains(c)).count();

    Some(CheckCounts {
        normal_checked: total_checked.saturating_sub(ap_checked),
        normal_total:   all_codes.len().saturating_sub(ap_total),
        ap_checked,
        ap_total,
    })
}

#[cfg(test)]
mod check_count_tests {
    use super::*;
    use crate::locations::LocationItem;

    fn slot_data() -> SlotData {
        let mut sd = SlotData::default();
        sd.custom_flag_to_location.insert(1, 100);
        sd.custom_flag_to_location.insert(2, 101);
        sd.goddess_chest_scene_flags.insert(200, (1, 1));
        sd.goddess_cube_story_flags.insert(300, 227);
        sd
    }

    #[test]
    fn none_until_slot_data_has_locations() {
        assert_eq!(check_counts(&SlotData::default(), &HashSet::new(), 1), None);
    }

    #[test]
    fn counts_chests_cubes_beedle_and_bosses() {
        let sd = slot_data();
        let c = check_counts(&sd, &HashSet::new(), 1).unwrap();
        let extra = beedle_shop::BEEDLE_STORYFLAG_TO_LOCATION.len() + boss_defeats::location_codes().count();
        assert_eq!(c.normal_total, 4 + extra);
        assert_eq!(c.ap_total, 0);
    }

    #[test]
    fn other_players_items_count_as_ap() {
        let mut sd = slot_data();
        sd.location_to_item_map.insert(300, LocationItem { item_id: 5, player: 2 });
        sd.location_to_item_map.insert(100, LocationItem { item_id: 6, player: 1 });
        let checked: HashSet<i64> = HashSet::from([300, 100]);
        let c = check_counts(&sd, &checked, 1).unwrap();
        assert_eq!(c.ap_total, 1);
        assert_eq!(c.ap_checked, 1);
        assert_eq!(c.normal_checked, 1);
    }
}

// Keeping the full `ApIpcRoot` type referenced here (via this size assert)
// is what guarantees `ap-ipc`'s layout hasn't silently drifted from
// `ipc.rs` on the game side, even though the functions above talk to
// individual mailboxes via `offsets::*` + raw byte slices rather than the
// struct directly.
const _: () = assert!(std::mem::size_of::<ApIpcRoot>() == offsets::TOTAL_SIZE);
