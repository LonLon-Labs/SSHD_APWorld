//! Iced GUI for the Rust Archipelago client, laid out to mirror
//! `kvui.py`'s `GameManager.build()` — the KivyMD window
//! `SSHDClient.py` opens via Archipelago's own `CommonContext.run_gui()`
//! — as closely as Iced reasonably allows. Top to bottom, same skeleton
//! as upstream:
//!
//! 1. A connect bar: an info icon + "Server:" label (hover for a
//!    tooltip), an address field, and a Connect/Disconnect button (kvui:
//!    `server_label` + `server_connect_bar` + `server_connect_button`,
//!    inside `connect_layout`). Slot name + password aren't part of
//!    kvui's connect bar (that client gets them from
//!    `--name`/prompts/`/connect` text commands instead) — since this
//!    client has no command console, they're a second, visually
//!    secondary row right underneath instead.
//! 2. A thin progress strip (kvui: `MDLinearProgressIndicator`), colored
//!    by connection status.
//! 3. A full-width flat tab bar over the log (kvui: `MDNavigationBar`,
//!    one tab per logging pair — this client only ever has one,
//!    "Archipelago"). The `checked / total` count lives in the server
//!    tooltip rather than here, matching kvui (which doesn't show it in
//!    the tab bar either).
//! 4. The scrollable, color-coded log itself, flat/borderless like
//!    kvui's.
//! 5. A persistent bottom command bar (kvui: `info_button` reading
//!    "Command:" + a text input) that actually works here: `/`-prefixed
//!    text is a local command, anything else (including `!`-prefixed
//!    server commands) is sent to the Archipelago server as chat — see
//!    `worker.rs`'s `handle_command`. Clicking "Command:" itself shows
//!    the local command list, mirroring kvui's info-button tooltip.
//!
//! Unlike kvui, log lines show up from the moment the app launches, not
//! only after connecting to a server — `worker.rs` starts searching for
//! the emulator immediately and independently of the AP connection,
//! exactly like the Python client's background emulator-watcher task.
//!
//! See `theme.rs` for the palette (dark navy, eyeballed against a real
//! screenshot of the Python client, with log colors taken verbatim from
//! `NetUtils.py`'s `color_codes`).

use iced::alignment::{Horizontal, Vertical};
use iced::widget::{button, column, container, rich_text, row, scrollable, span, text, text_input, tooltip, Column, Space};
use iced::{Color, Element, Length, Subscription, Task, Theme};

use crate::colors::{self, LogSpan, SpanColor};
use crate::theme;
use crate::worker::{self, WorkerEvent, WorkerInput};

/// The address kvui's own connect bar starts pre-filled with, when the
/// client wasn't launched with an explicit `--connect`.
const DEFAULT_SERVER: &str = "archipelago.gg:";

/// Where the last-used server address + slot name are remembered between
/// runs, so closing and reopening the client doesn't mean retyping them
/// (the password is deliberately NOT saved here, since it would otherwise
/// sit in plain text on disk). `%APPDATA%\sshd-ap-client\connection.txt`
/// on Windows, `$HOME/.config/sshd-ap-client/connection.txt` elsewhere.
fn config_dir() -> Option<std::path::PathBuf> {
    if let Ok(appdata) = std::env::var("APPDATA") {
        return Some(std::path::PathBuf::from(appdata).join("sshd-ap-client"));
    }
    if let Ok(home) = std::env::var("HOME") {
        return Some(std::path::PathBuf::from(home).join(".config").join("sshd-ap-client"));
    }
    None
}

fn saved_connection_path() -> Option<std::path::PathBuf> {
    config_dir().map(|dir| dir.join("connection.txt"))
}

/// Reads back whatever `save_connection` last wrote: server on the first
/// line, slot name on the second. Best-effort — any failure (file
/// missing, unreadable, garbled) just means "nothing remembered yet",
/// not an error the person needs to see.
fn load_saved_connection() -> Option<(String, String)> {
    let path = saved_connection_path()?;
    let contents = std::fs::read_to_string(path).ok()?;
    let mut lines = contents.lines();
    let server = lines.next()?.trim().to_string();
    let slot = lines.next().unwrap_or("").trim().to_string();
    if server.is_empty() || slot.is_empty() {
        return None;
    }
    Some((server, slot))
}

