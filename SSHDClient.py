"""
Skyward Sword HD Client for Archipelago with Ryujinx support.

This client connects to Ryujinx via direct memory access and communicates
with the Archipelago server to enable multiworld randomizer support.
"""

import asyncio
import json
import logging
import math
import os
import struct
import sys
import time
from pathlib import Path
from typing import Optional, Set, Dict, Any

# Add parent directory to path to find Archipelago modules when running as exe
if getattr(sys, 'frozen', False):
    # Running as compiled exe
    bundle_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    # Add Archipelago install directory to path (cross-platform)
    try:
        from platform_utils import get_archipelago_dir
        archipelago_dir = str(get_archipelago_dir())
    except ImportError:
        # Fallback if platform_utils not available
        if sys.platform == "win32":
            archipelago_dir = os.path.join(os.environ.get('PROGRAMDATA', 'C:\\ProgramData'), 'Archipelago')
        elif sys.platform == "linux":
            archipelago_dir = os.path.expanduser("~/.local/share/Archipelago")
        else:  # macOS and other
            archipelago_dir = os.path.expanduser("~/Library/Application Support/Archipelago")
    if os.path.exists(archipelago_dir):
        sys.path.insert(0, archipelago_dir)
else:
    # Running as script - add current directory to find bundled modules
    bundle_dir = os.path.dirname(os.path.abspath(__file__))
    # Add current directory first (for bundled core files in .apworld)
    sys.path.insert(0, bundle_dir)
    # Also try Archipelago folder if available
    archipelago_parent = os.path.dirname(bundle_dir)
    archipelago_dir = os.path.join(archipelago_parent, 'Archipelago')
    if os.path.exists(archipelago_dir):
        sys.path.insert(0, archipelago_dir)

# Disable ModuleUpdate (prevents unnecessary dependency checks)
class DummyModuleUpdate:
    @staticmethod
    def update(*args, **kwargs):
        pass
sys.modules['ModuleUpdate'] = DummyModuleUpdate()

import psutil
import pymem
import pymem.process

# Try to import from bundled modules first, then fall back to system Archipelago
try:
    # First try relative imports (when running from .apworld)
    try:
        from .CommonClient import CommonContext, server_loop, gui_enabled, \
            ClientCommandProcessor, logger, get_base_parser
        from .NetUtils import ClientStatus
    except ImportError:
        # Fall back to absolute imports (when running from Archipelago install)
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
    print(f"[Import] Successfully imported LocationFlags from package (.LocationFlags)")
    print(f"[Import] LOCATION_FLAG_MAP has {len(LOCATION_FLAG_MAP)} entries")
except ImportError as e:
    print(f"[Import] Failed to import .LocationFlags: {e}")
    # Fallback if running as standalone
    try:
        from LocationFlags import LOCATION_FLAG_MAP, FLAG_STORY, FLAG_SCENE, FLAG_SPECIAL
        print(f"[Import] Successfully imported LocationFlags from standalone (LocationFlags)")
        print(f"[Import] LOCATION_FLAG_MAP has {len(LOCATION_FLAG_MAP)} entries")
    except ImportError as e2:
        print(f"[Import] Failed to import LocationFlags: {e2}")
        print(f"[Import] LOCATION_FLAG_MAP will be empty - location checking DISABLED")
        LOCATION_FLAG_MAP = {}
        FLAG_STORY = "STORY"
        FLAG_SCENE = "SCENE"
        FLAG_SPECIAL = "SPECIAL"

# Import tracker bridge
try:
    from .TrackerBridge import TrackerBridge
    print(f"[Import] Successfully imported TrackerBridge from package")
except ImportError:
    try:
        from TrackerBridge import TrackerBridge
        print(f"[Import] Successfully imported TrackerBridge from standalone")
    except ImportError as e:
        print(f"[Import] TrackerBridge not available: {e}")
        TrackerBridge = None

# Import location table for proper location IDs
try:
    from .Locations import LOCATION_TABLE
except ImportError:
    try:
        from Locations import LOCATION_TABLE
    except ImportError:
        LOCATION_TABLE = {}

# Import item table for item code lookup
try:
    from .Items import ITEM_TABLE
except ImportError:
    try:
        from Items import ITEM_TABLE
    except ImportError:
        ITEM_TABLE = {}

# Import hint system
try:
    from .Hints import HintSystem
except ImportError:
    try:
        from Hints import HintSystem
    except ImportError:
        HintSystem = None

# Import Archipelago item system integration
try:
    from .ItemSystemIntegration import GameItemSystem
except ImportError:
    try:
        from ItemSystemIntegration import GameItemSystem
    except ImportError:
        GameItemSystem = None
        logger.warning("ItemSystemIntegration not found - falling back to direct memory writes")


# Beedle's Airshop detection constants
# Purchase storyflags are injected into 105-Terry.msbf flows at build time.
# At runtime, the client reads SHOP_ITEMS[N].event_entrypoint from memory,
# converts to a FEN1 name (e.g. 10531 -> "105_31"), and looks up the
# corresponding storyflag to dynamically map storyflag -> AP location.
BEEDLE_PURCHASE_STORYFLAGS = {
    "105_05": 1950,  "105_08": 1951,  "105_09": 1952,   # Pouch flows
    "105_31": 1953,  "105_32": 1954,  "105_33": 1955,   # Non-pouch flows
    "105_34": 1956,  "105_35": 1957,  "105_36": 1958,
    "105_37": 1959,  "105_38": 1960,
    "105_39": 1961,  "105_40": 1962,                     # Rando-added flows
}

SHOP_INDEX_TO_LOCATION = {
    20: "Beedle's Airshop - 300 Rupee Item",
    21: "Beedle's Airshop - 600 Rupee Item",
    22: "Beedle's Airshop - 1200 Rupee Item",
    23: "Beedle's Airshop - 1600 Rupee Item",
    24: "Beedle's Airshop - First 100 Rupee Item",
    25: "Beedle's Airshop - 50 Rupee Item",
    26: "Beedle's Airshop - 800 Rupee Item",
    27: "Beedle's Airshop - 1000 Rupee Item",
    28: "Beedle's Airshop - Second 100 Rupee Item",
    29: "Beedle's Airshop - Third 100 Rupee Item",
}

# SHOP_ITEMS memory layout
OFFSET_SHOP_ITEMS = 0x163C43C   # SHOP_ITEMS table base offset from game base
SHOP_ITEM_SIZE = 0x54           # Size of each SHOP_ITEMS entry
SHOP_ITEM_EVENT_EP_FIELD = 0x10 # event_entrypoint field offset (u16 LE)
SHOP_ITEM_SOLD_OUT_SF_FIELD = 0x52  # sold_out_storyflag field offset (u16 LE)

# Memory signature to find SSHD base address
MEMORY_SIGNATURE = bytes.fromhex("00000000080000004D4F443088BD8101")

# Memory offsets (relative to base address)
# All addresses verified from sshd-cheat-table.CT

# Main pointers
OFFSET_PLAYER = 0x623E680          # Player structure base
OFFSET_FILE_MANAGER = 0x6288408    # Save file manager (actually at 0x5AEAD44 in cheat table)
OFFSET_CURRENT_STAGE = 0x2BF98D8   # Current stage info
OFFSET_NEXT_STAGE = 0x2BF9904      # Next stage info

# Static flag addresses (absolute, not relative to player) - from cheat table
OFFSET_STORY_FLAGS_STATIC = 0x182E1F8   # Static story flags (256 bytes)
OFFSET_SCENE_FLAGS_STATIC = 0x182DF00   # Static scene flags (16 bytes)
OFFSET_SCENE_FLAGS = 0x9E4              # Scene flags within player structure
OFFSET_TEMP_FLAGS_STATIC = 0x182DF10    # Static temp flags (8 bytes)
OFFSET_ZONE_FLAGS_STATIC = 0x182DF18    # Static zone flags (504 bytes)
OFFSET_ITEM_FLAGS_STATIC = 0x182E170    # Static item flags (128 bytes)
OFFSET_DUNGEON_FLAGS_STATIC = 0x182E128 # Static dungeon flags (16 bytes)

# File Manager structure (cheat table shows FA at +5AEAD44)
# NOTE: The cheat table offset 0x5AEAD44 points directly to FA (SaveFile), not to the start of FileMgr
# FileMgr has: all_save_files (8), save_tails (8), then FA embedded at +0x10
# But the CT offset already accounts for this, so we use it directly
OFFSET_SAVEFILE_A = 0x5AEAD54  # Direct offset to FA (SaveFile structure) - from CT: base+0x5AEAD44+0x10
# SaveFile structure offsets (from cheat table actual addresses)
OFFSET_FA_STORYFLAGS = 0x8E4            # Story flags in save file (CT: 0x307126AF638 - FA@0x307126AED54 = 0x8E4)
OFFSET_FA_ITEMFLAGS = 0xA64            # Item flags (CT shows at base+5AEF7B8-5AEAD54)  
OFFSET_FA_DUNGEONFLAGS = 0xA64         # Dungeon flags (CT shows at base+5AEF7B8-5AEAD54)
# CORRECTED: Diagnostic scan showed actual sceneflags 0x800 bytes before expected!
# Scan found flag change at base+0x5AEC7B8 vs expected base+0x5AECFB8
OFFSET_FA_SCENEFLAGS = 0x1A64          # CORRECTED from 0x2264: actual offset is 0x2264 - 0x800 = 0x1A64
OFFSET_FA_TBOXFLAGS = 0x28C4           # Treasure box flags [[u8; 4]; 26] (104 bytes)
OFFSET_FA_TEMPFLAGS = 0x50F4           # Temp flags (CT shows at base+5AF3E48-5AEAD54)
OFFSET_FA_ZONEFLAGS = 0x50FC           # Zone flags (CT shows at base+5AF3E50-5AEAD54)

# Player structure offsets (relative to OFFSET_PLAYER)
# All offsets verified against Rust struct definitions in:
#   player.rs  (dPlayer),  actor.rs (dAcOBasemembers / dAcBasemembers),
#   input.rs   (BUTTON_INPUTS enum),  math.rs (Vec3f / Vec3s)
OFFSET_POS_X = 0x144               # dAcBasemembers.pos.x  (f32)
OFFSET_POS_Y = 0x148               # dAcBasemembers.pos.y  (f32)
OFFSET_POS_Z = 0x14C               # dAcBasemembers.pos.z  (f32)
OFFSET_ANGLE_Y = 0x13E             # dAcBasemembers.rot.y  (u16, full turn = 65536)
OFFSET_VELOCITY_X = 0x1E8          # dAcOBasemembers.velocity.x  (f32)
OFFSET_VELOCITY_Y = 0x1EC          # dAcOBasemembers.velocity.y  (f32)
OFFSET_VELOCITY_Z = 0x1F0          # dAcOBasemembers.velocity.z  (f32)
OFFSET_FORWARD_SPEED = 0x1DC       # dAcOBasemembers.forward_speed  (f32)
OFFSET_ACTION_FLAGS = 0x460        # dPlayer.action_flags  (u32)
OFFSET_ACTION_FLAGS_MORE = 0x464   # dPlayer.action_flags_cont  (u32)
OFFSET_CURRENT_ACTION = 0x468      # dPlayer.current_action  (PLAYER_ACTIONS, u32)
OFFSET_TRIGGERED_BUTTONS = 0x63F8  # dPlayer.triggered_buttons  (u16, set for ONE frame on press)
OFFSET_HELD_BUTTONS = 0x63FC       # dPlayer.held_buttons  (u16, set while button is held)
OFFSET_B_WHEEL_EQUIPPED = 0x6408   # dPlayer.equipped_b_item  (u16)
OFFSET_STAMINA = 0x64D8            # dPlayer.stamina_amount  (u32)
OFFSET_STAMINA_RECOVERY_TIMER = 0x6414  # dPlayer.stamina_recovery_timer  (u16)
OFFSET_STAMINA_EXHAUSTION_FLAG = 0x6416 # dPlayer.something_we_use_for_stamina  (u8)
OFFSET_SKYWARD_STRIKE_TIMER = 0x641E    # dPlayer.skyward_strike_timer  (u16)  — was 0x641C!
OFFSET_GAME_STATE = 0x2BF98A0      # Game state flags (dialogue, cutscene, etc.)
OFFSET_CURRENT_HEALTH = 0x5AF005A  # Current hearts (2 bytes) - from File Mgr->FA structure
OFFSET_HEALTH_CAPACITY = 0x5302    # Max hearts (2 bytes)

# Cheat-related offsets (relative to base address, from cheat table)
# Ammo counters are bit-packed in the committed item flags area
# SaveFile A is at base + OFFSET_SAVEFILE_A (0x5AEAD54)
# Itemflags start at SaveFile + 0x9E4
# Committed counters:
#   Rupee:    itemflags+0x70+0xA, 20 bits from bit 0
#   Arrow:    itemflags+0x70+0xE, 7 bits from bit 0
#   Bomb:     itemflags+0x70+0xE, 7 bits from bit 7
#   DekuSeed: itemflags+0x70+0xC, 7 bits from bit 7
# Uncommitted counters (static):
#   Rupee:    base+0x182E170+0x70+0xA
#   Arrow:    base+0x182E170+0x70+0xE
#   Bomb:     base+0x182E170+0x70+0xE
#   DekuSeed: base+0x182E170+0x70+0xC

# Button bitmask values for dPlayer.held_buttons (u16 at +0x63FC)
# IMPORTANT: These do NOT match the Rust BUTTON_INPUTS enum in input.rs!
# The BUTTON_INPUTS enum is for the InputMgr vtable API.
# The held_buttons field uses a different encoding, verified by Cheat Engine:
#   Y held → held_buttons = 0x0800
#   X held → held_buttons = 0x0400
#   Both   → held_buttons = 0x0C00
# This matches Atmosphere HID encoding shifted left 8 bits.
BUTTON_A           = 0x0100
BUTTON_B           = 0x0200
BUTTON_X           = 0x0400  # Verified via Cheat Engine
BUTTON_Y           = 0x0800  # Verified via Cheat Engine
BUTTON_MINUS       = 0x1000
BUTTON_ZL          = 0x2000
BUTTON_L           = 0x4000

# Speed override field — past the end of the mapped dPlayer struct (0x64DC),
# but confirmed by Atmosphere cheats on v1.0.1:
#   [*Speed R]       → 04000000 06244B68 42880000  (68.0)
#   [Run Speed (L)]  → 04000000 06244B68 42900000  (72.0)
#   06244B68 - 0623E680 = 0x64E8
OFFSET_SPEED_OVERRIDE = 0x64E8  # f32, controls movement speed (player-relative)

# Shield-related offsets
OFFSET_SHIELD_POUCH_SLOT = 0x53B1  # u8, index into pouch_items for equipped shield (relative to SaveFile A)
OFFSET_POUCH_ITEMS = 0x7C0         # [i32; 8], pouch item slots (relative to SaveFile A)
OFFSET_SHIELD_BURN_TIMER = 0x642C  # dPlayer.shield_burn_timer (u16)  — was 0x6484!

# Shield item IDs (low byte of pouch_items entry)
SHIELD_IDS = {116, 117, 118, 119, 120, 121, 122, 123, 124, 125}
# Wooden=116, Banded=117, Braced=118, Iron=119, Reinforced=120, Fortified=121,
# Sacred=122, Divine=123, Goddess=124, Hylian=125

# Bug boolean itemflag IDs (these are single-bit flags in the itemflags u16[64] array)
# Flag ID 0x8D-0x98 (141-152)
BUG_ITEMFLAG_IDS = list(range(0x8D, 0x99))  # 12 bugs

# Treasure/material boolean itemflag IDs
# Flag ID 0xA1-0xB0 (161-176)
TREASURE_ITEMFLAG_IDS = list(range(0xA1, 0xB1))  # 16 treasures

# Beetle flying time cheat: ARM64 code patch
# The original instruction at main+0x279CE4 loads a small timer value.
# Patching it to `mov w8, #0x360` (0x52806C08) makes the beetle timer huge.
# From Atmosphere cheat: [Inf Beetle Flying Time] 040E0000 00279CE4 52806C08
OFFSET_BEETLE_TIMER_INSTRUCTION = 0x279CE4
BEETLE_TIMER_PATCHED_VALUE = 0x52806C08  # ARM64: mov w8, #0x360

# Loftwing spiral charge cheats (data writes, not code patches)
# From Atmosphere cheats: write byte 0x03 to keep spiral charges at max (3)
OFFSET_LOFTWING_CHARGE_A = 0x619936A  # Loftwing charge counter A
OFFSET_LOFTWING_CHARGE_B = 0x6186B32  # Loftwing charge counter B (spiral charges)
LOFTWING_MAX_CHARGES = 3

# Stamina full value (from observing normal gameplay)
STAMINA_FULL = 1000000  # Full stamina gauge value

# Skyward strike timer value to keep it charged
SKYWARD_STRIKE_CHARGED = 300  # Keep timer positive to stay charged

# Current Stage Info offsets (relative to OFFSET_CURRENT_STAGE)
OFFSET_STAGE_NAME = 0x0            # Stage name (8 byte string)
OFFSET_STAGE_LAYER = 0x23          # Layer ID
OFFSET_STAGE_ROOM = 0x22           # Room ID
OFFSET_STAGE_ENTRANCE = 0x24       # Entrance ID
OFFSET_STAGE_NIGHT = 0x25          # Night flag

# Scene name to scene flag base address mapping (base-relative offsets for SSHD)
# These are the offsets from base_address where scene flags are stored
# Scene flags are organized by scene in the static scene flag array
SCENE_FLAG_ADDRESSES = {
    "Skyloft": 0x182DF00,              # Skyloft scene flags (base-relative)
    "Sky": 0x182DF10,                  # Sky scene flags
    "Sealed Grounds": 0x182DF20,       # Sealed Grounds
    "Faron Woods": 0x182DF30,          # Faron Woods
    "Lake Floria": 0x182DF40,          # Lake Floria
    "Skyview": 0x182DF50,              # Skyview Temple
    "Eldin Volcano": 0x182DF60,        # Eldin Volcano
    "Earth Temple": 0x182DF70,         # Earth Temple
    "Lanayru Desert": 0x182DF80,       # Lanayru Desert
    "Lanayru Mining Facility": 0x182DF90,  # Lanayru Mining Facility
    "Ancient Cistern": 0x182DFA0,      # Ancient Cistern
    "Sandship": 0x182DFB0,             # Sandship
    "Fire Sanctuary": 0x182DFC0,       # Fire Sanctuary
    "Sky Keep": 0x182DFD0,             # Sky Keep
}

