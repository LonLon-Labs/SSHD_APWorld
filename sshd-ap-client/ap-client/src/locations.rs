//! Location-check detection.
//!
//! Ports the majority-case mechanism from `SSHDClient.py`'s
//! `check_custom_flags`: most SSHD locations are tracked via a "custom
//! flag" — a 10-bit encoding (see `ap_ipc::custom_flag`) that packs a
//! sceneflag-or-dungeonflag bit into one of 4 scenes the randomizer
//! reserves for this purpose. The AP server tells us, in `slot_data`,
//! which flag_id corresponds to which of its location codes
//! (`custom_flag_to_location`); we batch-read the relevant scene/dungeon
//! flag arrays directly (via addresses `rust-additions` now exposes in
//! `AP_IPC_ROOT`) and diff against the last-seen state, exactly like the
//! Python client did — a handful of reads covering potentially hundreds of
//! locations, not one `flag_request` round trip per location.
//!
//! The other three check-detection mechanisms from `SSHDClient.py` —
//! goddess chests, Beedle's shop, boss defeats — are ported in
//! `goddess_chests.rs`, `beedle_shop.rs`, and `boss_defeats.rs`
//! respectively; this file also owns `SlotData` since all of them read
//! from it.

use std::collections::HashMap;

use ap_ipc::{custom_flag, offsets};
use process_memory::{MemError, ProcessMemory};
use serde::Deserialize;

/// Slot data received from the Archipelago server on connect. Only fields
/// this client currently uses are declared — serde ignores any other keys
/// the server's slot_data payload contains.
#[derive(Debug, Clone, Deserialize, Default)]
pub struct SlotData {
    /// flag_id (as encoded by `ap_ipc::custom_flag`) -> AP location code.
    /// The server sends this as a JSON object, whose keys are always
    /// strings even though the values are the game's numeric flag_ids —
    /// `deserialize_u16_keyed_map` parses those keys back to `u16`.
    #[serde(default, deserialize_with = "deserialize_u16_keyed_map")]
    pub custom_flag_to_location: HashMap<u16, i64>,

    /// AP location code -> (scene_index, chestflag), for goddess chests.
    /// The server sends this as `{"<location_code>": [scene_index,
    /// chestflag]}`.
    #[serde(default, deserialize_with = "deserialize_goddess_chest_map")]
    pub goddess_chest_scene_flags: HashMap<i64, (u16, u8)>,

    /// flag_id (same `custom_flag` encoding as `custom_flag_to_location`)
    /// -> the real item name and owning player name for that location, so
    /// the game can show "You found a(n) X for Y!" instead of the generic
    /// "Archipelago Item" / "another player" placeholder text when the
    /// location's item belongs to someone else. Mirrors `SSHDClient.py`'s
    /// `ap_item_info` slot_data handling; see `item_info.rs` for what
    /// writes this into the game's `item_info_table`. The server sends
    /// this as `{"<flag_id>": {"item": ..., "player": ...}}`.
    #[serde(default, deserialize_with = "deserialize_item_info_map")]
    pub ap_item_info: HashMap<u16, ApItemInfo>,

    /// AP location code -> the item placed there and the slot that owns it.
    /// Used by `/go_mode` to count items sitting in locations you've already
    /// checked locally (before the server echoes them back). Sent as
    /// `{"<location_code>": {"item_id": ..., "player": ...}}`.
    #[serde(default, deserialize_with = "deserialize_location_item_map")]
    pub location_to_item_map: HashMap<i64, LocationItem>,

    /// DeathLink / BreathLink slot options (enable the matching tag on connect).
    #[serde(default, deserialize_with = "deserialize_lenient_i64", rename = "option_death_link")]
    pub option_death_link: i64,
    #[serde(default, deserialize_with = "deserialize_lenient_i64", rename = "option_breath_link")]
    pub option_breath_link: i64,

