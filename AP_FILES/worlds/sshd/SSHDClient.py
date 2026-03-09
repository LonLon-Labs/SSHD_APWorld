"""
Skyward Sword HD Client for Archipelago with Ryujinx support.

This client connects to Ryujinx via direct memory access and communicates
with the Archipelago server to enable multiworld randomizer support.
"""

import asyncio
import json
import logging
import os
import struct
import sys
import time
from typing import Optional, Set, Dict, Any

# Add parent directory to path to find Archipelago modules when running as exe
if getattr(sys, 'frozen', False):
    # Running as compiled exe
    bundle_dir = sys._MEIPASS
    # Add Archipelago install directory to path
    archipelago_dir = os.path.join(os.environ.get('PROGRAMDATA', 'C:\\ProgramData'), 'Archipelago')
    if os.path.exists(archipelago_dir):
        sys.path.insert(0, archipelago_dir)
else:
    # Running as script - add Archipelago folder to path
    bundle_dir = os.path.dirname(os.path.abspath(__file__))
    archipelago_parent = os.path.dirname(bundle_dir)
    archipelago_dir = os.path.join(archipelago_parent, 'Archipelago')
    if os.path.exists(archipelago_dir):
        sys.path.insert(0, archipelago_dir)

# Disable ModuleUpdate for exe builds (prevents unnecessary dependency checks)
if getattr(sys, 'frozen', False):
    import sys
    class DummyModuleUpdate:
        @staticmethod
        def update(*args, **kwargs):
            pass
    sys.modules['ModuleUpdate'] = DummyModuleUpdate()

import psutil
from process_memory import ProcessMemory, ProcessMemoryError

try:
    from CommonClient import CommonContext, server_loop, gui_enabled, \
        ClientCommandProcessor, logger, get_base_parser
    from NetUtils import ClientStatus
except ImportError as e:
    print(f"ERROR: Cannot import Archipelago modules. Make sure Archipelago is installed.")
    print(f"Import error: {e}")
    print(f"\nTo fix this:")
    print(f"1. Install Archipelago from https://github.com/ArchipelagoMW/Archipelago/releases")
    print(f"2. Or run this script from within the Archipelago folder")
    input("Press Enter to exit...")
    sys.exit(1)

try:
    from .LocationFlags import LOCATION_FLAG_MAP, FLAG_STORY, FLAG_SCENE, FLAG_SPECIAL
except ImportError:
    # Fallback if running as standalone
    try:
        from LocationFlags import LOCATION_FLAG_MAP, FLAG_STORY, FLAG_SCENE, FLAG_SPECIAL
    except ImportError:
        LOCATION_FLAG_MAP = {}
        FLAG_STORY = "STORY"
        FLAG_SCENE = "SCENE"
        FLAG_SPECIAL = "SPECIAL"

# Import location table for proper location IDs
try:
    from .Locations import LOCATION_TABLE
except ImportError:
    try:
        from Locations import LOCATION_TABLE
    except ImportError:
        LOCATION_TABLE = {}

# Import hint system
try:
    from .Hints import HintSystem
except ImportError:
    try:
        from Hints import HintSystem
    except ImportError:
        HintSystem = None


# Memory signature to find SSHD base address
MEMORY_SIGNATURE = bytes.fromhex("00000000080000004D4F443088BD8101")

# Memory offsets (relative to base address)
# ⚠️ WARNING: These offsets are from Wii version and may NOT work for Switch!
# TODO: Research correct Switch/Ryujinx memory addresses using:
#   - Ryujinx debugger
#   - Cheat Engine
#   - Memory dumps from running game
# The base address finding via signature should work, but these offsets need verification.

# Main pointers
OFFSET_PLAYER = 0x623E680          # Player structure base (WII - NEEDS VERIFICATION)
OFFSET_FILE_MANAGER = 0x6288408    # Save file manager (WII - NEEDS VERIFICATION)
OFFSET_CURRENT_STAGE = 0x2BF98D8   # Current stage info (WII - NEEDS VERIFICATION)
OFFSET_NEXT_STAGE = 0x2BF9904      # Next stage info (WII - NEEDS VERIFICATION)

