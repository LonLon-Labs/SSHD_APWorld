//! Stage code <-> friendly name table, ported verbatim from
//! `SSHDClient.py`'s `STAGE_NAMES` / `_resolve_stage_code`, for the
//! `/warp` command.

/// (stage code, friendly name), exactly mirroring `STAGE_NAMES` in
/// `SSHDClient.py`.
pub const STAGE_NAMES: &[(&str, &str)] = &[
    // Skyloft and interiors
    ("F000", "Skyloft"),
    ("F001r", "Knight Academy"),
    ("F002r", "Beedle's Airshop"),
    ("F004r", "Bazaar"),
    ("F005r", "Orielle and Parrow's House"),
    ("F006r", "Kukiel's House"),
    ("F007r", "Piper's House"),
    ("F008r", "Inside the Statue of the Goddess"),
    ("F009r", "Sparring Hall"),
    ("F010r", "Isle of Songs"),
    ("F011r", "Lumpy Pumpkin"),
    ("F012r", "Batreaux's House"),
    ("F013r", "Sparrot's House"),
    ("F014r", "Potion Shop"),
    ("F015r", "Scrap Shop"),
    ("F016r", "Pipit's House"),
    ("F017r", "Rupin's House"),
    ("F018r", "Peatrice's House"),
    ("F019r", "Bamboo Island"),
    ("F020", "The Sky"),
    ("F021", "Cutscene Sky"),
    ("F023", "Thunderhead"),
    // Faron region
    ("F100", "Faron Woods"),
    ("F100_1", "Great Tree"),
    ("F101", "Deep Woods"),
    ("F102", "Lake Floria"),
    ("F102_1", "Outside Ancient Cistern"),
    ("F102_2", "Faron's Lair"),
    ("F103", "Flooded Faron Woods"),
    ("F103_1", "Flooded Great Tree"),
    // Eldin region
    ("F200", "Eldin Volcano"),
    ("F201", "Volcano Summit"),
    ("F201_1", "Inside the Volcano"),
    ("F201_2", "Inside the Volcano (Bokoblin Base)"),
    ("F201_3", "Outside Fire Sanctuary"),
    ("F201_4", "Volcano Waterfall"),
    ("F202", "Bokoblin Base"),
    ("F210", "Mogma Turf"),
    ("F211", "Thrill Digger"),
    ("F221", "Fire Dragon Room"),
    // Lanayru region
    ("F300", "Lanayru Desert"),
    ("F300_1", "Lanayru Mine"),
    ("F300_2", "Lightning Node"),
    ("F300_3", "Fire Node"),
    ("F300_4", "Temple of Time"),
    ("F300_5", "Lanayru Mining Facility to Temple of Time"),
    ("F301", "Ancient Harbour"),
    ("F301_1", "Lanayru Sand Sea"),
    ("F301_2", "Inside Pirate Stronghold"),
    ("F301_3", "Skipper's Retreat"),
    ("F301_4", "Shipyard"),
    ("F301_5", "Skipper's Retreat Shack"),
    ("F301_6", "Outside Pirate Stronghold"),
    ("F301_7", "Construction Bay"),
    ("F302", "Lanayru Gorge"),
    ("F303", "Lanayru Caves"),
    // Sealed grounds and late-game stages
    ("F400", "Behind the Temple"),
    ("F401", "Sealed Grounds Spiral"),
    ("F402", "Sealed Temple"),
    ("F403", "Ghirahim Boss Arena"),
    ("F404", "Sealed Grounds Temple (Past)"),
    ("F405", "Sealed Grounds Spiral Cutscene (first cutscene)"),
    ("F407", "Sky Keep beaten CS"),
    // Dungeons
    ("D000", "Waterfall Cave"),
    ("D003_0", "Sky Keep Courage Room"),
    ("D003_1", "Sky Keep Earth Temple Room"),
    ("D003_2", "Sky Keep Power Room"),
    ("D003_3", "Sky Keep Wisdom Room"),
    ("D003_4", "Sky Keep LMF Room"),
    ("D003_5", "Sky Keep Skyview Temple Room"),
    ("D003_6", "Sky Keep"),
    ("D003_7", "Sky Keep Entrance Room"),
    ("D003_8", "Triforce Room"),
    ("D100", "Skyview Temple"),
    ("D101", "Ancient Cistern"),
    ("D200", "Earth Temple"),
    ("D201", "Fire Sanctuary"),
    ("D201_1", "Fire Sanctuary (Inner)"),
    ("D300", "Lanayru Mining Facility"),
    ("D300_1", "Lanayru Mining Facility (Back)"),
    ("D301", "Sandship"),
    ("D301_1", "Sandship (Escape)"),
    // Silent realms
    ("S000", "The Goddess's Silent Realm"),
    ("S100", "Farore's Silent Realm"),
    ("S200", "Din's Silent Realm"),
    ("S300", "Nayru's Silent Realm"),
    // Boss stages
    ("B100", "Ghirahim 1 Boss Room"),
    ("B100_1", "Skyview Spring"),
    ("B101", "Koloktos Boss Room"),
    ("B101_1", "Ancient Cistern Crest Room"),
    ("B200", "Scaldera Boss Room"),
    ("B201", "Ghirahim 2 Boss Room"),
    ("B201_1", "Fire Sanctuary Crest Room"),
    ("B210", "Earth Spring"),
    ("B300", "Moldarach Boss Room"),
    ("B301", "Tentalus Boss Room"),
    ("B400", "Demise's Realm"),
];

/// Resolve `/warp`'s stage argument to a stage code. Accepts either a
/// stage code directly (case-insensitive, e.g. "f000" or "F103_1") or a
/// friendly name from `STAGE_NAMES` (case-insensitive, e.g. "skyloft" or
/// "Lanayru Mining Facility") -- mirrors `_resolve_stage_code` in
/// `SSHDClient.py`.
pub fn resolve_stage_code(text: &str) -> Option<&'static str> {
    let text = text.trim();
    if text.is_empty() {
        return None;
    }
    let lower = text.to_lowercase();
    for &(code, _name) in STAGE_NAMES {
        if code.to_lowercase() == lower {
            return Some(code);
        }
    }
    for &(code, name) in STAGE_NAMES {
        if name.to_lowercase() == lower {
            return Some(code);
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolves_by_code_case_insensitive() {
        assert_eq!(resolve_stage_code("f000"), Some("F000"));
        assert_eq!(resolve_stage_code("F103_1"), Some("F103_1"));
    }

    #[test]
    fn resolves_by_friendly_name_case_insensitive() {
        assert_eq!(resolve_stage_code("skyloft"), Some("F000"));
        assert_eq!(resolve_stage_code("Lanayru Mining Facility"), Some("D300"));
    }

    #[test]
    fn unknown_returns_none() {
        assert_eq!(resolve_stage_code("not a real stage"), None);
    }
}
