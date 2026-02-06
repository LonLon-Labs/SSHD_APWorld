"""
Options for Skyward Sword HD Archipelago World.
"""

from dataclasses import dataclass

from Options import (
    Choice,
    DeathLink,
    DefaultOnToggle,
    FreeText,
    ItemDict,
    PerGameCommonOptions,
    Range,
    Toggle,
)


# === Core Logic Settings ===

class LogicRules(Choice):
    """
    Determines what logic the randomizer uses.
    All Locations Reachable: The randomizer ensures that all locations can be reached. If a location's item is required to beat the game, that item is placed where it can be obtained.
    Beatable Only: The randomizer only ensures the game is beatable. Some locations may be unreachable, and items required to reach those locations will not be placed at them.
    """
    display_name = "Logic Rules"
    option_all_locations_reachable = 0
    option_beatable_only = 1
    default = 0


class ItemPool(Choice):
    """
    Determines the size of the item pool.
    Minimal: Only essential items are included.
    Standard: Normal item pool with standard items.
    Extra: Extra items added for more variety.
    Plentiful: Maximum items for a more relaxed experience.
    """
    display_name = "Item Pool"
    option_minimal = 0
    option_standard = 1
    option_extra = 2
    option_plentiful = 3
    default = 1


# === Completion Requirements ===

class RequiredDungeonCount(Range):
    """
    Determines the number of dungeons required to beat the seed.
    Beating Sky Keep is NOT required.
    Lanayru Mining Facility is beaten when exiting to the Temple of Time.
    Other dungeons are beaten when the Goddess Crest is struck with a Skyward Strike.
    """
    display_name = "Required Dungeon Count"
    range_start = 0
    range_end = 6
    default = 2


class TriforceRequired(DefaultOnToggle):
    """
    If enabled, the three Triforces will be required to open the door to Hylia's Realm at the end.
    """
    display_name = "Triforce Required"


class TriforceShuffle(Choice):
    """
    Choose where Triforces will appear in the game.
    Vanilla: Triforces are placed in their vanilla locations in Sky Keep.
    Sky Keep: Triforces are shuffled only within Sky Keep.
    Anywhere: Triforces are shuffled with all other valid locations in the game.
    """
    display_name = "Triforce Shuffle"
    option_vanilla = 0
    option_sky_keep = 1
    option_anywhere = 2
    default = 2


class GateOfTimeSwordRequirement(Choice):
    """
    Determines the sword needed to open the Gate of Time.
    """
    display_name = "Gate of Time Sword Requirement"
    option_goddess_sword = 0
    option_goddess_longsword = 1
    option_goddess_white_sword = 2
    option_master_sword = 3
    option_true_master_sword = 4
    default = 4


class GateOfTimeDungeonRequirements(Choice):
    """
    Enables dungeon requirements for opening the Gate of Time.
    Required: beating the required dungeons is necessary to open the Gate of Time.
    Unrequired: the Gate of Time can be opened without beating the required dungeons.
    """
    display_name = "Gate of Time Dungeon Requirements"
    option_required = 0
    option_unrequired = 1
    default = 0


class Imp2Skip(DefaultOnToggle):
    """
    If enabled, the requirement to defeat Imprisoned 2 at the end is skipped.
    """
    display_name = "Imp 2 Skip"


class SkipHorde(Toggle):
    """
    If enabled, the requirement to defeat The Horde at the end is skipped.
    """
    display_name = "Skip Horde"


class SkipGhirahim3(Toggle):
    """
    If enabled, the requirement to defeat Ghirahim 3 at the end is skipped.
    """
    display_name = "Skip Ghirahim 3"


# === Randomization Settings ===

class GratitudeCrystalShuffle(Toggle):
    """Shuffle gratitude crystals into the item pool."""
    display_name = "Gratitude Crystal Shuffle"

class StaminaFruitShuffle(Toggle):
    """Shuffle stamina fruits into the item pool."""
    display_name = "Stamina Fruit Shuffle"

