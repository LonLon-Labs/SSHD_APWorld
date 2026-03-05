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
    option_vanilla = 0
    option_own_dungeon = 1
    option_any_dungeon = 2
    option_own_region = 3
    option_overworld = 4
    option_anywhere = 5
    option_removed = 6
    alias_keysy = 6  # Backward compatibility
    default = 1

class BossKeyShuffle(Choice):
    """Where boss keys can appear."""
    display_name = "Boss Key Shuffle"
    option_vanilla = 0
    option_own_dungeon = 1
    option_any_dungeon = 2
    option_own_region = 3
    option_overworld = 4
    option_anywhere = 5
    option_removed = 6
    alias_keysy = 6  # Backward compatibility
    default = 1

class MapShuffle(Choice):
    """Where dungeon maps can appear."""
    display_name = "Map Shuffle"
    option_vanilla = 0
    option_own_dungeon_restricted = 1
    option_own_dungeon_unrestricted = 2
    option_any_dungeon = 3
    option_own_region = 4
    option_overworld = 5
    option_anywhere = 6
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


class BeedleShopShuffle(Choice):
    """
    Controls what items appear in Beedle's Airshop.
    """
    display_name = "Beedle's Airshop Shuffle"
    option_vanilla = 0
    option_junk_only = 1
    option_randomized = 2
    default = 2
    # Backward compatibility with old boolean format
    alias_false = 0  # false -> vanilla
    alias_true = 2   # true -> randomized


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
    If enabled, the air meter depletes faster when swimming.
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
    option_overworld = 1
    option_anywhere = 2
    option_removed = 3
    default = 3


# === Quality of Life Shortcuts ===

class ShortcutIosBridgeComplete(Toggle):
    """
    If enabled, the Isle of Songs bridge puzzle is solved from the start.
    """
    display_name = "Isle of Songs Bridge Complete"


class ShortcutSpiralLogToBtt(Toggle):
    """
    If enabled, the log between Sealed Grounds Spiral and Behind the Temple is pushed down.
    """
    display_name = "Sealed Spiral Log to Behind the Temple"


class ShortcutLogNearMachi(Toggle):
    """
    If enabled, logs near Faron Woods entry are pushed down.
    """
    display_name = "Faron Woods Logs near Entry"


class ShortcutFaronLogToFloria(Toggle):
    """
    If enabled, the log from Faron Woods to after Lake Floria is pushed down.
    """
    display_name = "Faron Woods Log to Lake Floria"


class ShortcutDeepWoodsLogBeforeTightrope(Toggle):
    """
    If enabled, the log before Deep Woods tightrope is pushed down.
    """
    display_name = "Deep Woods Log before Tightrope"


class ShortcutDeepWoodsLogBeforeTemple(Toggle):
    """
    If enabled, the log before Deep Woods temple is pushed down.
    """
    display_name = "Deep Woods Log before Temple"


class ShortcutEldinEntranceBoulder(Toggle):
    """
    If enabled, the boulder at Eldin Volcano entrance is blown up.
    """
    display_name = "Eldin Volcano Entrance Boulder"


class ShortcutEldinAscentBoulder(Toggle):
    """
    If enabled, the boulder near Volcano Ascent is blown up.
    """
    display_name = "Eldin Volcano Boulder near Ascent"


class ShortcutVsFlames(Toggle):
    """
    If enabled, flames in Volcano Summit are removed.
    """
    display_name = "Volcano Summit Flames"


class ShortcutLanayruBars(Toggle):
    """
    If enabled, bars separating Lanayru Desert from Stone Cache are raised.
    """
    display_name = "Lanayru Desert Bars near Stone Cache"


class ShortcutWestWallMinecart(Toggle):
    """
    If enabled, minecart on West Wall is pushed down.
    """
    display_name = "Lanayru Desert Minecart on West Wall"


class ShortcutSandOasisMinecart(Toggle):
    """
    If enabled, minecart in Sand Oasis is pushed down.
    """
    display_name = "Lanayru Desert Minecart in Sand Oasis"


class ShortcutMinecartBeforeCaves(Toggle):
    """
    If enabled, minecart before Lanayru Caves is pushed down.
    """
    display_name = "Lanayru Desert Minecart before Caves"


