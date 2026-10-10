//! AP item code → game `original_id` mapping, generated from `Items.py`'s
//! `ITEM_TABLE` (206 entries as of this port — regenerate this file if
//! `Items.py` changes).
//!
//! Every entry's AP `code` is `2773000 + original_id` (a fixed offset the
//! apworld uses), and `original_id` is exactly the byte value
//! `rust-additions` expects in `ArchipelagoItemSlot` — the low byte in
//! `item_id` and the high byte in `item_id_hi` (see `ap-ipc`), combined by
//! `item.rs::archipelago_check_item_buffer()`, which treats the result as a
//! real item ID and spawns an item actor for it directly. The item actor's
//! id field is 9 bits wide, so ids up to 511 can be delivered.
//!
//! 28 entries (`Game Beatable` + the 27 Goddess Cube pseudo-items, ids
//! 256..=283) are event-only IDs that Archipelago's server logic never
//! actually sends as a `ReceivedItems` payload in normal play (Goddess Cubes
//! are a location-side effect, not an inventory item; Game Beatable is the win
//! condition). `original_id_for_ap_code` returns `None` for these so
//! callers can't accidentally deliver them. Id 255 is the game's "no item"
//! sentinel and is never used.

/// (ap_code, original_id) — sorted by ap_code. The Bird Statue unlock items
/// use ids 300..=322 and therefore sit after the event-only ids.
const ITEM_CODE_TO_ORIGINAL_ID: &[(i64, u16)] = &[
    (2773001, 1), // Small Key
    (2773002, 2), // Green Rupee
    (2773003, 3), // Blue Rupee
    (2773004, 4), // Red Rupee
    (2773006, 6), // Heart
    (2773008, 8), // 10 Arrows
    (2773009, 9), // Goddess White Sword
    (2773010, 10), // Progressive Sword
    (2773011, 11), // Goddess Sword
    (2773012, 12), // Goddess Longsword
    (2773013, 13), // Master Sword
    (2773014, 14), // True Master Sword
    (2773015, 15), // Sailcloth
    (2773016, 16), // Goddess's Harp
    (2773019, 19), // Progressive Bow
    (2773020, 20), // Clawshots
    (2773021, 21), // Spiral Charge
    (2773025, 25), // Ancient Cistern Boss Key
    (2773026, 26), // Fire Sanctuary Boss Key
    (2773027, 27), // Sandship Boss Key
    (2773028, 28), // Key Piece
    (2773029, 29), // Skyview Temple Boss Key
    (2773030, 30), // Earth Temple Boss Key
    (2773031, 31), // Lanayru Mining Facility Boss Key
    (2773032, 32), // Silver Rupee
    (2773033, 33), // Gold Rupee
    (2773034, 34), // Rupoor
    (2773035, 35), // Gratitude Crystal Pack
    (2773036, 36), // Glittering Spores
    (2773040, 40), // 5 Bombs
    (2773041, 41), // 10 Bombs
    (2773042, 42), // Stamina Fruit
    (2773048, 48), // Gratitude Crystal
    (2773049, 49), // Gust Bellows
    (2773050, 50), // Map
    (2773052, 52), // Progressive Slingshot
    (2773053, 53), // Progressive Beetle
    (2773054, 54), // Bottle of Water
    (2773055, 55), // Mushroom Spores
    (2773056, 56), // Progressive Mitts
    (2773057, 57), // 5 Deku Seeds
    (2773060, 60), // 10 Deku Seeds
    (2773063, 63), // Uncommon Treasure
    (2773064, 64), // Rare Treasure
    (2773065, 65), // Guardian Potion
    (2773066, 66), // Guardian Potion Plus
    (2773068, 68), // Water Dragon's Scale
    (2773070, 70), // Bug Medal
    (2773071, 71), // Progressive Bug Net
    (2773072, 72), // Fairy
    (2773074, 74), // Sacred Water
    (2773075, 75), // Hook Beetle
    (2773076, 76), // Quick Beetle
    (2773077, 77), // Tough Beetle
    (2773078, 78), // Heart Potion
    (2773079, 79), // Heart Potion Plus
    (2773081, 81), // Heart Potion Plus Plus
    (2773084, 84), // Stamina Potion
    (2773085, 85), // Stamina Potion Plus
    (2773086, 86), // Air Potion
    (2773087, 87), // Air Potion Plus
    (2773088, 88), // Fairy in a Bottle
    (2773090, 90), // Iron Bow
    (2773091, 91), // Sacred Bow
    (2773092, 92), // Bomb Bag
    (2773093, 93), // Heart Container
    (2773094, 94), // Heart Piece
    (2773095, 95), // Triforce of Courage
    (2773096, 96), // Triforce of Power
    (2773097, 97), // Triforce of Wisdom
    (2773098, 98), // Sea Chart
    (2773099, 99), // Mogma Mitts
    (2773100, 100), // Heart Medal
    (2773101, 101), // Rupee Medal
    (2773102, 102), // Treasure Medal
    (2773103, 103), // Potion Medal
    (2773104, 104), // Cursed Medal
    (2773105, 105), // Scattershot
    (2773108, 108), // Progressive Wallet
    (2773109, 109), // Big Wallet
    (2773110, 110), // Giant Wallet
    (2773111, 111), // Tycoon Wallet
    (2773112, 112), // Progressive Pouch
    (2773113, 113), // Pouch Expansion
    (2773114, 114), // Life Medal
    (2773116, 116), // Wooden Shield
    (2773125, 125), // Hylian Shield
    (2773126, 126), // Revitalizing Potion
    (2773127, 127), // Revitalizing Potion Plus
    (2773128, 128), // Small Seed Satchel
    (2773131, 131), // Small Quiver
    (2773134, 134), // Small Bomb Bag
    (2773137, 137), // Whip
    (2773138, 138), // Fireshield Earrings
    (2773140, 140), // Big Bug Net
    (2773141, 141), // Faron Grasshopper
    (2773142, 142), // Woodland Rhino Beetle
    (2773143, 143), // Deku Hornet
    (2773144, 144), // Skyloft Mantis
    (2773145, 145), // Volcanic Ladybug
    (2773146, 146), // Blessed Butterfly
    (2773147, 147), // Lanayru Ant
    (2773148, 148), // Sand Cicada
    (2773149, 149), // Gerudo Dragonfly
    (2773150, 150), // Eldin Roller
    (2773151, 151), // Sky Stag Beetle
    (2773152, 152), // Starry Firefly
    (2773153, 153), // Empty Bottle
    (2773158, 158), // Cawlin's Letter
    (2773159, 159), // Beedle's Insect Cage
    (2773160, 160), // Rattle
    (2773161, 161), // Hornet Larvae
    (2773162, 162), // Bird Feather
    (2773163, 163), // Tumbleweed
    (2773164, 164), // Lizard Tail
    (2773165, 165), // Eldin Ore
    (2773166, 166), // Ancient Flower
    (2773167, 167), // Amber Relic
    (2773168, 168), // Dusk Relic
    (2773169, 169), // Jelly Blob
    (2773170, 170), // Monster Claw
    (2773171, 171), // Monster Horn
    (2773172, 172), // Ornamental Skull
    (2773173, 173), // Evil Crystal
    (2773174, 174), // Blue Bird Feather
    (2773175, 175), // Golden Skull
    (2773176, 176), // Goddess Plume
    (2773177, 177), // Emerald Tablet
    (2773178, 178), // Ruby Tablet
    (2773179, 179), // Amber Tablet
    (2773180, 180), // Stone of Trials
    (2773186, 186), // Ballad of the Goddess
    (2773187, 187), // Farore's Courage
    (2773188, 188), // Nayru's Wisdom
    (2773189, 189), // Din's Power
    (2773190, 190), // Song of the Hero Part
    (2773191, 191), // Eldin Song of the Hero Part
    (2773192, 192), // Lanayru Song of the Hero Part
    (2773193, 193), // Song of the Hero
    (2773194, 194), // Revitalizing Potion Plus Plus
    (2773195, 195), // Hot Pumpkin Soup
    (2773196, 196), // Cold Pumpkin Soup
    (2773197, 197), // Life Tree Seedling
    (2773198, 198), // Life Tree Fruit
    (2773199, 199), // Extra Wallet
    (2773200, 200), // Skyview Temple Small Key
    (2773201, 201), // Lanayru Mining Facility Small Key
    (2773202, 202), // Ancient Cistern Small Key
    (2773203, 203), // Fire Sanctuary Small Key
    (2773204, 204), // Sandship Small Key
    (2773205, 205), // Sky Keep Small Key
    (2773206, 206), // Lanayru Caves Small Key
    (2773207, 207), // Skyview Temple Map
    (2773208, 208), // Earth Temple Map
    (2773209, 209), // Lanayru Mining Facility Map
    (2773210, 210), // Ancient Cistern Map
    (2773211, 211), // Fire Sanctuary Map
    (2773212, 212), // Sandship Map
    (2773213, 213), // Sky Keep Map
    (2773214, 214), // Group of Tadtones
    (2773215, 215), // Scrapper
    (2773216, 216), // Archipelago Item
    (2773217, 217), // Greg The Green Rupee
    (2773218, 218), // Tim The Tumbleweed
    (2773219, 219), // Progressive Loftwing (tier 1: Loftwing 219, tier 2: Spiral Charge 21 -- see progressive_tier_original_id)
    (2773220, 220), // Skyview Temple Key Ring
    (2773221, 221), // Lanayru Mining Facility Key Ring
    (2773222, 222), // Ancient Cistern Key Ring
    (2773223, 223), // Fire Sanctuary Key Ring
    (2773224, 224), // Sandship Key Ring
    (2773225, 225), // Sky Keep Key Ring
    (2773226, 226), // Lanayru Caves Key Ring
    (2773227, 227), // Skeleton Key
    (2773250, 250), // Health Trap
    (2773251, 251), // Groose Trap
    (2773252, 252), // Noise Trap
    (2773253, 253), // Curse Trap
    (2773254, 254), // Burn Trap
    (2773256, 256), // Game Beatable
    (2773257, 257), // Faron Woods Goddess Cube on West Great Tree near Exit
    (2773258, 258), // Faron Woods Goddess Cube on East Great Tree with Clawshots Target
    (2773259, 259), // Faron Woods Goddess Cube on East Great Tree with Rope
    (2773260, 260), // Deep Woods Goddess Cube near Goron
    (2773261, 261), // Deep Woods Goddess Cube in front of Temple
    (2773262, 262), // Deep Woods Goddess Cube on top of Temple
    (2773263, 263), // Lake Floria Goddess Cube
    (2773264, 264), // Floria Waterfall Goddess Cube on High Ledge
    (2773265, 265), // Eldin Volcano Goddess Cube at Eldin Entrance
    (2773266, 266), // Eldin Volcano Goddess Cube near Mogma Turf Entrance
    (2773267, 267), // Eldin Volcano Goddess Cube West of Temple
    (2773268, 268), // Eldin Volcano Goddess Cube East of Temple
    (2773269, 269), // Eldin Volcano Goddess Cube on Sand Slide
    (2773270, 270), // Mogma Turf Goddess Cube on Raised Pillar
    (2773271, 271), // Volcano Summit Goddess Cube in Lava Lake
    (2773272, 272), // Volcano Summit Goddess Cube at Summit Waterfall
    (2773273, 273), // Volcano Summit Goddess Cube near Fire Sanctuary Entrance
    (2773274, 274), // Lanayru Mine Goddess Cube behind First Landing Robot
    (2773275, 275), // Lanayru Desert Goddess Cube near Caged Robot
    (2773276, 276), // Lanayru Desert Goddess Cube in Sand Oasis
    (2773277, 277), // Lanayru Desert Goddess Cube in Secret Passageway
    (2773278, 278), // Temple of Time Goddess Cube
    (2773279, 279), // Lanayru Gorge Goddess Cube
    (2773280, 280), // Ancient Harbour Goddess Cube
    (2773281, 281), // Skipper's Retreat Goddess Cube
    (2773282, 282), // Pirate Stronghold Goddess Cube
    (2773283, 283), // Skyview Spring Goddess Cube
    (2773300, 300), // Behind the Temple Statue Unlock
    (2773301, 301), // Faron Woods Entry Statue Unlock
    (2773302, 302), // In the Woods Statue Unlock
    (2773303, 303), // Viewing Platform Statue Unlock
    (2773304, 304), // Deep Woods Statue Unlock
    (2773305, 305), // Forest Temple Statue Unlock
    (2773306, 306), // The Great Tree Statue Unlock
    (2773307, 307), // Lake Floria Statue Unlock
    (2773308, 308), // Floria Waterfall Statue Unlock
    (2773309, 309), // Volcano East Statue Unlock
    (2773310, 310), // Volcano Ascent Statue Unlock
    (2773311, 311), // Temple Entrance Statue Unlock
    (2773312, 312), // Desert Entrance Statue Unlock
    (2773313, 313), // West Desert Statue Unlock
    (2773314, 314), // Desert Gorge Statue Unlock
    (2773315, 315), // Temple of Time Statue Unlock
    (2773316, 316), // North Desert Statue Unlock
    (2773317, 317), // Stone Cache Statue Unlock
    (2773318, 318), // Ancient Harbour Statue Unlock
    (2773319, 319), // Skipper's Retreat Statue Unlock
    (2773320, 320), // Shipyard Statue Unlock
    (2773321, 321), // Pirate Stronghold Statue Unlock
    (2773322, 322), // Lanayru Gorge Statue Unlock
];

