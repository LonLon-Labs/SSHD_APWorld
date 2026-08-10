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
    CURRENT_STAGE_LAYER = 0x2bf98fb
    NEXT_STAGE_NAME = 0x2bf9904
    TITLE_STAGE = b"F000"
    
    # Player
    PLAYER = 0x623E680  # Direct offset to player structure
    PLAYER_CURRENT_ACTION = 0x468  # dPlayer.current_action (u32, relative to PLAYER)
    PLAYER_ITEM_BEING_USED = 0x6404  # dPlayer.item_being_used (u16, relative to PLAYER)
    
    # Archipelago integration
    # Buffer is allocated as a Rust static variable in item.rs
    # Structure: 1024 slots × 4 bytes each = 4096 bytes total
    # Each slot: [item_id (u8), flags (u8), reserved (u16)]
    ARCHIPELAGO_BUFFER_SIZE = 1024  # Number of slots
    ARCHIPELAGO_BUFFER_SLOT_SIZE = 4  # Bytes per slot

    # Save-file item flag addresses for direct flag writing fallback.
    # These let us guarantee item delivery by writing the flag bit directly
    # to the committed (SaveFile FA) and uncommitted (static) copies,
    # bypassing the actor-spawn system entirely.
    # Offsets verified against working cheat code in SSHDClient.py.
    SAVEFILE_A = 0x5AEAD54             # FileMgr.FA start
    FA_ITEMFLAGS = SAVEFILE_A + 0x9E4  # committed itemflags [u16; 64]
    STATIC_ITEMFLAGS = 0x182E170       # uncommitted/working copy [u16; 64]

    # FlagMgr pointer-chasing offsets (from flag.rs / symbols.yaml).
    # ITEMFLAG_MGR is a *mut FlagMgr stored 8 bytes before STATIC_ITEMFLAGS.
    ITEMFLAG_MGR = STATIC_ITEMFLAGS - 8  # 0x182E168
    # FlagMgr struct layout: {funcs: 8, flag_size: 4, another_size: 4, flags_ptr: 8}
    FLAGMGR_FLAGS_PTR_OFFSET = 16  # offset of *mut FlagSpace within FlagMgr
    # FlagSpace struct layout: {flag_ptr: 8, static_flag_ptr: 8, flag_space_size: 2, pad: 6}
    FLAGSPACE_FLAG_PTR_OFFSET = 0   # committed/active flag data pointer
    FLAGSPACE_STATIC_PTR_OFFSET = 8  # working-copy (STATIC_ITEMFLAGS) pointer


# Player actions that indicate the player is "busy" and must NOT be given
# a new item.  Values match the PLAYER_ACTIONS enum in player.rs.
# If the Rust-side busy check is active these duplicate the protection,
# but having both guards is harmless and the Python check lets us skip
# the buffer write entirely (faster retry).
BUSY_PLAYER_ACTIONS = frozenset([
    0x12,  # DIVE_SKY  (diving from sky to surface)
    0x13,  # FREE_FALL
    0x14,  # FALLING
    0x26,  # VINES_USING_CLAWS
    0x40,  # PICK_UP
    0x41,  # THROWING
    0x43,  # HOLDING
    0x45,  # USE_BOW
    0x46,  # USE_SLINGSHOT
    0x4A,  # DIE
    0x4B,  # REVIVE
    0x58,  # INTERACT
    0x59,  # USE_CLAWSHOTS
    0x5A,  # BEING_PULLED_BY_CLAWS
    0x5B,  # HANG_FROM_PEAHAT
    0x5C,  # HANG_FROM_PEAHAT_USE_CLAWS_
    0x5D,  # HANG_FROM_TARGET
    0x5E,  # HANG_FROM_TARGET_USE_CLAWS_
    0x5F,  # USE_BEETLE  (controlling beetle in flight)
    0x60,  # FINAL_BLOW
    0x61,  # FINAL_BLOW_FINISH
    0x66,  # CRAWLING
    0x69,  # USE_BELLOWS
    0x6E,  # USING_DOOR
    0x6F,  # USE_DDOOR
    0x74,  # CRAWLSPACE
    0x77,  # ZEV_EVENT_MAYBE  (cutscene / event)
    0x78,  # ITEM_GET
    0x7B,  # RELATED_TO_NEW_SWORD_IN_CS_
    0x7D,  # OPEN_CHEST
    0x86,  # SWORD_IN_DIAL
    0x87,  # ENTER_MINECART
    0x88,  # LEAVE_MINECART
    0x89,  # IN_TRUCK_MINECART
    0x8A,  # ON_BIRD  (flying Loftwing)
    0x8B,  # BIRD_REACH_FOR_STATUETTE
    0x8D,  # USE_WHIP
    0x8E,  # WHIP_LOCKED
    0x91,  # RECEIVE_GODDESS_FRUIT
    0x93,  # SLEEPING
    0x94,  # USE_BUGNET_CATCH
    0x95,  # IN_GROOSENATOR
    0x96,  # LAUNCH_FROM_GROOSENATOR
    0x99,  # IN_BOAT
    0xAF,  # PLACE_TABLET
    0xB4,  # ENTER_GODDESS_WALL
    0xB6,  # EXIT_GODDESS_WALL
    0xB7,  # SPIRIT_VESSEL_CHEST_EXIT
])