# Player structure offsets (relative to OFFSET_PLAYER)
OFFSET_POS_X = 0x144               # Player X position
OFFSET_POS_Y = 0x148               # Player Y position
OFFSET_POS_Z = 0x14C               # Player Z position
OFFSET_VELOCITY_X = 0x1E8          # Velocity X
OFFSET_VELOCITY_Y = 0x1EC          # Velocity Y
OFFSET_VELOCITY_Z = 0x1F0          # Velocity Z
OFFSET_ACTION_FLAGS = 0x460        # Action flags
OFFSET_ACTION_FLAGS_MORE = 0x464   # More action flags
OFFSET_B_WHEEL_EQUIPPED = 0x6408   # B-wheel equipped item
OFFSET_CURRENT_HEALTH = 0x5306     # Current hearts (2 bytes)
OFFSET_HEALTH_CAPACITY = 0x5302    # Max hearts (2 bytes)
OFFSET_STAMINA = 0x64D8            # Stamina gauge
OFFSET_STORY_FLAGS = 0x8E4         # Story flags (256 bytes)
OFFSET_SCENE_FLAGS = 0x9E4         # Scene flags within player

# Current Stage Info offsets (relative to OFFSET_CURRENT_STAGE)
OFFSET_STAGE_NAME = 0x0            # Stage name (8 byte string)
OFFSET_STAGE_LAYER = 0x23          # Layer ID
OFFSET_STAGE_ROOM = 0x22           # Room ID
OFFSET_STAGE_ENTRANCE = 0x24       # Entrance ID
OFFSET_STAGE_NIGHT = 0x25          # Night flag

# File Manager / Save File offsets
# File A (main save) = File Manager base + 0x10
OFFSET_FILE_A_FROM_MANAGER = 0x10

# Within File A structure (relative to File A pointer)
OFFSET_FA_STORY_FLAGS = 0x0        # Story flags in save file
OFFSET_FA_SCENE_FLAGS = 0x100      # Scene flags in save file  
OFFSET_FA_INVENTORY = 0x200        # Inventory start (approximate)

# Scene name to scene flag base address mapping (absolute addresses in SSHD memory)
# These are the absolute memory addresses where scene flags are stored
# Scene flags start at 0x805A9F00 and are organized by scene
SCENE_FLAG_ADDRESSES = {
    "Skyloft": 0x805A9F00,              # Skyloft scene flags
    "Sky": 0x805AA000,                  # Sky scene flags
    "Sealed Grounds": 0x805AA100,       # Sealed Grounds
    "Faron Woods": 0x805AA200,          # Faron Woods
    "Lake Floria": 0x805AA300,          # Lake Floria
    "Skyview": 0x805AA400,              # Skyview Temple
    "Eldin Volcano": 0x805AA500,        # Eldin Volcano
    "Earth Temple": 0x805AA600,         # Earth Temple
    "Lanayru Desert": 0x805AA700,       # Lanayru Desert
    "Lanayru Mining Facility": 0x805AA800,  # Lanayru Mining Facility
    "Ancient Cistern": 0x805AA900,      # Ancient Cistern
    "Sandship": 0x805AAA00,             # Sandship
    "Fire Sanctuary": 0x805AAB00,       # Fire Sanctuary
    "Sky Keep": 0x805AAC00,             # Sky Keep
}

# Story flags base address (absolute)
STORY_FLAGS_BASE = 0x805A9AD0

# Scene flags base address (absolute)
SCENE_FLAGS_BASE = 0x805A9F00


class RyujinxMemoryError(Exception):
    """Exception raised for Ryujinx memory access errors."""
    pass