class ShortcutSkyviewBoards(Toggle):
    """
    If enabled, wooden boards in Skyview Temple are destroyed.
    """
    display_name = "Skyview Temple Boarded Shortcut"


class ShortcutSkyviewBars(Toggle):
    """
    If enabled, bars before Skyview Temple boss door are raised.
    """
    display_name = "Skyview Temple Bars before Boss Door"


class ShortcutEarthTempleBridge(Toggle):
    """
    If enabled, the bridge in Earth Temple main room is raised.
    """
    display_name = "Earth Temple Pegs Bridge"


class ShortcutLmfWindGates(Toggle):
    """
    If enabled, wind gates in Lanayru Mining Facility hub are raised.
    """
    display_name = "Lanayru Mining Facility Wind Gates"


class ShortcutLmfBoxes(Toggle):
    """
    If enabled, pushable boxes in Lanayru Mining Facility are pushed.
    """
    display_name = "Lanayru Mining Facility Pushable Boxes"


class ShortcutLmfBarsToWestSide(Toggle):
    """
    If enabled, bars to west side in Lanayru Mining Facility are raised.
    """
    display_name = "Lanayru Mining Facility Bars to West Side"


class ShortcutAcBridge(Toggle):
    """
    If enabled, the bridge to basement in Ancient Cistern is extended.
    """
    display_name = "Ancient Cistern Bridge to Basement"


class ShortcutAcWaterVents(Toggle):
    """
    If enabled, water vents in Ancient Cistern are opened.
    """
    display_name = "Ancient Cistern Water Vents"


class ShortcutSandshipWindows(Toggle):
    """
    If enabled, windows below life boat in Sandship are opened.
    """
    display_name = "Sandship Windows below Life Boat"


class ShortcutSandshipBrigBars(Toggle):
    """
    If enabled, bars before brig in Sandship are raised.
    """
    display_name = "Sandship Bars before Brig"


class ShortcutFsOutsideBars(Toggle):
    """
    If enabled, bars between outdoor bridges in Fire Sanctuary are raised.
    """
    display_name = "Fire Sanctuary Bars between Outdoor Bridges"


class ShortcutFsLavaFlow(Toggle):
    """
    If enabled, lava river at end of Fire Sanctuary is flowing.
    """
    display_name = "Fire Sanctuary Skip Lava Flow"


class ShortcutSkyKeepSvtRoomBars(Toggle):
    """
    If enabled, bars in Skyview Temple room in Sky Keep are raised.
    """
    display_name = "Sky Keep Bars in Skyview Temple Room"


class ShortcutSkyKeepFsRoomLowerBars(Toggle):
    """
    If enabled, lower bars in Fire Sanctuary room in Sky Keep are raised.
    """
    display_name = "Sky Keep Lower Bars in Fire Sanctuary Room"


class ShortcutSkyKeepFsRoomUpperBars(Toggle):
    """
    If enabled, upper bars in Fire Sanctuary room in Sky Keep are raised.
    """
    display_name = "Sky Keep Upper Bars in Fire Sanctuary Room"


# === Logic Tricks/Advanced Options ===

class LogicEarlyLakeFloria(Toggle):
    """
    If enabled, you may need to enter Lake Floria using jumpslash tricks.
    """
    display_name = "Early Lake Floria Jumpslash"


class LogicBeedlesIslandCageChestDive(Toggle):
    """
    If enabled, you may need to skydive into cage on Beedle's Island.
    """
    display_name = "Beedle's Island Cage Chest Dive"


class LogicVolcanicIslandDive(Toggle):
    """
    If enabled, you may need to skydive onto Volcanic Island.
    """
    display_name = "Volcanic Island Dive"


class LogicEastIslandDive(Toggle):
    """
    If enabled, you may need to skydive onto archway inside Thunderhead.
    """
    display_name = "Inside the Thunderhead East Island Dive"


class LogicAdvancedLizalfosCombat(Toggle):
    """
    If enabled, you may need to defeat Lizalfos with bombs or bow only.
    """
    display_name = "Advanced Lizalfos Combat"


