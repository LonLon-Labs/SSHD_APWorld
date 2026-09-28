# sshd-ap-client (Rust)

Rust replacement for the memory-interfacing half of `SSHDClient.py` /
`process_memory.py`. Talks to the Archipelago server AND to the game, and
retires signature-scanning-for-a-base-address plus the seven separate
per-mailbox magic scans in favor of one scan for `AP_IPC_ROOT`.

## Crates

- **`ap-ipc`** — byte-for-byte mirror of `AP_IPC_ROOT` (defined in
  `sshd-rando-backend/asm/additions/rust-additions/src/ipc.rs`). Pure data
  + safe (de)serialization helpers. No I/O.
  **Status: builds and passes tests in this environment (Rust 1.75).**
- **`process-memory`** — cross-platform process attach/read/write/scan.
  Faithful port of `process_memory.py`'s Linux (`/proc/<pid>/mem` +
  ptrace-attach-and-detach) and Windows (`ReadProcessMemory` /
  `WriteProcessMemory` / `VirtualQueryEx` via `windows-sys`) backends.
  **Status: Linux path builds AND is exercised by a real test
  (`can_attach_to_self_and_read_own_memory`) in this environment. The
  Windows path is written against the real `windows-sys` API shapes but
  has NOT been compiled anywhere — there's no Windows target available
  in the environment this was built in. Compile it on a Windows machine
  (`cargo check --target x86_64-pc-windows-msvc`) before relying on it.**
- **`ap-client`** — the actual bridge binary: finds the emulator, attaches,
  scans once for `AP_IPC_MAGIC`, connects to an Archipelago server via the
  `archipelago_rs` crate, maps received items to game item IDs (`items.rs`),
  writes them into `item_buffer`, polls for completed location checks
  (`locations.rs`), and reports them to the server — either through a
  small Iced GUI (`gui.rs` + `worker.rs`, the default) or headlessly via
  `--headless` (`run_headless` in `main.rs`). See "GUI (Iced)" below.
  **Status: written against `archipelago_rs` v3.0.1's real, published
  source (I downloaded and read it directly rather than guessing the
  API), and its own logic — including `items.rs` and `locations.rs` —
  has been type-checked in this environment against a hand-written stub
  that mirrors `archipelago_rs`'s real API 1:1 (`Connection`, `Client`,
  `Event`, `slot_data()`, `mark_checked()`, etc.). It could NOT be
  compiled against the REAL `archipelago_rs` crate here — its dependency
  tree requires a Rust/Cargo new enough to support the `edition2024`
  Cargo feature, and this environment only has 1.75 available via `apt`.
  The Iced GUI (`gui.rs`, `worker.rs`) is new and, like the rest of this
  bullet, has NOT been compiled anywhere in this environment either —
  there's no windowing/GPU target available here to build against. On
  your machine, with a normal up-to-date toolchain (`rustup update`),
  this should just build — please run `cargo build` and fix anything
  that comes up before trusting it.**
- **`items.rs`** (inside `ap-client`) — AP item code → game `original_id`
  table, mechanically generated from `Items.py`'s `ITEM_TABLE` (206
  entries) via a script, not hand-transcribed. **Status: fully tested in
  isolation in this environment** (sortedness, known-item lookups, and
  that the 28 event-only IDs — `Game Beatable` + 27 Goddess Cubes, whose
  `original_id` exceeds `u8::MAX` — correctly return `None` rather than a
  silently-truncated wrong byte).
- **`locations.rs`** (inside `ap-client`) — the majority-case location-check
  mechanism ("custom flags"), ported from `SSHDClient.py`'s
  `check_custom_flags`. Batch-reads the save file's sceneflag/dungeonflag
  arrays directly (via addresses `rust-additions` now exposes in
  `AP_IPC_ROOT`, see below) and diffs against previously-seen state.
  Location-to-flag mapping comes from the AP server's `slot_data` on
  connect, not a static table. Also owns `SlotData` itself, since the
  goddess-chest mechanism below reads from it too. **Status: the
  bit-decoding logic (`ap_ipc::custom_flag::decode`) and slot_data
  parsing are unit-tested in this environment; the live batch-read/diff
  loop is untested against a real game since I have no way to run one
  here.**
- **`goddess_chests.rs`** — ported from `check_goddess_chest_flags`.
  Batch-reads `FA.tboxflags` (exposed via a third address,
  `tboxflags_addr`) the same way `locations.rs` reads scene/dungeon
  flags. Deliberately simplified vs. Python: only reads the persistent
  save-file copy, not the in-RAM "current scene" working copy, so a
  check may show up on leaving the room rather than the instant the
  chest opens — see the module doc for what closing that gap would take.
  **Status: bit-math unit-tested; live behavior unverified.**
