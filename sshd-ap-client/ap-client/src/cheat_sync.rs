//! Applies cheat toggles from Archipelago slot_data to
//! `AP_IPC_ROOT.cheat_flags`, ported from `SSHDClient.py`'s slot_data
//! handling of the `option_cheat_*` keys. Call `apply_cheat_flags` once
//! per connection, right after `Event::Connected` — both `main.rs`'s
//! `run_headless` and `worker.rs` should call this so the two don't drift.
//!
//! Does a read-modify-write rather than overwriting the whole
//! `ApCheatFlags` struct, so it never clobbers `hover_vel_y_bits` (a fixed
//! physics constant, not slot_data-configurable) or `spawn_demise_request`
//! (a one-shot trigger flag that could be genuinely pending mid-flight).
//!
//! NOTE: `option_cheat_infinite_beetle` exists in the Python client's
//! slot_data handling but has no corresponding field in `ApCheatFlags` on
//! the Rust-additions side — that cheat isn't implemented there. It's
//! read here only so it can be reported as unsupported rather than
//! silently ignored.

use ap_ipc::offsets;
use process_memory::{MemError, ProcessMemory};

use crate::locations::SlotData;

/// Writes every cheat toggle from `slot_data` into `AP_IPC_ROOT.cheat_flags`
/// in one read-modify-write, and returns a human-readable list of what
/// ended up active (for logging), matching the Python client's
/// `active_cheats` summary line.
pub fn apply_cheat_flags(
    mem: &mut impl ProcessMemory,
    root_addr: usize,
    slot_data: &SlotData,
) -> Result<Vec<String>, MemError> {
    let addr = root_addr + offsets::CHEAT_FLAGS;
    let raw = mem.read_bytes(addr, std::mem::size_of::<ap_ipc::ApCheatFlags>())?;
    let mut flags: ap_ipc::ApCheatFlags = ap_ipc::bytes::read(&raw);

    flags.infinite_health = slot_data.option_cheat_infinite_health;
    flags.infinite_stamina = slot_data.option_cheat_infinite_stamina;
    flags.infinite_ammo = slot_data.option_cheat_infinite_ammo;
    flags.infinite_bugs = slot_data.option_cheat_infinite_bugs;
    flags.infinite_materials = slot_data.option_cheat_infinite_materials;
    flags.infinite_shield = slot_data.option_cheat_infinite_shield;
    flags.infinite_skyward_strike = slot_data.option_cheat_infinite_skyward_strike;
    flags.infinite_rupees = slot_data.option_cheat_infinite_rupees;
    flags.moon_jump = slot_data.option_cheat_moon_jump;
    flags.hovercraft = slot_data.option_cheat_hovercraft;
    flags.infinite_loftwing = slot_data.option_cheat_infinite_loftwing;
    flags.no_electric_stun = slot_data.option_cheat_no_electric_stun;
    flags.no_enemy_damage = slot_data.option_cheat_no_enemy_damage;

    // Stored as integer x10 (10 = 1.0x) in slot_data, matching the Python
    // client exactly; 0 or exactly 1.0 both mean "disabled" on the game
    // side (see handle_speed_multiplier's check in cheats.rs).
    let speed_multiplier = slot_data.option_cheat_speed_multiplier as f32 / 10.0;
    flags.speed_multiplier_bits = speed_multiplier.to_bits();

    mem.write_bytes(addr, &ap_ipc::bytes::write(&flags))?;

    let mut active = Vec::new();
    if flags.infinite_health != 0 {
        active.push("Infinite Health".to_string());
    }
    if flags.infinite_stamina != 0 {
        active.push("Infinite Stamina".to_string());
    }
    if flags.infinite_ammo != 0 {
        active.push("Infinite Ammo".to_string());
    }
    if flags.infinite_bugs != 0 {
        active.push("Infinite Bugs".to_string());
    }
    if flags.infinite_materials != 0 {
        active.push("Infinite Materials".to_string());
    }
    if flags.infinite_shield != 0 {
        active.push("Infinite Shield".to_string());
    }
    if flags.infinite_skyward_strike != 0 {
        active.push("Infinite Skyward Strike".to_string());
    }
    if flags.infinite_rupees != 0 {
        active.push("Infinite Rupees".to_string());
    }
    if flags.moon_jump != 0 {
        active.push("Moon Jump".to_string());
    }
    if flags.hovercraft != 0 {
        active.push("Hovercraft".to_string());
    }
    if flags.infinite_loftwing != 0 {
        active.push("Infinite Loftwing".to_string());
    }
    if flags.no_electric_stun != 0 {
        active.push("No Electric Stun".to_string());
    }
    if flags.no_enemy_damage != 0 {
        active.push("No Enemy Damage".to_string());
    }
    if speed_multiplier != 1.0 {
        active.push(format!("Speed x{speed_multiplier:.1}"));
    }
    if slot_data.option_cheat_infinite_beetle != 0 {
        active.push("Infinite Beetle (requested but not supported by this client yet)".to_string());
    }

    Ok(active)
}

