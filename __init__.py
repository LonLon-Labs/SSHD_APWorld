"""
Skyward Sword HD (SSHD) Archipelago World

This is an Archipelago integration for The Legend of Zelda: Skyward Sword HD
running on the Ryujinx emulator.

Based on the original Skyward Sword (Wii/Dolphin) integration.
"""

import os
import sys
import zipfile
import json
import tempfile
import shutil
import atexit
import threading
from base64 import b64encode
from copy import deepcopy
from dataclasses import fields
from pathlib import Path
from typing import Any, ClassVar, Tuple

# Add current directory to path for bundled modules
_current_dir = os.path.dirname(os.path.abspath(__file__))
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)

from BaseClasses import Region, Location, Item, Tutorial, ItemClassification as IC, LocationProgressType
from worlds.AutoWorld import WebWorld, World
from worlds.Files import APPlayerContainer
from worlds.LauncherComponents import (
    Component,
    SuffixIdentifier,
    Type,
    components,
    launch_subprocess,
    icon_paths,
)

from .Items import ITEM_TABLE
from .Locations import LOCATION_TABLE
from .SSHD_Options import SSHDOptions
from .Rules import set_rules, set_completion_condition
from .rando.ArcPatcher import patch_archipelago_logo
from .SSHDRWrapper import generate_sshd_rando_mod, extract_location_item_mapping, extract_custom_flag_mapping

try:
    from platform_utils import get_default_sshd_extract_path, get_os_name
except ImportError:
    def get_os_name():
        import sys
        if sys.platform == "win32":
            return "windows"
        elif sys.platform == "linux":
            return "linux"
        else:
            return sys.platform
    def get_default_sshd_extract_path():
        from pathlib import Path
        return Path.home() / ".local" / "share" / "Archipelago" / "sshd_extract"

# Mock args to enable nogui mode before any sshd-rando imports
class NoGuiArgs:
    nogui = True
    debug = False

# Create mock module for util.arguments with get_program_args function
import types
util_arguments_mock = types.ModuleType('util.arguments')
util_arguments_mock.args = NoGuiArgs()
util_arguments_mock.get_program_args = lambda: NoGuiArgs()
sys.modules['util.arguments'] = util_arguments_mock

# Add sshd-rando-backend to path for patch generation
SSHD_RANDO_PATH = Path(__file__).parent / "sshd-rando-backend"
SSHD_RANDO_TEMP_DIR = None  # Will hold temp directory if extracted from zip

# Check if we're running from a zip file (.apworld)
if hasattr(sys.modules[__name__], '__loader__') and hasattr(sys.modules[__name__].__loader__, 'archive'):
    # Running from .apworld zip - need to extract to temp directory
    # because sshd-rando-backend uses file I/O operations that don't work on zip contents
    # and C-extension packages (.pyd/.so) cannot be imported from inside a zip.
    apworld_path = Path(sys.modules[__name__].__loader__.archive)
    
    # Create temp directory for extraction
    SSHD_RANDO_TEMP_DIR = tempfile.mkdtemp(prefix="sshd_rando_")
    temp_backend_path = Path(SSHD_RANDO_TEMP_DIR) / "sshd-rando-backend"
    temp_deps_path = Path(SSHD_RANDO_TEMP_DIR) / "_bundled_deps"
    
    # Extract sshd-rando-backend AND _bundled_deps from the zip
    _EXTRACT_PREFIXES = ('sshd/sshd-rando-backend/', 'sshd/_bundled_deps/')
    with zipfile.ZipFile(apworld_path, 'r') as zip_file:
        for file_info in zip_file.filelist:
            if not any(file_info.filename.startswith(p) for p in _EXTRACT_PREFIXES):
                continue
            # Remove 'sshd/' prefix to get relative path
            relative_path = file_info.filename[5:]  # Remove 'sshd/'
            # Skip bare directory entries
            if relative_path.rstrip('/') in ('sshd-rando-backend', '_bundled_deps'):
                continue
            
            target_path = Path(SSHD_RANDO_TEMP_DIR) / relative_path
            
            # Create parent directories
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Extract the file
            if not file_info.is_dir():
                with zip_file.open(file_info.filename) as source:
                    with open(target_path, 'wb') as target:
                        target.write(source.read())
    
    # Add sshd-rando-backend at highest priority.
    sys.path.insert(0, str(temp_backend_path))

    # Add bundled deps right after the backend.  The _bundled_deps directory
    # contains .pyd files for multiple Python versions (cp311, cp312, cp313)
    # so the correct one is picked by importlib regardless of host version.
    if temp_deps_path.exists():
        sys.path.insert(1, str(temp_deps_path))
        # On Windows 3.8+, explicitly register the DLL search directory so
        # that any native extension (.pyd) and its transitive DLL deps can
        # be loaded from the temp extraction path.
        if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(str(temp_deps_path))
            except OSError:
                pass

    # Flush Python's import-finder caches so the freshly extracted
    # directories are recognised immediately.
    import importlib
    importlib.invalidate_caches()

    SSHD_RANDO_AVAILABLE = True
    
    # Register cleanup function to delete temp directory on exit
    def cleanup_temp_dir():
        if SSHD_RANDO_TEMP_DIR and Path(SSHD_RANDO_TEMP_DIR).exists():
            shutil.rmtree(SSHD_RANDO_TEMP_DIR, ignore_errors=True)
    atexit.register(cleanup_temp_dir)
    
elif SSHD_RANDO_PATH.exists():
    # Running from filesystem
    sys.path.insert(0, str(SSHD_RANDO_PATH))
    SSHD_RANDO_AVAILABLE = True
else:
    SSHD_RANDO_AVAILABLE = False

# Version information
AP_VERSION = [0, 6, 5]
WORLD_VERSION = [0, 7, 0]  # Starting at [BETA] 0.7.0 for SSHD
RANDO_VERSION = [0, 1, 0]


def run_client(*args: str) -> None:
    """
    Handle .apsshd patch files or show client launch instructions.
    When a patch file is provided, only installs the patch (romfs/exefs)
    without launching the full client GUI.
    """
    import sys
    from pathlib import Path
    
    print(f"Running SSHD Client with args: {args}")
    
    # If launched WITHOUT a patch file (from launcher menu), show instructions
    if not args or not any(arg.endswith('.apsshd') for arg in args):
        print("\n" + "=" * 70)
        print("SSHD Client Launch Instructions")
        print("=" * 70)
        print("\nTo launch the SSHD Client GUI, run this command in a terminal:")
        
        os_name = get_os_name()
        if os_name == "windows":
            print("    C:\\ProgramData\\Archipelago\\launch_sshd.bat")
            print("Or double-click: C:\\ProgramData\\Archipelago\\launch_sshd.bat")
        elif os_name == "linux":
            print("    ~/.local/share/Archipelago/launch_sshd.py")
            print("Or: python launch_sshd.py")
        elif os_name == "darwin":
            print("    ~/Library/Application\\ Support/Archipelago/launch_sshd.py")
            print("Or: python launch_sshd.py")
        
        print("\nThe client will open in a new window with full GUI support.")
        print("=" * 70 + "\n")
        input("Press Enter to close this window...")
        return
    
    # If launched WITH a patch file, only install the patch without opening the client
    from .SSHDClient import install_patch
    
    patch_file = next((arg for arg in args if arg.endswith('.apsshd')), None)
    if patch_file:
        print(f"\nInstalling patch: {patch_file}")
        success, _ = install_patch(patch_file)
        if success:
            print("\n" + "=" * 60)
            print("Patch installed successfully!")
            print("=" * 60)
        else:
            print("\nERROR: Failed to install patch")
        input("\nPress Enter to close this window...")


# Register the client launcher
components.append(
    Component(
        "Skyward Sword HD Client",
        func=run_client,
        component_type=Type.CLIENT,
        file_identifier=SuffixIdentifier(".apsshd"),
        icon="Skyward Sword HD"
    )
)
icon_paths["Skyward Sword HD"] = "ap:worlds.sshd/assets/icon.png"


class SSHDWeb(WebWorld):
    """
    Web interface for SSHD Archipelago.
    """
    tutorials = [Tutorial(
        "Skyward Sword HD Setup Guide",
        "A guide to setting up SSHD for Archipelago with Ryujinx.",
        "English",
        "setup_en.md",
        "setup/en",
        ["Wesley-Playz"]
    )]
    theme = "ice"
    rich_text_options_doc = True


class SSHDContainer(APPlayerContainer):
    """
    Container file for SSHD patches (.apsshd files).
    """
    game: str = "Skyward Sword HD"
    patch_file_ending: str = ".apsshd"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if "data" in kwargs:
            self.data = kwargs["data"]
            del kwargs["data"]
        super().__init__(*args, **kwargs)

    def write_contents(self, opened_zipfile: zipfile.ZipFile) -> None:
        """Write patch data to the container file."""
        super().write_contents(opened_zipfile)
        # Store randomization data
        opened_zipfile.writestr("data", b64encode(bytes(json.dumps(self.data), "utf-8")))


