"""
SSHD Archipelago - Game Item System Integration

This module provides integration with the sshd-rando backend's item spawning system
to enable proper item-get animations and models instead of direct memory writes.

Key Features:
- Uses game's native give_item() function
- Shows item-get animations (Link holding up item)
- Displays 3D item models
- Plays appropriate jingles/fanfares
- Items appear immediately without stage reload

Architecture:
- Python client writes item ID to memory buffer
- Patched game code monitors buffer via ASM hook
- When item detected, game calls Rust give_item() function
- Buffer cleared when complete, signaling Python to continue
"""

import logging
import time
from typing import Optional

logger = logging.getLogger("ItemSystem")


# Memory offsets (relative to base address)
# These are calculated from sshd-rando-backend/asm/symbols.yaml
class GameOffsets:
    """Relative memory offsets for game item system."""
    
    # Item system (relative offsets)
    NUMBER_OF_ITEMS = 0x18265fc
    ITEM_GET_BOTTLE_POUCH_SLOT = 0x15904e8
    EQUIPPED_SWORD = 0x1675c6c
    
    # Room/Stage management
    ROOM_MGR = 0x2bfdd90
    STAGE_MGR = 0x2bfdda8
    CURRENT_STAGE_NAME = 0x2bf98d8
    
    # Player
    PLAYER = 0x623E680  # Direct offset to player structure
    PLAYER_CURRENT_ACTION = 0x468  # dPlayer.current_action (u32, relative to PLAYER)
    
    # Archipelago integration
    # Buffer is allocated as a Rust static variable in item.rs
    # Structure: 16 slots × 4 bytes each = 64 bytes total
    # Each slot: [item_id (u8), flags (u8), reserved (u16)]
    ARCHIPELAGO_BUFFER_SIZE = 16  # Number of slots
    ARCHIPELAGO_BUFFER_SLOT_SIZE = 4  # Bytes per slot


# Player actions that indicate the player is "busy" and must NOT be given
# a new item.  Values match the PLAYER_ACTIONS enum in player.rs.
# If the Rust-side busy check is active these duplicate the protection,
# but having both guards is harmless and the Python check lets us skip
# the buffer write entirely (faster retry).
BUSY_PLAYER_ACTIONS = frozenset([
    0x4A,  # DIE
    0x4B,  # REVIVE
    0x58,  # INTERACT
    0x6E,  # USING_DOOR
    0x6F,  # USE_DDOOR
    0x77,  # ZEV_EVENT_MAYBE  (cutscene / event)
    0x78,  # ITEM_GET
    0x7B,  # RELATED_TO_NEW_SWORD_IN_CS_
    0x7D,  # OPEN_CHEST
    0x86,  # SWORD_IN_DIAL
    0x8A,  # ON_BIRD  (flying Loftwing)
    0x91,  # RECEIVE_GODDESS_FRUIT
    0x93,  # SLEEPING
    0xAF,  # PLACE_TABLET
    0xB4,  # ENTER_GODDESS_WALL
    0xB6,  # EXIT_GODDESS_WALL
    0xB7,  # SPIRIT_VESSEL_CHEST_EXIT
])