    // ── Cheat toggles, mirroring SSHDClient.py's `option_cheat_*` slot_data
    // reads. Sent as 0/1 integers (not JSON booleans), matching Python's
    // `bool(slot_data.get(key, 0))` pattern, so these are `u8` rather than
    // `bool` to accept that shape directly.
    #[serde(default, rename = "option_cheat_infinite_health")]
    pub option_cheat_infinite_health: u8,
    #[serde(default, rename = "option_cheat_infinite_stamina")]
    pub option_cheat_infinite_stamina: u8,
    #[serde(default, rename = "option_cheat_infinite_ammo")]
    pub option_cheat_infinite_ammo: u8,
    #[serde(default, rename = "option_cheat_infinite_bugs")]
    pub option_cheat_infinite_bugs: u8,
    #[serde(default, rename = "option_cheat_infinite_materials")]
    pub option_cheat_infinite_materials: u8,
    #[serde(default, rename = "option_cheat_infinite_shield")]
    pub option_cheat_infinite_shield: u8,
    #[serde(default, rename = "option_cheat_infinite_skyward_strike")]
    pub option_cheat_infinite_skyward_strike: u8,
    #[serde(default, rename = "option_cheat_infinite_rupees")]
    pub option_cheat_infinite_rupees: u8,
    #[serde(default, rename = "option_cheat_moon_jump")]
    pub option_cheat_moon_jump: u8,
    #[serde(default, rename = "option_cheat_hovercraft")]
    pub option_cheat_hovercraft: u8,
    /// Present in the Python client's slot_data handling, but there's no
    /// corresponding field in `ApCheatFlags` on the Rust-additions side —
    /// that cheat was never implemented there. Kept here so `cheat_sync.rs`
    /// can at least log that it was requested but isn't supported.
    #[serde(default, rename = "option_cheat_infinite_beetle")]
    pub option_cheat_infinite_beetle: u8,
    #[serde(default, rename = "option_cheat_infinite_loftwing")]
    pub option_cheat_infinite_loftwing: u8,
    #[serde(default, rename = "option_cheat_no_electric_stun")]
    pub option_cheat_no_electric_stun: u8,
    #[serde(default, rename = "option_cheat_no_enemy_damage")]
    pub option_cheat_no_enemy_damage: u8,
    /// Stored as integer x10 (10 = 1.0x, 20 = 2.0x, ...), matching Python's
    /// `speed_raw / 10.0` convention exactly. Defaults to 10 (1.0x, i.e.
    /// no change) when absent, same as Python's `.get(..., 10)`.
    #[serde(default = "default_speed_multiplier", rename = "option_cheat_speed_multiplier")]
    pub option_cheat_speed_multiplier: u32,

    // ── Victory-condition options, read by `/go_mode` (see `go_mode.rs`),
    // mirroring `get_go_mode_requirements` in SSHDClient.py. The server may
    // send these as bool, int, or string depending on the option type, so
    // they go through `deserialize_lenient_i64` (same normalization as
    // Python's `_slot_option_enabled`) instead of a strict type.
    #[serde(default = "default_gate_of_time_sword", deserialize_with = "deserialize_lenient_i64", rename = "option_gate_of_time_sword_requirement")]
    pub option_gate_of_time_sword_requirement: i64,
    #[serde(default = "default_boss_key_shuffle", deserialize_with = "deserialize_lenient_i64", rename = "option_boss_key_shuffle")]
    pub option_boss_key_shuffle: i64,
    #[serde(default, deserialize_with = "deserialize_lenient_i64", rename = "option_dungeon_goal_requirement")]
    pub option_dungeon_goal_requirement: i64,
    #[serde(default = "default_required_dungeon_count", deserialize_with = "deserialize_lenient_i64", rename = "option_required_dungeon_count")]
    pub option_required_dungeon_count: i64,
    #[serde(default, deserialize_with = "deserialize_lenient_i64", rename = "option_require_triforce_pieces")]
    pub option_require_triforce_pieces: i64,
    #[serde(default = "default_required_triforce_pieces", deserialize_with = "deserialize_lenient_i64", rename = "option_required_triforce_pieces")]
    pub option_required_triforce_pieces: i64,
    #[serde(default, deserialize_with = "deserialize_lenient_i64", rename = "option_require_greg")]
    pub option_require_greg: i64,
    #[serde(default, deserialize_with = "deserialize_lenient_i64", rename = "option_require_tim")]
    pub option_require_tim: i64,
    #[serde(default, deserialize_with = "deserialize_lenient_i64", rename = "option_require_all_progression_items")]
    pub option_require_all_progression_items: i64,
}

fn default_speed_multiplier() -> u32 {
    10
}