class NpcClosetShuffle(Toggle):
    """Shuffle NPC closets."""
    display_name = "NPC Closet Shuffle"

class HiddenItemShuffle(Toggle):
    """Shuffle hidden items."""
    display_name = "Hidden Item Shuffle"

class RupeeShuffle(Choice):
    """Shuffle rupees with varying difficulty."""
    display_name = "Rupee Shuffle"
    option_vanilla = 0
    option_beginner = 1
    option_intermediate = 2
    option_advanced = 3
    default = 0

class GoddessChestShuffle(Toggle):
    """Shuffle goddess chests."""
    display_name = "Goddess Chest Shuffle"

class TrialTreasureShuffle(Range):
    """Number of trial treasures to shuffle (0-10)."""
    display_name = "Trial Treasure Shuffle"
    range_start = 0
    range_end = 10
    default = 0

class TadtoneShuffle(Toggle):
    """Shuffle tadtones."""
    display_name = "Tadtone Shuffle"

class GossipStoneTreasureShuffle(Toggle):
    """Shuffle gossip stone treasures."""
    display_name = "Gossip Stone Treasure Shuffle"

class SmallKeyShuffle(Choice):
    """Where small keys can appear."""
    display_name = "Small Key Shuffle"
    option_own_dungeon = 0
    option_any_dungeon = 1
    option_anywhere = 2
    option_keysy = 3
    default = 0

class BossKeyShuffle(Choice):
    """Where boss keys can appear."""
    display_name = "Boss Key Shuffle"
    option_own_dungeon = 0
    option_any_dungeon = 1
    option_anywhere = 2
    option_keysy = 3
    default = 0

class MapShuffle(Choice):
    """Where dungeon maps can appear."""
    display_name = "Map Shuffle"
    option_vanilla = 0
    option_own_dungeon_restricted = 1
    option_anywhere = 2
    default = 0

class RandomizeEntrances(Toggle):
    """
    Randomize dungeon entrances and major area connections.
    """
    display_name = "Randomize Entrances"


class RandomizeDungeons(Toggle):
    """
    Randomize dungeon entrances only.
    """
    display_name = "Randomize Dungeons"


class RandomizeTrials(Toggle):
    """
    Randomize Silent Realm trial entrances.
    """
    display_name = "Randomize Trials"


class RandomizeDoorEntrances(Toggle):
    """
    Randomize door entrances (interior and overworld doors).
    """
    display_name = "Randomize Door Entrances"


class DecoupleSkykeepLayout(Toggle):
    """
    Randomize the layout/order of Sky Keep rooms.
    """
    display_name = "Randomize Sky Keep Layout"


class RandomizeInteriorEntrances(Toggle):
    """
    Randomize interior building entrances.
    """
    display_name = "Randomize Interior Entrances"


class RandomizeOverworldEntrances(Toggle):
    """
    Randomize overworld region entrances.
    """
    display_name = "Randomize Overworld Entrances"


class DecoupleEntrances(Toggle):
    """
    Decouple forward and return entrances (entrances are no longer guaranteed to return you to where you came from).
    """
    display_name = "Decouple Entrances"


class DecopleDoubleDoors(Toggle):
    """
    Decouple left and right double doors so they can lead to different locations.
    """
    display_name = "Decouple Double Doors"


# === Starting Inventory ===

class StartingTablets(Range):
    """
    Number of tablets (Ruby, Amber, Emerald) to start with.
    """
    display_name = "Starting Tablets"
    range_start = 0
    range_end = 3
    default = 0


class StartingSword(Choice):
    """
    Which sword to start with.
    """
    display_name = "Starting Sword"
    option_none = 0
    option_practice_sword = 1
    option_goddess_sword = 2
    option_goddess_longsword = 3
    option_goddess_white_sword = 4
    option_master_sword = 5
    option_true_master_sword = 6
    default = 1