class GameItemSystem:
    """
    Interface to the game's built-in item spawning system.
    
    Requires ASM patch to monitor buffer and call give_item().
    """
    
    def __init__(self, memory_accessor):
        """
        Initialize the item system.
        
        Args:
            memory_accessor: MemoryAccessor instance for reading/writing game memory
        """
        self.memory = memory_accessor
        self.base_address = getattr(memory_accessor, 'base_address', None)
        self.buffer_addr = None  # Will be found dynamically
        self.timeout_frames = 300  # 5 seconds at 60 FPS
        
        # Buffer address cycling: store ALL valid candidate addresses
        self._candidate_buffer_addrs: list = []  # All prescan hits with valid magic
        self._current_buffer_index: int = 0  # Which candidate we're currently using
        
        # Failure tracking for automatic buffer re-discovery
        self._consecutive_failures: int = 0
        self.MAX_FAILURES_BEFORE_CYCLE = 3  # Try next buffer address after this many failures
        
    def _find_buffer_address(self) -> Optional[int]:
        """
        Find the Archipelago buffer address by scanning for magic signature.
        
        The Rust static buffer is NOT at a fixed offset from the MOD base address.
        It's allocated in a different memory region (heap/separate segment), so we
        must scan for the magic signature 'AP\x00\x01' to locate it dynamically.
        
        First checks addresses cached by the base-address scan (prescan_results)
        so this is typically instantaneous.  Falls back to a full process scan
        only if the cache missed.
        
        Collects ALL valid candidate addresses so we can cycle between them
        if the first one turns out to be the wrong buffer.
        
        Returns:
            Buffer address OFFSET (relative to base) if found, None otherwise
        """
        magic_signature = bytes([0x41, 0x50, 0x00, 0x01])
        
        base_address = getattr(self.memory, 'base_address', None)
        if not base_address:
            logger.error("❌ Base address not set")
            return None
        
        # --- Fast path: use addresses cached during the base-address scan ---
        prescan = getattr(self.memory, 'prescan_results', {})
        cached = prescan.get("AP_ITEM_BUFFER", [])
        
        # Collect ALL valid candidates, not just the first
        self._candidate_buffer_addrs = []
        for addr in cached:
            buffer_offset = addr - base_address
            try:
                test_data = self.memory.read_bytes(buffer_offset, 4)
                if test_data == magic_signature:
                    self._candidate_buffer_addrs.append(buffer_offset)
            except Exception:
                continue
        
        if self._candidate_buffer_addrs:
            self._current_buffer_index = 0
            chosen = self._candidate_buffer_addrs[0]
            abs_addr = base_address + chosen
            logger.debug(f"Found Archipelago buffer at 0x{abs_addr:x} (offset 0x{chosen:x}) [prescan cache]")
            logger.debug(f"   {len(self._candidate_buffer_addrs)} candidate buffer address(es) available")
            return chosen
        
        # --- Slow path: full process scan ---
        logger.debug("Scanning entire process memory for Archipelago buffer magic signature...")
        try:
            from pymem import pattern
            pm = self.memory.pm
            if not pm:
                logger.error("❌ Process memory accessor not available")
                return None
            
            found_address = pattern.pattern_scan_all(pm.process_handle, magic_signature)
            if found_address:
                absolute_addr = found_address[0] if isinstance(found_address, list) else found_address
                buffer_offset = absolute_addr - base_address
                logger.debug(f"Found Archipelago buffer at absolute address 0x{absolute_addr:x}")
                logger.debug(f"Buffer offset from base: 0x{buffer_offset:x}")
                return buffer_offset
            
        except ImportError:
            logger.warning("⚠️ pymem pattern scanning not available, using manual scan")
        except Exception as e:
            logger.warning(f"⚠️ Pattern scan failed: {e}, falling back to manual scan")
        
        # Fallback: Manual scan in likely ranges
        logger.debug("Falling back to manual memory scan...")
        # Rust statics are often in high memory (0x1D000000000 range based on Cheat Engine)
        search_ranges = [
            (0x1D000000000, 0x1E000000000),  # High memory range where we found it
            (0x1000000, 0x10000000),         # Lower range as fallback
        ]
        
        for search_start, search_end in search_ranges:
            logger.debug(f"Searching range 0x{search_start:x}-0x{search_end:x}")
            chunk_size = 4096
            for offset in range(search_start, search_end, chunk_size):
                try:
                    chunk = self.memory.read_bytes(offset, chunk_size)
                    if chunk:
                        idx = chunk.find(magic_signature)
                        if idx != -1:
                            buffer_offset = offset + idx
                            # Verify it's actually the buffer by checking size
                            test_data = self.memory.read_bytes(buffer_offset, 64)
                            if test_data and len(test_data) == 64 and test_data[0:4] == magic_signature:
                                logger.debug(f"Found Archipelago buffer at offset 0x{buffer_offset:x}")
                                return buffer_offset
                except Exception:
                    continue
        
        logger.error("❌ Could not find Archipelago buffer magic signature in memory")
        return None
    
    def _test_buffer_access(self, offset: int) -> bool:
        """Test if we can write to the buffer address (skip magic signature slot)."""
        try:
            # Test on slot 1 (offset+4), not slot 0 which has magic signature
            test_offset = offset + 4
            # Write test byte
            self.memory.write_byte(test_offset, 0x42)
            # Read it back
            val = self.memory.read_byte(test_offset)
            # Restore zero
            self.memory.write_byte(test_offset, 0x00)
            return val == 0x42
        except:
            return False
        
    def give_item(self, item_id: int, show_animation: bool = True, 
                  play_jingle: bool = True) -> bool:
        """
        Give an item to the player using the game's built-in system.
        
        This will:
        - Spawn an item actor
        - Show Link holding up the item (if show_animation=True)
        - Play the item-get jingle (if play_jingle=True)
        - Add the item to inventory
        - No stage reload required
        
        Args:
            item_id: Game item ID (0-255)
            show_animation: Whether to show item-get animation
            play_jingle: Whether to play jingle/fanfare
            
        Returns:
            True if item was given successfully, False otherwise
        """
        if not self.memory.connected:
            logger.error("Cannot give item: not connected to game")
            return False
        
        # Find buffer address on first use
        if self.buffer_addr is None:
            self.buffer_addr = self._find_buffer_address()
            if self.buffer_addr is None:
                logger.error("Cannot give item: buffer address not found")
                return False
        
        # Check if player is in valid state for receiving items
        if not self._is_player_ready():
            logger.debug("Player not ready to receive items")
            return False
        
        # Find empty slot in buffer
        slot = self._find_empty_buffer_slot()
        if slot is None:
            logger.error("Item buffer full - cannot queue item")
            return False
        
        # Prepare flags
        flags = 0
        if show_animation:
            flags |= 0x01
        if play_jingle:
            flags |= 0x02
        
        # Write to buffer
        buffer_offset = self.buffer_addr + (slot * GameOffsets.ARCHIPELAGO_BUFFER_SLOT_SIZE)
        if not self.memory.write_byte(buffer_offset, item_id):
            logger.error(f"Failed to write item ID to buffer slot {slot}")
            return False
        
        if not self.memory.write_byte(buffer_offset + 1, flags):
            logger.error(f"Failed to write flags to buffer slot {slot}")
            return False
        
        # Read back to verify the write actually stuck.
        # There is a small race window where the Rust main-loop can process
        # and clear the slot between our write and readback.  If readback_id
        # is 0 but we just wrote a non-zero value, the write was likely lost
        # (wrong buffer address, game not loaded, etc.).  We treat this as a
        # failure so the caller retries.
        readback_id = self.memory.read_byte(buffer_offset)
        readback_flags = self.memory.read_byte(buffer_offset + 1)
        logger.info(f"Wrote item {item_id} to buffer slot {slot} with flags {flags:02x} (readback: id={readback_id}, flags={readback_flags:02x})")
        logger.info(f"Buffer address: base+0x{self.buffer_addr:x} = 0x{self.memory.base_address + self.buffer_addr:x}")

        if readback_id != item_id:
            logger.warning(
                f"Readback mismatch: wrote item_id={item_id}, read back {readback_id}. "
                f"Buffer may be stale or incorrect — will retry."
            )
            # Clear the slot to be safe
            self.memory.write_byte(buffer_offset, 0)
            self.memory.write_byte(buffer_offset + 1, 0)
            return False
        
        # Wait for game to process (buffer cleared when done)
        success = self._wait_for_item_processed(buffer_offset, expected_item_id=item_id)
        
        if success:
            self._consecutive_failures = 0
        else:
            self._consecutive_failures += 1
            if (self._consecutive_failures >= self.MAX_FAILURES_BEFORE_CYCLE 
                    and len(self._candidate_buffer_addrs) > 1):
                self._cycle_to_next_buffer()
        
        return success
    
    def _cycle_to_next_buffer(self):
        """
        Switch to the next candidate buffer address after repeated failures.
        
        This handles the case where the prescan found multiple copies of the
        magic signature and the first one isn't the real game buffer.
        """
        old_index = self._current_buffer_index
        self._current_buffer_index = (self._current_buffer_index + 1) % len(self._candidate_buffer_addrs)
        self.buffer_addr = self._candidate_buffer_addrs[self._current_buffer_index]
        self._consecutive_failures = 0
        
        # Clear ALL slots in the new buffer to start fresh
        self.clear_buffer()
        
        abs_addr = (self.memory.base_address or 0) + self.buffer_addr
        logger.warning(
            f"[BufferCycle] Switching from candidate {old_index + 1} to "
            f"{self._current_buffer_index + 1}/{len(self._candidate_buffer_addrs)} "
            f"(new buffer at 0x{abs_addr:x}, offset 0x{self.buffer_addr:x})"
        )
    
    def give_item_by_name(self, item_name: str) -> bool:
        """
        Give an item by its name (from ITEM_TABLE).
        
        Args:
            item_name: Name of item (e.g., "Progressive Sword", "Clawshots")
            
        Returns:
            True if successful, False otherwise
        """
        # Import here to avoid circular dependency
        try:
            from Items import ITEM_TABLE
        except ImportError:
            logger.error("Failed to import ITEM_TABLE")
            return False
        
        if item_name not in ITEM_TABLE:
            logger.error(f"Unknown item: {item_name}")
            return False
        
        item_data = ITEM_TABLE[item_name]
        
        # Convert AP item ID to game item ID
        # This mapping depends on how your randomizer assigns IDs
        game_item_id = self._ap_id_to_game_id(item_data.code)
        
        if game_item_id is None:
            logger.error(f"No game ID mapping for {item_name}")
            return False
        
        return self.give_item(game_item_id)
    
    def _find_empty_buffer_slot(self) -> Optional[int]:
        """Find first empty slot in item buffer."""
        # Slot 0 is RESERVED for magic signature "AP\x00\x01" - game ignores it
        # Only use slots 1-15 for actual items
        for slot in range(1, GameOffsets.ARCHIPELAGO_BUFFER_SIZE):
            buffer_offset = self.buffer_addr + (slot * GameOffsets.ARCHIPELAGO_BUFFER_SLOT_SIZE)
            item_id = self.memory.read_byte(buffer_offset)
            if item_id == 0:
                return slot
        return None
    
    def _wait_for_item_processed(self, buffer_offset: int, expected_item_id: int = 0) -> bool:
        """Wait for game to process item (clear buffer slot).
        
        Args:
            buffer_offset: Absolute offset into process memory for this slot
            expected_item_id: The item_id we wrote; used to detect a failed write.
        """
        # --- First poll: verify the item is actually in the buffer ----------
        # If the very first read already shows item_id == 0 AND the expected
        # id was non-zero, the write never reached the game buffer (wrong
        # buffer address, race condition, etc.).  Report failure so the
        # caller can retry rather than silently losing the item.
        first_id = self.memory.read_byte(buffer_offset)
        first_flags = self.memory.read_byte(buffer_offset + 1)
        logger.info(f"[POLL FRAME 0] Buffer slot: item_id={first_id}, flags={first_flags:02x}")

        if first_id == 0 and expected_item_id != 0:
            # The slot is already empty before the game had a chance to run a
            # single frame.  This almost certainly means the write was lost.
            logger.warning(
                f"Buffer slot was empty on first poll (expected item {expected_item_id}). "
                f"Write may have been lost — will retry."
            )
            return False

        if first_id == 0:
            logger.info("Item processed after 0 frames")
            return True

        # --- Normal polling loop (frames 1+) --------------------------------
        for frame in range(1, self.timeout_frames):
            time.sleep(1.0 / 60.0)  # ~60 FPS
            
            item_id = self.memory.read_byte(buffer_offset)
            flags = self.memory.read_byte(buffer_offset + 1)
            
            if frame < 5:
                logger.info(f"[POLL FRAME {frame}] Buffer slot: item_id={item_id}, flags={flags:02x}")
            
            if item_id == 0:
                # Buffer cleared - item was processed by the game
                logger.info(f"Item processed after {frame} frames")
                return True
        
        logger.error(f"Item processing timeout after {self.timeout_frames} frames")
        # Clear BOTH item_id and flags to fully reset the slot
        self.memory.write_byte(buffer_offset, 0)      # item_id
        self.memory.write_byte(buffer_offset + 1, 0)   # flags
        return False
    
    def _is_player_ready(self) -> bool:
        """Check if player is in valid state to receive items.
        
        Returns False when:
        - Base address is not set (game not attached)
        - Buffer has not been located yet
        - Player is in a busy action (item-get, cutscene, chest, etc.)
        """
        # Get current base address from memory accessor
        base_address = getattr(self.memory, 'base_address', None)
        if not base_address:
            logger.debug("Player not ready: base_address is None")
            return False
        
        # Verify buffer is accessible (this ensures game is loaded enough)
        if self.buffer_addr is None:
            self.buffer_addr = self._find_buffer_address()
            if self.buffer_addr is None:
                logger.debug("Player not ready: Buffer not found")
                return False
        
        # ---- Player action busy-state check --------------------------------
        # Read the player's current action and reject if it's one of the
        # "busy" states where giving an item would be lost or cause issues.
        try:
            action_offset = GameOffsets.PLAYER + GameOffsets.PLAYER_CURRENT_ACTION
            current_action = self.memory.read_int(action_offset)
            if current_action is not None and current_action in BUSY_PLAYER_ACTIONS:
                logger.debug(
                    f"Player not ready: current action 0x{current_action:X} is busy"
                )
                return False
        except Exception as e:
            # If we can't read the action, err on the side of caution and
            # allow the item — the Rust-side busy check is the real safety net.
            logger.debug(f"Could not read player action: {e}")
        
        logger.debug("Player ready check passed (base address + buffer accessible)")
        return True
    
    def _ap_id_to_game_id(self, ap_item_id: int) -> Optional[int]:
        """
        Convert Archipelago item ID to game item ID.
        
        This mapping depends on your randomizer's item ID scheme.
        You'll need to create a proper mapping based on:
        - Items.py ITEM_TABLE codes
        - sshd-rando-backend/constants/itemnames.py IDs
        
        For now, we'll use the original_id from the ITEM_TABLE
        
        Args:
            ap_item_id: Archipelago item code
            
        Returns:
            Game item ID (0-255) or None if no mapping
        """
        # Import here to avoid circular dependency
        try:
            from Items import ITEM_TABLE
        except ImportError:
            logger.error("Failed to import ITEM_TABLE for ID conversion")
            return None
            
        for item_name, item_data in ITEM_TABLE.items():
            if item_data.code == ap_item_id:
                return item_data.original_id
        
        return None
    
    def clear_buffer(self):
        """Clear all slots in item buffer."""
        if not self.buffer_addr:
            return
        for slot in range(GameOffsets.ARCHIPELAGO_BUFFER_SIZE):
            buffer_offset = self.buffer_addr + (slot * GameOffsets.ARCHIPELAGO_BUFFER_SLOT_SIZE)
            # Write 4 zero bytes to clear the slot
            for i in range(GameOffsets.ARCHIPELAGO_BUFFER_SLOT_SIZE):
                self.memory.write_byte(buffer_offset + i, 0)
        logger.info("Cleared Archipelago item buffer")
