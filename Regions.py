"""
Region connection definitions for Skyward Sword HD.

This file defines all regions and their connections for proper logic enforcement.
"""

from typing import TYPE_CHECKING, Dict, List, Tuple

if TYPE_CHECKING:
    from . import SSHDWorld

# Define which regions connect to which (source -> [(destination, rule_name), ...])
# rule_name is the name of the access rule function from Rules.py, or None for no requirement
REGION_CONNECTIONS: Dict[str, List[Tuple[str, str]]] = {
    # Menu to starting location
    "Menu": [
        ("Knight Academy", None),
    ],
    
    # Skyloft areas (all interconnected, no major requirements)
    "Knight Academy": [
        ("Sparring Hall", None),
        ("Upper Skyloft", None),
    ],
    "Sparring Hall": [
        ("Knight Academy", None),
    ],
    "Upper Skyloft": [
        ("Knight Academy", None),
        ("Inside the Statue of the Goddess", None),
        ("Central Skyloft", None),
        ("Bazaar", None),
    ],
    "Central Skyloft": [
        ("Upper Skyloft", None),
        ("Bazaar", None),
        ("Skyloft Village", None),
        ("The Sky", "can_fly"),  # Requires Loftwing
        ("Sky Keep", "can_enter_sky_keep"),  # Requires Clawshots + Stone of Trials
    ],
    "Skyloft Village": [
        ("Central Skyloft", None),
        ("Lumpy Pumpkin", "can_fly"),
        ("Batreaux's House", None),
    ],
    "Bazaar": [
        ("Central Skyloft", None),
        ("Upper Skyloft", None),
    ],
    "Inside the Statue of the Goddess": [
        ("Upper Skyloft", None),
    ],
    "Batreaux's House": [
        ("Skyloft Village", None),
    ],
    
    # Sky regions
    "The Sky": [
        ("Central Skyloft", None),  # Can always return to Skyloft
        ("Sealed Grounds", "can_enter_faron"),
        ("Eldin Volcano", "can_enter_eldin"),
        ("Lanayru Desert", "can_enter_lanayru"),
        ("Lumpy Pumpkin", None),
        ("Fun Fun Island", None),
        ("Beedle's Island", None),
        ("Beedle's Airshop", None),  # Flying shop accessible from sky
        ("Bamboo Island", None),
        ("Volcanic Island", None),
        ("Northeast Island", None),
        ("Orielle's Island", None),
        ("Triple Island", None),
        ("Island Closest to Faron Pillar", None),
        ("Island near Bamboo Island", None),
        ("Inside the Thunderhead", "can_reach_thunderhead"),
    ],
    
    # Sky islands
    "Lumpy Pumpkin": [
        ("The Sky", None),
    ],
    "Fun Fun Island": [
        ("The Sky", None),
    ],
    "Beedle's Island": [
        ("The Sky", None),
    ],
    "Bamboo Island": [
        ("The Sky", None),
        ("Bamboo Island Interior", None),
    ],
    "Bamboo Island Interior": [
        ("Bamboo Island", None),
    ],
    "Volcanic Island": [
        ("The Sky", None),
    ],
    "Isle of Songs": [
        ("The Sky", None),
    ],
    "Inside the Thunderhead": [
        ("The Sky", None),
        ("Bug Heaven", None),
        ("Isle of Songs", None),  # YAML: Inside the Thunderhead -> Isle of Songs: Nothing
    ],
    "Bug Heaven": [
        ("Inside the Thunderhead", None),
    ],
    
    # Sealed Grounds and Temple
    "Sealed Grounds": [
        ("The Sky", None),
        ("Sealed Temple", None),
        ("Temple of Hylia", "can_reach_temple_of_hylia"),
        ("Faron Woods", "can_progress_faron"),
        ("Hylia's Realm", "can_reach_past"),
        ("The Goddess's Silent Realm", "can_enter_goddess_silent_realm"),
    ],
    "Sealed Temple": [
        ("Sealed Grounds", None),
    ],
    "Hylia's Realm": [
        ("Sealed Grounds", "can_reach_present"),
    ],
    
    # Faron Woods region
    "Faron Woods": [
        ("Sealed Grounds", None),
        ("Deep Woods", None),
        ("Inside the Great Tree", None),
        ("Skyview Temple", "can_enter_skyview"),
        ("Lake Floria", "can_reach_lake_floria"),
        ("Farore's Silent Realm", "can_enter_farores_silent_realm"),
    ],
    "Deep Woods": [
        ("Faron Woods", None),
        ("Skyview Spring", "has_skyview_boss_key"),
    ],
    "Inside the Great Tree": [
        ("Faron Woods", None),
    ],
    "Skyview Temple": [
        ("Faron Woods", None),
        ("Skyview Spring", "has_skyview_boss_key"),
    ],
    "Skyview Spring": [
        ("Skyview Temple", None),
    ],
    "Lake Floria": [
        ("Faron Woods", None),
        ("Flooded Faron Woods", "can_reach_flooded_faron"),
        ("Floria Waterfall", "can_swim_underwater"),
        ("Ancient Cistern", "can_enter_ancient_cistern"),
    ],
    "Flooded Faron Woods": [
        ("Lake Floria", None),
        ("Inside the Flooded Great Tree", None),
    ],
    "Inside the Flooded Great Tree": [
        ("Flooded Faron Woods", None),
    ],
    "Ancient Cistern": [
        ("Lake Floria", None),
    ],
    
    # Eldin Volcano region
    "Eldin Volcano": [
        ("The Sky", None),
        ("Mogma Turf", None),
        ("Thrill Digger Cave", None),
        ("Bokoblin Base", "can_reach_bokoblin_base"),
        ("Upper Eldin Cave", None),
        ("Lower Eldin Cave", None),
        ("Earth Temple", "can_enter_earth_temple"),
        ("Fire Sanctuary", "can_enter_fire_sanctuary"),
        ("Din's Silent Realm", "can_enter_dins_silent_realm"),
    ],
    "Mogma Turf": [
        ("Eldin Volcano", None),
    ],
    "Earth Temple": [
        ("Eldin Volcano", None),
        ("Earth Spring", "has_earth_temple_boss_key"),
    ],
    "Earth Spring": [
        ("Earth Temple", None),
    ],
    "Fire Sanctuary": [
        ("Eldin Volcano", None),
    ],
    
    # Lanayru region
    "Lanayru Desert": [
        ("The Sky", None),
        ("Fire Node", None),  # YAML: Fire Node in Lanayru Desert East, no special req
        ("Lightning Node", None),  # YAML: Lightning Node in Lanayru Desert North, no special req
        ("Temple of Time", None),  # YAML: Temple of Time in Lanayru Desert, no Harp req
        ("Lanayru Mine", None),
        ("Lanayru Mining Facility", None),  # No requirement - Gust Bellows is found inside
        ("Lanayru Gorge", "can_reach_lanayru_gorge"),
        ("Nayru's Silent Realm", "can_enter_nayrus_silent_realm"),
    ],
    "Temple of Time": [
        ("Lanayru Desert", None),
    ],
    "Lanayru Mine": [
        ("Lanayru Desert", None),
    ],
    "Lanayru Mining Facility": [
        ("Lanayru Desert", None),
    ],
    "Lanayru Gorge": [
        ("Lanayru Desert", None),
        ("Lanayru Caves", None),
        ("Pirate Stronghold", None),  # YAML: Sand Sea areas accessible without Sea Chart
        ("Skipper's Retreat", None),
        ("Ancient Harbour", None),
        ("Shipyard", None),
        ("Sandship", "can_board_sandship"),  # Requires Sea Chart + Sword
    ],
    "Lanayru Caves": [
        ("Lanayru Gorge", None),
    ],
    "Sandship": [
        ("Lanayru Gorge", None),
    ],
    
    # Silent Realms (each accessible from specific regions)
    "Farore's Silent Realm": [
        ("Faron Woods", None),  # Entered via stone monument
    ],
    "Nayru's Silent Realm": [
        ("Lanayru Desert", None),
    ],
    "Din's Silent Realm": [
        ("Eldin Volcano", None),
    ],
    "The Goddess's Silent Realm": [
        ("Sealed Grounds", None),
    ],
    
    # Sky Keep (late game)
    "Sky Keep": [
        ("The Sky", "can_enter_sky_keep"),
    ],
    
    # Misc regions (locations but not major areas)
    "Beedle's Airshop": [],  # Accessible from sky, but no outgoing connections
    "Thrill Digger Cave": [],
    "Pirate Stronghold": [
        ("Lanayru Gorge", None),
        ("Pirate Stronghold Interior", None),
    ],
    "Pirate Stronghold Interior": [
        ("Pirate Stronghold", None),
    ],
    "Skipper's Retreat": [
        ("Lanayru Gorge", None),
        ("Skipper's Retreat Shack", None),
    ],
    "Skipper's Retreat Shack": [
        ("Skipper's Retreat", None),
    ],
    "Ancient Harbour": [
        ("Lanayru Gorge", None),
    ],
    "Shipyard": [
        ("Lanayru Gorge", None),
        ("Construction Bay", None),
    ],
    "Construction Bay": [
        ("Shipyard", None),
    ],
    "Bokoblin Base": [
        ("Eldin Volcano", None),
        ("Volcano Summit", "can_enter_fire_sanctuary"),
    ],
    "Volcano Summit": [
        ("Bokoblin Base", None),
    ],
    "Floria Waterfall": [
        ("Lake Floria", None),
    ],
    "Fire Node": [
        ("Lanayru Desert", None),
    ],
    "Lightning Node": [
        ("Lanayru Desert", None),
    ],
    "Upper Eldin Cave": [
        ("Eldin Volcano", None),
    ],
    "Lower Eldin Cave": [
        ("Eldin Volcano", None),
    ],
    "Beedle's Airshop": [
        ("The Sky", None),
    ],
    "Thrill Digger Cave": [
        ("Eldin Volcano", None),
    ],
    "Northeast Island": [
        ("The Sky", None),
    ],
    "Orielle's Island": [
        ("The Sky", None),
    ],
    "Triple Island": [
        ("The Sky", None),
    ],
    "Island Closest to Faron Pillar": [
        ("The Sky", None),
    ],
    "Island near Bamboo Island": [
        ("The Sky", None),
    ],
    "Temple of Hylia": [
        ("Sealed Grounds", None),
    ],
}