class LogicLongRangedSkywardStrikes(Toggle):
    """
    If enabled, you may need to perform long-ranged Skyward Strikes.
    """
    display_name = "Long Ranged Skyward Strikes"


class LogicGravestoneJump(Toggle):
    """
    If enabled, you may need to jump on gravestones to reach Batreaux's door.
    """
    display_name = "Gravestone Jump"


class LogicWaterfallCaveJump(Toggle):
    """
    If enabled, you may need to dive and skydive to enter Waterfall Cave.
    """
    display_name = "Waterfall Cave Jump"


class LogicBirdNestItemFromBeedlesShop(Toggle):
    """
    If enabled, you may need to access Bird's Nest using Beedle's Airshop.
    """
    display_name = "Bird's Nest from Beedle's Airshop"


class LogicBeedlesShopWithBombs(Toggle):
    """
    If enabled, you may need to use bomb explosions to hit Beedle's shop bell.
    """
    display_name = "Beedle's Airshop with Bombs"


class LogicStutterSprint(Toggle):
    """
    If enabled, you may need to use stuttersprint to cross quicksand or slopes.
    """
    display_name = "Stutter Sprinting"


class LogicPreciseBeetle(Toggle):
    """
    If enabled, you may need to precisely control Beetle for distant checks.
    """
    display_name = "Precise Beetle Flying"


class LogicPreciseBombThrows(Toggle):
    """
    If enabled, you may need to time bomb throws for switches or targets.
    """
    display_name = "Precise Bomb Throws"


class LogicFaronWoodsWithGroosenator(Toggle):
    """
    If enabled, you may need to use Groosenator to unlock Flooded Faron Woods statues.
    """
    display_name = "Faron Woods with Groosenator"


class LogicItemlessFirstTimeshift(Toggle):
    """
    If enabled, you may need to activate first Lanayru Mine timeshift stone without items.
    """
    display_name = "Itemless First Timeshift Stone"


class LogicStaminaPotionThroughSinkSand(Toggle):
    """
    If enabled, you may need to use stamina potion to traverse sink sand.
    """
    display_name = "Stamina Potion through Sink Sand"


class LogicBrakeslide(Toggle):
    """
    If enabled, you may need to use brakeslide glitch.
    """
    display_name = "Brakesliding"


class LogicLanayruMineQuickBomb(Toggle):
    """
    If enabled, you may need to use Bomb Bag in Lanayru Mine.
    """
    display_name = "Lanayru Mine Quick Bomb"


class LogicTotSkipBrakeslide(Toggle):
    """
    If enabled, you may need to brakeslide to reach east Lanayru Desert from Temple of Time.
    """
    display_name = "Temple of Time Skip Brakeslide"


class LogicTotSlingshot(Toggle):
    """
    If enabled, you may need to use Slingshot to activate Temple of Time timeshift stone.
    """
    display_name = "Temple of Time Precise Slingshot"


class LogicFireNodeWithoutHookBeetle(Toggle):
    """
    If enabled, you may need to activate Fire Node without Hook Beetle.
    """
    display_name = "Activate Fire Node without Hook Beetle"


class LogicCactusBombWhip(Toggle):
    """
    If enabled, you may need to use Whip to pick bombs from cacti.
    """
    display_name = "Whip Bomb Flowers off Cacti"


class LogicSkippersRetreatFastClawshots(Toggle):
    """
    If enabled, you may need to use Clawshots to stun Deku Baba in Skipper's Retreat.
    """
    display_name = "Skipper's Retreat Fast Clawshots"


class LogicSkyviewSpiderRoll(Toggle):
    """
    If enabled, you may need to roll next to Skultullas in Skyview Temple.
    """
    display_name = "Skyview Temple Spider Roll"


class LogicSkyviewCoiledRupeeJump(Toggle):
    """
    If enabled, you may need to jump-slash for Coiled Branch rupee in Skyview Temple.
    """
    display_name = "Skyview Coiled Rupee Jump"


class LogicSkyviewPreciseSlingshot(Toggle):
    """
    If enabled, you may need to use Slingshot to hit crystal in Skyview Temple.
    """
    display_name = "Skyview Temple Precise Slingshot"


