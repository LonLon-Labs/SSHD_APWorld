//! Color palette + widget styling meant to evoke Archipelago's own client
//! (`kvui.py`, a KivyMD app) as closely as reasonably possible from Iced.
//!
//! Two things below are copied faithfully from the real Archipelago
//! source rather than guessed:
//! - The log-message color codes, straight from `NetUtils.py`'s
//!   `JSONtoTextParser.color_codes` (the `AP_*` constants below) — these
//!   are the exact colors AP's own client uses for item/location/player
//!   names and hint statuses in chat.
//! - The overall shape of `kvui.py`'s `GameManager.build()`: a connect
//!   bar (info icon + server label + address field + Connect button), a
//!   thin progress strip under it, a full-width tab bar over the log, a
//!   scrollable log, and a bottom bar — see `gui.rs` for how these get
//!   assembled.
//!
//! The rest of the palette (background/surface/tab hex values) was
//! eyeballed directly against a real screenshot of the Python client's
//! window (kvui's colors come from KivyMD's Material 3 *dynamic color
//! scheme*, generated at runtime from a seed color, so there's no fixed
//! hex to copy from source — this was matched by eye instead).

use iced::widget::{button, container, text_input};
use iced::{Background, Border, Color, Theme};

/// `Color::from_rgb8` isn't a `const fn` in this `iced` version, so it
/// can't be used to initialize a `const`. This is the const-friendly
/// equivalent, doing the same `u8 -> f32` normalization by hand.
const fn rgb8(r: u8, g: u8, b: u8) -> Color {
    Color { r: r as f32 / 255.0, g: g as f32 / 255.0, b: b as f32 / 255.0, a: 1.0 }
}

// ── Chrome (backgrounds, borders, accent) ───────────────────────────────
/// Window/log background — a near-black, faintly blue navy, matching the
/// Python client rather than a neutral dark gray.
pub const BACKGROUND: Color = rgb8(0x0c, 0x0f, 0x14);
/// Slightly lighter than `BACKGROUND` — used only for the server tooltip
/// card, which kvui itself pops as a distinct surface.
pub const SURFACE: Color = rgb8(0x1a, 0x1d, 0x24);
/// Field backgrounds (text inputs, the read-only status bar) — close to
/// `BACKGROUND` but distinguishable by their border, same as kvui.
pub const SURFACE_ALT: Color = rgb8(0x14, 0x17, 0x1d);
pub const OUTLINE: Color = rgb8(0x2c, 0x31, 0x3a);
/// The bright sky-blue used for the Connect button and the info icon.
pub const ACCENT: Color = rgb8(0x4f, 0x8f, 0xf0);
pub const ACCENT_DIM: Color = rgb8(0x24, 0x30, 0x47);
/// The selected tab's fill — a muted slate-blue, not the bright accent.
pub const TAB_SELECTED: Color = rgb8(0x39, 0x41, 0x56);
pub const TEXT: Color = rgb8(0xe8, 0xe8, 0xe8);
pub const TEXT_MUTED: Color = rgb8(0x8a, 0x90, 0x9a);

// ── Log/message colors, verbatim from NetUtils.py's color_codes ────────
pub const AP_RED: Color = rgb8(0xEE, 0x00, 0x00);
pub const AP_GREEN: Color = rgb8(0x00, 0xFF, 0x7F);
#[allow(dead_code)] // kept for parity with color_codes even though unused today
pub const AP_YELLOW: Color = rgb8(0xFA, 0xFA, 0xD2);
#[allow(dead_code)]
pub const AP_BLUE: Color = rgb8(0x64, 0x95, 0xED);
#[allow(dead_code)]
pub const AP_MAGENTA: Color = rgb8(0xEE, 0x00, 0xEE);
pub const AP_CYAN: Color = rgb8(0x00, 0xEE, 0xEE);
#[allow(dead_code)]
pub const AP_SLATEBLUE: Color = rgb8(0x6D, 0x8B, 0xE8);
#[allow(dead_code)]
pub const AP_PLUM: Color = rgb8(0xAF, 0x99, 0xEF);
#[allow(dead_code)]
pub const AP_SALMON: Color = rgb8(0xFA, 0x80, 0x72);
pub const AP_ORANGE: Color = rgb8(0xFF, 0x77, 0x00);