/// AP item code base — every SSHD item's `code` is `2773000 + original_id`.
pub const AP_CODE_BASE: i64 = 2773000;

/// AP code of "Progressive Loftwing" (the code the old standalone "Loftwing"
/// item had). The game has no native tier resolution for it, so the client
/// resolves the tier itself: 1st copy -> Loftwing, 2nd copy -> Spiral Charge.
pub const PROGRESSIVE_LOFTWING_CODE: i64 = 2773219;

/// Game item ids for each Progressive Loftwing tier, in order.
const PROGRESSIVE_LOFTWING_TIERS: [u16; 2] = [219, 21];

/// Like `original_id_for_ap_code`, but resolves progressive items the game
/// can't resolve on its own. `prior_copies` is how many copies of this same
/// AP item were received before this one (start-inventory copies included).
pub fn progressive_tier_original_id(ap_code: i64, prior_copies: usize) -> Option<u16> {
    if ap_code == PROGRESSIVE_LOFTWING_CODE {
        let tier = prior_copies.min(PROGRESSIVE_LOFTWING_TIERS.len() - 1);
        return Some(PROGRESSIVE_LOFTWING_TIERS[tier]);
    }
    original_id_for_ap_code(ap_code)
}

/// Highest game item id the item actor's 9-bit id field can hold.
pub const MAX_DELIVERABLE_ITEM_ID: u16 = 511;

