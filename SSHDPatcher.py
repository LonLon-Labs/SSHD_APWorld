"""
Standalone SSHD Archipelago Patcher (GUI)

Generates romfs/exefs mod files from a lightweight .apsshd patch file
using the end user's own extracted ROM files.

This allows multiworld generation to happen WITHOUT the ROM — only the
end user who plays the game needs the ROM extract. The .apsshd file
distributed by the host is much smaller since it contains only JSON data
(settings, item placements, flag mappings) instead of binary ROM patches.

Usage:
    GUI:  python SSHDPatcher.py [patch_file.apsshd]
    CLI:  python SSHDPatcher.py <patch_file.apsshd> --nogui [--extract-path <path>]

The patcher will:
1. Read settings and item placements from the .apsshd
2. Re-run sshd-rando world generation with the same settings/seed
3. Overlay the Archipelago multiworld items
4. Inject custom flags
5. Apply ROM patches using the user's extracted ROM
6. Install the resulting mod to Ryujinx's LayeredFS directory
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import threading
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# Bootstrap: locate and import sshd-rando-backend
# ---------------------------------------------------------------------------

_CURRENT_DIR = Path(__file__).resolve().parent

# When running standalone (not from .apworld), find the backend on disk.
_SSHD_RANDO_BACKEND = _CURRENT_DIR / "sshd-rando-backend"
if _SSHD_RANDO_BACKEND.is_dir():
    if str(_SSHD_RANDO_BACKEND) not in sys.path:
        sys.path.insert(0, str(_SSHD_RANDO_BACKEND))
else:
    # Try parent directory (installed alongside the world)
    _ALT = _CURRENT_DIR.parent / "sshd-rando-backend"
    if _ALT.is_dir():
        _SSHD_RANDO_BACKEND = _ALT
        if str(_ALT) not in sys.path:
            sys.path.insert(0, str(_ALT))

# Add the current directory for local imports (Items, Locations, etc.)
if str(_CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(_CURRENT_DIR))

# Mock GUI / nogui modules before any sshd-rando imports
import types as _types
_mock_args = _types.ModuleType("util.arguments")


class _NoGuiArgs:
    nogui = True
    debug = False


_mock_args.args = _NoGuiArgs()
_mock_args.get_program_args = lambda: _NoGuiArgs()
sys.modules["util.arguments"] = _mock_args

# Mock PySide6 + GUI
from unittest.mock import MagicMock as _MagicMock

for _mod_name in (
    "PySide6", "PySide6.QtCore", "PySide6.QtWidgets",
    "gui", "gui.dialogs", "gui.dialogs.dialog_header", "gui.guithreads",
):
    sys.modules[_mod_name] = _MagicMock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_extract_path() -> Path:
    """Return the default SSHD ROM extract path for this platform."""
    try:
        from platform_utils import get_default_sshd_extract_path
        return get_default_sshd_extract_path()
    except ImportError:
        if sys.platform == "win32":
            prog = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
            return Path(prog) / "Archipelago" / "sshd_extract"
        return Path.home() / ".local" / "share" / "Archipelago" / "sshd_extract"


def _find_ryujinx_mod_dir() -> Optional[Path]:
    """Return the Ryujinx LayeredFS mod path for SSHD, or None."""
    try:
        from platform_utils import get_ryujinx_mod_dirs
        for p in get_ryujinx_mod_dirs():
            if p.parent.parent.parent.exists():
                p.mkdir(parents=True, exist_ok=True)
                return p
    except ImportError:
        pass

    # Manual fallback
    game_id = "01002da013484000"
    if sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", ""))
        candidates = [
            appdata / "Ryujinx" / "sdcard" / "atmosphere" / "contents" / game_id,
        ]
    elif sys.platform == "linux":
        candidates = [
            Path.home() / ".config" / "Ryujinx" / "sdcard" / "atmosphere" / "contents" / game_id,
        ]
    else:
        candidates = [
            Path.home() / "Library" / "Application Support" / "Ryujinx" / "sdcard" / "atmosphere" / "contents" / game_id,
        ]

    for p in candidates:
        if p.parent.parent.parent.exists():
            p.mkdir(parents=True, exist_ok=True)
            return p
    return None


# ---------------------------------------------------------------------------
# Core patcher logic
# ---------------------------------------------------------------------------

def read_apsshd(patch_path: Path) -> Tuple[dict, dict, dict]:
    """
    Read manifest, patch_data, and patcher_data from an .apsshd file.

    Returns (manifest, patch_data, patcher_data).
    Raises ValueError if patcher_data is missing.
    """
    with zipfile.ZipFile(patch_path, "r") as zf:
        manifest = json.loads(zf.read("manifest.json"))
        patch_data = json.loads(zf.read("patch_data.json"))

        if "patcher_data.json" not in zf.namelist():
            raise ValueError(
                "This .apsshd file does not contain patcher_data.json.\n"
                "It was likely generated by an older version of the SSHD world.\n"
                "Please ask the host to regenerate with the latest version."
            )
        patcher_data = json.loads(zf.read("patcher_data.json"))

    return manifest, patch_data, patcher_data


def generate_patches(
    patcher_data: dict,
    extract_path: Path,
    output_dir: Path,
) -> Tuple[Optional[Path], Optional[Path]]:
    """
    Generate romfs/exefs mod files from patcher_data + user's ROM extract.

    Args:
        patcher_data: Dict loaded from patcher_data.json inside .apsshd
        extract_path: Path to the extracted SSHD ROM (contains romfs/ and exefs/)
        output_dir: Temporary directory for generation output

    Returns:
        (romfs_path, exefs_path) on success, or (None, None) on failure.
    """
    romfs_check = extract_path / "romfs"
    if not romfs_check.exists():
        raise FileNotFoundError(
            f"ROM extract not found at {extract_path}\n"
            f"Expected {romfs_check} to exist.\n"
            f"Extract your SSHD ROM with hactool and place romfs/ and exefs/ there."
        )

    # ---- Environment setup for sshd-rando ----
    os.environ["SSHD_AP_EXTRACT_PATH"] = str(extract_path.resolve())
    os.environ["SSHD_AP_USERDATA_PATH"] = str(extract_path.resolve().parent)

    # Force reload filepathconstants if already imported so new env vars apply
    import importlib
    if "filepathconstants" in sys.modules:
        importlib.reload(sys.modules["filepathconstants"])
    importlib.invalidate_caches()

    # ---- Lazy-import sshd-rando modules ----
    from SSHDRWrapper import (
        _initialize_sshd_rando,
        create_sshd_rando_config,
        overlay_multiworld_items,
        inject_custom_flags_into_world,
    )
    _initialize_sshd_rando()

    from logic.generate import generate
    from logic.config import write_config_to_file
    from patches.allpatchhandler import AllPatchHandler
    from util.text import load_text_data

    # ---- Reconstruct sshd-rando config ----
    ap_settings = patcher_data["ap_settings"]
    seed = patcher_data.get("sshdr_seed")
    setting_string = patcher_data.get("sshd_setting_string", "")

    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if setting_string and setting_string.strip():
        print(f"[Patcher] Using Setting String for config...")
        from setting_string_decoder import decode_setting_string_to_config
        config = decode_setting_string_to_config(setting_string, output_dir, seed)

        # Apply AP-required overrides
        _AP_OVERRIDES = {
            "progressive_items": "on",
            "skip_demise": "off",
            "spawn_hearts": "on",
        }
        if hasattr(config, "settings") and config.settings:
            sm = config.settings[0]
            if hasattr(sm, "settings"):
                from logic.settings import get_all_settings_info
                for ok, ov in _AP_OVERRIDES.items():
                    if ok in sm.settings:
                        s = sm.settings[ok]
                        if s.info and ov in s.info.options:
                            s.update_current_value(s.info.options.index(ov))
    else:
        print(f"[Patcher] Using individual AP settings for config...")
        config = create_sshd_rando_config(ap_settings, output_dir, seed)

    config.output_dir = output_dir

    # Write config to disk for sshd-rando's generate()
    config_file = output_dir / "ap_config.yaml"
    write_config_to_file(config_file, config, write_preferences=False)

    if seed is not None:
        import yaml
        with open(config_file, "r") as f:
            cfg = yaml.safe_load(f) or {}
        cfg["seed"] = str(seed)
        with open(config_file, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False)

    # Write preferences so sshd-rando finds output_dir
    try:
        import filepathconstants as _fpc
        import yaml as _yaml
        prefs = Path(_fpc.PREFERENCES_PATH)
        prefs.parent.mkdir(parents=True, exist_ok=True)
        pd = {}
        if prefs.is_file():
            with open(prefs, "r", encoding="utf-8") as f:
                pd = _yaml.safe_load(f) or {}
        pd["output_dir"] = output_dir.as_posix()
        with open(prefs, "w", encoding="utf-8") as f:
            _yaml.safe_dump(pd, f, sort_keys=False)
    except Exception as e:
        print(f"[Patcher] Warning: could not write preferences.yaml: {e}")

    # ---- Generate world ----
    print("[Patcher] Generating sshd-rando world...")
    worlds = generate(config_file)
    world = worlds[0]
    if world is None:
        raise RuntimeError("sshd-rando generation returned None world")
    world.config.output_dir = output_dir

    # ---- Overlay multiworld items ----
    item_mapping = patcher_data.get("multiworld_item_mapping", {})
    if item_mapping:
        print(f"[Patcher] Overlaying {len(item_mapping)} multiworld items...")
        results = overlay_multiworld_items(world, item_mapping)
        print(f"[Patcher]   Replaced: {results.get('replaced_items', 0)}, "
              f"Cross-world: {results.get('cross_world_items', 0)}")
    else:
        print("[Patcher] No multiworld item mapping found — using sshd-rando placements")

    # ---- Inject custom flags ----
    raw_flag_mapping = patcher_data.get("custom_flag_mapping", {})
    if raw_flag_mapping:
        # Keys were stringified for JSON; convert back to int
        flag_mapping = {int(k): v for k, v in raw_flag_mapping.items()}
        print(f"[Patcher] Injecting {len(flag_mapping)} custom flags...")

        # inject_custom_flags_into_world normally uses the multiworld object
        # to look up locations.  In standalone mode we don't have a multiworld,
        # so we inject directly using the pre-built mapping.
        location_code_to_flag = {loc_code: fid for fid, loc_code in flag_mapping.items()}

        from Locations import LOCATION_TABLE

        # Build name→code lookup from LOCATION_TABLE
        name_to_code = {name: data.code for name, data in LOCATION_TABLE.items() if data.code is not None}

        injected = 0
        for loc_name, loc_obj in world.location_table.items():
            code = name_to_code.get(loc_name)
            if code is not None and code in location_code_to_flag:
                loc_obj.custom_flag = location_code_to_flag[code]
                injected += 1
        print(f"[Patcher] Injected custom flags into {injected} locations")
    else:
        print("[Patcher] No custom flag mapping found — flags will use sshd-rando defaults")

    # ---- Apply patches (requires ROM) ----
    print("[Patcher] Applying ROM patches (this reads from your ROM extract)...")
    load_text_data()
    handler = AllPatchHandler(world)
    handler.do_all_patches()
    print("[Patcher] Patches applied successfully")

    # ---- Patch Archipelago logos ----
    romfs_out = output_dir / "romfs"
    try:
        from rando.ArcPatcher import patch_archipelago_logo

        assets_dir = _CURRENT_DIR / "assets"
        if not assets_dir.exists():
            # Try sshd-rando-backend assets
            assets_dir = _SSHD_RANDO_BACKEND / "assets"

        import filepathconstants as fpc
        title2d_src = Path(fpc.TITLE2D_SOURCE_PATH) if hasattr(fpc, "TITLE2D_SOURCE_PATH") else None
        endroll_src = Path(fpc.ENDROLL_SOURCE_PATH) if hasattr(fpc, "ENDROLL_SOURCE_PATH") else None

        if assets_dir.exists() and title2d_src and endroll_src:
            patch_archipelago_logo(romfs_out, assets_dir, title2d_src, endroll_src)
            print("[Patcher] Archipelago logos patched")
    except Exception as e:
        print(f"[Patcher] Warning: Could not patch logos: {e}")

    exefs_out = output_dir / "exefs"
    if romfs_out.exists() and exefs_out.exists():
        print(f"[Patcher] Generated {len(list(romfs_out.rglob('*')))} romfs files, "
              f"{len(list(exefs_out.rglob('*')))} exefs files")
        return romfs_out, exefs_out
    else:
        print(f"[Patcher] Warning: romfs={romfs_out.exists()}, exefs={exefs_out.exists()}")
        return None, None


def install_to_ryujinx(romfs_path: Path, exefs_path: Path) -> bool:
    """Install generated romfs/exefs to Ryujinx's LayeredFS mod directory."""
    mod_dir = _find_ryujinx_mod_dir()
    if mod_dir is None:
        print("[Patcher] Could not locate Ryujinx mod directory automatically.")
        print("[Patcher] Copy the romfs/ and exefs/ folders manually to your Ryujinx")
        print("          sdcard/atmosphere/contents/01002da013484000/Archipelago/")
        return False

    install_dir = mod_dir / "Archipelago"
    print(f"[Patcher] Installing to: {install_dir}")

    if install_dir.exists():
        shutil.rmtree(install_dir)
    install_dir.mkdir(parents=True, exist_ok=True)

    shutil.copytree(str(romfs_path), str(install_dir / "romfs"))
    shutil.copytree(str(exefs_path), str(install_dir / "exefs"))

    print("[Patcher] Mod installed successfully!")
    return True


