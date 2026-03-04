"""
Access rules for Skyward Sword HD Archipelago World.

Defines logical requirements for accessing locations and regions.
"""

from typing import TYPE_CHECKING

from BaseClasses import CollectionState
from .Locations import LOCATION_TABLE

if TYPE_CHECKING:
    from . import SSHDWorld


def set_rules(world: "SSHDWorld") -> None:
    """
    Set all access rules for the world.
    
    This is called during world generation to establish what items are
    needed to access each location.
    """
    multiworld = world.multiworld
    player = world.player
    options = world.options
    
    # Get regions
    menu = multiworld.get_region("Menu", player)
    
    # Helper functions for checking items
    def has(state: CollectionState, item: str) -> bool:
        """Check if player has an item."""
        return state.has(item, player)
    
    def has_all(state: CollectionState, *items: str) -> bool:
        """Check if player has all specified items."""
        return all(state.has(item, player) for item in items)
    
    def has_any(state: CollectionState, *items: str) -> bool:
        """Check if player has any of the specified items."""
        return any(state.has(item, player) for item in items)
    
    def count(state: CollectionState, item: str) -> int:
        """Count how many of an item the player has."""
        return state.count(item, player)
    
    # Progressive item helpers
    def has_sword(state: CollectionState, level: int = 1) -> bool:
        """
        Check if player has sword of at least the specified level.
        
        Starting swords from config.yaml are precollected as Progressive Swords,
        so state.count already includes them. No additional starting offset needed.
        
        Sword levels: 0=none, 1=practice, 2=goddess, 3=longsword, 4=white, 5=master, 6=true_master
        """
        return count(state, "Progressive Sword") >= level
    
    def has_slingshot(state: CollectionState) -> bool:
        """Check if player has any slingshot."""
        return count(state, "Progressive Slingshot") >= 1
    
    def has_beetle(state: CollectionState) -> bool:
        """Check if player has any beetle."""
        return count(state, "Progressive Beetle") >= 1
    
    def has_mitts(state: CollectionState) -> bool:
        """Check if player has digging mitts."""
        return count(state, "Progressive Mitts") >= 1
    
    def has_bow(state: CollectionState) -> bool:
        """Check if player has any bow."""
        return count(state, "Progressive Bow") >= 1
    
    def can_use_bombs(state: CollectionState) -> bool:
        """Check if player can use bombs."""
        return has(state, "Bomb Bag")
    
    def can_swim_underwater(state: CollectionState) -> bool:
        """Check if player can swim underwater."""
        return has(state, "Water Dragon's Scale")
    
    def can_fly(state: CollectionState) -> bool:
        """Check if player can fly in the sky."""
        return has(state, "Sailcloth")
    
    # Apply entrance rules from Regions.py connections
    from .Regions import REGION_CONNECTIONS
    
    for source_name, connections in REGION_CONNECTIONS.items():
        try:
            source_region = multiworld.get_region(source_name, player)
        except KeyError:
            continue  # Region doesn't exist, skip
        
        for dest_name, rule_name in connections:
            try:
                dest_region = multiworld.get_region(dest_name, player)
            except KeyError:
                continue  # Destination doesn't exist, skip
            
            # Find the entrance by searching through the source region's exits
            entrance_name = f"{source_name} -> {dest_name}"
            entrance = None
            for exit in source_region.exits:
                if exit.name == entrance_name:
                    entrance = exit
                    break
            
            if not entrance:
                continue
            
            # Apply access rules based on rule name
            if rule_name == "has_sword":
                entrance.access_rule = lambda state: has_sword(state, 1)
            elif rule_name == "can_fly":
                entrance.access_rule = lambda state: can_fly(state)
            elif rule_name == "can_enter_faron":
                entrance.access_rule = lambda state: can_fly(state)
            elif rule_name == "can_enter_eldin":
                entrance.access_rule = lambda state: can_fly(state)
            elif rule_name == "can_enter_lanayru":
                entrance.access_rule = lambda state: can_fly(state)
            elif rule_name == "can_progress_faron":
                entrance.access_rule = lambda state: has_sword(state, 1)
            elif rule_name == "can_enter_skyview":
                entrance.access_rule = lambda state: has_slingshot(state)
            elif rule_name == "has_skyview_boss_key":
                entrance.access_rule = lambda state: has(state, "Skyview Temple Boss Key")
            elif rule_name == "can_reach_lake_floria":
                entrance.access_rule = lambda state: has(state, "Water Dragon's Scale")
            elif rule_name == "can_reach_flooded_faron":
                entrance.access_rule = lambda state: has(state, "Whip") and can_swim_underwater(state)
            elif rule_name == "can_enter_ancient_cistern":
                entrance.access_rule = lambda state: has(state, "Whip") and can_swim_underwater(state)
            elif rule_name == "can_enter_earth_temple":
                entrance.access_rule = lambda state: can_use_bombs(state) and has_beetle(state)
            elif rule_name == "has_earth_temple_boss_key":
                entrance.access_rule = lambda state: has(state, "Earth Temple Boss Key")
            elif rule_name == "can_enter_fire_sanctuary":
                entrance.access_rule = lambda state: has(state, "Fireshield Earrings") and can_use_bombs(state)
            elif rule_name == "can_enter_temple_of_time":
                entrance.access_rule = lambda state: has(state, "Goddess's Harp")
            elif rule_name == "can_enter_lanayru_mining_facility":
                entrance.access_rule = lambda state: has(state, "Gust Bellows")
            elif rule_name == "can_reach_lanayru_gorge":
                entrance.access_rule = lambda state: has(state, "Clawshots")
            elif rule_name == "can_board_sandship":
                entrance.access_rule = lambda state: has(state, "Clawshots")
            elif rule_name == "can_reach_thunderhead":
                # Only requires Goddess's Harp to play Ballad of the Goddess
                entrance.access_rule = lambda state: has(state, "Goddess's Harp")
            elif rule_name == "can_reach_isle_of_songs":
                entrance.access_rule = lambda state: has(state, "Clawshots")
            elif rule_name == "can_enter_sky_keep":
                entrance.access_rule = lambda state: has(state, "Stone of Trials")
            elif rule_name == "can_reach_past":
                # Gate of Time: requires Goddess's Harp + Ballad of the Goddess + sword level
                # from got_sword_requirement setting (matches sshd-rando's Faron.yaml logic)
                resolved = getattr(world, '_sshd_resolved_settings', {})
                got_sword = resolved.get('got_sword_requirement', 'true_master_sword')
                sword_level_map = {
                    'goddess_sword': 2,
                    'goddess_longsword': 3,
                    'goddess_white_sword': 4,
                    'master_sword': 5,
                    'true_master_sword': 6,
                }
                req_level = sword_level_map.get(got_sword, 6)
                entrance.access_rule = lambda state, lvl=req_level: (
                    has(state, "Goddess's Harp")
                    and has(state, "Ballad of the Goddess")
                    and has_sword(state, lvl)
                )
            elif rule_name == "can_reach_present":
                # Returning from the past is always possible once you're there
                entrance.access_rule = lambda state: True
            elif rule_name == "can_reach_temple_of_hylia":
                entrance.access_rule = lambda state: has(state, "Ballad of the Goddess")
            elif rule_name == "can_reach_bokoblin_base":
                entrance.access_rule = lambda state: can_use_bombs(state) or has(state, "Clawshots")
            elif rule_name == "can_activate_fire_node":
                entrance.access_rule = lambda state: has(state, "Goddess's Harp")
            elif rule_name == "can_activate_lightning_node":
                entrance.access_rule = lambda state: has(state, "Goddess's Harp")
            elif rule_name == "can_reach_sand_sea":
                entrance.access_rule = lambda state: has(state, "Sea Chart")
            elif rule_name == "can_enter_silent_realm":
                # Silent Realms only require Goddess's Harp and basic Goddess Sword (level 1)
                entrance.access_rule = lambda state: has(state, "Goddess's Harp") and has_sword(state, 1)
            else:
                # If rule_name is None or unknown, always accessible
                entrance.access_rule = lambda state: True
    
    # Additional helper functions
    def can_cut_grass(state: CollectionState) -> bool:
        """Check if player can cut grass/vines."""
        return has_sword(state, 1)  # Any sword works
    
    def can_dousing(state: CollectionState) -> bool:
        """Check if player can use dowsing."""
        return has_sword(state, 1)  # Practice Sword enables dowsing
    
    def can_use_goddess_walls(state: CollectionState) -> bool:
        """Check if player can use goddess walls."""
        return has_sword(state, 2)  # Goddess Sword enables walls
    
    def can_open_goddess_chests(state: CollectionState) -> bool:
        """Check if player can open goddess chests."""
        return has_sword(state, 2) and can_dousing(state)
    
    # Wallet capacity helpers
    def wallet_capacity(state: CollectionState) -> int:
        """Get current wallet capacity."""
        wallet_count = count(state, "Progressive Wallet")
        extra_wallets = count(state, "Extra Wallet")
        
        # Progressive wallet: 300 -> 500 -> 1000 -> 5000 -> 9000
        capacities = [300, 500, 1000, 5000, 9000]
        capacity = capacities[min(wallet_count, len(capacities) - 1)]
        
        # Each extra wallet adds +300
        capacity += extra_wallets * 300
        
        return capacity
    
    def can_afford(state: CollectionState, cost: int) -> bool:
        """Check if player can afford something."""
        return wallet_capacity(state) >= cost
    
    # Region access helpers for major areas
    def can_access_faron(state: CollectionState) -> bool:
        """Check if player can access Faron Woods region."""
        return can_fly(state)  # Need sailcloth to reach surface
    
    def can_access_eldin(state: CollectionState) -> bool:
        """Check if player can access Eldin Volcano region."""
        return can_fly(state)  # Need sailcloth to reach surface
    
    def can_access_lanayru(state: CollectionState) -> bool:
        """Check if player can access Lanayru Desert region."""
        return can_fly(state)  # Need sailcloth to reach surface
    
    # Dungeon access requirements
    def can_access_skyview(state: CollectionState) -> bool:
        """Check if player can access Skyview Temple."""
        return can_access_faron(state) and has_slingshot(state)
    
    def can_access_earth_temple(state: CollectionState) -> bool:
        """Check if player can access Earth Temple."""
        return can_access_eldin(state) and can_use_bombs(state) and has_beetle(state)
    
    def can_access_lanayru_mining_facility(state: CollectionState) -> bool:
        """Check if player can access Lanayru Mining Facility."""
        return can_access_lanayru(state) and has(state, "Gust Bellows")
    
    def can_access_ancient_cistern(state: CollectionState) -> bool:
        """Check if player can access Ancient Cistern."""
        return can_access_faron(state) and has(state, "Whip") and can_swim_underwater(state)
    
    def can_access_sandship(state: CollectionState) -> bool:
        """Check if player can access Sandship."""
        return can_access_lanayru(state) and has(state, "Clawshots") and has_bow(state)
    
    def can_access_fire_sanctuary(state: CollectionState) -> bool:
        """Check if player can access Fire Sanctuary."""
        return can_access_eldin(state) and has_mitts(state) and has(state, "Water Basin")
    
    # Set location access rules
    # These are BASIC rules - full logic would be much more complex
    for location in multiworld.get_locations(player):
        location_name = location.name
        location_types = LOCATION_TABLE.get(location_name)
        
        if not location_types:
            continue
        
        types = location_types.types if hasattr(location_types, 'types') else []
        
        # Dungeon-specific rules
        if "Skyview Temple" in location_name:
            location.access_rule = lambda state: has_slingshot(state)
        
        elif "Earth Temple" in location_name:
            location.access_rule = lambda state: has_all(state, "Bomb Bag", "Progressive Beetle")
        
        elif "Ancient Cistern" in location_name:
            location.access_rule = lambda state: has_all(state, "Whip", "Water Dragon's Scale")
        
        elif "Sandship" in location_name:
            location.access_rule = lambda state: has(state, "Clawshots")
        
        elif "Fire Sanctuary" in location_name:
            location.access_rule = lambda state: has_all(state, "Fireshield Earrings", "Bomb Bag")
        
        # Sky Keep - no location requirements needed
        # Entrance requirement (Stone of Trials) handles access
        # Boss keys were removed due to circular dependencies
        
        # Boss fights require boss keys
        if "Defeat Boss" in location_name or "Boss Key" in location_name:
            if "Skyview" in location_name:
                location.access_rule = lambda state: has(state, "Skyview Temple Boss Key")
            elif "Earth Temple" in location_name:
                location.access_rule = lambda state: has(state, "Earth Temple Boss Key")
        
        # Goddess Cube checks require various items
        if "Goddess Cube" in location_name or "Goddess Chest" in location_name:
            if "Clawshot" in location_name:
                location.access_rule = lambda state: has(state, "Clawshots")
            elif "Beetle" in location_name:
                location.access_rule = lambda state: has_beetle(state)
        
        # Silent Realm checks - NO LOCATION REQUIREMENTS
        # Entrance requirements (Harp + Sword level 1) handle access
        # Removed all completion item requirements due to circular dependencies
        # if "Silent Realm" in location_name:
        #     # Only require completion items for collecting tears/relics, not for the final reward
        #     if "Collect all Tears Reward" not in location_name:
        #         if "Farore" in location_name:
        #             location.access_rule = lambda state: has(state, "Farore's Courage")
        #         elif "Nayru" in location_name:
        #             location.access_rule = lambda state: has(state, "Nayru's Wisdom")
        #         elif "Din" in location_name:
        #             location.access_rule = lambda state: has(state, "Din's Power")
        #         elif "Goddess" in location_name:
        #             location.access_rule = lambda state: has(state, "Song of the Hero")
        
        # Victory location - just needs to reach Hylia's Realm (handled by region access)
        # The "Game Beatable" event is what's checked by completion_condition
    
    # Set goal/victory condition
    # The victory is represented by the "Game Beatable" event item.
    # All game-completion requirements (boss keys, sword level) are embedded
    # directly in the event location's access rule (in logic_converter.py),
    # so the fill algorithm properly tracks these dependencies.
    multiworld.completion_condition[player] = lambda state: has(state, "Game Beatable")