# Story flags base address (base-relative)
STORY_FLAGS_BASE = OFFSET_STORY_FLAGS_STATIC

# Scene flags base address (base-relative)
SCENE_FLAGS_BASE = OFFSET_SCENE_FLAGS_STATIC

# Stage name mapping (internal codes to friendly names)
STAGE_NAMES = {
    "F000": "Skyloft",
    "F001r": "Knight Academy",
    "F002r": "Bazaar",
    "F004r": "Sparring Hall",
    "F005r": "Isle of Songs",
    "F006r": "Lumpy Pumpkin",
    "F007r": "Batreaux's House",
    "F008r": "Bamboo Island",
    "F009r": "Beedle's Airshop",
    "F010r": "Peatrice's House",
    "F012r": "Orielle & Parrow's House",
    "F013r": "Pippit's House",
    "F014r": "Kukiel's House",
    "F015r": "Potion Shop",
    "F016r": "Scrap Shop",
    "F017r": "Fortune Teller",
    "F018r": "Gear Shop",
    "F019r": "Item Check",
    "F020": "The Sky",
    "F021": "Thunderhead",
    "F023": "Inside the Thunderhead",
    "F100": "Faron Woods",
    "F101": "Deep Woods",
    "F102": "Lake Floria",
    "F103": "Flooded Faron Woods",
    "F200": "Eldin Volcano",
    "F201": "Volcano Summit",
    "F210": "Mogma Turf",
    "F211": "Thrill Digger",
    "F300": "Lanayru Desert",
    "F301": "Lanayru Sand Sea",
    "F302": "Lanayru Gorge",
    "F303": "Lanayru Caves",
    "D000": "Skyview Temple",
    "D100": "Earth Temple",
    "D200": "Lanayru Mining Facility",
    "D201": "Temple of Time",
    "D300": "Ancient Cistern",
    "D301": "Sandship",
    "D302": "Pirate Stronghold",
    "D003": "Fire Sanctuary",
    "D003_1": "Fire Sanctuary (Underwater)",
    "S000": "Sealed Grounds",
    "S100": "Hylia's Temple",
    "S200": "Sealed Temple",
    "B000": "Sky Keep",
    "B100": "Lanayru Gorge Silent Realm",
    "B101": "Faron Silent Realm",
    "B102": "Eldin Silent Realm",
    "B103": "Skyloft Silent Realm",
}


class RyujinxMemoryError(Exception):
    """Exception raised for Ryujinx memory access errors."""
    pass