class CustomStartingItems(ItemDict):
    """
    Add custom items to starting inventory as a YAML dictionary.
    Format: {"Item Name": count, "Another Item": count}
    Leave empty {} for no custom items.
    See Available_Starting_Items.yaml for all available items.
    """
    display_name = "Custom Starting Items"
    default = {}


class RandomStartingStatues(Toggle):
    """
    Randomize which bird statue is unlocked at the start for each surface region.
    """
    display_name = "Random Starting Statues"


class RandomStartingSpawn(Choice):
    """
    Randomize where you start the game.
    """
    display_name = "Randomize Starting Spawn"
    option_vanilla = 0
    option_anywhere = 1
    default = 0


class LimitStartingSpawn(Toggle):
    """
    If enabled with Randomize Starting Spawn, limit spawn to regions where you have starting tablets.
    """
    display_name = "Limit Starting Spawn"


class RandomStartingItemCount(Range):
    """
    Number of additional random items to start with from the item pool.
    """
    display_name = "Random Starting Item Count"
    range_start = 0
    range_end = 6
    default = 0


class PeatriceConversations(Range):
    """
    How many times you need to talk to Peatrice before she calls you darling and you can start Peater's quest.
    """
    display_name = "Peatrice Conversations"
    range_start = 0
    range_end = 6
    default = 0


# === Quality of Life ===

class OpenLakeFloriaGate(DefaultOnToggle):
    """
    If enabled, the gate to Lake Floria is open from the start.
    """
    display_name = "Open Lake Floria Gate"


class OpenThunderhead(DefaultOnToggle):
    """
    If enabled, the Thunderhead is open from the start.
    """
    display_name = "Open Thunderhead"


class OpenEarthTemple(Toggle):
    """
    If enabled, the Earth Temple is open from the start.
    """
    display_name = "Open Earth Temple"


class OpenLmf(Toggle):
    """
    If enabled, the Lanayru Mining Facility is open from the start.
    """
    display_name = "Open Lanayru Mining Facility"


class OpenBatraeuxShed(Toggle):
    """
    If enabled, Batreaux's Shed is open from the start.
    """
    display_name = "Open Batreaux Shed"


class SkipSkykeepDoorCutscene(DefaultOnToggle):
    """
    If enabled, skip the Sky Keep door opening cutscene.
    """
    display_name = "Skip Sky Keep Door Cutscene"


class SkipHarpPlaying(Toggle):
    """Skip harp playing mini-games."""
    display_name = "Skip Harp Playing"


class SkipMiscCutscenes(Toggle):
    """Skip miscellaneous small cutscenes."""
    display_name = "Skip Misc Cutscenes"


# === Difficulty Settings ===

class NoSpoilerLog(Toggle):
    """
    If enabled, no spoiler log will be generated.
    """
    display_name = "No Spoiler Log"


class EmptyUnreachableLocations(Toggle):
    """
    If enabled, locations that are unreachable will contain junk items.
    """
    display_name = "Empty Unreachable Locations"


class DamageMultiplier(Choice):
    """
    Multiplier for damage taken.
    """
    display_name = "Damage Multiplier"
    option_half = 0
    option_normal = 1
    option_double = 2
    option_quadruple = 3
    option_ohko = 4
    default = 1


# === Item Pool Settings ===

class AddJunkItems(Toggle):
    """
    If enabled, add extra junk items to the item pool (rupees, treasures, etc.).
    """
    display_name = "Add Junk Items"


class JunkItemRate(Range):
    """
    Percentage of junk items to add to the pool (if Add Junk Items is enabled).
    """
    display_name = "Junk Item Rate"
    range_start = 0
    range_end = 100
    default = 50


class ProgressiveItems(DefaultOnToggle):
    """
    If enabled, items with multiple tiers (Sword, Beetle, Bow, etc.) will be progressive.
    """
    display_name = "Progressive Items"