def set_completion_condition(world: "SSHDWorld") -> None:
    """
    Set only the completion condition (used when full logic is handled by logic_converter).
    
    The full logic converter sets all entrance/location rules, including the
    Game Beatable event's access rule which embeds boss key + sword checks.
    This function just sets the final victory condition.
    """
    multiworld = world.multiworld
    player = world.player
    
    multiworld.completion_condition[player] = lambda state: (
        state.has("Game Beatable", player)
    )


def _can_complete_game(state: CollectionState, world: "SSHDWorld") -> bool:
    """
    Check if the player can complete the game.
    
    Uses sshd-rando's resolved settings (stored in world._sshd_resolved_settings)
    to ensure the completion condition matches the actual item pool. Falls back to
    safe defaults if resolved settings are unavailable.
    
    Requirements:
    - Required number of dungeons beaten (via boss keys, unless boss_keys=removed)
    - Gate of Time sword requirement met
    """
    player = world.player
    resolved = getattr(world, '_sshd_resolved_settings', {})
    
    # --- Dungeon completion check ---
    # Only check boss keys if they actually exist in the pool (boss_keys != removed)
    boss_keys_setting = resolved.get('boss_keys', 'own_dungeon')
    
    if boss_keys_setting != 'removed':
        # Get required dungeon count from sshd-rando settings
        try:
            required_dungeons = int(resolved.get('required_dungeons', '2'))
        except (ValueError, TypeError):
            required_dungeons = 2
        
        dungeon_items = [
            "Skyview Temple Boss Key",
            "Earth Temple Boss Key",
            "Lanayru Mining Facility Boss Key",
            "Ancient Cistern Boss Key",
            "Sandship Boss Key",
            "Fire Sanctuary Boss Key"
        ]
        
        # Cap at 6: Sky Keep (7th dungeon) has no boss key.
        # Its accessibility is handled by region/entrance logic.
        boss_keys_needed = min(required_dungeons, len(dungeon_items))
        dungeons_beaten = sum(1 for key in dungeon_items if state.has(key, player))
        if dungeons_beaten < boss_keys_needed:
            return False
    
    # --- Gate of Time sword requirement ---
    # Use sshd-rando's got_sword_requirement setting
    got_sword = resolved.get('got_sword_requirement', 'true_master_sword')
    sword_name_to_level = {
        'goddess_sword': 2,
        'goddess_longsword': 3,
        'goddess_white_sword': 4,
        'master_sword': 5,
        'true_master_sword': 6,
    }
    required_sword_level = sword_name_to_level.get(got_sword, 6)
    
    # Starting swords are precollected as Progressive Swords, so state.count
    # already includes them. No additional starting offset needed.
    current_sword_level = state.count("Progressive Sword", player)
    if current_sword_level < required_sword_level:
        return False
    
    return True


