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
from base64 import b64encode
from copy import deepcopy
from dataclasses import fields
from pathlib import Path
from typing import Any, ClassVar

from BaseClasses import Region, Location, Item, Tutorial, ItemClassification as IC
from Utils import Version
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
from .Options import SSHDOptions
from .Rules import set_rules
from .rando.ArcPatcher import patch_archipelago_logo

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
if SSHD_RANDO_PATH.exists():
    sys.path.insert(0, str(SSHD_RANDO_PATH))

# Version information
AP_VERSION = [0, 6, 5]
WORLD_VERSION = [0, 7, 0]  # Version [BETA] 0.7.0 for SSHD
RANDO_VERSION = [0, 1, 0]


def run_client() -> None:
    """
    Launch the Skyward Sword HD client.
    """
    print("Running SSHD Client")
    from .SSHDClient import main

    launch_subprocess(main, name="SSHDClient")


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
        
        # Connect regions based on REGION_CONNECTIONS
        for source_name, connections in REGION_CONNECTIONS.items():
            if source_name in regions_dict:
                source_region = regions_dict[source_name]
                for dest_name, rule_name in connections:
                    if dest_name in regions_dict:
                        source_region.connect(regions_dict[dest_name], rule_name or f"{source_name} -> {dest_name}")
    
    def create_item(self, name: str) -> Item:
        """Create an item by name."""
        data = ITEM_TABLE[name]
        return Item(name, data.classification, data.code, self.player)
    
    def create_items(self) -> None:
        """Create all items for the world."""
        # Count total locations (excluding events)
        total_locations = len([loc for loc in self.multiworld.get_locations(self.player) if not loc.event])
        
        # Add all progression and useful items first
        item_pool = []
        for name, data in ITEM_TABLE.items():
            if data.classification in (IC.progression, IC.useful):
                item_pool.append(self.create_item(name))
        
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
            
            if SSHD_RANDO_PATH.exists():
                try:
                    self._generate_sshd_patches(temp_dir, patch_data)
                    
                    # Check if patches were created
                    potential_romfs = temp_dir / "romfs"
                    potential_exefs = temp_dir / "exefs"
                    
                    if potential_romfs.exists():
                        romfs_path = potential_romfs
                    if potential_exefs.exists():
                        exefs_path = potential_exefs
                    
                    # Patch logos with Archipelago branding
                    self._patch_archipelago_logos(temp_dir)
                        
                except Exception as e:
                    print(f"Warning: Could not generate sshd-rando patches: {e}")
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
                
                # Write patch data
                zip_file.writestr("patch_data.json", json.dumps(patch_data, indent=2))
                
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
    
    def _generate_sshd_patches(self, output_dir: Path, patch_data: dict) -> None:
        """
        Generate sshd-rando patches using the AllPatchHandler.
        
        This creates the romfs/exefs mod files that Ryujinx will load.
        """
        try:
            # Import sshd-rando modules
            from logic.world import World as SSHDWorld
            from logic.config import Config
            from patches.allpatchhandler import AllPatchHandler
            
            # Create a minimal sshd-rando World object
            sshd_world = SSHDWorld(0)
            
            # Set up config
            config = Config()
            config.output_dir = output_dir
            sshd_world.config = config
            
            # Map ALL Archipelago options to sshd-rando settings
            
            # Completion Requirements
            sshd_world.setting_map.set_setting("required_dungeon_count", 
                                                self.options.required_dungeon_count.value)
            sshd_world.setting_map.set_setting("triforce_required", 
                                                self.options.triforce_required.value)
            sshd_world.setting_map.set_setting("triforce_shuffle", 
                                                self.options.triforce_shuffle.value)
            sshd_world.setting_map.set_setting("gate_of_time_sword_requirement",
                                                self.options.gate_of_time_sword_requirement.value)
            sshd_world.setting_map.set_setting("gate_of_time_dungeon_requirements",
                                                self.options.gate_of_time_dungeon_requirements.value)
            sshd_world.setting_map.set_setting("imp2_skip", 
                                                self.options.imp2_skip.value)
            sshd_world.setting_map.set_setting("skip_horde", 
                                                self.options.skip_horde.value)
            sshd_world.setting_map.set_setting("skip_ghirahim3", 
                                                self.options.skip_ghirahim3.value)
            
            # Randomization Settings
            sshd_world.setting_map.set_setting("randomize_entrances", 
                                                self.options.randomize_entrances.value)
            sshd_world.setting_map.set_setting("randomize_dungeons",
                                                self.options.randomize_dungeons.value)
            sshd_world.setting_map.set_setting("randomize_trials",
                                                self.options.randomize_trials.value)
            sshd_world.setting_map.set_setting("music_randomization",
                                                self.options.music_randomization.value)
            sshd_world.setting_map.set_setting("cutoff_game_over_music",
                                                self.options.cutoff_game_over_music.value)
            
            # Starting Inventory
            sshd_world.setting_map.set_setting("random_starting_tablet_count",
                                                self.options.starting_tablets.value)
            sshd_world.setting_map.set_setting("starting_sword",
                                                self.options.starting_sword.value)

            
            # Quality of Life
            sshd_world.setting_map.set_setting("open_lake_floria_gate",
                                                self.options.open_lake_floria_gate.value)
            sshd_world.setting_map.set_setting("open_thunderhead",
                                                self.options.open_thunderhead.value)
            sshd_world.setting_map.set_setting("fast_bird_statues",
                                                self.options.fast_bird_statues.value)
            
            # Difficulty
            sshd_world.setting_map.set_setting("no_spoiler_log",
                                                self.options.no_spoiler_log.value)
            sshd_world.setting_map.set_setting("empty_unreachable_locations",
                                                self.options.empty_unreachable_locations.value)
            sshd_world.setting_map.set_setting("damage_multiplier",
                                                self.options.damage_multiplier.value)
            
            # Item Pool
            sshd_world.setting_map.set_setting("add_junk_items",
                                                self.options.add_junk_items.value)
            sshd_world.setting_map.set_setting("junk_item_rate",
                                                self.options.junk_item_rate.value)
            sshd_world.setting_map.set_setting("progressive_items",
                                                self.options.progressive_items.value)
            
            # Extract Path Configuration
            extract_path = self.options.extract_path
            if not extract_path:
                # Use platform-specific default
                try:
                    from platform_utils import get_default_sshd_extract_path
                    extract_path = str(get_default_sshd_extract_path())
                except ImportError:
                    extract_path = "C:\\ProgramData\\Archipelago\\sshd_extract"
            
            # Verify extract exists BEFORE attempting patch generation
            from pathlib import Path
            extract_path_obj = Path(extract_path)
            if not extract_path_obj.exists():
                raise FileNotFoundError(
                    f"SSHD extract path does not exist: {extract_path}\n"
                    f"Please extract your SSHD ROM files to this location before generating patches.\n"
                    f"You can set a custom path in your YAML using 'extract_path' option."
                )
            
            # Set extract path in config
            import os
            os.environ['ROMFS_EXTRACT_PATH'] = extract_path
            from filepathconstants import ROMFS_EXTRACT_PATH
            
            # Build the location table (required for patching)
            from logic.location_table import build_location_table
            sshd_world.location_table = build_location_table(sshd_world)
            
            # Assign items to locations based on Archipelago's assignments
            for location in self.multiworld.get_locations(self.player):
                if location.address is not None and location.item:
                    location_name = location.name
                    item_name = location.item.name
                    item_player = location.item.player
                    is_local = (item_player == self.player)
                    
                    # Find matching location in sshd-rando
                    if location_name in sshd_world.location_table:
                        sshd_location = sshd_world.location_table[location_name]
                        
                        # Handle item assignment
                        if is_local and item_name in sshd_world.item_table:
                            # Local SSHD item - use actual item
                            sshd_item = sshd_world.item_table[item_name]
                        else:
                            # Non-local item or multiworld item from another game
                            # Replace with Cawlin's Letter model (visual only)
                            # The client will handle giving the correct item via memory
                            if "Cawlin's Letter" in sshd_world.item_table:
                                sshd_item = sshd_world.item_table["Cawlin's Letter"]
                            else:
                                # Fallback: create placeholder
                                from logic.item import Item as SSHDItem
                                sshd_item = SSHDItem("Archipelago Item", sshd_world)
                            
                            # Store metadata for client to know what to give
                            sshd_item.ap_item_id = location.item.code
                            sshd_item.ap_item_name = item_name
                            sshd_item.ap_player = item_player
                        
                        sshd_location.current_item = sshd_item
            
            # Generate patches using AllPatchHandler
            patch_handler = AllPatchHandler(sshd_world)
            patch_handler.do_all_patches()
            
            print("Successfully generated sshd-rando patches")
            
        except ImportError as e:
            print(f"Warning: Could not import sshd-rando: {e}")
            raise
        except Exception as e:
            print(f"Error generating sshd-rando patches: {e}")
            raise
    
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
            
            # Check if the user wants the alternative logo
            use_alt_logo = bool(self.options.use_alternative_logo.value)
            
            # Call the patching function
            patch_archipelago_logo(romfs_output, assets_path, title2d_source, endroll_source, use_alt_logo)
            
        except Exception as e:
            print(f"Warning: Could not patch Archipelago logos: {e}")
            # Don't raise - logo patching is optional