/// Called right after a successful connect so next launch can pre-fill
/// (and auto-connect) without the person retyping anything. Best-effort:
/// if the config directory can't be created or written (e.g. no home
/// directory in some sandboxed environment), this silently does nothing
/// rather than interrupting the connection that just succeeded.
fn save_connection(server: &str, slot: &str) {
    let Some(dir) = config_dir() else { return };
    if std::fs::create_dir_all(&dir).is_err() {
        return;
    }
    if let Some(path) = saved_connection_path() {
        let _ = std::fs::write(path, format!("{server}\n{slot}\n"));
    }
}

/// Initial values the GUI starts with — filled in from `--connect`
/// `--name` `--password` (or the old positional form) so launching via
/// the Archipelago Launcher, which invokes this binary with those flags,
/// still pre-fills the form instead of making the user retype them.
pub struct Flags {
    pub server: String,
    pub slot: String,
    pub password: String,
    pub auto_connect: bool,
}

pub struct App {
    server: String,
    slot: String,
    password: String,

    status: String,
    /// One entry per log line, each a list of colored spans.
    logs: Vec<Vec<LogSpan>>,
    /// Whether the log should keep auto-scrolling to the newest line.
    /// Starts `true` (kvui-like "tail -f" behavior) and is flipped off
    /// the moment `on_scroll` reports the user isn't at the bottom
    /// anymore, so scrolling up to read earlier lines actually sticks
    /// instead of getting yanked back down by the next log line.
    log_pinned: bool,
    checked: u16,
    total: u16,
    /// Text currently typed into the command bar.
    command_input: String,

    connected: bool,
    connecting: bool,
    error: bool,

    /// Set once `WorkerEvent::Ready` arrives. `None` briefly on startup,
    /// before the subscription's stream has spun up.
    worker: Option<iced::futures::channel::mpsc::Sender<WorkerInput>>,
    /// Consumed the first time `worker` becomes available, if the
    /// startup flags had both a server and a slot name.
    auto_connect: bool,
    /// Commands submitted before `worker` became available (the window
    /// between the app opening and the worker stream's first `Ready`
    /// event) — queued here rather than dropped, and flushed in order
    /// the moment `worker` is set, so "can I send a command before
    /// connecting" holds even in that first instant.
    pending_commands: Vec<String>,
}

#[derive(Debug, Clone)]
pub enum Message {
    ServerChanged(String),
    SlotChanged(String),
    PasswordChanged(String),
    Connect,
    Disconnect,
    CommandChanged(String),
    CommandSubmit,
    ShowHelp,
    Worker(WorkerEvent),
    /// Fired by the log's `scrollable` on every scroll (wheel, drag, or
    /// our own `snap_to`) so `log_pinned` can track whether the user is
    /// still at the bottom.
    LogScrolled(scrollable::Viewport),
}

const MAX_LOG_LINES: usize = 500;

/// Id given to the log's `scrollable` so `snap_to` can target it from
/// `update()` (see `scroll_log_if_pinned`).
const LOG_SCROLLABLE_ID: &str = "log-scrollable";

impl App {
    pub fn new(flags: Flags) -> (Self, Task<Message>) {
        // CLI-provided server/slot (from `--connect`/`--name`, or the
        // Archipelago Launcher) always win. Otherwise, fall back to
        // whatever was remembered from the last successful connection —
        // see `save_connection` — so the person doesn't have to retype
        // the server and slot name every time they reopen the client.
        let mut auto_connect = flags.auto_connect;
        let (server, slot) = if !flags.server.is_empty() || !flags.slot.is_empty() {
            (flags.server, flags.slot)
        } else if let Some((saved_server, saved_slot)) = load_saved_connection() {
            auto_connect = true;
            (saved_server, saved_slot)
        } else {
            (String::new(), String::new())
        };
        let server = if server.is_empty() { DEFAULT_SERVER.to_string() } else { server };
        let app = App {
            server,
            slot,
            password: flags.password,

            status: "Not connected".to_string(),
            logs: Vec::new(),
            log_pinned: true,
            checked: 0,
            total: 0,
            command_input: String::new(),

            connected: false,
            connecting: false,
            error: false,

            worker: None,
            auto_connect,
            pending_commands: Vec::new(),
        };
        (app, Task::none())
    }

