"""
Wrapper to integrate sshd-rando generation into Archipelago.
Calls sshd-rando's generation pipeline and returns the World object for item manipulation.

NOTE: This wrapper requires sshd-rando to be installed locally. When running from bundled
.apworld files, sshd-rando must be available in the parent directory of the SSHD world module.
"""

import sys
import os
from pathlib import Path
import tempfile
import shutil
import zipfile
import random
from typing import Tuple, Dict, Any

# ---------------------------------------------------------------------------
# Detect sshd-rando-backend.
#
# When loaded from an .apworld, __init__.py has ALREADY extracted sshd-rando-
# backend (and _bundled_deps) into a temp directory and inserted them into
# sys.path.  We look there first so we never create a competing extraction.
# ---------------------------------------------------------------------------

def _find_sshd_rando_on_sys_path():
    """Check sys.path for an already-extracted sshd-rando-backend."""
    for p in sys.path:
        candidate = Path(p)
        if candidate.name == "sshd-rando-backend" and candidate.is_dir():
            if (candidate / "logic").is_dir() and (candidate / "constants").is_dir():
                return candidate
    return None


def _find_sshd_rando_path():
    """Find sshd-rando-backend directory, checking multiple locations."""
    # 1) Already on sys.path (set by __init__.py extraction)
    on_path = _find_sshd_rando_on_sys_path()
    if on_path:
        return on_path

    # 2) Filesystem locations (development / manual install)
    current_file = Path(__file__).resolve()
    potential_paths = [
        current_file.parent / "sshd-rando-backend",
        current_file.parent.parent / "sshd-rando-backend",
        current_file.parent.parent / "sshd-rando",
        Path.home() / "sshd-rando",
    ]
    for path in potential_paths:
        if path.is_dir() and (path / "logic").is_dir() and (path / "constants").is_dir():
            return path

    return None

POTENTIAL_SSHD_RANDO_PATHS = [
    Path(__file__).parent / "sshd-rando-backend",
    Path(__file__).parent.parent / "sshd-rando-backend",
    Path(__file__).parent.parent / "sshd-rando",
    Path.home() / "sshd-rando",
]

# NOTE: Do NOT resolve at import time — __init__.py hasn't extracted
# sshd-rando-backend from the .apworld zip yet when this module is first
# imported.  Resolution is deferred to _initialize_sshd_rando().
SSHD_RANDO_PATH = None

CURRENT_DIR = Path(__file__).parent

# Flag to track if sshd-rando has been initialized (checked lazily, not at import time)
_sshd_rando_initialized = False

def _initialize_sshd_rando():
    """Lazy initialization of sshd-rando imports. Only called when actually generating."""
    global _sshd_rando_initialized, SSHD_RANDO_PATH
    
    if _sshd_rando_initialized:
        return
    
    # Resolve path NOW (after __init__.py has extracted into temp and set sys.path)
    if SSHD_RANDO_PATH is None:
        SSHD_RANDO_PATH = _find_sshd_rando_path()
        if SSHD_RANDO_PATH:
            print(f"[SSHDRWrapper] Found sshd-rando-backend at: {SSHD_RANDO_PATH}")
    
    # Check if sshd-rando was found
    if SSHD_RANDO_PATH is None or not SSHD_RANDO_PATH.exists():
        current_file = Path(__file__).resolve()
        debug_info = [
            f"Current file: {current_file}",
            f"Parent directory: {current_file.parent}",
            f"sys.path entries with 'sshd': {[p for p in sys.path if 'sshd' in p.lower()]}",
        ]
        raise ImportError(
            f"sshd-rando not found. Searched in:\n" +
            "\n".join(f"  - {path} (exists: {path.exists()})" for path in POTENTIAL_SSHD_RANDO_PATHS) +
            "\n\nAlso checked sys.path for sshd-rando-backend directory.\n" +
            "\n".join(debug_info) +
            "\n\nPlease ensure sshd-rando-backend is installed in one of the searched locations."
        )
    
    # ------------------------------------------------------------------
    # Ensure the backend is at the FRONT of sys.path and flush the
    # import-finder caches.  Without invalidate_caches(), Python may
    # still resolve packages from an earlier snapshot of sys.path and
    # fail to find 'randomizer' even though it now exists on disk.
    # ------------------------------------------------------------------
    backend_str = str(SSHD_RANDO_PATH)
    if backend_str in sys.path:
        sys.path.remove(backend_str)
    sys.path.insert(0, backend_str)
    
    # Also ensure _bundled_deps is near the top (right after backend)
    for p in list(sys.path):
        if p.endswith("_bundled_deps"):
            sys.path.remove(p)
            sys.path.insert(1, p)
            break
    
    import importlib
    importlib.invalidate_caches()
    
    # Verify the critical sub-package is reachable BEFORE anything
    # tries to import it transitively (i.e. via logic.generate).
    randomizer_init = SSHD_RANDO_PATH / "randomizer" / "__init__.py"
    if not randomizer_init.is_file():
        raise ImportError(
            f"sshd-rando-backend is missing randomizer/__init__.py "
            f"(looked in {SSHD_RANDO_PATH / 'randomizer'}). "
            f"Contents: {list((SSHD_RANDO_PATH / 'randomizer').iterdir()) if (SSHD_RANDO_PATH / 'randomizer').is_dir() else 'DIR NOT FOUND'}"
        )

    # Force-import 'randomizer' from our backend so no stale/shadowed
    # version from elsewhere can interfere.
    import importlib.util
    if "randomizer" in sys.modules:
        del sys.modules["randomizer"]
    spec = importlib.util.spec_from_file_location(
        "randomizer",
        str(randomizer_init),
        submodule_search_locations=[str(SSHD_RANDO_PATH / "randomizer")],
    )
    randomizer_mod = importlib.util.module_from_spec(spec)
    sys.modules["randomizer"] = randomizer_mod
    spec.loader.exec_module(randomizer_mod)

    # Mock the GUI modules to avoid PySide6 dependency
    from unittest.mock import MagicMock
    
    sys.modules['PySide6'] = MagicMock()
    sys.modules['PySide6.QtCore'] = MagicMock()
    sys.modules['PySide6.QtWidgets'] = MagicMock()
    sys.modules['gui'] = MagicMock()
    sys.modules['gui.dialogs'] = MagicMock()
    sys.modules['gui.dialogs.dialog_header'] = MagicMock()
    sys.modules['gui.guithreads'] = MagicMock()
    
    _sshd_rando_initialized = True