def _get_sword_level(state: CollectionState, player: int) -> int:
    """Get the player's sword level (= number of Progressive Swords collected)."""
    return state.count("Progressive Sword", player)


def _has_sword_level(state: CollectionState, player: int, level: int) -> bool:
    """
    Check if player has at least the specified sword level.
    
    Levels (= Progressive Sword count):
    0 = None
    1 = Practice Sword
    2 = Goddess Sword
    3 = Goddess Longsword
    4 = Goddess White Sword
    5 = Master Sword
    6 = True Master Sword
    """
    return _get_sword_level(state, player) >= level


def _can_access_surface(state: CollectionState, player: int) -> bool:
    """Check if player can access the Surface from Skyloft."""
    return state.has("Sailcloth", player)


def _can_open_gate_of_time(state: CollectionState, world: "SSHDWorld") -> bool:
    """Check if player can open the Gate of Time."""
    player = world.player
    resolved = getattr(world, '_sshd_resolved_settings', {})
    
    # Check sword requirement from sshd-rando settings
    got_sword = resolved.get('got_sword_requirement', 'true_master_sword')
    sword_name_to_level = {
        'goddess_sword': 2,
        'goddess_longsword': 3,
        'goddess_white_sword': 4,
        'master_sword': 5,
        'true_master_sword': 6,
    }
    required_level = sword_name_to_level.get(got_sword, 6)
    if not _has_sword_level(state, player, required_level):
        return False
    
    return True


# Additional helper functions for specific checks
# These will be expanded as the logic is implemented

def _can_use_gust_bellows(state: CollectionState, player: int) -> bool:
    """Check if player has Gust Bellows."""
    return state.has("Gust Bellows", player)


def _can_use_clawshots(state: CollectionState, player: int) -> bool:
    """Check if player has Clawshots."""
    return state.has("Clawshots", player)


def _can_use_bow(state: CollectionState, player: int) -> bool:
    """Check if player has any Bow."""
    return state.has("Progressive Bow", player)


def _can_use_whip(state: CollectionState, player: int) -> bool:
    """Check if player has Whip."""
    return state.has("Whip", player)


def _can_use_bombs(state: CollectionState, player: int) -> bool:
    """Check if player has Bomb Bag."""
    return state.has("Bomb Bag", player)