class RyujinxMemoryReader:
    """
    Class to handle memory reading/writing for Ryujinx emulator.
    
    This provides direct access to SSHD's memory through Ryujinx's process.
    """
    
    def __init__(self):
        self.pm = None  # ProcessMemory instance (cross-platform)
        self.base_address: Optional[int] = None
        self.connected = False
        
    def connect(self) -> bool:
        """
        Connect to the Ryujinx process.
        
        Returns:
            True if successfully connected, False otherwise
        """
        try:
            # Find Ryujinx process (cross-platform)
            ryujinx_process = None
            
            # Process names by OS
            if sys.platform == "win32":
                process_names = ["Ryujinx.exe"]
            elif sys.platform == "linux":
                process_names = ["Ryujinx"]
            elif sys.platform == "darwin":  # macOS
                process_names = ["Ryujinx"]
            else:
                process_names = ["Ryujinx.exe", "Ryujinx"]  # Try both as fallback
            
            for proc in psutil.process_iter(['name']):
                if proc.info['name'] in process_names:
                    ryujinx_process = proc
                    break
            
            if not ryujinx_process:
                expected_names = " or ".join(f"'{name}'" for name in process_names)
                logger.info(f"Ryujinx process ({expected_names}) not found. Please start Ryujinx.")
                return False
            
            # Open process (cross-platform)
            try:
                self.pm = ProcessMemory()
            except ProcessMemoryError as e:
                logger.error(f"Platform not supported for memory access: {e}")
                return False
            self.pm.open_process_from_id(ryujinx_process.pid)
            
            logger.info(f"Connected to Ryujinx (PID: {ryujinx_process.pid})")
            self.connected = True
            return True
            
        except ProcessMemoryError as e:
            logger.error(f"Failed to connect to Ryujinx: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to connect to Ryujinx: {e}")
            return False
    
    def find_base_address(self) -> bool:
        """
        Find the SSHD base address by scanning memory for the signature.
        
        This can take several seconds as it scans the entire process memory.
        
        Returns:
            True if base address found, False otherwise
        """
        if not self.connected or not self.pm:
            logger.error("Not connected to Ryujinx")
            return False
        
        try:
            logger.info("Scanning memory for SSHD signature... (this may take 8-10 seconds)")
            start_time = time.time()
            
            # Scan memory regions
            address = 0x10000
            max_address = 0x7FFFFFFFFFFF
            chunk_size = 0x10000000  # 256 MB chunks
            
            while address < max_address:
                try:
                    # Read a chunk of memory
                    data = self.pm.read_bytes(address, min(chunk_size, max_address - address))
                    
                    # Search for signature
                    offset = data.find(MEMORY_SIGNATURE)
                    if offset != -1:
                        potential_base = address + offset
                        
                        # VALIDATION: Verify this is the correct base
                        try:
                            # Try reading from a known offset to validate
                            test_read = self.pm.read_bytes(potential_base + 0x6288408, 8)  # OFFSET_FILE_MANAGER
                            if test_read:
                                self.base_address = potential_base
                                elapsed = time.time() - start_time
                                logger.info(f"Found and validated SSHD base address: 0x{self.base_address:X} (took {elapsed:.1f}s)")
                                return True
                            else:
                                logger.warning(f"Found signature at 0x{potential_base:X} but validation failed - continuing search...")
                        except Exception:
                            logger.warning(f"Found signature at 0x{potential_base:X} but validation failed - continuing search...")
                            pass
                    
                    address += chunk_size
                    
                except Exception:
                    # Skip inaccessible memory regions
                    address += chunk_size
                    continue
            
            logger.error("Could not find SSHD signature in memory")
            return False
            
        except Exception as e:
            logger.error(f"Error scanning memory: {e}")
            return False
    
    def read_float(self, offset: int) -> Optional[float]:
        """Read a float from memory at base_address + offset."""
        if not self.base_address or not self.pm:
            return None
        try:
            data = self.pm.read_bytes(self.base_address + offset, 4)
            return struct.unpack('<f', data)[0]
        except Exception as e:
            logger.debug(f"Error reading float at 0x{offset:X}: {e}")
            return None
    
    def read_int(self, offset: int) -> Optional[int]:
        """Read a 32-bit integer from memory at base_address + offset."""
        if not self.base_address or not self.pm:
            return None
        try:
            data = self.pm.read_bytes(self.base_address + offset, 4)
            return struct.unpack('<I', data)[0]
        except Exception as e:
            logger.debug(f"Error reading int at 0x{offset:X}: {e}")
            return None
    
    def read_short(self, offset: int) -> Optional[int]:
        """Read a 16-bit integer from memory at base_address + offset."""
        if not self.base_address or not self.pm:
            return None
        try:
            data = self.pm.read_bytes(self.base_address + offset, 2)
            return struct.unpack('<H', data)[0]
        except Exception as e:
            logger.debug(f"Error reading short at 0x{offset:X}: {e}")
            return None
    
    def read_byte(self, offset: int) -> Optional[int]:
        """Read a single byte from memory at base_address + offset."""
        if not self.base_address or not self.pm:
            return None
        try:
            return self.pm.read_uchar(self.base_address + offset)
        except Exception as e:
            logger.debug(f"Error reading byte at 0x{offset:X}: {e}")
            return None
    
    def read_string(self, offset: int, length: int = 32) -> Optional[str]:
        """Read a null-terminated string from memory."""
        if not self.base_address or not self.pm:
            return None
        try:
            data = self.pm.read_bytes(self.base_address + offset, length)
            # Find null terminator
            null_pos = data.find(b'\x00')
            if null_pos != -1:
                data = data[:null_pos]
            return data.decode('utf-8', errors='ignore')
        except Exception as e:
            logger.debug(f"Error reading string at 0x{offset:X}: {e}")
            return None
    
    def read_pointer(self, offset: int) -> Optional[int]:
        """Read a pointer (64-bit address) from memory."""
        if not self.base_address or not self.pm:
            return None
        try:
            data = self.pm.read_bytes(self.base_address + offset, 8)
            return struct.unpack('<Q', data)[0]  # Little-endian 64-bit
        except Exception as e:
            logger.debug(f"Error reading pointer at 0x{offset:X}: {e}")
            return None
    
    def write_float(self, offset: int, value: float) -> bool:
        """Write a float to memory at base_address + offset."""
        if not self.base_address or not self.pm:
            return False
        try:
            data = struct.pack('<f', value)
            self.pm.write_bytes(self.base_address + offset, data, len(data))
            return True
        except Exception as e:
            logger.debug(f"Error writing float at 0x{offset:X}: {e}")
            return False
    
    def write_int(self, offset: int, value: int) -> bool:
        """Write a 32-bit integer to memory at base_address + offset."""
        if not self.base_address or not self.pm:
            return False
        try:
            data = struct.pack('<I', value)
            self.pm.write_bytes(self.base_address + offset, data, len(data))
            return True
        except Exception as e:
            logger.debug(f"Error writing int at 0x{offset:X}: {e}")
            return False
    
    def write_byte(self, offset: int, value: int) -> bool:
        """Write a single byte to memory at base_address + offset."""
        if not self.base_address or not self.pm:
            return False
        try:
            self.pm.write_uchar(self.base_address + offset, value)
            return True
        except Exception as e:
            logger.debug(f"Error writing byte at 0x{offset:X}: {e}")
            return False
    
    def write_short(self, offset: int, value: int) -> bool:
        """Write a 16-bit short to memory at base_address + offset."""
        if not self.base_address or not self.pm:
            return False
        try:
            data = struct.pack('<H', value)
            self.pm.write_bytes(self.base_address + offset, data, len(data))
            return True
        except Exception as e:
            logger.debug(f"Error writing short at 0x{offset:X}: {e}")
            return False