    pub fn update(&mut self, message: Message) -> Task<Message> {
        match message {
            Message::ServerChanged(v) => {
                self.server = v;
                Task::none()
            },
            Message::SlotChanged(v) => {
                self.slot = v;
                Task::none()
            },
            Message::PasswordChanged(v) => {
                self.password = v;
                Task::none()
            },
            Message::Connect => {
                self.try_connect();
                self.scroll_log_if_pinned()
            },
            Message::Disconnect => {
                if let Some(sender) = self.worker.as_mut() {
                    let _ = sender.try_send(WorkerInput::Disconnect);
                }
                Task::none()
            },
            Message::CommandChanged(v) => {
                self.command_input = v;
                Task::none()
            },
            Message::CommandSubmit => {
                let text = std::mem::take(&mut self.command_input);
                self.submit_command(text);
                self.scroll_log_if_pinned()
            },
            Message::ShowHelp => {
                self.submit_command("/help".to_string());
                self.scroll_log_if_pinned()
            },
            Message::Worker(event) => {
                self.handle_worker_event(event);
                self.scroll_log_if_pinned()
            },
            Message::LogScrolled(viewport) => {
                // `relative_offset().y` is 1.0 at the very bottom. There's
                // no public way to ask a `Viewport` whether it can scroll
                // at all, so a log short enough to show in full reports
                // 0.0 here same as "scrolled to the top" would — meaning a
                // stray wheel-scroll over a not-yet-overflowing log could
                // in principle flip this off early. Harmless in practice
                // (nothing to see either way until it overflows), and far
                // simpler than the alternative of tracking raw wheel
                // deltas ourselves.
                self.log_pinned = viewport.relative_offset().y >= 0.999;
                Task::none()
            },
        }
    }

    /// Snaps the log to its newest line if (and only if) the user hasn't
    /// scrolled up away from the bottom — called after anything that may
    /// have appended a line, so the log keeps following like a normal
    /// console/tail unless someone's mid-scroll reading history.
    fn scroll_log_if_pinned(&self) -> Task<Message> {
        if self.log_pinned {
            scrollable::snap_to(scrollable::Id::new(LOG_SCROLLABLE_ID), scrollable::RelativeOffset::END)
        } else {
            Task::none()
        }
    }

    pub fn view(&self) -> Element<'_, Message> {
        // ── 1. Connect bar (kvui: connect_layout) ───────────────────────
        let info_icon = container(text("i").size(13.0).color(Color::WHITE))
            .width(Length::Fixed(22.0))
            .height(Length::Fixed(22.0))
            .align_x(Horizontal::Center)
            .align_y(Vertical::Center)
            .style(theme::info_icon_container);

        let server_label = tooltip(
            row![info_icon, text("Server:").size(16.0).color(theme::TEXT)].spacing(8).align_y(Vertical::Center),
            container(text(self.server_tooltip_text()).size(13.0).color(theme::TEXT))
                .padding(10)
                .style(theme::panel_container),
            tooltip::Position::Bottom,
        );

        let busy = self.connected || self.connecting;
        let (action_label, action_message) =
            if busy { ("Disconnect", Message::Disconnect) } else { ("Connect", Message::Connect) };

        let connect_row = row![
            server_label,
            text_input(DEFAULT_SERVER, &self.server)
                .on_input(Message::ServerChanged)
                .on_submit(Message::Connect)
                .size(16.0)
                .padding(10)
                .style(theme::field_input)
                .width(Length::Fill),
            button(text(action_label).size(15.0))
                .on_press(action_message)
                .padding([10, 24])
                .style(theme::accent_button),
        ]
        .spacing(10)
        .padding(12)
        .align_y(Vertical::Center);

        // ── Secondary row: slot + password (not part of kvui's connect ──
        // bar, but this client needs them upfront rather than via /connect)
        let details_row = row![
            text_input("slot name", &self.slot)
                .on_input(Message::SlotChanged)
                .on_submit(Message::Connect)
                .size(14.0)
                .padding(8)
                .style(theme::field_input)
                .width(Length::FillPortion(1)),
            text_input("password (optional)", &self.password)
                .secure(true)
                .on_input(Message::PasswordChanged)
                .size(14.0)
                .padding(8)
                .style(theme::field_input)
                .width(Length::FillPortion(1)),
        ]
        .spacing(10)
        .padding(iced::Padding { top: 0.0, right: 12.0, bottom: 12.0, left: 12.0 });

        // ── 2. Progress strip (kvui: MDLinearProgressIndicator) ─────────
        let progress = container(Space::new(Length::Fill, Length::Fixed(3.0)))
            .style(theme::progress_container(self.progress_color()));

