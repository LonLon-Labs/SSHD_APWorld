"""
Logic Converter for Skyward Sword HD Archipelago World.

Parses sshd-rando's world YAML files and macros.yaml to generate
Archipelago-compatible regions, entrances, events, and access rules.

This replaces the hand-coded basic rules with the full logic from sshd-rando,
giving us ~373 regions, ~825 entrances, ~137 events, and per-location rules.
"""

import os
import yaml
import re
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Any, Optional

from BaseClasses import CollectionState, Region, Entrance, Location, LocationProgressType

if TYPE_CHECKING:
    from . import SSHDWorld

logger = logging.getLogger(__name__)

# Path to sshd-rando backend data files (relative to this module)
_MODULE_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
_BACKEND_DIR = _MODULE_DIR / "sshd-rando-backend"
_WORLD_DATA_DIR = _BACKEND_DIR / "data" / "world"
_MACROS_PATH = _BACKEND_DIR / "data" / "macros.yaml"

# ---------------------------------------------------------------------------
# Item name normalization: sshd-rando YAML uses underscores, AP uses spaces
# Also some names need special mapping
# ---------------------------------------------------------------------------
_ITEM_NAME_FIXES = {
    "Goddesss_Harp": "Goddess's Harp",
    "Goddess's_Harp": "Goddess's Harp",  # alternate form
    "Water_Dragons_Scale": "Water Dragon's Scale",
    "Water_Dragon's_Scale": "Water Dragon's Scale",
    "Cawlins_Letter": "Cawlin's Letter",
    "Cawlin's_Letter": "Cawlin's Letter",
    "Beedles_Insect_Cage": "Beedle's Insect Cage",
    "Beedle's_Insect_Cage": "Beedle's Insect Cage",
    "Skipper's_Retreat_Statue": "Skipper's Retreat Statue",
    # Event name mismatch: reference has apostrophe, definition doesn't
    "Unlock_Skipper's_Retreat_Statue": "Unlock Skippers Retreat Statue",
    # Song items — YAML drops the apostrophe (Farores vs Farore's)
    "Farores_Courage": "Farore's Courage",
    "Nayrus_Wisdom": "Nayru's Wisdom",
    "Dins_Power": "Din's Power",
    # Goddess Cube item — YAML drops the apostrophe in Skipper's
    "Skippers_Retreat_Goddess_Cube": "Skipper's Retreat Goddess Cube",
}


def _normalize_item_name(name: str) -> str:
    """Convert sshd-rando item/macro name (underscored) to AP item name (spaced)."""
    if name in _ITEM_NAME_FIXES:
        return _ITEM_NAME_FIXES[name]
    return name.replace("_", " ")


# ---------------------------------------------------------------------------
# Sentinel constant-rule functions
# These allow the parser and event builder to detect rules that always resolve
# to True or False (e.g. because a setting like a trick is "off").
# Using named functions with identity (is) comparison lets us short-circuit
# AND/OR expressions and skip creating permanently-unreachable event locations.
# ---------------------------------------------------------------------------

def _always_true(state, player):
    return True

def _always_false(state, player):
    return False

ALWAYS_TRUE = _always_true
ALWAYS_FALSE = _always_false


# ---------------------------------------------------------------------------
# Requirement string parser
# 
# Converts sshd-rando logic strings like:
#   "Sword and (Bomb_Bag or Bow) and 'Some_Event'"
# into Python callables: (CollectionState, int) -> bool
# ---------------------------------------------------------------------------

