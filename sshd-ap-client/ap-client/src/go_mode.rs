//! `/go_mode`: seed-specific game-completion requirements, ported from
//! `SSHDClient.py`'s `get_go_mode_requirements`.
//!
//! Kept free of any emulator/AP-connection types on purpose: the caller
//! passes in the owned-item counts and a closure that answers "is this
//! storyflag set?", so the rules themselves are plain, unit-testable
//! code.

use std::collections::HashMap;

use crate::locations::SlotData;

/// One line of `/go_mode` output.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Requirement {
    pub label: String,
    pub have:  i64,
    pub need:  i64,
}

impl Requirement {
    pub fn met(&self) -> bool {
        self.have >= self.need
    }
}

/// Dungeon-boss kill storyflags, from `fix-boss-doors.asm` (same table as
/// the Python client). Distinct from storyflags 900/901 ("Beaten Ancient
/// Cistern" / "Beaten Fire Sanctuary"), which mark full dungeon clears,
/// not the boss kill itself.
pub const DUNGEON_BOSS_FLAGS: &[(&str, u16)] = &[
    ("Skyview Temple", 0x53),           // Ghirahim 1
    ("Earth Temple", 0x7),              // Scaldera
    ("Lanayru Mining Facility", 0x32C), // Moldarach
    ("Ancient Cistern", 0x288),         // Koloktos
    ("Fire Sanctuary", 0x54),           // Ghirahim 2
    ("Sandship", 0x3A5),                // Tentalus
];

/// Builds the requirement list plus any explanatory notes.
/// `owned` maps item name -> count received. `boss_flag_set` reports
/// whether a given storyflag is set in-game (only called when the
/// dungeon-goal requirement is active).
pub fn requirements(
    slot_data: &SlotData,
    owned: &HashMap<String, i64>,
    boss_flag_set: &mut dyn FnMut(u16) -> bool,
) -> (Vec<Requirement>, Vec<String>) {
    let mut reqs = Vec::new();
    let mut notes = Vec::new();
    let have = |name: &str| owned.get(name).copied().unwrap_or(0);

    let mut add = |label: String, have: i64, need: i64| {
        reqs.push(Requirement { label, have, need });
    };

    // Gate of Time sword requirement.
    let sword_needed = match slot_data.option_gate_of_time_sword_requirement {
        0 => 2, // goddess_sword
        1 => 3, // goddess_longsword
        2 => 4, // goddess_white_sword
        3 => 5, // master_sword
        4 => 6, // true_master_sword
        _ => 6,
    };
    add("Progressive Sword".to_string(), have("Progressive Sword"), sword_needed);

    // Main-quest song chain.
    add("Goddess's Harp".to_string(), have("Goddess's Harp"), 1);
    add("Ballad of the Goddess".to_string(), have("Ballad of the Goddess"), 1);
    let song_parts_have: i64 = [
        "Song of the Hero Part",
        "Eldin Song of the Hero Part",
        "Lanayru Song of the Hero Part",
        "Song of the Hero",
    ]
    .iter()
    .map(|n| have(*n))
    .sum();
    add("Song of the Hero Parts".to_string(), song_parts_have, 4);

    // Optional dungeon requirement: counts real boss-kill storyflags, not
    // boss keys (a key can arrive via the multiworld long before the
    // dungeon is entered).
    if slot_data.option_dungeon_goal_requirement != 0 && slot_data.option_boss_key_shuffle != 6 {
        let needed = slot_data.option_required_dungeon_count.clamp(0, DUNGEON_BOSS_FLAGS.len() as i64);
        let defeated = DUNGEON_BOSS_FLAGS.iter().filter(|(_, flag)| boss_flag_set(*flag)).count() as i64;
        let names: Vec<&str> = DUNGEON_BOSS_FLAGS.iter().map(|(n, _)| *n).collect();
        add(format!("Dungeon Bosses Defeated ({})", names.join(", ")), defeated, needed);
    }

    // Optional Triforce requirement.
    if slot_data.option_require_triforce_pieces != 0 {
        let items = ["Triforce of Courage", "Triforce of Power", "Triforce of Wisdom"];
        let needed = slot_data.option_required_triforce_pieces.clamp(0, items.len() as i64);
        let got: i64 = items.iter().map(|n| have(*n)).sum();
        add(format!("Any Triforce Pieces ({})", items.join(", ")), got, needed);
    }

    // Optional Greg / Tim requirements.
    if slot_data.option_require_greg != 0 {
        add("Greg The Green Rupee".to_string(), have("Greg The Green Rupee"), 1);
    }
    if slot_data.option_require_tim != 0 {
        add("Tim The Tumbleweed".to_string(), have("Tim The Tumbleweed"), 1);
    }

    // We can't derive the full target set client-side from slot_data.
    if slot_data.option_require_all_progression_items != 0 {
        notes.push(
            "Require All Progression Items is enabled: every progression item in your seed is required."
                .to_string(),
        );
        notes.push("This command currently reports the explicit victory-rule requirements above.".to_string());
    }

    (reqs, notes)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn slot(json: &str) -> SlotData {
        serde_json::from_str(json).unwrap()
    }

    #[test]
    fn default_requirements_need_true_master_sword() {
        let sd = slot("{}");
        let owned = HashMap::new();
        let (reqs, notes) = requirements(&sd, &owned, &mut |_| false);
        assert!(notes.is_empty());
        assert_eq!(reqs[0].label, "Progressive Sword");
        assert_eq!(reqs[0].need, 6);
        assert_eq!(reqs.len(), 4);
        assert!(reqs.iter().all(|r| !r.met()));
    }

    #[test]
    fn dungeon_goal_counts_boss_flags() {
        let sd = slot(r#"{"option_dungeon_goal_requirement": 1, "option_required_dungeon_count": 2}"#);
        let owned = HashMap::new();
        let (reqs, _) = requirements(&sd, &owned, &mut |flag| flag == 0x53 || flag == 0x7);
        let dungeons = reqs.iter().find(|r| r.label.starts_with("Dungeon Bosses")).unwrap();
        assert_eq!((dungeons.have, dungeons.need), (2, 2));
        assert!(dungeons.met());
    }

    #[test]
    fn options_accept_bool_and_string_forms() {
        let sd = slot(r#"{"option_require_greg": true, "option_require_tim": "on"}"#);
        let owned = HashMap::new();
        let (reqs, _) = requirements(&sd, &owned, &mut |_| false);
        assert!(reqs.iter().any(|r| r.label == "Greg The Green Rupee"));
        assert!(reqs.iter().any(|r| r.label == "Tim The Tumbleweed"));
    }
}