class SSHDClientCommandProcessor(ClientCommandProcessor):
    """Command processor for SSHD-specific commands."""
    
    def __init__(self, ctx: CommonContext):
        super().__init__(ctx)
    
    def _cmd_sshd(self):
        """Show SSHD client status."""
        if isinstance(self.ctx, SSHDContext):
            logger.info(f"Connected to Ryujinx: {self.ctx.memory.connected}")
            if self.ctx.memory.base_address:
                logger.info(f"Base address: 0x{self.ctx.memory.base_address:X}")
            logger.info(f"Locations checked: {len(self.ctx.checked_locations)}")
        else:
            logger.warning("Not connected to SSHD context")
    
    def _cmd_hints(self):
        """Show all received hints."""
        if isinstance(self.ctx, SSHDContext) and self.ctx.hints:
            hints = self.ctx.hints.get_all_hints()
            if hints:
                logger.info(f"\n=== Hints ({len(hints)}) ===")
                for location_id, hint_text in hints:
                    revealed = "[READ]" if self.ctx.hints.is_revealed(location_id) else "[NEW]"
                    logger.info(f"{revealed} {hint_text}")
            else:
                logger.info("No hints received yet.")
        else:
            logger.warning("Hint system not available")


class SSHDContext(CommonContext):
    """
    Main context for SSHD client.
    
    Handles connection to both Archipelago server and Ryujinx emulator.
    """
    
    command_processor = SSHDClientCommandProcessor
    game = "Skyward Sword HD"
    items_handling = 0b111  # Full remote item handling
    
    def __init__(self, server_address: Optional[str], password: Optional[str]):
        super().__init__(server_address, password)
        
        self.memory = RyujinxMemoryReader()
        self.checked_locations: Set[int] = set()
        self.item_queue: list = []  # Items waiting to be given
        
        # Initialize hint system
        self.hints = HintSystem() if HintSystem else None
        
        # Progressive item counters
        self.progressive_counts = {
            "Progressive Sword": 0,
            "Progressive Bow": 0,
            "Progressive Slingshot": 0,
            "Progressive Beetle": 0,
            "Progressive Mitts": 0,
            "Progressive Bug Net": 0,
            "Progressive Wallet": 0,
            "Progressive Pouch": 0,
        }
        
        # Game state tracking
        self.current_stage: Optional[str] = None
        self.last_stage: Optional[str] = None
        self.last_hearts: Optional[int] = None
        self.slot_options: Dict[str, Any] = {}  # Player options from slot data
        
    async def server_auth(self, password_requested: bool = False):
        """Authenticate with the Archipelago server."""
        if password_requested and not self.password:
            await super().server_auth(password_requested)
        await self.get_username()
        await self.send_connect()
    
    async def connection_closed(self):
        """Handle disconnection from server."""
        await super().connection_closed()
        logger.info("Connection to Archipelago server closed")
    
    def on_package(self, cmd: str, args: dict):
        """Handle incoming packages from the server."""
        if cmd == "Connected":
            # Server confirmed connection - validate slot data
            slot_data = args.get("slot_data", {})
            
            # Check world version compatibility
            server_version = slot_data.get("world_version", [0, 0, 0])
            if server_version[0] != 0 or server_version[1] != 7:
                logger.warning(f"World version mismatch! Client expects 0.7.x, server has {server_version}")
                logger.warning("The game may not work correctly. Please update your client or regenerate your seed.")
            
            # Store slot options for reference
            self.slot_options = {}
            for key, value in slot_data.items():
                if key.startswith("option_"):
                    option_name = key[7:]  # Remove "option_" prefix
                    self.slot_options[option_name] = value
            
            logger.info(f"Connected to Archipelago as {self.auth}")
            logger.info(f"Loaded {len(self.slot_options)} player options from slot data")
            
        elif cmd == "ReceivedItems":
            # Received items from other players
            start_index = args.get("index", 0)
            for i, network_item in enumerate(args.get("items", [])):
                item_id = network_item.item
                item_name = self.item_names.get(item_id, f"Unknown Item {item_id}")
                sender_id = network_item.player
                sender_name = self.player_names.get(sender_id, f"Player {sender_id}")
                
                # Add to queue to be given in-game
                self.item_queue.append({
                    "id": item_id,
                    "name": item_name,
                    "player": sender_id,
                    "player_name": sender_name,
                    "index": start_index + i,
                })
                
                # Display prominent notification
                is_own_item = (sender_id == self.slot)
                if is_own_item:
                    logger.info(f"📦 Received YOUR item: {item_name}")
                else:
                    logger.info(f"")
                    logger.info(f"{'='*60}")
                    logger.info(f"  🎁 YOU RECEIVED: {item_name}")
                    logger.info(f"  👤 FROM: {sender_name}")
                    logger.info(f"{'='*60}")
                    logger.info(f"")
        
        elif cmd == "LocationInfo":
            # Information about locations - used for hints
            if self.hints:
                for location_info in args.get("locations", []):
                    location_id = location_info.get("location")
                    item_id = location_info.get("item")
                    player_id = location_info.get("player")
                    
                    # Get names from mappings
                    location_name = self.location_names.get(location_id, f"Location {location_id}")
                    item_name = self.item_names.get(item_id, f"Item {item_id}")
                    player_name = self.player_names.get(player_id, f"Player {player_id}")
                    
                    # Format and store hint
                    is_local = (player_id == self.slot)
                    hint_text = self.hints.format_hint(location_name, item_name, player_name, is_local)
                    self.hints.add_hint(location_id, hint_text)
                    
                    logger.info(f"Received hint: {hint_text}")
    
    def give_item_to_player(self, item_name: str, item_id: int) -> bool:
        """
        Give an item to the player in-game.
        
        This writes directly to the save file structure in memory.
        The game reads from this structure when loading/saving.
        
        Returns True if successful, False if failed.
        """
        if not self.memory.connected or not self.memory.base_address:
            return False
        
        try:
            # Handle progressive items
            if item_name in self.progressive_counts:
                self.progressive_counts[item_name] += 1
                count = self.progressive_counts[item_name]
                
                # Map progressive items to actual items based on count
                actual_item_id = self.get_progressive_item_id(item_name, count)
                
                if actual_item_id is None:
                    logger.warning(f"Could not determine item ID for {item_name} level {count}")
                    return False
                
                logger.info(f"Giving {item_name} level {count} (ID: {actual_item_id})")
                
            else:
                # Non-progressive item - use the item ID from Locations/Items tables
                # These IDs match the sshd-rando item IDs
                actual_item_id = item_id
            
            # Write item to save file memory
            # We write to BOTH player memory (for immediate effect) AND File A (for persistence)
            
            # Method 1: Write to player memory (immediate, not persistent)
            flag_byte_offset = actual_item_id // 8
            flag_bit = actual_item_id % 8
            
            # Read and set player story flag
            current_flag = self.memory.read_byte(OFFSET_PLAYER + OFFSET_STORY_FLAGS + flag_byte_offset)
            if current_flag is not None:
                new_flag = current_flag | (1 << flag_bit)
                success_player = self.memory.write_byte(OFFSET_PLAYER + OFFSET_STORY_FLAGS + flag_byte_offset, new_flag)
            else:
                success_player = False
            
            # Method 2: Write to File A save structure (persistent across save/load)
            # Dereference File Manager pointer to get File A address
            file_manager_ptr = self.memory.read_pointer(OFFSET_FILE_MANAGER)
            if file_manager_ptr:
                # File A is at offset +0x10 from File Manager
                file_a_addr = file_manager_ptr + OFFSET_FILE_A_FROM_MANAGER
                
                # Read File A pointer
                file_a_ptr = self.memory.read_pointer(file_a_addr)
                if file_a_ptr:
                    # Story flags are at the start of File A
                    save_flag_addr = file_a_ptr + OFFSET_FA_STORY_FLAGS + flag_byte_offset
                    
                    # Read current save flag
                    current_save_flag = self.memory.read_byte(save_flag_addr - self.memory.base_address)
                    if current_save_flag is not None:
                        new_save_flag = current_save_flag | (1 << flag_bit)
                        success_save = self.memory.write_byte(save_flag_addr - self.memory.base_address, new_save_flag)
                    else:
                        success_save = False
                else:
                    logger.debug(f"Could not dereference File A pointer")
                    success_save = False
            else:
                logger.debug(f"Could not read File Manager pointer")
                success_save = False
            
            # Report success if either write succeeded
            if success_player or success_save:
                status = []
                if success_player:
                    status.append("player memory")
                if success_save:
                    status.append("save file")
                logger.info(f"Gave item: {item_name} (ID: {actual_item_id}) to {', '.join(status)}")
                return True
            else:
                logger.error(f"Failed to give item {item_name} (both player memory and save file failed)")
                return False
            
        except Exception as e:
            logger.error(f"Error giving item {item_name}: {e}")
            return False
    
    def get_progressive_item_id(self, progressive_name: str, count: int) -> Optional[int]:
        """
        Convert progressive item name + count to actual item ID.
        
        For example: "Progressive Sword" with count 1 = Goddess Sword
                     "Progressive Sword" with count 2 = Goddess Longsword
                     etc.
        """
        # Progressive item mappings (item IDs from sshd-rando)
        progressive_maps = {
            "Progressive Sword": [2773023, 2773031, 2773032, 2773033, 2773034],  # Practice -> Goddess -> Longsword -> White -> Master
            "Progressive Bow": [2773050, 2773120],  # Wooden Bow -> Iron Bow
            "Progressive Slingshot": [2773055, 2773285],  # Slingshot -> Scattershot
            "Progressive Beetle": [2773056, 2773295, 2773296],  # Beetle -> Hook Beetle -> Quick Beetle
            "Progressive Mitts": [2773058, 2773325],  # Digging Mitts -> Mogma Mitts
            "Progressive Bug Net": [2773071, 2773140],  # Bug Net -> Big Bug Net
            "Progressive Wallet": [2773082, 2773672, 2773673, 2773674],  # Medium -> Big -> Giant -> Tycoon
            "Progressive Pouch": [2773084, 2773710, 2773711, 2773712, 2773713],  # 5 levels of pouch
            "Progressive Bomb Bag": [2773051, 2773121, 2773122],  # Regular -> Big -> Bigger
        }
        
        if progressive_name not in progressive_maps:
            return None
        
        item_list = progressive_maps[progressive_name]
        
        # Return the item for this level (1-indexed)
        if 1 <= count <= len(item_list):
            return item_list[count - 1]
        
        # Already at max level, give last level again
        return item_list[-1] if item_list else None
    
    async def ryujinx_connection_task(self):
        """Background task to maintain connection to Ryujinx."""
        while not self.exit_event.is_set():
            try:
                # Try to connect if not connected
                if not self.memory.connected:
                    if self.memory.connect():
                        # Connection successful, find base address
                        if not self.memory.find_base_address():
                            logger.error("Failed to find SSHD in memory. Is the game running?")
                            self.memory.connected = False
                    
                    # Wait before retrying
                    await asyncio.sleep(5)
                    continue
                
                # Connection established, update game state
                await self.update_game_state()
                await asyncio.sleep(0.1)  # Update 10 times per second
                
            except Exception as e:
                logger.error(f"Error in Ryujinx connection task: {e}")
                self.memory.connected = False
                await asyncio.sleep(5)
    
    async def update_game_state(self):
        """
        Read game state from memory and check for location completions.
        
        This is called frequently to monitor game progress.
        """
        if not self.memory.connected or not self.memory.base_address:
            return
        
        try:
            # Verify game is loaded by reading stage name
            stage_name = self.memory.read_string(OFFSET_CURRENT_STAGE + OFFSET_STAGE_NAME, 16)
            if not stage_name or len(stage_name) == 0:
                # Game not loaded yet (title screen, loading, etc.)
                return
            
            # Update current stage
            if stage_name != self.current_stage:
                logger.info(f"Entered stage: {stage_name}")
                self.current_stage = stage_name
            
            # Give queued items to player
            if self.item_queue:
                item_data = self.item_queue[0]
                if self.give_item_to_player(item_data["name"], item_data["id"]):
                    # Successfully gave item
                    player_name = item_data.get("player_name", "another player")
                    is_own_item = (item_data["player"] == self.slot)
                    
                    if not is_own_item:
                        # Show popup-style notification for items from other players
                        logger.info(f"")
                        logger.info(f"✅ ITEM RECEIVED IN-GAME!")
                        logger.info(f"   {item_data['name']} from {player_name}")
                        logger.info(f"")
                    else:
                        logger.info(f"✅ Received your own item: {item_data['name']}")
                    
                    self.item_queue.pop(0)
                else:
                    # Failed to give item, will retry next frame
                    pass
            
            # Check for death (for death link)
            current_health = self.memory.read_short(OFFSET_PLAYER + OFFSET_CURRENT_HEALTH)
            if current_health is not None:
                # Player just died if health went to 0 (from any positive value OR if we had None before)
                if current_health == 0 and (self.last_hearts is None or self.last_hearts > 0):
                    # Player just died
                    if "DeathLink" in self.tags:
                        await self.send_death(f"{self.auth} died in {self.current_stage or 'Skyloft'}")
                self.last_hearts = current_health
            
            # Check for completed locations using LocationFlags.py data
            if LOCATION_FLAG_MAP:
                await self.check_all_locations()
            
            # Send any newly checked locations to server
            new_locations = self.checked_locations.difference(self.missing_locations)
            if new_locations:
                await self.send_msgs([{
                    "cmd": "LocationChecks",
                    "locations": list(new_locations)
                }])
                logger.info(f"Sent {len(new_locations)} location checks to server")
                
                # Check if "Defeat Demise" location (2773238) was just checked - this means victory!
                DEFEAT_DEMISE_LOCATION = 2773238
                if DEFEAT_DEMISE_LOCATION in new_locations:
                    logger.info("=== VICTORY! Demise defeated - sending goal completion to server ===")
                    await self.send_msgs([{
                        "cmd": "StatusUpdate",
                        "status": ClientStatus.CLIENT_GOAL
                    }])
                    # Server will automatically release all remaining items if auto-release is enabled
            
        except Exception as e:
            logger.error(f"Error updating game state: {e}")
    
    async def check_all_locations(self):
        """Check all 350+ locations using LocationFlags.py data."""
        if not self.memory.connected or not self.memory.base_address:
            return
        
        newly_checked = []
        
        for location_name, (flag_type, flag_bit, flag_value, scene_or_addr) in LOCATION_FLAG_MAP.items():
            # Get proper location ID from LOCATION_TABLE
            if location_name in LOCATION_TABLE:
                location_id = LOCATION_TABLE[location_name].code
            else:
                # Fallback to hash-based ID if not in table
                location_id = 2773000 + (hash(location_name) % 900)
                logger.warning(f"Location '{location_name}' not found in LOCATION_TABLE, using hash ID {location_id}")
            
            # Skip if already checked
            if location_id in self.checked_locations:
                continue
            
            try:
                is_checked = False
                
                if flag_type == FLAG_STORY:
                    # Story flag: read from absolute story flag memory address
                    story_addr = scene_or_addr
                    if isinstance(story_addr, int):
                        # Calculate byte offset from story flags base
                        flag_byte_offset = (story_addr - STORY_FLAGS_BASE) + flag_bit
                        # Read from player memory: OFFSET_PLAYER + OFFSET_STORY_FLAGS + byte offset
                        flag_byte = self.memory.read_byte(OFFSET_PLAYER + OFFSET_STORY_FLAGS + flag_byte_offset)
                        if flag_byte is not None:
                            is_checked = bool(flag_byte & flag_value)
                
                elif flag_type == FLAG_SCENE:
                    # Scene flag: read from scene-specific memory
                    scene_name = scene_or_addr
                    if scene_name in SCENE_FLAG_ADDRESSES:
                        scene_base = SCENE_FLAG_ADDRESSES[scene_name]
                        # Calculate byte offset from scene flags base
                        flag_byte_offset = (scene_base - SCENE_FLAGS_BASE) + flag_bit
                        # Read from player memory: OFFSET_PLAYER + OFFSET_SCENE_FLAGS + byte offset
                        flag_byte = self.memory.read_byte(OFFSET_PLAYER + OFFSET_SCENE_FLAGS + flag_byte_offset)
                        if flag_byte is not None:
                            is_checked = bool(flag_byte & flag_value)
                    else:
                        logger.warning(f"Scene '{scene_name}' not found in SCENE_FLAG_ADDRESSES")
                
                elif flag_type == FLAG_SPECIAL:
                    # Special flags require custom logic with absolute address reads
                    # SPECIAL index 0: "Upper Skyloft - Ghost/Pipit's Crystals"
                    if "Ghost/Pipit" in location_name or scene_or_addr == 0x0:
                        # Read from absolute address 0x805A9B16
                        abs_addr = 0x805A9B16
                        rel_addr = abs_addr - STORY_FLAGS_BASE
                        flag_byte = self.memory.read_byte(OFFSET_PLAYER + OFFSET_STORY_FLAGS + rel_addr)
                        if flag_byte is not None:
                            flag1 = bool(flag_byte & 0x80)  # Pipit crystal (bit 7)
                            flag2 = bool(flag_byte & 0x04)  # Ghost crystal (bit 2)
                            is_checked = flag1 or flag2
                    
                    # SPECIAL index 1: "Central Skyloft - Peater/Peatrice's Crystals"
                    elif "Peater/Peatrice" in location_name or scene_or_addr == 0x1:
                        # Read 4 bytes from absolute address 0x805A9B1A
                        abs_addr = 0x805A9B1A
                        rel_addr = abs_addr - STORY_FLAGS_BASE
                        flag_int = self.memory.read_int(OFFSET_PLAYER + OFFSET_STORY_FLAGS + rel_addr)
                        if flag_int is not None:
                            flag1 = bool(flag_int & 0x40000000)  # Peatrice crystal
                            flag2 = bool(flag_int & 0x02)        # Peater crystal
                            is_checked = flag1 or flag2
                
                if is_checked:
                    self.checked_locations.add(location_id)
                    newly_checked.append(location_id)
                    logger.debug(f"Location checked: {location_name} (ID: {location_id})")
            
            except Exception as e:
                logger.debug(f"Error checking location {location_name}: {e}")
                continue
        
        # Send newly checked locations to server
        if newly_checked:
            await self.send_msgs([{
                "cmd": "LocationChecks",
                "locations": newly_checked
            }])
            logger.info(f"Sent {len(newly_checked)} location checks to server")
    
    def mark_location_checked(self, location_name: str):
        """Mark a location as checked (legacy helper method)."""
        if location_name in LOCATION_TABLE:
            location_id = LOCATION_TABLE[location_name].code
        else:
            location_id = 2773000 + (hash(location_name) % 900)
        
        if location_id not in self.checked_locations:
            self.checked_locations.add(location_id)
            logger.info(f"Marked location checked: {location_name} (ID: {location_id})")
    
    async def on_deathlink(self, data: dict):
        """
        Handle death link - kill the player when someone else dies.
        """
        if not self.memory.connected or not self.memory.base_address:
            return
        
        logger.info(f"Death link received from {data.get('source', 'Unknown')}: {data.get('cause', 'died')}")
        
        # Set player hearts to 0 to trigger death
        self.memory.write_short(OFFSET_PLAYER + OFFSET_CURRENT_HEALTH, 0)
    
    async def send_death(self, death_text: str = ""):
        """
        Send a death link notification to other players.
        """
        if "DeathLink" not in self.tags:
            return
        
        await self.send_msgs([{
            "cmd": "Deathlink",
            "time": time.time(),
            "source": self.auth,
            "cause": death_text or f"{self.auth} died"
        }])
    
    def run_gui(self):
        """Run the GUI for the client."""
        from kvui import GameManager
        
        class SSHDManager(GameManager):
            logging_pairs = [
                ("Client", "Archipelago"),
            ]
            base_title = "Archipelago Skyward Sword HD Client Version"
        
        self.ui = SSHDManager(self)
        self.ui_task = asyncio.create_task(self.ui.async_run(), name="UI")


def main(args=None):
    """
    Main entry point for the SSHD client.
    """
    import colorama
    
    parser = get_base_parser(description="Skyward Sword HD Client for Archipelago with Ryujinx support.")
    args = parser.parse_args(args)
    
    colorama.init()
    
    # Create context
    ctx = SSHDContext(args.connect, args.password)
    ctx.server_task = asyncio.create_task(server_loop(ctx), name="ServerLoop")
    
    if gui_enabled:
        ctx.run_gui()
    ctx.run_cli()
    
    # Add Ryujinx connection task
    ctx.ryujinx_task = asyncio.create_task(ctx.ryujinx_connection_task(), name="Ryujinx Connection")
    
    # Run event loop
    asyncio.get_event_loop().run_until_complete(ctx.exit_event.wait())
    
    # Cleanup
    ctx.server_address = None


if __name__ == "__main__":
    logging.basicConfig(
        format="[%(name)s]: %(message)s",
        level=logging.INFO
    )
    main()
