"""
Build script to create the SSHD.apworld file.

An .apworld file is simply a ZIP file containing the world's Python code
and assets. Archipelago will load it from the custom_worlds folder.
"""

import os
import zipfile
import shutil
import sys
import site
import importlib.util
import subprocess
import tempfile
import re
from pathlib import Path


# Third-party Python packages to bundle into the apworld.
# These will be extracted at runtime so C-extensions (.pyd/.so) work correctly.
# Each entry is a top-level package/module name.
BUNDLED_PACKAGES = [
    "lz4",       # Compression (C extension) – used by asmpatchhandler
    "nlzss11",   # Nintendo LZ compression (C extension) – used by sslib/u8file
]

# Python versions to download wheels for (covers all Archipelago releases).
# Wheels for each version contain ABI-tagged .pyd files that can coexist.
BUNDLE_PYTHON_VERSIONS = ["311", "312", "313"]

# Platform to download wheels for.
BUNDLE_PLATFORM = "win_amd64"


def _download_and_stage_wheels(packages: list[str], staging_dir: Path):
    """Download wheels for *packages* across multiple Python versions and
    extract their contents into *staging_dir*.

    Files from different Python versions have distinct ABI-tagged names
    (e.g. ``_block.cp312-win_amd64.pyd`` vs ``_block.cp313-win_amd64.pyd``)
    so they can safely coexist in the same directory.  At runtime Python's
    import machinery picks the one that matches the running interpreter.
    """
    staging_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="sshd_wheels_") as wheel_tmpdir:
        for pyver in BUNDLE_PYTHON_VERSIONS:
            ver_dir = Path(wheel_tmpdir) / pyver
            ver_dir.mkdir()
            for pkg in packages:
                print(f"  Downloading {pkg} for cp{pyver} {BUNDLE_PLATFORM} ...")
                try:
                    subprocess.check_call(
                        [
                            sys.executable, "-m", "pip", "download",
                            pkg,
                            "--python-version", pyver,
                            "--platform", BUNDLE_PLATFORM,
                            "--only-binary", ":all:",
                            "--no-deps",
                            "-d", str(ver_dir),
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                    )
                except subprocess.CalledProcessError:
                    print(f"    WARNING: no wheel for {pkg} cp{pyver} – skipping")
                    continue

        # Now extract all downloaded wheels into the staging directory.
        # Skip .dist-info metadata – we only need the actual package files.
        for whl_file in Path(wheel_tmpdir).rglob("*.whl"):
            print(f"  Extracting {whl_file.name} ...")
            with zipfile.ZipFile(whl_file) as whl:
                for entry in whl.filelist:
                    # Skip dist-info metadata
                    if ".dist-info/" in entry.filename or entry.filename.endswith(".dist-info"):
                        continue
                    target = staging_dir / entry.filename
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not entry.is_dir():
                        with whl.open(entry.filename) as src, open(target, "wb") as dst:
                            dst.write(src.read())


def build_apworld():
    """Build the SSHD.apworld file from the source code."""
    
    # Get the directory containing this script
    source_dir = Path(__file__).parent
    
    # Output to current directory by default, or use parent if source_dir looks like a project folder
    if (source_dir / "__init__.py").exists():
        # We're in the project directory itself
        output_file = source_dir / "sshd.apworld"
    else:
        # Default to current working directory for CI/CD compatibility
        output_file = Path.cwd() / "sshd.apworld"
    
    archipelago_source = source_dir / "AP_FILES"
    
    # Archipelago core files to bundle
    archipelago_files = [
        "BaseClasses.py",
        "CommonClient.py",
        "MultiServer.py",
        "NetUtils.py",
        "Utils.py",
        "Options.py",  # Core Options with base classes (Choice, Toggle, etc.)
        "kvui.py",
        "settings.py",
        "ModuleUpdate.py",
        "Fill.py",
        "entrance_rando.py",
    ]
    
    # Archipelago worlds files to bundle
    archipelago_worlds_files = [
        "worlds/__init__.py",
        "worlds/AutoWorld.py",
        "worlds/AutoSNIClient.py",
        "worlds/Files.py",
        "worlds/LauncherComponents.py",
    ]
    
    # Archipelago data folder files needed for GUI
    archipelago_data_files = [
        "data/client.kv",
        "data/icon.png",
    ]
    
    # Files/folders to include in the .apworld
    include_patterns = [
        "__init__.py",
        "Items.py",
        "Locations.py",
        "LocationFlags.py",
        "Regions.py",
        "SSHD_Options.py",
        "Rules.py",
        "Hints.py",
        "SSHDClient.py",
        "SSHDRWrapper.py",
        "TrackerBridge.py",
        "setting_string_decoder.py",
        "README.md",
        "archipelago.json",
        # "ArchipelagoSSHDClient.exe",
        "worlds_stub.py",
        "ItemSystemIntegration.py",
        "logic_converter.py",
        # Folders
        "docs/",
        "assets/",
        "rando/",
        "sshd-rando-backend/",  # BUNDLED: Extracted to temp at runtime by __init__.py
    ]
    
    # Files/folders to exclude
    exclude_patterns = [
        "__pycache__",
        ".pyc",
        ".git",
        "build_apworld.py",
    ]
    
    def should_include(filepath: Path) -> bool:
        """Check if a file should be included in the .apworld."""
        rel_path = filepath.relative_to(source_dir)
        rel_str = str(rel_path).replace("\\", "/")
        filename = filepath.name
        
        # Check if explicitly excluded (exact filename match to avoid false positives)
        for pattern in exclude_patterns:
            if pattern in ["__pycache__", ".pyc", ".git"]:
                # Substring match for these
                if pattern in rel_str:
                    return False
            else:
                # Exact filename match for others
                if filename == pattern:
                    return False
        
        # Check if matches include patterns
        for pattern in include_patterns:
            if pattern.endswith("/"):
                # Directory pattern
                if rel_str.startswith(pattern):
                    return True
            else:
                # File pattern
                if rel_str == pattern or rel_str.startswith(pattern + "/"):
                    return True
        
        return False
    
    print(f"Building sshd.apworld...")
    print(f"Source: {source_dir}")
    print(f"Output: {output_file}")
    print()
    
    with zipfile.ZipFile(output_file, 'w', zipfile.ZIP_DEFLATED) as apworld:
        file_count = 0
        
        # First, add bundled Archipelago core files
        print("Bundling Archipelago core files...")
        for ap_file in archipelago_files:
            # Special handling for kvui.py and CommonClient.py - use our modified versions
            if ap_file in ["kvui.py", "CommonClient.py"]:
                source_path = source_dir / ap_file
                print(f"  Using custom {ap_file} from SSHD_APWorld (with websockets 16.0 fixes)")
            else:
                source_path = archipelago_source / ap_file
            
            if source_path.exists():
                arcname = Path("sshd") / ap_file
                apworld.write(source_path, arcname)
                print(f"  Added: {arcname}")
                file_count += 1
            else:
                print(f"  WARNING: {ap_file} not found in {source_path.parent}")
        
        # Add Archipelago data files needed for GUI
        print("Bundling Archipelago data files...")
        for data_file in archipelago_data_files:
            source_path = archipelago_source / data_file
            if source_path.exists():
                arcname = Path("sshd") / data_file
                apworld.write(source_path, arcname)
                print(f"  Added: {arcname}")
                file_count += 1
            else:
                print(f"  WARNING: {data_file} not found in {archipelago_source}")
        
        # Add Archipelago worlds files (but use stub for __init__.py)
        print("Bundling Archipelago worlds files...")
        for worlds_file in archipelago_worlds_files:
            # Skip worlds/__init__.py - we'll use the stub instead
            if worlds_file == "worlds/__init__.py":
                continue
                
            source_path = archipelago_source / worlds_file
            if source_path.exists():
                arcname = Path("sshd") / worlds_file
                apworld.write(source_path, arcname)
                print(f"  Added: {arcname}")
                file_count += 1
            else:
                print(f"  WARNING: {worlds_file} not found in {archipelago_source}")
        
        # Use custom worlds stub instead of real __init__.py (avoids filesystem scanning)
        print("Bundling worlds stub...")
        worlds_stub = source_dir / "worlds_stub.py"
        if worlds_stub.exists():
            arcname = Path("sshd") / "worlds" / "__init__.py"
            apworld.write(worlds_stub, arcname)
            print(f"  Added: {arcname} (custom stub)")
            file_count += 1
        else:
            print(f"  WARNING: worlds_stub.py not found")
        
        # Walk through all files in the source directory
        print("Bundling SSHD world files...")
        for root, dirs, files in os.walk(source_dir):
            root_path = Path(root)
            
            # Skip excluded directories
            dirs[:] = [d for d in dirs if d not in exclude_patterns]
            
            for filename in files:
                filepath = root_path / filename
                
                if should_include(filepath):
                    # Get the archive name (relative path from source_dir)
                    # IMPORTANT: All files must be inside a "sshd" subdirectory in the ZIP
                    arcname = Path("sshd") / filepath.relative_to(source_dir)
                    
                    # Add to the ZIP with the correct path structure
                    apworld.write(filepath, arcname)
                    print(f"  Added: {arcname}")
                    file_count += 1
        
        # ------------------------------------------------------------------
        # Bundle third-party Python packages (including C extensions)
        # Downloads wheels for multiple Python versions so the .pyd files
        # work regardless of which CPython the host Archipelago ships.
        # ------------------------------------------------------------------
        print("Bundling third-party Python dependencies...")
        with tempfile.TemporaryDirectory(prefix="sshd_staging_") as staging_tmp:
            staging_dir = Path(staging_tmp)
            _download_and_stage_wheels(BUNDLED_PACKAGES, staging_dir)

            # Walk the staging directory and add everything to the zip
            for root, _dirs, files in os.walk(staging_dir):
                _dirs[:] = [d for d in _dirs if d != "__pycache__"]
                for fname in files:
                    if fname.endswith(".pyc"):
                        continue
                    full = Path(root) / fname
                    rel = full.relative_to(staging_dir)
                    arcname = Path("sshd") / "_bundled_deps" / str(rel).replace("\\", "/")
                    apworld.write(full, arcname)
                    print(f"  Added: {arcname}")
                    file_count += 1
    
    print()
    print(f"Successfully built SSHD.apworld with {file_count} files!")
    print(f"   Location: {output_file}")
    print()
    
    # Auto-deploy to custom_worlds folder
    try:
        from platform_utils import get_custom_worlds_dir
        custom_worlds_dir = get_custom_worlds_dir()
    except ImportError:
        import sys
        if sys.platform == "win32":
            custom_worlds_dir = Path("C:/ProgramData/Archipelago/custom_worlds")
        elif sys.platform == "linux":
            custom_worlds_dir = Path.home() / ".local" / "share" / "Archipelago" / "custom_worlds"
        else:
            custom_worlds_dir = Path.home() / "Library" / "Application Support" / "Archipelago" / "custom_worlds"
    
    custom_worlds_dir.mkdir(parents=True, exist_ok=True)
    
    if custom_worlds_dir.exists():
        destination = custom_worlds_dir / "sshd.apworld"
        try:
            shutil.copy2(output_file, destination)
            print(f"[OK] Auto-deployed to: {destination}")
            
            # Clean up extracted sshd directory to force reload
            extracted_dir = custom_worlds_dir / "sshd"
            if extracted_dir.exists():
                shutil.rmtree(extracted_dir)
                print(f"[OK] Cleaned extracted cache: {extracted_dir}")
        except Exception as e:
            print(f"[!] Warning: Could not auto-deploy - {e}")
    else:
        print(f"[!] Custom worlds directory not found: {custom_worlds_dir}")
        print("Manual deployment needed - copy sshd.apworld to your Archipelago custom_worlds folder")
    
    print()
    print("Next steps:")
    print("1. Restart Archipelago (if running)")
    print("2. Generate a seed with your SSHD YAML file")
    
    return output_file


if __name__ == "__main__":
    build_apworld()