class LogicEarthTempleKeeseSkywardStrike(Toggle):
    """
    If enabled, you may need to use long-range Skyward Strike on Keese in Earth Temple.
    """
    display_name = "Earth Temple Keese Skyward Strike"


class LogicEarthTempleSlopeStuttersprint(Toggle):
    """
    If enabled, you may need to use stuttersprint on Earth Temple slope.
    """
    display_name = "Earth Temple Slope Stuttersprint"


class LogicEarthTempleBomblessScaldera(Toggle):
    """
    If enabled, you may need to defeat Scaldera without Bomb Bag.
    """
    display_name = "Earth Temple Bomb Flower Scaldera"


class LogicLmfWhipSwitch(Toggle):
    """
    If enabled, you may need to use Whip to flip lever in Lanayru Mining Facility.
    """
    display_name = "Lanayru Mining Facility Whip Switch"


class LogicLmfCeilingPreciseSlingshot(Toggle):
    """
    If enabled, you may need to use Slingshot to hit timeshift stone in Lanayru Mining Facility.
    """
    display_name = "Lanayru Mining Facility Precise Slingshot"


class LogicLmfWhipTimeshiftStone(Toggle):
    """
    If enabled, you may need to use Whip to hit timeshift stone in Lanayru Mining Facility.
    """
    display_name = "Lanayru Mining Facility Whip Timeshift Stone"


class LogicLmfMinecartJump(Toggle):
    """
    If enabled, you may need to jump onto minecart in Lanayru Mining Facility.
    """
    display_name = "Lanayru Mining Facility Ride on Minecart"


class LogicLmfBellowslessMoldarach(Toggle):
    """
    If enabled, you may need to defeat Moldarach without Gust Bellows.
    """
    display_name = "Lanayru Mining Facility Moldarach without Gust Bellows"


class LogicAcLeverJumpTrick(Toggle):
    """
    If enabled, you may need to jump down to flip waterfall lever in Ancient Cistern.
    """
    display_name = "Ancient Cistern Lever Jump"


class LogicAcChestAfterWhipHooksJump(Toggle):
    """
    If enabled, you may need to jump for chest in Ancient Cistern.
    """
    display_name = "Ancient Cistern Chest after Whip Hooks Jump"


class LogicSandshipJumpToStern(Toggle):
    """
    If enabled, you may need to sidehop to Sandship stern.
    """
    display_name = "Sandship Jump to Stern"


class LogicSandshipItemlessSpume(Toggle):
    """
    If enabled, you may need to get past Spume in Sandship without items.
    """
    display_name = "Sandship Itemless Spume"


class LogicSandshipNoCombinationHint(Toggle):
    """
    If enabled, you may need to open Sandship combination lock without hint.
    """
    display_name = "Sandship No Combination Hint"


class LogicFsPillarJump(Toggle):
    """
    If enabled, you may need to jump around pillars on broken bridge in Fire Sanctuary.
    """
    display_name = "Fire Sanctuary Pillar Jump"


class LogicFsPracticeSwordGhirahim2(Toggle):
    """
    If enabled, you may need to defeat Ghirahim 2 with Practice Sword.
    """
    display_name = "Fire Sanctuary Ghirahim 2 with Practice Sword"


class LogicPresentBowSwitches(Toggle):
    """
    If enabled, you may need to hit Bow switches in present with barbed wire.
    """
    display_name = "Present Bow Switch Shots"


class LogicSkyKeepVineClip(Toggle):
    """
    If enabled, you may need to clip through vines in Sky Keep.
    """
    display_name = "Sky Keep Vine Clip"


# === Cosmetic Options ===

class TunicSwap(Toggle):
    """
    If enabled, Link wears his Skyloft outfit instead of green knight uniform.
    """
    display_name = "Tunic Swap"


class LightnningSkywardStrike(Toggle):
    """
    If enabled, Skyward strikes have lightning effects at all times.
    """
    display_name = "Lightning Skyward Strike"


class StarrySky(Toggle):
    """
    If enabled, stars appear in the sky during day and night.
    """
    display_name = "Starry Skies"


class RemoveEnemyMusic(Toggle):
    """
    If enabled, enemy drums won't interrupt background music.
    """
    display_name = "Remove Enemy Music"