/// Look up the game's `original_id` for an Archipelago item code. Returns
/// `None` if the code is unrecognized, OR if it maps to an id that can't be
/// delivered through `ArchipelagoItemSlot`: the event-only ids 256..=283
/// (Game Beatable + Goddess Cube pseudo-items) and 255, the game's "no item"
/// sentinel.
pub fn original_id_for_ap_code(ap_code: i64) -> Option<u16> {
    let idx = ITEM_CODE_TO_ORIGINAL_ID
        .binary_search_by_key(&ap_code, |&(code, _)| code)
        .ok()?;
    let (_, original_id) = ITEM_CODE_TO_ORIGINAL_ID[idx];
    if (1..=254).contains(&original_id) || (300..=MAX_DELIVERABLE_ITEM_ID).contains(&original_id) {
        Some(original_id)
    } else {
        None
    }
}

/// Names of the items `/go_mode` counts, keyed by `original_id`. Only these
/// are needed: local (not yet echoed by the server) items are matched by name.
const GO_MODE_ITEM_NAMES: &[(i64, &str)] = &[
    (10, "Progressive Sword"),
    (16, "Goddess's Harp"),
    (95, "Triforce of Courage"),
    (96, "Triforce of Power"),
    (97, "Triforce of Wisdom"),
    (186, "Ballad of the Goddess"),
    (190, "Song of the Hero Part"),
    (191, "Eldin Song of the Hero Part"),
    (192, "Lanayru Song of the Hero Part"),
    (193, "Song of the Hero"),
    (217, "Greg The Green Rupee"),
    (218, "Tim The Tumbleweed"),
];