impl SlotData {
    /// `ap_item_info` as the game needs it. Beedle's Airshop items are looked
    /// up in-game by `0x8000 | sold_out_storyflag` (see `shop.rs`), but
    /// seeds generated before the apworld fix key them by their ordinary
    /// custom flag instead (every location gets one). For each Beedle
    /// location, if there's no `0x8000|storyflag` entry yet, copy the one
    /// found under its custom flag to that key, so old and new seeds both
    /// work. Non-Beedle entries pass through untouched.
    pub fn item_info_for_game(&self) -> HashMap<u16, ApItemInfo> {
        let mut out = self.ap_item_info.clone();
        for &(storyflag, location_code) in crate::beedle_shop::BEEDLE_STORYFLAG_TO_LOCATION {
            let game_key = 0x8000 | storyflag;
            if out.contains_key(&game_key) {
                continue;
            }
            let custom_flag = self
                .custom_flag_to_location
                .iter()
                .find(|(_, &loc)| loc == location_code)
                .map(|(&flag, _)| flag);
            if let Some(info) = custom_flag.and_then(|f| self.ap_item_info.get(&f)) {
                out.insert(game_key, info.clone());
            }
        }
        out
    }
}

fn default_gate_of_time_sword() -> i64 {
    4
}

fn default_boss_key_shuffle() -> i64 {
    1
}

fn default_required_dungeon_count() -> i64 {
    2
}

fn default_required_triforce_pieces() -> i64 {
    3
}

/// Accepts a bool, integer, float, or string slot_data value and
/// normalizes it to an `i64` (bools -> 0/1; strings "true"/"on"/"yes" ->
/// 1, "false"/"off"/"no" -> 0, numeric strings parsed; anything
/// unparseable -> 0), mirroring Python's `_slot_option_enabled`
/// normalization.
fn deserialize_lenient_i64<'de, D>(deserializer: D) -> Result<i64, D::Error>
where
    D: serde::Deserializer<'de>,
{
    #[derive(Deserialize)]
    #[serde(untagged)]
    enum Lenient {
        Bool(bool),
        Int(i64),
        Float(f64),
        Str(String),
    }

    Ok(match Lenient::deserialize(deserializer)? {
        Lenient::Bool(b) => b as i64,
        Lenient::Int(i) => i,
        Lenient::Float(f) => f as i64,
        Lenient::Str(s) => {
            let s = s.trim().to_lowercase();
            match s.as_str() {
                "true" | "on" | "yes" => 1,
                "false" | "off" | "no" | "" => 0,
                other => other.parse::<i64>().unwrap_or(0),
            }
        },
    })
}

fn deserialize_u16_keyed_map<'de, D>(deserializer: D) -> Result<HashMap<u16, i64>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let raw: HashMap<String, i64> = HashMap::deserialize(deserializer)?;
    Ok(raw.into_iter().filter_map(|(k, v)| k.parse::<u16>().ok().map(|k| (k, v))).collect())
}

fn deserialize_goddess_chest_map<'de, D>(
    deserializer: D,
) -> Result<HashMap<i64, (u16, u8)>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let raw: HashMap<String, (u16, u8)> = HashMap::deserialize(deserializer)?;
    Ok(raw.into_iter().filter_map(|(k, v)| k.parse::<i64>().ok().map(|k| (k, v))).collect())
}

/// The real item name and owning player name for one `ap_item_info` entry
/// -- see `SlotData::ap_item_info`'s field doc.
#[derive(Debug, Clone, Deserialize, Default)]
pub struct ApItemInfo {
    #[serde(default)]
    pub item:   String,
    #[serde(default)]
    pub player: String,
}

/// One `location_to_item_map` entry.
#[derive(Debug, Clone, Deserialize, Default)]
pub struct LocationItem {
    #[serde(default)]
    pub item_id: i64,
    #[serde(default)]
    pub player:  i64,
}

fn deserialize_location_item_map<'de, D>(
    deserializer: D,
) -> Result<HashMap<i64, LocationItem>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let raw: HashMap<String, LocationItem> = HashMap::deserialize(deserializer)?;
    Ok(raw.into_iter().filter_map(|(k, v)| k.parse::<i64>().ok().map(|k| (k, v))).collect())
}

fn deserialize_item_info_map<'de, D>(
    deserializer: D,
) -> Result<HashMap<u16, ApItemInfo>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let raw: HashMap<String, ApItemInfo> = HashMap::deserialize(deserializer)?;
    Ok(raw.into_iter().filter_map(|(k, v)| k.parse::<u16>().ok().map(|k| (k, v))).collect())
}