BUSY_ITEM_USED = frozenset([
    0x0,  # BOMB_BAG
    0x1,  # BOW
    0x2,  # CLAWSHOTS
    0x3,  # BEETLE
    0x4,  # SLINGSHOT
    0x5,  # GUST_BELLOWS
    0x6,  # WHIP
    0x7,  # MITTS
    0x8,  # BUG_NET
    0x9,  # HARP
    0xA,  # SAILCLOTH
    0xC,  # POTION
    0x12, # WATER_DRAGON_SCALE
    0x13, # GUIDE_PT_PM
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
        self.timeout_frames = 900  # 15 seconds at 60 FPS polling rate — must cover Rust stage-transition cooldown (90 game frames) + retry window (300 game frames)
        self.last_delivery_mode = "none"  # "buffer" | "direct_flag" | "none"
        
        # Stage-transition cooldown (mirrors Rust-side protection).
        # When the Python client detects a stage change it blocks item
        # delivery for a few seconds so the game has time to finish
        # loading rooms/actors/heaps.  Without this, buffer writes that
        # land during the transition are consumed by the Rust loop but
        # the spawned actor is destroyed when the old scene unloads.
        self._last_known_stage: Optional[bytes] = None
        self._stage_cooldown_until: float = 0.0
        self._STAGE_COOLDOWN_SECS: float = 3.0  # seconds after a stage change
        self._scene_transition_cooldown_until: float = 0.0
        self._last_next_stage: Optional[bytes] = None
        self._last_next_stage_change_at: float = 0.0
        
        # Buffer address cycling: store ALL valid candidate addresses
        self._candidate_buffer_addrs: list = []  # All prescan hits with valid magic
        self._current_buffer_index: int = 0  # Which candidate we're currently using
        
        # Failure tracking for automatic buffer re-discovery
        self._consecutive_failures: int = 0
        self.MAX_FAILURES_BEFORE_CYCLE = 3  # Try next buffer address after this many failures
        
        # Set True once we confirm the selected buffer is the real game buffer
        # (game set the itemflag after processing).  Skips the 250ms post-
        # delivery verification delay for subsequent items.
        self._buffer_verified: bool = False

        self._forced_dungeon_keys: dict = {}

        # FlagMgr pointer-chase state.
        # After discovering the committed flag data location once, we cache
        # the host offset so _ensure_itemflag_set can write there directly.
        # Invalidated on scene transitions because the committed flag data
        # lives on the heap and can be reallocated.
        self._guest_to_host_delta: Optional[int] = None
        self._committed_flag_offset: Optional[int] = None  # host offset of committed flag data
        self._flagmgr_discovery_retry_at: float = 0.0  # earliest time to retry discovery
        self._flagmgr_invalid_log_retry_at: float = 0.0  # throttle repeated null/invalid pointer logs
        
    def _score_buffer_candidate(self, offset: int, magic_signature: bytes,
                                cs_addresses: list) -> tuple:
        """Score a buffer candidate to determine if it's the real game buffer.

        Returns (total_score, detail_dict) where higher score = more likely real.

        Scoring criteria:
          +1 per zero byte in data slots (max 4092) — real buffer is all-zero
          +100 if write-read-back test passes (writable memory)
          +50  if within 4 MB of any AP_CHECK_STATS address (same module)
          -200 if fewer than 40 of 60 data bytes are zero (very unlikely real)
        """
        details = {"zero_count": 0, "writable": False, "near_stats": False}
        score = 0

        # Read the full buffer so scoring sees every slot.
        try:
            buffer_size = GameOffsets.ARCHIPELAGO_BUFFER_SIZE * GameOffsets.ARCHIPELAGO_BUFFER_SLOT_SIZE
            data = self.memory.read_bytes(offset, buffer_size)
            if not data or len(data) < buffer_size:
                return (-1000, details)
            if data[:4] != magic_signature:
                return (-1000, details)
        except Exception:
            return (-1000, details)

        # Count zero bytes in the data slots (bytes 4+).
        # The real buffer should be all zeros when no items are pending.
        zero_count = sum(1 for b in data[4:] if b == 0)
        details["zero_count"] = zero_count
        score += zero_count
        if zero_count < 40:
            score -= 200  # Almost certainly a false positive

        # Writability: test write + read-back on slot 1
        if self._test_buffer_access(offset):
            score += 100
            details["writable"] = True

        # Proximity to AP_CHECK_STATS (Rust statics live in the same module)
        base_address = self.memory.base_address or 0
        abs_addr = base_address + offset
        MODULE_RANGE = 4 * 1024 * 1024  # 4 MB
        for cs_addr in cs_addresses:
            if abs(abs_addr - cs_addr) < MODULE_RANGE:
                score += 50
                details["near_stats"] = True
                break

        return (score, details)

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
        
        **Buffer scoring (v2):** Instead of blindly picking the first candidate,
        each candidate is scored by:
          - Zero-byte count in data slots (real buffer = all zeros on init)
          - Writability (write + read-back test)
          - Proximity to AP_CHECK_STATS (same subsdk8 module)
        The highest-scoring candidate is selected.
        
        Returns:
            Buffer address OFFSET (relative to base) if found, None otherwise
        """
        magic_signature = bytes([0x41, 0x50, 0x00, 0x01])
        
        base_address = getattr(self.memory, 'base_address', None)
        if not base_address:
            logger.error("❌ Base address not set")
            return None
        
        # Grab AP_CHECK_STATS addresses for cross-reference scoring
        prescan = getattr(self.memory, 'prescan_results', {})
        cs_addresses = prescan.get("AP_CHECK_STATS", [])
        cached = prescan.get("AP_ITEM_BUFFER", [])
        
        # --- Fast path: score all prescan candidates and pick the best ---
        self._candidate_buffer_addrs = []
        scored_candidates = []  # (score, offset, details)
        
        for addr in cached:
            buffer_offset = addr - base_address
            try:
                test_data = self.memory.read_bytes(buffer_offset, 4)
                if test_data != magic_signature:
                    continue
            except Exception:
                continue
            
            self._candidate_buffer_addrs.append(buffer_offset)
            score, details = self._score_buffer_candidate(
                buffer_offset, magic_signature, cs_addresses
            )
            scored_candidates.append((score, buffer_offset, details))
            abs_addr = base_address + buffer_offset
            logger.info(
                f"[BufferScore] Candidate 0x{abs_addr:x} (offset 0x{buffer_offset:x}): "
                f"score={score}, zeros={details['zero_count']}/60, "
                f"writable={details['writable']}, near_stats={details['near_stats']}"
            )
        
        if scored_candidates:
            # Sort by score descending — pick best
            scored_candidates.sort(key=lambda t: t[0], reverse=True)
            best_score, best_offset, best_details = scored_candidates[0]
            
            # Reorder _candidate_buffer_addrs so the best is first
            self._candidate_buffer_addrs = [t[1] for t in scored_candidates]
            self._current_buffer_index = 0
            
            abs_addr = base_address + best_offset
            logger.info(
                f"[BufferSelect] Selected buffer at 0x{abs_addr:x} "
                f"(score {best_score}, {len(scored_candidates)} candidates, "
                f"zeros={best_details['zero_count']}/60, "
                f"writable={best_details['writable']}, "
                f"near_stats={best_details['near_stats']})"
            )
            
            if best_details["zero_count"] < 50:
                logger.warning(
                    f"[BufferSelect] ⚠️ Best candidate only has "
                    f"{best_details['zero_count']}/60 zero bytes in data slots. "
                    f"This may be a false positive! Items may not be delivered."
                )
            
            return best_offset
        
        # --- Slow path: full process scan ---
        logger.debug("Scanning entire process memory for Archipelago buffer magic signature...")
        try:
            pm = self.memory.pm
            if not pm:
                logger.error("❌ Process memory accessor not available")
                return None
            
            addresses = pm.pattern_scan(magic_signature)
            if addresses:
                absolute_addr = addresses[0] if isinstance(addresses, list) else addresses
                buffer_offset = absolute_addr - base_address
                logger.debug(f"Found Archipelago buffer at absolute address 0x{absolute_addr:x}")
                logger.debug(f"Buffer offset from base: 0x{buffer_offset:x}")
                return buffer_offset
            
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
                            # Verify it's actually the buffer by checking the signature
                            test_data = self.memory.read_bytes(buffer_offset, 4)
                            if test_data and len(test_data) == 4 and test_data[0:4] == magic_signature:
                                logger.debug(f"Found Archipelago buffer at offset 0x{buffer_offset:x}")
                                return buffer_offset
                except Exception:
                    continue
        
        logger.error("❌ Could not find Archipelago buffer magic signature in memory")
        return None
    
    def _test_buffer_access(self, offset: int) -> bool:
        """Test if we can write to the buffer address (skip magic signature slot).

        IMPORTANT: We test on slot 1's *reserved* bytes (offset+6), NOT on
        the item_id byte (offset+4).  The Rust game loop checks item_id != 0
        every frame to detect pending items.  Writing a non-zero test value
        to the item_id byte races with the game loop and can cause a
        spurious item spawn (0x42 = game item 66 = Guardian Potion+).
        """
        try:
            # Test on slot 1's reserved byte (offset+6), not the item_id byte
            test_offset = offset + 6
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
        
        Two delivery paths run in sequence:
        
        1. **Buffer path** (preferred): write item to the shared memory buffer,
           wait for the Rust game loop to spawn the item actor with proper
           animations / models / jingles.  This can fail if the buffer address
           hasn't been found yet, the player is busy, or the buffer is full.
        
        2. **Direct-flag fallback** (always runs): set the item flag directly
           in save memory so the item appears in inventory even if the buffer
           path failed.  For equipment and key items this is sufficient; for
           consumables (rupees, ammo) it only sets the "collected" bit, not
           the quantity counter.
        
        Returns True if the item reached the player's inventory through
        *either* path.  The caller can safely dequeue the item.
        
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

        # Intercept real per-dungeon Small Keys (200-206) when that dungeon
        # is already under a forced Key Ring / Skeleton Key count. The
        # native buffer-path pickup increments dungeonflags directly and
        # will desync the forced 4/5 value — so instead of letting it
        # through, just re-assert the forced value and report delivered.
        forced_scene_idx = self._SMALL_KEY_ITEM_ID_TO_SCENE.get(item_id)
        if forced_scene_idx is not None and forced_scene_idx in self._forced_dungeon_keys:
            forced_value = self._forced_dungeon_keys[forced_scene_idx]
            self._write_dungeon_key_count(
                forced_scene_idx, forced_value, self._current_dungeon_key_scene_idx()
            )
            logger.info(
                f"[DungeonKeys] Suppressed real Small Key (item_id {item_id}) — "
                f"scene {forced_scene_idx} is forced to {forced_value}"
            )
            self.last_delivery_mode = "direct_flag"
            return True

        # Key Rings (220-226) / Skeleton Key (227) register their forced
        # dungeon-key count HERE, unconditionally — NOT only as a fallback
        # when the buffer path fails. These items have real OARC models and
        # normally deliver successfully via the buffer path (native game
        # code), so _ensure_dungeon_keys_set would otherwise never run and
        # _forced_dungeon_keys would stay empty forever, silently disabling
        # the Small Key suppression above. Registering it here guarantees
        # the tracking dict is populated the moment the item is granted,
        # regardless of which delivery path actually shows the pickup.
        if 220 <= item_id <= 227:
            self._ensure_dungeon_keys_set(item_id)

        self.last_delivery_mode = "none"
        
        # ---- Path 1: Buffer-based delivery (with animation) -----------------
        buffer_success = False
        try:
            # Find buffer address on first use
            if self.buffer_addr is None:
                self.buffer_addr = self._find_buffer_address()
            
            if self.buffer_addr is None:
                logger.debug("Buffer address not found — skipping buffer path")
            else:
                # Check if the player is ready (not in a busy action).
                # Instead of a synchronous busy-wait (which blocks the
                # async event loop and prevents websocket pings/GUI), do
                # a single check and return False immediately if busy.
                # The caller's item queue will retry on the next tick.
                if not self._is_player_ready():
                    return False

                if self._scene_transition_active():
                    logger.debug("Scene transition active — skipping item delivery")
                    return False

                # Re-check immediately before writing; the scene can start
                # transitioning in the gap between the readiness test and
                # the actual memory write.
                if self._scene_transition_active():
                    logger.debug("Scene transition became active before buffer write — retrying later")
                    return False

                # Player is ready — proceed with buffer write
                slot = self._find_empty_buffer_slot()
                if slot is None:
                    logger.debug("Item buffer full — skipping buffer path")
                else:
                    # Prepare flags
                    flags = 0
                    if show_animation:
                        flags |= 0x01
                    if play_jingle:
                        flags |= 0x02

                    # Write to buffer ATOMICALLY using a single 16-bit write.
                    buffer_offset = self.buffer_addr + (slot * GameOffsets.ARCHIPELAGO_BUFFER_SLOT_SIZE)
                    slot_value = item_id | (flags << 8)  # little-endian: [item_id, flags]
                    if self.memory.write_short(buffer_offset, slot_value):
                        logger.info(f"Wrote item {item_id} to buffer slot {slot} with flags {flags:02x}")
                        logger.info(f"Buffer address: base+0x{self.buffer_addr:x} = 0x{self.memory.base_address + self.buffer_addr:x}")
                        buffer_success = self._wait_for_item_processed(
                            buffer_offset, expected_item_id=item_id
                        )
                    else:
                        logger.warning(f"Failed to write item {item_id} to buffer slot {slot}")
        except Exception as exc:
            logger.warning(f"Buffer delivery error for item {item_id}: {exc}")
        
        # ---- Path 2: Direct-flag fallback (only when buffer failed) --------
        # If the buffer path succeeded, the game's item actor will set the
        # flag itself during stateGet.  Writing the flag here would race
        # with the actor's determineFinalItemid call and cause progressive
        # items (especially swords) to resolve to the wrong tier.
        flag_confirmed = False
        if not buffer_success:
            flag_confirmed = self._ensure_itemflag_set(item_id)
        
        # ---- Track consecutive buffer failures for address cycling ----------
        if buffer_success:
            self._consecutive_failures = 0
        else:
            self._consecutive_failures += 1
            if (self._consecutive_failures >= self.MAX_FAILURES_BEFORE_CYCLE 
                    and len(self._candidate_buffer_addrs) > 1):
                self._cycle_to_next_buffer()
        
        # Item is delivered if EITHER path succeeded.
        delivered = buffer_success or flag_confirmed
        if delivered and buffer_success:
            self.last_delivery_mode = "buffer"
        elif delivered and not buffer_success:
            self.last_delivery_mode = "direct_flag"
            logger.info(
                f"Item {item_id} delivered via direct flag write "
                f"(buffer path unavailable)"
            )
        return delivered
    
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
        self._buffer_verified = False  # must re-verify the new candidate
        
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
        # Only use slots 1-(N-1) for actual items
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
        # --- Race-condition handling -----------------------------------------
        # The game's Rust loop processes the buffer every frame (~16ms) on a
        # SEPARATE THREAD.  There is an inherent race window where the game
        # can read our write, process the item, and clear the slot BEFORE
        # Python gets to read it back.  When that happens, item_id == 0 on
        # the very first poll — which looks identical to "the write never
        # landed".
        #
        # Because all buffer-delivered items have show_animation + play_jingle
        # flags set (0x03), the game ALWAYS enters ITEM_GET (action 0x78)
        # when it processes an item.  We use this as the primary evidence
        # that the game consumed our write even though the slot is already
        # cleared:
        #
        #   1. If we ever see our expected item_id in the slot, the write
        #      definitely worked.  Keep polling until cleared → success.
        #   2. If the slot is zero, check the player's current action:
        #        a) Player is in ITEM_GET (0x78) → game processed it → success.
        #        b) Buffer magic signature ("AP\x00\x01") at slot 0 is still
        #           intact (fallback) → we're on the real buffer, the game
        #           must have cleared it → success.
        #   3. If neither check passes by the end of the grace period, the
        #      write was genuinely lost (wrong buffer, stale memory) → retry.
        #
        # This eliminates the old false-negative race that caused item
        # duplication: the game would process the item, Python would think
        # the write failed, and the retry would give a second copy.
        GRACE_FRAMES = 4  # ~67ms at 60 FPS — enough for the game loop
        STUCK_ITEM_TIMEOUT_FRAMES = 300  # fail fast after ~5s if item never clears

        ever_saw_item = False
        for frame in range(self.timeout_frames):
            item_id = self.memory.read_byte(buffer_offset)
            flags = self.memory.read_byte(buffer_offset + 1)

            if frame < 5:
                logger.info(f"[POLL FRAME {frame}] Buffer slot: item_id={item_id}, flags={flags:02x}")

            if item_id == expected_item_id and expected_item_id != 0:
                ever_saw_item = True

                # If the slot remains occupied by the same item for too long,
                # fail fast so caller can retry/cycle instead of stalling for
                # the full timeout window.
                if frame >= STUCK_ITEM_TIMEOUT_FRAMES:
                    logger.warning(
                        f"Item {expected_item_id} stuck in buffer for {frame} frames; "
                        "treating as timeout and retrying"
                    )
                    return False

            if item_id == 0:
                if ever_saw_item:
                    if self._scene_transition_active():
                        logger.warning(
                            f"Item {expected_item_id} cleared during a scene transition; will retry instead of confirming delivery"
                        )
                        return False
                    # Normal path: we saw our item, now it's cleared → success
                    logger.info(f"Item processed after {frame} frames")
                    return True

                if frame <= GRACE_FRAMES:
                    # Slot is empty but we're within the grace window.
                    # Check corroborating evidence before concluding.

                    # Evidence A: player entered ITEM_GET animation
                    try:
                        action_offset = GameOffsets.PLAYER + GameOffsets.PLAYER_CURRENT_ACTION
                        current_action = self.memory.read_int(action_offset)
                        if current_action == 0x78:  # ITEM_GET
                            if self._scene_transition_active():
                                logger.warning(
                                    f"Item {expected_item_id} entered ITEM_GET during a scene transition; waiting instead of confirming"
                                )
                                continue
                            logger.info(
                                f"Item processed after {frame} frames (player in ITEM_GET)"
                            )
                            return True
                    except Exception:
                        pass

                    if frame == GRACE_FRAMES:
                        # Evidence B: buffer magic signature is intact, proving
                        # we're pointed at the real game buffer.  An empty
                        # slot on the real buffer means the game cleared it.
                        if self._verify_buffer_magic():
                            logger.info(
                                f"Item processed after {frame} frames "
                                f"(buffer magic valid, slot cleared by game)"
                            )
                            return True

                        # Magic invalid → we're pointed at stale/wrong memory.
                        logger.warning(
                            f"Buffer slot empty for {frame} frames and magic "
                            f"signature invalid. Buffer address may be stale "
                            f"— will retry."
                        )
                        return False

                    # Still within grace window — wait one frame and re-check
                    time.sleep(1.0 / 60.0)
                    continue

                # Past grace period and we never saw our item — shouldn't
                # normally reach here (grace period returns), but guard anyway.
                logger.warning(
                    f"Buffer slot empty for {frame} frames with no evidence "
                    f"of processing. Write of item {expected_item_id} was "
                    f"likely lost — will retry."
                )
                return False

            # item_id is non-zero (either our item or stale data) — keep waiting
            time.sleep(1.0 / 60.0)

        logger.error(f"Item processing timeout after {self.timeout_frames} frames")
        # Only clear slot when buffer magic is valid. If magic is invalid, do
        # not write into potentially stale memory; force caller to retry.
        if self._verify_buffer_magic():
            self.memory.write_short(buffer_offset, 0)
        else:
            logger.warning(
                "Buffer magic invalid at timeout; skipping slot clear to avoid stale-memory write"
            )
        return False
    
    def _verify_buffer_magic(self) -> bool:
        """Check if the Archipelago buffer magic signature is still valid.
        
        The first 4 bytes of the buffer should always be 'AP\\x00\\x01'.
        If this is intact, we know self.buffer_addr points at the real
        game buffer (not stale/deallocated memory).
        """
        if not self.buffer_addr:
            return False
        try:
            magic = self.memory.read_bytes(self.buffer_addr, 4)
            return magic == bytes([0x41, 0x50, 0x00, 0x01])
        except Exception:
            return False

    def _scene_transition_active(self) -> bool:
        """Return True when the game is in or entering a scene transition."""
        try:
            stage_raw = self.memory.read_bytes(GameOffsets.CURRENT_STAGE_NAME, 8)
            if not stage_raw:
                return True

            stage = stage_raw.split(b"\x00", 1)[0]
            if not stage:
                return True

            next_stage_raw = self.memory.read_bytes(GameOffsets.NEXT_STAGE_NAME, 8)
            if not next_stage_raw:
                return time.time() < self._scene_transition_cooldown_until

            next_stage = next_stage_raw.split(b"\x00", 1)[0]
            # Empty NEXT_STAGE means no pending transition.
            if not next_stage:
                return time.time() < self._scene_transition_cooldown_until

            now = time.time()
            if next_stage != self._last_next_stage:
                self._last_next_stage = next_stage
                self._last_next_stage_change_at = now

            # Do not hard-block solely on NEXT_STAGE mismatch. On some builds
            # NEXT_STAGE can hold stale values for long periods, which would
            # permanently block AP item delivery.

            return time.time() < self._scene_transition_cooldown_until
        except Exception:
            return True
    
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
        
        # ---- Stage-transition cooldown ------------------------------------
        # Detect stage changes by reading the current stage name.  If it
        # changed since the last check, impose a cooldown so the engine
        # finishes loading rooms, OARCs and heaps before we spawn items.
        try:
            stage_raw = self.memory.read_bytes(
                GameOffsets.CURRENT_STAGE_NAME, 8
            )
            if stage_raw is not None:
                stage_bytes = stage_raw.split(b"\x00", 1)[0]
                if not stage_bytes:
                    return False
                if stage_bytes == GameOffsets.TITLE_STAGE:
                    stage_layer = self.memory.read_byte(GameOffsets.CURRENT_STAGE_LAYER)
                    if stage_layer == 26:
                        logger.debug("Player not ready: title stage active")
                        return False
                if self._last_known_stage is None:
                    self._last_known_stage = stage_bytes
                elif stage_bytes != self._last_known_stage:
                    self._last_known_stage = stage_bytes
                    self._stage_cooldown_until = time.time() + self._STAGE_COOLDOWN_SECS
                    # Invalidate the buffer address cache — heap allocations
                    # can move during a scene transition and a stale address
                    # would corrupt game memory.
                    self.buffer_addr = None
                    self._buffer_verified = False
                    # Also invalidate the committed-flag pointer — the
                    # FlagMgr heap data can move during scene transitions.
                    self._committed_flag_offset = None
                    self._guest_to_host_delta = None
                    logger.debug(
                        f"Stage transition detected — cooldown until "
                        f"{self._stage_cooldown_until:.1f}, buffer+flag caches invalidated"
                    )
            if time.time() < self._stage_cooldown_until:
                logger.debug("Player not ready: stage-transition cooldown active")
                return False
        except Exception as e:
            logger.debug(f"Could not read stage name: {e}")

        if self._scene_transition_active():
            logger.debug("Player not ready: scene transition active or imminent")
            return False
        
        # ---- Player action busy-state check --------------------------------
        # Read the player's current action and reject if it's one of the
        # "busy" states where giving an item would be lost or cause issues.
        try:
            action_offset = GameOffsets.PLAYER + GameOffsets.PLAYER_CURRENT_ACTION
            current_action = self.memory.read_int(action_offset)
            item_offsets = GameOffsets.PLAYER + GameOffsets.PLAYER_ITEM_BEING_USED
            current_item_being_used = self.memory.read_int(item_offsets)

            is_action_busy = current_action is not None and current_action in BUSY_PLAYER_ACTIONS
            is_item_busy = current_item_being_used is not None and current_item_being_used in BUSY_ITEM_USED

            if is_action_busy or is_item_busy:
                # Log only every 60th call (~once per second) to avoid spam
                self._busy_log_counter = getattr(self, '_busy_log_counter', 0) + 1
                if self._busy_log_counter % 60 == 1:
                    # Construct the log pieces safely to handle None values and nested formatting
                    action_str = f"0x{current_action:X}" if current_action is not None else "None"
                    item_str = f" and current item 0x{current_item_being_used:X} is busy" if is_item_busy else ""
                    
                    logger.debug(f"Player not ready: current action {action_str} is busy{item_str}")
                    
                return False
            else:
                self._busy_log_counter = 0
                return True
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
    
    # ---- Direct item-flag reading and writing (guaranteed delivery) --------

    def _invalidate_committed_cache(self):
        """Reset the cached committed-flag pointer.

        Called on scene transitions (heap may move) and when a validation
        read fails.  Forces the next ``_ensure_itemflag_set`` call to
        re-discover the pointer via ``_discover_committed_flags``.
        """
        if self._committed_flag_offset is not None:
            logger.debug(
                "[FlagMgr] Invalidating cached committed-flag pointer "
                "(was 0x%X)", self._committed_flag_offset
            )
        self._committed_flag_offset = None
        self._guest_to_host_delta = None

    def _discover_committed_flags(self) -> bool:
        """Discover the FlagMgr's committed flag data by chasing pointers.

        The game's ``determineFinalItemid`` reads item flags through
        ``get_flag_or_counter`` which uses the *committed* flag copy inside
        FlagMgr.  This is NOT the same as STATIC_ITEMFLAGS (the
        uncommitted/working copy).

        Pointer chain:
          ITEMFLAG_MGR (host offset) → FlagMgr guest ptr
            → FlagMgr.flags_ptr → FlagSpace guest ptr
              → FlagSpace.flag_ptr       → committed flag data (target)
              → FlagSpace.static_flag_ptr → STATIC_ITEMFLAGS (validation)

        The guest→host conversion delta is calibrated dynamically by
        comparing ``FlagSpace.static_flag_ptr`` (a guest address) against
        the known host offset of STATIC_ITEMFLAGS.

        Discovery is retried after a short cooldown on failure (the game
        may not have fully initialised FlagMgr yet).

        Returns True if the committed flag data location was resolved.
        """
        if self._committed_flag_offset is not None:
            return True

        # Respect retry cooldown — avoid hammering every frame.
        if time.time() < self._flagmgr_discovery_retry_at:
            return False  # already discovered

        if not self.memory or not self.memory.connected:
            return False

        # Step 1: Read the ITEMFLAG_MGR pointer (guest address of FlagMgr).
        flagmgr_guest = self.memory.read_pointer(GameOffsets.ITEMFLAG_MGR)
        if not flagmgr_guest or flagmgr_guest < 0x7100000000:
            now = time.time()
            if now >= self._flagmgr_invalid_log_retry_at:
                logger.debug("[FlagMgr] ITEMFLAG_MGR pointer is null or invalid")
                self._flagmgr_invalid_log_retry_at = now + 2.0
            self._flagmgr_discovery_retry_at = now + 2.0
            return False

        # Step 2: Try candidate guest→host deltas.
        #   0x7100004000 — typical for BSS/data-segment globals
        #   0x7100000000 — typical for heap/manager pointers
        for delta in [0x7100004000, 0x7100000000, 0x7100008000, 0x7100002000]:
            flagmgr_host = flagmgr_guest - delta
            if flagmgr_host < 0 or flagmgr_host > 0xFFFFFFFF:
                continue

            try:
                # Read FlagMgr.funcs — should be a valid guest vtable ptr
                funcs_guest = self.memory.read_pointer(flagmgr_host)
                if not funcs_guest or funcs_guest < 0x7100000000:
                    continue

                # Read FlagMgr.flags_ptr at offset 16
                flagspace_guest = self.memory.read_pointer(
                    flagmgr_host + GameOffsets.FLAGMGR_FLAGS_PTR_OFFSET
                )
                if not flagspace_guest or flagspace_guest < 0x7100000000:
                    continue

                flagspace_host = flagspace_guest - delta
                if flagspace_host < 0 or flagspace_host > 0xFFFFFFFF:
                    continue

                # Read FlagSpace.static_flag_ptr at offset 8 (validation)
                static_ptr_guest = self.memory.read_pointer(
                    flagspace_host + GameOffsets.FLAGSPACE_STATIC_PTR_OFFSET
                )
                if not static_ptr_guest:
                    continue

                # Validate: static_flag_ptr - delta should equal our known
                # STATIC_ITEMFLAGS host offset.
                if (static_ptr_guest - delta) != GameOffsets.STATIC_ITEMFLAGS:
                    continue

                # Validation passed — delta is correct!
                # Now read FlagSpace.flag_ptr (committed flag data pointer).
                flag_ptr_guest = self.memory.read_pointer(
                    flagspace_host + GameOffsets.FLAGSPACE_FLAG_PTR_OFFSET
                )
                if not flag_ptr_guest or flag_ptr_guest < 0x7100000000:
                    # flag_ptr might be 0 if not yet initialized (title screen)
                    logger.debug(
                        "[FlagMgr] Delta 0x%X validated but flag_ptr is null "
                        "(game may not be loaded yet)", delta
                    )
                    return False

                committed_host = flag_ptr_guest - delta
                if committed_host < 0 or committed_host > 0xFFFFFFFF:
                    continue

                # Sanity check: committed flags should NOT be the same as
                # STATIC_ITEMFLAGS (otherwise there's no point).
                if committed_host == GameOffsets.STATIC_ITEMFLAGS:
                    logger.info(
                        "[FlagMgr] Committed flags == STATIC_ITEMFLAGS "
                        "(flag_ptr == static_flag_ptr); single-copy mode"
                    )
                    # Still usable — just means the game uses one copy.
                    # Writing to STATIC_ITEMFLAGS is sufficient.
                    self._guest_to_host_delta = delta
                    self._committed_flag_offset = committed_host
                    return True

                # Verify we can read from the committed flag area.
                test = self.memory.read_short(committed_host)
                if test is None:
                    logger.warning(
                        "[FlagMgr] Cannot read committed flags at host "
                        "offset 0x%X", committed_host
                    )
                    continue

                self._guest_to_host_delta = delta
                self._committed_flag_offset = committed_host
                logger.info(
                    "[FlagMgr] Pointer chain resolved: delta=0x%X, "
                    "FlagMgr@0x%X, FlagSpace@0x%X, committed_flags=0x%X "
                    "(host 0x%X), static_flags=0x%X",
                    delta, flagmgr_guest, flagspace_guest,
                    flag_ptr_guest, committed_host,
                    static_ptr_guest,
                )
                return True

            except Exception as exc:
                logger.debug(
                    "[FlagMgr] Delta 0x%X failed: %s", delta, exc
                )
                continue

        logger.warning(
            "[FlagMgr] Could not resolve pointer chain (FlagMgr@0x%X). "
            "Committed flag writes will be skipped this cycle.",
            flagmgr_guest,
        )
        # Retry after 5 seconds instead of permanently giving up.
        # FlagMgr may not be initialised yet during early loading.
        self._flagmgr_discovery_retry_at = time.time() + 5.0
        return False

    def _validate_committed_pointer(self) -> bool:
        """Re-validate the cached committed-flag pointer.

        Reads ``FlagSpace.static_flag_ptr`` through the cached delta and
        verifies it still resolves to ``STATIC_ITEMFLAGS``.  Returns False
        if the pointer chain has moved (e.g. heap reallocated during a
        scene transition), signalling that ``_committed_flag_offset`` is
        stale and must be re-discovered.
        """
        if self._committed_flag_offset is None or self._guest_to_host_delta is None:
            return False

        try:
            flagmgr_guest = self.memory.read_pointer(GameOffsets.ITEMFLAG_MGR)
            if not flagmgr_guest or flagmgr_guest < 0x7100000000:
                return False

            delta = self._guest_to_host_delta
            flagmgr_host = flagmgr_guest - delta
            if flagmgr_host < 0 or flagmgr_host > 0xFFFFFFFF:
                return False

            flagspace_guest = self.memory.read_pointer(
                flagmgr_host + GameOffsets.FLAGMGR_FLAGS_PTR_OFFSET
            )
            if not flagspace_guest or flagspace_guest < 0x7100000000:
                return False

            flagspace_host = flagspace_guest - delta
            if flagspace_host < 0 or flagspace_host > 0xFFFFFFFF:
                return False

            static_ptr_guest = self.memory.read_pointer(
                flagspace_host + GameOffsets.FLAGSPACE_STATIC_PTR_OFFSET
            )
            if not static_ptr_guest:
                return False

            return (static_ptr_guest - delta) == GameOffsets.STATIC_ITEMFLAGS
        except Exception:
            return False

    def _check_itemflag(self, item_id: int) -> bool:
        """Read-only check: is the itemflag for this item currently set?

        Checks the uncommitted/static copy (the working copy the game checks
        during gameplay) to see if the game's actor-spawn set the flag.
        Does NOT write anything.

        Returns True if the flag is set, False otherwise.
        """
        if not self.memory or not self.memory.connected:
            return False
        if item_id > 215:
            return True  # virtual items have no flag — treat as OK

        flag_id = item_id
        word_idx = flag_id // 16
        bit_idx = flag_id % 16
        byte_off = word_idx * 2
        mask = 1 << bit_idx

        try:
            current = self.memory.read_short(GameOffsets.STATIC_ITEMFLAGS + byte_off)
            if current is not None:
                return bool(current & mask)
        except Exception as exc:
            logger.debug(f"[CheckFlag] Could not read flag {flag_id}: {exc}")
        return False

    def _ensure_itemflag_set(self, item_id: int) -> bool:
        """Guarantee an item is in the player's inventory by setting its flag
        directly in save memory.

        In SSHD the item-flag index equals the game item ID, so no
        separate mapping table is needed.  The flag is a single bit inside
        the ``itemflags [u16; 64]`` bitfield array.  We write to THREE
        flag copies:

        1. **FA_ITEMFLAGS** (SaveFile) — survives game saves.
        2. **STATIC_ITEMFLAGS** (uncommitted) — the working copy that
           ``set_flag`` writes to; committed on scene transitions.
        3. **Committed flag data** (via FlagMgr pointer chain) — the copy
           that ``get_flag_or_counter`` / ``determineFinalItemid`` reads.
           Discovered dynamically by ``_discover_committed_flags()``.

        Writing to all three guarantees that:
        - The flag persists across saves (FA).
        - The next ``do_commit`` preserves it (STATIC).
        - ``determineFinalItemid`` sees it *immediately* (committed).

        Returns True if the flag is confirmed set after the operation.
        """
        if not self.memory or not self.memory.connected:
            return False

        # Item IDs above 215 are custom/virtual (Archipelago Item 216,
        # traps 250+, goddess cubes 257+, Game Beatable 256).  These do
        # not have a real item flag in the vanilla flag table.
        # Exception: Key Rings (220-226) and Skeleton Key (227) write dungeon key counts.
        if item_id > 215:
            if 220 <= item_id <= 227:
                return self._ensure_dungeon_keys_set(item_id)
            return True  # nothing to set — not a failure

        flag_id = item_id
        word_idx = flag_id // 16
        bit_idx = flag_id % 16
        byte_off = word_idx * 2
        mask = 1 << bit_idx

        confirmed = False

        # Build the list of flag copy bases to write to.
        bases = [GameOffsets.FA_ITEMFLAGS, GameOffsets.STATIC_ITEMFLAGS]

        # Try to discover the FlagMgr committed flag data (lazy, cached).
        # Re-validate the cached pointer by re-reading the FlagSpace to
        # detect heap reallocation (e.g. after scene transitions).
        self._discover_committed_flags()
        if self._committed_flag_offset is not None:
            if self._validate_committed_pointer():
                bases.append(self._committed_flag_offset)
            else:
                # Pointer stale — invalidate and re-discover immediately.
                self._invalidate_committed_cache()
                self._discover_committed_flags()
                if self._committed_flag_offset is not None:
                    bases.append(self._committed_flag_offset)

        for base in bases:
            try:
                current = self.memory.read_short(base + byte_off)
                if current is None:
                    logger.warning(
                        f"[DirectFlag] read_short returned None at 0x{base + byte_off:x} "
                        f"for flag {flag_id}"
                    )
                    continue

                if not (current & mask):
                    self.memory.write_short(base + byte_off, current | mask)
                    # Read back to verify the write stuck
                    verify = self.memory.read_short(base + byte_off)
                    if verify is not None and (verify & mask):
                        label = "committed" if base == self._committed_flag_offset else (
                            "FA" if base == GameOffsets.FA_ITEMFLAGS else "STATIC"
                        )
                        logger.info(
                            f"[DirectFlag] Set itemflag {flag_id} "
                            f"(word {word_idx}, bit {bit_idx}) at {label} "
                            f"0x{base:x} [verified]"
                        )
                        confirmed = True
                    else:
                        logger.warning(
                            f"[DirectFlag] Write to flag {flag_id} at 0x{base:x} "
                            f"did NOT stick! wrote 0x{current | mask:04x}, "
                            f"read back 0x{verify:04x}" if verify is not None
                            else f"read back None"
                        )
                else:
                    # Flag was already set (game handled it)
                    confirmed = True
            except Exception as exc:
                logger.warning(f"[DirectFlag] Could not write flag {flag_id}: {exc}")

        return confirmed

    # Real per-dungeon Small Key game item IDs -> scene_idx. Matches the
    # DUNGEON_KEY_INFO order used in _ensure_dungeon_keys_set (id - 200 is
    # the index). Used to intercept and suppress real Small Key delivery
    # while that dungeon is under a forced Key Ring / Skeleton Key count —
    # the game's own native pickup code increments dungeonflags directly
    # via the buffer path, which our reapply loop can never reliably win a
    # race against.
    _SMALL_KEY_ITEM_ID_TO_SCENE = {
        200: 11,  # Skyview Temple
        201: 17,  # Lanayru Mining Facility
        202: 12,  # Ancient Cistern
        203: 15,  # Fire Sanctuary
        204: 18,  # Sandship
        205: 20,  # Sky Keep
        206: 9,   # Lanayru Caves
    }

    # Stage name -> dungeon-key scene_idx (matches DUNGEON_KEY_INFO order
    # used in _ensure_dungeon_keys_set). Used to scope the STATIC write to
    # only the dungeon the player is currently standing in, since
    # STATIC_DUNGEON_FLAGS holds only the current scene's data.
    _DUNGEON_KEY_STAGE_TO_SCENE = {
        b"D100":   11,  # Skyview Temple
        b"D101":   12,  # Ancient Cistern
        b"D201":   15,  # Fire Sanctuary
        b"D201_1": 15,  # Fire Sanctuary (inner)
        b"D300":   17,  # Lanayru Mining Facility
        b"D300_1": 17,  # Lanayru Mining Facility (back)
        b"D301":   18,  # Sandship
        b"D301_1": 18,  # Sandship (escape)
        b"D003_0": 20,  # Sky Keep (Courage Room)
        b"D003_1": 20,  # Sky Keep (Earth Temple Room)
        b"D003_2": 20,  # Sky Keep (Power Room)
        b"D003_3": 20,  # Sky Keep (Wisdom Room)
        b"D003_4": 20,  # Sky Keep (Lanayru Mining Facility Room)
        b"D003_5": 20,  # Sky Keep (Skyview Temple Room)
        b"D003_6": 20,  # Sky Keep (Dreadfuse Room)
        b"D003_7": 20,  # Sky Keep (Entrance Room)
        b"D003_8": 20,  # Sky Keep (Triforce Room)
        b"F303":   9,   # Lanayru Caves
    }

    def _current_dungeon_key_scene_idx(self) -> Optional[int]:
        """Return the dungeon-key scene_idx for the currently loaded stage,
        or None if not in a dungeon that has a Key Ring / Skeleton Key."""
        try:
            stage_raw = self.memory.read_bytes(GameOffsets.CURRENT_STAGE_NAME, 8)
            if not stage_raw:
                return None
            stage = stage_raw.split(b"\x00", 1)[0]
            return self._DUNGEON_KEY_STAGE_TO_SCENE.get(stage)
        except Exception:
            return None

    def _ensure_dungeon_keys_set(self, item_id: int) -> bool:
        """Direct-write fallback for Key Rings (220-226) and Skeleton Key (227).

        Writes the max key count for the relevant dungeon(s) directly to save
        memory (FA.dungeonflags) and the static dungeon flags so the doors
        open immediately without needing the game's actor system.
        """
        if not self.memory or not self.memory.connected:
            return False

        # FA.dungeonflags offset: FA base + 0xA64, layout [[u16;8];26]
        # Each u16[8] block is 16 bytes (8 × 2 bytes).
        # Key count is stored in slot [1]: lower nibble = current, upper nibble = obtained.
        FA_DUNGEON_FLAGS_OFFSET = 0x5AEAD54 + 0xA64  # absolute host offset
        STATIC_DUNGEON_FLAGS    = 0x182E128           # absolute host offset

        # scene_index per dungeon.
        DUNGEON_KEY_INFO = [
            11,  # SVT - item id 220
            17,  # LMF - item id 221
            12,  # AC  - item id 222
            15,  # FS  - item id 223
            18,  # SSH - item id 224
            20,  # SK  - item id 225
            9,   # Caves - item id 226
        ]

        if item_id == 227:
            targets = [(scene_idx, 5) for scene_idx in DUNGEON_KEY_INFO]  # skeleton key → all dungeons
        else:
            scene_idx = DUNGEON_KEY_INFO[item_id - 220]
            targets = [(scene_idx, 4)]  # one key ring

        confirmed = False
        for scene_idx, max_keys in targets:
            # High-water mark: never let a later, lower-value item (e.g. a
            # Key Ring arriving after the Skeleton Key) downgrade a dungeon
            # that's already been forced higher.
            forced = max(max_keys, self._forced_dungeon_keys.get(scene_idx, 0))
            self._forced_dungeon_keys[scene_idx] = forced

            if self._write_dungeon_key_count(scene_idx, forced, self._current_dungeon_key_scene_idx()):
                confirmed = True
                logger.info(
                    f"[DungeonKeys] Forced scene {scene_idx} keys to {forced} "
                    f"(requested {max_keys} for item_id {item_id})"
                )

        return confirmed

    def _write_dungeon_key_count(self, scene_idx: int, max_keys: int, current_scene_idx: Optional[int] = None) -> bool:
        """Write max_keys to a dungeon's key counter.

        FA is a per-scene array (FA base + 0xA64, [[u16;8];26]) so it's
        always safe to write regardless of where the player currently is.
        STATIC_DUNGEON_FLAGS is a SINGLE address that only ever holds the
        *currently loaded* dungeon's data — writing it for a dungeon the
        player isn't in would stomp whichever dungeon actually is loaded.
        So the STATIC write only happens when scene_idx == current_scene_idx.
        """
        FA_DUNGEON_FLAGS_OFFSET = 0x5AEAD54 + 0xA64  # absolute host offset
        STATIC_DUNGEON_FLAGS    = 0x182E128           # absolute host offset

        key_bits = (max_keys << 4) | max_keys
        fa_offset = FA_DUNGEON_FLAGS_OFFSET + scene_idx * 16 + 1 * 2

        wrote = False
        try:
            self.memory.write_short(fa_offset, key_bits)
            wrote = True
        except Exception as exc:
            logger.warning(f"[DungeonKeys] Failed to write FA dungeon flags for scene {scene_idx}: {exc}")

        if current_scene_idx is not None and scene_idx == current_scene_idx:
            static_offset = STATIC_DUNGEON_FLAGS + 1 * 2  # slot [1] of current scene
            try:
                self.memory.write_short(static_offset, key_bits)
            except Exception as exc:
                logger.warning(f"[DungeonKeys] Failed to write STATIC dungeon flags for scene {scene_idx}: {exc}")

        return wrote

    def reapply_forced_dungeon_keys(self) -> None:
        """Re-assert every forced dungeon key count. Call on every poll tick."""
        if not self._forced_dungeon_keys:
            return
        if not self.memory or not self.memory.connected:
            return
        current_scene_idx = self._current_dungeon_key_scene_idx()
        for scene_idx, max_keys in self._forced_dungeon_keys.items():
            self._write_dungeon_key_count(scene_idx, max_keys, current_scene_idx)

    def _clear_itemflag(self, item_id: int) -> bool:
        """Clear (unset) the itemflag for the given item in all flag copies.

        Mirrors _ensure_itemflag_set but ANDs with ~mask instead of ORing.
        Used to clean up stale progressive flags before re-presetting the
        correct state so determineFinalItemid resolves to the right tier.
        """
        if not self.memory or not self.memory.connected:
            return False
        if item_id > 215:
            return True

        flag_id = item_id
        word_idx = flag_id // 16
        bit_idx = flag_id % 16
        byte_off = word_idx * 2
        mask = 1 << bit_idx

        cleared = False
        bases = [GameOffsets.FA_ITEMFLAGS, GameOffsets.STATIC_ITEMFLAGS]
        self._discover_committed_flags()
        if self._committed_flag_offset is not None:
            if self._validate_committed_pointer():
                bases.append(self._committed_flag_offset)
            else:
                self._invalidate_committed_cache()
                self._discover_committed_flags()
                if self._committed_flag_offset is not None:
                    bases.append(self._committed_flag_offset)
        for base in bases:
            try:
                current = self.memory.read_short(base + byte_off)
                if current is None:
                    continue
                if current & mask:
                    new_val = current & (~mask & 0xFFFF)
                    self.memory.write_short(base + byte_off, new_val)
                    verify = self.memory.read_short(base + byte_off)
                    if verify is not None and not (verify & mask):
                        logger.info(
                            f"[DirectFlag] Cleared itemflag {flag_id} "
                            f"(word {word_idx}, bit {bit_idx}) at base 0x{base:x} "
                            f"[verified]"
                        )
                        cleared = True
                    else:
                        logger.warning(
                            f"[DirectFlag] Clear of flag {flag_id} at 0x{base:x} "
                            f"did NOT stick!"
                        )
                else:
                    cleared = True  # already clear
            except Exception as exc:
                logger.warning(f"[DirectFlag] Could not clear flag {flag_id}: {exc}")
        return cleared

    def _read_itemflags_word(self, word_idx: int) -> tuple:
        """Read a u16 word from both flag copies. Returns (fa_val, static_val)."""
        byte_off = word_idx * 2
        fa_val = None
        static_val = None
        try:
            fa_val = self.memory.read_short(GameOffsets.FA_ITEMFLAGS + byte_off)
        except Exception:
            pass
        try:
            static_val = self.memory.read_short(GameOffsets.STATIC_ITEMFLAGS + byte_off)
        except Exception:
            pass
        return (fa_val, static_val)

    def clear_buffer(self):
        """Clear all slots in item buffer."""
        if not self.buffer_addr:
            return
        for slot in range(GameOffsets.ARCHIPELAGO_BUFFER_SIZE):
            buffer_offset = self.buffer_addr + (slot * GameOffsets.ARCHIPELAGO_BUFFER_SLOT_SIZE)
            # Write 4 zero bytes to clear the slot (two 16-bit writes)
            self.memory.write_short(buffer_offset, 0)
            self.memory.write_short(buffer_offset + 2, 0)
        logger.info("Cleared Archipelago item buffer")

    def reapply_progressive_flags(
        self,
        progressive_counts: dict,
        tier_flag_table: dict,
    ) -> None:
        """Re-write all progressive item flags to all three flag copies.

        Called after scene transitions to guarantee that the committed flag
        copy (which ``determineFinalItemid`` reads) matches the items the
        player has actually received.  This closes the race window where
        a stale committed pointer or a ``copy_flags_from_save`` load could
        leave committed flags out of date.

        Args:
            progressive_counts: ``{"Progressive Sword": 3, ...}`` — the
                number of each progressive item received so far.
            tier_flag_table: ``{"Progressive Sword": [10,11,12,9,13,14], ...}``
                — ordered game-flag IDs for each progressive tier.
        """
        for prog_name, count in progressive_counts.items():
            if count <= 0:
                continue
            tier_ids = tier_flag_table.get(prog_name)
            if not tier_ids:
                continue
            for t in range(min(count, len(tier_ids))):
                self._ensure_itemflag_set(tier_ids[t])