/// A dark base theme; our containers/text override colors explicitly on
/// top of it rather than relying much on the theme's own palette.
pub fn app_theme() -> Theme {
    Theme::Dark
}

fn radius(px: f32) -> iced::border::Radius {
    px.into()
}

pub fn window_container(_theme: &Theme) -> container::Style {
    container::Style {
        background: Some(Background::Color(BACKGROUND)),
        text_color: Some(TEXT),
        ..Default::default()
    }
}

/// The small floating card used for the server tooltip — kvui pops a
/// similar boxed tooltip on hover.
pub fn panel_container(_theme: &Theme) -> container::Style {
    container::Style {
        background: Some(Background::Color(SURFACE)),
        border: Border { color: OUTLINE, width: 1.0, radius: radius(6.0) },
        text_color: Some(TEXT),
        ..Default::default()
    }
}

/// The log itself: flat and borderless, flush with the window background
pub fn log_container(_theme: &Theme) -> container::Style {
    container::Style { background: Some(Background::Color(BACKGROUND)), text_color: Some(TEXT), ..Default::default() }
}

/// A full-width flat tab (kvui: `MDNavigationBar`) — no pill shape, no
/// border; `selected` just gets a lighter slate-blue fill.
pub fn tab_container(selected: bool) -> impl Fn(&Theme) -> container::Style {
    move |_theme| container::Style {
        background: Some(Background::Color(if selected { TAB_SELECTED } else { BACKGROUND })),
        text_color: Some(if selected { TEXT } else { TEXT_MUTED }),
        ..Default::default()
    }
}

/// The circular "i" info icon next to the server label (kvui's
/// `ServerLabel` has a matching info icon with the same tooltip role).
pub fn info_icon_container(_theme: &Theme) -> container::Style {
    container::Style {
        background: Some(Background::Color(ACCENT)),
        border: Border { radius: radius(999.0), ..Border::default() },
        text_color: Some(Color::WHITE),
        ..Default::default()
    }
}

/// The thin (3px) strip under the connect bar that mirrors kvui's
/// `MDLinearProgressIndicator` — here just a plain color block whose
/// color the caller picks based on connection status.
pub fn progress_container(color: Color) -> impl Fn(&Theme) -> container::Style {
    move |_theme| container::Style { background: Some(Background::Color(color)), ..Default::default() }
}

pub fn accent_button(_theme: &Theme, status: button::Status) -> button::Style {
    let bg = match status {
        button::Status::Hovered => Color { a: 0.85, ..ACCENT },
        button::Status::Pressed => Color { a: 0.7, ..ACCENT },
        button::Status::Disabled => SURFACE_ALT,
        button::Status::Active => ACCENT,
    };
    button::Style {
        background: Some(Background::Color(bg)),
        text_color: if matches!(status, button::Status::Disabled) { TEXT_MUTED } else { Color::WHITE },
        border: Border { radius: radius(5.0), ..Border::default() },
        ..Default::default()
    }
}

pub fn field_input(_theme: &Theme, status: text_input::Status) -> text_input::Style {
    let border_color = match status {
        text_input::Status::Active => OUTLINE,
        text_input::Status::Disabled => OUTLINE,
        // Hovered, and Focused { is_hovered } on newer `iced` — either way,
        // highlight it.
        _ => ACCENT,
    };
    text_input::Style {
        background: Background::Color(SURFACE_ALT),
        border: Border { color: border_color, width: 1.0, radius: radius(5.0) },
        icon: TEXT_MUTED,
        placeholder: TEXT_MUTED,
        value: TEXT,
        selection: ACCENT_DIM,
    }
}
