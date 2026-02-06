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
from .Rules import set_rules
from .rando.ArcPatcher import patch_archipelago_logo
from .SSHDRWrapper import generate_sshd_rando_mod, extract_location_item_mapping

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
    apworld_path = Path(sys.modules[__name__].__loader__.archive)
    
    # Create temp directory for extraction
    SSHD_RANDO_TEMP_DIR = tempfile.mkdtemp(prefix="sshd_rando_")
    temp_backend_path = Path(SSHD_RANDO_TEMP_DIR) / "sshd-rando-backend"
    
    # Extract sshd-rando-backend from the zip
    with zipfile.ZipFile(apworld_path, 'r') as zip_file:
        # Extract all files from sshd/sshd-rando-backend/
        for file_info in zip_file.filelist:
            if file_info.filename.startswith('sshd/sshd-rando-backend/'):
                # Remove 'sshd/' prefix to get relative path within sshd-rando-backend
                relative_path = file_info.filename[5:]  # Remove 'sshd/'
                if relative_path == 'sshd-rando-backend/' or relative_path == 'sshd-rando-backend':
                    continue  # Skip the directory itself
                
                target_path = Path(SSHD_RANDO_TEMP_DIR) / relative_path
                
                # Create parent directories
                target_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Extract the file
                if not file_info.is_dir():
                    with zip_file.open(file_info.filename) as source:
                        with open(target_path, 'wb') as target:
                            target.write(source.read())
    
    # Add temp directory to path
    sys.path.insert(0, str(temp_backend_path))
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
WORLD_VERSION = [0, 1, 0]  # Starting at 0.1.0 for SSHD
RANDO_VERSION = [0, 1, 0]