/// Name of a `/go_mode`-relevant item from either its AP code or its
/// `original_id` (slot_data may carry either form).
pub fn go_mode_item_name(id: i64) -> Option<&'static str> {
    let original = if id >= AP_CODE_BASE { id - AP_CODE_BASE } else { id };
    GO_MODE_ITEM_NAMES.iter().find(|(o, _)| *o == original).map(|(_, n)| *n)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn table_is_sorted_by_code() {
        let codes: Vec<i64> = ITEM_CODE_TO_ORIGINAL_ID.iter().map(|&(c, _)| c).collect();
        let mut sorted = codes.clone();
        sorted.sort();
        assert_eq!(codes, sorted, "table must stay sorted for binary_search_by_key");
    }

    #[test]
    fn known_items_resolve() {
        assert_eq!(original_id_for_ap_code(2773001), Some(1)); // Small Key
        assert_eq!(original_id_for_ap_code(2773092), Some(92)); // Bomb Bag
        assert_eq!(original_id_for_ap_code(2773219), Some(219)); // Progressive Loftwing (tier 1)
        assert_eq!(original_id_for_ap_code(2773254), Some(254)); // Burn Trap
    }

    #[test]
    fn progressive_loftwing_resolves_tiers() {
        assert_eq!(progressive_tier_original_id(2773219, 0), Some(219)); // Loftwing
        assert_eq!(progressive_tier_original_id(2773219, 1), Some(21)); // Spiral Charge
        assert_eq!(progressive_tier_original_id(2773219, 5), Some(21)); // clamps to last tier
        // Non-loftwing items fall through to the plain table lookup.
        assert_eq!(progressive_tier_original_id(2773001, 3), Some(1));
    }

    #[test]
    fn bird_statue_unlocks_resolve_above_255() {
        assert_eq!(original_id_for_ap_code(2773300), Some(300)); // Behind the Temple
        assert_eq!(original_id_for_ap_code(2773322), Some(322)); // Lanayru Gorge
        // The old statue ids (228..=249, and 156 for Lanayru Gorge) are gone.
        assert_eq!(original_id_for_ap_code(2773228), None);
        assert_eq!(original_id_for_ap_code(2773156), None);
    }

    #[test]
    fn event_only_ids_are_rejected_not_truncated() {
        // Game Beatable (256) and all 27 Goddess Cubes (257..=283) are
        // event-only and must come back None, never a delivered item.
        assert_eq!(original_id_for_ap_code(2773256), None);
        assert_eq!(original_id_for_ap_code(2773257), None);
        assert_eq!(original_id_for_ap_code(2773283), None);
    }

    #[test]
    fn unknown_code_is_none() {
        assert_eq!(original_id_for_ap_code(999999), None);
    }
}