def create_sshd_rando_config(settings_dict: Dict[str, Any], output_dir: Path, seed: str = None) -> 'Config':
    """
    Create an sshd-rando Config object from Archipelago settings.
    
    Args:
        settings_dict: Dictionary of SSHD setting names → values
        output_dir: Path where romfs/exefs should be generated
        seed: Seed string (e.g. "AirStrongholdPlantSkipper")
    
    Returns:
        Config object compatible with sshd-rando
        print(f"[SSHDRWrapper] ======== create_sshd_rando_config CALLED ========")
        print(f"[SSHDRWrapper] settings_dict keys: {list(settings_dict.keys())}")
    """
    # Import sshd-rando modules (lazy load)
    from logic.config import Config, create_default_setting, write_config_to_file
    from logic.settings import get_all_settings_info, SettingMap
    
    # Create default config first
    config = Config()
    config.output_dir = output_dir
    # Note: seed should be specified in the YAML config file, not set directly here
    # Let sshd-rando's generate() function handle seed from config file
    config.generate_spoiler_log = False  # We don't need spoiler logs
    
    # Add default SettingMap for one world
    config.settings.append(SettingMap())
    setting_map = config.settings[0]
    
    # Initialize all settings to defaults
    for setting_name in get_all_settings_info():
        setting_map.settings[setting_name] = create_default_setting(setting_name)
    
    # Now override with settings from settings_dict
    # Apply ALL settings that exist in both settings_dict and sshd-rando settings
    # Skip special keys that are handled separately or are metadata
    skip_keys = {
        'extract_path', 'setting_string', 'seed', 'generate_spoiler_log', 
        'use_plandomizer', 'plandomizer_file', 'custom_starting_items',
        '_setting_string_starting_items', '_sshd_hash',
        'starting_inventory', 'excluded_locations', 'excluded_hint_locations',
        'mixed_entrance_pools', 'other_mods'
    }
    
    print(f"[SSHDRWrapper] Applying settings from settings_dict ({len(settings_dict)} total settings)")
    applied_count = 0
    skipped_count = 0
    
    for setting_key, value in settings_dict.items():
        # Skip special keys
        if setting_key in skip_keys:
            continue
            
        # Check if this setting exists in sshd-rando
        if setting_key in setting_map.settings:
            setting = setting_map.settings[setting_key]
            
            # Convert Python booleans to string values that sshd-rando expects
            if isinstance(value, bool):
                value_str = "on" if value else "off"
            elif isinstance(value, (int, float)):
                value_str = str(value)
            elif isinstance(value, list):
                # Handle lists (like starting_inventory items)
                value_str = str(value)
            else:
                value_str = str(value)
            
            # Find the option index for this value in the setting's valid options
            if setting.info and value_str in setting.info.options:
                option_index = setting.info.options.index(value_str)
                setting.update_current_value(option_index)
                applied_count += 1
            else:
                # Value not found in options - might be "random" or invalid
                # Try to apply it anyway if it's a valid string option
                if setting.info:
                    # Check if "random" is a valid option
                    if value_str == "random" and "random" in setting.info.options:
                        option_index = setting.info.options.index("random")
                        setting.update_current_value(option_index)
                        applied_count += 1
                    else:
                        print(f"[SSHDRWrapper] Warning: Value '{value_str}' not valid for setting '{setting_key}'. Valid options: {setting.info.options[:5]}...")
                        skipped_count += 1
        else:
            # Setting doesn't exist in sshd-rando
            skipped_count += 1
    
    print(f"[SSHDRWrapper] Applied {applied_count} settings, skipped {skipped_count} (not applicable or invalid)")
    
    # Handle starting_inventory from config.yaml (if present)
    # This is a list like: ["Progressive Pouch", "Scrapper", "Hylian Shield", ...]
    if "starting_inventory" in settings_dict:
        starting_items_list = settings_dict["starting_inventory"]
        if isinstance(starting_items_list, list):
            print(f"[SSHDRWrapper] Processing starting_inventory from config.yaml ({len(starting_items_list)} items)")
            for item_name in starting_items_list:
                # Add each item to the starting inventory
                if item_name in setting_map.starting_inventory:
                    setting_map.starting_inventory[item_name] += 1
                else:
                    setting_map.starting_inventory[item_name] = 1
            print(f"[SSHDRWrapper] Added {len(starting_items_list)} items to starting_inventory")
    
    # Handle excluded_locations from config.yaml (if present)
    # This is a list of location names that should NOT be randomized
    if "excluded_locations" in settings_dict:
        excluded_locs_list = settings_dict["excluded_locations"]
        if isinstance(excluded_locs_list, list):
            print(f"[SSHDRWrapper] Processing excluded_locations from config.yaml ({len(excluded_locs_list)} locations)")
            setting_map.excluded_locations = excluded_locs_list
            print(f"[SSHDRWrapper] Excluded {len(excluded_locs_list)} locations from randomization")
    
    # NOTE: excluded_locations from config.yaml always have the highest priority.
    # Even if a shuffle setting (like beedle_shop_shuffle) is turned on, individually
    # excluded locations remain vanilla.  We no longer strip Beedle locations from
    # the excluded list when the shop shuffle is enabled — the user's explicit
    # exclusions must be respected.
    
    # NOTE: excluded_hint_locations is NOT used in Archipelago mode
    # Archipelago disables all hints (overrides all hint counts to 0), so there's no need
    # to handle excluded_hint_locations. Gossip stone locations are hint-givers, not item
    # locations, so they don't exist in sshd-rando's location_table and would cause errors.
    # If user has excluded_hint_locations in their config.yaml, silently ignore it.
    if "excluded_hint_locations" in settings_dict:
        print(f"[SSHDRWrapper] INFO: excluded_hint_locations from config.yaml ignored (Archipelago disables hints)")
    
    # Handle mixed_entrance_pools from config.yaml (if present)
    if "mixed_entrance_pools" in settings_dict:
        mixed_pools = settings_dict["mixed_entrance_pools"]
        if isinstance(mixed_pools, list):
            # Filter out empty lists
            mixed_pools = [pool for pool in mixed_pools if pool]
            if mixed_pools:
                print(f"[SSHDRWrapper] Processing mixed_entrance_pools from config.yaml ({len(mixed_pools)} pools)")
                setting_map.mixed_entrance_pools = mixed_pools
    
    # Handle starting_sword (add Progressive Sword based on level)
    # Always add to setting_map.starting_inventory so that
    # world.starting_item_pool includes the sword for AP extraction.
    # (sshd-rando's item_pool.py handles its own fill separately but
    # that local dict is NOT what AP reads for precollected items.)
    if "starting_sword" in settings_dict:
        sword_value = settings_dict["starting_sword"]
        sword_levels = {
            "none": 0, "no_sword": 0,
            "practice_sword": 1,          # Progressive Sword x1
            "goddess_sword": 2,           # Progressive Sword x2
            "goddess_longsword": 3,       # Progressive Sword x3
            "goddess_white_sword": 4,     # Progressive Sword x4
            "master_sword": 5,            # Progressive Sword x5
            "true_master_sword": 6        # Progressive Sword x6
        }
        if isinstance(sword_value, int):
            sword_level = max(0, min(6, sword_value))
        else:
            sword_level = sword_levels.get(str(sword_value), 0)
        if sword_level > 0:
            existing = setting_map.starting_inventory.get("Progressive Sword", 0)
            setting_map.starting_inventory["Progressive Sword"] = existing + sword_level
            print(f"[SSHDRWrapper] Starting sword '{sword_value}' -> Progressive Sword x{sword_level} (total: {existing + sword_level})")
    


    # Ensure sshd-rando starting_sword setting matches the Archipelago option
    if "starting_sword" in settings_dict and "starting_sword" in setting_map.settings:
        starting_sword_setting = setting_map.settings["starting_sword"]
        sword_value = settings_dict["starting_sword"]
        sword_value_map = {
            0: "no_sword",
            1: "practice_sword",
            2: "goddess_sword",
            3: "goddess_longsword",
            4: "goddess_white_sword",
            5: "master_sword",
            6: "true_master_sword"
        }
        if isinstance(sword_value, int):
            sword_value_str = sword_value_map.get(sword_value, "goddess_sword")
        else:
            sword_value_str = str(sword_value)
        if starting_sword_setting.info and sword_value_str in starting_sword_setting.info.options:
            option_index = starting_sword_setting.info.options.index(sword_value_str)
            starting_sword_setting.update_current_value(option_index)
    
    # Handle custom_starting_items from YAML
    if "custom_starting_items" in settings_dict:
        custom_items = settings_dict["custom_starting_items"]
        if isinstance(custom_items, dict):
            for item_name, count in custom_items.items():
                if count > 0:
                    setting_map.starting_inventory[item_name] = count

    return config


