//! Per-word ("per-part") coloring of Archipelago `Print` messages.
//!
//! The Python client got this for free from Archipelago's
//! `NetUtils.JSONtoTextParser`, which renders every part of a server
//! message (player name, item name, location name, ...) in its own
//! color. `archipelago_rs` hands us the same structure as
//! `Print::data() -> &[RichText]`; this module turns it into a list of
//! `LogSpan`s (text + semantic color) that can be rendered two ways:
//! - as ANSI escape codes for the terminal echo (`spans_to_ansi`)
//! - as `iced::Color` spans in the GUI log (`SpanColor::to_iced`)
//!
//! The semantic mapping mirrors `JSONtoTextParser`'s handlers:
//! - item: progression -> plum, useful -> slateblue, trap -> salmon,
//!   otherwise (filler) cyan
//! - player: magenta if it's you, yellow otherwise
//! - location: green, entrance: blue
//! - explicit `Color` parts: the color the server asked for
//!
//! Background-color / bold / underline variants can't be expressed as a
//! simple foreground color span; backgrounds fall back to the matching
//! foreground color, bold/underline to plain text.

use archipelago_rs::{Print, RichText, TextColor};
use iced::Color;

use crate::theme;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SpanColor {
    /// No explicit color: use the log's normal text color.
    Plain,
    Black,
    Red,
    Green,
    Yellow,
    Blue,
    Magenta,
    Cyan,
    White,
    SlateBlue,
    Plum,
    Salmon,
    Orange,
}

impl SpanColor {
    /// `None` for `Plain` (caller uses its default text color).
    pub fn to_iced(self) -> Option<Color> {
        Some(match self {
            SpanColor::Plain => return None,
            SpanColor::Black => Color::BLACK,
            SpanColor::Red => theme::AP_RED,
            SpanColor::Green => theme::AP_GREEN,
            SpanColor::Yellow => theme::AP_YELLOW,
            SpanColor::Blue => theme::AP_BLUE,
            SpanColor::Magenta => theme::AP_MAGENTA,
            SpanColor::Cyan => theme::AP_CYAN,
            SpanColor::White => Color::WHITE,
            SpanColor::SlateBlue => theme::AP_SLATEBLUE,
            SpanColor::Plum => theme::AP_PLUM,
            SpanColor::Salmon => theme::AP_SALMON,
            SpanColor::Orange => theme::AP_ORANGE,
        })
    }
}

impl From<&TextColor> for SpanColor {
    fn from(c: &TextColor) -> Self {
        match c {
            TextColor::Bold | TextColor::Underline => SpanColor::Plain,
            TextColor::Black | TextColor::BlackBg => SpanColor::Black,
            TextColor::Red | TextColor::RedBg => SpanColor::Red,
            TextColor::Green | TextColor::GreenBg => SpanColor::Green,
            TextColor::Yellow | TextColor::YellowBg => SpanColor::Yellow,
            TextColor::Blue | TextColor::BlueBg => SpanColor::Blue,
            TextColor::Magenta | TextColor::MagentaBg => SpanColor::Magenta,
            TextColor::Cyan | TextColor::CyanBg => SpanColor::Cyan,
            TextColor::White | TextColor::WhiteBg => SpanColor::White,
        }
    }
}

/// One colored run of text within a log line.
#[derive(Debug, Clone)]
pub struct LogSpan {
    pub text: String,
    pub color: SpanColor,
}

impl LogSpan {
    pub fn new(text: impl Into<String>, color: SpanColor) -> Self {
        LogSpan { text: text.into(), color }
    }

    pub fn plain(text: impl Into<String>) -> Self {
        LogSpan::new(text, SpanColor::Plain)
    }
}

/// Same precedence as `NetUtils.py`: progression, then useful, then
/// trap; anything else (filler) is cyan.
fn item_color(progression: bool, useful: bool, trap: bool) -> SpanColor {
    if progression {
        SpanColor::Plum
    } else if useful {
        SpanColor::SlateBlue
    } else if trap {
        SpanColor::Salmon
    } else {
        SpanColor::Cyan
    }
}

fn part_to_span(part: &RichText, own_name: &str) -> LogSpan {
    match part {
        RichText::Player(player) => {
            let color = if player.name().as_str() == own_name { SpanColor::Magenta } else { SpanColor::Yellow };
            LogSpan::new(player.to_string(), color)
        },
        RichText::PlayerName(text) => LogSpan::new(text.clone(), SpanColor::Yellow),
        RichText::Item { item, progression, useful, trap, .. } => {
            LogSpan::new(item.to_string(), item_color(*progression, *useful, *trap))
        },
        RichText::Location { location, .. } => LogSpan::new(location.to_string(), SpanColor::Green),
        RichText::EntranceName(text) => LogSpan::new(text.clone(), SpanColor::Blue),
        RichText::Color { text, color } => LogSpan::new(text.clone(), SpanColor::from(color)),
        RichText::Text(text) => LogSpan::plain(text.clone()),
        #[allow(unreachable_patterns)]
        other => LogSpan::plain(other.to_string()),
    }
}

/// Converts a server `Print` into per-part colored spans. `own_name` is
/// this client's slot name, used to tell "you" apart from other players.
pub fn print_to_spans(print: &Print, own_name: &str) -> Vec<LogSpan> {
    print.data().iter().map(|part| part_to_span(part, own_name)).collect()
}

/// Renders spans as one string with 24-bit ANSI color escapes (same hex
/// colors as the GUI). Requires `enable_ansi()` on Windows consoles.
pub fn spans_to_ansi(spans: &[LogSpan]) -> String {
    let mut out = String::new();
    for span in spans {
        match span.color.to_iced() {
            Some(c) => {
                let (r, g, b) = ((c.r * 255.0).round() as u8, (c.g * 255.0).round() as u8, (c.b * 255.0).round() as u8);
                out.push_str(&format!("\x1b[38;2;{r};{g};{b}m{}\x1b[0m", span.text));
            },
            None => out.push_str(&span.text),
        }
    }
    out
}

/// Turns on ANSI escape processing for this process's console window
/// (the Rust equivalent of `colorama.just_fix_windows_console()`).
/// Best-effort; a no-op on non-Windows targets.
pub fn enable_ansi() {
    #[cfg(windows)]
    unsafe {
        use windows_sys::Win32::System::Console::{
            GetConsoleMode, GetStdHandle, SetConsoleMode, ENABLE_VIRTUAL_TERMINAL_PROCESSING, STD_ERROR_HANDLE,
            STD_OUTPUT_HANDLE,
        };
        for std_handle in [STD_OUTPUT_HANDLE, STD_ERROR_HANDLE] {
            let handle = GetStdHandle(std_handle);
            let mut mode = 0u32;
            if GetConsoleMode(handle, &mut mode) != 0 {
                SetConsoleMode(handle, mode | ENABLE_VIRTUAL_TERMINAL_PROCESSING);
            }
        }
    }
}