def run_client(*args: str) -> None:
    """
    Launch the Skyward Sword HD client.
    Receives args including the patch file path when launched from the GUI.
    """
    import asyncio
    import subprocess
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
    
    # If launched WITH a patch file, run in existing event loop
    from .SSHDClient import main
    try:
        loop = asyncio.get_running_loop()
        asyncio.create_task(main(list(args)))
    except RuntimeError:
        asyncio.run(main(list(args)))


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
        ["Your Username Here"]
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
    
    def create_regions(self) -> None:
        """Create all regions for the world."""
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
        
        # Add all locations to their respective regions
        for name, data in LOCATION_TABLE.items():
            if data.code is not None:
                region = regions_dict.get(data.region)
                if region:
                    location = Location(
                        self.player,
                        name,
                        data.code,
                        region
                    )
                    region.locations.append(location)

        # Lock victory location to the Game Beatable event item
        try:
            victory_location = self.multiworld.get_location("Hylia's Realm - Defeat Demise", self.player)
            victory_location.place_locked_item(self.create_item("Game Beatable"))
            victory_location.event = True
            victory_location.locked = True
            victory_location.progress_type = LocationProgressType.EXCLUDED
        except Exception as e:
            print(f"[__init__.py] Warning: Could not lock victory location: {e}")
        
        # Connect regions based on REGION_CONNECTIONS
        for source_name, connections in REGION_CONNECTIONS.items():
            if source_name in regions_dict:
                source_region = regions_dict[source_name]
                for dest_name, rule_name in connections:
                    if dest_name in regions_dict:
                        source_region.connect(regions_dict[dest_name], None, f"{source_name} -> {dest_name}")
    
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
    
    def create_item(self, name: str) -> Item:
        """Create an item by name."""
        data = ITEM_TABLE[name]
        return Item(name, data.classification, data.code, self.player)
    
    def create_items(self) -> None:
        """Create all items for the world."""
        # Lock Fledge locations to rupees so they can be safely skipped
        fledge_skip_locations = {
            "Knight Academy - Fledge's Gift",
            "Knight Academy - Help Fledge Workout",
        }
        locked_locations = 0
        for loc in self.multiworld.get_locations(self.player):
            if loc.address is not None and loc.name in fledge_skip_locations:
                loc.place_locked_item(self.create_item("Green Rupee"))
                loc.progress_type = LocationProgressType.EXCLUDED
                locked_locations += 1
        
        # Count total locations (excluding events and locked locations)
        total_locations = len([
            loc for loc in self.multiworld.get_locations(self.player)
            if loc.address is not None and not getattr(loc, "event", False)
        ]) - locked_locations
        
        # Get starting items from sshd-rando world (if available)
        # These items should NOT be added to the item pool since they're given at start
        starting_items = getattr(self, '_sshd_starting_items', {})
        
        # Grant starting items as precollected items to the player
        if starting_items:
            print(f"[__init__.py] Granting starting items as precollected:")
            for item_name, count in starting_items.items():
                if item_name in ITEM_TABLE:
                    for _ in range(count):
                        item = self.create_item(item_name)
                        self.multiworld.push_precollected(item)
                    print(f"  {item_name} x{count}")
                else:
                    print(f"  [WARNING] '{item_name}' not found in ITEM_TABLE - skipped")
        
        # Add all progression and useful items first (but not traps)
        item_pool = []
        for name, data in ITEM_TABLE.items():
            if name == "Game Beatable":
                continue
            if data.classification in (IC.progression, IC.useful):
                # Skip items that are in the starting inventory
                if name in starting_items and starting_items[name] > 0:
                    continue
                item_pool.append(self.create_item(name))
        
        # Add trap items from the option
        trap_count = 0
        for trap_name, count in self.options.trap_items.value.items():
            for _ in range(count):
                item_pool.append(self.create_item(trap_name))
                trap_count += 1
        
        # Fill remaining slots with filler items (rupees, hearts, etc.)
        filler_items = [name for name, data in ITEM_TABLE.items() if data.classification == IC.filler]
        
        while len(item_pool) < total_locations:
            # Cycle through filler items
            filler_name = filler_items[len(item_pool) % len(filler_items)]
            item_pool.append(self.create_item(filler_name))
        
        # Add items to the multiworld pool
        self.multiworld.itempool += item_pool
    
    def set_rules(self) -> None:
        """Set access rules for regions and locations."""
        set_rules(self)
    
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
        
        # Build custom flag to location mapping for location detection
        # This replicates sshd-rando's custom flag assignment logic
        custom_flag_to_location = self._build_custom_flag_mapping()
        slot_data["custom_flag_to_location"] = custom_flag_to_location
        
        # Build reverse mapping: location -> custom_flag for item giving
        # This lets the client set custom flags to trigger vanilla item pickups
        location_to_custom_flag = {loc: flag for flag, loc in custom_flag_to_location.items()}
        slot_data["location_to_custom_flag"] = location_to_custom_flag
        
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
            
            # Apply patches with the overlaid items
            # This generates the romfs/exefs with Archipelago items in them
            print("[__init__.py] Applying patches with multiworld items...")
            try:
                # Import from sshd-rando via sys.path
                import sys
                from patches.allpatchhandler import AllPatchHandler
                patch_handler = AllPatchHandler(world)
                patch_handler.do_all_patches()
                print("[__init__.py] ✓ Patches applied successfully")
                
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
    
    def _collect_archipelago_settings(self) -> dict:
        """
        Collect Archipelago options as a dictionary for sshd-rando wrapper.
        
        Maps Archipelago option values to sshd-rando setting names and values.
        """
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
        key_mode_map = {0: "own_dungeon", 1: "any_dungeon", 2: "anywhere", 3: "keysy"}
        settings_dict["small_keys"] = key_mode_map[self.options.small_key_shuffle.value]
        settings_dict["boss_keys"] = key_mode_map[self.options.boss_key_shuffle.value]
        
        map_mode_map = {0: "vanilla", 1: "own_dungeon_restricted", 2: "anywhere"}
        settings_dict["map_mode"] = map_mode_map[self.options.map_shuffle.value]
        
        # Entrance Randomization
        settings_dict["randomize_dungeon_entrances"] = "on" if self.options.randomize_dungeon_entrances.value else "off"
        settings_dict["randomize_trial_gate_entrances"] = "on" if self.options.randomize_trial_gate_entrances.value else "off"
        settings_dict["randomize_door_entrances"] = "on" if self.options.randomize_door_entrances.value else "off"
        settings_dict["decouple_double_doors"] = "on" if self.options.decouple_double_doors.value else "off"
        settings_dict["randomize_interior_entrances"] = "on" if self.options.randomize_interior_entrances.value else "off"
        settings_dict["randomize_overworld_entrances"] = "on" if self.options.randomize_overworld_entrances.value else "off"
        settings_dict["decouple_entrances"] = "on" if self.options.decouple_entrances.value else "off"
        settings_dict["randomize_skykeep_layout"] = "on" if self.options.randomize_skykeep_layout.value else "off"
        
        # Music & Audio
        music_map = {0: "vanilla", 1: "shuffle_music", 2: "shuffle_music_limit_vanilla"}
        settings_dict["randomize_music"] = music_map.get(self.options.music_randomization.value, "vanilla")
        settings_dict["cutoff_game_over_music"] = "on" if self.options.cutoff_game_over_music.value else "off"
        
        # Advanced Randomization
        settings_dict["enable_back_in_time"] = "on" if self.options.enable_back_in_time.value else "off"
        settings_dict["underground_rupee_shuffle"] = "on" if self.options.underground_rupee_shuffle.value else "off"
        settings_dict["beedle_shop_shuffle"] = "on" if self.options.beedle_shop_shuffle.value else "off"
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
        
        # Quality of Life
        settings_dict["open_lake_floria"] = "open" if self.options.open_lake_floria.value else "vanilla"
        settings_dict["open_thunderhead"] = "on" if self.options.open_thunderhead.value else "off"
        settings_dict["open_earth_temple"] = "on" if self.options.open_earth_temple.value else "off"
        settings_dict["open_lmf"] = "on" if self.options.open_lmf.value else "off"
        settings_dict["open_batreaux_shed"] = "on" if self.options.open_batreaux_shed.value else "off"
        settings_dict["skip_harp_playing"] = "on" if self.options.skip_harp_playing.value else "off"
        settings_dict["skip_misc_small_cutscenes"] = "on" if self.options.skip_misc_cutscenes.value else "off"
        
        # Difficulty
        damage_map = {0: "half", 1: "normal", 2: "double", 3: "quadruple", 4: "ohko"}
        settings_dict["damage_multiplier"] = damage_map[self.options.damage_multiplier.value]
        settings_dict["spawn_hearts"] = "on"

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
        
        lanayru_caves_map = {0: "vanilla", 1: "removed"}
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
        
        This replicates sshd-rando's custom flag assignment logic.
        Custom flags are assigned sequentially (in reverse order) to locations
        with the "Custom Flag" type.
        
        Returns:
            Dict[int, int]: custom_flag_id -> location_code (Archipelago)
        """
        from .Locations import LOCATION_TABLE
        
        # Generate the same custom flag list as sshd-rando
        # Excludes flags where the lower 7 bits are all 1s (0x7F)
        custom_flags = [i for i in range(1024) if (i & 0x7F) != 0x7F]
        custom_flags.reverse()  # Assign from highest to lowest
        
        custom_flag_to_location = {}
        
        # Get all locations that use custom flags
        custom_flag_locations = []
        for location in self.multiworld.get_locations(self.player):
            if location.address is not None and location.name in LOCATION_TABLE:
                loc_data = LOCATION_TABLE[location.name]
                # Check if this location has the "Custom Flag" type
                # loc_data is a NamedTuple with a 'types' field containing a list
                if "Custom Flag" in loc_data.types:
                    custom_flag_locations.append(location)
        
        # Sort locations consistently (by location code) to ensure deterministic assignment
        custom_flag_locations.sort(key=lambda loc: loc.address)
        
        # Assign custom flags sequentially
        for location in custom_flag_locations:
            if custom_flags:
                custom_flag_id = custom_flags.pop()
                custom_flag_to_location[custom_flag_id] = location.address
                print(f"[__init__.py] Assigned custom flag {custom_flag_id} to location {location.name} ({location.address})")
        
        print(f"[__init__.py] Built custom flag mapping with {len(custom_flag_to_location)} flags")
        return custom_flag_to_location

    
    def _build_multiworld_item_mapping(self) -> dict:
        """
        Build a mapping from SSHD location names to Archipelago item names.
        
        Cross-world items (from other players' games) are replaced with Cawlin's Letter.
        PROTECTED LOCATIONS: Some critical locations should never be replaced with cross-world items.
        
        Returns:
            Dict[sshd_location_name: str] = ap_item_name: str
        """
        from .Locations import LOCATION_TABLE
        from .Items import ITEM_TABLE
        
        # Locations that should NEVER be replaced with cross-world items
        # These are critical for game progression or story
        # Note: Fledge's Gift is NOT protected because Progressive Pouch can be a starting item
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
                    
                    # Check if this is a SSHD item or a cross-world item
                    if ap_item_name in ITEM_TABLE:
                        # SSHD item - use it directly
                        location_item_mapping[location.name] = ap_item_name
                    elif location.name in PROTECTED_LOCATIONS:
                        # Protected location - keep the SSHD item instead of replacing
                        # Get the original vanilla item for this location
                        location_item_mapping[location.name] = ap_item_name
                        print(f"[__init__.py] PROTECTED: '{ap_item_name}' at {location.name} (not replaced)")
                        protected_count += 1
                    else:
                        # Cross-world item - replace with Cawlin's Letter
                        location_item_mapping[location.name] = "Cawlin's Letter"
                        print(f"[__init__.py] Note: Cross-world item '{ap_item_name}' at {location.name} -> Cawlin's Letter")
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
        """
        try:
            # Get paths
            assets_path = Path(__file__).parent / "assets"
            romfs_output = output_dir / "romfs"
            
            # Get source arc files from sshd-rando extract
            from filepathconstants import ROMFS_EXTRACT_PATH
            title2d_source = ROMFS_EXTRACT_PATH / "Layout" / "Title2D.arc"
            endroll_source = ROMFS_EXTRACT_PATH / "Layout" / "EndRoll.arc"
            
            # Call the patching function
            patch_archipelago_logo(romfs_output, assets_path, title2d_source, endroll_source)
            
        except Exception as e:
            print(f"Warning: Could not patch Archipelago logos: {e}")
            # Don't raise - logo patching is optional