def generate_sshd_rando_mod(settings_dict: Dict[str, Any], output_dir: Path, seed: str = None, apply_patches: bool = True) -> Tuple[Any, Path, str]:
    """
    Generate SSHD randomizer mod using sshd-rando backend.
    
    Args:
        settings_dict: Archipelago settings dictionary
        output_dir: Directory where romfs/exefs will be generated
        seed: Seed string (e.g. "AirStrongholdPlantSkipper"). If None, random seed is used.
        apply_patches: If True, apply patches immediately. If False, return world without patching (for Archipelago integration)
    
    Returns:
        Tuple of (World object, output_dir path, setting_string)
    
    Raises:
        Exception: If sshd-rando generation fails
    """
    # Check for lz4 module before anything else
    try:
        import lz4.block
    except ImportError as e:
        # Gather diagnostic info for debugging
        import importlib.machinery
        diag_lines = [
            f"Python version: {sys.version}",
            f"Extension suffixes: {importlib.machinery.EXTENSION_SUFFIXES}",
            f"sys.executable: {sys.executable}",
        ]
        # Check if bundled deps directory exists on sys.path
        for p in sys.path:
            if "_bundled_deps" in p:
                diag_lines.append(f"Bundled deps path: {p} (exists={os.path.isdir(p)})")
                lz4_dir = os.path.join(p, "lz4")
                if os.path.isdir(lz4_dir):
                    diag_lines.append(f"  lz4/ contents: {os.listdir(lz4_dir)}")
                    block_dir = os.path.join(lz4_dir, "block")
                    if os.path.isdir(block_dir):
                        diag_lines.append(f"  lz4/block/ contents: {os.listdir(block_dir)}")
                else:
                    diag_lines.append(f"  lz4/ directory: NOT FOUND")
        diag_str = "\n".join(diag_lines)
        error_msg = (
            "\n═══════════════════════════════════════════════════════════════\n"
            "ERROR: Required module 'lz4' could not be loaded!\n"
            "═══════════════════════════════════════════════════════════════\n\n"
            "The lz4 package should be bundled inside the .apworld file.\n"
            "If you see this error the .apworld was not built correctly,\n"
            "or the bundled extensions don't match your Python version.\n\n"
            f"Diagnostics:\n{diag_str}\n\n"
            "Rebuild with:  python build_apworld.py\n"
            "(make sure 'pip install lz4' has been run in the build environment first)\n"
            "═══════════════════════════════════════════════════════════════\n"
        )
        print(error_msg)
        raise Exception(
            f"Missing required dependency: lz4 ({type(e).__name__}: {e}). "
            f"Python {sys.version_info.major}.{sys.version_info.minor}. "
            "The .apworld may not have the right binary for this Python version."
        ) from e
    
    # ------------------------------------------------------------------
    # Determine extract_path BEFORE any sshd-rando modules are imported
    # so that filepathconstants.py picks up the correct absolute paths.
    # ------------------------------------------------------------------
    try:
        from platform_utils import get_default_sshd_extract_path
        default_path = str(get_default_sshd_extract_path())
    except ImportError:
        default_path = "C:\\ProgramData\\Archipelago\\sshd_extract"
    extract_path = Path(settings_dict.get("extract_path", default_path)).resolve()
    
    # Set env vars that our patched filepathconstants.py reads at import time.
    # SSHD_AP_EXTRACT_PATH  → overrides SSHD_EXTRACT_PATH (the romfs/exefs root)
    # SSHD_AP_USERDATA_PATH → overrides userdata_path (cache, output, config dirs)
    os.environ["SSHD_AP_EXTRACT_PATH"] = str(extract_path)
    os.environ["SSHD_AP_USERDATA_PATH"] = str(extract_path.parent)
    print(f"[SSHDRWrapper] Extract path: {extract_path}")
    print(f"[SSHDRWrapper] Userdata path: {extract_path.parent}")
    
    # If filepathconstants was already imported (e.g. multi-world), force
    # a reload so the new env vars take effect on all module-level constants.
    if "filepathconstants" in sys.modules:
        import importlib
        importlib.reload(sys.modules["filepathconstants"])
    
    # Initialize sshd-rando imports (lazy load)
    _initialize_sshd_rando()
    from logic.generate import generate
    from patches.allpatchhandler import AllPatchHandler
    from logic.config import write_config_to_file
    
    # Check if romfs is extracted
    romfs_path = extract_path / "romfs"
    
    if not romfs_path.exists():
        raise Exception(
            f"SSHD romfs not extracted. Please extract your SSHD ROM to:\n"
            f"  {extract_path}\n\n"
            f"The folder should contain 'romfs' and 'exefs' subdirectories."
        )
    
    # Create output directory - must be absolute path
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # CHECK IF SETTING STRING WAS PROVIDED FIRST (before creating config)
    setting_string = settings_dict.get("setting_string", "")
    if setting_string and setting_string.strip():
        print(f"[SSHDRWrapper] Using Setting String from Archipelago YAML")
        try:
            setting_string_file = output_dir / "setting_string.txt"
            setting_string_file.write_text(setting_string, encoding="utf-8")
            print(f"[SSHDRWrapper] Setting String written to: {setting_string_file}")
        except Exception as e:
            print(f"[SSHDRWrapper] WARNING: Could not write Setting String to file: {e}")
        
        # Use helper module to decode Setting String
        from .setting_string_decoder import decode_setting_string_to_config
        config = decode_setting_string_to_config(setting_string, output_dir, seed)
        
        # CRITICAL: Apply Archipelago-required overrides to the Setting String config.
        # The Setting String may have been generated with different settings (e.g.
        # progressive_items=off) that would break Archipelago's item system. The
        # overrides in settings_dict (set by _collect_archipelago_settings) must
        # take precedence.
        AP_REQUIRED_OVERRIDES = {
            "progressive_items": "on",
            "skip_demise": "off",
            "spawn_hearts": "on",
        }
        if hasattr(config, 'settings') and config.settings and len(config.settings) > 0:
            setting_map_for_overrides = config.settings[0]
            if hasattr(setting_map_for_overrides, 'settings'):
                for override_key, override_val in AP_REQUIRED_OVERRIDES.items():
                    if override_key in setting_map_for_overrides.settings:
                        setting = setting_map_for_overrides.settings[override_key]
                        if setting.info and override_val in setting.info.options:
                            option_index = setting.info.options.index(override_val)
                            setting.update_current_value(option_index)
                            print(f"[SSHDRWrapper] Applied AP override to Setting String config: {override_key}={override_val}")
                        else:
                            print(f"[SSHDRWrapper] WARNING: Could not apply override {override_key}={override_val} (option not found)")
        
        # EXTRACT SETTING STRING DECODED STARTING ITEMS (before other settings are applied)
        # These are the items that come directly from the Setting String, not from starting_sword/starting_hearts
        try:
            if hasattr(config, 'settings') and config.settings and len(config.settings) > 0:
                setting_map = config.settings[0]  # It's a list, not a dict!
                if hasattr(setting_map, 'starting_inventory'):
                    setting_string_starting_items = dict(setting_map.starting_inventory)
                    print(f"[SSHDRWrapper] Setting String decoded items: {len(setting_string_starting_items)} item types")
                    for item_name, count in setting_string_starting_items.items():
                        print(f"[SSHDRWrapper]   {item_name} x{count}")
                    # Store in settings_dict so __init__.py can access it
                    settings_dict['_setting_string_starting_items'] = setting_string_starting_items
        except Exception as e:
            print(f"[SSHDRWrapper] Exception during extraction: {e}")
            import traceback
            traceback.print_exc()
        
        # Write the populated config to file
        config_file = output_dir / "ap_config.yaml"
        from logic.config import write_config_to_file
        write_config_to_file(config_file, config, write_preferences=False)
        
        print(f"[SSHDRWrapper] Created config from Setting String")
        print(f"[SSHDRWrapper] Config written to: {config_file}")
    else:
        # FALLBACK: Use individual YAML settings conversion (if no Setting String provided)
        print(f"[SSHDRWrapper] Using individual YAML settings (no Setting String provided)")
        config = create_sshd_rando_config(settings_dict, output_dir, seed)
        config.output_dir = output_dir
        
        # Write config to the output directory
        config_file = output_dir / "ap_config.yaml"
        write_config_to_file(config_file, config, write_preferences=False)
        
        # If seed is specified, append it to the YAML config file
        # sshd-rando expects: seed: "12345" (as string) at the top level of the YAML
        if seed is not None:
            import yaml
            with open(config_file, 'r') as f:
                config_data = yaml.safe_load(f) or {}
            config_data['seed'] = str(seed)  # Convert to string for YAML
            with open(config_file, 'w') as f:
                yaml.dump(config_data, f, default_flow_style=False)
        
    
    # Now we have 'config' object populated either from Setting String or from individual settings
    # Ensure it's saved to the config file for reference
    if 'config_file' not in locals():
        # This shouldn't happen, but just in case
        config_file = output_dir / "ap_config.yaml"
    
    print(f"[SSHDRWrapper] Generating world logic with sshd-rando...")
    print(f"[SSHDRWrapper] Target output directory: {output_dir}")
    if seed:
        print(f"[SSHDRWrapper] Using seed: {seed}")
    else:
        print(f"[SSHDRWrapper] Using random seed")
    
    # DEBUG: Print the config file before generation
    try:
        import yaml
        with open(config_file, 'r') as f:
            config_data = yaml.safe_load(f) or {}
        print(f"[SSHDRWrapper] DEBUG: Config file seed field: {config_data.get('seed', 'NOT SET')}")
    except Exception as e:
        print(f"[SSHDRWrapper] DEBUG: Could not read config seed: {e}")
    
    # ---------------------------------------------------------------
    # Ensure the sshd-rando preferences file has the correct absolute
    # output_dir.  generate() -> load_config_from_file() -> load_preferences()
    # reads output_dir from a SEPARATE preferences.yaml.  If that file
    # is missing, stale, or relative, generate() will error out.
    # ---------------------------------------------------------------
    try:
        import filepathconstants as _fpc
        import yaml as _yaml
        _prefs_path = Path(_fpc.PREFERENCES_PATH)
        _prefs_path.parent.mkdir(parents=True, exist_ok=True)
        _prefs_data = {}
        if _prefs_path.is_file():
            with open(_prefs_path, 'r', encoding='utf-8') as _f:
                _prefs_data = _yaml.safe_load(_f) or {}
        _prefs_data['output_dir'] = output_dir.as_posix()
        with open(_prefs_path, 'w', encoding='utf-8') as _f:
            _yaml.safe_dump(_prefs_data, _f, sort_keys=False)
        print(f"[SSHDRWrapper] Wrote preferences output_dir: {output_dir.as_posix()}")
    except Exception as _e:
        print(f"[SSHDRWrapper] WARNING: Could not write preferences.yaml: {_e}")
    
    # Generate world (location placement logic)
    # Pass config_file path - generate() will read and use it
    worlds = generate(config_file)
    world = worlds[0]
    
    if world is None:
        raise Exception("sshd-rando generation failed: world is None")
    
    # CRITICAL: Override the output_dir after loading config
    # because sshd-rando might have loaded it as relative path
    world.config.output_dir = output_dir
    print(f"[SSHDRWrapper] Corrected world output dir to: {world.config.output_dir}")
    
    # Apply patches to create romfs/exefs (can be skipped for Archipelago integration)
    if apply_patches:
        print("[SSHDRWrapper] Applying patches to generate romfs/exefs...")
        patch_handler = AllPatchHandler(world)
        patch_handler.do_all_patches()
        
        # Verify output was created at the correct location
        romfs_out = output_dir / "romfs"
        exefs_out = output_dir / "exefs"
        
        if romfs_out.exists() and exefs_out.exists():
            print(f"[SSHDRWrapper] Successfully generated mod!")
            print(f"  romfs: {len(list(romfs_out.rglob('*')))} items")
            print(f"  exefs: {len(list(exefs_out.rglob('*')))} items")
        else:
            print(f"[ERROR] Output not found at expected location: {output_dir}")
            print(f"  romfs exists: {romfs_out.exists()}")
            print(f"  exefs exists: {exefs_out.exists()}")
    else:
        print("[SSHDRWrapper] Skipping patches (will be applied by Archipelago after overlay)")
    
    hash_value = world.config.get_hash()
    print(f"[SSHDRWrapper] Hash: {hash_value}")
    
    # Store the hash in settings_dict so __init__.py can pass it to Archipelago
    settings_dict['_sshd_hash'] = hash_value
    
    # Extract Setting String if available
    setting_string = ""
    if hasattr(world, 'config') and hasattr(world.config, 'setting_string'):
        setting_string = world.config.setting_string
        print(f"[SSHDRWrapper] Setting String: {setting_string[:60]}...")
    
    return world, output_dir, setting_string