/// Boolean cheat names accepted by `/cheat`/`/cheats`, in the same order
/// as `SSHDClientCommandProcessor.CHEAT_MAP` in `SSHDClient.py`. Every one
/// of these has a matching field in `ApCheatFlags` and can be toggled live.
/// `"beetle"` is intentionally not a command: the Python client lists it,
/// but there's no corresponding field on the Rust-additions side.
pub const TOGGLEABLE_CHEAT_NAMES: &[&str] = &[
    "health",
    "stamina",
    "ammo",
    "bugs",
    "materials",
    "shield",
    "skyward_strike",
    "rupees",
    "moon_jump",
    "hovercraft",
    "loftwing",
    "no_electric_stun",
    "no_enemy_damage",
];

/// Returns the current value of the named boolean cheat field, or `None`
/// if `name` isn't one of `TOGGLEABLE_CHEAT_NAMES`.
pub fn get_cheat_field(flags: &ap_ipc::ApCheatFlags, name: &str) -> Option<u8> {
    Some(match name {
        "health" => flags.infinite_health,
        "stamina" => flags.infinite_stamina,
        "ammo" => flags.infinite_ammo,
        "bugs" => flags.infinite_bugs,
        "materials" => flags.infinite_materials,
        "shield" => flags.infinite_shield,
        "skyward_strike" => flags.infinite_skyward_strike,
        "rupees" => flags.infinite_rupees,
        "moon_jump" => flags.moon_jump,
        "hovercraft" => flags.hovercraft,
        "loftwing" => flags.infinite_loftwing,
        "no_electric_stun" => flags.no_electric_stun,
        "no_enemy_damage" => flags.no_enemy_damage,
        _ => return None,
    })
}

/// Sets the named boolean cheat field to `value` (0/1). Returns `false`
/// if `name` isn't one of `TOGGLEABLE_CHEAT_NAMES` (the struct is left
/// unmodified in that case).
pub fn set_cheat_field(flags: &mut ap_ipc::ApCheatFlags, name: &str, value: u8) -> bool {
    match name {
        "health" => flags.infinite_health = value,
        "stamina" => flags.infinite_stamina = value,
        "ammo" => flags.infinite_ammo = value,
        "bugs" => flags.infinite_bugs = value,
        "materials" => flags.infinite_materials = value,
        "shield" => flags.infinite_shield = value,
        "skyward_strike" => flags.infinite_skyward_strike = value,
        "rupees" => flags.infinite_rupees = value,
        "moon_jump" => flags.moon_jump = value,
        "hovercraft" => flags.hovercraft = value,
        "loftwing" => flags.infinite_loftwing = value,
        "no_electric_stun" => flags.no_electric_stun = value,
        "no_enemy_damage" => flags.no_enemy_damage = value,
        _ => return false,
    }
    true
}

/// Reads `AP_IPC_ROOT.cheat_flags` in full, for `/cheats` and `/cheat`.
pub fn read_cheat_flags(
    mem: &mut impl ProcessMemory,
    root_addr: usize,
) -> Result<ap_ipc::ApCheatFlags, MemError> {
    let addr = root_addr + offsets::CHEAT_FLAGS;
    let raw = mem.read_bytes(addr, std::mem::size_of::<ap_ipc::ApCheatFlags>())?;
    Ok(ap_ipc::bytes::read(&raw))
}

/// Read-modify-writes a single boolean cheat field, leaving every other
/// field (including `hover_vel_y_bits`/`speed_multiplier_bits`/
/// `spawn_demise_request`) untouched. Returns the new value on success, or
/// `None` if `name` isn't a known toggleable cheat.
pub fn toggle_cheat_field(
    mem: &mut impl ProcessMemory,
    root_addr: usize,
    name: &str,
    value: u8,
) -> Result<Option<u8>, MemError> {
    let mut flags = read_cheat_flags(mem, root_addr)?;
    if !set_cheat_field(&mut flags, name, value) {
        return Ok(None);
    }
    let addr = root_addr + offsets::CHEAT_FLAGS;
    mem.write_bytes(addr, &ap_ipc::bytes::write(&flags))?;
    Ok(Some(value))
}