class RyujinxMemoryReader:
    """
    Class to handle memory reading/writing for Ryujinx emulator.
    
    This provides direct access to SSHD's memory through Ryujinx's process.
    """
    
    # Magic signatures for Rust static buffers that we scan for during the
    # base-address memory scan so they are immediately available later without
    # a second full-process scan.
    PRESCAN_MAGIC = {
        "AP_ITEM_INFO_TABLE": bytes([0x49, 0x54, 0x00, 0x01]),  # "IT\x00\x01"
        "AP_CHECK_STATS":     bytes([0x43, 0x53, 0x00, 0x01]),  # "CS\x00\x01"
        "AP_ITEM_BUFFER":     bytes([0x41, 0x50, 0x00, 0x01]),  # "AP\x00\x01"
    }

    # --- Connection health thresholds ---
    # After this many consecutive memory operation failures, the base address
    # is considered invalid and a rescan will be triggered.
    HEALTH_FAILURE_THRESHOLD = 100
    # Minimum seconds between error log bursts (throttle identical errors)
    ERROR_LOG_INTERVAL = 10.0
    # Minimum seconds between full pattern_scan_all retries per buffer
    SCAN_NEGATIVE_CACHE_SECS = 30.0

    def __init__(self):
        self.pm: Optional[pymem.Pymem] = None
        self.base_address: Optional[int] = None
        self.connected = False
        # Absolute addresses found during the base-address scan for each magic
        # pattern.  Keyed by pattern name -> list of absolute addresses.
        self.prescan_results: Dict[str, list] = {}

        # --- Connection health monitoring ---
        self._consecutive_failures: int = 0
        self._total_ops: int = 0
        self._total_failures: int = 0
        self._last_successful_op: float = 0.0
        self._error_log_time: float = 0.0
        self._errors_since_log: int = 0
        # Negative cache: buffer name -> timestamp of last failed full scan
        self._scan_negative_cache: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # Connection health helpers
    # ------------------------------------------------------------------

    def _record_success(self):
        """Record a successful memory operation and reset failure streak."""
        self._consecutive_failures = 0
        self._total_ops += 1
        self._last_successful_op = time.time()

    def _record_failure(self, operation: str, offset: int, error: Exception):
        """Record a failed memory operation with throttled logging.

        Instead of logging every single failure (which can produce thousands
        of lines per second), we aggregate error counts and emit a summary
        line at most once every ERROR_LOG_INTERVAL seconds.
        """
        self._consecutive_failures += 1
        self._total_ops += 1
        self._total_failures += 1
        self._errors_since_log += 1

        now = time.time()
        if now - self._error_log_time >= self.ERROR_LOG_INTERVAL:
            logger.debug(
                f"Memory errors: {self._errors_since_log} failures in "
                f"{now - self._error_log_time:.1f}s "
                f"(last: {operation} at 0x{offset:X}, "
                f"consecutive: {self._consecutive_failures}, "
                f"total: {self._total_failures}/{self._total_ops})"
            )
            self._error_log_time = now
            self._errors_since_log = 0

    def is_healthy(self) -> bool:
        """Return True if the memory connection is healthy.

        The connection is considered *unhealthy* when there have been more
        than HEALTH_FAILURE_THRESHOLD consecutive failures without a single
        success.  This strongly indicates the base address is a false
        positive and a rescan is needed.
        """
        return self._consecutive_failures < self.HEALTH_FAILURE_THRESHOLD

    def invalidate_base(self):
        """Reset the base address and related caches to force a rescan."""
        old = self.base_address
        self.base_address = None
        self.prescan_results = {}
        self._scan_negative_cache = {}
        self._consecutive_failures = 0
        self._errors_since_log = 0
        self._total_failures = 0
        self._total_ops = 0
        if old is not None:
            logger.warning(
                f"Invalidated base address 0x{old:X} — will rescan on next cycle"
            )

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
            
            # Open process
            self.pm = pymem.Pymem()
            self.pm.open_process_from_id(ryujinx_process.pid)
            
            logger.info(f"Connected to Ryujinx (PID: {ryujinx_process.pid})")
            self.connected = True
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to Ryujinx: {e}")
            return False
    
    async def find_base_address(self) -> bool:
        """
        Find the SSHD base address by scanning memory for the signature.
        
        This can take several seconds as it scans the entire process memory.
        Runs in a thread pool to avoid blocking the GUI.
        
        Returns:
            True if base address found, False otherwise
        """
        if not self.connected or not self.pm:
            logger.error("Not connected to Ryujinx")
            return False
        
        logger.info("Scanning memory for SSHD signature... (this may take 8-10 seconds)")
        
        try:
            # Run the heavy scanning in a thread pool to not block the GUI
            loop = asyncio.get_event_loop()
            logger.debug("Starting memory scan in thread pool...")
            result = await loop.run_in_executor(None, self._scan_memory_sync)
            logger.debug(f"Memory scan completed with result: {result}")
            
            if result:
                logger.debug(f"Scan successful - base address: 0x{self.base_address:X}")
            else:
                logger.error("Scan failed - signature not found")
            
            return result
        except Exception as e:
            logger.error(f"Exception during memory scan: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _validate_base_address(self, candidate_base: int) -> int:
        """Validate a candidate base address by checking known offsets.
        
        Returns:
            Score indicating how many validation tests passed (higher is better)
        """
        score = 0
        
        try:
            # Test 1: Check if the signature itself is valid (already confirmed, but verify)
            sig_data = self.pm.read_bytes(candidate_base, len(MEMORY_SIGNATURE))
            if sig_data == MEMORY_SIGNATURE:
                score += 1
            else:
                return 0  # Invalid signature, immediate fail
            
            # Test 2: Check for reasonable pointer values at key offsets
            # Pointers should be in user-space range (not null, not kernel space)
            player_ptr = self.pm.read_bytes(candidate_base + OFFSET_PLAYER, 8)
            if player_ptr:
                ptr_val = struct.unpack('<Q', player_ptr)[0]
                if 0x1000 < ptr_val < 0x7FFFFFFFFFFF:
                    score += 1
            
            # Test 3: Check file manager pointer
            filemgr_ptr = self.pm.read_bytes(candidate_base + OFFSET_FILE_MANAGER, 8)
            if filemgr_ptr:
                ptr_val = struct.unpack('<Q', filemgr_ptr)[0]
                if 0x1000 < ptr_val < 0x7FFFFFFFFFFF:
                    score += 1
            
            # Test 4: Check current stage pointer
            stage_ptr = self.pm.read_bytes(candidate_base + OFFSET_CURRENT_STAGE, 8)
            if stage_ptr:
                ptr_val = struct.unpack('<Q', stage_ptr)[0]
                if 0x1000 < ptr_val < 0x7FFFFFFFFFFF:
                    score += 1
                    
            # Test 5: Check story flags region - should be readable memory
            try:
                story_flags = self.pm.read_bytes(candidate_base + OFFSET_STORY_FLAGS_STATIC, 16)
                if story_flags and len(story_flags) == 16:
                    score += 1
            except:
                pass
            
            # Test 6: Check scene flags region - should be readable
            try:
                scene_flags = self.pm.read_bytes(candidate_base + OFFSET_SCENE_FLAGS_STATIC, 16)
                if scene_flags and len(scene_flags) == 16:
                    score += 1
            except:
                pass
                
            # Test 7: Check if save file pointer is in reasonable range
            try:
                savefile_data = self.pm.read_bytes(candidate_base + OFFSET_SAVEFILE_A, 4)
                if savefile_data:
                    score += 1
            except:
                pass
            
            # Test 8: Verify the MOD signature is followed by expected data pattern
            # The signature includes "MOD0" at offset 8, check what comes after
            try:
                post_sig = self.pm.read_bytes(candidate_base + 16, 16)
                if post_sig and len(post_sig) == 16:
                    score += 1
            except:
                pass
                
        except Exception as e:
            logger.debug(f"Validation error for base 0x{candidate_base:X}: {e}")
            return score
        
        return score
    
    def _scan_memory_sync(self) -> bool:
        """Synchronous memory scanning using VirtualQueryEx for precise region enumeration.
        
        Finds the game base address by searching for MEMORY_SIGNATURE, then does
        a fast targeted scan of the game memory region for Rust static buffer
        magic signatures (IT, CS, AP).
        """
        try:
            import ctypes
            
            start_time = time.time()
            print(f"[DEBUG] Starting VirtualQueryEx-based memory scan")
            
            # Windows memory constants
            MEM_COMMIT = 0x1000
            # Readable page protections (excludes PAGE_NOACCESS=0x01, PAGE_EXECUTE=0x10)
            READABLE_PROTECTIONS = {0x02, 0x04, 0x08, 0x20, 0x40, 0x80}
            PAGE_GUARD = 0x100

            # 64-bit MEMORY_BASIC_INFORMATION (48 bytes on Windows 10 x64)
            class MEMORY_BASIC_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("BaseAddress",      ctypes.c_uint64),
                    ("AllocationBase",   ctypes.c_uint64),
                    ("AllocationProtect",ctypes.c_uint32),
                    ("__alignment1",     ctypes.c_uint32),  # PartitionId+pad on Win10 1703+
                    ("RegionSize",       ctypes.c_uint64),
                    ("State",            ctypes.c_uint32),
                    ("Protect",          ctypes.c_uint32),
                    ("Type",             ctypes.c_uint32),
                    ("__alignment2",     ctypes.c_uint32),
                ]

            kernel32 = ctypes.windll.kernel32
            process_handle = self.pm.process_handle
            chunk_size = 4 * 1024 * 1024  # 4 MB — larger chunks = fewer cross-process calls
            max_address = 0x7FFFFFFFFFFF
            address = 0x10000
            chunks_scanned = 0
            regions_scanned = 0
            mbi = MEMORY_BASIC_INFORMATION()
            
            # Collect candidate addresses for the game base signature
            best_base = None
            best_score = -1

            while address < max_address:
                # Query exact boundaries and attributes of the region at 'address'
                result = kernel32.VirtualQueryEx(
                    process_handle,
                    ctypes.c_uint64(address),
                    ctypes.byref(mbi),
                    ctypes.sizeof(mbi)
                )

                if result == 0:
                    address += 0x1000  # query failed, advance one page
                    continue

                region_base = mbi.BaseAddress
                region_size = mbi.RegionSize

                if region_size == 0:
                    address += 0x1000
                    continue

                # Only read committed, readable pages
                base_protect = mbi.Protect & 0xFF  # strip modifier flags
                is_committed = (mbi.State == MEM_COMMIT)
                is_readable  = (base_protect in READABLE_PROTECTIONS) and not (mbi.Protect & PAGE_GUARD)

                if is_committed and is_readable:
                    regions_scanned += 1
                    region_end = region_base + region_size
                    scan_pos   = region_base

                    while scan_pos < region_end:
                        to_read = min(chunk_size, region_end - scan_pos)
                        try:
                            data = self.pm.read_bytes(scan_pos, to_read)
                            chunks_scanned += 1

                            if chunks_scanned % 100 == 0:
                                print(f"[DEBUG] Scanned {chunks_scanned} chunks, address: 0x{scan_pos:X}")

                            # Search for game base signature
                            search_offset = 0
                            while True:
                                sig_offset = data.find(MEMORY_SIGNATURE, search_offset)
                                if sig_offset == -1:
                                    break

                                candidate = scan_pos + sig_offset
                                score = self._validate_base_address(candidate)
                                print(f"[FOUND] Signature at 0x{candidate:X} - Score: {score}/8")

                                if score > best_score:
                                    best_score = score
                                    best_base = candidate

                                # High-confidence match — stop scanning immediately
                                if best_score >= 6:
                                    break

                                search_offset = sig_offset + 1

                        except Exception:
                            pass  # skip unreadable sub-chunks within this region

                        # Stop reading more chunks once we have a high-confidence match
                        if best_score >= 6:
                            break
                        scan_pos += to_read

                # Early exit once we have a high-confidence base
                if best_score >= 6:
                    break

                # Advance precisely to next region — no large arbitrary jumps
                address = region_base + region_size

            base_elapsed = time.time() - start_time
            print(f"[SCAN] Base scan took {base_elapsed:.1f}s, {chunks_scanned} chunks in {regions_scanned} regions")
            
            if best_base is None:
                print(f"[FAIL] No signatures found")
                logger.error("Could not find SSHD signature in memory")
                return False
            
            print(f"[SUCCESS] Selected base address: 0x{best_base:X} (score: {best_score}/8)")
            
            if best_score < 3:
                logger.warning(f"Base address has low validation score ({best_score}/8) - may be incorrect")
            
            self.base_address = best_base

            # ----------------------------------------------------------------
            # Targeted scan for Rust static buffer magic signatures.
            #
            # These buffers live in the game's address space (subsdk8 .bss/.data)
            # which is within a few GB of the base address.  Scanning a
            # bounded range instead of the entire process is dramatically faster.
            #
            # We scan both above and below the base because the subsdk8 module
            # may be loaded at a lower virtual address than the main binary.
            # ----------------------------------------------------------------
            magic_hits: Dict[str, list] = {name: [] for name in self.PRESCAN_MAGIC}
            MAX_MAGIC_HITS = 16

            PRESCAN_RANGE = 0x80000000  # 2 GB in each direction
            magic_scan_start = max(best_base - PRESCAN_RANGE, 0x10000)
            magic_scan_end = best_base + PRESCAN_RANGE
            magic_addr = magic_scan_start

            while magic_addr < magic_scan_end and magic_addr < max_address:
                result = kernel32.VirtualQueryEx(
                    process_handle,
                    ctypes.c_uint64(magic_addr),
                    ctypes.byref(mbi),
                    ctypes.sizeof(mbi)
                )

                if result == 0:
                    magic_addr += 0x1000
                    continue

                region_base = mbi.BaseAddress
                region_size = mbi.RegionSize

                if region_size == 0:
                    magic_addr += 0x1000
                    continue

                base_protect = mbi.Protect & 0xFF
                is_committed = (mbi.State == MEM_COMMIT)
                is_readable  = (base_protect in READABLE_PROTECTIONS) and not (mbi.Protect & PAGE_GUARD)

                if is_committed and is_readable:
                    region_end = min(region_base + region_size, magic_scan_end)
                    scan_pos = region_base

                    while scan_pos < region_end:
                        to_read = min(chunk_size, region_end - scan_pos)
                        try:
                            data = self.pm.read_bytes(scan_pos, to_read)

                            for magic_name, magic_bytes in self.PRESCAN_MAGIC.items():
                                if len(magic_hits[magic_name]) >= MAX_MAGIC_HITS:
                                    continue
                                ms_offset = 0
                                while True:
                                    idx = data.find(magic_bytes, ms_offset)
                                    if idx == -1:
                                        break
                                    magic_hits[magic_name].append(scan_pos + idx)
                                    ms_offset = idx + 1
                                    if len(magic_hits[magic_name]) >= MAX_MAGIC_HITS:
                                        break
                        except Exception:
                            pass

                        # Advance with a small overlap so patterns straddling a
                        # chunk boundary are not missed (max pattern is 4 bytes).
                        if to_read == chunk_size:
                            scan_pos += to_read - 3
                        else:
                            scan_pos += to_read

                magic_addr = region_base + region_size

            # ----------------------------------------------------------------
            # Cross-reference: In the subsdk8 binary, AP_CHECK_STATS (12 bytes)
            # is immediately followed by AP_ITEM_INFO_TABLE.  If the short
            # 4-byte magic for AP_ITEM_INFO_TABLE wasn't found (common because
            # the pattern is too generic and may not appear in the scanned
            # range), derive it from any AP_CHECK_STATS hit by probing +12.
            # The combined 8 bytes of validation (CS magic at +0, IT magic at
            # +12) is far more reliable than either 4-byte pattern alone.
            # ----------------------------------------------------------------
            if not magic_hits["AP_ITEM_INFO_TABLE"] and magic_hits["AP_CHECK_STATS"]:
                it_magic = bytes([0x49, 0x54, 0x00, 0x01])
                for cs_addr in magic_hits["AP_CHECK_STATS"]:
                    it_addr = cs_addr + 12
                    try:
                        probe = self.pm.read_bytes(it_addr, 4)
                        if probe == it_magic:
                            magic_hits["AP_ITEM_INFO_TABLE"].append(it_addr)
                            logging.debug(f"[PRESCAN] AP_ITEM_INFO_TABLE: derived from AP_CHECK_STATS at 0x{it_addr:X}")
                            break  # one reliable hit is enough
                    except Exception:
                        pass

            # Likewise, if AP_CHECK_STATS wasn't found but AP_ITEM_INFO_TABLE
            # was, derive AP_CHECK_STATS by probing -12.
            if not magic_hits["AP_CHECK_STATS"] and magic_hits["AP_ITEM_INFO_TABLE"]:
                cs_magic = bytes([0x43, 0x53, 0x00, 0x01])
                for it_addr in magic_hits["AP_ITEM_INFO_TABLE"]:
                    cs_addr = it_addr - 12
                    try:
                        probe = self.pm.read_bytes(cs_addr, 4)
                        if probe == cs_magic:
                            magic_hits["AP_CHECK_STATS"].append(cs_addr)
                            logging.debug(f"[PRESCAN] AP_CHECK_STATS: derived from AP_ITEM_INFO_TABLE at 0x{cs_addr:X}")
                            break
                    except Exception:
                        pass

            self.prescan_results = magic_hits
            total_elapsed = time.time() - start_time

            for mname, maddrs in magic_hits.items():
                if maddrs:
                    logging.debug(f"[PRESCAN] {mname}: {len(maddrs)} hit(s), first at 0x{maddrs[0]:X}")
                else:
                    logging.debug(f"[PRESCAN] {mname}: no hits")

            # ------------------------------------------------------------------
            # Post-scan sanity check: if the prescan found ZERO magic buffer
            # hits in ±2 GB around the base address and the score wasn't
            # perfect, the base is very likely a false positive (e.g. a stale
            # signature copy left in an unrelated heap region).  Log an
            # explicit warning so the health monitor knows to expect trouble.
            # ------------------------------------------------------------------
            all_empty = all(len(v) == 0 for v in magic_hits.values())
            if all_empty and best_score < 8:
                logger.warning(
                    f"Base address 0x{best_base:X} scored only {best_score}/8 "
                    f"and no Rust magic buffers (IT/CS/AP) were found nearby. "
                    f"This may be a stale/false-positive signature. "
                    f"The health monitor will rescan automatically if "
                    f"subsequent memory operations keep failing."
                )

            logger.info(f"Found SSHD base address: 0x{best_base:X} (score: {best_score}/8, took {total_elapsed:.1f}s)")
            
            return True

        except Exception as e:
            logger.error(f"[ERROR] Exception during scan: {e}")
            logger.error(f"Error scanning memory: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def read_float(self, offset: int) -> Optional[float]:
        """Read a float from memory at base_address + offset."""
        if not self.base_address or not self.pm:
            return None
        try:
            data = self.pm.read_bytes(self.base_address + offset, 4)
            self._record_success()
            return struct.unpack('<f', data)[0]
        except Exception as e:
            self._record_failure("read_float", offset, e)
            return None
    
    def read_int(self, offset: int) -> Optional[int]:
        """Read a 32-bit integer from memory at base_address + offset."""
        if not self.base_address or not self.pm:
            return None
        try:
            data = self.pm.read_bytes(self.base_address + offset, 4)
            self._record_success()
            return struct.unpack('<I', data)[0]
        except Exception as e:
            self._record_failure("read_int", offset, e)
            return None
    
    def read_short(self, offset: int) -> Optional[int]:
        """Read a 16-bit integer from memory at base_address + offset."""
        if not self.base_address or not self.pm:
            return None
        try:
            data = self.pm.read_bytes(self.base_address + offset, 2)
            self._record_success()
            return struct.unpack('<H', data)[0]
        except Exception as e:
            self._record_failure("read_short", offset, e)
            return None
    
    def read_byte(self, offset: int) -> Optional[int]:
        """Read a single byte from memory at base_address + offset."""
        if not self.base_address or not self.pm:
            return None
        try:
            val = self.pm.read_uchar(self.base_address + offset)
            self._record_success()
            return val
        except Exception as e:
            self._record_failure("read_byte", offset, e)
            return None
    
    def read_string(self, offset: int, length: int = 32) -> Optional[str]:
        """Read a null-terminated string from memory."""
        if not self.base_address or not self.pm:
            return None
        try:
            data = self.pm.read_bytes(self.base_address + offset, length)
            self._record_success()
            # Find null terminator
            null_pos = data.find(b'\x00')
            if null_pos != -1:
                data = data[:null_pos]
            return data.decode('utf-8', errors='ignore')
        except Exception as e:
            self._record_failure("read_string", offset, e)
            return None
    
    def read_pointer(self, offset: int) -> Optional[int]:
        """Read a pointer (64-bit address) from memory."""
        if not self.base_address or not self.pm:
            return None
        try:
            data = self.pm.read_bytes(self.base_address + offset, 8)
            self._record_success()
            return struct.unpack('<Q', data)[0]  # Little-endian 64-bit
        except Exception as e:
            self._record_failure("read_pointer", offset, e)
            return None
    
    def read_bytes(self, offset: int, length: int) -> Optional[bytes]:
        """Read raw bytes from memory at base_address + offset."""
        if not self.base_address or not self.pm:
            return None
        try:
            data = self.pm.read_bytes(self.base_address + offset, length)
            self._record_success()
            return data
        except Exception as e:
            self._record_failure("read_bytes", offset, e)
            return None
    
    def write_float(self, offset: int, value: float) -> bool:
        """Write a float to memory at base_address + offset."""
        if not self.base_address or not self.pm:
            return False
        try:
            data = struct.pack('<f', value)
            self.pm.write_bytes(self.base_address + offset, data, len(data))
            self._record_success()
            return True
        except Exception as e:
            self._record_failure("write_float", offset, e)
            return False
    
    def write_int(self, offset: int, value: int) -> bool:
        """Write a 32-bit integer to memory at base_address + offset."""
        if not self.base_address or not self.pm:
            return False
        try:
            data = struct.pack('<I', value)
            self.pm.write_bytes(self.base_address + offset, data, len(data))
            self._record_success()
            return True
        except Exception as e:
            self._record_failure("write_int", offset, e)
            return False
    
    def write_byte(self, offset: int, value: int) -> bool:
        """Write a single byte to memory at base_address + offset."""
        if not self.base_address or not self.pm:
            return False
        try:
            self.pm.write_uchar(self.base_address + offset, value)
            self._record_success()
            return True
        except Exception as e:
            self._record_failure("write_byte", offset, e)
            return False
    
    def write_short(self, offset: int, value: int) -> bool:
        """Write a 16-bit short to memory at base_address + offset."""
        if not self.base_address or not self.pm:
            return False
        try:
            data = struct.pack('<H', value)
            self.pm.write_bytes(self.base_address + offset, data, len(data))
            self._record_success()
            return True
        except Exception as e:
            self._record_failure("write_short", offset, e)
            return False


class SSHDClientCommandProcessor(ClientCommandProcessor):
    """Command processor for SSHD-specific commands."""
    
    # Map of cheat short names to attribute names
    CHEAT_MAP = {
        "health":          "cheat_infinite_health",
        "stamina":         "cheat_infinite_stamina",
        "ammo":            "cheat_infinite_ammo",
        "bugs":            "cheat_infinite_bugs",
        "materials":       "cheat_infinite_materials",
        "shield":          "cheat_infinite_shield",
        "skyward_strike":  "cheat_infinite_skyward_strike",
        "rupees":          "cheat_infinite_rupees",
        "moon_jump":       "cheat_moon_jump",
        "beetle":          "cheat_infinite_beetle",
        "loftwing":        "cheat_infinite_loftwing",
    }
    
    def __init__(self, ctx: CommonContext):
        super().__init__(ctx)
    
    def _cmd_sshd(self):
        """Show SSHD client status."""
        if isinstance(self.ctx, SSHDContext):
            logger.debug(f"Connected to Ryujinx: {self.ctx.memory.connected}")
            if self.ctx.memory.base_address:
                logger.debug(f"Base address: 0x{self.ctx.memory.base_address:X}")
            logger.debug(f"Locations checked: {len(self.ctx.checked_locations)}")
        else:
            logger.warning("Not connected to SSHD context")

    def _cmd_cheats(self):
        """Show the status of all cheats (enabled/disabled)."""
        if not isinstance(self.ctx, SSHDContext):
            logger.warning("Not connected to SSHD context")
            return
        logger.info("=== Cheat Status ===")
        for short_name, attr in self.CHEAT_MAP.items():
            status = "ON" if getattr(self.ctx, attr, False) else "off"
            logger.info(f"  {short_name:20s} {status}")
        spd = self.ctx.cheat_speed_multiplier
        logger.info(f"  {'speed':20s} {spd:.1f}x" + (" (normal)" if spd == 1.0 else ""))
        logger.info("Use /cheat <name> to toggle. Names: " + ", ".join(self.CHEAT_MAP.keys()))

    def _cmd_cheat(self, cheat_name: str = ""):
        """Toggle a cheat on/off.  Usage: /cheat <name>
        Names: health, stamina, ammo, bugs, materials, shield,
               skyward_strike, rupees, moon_jump, hover, beetle, loftwing"""
        if not isinstance(self.ctx, SSHDContext):
            logger.warning("Not connected to SSHD context")
            return
        cheat_name = cheat_name.strip().lower()
        if not cheat_name:
            logger.info("Usage: /cheat <name>  — toggle a cheat on/off")
            logger.info("Available: " + ", ".join(self.CHEAT_MAP.keys()))
            return
        if cheat_name not in self.CHEAT_MAP:
            logger.warning(f"Unknown cheat '{cheat_name}'. Available: {', '.join(self.CHEAT_MAP.keys())}")
            return
        attr = self.CHEAT_MAP[cheat_name]
        current = getattr(self.ctx, attr, False)
        new_val = not current
        setattr(self.ctx, attr, new_val)
        status = "ON" if new_val else "OFF"
        logger.info(f"Cheat '{cheat_name}' is now {status}")

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
    tags = {"AP"}  # Game client tags (not TextOnly)
    game = "Skyward Sword HD"
    items_handling = 0b101  # Receive items from others, but not your own (those come from in-game pickups)
    
    def __init__(self, server_address: Optional[str], password: Optional[str]):
        super().__init__(server_address, password)
        
        self.memory = RyujinxMemoryReader()
        self.checked_locations: Set[int] = set()
        self.sent_locations: Set[int] = set()  # Locations already sent to server
        self.item_queue: list = []  # Items waiting to be given
        self.location_to_item: Dict[str, Dict] = {}  # Maps location names to item info from patch
        self.item_to_location: Dict[int, int] = {}  # Maps item code -> location code for tracking
        self.slot_data: dict = {}  # Slot data from server containing location-to-item mapping
        
        # Debug: Verify tags are set correctly
        logger.debug(f"SSHDContext initialized with tags: {self.tags}")
        logger.debug(f"Game: {self.game}")
        logger.debug(f"Items handling: {self.items_handling}")
        
        # Initialize hint system
        self.hints = HintSystem() if HintSystem else None
        
        # Initialize Archipelago item system (buffer-based with animations)
        self.game_item_system = None
        
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
        self.last_death_link: float = 0.0   # For DeathLink echo prevention
        self.delivered_item_count: int = 0  # Items actually given (persisted across restarts)
        self.connection_time: float = 0.0   # When we connected (to avoid false death on startup)
        self.slot_options: Dict[str, Any] = {}  # Player options from slot data
        self.killed_by_deathlink: bool = False  # Flag to prevent sending death when killed by death link
        
        # BreathLink state tracking
        self.last_breath_link: float = 0.0      # For BreathLink echo prevention
        self.last_stamina: Optional[int] = None  # Previous stamina reading (for detecting depletion)
        self.exhausted_by_breathlink: bool = False  # Flag to prevent sending when exhausted by breath link
        
        # Cheat state (loaded from YAML at startup, may be overridden by slot_data on connect)
        self.cheat_infinite_health: bool = False
        self.cheat_infinite_stamina: bool = False
        self.cheat_infinite_ammo: bool = False
        self.cheat_infinite_bugs: bool = False
        self.cheat_infinite_materials: bool = False
        self.cheat_infinite_shield: bool = False
        self.cheat_infinite_skyward_strike: bool = False
        self.cheat_infinite_rupees: bool = False
        self.cheat_moon_jump: bool = False
        self.cheat_infinite_beetle: bool = False
        self.cheat_infinite_loftwing: bool = False
        self.cheat_speed_multiplier: float = 1.0  # 1.0 = normal
        self.default_forward_speed: Optional[float] = None  # Cached normal speed
        self.beetle_patch_applied: bool = False  # Track if beetle code patch was written
        self._moon_jump_logged: bool = False    # One-time diagnostic log
        
        # Location checking via custom flags
        self.previous_custom_flags: Dict[int, int] = {}  # custom_flag_id -> last_state (0 or 1)
        self.custom_flag_to_location: Dict[int, int] = {}  # custom_flag_id -> location_code
        self.location_to_custom_flag: Dict[int, int] = {}  # location_code -> custom_flag_id (for vanilla pickups)
        
        # Goddess chest scene flags: location_code -> [scene_index, set_sceneflag]
        # Used to detect goddess chest opens by polling the vanilla scene flag
        # that the game engine sets when the chest is opened.
        self.goddess_chest_scene_flags: Dict[int, list] = {}
        self.previous_goddess_flags: Dict[int, int] = {}  # location_code -> last_state
        
        # AP item info table (for item 216 textbox display) and check stats (for help menu)
        self.ap_item_info: Dict[int, dict] = {}  # custom_flag_id -> {"item": name, "player": name}
        self.ap_location_codes: Set[int] = set()  # Location codes that have cross-world items
        self._ap_item_info_offset: Optional[int] = None  # Memory offset of AP_ITEM_INFO_TABLE
        self._ap_check_stats_offset: Optional[int] = None  # Memory offset of AP_CHECK_STATS
        self._ap_item_info_written: bool = False  # Whether we've written the info table
        
        # Tracker bridge for autotracking
        self.tracker_bridge = TrackerBridge() if TrackerBridge else None
        if self.tracker_bridge:
            logger.info(f"Tracker bridge initialized: {self.tracker_bridge.get_state_file_path()}")

        # Load cheats from player YAML immediately so they work before server connect
        self._load_cheats_from_yaml()

    def _load_cheats_from_yaml(self):
        """
        Load cheat settings from the player YAML file so cheats are active
        as soon as the client starts (before connecting to the AP server).

        Search order:
          1. SkywardSwordHD.yaml next to the client script / .apworld
          2. <Archipelago>/Players/SkywardSwordHD.yaml
          3. <Archipelago>/SkywardSwordHD.yaml
          4. Any *.yaml in <Archipelago>/Players/ whose game is "Skyward Sword HD"
        """
        yaml_name = "SkywardSwordHD.yaml"
        candidates: list[Path] = []

        # 1. Next to the running script / .apworld
        script_dir = Path(os.path.dirname(os.path.abspath(__file__)))
        candidates.append(script_dir / yaml_name)

        # 2-3. Archipelago install directory
        try:
            from platform_utils import get_archipelago_dir
            ap_dir = Path(str(get_archipelago_dir()))
        except Exception:
            if sys.platform == "win32":
                ap_dir = Path(os.environ.get('PROGRAMDATA', 'C:\\ProgramData')) / 'Archipelago'
            elif sys.platform == "linux":
                ap_dir = Path.home() / '.local' / 'share' / 'Archipelago'
            else:
                ap_dir = Path.home() / 'Library' / 'Application Support' / 'Archipelago'
        candidates.append(ap_dir / 'Players' / yaml_name)
        candidates.append(ap_dir / yaml_name)

        yaml_path: Optional[Path] = None
        for c in candidates:
            if c.is_file():
                yaml_path = c
                break

        # 4. Fallback: scan Players/ for any yaml with game = Skyward Sword HD
        if yaml_path is None:
            players_dir = ap_dir / 'Players'
            if players_dir.is_dir():
                for f in players_dir.glob('*.yaml'):
                    try:
                        import yaml as _yaml
                        with open(f, 'r', encoding='utf-8') as fh:
                            data = _yaml.safe_load(fh)
                        if isinstance(data, dict) and data.get('game') == 'Skyward Sword HD':
                            yaml_path = f
                            break
                    except Exception:
                        continue

        if yaml_path is None:
            logger.info("No player YAML found — cheats will be loaded when connecting to server.")
            return

        logger.info(f"Loading cheats from YAML: {yaml_path}")
        try:
            import yaml as _yaml
            with open(yaml_path, 'r', encoding='utf-8') as fh:
                data = _yaml.safe_load(fh)
        except Exception as e:
            logger.warning(f"Failed to parse YAML: {e}")
            return

        # The cheat keys live under  data["Skyward Sword HD"]  in the YAML
        if not isinstance(data, dict):
            return
        game_section = data.get('Skyward Sword HD', {})
        if not isinstance(game_section, dict):
            return

        self.cheat_infinite_health          = bool(game_section.get('cheat_infinite_health', False))
        self.cheat_infinite_stamina         = bool(game_section.get('cheat_infinite_stamina', False))
        self.cheat_infinite_ammo            = bool(game_section.get('cheat_infinite_ammo', False))
        self.cheat_infinite_bugs            = bool(game_section.get('cheat_infinite_bugs', False))
        self.cheat_infinite_materials       = bool(game_section.get('cheat_infinite_materials', False))
        self.cheat_infinite_shield          = bool(game_section.get('cheat_infinite_shield', False))
        self.cheat_infinite_skyward_strike  = bool(game_section.get('cheat_infinite_skyward_strike', False))
        self.cheat_infinite_rupees          = bool(game_section.get('cheat_infinite_rupees', False))
        self.cheat_moon_jump                = bool(game_section.get('cheat_moon_jump', False))
        self.cheat_infinite_beetle          = bool(game_section.get('cheat_infinite_beetle', False))
        self.cheat_infinite_loftwing        = bool(game_section.get('cheat_infinite_loftwing', False))
        self.beetle_patch_applied = False

        speed_raw = game_section.get('cheat_speed_multiplier', 10)
        if isinstance(speed_raw, (int, float)) and speed_raw > 0:
            self.cheat_speed_multiplier = speed_raw / 10.0

        active = []
        if self.cheat_infinite_health:          active.append("Infinite Health")
        if self.cheat_infinite_stamina:         active.append("Infinite Stamina")
        if self.cheat_infinite_ammo:            active.append("Infinite Ammo")
        if self.cheat_infinite_bugs:            active.append("Infinite Bugs")
        if self.cheat_infinite_materials:       active.append("Infinite Materials")
        if self.cheat_infinite_shield:          active.append("Infinite Shield")
        if self.cheat_infinite_skyward_strike:  active.append("Infinite Skyward Strike")
        if self.cheat_infinite_rupees:          active.append("Infinite Rupees")
        if self.cheat_moon_jump:                active.append("Moon Jump")
        if self.cheat_infinite_beetle:          active.append("Infinite Beetle")
        if self.cheat_infinite_loftwing:        active.append("Infinite Loftwing")
        if self.cheat_speed_multiplier != 1.0:  active.append(f"Speed x{self.cheat_speed_multiplier:.1f}")
        if active:
            logger.info(f"Cheats loaded from YAML: {', '.join(active)}")
        else:
            logger.info("No cheats enabled in YAML.")

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

    # Progress persistence (prevents re-giving items on client restart)
    def _get_save_file(self) -> str:
        import os
        return os.path.join(os.path.expanduser("~"), "sshd_ap_progress.json")

    def load_progress(self):
        """Load persisted item delivery count for the current slot."""
        import json, os
        save_file = self._get_save_file()
        try:
            if os.path.exists(save_file) and self.auth:
                with open(save_file, "r") as f:
                    data = json.load(f)
                count = data.get(self.auth, 0)
                if count > self.delivered_item_count:
                    self.delivered_item_count = count
                    logger.info(f"[Progress] Restored delivery count: {self.delivered_item_count} items already given for {self.auth}")
        except Exception as e:
            logger.debug(f"[Progress] Could not load progress file: {e}")

    def save_progress(self):
        """Persist item delivery count so restarts don't re-give items."""
        import json, os
        save_file = self._get_save_file()
        try:
            existing: dict = {}
            if os.path.exists(save_file):
                with open(save_file, "r") as f:
                    existing = json.load(f)
            if self.auth:
                existing[self.auth] = self.delivered_item_count
            with open(save_file, "w") as f:
                json.dump(existing, f)
        except Exception as e:
            logger.debug(f"[Progress] Could not save progress: {e}")

    def update_tracker_state(self):
        """Update the tracker bridge with current state for autotracking."""
        if not self.tracker_bridge:
            return
        
        # Build received items dictionary from ALL items (including starting items)
        received_items = {}
        
        # Process all items from items_received (this includes starting items + all received items)
        if hasattr(self, 'items_received') and self.items_received:
            for network_item in self.items_received:
                try:
                    item_name = self.item_names.lookup_in_slot(network_item.item, self.slot)
                    received_items[item_name] = received_items.get(item_name, 0) + 1
                except Exception as e:
                    logger.debug(f"Failed to lookup item {network_item.item}: {e}")
        
        # Create location name mapping
        location_names = {}
        for loc_id in self.checked_locations:
            try:
                loc_name = self.location_names.lookup_in_slot(loc_id, self.slot)
                location_names[loc_id] = loc_name
            except:
                location_names[loc_id] = f"Location_{loc_id}"
        
        # Update tracker
        self.tracker_bridge.update_tracker_state(
            checked_locations=self.checked_locations,
            received_items=received_items,
            slot_name=self.auth or "Unknown",
            seed_name=self.slot_data.get("seed_name", None),
            location_names=location_names,
            item_names=None,  # Could add if needed
            slot_data=self.slot_data,
        )
        
        logger.debug(f"Updated tracker: {len(self.checked_locations)} locations, {len(received_items)} item types, {sum(received_items.values())} total items")

    
    def on_package(self, cmd: str, args: dict):
        """Handle incoming packages from the server."""
        # IMPORTANT: Call parent first so CommonContext sets up multiworld and other attributes
        super().on_package(cmd, args)
        
        if cmd == "Connected":
            # Server confirmed connection - validate slot data and build location mapping
            slot_data = args.get("slot_data", {})
            
            # Store slot_data for use in building the item-to-location mapping
            self.slot_data = slot_data
            
            # Initialize sent_locations with the locations server already knows about
            # (checked_locations comes from server and includes all previously checked locations)
            server_checked = args.get("checked_locations", [])
            self.sent_locations = set(server_checked)
            logger.debug(f"Server has {len(server_checked)} locations already checked")
            
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
            logger.debug(f"Loaded {len(self.slot_options)} player options from slot data")
            
            # Build the item-to-location mapping now that we have slot_data
            self.item_to_location = self.build_item_to_location_map()
            
            # Load custom flag to location mapping for location detection
            custom_flag_mapping = slot_data.get("custom_flag_to_location", {})
            if custom_flag_mapping:
                # Convert string keys back to integers (JSON serialization converts int keys to strings)
                self.custom_flag_to_location = {int(k): v for k, v in custom_flag_mapping.items()}
                logger.debug(f"Loaded custom flag mapping with {len(self.custom_flag_to_location)} flags")
            else:
                logger.debug("No custom flag mapping found in slot data - location detection disabled")
            
            # Load location to custom flag mapping for vanilla item pickups
            location_to_flag_mapping = slot_data.get("location_to_custom_flag", {})
            if location_to_flag_mapping:
                # Convert string keys back to integers
                self.location_to_custom_flag = {int(k): v for k, v in location_to_flag_mapping.items()}
                logger.debug(f"Loaded {len(self.location_to_custom_flag)} location -> flag mappings for vanilla pickups")
            else:
                logger.debug("No location→flag mapping found - vanilla pickups disabled")

            # Load AP item info for cross-world item textbox display
            ap_item_info_raw = slot_data.get("ap_item_info", {})
            if ap_item_info_raw:
                self.ap_item_info = {int(k): v for k, v in ap_item_info_raw.items()}
                # Build set of AP location codes for check stats counting
                self.ap_location_codes = set()
                for flag_id in self.ap_item_info:
                    if flag_id in self.custom_flag_to_location:
                        self.ap_location_codes.add(self.custom_flag_to_location[flag_id])
                logger.info(f"Loaded {len(self.ap_item_info)} AP item info entries for textbox display")
                # Reset so the info table gets written on next game state update
                self._ap_item_info_written = False
                self._ap_item_info_offset = None
                self._ap_check_stats_offset = None
                # Eagerly attempt to write the table right now if memory is
                # already connected.  This reduces the window during which a
                # player can check a location before the table is populated.
                self._write_ap_item_info_table()
            else:
                logger.debug("No AP item info in slot data")

            # Load goddess chest scene flag mapping for completion detection.
            # Goddess chests can't use custom flags (writing to params2 corrupts
            # the storyflag spawn gate), so the client polls the vanilla
            # set_sceneflag that the game engine sets when the chest is opened.
            goddess_flags_raw = slot_data.get("goddess_chest_scene_flags", {})
            if goddess_flags_raw:
                # Keys are location_code (str from JSON), values are [scene_index, set_sceneflag]
                self.goddess_chest_scene_flags = {int(k): v for k, v in goddess_flags_raw.items()}
                logger.info(f"Loaded {len(self.goddess_chest_scene_flags)} goddess chest scene flag mappings")
            else:
                self.goddess_chest_scene_flags = {}
                logger.debug("No goddess chest scene flag mapping in slot data")

            # Enable DeathLink if the player configured it
            death_link_enabled = slot_data.get("option_death_link", 0)  # Options use "option_" prefix
            if death_link_enabled:
                self.tags.add("DeathLink")
                logger.info("DeathLink enabled! Deaths will be shared with other players.")
            else:
                self.tags.discard("DeathLink")
                logger.info("DeathLink disabled.")

            # Enable BreathLink if the player configured it
            breath_link_enabled = slot_data.get("option_breath_link", 0)
            if breath_link_enabled:
                self.tags.add("BreathLink")
                logger.info("BreathLink enabled! Stamina exhaustion will be shared with other players.")
            else:
                self.tags.discard("BreathLink")
                logger.info("BreathLink disabled.")

            # Load cheat settings from slot data
            self.cheat_infinite_health = bool(slot_data.get("option_cheat_infinite_health", 0))
            self.cheat_infinite_stamina = bool(slot_data.get("option_cheat_infinite_stamina", 0))
            self.cheat_infinite_ammo = bool(slot_data.get("option_cheat_infinite_ammo", 0))
            self.cheat_infinite_bugs = bool(slot_data.get("option_cheat_infinite_bugs", 0))
            self.cheat_infinite_materials = bool(slot_data.get("option_cheat_infinite_materials", 0))
            self.cheat_infinite_shield = bool(slot_data.get("option_cheat_infinite_shield", 0))
            self.cheat_infinite_skyward_strike = bool(slot_data.get("option_cheat_infinite_skyward_strike", 0))
            self.cheat_infinite_rupees = bool(slot_data.get("option_cheat_infinite_rupees", 0))
            self.cheat_moon_jump = bool(slot_data.get("option_cheat_moon_jump", 0))
            self.cheat_infinite_beetle = bool(slot_data.get("option_cheat_infinite_beetle", 0))
            self.cheat_infinite_loftwing = bool(slot_data.get("option_cheat_infinite_loftwing", 0))
            self.beetle_patch_applied = False  # Reset so patch is re-applied on reconnect
            # Speed multiplier: stored as integer x10 (10=1.0x, 20=2.0x, etc.)
            speed_raw = slot_data.get("option_cheat_speed_multiplier", 10)
            self.cheat_speed_multiplier = speed_raw / 10.0
            
            active_cheats = []
            if self.cheat_infinite_health: active_cheats.append("Infinite Health")
            if self.cheat_infinite_stamina: active_cheats.append("Infinite Stamina")
            if self.cheat_infinite_ammo: active_cheats.append("Infinite Ammo")
            if self.cheat_infinite_bugs: active_cheats.append("Infinite Bugs")
            if self.cheat_infinite_materials: active_cheats.append("Infinite Materials")
            if self.cheat_infinite_shield: active_cheats.append("Infinite Shield")
            if self.cheat_infinite_skyward_strike: active_cheats.append("Infinite Skyward Strike")
            if self.cheat_infinite_rupees: active_cheats.append("Infinite Rupees")
            if self.cheat_moon_jump: active_cheats.append("Moon Jump")
            if self.cheat_infinite_beetle: active_cheats.append("Infinite Beetle")
            if self.cheat_infinite_loftwing: active_cheats.append("Infinite Loftwing")
            if self.cheat_speed_multiplier != 1.0: active_cheats.append(f"Speed x{self.cheat_speed_multiplier:.1f}")
            if active_cheats:
                logger.info(f"Cheats enabled: {', '.join(active_cheats)}")
            else:
                logger.info("No cheats enabled.")

            # Send ConnectUpdate to notify server of tag changes (DeathLink/BreathLink)
            asyncio.create_task(self.send_msgs([{"cmd": "ConnectUpdate", "tags": list(self.tags)}]))
            logger.debug(f"Sent ConnectUpdate with tags: {list(self.tags)}")

            # Load persisted delivery count so we don't re-give items on reconnect
            self.load_progress()
            
            # Initialize tracker state file on connection
            logger.info("Creating initial tracker state file")
            self.update_tracker_state()
            
        elif cmd == "ReceivedItems":
            # Received items from other players
            start_index = args.get("index", 0)
            items_list = args.get("items", [])
            for i, network_item in enumerate(items_list):
                item_global_index = start_index + i

                # Skip items already delivered in a previous session
                if item_global_index < self.delivered_item_count:
                    logger.debug(f"[ReceivedItems] Skipping already-delivered item at index {item_global_index}")
                    continue

                item_id = network_item.item
                location_id = network_item.location
                location_player = network_item.player  # Player whose location was checked
                
                # Look up names - item is from OUR game (SSHD), location is from sender's game
                item_name = self.item_names.lookup_in_slot(item_id, self.slot)
                location_name = self.location_names.lookup_in_slot(location_id, location_player)
                try:
                    sender_name = self.player_names[location_player]
                except (KeyError, TypeError):
                    sender_name = f"Player {location_player}"
                
                # Precollected / start-inventory items have location_id == -2.
                # The sshd-rando patches already bake these into the game save,
                # so we must NOT give them again via the memory buffer.
                is_start_inventory = (location_id == -2)
                if is_start_inventory:
                    logger.debug(f"[ReceivedItems] START INVENTORY item_id={item_id}, item_name='{item_name}' (will skip in-game delivery)")
                else:
                    logger.debug(f"[ReceivedItems] item_id={item_id}, item_name='{item_name}', location='{location_name}', from={sender_name}")
                
                # Add to queue to be given in-game
                self.item_queue.append({
                    "id": item_id,
                    "name": item_name,
                    "location": location_name,
                    "location_player": location_player,  # Who found it
                    "player_name": sender_name,
                    "index": start_index + i,
                    "is_start_inventory": is_start_inventory,
                })
        
        elif cmd == "LocationInfo":
            # Information about locations - used for hints
            if self.hints:
                for location_info in args.get("locations", []):
                    location_id = location_info.get("location")
                    item_id = location_info.get("item")
                    player_id = location_info.get("player")
                    
                    # Get names using lookup_in_slot helpers
                    location_name = self.location_names.lookup_in_slot(location_id, player_id)
                    item_name = self.item_names.lookup_in_slot(item_id, player_id)
                    try:
                        player_name = self.player_names[player_id]
                    except (KeyError, TypeError):
                        player_name = f"Player {player_id}"
                    
                    # Format and store hint
                    is_local = (player_id == self.slot)
                    hint_text = self.hints.format_hint(location_name, item_name, player_name, is_local)
                    self.hints.add_hint(location_id, hint_text)
                    
                    logger.info(f"Received hint: {hint_text}")
        
        elif cmd == "Bounced":
            # Bounced packet - used for DeathLink and BreathLink
            logger.debug(f"[Bounced] Received bounced packet: {args}")
            tags = args.get("tags", [])
            logger.debug(f"[Bounced] Tags: {tags}")
            if "DeathLink" in tags:
                data = args.get("data", {})
                logger.debug(f"[Bounced] DeathLink data: {data}")
                # Prevent echo: ignore if this bounce came from our own death
                if data.get("time", 0) != self.last_death_link:
                    logger.info(f"[Bounced] Triggering on_deathlink with data: {data}")
                    self.on_deathlink(data)
                else:
                    logger.debug(f"[Bounced] Ignoring echo (time={data.get('time')} == last_death_link={self.last_death_link})")
            if "BreathLink" in tags:
                data = args.get("data", {})
                logger.debug(f"[Bounced] BreathLink data: {data}")
                # Prevent echo: ignore if this bounce came from our own exhaustion
                if data.get("time", 0) != self.last_breath_link:
                    logger.info(f"[Bounced] Triggering on_breathlink with data: {data}")
                    self.on_breathlink(data)
                else:
                    logger.debug(f"[Bounced] Ignoring echo (time={data.get('time')} == last_breath_link={self.last_breath_link})")
    
    def on_print_json(self, args: dict):
        """
        Override to show location checks in a pretty format.
        Shows messages like: "Wesley-SoH found their Prelude of Light (Song from Impa)"
        """
        msg_type = args.get("type", "")
        
        # Handle ItemSend messages (when someone finds an item/checks a location)
        if msg_type == "ItemSend":
            try:
                receiving_player = args.get("receiving", 0)
                item = args.get("item", {})
                
                # Only show if this concerns our player (our items or items we're receiving)
                if self.slot_concerns_self(receiving_player):
                    item_id = item.item if hasattr(item, 'item') else item.get("item", 0)
                    location_id = item.location if hasattr(item, 'location') else item.get("location", 0)
                    finding_player = item.player if hasattr(item, 'player') else item.get("player", 0)
                    item_flags = item.flags if hasattr(item, 'flags') else item.get("flags", 0)
                    
                    # Get player name (the one who found the item)
                    finder_name = self.player_names.get(finding_player, f"Player {finding_player}")
                    
                    # Get item and location names
                    item_name = self.item_names.lookup_in_slot(item_id, receiving_player)
                    location_name = self.location_names.lookup_in_slot(location_id, finding_player)
                    
                    # Determine item color based on flags
                    if item_flags & 0b001:  # advancement
                        color = "magenta"
                    elif item_flags & 0b010:  # useful
                        color = "cyan"
                    elif item_flags & 0b100:  # trap
                        color = "red"
                    else:
                        color = "white"
                    
                    super().on_print_json(args)
                    return
            except Exception as e:
                logger.debug(f"Error formatting ItemSend message: {e}")
        
        # For all other messages, use default handling
        super().on_print_json(args)
    
    def give_item_to_player(self, item_name: str, item_id: int) -> bool:
        """
        Give an item to the player using the game's native item system.
        
        Uses a memory buffer that the game monitors every frame. When items are written
        to the buffer, the game spawns them with proper animations, models, and sound effects.
        
        Returns True if successful, False if failed.
        """
        if not self.memory.connected or not self.memory.base_address:
            logger.debug(f"Cannot give item: not connected to game")
            return False
        
        logger.debug(f"[give_item_to_player] Received item_name='{item_name}', item_id={item_id}")
        
        # Handle progressive items - compute target tier WITHOUT incrementing yet.
        # Counter only advances on a successful give to prevent wrong-tier retries.
        actual_item_name = item_name
        is_progressive = item_name in self.progressive_counts
        next_count = (self.progressive_counts.get(item_name, 0) + 1) if is_progressive else 0
        
        if is_progressive:
            count = next_count
            if item_name == "Progressive Sword":
                # Tier 1-4: Goddess Longsword → White Sword → Master Sword → True Master Sword
                sword_tiers = ["Goddess Longsword", "Goddess White Sword", "Master Sword", "True Master Sword"]
                actual_item_name = sword_tiers[min(count - 1, 3)]
                logger.debug(f"Progressive Sword #{count} -> {actual_item_name}")
            elif item_name == "Progressive Bow":
                # Tier 1: base Bow (game item 19), 2: Iron Bow, 3: Sacred Bow
                bow_tiers = ["Progressive Bow", "Iron Bow", "Sacred Bow"]
                actual_item_name = bow_tiers[min(count - 1, 2)]
                logger.debug(f"Progressive Bow #{count} -> {actual_item_name}")
            elif item_name == "Progressive Slingshot":
                # Tier 1: base Slingshot (game item 52), 2: Scattershot
                slingshot_tiers = ["Progressive Slingshot", "Scattershot"]
                actual_item_name = slingshot_tiers[min(count - 1, 1)]
                logger.debug(f"Progressive Slingshot #{count} -> {actual_item_name}")
            elif item_name == "Progressive Beetle":
                # Tier 1: base Beetle (game item 53), 2: Hook, 3: Quick, 4: Tough
                beetle_tiers = ["Progressive Beetle", "Hook Beetle", "Quick Beetle", "Tough Beetle"]
                actual_item_name = beetle_tiers[min(count - 1, 3)]
                logger.debug(f"Progressive Beetle #{count} -> {actual_item_name}")
            elif item_name == "Progressive Mitts":
                # Tier 1: base Mitts (game item 56), 2: Mogma Mitts
                mitts_tiers = ["Progressive Mitts", "Mogma Mitts"]
                actual_item_name = mitts_tiers[min(count - 1, 1)]
                logger.debug(f"Progressive Mitts #{count} -> {actual_item_name}")
            elif item_name == "Progressive Bug Net":
                # Tier 1: base Bug Net (game item 71), 2: Big Bug Net
                net_tiers = ["Progressive Bug Net", "Big Bug Net"]
                actual_item_name = net_tiers[min(count - 1, 1)]
                logger.debug(f"Progressive Bug Net #{count} -> {actual_item_name}")
            elif item_name == "Progressive Wallet":
                # Tier 1: Medium Wallet (game item 108), 2: Big, 3: Giant, 4: Tycoon
                wallet_tiers = ["Progressive Wallet", "Big Wallet", "Giant Wallet", "Tycoon Wallet"]
                actual_item_name = wallet_tiers[min(count - 1, 3)]
                logger.debug(f"Progressive Wallet #{count} -> {actual_item_name}")
            elif item_name == "Progressive Pouch":
                # All tiers give a Pouch Expansion (game item 113)
                actual_item_name = "Pouch Expansion"
                logger.debug(f"Progressive Pouch #{count} -> {actual_item_name}")
        
        # Try using the new item system with animations
        if GameItemSystem:
            try:
                # Initialize on first use
                if not self.game_item_system:
                    self.game_item_system = GameItemSystem(self.memory)
                
                # Use the integrated system (spawns items with animations)
                success = self.game_item_system.give_item_by_name(actual_item_name)
                if success:
                    # Only commit the progressive counter increment on success
                    # so retries don't skip tiers
                    if is_progressive:
                        self.progressive_counts[item_name] = next_count
                    logger.debug(f"Gave {actual_item_name} via item buffer (game will handle animation)")
                else:
                    logger.debug(f"Failed to give {actual_item_name} via item system (player may be busy)")
                return success
            except Exception as e:
                logger.warning(f"Item system error for {actual_item_name}: {e}")
                return False
        else:
            logger.error("GameItemSystem not available. Cannot give item.")
            return False

    async def ryujinx_connection_task(self):
        """Background task to maintain connection to Ryujinx."""
        while not self.exit_event.is_set():
            try:
                # Try to connect if not connected
                if not self.memory.connected:
                    if self.memory.connect():
                        # Connection successful, find base address
                        if not await self.memory.find_base_address():
                            logger.error("Failed to find SSHD in memory. Is the game running?")
                            self.memory.connected = False
                        else:
                            # Set connection time to prevent false death detection on startup
                            self.connection_time = time.time()
                            logger.debug(f"Connection time set to {self.connection_time}")
                            
                            # Eagerly try to write the AP item info table now
                            # that memory is connected. This minimises the window
                            # during which a player can check a location before
                            # the table has been written.
                            self._write_ap_item_info_table()
                    
                    # Wait before retrying
                    await asyncio.sleep(5)
                    continue
                
                # Connection established, update game state
                await self.update_game_state()

                # --- Health check: detect false-positive base addresses ---
                # If every single memory operation has been failing (e.g. all
                # reads returning None, all writes returning False) the base
                # address was likely a false positive.  Invalidate it so the
                # next iteration rescans.
                if not self.memory.is_healthy():
                    logger.error(
                        f"Memory health check failed — "
                        f"{self.memory._consecutive_failures} consecutive "
                        f"failures.  Base address likely invalid; rescanning..."
                    )
                    # Reset AP buffer offsets so they get re-scanned after
                    # the next successful base-address scan.
                    self._ap_item_info_offset = None
                    self._ap_check_stats_offset = None
                    self._ap_item_info_written = False
                    self.beetle_patch_applied = False
                    self.memory.invalidate_base()

                    # Immediately attempt a new base-address scan instead of
                    # waiting for the next cycle (which would spin doing
                    # nothing since connected=True but base_address=None).
                    logger.info("Attempting automatic rescan for SSHD base address...")
                    if not await self.memory.find_base_address():
                        logger.error(
                            "Rescan failed — will retry in 10 s.  "
                            "Is the game still running?"
                        )
                        await asyncio.sleep(10)
                    else:
                        self.connection_time = time.time()
                        self._write_ap_item_info_table()
                    continue

                await asyncio.sleep(0.1)  # Update 10 times per second
                
            except Exception as e:
                logger.error(f"Error in Ryujinx connection task: {e}")
                self.memory.connected = False
                await asyncio.sleep(5)

    async def cheat_loop_task(self):
        """
        Dedicated high-frequency loop for applying cheats (~60 Hz).
        Runs independently from the main game-state loop so cheat
        memory writes happen every ~16 ms instead of every 100 ms,
        drastically reducing perceived input lag (e.g. moon jump).
        """
        while not self.exit_event.is_set():
            try:
                if self.memory.connected and self.memory.base_address:
                    self._apply_cheats()
                await asyncio.sleep(0.016)  # ~60 Hz
            except Exception as e:
                logger.error(f"Error in cheat loop: {e}")
                await asyncio.sleep(0.5)  # Back off on error
    
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
                logger.debug(f"Entered stage: {stage_name}")
                self.current_stage = stage_name
            
            # Write AP buffers to game memory (item info table + check stats)
            self._write_ap_item_info_table()
            self._update_ap_check_stats()
            
            # Give queued items to player
            if self.item_queue:
                item_data = self.item_queue[0]
                
                # Start-inventory items (precollected) are already baked into the
                # game save by sshd-rando patches.  We must NOT give them again via
                # the memory buffer, but we DO need to advance the progressive
                # counter so that future progressive items resolve to the right tier.
                if item_data.get("is_start_inventory", False):
                    item_name = item_data["name"]
                    if item_name in self.progressive_counts:
                        self.progressive_counts[item_name] += 1
                        logger.debug(f"[StartInventory] Tracked {item_name} progressive count -> {self.progressive_counts[item_name]}")
                    logger.debug(f"[StartInventory] Skipped in-game delivery of {item_name} (already in save from patches)")
                    self.item_queue.pop(0)
                    self.delivered_item_count += 1
                    self.save_progress()
                    self.update_tracker_state()
                elif self.give_item_to_player(item_data["name"], item_data["id"]):
                    # Successfully gave item
                    player_name = item_data.get("player_name", "another player")
                    location_name = item_data.get("location", "unknown location")
                    is_own_item = (item_data.get("location_player") == self.slot)
                    
                    if not is_own_item:
                        # Received item from another player
                        logger.info(f"Received {item_data['name']} from {player_name} ({location_name})")
                    else:
                        # Received own item
                        logger.info(f"Received {item_data['name']} ({location_name})")
                    
                    # Clear retry counter on success
                    item_data.pop("_retry_count", None)
                    
                    # Remove from queue and persist delivery count
                    self.item_queue.pop(0)
                    self.delivered_item_count += 1
                    self.save_progress()
                    
                    # Update tracker with new item
                    self.update_tracker_state()
                else:
                    # Item delivery failed - track retries to avoid infinite loops
                    MAX_ITEM_RETRIES = 50  # ~50 attempts × 5s timeout = ~4 min max
                    retry_count = item_data.get("_retry_count", 0) + 1
                    item_data["_retry_count"] = retry_count
                    
                    if retry_count >= MAX_ITEM_RETRIES:
                        item_name = item_data["name"]
                        logger.error(
                            f"[ItemDelivery] Giving up on {item_name} after {retry_count} attempts. "
                            f"Item will be re-delivered on next reconnect."
                        )
                        # Move to back of queue instead of dropping forever,
                        # so it can be retried after other items succeed
                        # (which may fix the buffer address via cycling)
                        self.item_queue.pop(0)
                        item_data["_retry_count"] = 0  # Reset for next round
                        self.item_queue.append(item_data)
            
            # Check for death (for death link)
            current_health = self.memory.read_short(OFFSET_CURRENT_HEALTH)
            if current_health is not None:
                # Skip death detection for 10 seconds after connection to avoid false positives
                time_since_connect = time.time() - self.connection_time
                if time_since_connect > 10.0:
                    # Player just died if health went to 0 (from any positive value OR if we had None before)
                    if current_health == 0 and (self.last_hearts is None or self.last_hearts > 0):
                        # Player just died - but skip sending if we killed them via death link
                        if self.killed_by_deathlink:
                            logger.debug("Death detected, but caused by receiving death link - not sending")
                            self.killed_by_deathlink = False  # Clear flag
                        elif "DeathLink" in self.tags:
                            stage_name = STAGE_NAMES.get(self.current_stage, self.current_stage or "Skyloft")
                            await self.send_death(f"{self.auth} died in {stage_name}")
                self.last_hearts = current_health
            
            # Check for stamina exhaustion (for breath link)
            current_stamina = self.memory.read_int(OFFSET_PLAYER + OFFSET_STAMINA)
            if current_stamina is not None:
                time_since_connect = time.time() - self.connection_time
                if time_since_connect > 10.0:
                    # Stamina just ran out if it went from >0 to 0
                    if current_stamina == 0 and (self.last_stamina is not None and self.last_stamina > 0):
                        if self.exhausted_by_breathlink:
                            logger.debug("Stamina exhaustion detected, but caused by receiving breath link - not sending")
                            self.exhausted_by_breathlink = False  # Clear flag
                        elif "BreathLink" in self.tags:
                            stage_name = STAGE_NAMES.get(self.current_stage, self.current_stage or "Skyloft")
                            await self.send_breathlink(f"{self.auth} ran out of stamina in {stage_name}")
                self.last_stamina = current_stamina
            
            # ============================================================
            # Cheats are now applied in a dedicated 60 Hz loop
            # (cheat_loop_task) for minimal input lag.
            # ============================================================
            
            # Check for completed locations using custom flags or LocationFlags.py data
            if self.custom_flag_to_location:
                # Use custom flag system (preferred for SSHD)
                await self.check_custom_flags()
                # Goddess chests use vanilla scene flags instead of custom flags
                await self.check_goddess_chest_flags()
                # Supplement: shop purchases don't set custom scene/dungeon flags,
                # so also check Beedle's sold-out storyflags from the save file.
                await self.check_beedle_shop_storyflags()
            elif LOCATION_FLAG_MAP:
                # Fallback to LocationFlags.py - but only if static memory is accessible
                # Test if we can read the first static flag address to avoid error spam
                test_read = self.memory.read_byte(OFFSET_SCENE_FLAGS_STATIC)
                if test_read is not None:
                    # NOTE: FLAG_SCENE should work (uses SSHD addresses), but FLAG_STORY has Wii addresses
                    await self.check_all_locations()
            
            # Send any newly checked locations to server (locations not yet sent)
            new_locations = self.checked_locations.difference(self.sent_locations)
            if new_locations:
                await self.send_msgs([{
                    "cmd": "LocationChecks",
                    "locations": list(new_locations)
                }])
                
                # Mark these locations as sent to avoid re-sending
                self.sent_locations.update(new_locations)
                
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
    
    def _apply_cheats(self):
        """
        Apply active cheats by writing to game memory each tick.
        Called from cheat_loop_task() ~60 times per second.
        Each cheat is wrapped in its own try/except so one failure
        cannot prevent the others from running.
        """
        if not self.memory.connected or not self.memory.base_address:
            return

        player_base = OFFSET_PLAYER
        any_cheat = (
            self.cheat_infinite_health or self.cheat_infinite_stamina or
            self.cheat_infinite_ammo or self.cheat_infinite_bugs or
            self.cheat_infinite_materials or self.cheat_infinite_shield or
            self.cheat_infinite_skyward_strike or self.cheat_infinite_rupees or
            self.cheat_moon_jump or
            self.cheat_infinite_beetle or
            self.cheat_infinite_loftwing or self.cheat_speed_multiplier != 1.0
        )
        if not any_cheat:
            return

        # --- Infinite Health ---
        if self.cheat_infinite_health:
            try:
                health_capacity = self.memory.read_short(OFFSET_CURRENT_HEALTH - 4)
                if health_capacity and health_capacity > 0:
                    self.memory.write_short(OFFSET_CURRENT_HEALTH, health_capacity)
                else:
                    self.memory.write_short(OFFSET_CURRENT_HEALTH, 72)
            except Exception as e:
                logger.debug(f"Cheat error (health): {e}")

        # --- Infinite Stamina ---
        if self.cheat_infinite_stamina:
            try:
                self.memory.write_int(player_base + OFFSET_STAMINA, STAMINA_FULL)
                self.memory.write_byte(player_base + OFFSET_STAMINA_EXHAUSTION_FLAG, 0)
                self.memory.write_short(player_base + OFFSET_STAMINA_RECOVERY_TIMER, 0)
            except Exception as e:
                logger.debug(f"Cheat error (stamina): {e}")

        # --- Infinite Ammo ---
        if self.cheat_infinite_ammo:
            try:
                itemflags_committed = OFFSET_SAVEFILE_A + 0x9E4
                ammo_offset_arrows_bombs = itemflags_committed + 0x70 + 0xE
                max_arrows_bombs = (10 << 7) | 20
                self.memory.write_short(ammo_offset_arrows_bombs, max_arrows_bombs)

                seed_offset = itemflags_committed + 0x70 + 0xC
                current_seed_bytes = self.memory.read_short(seed_offset)
                if current_seed_bytes is not None:
                    new_val = (current_seed_bytes & 0x7F) | (20 << 7)
                    self.memory.write_short(seed_offset, new_val)

                itemflags_uncommitted_base = OFFSET_ITEM_FLAGS_STATIC
                ammo_offset_uc = itemflags_uncommitted_base + 0x70 + 0xE
                self.memory.write_short(ammo_offset_uc, max_arrows_bombs)
                seed_offset_uc = itemflags_uncommitted_base + 0x70 + 0xC
                current_seed_uc = self.memory.read_short(seed_offset_uc)
                if current_seed_uc is not None:
                    new_val_uc = (current_seed_uc & 0x7F) | (20 << 7)
                    self.memory.write_short(seed_offset_uc, new_val_uc)
            except Exception as e:
                logger.debug(f"Cheat error (ammo): {e}")

        # --- Infinite Bugs ---
        if self.cheat_infinite_bugs:
            try:
                itemflags_base_c = OFFSET_SAVEFILE_A + 0x9E4
                itemflags_base_u = OFFSET_ITEM_FLAGS_STATIC
                for flag_id in BUG_ITEMFLAG_IDS:
                    word_idx = flag_id // 16
                    bit_idx  = flag_id % 16
                    byte_off = word_idx * 2
                    for base in (itemflags_base_c, itemflags_base_u):
                        val = self.memory.read_short(base + byte_off)
                        if val is not None and not (val & (1 << bit_idx)):
                            self.memory.write_short(base + byte_off, val | (1 << bit_idx))
            except Exception as e:
                logger.debug(f"Cheat error (bugs): {e}")

        # --- Infinite Materials ---
        if self.cheat_infinite_materials:
            try:
                itemflags_base_c = OFFSET_SAVEFILE_A + 0x9E4
                itemflags_base_u = OFFSET_ITEM_FLAGS_STATIC
                for flag_id in TREASURE_ITEMFLAG_IDS:
                    word_idx = flag_id // 16
                    bit_idx  = flag_id % 16
                    byte_off = word_idx * 2
                    for base in (itemflags_base_c, itemflags_base_u):
                        val = self.memory.read_short(base + byte_off)
                        if val is not None and not (val & (1 << bit_idx)):
                            self.memory.write_short(base + byte_off, val | (1 << bit_idx))
            except Exception as e:
                logger.debug(f"Cheat error (materials): {e}")

        # --- Infinite Shield Durability ---
        if self.cheat_infinite_shield:
            try:
                self.memory.write_short(player_base + OFFSET_SHIELD_BURN_TIMER, 0)
                shield_slot = self.memory.read_byte(OFFSET_SAVEFILE_A + OFFSET_SHIELD_POUCH_SLOT)
                if shield_slot is not None and shield_slot < 8:
                    pouch_addr = OFFSET_SAVEFILE_A + OFFSET_POUCH_ITEMS + (shield_slot * 4)
                    pouch_val = self.memory.read_int(pouch_addr)
                    if pouch_val is not None:
                        item_id = pouch_val & 0xFF
                        if item_id in SHIELD_IDS:
                            new_val = item_id | (0x30 << 16)
                            if pouch_val != new_val:
                                self.memory.write_int(pouch_addr, new_val)
            except Exception as e:
                logger.debug(f"Cheat error (shield): {e}")

        # --- Infinite Skyward Strike ---
        if self.cheat_infinite_skyward_strike:
            try:
                # skyward_strike_timer is u16 at dPlayer+0x641E (from player.rs)
                current_timer = self.memory.read_short(player_base + OFFSET_SKYWARD_STRIKE_TIMER)
                if current_timer is not None and current_timer > 0:
                    self.memory.write_short(player_base + OFFSET_SKYWARD_STRIKE_TIMER, min(SKYWARD_STRIKE_CHARGED, 0xFFFF))
            except Exception as e:
                logger.debug(f"Cheat error (skyward strike): {e}")

        # --- Infinite Rupees ---
        if self.cheat_infinite_rupees:
            try:
                itemflags_committed = OFFSET_SAVEFILE_A + 0x9E4
                rupee_offset = itemflags_committed + 0x70 + 0xA
                current_val = self.memory.read_int(rupee_offset)
                if current_val is not None:
                    max_rupees = min(9999, 0xFFFFF)
                    new_val = (current_val & 0xFFF00000) | max_rupees
                    self.memory.write_int(rupee_offset, new_val)

                rupee_offset_uc = OFFSET_ITEM_FLAGS_STATIC + 0x70 + 0xA
                current_val_uc = self.memory.read_int(rupee_offset_uc)
                if current_val_uc is not None:
                    new_val_uc = (current_val_uc & 0xFFF00000) | max_rupees
                    self.memory.write_int(rupee_offset_uc, new_val_uc)
            except Exception as e:
                logger.debug(f"Cheat error (rupees): {e}")

        # --- Moon Jump ---
        # Hold Y → lift Link upward.  Works from ground or mid-air.
        # Writing velocity_y alone doesn't work on the ground because the
        # game's ground-collision snaps Link back.  We fix this by ALSO
        # directly incrementing pos_y each tick, which physically lifts
        # Link off the surface and lets the velocity take over once airborne.
        if self.cheat_moon_jump:
            try:
                btn_held = self.memory.read_short(player_base + OFFSET_HELD_BUTTONS)

                # One-time diagnostic log
                if not self._moon_jump_logged:
                    btn_trig = self.memory.read_short(player_base + OFFSET_TRIGGERED_BUTTONS)
                    logger.debug(f"[MoonJump] held_buttons=0x{btn_held:04X}, triggered=0x{btn_trig:04X}" if btn_held is not None and btn_trig is not None else f"[MoonJump] button read returned None!")
                    logger.debug(f"[MoonJump] BUTTON_Y=0x{BUTTON_Y:04X} (CE-verified, NOT the InputMgr enum)")
                    logger.debug(f"[MoonJump] held_buttons offset=0x{player_base + OFFSET_HELD_BUTTONS:X}")
                    self._moon_jump_logged = True

                if btn_held is not None and (btn_held & BUTTON_Y):
                    # 1. Directly lift Link's position (bypasses ground collision)
                    cur_y = self.memory.read_float(player_base + OFFSET_POS_Y)
                    if cur_y is not None:
                        new_y = cur_y + 1.5  # ~90 units/sec at 60 Hz
                        self.memory.write_float(player_base + OFFSET_POS_Y, new_y)
                    # 2. Also set upward velocity for smooth motion once airborne
                    self.memory.write_float(player_base + OFFSET_VELOCITY_Y, 52.5)
            except Exception as e:
                logger.warning(f"Cheat error (moon_jump): {e}")

        # --- Infinite Beetle Flying Time ---
        if self.cheat_infinite_beetle and not self.beetle_patch_applied:
            try:
                current_instruction = self.memory.read_int(OFFSET_BEETLE_TIMER_INSTRUCTION)
                if current_instruction is not None and current_instruction != BEETLE_TIMER_PATCHED_VALUE:
                    success = self.memory.write_int(OFFSET_BEETLE_TIMER_INSTRUCTION, BEETLE_TIMER_PATCHED_VALUE)
                    if success:
                        self.beetle_patch_applied = True
                        logger.debug("Beetle time patch applied (ARM64 code patch at +0x279CE4)")
                elif current_instruction == BEETLE_TIMER_PATCHED_VALUE:
                    self.beetle_patch_applied = True
            except Exception as e:
                logger.debug(f"Cheat error (beetle): {e}")

        # --- Infinite Loftwing Charges ---
        if self.cheat_infinite_loftwing:
            try:
                self.memory.write_byte(OFFSET_LOFTWING_CHARGE_A, LOFTWING_MAX_CHARGES)
                self.memory.write_byte(OFFSET_LOFTWING_CHARGE_B, LOFTWING_MAX_CHARGES)
            except Exception as e:
                logger.debug(f"Cheat error (loftwing): {e}")

        # --- Speed Multiplier ---
        if self.cheat_speed_multiplier != 1.0:
            try:
                current_speed = self.memory.read_float(player_base + OFFSET_FORWARD_SPEED)
                if current_speed is not None and current_speed > 0.1:
                    if self.default_forward_speed is None:
                        self.default_forward_speed = current_speed
                    if self.default_forward_speed and current_speed <= self.default_forward_speed * 1.1:
                        new_speed = current_speed * self.cheat_speed_multiplier
                        self.memory.write_float(player_base + OFFSET_FORWARD_SPEED, new_speed)
            except Exception as e:
                logger.debug(f"Cheat error (speed): {e}")

    # ================================================================
    # AP Memory Buffers: Item Info Table + Check Stats
    # ================================================================

    # Maximum distance from the game base address that a subsdk8 static can
    # reasonably be.  Anything further is almost certainly a false positive.
    _MAX_BUFFER_DISTANCE = 0x200000000  # 8 GB

    def _validate_buffer_address(self, addr: int, magic_bytes: bytes, name: str) -> bool:
        """
        Validate that *addr* is a plausible location for the named Rust
        static buffer.  Checks proximity to the game base address, readback
        of the magic bytes, and (for AP_ITEM_INFO_TABLE) structural checks
        plus the adjacent AP_CHECK_STATS signature.
        """
        base = self.memory.base_address

        # 1. Proximity: subsdk8 statics are in the same virtual memory region
        #    as the main game binary.  Reject addresses that are absurdly far.
        if abs(addr - base) > self._MAX_BUFFER_DISTANCE:
            return False

        # 2. Readback: confirm the magic is still present at that address.
        try:
            readback = self.memory.pm.read_bytes(addr, len(magic_bytes))
            if readback != magic_bytes:
                return False
        except Exception:
            return False

        # 3. Structural validation specific to each buffer.
        if name == "AP_ITEM_INFO_TABLE":
            return self._validate_ap_item_table(addr)
        if name == "AP_CHECK_STATS":
            return self._validate_ap_check_stats(addr)

        return True

    def _validate_ap_item_table(self, addr: int) -> bool:
        """Extra validation for an AP_ITEM_INFO_TABLE candidate."""
        try:
            # Read header (8 bytes) + first entry flag_id (2 bytes)
            header = self.memory.pm.read_bytes(addr, 10)

            # count (u16 at offset 4) must be <= 512
            count = int.from_bytes(header[4:6], 'little')
            if count > 512:
                return False

            # _pad (u16 at offset 6) must be 0
            pad = int.from_bytes(header[6:8], 'little')
            if pad != 0:
                return False

            # First entry flag_id: if count==0, should be 0xFFFF (uninit);
            # if count>0, should be a valid id (< 1024) or 0xFFFF.
            flag0 = int.from_bytes(header[8:10], 'little')
            if count == 0 and flag0 != 0xFFFF:
                return False
            if count > 0 and flag0 > 1023 and flag0 != 0xFFFF:
                return False

            # Strongest check: AP_CHECK_STATS magic should be exactly 12 bytes
            # before this address (they are adjacent in the subsdk8 binary).
            cs_magic = bytes([0x43, 0x53, 0x00, 0x01])
            try:
                probe = self.memory.pm.read_bytes(addr - 12, 4)
                if probe == cs_magic:
                    return True  # Very high confidence
            except Exception:
                pass

            # Even without the adjacent check, the structural checks passed.
            # Accept it with medium confidence.
            return True
        except Exception:
            return False

    def _validate_ap_check_stats(self, addr: int) -> bool:
        """Extra validation for an AP_CHECK_STATS candidate."""
        try:
            # Read the full struct (12 bytes): magic (4) + 4 u16s (8).
            data = self.memory.pm.read_bytes(addr, 12)

            # Each stat u16 should be reasonable (< 2000 locations).
            for i in range(4, 12, 2):
                val = int.from_bytes(data[i:i+2], 'little')
                if val > 2000:
                    return False

            # Bonus: AP_ITEM_INFO_TABLE magic should be at +12.
            it_magic = bytes([0x49, 0x54, 0x00, 0x01])
            try:
                probe = self.memory.pm.read_bytes(addr + 12, 4)
                if probe == it_magic:
                    return True  # Very high confidence
            except Exception:
                pass

            return True
        except Exception:
            return False

    def _scan_for_buffer(self, magic_bytes: bytes, name: str) -> Optional[int]:
        """
        Find a Rust static buffer with the given magic signature.
        
        First checks addresses collected during the base-address memory scan
        (prescan_results) so this is typically instantaneous.  Falls back to
        a full pattern_scan_all only if the prescan didn't find anything.
        
        All candidates are validated for proximity to the game base address
        and structural correctness to filter out false positives.
        
        Returns:
            Offset from base address if found, None otherwise.
        """
        if not self.memory.connected or not self.memory.pm or not self.memory.base_address:
            return None
        
        base = self.memory.base_address
        
        # --- Fast path: use addresses cached during the base-address scan ---
        cached = self.memory.prescan_results.get(name, [])
        if cached:
            # Sort by proximity — the closest valid hit is most likely correct.
            for addr in sorted(cached, key=lambda a: abs(a - base)):
                if self._validate_buffer_address(addr, magic_bytes, name):
                    offset = addr - base
                    logger.debug(f"Found {name} at 0x{addr:X} (offset 0x{offset:X}) [prescan cache]")
                    return offset
        
        # --- Derive from adjacent buffer (AP_CHECK_STATS ↔ AP_ITEM_INFO_TABLE) ---
        derived_addr = self._derive_from_adjacent(name)
        if derived_addr is not None:
            if self._validate_buffer_address(derived_addr, magic_bytes, name):
                offset = derived_addr - base
                logger.info(f"Found {name} at 0x{derived_addr:X} (offset 0x{offset:X}) [derived from adjacent buffer]")
                return offset
        
        # --- Slow path: fall back to full process scan ---
        # Use a negative cache to avoid running this expensive scan every cycle
        # when the prescan didn't find anything (which is the expected case when
        # the base address is a false positive).
        now = time.time()
        last_miss = self.memory._scan_negative_cache.get(name, 0.0)
        if now - last_miss < self.memory.SCAN_NEGATIVE_CACHE_SECS:
            return None  # Too soon since last failed scan

        logger.debug(f"Prescan cache miss for {name}, doing full pattern scan...")
        try:
            from pymem import pattern
            found = pattern.pattern_scan_all(self.memory.pm.process_handle, magic_bytes)
            if found:
                addresses = found if isinstance(found, list) else [found]
                # Sort by proximity to base — real statics are in the same
                # virtual memory region, whereas false positives tend to be
                # far away (e.g. in other heap allocations).
                addresses.sort(key=lambda a: abs(a - base))
                for addr in addresses:
                    if self._validate_buffer_address(addr, magic_bytes, name):
                        offset = addr - base
                        logger.debug(f"Found {name} at 0x{addr:X} (offset 0x{offset:X}) [full scan]")
                        return offset
                # Log rejection for debugging
                logger.warning(
                    f"pattern_scan_all found {len(addresses)} hit(s) for {name} "
                    f"but none passed validation (closest: 0x{addresses[0]:X}, "
                    f"distance: 0x{abs(addresses[0] - base):X})"
                )
        except ImportError:
            logger.warning(f"pymem pattern scanning not available for {name}")
        except Exception as e:
            logger.warning(f"Pattern scan for {name} failed: {e}")
        
        # Record this miss so we don't rescan again for SCAN_NEGATIVE_CACHE_SECS
        self.memory._scan_negative_cache[name] = now
        logger.warning(f"Could not find {name} buffer in memory")
        return None

    def _derive_from_adjacent(self, name: str) -> Optional[int]:
        """
        Attempt to derive a buffer address from a known adjacent buffer.
        AP_CHECK_STATS and AP_ITEM_INFO_TABLE are exactly 12 bytes apart
        in the subsdk8 binary (AP_CHECK_STATS first, then AP_ITEM_INFO_TABLE).
        """
        if name == "AP_ITEM_INFO_TABLE":
            # Try to derive from AP_CHECK_STATS (which is 12 bytes before).
            if self._ap_check_stats_offset is not None:
                cs_addr = self.memory.base_address + self._ap_check_stats_offset
                return cs_addr + 12
            # Also try prescan hits for AP_CHECK_STATS
            for cs_addr in self.memory.prescan_results.get("AP_CHECK_STATS", []):
                it_addr = cs_addr + 12
                try:
                    probe = self.memory.pm.read_bytes(it_addr, 4)
                    if probe == bytes([0x49, 0x54, 0x00, 0x01]):
                        return it_addr
                except Exception:
                    continue
        elif name == "AP_CHECK_STATS":
            # Try to derive from AP_ITEM_INFO_TABLE (which is 12 bytes after).
            if self._ap_item_info_offset is not None:
                it_addr = self.memory.base_address + self._ap_item_info_offset
                return it_addr - 12
        return None

    def _write_ap_item_info_table(self):
        """
        Write the AP item info table to game memory so the Rust code can
        display the actual item name and player name when item 216 is picked up.
        
        Called once after connecting (when both slot_data and memory are available).
        
        Table layout (packed, little-endian):
          offset 0: magic [u8; 4] = "IT\\x00\\x01"
          offset 4: count (u16)
          offset 6: _pad (u16)
          offset 8: entries[0..512], each 98 bytes:
            flag_id (u16) + item_name ([u16; 32] = 64 bytes) + player_name ([u16; 16] = 32 bytes)
        
        IMPORTANT: Entries are written BEFORE count to avoid a race condition.
        The Rust lookup_ap_item_index() uses count to determine how many entries
        to scan.  If we wrote count first, the game could read a non-zero count
        while entries are still 0xFFFF (empty sentinel), causing the lookup to
        miss and fall back to the default "AP Item / another player" text.
        Writing entries first, then count last, ensures the game never sees a
        non-zero count with uninitialised entries.
        """
        if self._ap_item_info_written or not self.ap_item_info:
            return
        
        if not self.memory.connected or not self.memory.pm or not self.memory.base_address:
            return
        
        # Find the buffer address (scan once)
        if self._ap_item_info_offset is None:
            self._ap_item_info_offset = self._scan_for_buffer(
                bytes([0x49, 0x54, 0x00, 0x01]), "AP_ITEM_INFO_TABLE"
            )
        
        if self._ap_item_info_offset is None:
            return
        
        try:
            base = self.memory.base_address
            table_addr = base + self._ap_item_info_offset
            
            # Build entry data
            entries = []
            for flag_id, info in self.ap_item_info.items():
                item_name = info.get("item", "AP Item")
                player_name = info.get("player", "another player")
                
                # Encode as UTF-16LE, truncate to fit, null-terminate
                item_name_bytes = item_name.encode('utf-16-le')[:62]   # max 31 chars (62 bytes)
                item_name_bytes = item_name_bytes.ljust(64, b'\x00')   # pad to 64 bytes (32 u16s)
                
                player_name_bytes = player_name.encode('utf-16-le')[:30]  # max 15 chars (30 bytes)
                player_name_bytes = player_name_bytes.ljust(32, b'\x00')  # pad to 32 bytes (16 u16s)
                
                entry = struct.pack('<H', flag_id) + item_name_bytes + player_name_bytes
                entries.append(entry)
            
            count = min(len(entries), 512)
            
            # Write entries FIRST (offset +8, each 98 bytes)
            # This must happen before writing count to avoid a race where the
            # game sees count > 0 but entries are still uninitialised (0xFFFF).
            for i in range(count):
                entry_addr = table_addr + 8 + (i * 98)
                self.memory.pm.write_bytes(entry_addr, entries[i], len(entries[i]))
            
            # Write count field LAST (offset +4, skip magic)
            # Now the game can safely scan entries[0..count].
            count_data = struct.pack('<HH', count, 0)  # count + padding
            self.memory.pm.write_bytes(table_addr + 4, count_data, len(count_data))
            
            self._ap_item_info_written = True
            logger.debug(f"Wrote {count} AP item info entries to game memory")
            
        except Exception as e:
            logger.warning(f"Failed to write AP item info table: {e}")

    def _update_ap_check_stats(self):
        """
        Write current location check statistics to game memory for the help menu.
        
        Stats layout (packed, little-endian):
          offset 0: magic [u8; 4] = "CS\\x00\\x01"
          offset 4: normal_checked (u16)
          offset 6: normal_total (u16)
          offset 8: ap_checked (u16)
          offset 10: ap_total (u16)
        """
        if not self.memory.connected or not self.memory.pm or not self.memory.base_address:
            return
        
        if not self.custom_flag_to_location:
            return  # No location data yet
        
        # Find the buffer address (scan once)
        if self._ap_check_stats_offset is None:
            self._ap_check_stats_offset = self._scan_for_buffer(
                bytes([0x43, 0x53, 0x00, 0x01]), "AP_CHECK_STATS"
            )
        
        if self._ap_check_stats_offset is None:
            return
        
        try:
            # Count totals
            total_locations = len(self.custom_flag_to_location)
            ap_total = len(self.ap_location_codes)
            normal_total = total_locations - ap_total
            
            # Count checked locations (union of checked + sent to handle reconnects)
            all_checked = self.checked_locations | self.sent_locations
            ap_checked = len(self.ap_location_codes & all_checked)
            total_checked = 0
            for flag_id, loc_code in self.custom_flag_to_location.items():
                if loc_code in all_checked:
                    total_checked += 1
            normal_checked = total_checked - ap_checked
            
            # Write stats (offset +4, skip magic)
            stats_addr = self.memory.base_address + self._ap_check_stats_offset + 4
            stats_data = struct.pack('<HHHH', normal_checked, normal_total, ap_checked, ap_total)
            self.memory.pm.write_bytes(stats_addr, stats_data, len(stats_data))
            
        except Exception as e:
            logger.debug(f"Failed to update AP check stats: {e}")

    async def check_custom_flags(self):
        """Check custom flags for location completion (SSHD-specific)."""
        if not self.memory.connected or not self.memory.base_address:
            return
        
        # Custom flags use the game's sceneflag/dungeonflag system
        # Each flag is a single bit that gets set when a location is checked
        # The mapping from flag ID to location code is provided in slot_data
        
        # Flags are stored as [[u16; 8]; 26] - 26 scenes, each with 8 u16 values (16 bytes per scene)
        # We use 4 specific scenes for custom flags (scenes 6, 13, 16, 19)
        
        # OPTIMIZATION: Batch-read entire scenes instead of individual flags
        # This reduces 911 individual memory reads to just 8 batch reads (4 scenes × 2 flag types)
        
        if not hasattr(self, '_flag_check_count'):
            self._flag_check_count = 0
        self._flag_check_count += 1
        
        # Cache for scene data to avoid re-reading the same scene multiple times
        scene_cache = {}
        
        for flag_id, location_code in self.custom_flag_to_location.items():
            # Skip if already checked
            if location_code in self.checked_locations:
                continue
            
            # Unpack the custom flag encoding from item.rs logic
            # The flag_id encodes: scene index (bits 7-8), flag number (bits 0-6), flag space (bit 9)
            #
            # Encoding:
            # - Bits 0-6 (0x7F): flag number within the scene (0-127, but we skip 0x7F)
            # - Bits 7-8: scene index selector (0-3, maps to scenes 6, 13, 16, 19)
            # - Bit 9: flag_space_trigger (0=sceneflag, 1=dungeonflag)
            
            flag_num = flag_id & 0x7F  # Lower 7 bits
            scene_idx_raw = (flag_id >> 7) & 0x03  # Bits 7-8
            flag_space_trigger = (flag_id >> 9) & 0x01  # Bit 9
            
            # Transform scene index - these are the actual scene indices in the 26-scene array
            scene_idx_map = {0: 6, 1: 13, 2: 16, 3: 19}
            sceneindex = scene_idx_map.get(scene_idx_raw, 6)
            
            # Calculate u16 position and bit position within that u16
            # Each u16 holds 16 flags (bits 0-15)
            upper_flag = flag_num // 16  # Which u16 in the scene's 8 u16s (0-7)
            lower_flag = flag_num % 16   # Which bit in that u16 (0-15)
            
            # Validate bounds
            if upper_flag > 7:
                logger.error(f"Invalid flag {flag_id}: upper_flag={upper_flag} exceeds array bounds (max 7)")
                continue
            
            try:
                # OPTIMIZATION: Use cached scene data if available
                scene_key = (flag_space_trigger, sceneindex)
                
                if scene_key not in scene_cache:
                    # Batch-read the entire scene (16 bytes = 8 u16 values)
                    file_a_offset = OFFSET_SAVEFILE_A
                    
                    # DEBUG: Log addresses on first custom flag check
                    if not hasattr(self, '_logged_addresses'):
                        logger.debug(f"[DEBUG] Base address: 0x{self.memory.base_address:X}")
                        logger.debug(f"[DEBUG] SaveFile FA offset: 0x{file_a_offset:X}")
                        logger.debug(f"[DEBUG] Sceneflags offset within FA: 0x{OFFSET_FA_SCENEFLAGS:X}")
                        logger.debug(f"[DEBUG] Dungeonflags offset within FA: 0x{OFFSET_FA_DUNGEONFLAGS:X}")
                        logger.debug(f"[Optimization] Batch-reading flag scenes for {len(self.custom_flag_to_location)} locations")
                        logger.debug(f"[FlagInit] Initializing previous_custom_flags to prevent false positives...")
                        self._logged_addresses = True
                        # Initialize previous_custom_flags on first poll to prevent treating
                        # already-set flags as new location checks
                        self._initializing_flags = True
                    
                    # Calculate base offset for this flag type
                    if flag_space_trigger == 0:
                        flags_base_offset = file_a_offset + OFFSET_FA_SCENEFLAGS
                    else:
                        flags_base_offset = file_a_offset + OFFSET_FA_DUNGEONFLAGS
                    
                    # Calculate scene base offset
                    scene_offset = flags_base_offset + (sceneindex * 16)
                    
                    # Batch-read all 16 bytes (8 u16 values) for this scene at once
                    scene_data = self.memory.read_bytes(scene_offset, 16)
                    
                    if scene_data and len(scene_data) == 16:
                        # Parse into 8 u16 values (little-endian)
                        scene_u16s = [
                            int.from_bytes(scene_data[i:i+2], byteorder='little')
                            for i in range(0, 16, 2)
                        ]
                        scene_cache[scene_key] = scene_u16s
                    else:
                        scene_cache[scene_key] = None
                
                # Get the u16 value from cache
                scene_u16s = scene_cache.get(scene_key)
                if scene_u16s is not None and upper_flag < len(scene_u16s):
                    current_u16 = scene_u16s[upper_flag]
                    # Check if the specific bit is set
                    flag_state = (current_u16 >> lower_flag) & 0x1
                    previous_state = self.previous_custom_flags.get(flag_id, 0)
                    
                    # Debug logging for first few flags to verify state tracking
                    if not hasattr(self, '_debug_log_count'):
                        self._debug_log_count = 0
                    if flag_state == 1 and self._debug_log_count < 5:
                        location_name = self.location_names.lookup_in_slot(location_code, self.slot)
                        logger.debug(f"[StateDebug] {location_name}: flag_state={flag_state}, previous_state={previous_state}, flag_id={flag_id}")
                        self._debug_log_count += 1
                    
                    # Only check locations if we're NOT initializing (to prevent false positives)
                    if hasattr(self, '_initializing_flags') and self._initializing_flags:
                        # First poll: just record current state, don't check locations
                        self.previous_custom_flags[flag_id] = flag_state
                        # Log initialization of already-set flags
                        if flag_state == 1 and len(self.previous_custom_flags) < 20:
                            location_name = self.location_names.lookup_in_slot(location_code, self.slot)
                            logger.debug(f"[Init] Capturing already-set flag: {location_name} (scene={sceneindex}, flag={lower_flag})")
                    elif flag_state == 1 and previous_state == 0:
                        # Flag was just set - location completed!
                        self.checked_locations.add(location_code)
                        # Get location name for logging
                        location_name = self.location_names.lookup_in_slot(location_code, self.slot)
                        flag_type = "Scene" if flag_space_trigger == 0 else "Dungeon"
                        logger.debug(f"Location checked: {location_name}")
                        logger.debug(f"   Flag details: type={flag_type}, scene={sceneindex}, flag={lower_flag}, u16=0x{current_u16:04X}, bit={lower_flag}")
                        logger.debug(f"   Previous was {previous_state}, now is {flag_state}")
                        
                        # Update tracker with new location
                        self.update_tracker_state()
                        self.previous_custom_flags[flag_id] = flag_state
                    elif flag_state == 1 and previous_state == 1:
                        # Flag is set but was already set - this should NOT trigger a check
                        # Log if this happens early on (potential false positive detection)
                        if not hasattr(self, '_flag_already_set_logged'):
                            self._flag_already_set_logged = set()
                        if flag_id not in self._flag_already_set_logged and len(self._flag_already_set_logged) < 10:
                            location_name = self.location_names.lookup_in_slot(location_code, self.slot)
                            logger.debug(f"[StateCheck] Flag already set in both states: {location_name} (prev=1, curr=1)")
                            self._flag_already_set_logged.add(flag_id)
                        # Keep previous state (already correct)
                    else:
                        # Normal state tracking (flag is 0 or unchanged)
                        self.previous_custom_flags[flag_id] = flag_state
                
            except Exception as e:
                # Suppress repeated errors for the same scene to avoid log spam
                if not hasattr(self, '_error_suppression'):
                    self._error_suppression = {}
                scene_key = (flag_space_trigger, sceneindex)
                if scene_key not in self._error_suppression:
                    logger.error(f"Error reading custom flags from scene {sceneindex} (type {flag_space_trigger}): {e}")
                    self._error_suppression[scene_key] = True
        
        # Clear initialization flag after first complete poll (outside the loop)
        if hasattr(self, '_initializing_flags') and self._initializing_flags:
            self._initializing_flags = False
            initialized_count = len(self.previous_custom_flags)
            # Count how many flags are already set
            already_set = sum(1 for v in self.previous_custom_flags.values() if v == 1)
            logger.debug(f"[FlagInit] Initialized {initialized_count} custom flags - now monitoring for changes")
            logger.debug(f"[FlagInit] {already_set} flags were already set in save file")
    
    async def check_goddess_chest_flags(self):
        """
        Detect goddess chest opens by polling the vanilla set_sceneflag values.

        Goddess chests cannot use the normal custom-flag pathway because writing
        a custom flag to params2 bits 8-17 overwrites the goddess cube storyflag
        encoding and breaks the spawn gate.  Instead, when the player opens a
        goddess chest the game engine itself sets a local scene flag
        (set_sceneflag from anglex & 0xFF).  We read those flags from the save
        file's scene flag array [[u16; 8]; 26].

        The mapping location_code → [scene_index, set_sceneflag] is provided
        by fill_slot_data → goddess_chest_scene_flags.
        """
        if not self.memory.connected or not self.memory.base_address:
            return
        if not self.goddess_chest_scene_flags:
            return

        # Track initialisation similarly to check_custom_flags
        if not hasattr(self, '_goddess_flags_initializing'):
            self._goddess_flags_initializing = True

        file_a_offset = OFFSET_SAVEFILE_A
        flags_base = file_a_offset + OFFSET_FA_SCENEFLAGS

        # Cache per-scene reads so each scene is only read once per tick
        scene_cache: Dict[int, Optional[list]] = {}

        for location_code, (scene_index, set_sceneflag) in self.goddess_chest_scene_flags.items():
            if location_code in self.checked_locations:
                continue

            # Batch-read the 16 bytes for this scene on first access
            if scene_index not in scene_cache:
                scene_offset = flags_base + (scene_index * 16)
                try:
                    scene_data = self.memory.read_bytes(scene_offset, 16)
                    if scene_data and len(scene_data) == 16:
                        scene_cache[scene_index] = [
                            int.from_bytes(scene_data[i:i+2], byteorder='little')
                            for i in range(0, 16, 2)
                        ]
                    else:
                        scene_cache[scene_index] = None
                except Exception:
                    scene_cache[scene_index] = None

            scene_u16s = scene_cache.get(scene_index)
            if scene_u16s is None:
                continue

            u16_index = set_sceneflag // 16
            bit_index = set_sceneflag % 16
            if u16_index >= 8:
                continue

            flag_state = (scene_u16s[u16_index] >> bit_index) & 1
            previous = self.previous_goddess_flags.get(location_code, 0)

            if self._goddess_flags_initializing:
                # First poll: snapshot current state to avoid false positives
                self.previous_goddess_flags[location_code] = flag_state
            elif flag_state == 1 and previous == 0:
                # Flag just transitioned 0→1: chest was opened
                self.checked_locations.add(location_code)
                location_name = self.location_names.lookup_in_slot(location_code, self.slot)
                logger.debug(f"Goddess chest checked: {location_name}")
                logger.debug(f"   scene={scene_index}, flag={set_sceneflag}, "
                             f"u16[{u16_index}]=0x{scene_u16s[u16_index]:04X}, bit={bit_index}")
                self.update_tracker_state()
                self.previous_goddess_flags[location_code] = flag_state
            else:
                self.previous_goddess_flags[location_code] = flag_state

        # End initialisation after first complete scan
        if self._goddess_flags_initializing:
            self._goddess_flags_initializing = False
            already_set = sum(1 for v in self.previous_goddess_flags.values() if v == 1)
            logger.debug(f"[GoddessInit] Initialized {len(self.previous_goddess_flags)} goddess chest flags "
                         f"({already_set} already set)")

    async def check_beedle_shop_storyflags(self):
        """
        Detect Beedle's Airshop purchases by monitoring multiple signal sources:
        
        1. MSBF-injected storyflags (1950-1962) - set_storyflag commands injected
           into 105-Terry.msbf purchase flows at build time, after the start node.
        2. Vanilla sold_out storyflags from SHOP_ITEMS[N]+0x52 (813-944) - set by
           the Rust ASM hooks if they fire.
        3. SHOP_ITEMS entry byte-level diffs - detects any field change in entries.
        
        Storyflags: stored as [u16; 128]. Storyflag N -> word[N//16] bit (N%16).
        """
        if not self.memory.connected or not self.memory.base_address:
            return
        
        # ── One-time initialisation ──────────────────────────────────
        if not hasattr(self, '_prev_beedle_flags'):
            self._prev_beedle_flags = {}
            self._beedle_flags_initializing = True
            self._fa_storyflag_snapshot = None
            self._static_storyflag_snapshot = None
            self._beedle_dynamic_map = {}           # storyflag -> location_name
            self._shop_entry_snapshots = {}         # idx -> bytes (0x54 per entry)
            
            abs_fa = self.memory.base_address + OFFSET_SAVEFILE_A + OFFSET_FA_STORYFLAGS
            abs_static = self.memory.base_address + OFFSET_STORY_FLAGS_STATIC
            logger.debug(f"[Beedle] FA Storyflags : 0x{abs_fa:X}")
            logger.debug(f"[Beedle] STATIC Storyflags: 0x{abs_static:X}")
            logger.debug(f"[Beedle] (base=0x{self.memory.base_address:X})")
            
            # ---- Build storyflag -> location mapping from SHOP_ITEMS ----
            logger.debug("[Beedle] Reading SHOP_ITEMS for Beedle items (indices 20-29)...")
            try:
                for idx in range(20, 30):
                    location = SHOP_INDEX_TO_LOCATION.get(idx)
                    if not location:
                        continue
                    
                    # Read sold_out_storyflag (+0x52)
                    sf_offset = OFFSET_SHOP_ITEMS + idx * SHOP_ITEM_SIZE + SHOP_ITEM_SOLD_OUT_SF_FIELD
                    sf_data = self.memory.read_bytes(sf_offset, 2)
                    sold_out_sf = int.from_bytes(sf_data, 'little') if sf_data and len(sf_data) == 2 else 0
                    
                    # Read event_entrypoint (+0x10)
                    ep_offset = OFFSET_SHOP_ITEMS + idx * SHOP_ITEM_SIZE + SHOP_ITEM_EVENT_EP_FIELD
                    ep_data = self.memory.read_bytes(ep_offset, 2)
                    ep_val = int.from_bytes(ep_data, 'little') if ep_data and len(ep_data) == 2 else 0
                    
                    # Convert entrypoint to FEN1 name and look up MSBF-injected storyflag
                    ep_str = str(ep_val)
                    fen1_name = f"{ep_str[:3]}_{ep_str[3:]}" if len(ep_str) >= 4 else None
                    msbf_sf = BEEDLE_PURCHASE_STORYFLAGS.get(fen1_name) if fen1_name else None
                    
                    # Map BOTH storyflag sources to this location
                    if sold_out_sf > 0 and sold_out_sf != 0xFFFF:
                        self._beedle_dynamic_map[sold_out_sf] = location
                    if msbf_sf:
                        self._beedle_dynamic_map[msbf_sf] = location
                    
                    logger.debug(f"[Beedle] SHOP_ITEMS[{idx}] ep={ep_val} fen1={fen1_name} "
                                f"msbf_sf={msbf_sf} sold_out_sf={sold_out_sf} -> {location}")
                    
                    # Read full entry for byte-level diffing
                    entry_offset = OFFSET_SHOP_ITEMS + idx * SHOP_ITEM_SIZE
                    entry_data = self.memory.read_bytes(entry_offset, SHOP_ITEM_SIZE)
                    if entry_data and len(entry_data) == SHOP_ITEM_SIZE:
                        self._shop_entry_snapshots[idx] = entry_data
                
                logger.debug(f"[Beedle] Dynamic mapping built: {len(self._beedle_dynamic_map)} storyflags")
                for sf, loc in sorted(self._beedle_dynamic_map.items()):
                    logger.debug(f"[Beedle]   sf{sf} -> {loc}")
                    
            except Exception as e:
                logger.warning(f"[Beedle] Failed to build dynamic mapping: {e}")
                import traceback; traceback.print_exc()
        
        # ── Read storyflag arrays ────────────────────────────────────
        fa_storyflags_offset = OFFSET_SAVEFILE_A + OFFSET_FA_STORYFLAGS
        fa_raw = self.memory.read_bytes(fa_storyflags_offset, 256)
        static_raw = self.memory.read_bytes(OFFSET_STORY_FLAGS_STATIC, 256)
        
        # ── Diagnostic: log ANY FA storyflag changes ─────────────────
        if fa_raw and len(fa_raw) == 256:
            if self._fa_storyflag_snapshot is not None:
                for i in range(128):
                    old_val = int.from_bytes(self._fa_storyflag_snapshot[i*2:i*2+2], 'little')
                    new_val = int.from_bytes(fa_raw[i*2:i*2+2], 'little')
                    if old_val != new_val:
                        diff = old_val ^ new_val
                        changed_bits = []
                        for b in range(16):
                            if diff & (1 << b):
                                sf_num = i * 16 + b
                                was = (old_val >> b) & 1
                                now = (new_val >> b) & 1
                                changed_bits.append(f"sf{sf_num}:{was}->{now}")
                        logger.debug(f"[BeedleScan] FA storyflag u16[{i}] changed: "
                                    f"0x{old_val:04X}->0x{new_val:04X}  ({', '.join(changed_bits)})")
            self._fa_storyflag_snapshot = fa_raw
        
        # ── Diagnostic: log ANY STATIC storyflag changes ─────────────
        if static_raw and len(static_raw) == 256:
            if self._static_storyflag_snapshot is not None:
                for i in range(128):
                    old_val = int.from_bytes(self._static_storyflag_snapshot[i*2:i*2+2], 'little')
                    new_val = int.from_bytes(static_raw[i*2:i*2+2], 'little')
                    if old_val != new_val:
                        diff = old_val ^ new_val
                        changed_bits = []
                        for b in range(16):
                            if diff & (1 << b):
                                sf_num = i * 16 + b
                                was = (old_val >> b) & 1
                                now = (new_val >> b) & 1
                                changed_bits.append(f"sf{sf_num}:{was}->{now}")
                        logger.debug(f"[BeedleScan] STATIC storyflag u16[{i}] changed: "
                                    f"0x{old_val:04X}->0x{new_val:04X}  ({', '.join(changed_bits)})")
            self._static_storyflag_snapshot = static_raw
        
        # ── Diagnostic: SHOP_ITEMS byte-level diff ───────────────────
        for idx in range(20, 30):
            entry_offset = OFFSET_SHOP_ITEMS + idx * SHOP_ITEM_SIZE
            entry_data = self.memory.read_bytes(entry_offset, SHOP_ITEM_SIZE)
            if entry_data and len(entry_data) == SHOP_ITEM_SIZE:
                old_data = self._shop_entry_snapshots.get(idx)
                if old_data and old_data != entry_data:
                    # Find changed bytes
                    changes = []
                    for off in range(SHOP_ITEM_SIZE):
                        if old_data[off] != entry_data[off]:
                            changes.append(f"+0x{off:02X}:0x{old_data[off]:02X}->0x{entry_data[off]:02X}")
                    location = SHOP_INDEX_TO_LOCATION.get(idx, "?")
                    logger.debug(f"[BeedleShopItem] SHOP_ITEMS[{idx}] ({location}) bytes changed: {', '.join(changes)}")
                self._shop_entry_snapshots[idx] = entry_data
        
        # ── Check mapped storyflags for purchases ────────────────────
        for storyflag_num, location_name in self._beedle_dynamic_map.items():
            if location_name not in LOCATION_TABLE:
                continue
            location_code = LOCATION_TABLE[location_name].code
            if location_code in self.checked_locations:
                continue
            
            u16_index = storyflag_num // 16
            bit_offset = storyflag_num % 16
            
            try:
                flag_state = 0
                source = "?"
                if fa_raw and len(fa_raw) == 256:
                    u16_val = int.from_bytes(fa_raw[u16_index*2:u16_index*2+2], 'little')
                    flag_state = (u16_val >> bit_offset) & 1
                    source = "FA"
                
                if flag_state == 0 and static_raw and len(static_raw) == 256:
                    u16_val = int.from_bytes(static_raw[u16_index*2:u16_index*2+2], 'little')
                    flag_state = (u16_val >> bit_offset) & 1
                    source = "STATIC"
                
                prev_state = self._prev_beedle_flags.get(storyflag_num, 0)
                
                if self._beedle_flags_initializing:
                    self._prev_beedle_flags[storyflag_num] = flag_state
                    if flag_state == 1:
                        if location_code not in self.checked_locations:
                            self.checked_locations.add(location_code)
                            logger.debug(f"[BeedleInit] Recovering: {location_name} (sf{storyflag_num}, {source})")
                elif flag_state == 1 and prev_state == 0:
                    self.checked_locations.add(location_code)
                    logger.debug(f"[Beedle] Location checked: {location_name} (sf{storyflag_num}, detected in {source})")
                    self.update_tracker_state()
                    self._prev_beedle_flags[storyflag_num] = flag_state
                else:
                    self._prev_beedle_flags[storyflag_num] = flag_state
                    
            except Exception as e:
                logger.debug(f"Error reading Beedle storyflag {storyflag_num}: {e}")
        
        # Clear initialization flag after first complete poll
        if self._beedle_flags_initializing:
            self._beedle_flags_initializing = False
            already_bought = sum(1 for v in self._prev_beedle_flags.values() if v == 1)
            logger.debug(f"[BeedleInit] Initialized {len(self._prev_beedle_flags)} Beedle storyflags "
                        f"({already_bought} already purchased)")
    
    async def check_all_locations(self):
        """Check all locations using LocationFlags.py data (Wii addresses - may not work on Switch)."""
        if not self.memory.connected or not self.memory.base_address:
            return
        
        for location_name, (flag_type, flag_bit, flag_value, scene_or_addr) in LOCATION_FLAG_MAP.items():
            # Get proper location ID from LOCATION_TABLE
            if location_name in LOCATION_TABLE:
                location_id = LOCATION_TABLE[location_name].code
            else:
                # Skip locations not in table
                continue
            
            # Skip if already checked
            if location_id in self.checked_locations:
                continue
            
            try:
                is_checked = False
                
                if flag_type == FLAG_STORY:
                    # Story flags use static addresses (base-relative)
                    story_addr = scene_or_addr
                    if isinstance(story_addr, int):
                        byte_val = self.memory.read_byte(story_addr)
                        if byte_val is not None:
                            is_checked = bool(byte_val & (1 << flag_bit))
                
                elif flag_type == FLAG_SCENE:
                    # Scene flags use scene name and are stored in static scene flag array
                    scene_name = scene_or_addr
                    if scene_name in SCENE_FLAG_ADDRESSES:
                        # SCENE_FLAG_ADDRESSES contains base-relative offsets, not absolute addresses
                        scene_base = SCENE_FLAG_ADDRESSES[scene_name]
                        flag_addr = scene_base + flag_bit
                        byte_val = self.memory.read_byte(flag_addr)
                        if byte_val is not None:
                            is_checked = bool(byte_val & flag_value)
                
                if is_checked:
                    self.checked_locations.add(location_id)
                    location_name_display = location_name[:50]  # Truncate long names
                    logger.info(f"Location checked: {location_name_display}")
                    
                    # Update tracker with new location
                    self.update_tracker_state()
                    
            except Exception as e:
                logger.debug(f"Error checking location {location_name}: {e}")
    
    def build_item_to_location_map(self) -> Dict[int, int]:
        """
        Build a mapping from item codes to location codes.
        
        This is built from slot_data which contains the randomized item placements.
        Each location has an item placed at it, creating the item->location relationship.
        
        Returns:
            Dictionary mapping item code -> location code
        """
        item_to_loc = {}
        
        # Check if slot_data has location placements
        if not self.slot_data:
            logger.warning("No slot_data available yet - cannot build item_to_location map")
            return item_to_loc
        
        # Try to build from location_to_item mapping in patch data
        if hasattr(self, 'location_to_item') and self.location_to_item:
            for loc_name, item_info in self.location_to_item.items():
                # Get location code from LOCATION_TABLE
                if loc_name in LOCATION_TABLE:
                    location_code = LOCATION_TABLE[loc_name].code
                    item_code = item_info.get('id') or item_info.get('code')
                    if location_code and item_code:
                        item_to_loc[item_code] = location_code
            
            if item_to_loc:
                logger.debug(f"Built item_to_location map with {len(item_to_loc)} entries from patch data")
                return item_to_loc
        
        # Alternative: Build from slot_data if it has item placements
        item_placements = self.slot_data.get('item_placements', {})
        if item_placements:
            for loc_code_str, item_code in item_placements.items():
                try:
                    loc_code = int(loc_code_str) if isinstance(loc_code_str, str) else loc_code_str
                    item_to_loc[item_code] = loc_code
                except (ValueError, TypeError):
                    continue
            
            if item_to_loc:
                logger.debug(f"Built item_to_location map with {len(item_to_loc)} entries from slot_data")
                return item_to_loc
        
        logger.debug("No item placement data found - item_to_location map is empty")
        return item_to_loc

    def check_locations(self):
        """
        Check for completed locations.
        
        NOTE: Location checking is now item-based instead of memory-based.
        When an item is given to the player via give_item_to_player(),
        the corresponding location is automatically marked as checked.
        
        This function is kept for compatibility but no longer reads memory flags
        (LocationFlags.py addresses are from Wii game and incompatible with SSHD).
        """
        # Item-based location checking is handled in give_item_to_player()
        # No additional memory-based checking needed
        pass
    
    def on_deathlink(self, data: dict):
        """
        Handle death link - kill the player when someone else dies.
        """
        self.last_death_link = max(data.get("time", 0.0), self.last_death_link)

        if not self.memory.connected or not self.memory.base_address:
            logger.warning("DeathLink: Cannot kill player - not connected to game")
            return

        source = data.get('source', 'Unknown')
        cause = data.get('cause', '') or f"{source} died"
        logger.info(f"DeathLink: {cause}")

        # Write 0 to current health to kill the player
        health_offset = OFFSET_CURRENT_HEALTH
        success = self.memory.write_short(health_offset, 0)
        if success:
            logger.info(f"DeathLink: Set health to 0 at offset 0x{health_offset:X}")
            # Set flag to prevent sending death link for this death
            self.killed_by_deathlink = True
        else:
            logger.error(f"DeathLink: Failed to write health at offset 0x{health_offset:X}")
    
    async def send_death(self, death_text: str = ""):
        """
        Send a death link notification to other players.
        """
        if "DeathLink" not in self.tags:
            return

        if self.server and self.server.socket:
            self.last_death_link = time.time()
            logger.info("DeathLink: Sending death to your friends...")
            await self.send_msgs([{
                "cmd": "Bounce",
                "tags": ["DeathLink"],
                "data": {
                    "time": self.last_death_link,
                    "source": self.auth,
                    "cause": death_text or f"{self.auth} died"
                }
            }])
    
    def on_breathlink(self, data: dict):
        """
        Handle breath link - drain the player's stamina when someone else runs out.
        Sets stamina to 0 and triggers the exhaustion state, same as the health trap
        in traps.rs.
        """
        self.last_breath_link = max(data.get("time", 0.0), self.last_breath_link)

        if not self.memory.connected or not self.memory.base_address:
            logger.warning("BreathLink: Cannot drain stamina - not connected to game")
            return

        source = data.get('source', 'Unknown')
        cause = data.get('cause', '') or f"{source} ran out of stamina"
        logger.info(f"BreathLink: {cause}")

        # Write all three stamina fields to trigger proper exhaustion
        # (same approach as the health trap in traps.rs)
        player_base = OFFSET_PLAYER

        # Set stamina_amount to 0
        s1 = self.memory.write_int(player_base + OFFSET_STAMINA, 0)
        # Set exhaustion flag (something_we_use_for_stamina) to 0x5A
        s2 = self.memory.write_byte(player_base + OFFSET_STAMINA_EXHAUSTION_FLAG, 0x5A)
        # Set stamina_recovery_timer to 64 frames (~1-2 seconds of recovery delay)
        s3 = self.memory.write_short(player_base + OFFSET_STAMINA_RECOVERY_TIMER, 64)

        if s1 and s2 and s3:
            logger.info(f"BreathLink: Drained stamina (3 fields written at player+0x{OFFSET_STAMINA:X})")
            # Set flag to prevent sending breath link for this exhaustion
            self.exhausted_by_breathlink = True
        else:
            logger.error(f"BreathLink: Failed to write stamina fields (success: amount={s1}, flag={s2}, timer={s3})")

    async def send_breathlink(self, breath_text: str = ""):
        """
        Send a breath link notification to other players.
        NOTE: The "BreathLink" tag name should be kept in sync with the SS AP (and otehr future games)
        implementation for cross-game compatibility.
        """
        if "BreathLink" not in self.tags:
            return

        if self.server and self.server.socket:
            self.last_breath_link = time.time()
            logger.info("BreathLink: Sending stamina exhaustion to other players...")
            await self.send_msgs([{
                "cmd": "Bounce",
                "tags": ["BreathLink"],
                "data": {
                    "time": self.last_breath_link,
                    "source": self.auth,
                    "cause": breath_text or f"{self.auth} ran out of stamina"
                }
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
        
        # Log task creation
        logging.info(f"GUI task created: {self.ui_task}")
        logging.info(f"UI object: {self.ui}")


def install_patch(patch_file_path: str) -> tuple[bool, dict]:
    """
    Extract and install .apsshd patch to Ryujinx mod directory.
    
    Returns (success: bool, location_to_item: dict).
    """
    import zipfile
    import json
    from pathlib import Path
    import shutil
    
    print(f"\n{'='*60}")
    print(f"Installing SSHD Archipelago Patch")
    print(f"{'='*60}")
    print(f"Patch file: {patch_file_path}")
    
    patch_path = Path(patch_file_path)
    if not patch_path.exists():
        print(f"ERROR: Patch file not found: {patch_file_path}")
        return False, {}
    
    try:
        # Extract patch file
        print(f"\nExtracting patch file...")
        with zipfile.ZipFile(patch_path, 'r') as zip_file:
            # Read manifest
            manifest = json.loads(zip_file.read("manifest.json"))
            print(f"  Game: {manifest.get('game')}")
            print(f"  Player: {manifest.get('player')}")
            print(f"  Seed: {manifest.get('seed')}")
            
            # Load patch data with location-to-item mapping
            location_to_item = {}
            if 'patch_data.json' in zip_file.namelist():
                patch_data = json.loads(zip_file.read("patch_data.json"))
                location_to_item = patch_data.get('locations', {})
                print(f"\n  Loaded {len(location_to_item)} location-to-item mappings")
            
            # Check if romfs/exefs exist
            file_list = zip_file.namelist()
            has_romfs = any(f.startswith('romfs/') for f in file_list)
            has_exefs = any(f.startswith('exefs/') for f in file_list)
            
            print(f"\nPatch contents:")
            print(f"  - manifest.json: YES")
            print(f"  - patch_data.json: YES")
            print(f"  - romfs/: {'YES' if has_romfs else 'NO'}")
            print(f"  - exefs/: {'YES' if has_exefs else 'NO'}")
            
            if not has_romfs and not has_exefs:
                print(f"\nWARNING: No game mod files found in patch!")
                print(f"This patch only contains item/location data.")
                print(f"You may need to apply the base randomizer mod manually.")
                return False
            
            # Find Ryujinx atmosphere directory for LayeredFS mods
            try:
                from platform_utils import get_ryujinx_mod_dirs
                ryujinx_paths = get_ryujinx_mod_dirs()
            except ImportError:
                # Fallback if platform_utils not available - use OS-specific paths
                if sys.platform == "win32":
                    ryujinx_paths = [
                        Path.home() / "AppData" / "Roaming" / "Ryujinx" / "sdcard" / "atmosphere" / "contents" / "01002da013484000",
                        Path(os.environ.get('APPDATA', '')) / "Ryujinx" / "sdcard" / "atmosphere" / "contents" / "01002da013484000",
                    ]
                elif sys.platform == "linux":
                    ryujinx_paths = [
                        Path.home() / ".config" / "Ryujinx" / "sdcard" / "atmosphere" / "contents" / "01002da013484000",
                    ]
                else:  # macOS
                    ryujinx_paths = [
                        Path.home() / "Library" / "Application Support" / "Ryujinx" / "sdcard" / "atmosphere" / "contents" / "01002da013484000",
                    ]
            
            ryujinx_mod_dir = None
            for path in ryujinx_paths:
                if path.parent.parent.parent.exists():  # Check if sdcard/atmosphere folder exists
                    ryujinx_mod_dir = path
                    ryujinx_mod_dir.mkdir(parents=True, exist_ok=True)
                    break
            
            if ryujinx_mod_dir:
                print(f"\nFound Ryujinx atmosphere directory: {ryujinx_mod_dir}")
                
                # Install to Archipelago folder (LayeredFS will merge with game files)
                mod_install_dir = ryujinx_mod_dir / "Archipelago"
                
                print(f"Installing to: {mod_install_dir}")
                
                # Remove existing mod if present
                if mod_install_dir.exists():
                    print(f"  Removing existing mod...")
                    shutil.rmtree(mod_install_dir)
                
                # Extract romfs and exefs
                mod_install_dir.mkdir(parents=True, exist_ok=True)
                
                for file_name in file_list:
                    if file_name.startswith('romfs/') or file_name.startswith('exefs/'):
                        # Extract to mod directory
                        target_path = mod_install_dir / file_name
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        
                        with zip_file.open(file_name) as source:
                            with open(target_path, 'wb') as target:
                                target.write(source.read())
                
                print(f"\n✓ Patch installed successfully!")
                print(f"\nNext steps:")
                print(f"  1. Launch Skyward Sword HD in Ryujinx")
                print(f"  2. The LayeredFS mod will be automatically applied")
                print(f"  3. Connect to the Archipelago server")
                return True, location_to_item
            else:
                # No Ryujinx found - extract to temp for manual install
                print(f"\nWARNING: Ryujinx installation not found automatically.")
                print(f"Extracting patch files for manual installation...")
                
                # Extract to a folder next to the patch file
                extract_dir = patch_path.parent / f"{patch_path.stem}_extracted"
                if extract_dir.exists():
                    shutil.rmtree(extract_dir)
                extract_dir.mkdir(parents=True, exist_ok=True)
                
                zip_file.extractall(extract_dir)
                
                print(f"\nExtracted to: {extract_dir}")
                print(f"\nManual installation:")
                print(f"  1. Copy the romfs/ and exefs/ folders to:")
                try:
                    from platform_utils import get_ryujinx_dir
                    ryujinx_manual_path = get_ryujinx_dir() / "sdcard" / "atmosphere" / "contents" / "01002da013484000" / "Archipelago"
                    print(f"     {ryujinx_manual_path}")
                except ImportError:
                    print(f"     %APPDATA%\\Ryujinx\\sdcard\\atmosphere\\contents\\01002da013484000\\Archipelago\\")
                print(f"  2. Launch Skyward Sword HD in Ryujinx")
                print(f"  3. The LayeredFS mod will be automatically applied")
                return False, location_to_item
                
    except Exception as e:
        print(f"\nERROR: Failed to install patch: {e}")
        import traceback
        traceback.print_exc()
        return False, {}


async def main(args=None):
    """
    Main entry point for the SSHD client.
    """
    import colorama
    
    print("="*60)
    print("Skyward Sword HD Archipelago Client")
    print("  Build: [BETA] 0.7.0")
    print("="*60)
    print(f"Starting client...")
    print(f"Arguments: {args}")
    
    parser = get_base_parser(description="Skyward Sword HD Client for Archipelago with Ryujinx support.")
    parser.add_argument('diff_file', default="", type=str, nargs="?",
                        help='Path to an Archipelago Binary Patch file (.apsshd)')
    parsed_args = parser.parse_args(args)
    
    # Install patch if provided and get location mapping
    location_to_item = {}
    if parsed_args.diff_file:
        patch_file = parsed_args.diff_file
        print(f"\nPatch file provided: {patch_file}")
        if patch_file.endswith('.apsshd'):
            success, location_to_item = install_patch(patch_file)
            if not success:
                print("ERROR: Failed to install patch")
                return
            print(f"\n" + "="*60)
            print(f"Continuing to launch client...")
            print(f"="*60 + "\n")
        else:
            print(f"WARNING: Expected .apsshd file, got {patch_file}")
    
    print(f"Parsed arguments: {parsed_args}")
    
    # Enable GUI when available (Archipelago launcher has all GUI dependencies)
    use_gui = gui_enabled
    print(f"GUI enabled: {use_gui}")
    
    colorama.init()
    
    # Create context (requires event loop to already be running)
    ctx = SSHDContext(parsed_args.connect, parsed_args.password)
    ctx.location_to_item = location_to_item  # Set mapping loaded from patch
    
    ctx.server_task = asyncio.create_task(server_loop(ctx), name="ServerLoop")
    
    # Add Ryujinx connection task
    ctx.ryujinx_task = asyncio.create_task(ctx.ryujinx_connection_task(), name="Ryujinx Connection")

    # Add dedicated high-frequency cheat loop (~60 Hz)
    ctx.cheat_task = asyncio.create_task(ctx.cheat_loop_task(), name="Cheat Loop")
    
    if use_gui:
        print("Launching GUI...")
        ctx.run_gui()
        # Give the GUI task a chance to start and build the interface
        await asyncio.sleep(0.1)
    else:
        ctx.run_cli()
    
    print("Client initialized. Waiting for connection...")
    
    # Wait for exit event (set when GUI window closes or user exits)
    await ctx.exit_event.wait()
    
    print("Exit event received, shutting down...")
    
    # Cleanup
    ctx.server_address = None


if __name__ == "__main__":
    import colorama
    logging.basicConfig(
        format="[%(name)s]: %(message)s",
        level=logging.DEBUG  # Allow debug messages in terminal
    )
    
    # Add filter to hide debug messages from GUI (they'll still show in terminal)
    class DebugToTerminalOnly(logging.Filter):
        """Filter that marks debug log records to skip GUI output"""
        def filter(self, record):
            # Mark debug-level messages to skip the GUI
            if record.levelno == logging.DEBUG:
                record.skip_gui = True
            return True  # Always allow the record through (for terminal)
    
    # Apply the filter to the root logger so all loggers inherit it
    logging.getLogger().addFilter(DebugToTerminalOnly())
    
    colorama.just_fix_windows_console()
    asyncio.run(main())
    colorama.deinit()