- **`beedle_shop.rs`** — ported from `check_beedle_shop_storyflags`, using
  the existing `flag_request` mailbox (a `STORYFLAG`/`GET` round trip per
  entry) rather than a new exposed address, since which storyflag IDs are
  plain booleans vs. multi-bit counters is knowledge only `flag.rs` has.
  Throttled by wall-clock time (every few seconds) rather than by
  checking the player's current stage, trading a little unnecessary
  polling for not needing to expose the current stage name too.
  **Status: table-shape unit-tested; live behavior unverified.**
- **`boss_defeats.rs`** — ported from `check_boss_defeat_flags`: a static
  6-entry (scene, byte, bitmask) table, reusing `sceneflags_addr`. No
  slot_data, no internal state — just "is this bit set". **Status:
  table-shape unit-tested; live behavior unverified.**

## GUI (Iced)

Launching `ap-client` with no `--headless` flag opens a `1404×1106` window
(built with [`iced`](https://iced.rs/) 0.13) instead of dropping into the
console loop. Its layout deliberately mirrors `kvui.py`'s
`GameManager.build()` — the KivyMD window `SSHDClient.py` opens via
Archipelago's own `CommonContext.run_gui()` — top to bottom:

1. A connect bar: an info-icon + "Server:" label (hover it for a
   tooltip, like kvui's `ServerLabel`), an address field pre-filled with
   `archipelago.gg:` exactly like kvui's does when no `--connect` is
   given, and a Connect/Disconnect button.
2. A slot name + password row. kvui doesn't have this in its connect bar
   at all — that client gets the slot name from `--name`/a startup
   prompt and the password via its `/connect` text command — but since
   this client's command bar doesn't get evaluated until the user types
   into it (see below), they're a secondary row right under the connect
   bar so they're visible before that.
3. A thin progress strip (kvui: `MDLinearProgressIndicator`), colored by
   connection status (accent while connecting, green once connected, red
   on error).
4. A single-tab bar over the log (kvui: `MDNavigationBar` — this client
   only ever has the one "Archipelago" logger, so there's only one tab,
   filling the full width rather than kvui's per-tab pills).
5. A scrollable, dark, borderless, color-coded log — populated from the
   moment the app launches, same as kvui: `worker.rs` starts searching
   for the emulator immediately, independently of whether an AP server
   connection exists yet (see below), which is why lines like "Looking
   for a supported emulator..." and "No supported emulator found...
   Please start your emulator." show up before the user has done
   anything at all.
6. A persistent bottom command bar (kvui: an `info_button` reading
   "Command:" + a text input), which actually works here rather than
   being a placeholder: see "Command bar" below.

Two things are copied verbatim from upstream Archipelago source rather
than eyeballed: the log/message colors (`theme.rs`'s `AP_*` constants,
color-for-color from `NetUtils.py`'s `JSONtoTextParser.color_codes`), and
the six-part layout above. What's NOT reproduced exactly is kvui's own
background/surface hex values — those come from KivyMD's Material 3
*dynamic color scheme*, computed at runtime from a seed color rather than
hardcoded, so there's no fixed hex to copy; `theme.rs` uses a hand-picked
dark palette eyeballed against a real screenshot instead. The log's
per-line coloring is also an approximation: kvui's `KivyJSONtoTextParser`
colors individual *parts* of a structured server message (an item name
here, a player name there), but `archipelago_rs`'s `Event::Print` only
hands this client the already-flattened string, so `gui.rs` falls back to
coloring whole lines by prefix/substring (`ERROR` → red, `Received item`
→ cyan, etc.) using the same real color values.

`--connect <server:port>`, `--name <slot>`, and `--password <pw>` (or the
old positional `<server:port> <slot> [password]` form) still work and now
just **pre-fill the form** — if both a server and a slot were given, the
GUI auto-connects on launch, so the Archipelago Launcher's existing
invocation still "just works" without any manual clicking. `--headless`
skips the GUI entirely and runs the original console-only loop (useful
for scripting or testing without a display).

### Command bar

Unlike the first pass at this GUI, the bottom bar is a real command
input, not a placeholder. `worker.rs`'s `handle_command` interprets it
the same way kvui's `SSHDClientCommandProcessor` does: `/`-prefixed text
is a **local** command handled entirely client-side (currently a small
subset: `/connect <server> <slot> [password]`, `/disconnect`, `/help`);
anything else — including `!`-prefixed text like `!hint` — is sent
unmodified to the Archipelago server as a chat message via
`Client::say`, since `!` commands are interpreted server-side, not by
the client. Clicking the "Command:" button itself submits `/help`,
mirroring kvui's info-button tooltip. A typed `/connect` or
`/disconnect` routes through the exact same `start_connection`/
`do_disconnect` functions the Connect/Disconnect buttons use, so the two
can't drift out of sync with each other.

### Emulator discovery vs. the AP connection

`worker.rs`'s single persistent loop (`run()`) runs two independent
activities, matching how the Python client's background emulator-watcher
task behaves regardless of `CommonContext`'s connection state:

- **Emulator discovery** — find the process, attach, scan for
  `AP_IPC_ROOT` — starts immediately on launch and keeps retrying
  forever in the background (with a liveness re-check each tick once
  attached, in case the emulator closes), independent of the AP
  connection.
- **The Archipelago connection** only starts once a `Connect` command
  arrives (button or `/connect`), and is otherwise independent of
  emulator state.

Item delivery, location-check polling, and `check_stats` reporting only
run once BOTH are ready — emulator attached AND `Event::Connected` seen.
This replaces the earlier design, where both were bundled into one
session gated entirely behind the Connect button (which is what caused
the log to stay empty until connecting).

**Why a separate `worker.rs` instead of reusing `run_headless`'s loop
directly:** `run_headless`'s loop blocks forever, talks to
`stdout`/`stderr`, and bundles emulator-attach and the AP connection into
one linear sequence. `worker.rs` is a from-scratch async re-implementation
structured as a stream (`iced::stream::channel`) suitable for
`Subscription::run`: it starts once, hands the GUI a channel it can push
`Connect`/`Disconnect`/`Command` into, and reports back via `WorkerEvent`s
(`Status`, `Log`, `Stats`, `Connected`, `Disconnected`, `Error`) that
`gui.rs` folds into on-screen state. This means the two loops are
maintained separately rather than sharing one implementation — worth
unifying behind a common "reporter" abstraction as a follow-up if
`--headless` and the GUI drift. The GUI path also skips the CLI's
`demo_flag_request_roundtrip` (it was always just a demonstration of the
request/response mailbox pattern, not real functionality).

## Why this design

- The old approach: five to seven independent `static`s in
  `rust-additions`, each with its own magic-byte signature, each requiring
  its own full-memory scan from the Python client, PLUS a separate scan
  for the game's own NSO base address that everything else was computed
  as an offset from.
- The new approach: all of that got folded into one `AP_IPC_ROOT` struct
  (see `ipc.rs`) with ONE magic (`"SSHDAPI\x01"`). The client scans for
  that once, and every mailbox (flag requests, warp requests, spawn
  requests, cheat flags, check stats, the item queue, the item-info table)
  is a fixed, computed byte offset from that one address.
- This is *not* real OS-level IPC (sockets, pipes) — `rust-additions` is a
  `no_std` freestanding binary linked into the game itself, with no
  networking stack and no threads, so that wasn't realistically buildable
  without reimplementing a chunk of Switch's Horizon-OS socket IPC by
  hand. What you get instead is the same "shared-memory RPC" pattern the
  codebase already used for `AP_FLAG_REQUEST`/`AP_WARP_REQUEST`, just
  consolidated and given a Rust host-side type system on top instead of
  hand-rolled `struct.pack`/`struct.unpack` calls.

## What's genuinely done vs. still a TODO

Done, and touches real Rust-additions logic:
- `ipc.rs` (new file) + edits to `commands.rs`, `item.rs`, `cheats.rs`,
  `lyt.rs`, `event.rs`, `mainloop.rs`, `lib.rs` in `rust-additions` — see
  the comments in each for what moved and why. This includes the
  `AP_IPC_ROOT` consolidation (7 mailboxes → 1 magic scan) AND three new
  fields (`sceneflags_addr`/`dungeonflags_addr`/`tboxflags_addr`, IPC
  version now 3) that `item::refresh_ipc_addresses()` populates every
  frame so the client can batch-read location-check flag data without
  hardcoding any offset. **You still need to build this yourself**
  (`python assemble.py` + whatever your normal `cargo check`/build step
  is for rust-additions) — I have no way to compile/verify this
  `no_std`/aarch64 target from here.
- `ap-ipc` — full mirror of the new layout (including all three address
  fields and the custom-flag bit-decoder), tested.
- `process-memory` — full Linux backend, tested against a real process
  (itself). Windows backend written but unverified.
- `ap-client` — real process discovery → real single-scan discovery →
  real typed mailbox reads/writes → real `archipelago_rs` connection
  wiring for events (`Connected`, `Print`, `ReceivedItems`, `Error`) →
  real item delivery (mapped through `items.rs`, written into
  `item_buffer`, with a buffer-full retry loop and correct rejection of
  the 28 event-only item codes) → ALL FOUR of `SSHDClient.py`'s
  location-check mechanisms ported and unioned into one
  `mark_checked(...)` call per tick: custom flags (`locations.rs`),
  goddess chests (`goddess_chests.rs`), Beedle's shop (`beedle_shop.rs`),
  and boss defeats (`boss_defeats.rs`).
- **GUI** — an Iced window (`gui.rs`) driven by a background worker
  (`worker.rs`) that runs the same steps above and reports them as
  events instead of `println!`s; see "GUI (Iced)" above. `--headless`
  still gives you the original console-only loop.

Deliberately not ported (no remaining gap, not a TODO):
- **Hints** — `!hint` and every other server-side `!` command already
  work: the command bar sends any non-`/`-prefixed text straight to the
  server as chat via `Client::say`, and the response comes back as an
  ordinary `Event::Print` log line — same mechanism the Python client
  uses for its `!` commands. Nothing SSHD-specific to build here.
- **"General shop logic"** — there isn't any in `SSHDClient.py` beyond
  Beedle's Airshop (`check_beedle_shop_storyflags`, already ported).
- **PopTracker bridge** (`TrackerBridge.py`) — was never finished
  upstream and isn't being ported here (explicit call not to, given the
  time it'd take to finish designing on top of an incomplete reference).

Still genuinely open:
- **Cheat toggles from slot_data** — the Python client reads
  `option_cheat_*` fields from slot_data and applies them automatically;
  this client has the `AP_IPC_ROOT.cheat_flags` mailbox ready to receive
  them but nothing currently writes to it from slot_data.
- **Goddess chest instant detection** — see `goddess_chests.rs`'s module
  doc for the (small) gap vs. the Python client's dual-source read.

## Before you trust any of this

1. `rust-additions`: run your normal build/assemble pipeline and fix
   anything that doesn't compile. I changed 6 files there and cannot
   compile-check that toolchain from here.
2. `sshd-ap-client`: run `cargo build --workspace` / `cargo test
   --workspace` on your machine with a current Rust toolchain (this
   environment's 1.75 is too old for `archipelago_rs`'s and `iced`'s
   dependencies) — `ap-ipc` and `process-memory`'s Linux path already
   pass here, but `ap-client` (including the new `gui.rs`/`worker.rs`)
   has never been compiled anywhere. Pay particular attention to
   `worker.rs`'s `Subscription::run(|| stream::channel(...))` — the
   exact `iced` 0.13 stream/channel API was cross-checked against current
   docs rather than run, so double-check it compiles and actually
   receives events once connected.
3. If you're on Windows, additionally run
   `cargo check -p process-memory --target x86_64-pc-windows-msvc` (or
   just build the whole workspace, since you're presumably testing this
   against a Windows emulator anyway) — the Windows backend is unverified.

## Getting the client into the .apworld

The `.apworld` file is what Archipelago actually loads, and the
Archipelago Launcher runs the client FROM INSIDE it (see
"Skyward Sword HD Client" in the launcher) — building this Rust workspace
by itself doesn't make it reachable from there. Three pieces now connect
the two:

- **`build_ap_client.py`** (repo root) — runs `cargo build --release` for
  this workspace and stages the resulting binary at
  `sshd-ap-client/dist/<platform_tag>/ap-client[.exe]`. Best-effort: if
  `cargo` isn't installed or the build fails, it just skips itself so it
  never blocks the Python side from building.
- **`build_apworld.py`** now calls `build_ap_client()` automatically and
  bundles whatever ends up in `dist/` into the `.apworld` under
  `sshd/_bundled_bin/<platform_tag>/`.
- **`__init__.py`** extracts `_bundled_bin/` the same way it already
  extracts `sshd-rando-backend/` (temp dir, since the apworld runs as a
  zip), and registers a SEPARATE Launcher entry, "Skyward Sword HD Client
  (Rust, experimental)", that runs the bundled binary if one exists for
  the current platform, or transparently falls back to the Python client
  if not.

**Important limitation:** `build_ap_client.py` only builds for whatever
platform you run it FROM (a native build, not a cross-compile) — unlike
the Python side, which downloads wheels for every platform regardless of
what you're building on. So right now, the `.apworld` only bundles a Rust
binary for your one platform. Getting all of Windows/Linux/macOS bundled
from a single build needs either the `cross` tool or a CI matrix (e.g.
GitHub Actions building on `windows-latest`/`ubuntu-latest`/`macos-latest`
and running `build_ap_client.py` on each before the final
`build_apworld.py` packaging step) — not set up here.

The existing, more feature-complete Python client stays the default
Launcher entry precisely because of everything in the "Not done" section
above — this is deliberately an opt-in second entry, not a replacement,
until the Rust client covers the remaining check mechanisms.