class UseAlternativeLogo(Toggle):
    """
    If enabled, the alternative Archipelago logo is used on the title screen
    and credits instead of the default Archipelago logo.
    """
    display_name = "Use Alternative Logo"


# === Extra Starting Inventory ===

class StartingHearts(Range):
    """
    Number of hearts to start with.
    """
    display_name = "Starting Hearts"
    range_start = 6
    range_end = 18
    default = 6


class StartWithAllBugs(Toggle):
    """
    If enabled, start with 99 of each bug.
    """
    display_name = "Start with All Bugs"


class StartWithAllTreasures(Toggle):
    """
    If enabled, start with 99 of each treasure.
    """
    display_name = "Start with All Treasures"


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


class ConfigYamlPath(FreeText):
    """
    Path to the config.yaml file generated by the randomizer.
    If specified, the randomizer will load settings from this file instead of using the options below.
    Leave blank to use Archipelago options.
    Example: C:\\ProgramData\\Archipelago\\config.yaml
    """
    display_name = "Config YAML Path"
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

# === Cheats ===

class CheatInfiniteHealth(Toggle):
    """
    When enabled, the damage multiplier is forced to 0 so Link takes no damage.
    Your health will never decrease from enemy attacks or hazards.
    """
    display_name = "Infinite Health"


class CheatInfiniteStamina(Toggle):
    """
    When enabled, the stamina gauge is kept full at all times via memory writes.
    You will never run out of stamina while sprinting, climbing, or spin-attacking.
    """
    display_name = "Infinite Stamina"


class CheatInfiniteAmmo(Toggle):
    """
    When enabled, Arrow, Bomb, and Deku Seed counters are kept at their maximums.
    You will never run out of ammunition.
    """
    display_name = "Infinite Arrows/Bombs/Seeds"


class CheatInfiniteBugs(Toggle):
    """
    When enabled, the 'Start with All Bugs' setting is forced on,
    giving you 99 of every bug from the start of the game.
    The client also keeps your bug-ownership flags set each tick.
    """
    display_name = "Infinite Bugs"


class CheatInfiniteMaterials(Toggle):
    """
    When enabled, the 'Start with All Treasures' setting is forced on,
    giving you 99 of every treasure/material from the start of the game.
    The client also keeps your treasure-ownership flags set each tick.
    """
    display_name = "Infinite Materials"


class CheatInfiniteShield(Toggle):
    """
    When enabled, shield durability is kept at its maximum value.
    Your equipped shield will never break.
    """
    display_name = "Infinite Shield Durability"


class CheatInfiniteSkywardStrike(Toggle):
    """
    When enabled, the Skyward Strike active timer is kept charged.
    Once charged, your sword stays charged indefinitely.
    """
    display_name = "Infinite Skyward Strike Time"


class CheatInfiniteRupees(Toggle):
    """
    When enabled, the rupee counter is kept at the maximum value for your wallet.
    You will always have enough rupees for any purchase.
    """
    display_name = "Infinite Rupees"


class CheatMoonJump(Toggle):
    """
    When enabled, pressing Y gives Link a large upward velocity boost.
    Hold Y to fly upward freely.
    """
    display_name = "Moon Jump"


class CheatInfiniteBeetle(Toggle):
    """
    When enabled, the Beetle's flight timer is set to a very large value
    via an ARM64 code patch. The Beetle will fly indefinitely without
    returning automatically.
    NOTE: This patches game code; may require a game restart to take effect.
    """
    display_name = "Infinite Beetle Flying Time"


class CheatInfiniteLoftwing(Toggle):
    """
    When enabled, the Loftwing's spiral charge counter is kept at the
    maximum (3 charges) at all times.
    """
    display_name = "Infinite Loftwing Charges"


class CheatSpeedMultiplier(Range):
    """
    Multiplies Link's forward movement speed.
    10 = normal (1.0x), 20 = double (2.0x), etc.
    Values above 30 (3.0x) may cause collision issues.
    """
    display_name = "Speed Multiplier (x10)"
    range_start = 10
    range_end = 50
    default = 10


# === Archipelago-specific ===

class SSHDDeathLink(DeathLink):
    """
    When you die, everyone dies. Of course the reverse is true too.
    """