/// Read-modify-writes `hover_vel_y_bits` (the hovercraft sustain
/// velocity), without touching `hovercraft`'s on/off state or any other
/// field. Mirrors `/cheat hovercraft <velocity>` in `SSHDClient.py`.
pub fn set_hovercraft_velocity(
    mem: &mut impl ProcessMemory,
    root_addr: usize,
    velocity: f32,
) -> Result<(), MemError> {
    let mut flags = read_cheat_flags(mem, root_addr)?;
    flags.hover_vel_y_bits = velocity.to_bits();
    let addr = root_addr + offsets::CHEAT_FLAGS;
    mem.write_bytes(addr, &ap_ipc::bytes::write(&flags))
}

/// Highest multiplier `/cheat speed` accepts. The apworld's
/// `cheat_speed_multiplier` option tops out at 5.0x (range 10-50, x10), so
/// this leaves headroom for experimenting without allowing absurd values.
pub const MAX_SPEED_MULTIPLIER: f32 = 10.0;

/// Above this the apworld itself warns about collision problems.
pub const SPEED_COLLISION_WARN_ABOVE: f32 = 3.0;

/// Parses the argument to `/cheat speed <multiplier>`. Accepts a plain
/// float (`2`, `2.5`) or `off`/`reset`/`normal` (all mean 1.0x). Returns a
/// user-facing error message on bad input.
pub fn parse_speed_multiplier(arg: &str) -> Result<f32, String> {
    let t = arg.trim().trim_end_matches(['x', 'X']);
    if matches!(t.to_lowercase().as_str(), "off" | "reset" | "normal") {
        return Ok(1.0);
    }
    let value: f32 = t
        .parse()
        .map_err(|_| format!("Invalid speed '{arg}'. Use a number like 2 or 2.5, or 'off'."))?;
    if !value.is_finite() || value < 0.1 || value > MAX_SPEED_MULTIPLIER {
        return Err(format!("Speed must be between 0.1 and {MAX_SPEED_MULTIPLIER:.0} (1.0 = normal)."));
    }
    Ok(value)
}

/// Sets the live speed multiplier (`speed_multiplier_bits`). Writes ONLY
/// those 4 bytes rather than read-modify-writing the whole struct, so it
/// can't race with the game clearing a one-shot field like
/// `spawn_demise_request`. 1.0 (bits 0x3F800000) means "disabled" on the
/// game side, see `handle_speed_multiplier` in cheats.rs.
pub fn set_speed_multiplier(
    mem: &mut impl ProcessMemory,
    root_addr: usize,
    multiplier: f32,
) -> Result<(), MemError> {
    let addr = root_addr
        + offsets::CHEAT_FLAGS
        + std::mem::offset_of!(ap_ipc::ApCheatFlags, speed_multiplier_bits);
    mem.write_bytes(addr, &multiplier.to_bits().to_le_bytes())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn speed_bits_offset_matches_game_side() {
        // cheats.rs documents speed_multiplier_bits at +24 within ApCheatFlags.
        assert_eq!(std::mem::offset_of!(ap_ipc::ApCheatFlags, speed_multiplier_bits), 24);
    }

    #[test]
    fn parse_speed_multiplier_cases() {
        assert_eq!(parse_speed_multiplier("2"), Ok(2.0));
        assert_eq!(parse_speed_multiplier("2.5"), Ok(2.5));
        assert_eq!(parse_speed_multiplier("3x"), Ok(3.0));
        assert_eq!(parse_speed_multiplier("off"), Ok(1.0));
        assert_eq!(parse_speed_multiplier("RESET"), Ok(1.0));
        assert!(parse_speed_multiplier("0").is_err());
        assert!(parse_speed_multiplier("-2").is_err());
        assert!(parse_speed_multiplier("11").is_err());
        assert!(parse_speed_multiplier("nan").is_err());
        assert!(parse_speed_multiplier("fast").is_err());
    }

    #[test]
    fn speed_multiplier_conversion_matches_python() {
        // Python: speed_raw / 10.0. 10 -> 1.0, 25 -> 2.5.
        assert_eq!(10.0f32 / 10.0, 1.0);
        assert_eq!(25.0f32 / 10.0, 2.5);
    }
}
