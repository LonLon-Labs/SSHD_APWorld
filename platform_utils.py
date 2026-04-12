"""
Cross-platform utilities for Windows, Linux, and macOS support.

Handles:
- Default directory paths for each OS
- Environment variable lookups
- Path normalization
"""

import os
import sys
from pathlib import Path
from typing import List, Optional


def get_os_name() -> str:
    """Get OS identifier: 'windows', 'linux', or 'darwin' (macOS)."""
    if sys.platform == "win32":
        return "windows"
    elif sys.platform == "linux":
        return "linux"
    elif sys.platform == "darwin":
        return "darwin"
    else:
        return sys.platform


def get_archipelago_dir() -> Path:
    """
    Get the Archipelago base directory for the current OS.
    
    Windows: C:\\ProgramData\\Archipelago or %APPDATA%\\Archipelago
    Linux: ~/.local/share/Archipelago
    macOS: ~/Library/Application Support/Archipelago
    """
    if get_os_name() == "windows":
        # Try PROGRAMDATA first (system-wide)
        if "PROGRAMDATA" in os.environ:
            return Path(os.environ["PROGRAMDATA"]) / "Archipelago"
        # Fall back to user AppData
        if "APPDATA" in os.environ:
            return Path(os.environ["APPDATA"]) / "Archipelago"
        # Ultimate fallback
        return Path("C:/ProgramData/Archipelago")
    
    elif get_os_name() == "linux":
        return Path.home() / ".local" / "share" / "Archipelago"
    
    elif get_os_name() == "darwin":  # macOS
        return Path.home() / "Library" / "Application Support" / "Archipelago"
    
    else:
        # Fallback for unknown OS
        return Path.home() / "Archipelago"


def get_default_sshd_extract_path() -> Path:
    """Get the default path to extract SSHD ROM files."""
    return get_archipelago_dir() / "sshd_extract"


# Supported emulators and their data directory names per OS.
# Order matters: the first match wins for process detection and mod install.
SUPPORTED_EMULATORS = ["Ryujinx", "yuzu", "suyu", "sudachi", "eden"]

# Map of emulator name (lowercase) -> Linux config dir name.
# Most yuzu-family emulators use lowercase directories on Linux.
_LINUX_DIR_NAMES = {
    "ryujinx": "Ryujinx",
    "yuzu":    "yuzu",
    "suyu":    "suyu",
    "sudachi": "sudachi",
    "eden":    "eden",
}


def get_emulator_dir(emulator: str = "Ryujinx") -> Path:
    """
    Get the base data directory for the given emulator on the current OS.

    Windows: %APPDATA%\\<emulator>
    Linux: ~/.config/<emulator>  (or ~/.local/share/<emulator> for yuzu-family)
    macOS: ~/Library/Application Support/<emulator>
    """
    emu_lower = emulator.lower()
    linux_name = _LINUX_DIR_NAMES.get(emu_lower, emulator)

    if get_os_name() == "windows":
        if "APPDATA" in os.environ:
            return Path(os.environ["APPDATA"]) / emulator
        return Path.home() / "AppData" / "Roaming" / emulator

    elif get_os_name() == "linux":
        # yuzu-family stores data in ~/.local/share/<name>
        if emu_lower != "ryujinx":
            xdg = os.environ.get("XDG_DATA_HOME", "")
            if xdg:
                return Path(xdg) / linux_name
            return Path.home() / ".local" / "share" / linux_name
        # Ryujinx uses ~/.config/Ryujinx
        return Path.home() / ".config" / linux_name

    elif get_os_name() == "darwin":
        return Path.home() / "Library" / "Application Support" / emulator

    else:
        return Path.home() / emulator


# Keep the old name as an alias for backward compatibility
def get_ryujinx_dir() -> Path:
    return get_emulator_dir("Ryujinx")


