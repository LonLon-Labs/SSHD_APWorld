"""
Build the Rust Archipelago client (sshd-ap-client) for the CURRENT platform
and stage the resulting binary where build_apworld.py can find and bundle
it.

This only builds for whatever platform you run it FROM (native build, no
cross-compilation) — unlike the Python side, which bundles wheels for every
supported platform by downloading them. Producing binaries for every
platform (Windows/Linux/macOS) from one machine would need a proper
cross-compilation setup (the `cross` tool, or per-platform CI runners) and
isn't done here. Run this once per platform you want to bundle, ideally
from CI with a build matrix.

Usage:
    python build_ap_client.py

This is best-effort: if `cargo` isn't installed, or the build fails, it
prints a warning and exits non-zero WITHOUT raising — build_apworld.py
treats that as "skip bundling the Rust client", so a missing/broken Rust
toolchain never blocks building the .apworld itself.

If you hit a build failure here, first try `rustup update` — the Rust
client depends on `archipelago_rs`, which needs a reasonably recent
toolchain.
"""

import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

SOURCE_DIR = Path(__file__).parent
CLIENT_WORKSPACE_DIR = SOURCE_DIR / "sshd-ap-client"
DIST_DIR = CLIENT_WORKSPACE_DIR / "dist"


def platform_tag() -> str:
    """Matches the platform tag convention build_apworld.py already uses
    for bundled Python wheels (BUNDLE_PLATFORMS), so both bundling schemes
    stay consistent and __init__.py can look things up the same way for
    either."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "windows":
        return "win_amd64"
    if system == "linux":
        return "manylinux2014_x86_64"
    if system == "darwin":
        return "macosx_11_0_arm64" if machine in ("arm64", "aarch64") else "macosx_10_9_x86_64"
    return f"{system}_{machine}"


def binary_name() -> str:
    return "ap-client.exe" if platform.system().lower() == "windows" else "ap-client"


def build_ap_client() -> Optional[Path]:
    """Builds the Rust client (release profile) for the current platform
    and copies it to dist/<platform_tag>/<binary_name>. Returns the staged
    path, or None if the build was skipped or failed (never raises)."""

    if not CLIENT_WORKSPACE_DIR.exists():
        print("[ap-client] sshd-ap-client/ not found — skipping Rust client build.")
        return None

    if shutil.which("cargo") is None:
        print("[ap-client] cargo not found on PATH — skipping Rust client build.")
        print("[ap-client] Install Rust (https://rustup.rs) to bundle the Rust client.")
        return None

    tag = platform_tag()
    print(f"[ap-client] Building sshd-ap-client (release) for {tag}...")
    try:
        subprocess.check_call(
            ["cargo", "build", "--release", "-p", "ap-client"],
            cwd=str(CLIENT_WORKSPACE_DIR),
        )
    except subprocess.CalledProcessError as e:
        print(f"[ap-client] WARNING: cargo build failed (exit {e.returncode}).")
        print("[ap-client] Skipping Rust client bundling — the .apworld will still build,")
        print("[ap-client] using the Python client only. Try 'rustup update' and retry.")
        return None

    built_binary = CLIENT_WORKSPACE_DIR / "target" / "release" / binary_name()
    if not built_binary.exists():
        print(f"[ap-client] WARNING: expected binary not found at {built_binary}")
        return None

    staged_dir = DIST_DIR / tag
    staged_dir.mkdir(parents=True, exist_ok=True)
    staged_binary = staged_dir / binary_name()
    shutil.copy2(built_binary, staged_binary)

    # The exec bit matters when this gets zipped and later extracted on
    # Linux/macOS — copy2 preserves source permissions, but cargo's output
    # is already executable on those platforms, so this is mostly a
    # explicit-is-better-than-implicit safety net.
    if platform.system().lower() != "windows":
        staged_binary.chmod(0o755)

    print(f"[ap-client] Built and staged: {staged_binary}")
    return staged_binary


if __name__ == "__main__":
    result = build_ap_client()
    sys.exit(0 if result is not None else 1)