class _ReqParser:
    """
    Parses sshd-rando requirement strings into AP-compatible lambda functions.
    
    Each parsed requirement is a callable: (state: CollectionState, player: int) -> bool
    
    Settings are resolved at parse time (like sshd-rando does) into True/False constants,
    so there's no runtime setting branching.
    """
    
    def __init__(self, resolved_settings: dict[str, str], known_items: set[str],
                 macros: dict[str, Callable] = None, backend_dir: Path = None,
                 vanilla_items: set[str] = None):
        self.resolved_settings = resolved_settings
        self.known_items = known_items  # Set of AP item names that exist
        self.macros: dict[str, Callable] = macros or {}
        self.events: set[str] = set()  # Discovered event names (cumulative)
        self._last_parse_events: set[str] = set()  # Event refs from last parse() call
        # Track areas referenced by can_access()
        self.can_access_areas: set[str] = set()
        # Backend directory for loading data files
        self._backend_dir = backend_dir or _BACKEND_DIR
        # Items that are collected in vanilla (not shuffled into AP pool).
        # Any rule requiring these items is automatically satisfied.
        self.vanilla_items: set[str] = vanilla_items or set()
        # Setting info for comparison operators — maps setting name -> list of option values
        self._setting_options: dict[str, list[str]] = {}
        self._load_setting_options()
    
    def _load_setting_options(self):
        """Load setting option lists from settings_list.yaml for comparison operators."""
        settings_path = self._backend_dir / "data" / "settings_list.yaml"
        if settings_path.exists():
            try:
                with open(settings_path, "r", encoding="utf-8") as f:
                    settings_data = yaml.safe_load(f)
                    for node in settings_data:
                        name = node.get("name", "")
                        options = node.get("options", [])
                        self._setting_options[name] = [str(o) for o in options]
            except Exception as e:
                logger.warning(f"Could not load settings_list.yaml: {e}")
    
    def parse(self, req_str: str) -> Callable[[CollectionState, int], bool]:
        """Parse a requirement string into an AP rule function."""
        self._last_parse_events = set()  # Reset per-parse event tracking
        if not req_str or req_str.strip() == "":
            return ALWAYS_TRUE
        
        req_str = str(req_str).strip()
        
        # Remove outer quotes if the whole thing is quoted
        if req_str.startswith('"') and req_str.endswith('"'):
            req_str = req_str[1:-1].strip()
        
        return self._parse_expr(req_str)

    def get_last_parse_event_refs(self) -> set[str]:
        """Return the set of AP event item names referenced by the last parse() call."""
        return set(self._last_parse_events)
    
    def _parse_expr(self, expr: str) -> Callable[[CollectionState, int], bool]:
        """Parse a single expression recursively."""
        expr = expr.strip()
        
        if not expr:
            return ALWAYS_TRUE
        
        # Split at top-level spaces (respecting parentheses nesting)
        tokens = self._split_top_level(expr)
        
        if len(tokens) == 1:
            return self._parse_atom(tokens[0])
        
        if len(tokens) == 2 and tokens[0] == "not":
            inner = self._parse_atom_or_paren(tokens[1])
            if inner is ALWAYS_TRUE:
                return ALWAYS_FALSE
            if inner is ALWAYS_FALSE:
                return ALWAYS_TRUE
            return lambda state, player, _i=inner: not _i(state, player)
        
        # Check for and/or
        has_and = "and" in tokens
        has_or = "or" in tokens
        
        if has_and and has_or:
            # This shouldn't happen in well-formed logic, but handle it
            # by treating as AND (sshd-rando throws an error)
            logger.warning(f"Mixed and/or in expression: {expr}")
        
        if has_and:
            # Filter out "and" tokens, parse remaining
            parts = []
            i = 0
            while i < len(tokens):
                if tokens[i] == "and":
                    i += 1
                    continue
                if tokens[i] == "not" and i + 1 < len(tokens):
                    inner = self._parse_atom_or_paren(tokens[i + 1])
                    if inner is ALWAYS_TRUE:
                        parts.append(ALWAYS_FALSE)
                    elif inner is ALWAYS_FALSE:
                        parts.append(ALWAYS_TRUE)
                    else:
                        parts.append(lambda state, player, _i=inner: not _i(state, player))
                    i += 2
                else:
                    parts.append(self._parse_atom_or_paren(tokens[i]))
                    i += 1
            # Short-circuit: if ANY part is always-false, the whole AND is false
            if any(p is ALWAYS_FALSE for p in parts):
                return ALWAYS_FALSE
            # Filter out always-true parts (they don't affect AND)
            filtered = [p for p in parts if p is not ALWAYS_TRUE]
            if not filtered:
                return ALWAYS_TRUE
            if len(filtered) == 1:
                return filtered[0]
            return lambda state, player, _p=filtered: all(f(state, player) for f in _p)
        
        if has_or:
            parts = []
            i = 0
            while i < len(tokens):
                if tokens[i] == "or":
                    i += 1
                    continue
                if tokens[i] == "not" and i + 1 < len(tokens):
                    inner = self._parse_atom_or_paren(tokens[i + 1])
                    if inner is ALWAYS_TRUE:
                        parts.append(ALWAYS_FALSE)
                    elif inner is ALWAYS_FALSE:
                        parts.append(ALWAYS_TRUE)
                    else:
                        parts.append(lambda state, player, _i=inner: not _i(state, player))
                    i += 2
                else:
                    parts.append(self._parse_atom_or_paren(tokens[i]))
                    i += 1
            # Short-circuit: if ANY part is always-true, the whole OR is true
            if any(p is ALWAYS_TRUE for p in parts):
                return ALWAYS_TRUE
            # Filter out always-false parts (they don't affect OR)
            filtered = [p for p in parts if p is not ALWAYS_FALSE]
            if not filtered:
                return ALWAYS_FALSE
            if len(filtered) == 1:
                return filtered[0]
            return lambda state, player, _p=filtered: any(f(state, player) for f in _p)
        
        # Fallback: treat as AND of all tokens
        parts = [self._parse_atom_or_paren(t) for t in tokens]
        if any(p is ALWAYS_FALSE for p in parts):
            return ALWAYS_FALSE
        filtered = [p for p in parts if p is not ALWAYS_TRUE]
        if not filtered:
            return ALWAYS_TRUE
        if len(filtered) == 1:
            return filtered[0]
        return lambda state, player, _p=filtered: all(f(state, player) for f in _p)
    
    def _split_top_level(self, expr: str) -> list[str]:
        """Split expression by spaces at the top nesting level only."""
        tokens = []
        depth = 0
        current = []
        i = 0
        while i < len(expr):
            ch = expr[i]
            if ch == '(':
                depth += 1
                current.append(ch)
            elif ch == ')':
                depth -= 1
                current.append(ch)
            elif ch == ' ' and depth == 0:
                # Check if this space is part of a comparison operator (==, !=, >=, <=)
                # by looking at surrounding characters
                before = expr[i - 1] if i > 0 else ''
                after = expr[i + 1] if i + 1 < len(expr) else ''
                if before in '!=<>' or after in '!=<>':
                    # Don't split - this is part of a comparison operator
                    i += 1
                    continue
                else:
                    if current:
                        tokens.append(''.join(current))
                    current = []
            else:
                current.append(ch)
            i += 1
        if current:
            tokens.append(''.join(current))
        return tokens
    
    def _parse_atom_or_paren(self, token: str) -> Callable[[CollectionState, int], bool]:
        """Parse a token that might be parenthesized or an atom."""
        token = token.strip()
        if token.startswith('(') and token.endswith(')'):
            return self._parse_expr(token[1:-1])
        return self._parse_atom(token)
    
    def _parse_atom(self, atom: str) -> Callable[[CollectionState, int], bool]:
        """Parse a single atomic expression."""
        atom = atom.strip()
        
        # Strip outer parentheses
        while atom.startswith('(') and atom.endswith(')'):
            # Make sure these parens actually match
            depth = 0
            matched = True
            for i, ch in enumerate(atom):
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                if depth == 0 and i < len(atom) - 1:
                    matched = False
                    break
            if matched:
                atom = atom[1:-1].strip()
            else:
                break
        
        if not atom:
            return ALWAYS_TRUE
        
        # Nothing — always true
        if atom == "Nothing":
            return ALWAYS_TRUE
        
        # Impossible — always false
        if atom == "Impossible":
            return ALWAYS_FALSE
        
        # not_tracker — we're not the tracker, so this is true (NOTHING)
        if atom == "not_tracker":
            return ALWAYS_TRUE
        
        # Day — in AP we don't model time-of-day, so treat as always true
        if atom == "Day":
            return ALWAYS_TRUE
        
        # Night — same, treat as always true (conservative for accessibility)
        if atom == "Night":
            return ALWAYS_TRUE
        
        # Event reference: 'Event_Name'
        if atom.startswith("'") and atom.endswith("'"):
            event_name = atom[1:-1]
            self.events.add(event_name)
            ap_event_name = f"Event: {_normalize_item_name(event_name)}"
            self._last_parse_events.add(ap_event_name)  # Track per-parse
            return lambda state, player, _e=ap_event_name: state.has(_e, player)
        
        # count(N, Item_Name)
        if atom.startswith("count("):
            inner = atom[atom.index("(") + 1:atom.rindex(")")]
            inner = inner.replace(" ", "")
            parts = inner.split(",", 1)
            count_val = int(parts[0])
            item_name = _normalize_item_name(parts[1])
            # If this item is collected in vanilla (not shuffled), rule is auto-satisfied
            if item_name in self.vanilla_items:
                return ALWAYS_TRUE
            if count_val == 1:
                return lambda state, player, _i=item_name: state.has(_i, player)
            return lambda state, player, _c=count_val, _i=item_name: state.count(_i, player) >= _c
        
        # can_access(Area_Name)
        if atom.startswith("can_access("):
            area_name = atom[atom.index("(") + 1:atom.rindex(")")]
            self.can_access_areas.add(area_name)
            # can_access checks are resolved by AP's region reachability
            return lambda state, player, _a=area_name: state.can_reach_region(_a, player)
        
        # wallet_capacity(N)
        if atom.startswith("wallet_capacity("):
            required = int(atom[atom.index("(") + 1:atom.rindex(")")])
            return self._make_wallet_check(required)
        
        # gratitude_crystals(N)
        if atom.startswith("gratitude_crystals("):
            required = int(atom[atom.index("(") + 1:atom.rindex(")")])
            return self._make_crystal_check(required)
        
        # Setting comparison: setting_name == value, !=, >=, <=
        for op in ["==", "!=", ">=", "<="]:
            if op in atom:
                return self._resolve_setting_comparison(atom, op)
        
        # Boolean setting check (setting name as bare word that resolves to on/off)
        if atom.replace("_", " ") not in self.known_items and atom in self.resolved_settings:
            val = self.resolved_settings[atom]
            return ALWAYS_TRUE if (val == "on") else ALWAYS_FALSE
        
        # Macro expansion
        macro_name = atom.replace("_", " ")
        if macro_name in self.macros:
            return self.macros[macro_name]
        
        # Item check
        item_name = _normalize_item_name(atom)
        if item_name in self.known_items:
            # If this item is collected in vanilla (not shuffled), rule is auto-satisfied
            if item_name in self.vanilla_items:
                return ALWAYS_TRUE
            return lambda state, player, _i=item_name: state.has(_i, player)
        
        # Check if it could be a setting we haven't seen
        if atom in self.resolved_settings:
            val = self.resolved_settings[atom]
            return ALWAYS_TRUE if (val == "on") else ALWAYS_FALSE
        
        # Unknown — log warning and return True (permissive)
        logger.debug(f"Unknown logic atom: '{atom}' — treating as always-true")
        return ALWAYS_TRUE
    
    def _resolve_setting_comparison(self, expr: str, op: str) -> Callable:
        """Resolve a setting comparison to True or False at parse time."""
        # Find the operator position, handling spaces around it
        idx = expr.index(op)
        setting_name = expr[:idx].strip()
        compared_value = expr[idx + len(op):].strip()
        
        actual_value = self.resolved_settings.get(setting_name, None)
        if actual_value is None:
            logger.debug(f"Unknown setting '{setting_name}' in comparison — treating as False")
            return ALWAYS_FALSE
        
        # For numeric comparisons (>= , <=), use the option index
        if op in (">=", "<="):
            options = self._setting_options.get(setting_name, [])
            if options:
                try:
                    actual_idx = options.index(actual_value)
                    compared_idx = options.index(compared_value)
                    if op == ">=":
                        result = actual_idx >= compared_idx
                    else:
                        result = actual_idx <= compared_idx
                except ValueError:
                    result = False
            else:
                result = False
        elif op == "==":
            result = (actual_value == compared_value)
        elif op == "!=":
            result = (actual_value != compared_value)
        else:
            result = False
        
        return ALWAYS_TRUE if result else ALWAYS_FALSE
    
    def _make_wallet_check(self, required: int) -> Callable:
        """Create a wallet capacity check function."""
        def check_wallet(state: CollectionState, player: int) -> bool:
            prog_wallets = state.count("Progressive Wallet", player)
            extra_wallets = state.count("Extra Wallet", player)
            base = [300, 500, 1000, 5000, 9000]
            capacity = base[min(prog_wallets, len(base) - 1)]
            capacity += extra_wallets * 300
            return capacity >= required
        return check_wallet
    
    def _make_crystal_check(self, required: int) -> Callable:
        """Create a gratitude crystal count check function."""
        # If gratitude crystals are collected in vanilla, rule is auto-satisfied
        if "Gratitude Crystal" in self.vanilla_items:
            return ALWAYS_TRUE
        def check_crystals(state: CollectionState, player: int) -> bool:
            singles = state.count("Gratitude Crystal", player)
            packs = state.count("Gratitude Crystal Pack", player)
            return singles + (packs * 5) >= required
        return check_crystals