def update_apsshd_with_patches(
    apsshd_path: Path,
    romfs_path: Path,
    exefs_path: Path,
) -> Path:
    """
    Create a new .apsshd that includes the generated romfs/exefs.

    This produces a "full" .apsshd identical to what a host with ROM access
    would have generated, useful for sharing with others or archiving.

    Returns the path to the updated .apsshd file.
    """
    out_path = apsshd_path.with_suffix(".patched.apsshd")

    with zipfile.ZipFile(apsshd_path, "r") as src, \
         zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as dst:

        # Copy existing entries (manifest, patch_data, patcher_data)
        for item in src.namelist():
            if item.startswith("romfs/") or item.startswith("exefs/"):
                continue  # Skip old ROM data if any
            dst.writestr(item, src.read(item))

        # Update manifest
        manifest = json.loads(src.read("manifest.json"))
        manifest["has_rom_patches"] = True
        dst.writestr("manifest.json", json.dumps(manifest, indent=2))

        # Add romfs
        if romfs_path and romfs_path.exists():
            for root, _, files in os.walk(romfs_path):
                for f in files:
                    fp = Path(root) / f
                    arc = f"romfs/{fp.relative_to(romfs_path)}"
                    dst.write(fp, arc)

        # Add exefs
        if exefs_path and exefs_path.exists():
            for root, _, files in os.walk(exefs_path):
                for f in files:
                    fp = Path(root) / f
                    arc = f"exefs/{fp.relative_to(exefs_path)}"
                    dst.write(fp, arc)

    print(f"[Patcher] Full .apsshd written to: {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# GUI application (PyQt6)
# ---------------------------------------------------------------------------

_STYLESHEET = """
QWidget#PatcherWindow {
    background-color: #1e1e2e;
}

QLabel#TitleLabel {
    color: #b0c4de;
    font-size: 20px;
    font-weight: bold;
    padding: 6px 0;
}

QLabel#SubtitleLabel {
    color: #6d8be8;
    font-size: 11px;
    padding-bottom: 4px;
}

QLabel#InfoLabel {
    color: #8899aa;
    font-size: 12px;
    padding: 4px 8px;
    background-color: #252538;
    border-radius: 4px;
}

QLabel.FieldLabel {
    color: #b0c4de;
    font-size: 12px;
    font-weight: bold;
    min-width: 90px;
}

QLineEdit {
    background-color: #2a2a3e;
    color: #d4d4d4;
    border: 1px solid #3a3a52;
    border-radius: 5px;
    padding: 6px 10px;
    font-size: 12px;
    selection-background-color: #4a6fa5;
}
QLineEdit:focus {
    border: 1px solid #6d8be8;
}
QLineEdit::placeholder {
    color: #555566;
}

QPushButton#BrowseBtn {
    background-color: #2f3348;
    color: #b0c4de;
    border: 1px solid #3a3a52;
    border-radius: 5px;
    padding: 6px 16px;
    font-size: 12px;
    font-weight: bold;
    min-width: 70px;
}
QPushButton#BrowseBtn:hover {
    background-color: #3a4060;
    border: 1px solid #6d8be8;
}
QPushButton#BrowseBtn:pressed {
    background-color: #4a5070;
}

QPushButton#PatchBtn {
    background-color: #4a6fa5;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 10px;
    font-size: 14px;
    font-weight: bold;
}
QPushButton#PatchBtn:hover {
    background-color: #5a82be;
}
QPushButton#PatchBtn:pressed {
    background-color: #3d5d8a;
}
QPushButton#PatchBtn:disabled {
    background-color: #2f3348;
    color: #555566;
}

QProgressBar {
    background-color: #252538;
    border: 1px solid #3a3a52;
    border-radius: 4px;
    text-align: center;
    color: #d4d4d4;
    font-size: 11px;
    height: 22px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #4a6fa5, stop:1 #6d8be8);
    border-radius: 3px;
}

QTextEdit#LogOutput {
    background-color: #181825;
    color: #cdd6f4;
    border: 1px solid #3a3a52;
    border-radius: 5px;
    padding: 8px;
    font-family: "Cascadia Code", "Consolas", "Courier New", monospace;
    font-size: 11px;
    selection-background-color: #4a6fa5;
}

QFrame#Separator {
    background-color: #3a3a52;
    max-height: 1px;
}
"""


def _run_gui(initial_patch_file: Optional[str] = None):
    """Launch the patcher GUI."""
    from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
    from PyQt6.QtWidgets import (
        QApplication, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QLineEdit, QPushButton, QTextEdit, QProgressBar,
        QFileDialog, QFrame, QSizePolicy,
    )
    from PyQt6.QtGui import QFont, QTextCursor, QColor, QPalette, QIcon

    class PatchWorker(QThread):
        log = pyqtSignal(str)
        progress = pyqtSignal(int)
        info = pyqtSignal(str, str)  # text, color
        finished_signal = pyqtSignal()

        def __init__(self, patch_path: Path, extract_path: Path):
            super().__init__()
            self._patch_path = patch_path
            self._extract_path = extract_path

        def run(self):
            try:
                self.log.emit("Reading .apsshd file...")
                self.progress.emit(5)
                manifest, patch_data, patcher_data = read_apsshd(self._patch_path)
                self.log.emit(f"  Player: {manifest.get('player')}")
                self.log.emit(f"  Seed:   {manifest.get('seed')}")

                has_existing = manifest.get("has_rom_patches", False)
                with zipfile.ZipFile(self._patch_path, "r") as zf:
                    has_romfs = any(n.startswith("romfs/") for n in zf.namelist())
                    has_exefs = any(n.startswith("exefs/") for n in zf.namelist())

                if has_existing and has_romfs and has_exefs:
                    self.log.emit("\nThis .apsshd already contains ROM patches.")
                    self.log.emit("Installing existing patches...")
                    self.progress.emit(50)

                    mod_dir = _find_ryujinx_mod_dir()
                    if mod_dir is None:
                        self.info.emit("Ryujinx mod directory not found", "#ff7700")
                        self.log.emit("\nCould not locate Ryujinx mod directory.")
                        self.log.emit("Extract romfs/ and exefs/ from the .apsshd manually.")
                        return

                    install_dir = mod_dir / "Archipelago"
                    self.log.emit(f"Installing to: {install_dir}")
                    if install_dir.exists():
                        shutil.rmtree(install_dir)
                    install_dir.mkdir(parents=True, exist_ok=True)

                    with zipfile.ZipFile(self._patch_path, "r") as zf:
                        for name in zf.namelist():
                            if name.startswith("romfs/") or name.startswith("exefs/"):
                                target = install_dir / name
                                target.parent.mkdir(parents=True, exist_ok=True)
                                with zf.open(name) as src, open(target, "wb") as dst:
                                    dst.write(src.read())

                    self.progress.emit(100)
                    self.info.emit("Installed successfully!", "#00ff7f")
                    self.log.emit("\nDone! Launch Skyward Sword HD in Ryujinx.")
                    return

                self.log.emit("\nGenerating ROM patches from your ROM extract...")
                self.progress.emit(10)
                temp_dir = Path(tempfile.mkdtemp(prefix="sshd_patch_"))
                try:
                    import io

                    class LogCapture(io.StringIO):
                        def __init__(self, worker):
                            super().__init__()
                            self._worker = worker
                        def write(self, s):
                            if s.strip():
                                self._worker.log.emit(s.rstrip())
                            return len(s)
                        def flush(self):
                            pass

                    old_stdout = sys.stdout
                    sys.stdout = LogCapture(self)

                    try:
                        self.progress.emit(15)
                        romfs_path, exefs_path = generate_patches(
                            patcher_data, self._extract_path, temp_dir,
                        )
                    finally:
                        sys.stdout = old_stdout

                    if romfs_path is None or exefs_path is None:
                        self.info.emit("Patch generation failed", "#ee0000")
                        self.log.emit("\nERROR: Patch generation failed.")
                        return

                    self.progress.emit(85)
                    self.log.emit("\nInstalling to Ryujinx...")
                    success = install_to_ryujinx(romfs_path, exefs_path)

                    self.progress.emit(100)
                    if success:
                        self.info.emit("Patched and installed successfully!", "#00ff7f")
                        self.log.emit("\nDone! Launch Skyward Sword HD in Ryujinx and connect to the server.")
                    else:
                        self.info.emit("Patches generated — manual install needed", "#ff7700")
                        self.log.emit(f"\nPatches generated at: {temp_dir}")
                        self.log.emit("Copy romfs/ and exefs/ to your Ryujinx mod directory manually.")
                        return  # Don't clean up temp dir if manual install needed

                finally:
                    if temp_dir.exists():
                        shutil.rmtree(temp_dir, ignore_errors=True)

            except FileNotFoundError as e:
                self.info.emit("ROM extract not found", "#ee0000")
                self.log.emit(f"\nERROR: {e}")
            except ValueError as e:
                self.info.emit("Invalid .apsshd file", "#ee0000")
                self.log.emit(f"\nERROR: {e}")
            except Exception as e:
                self.info.emit("Error during patching", "#ee0000")
                self.log.emit(f"\nERROR: {e}")
                import traceback
                self.log.emit(traceback.format_exc())
            finally:
                self.finished_signal.emit()

    class PatcherWindow(QWidget):
        def __init__(self, initial_file=None):
            super().__init__()
            self._worker = None
            self.setObjectName("PatcherWindow")
            self.setWindowTitle("SSHD Archipelago Patcher")
            self.setMinimumSize(720, 560)
            self.resize(720, 560)
            self._build_ui(initial_file)

        def _build_ui(self, initial_file):
            layout = QVBoxLayout(self)
            layout.setContentsMargins(20, 16, 20, 16)
            layout.setSpacing(0)

            # ── Title area ───────────────────────────────────
            title = QLabel("SSHD Archipelago Patcher")
            title.setObjectName("TitleLabel")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(title)

            subtitle = QLabel("Generate and install ROM patches from .apsshd files")
            subtitle.setObjectName("SubtitleLabel")
            subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(subtitle)

            layout.addSpacing(12)

            # ── Patch file row ───────────────────────────────
            row1 = QHBoxLayout()
            row1.setSpacing(8)
            lbl1 = QLabel("Patch file:")
            lbl1.setProperty("class", "FieldLabel")
            row1.addWidget(lbl1)
            self.patch_input = QLineEdit(initial_file or "")
            self.patch_input.setPlaceholderText("Select an .apsshd file...")
            self.patch_input.textChanged.connect(self._on_patch_changed)
            row1.addWidget(self.patch_input, stretch=1)
            browse_btn = QPushButton("Browse")
            browse_btn.setObjectName("BrowseBtn")
            browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            browse_btn.clicked.connect(self._browse_patch)
            row1.addWidget(browse_btn)
            layout.addLayout(row1)

            layout.addSpacing(8)

            # ── Extract path row ─────────────────────────────
            row2 = QHBoxLayout()
            row2.setSpacing(8)
            lbl2 = QLabel("ROM extract:")
            lbl2.setProperty("class", "FieldLabel")
            row2.addWidget(lbl2)
            self.extract_input = QLineEdit(str(_find_extract_path()))
            self.extract_input.setPlaceholderText("Path to sshd_extract folder")
            row2.addWidget(self.extract_input, stretch=1)
            browse_ext = QPushButton("Browse")
            browse_ext.setObjectName("BrowseBtn")
            browse_ext.setCursor(Qt.CursorShape.PointingHandCursor)
            browse_ext.clicked.connect(self._browse_extract)
            row2.addWidget(browse_ext)
            layout.addLayout(row2)

            layout.addSpacing(12)

            # ── Separator ────────────────────────────────────
            sep = QFrame()
            sep.setObjectName("Separator")
            sep.setFrameShape(QFrame.Shape.HLine)
            layout.addWidget(sep)

            layout.addSpacing(8)

            # ── Info label ───────────────────────────────────
            self.info_label = QLabel("Select an .apsshd file and click Patch & Install")
            self.info_label.setObjectName("InfoLabel")
            layout.addWidget(self.info_label)

            layout.addSpacing(8)

            # ── Progress bar ─────────────────────────────────
            self.progress = QProgressBar()
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.progress.setTextVisible(True)
            self.progress.setFormat("%p%")
            layout.addWidget(self.progress)

            layout.addSpacing(8)

            # ── Log output ───────────────────────────────────
            self.log_output = QTextEdit()
            self.log_output.setObjectName("LogOutput")
            self.log_output.setReadOnly(True)
            self.log_output.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding,
            )
            layout.addWidget(self.log_output, stretch=1)

            layout.addSpacing(12)

            # ── Patch button ─────────────────────────────────
            self.patch_btn = QPushButton("Patch && Install")
            self.patch_btn.setObjectName("PatchBtn")
            self.patch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.patch_btn.setMinimumHeight(44)
            self.patch_btn.clicked.connect(self._start_patch)
            layout.addWidget(self.patch_btn)

            # Load info if file was passed
            if initial_file:
                self._load_patch_info()

        # ── Browse dialogs ───────────────────────────────────

        def _browse_patch(self):
            start = str(Path(self.patch_input.text()).parent) if self.patch_input.text().strip() else str(Path.home())
            path, _ = QFileDialog.getOpenFileName(
                self, "Select .apsshd file", start,
                "SSHD Patches (*.apsshd);;All Files (*)",
            )
            if path:
                self.patch_input.setText(path)

        def _browse_extract(self):
            start = self.extract_input.text().strip() or str(Path.home())
            path = QFileDialog.getExistingDirectory(
                self, "Select ROM extract folder", start,
            )
            if path:
                self.extract_input.setText(path)

        def _on_patch_changed(self, text):
            if text.strip():
                self._load_patch_info()

        def _load_patch_info(self):
            path_str = self.patch_input.text().strip()
            if not path_str:
                return
            p = Path(path_str)
            if not p.exists() or p.suffix != ".apsshd":
                self._set_info("Invalid file — select an .apsshd file", "#ee0000")
                return
            try:
                manifest, _, _ = read_apsshd(p)
                player = manifest.get("player", "?")
                seed = manifest.get("seed", "?")
                has_rom = manifest.get("has_rom_patches", False)
                status = "contains ROM patches" if has_rom else "lightweight (needs patching)"
                self._set_info(
                    f"Player: {player}  \u2502  Seed: {seed}  \u2502  {status}",
                    "#b0c4de",
                )
            except Exception as e:
                self._set_info(f"Error reading file: {e}", "#ee0000")

        # ── Helpers ──────────────────────────────────────────

        def _set_info(self, text: str, color: str = "#8899aa"):
            self.info_label.setText(text)
            self.info_label.setStyleSheet(
                f"color: {color}; font-size: 12px; padding: 4px 8px; "
                f"background-color: #252538; border-radius: 4px;"
            )

        def _append_log(self, msg: str):
            self.log_output.append(msg)
            self.log_output.moveCursor(QTextCursor.MoveOperation.End)

        # ── Patch execution ──────────────────────────────────

        def _start_patch(self):
            if self._worker is not None and self._worker.isRunning():
                return
            patch_path = self.patch_input.text().strip()
            extract_path = self.extract_input.text().strip()
            if not patch_path:
                self._set_info("Please select an .apsshd file first", "#ee0000")
                return
            if not Path(patch_path).exists():
                self._set_info("Patch file not found", "#ee0000")
                return
            if not extract_path or not Path(extract_path).exists():
                self._set_info("ROM extract path not found", "#ee0000")
                return

            self.patch_btn.setEnabled(False)
            self.log_output.clear()
            self.progress.setValue(0)
            self._set_info("Patching...", "#6d8be8")

            self._worker = PatchWorker(Path(patch_path), Path(extract_path))
            self._worker.log.connect(self._append_log)
            self._worker.progress.connect(self.progress.setValue)
            self._worker.info.connect(self._set_info)
            self._worker.finished_signal.connect(self._on_patch_done)
            self._worker.start()

        def _on_patch_done(self):
            self.patch_btn.setEnabled(True)

    app = QApplication(sys.argv)
    app.setStyleSheet(_STYLESHEET)

    # Apply dark palette as base (for native dialogs, menus, etc.)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#1e1e2e"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#cdd6f4"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#181825"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#252538"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#cdd6f4"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#2f3348"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#cdd6f4"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#4a6fa5"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)

    window = PatcherWindow(initial_file=initial_patch_file)
    window.show()
    app.exec()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="SSHD Archipelago Patcher — generate ROM patches from a lightweight .apsshd file"
    )
    parser.add_argument(
        "patch_file",
        nargs="?",
        default=None,
        help="Path to the .apsshd file (opens GUI file picker if omitted)",
    )
    parser.add_argument(
        "--extract-path",
        help="Path to extracted SSHD ROM (folder containing romfs/ and exefs/). "
             "Defaults to the standard Archipelago sshd_extract location.",
        default=None,
    )
    parser.add_argument(
        "--output",
        help="Output directory for generated mod files. If omitted, uses a temp directory.",
        default=None,
    )
    parser.add_argument(
        "--no-install",
        action="store_true",
        help="Generate patches but do not install to Ryujinx automatically.",
    )
    parser.add_argument(
        "--save-full-apsshd",
        action="store_true",
        help="Create a new .apsshd with ROM patches included (for sharing with others).",
    )
    parser.add_argument(
        "--nogui",
        action="store_true",
        help="Run in CLI mode without the GUI.",
    )
    args = parser.parse_args()

    # ── GUI mode ──────────────────────────────────────────────────
    if not args.nogui:
        _run_gui(initial_patch_file=args.patch_file)
        return

    # ── CLI mode (--nogui) ────────────────────────────────────────
    if not args.patch_file:
        parser.error("patch_file is required in --nogui mode")

    patch_path = Path(args.patch_file)
    if not patch_path.exists():
        print(f"ERROR: Patch file not found: {patch_path}")
        sys.exit(1)

    extract_path = Path(args.extract_path) if args.extract_path else _find_extract_path()
    extract_path = extract_path.resolve()

    print("=" * 65)
    print("  SSHD Archipelago Patcher")
    print("=" * 65)
    print(f"  Patch file:   {patch_path}")
    print(f"  ROM extract:  {extract_path}")

    # ---- Read .apsshd ----
    manifest, patch_data, patcher_data = read_apsshd(patch_path)
    print(f"  Player:       {manifest.get('player')}")
    print(f"  Seed:         {manifest.get('seed')}")
    has_existing = manifest.get("has_rom_patches", False)

    # Check if ROM patches are already included
    with zipfile.ZipFile(patch_path, "r") as zf:
        has_romfs = any(n.startswith("romfs/") for n in zf.namelist())
        has_exefs = any(n.startswith("exefs/") for n in zf.namelist())

    if has_existing and has_romfs and has_exefs:
        print("\n  This .apsshd already contains ROM patches.")
        resp = input("  Re-generate from your ROM anyway? [y/N]: ").strip().lower()
        if resp != "y":
            print("  Using existing patches from .apsshd instead.")
            # Just install the existing patches
            if not args.no_install:
                from SSHDClient import install_patch
                success, _ = install_patch(str(patch_path))
                if success:
                    print("\nDone! Launch Skyward Sword HD in Ryujinx.")
                else:
                    print("\nInstallation failed. Check the output above.")
            sys.exit(0)

    print("=" * 65)

    # ---- Generate patches ----
    temp_dir = Path(args.output) if args.output else Path(tempfile.mkdtemp(prefix="sshd_patch_"))
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        romfs_path, exefs_path = generate_patches(patcher_data, extract_path, temp_dir)

        if romfs_path is None or exefs_path is None:
            print("\nERROR: Patch generation failed.")
            sys.exit(1)

        # ---- Install ----
        if not args.no_install:
            print()
            install_to_ryujinx(romfs_path, exefs_path)

        # ---- Optionally save full .apsshd ----
        if args.save_full_apsshd:
            update_apsshd_with_patches(patch_path, romfs_path, exefs_path)

        print("\nDone!")
        if not args.no_install:
            print("Launch Skyward Sword HD in Ryujinx and connect to the Archipelago server.")

    finally:
        # Clean up temp directory only if we created it
        if not args.output and temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