def extract_location_item_mapping(world: Any) -> Dict[str, str]:
    """
    Extract the location → item mapping from the generated world.
    
    Args:
        world: sshd-rando World object
    
    Returns:
        Dictionary mapping location names to item names
    """
    location_item_map = {}
    
    # World is a World object with a list of areas
    # Each area has locations
    if not hasattr(world, 'areas'):
        print(f"[Warning] World object structure unexpected: {type(world)}")
        return location_item_map
    
    # Iterate through all areas and locations in the world
    for area in world.areas:
        if not hasattr(area, 'locations'):
            continue
        for location in area.locations:
            if location.current_item:
                location_item_map[location.name] = location.current_item.name
            else:
                location_item_map[location.name] = "Empty"
    
    return location_item_map


def inject_custom_flags_into_world(world: Any, custom_flag_mapping: Dict[int, int], 
                                   multiworld, player: int) -> None:
    """
    Inject custom flag assignments for ALL Archipelago locations into the sshd-rando world.
    
    This must be called BEFORE patches are applied so that the patcher writes
    ALL custom flags into the game ROM (not just the 472 it knows about).
    
    Args:
        world: sshd-rando World object (before patches)
        custom_flag_mapping: Dict[custom_flag_id, location_code] from _build_custom_flag_mapping()
        multiworld: Archipelago multiworld object
        player: Player number
    """
    if not hasattr(world, 'location_table'):
        print("[SSHDRWrapper] ERROR: World has no location_table - cannot inject custom flags!")
        return
    
    # Build reverse lookup: location_code -> custom_flag_id
    location_code_to_flag = {loc_code: flag_id for flag_id, loc_code in custom_flag_mapping.items()}
    
    injected_count = 0
    for location_name, location_obj in world.location_table.items():
        # Look up this location in Archipelago to get its location code
        try:
            ap_location = multiworld.get_location(location_name, player)
            if ap_location and ap_location.address is not None:
                location_code = ap_location.address
                
                # Check if we have a custom flag assignment for this location
                if location_code in location_code_to_flag:
                    custom_flag_id = location_code_to_flag[location_code]
                    
                    # Inject the custom flag into the sshd-rando location object
                    # The patcher will see this and write it into the ROM
                    location_obj.custom_flag = custom_flag_id
                    injected_count += 1
                    
                    if injected_count <= 10:  # Log first few for verification
                        print(f"[SSHDRWrapper]   {location_name}: custom_flag={custom_flag_id}")
        except Exception as e:
            # Some locations might not exist in Archipelago (vanilla-only)
            pass
    
    print(f"[SSHDRWrapper] Injected custom flags into {injected_count} locations")