# ---------------------------------------------------------------------------
# Main converter: reads YAML, builds AP world graph
# ---------------------------------------------------------------------------

class SSHDLogicConverter:
    """
    Reads sshd-rando's world YAML files and macros, and generates an
    Archipelago-compatible region graph with full logic rules.
    """
    
    def __init__(self, world: "SSHDWorld", backend_dir: Path = None):
        self.world = world
        self.player = world.player
        self.multiworld = world.multiworld
        self.resolved_settings = getattr(world, '_sshd_resolved_settings', {})
        
        # Backend directory for loading data files
        self._backend_dir = backend_dir or _BACKEND_DIR
        self._world_data_dir = self._backend_dir / "data" / "world"
        self._macros_path = self._backend_dir / "data" / "macros.yaml"
        
        # Collect all known AP item names
        try:
            from .Items import ITEM_TABLE
        except ImportError:
            from Items import ITEM_TABLE
        self.known_items: set[str] = set(ITEM_TABLE.keys())
        
        # Add items that might appear in logic but aren't in ITEM_TABLE
        # (sshd-rando references items by their exact names)
        self._add_extra_known_items()
        
        # Build set of items that are collected in vanilla (not shuffled into AP).
        # Rules that require these items are auto-satisfied since the player
        # picks them up through normal in-game actions, not via AP.
        vanilla_items = self._compute_vanilla_items()
        
        # Parser instance
        self.parser = _ReqParser(self.resolved_settings, self.known_items,
                                 backend_dir=self._backend_dir,
                                 vanilla_items=vanilla_items)
        
        # Excluded location types (computed from settings in _create_locations)
        self.excluded_item_types: set[str] = set()  # Types excluded from item pool
        
        # Data structures built during conversion
        self.area_data: list[dict] = []  # Raw parsed YAML data
        self.macros: dict[str, Callable] = {}  # name -> rule function
        
        # AP objects
        self.regions: dict[str, Region] = {}  # name -> Region
        self.events: dict[str, list] = {}  # event_name -> [(area_name, rule_func)]
        
        # Location name -> SSHDLocation data from Locations.py
        try:
            from .Locations import LOCATION_TABLE
        except ImportError:
            from Locations import LOCATION_TABLE
        self.location_table = LOCATION_TABLE
        # Build set of valid location names
        self.valid_location_names: set[str] = set(LOCATION_TABLE.keys())
    
    def _add_extra_known_items(self):
        """Add item names that logic references but might not be in AP ITEM_TABLE."""
        # Goddess Cube trigger items (referenced in logic for goddess chests)
        # These are items like "Deep_Woods_Goddess_Cube_on_top_of_Temple"
        # that gate goddess chests on sky islands
        # Add all items from sshd-rando's items.yaml that might not be in AP
        items_path = self._backend_dir / "data" / "items.yaml"
        if items_path.exists():
            try:
                with open(items_path, "r", encoding="utf-8") as f:
                    items_data = yaml.safe_load(f)
                    for item in items_data:
                        name = item.get("name", "")
                        stripped = name.replace("'", "")
                        self.known_items.add(stripped)
                        # Also add underscore version for matching
                        self.known_items.add(stripped.replace(" ", "_"))
            except Exception as e:
                logger.warning(f"Could not load sshd-rando items.yaml: {e}")
    
    def _compute_vanilla_items(self) -> set[str]:
        """
        Build the set of item names that are collected in vanilla (not shuffled).
        When a shuffle setting is off, the corresponding items remain at their
        original locations in-game and should not be tracked by AP.  Any logic
        rule that checks for these items should be treated as auto-satisfied.
        """
        s = self.resolved_settings
        vanilla: set[str] = set()

        # Tadtone shuffle
        if s.get("tadtone_shuffle", "off") not in ("on", "randomized"):
            vanilla.add("Group of Tadtones")

        # Gratitude crystal shuffle
        if s.get("gratitude_crystal_shuffle", "off") not in ("on", "randomized"):
            vanilla.add("Gratitude Crystal")
            vanilla.add("Gratitude Crystal Pack")

        # When goddess_chest_shuffle is ON, Goddess Chests become AP locations.
        # Goddess Cubes are never AP locations (dummy items), but their
        # requirements (including Goddess_Sword) must be propagated to the
        # corresponding chests via event locations. This is done in
        # _build_goddess_cube_events() — do NOT mark cube items as vanilla
        # here, since that would auto-satisfy them and drop the sword req.

        if vanilla:
            logger.info(f"Vanilla (non-shuffled) items for logic: {sorted(vanilla)}")

        return vanilla

    def convert(self):
        """
        Main entry point. Loads macros, parses all world YAMLs,
        then builds AP regions/entrances/events/locations with full logic.
        """
        self._load_macros()
        self._load_world_data()
        self._build_regions()
        self._create_locations()
        self._build_entrances()
        self._build_events()
        self._build_goddess_cube_events()
        self._build_location_rules()
        self._place_victory_event()
    
    def _build_goddess_cube_events(self):
        """
        When goddess_chest_shuffle is on, create event locations for each
        Goddess Cube strike.  Each cube's YAML requirements (including
        Goddess_Sword, i.e. 2 Progressive Swords) are preserved as the
        event's access rule.  The event item name matches the cube's item
        name so that Goddess Chest logic properly requires the sword.

        When goddess_chest_shuffle is off, Goddess Chests are excluded from
        the AP world entirely, so no cube events are needed.
        """
        s = self.resolved_settings
        if s.get("goddess_chest_shuffle", "off") not in ("on", "randomized"):
            return  # Chests aren't AP locations — nothing to gate

        from BaseClasses import Item as APItem, ItemClassification

        # Load locations.yaml to identify Goddess Cube locations + item names
        locations_path = self._backend_dir / "data" / "locations.yaml"
        if not locations_path.exists():
            logger.warning("locations.yaml not found — cannot create goddess cube events")
            return

        with open(locations_path, "r", encoding="utf-8") as f:
            loc_data = yaml.safe_load(f)

        # Map: cube location name (YAML) -> original_item name (AP item name)
        cube_item_map: dict[str, str] = {}
        for loc in loc_data:
            if "Goddess Cube" in loc.get("types", []):
                loc_name = loc.get("name", "")
                item_name = loc.get("original_item", "")
                if loc_name and item_name:
                    cube_item_map[loc_name] = item_name

        # Find each cube's requirements from the world YAML data.
        # A cube can be defined in multiple areas (different access paths).
        cube_rules: dict[str, list[tuple[str, str]]] = {}
        for area_node in self.area_data:
            area_name = area_node["name"]
            for loc_name, req_str in area_node.get("locations", {}).items():
                if loc_name in cube_item_map:
                    cube_rules.setdefault(loc_name, []).append(
                        (area_name, str(req_str))
                    )

        events_created = 0
        for cube_loc_name, item_name in cube_item_map.items():
            entries = cube_rules.get(cube_loc_name)
            if not entries:
                logger.debug(f"No YAML rule found for goddess cube '{cube_loc_name}' — skipping")
                continue

            # Build the access rule
            if len(entries) == 1:
                area_name, req_str = entries[0]
                rule = self.parser.parse(req_str)
                region = self.regions.get(area_name)
            else:
                # Multiple access points — OR the paths together
                parsed_rules: list[tuple[str, Callable]] = []
                for area_name, req_str in entries:
                    parsed_rules.append((area_name, self.parser.parse(req_str)))
                region = self.regions.get(entries[0][0])

                def _make_or_rule(rule_list, pid):
                    def _or(state, player):
                        for a_name, r_fn in rule_list:
                            if state.can_reach_region(a_name, pid) and r_fn(state, pid):
                                return True
                        return False
                    return _or

                rule = _make_or_rule(parsed_rules, self.player)

            if not region:
                logger.debug(
                    f"Region not found for goddess cube '{cube_loc_name}' — skipping"
                )
                continue

            # Create event location
            event_location = Location(
                self.player,
                f"{cube_loc_name} (Cube Strike)",
                None,  # Event location — no address
                region,
            )
            event_location.locked = True
            event_location.progress_type = LocationProgressType.DEFAULT

            # The event item name must be the EXACT cube item name (no "Event:"
            # prefix) so that the parser's `state.has(item_name, player)` call
            # produced for Goddess Chest requirements matches this item.
            event_item = APItem(
                item_name,
                ItemClassification.progression,
                None,  # Event item — no code
                self.player,
            )

            event_location.place_locked_item(event_item)

            player = self.player
            event_location.access_rule = (
                lambda state, _r=rule, _p=player: _r(state, _p)
            )

            region.locations.append(event_location)
            events_created += 1

        logger.debug(
            f"Created {events_created} goddess cube event locations "
            f"(goddess_chest_shuffle is on)"
        )

    def _get_excluded_location_types(self) -> set[str]:
        """
        Determine which location types must be EXCLUDED from the AP world.

        When a shuffle setting is off, the corresponding locations stay
        vanilla in-game and must not be AP locations. If they existed as
        AP locations without their vanilla items in the pool, Archipelago's
        fill algorithm would place random items there — which is wrong.

        This mirrors sshd-rando-backend's get_disabled_shuffle_locations().
        """
        excluded: set[str] = set()
        s = self.resolved_settings

        # Goddess Cubes are dummy logic items (oarc: null) used internally by
        # sshd-rando to link cube-strike locations to sky Goddess Chests.
        # They have no in-game model and must never be AP locations.
        excluded.add("Goddess Cube")

        # Goddess Chests: excluded unless goddess_chest_shuffle is on
        if s.get("goddess_chest_shuffle", "off") not in ("on", "randomized"):
            excluded.add("Goddess Chests")

        # Simple on/off toggles
        _TOGGLE_MAP = {
            "Tadtones":              "tadtone_shuffle",
            "Gratitude Crystals":    "gratitude_crystal_shuffle",
            "Stamina Fruits":        "stamina_fruit_shuffle",
            "Hidden Items":          "hidden_item_shuffle",
            "Gossip Stone Treasures": "gossip_stone_treasure_shuffle",
            "Underground Rupees":    "underground_rupee_shuffle",
        }
        for loc_type, setting_key in _TOGGLE_MAP.items():
            val = s.get(setting_key, "off")
            if val not in ("on", "randomized"):
                excluded.add(loc_type)

        # NPC Closet shuffle: "vanilla" means off
        if s.get("npc_closet_shuffle", "vanilla") == "vanilla":
            excluded.add("Closets")

        # Beedle's Airshop: "vanilla" means off
        if s.get("beedle_shop_shuffle", "vanilla") == "vanilla":
            excluded.add("Beedle's Airshop")

        # Rupee shuffle is tiered: vanilla < beginner < intermediate < advanced
        rupee_val = s.get("rupee_shuffle", "vanilla")
        if rupee_val == "vanilla":
            excluded.update(["Beginner Rupees", "Intermediate Rupees", "Advanced Rupees"])
        elif rupee_val == "beginner":
            excluded.update(["Intermediate Rupees", "Advanced Rupees"])
        elif rupee_val == "intermediate":
            excluded.add("Advanced Rupees")

        return excluded

    def _get_excluded_item_types(self) -> set[str]:
        """
        Determine which location types' ITEMS should be excluded from the
        AP item pool based on shuffle settings. When a shuffle is off, items
        from those locations are replaced with filler in the pool, but the
        locations themselves still exist in the AP world.
        """
        s = self.resolved_settings
        excluded: set[str] = set()

        # Simple on/off toggles: type excluded when setting is not "on"
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
            val = s.get(setting_key, "off")
            if val not in ("on", "randomized"):
                excluded.add(loc_type)

        # NPC Closet shuffle: "vanilla" means off
        if s.get("npc_closet_shuffle", "vanilla") == "vanilla":
            excluded.add("Closets")

        # Rupee shuffle is tiered: vanilla < beginner < intermediate < advanced
        rupee_val = s.get("rupee_shuffle", "vanilla")
        if rupee_val == "vanilla":
            excluded.update(["Beginner Rupees", "Intermediate Rupees", "Advanced Rupees"])
        elif rupee_val == "beginner":
            excluded.update(["Intermediate Rupees", "Advanced Rupees"])
        elif rupee_val == "intermediate":
            excluded.add("Advanced Rupees")
        # "advanced" → nothing extra excluded

        # Goddess Cubes are dummy logic items — always exclude from pool too
        excluded.add("Goddess Cube")

        return excluded

    def _create_locations(self):
        """
        Create AP Location objects from LOCATION_TABLE and place them
        into their initial regions. The _build_location_rules step will
        later move them to fine-grained sshd-rando regions.

        When a shuffle setting is off, the corresponding locations are
        excluded from the AP world entirely so Archipelago won't place
        random items at them. This mirrors get_disabled_shuffle_locations()
        in the sshd-rando backend.
        """
        try:
            from .Items import ITEM_TABLE as AP_ITEM_TABLE
        except ImportError:
            from Items import ITEM_TABLE as AP_ITEM_TABLE
        
        # Build a map from sshd-rando YAML: location_name -> first area that defines it
        yaml_location_areas: dict[str, str] = {}
        for area_node in self.area_data:
            area_name = area_node["name"]
            for loc_name in area_node.get("locations", {}).keys():
                if loc_name not in yaml_location_areas:
                    yaml_location_areas[loc_name] = area_name
        
        excluded_types = self._get_excluded_location_types()

        # Dusk Relic exclusion: trial_treasure_shuffle is a numeric value (0-10).
        # Relics whose number exceeds the setting are excluded.
        # When 0, all Dusk Relic locations are excluded.
        s = self.resolved_settings
        trial_treasure_val = s.get("trial_treasure_shuffle", "0")
        # "random" means all relics are enabled
        trial_treasure_is_random = trial_treasure_val == "random"
        try:
            trial_treasure_num = int(trial_treasure_val) if not trial_treasure_is_random else 999
        except (ValueError, TypeError):
            trial_treasure_num = 0

        if excluded_types:
            logger.info(f"Excluding location types: {sorted(excluded_types)}")
        
        locations_created = 0
        locations_excluded = 0
        for name, data in self.location_table.items():
            if data.code is None:
                continue
            
            # Exclude location types determined by _get_excluded_location_types()
            if excluded_types and any(t in excluded_types for t in data.types):
                locations_excluded += 1
                continue

            # Dusk Relic per-location check: exclude relics above the setting number
            if "Dusk Relic" in data.types and not trial_treasure_is_random:
                try:
                    relic_num = int(name.split(" ")[-1])
                except (ValueError, IndexError):
                    relic_num = 0
                if relic_num > trial_treasure_num:
                    locations_excluded += 1
                    continue
            
            # Determine which region to place this location in:
            # 1. If sshd-rando YAML defines it in an area, use that area
            # 2. Otherwise use the coarse region from LOCATION_TABLE
            target_region_name = yaml_location_areas.get(name, data.region)
            region = self.regions.get(target_region_name)
            
            if not region:
                # Fallback to the coarse region
                region = self.regions.get(data.region)
            
            if not region:
                # Create the region as a last resort
                region = Region(data.region, self.player, self.multiworld)
                self.multiworld.regions.append(region)
                self.regions[data.region] = region
            
            location = Location(
                self.player,
                name,
                data.code,
                region
            )
            region.locations.append(location)
            locations_created += 1
        
        if locations_excluded:
            logger.info(f"Excluded {locations_excluded} locations (shuffle settings off)")
        logger.info(f"Created {locations_created} locations")
    
    def _place_victory_event(self):
        """
        Create a proper event location for Game Beatable in the same region
        as the Defeat Demise location.
        
        IMPORTANT: We do NOT place the event at the real "Defeat Demise"
        location (address=2773238) because AP requires that locations with
        int addresses have items with int codes. Event items have code=None.
        Instead, we create a separate event-only location (address=None)
        in the Temple of Hylia region.
        
        The event's access rule embeds ALL completion requirements
        (boss keys + sword level) so the fill algorithm properly tracks
        dependencies. The completion_condition just checks state.has("Game Beatable").
        """
        from BaseClasses import Item as APItem, ItemClassification
        
        try:
            # Find the region that contains the Defeat Demise location.
            # The YAML defines it in "Temple of Hylia" area.
            target_region = self.regions.get("Temple of Hylia")
            if not target_region:
                # Fallback: try the Hylia's Realm region from LOCATION_TABLE
                target_region = self.regions.get("Hylia's Realm")
            if not target_region:
                logger.warning("Could not find Temple of Hylia or Hylia's Realm region for victory event")
                return
            
            # Create a proper event location (address=None)
            event_location = Location(
                self.player,
                "Victory - Game Beatable",
                None,  # Event location: no address
                target_region
            )
            event_location.locked = True
            event_location.progress_type = LocationProgressType.DEFAULT
            
            # Build the access rule: embed _can_complete_game requirements
            # so the fill algorithm properly tracks boss key + sword dependencies.
            player = self.player
            world = self.world
            
            def victory_access_rule(state):
                """Check all game completion requirements."""
                resolved = getattr(world, '_sshd_resolved_settings', {})
                
                # Boss key check
                boss_keys_setting = resolved.get('boss_keys', 'own_dungeon')
                if boss_keys_setting != 'removed':
                    try:
                        required_dungeons = int(resolved.get('required_dungeons', '2'))
                    except (ValueError, TypeError):
                        required_dungeons = 2
                    
                    dungeon_keys = [
                        "Skyview Temple Boss Key",
                        "Earth Temple Boss Key",
                        "Lanayru Mining Facility Boss Key",
                        "Ancient Cistern Boss Key",
                        "Sandship Boss Key",
                        "Fire Sanctuary Boss Key"
                    ]
                    # Cap at 6: Sky Keep (7th dungeon) has no boss key.
                    # Its accessibility is handled by region/entrance logic.
                    boss_keys_needed = min(required_dungeons, len(dungeon_keys))
                    dungeons_beaten = sum(1 for key in dungeon_keys if state.has(key, player))
                    if dungeons_beaten < boss_keys_needed:
                        return False
                
                # Sword level check
                got_sword = resolved.get('got_sword_requirement', 'true_master_sword')
                sword_levels = {
                    'goddess_sword': 2, 'goddess_longsword': 3,
                    'goddess_white_sword': 4, 'master_sword': 5,
                    'true_master_sword': 6,
                }
                required_level = sword_levels.get(got_sword, 6)
                if state.count("Progressive Sword", player) < required_level:
                    return False
                
                return True
            
            event_location.access_rule = victory_access_rule
            
            # Create event item
            event_item = APItem(
                "Game Beatable",
                ItemClassification.progression,
                None,  # Event items must have None code
                self.player
            )
            
            # Place the event item
            event_location.place_locked_item(event_item)
            
            # Add to region
            target_region.locations.append(event_location)
            
            logger.info(f"Placed victory event in region '{target_region.name}'")
        except Exception as e:
            logger.warning(f"Could not create victory event location: {e}")
            import traceback
            traceback.print_exc()
    
    def _load_macros(self):
        """Load and parse macros.yaml into callable rule functions."""
        if not self._macros_path.exists():
            logger.warning(f"macros.yaml not found at {self._macros_path}")
            return
        
        with open(self._macros_path, "r", encoding="utf-8") as f:
            macros_data = yaml.safe_load(f)
        
        # Macros can reference other macros, so we parse them in order.
        # Since macros.yaml is ordered such that dependencies come first,
        # a single pass should work for most. We do two passes to be safe.
        for pass_num in range(2):
            for macro_name, req_str in macros_data.items():
                if macro_name in self.macros and pass_num == 0:
                    continue  # Already parsed
                try:
                    self.parser.macros = self.macros
                    rule = self.parser.parse(str(req_str))
                    self.macros[macro_name] = rule
                except Exception as e:
                    if pass_num == 1:
                        logger.debug(f"Could not parse macro '{macro_name}': {e}")
                    # Will retry on second pass
        
        # Update parser with all macros
        self.parser.macros = self.macros
        logger.info(f"Loaded {len(self.macros)} macros")
    
    def _load_world_data(self):
        """Load all world YAML files."""
        if not self._world_data_dir.exists():
            logger.warning(f"World data directory not found at {self._world_data_dir}")
            return
        
        for filepath in sorted(self._world_data_dir.iterdir()):
            if not filepath.suffix == ".yaml":
                continue
            with open(filepath, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data:
                    self.area_data.extend(data)
        
        logger.info(f"Loaded {len(self.area_data)} area nodes from world YAMLs")
    
    def _build_regions(self):
        """Create AP Region objects for every area in the world data."""
        # Always create Menu region
        menu = Region("Menu", self.player, self.multiworld)
        self.multiworld.regions.append(menu)
        self.regions["Menu"] = menu
        
        # Create a region for every area defined in the world YAMLs
        for area_node in self.area_data:
            area_name = area_node["name"]
            if area_name not in self.regions:
                region = Region(area_name, self.player, self.multiworld)
                self.multiworld.regions.append(region)
                self.regions[area_name] = region
            
            # Also create regions for exit targets that might not have their own area node
            for dest_name in area_node.get("exits", {}).keys():
                if dest_name not in self.regions:
                    region = Region(dest_name, self.player, self.multiworld)
                    self.multiworld.regions.append(region)
                    self.regions[dest_name] = region
        
        # Ensure all regions from location_table exist (for any locations
        # in regions not defined in world YAMLs)
        for loc_data in self.location_table.values():
            if loc_data.region not in self.regions:
                region = Region(loc_data.region, self.player, self.multiworld)
                self.multiworld.regions.append(region)
                self.regions[loc_data.region] = region
        
        logger.info(f"Created {len(self.regions)} AP regions")
    
    def _build_entrances(self):
        """Create AP Entrance objects with parsed access rules."""
        # Connect Menu -> Root (sshd-rando's Root area)
        if "Root" in self.regions:
            menu = self.regions["Menu"]
            root = self.regions["Root"]
            menu.connect(root, "Menu -> Root")
        
        # Build entrances from world data
        for area_node in self.area_data:
            area_name = area_node["name"]
            source_region = self.regions.get(area_name)
            if not source_region:
                continue
            
            for dest_name, req_str in area_node.get("exits", {}).items():
                dest_region = self.regions.get(dest_name)
                if not dest_region:
                    continue
                
                entrance_name = f"{area_name} -> {dest_name}"
                
                # Parse the requirement string into a rule
                rule = self.parser.parse(str(req_str))
                
                # Create the entrance with the rule
                player = self.player  # capture for lambda
                entrance = source_region.connect(
                    dest_region,
                    entrance_name,
                    lambda state, _r=rule, _p=player: _r(state, _p)
                )
        
        logger.info(f"Created entrances from {len(self.area_data)} area nodes")
    
    def _build_events(self):
        """
        Create AP event locations and items for every event defined in world YAMLs.
        
        Events in sshd-rando are intermediate state flags (like 'Push_Down_Log')
        that are achievable when their requirement is met in their area. In AP,
        we model these as event locations with event items.
        
        Events whose rule is always-false (e.g. because a trick setting is off)
        are skipped entirely to avoid accessibility warnings.
        
        After creation, a zombie-cleanup pass removes events that depend on
        non-existent events (which would make them permanently unreachable and
        cause Archipelago's accessibility check to fail).
        """
        from BaseClasses import Item as APItem, ItemClassification
        
        events_created = 0
        events_skipped = 0
        
        # Track created events and their dependencies for zombie cleanup
        created_event_names: set[str] = set()  # AP event item names actually created
        event_locations_by_name: dict[str, Location] = {}  # AP event name -> Location
        event_deps: dict[str, set[str]] = {}  # AP event name -> set of AP event names it references
        
        for area_node in self.area_data:
            area_name = area_node["name"]
            
            for event_name, req_str in area_node.get("events", {}).items():
                # Parse the access rule first so we can check for always-false
                rule = self.parser.parse(str(req_str))
                event_refs = self.parser.get_last_parse_event_refs()
                
                # Skip events with always-false rules (e.g. trick settings that are off)
                if rule is ALWAYS_FALSE:
                    events_skipped += 1
                    continue
                
                # Normalize event name: YAML may use spaces or underscores
                # Requirements always reference events with underscores, and
                # the parser normalizes them with _normalize_item_name (underscores→spaces).
                # So we must normalize the event item name the same way.
                normalized_event_name = _normalize_item_name(event_name.replace(" ", "_"))
                ap_event_name = f"Event: {normalized_event_name}"
                
                region = self.regions.get(area_name)
                if not region:
                    continue
                
                # Create event location
                event_location = Location(
                    self.player,
                    f"{area_name} - {event_name}",
                    None,  # No code = event location
                    region
                )
                event_location.locked = True
                event_location.progress_type = LocationProgressType.DEFAULT
                
                # Create event item
                event_item = APItem(
                    ap_event_name,
                    ItemClassification.progression,
                    None,  # No code = event item
                    self.player
                )
                
                # Place the event item at the event location
                event_location.place_locked_item(event_item)
                
                # Set the access rule
                player = self.player
                event_location.access_rule = lambda state, _r=rule, _p=player: _r(state, _p)
                
                # Add to region
                region.locations.append(event_location)
                events_created += 1
                
                # Track for zombie cleanup
                created_event_names.add(ap_event_name)
                event_locations_by_name[ap_event_name] = event_location
                event_deps[ap_event_name] = event_refs
        
        # --- Zombie event cleanup ---
        # An event is a "zombie" if its rule references another event that
        # doesn't exist (was skipped or is itself a zombie). Such events can
        # never be reached at runtime, and their presence as advancement
        # locations causes Archipelago's accessibility check to fail.
        zombies_removed = 0
        changed = True
        while changed:
            changed = False
            for ap_name in list(created_event_names):
                deps = event_deps.get(ap_name, set())
                # Check if any dependency is NOT a created event
                missing = deps - created_event_names
                if missing:
                    # This event can never be reached — remove it
                    event_loc = event_locations_by_name[ap_name]
                    parent = event_loc.parent_region
                    if parent and event_loc in parent.locations:
                        parent.locations.remove(event_loc)
                    created_event_names.discard(ap_name)
                    changed = True
                    zombies_removed += 1
                    logger.debug(f"Removed zombie event '{ap_name}' (missing deps: {missing})")
        
        if zombies_removed:
            logger.info(f"Removed {zombies_removed} zombie event locations (unreachable due to missing dependencies)")
        logger.info(f"Created {events_created - zombies_removed} event locations (skipped {events_skipped} always-false, removed {zombies_removed} zombies)")
    
    def _build_location_rules(self):
        """
        Set per-location access rules from the world YAML data.
        
        Each location in sshd-rando has a requirement string defined in the
        area it belongs to. We parse these and set them as AP access rules.
        """
        # Build a map: location_name -> [(area_name, req_str)] from world data
        location_rules: dict[str, list[tuple[str, str]]] = {}
        for area_node in self.area_data:
            area_name = area_node["name"]
            for loc_name, req_str in area_node.get("locations", {}).items():
                if loc_name not in location_rules:
                    location_rules[loc_name] = []
                location_rules[loc_name].append((area_name, str(req_str)))
        
        # Now apply rules to AP locations
        rules_applied = 0
        
        for location in self.multiworld.get_locations(self.player):
            if location.address is None:
                continue  # Events already have rules
            
            loc_name = location.name
            if loc_name not in location_rules:
                continue
            
            entries = location_rules[loc_name]
            
            if len(entries) == 1:
                area_name, req_str = entries[0]
                rule = self.parser.parse(req_str)
                player = self.player
                location.access_rule = lambda state, _r=rule, _p=player: _r(state, _p)
                rules_applied += 1
            else:
                # Multiple access points — location is in the first area's region,
                # but can be accessed from any of the defining areas.
                # Build a compound rule that checks if ANY access path works.
                rules = []
                for area_name, req_str in entries:
                    rule = self.parser.parse(req_str)
                    rules.append((area_name, rule))
                
                player = self.player
                
                def make_multi_rule(rule_list, player_id):
                    def multi_rule(state):
                        for area_name, rule_func in rule_list:
                            if state.can_reach_region(area_name, player_id) and rule_func(state, player_id):
                                return True
                        return False
                    return multi_rule
                
                location.access_rule = make_multi_rule(rules, player)
                rules_applied += 1
        
        logger.info(f"Applied {rules_applied} location access rules")


# ---------------------------------------------------------------------------
# Public API — called from __init__.py
# ---------------------------------------------------------------------------

def build_full_logic(world: "SSHDWorld", backend_dir: Path = None):
    """
    Build the complete world graph with full sshd-rando logic.
    
    This replaces the basic Regions.py + Rules.py approach with auto-generated
    regions, entrances, events, and per-location access rules parsed directly
    from sshd-rando's world YAML files.
    
    Args:
        world: The SSHDWorld instance.
        backend_dir: Path to sshd-rando-backend directory. If None, uses the
                     default module-relative path (works for local dev).
                     When running from .apworld, pass the extracted temp path.
    
    Call this INSTEAD of the old create_regions + set_rules approach.
    """
    converter = SSHDLogicConverter(world, backend_dir=backend_dir)
    converter.convert()
    return converter