/// Polls the custom-flag location-check mechanism. Call `poll()` once per
/// loop tick; it returns any AP location codes that should be reported to
/// the server via `client.mark_checked(...)`.
pub struct CustomFlagPoller {
    flag_to_location: HashMap<u16, i64>,
    previous_state:   HashMap<u16, u8>,
    initialized:      bool,
}

const FLAG_ARRAY_BYTES: usize = 26 * 8 * 2; // [[u16; 8]; 26]

impl CustomFlagPoller {
    pub fn new(flag_to_location: HashMap<u16, i64>) -> Self {
        CustomFlagPoller { flag_to_location, previous_state: HashMap::new(), initialized: false }
    }

    pub fn location_count(&self) -> usize {
        self.flag_to_location.len()
    }

    /// Returns newly-checked AP location codes. On the very FIRST call, any
    /// flag that is ALREADY set is also returned — this mirrors the Python
    /// client's "recovered unsent check" behavior for checks completed
    /// while the client wasn't running, rather than silently swallowing
    /// them into the initial baseline. `already_checked` lets the caller
    /// suppress locations it already knows are done (e.g. from the AP
    /// server's own `checked_locations` on connect).
    pub fn poll(
        &mut self,
        mem: &mut impl ProcessMemory,
        root_addr: usize,
        already_checked: &impl Fn(i64) -> bool,
    ) -> Result<Vec<i64>, MemError> {
        if self.flag_to_location.is_empty() {
            return Ok(Vec::new());
        }

        let sceneflags = mem.read_bytes(root_addr + offsets::SCENEFLAGS, FLAG_ARRAY_BYTES)?;
        let dungeonflags = mem.read_bytes(root_addr + offsets::DUNGEONFLAGS, FLAG_ARRAY_BYTES)?;

        let is_first_poll = !self.initialized;
        let mut newly_checked = Vec::new();

        for (&flag_id, &location_code) in &self.flag_to_location {
            let d = custom_flag::decode(flag_id);
            let array = if d.is_dungeonflag { &dungeonflags } else { &sceneflags };
            let byte_offset = (d.scene_index as usize) * 16 + d.array_index * 2;
            let u16_val = u16::from_le_bytes([array[byte_offset], array[byte_offset + 1]]);
            let bit = ((u16_val >> d.bit_index) & 1) as u8;

            let previous = self.previous_state.insert(flag_id, bit);
            if already_checked(location_code) {
                continue;
            }
            match previous {
                None if is_first_poll && bit == 1 => newly_checked.push(location_code),
                Some(0) if bit == 1 => newly_checked.push(location_code),
                _ => {},
            }
        }

        self.initialized = true;
        Ok(newly_checked)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn slot_data_parses_string_keyed_json() {
        let json = r#"{"custom_flag_to_location": {"5": 2773006, "261": 2773100}}"#;
        let parsed: SlotData = serde_json::from_str(json).unwrap();
        assert_eq!(parsed.custom_flag_to_location.get(&5), Some(&2773006));
        assert_eq!(parsed.custom_flag_to_location.get(&261), Some(&2773100));
    }

    #[test]
    fn slot_data_defaults_when_key_missing() {
        let parsed: SlotData = serde_json::from_str("{}").unwrap();
        assert!(parsed.custom_flag_to_location.is_empty());
        assert!(parsed.goddess_chest_scene_flags.is_empty());
    }

    #[test]
    fn slot_data_parses_goddess_chest_map() {
        let json = r#"{"goddess_chest_scene_flags": {"2773500": [21, 40]}}"#;
        let parsed: SlotData = serde_json::from_str(json).unwrap();
        assert_eq!(parsed.goddess_chest_scene_flags.get(&2773500), Some(&(21, 40)));
    }

    #[test]
    fn slot_data_parses_ap_item_info_map() {
        let json = r#"{"ap_item_info": {"261": {"item": "Green Rupee", "player": "ShipOfHarkinianPlayer"}}}"#;
        let parsed: SlotData = serde_json::from_str(json).unwrap();
        let entry = parsed.ap_item_info.get(&261).expect("flag 261 present");
        assert_eq!(entry.item, "Green Rupee");
        assert_eq!(entry.player, "ShipOfHarkinianPlayer");
    }
}