def extract_custom_flag_mapping(world: Any) -> Dict[int, str]:
    """
    Extract the custom_flag → location_name mapping from the generated world.
    
    After sshd-rando's checkpatchhandler assigns custom flags to locations,
    this extracts that mapping so the Archipelago client knows which flags to monitor.
    
    Args:
        world: sshd-rando World object (after patches have been determined)
    
    Returns:
        Dictionary mapping custom_flag_id (int) to location_name (str)
    """
    custom_flag_map = {}
    
    if not hasattr(world, 'location_table'):
        print(f"[SSHDRWrapper] Warning: World has no location_table for custom flag extraction")
        return custom_flag_map
    
    # Iterate through all locations and extract custom flags
    for location_name, location in world.location_table.items():
        if hasattr(location, 'custom_flag'):
            custom_flag_id = location.custom_flag
            # Only store if it's a valid custom flag (not 0x3FF which means "no flag")
            if custom_flag_id != 0x3FF:
                custom_flag_map[custom_flag_id] = location_name
    
    print(f"[SSHDRWrapper] Extracted {len(custom_flag_map)} custom flag assignments")
    return custom_flag_map


def overlay_multiworld_items(world: Any, location_item_mapping: Dict[str, str]) -> Dict[str, Any]:
    """
    Overlay Archipelago multiworld items onto the sshd-rando generated world.
    
    This replaces items in SSHD locations with Archipelago multiworld items.
    Cross-world items are replaced with Archipelago Item (ID 216) containers.
    
    Args:
        world: sshd-rando World object with filled locations
        location_item_mapping: Dict[sshd_location_name] = ap_item_name
                              Maps SSHD location names to Archipelago item names
    
    Returns:
        Dictionary with overlay results:
        {
            "total_locations": int,
            "replaced_items": int,
            "cross_world_items": int,
            "unmapped_locations": int,
            "protected_locations_skipped": int
        }
    """
    # Locations with hardcoded game logic that MUST keep their original items
    # These locations have event flags tied to specific items that trigger game progression
    PROTECTED_LOCATIONS = {
    }
    
    results = {
        "total_locations": 0,
        "replaced_items": 0,
        "cross_world_items": 0,
        "unmapped_locations": 0,
        "protected_locations_skipped": 0
    }
    
    if not hasattr(world, 'item_table'):
        print(f"[SSHDRWrapper] Warning: World object doesn't have 'item_table' attribute")
        return results
    
    replaced_count = 0
    cross_world_count = 0
    unmapped_count = 0
    protected_count = 0
    
    # Get locations from sshd-rando world.location_table
    if not hasattr(world, 'location_table'):
        print(f"[SSHDRWrapper] Warning: World has no location_table attribute")
        print(f"[SSHDRWrapper] World type: {type(world)}")
        print(f"[SSHDRWrapper] Available attributes: {[a for a in dir(world) if not a.startswith('_')]}")
        return results
    
    print(f"[SSHDRWrapper] Processing {len(world.location_table)} locations from location_table")
    
    # Debug: Check if Archipelago Item is in item_table
    ap_item_lookup = "Archipelago Item"
    if ap_item_lookup in world.item_table:
        print(f"[SSHDRWrapper] ✓ Archipelago Item found in item_table")
    else:
        print(f"[SSHDRWrapper] ✗ Archipelago Item NOT in item_table!")
        print(f"[SSHDRWrapper] Available items (first 30): {list(world.item_table.keys())[:30]}...")
    
    # Track mapping distribution
    crossworld_in_mapping = sum(1 for v in location_item_mapping.values() if v not in world.item_table)
    print(f"[SSHDRWrapper] Mapping contains approximately {crossworld_in_mapping} cross-world item entries")
    
    # Iterate through all locations in the mapping
    for location_name, location in world.location_table.items():
        results["total_locations"] += 1
        
        # Skip protected locations - they have hardcoded game logic that depends on specific items
        if location_name in PROTECTED_LOCATIONS:
            protected_count += 1
            unmapped_count += 1
            print(f"[SSHDRWrapper] Protected location '{location_name}' - keeping original item")
            continue
        
        # Check if this location should have its item replaced
        if location_name in location_item_mapping:
            target_item_name = location_item_mapping[location_name]
            
            # sshd-rando strips apostrophes from item names when storing in item_table
            # So we need to do the same when looking them up
            target_item_lookup = target_item_name.replace("'", "")
            
            # Get or create the replacement item
            new_item = None
            
            # Check if this is explicitly an Archipelago Item (cross-world placeholder)
            is_cross_world = (target_item_name == "Archipelago Item")
            
            if target_item_lookup in world.item_table:
                new_item = world.item_table[target_item_lookup]
                # Log first few cross-world replacements
                if is_cross_world and cross_world_count <= 5:
                    print(f"[SSHDRWrapper] Using Archipelago Item for cross-world item at {location_name}")
            
            # If item not found, use Archipelago Item as fallback (cross-world item placeholder)
            if new_item is None:
                target_item_lookup = "Archipelago Item"
                if target_item_lookup in world.item_table:
                    new_item = world.item_table[target_item_lookup]
                    is_cross_world = True
                    # Log first few fallback replacements
                    if cross_world_count <= 5:
                        print(f"[SSHDRWrapper] Fallback: Using Archipelago Item for unmapped item '{target_item_name}' at {location_name}")
            
            # Safety check: ensure we have a valid item before replacing
            if new_item is None:
                print(f"[SSHDRWrapper] ERROR: Could not find item '{target_item_lookup}' OR Archipelago Item in item_table!")
                print(f"[SSHDRWrapper] Available items (first 30): {list(world.item_table.keys())[:30]}")
                unmapped_count += 1
                continue
            
            old_item_name = location.current_item.name if hasattr(location, 'current_item') and location.current_item else "Empty"
            
            try:
                # Replace the item in the location
                if hasattr(location, 'set_current_item'):
                    location.set_current_item(new_item)
                else:
                    location.current_item = new_item
                
                replaced_count += 1
                
                # Count cross-world items
                if is_cross_world:
                    cross_world_count += 1
                    # Debug first few replacements
                    if cross_world_count <= 3:
                        print(f"[SSHDRWrapper] Replaced with Archipelago Item at {location_name}")
                
            except Exception as e:
                print(f"[SSHDRWrapper] Warning: Failed to set item at {location_name}: {e}")
                unmapped_count += 1
        else:
            unmapped_count += 1
    
    results["replaced_items"] = replaced_count
    results["cross_world_items"] = cross_world_count
    results["unmapped_locations"] = unmapped_count
    results["protected_locations_skipped"] = protected_count
    print(f"[SSHDRWrapper] Overlay complete: {replaced_count} items replaced ({cross_world_count} Archipelago Items) from {results['total_locations']} total")
    
    return results


if __name__ == "__main__":
    # Test the wrapper
    test_settings = {
        "required_dungeon_count": 2,
        "triforce_required": True,
        "logic_rules": "all_locations_reachable",
    }
    
    test_output = Path(__file__).parent / "test_sshdr_output"
    
    try:
        # Test WITHOUT seed first to verify basic functionality
        world, output_path, setting_string = generate_sshd_rando_mod(test_settings, test_output)
        print(f"\n✓ Test successful!")
        print(f"  Generated at: {output_path}")
        print(f"  Setting String: {setting_string[:80] if setting_string else 'N/A'}...")
        
        # Show location mapping
        mapping = extract_location_item_mapping(world)
        print(f"  Total locations: {len(mapping)}")
        print(f"  Sample: {list(mapping.items())[:5]}")
        
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