class SSHDWorld(World):
    """
    The Legend of Zelda: Skyward Sword HD for Ryujinx
    
    An epic adventure where Link must rescue Zelda and stop the Demon King Ghirahim.
    Travel between the Surface and Sky, explore dungeons, and collect items across
    a vast interconnected world.
    """

    # Lock to serialize sshd-rando patch generation across players.
    # generate_output runs in parallel threads, but sshd-rando uses module-level
    # global state (text_table, etc.) that is not thread-safe.
    _sshd_patch_lock: ClassVar[threading.Lock] = threading.Lock()

    game: ClassVar[str] = "Skyward Sword HD"
    web = SSHDWeb()
    
    options_dataclass = SSHDOptions
    options: SSHDOptions
    
    topology_present: bool = True
    required_client_version: tuple[int, int, int] = (0, 5, 1)
    
    # Hint blacklist - locations that should not be hinted
    hint_blacklist: ClassVar[set[str]] = {
        # Tutorial locations that are too obvious
        "Skyloft - Sword Practice",
        "Skyloft - Knight Academy - First Chest",
    }
    
    # Non-local items: bugs and materials that should stay in SSHD only
    # These items can be found in random SSHD locations but won't be sent to other games
    non_local_items: ClassVar[set[str]] = {
        # Bugs (IDs 141-152)
        "Faron Grasshopper",
        "Woodland Rhino Beetle",
        "Deku Hornet",
        "Skyloft Mantis",
        "Volcanic Ladybug",
        "Blessed Butterfly",
        "Lanayru Ant",
        "Sand Cicada",
        "Gerudo Dragonfly",
        "Eldin Roller",
        "Sky Stag Beetle",
        "Starry Firefly",
        # Materials (IDs 161-176)
        "Hornet Larvae",
        "Bird Feather",
        "Tumbleweed",
        "Lizard Tail",
        "Eldin Ore",
        "Ancient Flower",
        "Amber Relic",
        "Dusk Relic",
        "Jelly Blob",
        "Monster Claw",
        "Monster Horn",
        "Ornamental Skull",
        "Evil Crystal",
        "Blue Bird Feather",
        "Golden Skull",
        "Goddess Plume",
    }
    
    # Item and location tables
    item_name_to_id: ClassVar[dict[str, int]] = {
        name: data.code
        for name, data in ITEM_TABLE.items()
        if data.code is not None
    }
    
    location_name_to_id: ClassVar[dict[str, int]] = {
        name: data.code
        for name, data in LOCATION_TABLE.items()
        if data.code is not None
    }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.created_regions: list[str] = []
    
    def get_resolved_setting(self, setting_name: str, default: str = None) -> str:
        """
        Get a resolved setting value from sshd-rando.
        If the setting was "random", this returns what sshd-rando actually chose.
        """
        if hasattr(self, '_sshd_resolved_settings') and setting_name in self._sshd_resolved_settings:
            return self._sshd_resolved_settings[setting_name]
        return default

    # ── Config.yaml key → (AP option field, mapping_type, value_map) ─────
    # mapping_type: "toggle" | "toggle_custom" | "choice" | "range"
    _CONFIG_TO_AP_OPTION: ClassVar[dict] = {
        # Core Logic
        "logic_rules": ("logic_rules", "choice", {"all_locations_reachable": 0, "beatable_only": 1}),
        "item_pool": ("item_pool", "choice", {"minimal": 0, "standard": 1, "extra": 2, "plentiful": 3}),
        # Completion
        "required_dungeons": ("required_dungeon_count", "range", None),
        "triforce_required": ("triforce_required", "toggle", None),
        "triforce_shuffle": ("triforce_shuffle", "choice", {"vanilla": 0, "sky_keep": 1, "anywhere": 2}),
        "got_sword_requirement": ("gate_of_time_sword_requirement", "choice", {
            "goddess_sword": 0, "goddess_longsword": 1, "goddess_white_sword": 2,
            "master_sword": 3, "true_master_sword": 4,
        }),
        "got_dungeon_requirement": ("gate_of_time_dungeon_requirements", "choice", {"required": 0, "unrequired": 1}),
        "imp_2_skip": ("imp2_skip", "toggle", None),
        "skip_horde": ("skip_horde", "toggle", None),
        "skip_g3": ("skip_ghirahim3", "toggle", None),
        # Shuffles
        "gratitude_crystal_shuffle": ("gratitude_crystal_shuffle", "toggle", None),
        "stamina_fruit_shuffle": ("stamina_fruit_shuffle", "toggle", None),
        "npc_closet_shuffle": ("npc_closet_shuffle", "toggle_custom", {"randomized": 1, "vanilla": 0}),
        "hidden_item_shuffle": ("hidden_item_shuffle", "toggle", None),
        "rupee_shuffle": ("rupee_shuffle", "choice", {"vanilla": 0, "beginner": 1, "intermediate": 2, "advanced": 3}),
        "goddess_chest_shuffle": ("goddess_chest_shuffle", "toggle", None),
        "trial_treasure_shuffle": ("trial_treasure_shuffle", "range", None),
        "tadtone_shuffle": ("tadtone_shuffle", "toggle", None),
        "gossip_stone_treasure_shuffle": ("gossip_stone_treasure_shuffle", "toggle", None),
        # Keys & Maps
        "small_keys": ("small_key_shuffle", "choice", {"vanilla": 0, "own_dungeon": 1, "any_dungeon": 2, "own_region": 3, "overworld": 4, "anywhere": 5, "removed": 6}),
        "boss_keys": ("boss_key_shuffle", "choice", {"vanilla": 0, "own_dungeon": 1, "any_dungeon": 2, "own_region": 3, "overworld": 4, "anywhere": 5, "removed": 6}),
        "map_mode": ("map_shuffle", "choice", {"vanilla": 0, "own_dungeon_restricted": 1, "own_dungeon_unrestricted": 2, "any_dungeon": 3, "own_region": 4, "overworld": 5, "anywhere": 6}),
        # Entrances
        "randomize_entrances": ("randomize_entrances", "toggle", None),
        "randomize_dungeon_entrances": ("randomize_dungeons", "toggle", None),
        "randomize_trial_gate_entrances": ("randomize_trials", "toggle", None),
        "randomize_door_entrances": ("randomize_door_entrances", "toggle", None),
        "randomize_skykeep_layout": ("decouple_skykeep_layout", "toggle", None),
        "randomize_interior_entrances": ("randomize_interior_entrances", "toggle", None),
        "randomize_overworld_entrances": ("randomize_overworld_entrances", "toggle", None),
        "decouple_entrances": ("decouple_entrances", "toggle", None),
        "decouple_double_doors": ("decouple_double_doors", "toggle", None),
        # Music
        "randomize_music": ("music_randomization", "choice", {"vanilla": 0, "shuffle_music": 1, "shuffle_music_limit_vanilla": 2}),
        "cutoff_game_over_music": ("cutoff_game_over_music", "toggle", None),
        # Advanced Randomization
        "enable_back_in_time": ("enable_back_in_time", "toggle", None),
        "underground_rupee_shuffle": ("underground_rupee_shuffle", "toggle", None),
        "beedle_shop_shuffle": ("beedle_shop_shuffle", "choice", {"vanilla": 0, "junk_only": 1, "randomized": 2}),
        "random_bottle_contents": ("random_bottle_contents", "toggle", None),
        "randomize_shop_prices": ("randomize_shop_prices", "toggle", None),
        "ammo_availability": ("ammo_availability", "choice", {"scarce": 0, "vanilla": 1, "useful": 2, "plentiful": 3}),
        "boss_key_puzzles": ("boss_key_puzzles", "choice", {"correct_orientation": 0, "vanilla_orientation": 1, "random_orientation": 2}),
        "minigame_difficulty": ("minigame_difficulty", "choice", {"easy": 0, "medium": 1, "hard": 2}),
        "trap_mode": ("trap_mode", "choice", {"no_traps": 0, "trapish": 1, "trapsome": 2, "traps_o_plenty": 3, "traptacular": 4}),
        "trappable_items": ("trappable_items", "choice", {"major_items": 0, "non_major_items": 1, "any_items": 2}),
        # Trap Types
        "burn_traps": ("burn_traps", "toggle", None),
        "curse_traps": ("curse_traps", "toggle", None),
        "noise_traps": ("noise_traps", "toggle", None),
        "groose_traps": ("groose_traps", "toggle", None),
        "health_traps": ("health_traps", "toggle", None),
        # Advanced Options
        "full_wallet_upgrades": ("full_wallet_upgrades", "toggle", None),
        "chest_type_matches_contents": ("chest_type_matches_contents", "choice", {"off": 0, "only_dungeon_items": 1, "all_contents": 2}),
        "small_keys_in_fancy_chests": ("small_keys_in_fancy_chests", "toggle", None),
        "random_trial_object_positions": ("random_trial_object_positions", "toggle", None),
        "upgraded_skyward_strike": ("upgraded_skyward_strike", "toggle", None),
        "faster_air_meter_depletion": ("faster_air_meter_depletion", "toggle", None),
        "unlock_all_groosenator_destinations": ("unlock_all_groosenator_destinations", "toggle", None),
        "allow_flying_at_night": ("allow_flying_at_night", "toggle", None),
        "natural_night_connections": ("natural_night_connections", "toggle", None),
        "dungeons_include_sky_keep": ("dungeons_include_sky_keep", "toggle", None),
        "empty_unrequired_dungeons": ("empty_unrequired_dungeons", "toggle", None),
        "lanayru_caves_keys": ("lanayru_caves_keys", "choice", {"vanilla": 0, "overworld": 1, "anywhere": 2, "removed": 3}),
        # QoL - Open Locations (some use "open" instead of "on")
        "open_lake_floria": ("open_lake_floria", "toggle_custom", {"vanilla": 0, "yerbal": 1, "open": 1}),
        "open_thunderhead": ("open_thunderhead", "toggle", None),
        "open_earth_temple": ("open_earth_temple", "toggle_custom", {"open": 1, "shuffle_eldin": 0, "shuffle_anywhere": 0}),
        "open_lmf": ("open_lmf", "toggle_custom", {"nodes": 0, "main_node": 0, "open": 1}),
        "open_batreaux_shed": ("open_batreaux_shed", "toggle", None),
        "skip_skykeep_door_cutscene": ("skip_skykeep_door_cutscene", "toggle", None),
        "skip_harp_playing": ("skip_harp_playing", "toggle", None),
        "skip_misc_cutscenes": ("skip_misc_cutscenes", "toggle", None),
        # Shortcuts
        "shortcut_ios_bridge_complete": ("shortcut_ios_bridge_complete", "toggle", None),
        "shortcut_spiral_log_to_btt": ("shortcut_spiral_log_to_btt", "toggle", None),
        "shortcut_logs_near_machi": ("shortcut_logs_near_machi", "toggle", None),
        "shortcut_faron_log_to_floria": ("shortcut_faron_log_to_floria", "toggle", None),
        "shortcut_deep_woods_log_before_tightrope": ("shortcut_deep_woods_log_before_tightrope", "toggle", None),
        "shortcut_deep_woods_log_before_temple": ("shortcut_deep_woods_log_before_temple", "toggle", None),
        "shortcut_eldin_entrance_boulder": ("shortcut_eldin_entrance_boulder", "toggle", None),
        "shortcut_eldin_ascent_boulder": ("shortcut_eldin_ascent_boulder", "toggle", None),
        "shortcut_vs_flames": ("shortcut_vs_flames", "toggle", None),
        "shortcut_lanayru_bars": ("shortcut_lanayru_bars", "toggle", None),
        "shortcut_west_wall_minecart": ("shortcut_west_wall_minecart", "toggle", None),
        "shortcut_sand_oasis_minecart": ("shortcut_sand_oasis_minecart", "toggle", None),
        "shortcut_minecart_before_caves": ("shortcut_minecart_before_caves", "toggle", None),
        "shortcut_skyview_boards": ("shortcut_skyview_boards", "toggle", None),
        "shortcut_skyview_bars": ("shortcut_skyview_bars", "toggle", None),
        "shortcut_earth_temple_bridge": ("shortcut_earth_temple_bridge", "toggle", None),
        "shortcut_lmf_wind_gates": ("shortcut_lmf_wind_gates", "toggle", None),
        "shortcut_lmf_boxes": ("shortcut_lmf_boxes", "toggle", None),
        "shortcut_lmf_bars_to_west_side": ("shortcut_lmf_bars_to_west_side", "toggle", None),
        "shortcut_ac_bridge": ("shortcut_ac_bridge", "toggle", None),
        "shortcut_ac_water_vents": ("shortcut_ac_water_vents", "toggle", None),
        "shortcut_sandship_windows": ("shortcut_sandship_windows", "toggle", None),
        "shortcut_sandship_brig_bars": ("shortcut_sandship_brig_bars", "toggle", None),
        "shortcut_fs_outside_bars": ("shortcut_fs_outside_bars", "toggle", None),
        "shortcut_fs_lava_flow": ("shortcut_fs_lava_flow", "toggle", None),
        "shortcut_sky_keep_svt_room_bars": ("shortcut_sky_keep_svt_room_bars", "toggle", None),
        "shortcut_sky_keep_fs_room_lower_bars": ("shortcut_sky_keep_fs_room_lower_bars", "toggle", None),
        "shortcut_sky_keep_fs_room_upper_bars": ("shortcut_sky_keep_fs_room_upper_bars", "toggle", None),
        # Logic Tricks
        "logic_early_lake_floria": ("logic_early_lake_floria", "toggle", None),
        "logic_beedles_island_cage_chest_dive": ("logic_beedles_island_cage_chest_dive", "toggle", None),
        "logic_volcanic_island_dive": ("logic_volcanic_island_dive", "toggle", None),
        "logic_east_island_dive": ("logic_east_island_dive", "toggle", None),
        "logic_advanced_lizalfos_combat": ("logic_advanced_lizalfos_combat", "toggle", None),
        "logic_long_ranged_skyward_strikes": ("logic_long_ranged_skyward_strikes", "toggle", None),
        "logic_gravestone_jump": ("logic_gravestone_jump", "toggle", None),
        "logic_waterfall_cave_jump": ("logic_waterfall_cave_jump", "toggle", None),
        "logic_bird_nest_item_from_beedles_shop": ("logic_bird_nest_item_from_beedles_shop", "toggle", None),
        "logic_beedles_shop_with_bombs": ("logic_beedles_shop_with_bombs", "toggle", None),
        "logic_stuttersprint": ("logic_stuttersprint", "toggle", None),
        "logic_precise_beetle": ("logic_precise_beetle", "toggle", None),
        "logic_bomb_throws": ("logic_bomb_throws", "toggle", None),
        "logic_faron_woods_with_groosenator": ("logic_faron_woods_with_groosenator", "toggle", None),
        "logic_itemless_first_timeshift_stone": ("logic_itemless_first_timeshift_stone", "toggle", None),
        "logic_stamina_potion_through_sink_sand": ("logic_stamina_potion_through_sink_sand", "toggle", None),
        "logic_brakeslide": ("logic_brakeslide", "toggle", None),
        "logic_lanayru_mine_quick_bomb": ("logic_lanayru_mine_quick_bomb", "toggle", None),
        "logic_tot_skip_brakeslide": ("logic_tot_skip_brakeslide", "toggle", None),
        "logic_tot_slingshot": ("logic_tot_slingshot", "toggle", None),
        "logic_fire_node_without_hook_beetle": ("logic_fire_node_without_hook_beetle", "toggle", None),
        "logic_cactus_bomb_whip": ("logic_cactus_bomb_whip", "toggle", None),
        "logic_skippers_fast_clawshots": ("logic_skippers_fast_clawshots", "toggle", None),
        "logic_skyview_spider_roll": ("logic_skyview_spider_roll", "toggle", None),
        "logic_skyview_coiled_rupee_jump": ("logic_skyview_coiled_rupee_jump", "toggle", None),
        "logic_skyview_precise_slingshot": ("logic_skyview_precise_slingshot", "toggle", None),
        "logic_et_keese_skyward_strike": ("logic_et_keese_skyward_strike", "toggle", None),
        "logic_et_slope_stuttersprint": ("logic_et_slope_stuttersprint", "toggle", None),
        "logic_et_bombless_scaldera": ("logic_et_bombless_scaldera", "toggle", None),
        "logic_lmf_whip_switch": ("logic_lmf_whip_switch", "toggle", None),
        "logic_lmf_ceiling_precise_slingshot": ("logic_lmf_ceiling_precise_slingshot", "toggle", None),
        "logic_lmf_whip_armos_room_timeshift_stone": ("logic_lmf_whip_armos_room_timeshift_stone", "toggle", None),
        "logic_lmf_minecart_jump": ("logic_lmf_minecart_jump", "toggle", None),
        "logic_lmf_bellowsless_moldarach": ("logic_lmf_bellowsless_moldarach", "toggle", None),
        "logic_ac_lever_jump_trick": ("logic_ac_lever_jump_trick", "toggle", None),
        "logic_ac_chest_after_whip_hooks_jump": ("logic_ac_chest_after_whip_hooks_jump", "toggle", None),
        "logic_sandship_jump_to_stern": ("logic_sandship_jump_to_stern", "toggle", None),
        "logic_sandship_itemless_spume": ("logic_sandship_itemless_spume", "toggle", None),
        "logic_sandship_no_combination_hint": ("logic_sandship_no_combination_hint", "toggle", None),
        "logic_fs_pillar_jump": ("logic_fs_pillar_jump", "toggle", None),
        "logic_fs_practice_sword_ghirahim_2": ("logic_fs_practice_sword_ghirahim_2", "toggle", None),
        "logic_present_bow_switches": ("logic_present_bow_switches", "toggle", None),
        "logic_skykeep_vineclip": ("logic_skykeep_vineclip", "toggle", None),
        # Starting Inventory
        "starting_hearts": ("starting_hearts", "range", None),
        "start_with_all_bugs": ("start_with_all_bugs", "toggle", None),
        "start_with_all_treasures": ("start_with_all_treasures", "toggle", None),
        "random_starting_tablet_count": ("starting_tablets", "range", None),
        "starting_sword": ("starting_sword", "choice", {
            "no_sword": 0, "practice_sword": 1, "goddess_sword": 2, "goddess_longsword": 3,
            "goddess_white_sword": 4, "master_sword": 5, "true_master_sword": 6,
        }),
        "random_starting_statues": ("random_starting_statues", "toggle", None),
        "random_starting_spawn": ("random_starting_spawn", "choice", {"vanilla": 0, "anywhere": 1}),
        "limit_starting_spawn": ("limit_starting_spawn", "toggle", None),
        "random_starting_item_count": ("random_starting_item_count", "range", None),
        "peatrice_conversations": ("peatrice_conversations", "range", None),
        # Cosmetics
        "tunic_swap": ("tunic_swap", "toggle", None),
        "lightning_skyward_strike": ("lightning_skyward_strike", "toggle", None),
        "starry_skies": ("starry_skies", "toggle", None),
        "remove_enemy_music": ("remove_enemy_music", "toggle", None),
        # Difficulty
        "damage_multiplier": ("damage_multiplier", "choice", {"half": 0, "1": 1, "normal": 1, "2": 2, "double": 2, "4": 3, "quadruple": 3, "ohko": 4}),
        "no_spoiler_log": ("no_spoiler_log", "toggle", None),
        "empty_unreachable_locations": ("empty_unreachable_locations", "toggle", None),
        "add_junk_items": ("add_junk_items", "toggle", None),
        "junk_item_rate": ("junk_item_rate", "range", None),
    }

    def _sync_ap_options_from_resolved(self, resolved_settings: dict) -> None:
        """
        Update self.options.* fields to match the resolved sshd-rando settings
        so the spoiler log, fill_slot_data, and other AP subsystems display
        the actual config.yaml values rather than Archipelago defaults.
        """
        synced = 0
        for config_key, (ap_field, mapping_type, value_map) in self._CONFIG_TO_AP_OPTION.items():
            if config_key not in resolved_settings:
                continue

            option_obj = getattr(self.options, ap_field, None)
            if option_obj is None:
                continue

            raw = resolved_settings[config_key]
            try:
                if mapping_type == "toggle":
                    raw_s = str(raw).lower()
                    # Accept "on", "open", "true", "1", "yes" as truthy
                    option_obj.value = 1 if raw_s in ("on", "open", "true", "1", "yes") else 0

                elif mapping_type == "toggle_custom":
                    option_obj.value = value_map.get(str(raw).lower(), 0)

                elif mapping_type == "choice":
                    raw_s = str(raw).lower()
                    if raw_s in value_map:
                        option_obj.value = value_map[raw_s]
                    else:
                        try:
                            int_val = int(raw)
                            if int_val in value_map.values():
                                option_obj.value = int_val
                        except (ValueError, TypeError):
                            continue

                elif mapping_type == "range":
                    option_obj.value = int(raw)

                synced += 1
            except Exception as e:
                print(f"[__init__.py] Warning: Could not sync AP option '{ap_field}' from config '{config_key}={raw}': {e}")

        print(f"[__init__.py] Synced {synced} AP options from resolved sshd-rando settings")
    
    def create_regions(self) -> None:
        """
        Create all regions for the world using full sshd-rando logic.
        
        Uses the logic_converter to parse sshd-rando's world YAML files and
        create ~373 regions, ~825 entrances, ~137 events, and per-location rules.
        Falls back to basic Regions.py if the converter fails.
        """
        try:
            from .logic_converter import build_full_logic
            
            # First, create a temporary basic region structure so locations exist
            # The logic converter will move them to fine-grained regions
            self._create_initial_locations()
            
            # Determine the correct backend directory path:
            # When running from .apworld zip, the files are extracted to a temp dir.
            # When running from filesystem (dev), use the local sshd-rando-backend dir.
            from pathlib import Path
            backend_dir = None
            if SSHD_RANDO_TEMP_DIR:
                candidate = Path(SSHD_RANDO_TEMP_DIR) / "sshd-rando-backend"
                if candidate.exists() and (candidate / "data").exists():
                    backend_dir = candidate
            if not backend_dir:
                # Check SSHDRWrapper's resolved path (it scans sys.path + filesystem)
                from .SSHDRWrapper import SSHD_RANDO_PATH as _wrapper_rando_path
                if _wrapper_rando_path and _wrapper_rando_path.exists() and (_wrapper_rando_path / "data").exists():
                    backend_dir = _wrapper_rando_path
            if not backend_dir and SSHD_RANDO_PATH and SSHD_RANDO_PATH.exists():
                backend_dir = SSHD_RANDO_PATH
            
            # Build full logic from sshd-rando YAMLs
            print(f"[__init__.py] Building full logic from sshd-rando world data...")
            if backend_dir:
                print(f"[__init__.py] Using backend data from: {backend_dir}")
            self._logic_converter = build_full_logic(self, backend_dir=backend_dir)
            print(f"[__init__.py] Full logic built successfully")
            self._using_full_logic = True
            
        except Exception as e:
            print(f"[__init__.py] WARNING: Full logic conversion failed: {e}")
            import traceback
            traceback.print_exc()
            print(f"[__init__.py] Falling back to basic region structure...")
            self._using_full_logic = False
            self._create_basic_regions()
    
    def _create_initial_locations(self) -> None:
        """
        Create initial location objects without regions.
        The logic_converter will create proper regions and place locations into them.
        Locations not covered by sshd-rando YAMLs get a fallback region.
        """
        # We don't create regions here — the logic_converter creates them.
        # But we DO need to pre-create all Location objects so the converter
        # can find them and move them to the right region.
        
        # The logic converter creates regions first, then places locations.
        # It needs locations to already exist in the multiworld.
        # So we'll create them in a temporary "Unassigned" region,
        # then the converter will move them.
        
        # Actually, the converter handles everything: it creates regions,
        # then creates locations within those regions based on the YAML data.
        # But we need all LOCATION_TABLE locations to exist. The converter's
        # _build_location_rules will handle locations defined in YAMLs.
        # For locations NOT in any YAML (shouldn't happen, but safety), we need
        # a fallback.
        
        # Let the converter create regions first (in build_full_logic -> convert -> _build_regions).
        # Then the converter adds locations to the correct fine-grained regions.
        # We just need to ensure all locations from LOCATION_TABLE are created.
        pass
    
    def _get_excluded_item_types(self) -> set:
        """
        Determine which location types should be excluded based on shuffle
        settings. When a shuffle is off, both the items from those locations
        AND the locations themselves are excluded from the AP world. This
        prevents Archipelago's fill algorithm from placing random items at
        locations that should remain vanilla in-game.
        """
        # Use resolved sshd-rando settings if available, else fall back to AP options
        s = getattr(self, '_sshd_resolved_settings', {})
        excluded: set = set()

        # Simple on/off toggles
        _TOGGLE_MAP = {
            "Tadtones":              "tadtone_shuffle",
            "Gratitude Crystals":    "gratitude_crystal_shuffle",
            "Stamina Fruits":        "stamina_fruit_shuffle",
            "Hidden Items":          "hidden_item_shuffle",
            "Goddess Chests":        "goddess_chest_shuffle",
            "Gossip Stone Treasures": "gossip_stone_treasure_shuffle",
            "Underground Rupees":    "underground_rupee_shuffle",
        }
        for loc_type, setting_key in _TOGGLE_MAP.items():
            if s:
                val = s.get(setting_key, "off")
                if val not in ("on", "randomized"):
                    excluded.add(loc_type)
            else:
                opt = getattr(self.options, setting_key, None)
                if opt is not None and not opt.value:
                    excluded.add(loc_type)

        # NPC Closet shuffle
        if s:
            if s.get("npc_closet_shuffle", "vanilla") == "vanilla":
                excluded.add("Closets")
        else:
            if not self.options.npc_closet_shuffle.value:
                excluded.add("Closets")

        # Rupee shuffle (tiered)
        if s:
            rupee_val = s.get("rupee_shuffle", "vanilla")
        else:
            rupee_map = {0: "vanilla", 1: "beginner", 2: "intermediate", 3: "advanced"}
            rupee_val = rupee_map.get(self.options.rupee_shuffle.value, "vanilla")

        if rupee_val == "vanilla":
            excluded.update(["Beginner Rupees", "Intermediate Rupees", "Advanced Rupees"])
        elif rupee_val == "beginner":
            excluded.update(["Intermediate Rupees", "Advanced Rupees"])
        elif rupee_val == "intermediate":
            excluded.add("Advanced Rupees")

        # Goddess Cubes are dummy logic items (oarc: null) used internally by
        # sshd-rando to link cube-strike locations to sky Goddess Chests.
        # They have no in-game model and must never be in the AP pool.
        excluded.add("Goddess Cube")

        return excluded

    def _create_basic_regions(self) -> None:
        """Fallback: create basic regions from Regions.py (old behavior)."""
        from .Regions import REGION_CONNECTIONS
        
        # Create all unique regions from location table
        unique_regions = set(["Menu"])  # Always need menu
        for loc in LOCATION_TABLE.values():
            unique_regions.add(loc.region)
        
        # Create region objects
        regions_dict = {}
        for region_name in unique_regions:
            region = Region(region_name, self.player, self.multiworld)
            self.multiworld.regions.append(region)
            regions_dict[region_name] = region
        
        # Add locations to their respective regions
        # When a shuffle setting is off, the corresponding locations stay
        # vanilla in-game and must not be AP locations. If they existed as
        # AP locations without their vanilla items in the pool, Archipelago's
        # fill algorithm would place random items there.
        # This mirrors sshd-rando-backend's get_disabled_shuffle_locations().
        excluded_types = self._get_excluded_item_types()
        
        # Dusk Relic per-location exclusion based on trial_treasure_shuffle
        s = getattr(self, '_sshd_resolved_settings', {})
        if s:
            trial_treasure_val = s.get("trial_treasure_shuffle", "0")
        else:
            trial_treasure_val = str(self.options.trial_treasure_shuffle.value)
        trial_treasure_is_random = trial_treasure_val == "random"
        try:
            trial_treasure_num = int(trial_treasure_val) if not trial_treasure_is_random else 999
        except (ValueError, TypeError):
            trial_treasure_num = 0
        
        for name, data in LOCATION_TABLE.items():
            if data.code is not None:
                # Skip locations whose types are in the excluded set
                if any(t in excluded_types for t in data.types):
                    continue

                # Dusk Relic per-location check: exclude relics above the setting number
                if "Dusk Relic" in data.types and not trial_treasure_is_random:
                    try:
                        relic_num = int(name.split(" ")[-1])
                    except (ValueError, IndexError):
                        relic_num = 0
                    if relic_num > trial_treasure_num:
                        continue
                region = regions_dict.get(data.region)
                if region:
                    location = Location(
                        self.player,
                        name,
                        data.code,
                        region
                    )
                    region.locations.append(location)

        # Create a proper event-only location for Game Beatable
        # IMPORTANT: Don't place event at the real Defeat Demise location (address=2773238)
        # because AP requires locations with int addresses to have items with int codes.
        try:
            from BaseClasses import Item as APItem, ItemClassification
            
            # Find the Temple of Hylia region (where Defeat Demise is)
            target_region = regions_dict.get("Temple of Hylia") or regions_dict.get("Hylia's Realm")
            if target_region:
                event_location = Location(
                    self.player,
                    "Victory - Game Beatable",
                    None,  # Event: no address
                    target_region
                )
                event_location.locked = True
                event_location.progress_type = LocationProgressType.DEFAULT
                
                event_item = APItem("Game Beatable", ItemClassification.progression, None, self.player)
                event_location.place_locked_item(event_item)
                target_region.locations.append(event_location)
            else:
                print("[__init__.py] Warning: Could not find victory region for Game Beatable event")
        except Exception as e:
            print(f"[__init__.py] Warning: Could not create victory event: {e}")
        
        # Connect regions based on REGION_CONNECTIONS
        for source_name, connections in REGION_CONNECTIONS.items():
            if source_name in regions_dict:
                source_region = regions_dict[source_name]
                for dest_name, rule_name in connections:
                    if dest_name in regions_dict:
                        source_region.connect(regions_dict[dest_name], f"{source_name} -> {dest_name}")
    
    def generate_early(self) -> None:
        """
        Called before create_items to set up world-specific data.
        We generate the sshd-rando world here to determine starting items.
        """
        try:
            # Collect Archipelago settings
            from .SSHDRWrapper import generate_sshd_rando_mod
            import tempfile
            from pathlib import Path
            
            # Generate sshd-rando world to determine starting items
            # Use a temp directory since this is just for analysis
            temp_dir = Path(tempfile.mkdtemp(prefix="sshd_early_"))
            ap_settings = self._collect_archipelago_settings()
            seed = self.options.sshdr_seed.value if self.options.sshdr_seed.value else None
            
            print("[__init__.py] Generating sshd-rando world to determine starting items...")
            world, _, setting_string = generate_sshd_rando_mod(
                ap_settings, temp_dir, seed=seed, apply_patches=False
            )
            
            # Extract Setting String decoded starting items (these are the ONLY items we want)
            # ap_settings contains _setting_string_starting_items if Setting String was used
            starting_item_dict = ap_settings.get('_setting_string_starting_items', {})
            
            self._sshd_starting_items = starting_item_dict
            self._sshd_setting_string = setting_string
            self._sshd_world_cache = world  # Cache for later use in generate_output
            
            if starting_item_dict:
                print(f"[__init__.py] Starting items from Setting String:")
                for item_name, count in starting_item_dict.items():
                    print(f"  {item_name} x{count}")
            
            # Extract the COMPLETE item pool from the sshd-rando world.
            # After generate(), all items have been placed into locations.
            # By scanning locations + starting_item_pool, we get the exact pool that
            # sshd-rando built — respecting ALL config.yaml settings: item_pool size,
            # trap_mode, key removal, shuffle-dependent items, etc.
            try:
                from collections import Counter
                sshd_item_pool = Counter()  # item_name -> count
                
                # ── Compute excluded location types from sshd-rando settings ──
                # When a shuffle is off, those locations stay vanilla in-game
                # and must not contribute items to Archipelago's randomized pool.
                excluded_loc_types: set[str] = set()
                trial_treasure_num_early = 0
                trial_treasure_is_random_early = False
                if hasattr(world, 'setting_map') and world.setting_map:
                    sm = world.setting_map.settings
                    _toggle_map = {
                        "Tadtones":              "tadtone_shuffle",
                        "Gratitude Crystals":    "gratitude_crystal_shuffle",
                        "Stamina Fruits":        "stamina_fruit_shuffle",
                        "Hidden Items":          "hidden_item_shuffle",
                        "Goddess Chests":        "goddess_chest_shuffle",
                        "Gossip Stone Treasures": "gossip_stone_treasure_shuffle",
                        "Underground Rupees":    "underground_rupee_shuffle",
                    }
                    for loc_type, skey in _toggle_map.items():
                        if skey in sm and sm[skey].value not in ("on", "randomized"):
                            excluded_loc_types.add(loc_type)
                    if "npc_closet_shuffle" in sm and sm["npc_closet_shuffle"].value == "vanilla":
                        excluded_loc_types.add("Closets")
                    if "beedle_shop_shuffle" in sm and sm["beedle_shop_shuffle"].value == "vanilla":
                        excluded_loc_types.add("Beedle's Airshop")
                    rupee_setting = sm.get("rupee_shuffle", None)
                    rupee_str = rupee_setting.value if rupee_setting else "vanilla"
                    if rupee_str == "vanilla":
                        excluded_loc_types.update(["Beginner Rupees", "Intermediate Rupees", "Advanced Rupees"])
                    elif rupee_str == "beginner":
                        excluded_loc_types.update(["Intermediate Rupees", "Advanced Rupees"])
                    elif rupee_str == "intermediate":
                        excluded_loc_types.add("Advanced Rupees")
                    # Dusk Relic: trial_treasure_shuffle
                    tt_setting = sm.get("trial_treasure_shuffle", None)
                    tt_str = tt_setting.value if tt_setting else "0"
                    trial_treasure_is_random_early = tt_str == "random"
                    try:
                        trial_treasure_num_early = int(tt_str) if not trial_treasure_is_random_early else 999
                    except (ValueError, TypeError):
                        trial_treasure_num_early = 0

                # Goddess Cubes are dummy logic items (oarc: null) — always exclude
                excluded_loc_types.add("Goddess Cube")
                
                if excluded_loc_types:
                    print(f"[__init__.py] Excluding location types from item pool: {sorted(excluded_loc_types)}")
                
                # Scan all filled locations to reconstruct the placed item pool
                locations_excluded = 0
                if hasattr(world, 'location_table'):
                    for loc_name, location in world.location_table.items():
                        if hasattr(location, 'types') and "Hint Location" in location.types:
                            continue  # Skip gossip stones
                        # Skip locations for non-shuffled types
                        if excluded_loc_types and hasattr(location, 'types'):
                            if any(t in excluded_loc_types for t in location.types):
                                locations_excluded += 1
                                continue
                        # Dusk Relic per-location check
                        if hasattr(location, 'types') and "Dusk Relic" in location.types and not trial_treasure_is_random_early:
                            try:
                                relic_num = int(loc_name.split(" ")[-1])
                            except (ValueError, IndexError):
                                relic_num = 0
                            if relic_num > trial_treasure_num_early:
                                locations_excluded += 1
                                continue
                        if hasattr(location, 'current_item') and location.current_item:
                            item_name = location.current_item.name
                            sshd_item_pool[item_name] += 1
                
                if locations_excluded > 0:
                    print(f"[__init__.py] Skipped {locations_excluded} non-shuffled locations from item pool")
                
                # Also count starting items (they were removed from pool during generation)
                sshd_starting_pool = Counter()
                if hasattr(world, 'starting_item_pool'):
                    for item, count in world.starting_item_pool.items():
                        sshd_starting_pool[item.name] += count
                
                # The Archipelago item pool = location items - starting items
                # (starting items are precollected, not in the randomized pool)
                self._sshd_full_item_pool = dict(sshd_item_pool)
                self._sshd_starting_pool = dict(sshd_starting_pool)
                
                print(f"[__init__.py] Extracted sshd-rando item pool: {sum(sshd_item_pool.values())} items across locations")
                print(f"[__init__.py] Starting pool: {sum(sshd_starting_pool.values())} items")
                
                # Log trap counts
                trap_names = {"Health Trap", "Groose Trap", "Noise Trap", "Curse Trap", "Burn Trap"}
                trap_count = sum(count for name, count in sshd_item_pool.items() if name in trap_names)
                if trap_count > 0:
                    print(f"[__init__.py] Traps in pool: {trap_count}")
                    for name in trap_names:
                        if sshd_item_pool[name] > 0:
                            print(f"  {name} x{sshd_item_pool[name]}")
                else:
                    print(f"[__init__.py] No traps in pool (trap_mode may be no_traps)")
                    
            except Exception as e:
                print(f"[__init__.py] Warning: Could not extract sshd-rando item pool: {e}")
                import traceback
                traceback.print_exc()
                self._sshd_full_item_pool = {}
                self._sshd_starting_pool = {}
            
            # Extract hash from ap_settings and store in multiworld
            sshd_hash = ap_settings.get('_sshd_hash', None)
            if sshd_hash:
                self.multiworld.spoiler.hashes[self.player] = sshd_hash
                print(f"[__init__.py] Set multiworld hash: {sshd_hash}")
            
            # IMPORTANT: Extract resolved settings from sshd-rando
            # If any settings were "random", sshd-rando has now resolved them to concrete values
            # We need to update our Archipelago options so the Rules know the actual values
            try:
                resolved_settings = {}
                if hasattr(world, 'setting_map') and world.setting_map:
                    for setting_name, setting_obj in world.setting_map.settings.items():
                        # Get the actual current value (this will be concrete, not "random")
                        value_str = setting_obj.value  # value is the string like "on" or "off"
                        resolved_settings[setting_name] = value_str
                
                if resolved_settings:
                    print(f"[__init__.py] Resolved settings from sshd-rando (random values expanded):")
                    # Show only the settings that might have been random
                    potentially_random = ['small_keys_in_fancy_chests', 'barren_hints_on_gossip_stones', 
                                        'location_hints_on_gossip_stones', 'item_hints_on_gossip_stones', 
                                        'health_traps']
                    for name in potentially_random:
                        if name in resolved_settings:
                            print(f"  {name} = {resolved_settings[name]}")
                
                # Store resolved settings for use in Rules (if needed in future)
                self._sshd_resolved_settings = resolved_settings
                
                # Sync AP options to match resolved settings so the spoiler log
                # and fill_slot_data display the real config.yaml values
                self._sync_ap_options_from_resolved(resolved_settings)
                
            except Exception as e:
                print(f"[__init__.py] Warning: Could not extract resolved settings: {e}")
                import traceback
                traceback.print_exc()
                self._sshd_resolved_settings = {}
            
            # Clean up temp directory
            from shutil import rmtree
            if temp_dir.exists():
                rmtree(temp_dir, ignore_errors=True)
                
        except Exception as e:
            print(f"[__init__.py] Warning: Could not determine starting items: {e}")
            import traceback
            traceback.print_exc()
            self._sshd_starting_items = {}
            self._sshd_resolved_settings = {}
            self._sshd_full_item_pool = {}
            self._sshd_starting_pool = {}
    
    def create_item(self, name: str) -> Item:
        """Create an item by name."""
        data = ITEM_TABLE[name]
        return Item(name, data.classification, data.code, self.player)
    
    def create_items(self) -> None:
        """
        Create all items for the world.
        
        Uses the sshd-rando world's actual item pool (extracted in generate_early)
        as the source of truth. This ensures ALL config.yaml settings are respected:
        trap_mode, item_pool size, key removal, shuffle-dependent items, etc.
        
        Falls back to a hardcoded STANDARD pool if sshd-rando extraction failed.
        """
        
        # Count total locations (excluding events)
        total_locations = len([
            loc for loc in self.multiworld.get_locations(self.player)
            if loc.address is not None and not getattr(loc, "event", False)
        ])
        
        # Items that are stage names for progressive chains — must NEVER be in the AP pool.
        # sshd-rando uses these internally but the Archipelago pool uses only progressive names.
        PROGRESSIVE_STAGE_ITEMS = {
            # Sword stages (Progressive Sword covers all of these)
            "Goddess Sword", "Goddess Longsword", "Goddess White Sword",
            "Master Sword", "True Master Sword",
            # Bow stages (Progressive Bow covers these)
            "Iron Bow", "Sacred Bow",
            # Beetle stages (Progressive Beetle covers these)
            "Hook Beetle", "Quick Beetle", "Tough Beetle",
            # Slingshot stages (Progressive Slingshot covers these)
            "Scattershot",
            # Mitts stages (Progressive Mitts covers these)
            "Mogma Mitts",
            # Bug Net stages (Progressive Bug Net covers these)
            "Big Bug Net",
            # Wallet stages (Progressive Wallet covers these)
            "Big Wallet", "Giant Wallet", "Tycoon Wallet",
            # Pouch stages (Progressive Pouch covers these)
            "Pouch Expansion",
        }
        
        # Map sshd-rando stage names back to their progressive item name.
        # When sshd-rando places e.g. "Goddess Longsword" at a location, that's
        # actually a "Progressive Sword" for Archipelago's purposes.
        STAGE_TO_PROGRESSIVE = {
            "Goddess Sword": "Progressive Sword",
            "Goddess Longsword": "Progressive Sword",
            "Goddess White Sword": "Progressive Sword",
            "Master Sword": "Progressive Sword",
            "True Master Sword": "Progressive Sword",
            "Iron Bow": "Progressive Bow",
            "Sacred Bow": "Progressive Bow",
            "Hook Beetle": "Progressive Beetle",
            "Quick Beetle": "Progressive Beetle",
            "Tough Beetle": "Progressive Beetle",
            "Scattershot": "Progressive Slingshot",
            "Mogma Mitts": "Progressive Mitts",
            "Big Bug Net": "Progressive Bug Net",
            "Big Wallet": "Progressive Wallet",
            "Giant Wallet": "Progressive Wallet",
            "Tycoon Wallet": "Progressive Wallet",
            "Pouch Expansion": "Progressive Pouch",
        }
        
        # Items to skip entirely (not part of the randomized pool)
        SKIP_ITEMS = {
            "Game Beatable",      # Victory event, placed separately
            "Archipelago Item",   # Cross-world placeholder, not in our pool
            "Sailcloth",          # Always given as a starting item, never randomized
        }

        # Goddess Cube items are dummy logic items with no in-game model (oarc: null).
        # They exist in sshd-rando to link cube-strike locations → sky Goddess Chests
        # but must never appear as real items in the AP pool.
        SKIP_GODDESS_CUBES = {name for name in ITEM_TABLE if "Goddess Cube" in name}
        
        # --- FORCE SAILCLOTH AS STARTING ITEM ---
        # Sailcloth is always given to the player unconditionally.
        # Rando devs are still working on logic for it; until then it must not be randomized.
        self.multiworld.push_precollected(self.create_item("Sailcloth"))
        print(f"[__init__.py] Sailcloth granted as forced starting item")
        
        # --- PRECOLLECT STARTING ITEMS ---
        # sshd-rando's starting_item_pool (extracted in generate_early) contains items
        # the player begins with. These are SEPARATE from the fill pool — items at
        # locations do NOT include starting items (they were removed before fill).
        # We must precollect them so Archipelago's logic knows they're available.
        starting_items = getattr(self, '_sshd_starting_pool', {})
        
        if starting_items:
            print(f"[__init__.py] Granting {sum(starting_items.values())} starting items as precollected:")
            for raw_name, count in starting_items.items():
                # Convert any stage names to progressive (safety net for progressive_items=on)
                item_name = STAGE_TO_PROGRESSIVE.get(raw_name, raw_name)
                # Skip Sailcloth — already force-granted above
                if item_name == "Sailcloth":
                    print(f"  {item_name} x{count} (skipped, already force-granted)")
                    continue
                if item_name in ITEM_TABLE:
                    for _ in range(count):
                        item = self.create_item(item_name)
                        self.multiworld.push_precollected(item)
                    print(f"  {item_name} x{count}")
                else:
                    print(f"  [WARNING] '{raw_name}' not found in ITEM_TABLE - skipped")
        
        # --- BUILD POOL FROM SSHD-RANDO WORLD (source of truth) ---
        # The sshd-rando world was generated in generate_early() with all config.yaml
        # settings applied. Its filled locations contain the exact items it chose,
        # including traps, respecting item_pool size, key removal, etc.
        # NOTE: Starting items were already removed from sshd-rando's item_pool before
        # fill_worlds() ran, so items at locations are exclusively non-starting items.
        sshd_pool = getattr(self, '_sshd_full_item_pool', {})
        
        item_pool = []
        
        if sshd_pool:
            print(f"[__init__.py] Building Archipelago item pool from sshd-rando world...")
            
            # Build a unified pool: count each item across all sshd-rando locations,
            # converting stage names to progressive names.
            from collections import Counter
            ap_pool_counts = Counter()
            
            for item_name, count in sshd_pool.items():
                # Convert stage names to progressive names
                ap_name = STAGE_TO_PROGRESSIVE.get(item_name, item_name)
                ap_pool_counts[ap_name] += count
            
            # Cap Green Rupee and Tumbleweed to exactly 1 each
            for cap_item in ["Green Rupee", "Tumbleweed"]:
                if ap_pool_counts.get(cap_item, 0) > 1:
                    ap_pool_counts[cap_item] = 1
            
            # Add all placed items directly to the AP pool.
            # No subtraction needed — sshd-rando already removed starting items
            # from item_pool before fill_worlds() ran, so items at locations
            # are exclusively non-starting items. Starting items were precollected above.
            for ap_name, count in ap_pool_counts.items():
                # Skip items not in our ITEM_TABLE (e.g. sshd-rando internal items)
                if ap_name not in ITEM_TABLE:
                    continue
                
                # Skip non-pool items
                if ap_name in SKIP_ITEMS or ap_name in SKIP_GODDESS_CUBES:
                    continue
                
                for _ in range(count):
                    item_pool.append(self.create_item(ap_name))
            
            # Log trap counts
            trap_count = len([i for i in item_pool if i.classification == IC.trap])
            if trap_count > 0:
                print(f"[__init__.py] Traps in AP pool: {trap_count}")
        else:
            # --- FALLBACK: hardcoded STANDARD pool ---
            # Used only if sshd-rando world extraction failed
            print(f"[__init__.py] WARNING: No sshd-rando pool available, using hardcoded STANDARD fallback")
            
            # Determine excluded types to filter shuffle-dependent items
            excluded_types = self._get_excluded_item_types()
            
            # Map items to the location type they belong to (so we can exclude them)
            _ITEM_TO_LOC_TYPE = {
                "Group of Tadtones": "Tadtones",
                "Gratitude Crystal": "Gratitude Crystals",
            }
            
            POOL_ITEM_COUNTS = {
                "Progressive Sword": 6,
                "Progressive Bow": 3,
                "Progressive Beetle": 4,
                "Progressive Bug Net": 2,
                "Progressive Slingshot": 2,
                "Progressive Mitts": 2,
                "Progressive Pouch": 5,
                "Progressive Wallet": 4,
                "Extra Wallet": 3,
                "Song of the Hero Part": 4,
                "Key Piece": 5,
                "Empty Bottle": 5,
                "Gratitude Crystal Pack": 13,
                "Gratitude Crystal": 15,
                "Group of Tadtones": 17,
                "Skyview Temple Small Key": 2,
                "Ancient Cistern Small Key": 2,
                "Sandship Small Key": 2,
                "Fire Sanctuary Small Key": 3,
                "Lanayru Caves Small Key": 2,
                "Heart Medal": 2,
                "Rupee Medal": 2,
                "Heart Piece": 24,
                "Heart Container": 6,
                "Life Medal": 2,
                "Wooden Shield": 1,
                "Hylian Shield": 1,
                "Cursed Medal": 1,
                "Treasure Medal": 1,
                "Potion Medal": 1,
                "Small Seed Satchel": 1,
                "Small Quiver": 1,
                "Small Bomb Bag": 1,
                "Bug Medal": 1,
                "Golden Skull": 1,
                "Goddess Plume": 1,
                "Dusk Relic": 1,
                "Tumbleweed": 1,
                "Green Rupee": 1,
                "5 Bombs": 1,
            }
            
            for name, data in ITEM_TABLE.items():
                if name in SKIP_ITEMS or name in PROGRESSIVE_STAGE_ITEMS:
                    continue
                if data.classification == IC.trap:
                    continue
                # Skip items whose shuffle is off
                item_loc_type = _ITEM_TO_LOC_TYPE.get(name)
                if item_loc_type and item_loc_type in excluded_types:
                    continue
                # Skip Goddess Cube dummy items
                if "Goddess Cube" in name:
                    continue
                
                if name in POOL_ITEM_COUNTS:
                    total_count = POOL_ITEM_COUNTS[name]
                    starting_count = starting_items.get(name, 0)
                    pool_count = max(0, total_count - starting_count)
                    for _ in range(pool_count):
                        item_pool.append(self.create_item(name))
                elif data.classification in (IC.progression, IC.useful):
                    starting_count = starting_items.get(name, 0)
                    if starting_count == 0:
                        item_pool.append(self.create_item(name))
        
        # Fill remaining slots with junk filler items
        JUNK_FILL_ITEMS = [
            "Blue Rupee", "Red Rupee",
            "10 Arrows", "5 Bombs", "10 Bombs",
            "5 Deku Seeds", "10 Deku Seeds",
        ]
        junk_items = [name for name in JUNK_FILL_ITEMS if name in ITEM_TABLE]
        
        junk_idx = 0
        while len(item_pool) < total_locations:
            junk_name = junk_items[junk_idx % len(junk_items)]
            item_pool.append(self.create_item(junk_name))
            junk_idx += 1
        
        # If we have more items than locations (shouldn't happen normally), trim
        if len(item_pool) > total_locations:
            print(f"[__init__.py] WARNING: Pool has {len(item_pool)} items but only {total_locations} locations, trimming excess")
            item_pool = item_pool[:total_locations]
        
        print(f"[__init__.py] Created item pool:")
        print(f"  Total locations: {total_locations}")
        print(f"  Progression/Useful items: {len([i for i in item_pool if i.classification in (IC.progression, IC.useful)])}")
        print(f"  Filler items: {len([i for i in item_pool if i.classification == IC.filler])}")
        print(f"  Trap items: {len([i for i in item_pool if i.classification == IC.trap])}")
        print(f"  Starting items (precollected): {sum(starting_items.values())}")
        
        # Add items to the multiworld pool
        self.multiworld.itempool += item_pool
    
    # ── Dungeon item pre-fill constants ──────────────────────────────────
    
    # Maps each dungeon to its small key name(s), boss key name, and map name.
    DUNGEON_ITEM_NAMES: dict[str, dict[str, list[str]]] = {
        "Skyview Temple": {
            "small_keys": ["Skyview Temple Small Key"],
            "boss_keys": ["Skyview Temple Boss Key"],
            "maps": ["Skyview Temple Map"],
        },
        "Earth Temple": {
            "small_keys": [],
            "boss_keys": ["Earth Temple Boss Key"],
            "maps": ["Earth Temple Map"],
        },
        "Lanayru Mining Facility": {
            "small_keys": ["Lanayru Mining Facility Small Key"],
            "boss_keys": ["Lanayru Mining Facility Boss Key"],
            "maps": ["Lanayru Mining Facility Map"],
        },
        "Ancient Cistern": {
            "small_keys": ["Ancient Cistern Small Key"],
            "boss_keys": ["Ancient Cistern Boss Key"],
            "maps": ["Ancient Cistern Map"],
        },
        "Fire Sanctuary": {
            "small_keys": ["Fire Sanctuary Small Key"],
            "boss_keys": ["Fire Sanctuary Boss Key"],
            "maps": ["Fire Sanctuary Map"],
        },
        "Sandship": {
            "small_keys": ["Sandship Small Key"],
            "boss_keys": ["Sandship Boss Key"],
            "maps": ["Sandship Map"],
        },
        "Sky Keep": {
            "small_keys": ["Sky Keep Small Key"],
            "boss_keys": [],
            "maps": ["Sky Keep Map"],
        },
    }
    
    # All dungeons (AP location regions that are considered "dungeons")
    ALL_DUNGEON_REGIONS: set[str] = set(DUNGEON_ITEM_NAMES.keys())
    
    # Maps each dungeon to its parent "hint region" (the overworld area outside the dungeon).
    # Used for "own_region" key shuffle mode.
    DUNGEON_TO_HINT_REGION: dict[str, str] = {
        "Skyview Temple": "Faron Woods",
        "Earth Temple": "Eldin Volcano",
        "Lanayru Mining Facility": "Lanayru Desert",
        "Ancient Cistern": "Lake Floria",
        "Fire Sanctuary": "Volcano Summit",
        "Sandship": "Lanayru Sand Sea",
        "Sky Keep": "Central Skyloft",
    }
    
    # Maps each hint region to the set of AP location regions it encompasses.
    HINT_REGION_TO_AP_REGIONS: dict[str, set[str]] = {
        "Faron Woods": {"Faron Woods", "Deep Woods", "Inside the Great Tree",
                        "Inside the Flooded Great Tree", "Flooded Faron Woods"},
        "Lake Floria": {"Lake Floria", "Floria Waterfall"},
        "Eldin Volcano": {"Eldin Volcano", "Mogma Turf", "Bokoblin Base",
                          "Lower Eldin Cave", "Upper Eldin Cave", "Thrill Digger Cave"},
        "Volcano Summit": {"Volcano Summit"},
        "Lanayru Desert": {"Lanayru Mine", "Lanayru Desert", "Temple of Time",
                           "Fire Node", "Lightning Node"},
        "Lanayru Sand Sea": {"Lanayru Gorge", "Ancient Harbour", "Shipyard",
                             "Skipper's Retreat", "Skipper's Retreat Shack",
                             "Pirate Stronghold", "Pirate Stronghold Interior",
                             "Construction Bay"},
        "Central Skyloft": {"Central Skyloft", "Upper Skyloft", "Skyloft Village",
                            "Knight Academy", "Sparring Hall", "Bazaar",
                            "Batreaux's House", "Lumpy Pumpkin",
                            "Inside the Statue of the Goddess"},
    }
    
    # All regions that are considered "overworld" (non-dungeon, non-sky).
    # Built dynamically; used for "overworld" key shuffle mode.
    
    def _get_dungeon_locations(self, dungeon: str) -> list:
        """Get all unfilled AP locations in a specific dungeon."""
        return [
            loc for loc in self.multiworld.get_locations(self.player)
            if loc.address is not None
            and loc.item is None
            and getattr(loc, "sshd_region", loc.name.split(" - ")[0] if " - " in loc.name else "") == dungeon
        ]
    
    def _get_locations_by_region_names(self, region_names: set[str]) -> list:
        """Get all unfilled AP locations whose region is in the given set."""
        from .Locations import LOCATION_TABLE
        return [
            loc for loc in self.multiworld.get_locations(self.player)
            if loc.address is not None
            and loc.item is None
            and LOCATION_TABLE.get(loc.name, None) is not None
            and LOCATION_TABLE[loc.name].region in region_names
        ]
    
    def _get_all_dungeon_location_set(self) -> set[str]:
        """Get the set of all location names that are inside any dungeon."""
        from .Locations import LOCATION_TABLE
        return {
            name for name, loc_data in LOCATION_TABLE.items()
            if loc_data.region in self.ALL_DUNGEON_REGIONS
        }

    def _get_overworld_locations(self) -> list:
        """Get all unfilled AP locations in the overworld (not in a dungeon, not in sky/skyloft)."""
        from .Locations import LOCATION_TABLE
        dungeon_locs = self._get_all_dungeon_location_set()
        return [
            loc for loc in self.multiworld.get_locations(self.player)
            if loc.address is not None
            and loc.item is None
            and loc.name not in dungeon_locs
        ]
    
    def pre_fill(self) -> None:
        """
        Restrict dungeon items (small keys, boss keys, maps) based on shuffle settings.
        
        This pulls restricted items out of the general multiworld.itempool and places
        them into only valid locations using fill_restrictive, so Archipelago's fill
        algorithm respects the player's key/map shuffle settings.
        """
        from .Locations import LOCATION_TABLE
        from Fill import fill_restrictive
        
        small_key_mode = self.options.small_key_shuffle.current_key   # e.g. "own_dungeon"
        boss_key_mode = self.options.boss_key_shuffle.current_key     # e.g. "own_dungeon" 
        map_mode = self.options.map_shuffle.current_key               # e.g. "own_dungeon_restricted"
        
        print(f"[__init__.py] pre_fill: small_keys={small_key_mode}, boss_keys={boss_key_mode}, map_mode={map_mode}")
        
        # "anywhere" and "removed" modes need no restriction — AP fill handles them.
        # "vanilla" is handled by sshd-rando's fill, but we also enforce it here.
        
        def _collect_items_from_pool(item_names: list[str]) -> list:
            """Remove and return all items with matching names from multiworld.itempool."""
            collected = []
            remaining = []
            name_set = set(item_names)
            for item in self.multiworld.itempool:
                if item.player == self.player and item.name in name_set:
                    collected.append(item)
                else:
                    remaining.append(item)
            self.multiworld.itempool = remaining
            return collected
        
        def _get_valid_locations_for_mode(mode: str, dungeon: str) -> list:
            """Get valid unfilled locations for a given shuffle mode and dungeon."""
            if mode in ("own_dungeon", "own_dungeon_restricted", "own_dungeon_unrestricted", "vanilla"):
                # Restrict to the dungeon's own locations
                return [
                    loc for loc in self.multiworld.get_locations(self.player)
                    if loc.address is not None
                    and loc.item is None
                    and LOCATION_TABLE.get(loc.name) is not None
                    and LOCATION_TABLE[loc.name].region == dungeon
                ]
            elif mode == "any_dungeon":
                # Restrict to any dungeon location
                return [
                    loc for loc in self.multiworld.get_locations(self.player)
                    if loc.address is not None
                    and loc.item is None
                    and LOCATION_TABLE.get(loc.name) is not None
                    and LOCATION_TABLE[loc.name].region in self.ALL_DUNGEON_REGIONS
                ]
            elif mode == "own_region":
                # Restrict to dungeon + its parent hint region
                hint_region = self.DUNGEON_TO_HINT_REGION.get(dungeon, "")
                valid_regions = self.HINT_REGION_TO_AP_REGIONS.get(hint_region, set()).copy()
                valid_regions.add(dungeon)  # Include the dungeon itself
                return [
                    loc for loc in self.multiworld.get_locations(self.player)
                    if loc.address is not None
                    and loc.item is None
                    and LOCATION_TABLE.get(loc.name) is not None
                    and LOCATION_TABLE[loc.name].region in valid_regions
                ]
            elif mode == "overworld":
                # Restrict to non-dungeon locations
                all_dungeon_locs = self._get_all_dungeon_location_set()
                return [
                    loc for loc in self.multiworld.get_locations(self.player)
                    if loc.address is not None
                    and loc.item is None
                    and loc.name not in all_dungeon_locs
                ]
            else:
                # "anywhere" or "removed" — no restriction needed
                return []
        
        def _place_restricted_items(item_type: str, mode: str, items_by_dungeon: dict[str, list]):
            """Place items restricted to valid locations per dungeon."""
            if mode in ("anywhere", "removed"):
                return  # No restriction — leave items in the general pool
            
            for dungeon, items in items_by_dungeon.items():
                if not items:
                    continue
                    
                valid_locations = _get_valid_locations_for_mode(mode, dungeon)
                
                if not valid_locations:
                    print(f"[__init__.py] WARNING: No valid locations for {item_type} "
                          f"in {dungeon} with mode={mode}. Leaving in general pool.")
                    # Put items back in general pool as fallback
                    self.multiworld.itempool.extend(items)
                    continue
                
                if len(items) > len(valid_locations):
                    print(f"[__init__.py] WARNING: {len(items)} {item_type} items for {dungeon} "
                          f"but only {len(valid_locations)} valid locations with mode={mode}. "
                          f"Placing what we can, rest goes to general pool.")
                
                # Shuffle locations for randomness
                self.random.shuffle(valid_locations)
                
                try:
                    fill_restrictive(
                        self.multiworld,
                        self.multiworld.get_all_state(False),
                        valid_locations,
                        items,
                        single_player_placement=True,
                        lock=True,
                        allow_partial=True,
                        name=f"SSHD {item_type} ({dungeon})",
                    )
                except Exception as e:
                    print(f"[__init__.py] WARNING: fill_restrictive failed for {item_type} "
                          f"in {dungeon}: {e}. Remaining items go to general pool.")
                
                # Any items not placed go back to the general pool
                if items:
                    print(f"[__init__.py] {len(items)} {item_type} items could not be "
                          f"placed in {dungeon}, adding to general pool")
                    self.multiworld.itempool.extend(items)
        
        # ── Small Keys ───────────────────────────────────────────────────
        if small_key_mode not in ("anywhere", "removed"):
            small_key_items: dict[str, list] = {}
            for dungeon, info in self.DUNGEON_ITEM_NAMES.items():
                items = _collect_items_from_pool(info["small_keys"])
                if items:
                    small_key_items[dungeon] = items
            
            total_sk = sum(len(v) for v in small_key_items.values())
            print(f"[__init__.py] pre_fill: Placing {total_sk} small keys with mode={small_key_mode}")
            _place_restricted_items("small_keys", small_key_mode, small_key_items)
        
        # ── Boss Keys ────────────────────────────────────────────────────
        if boss_key_mode not in ("anywhere", "removed"):
            boss_key_items: dict[str, list] = {}
            for dungeon, info in self.DUNGEON_ITEM_NAMES.items():
                items = _collect_items_from_pool(info["boss_keys"])
                if items:
                    boss_key_items[dungeon] = items
            
            total_bk = sum(len(v) for v in boss_key_items.values())
            print(f"[__init__.py] pre_fill: Placing {total_bk} boss keys with mode={boss_key_mode}")
            _place_restricted_items("boss_keys", boss_key_mode, boss_key_items)
        
        # ── Dungeon Maps ─────────────────────────────────────────────────
        if map_mode not in ("anywhere",):
            map_items: dict[str, list] = {}
            for dungeon, info in self.DUNGEON_ITEM_NAMES.items():
                items = _collect_items_from_pool(info["maps"])
                if items:
                    map_items[dungeon] = items
            
            total_maps = sum(len(v) for v in map_items.values())
            if total_maps > 0:
                print(f"[__init__.py] pre_fill: Placing {total_maps} maps with mode={map_mode}")
                _place_restricted_items("maps", map_mode, map_items)
        
        # ── Lanayru Caves Keys (separate setting) ───────────────────────
        lanayru_caves_mode = self.options.lanayru_caves_keys.current_key
        if lanayru_caves_mode not in ("anywhere", "removed"):
            lc_items = _collect_items_from_pool(["Lanayru Caves Small Key"])
            if lc_items:
                print(f"[__init__.py] pre_fill: Placing {len(lc_items)} Lanayru Caves keys with mode={lanayru_caves_mode}")
                if lanayru_caves_mode == "vanilla":
                    # Restrict to Lanayru Caves locations
                    valid_locs = [
                        loc for loc in self.multiworld.get_locations(self.player)
                        if loc.address is not None
                        and loc.item is None
                        and LOCATION_TABLE.get(loc.name) is not None
                        and LOCATION_TABLE[loc.name].region == "Lanayru Caves"
                    ]
                elif lanayru_caves_mode == "overworld":
                    all_dungeon_locs = self._get_all_dungeon_location_set()
                    valid_locs = [
                        loc for loc in self.multiworld.get_locations(self.player)
                        if loc.address is not None
                        and loc.item is None
                        and loc.name not in all_dungeon_locs
                    ]
                else:
                    valid_locs = []
                
                if valid_locs:
                    self.random.shuffle(valid_locs)
                    try:
                        fill_restrictive(
                            self.multiworld,
                            self.multiworld.get_all_state(False),
                            valid_locs,
                            lc_items,
                            single_player_placement=True,
                            lock=True,
                            allow_partial=True,
                            name="SSHD Lanayru Caves Keys",
                        )
                    except Exception as e:
                        print(f"[__init__.py] WARNING: fill_restrictive failed for Lanayru Caves keys: {e}")
                
                # Any remaining go to general pool
                if lc_items:
                    self.multiworld.itempool.extend(lc_items)
        
        # ── Triforce Shuffle ─────────────────────────────────────────────
        triforce_mode = self.options.triforce_shuffle.current_key
        if triforce_mode != "anywhere":
            triforce_items = _collect_items_from_pool([
                "Triforce of Courage",
                "Triforce of Power",
                "Triforce of Wisdom"
            ])
            if triforce_items:
                print(f"[__init__.py] pre_fill: Placing {len(triforce_items)} Triforce pieces with mode={triforce_mode}")
                
                if triforce_mode == "vanilla":
                    # Restrict to the 3 vanilla Sky Keep locations
                    vanilla_triforce_locs = [
                        "Sky Keep - Sacred Power of Din",
                        "Sky Keep - Sacred Power of Nayru",
                        "Sky Keep - Sacred Power of Farore"
                    ]
                    valid_locs = [
                        loc for loc in self.multiworld.get_locations(self.player)
                        if loc.address is not None
                        and loc.item is None
                        and loc.name in vanilla_triforce_locs
                    ]
                elif triforce_mode == "sky_keep":
                    # Restrict to any Sky Keep location
                    valid_locs = [
                        loc for loc in self.multiworld.get_locations(self.player)
                        if loc.address is not None
                        and loc.item is None
                        and LOCATION_TABLE.get(loc.name) is not None
                        and LOCATION_TABLE[loc.name].region == "Sky Keep"
                    ]
                else:
                    valid_locs = []
                
                if valid_locs:
                    self.random.shuffle(valid_locs)
                    try:
                        fill_restrictive(
                            self.multiworld,
                            self.multiworld.get_all_state(False),
                            valid_locs,
                            triforce_items,
                            single_player_placement=True,
                            lock=True,
                            allow_partial=True,
                            name="SSHD Triforce Pieces",
                        )
                    except Exception as e:
                        print(f"[__init__.py] WARNING: fill_restrictive failed for Triforce pieces: {e}")
                
                # Any remaining go to general pool
                if triforce_items:
                    print(f"[__init__.py] {len(triforce_items)} Triforce pieces could not be placed, adding to general pool")
                    self.multiworld.itempool.extend(triforce_items)
        
        print(f"[__init__.py] pre_fill complete")

    def set_rules(self) -> None:
        """
        Set access rules for regions and locations.
        
        If full logic was built by logic_converter (in create_regions), rules
        are already set on entrances, events, and locations. We only need to
        set the completion condition here.
        
        Falls back to basic Rules.py rules if full logic wasn't available.
        """
        if getattr(self, '_using_full_logic', False):
            # Full logic already applied by logic_converter in create_regions.
            # Just set the completion condition.
            set_completion_condition(self)
        else:
            # Fallback: use basic rules from Rules.py
            set_rules(self)
    
    def post_fill(self) -> None:
        """
        Run after the fill to diagnose any accessibility issues.
        
        Simulates the same sweep that fulfills_accessibility() performs,
        and reports which advancement locations are stuck (unreachable).
        This runs BEFORE the concurrent accessibility check in Main.py,
        so we get diagnostic output even if the check fails.
        """
        from BaseClasses import CollectionState
        
        try:
            state = CollectionState(self.multiworld)
            advancement_locs = [
                loc for loc in self.multiworld.get_locations()
                if loc.advancement
            ]
            
            remaining = list(advancement_locs)
            iteration = 0
            beatable = False
            
            while remaining:
                sphere = [loc for loc in remaining if loc.can_reach(state)]
                if not sphere:
                    break
                for loc in sphere:
                    remaining.remove(loc)
                    if loc.item:
                        state.collect(loc.item, True, loc)
                iteration += 1
                if self.multiworld.has_beaten_game(state):
                    beatable = True
                    break
            
            if remaining:
                # Report stuck locations for debugging
                print(f"[SSHD-DIAG] Post-fill check: {len(remaining)} advancement locations unreachable "
                      f"(of {len(advancement_locs)} total, {iteration} spheres)")
                for loc in remaining[:30]:
                    region_name = loc.parent_region.name if loc.parent_region else "None"
                    item_name = loc.item.name if loc.item else "None"
                    print(f"  STUCK: {loc.name} (region={region_name}, item={item_name})")
                
                # Also check which regions are unreachable
                unreachable_regions = set()
                for loc in remaining:
                    if loc.parent_region and not loc.parent_region.can_reach(state):
                        unreachable_regions.add(loc.parent_region.name)
                if unreachable_regions:
                    print(f"[SSHD-DIAG] Unreachable regions ({len(unreachable_regions)}):")
                    for rn in sorted(unreachable_regions)[:20]:
                        print(f"  UNREACHABLE REGION: {rn}")
                
                if not beatable:
                    # Check what's missing for completion
                    resolved = getattr(self, '_sshd_resolved_settings', {})
                    print(f"[SSHD-DIAG] Game NOT beatable at end of sweep")
                    print(f"  Progressive Swords collected: {state.count('Progressive Sword', self.player)}")
                    print(f"  got_sword_requirement: {resolved.get('got_sword_requirement', 'unknown')}")
                    print(f"  required_dungeons: {resolved.get('required_dungeons', 'unknown')}")
                    boss_keys = ['Skyview Temple Boss Key', 'Earth Temple Boss Key',
                                'Lanayru Mining Facility Boss Key', 'Ancient Cistern Boss Key',
                                'Sandship Boss Key', 'Fire Sanctuary Boss Key']
                    for bk in boss_keys:
                        print(f"  {bk}: {'YES' if state.has(bk, self.player) else 'no'}")
                    print(f"  Has Game Beatable: {'YES' if state.has('Game Beatable', self.player) else 'no'}")
            else:
                status = "beatable" if beatable else "all locations reachable but game not beaten"
                print(f"[SSHD-DIAG] Post-fill check OK: all {len(advancement_locs)} advancement locations "
                      f"reachable in {iteration} spheres, game {status}")
        except Exception as e:
            print(f"[SSHD-DIAG] Post-fill diagnostic failed: {e}")
            import traceback
            traceback.print_exc()
    
    def fill_slot_data(self) -> dict[str, Any]:
        """Generate slot data for the client."""
        slot_data = {
            "world_version": WORLD_VERSION,
            "rando_version": RANDO_VERSION,
            "seed": self.multiworld.seed,
        }
        
        # Add all player options for client validation
        for field in fields(self.options):
            option_name = field.name
            option_value = getattr(self.options, field.name)
            slot_data[f"option_{option_name}"] = option_value.value
        
        # Build location-to-item mapping for the client
        # This maps Archipelago item codes to SSHD location codes
        location_to_item_map = {}
        for location in self.multiworld.get_locations(self.player):
            if location.address is not None and location.item:
                # Map: location_code -> item_code
                location_to_item_map[location.address] = location.item.code
        
        slot_data["location_to_item_map"] = location_to_item_map
        
        # Build custom flag mapping for ALL locations
        # This happens during slot_data generation (before generate_output)
        # so the client gets the mapping immediately on connect
        # Cache it so we can reuse the same mapping when injecting into sshd-rando
        print("[__init__.py] Building custom flag mapping for slot_data...")
        self._custom_flag_mapping = self._build_custom_flag_mapping()
        
        slot_data["custom_flag_to_location"] = self._custom_flag_mapping
        print(f"[__init__.py] Added {len(self._custom_flag_mapping)} custom flag -> location mappings to slot_data")
        
        # Build reverse mapping: location -> custom_flag for item giving
        # This lets the client set custom flags to trigger vanilla item pickups
        location_to_custom_flag = {loc_code: flag for flag, loc_code in self._custom_flag_mapping.items()}
        slot_data["location_to_custom_flag"] = location_to_custom_flag
        
        # Build AP item info for cross-world items (item 216 locations)
        # Maps custom_flag_id -> {"item": item_name, "player": player_name}
        # This lets the client tell the game what item name and player name to display
        ap_item_info = {}
        for location in self.multiworld.get_locations(self.player):
            if location.address is not None and location.item:
                # Check if this is a cross-world item (not for this player or not in our item table)
                from .Items import ITEM_TABLE
                is_own_item = (location.item.name in ITEM_TABLE and location.item.player == self.player)
                if not is_own_item:
                    # Find the custom_flag_id for this location
                    loc_code = location.address
                    if loc_code in location_to_custom_flag:
                        flag_id = location_to_custom_flag[loc_code]
                        player_name = self.multiworld.get_player_name(location.item.player)
                        ap_item_info[flag_id] = {
                            "item": location.item.name,
                            "player": player_name,
                        }
        
        slot_data["ap_item_info"] = ap_item_info
        print(f"[__init__.py] Added {len(ap_item_info)} AP item info entries to slot_data")
        
        return slot_data
    
    def generate_output(self, output_directory: str) -> None:
        """
        Generate the .apsshd patch file.
        
        This integrates with sshd-rando to create romfs/exefs mod files.
        """
        import tempfile
        from shutil import rmtree, copytree
        
        # Create temporary directory for patch generation
        temp_dir = Path(tempfile.mkdtemp(prefix="sshd_ap_"))
        
        try:
            # Collect randomization data for JSON
            patch_data = {
                "seed": self.multiworld.seed,
                "player_name": self.player_name,
                "player_id": self.player,
                "sshd_setting_string": getattr(self, '_sshd_setting_string', ""),  # Set by _generate_sshd_patches
                "locations": {},
                "items": {},
                "options": {},
            }
            
            # Map Archipelago locations to SSHD items
            for location in self.multiworld.get_locations(self.player):
                if location.address is not None and location.item:
                    # Get the SSHD item name from the Archipelago item
                    ap_item_name = location.item.name
                    
                    # Map to sshd-rando location/item names
                    patch_data["locations"][location.name] = {
                        "item": ap_item_name,
                        "player": location.item.player,
                        "is_local": location.item.player == self.player,
                    }
            
            # Store all items we need to be able to give
            for item_name, item_data in ITEM_TABLE.items():
                patch_data["items"][item_name] = {
                    "code": item_data.code,
                    "classification": item_data.classification.name,
                    "original_id": item_data.original_id,
                }
            
            # Add options
            for field in fields(self.options):
                option_name = field.name
                option_value = getattr(self.options, field.name)
                patch_data["options"][option_name] = option_value.value
            
            # Try to generate sshd-rando patches if available
            romfs_path = None
            exefs_path = None
            
            if SSHD_RANDO_AVAILABLE:
                try:
                    print("[__init__.py] Generating sshd-rando patches...")
                    romfs_path, exefs_path = self._generate_sshd_patches(temp_dir, patch_data)
                    
                    if romfs_path and exefs_path:
                        print(f"[__init__.py] ✓ sshd-rando patches generated")
                        print(f"  romfs: {len(list(romfs_path.rglob('*')))} files")
                        print(f"  exefs: {len(list(exefs_path.rglob('*')))} files")
                        
                        # Patch logos with Archipelago branding
                        self._patch_archipelago_logos(romfs_path)
                    else:
                        print(f"[__init__.py] WARNING: sshd-rando generation returned no paths")
                        
                except FileNotFoundError as e:
                    # Specific handling for missing extract files
                    error_msg = str(e)
                    if "sshd_extract" in error_msg or "ObjectPack.arc.LZ" in error_msg or "romfs" in error_msg:
                        print(f"\n" + "="*80)
                        print(f"ERROR: SSHD ROM files not found")
                        default_path = get_default_sshd_extract_path()
                        os_name = get_os_name()
                        print(f"="*80)
                        print(f"\nThe SSHD randomizer requires extracted ROM files to generate patches.")
                        print(f"\nTo fix this:")
                        print(f"1. Extract your SSHD ROM (romfs and exefs folders) using a tool like hactool")
                        print(f"2. Place the extracted files in:") 
                        print(f"   {default_path}/romfs")
                        print(f"   {default_path}/exefs")
                        print(f"   OR set 'extract_path' in your YAML to point to your extraction")
                        print(f"\nCurrent extract path: {self.options.extract_path.value or default_path}")
                        print(f"Missing file: {error_msg}")
                        print(f"\nPatch file will only contain item/location mappings (no visual/gameplay changes)")
                        print(f"="*80 + "\n")
                    else:
                        # Other file not found errors
                        import traceback
                        print(f"\nERROR: File not found while generating patches:")
                        print(f"Exception: {e}")
                        print(f"\nFull traceback:")
                        traceback.print_exc()
                        print("\nPatch file will only contain item/location mappings")
                        
                except Exception as e:
                    import traceback
                    print(f"\nERROR: Could not generate sshd-rando patches:")
                    print(f"Exception: {e}")
                    print(f"\nFull traceback:")
                    traceback.print_exc()
                    print("\nPatch file will only contain item/location mappings")
            else:
                print(f"Warning: sshd-rando-backend not available")
                print("Patch file will only contain item/location mappings")
            
            # Create the .apsshd patch file
            patch_file_name = f"AP_{self.multiworld.seed}_P{self.player}_{self.player_name}.apsshd"
            patch_file_path = os.path.join(output_directory, patch_file_name)
            
            with zipfile.ZipFile(patch_file_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
                # Always write the manifest
                manifest = {
                    "game": "Skyward Sword HD",
                    "player": self.player_name,
                    "player_id": self.player,
                    "seed": self.multiworld.seed,
                    "version": WORLD_VERSION,
                }
                zip_file.writestr("manifest.json", json.dumps(manifest, indent=2))
                
                # Write patch data (convert any sets to lists for JSON serialization)
                def convert_sets_to_lists(obj):
                    """Recursively convert sets to lists for JSON serialization."""
                    if isinstance(obj, set):
                        return list(obj)
                    elif isinstance(obj, dict):
                        return {k: convert_sets_to_lists(v) for k, v in obj.items()}
                    elif isinstance(obj, (list, tuple)):
                        return [convert_sets_to_lists(item) for item in obj]
                    else:
                        return obj
                
                serializable_patch_data = convert_sets_to_lists(patch_data)
                zip_file.writestr("patch_data.json", json.dumps(serializable_patch_data, indent=2))
                
                # Include romfs if generated
                if romfs_path and romfs_path.exists():
                    for root, dirs, files in os.walk(romfs_path):
                        for file in files:
                            file_path = Path(root) / file
                            arc_path = f"romfs/{file_path.relative_to(romfs_path)}"
                            zip_file.write(file_path, arc_path)
                
                # Include exefs if generated
                if exefs_path and exefs_path.exists():
                    for root, dirs, files in os.walk(exefs_path):
                        for file in files:
                            file_path = Path(root) / file
                            arc_path = f"exefs/{file_path.relative_to(exefs_path)}"
                            zip_file.write(file_path, arc_path)
            
        finally:
            # Clean up temp directory
            if temp_dir.exists():
                rmtree(temp_dir)
    
    def _generate_sshd_patches(self, output_dir: Path, patch_data: dict) -> Tuple[Path, Path]:
        """
        Generate sshd-rando patches using the SSHDRWrapper.
        
        Returns:
            Tuple of (romfs_path, exefs_path) if generation succeeds, else (None, None)
        """
        try:
            # Collect Archipelago settings as a dictionary for the wrapper
            ap_settings = self._collect_archipelago_settings()
            
            # Get seed from options (empty string means use random)
            seed = self.options.sshdr_seed.value if self.options.sshdr_seed.value else None
            
            # Use sshd-rando wrapper to generate the mod WITHOUT patches
            # We'll apply patches after overlaying Archipelago items
            print("[__init__.py] Calling SSHDRWrapper to generate mod (without patches)...")
            world, actual_output_dir, setting_string = generate_sshd_rando_mod(
                ap_settings, output_dir, seed=seed, apply_patches=False
            )
            
            # Store setting string for patch data
            self._sshd_setting_string = setting_string
            
            # Extract starting items from the sshd-rando world
            # These items should be excluded from the Archipelago item pool
            # NOTE: If _sshd_starting_items was already set in generate_early() from the Setting String decoder,
            # DON'T overwrite it with world.starting_item_pool (which includes extra items from starting_sword/hearts)
            if not hasattr(self, '_sshd_starting_items') or not self._sshd_starting_items:
                starting_item_dict = {}
                for item, count in world.starting_item_pool.items():
                    starting_item_dict[item.name] = count
                self._sshd_starting_items = starting_item_dict
                
                if starting_item_dict:
                    print(f"[__init__.py] Starting items from sshd-rando:")
                    for item_name, count in starting_item_dict.items():
                        print(f"  {item_name} x{count}")
            else:
                # We already have the Setting String items from generate_early(), so don't extract from world.starting_item_pool
                print(f"[__init__.py] Using Setting String starting items (already extracted in generate_early())")
            
            # Build multiworld item overlay mapping
            # Map Archipelago locations → SSHD locations → items
            print("[__init__.py] Building multiworld item overlay...")
            sshd_to_ap_item_mapping = self._build_multiworld_item_mapping()
            
            # Apply overlay to the generated world
            from .SSHDRWrapper import overlay_multiworld_items
            overlay_results = overlay_multiworld_items(world, sshd_to_ap_item_mapping)
            print(f"[__init__.py] Overlay results:")
            print(f"  Total locations: {overlay_results.get('total_locations', 0)}")
            print(f"  Replaced items: {overlay_results.get('replaced_items', 0)}")
            print(f"  Cross-world items: {overlay_results.get('cross_world_items', 0)}")
            print(f"  Unmapped locations: {overlay_results.get('unmapped_locations', 0)}")
            
            # CRITICAL: Inject custom flags for ALL 911 locations BEFORE patches are applied
            # This ensures sshd-rando patcher writes ALL custom flags into the game ROM
            # Use the SAME mapping we built in fill_slot_data() to ensure ROM matches client
            print("[__init__.py] Injecting custom flags for all Archipelago locations...")
            if not hasattr(self, '_custom_flag_mapping'):
                # Build the mapping if fill_slot_data() hasn't been called yet
                self._custom_flag_mapping = self._build_custom_flag_mapping()
            
            from .SSHDRWrapper import inject_custom_flags_into_world
            inject_custom_flags_into_world(world, self._custom_flag_mapping, self.multiworld, self.player)
            print(f"[__init__.py] ✓ Injected {len(self._custom_flag_mapping)} custom flags")
            
            # Apply patches with the overlaid items
            # This generates the romfs/exefs with Archipelago items in them
            print("[__init__.py] Applying patches with multiworld items...")
            try:
                # Import from sshd-rando via sys.path
                import sys
                from patches.allpatchhandler import AllPatchHandler
                from util.text import load_text_data
                # Serialize patch generation: sshd-rando uses module-level global
                # state (text_table) that is not thread-safe. Archipelago runs
                # generate_output in parallel threads, so we must hold a lock
                # for the entire patch generation to prevent data corruption.
                with SSHDWorld._sshd_patch_lock:
                    load_text_data()
                    patch_handler = AllPatchHandler(world)
                    patch_handler.do_all_patches()
                print("[__init__.py] ✓ Patches applied successfully")
                
                # Extract the ACTUAL custom flag assignments from sshd-rando's world object
                # These are the flags that were written into the game ROM by the patcher
                print("[__init__.py] Extracting custom flag assignments from patched world...")
                sshd_custom_flag_names = extract_custom_flag_mapping(world)
                
                # Convert location names to location codes for the client
                # All real locations exist in the AP world (only Goddess Cubes excluded)
                self._actual_custom_flag_mapping = {}
                skipped_internal = 0
                for custom_flag_id, location_name in sshd_custom_flag_names.items():
                    try:
                        location = self.multiworld.get_location(location_name, self.player)
                        if location and location.address is not None:
                            self._actual_custom_flag_mapping[custom_flag_id] = location.address
                    except Exception as e:
                        # Only Goddess Cube locations should be missing
                        skipped_internal += 1
                
                print(f"[__init__.py] Stored {len(self._actual_custom_flag_mapping)} custom flag assignments for client")
                if skipped_internal:
                    print(f"[__init__.py] Skipped {skipped_internal} internal locations (Goddess Cubes)")
                
                # VERIFICATION: Compare intended vs actual custom flag assignments
                # This detects mismatches that would cause AP item text to fail
                if hasattr(self, '_custom_flag_mapping') and self._actual_custom_flag_mapping:
                    intended = self._custom_flag_mapping  # flag_id -> location_code
                    actual_reverse = {loc_code: flag_id for flag_id, loc_code in self._actual_custom_flag_mapping.items()}
                    intended_reverse = {loc_code: flag_id for flag_id, loc_code in intended.items()}
                    
                    mismatches = 0
                    missing_from_rom = 0
                    for loc_code, intended_flag in intended_reverse.items():
                        if loc_code in actual_reverse:
                            actual_flag = actual_reverse[loc_code]
                            if intended_flag != actual_flag:
                                mismatches += 1
                                if mismatches <= 10:
                                    print(f"[__init__.py] ⚠ FLAG MISMATCH: location {loc_code} intended flag={intended_flag} but ROM has flag={actual_flag}")
                        else:
                            missing_from_rom += 1
                    
                    if mismatches == 0 and missing_from_rom <= 50:  # Goddess Cubes are expected missing
                        print(f"[__init__.py] ✓ Custom flag verification passed ({len(intended)} intended, {len(self._actual_custom_flag_mapping)} in ROM, {missing_from_rom} not in ROM)")
                    else:
                        print(f"[__init__.py] ⚠ Custom flag issues: {mismatches} mismatches, {missing_from_rom} missing from ROM")
                        if mismatches > 0:
                            print(f"[__init__.py] ⚠ AP item text may show fallback for {mismatches} locations!")
                
                # Verify files were created
                exefs_out = actual_output_dir / "exefs"
                if exefs_out.exists():
                    exefs_files = list(exefs_out.glob("*"))
                    print(f"[__init__.py] exefs contains {len(exefs_files)} files:")
                    for f in sorted(exefs_files):
                        print(f"  - {f.name}")
                else:
                    print(f"[__init__.py] ERROR: exefs directory not created!")
                    
            except Exception as e:
                print(f"[__init__.py] ERROR: Could not apply patches: {e}")
                import traceback
                traceback.print_exc()
                print(f"[__init__.py] This will result in incomplete exefs files!")
            
            # Verify output was created
            romfs_path = actual_output_dir / "romfs"
            exefs_path = actual_output_dir / "exefs"
            
            if romfs_path.exists() and exefs_path.exists():
                print(f"[__init__.py] ✓ Mod generated successfully with multiworld items")
                print(f"  romfs: {len(list(romfs_path.rglob('*')))} items")
                print(f"  exefs: {len(list(exefs_path.rglob('*')))} items")
                if setting_string:
                    print(f"  Setting String: {setting_string[:60]}...")
                return romfs_path, exefs_path
            else:
                print(f"[__init__.py] WARNING: Some output files missing")
                print(f"  romfs exists: {romfs_path.exists()}")
                print(f"  exefs exists: {exefs_path.exists()}")
                return None, None
            
        except Exception as e:
            import traceback
            print(f"[__init__.py] ERROR: sshd-rando generation failed: {e}")
            traceback.print_exc()
            return None, None
    
    def _load_config_yaml(self) -> dict:
        """
        Load settings from config.yaml file.
        
        Returns:
            dict: Settings loaded from config.yaml, or empty dict if file not found
        """
        import yaml
        from pathlib import Path
        
        # Get config path from options
        config_path_str = self.options.config_yaml_path.value
        if not config_path_str:
            # No config path specified, return empty dict to use Archipelago options
            return {}
        
        config_path = Path(config_path_str)
        
        if not config_path.exists():
            print(f"[__init__.py] Warning: config.yaml not found at {config_path}")
            return {}
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)
            
            if not config_data:
                print(f"[__init__.py] Warning: config.yaml is empty")
                return {}
            
            # Extract World 1 settings (the config has a "World 1" key)
            world_settings = config_data.get('World 1', {})
            
            # Also include top-level settings like seed, generate_spoiler_log, etc.
            result = {}
            
            # Copy top-level settings
            for key in ['seed', 'generate_spoiler_log', 'use_plandomizer', 'plandomizer_file']:
                if key in config_data:
                    result[key] = config_data[key]
            
            # Merge world settings
            result.update(world_settings)
            
            print(f"[__init__.py] Loaded {len(result)} settings from config.yaml")
            return result
            
        except Exception as e:
            print(f"[__init__.py] Error loading config.yaml: {e}")
            import traceback
            traceback.print_exc()
            return {}
    
    def _collect_archipelago_settings(self) -> dict:
        """
        Collect Archipelago options as a dictionary for sshd-rando wrapper.
        
        First tries to load from config.yaml if config_yaml_path option is set.
        If that file exists and contains valid settings, uses those.
        Otherwise falls back to Archipelago options.
        
        Maps Archipelago option values to sshd-rando setting names and values.
        """
        # Try loading from config.yaml first
        config_settings = self._load_config_yaml()
        
        if config_settings:
            print("[__init__.py] Using settings from config.yaml")
            # Convert the config settings to the format expected by sshd-rando
            # Most settings are already in the correct format (string values like "on"/"off")
            # Just need to ensure proper types
            settings_dict = {}
            
            # Copy all settings from config
            for key, value in config_settings.items():
                if key in ['seed', 'generate_spoiler_log', 'use_plandomizer', 'plandomizer_file']:
                    # These are top-level settings, handle separately if needed
                    continue
                
                # Convert values to strings if they aren't already
                if isinstance(value, bool):
                    settings_dict[key] = "on" if value else "off"
                elif isinstance(value, (int, float)):
                    settings_dict[key] = str(value)
                elif isinstance(value, str):
                    # Keep strings as-is (including "random", "on", "off", etc.)
                    settings_dict[key] = value
                elif isinstance(value, list):
                    settings_dict[key] = value
                elif value is None:
                    # Skip None values
                    continue
                else:
                    settings_dict[key] = str(value)
            
            # Handle extract_path if not in config
            if 'extract_path' not in settings_dict:
                settings_dict["extract_path"] = self.options.extract_path.value or str(get_default_sshd_extract_path())
            
            # Handle setting_string if not in config
            if 'setting_string' not in settings_dict:
                settings_dict["setting_string"] = self.options.setting_string.value or ""
            
            # OVERRIDE settings that would break Archipelago functionality
            # These must be set regardless of what's in config.yaml
            print("[__init__.py] Applying Archipelago-required setting overrides...")
            
            # Demise must be enabled for Archipelago (it's the goal)
            settings_dict["skip_demise"] = "off"
            
            # Hints are disabled - Archipelago uses its own hint system
            settings_dict["path_hints"] = "0"
            settings_dict["barren_hints"] = "0"
            settings_dict["location_hints"] = "0"
            settings_dict["item_hints"] = "0"
            settings_dict["song_hints"] = "off"
            settings_dict["impa_sot_hint"] = "off"
            
            # Ensure hints on Fi/Gossip Stones are off (Archipelago handles hints)
            settings_dict["path_hints_on_fi"] = "off"
            settings_dict["path_hints_on_gossip_stones"] = "off"
            settings_dict["barren_hints_on_fi"] = "off"
            settings_dict["barren_hints_on_gossip_stones"] = "off"
            settings_dict["location_hints_on_fi"] = "off"
            settings_dict["location_hints_on_gossip_stones"] = "off"
            settings_dict["item_hints_on_fi"] = "off"
            settings_dict["item_hints_on_gossip_stones"] = "off"
            
            # Spawn hearts must be on for Archipelago
            settings_dict["spawn_hearts"] = "on"
            
            # CRITICAL: Progressive items MUST be enabled for Archipelago
            # Archipelago's item system expects progressive items (Progressive Beetle, Progressive Sword, etc.)
            # Non-progressive items would break the item pool and cause mismatches
            settings_dict["progressive_items"] = "on"
            
            print("[__init__.py] Applied overrides: skip_demise=off, all hints disabled, spawn_hearts=on, progressive_items=on")
            
            return settings_dict
        
        # Fall back to Archipelago options if config.yaml doesn't exist or is empty
        print("[__init__.py] Using Archipelago options (config.yaml not found or empty)")
        settings_dict = {}
        
        # Logic Settings
        logic_map = {0: "all_locations_reachable", 1: "beatable_only"}
        settings_dict["logic_rules"] = logic_map[self.options.logic_rules.value]
        
        item_pool_map = {0: "minimal", 1: "standard", 2: "extra", 3: "plentiful"}
        settings_dict["item_pool"] = item_pool_map[self.options.item_pool.value]
        
        # Completion Requirements
        settings_dict["required_dungeons"] = str(self.options.required_dungeon_count.value)
        settings_dict["skip_horde"] = "on" if self.options.skip_horde.value else "off"
        settings_dict["skip_g3"] = "on" if self.options.skip_ghirahim3.value else "off"
        settings_dict["skip_demise"] = "off"  # Keep for Archipelago
        
        # Gate of Time
        got_sword_map = {
            0: "goddess_sword",
            1: "goddess_longsword",
            2: "goddess_white_sword",
            3: "master_sword",
            4: "true_master_sword"
        }
        settings_dict["got_sword_requirement"] = got_sword_map[self.options.gate_of_time_sword_requirement.value]
        
        # Shuffles
        settings_dict["gratitude_crystal_shuffle"] = "on" if self.options.gratitude_crystal_shuffle.value else "off"
        settings_dict["stamina_fruit_shuffle"] = "on" if self.options.stamina_fruit_shuffle.value else "off"
        settings_dict["npc_closet_shuffle"] = "randomized" if self.options.npc_closet_shuffle.value else "vanilla"
        settings_dict["hidden_item_shuffle"] = "on" if self.options.hidden_item_shuffle.value else "off"
        
        rupee_mode_map = {0: "vanilla", 1: "beginner", 2: "intermediate", 3: "advanced"}
        settings_dict["rupee_shuffle"] = rupee_mode_map[self.options.rupee_shuffle.value]
        
        settings_dict["goddess_chest_shuffle"] = "on" if self.options.goddess_chest_shuffle.value else "off"
        settings_dict["trial_treasure_shuffle"] = str(self.options.trial_treasure_shuffle.value)
        settings_dict["tadtone_shuffle"] = "on" if self.options.tadtone_shuffle.value else "off"
        settings_dict["gossip_stone_treasure_shuffle"] = "on" if self.options.gossip_stone_treasure_shuffle.value else "off"
        
        # Keys & Maps
        key_mode_map = {0: "vanilla", 1: "own_dungeon", 2: "any_dungeon", 3: "own_region", 4: "overworld", 5: "anywhere", 6: "removed"}
        settings_dict["small_keys"] = key_mode_map[self.options.small_key_shuffle.value]
        settings_dict["boss_keys"] = key_mode_map[self.options.boss_key_shuffle.value]
        
        map_mode_map = {0: "vanilla", 1: "own_dungeon_restricted", 2: "own_dungeon_unrestricted", 3: "any_dungeon", 4: "own_region", 5: "overworld", 6: "anywhere"}
        settings_dict["map_mode"] = map_mode_map[self.options.map_shuffle.value]
        
        # Entrance Randomization
        settings_dict["randomize_dungeons"] = "on" if self.options.randomize_dungeons.value else "off"
        settings_dict["randomize_trials"] = "on" if self.options.randomize_trials.value else "off"
        settings_dict["randomize_door_entrances"] = "on" if self.options.randomize_door_entrances.value else "off"
        settings_dict["decouple_double_doors"] = "on" if self.options.decouple_double_doors.value else "off"
        settings_dict["randomize_interior_entrances"] = "on" if self.options.randomize_interior_entrances.value else "off"
        settings_dict["randomize_overworld_entrances"] = "on" if self.options.randomize_overworld_entrances.value else "off"
        settings_dict["decouple_entrances"] = "on" if self.options.decouple_entrances.value else "off"
        settings_dict["randomize_skykeep_layout"] = "on" if self.options.decouple_skykeep_layout.value else "off"
        
        # Music & Audio
        music_map = {0: "vanilla", 1: "shuffle_music", 2: "shuffle_music_limit_vanilla"}
        settings_dict["randomize_music"] = music_map.get(self.options.music_randomization.value, "vanilla")
        settings_dict["cutoff_game_over_music"] = "on" if self.options.cutoff_game_over_music.value else "off"
        
        # Advanced Randomization
        settings_dict["enable_back_in_time"] = "on" if self.options.enable_back_in_time.value else "off"
        settings_dict["underground_rupee_shuffle"] = "on" if self.options.underground_rupee_shuffle.value else "off"
        
        beedle_shop_map = {0: "vanilla", 1: "junk_only", 2: "randomized"}
        settings_dict["beedle_shop_shuffle"] = beedle_shop_map[self.options.beedle_shop_shuffle.value]
        
        settings_dict["random_bottle_contents"] = "on" if self.options.random_bottle_contents.value else "off"
        settings_dict["randomize_shop_prices"] = "on" if self.options.randomize_shop_prices.value else "off"
        
        ammo_map = {0: "scarce", 1: "vanilla", 2: "useful", 3: "plentiful"}
        settings_dict["ammo_availability"] = ammo_map[self.options.ammo_availability.value]
        
        boss_key_map = {0: "correct_orientation", 1: "vanilla_orientation", 2: "random_orientation"}
        settings_dict["boss_key_puzzles"] = boss_key_map[self.options.boss_key_puzzles.value]
        
        minigame_map = {0: "easy", 1: "medium", 2: "hard"}
        settings_dict["minigame_difficulty"] = minigame_map[self.options.minigame_difficulty.value]
        
        trap_mode_map = {0: "no_traps", 1: "trapish", 2: "trapsome", 3: "traps_o_plenty", 4: "traptacular"}
        settings_dict["trap_mode"] = trap_mode_map[self.options.trap_mode.value]
        
        trappable_map = {0: "major_items", 1: "non_major_items", 2: "any_items"}
        settings_dict["trappable_items"] = trappable_map[self.options.trappable_items.value]
        
        # Trap Types
        settings_dict["burn_traps"] = "on" if self.options.burn_traps.value else "off"
        settings_dict["curse_traps"] = "on" if self.options.curse_traps.value else "off"
        settings_dict["noise_traps"] = "on" if self.options.noise_traps.value else "off"
        settings_dict["groose_traps"] = "on" if self.options.groose_traps.value else "off"
        settings_dict["health_traps"] = "on" if self.options.health_traps.value else "off"
        
        # Advanced Options
        settings_dict["full_wallet_upgrades"] = "on" if self.options.full_wallet_upgrades.value else "off"
        
        chest_type_map = {0: "off", 1: "only_dungeon_items", 2: "all_contents"}
        settings_dict["chest_type_matches_contents"] = chest_type_map[self.options.chest_type_matches_contents.value]
        
        settings_dict["small_keys_in_fancy_chests"] = "on" if self.options.small_keys_in_fancy_chests.value else "off"
        settings_dict["random_trial_object_positions"] = "on" if self.options.random_trial_object_positions.value else "off"
        settings_dict["upgraded_skyward_strike"] = "on" if self.options.upgraded_skyward_strike.value else "off"
        settings_dict["faster_air_meter_depletion"] = "on" if self.options.faster_air_meter_depletion.value else "off"
        settings_dict["unlock_all_groosenator_destinations"] = "on" if self.options.unlock_all_groosenator_destinations.value else "off"
        settings_dict["allow_flying_at_night"] = "on" if self.options.allow_flying_at_night.value else "off"
        settings_dict["natural_night_connections"] = "on" if self.options.natural_night_connections.value else "off"
        settings_dict["peatrice_conversations"] = str(self.options.peatrice_conversations.value)
        
        # Quality of Life - Shortcuts
        settings_dict["shortcut_ios_bridge_complete"] = "on" if self.options.shortcut_ios_bridge_complete.value else "off"
        settings_dict["shortcut_spiral_log_to_btt"] = "on" if self.options.shortcut_spiral_log_to_btt.value else "off"
        settings_dict["shortcut_logs_near_machi"] = "on" if self.options.shortcut_logs_near_machi.value else "off"
        settings_dict["shortcut_faron_log_to_floria"] = "on" if self.options.shortcut_faron_log_to_floria.value else "off"
        settings_dict["shortcut_deep_woods_log_before_tightrope"] = "on" if self.options.shortcut_deep_woods_log_before_tightrope.value else "off"
        settings_dict["shortcut_deep_woods_log_before_temple"] = "on" if self.options.shortcut_deep_woods_log_before_temple.value else "off"
        settings_dict["shortcut_eldin_entrance_boulder"] = "on" if self.options.shortcut_eldin_entrance_boulder.value else "off"
        settings_dict["shortcut_eldin_ascent_boulder"] = "on" if self.options.shortcut_eldin_ascent_boulder.value else "off"
        settings_dict["shortcut_vs_flames"] = "on" if self.options.shortcut_vs_flames.value else "off"
        settings_dict["shortcut_lanayru_bars"] = "on" if self.options.shortcut_lanayru_bars.value else "off"
        settings_dict["shortcut_west_wall_minecart"] = "on" if self.options.shortcut_west_wall_minecart.value else "off"
        settings_dict["shortcut_sand_oasis_minecart"] = "on" if self.options.shortcut_sand_oasis_minecart.value else "off"
        settings_dict["shortcut_minecart_before_caves"] = "on" if self.options.shortcut_minecart_before_caves.value else "off"
        settings_dict["shortcut_skyview_boards"] = "on" if self.options.shortcut_skyview_boards.value else "off"
        settings_dict["shortcut_skyview_bars"] = "on" if self.options.shortcut_skyview_bars.value else "off"
        settings_dict["shortcut_earth_temple_bridge"] = "on" if self.options.shortcut_earth_temple_bridge.value else "off"
        settings_dict["shortcut_lmf_wind_gates"] = "on" if self.options.shortcut_lmf_wind_gates.value else "off"
        settings_dict["shortcut_lmf_boxes"] = "on" if self.options.shortcut_lmf_boxes.value else "off"
        settings_dict["shortcut_lmf_bars_to_west_side"] = "on" if self.options.shortcut_lmf_bars_to_west_side.value else "off"
        settings_dict["shortcut_ac_bridge"] = "on" if self.options.shortcut_ac_bridge.value else "off"
        settings_dict["shortcut_ac_water_vents"] = "on" if self.options.shortcut_ac_water_vents.value else "off"
        settings_dict["shortcut_sandship_windows"] = "on" if self.options.shortcut_sandship_windows.value else "off"
        settings_dict["shortcut_sandship_brig_bars"] = "on" if self.options.shortcut_sandship_brig_bars.value else "off"
        settings_dict["shortcut_fs_outside_bars"] = "on" if self.options.shortcut_fs_outside_bars.value else "off"
        settings_dict["shortcut_fs_lava_flow"] = "on" if self.options.shortcut_fs_lava_flow.value else "off"
        settings_dict["shortcut_sky_keep_svt_room_bars"] = "on" if self.options.shortcut_sky_keep_svt_room_bars.value else "off"
        settings_dict["shortcut_sky_keep_fs_room_lower_bars"] = "on" if self.options.shortcut_sky_keep_fs_room_lower_bars.value else "off"
        settings_dict["shortcut_sky_keep_fs_room_upper_bars"] = "on" if self.options.shortcut_sky_keep_fs_room_upper_bars.value else "off"
        
        # Logic Tricks
        settings_dict["logic_early_lake_floria"] = "on" if self.options.logic_early_lake_floria.value else "off"
        settings_dict["logic_beedles_island_cage_chest_dive"] = "on" if self.options.logic_beedles_island_cage_chest_dive.value else "off"
        settings_dict["logic_volcanic_island_dive"] = "on" if self.options.logic_volcanic_island_dive.value else "off"
        settings_dict["logic_east_island_dive"] = "on" if self.options.logic_east_island_dive.value else "off"
        settings_dict["logic_advanced_lizalfos_combat"] = "on" if self.options.logic_advanced_lizalfos_combat.value else "off"
        settings_dict["logic_long_ranged_skyward_strikes"] = "on" if self.options.logic_long_ranged_skyward_strikes.value else "off"
        settings_dict["logic_gravestone_jump"] = "on" if self.options.logic_gravestone_jump.value else "off"
        settings_dict["logic_waterfall_cave_jump"] = "on" if self.options.logic_waterfall_cave_jump.value else "off"
        settings_dict["logic_bird_nest_item_from_beedles_shop"] = "on" if self.options.logic_bird_nest_item_from_beedles_shop.value else "off"
        settings_dict["logic_beedles_shop_with_bombs"] = "on" if self.options.logic_beedles_shop_with_bombs.value else "off"
        settings_dict["logic_stuttersprint"] = "on" if self.options.logic_stuttersprint.value else "off"
        settings_dict["logic_precise_beetle"] = "on" if self.options.logic_precise_beetle.value else "off"
        settings_dict["logic_bomb_throws"] = "on" if self.options.logic_bomb_throws.value else "off"
        settings_dict["logic_faron_woods_with_groosenator"] = "on" if self.options.logic_faron_woods_with_groosenator.value else "off"
        settings_dict["logic_itemless_first_timeshift_stone"] = "on" if self.options.logic_itemless_first_timeshift_stone.value else "off"
        settings_dict["logic_stamina_potion_through_sink_sand"] = "on" if self.options.logic_stamina_potion_through_sink_sand.value else "off"
        settings_dict["logic_brakeslide"] = "on" if self.options.logic_brakeslide.value else "off"
        settings_dict["logic_lanayru_mine_quick_bomb"] = "on" if self.options.logic_lanayru_mine_quick_bomb.value else "off"
        settings_dict["logic_tot_skip_brakeslide"] = "on" if self.options.logic_tot_skip_brakeslide.value else "off"
        settings_dict["logic_tot_slingshot"] = "on" if self.options.logic_tot_slingshot.value else "off"
        settings_dict["logic_fire_node_without_hook_beetle"] = "on" if self.options.logic_fire_node_without_hook_beetle.value else "off"
        settings_dict["logic_cactus_bomb_whip"] = "on" if self.options.logic_cactus_bomb_whip.value else "off"
        settings_dict["logic_skippers_fast_clawshots"] = "on" if self.options.logic_skippers_fast_clawshots.value else "off"
        settings_dict["logic_skyview_spider_roll"] = "on" if self.options.logic_skyview_spider_roll.value else "off"
        settings_dict["logic_skyview_coiled_rupee_jump"] = "on" if self.options.logic_skyview_coiled_rupee_jump.value else "off"
        settings_dict["logic_skyview_precise_slingshot"] = "on" if self.options.logic_skyview_precise_slingshot.value else "off"
        settings_dict["logic_et_keese_skyward_strike"] = "on" if self.options.logic_et_keese_skyward_strike.value else "off"
        settings_dict["logic_et_slope_stuttersprint"] = "on" if self.options.logic_et_slope_stuttersprint.value else "off"
        settings_dict["logic_et_bombless_scaldera"] = "on" if self.options.logic_et_bombless_scaldera.value else "off"
        settings_dict["logic_lmf_whip_switch"] = "on" if self.options.logic_lmf_whip_switch.value else "off"
        settings_dict["logic_lmf_ceiling_precise_slingshot"] = "on" if self.options.logic_lmf_ceiling_precise_slingshot.value else "off"
        settings_dict["logic_lmf_whip_armos_room_timeshift_stone"] = "on" if self.options.logic_lmf_whip_armos_room_timeshift_stone.value else "off"
        settings_dict["logic_lmf_minecart_jump"] = "on" if self.options.logic_lmf_minecart_jump.value else "off"
        settings_dict["logic_lmf_bellowsless_moldarach"] = "on" if self.options.logic_lmf_bellowsless_moldarach.value else "off"
        settings_dict["logic_ac_lever_jump_trick"] = "on" if self.options.logic_ac_lever_jump_trick.value else "off"
        settings_dict["logic_ac_chest_after_whip_hooks_jump"] = "on" if self.options.logic_ac_chest_after_whip_hooks_jump.value else "off"
        settings_dict["logic_sandship_jump_to_stern"] = "on" if self.options.logic_sandship_jump_to_stern.value else "off"
        settings_dict["logic_sandship_itemless_spume"] = "on" if self.options.logic_sandship_itemless_spume.value else "off"
        settings_dict["logic_sandship_no_combination_hint"] = "on" if self.options.logic_sandship_no_combination_hint.value else "off"
        settings_dict["logic_fs_pillar_jump"] = "on" if self.options.logic_fs_pillar_jump.value else "off"
        settings_dict["logic_fs_practice_sword_ghirahim_2"] = "on" if self.options.logic_fs_practice_sword_ghirahim_2.value else "off"
        settings_dict["logic_present_bow_switches"] = "on" if self.options.logic_present_bow_switches.value else "off"
        settings_dict["logic_skykeep_vineclip"] = "on" if self.options.logic_skykeep_vineclip.value else "off"
        
        # Cosmetics
        settings_dict["tunic_swap"] = "on" if self.options.tunic_swap.value else "off"
        settings_dict["lightning_skyward_strike"] = "on" if self.options.lightning_skyward_strike.value else "off"
        settings_dict["starry_skies"] = "on" if self.options.starry_skies.value else "off"
        settings_dict["remove_enemy_music"] = "on" if self.options.remove_enemy_music.value else "off"
        
        # Extra Starting Inventory
        settings_dict["starting_hearts"] = str(self.options.starting_hearts.value)
        settings_dict["start_with_all_bugs"] = "on" if self.options.start_with_all_bugs.value else "off"
        settings_dict["start_with_all_treasures"] = "on" if self.options.start_with_all_treasures.value else "off"
        
        # Difficulty
        # damage_multiplier is a raw integer (0=invincible, 1=normal, 2=double, 4=quadruple, 80=OHKO)
        damage_map = {0: "0", 1: "1", 2: "2", 3: "4", 4: "80"}
        settings_dict["damage_multiplier"] = damage_map[self.options.damage_multiplier.value]
        settings_dict["spawn_hearts"] = "on"

        # === Cheat overrides ===
        # Infinite Health: force damage_multiplier to 0 (invincible)
        # The client also writes max health each tick as a safety net.
        if getattr(self.options, "cheat_infinite_health", None) and self.options.cheat_infinite_health.value:
            settings_dict["damage_multiplier"] = "0"
            print("[Cheats] Infinite Health enabled - damage_multiplier forced to 0 (invincible)")

        # Infinite Bugs: force start_with_all_bugs on (gives 99 at generation)
        if getattr(self.options, "cheat_infinite_bugs", None) and self.options.cheat_infinite_bugs.value:
            settings_dict["start_with_all_bugs"] = "on"
            print("[Cheats] Infinite Bugs enabled - start_with_all_bugs forced to 'on'")

        # Infinite Materials: force start_with_all_treasures on (gives 99 at generation)
        if getattr(self.options, "cheat_infinite_materials", None) and self.options.cheat_infinite_materials.value:
            settings_dict["start_with_all_treasures"] = "on"
            print("[Cheats] Infinite Materials enabled - start_with_all_treasures forced to 'on'")

        # Starting Inventory
        settings_dict["starting_tablets"] = self.options.starting_tablets.value
        settings_dict["starting_sword"] = self.options.starting_sword.value
        settings_dict["random_starting_statues"] = "on" if self.options.random_starting_statues.value else "off"
        
        spawn_map = {0: "vanilla", 1: "anywhere"}
        settings_dict["random_starting_spawn"] = spawn_map[self.options.random_starting_spawn.value]
        
        settings_dict["limit_starting_spawn"] = "on" if self.options.limit_starting_spawn.value else "off"
        settings_dict["random_starting_item_count"] = str(self.options.random_starting_item_count.value)


        custom_items_value = self.options.custom_starting_items.value
        if isinstance(custom_items_value, dict):
            settings_dict["custom_starting_items"] = custom_items_value
        else:
            print(f"[__init__.py] WARNING: custom_starting_items must be a dictionary, got {type(custom_items_value)}")
            settings_dict["custom_starting_items"] = {}
        
        # Dungeon Settings
        settings_dict["dungeons_include_sky_keep"] = "on" if self.options.dungeons_include_sky_keep.value else "off"
        settings_dict["empty_unrequired_dungeons"] = "on" if self.options.empty_unrequired_dungeons.value else "off"
        
        lanayru_caves_map = {0: "vanilla", 1: "overworld", 2: "anywhere", 3: "removed"}
        settings_dict["lanayru_caves_keys"] = lanayru_caves_map[self.options.lanayru_caves_keys.value]
        
        # Hints (disabled - Archipelago uses its own)
        settings_dict["path_hints"] = "0"
        settings_dict["barren_hints"] = "0"
        settings_dict["location_hints"] = "0"
        settings_dict["item_hints"] = "0"
        settings_dict["song_hints"] = "off"
        settings_dict["impa_sot_hint"] = "off"
        
        # Configuration
        settings_dict["extract_path"] = self.options.extract_path.value or str(get_default_sshd_extract_path())
        settings_dict["setting_string"] = self.options.setting_string.value or ""
        
        return settings_dict

    
    def _build_custom_flag_mapping(self) -> dict:
        """
        Build a mapping from custom flag IDs to location codes.
        
        ALL locations need custom flags because any location could contain
        an Archipelago item for another player's world.
        
        Custom flags are assigned from the HIGH end of the pool (1015, 1014, ...)
        to avoid collisions with the sshd-rando patcher, which assigns non-AP
        locations from the LOW end (0, 1, 2, ...).
        
        Returns:
            Dict[int, int]: custom_flag_id -> location_code (Archipelago)
        """
        from .Locations import LOCATION_TABLE
        
        # Generate the same custom flag list as sshd-rando
        # Excludes flags where the lower 7 bits are all 1s (0x7F)
        # IMPORTANT: Do NOT reverse - pop() from the end gives high IDs (1015, 1014, ...)
        # The sshd-rando patcher assigns from the low end (0, 1, 2, ...) for non-AP locations,
        # so AP must use the high end to avoid flag ID collisions.
        custom_flags = [i for i in range(1024) if (i & 0x7F) != 0x7F]
        
        custom_flag_to_location = {}
        
        # Get ALL locations - every location needs a custom flag for Archipelago
        all_locations = []
        for location in self.multiworld.get_locations(self.player):
            if location.address is not None and location.name in LOCATION_TABLE:
                all_locations.append(location)
        
        # Sort locations consistently (by location code) to ensure deterministic assignment
        all_locations.sort(key=lambda loc: loc.address)
        
        # Assign custom flags sequentially to ALL locations
        for location in all_locations:
            if custom_flags:
                custom_flag_id = custom_flags.pop()
                custom_flag_to_location[custom_flag_id] = location.address
            else:
                print(f"[__init__.py] ERROR: Ran out of custom flags! Location {location.name} could not be assigned.")
        
        print(f"[__init__.py] Built custom flag mapping with {len(custom_flag_to_location)} flags for {len(all_locations)} locations")
        return custom_flag_to_location

    
    def _build_multiworld_item_mapping(self) -> dict:
        """
        Build a mapping from SSHD location names to Archipelago item names.
        
        Cross-world items (from other players' games) are replaced with Archipelago Item.
        PROTECTED LOCATIONS: Some critical locations should never be replaced with cross-world items.
        
        Returns:
            Dict[sshd_location_name: str] = ap_item_name: str
        """
        from .Locations import LOCATION_TABLE
        from .Items import ITEM_TABLE
        
        # Locations that should NEVER be replaced with cross-world items
        # These are critical for game progression or story
        PROTECTED_LOCATIONS = set()
        
        location_item_mapping = {}
        unmapped_locations = []
        cross_world_count = 0
        protected_count = 0
        
        # Iterate through all locations in the multiworld for this player
        for location in self.multiworld.get_locations(self.player):
            if location.address is None:
                # Location not relevant to SSHD (e.g., event location)
                continue
            
            # Find the SSHD location name from our LOCATION_TABLE
            # The location.name in Archipelago should match an SSHD location name
            if location.name in LOCATION_TABLE:
                sshd_location = LOCATION_TABLE[location.name]
                
                # Get the item that should be at this location
                if location.item:
                    ap_item_name = location.item.name
                    
                    # Check if this is a SSHD item for THIS player or a cross-world item
                    # We must check the player too, because another game may have
                    # an item with the same name (e.g. "Heart Container", "Progressive Sword").
                    if ap_item_name in ITEM_TABLE and location.item.player == self.player:
                        # SSHD item belonging to this player - use it directly
                        location_item_mapping[location.name] = ap_item_name
                    elif location.name in PROTECTED_LOCATIONS:
                        # Protected location - keep the SSHD item instead of replacing
                        # Get the original vanilla item for this location
                        location_item_mapping[location.name] = ap_item_name
                        print(f"[__init__.py] PROTECTED: '{ap_item_name}' at {location.name} (not replaced)")
                        protected_count += 1
                    else:
                        # Cross-world item - replace with Archipelago Item
                        location_item_mapping[location.name] = "Archipelago Item"
                        print(f"[__init__.py] Note: Cross-world item '{ap_item_name}' at {location.name} -> Archipelago Item")
                        cross_world_count += 1
                else:
                    # Location has no item - skip
                    unmapped_locations.append(location.name)
            else:
                # Location name not found in SSHD table
                unmapped_locations.append(location.name)
        
        if unmapped_locations:
            print(f"[__init__.py] Warning: {len(unmapped_locations)} locations not found in SSHD location table")
            if len(unmapped_locations) <= 5:
                for loc in unmapped_locations:
                    print(f"  - {loc}")
        
        print(f"[__init__.py] Built mapping with {len(location_item_mapping)} locations ({cross_world_count} cross-world, {protected_count} protected)")
        return location_item_mapping

    
    def _patch_archipelago_logos(self, output_dir: Path) -> None:
        """
        Patch the title and credits logos with Archipelago branding.
        
        This is called after sshd-rando patches are generated to replace
        the randomizer logo with Archipelago's custom logo.
        
        Args:
            output_dir: The romfs output directory (already includes 'romfs' in path)
        """
        try:
            # Get paths
            assets_path = Path(__file__).parent / "assets"
            # output_dir is already the romfs directory, don't add another "romfs"
            romfs_output = output_dir
            
            # Get source arc files from sshd-rando extract
            from filepathconstants import ROMFS_EXTRACT_PATH
            title2d_source = ROMFS_EXTRACT_PATH / "Layout" / "Title2D.arc"
            endroll_source = ROMFS_EXTRACT_PATH / "Layout" / "EndRoll.arc"
            
            # Call the patching function
            patch_archipelago_logo(romfs_output, assets_path, title2d_source, endroll_source)
            
        except Exception as e:
            print(f"Warning: Could not patch Archipelago logos: {e}")
            # Don't raise - logo patching is optional
