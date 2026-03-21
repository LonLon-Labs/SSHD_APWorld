"""
Build a complete release package for SSHD Archipelago.

This script:
1. Builds ArchipelagoSSHDClient (standalone folder, no Python needed)
2. Builds sshd.apworld
3. Creates a release zip with everything users need

Usage (developer only):
    pip install -r requirements.txt pyinstaller
    python build_release.py
"""

import os
import shutil
import sys
import zipfile
from pathlib import Path


def main():
    source_dir = Path(__file__).parent
    release_dir = source_dir / "release"
    dist_dir = source_dir / "dist"
    client_folder_name = "ArchipelagoSSHDClient"
    patcher_folder_name = "ArchipelagoSSHDPatcher"

    print("=" * 60)
    print("  SSHD Archipelago - Full Release Build")
    print("=" * 60)
    print()

    # ── Step 1: Build the standalone client exe ───────────────────
    print("━" * 60)
    print("Step 1/4: Building standalone client executable...")
    print("━" * 60)
    print()

    from build_client_exe import build_client_exe
    exe_path = build_client_exe()

    # The exe lives inside dist/ArchipelagoSSHDClient/
    client_dist_folder = dist_dir / client_folder_name
    if not client_dist_folder.exists():
        print(f"[FAIL] Client folder not found at {client_dist_folder}")
        sys.exit(1)

    print()

    # ── Step 2: Build the standalone patcher exe ──────────────────
    print("━" * 60)
    print("Step 2/4: Building standalone patcher executable...")
    print("━" * 60)
    print()

    from build_patcher_exe import build_patcher_exe
    patcher_exe_path = build_patcher_exe()

    patcher_exe_file = dist_dir / f"{patcher_folder_name}.exe"
    if not patcher_exe_file.exists():
        print(f"[FAIL] Patcher exe not found at {patcher_exe_file}")
        sys.exit(1)

    print()

    # ── Step 3: Build the .apworld ────────────────────────────────
    print("━" * 60)
    print("Step 3/4: Building sshd.apworld...")
    print("━" * 60)
    print()

    from build_apworld import build_apworld
    apworld_path = build_apworld()

    print()

    # ── Step 4: Create release package ────────────────────────────
    print("━" * 60)
    print("Step 4/4: Creating release package...")
    print("━" * 60)
    print()

    # Clean and create release directory
    if release_dir.exists():
        shutil.rmtree(release_dir)
    release_dir.mkdir(parents=True)

    # Copy standalone client folder
    release_client_dir = release_dir / client_folder_name
    shutil.copytree(client_dist_folder, release_client_dir)
    print(f"  Added: {client_folder_name}/ (standalone client)")

    # Copy standalone patcher exe (single file)
    shutil.copy2(patcher_exe_file, release_dir / f"{patcher_folder_name}.exe")
    print(f"  Added: {patcher_folder_name}.exe (standalone patcher)")

    # Copy individual release files alongside the client folder
    extra_files = {
        "sshd.apworld": source_dir / "sshd.apworld",
        "launch_sshd_wrapper.py": source_dir / "launch_sshd_wrapper.py",
        "Skyward Sword HD.yaml": source_dir / "SkywardSwordHD.yaml",
        "README.md": source_dir / "README.md",
    }
    if (source_dir / "launch_sshd.bat").exists():
        extra_files["launch_sshd.bat"] = source_dir / "launch_sshd.bat"

    for name, path in extra_files.items():
        if path.exists():
            shutil.copy2(path, release_dir / name)
            print(f"  Added: {name}")
        else:
            print(f"  [SKIP] {name} not found")

    # Create release zip
    release_zip = source_dir / "SSHD_Archipelago_Release.zip"
    with zipfile.ZipFile(release_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(release_dir):
            for f in files:
                full = Path(root) / f
                arcname = full.relative_to(release_dir)
                zf.write(full, arcname)

    zip_size = release_zip.stat().st_size / (1024 * 1024)

    print()
    print("=" * 60)
    print("  Release Build Complete!")
    print("=" * 60)
    print()
    print(f"  Release folder: {release_dir}")
    print(f"  Release zip:    {release_zip} ({zip_size:.1f} MB)")
    print()
    print("  Users only need to:")
    print(f"    1. Place sshd.apworld in Archipelago/custom_worlds/")
    print(f"    2. Run {client_folder_name}/{client_folder_name}.exe")
    print("    (No Python or pip install required!)")


if __name__ == "__main__":
    main()
    

if __name__ == "__main__":
    main()