class MusicRandomization(Choice):
    """
    Randomize background music throughout the game.
    
    - Vanilla: No music shuffling
    - Shuffled: Background music randomly shuffled
    - Shuffled (Limit Vanilla): Minimize unchanged tracks
    """
    display_name = "Music Randomization"
    option_vanilla = 0
    option_shuffled = 1
    option_shuffled_limit_vanilla = 2
    default = 0


class CutoffGameOverMusic(Toggle):
    """
    If music randomization places a very long song as the game over music,
    this will cut it off after a reasonable duration instead of playing the entire song.
    """
    display_name = "Cutoff Game Over Music"


# === Advanced Randomization ===

class EnableBackInTime(Toggle):
    """
    If enabled, the Back in Time (BiT) glitch can be performed from the Wii version.
    """
    display_name = "Enable Back in Time (BiT)"


class UndergroundRupeeShufle(Toggle):
    """
    If enabled, rupees found in the underground will be shuffled.
    """
    display_name = "Underground Rupee Shuffle"


class BeedleShopShuffle(Toggle):
    """
    If enabled, Beedle's shop will be randomized.
    """
    display_name = "Beedle Shop Shuffle"


class RandomBottleContents(Toggle):
    """
    If enabled, bottle contents will be randomized instead of following the vanilla layout.
    """
    display_name = "Random Bottle Contents"


class RandomizeShopPrices(Toggle):
    """
    If enabled, all shop prices will be randomized.
    """
    display_name = "Randomize Shop Prices"


class AmmoAvailability(Choice):
    """
    Determines how ammo is distributed in the game.
    """
    display_name = "Ammo Availability"
    option_scarce = 0
    option_vanilla = 1
    option_useful = 2
    option_plentiful = 3
    default = 3


class BossKeyPuzzles(Choice):
    """
    Determines boss key puzzle orientation when attempting to open boss doors.
    """
    display_name = "Boss Key Puzzles"
    option_correct_orientation = 0
    option_vanilla_orientation = 1
    option_random_orientation = 2
    default = 1


class MinigameDifficulty(Choice):
    """
    Determines the difficulty of minigames.
    """
    display_name = "Minigame Difficulty"
    option_easy = 0
    option_medium = 1
    option_hard = 2
    default = 0


class TrapMode(Choice):
    """
    Determines how many items are replaced with traps.
    """
    display_name = "Trap Mode"
    option_no_traps = 0
    option_trapish = 1
    option_trapsome = 2
    option_traps_o_plenty = 3
    option_traptacular = 4
    default = 0


class TrappableItems(Choice):
    """
    Determines which items can be trapped.
    """
    display_name = "Trappable Items"
    option_major_items = 0
    option_non_major_items = 1
    option_any_items = 2
    default = 0


# === Trap Types ===

class BurnTraps(DefaultOnToggle):
    """
    If enabled, traps that set you on fire can appear.
    """
    display_name = "Burn Traps"


class CurseTraps(DefaultOnToggle):
    """
    If enabled, traps that curse you (prevent item usage) can appear.
    """
    display_name = "Curse Traps"


class NoiseTraps(DefaultOnToggle):
    """
    If enabled, traps that create excessive noise can appear.
    """
    display_name = "Noise Traps"


class GrooseTraps(Toggle):
    """
    If enabled, traps that spawn Groose can appear (not in Silent Realms).
    """
    display_name = "Groose Traps"


class HealthTraps(Toggle):
    """
    If enabled, traps that reduce health to 1 can appear.
    """
    display_name = "Health Traps"


# === Advanced Options ===

class FullWalletUpgrades(Toggle):
    """
    If enabled, all wallet upgrades are available for purchase.
    """
    display_name = "Full Wallet Upgrades"


class ChestTypeMatchesContents(Choice):
    """
    Determines whether chest appearance matches their contents.
    """
    display_name = "Chest Type Matches Contents"
    option_off = 0
    option_only_dungeon_items = 1
    option_all_contents = 2
    default = 2


class RandomTrialObjectPositions(Toggle):
    """
    If enabled, object positions in Silent Realm trials will be randomized.
    """
    display_name = "Random Trial Object Positions"