class SSHDBreathLink(Toggle):
    """
    When your stamina runs out, everyone's stamina runs out (and vice versa).
    Think Death Link, but for stamina exhaustion instead of dying.
    """
    display_name = "Breath Link"


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
    
    # Quality of Life Shortcuts
    shortcut_ios_bridge_complete: ShortcutIosBridgeComplete
    shortcut_spiral_log_to_btt: ShortcutSpiralLogToBtt
    shortcut_logs_near_machi: ShortcutLogNearMachi
    shortcut_faron_log_to_floria: ShortcutFaronLogToFloria
    shortcut_deep_woods_log_before_tightrope: ShortcutDeepWoodsLogBeforeTightrope
    shortcut_deep_woods_log_before_temple: ShortcutDeepWoodsLogBeforeTemple
    shortcut_eldin_entrance_boulder: ShortcutEldinEntranceBoulder
    shortcut_eldin_ascent_boulder: ShortcutEldinAscentBoulder
    shortcut_vs_flames: ShortcutVsFlames
    shortcut_lanayru_bars: ShortcutLanayruBars
    shortcut_west_wall_minecart: ShortcutWestWallMinecart
    shortcut_sand_oasis_minecart: ShortcutSandOasisMinecart
    shortcut_minecart_before_caves: ShortcutMinecartBeforeCaves
    shortcut_skyview_boards: ShortcutSkyviewBoards
    shortcut_skyview_bars: ShortcutSkyviewBars
    shortcut_earth_temple_bridge: ShortcutEarthTempleBridge
    shortcut_lmf_wind_gates: ShortcutLmfWindGates
    shortcut_lmf_boxes: ShortcutLmfBoxes
    shortcut_lmf_bars_to_west_side: ShortcutLmfBarsToWestSide
    shortcut_ac_bridge: ShortcutAcBridge
    shortcut_ac_water_vents: ShortcutAcWaterVents
    shortcut_sandship_windows: ShortcutSandshipWindows
    shortcut_sandship_brig_bars: ShortcutSandshipBrigBars
    shortcut_fs_outside_bars: ShortcutFsOutsideBars
    shortcut_fs_lava_flow: ShortcutFsLavaFlow
    shortcut_sky_keep_svt_room_bars: ShortcutSkyKeepSvtRoomBars
    shortcut_sky_keep_fs_room_lower_bars: ShortcutSkyKeepFsRoomLowerBars
    shortcut_sky_keep_fs_room_upper_bars: ShortcutSkyKeepFsRoomUpperBars
    
    # Quality of Life - Open Locations
    open_lake_floria: OpenLakeFloriaGate
    open_thunderhead: OpenThunderhead
    open_earth_temple: OpenEarthTemple
    open_lmf: OpenLmf
    open_batreaux_shed: OpenBatraeuxShed
    skip_skykeep_door_cutscene: SkipSkykeepDoorCutscene
    skip_harp_playing: SkipHarpPlaying
    skip_misc_cutscenes: SkipMiscCutscenes
    
    # Logic Tricks
    logic_early_lake_floria: LogicEarlyLakeFloria
    logic_beedles_island_cage_chest_dive: LogicBeedlesIslandCageChestDive
    logic_volcanic_island_dive: LogicVolcanicIslandDive
    logic_east_island_dive: LogicEastIslandDive
    logic_advanced_lizalfos_combat: LogicAdvancedLizalfosCombat
    logic_long_ranged_skyward_strikes: LogicLongRangedSkywardStrikes
    logic_gravestone_jump: LogicGravestoneJump
    logic_waterfall_cave_jump: LogicWaterfallCaveJump
    logic_bird_nest_item_from_beedles_shop: LogicBirdNestItemFromBeedlesShop
    logic_beedles_shop_with_bombs: LogicBeedlesShopWithBombs
    logic_stuttersprint: LogicStutterSprint
    logic_precise_beetle: LogicPreciseBeetle
    logic_bomb_throws: LogicPreciseBombThrows
    logic_faron_woods_with_groosenator: LogicFaronWoodsWithGroosenator
    logic_itemless_first_timeshift_stone: LogicItemlessFirstTimeshift
    logic_stamina_potion_through_sink_sand: LogicStaminaPotionThroughSinkSand
    logic_brakeslide: LogicBrakeslide
    logic_lanayru_mine_quick_bomb: LogicLanayruMineQuickBomb
    logic_tot_skip_brakeslide: LogicTotSkipBrakeslide
    logic_tot_slingshot: LogicTotSlingshot
    logic_fire_node_without_hook_beetle: LogicFireNodeWithoutHookBeetle
    logic_cactus_bomb_whip: LogicCactusBombWhip
    logic_skippers_fast_clawshots: LogicSkippersRetreatFastClawshots
    logic_skyview_spider_roll: LogicSkyviewSpiderRoll
    logic_skyview_coiled_rupee_jump: LogicSkyviewCoiledRupeeJump
    logic_skyview_precise_slingshot: LogicSkyviewPreciseSlingshot
    logic_et_keese_skyward_strike: LogicEarthTempleKeeseSkywardStrike
    logic_et_slope_stuttersprint: LogicEarthTempleSlopeStuttersprint
    logic_et_bombless_scaldera: LogicEarthTempleBomblessScaldera
    logic_lmf_whip_switch: LogicLmfWhipSwitch
    logic_lmf_ceiling_precise_slingshot: LogicLmfCeilingPreciseSlingshot
    logic_lmf_whip_armos_room_timeshift_stone: LogicLmfWhipTimeshiftStone
    logic_lmf_minecart_jump: LogicLmfMinecartJump
    logic_lmf_bellowsless_moldarach: LogicLmfBellowslessMoldarach
    logic_ac_lever_jump_trick: LogicAcLeverJumpTrick
    logic_ac_chest_after_whip_hooks_jump: LogicAcChestAfterWhipHooksJump
    logic_sandship_jump_to_stern: LogicSandshipJumpToStern
    logic_sandship_itemless_spume: LogicSandshipItemlessSpume
    logic_sandship_no_combination_hint: LogicSandshipNoCombinationHint
    logic_fs_pillar_jump: LogicFsPillarJump
    logic_fs_practice_sword_ghirahim_2: LogicFsPracticeSwordGhirahim2
    logic_present_bow_switches: LogicPresentBowSwitches
    logic_skykeep_vineclip: LogicSkyKeepVineClip
    
    # Cosmetics
    tunic_swap: TunicSwap
    lightning_skyward_strike: LightnningSkywardStrike
    starry_skies: StarrySky
    remove_enemy_music: RemoveEnemyMusic
    use_alternative_logo: UseAlternativeLogo
    
    # Extra Starting Inventory
    starting_hearts: StartingHearts
    start_with_all_bugs: StartWithAllBugs
    start_with_all_treasures: StartWithAllTreasures
    
    # Original Starting Inventory
    starting_tablets: StartingTablets
    starting_sword: StartingSword
    random_starting_statues: RandomStartingStatues
    random_starting_spawn: RandomStartingSpawn
    limit_starting_spawn: LimitStartingSpawn
    random_starting_item_count: RandomStartingItemCount
    peatrice_conversations: PeatriceConversations
    custom_starting_items: CustomStartingItems
    
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
    config_yaml_path: ConfigYamlPath
    sshdr_seed: SshdrSeed
    setting_string: SettingString
    
    # Cheats
    cheat_infinite_health: CheatInfiniteHealth
    cheat_infinite_stamina: CheatInfiniteStamina
    cheat_infinite_ammo: CheatInfiniteAmmo
    cheat_infinite_bugs: CheatInfiniteBugs
    cheat_infinite_materials: CheatInfiniteMaterials
    cheat_infinite_shield: CheatInfiniteShield
    cheat_infinite_skyward_strike: CheatInfiniteSkywardStrike
    cheat_infinite_rupees: CheatInfiniteRupees
    cheat_moon_jump: CheatMoonJump
    cheat_infinite_beetle: CheatInfiniteBeetle
    cheat_infinite_loftwing: CheatInfiniteLoftwing
    cheat_speed_multiplier: CheatSpeedMultiplier
    
    # Archipelago
    death_link: SSHDDeathLink
    breath_link: SSHDBreathLink