def _mod_dir_for_emulator(emulator: str) -> Path:
    """Return the LayeredFS / atmosphere mod path for one emulator."""
    game_id = "01002da013484000"
    base = get_emulator_dir(emulator)
    if emulator.lower() == "ryujinx":
        return base / "sdcard" / "atmosphere" / "contents" / game_id
    # yuzu-family: <data>/load/01002da013484000/Archipelago
    # But the atmosphere path layout also works if people set it up that way.
    # yuzu uses: <data>/load/<title_id>/<mod_name>/  (romfs/ and exefs/ inside)
    return base / "load" / game_id


def get_emulator_mod_dirs() -> List[Path]:
    """
    Get possible LayeredFS mod directories for SSHD across all supported emulators.

    Returns a list of paths to check, in order of preference.
    """
    paths: List[Path] = []
    for emu in SUPPORTED_EMULATORS:
        paths.append(_mod_dir_for_emulator(emu))

    # On Windows, also check alternative APPDATA locations for Ryujinx
    if get_os_name() == "windows":
        appdata = Path(os.environ.get("APPDATA", ""))
        if appdata.exists():
            game_id = "01002da013484000"
            paths.append(appdata / "Ryujinx" / "sdcard" / "atmosphere" / "contents" / game_id)

    return paths


# Keep old name as alias
def get_ryujinx_mod_dirs() -> List[Path]:
    return get_emulator_mod_dirs()


def find_emulator_mod_dir() -> Optional[Path]:
    """
    Find the first existing emulator mod directory for SSHD.

    Returns the first directory whose parent structure exists, or None.
    """
    for path in get_emulator_mod_dirs():
        # For Ryujinx-style: check sdcard/atmosphere exists
        # For yuzu-style: check load/ dir exists
        parent = path.parent
        if parent.exists():
            return path
    return None


def find_all_emulator_mod_dirs() -> List[Path]:
    """
    Find ALL existing emulator mod directories for SSHD.

    Returns every emulator mod path whose parent structure exists.
    Useful for installing to all installed emulators at once.
    """
    found: List[Path] = []
    for path in get_emulator_mod_dirs():
        parent = path.parent
        if parent.exists():
            found.append(path)
    return found


def find_mod_dir_for_emulator(emulator: str) -> Optional[Path]:
    """
    Find the mod directory for a specific emulator.

    Returns the mod path if the emulator's directory structure exists, or None.
    """
    path = _mod_dir_for_emulator(emulator)
    if path.parent.exists():
        return path
    return None


def detect_installed_emulators() -> List[str]:
    """
    Return the names of emulators whose base data directory exists.
    """
    return [emu for emu in SUPPORTED_EMULATORS if get_emulator_dir(emu).exists()]


# Keep old name as alias
def find_ryujinx_mod_dir() -> Optional[Path]:
    return find_emulator_mod_dir()


def normalize_path(path_str: str) -> Path:
    """
    Normalize a path string to a Path object, handling cross-platform separators.
    
    Converts Windows backslashes to forward slashes for consistency.
    """
    if not path_str:
        return Path()
    
    # Replace backslashes with forward slashes for consistency
    normalized = path_str.replace("\\", "/")
    return Path(normalized)


def get_custom_worlds_dir() -> Path:
    """Get the directory where custom .apworld files should be placed."""
    arch_dir = get_archipelago_dir()
    return arch_dir / "custom_worlds"


def print_os_info():
    """Print OS and path information for debugging."""
    os_name = get_os_name()
    print(f"OS: {os_name}")
    print(f"Archipelago dir: {get_archipelago_dir()}")
    print(f"Default SSHD extract: {get_default_sshd_extract_path()}")
    for emu in SUPPORTED_EMULATORS:
        print(f"{emu} dir: {get_emulator_dir(emu)}")
    print(f"Possible mod dirs: {get_emulator_mod_dirs()}")
    print(f"Found mod dir: {find_emulator_mod_dir()}")