class UpgradedSkywardStrike(DefaultOnToggle):
    """
    If enabled, Skyward Strike will have upgrades available.
    """
    display_name = "Upgraded Skyward Strike"


class FasterAirMeterDepletion(Toggle):
    """
    If enabled, the air meter depletes faster when sky diving.
    """
    display_name = "Faster Air Meter Depletion"


class UnlockAllGroosenatorDestinations(Toggle):
    """
    If enabled, all Groosenator destinations are unlocked from the start.
    """
    display_name = "Unlock All Groosenator Destinations"


class SmallKeysInFancyChests(Toggle):
    """
    If enabled with Chest Type Matches Contents, small keys will appear in fancy chests instead of blue chests.
    """
    display_name = "Small Keys in Fancy Chests"


class AllowFlyingAtNight(Toggle):
    """
    If enabled, you can call your Loftwing and fly in The Sky at night.
    """
    display_name = "Allow Flying at Night"


class NaturalNightConnections(DefaultOnToggle):
    """
    If enabled, nighttime-only checks are only accessible via natural night connections in the overworld.
    """
    display_name = "Require Natural Night Connections"


class DungeonsIncludeSkyKeep(Toggle):
    """
    If enabled, Sky Keep can be selected as a required dungeon.
    """
    display_name = "Include Sky Keep as a Dungeon"


class EmptyUnrequiredDungeons(DefaultOnToggle):
    """
    If enabled, unrequired dungeons will be barren (empty of progression items).
    """
    display_name = "Barren Unrequired Dungeons"


class LanaryuCavesKeys(Choice):
    """
    Separate control for small keys in the Lanayru Caves.
    """
    display_name = "Lanayru Caves Small Keys"
    option_vanilla = 0
    option_removed = 1
    default = 1


class ExtractPath(FreeText):
    """
    Path to the extracted SSHD romfs folder.
    Defaults to:
    - Windows: C:\\ProgramData\\Archipelago\\sshd_extract
    - Linux: ~/.local/share/Archipelago/sshd_extract
    - macOS: ~/Library/Application Support/Archipelago/sshd_extract
    
    This folder must contain the extracted romfs files from your SSHD ROM.
    """
    display_name = "Extract Path"
    default = ""


class SshdrSeed(FreeText):
    """
    The seed to use for randomization. If not specified, a random seed will be generated.
    Use word-based seeds like 'AirStrongholdPlantSkipper' or leave blank for random.
    """
    display_name = "SSHD-Rando Seed"
    default = ""


class SettingString(FreeText):
    """
    The sshd-rando Setting String for this seed. This is an advanced option - leave blank to auto-generate.
    This string uniquely identifies all randomization settings and can be used to recreate an exact seed.
    """
    display_name = "Setting String"
    default = ""


# === Traps ===

# === Archipelago-specific ===

class SSHDDeathLink(DeathLink):
    """
    When you die, everyone dies. Of course the reverse is true too.
    """