        // ── 3. Tab bar (kvui: MDNavigationBar) — full-width, flat ───────
        let tabs_row = container(text("Archipelago").size(15.0))
            .width(Length::Fill)
            .height(Length::Fixed(44.0))
            .align_x(Horizontal::Center)
            .align_y(Vertical::Center)
            .style(theme::tab_container(true));

        // ── 4. Log ────────────────────────────────────────────────────
        let log_view: Element<'_, Message> = if self.logs.is_empty() {
            container(text("Logs will appear here once you connect.").size(14.0).color(theme::TEXT_MUTED))
                .padding(14)
                .into()
        } else {
            Column::with_children(self.logs.iter().map(|line| Self::log_line(line)))
                .spacing(3)
                .padding(14)
                .into()
        };

        let log_scrollable = scrollable(log_view)
            .height(Length::Fill)
            .width(Length::Fill)
            .id(scrollable::Id::new(LOG_SCROLLABLE_ID))
            .on_scroll(Message::LogScrolled);

        let log_panel = container(log_scrollable).style(theme::log_container).width(Length::Fill).height(Length::Fill);

        // ── 5. Command bar (kvui: info_button "Command:" + textinput) ───
        let command_button = button(text("Command:").size(14.0))
            .on_press(Message::ShowHelp)
            .padding([10, 20])
            .style(theme::accent_button);

        let command_field = text_input("", &self.command_input)
            .on_input(Message::CommandChanged)
            .on_submit(Message::CommandSubmit)
            .size(14.0)
            .padding(10)
            .style(theme::field_input)
            .width(Length::Fill);

        let bottom_row = row![command_button, command_field].spacing(10).padding(12).align_y(Vertical::Center);

        let content = column![connect_row, details_row, progress, tabs_row, log_panel, bottom_row].spacing(0);

        container(content).style(theme::window_container).width(Length::Fill).height(Length::Fill).into()
    }

    pub fn subscription(&self) -> Subscription<Message> {
        worker::subscription().map(Message::Worker)
    }

    pub fn theme(&self) -> Theme {
        theme::app_theme()
    }

    fn try_connect(&mut self) {
        if self.server.trim().is_empty() || self.server.trim() == DEFAULT_SERVER.trim_end_matches(':') {
            self.push_log("Enter a server address before connecting.");
            return;
        }
        if self.slot.trim().is_empty() {
            self.push_log("Enter a slot name before connecting.");
            return;
        }
        let Some(sender) = self.worker.as_mut() else {
            self.push_log("Worker not ready yet — try again in a moment.");
            return;
        };
        let password = if self.password.is_empty() { None } else { Some(self.password.clone()) };
        let _ = sender.try_send(WorkerInput::Connect {
            server: self.server.trim().to_string(),
            slot: self.slot.trim().to_string(),
            password,
        });
        self.connecting = true;
        self.error = false;
        self.status = "Connecting…".to_string();
    }

    /// Echoes `text` into the log (so the user can see what they typed,
    /// same as kvui) and forwards it to the worker's command handling —
    /// shared by the command bar's Enter key and the "Command:" button
    /// (which submits `/help`). Works before a server connection exists
    /// (the worker only requires one for non-`/` chat text — see
    /// `handle_command`) and even before the worker itself has finished
    /// starting up, in which case the command is queued rather than
    /// dropped.
    fn submit_command(&mut self, text: String) {
        if text.trim().is_empty() {
            return;
        }
        self.push_log(&format!("> {text}"));
        match self.worker.as_mut() {
            Some(sender) => {
                let _ = sender.try_send(WorkerInput::Command(text));
            },
            None => self.pending_commands.push(text),
        }
    }

    fn handle_worker_event(&mut self, event: WorkerEvent) {
        match event {
            WorkerEvent::Ready(sender) => {
                self.worker = Some(sender);
                for text in std::mem::take(&mut self.pending_commands) {
                    if let Some(sender) = self.worker.as_mut() {
                        let _ = sender.try_send(WorkerInput::Command(text));
                    }
                }
                if self.auto_connect {
                    self.auto_connect = false;
                    self.try_connect();
                }
            },
            WorkerEvent::Status(s) => self.status = s,
            WorkerEvent::Log(line) => self.push_log(&line),
            WorkerEvent::Print(spans) => self.push_spans(spans),
            WorkerEvent::Stats { checked, total } => {
                self.checked = checked;
                self.total = total;
            },
            WorkerEvent::Connected => {
                self.connected = true;
                self.connecting = false;
                self.error = false;
                // Remember this server + slot for next launch (see
                // `save_connection`'s docs for why the password isn't
                // included). Best-effort: never surfaces an error.
                save_connection(self.server.trim(), self.slot.trim());
            },
            WorkerEvent::Disconnected => {
                self.connected = false;
                self.connecting = false;
                if self.status != "Not connected" {
                    self.status = "Not connected".to_string();
                }
            },
            WorkerEvent::Error(e) => {
                self.push_log(&format!("ERROR: {e}"));
                self.connected = false;
                self.connecting = false;
                self.error = true;
                self.status = format!("Error: {e}");
            },
        }
    }

    /// Appends `line` to the GUI's own curated scrolling log AND echoes
    /// it to stdout, i.e. the plain terminal/console window this process
    /// already opens alongside the GUI on Windows (it's a normal console
    /// subsystem binary, not a `windows_subsystem = "windows"` one).
    /// This is the single place that happens, so it automatically covers
    /// every curated line regardless of source: `WorkerEvent::Log` lines
    /// from `worker.rs` (see its `log!` macro) as well as this app's own
    /// local-only feedback (typed-command echoes, validation errors like
    /// "Enter a server address...").
    ///
    /// `worker.rs` also prints plenty of its own lines directly via a
    /// bare `println!` (its `vlog!` macro) WITHOUT going through here —
    /// verbose/internal detail (emulator discovery, per-tick poll
    /// diagnostics, item-buffer bookkeeping) that would just be noise in
    /// this curated panel. So the terminal ends up showing everything
    /// (curated + verbose), while this panel only ever shows the curated
    /// subset — mirroring how the Python client had a separate, more
    /// verbose console window alongside its own curated GUI log.
    fn push_log(&mut self, line: &str) {
        println!("{line}");
        self.store_line(vec![LogSpan::new(line, Self::log_color(line))]);
    }

    /// Like `push_log`, but for a server message that already arrived as
    /// per-part colored spans (see `colors.rs`). The terminal echo gets
    /// the same colors via ANSI escapes.
    fn push_spans(&mut self, spans: Vec<LogSpan>) {
        println!("{}", colors::spans_to_ansi(&spans));
        self.store_line(spans);
    }

    fn store_line(&mut self, spans: Vec<LogSpan>) {
        self.logs.push(spans);
        if self.logs.len() > MAX_LOG_LINES {
            let excess = self.logs.len() - MAX_LOG_LINES;
            self.logs.drain(0..excess);
        }
    }

    fn log_line(line: &[LogSpan]) -> Element<'_, Message> {
        let spans: Vec<iced::widget::text::Span<'_, Message, iced::Font>> = line
            .iter()
            .map(|s| {
                let sp = span(s.text.clone());
                match s.color.to_iced() {
                    Some(c) => sp.color(c),
                    None => sp,
                }
            })
            .collect();
        rich_text(spans).size(14.0).color(theme::TEXT).into()
    }

    /// Whole-line, prefix/substring-based coloring for this app's OWN
    /// status lines (errors, warnings, checks found). Server messages
    /// don't go through this: they arrive as per-part colored spans
    /// (see `colors.rs`), like `KivyJSONtoTextParser` does.
    fn log_color(line: &str) -> SpanColor {
        if line.starts_with("ERROR") {
            SpanColor::Red
        } else if line.starts_with("WARNING") {
            SpanColor::Orange
        } else if line.contains("Connected.") || line.contains("location(s) checked") {
            SpanColor::Green
        } else if line.contains("Received item") {
            SpanColor::Cyan
        } else {
            SpanColor::Plain
        }
    }

    fn progress_color(&self) -> Color {
        if self.error {
            theme::AP_RED
        } else if self.connected {
            theme::AP_GREEN
        } else if self.connecting {
            theme::ACCENT
        } else {
            theme::SURFACE_ALT
        }
    }

    /// Mirrors the gist of kvui's `ServerLabel` tooltip (connection +
    /// check-progress info on hover), though not its exact wording.
    /// Also folds in the worker's latest `Status` line ("Looking for a
    /// supported emulator...", "Connecting...", etc.) since this client
    /// has nowhere else to show it once the bottom bar became a real
    /// command bar.
    fn server_tooltip_text(&self) -> String {
        let mut text = format!("Status: {}", self.status);
        if self.connected {
            text.push_str(&format!(
                "\nSlot: {}\nChecked {} / {} locations.",
                self.slot, self.checked, self.total
            ));
        }
        text
    }
}
