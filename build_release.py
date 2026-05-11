"""
Build the SSHD Archipelago world file (.apworld).

This script creates the sshd.apworld file which can be placed in the
Archipelago custom_worlds folder to enable SSHD support.

The SSHD client will launch from the Archipelago launcher once installed.

Usage (developer only):
    pip install -r requirements.txt
    python build_apworld.py
    
    # Or build the release:
    python build_release.py
"""

import shutil
import sys
from pathlib import Path


def main():
    source_dir = Path(__file__).parent
    release_dir = source_dir / "release"

    print("=" * 60)
    print("  SSHD Archipelago - APWorld Build")
    print("=" * 60)
    print()

    # ── Step 1: Build the .apworld ────────────────────────────
    print("Building sshd.apworld...")
    print()

    from build_apworld import build_apworld
    apworld_path = build_apworld()

    print()

    # ── Step 2: Create release package ────────────────────────
    print("=" * 60)
    print("  Creating release package...")
    print("=" * 60)
    print()

    # Clean and create release directory
    if release_dir.exists():
        shutil.rmtree(release_dir)
    release_dir.mkdir(parents=True)

    # Copy the apworld
    release_apworld = release_dir / "sshd.apworld"
    shutil.copy2(apworld_path, release_apworld)
    print(f"  Added: sshd.apworld")

    # Copy supporting files for users
    extra_files = {
        "README.md": source_dir / "README.md",
        "Skyward Sword HD.yaml": source_dir / "Skyward Sword HD.yaml",
        "launch_sshd_wrapper.py": source_dir / "launch_sshd_wrapper.py",
    }
    
    for filename, source_path in extra_files.items():
        if source_path.exists():
            shutil.copy2(source_path, release_dir / filename)
            print(f"  Added: {filename}")

    print()
    print("=" * 60)
    print("  Release created successfully!")
    print("=" * 60)
    print()
    print(f"  Location: {release_dir}")
    print()
    print("To use:")
    print(f"  1. Place sshd.apworld in your Archipelago custom_worlds folder")
    print(f"  2. Launch Archipelago")
    print(f"  3. Click 'Skyward Sword HD Client' to connect")
    print()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