@dataclass
class SSHDOptions(PerGameCommonOptions):
    """
    All options for Skyward Sword HD.
    """
    # Core Logic
    logic_rules: LogicRules
    item_pool: ItemPool
    
    # Completion
    required_dungeon_count: RequiredDungeonCount
    triforce_required: TriforceRequired
    triforce_shuffle: TriforceShuffle
    gate_of_time_sword_requirement: GateOfTimeSwordRequirement
    gate_of_time_dungeon_requirements: GateOfTimeDungeonRequirements
    imp2_skip: Imp2Skip
    skip_horde: SkipHorde
    skip_ghirahim3: SkipGhirahim3
    
    # Randomization
    gratitude_crystal_shuffle: GratitudeCrystalShuffle
    stamina_fruit_shuffle: StaminaFruitShuffle
    npc_closet_shuffle: NpcClosetShuffle
    hidden_item_shuffle: HiddenItemShuffle
    rupee_shuffle: RupeeShuffle
    goddess_chest_shuffle: GoddessChestShuffle
    trial_treasure_shuffle: TrialTreasureShuffle
    tadtone_shuffle: TadtoneShuffle
    gossip_stone_treasure_shuffle: GossipStoneTreasureShuffle
    small_key_shuffle: SmallKeyShuffle
    boss_key_shuffle: BossKeyShuffle
    map_shuffle: MapShuffle
    randomize_entrances: RandomizeEntrances
    randomize_dungeons: RandomizeDungeons
    randomize_trials: RandomizeTrials
    randomize_door_entrances: RandomizeDoorEntrances
    decouple_skykeep_layout: DecoupleSkykeepLayout
    randomize_interior_entrances: RandomizeInteriorEntrances
    randomize_overworld_entrances: RandomizeOverworldEntrances
    decouple_entrances: DecoupleEntrances
    decouple_double_doors: DecopleDoubleDoors
    music_randomization: MusicRandomization
    cutoff_game_over_music: CutoffGameOverMusic
    
    # Advanced Randomization
    enable_back_in_time: EnableBackInTime
    underground_rupee_shuffle: UndergroundRupeeShufle
    beedle_shop_shuffle: BeedleShopShuffle
    random_bottle_contents: RandomBottleContents
    randomize_shop_prices: RandomizeShopPrices
    ammo_availability: AmmoAvailability
    boss_key_puzzles: BossKeyPuzzles
    minigame_difficulty: MinigameDifficulty
    trap_mode: TrapMode
    trappable_items: TrappableItems
    
    # Trap Types
    burn_traps: BurnTraps
    curse_traps: CurseTraps
    noise_traps: NoiseTraps
    groose_traps: GrooseTraps
    health_traps: HealthTraps
    
    # Advanced Options
    full_wallet_upgrades: FullWalletUpgrades
    chest_type_matches_contents: ChestTypeMatchesContents
    small_keys_in_fancy_chests: SmallKeysInFancyChests
    random_trial_object_positions: RandomTrialObjectPositions
    upgraded_skyward_strike: UpgradedSkywardStrike
    faster_air_meter_depletion: FasterAirMeterDepletion
    unlock_all_groosenator_destinations: UnlockAllGroosenatorDestinations
    allow_flying_at_night: AllowFlyingAtNight
    natural_night_connections: NaturalNightConnections
    dungeons_include_sky_keep: DungeonsIncludeSkyKeep
    empty_unrequired_dungeons: EmptyUnrequiredDungeons
    lanayru_caves_keys: LanaryuCavesKeys
    
    # Starting Inventory
    starting_tablets: StartingTablets
    starting_sword: StartingSword
    random_starting_statues: RandomStartingStatues
    random_starting_spawn: RandomStartingSpawn
    limit_starting_spawn: LimitStartingSpawn
    random_starting_item_count: RandomStartingItemCount
    peatrice_conversations: PeatriceConversations
    custom_starting_items: CustomStartingItems
    
    # Quality of Life
    open_lake_floria_gate: OpenLakeFloriaGate
    open_thunderhead: OpenThunderhead
    open_earth_temple: OpenEarthTemple
    open_lmf: OpenLmf
    open_batreaux_shed: OpenBatraeuxShed
    skip_skykeep_door_cutscene: SkipSkykeepDoorCutscene
    skip_harp_playing: SkipHarpPlaying
    skip_misc_cutscenes: SkipMiscCutscenes
    
    # Difficulty
    no_spoiler_log: NoSpoilerLog
    empty_unreachable_locations: EmptyUnreachableLocations
    damage_multiplier: DamageMultiplier
    
    # Item Pool
    add_junk_items: AddJunkItems
    junk_item_rate: JunkItemRate
    progressive_items: ProgressiveItems
    
    # Configuration
    extract_path: ExtractPath
    sshdr_seed: SshdrSeed
    setting_string: SettingString
    
    # Archipelago
    death_link: SSHDDeathLink
