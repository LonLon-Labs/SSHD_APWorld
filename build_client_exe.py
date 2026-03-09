"""
Build standalone ArchipelagoSSHDClient.exe using PyInstaller.

This bundles Python, all dependencies (kivy, kivymd, pymem, websockets, etc.)
and the client code into a single-folder distribution so users don't need
to install Python or any packages.

Usage:
    pip install pyinstaller   (one-time, developer only)
    python build_client_exe.py
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

# On headless CI runners (no GPU), Kivy's default OpenGL backend fails because
# only OpenGL 1.1 (GDI Generic) is available.  Force the ANGLE backend which
# ships with kivy_deps.angle and provides a software OpenGL ES context that
# satisfies Kivy's minimum requirement (OpenGL 2.0).
os.environ.setdefault("KIVY_GL_BACKEND", "angle_sdl2")


def build_client_exe():
    """Build the standalone SSHD Archipelago Client executable."""

    source_dir = Path(__file__).parent
    dist_dir = source_dir / "dist"
    exe_name = "ArchipelagoSSHDClient"
    spec_path = source_dir / f"{exe_name}.spec"

    print("=" * 60)
    print("  Building ArchipelagoSSHDClient.exe")
    print("=" * 60)
    print()

    # ── Verify dependencies ───────────────────────────────────────
    try:
        import PyInstaller
        print(f"[OK] PyInstaller {PyInstaller.__version__}")
    except ImportError:
        print("[!] PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        import PyInstaller
        print(f"[OK] PyInstaller {PyInstaller.__version__} installed")

    required = {
        "psutil": "psutil",
        "pymem": "pymem",
        "websockets": "websockets",
        "yaml": "pyyaml",
        "kivy": "kivy",
        "kivymd": "kivymd",
        "platformdirs": "platformdirs",
    }
    for mod, pip_name in required.items():
        try:
            __import__(mod)
            print(f"[OK] {mod}")
        except ImportError:
            print(f"[!] Missing: {mod}  (pip install {pip_name})")
            sys.exit(1)

    print()

    # ── Resolve paths for the .spec file ──────────────────────────
    ap_files = source_dir / "AP_FILES"

    # Collect (src, dest_folder) tuples for datas
    datas_lines = []

    # Archipelago core modules the client needs at runtime
    bundled_modules = [
        "BaseClasses.py", "CommonClient.py", "NetUtils.py", "Utils.py",
        "Options.py", "kvui.py", "settings.py", "ModuleUpdate.py", "Fill.py",
        "entrance_rando.py", "MultiServer.py",
    ]
    for mod in bundled_modules:
        if mod in ("kvui.py", "CommonClient.py") and (source_dir / mod).exists():
            src = source_dir / mod
        elif (ap_files / mod).exists():
            src = ap_files / mod
        else:
            continue
        datas_lines.append(f"    (r'{src}', '.'),")

    # Worlds stubs
    worlds_dir = ap_files / "worlds"
    if worlds_dir.exists():
        for f in worlds_dir.glob("*.py"):
            if f.name == "__init__.py":
                continue
            datas_lines.append(f"    (r'{f}', 'worlds'),")
    worlds_stub = source_dir / "worlds_stub.py"
    if worlds_stub.exists():
        datas_lines.append(f"    (r'{worlds_stub}', 'worlds'),")

    # Create a worlds/__init__.py from the stub so that `from worlds import ...` works.
    # PyInstaller datas keep filenames, so we create a temp __init__.py.
    worlds_init_dir = source_dir / "build" / "_worlds_pkg"
    worlds_init_dir.mkdir(parents=True, exist_ok=True)
    worlds_init_file = worlds_init_dir / "__init__.py"
    if worlds_stub.exists():
        import shutil as _shutil
        _shutil.copy2(worlds_stub, worlds_init_file)
    else:
        worlds_init_file.write_text("# stub\nnetwork_data_package = {}\n", encoding="utf-8")
    datas_lines.append(f"    (r'{worlds_init_file}', 'worlds'),")

    # AP data files (client.kv, icon.png)
    ap_data_dir = ap_files / "data"
    if ap_data_dir.exists():
        for f in ap_data_dir.iterdir():
            if f.is_file():
                datas_lines.append(f"    (r'{f}', 'data'),")

    # SSHD world modules the client imports
    sshd_files = [
        "LocationFlags.py", "Locations.py", "Items.py", "Hints.py",
        "TrackerBridge.py", "ItemSystemIntegration.py", "SSHD_Options.py",
        "platform_utils.py", "archipelago.json",
    ]
    for f in sshd_files:
        p = source_dir / f
        if p.exists():
            datas_lines.append(f"    (r'{p}', '.'),")

    datas_block = "\n".join(datas_lines)

    # ── kivy_deps binary Trees (Windows) ──────────────────────────
    kivy_deps_lines = []
    if sys.platform == "win32":
        for dep_name in ("sdl2", "glew", "angle"):
            try:
                dep_mod = __import__(f"kivy_deps.{dep_name}", fromlist=["dep_bins"])
                for bin_dir in dep_mod.dep_bins:
                    if os.path.isdir(bin_dir):
                        kivy_deps_lines.append(
                            f"    Tree(r'{bin_dir}', prefix='.'),"
                        )
                        print(f"[OK] kivy_deps.{dep_name} DLLs: {bin_dir}")
            except (ImportError, AttributeError):
                print(f"[WARN] kivy_deps.{dep_name} not found (optional)")

    kivy_deps_block = "\n".join(kivy_deps_lines)

    # ── Resolve kivy and kivymd data directories ──────────────────
    import kivy
    kivy_pkg = Path(kivy.__file__).parent
    import kivymd
    kivymd_pkg = Path(kivymd.__file__).parent

    print(f"[OK] kivy data:   {kivy_pkg / 'data'}")
    print(f"[OK] kivymd fonts: {kivymd_pkg / 'fonts'}")
    print()

    # ── Runtime hooks ─────────────────────────────────────────────
    runtime_hook = source_dir / "pyi_rth_kivy_fixpath.py"
    if not runtime_hook.exists():
        raise FileNotFoundError(f"Missing runtime hook: {runtime_hook}")
    print(f"[OK] Runtime hook: {runtime_hook}")

    # ── Generate .spec file ───────────────────────────────────────
    spec_content = f"""\
# -*- mode: python ; coding: utf-8 -*-
# Auto-generated by build_client_exe.py — do not edit manually.

from PyInstaller.utils.hooks import collect_data_files
import sys, os

block_cipher = None

# Collect all kivy + kivymd data files (fonts, images, .kv, etc.)
kivy_datas = collect_data_files('kivy')
kivymd_datas = collect_data_files('kivymd')

# Also add kivy data at top-level 'data/' since frozen kivy resolves paths
# relative to _MEIPASS, not _MEIPASS/kivy/ (shader.pyx hardcodes this).
import kivy as _kivy
_kivy_data_dir = os.path.join(os.path.dirname(_kivy.__file__), 'data')
kivy_toplevel_data = [(os.path.join(dp, f), os.path.join('data', os.path.relpath(dp, _kivy_data_dir)))
                       for dp, dn, fns in os.walk(_kivy_data_dir) for f in fns]

datas = kivy_datas + kivymd_datas + kivy_toplevel_data + [
{datas_block}
]

# Hidden imports — modules loaded dynamically at runtime
hiddenimports = [
    # kivy core
    'kivy', 'kivy.app', 'kivy.base', 'kivy.clock', 'kivy.config',
    'kivy.factory', 'kivy.lang', 'kivy.lang.builder', 'kivy.lang.parser',
    'kivy.properties', 'kivy.metrics', 'kivy.animation', 'kivy.utils',
    'kivy.resources', 'kivy.event', 'kivy.cache',
    # kivy core providers
    'kivy.core.window', 'kivy.core.window.window_sdl2',
    'kivy.core.text', 'kivy.core.text.text_sdl2',
    'kivy.core.clipboard', 'kivy.core.clipboard.clipboard_winctypes',
    'kivy.core.image', 'kivy.core.image.img_sdl2', 'kivy.core.image.img_pil',
    'kivy.core.image.img_tex', 'kivy.core.image.img_dds',
    'kivy.core.audio', 'kivy.core.audio.audio_sdl2',
    'kivy.core.text.markup',
    # kivy graphics
    'kivy.graphics', 'kivy.graphics.compiler', 'kivy.graphics.context',
    'kivy.graphics.context_instructions', 'kivy.graphics.fbo',
    'kivy.graphics.gl_instructions', 'kivy.graphics.instructions',
    'kivy.graphics.opengl', 'kivy.graphics.opengl_utils',
    'kivy.graphics.scissor_instructions', 'kivy.graphics.shader',
    'kivy.graphics.stencil_instructions', 'kivy.graphics.texture',
    'kivy.graphics.transformation', 'kivy.graphics.vbo',
    'kivy.graphics.vertex', 'kivy.graphics.vertex_instructions',
    'kivy.graphics.cgl', 'kivy.graphics.cgl_backend',
    'kivy.graphics.cgl_backend.cgl_glew', 'kivy.graphics.cgl_backend.cgl_sdl2',
    'kivy.graphics.cgl_backend.cgl_gl', 'kivy.graphics.cgl_backend.cgl_debug',
    'kivy.graphics.boxshadow', 'kivy.graphics.svg', 'kivy.graphics.buffer',
    'kivy.graphics.tesselator',
    # kivy uix widgets used by kvui
    'kivy.uix.widget', 'kivy.uix.layout', 'kivy.uix.label',
    'kivy.uix.button', 'kivy.uix.togglebutton', 'kivy.uix.textinput',
    'kivy.uix.boxlayout', 'kivy.uix.gridlayout', 'kivy.uix.floatlayout',
    'kivy.uix.relativelayout', 'kivy.uix.anchorlayout',
    'kivy.uix.scrollview', 'kivy.uix.popup', 'kivy.uix.image',
    'kivy.uix.progressbar', 'kivy.uix.tabbedpanel',
    'kivy.uix.recycleview', 'kivy.uix.recycleview.views',
    'kivy.uix.recycleview.layout', 'kivy.uix.recycleboxlayout',
    'kivy.uix.recyclegridlayout',
    'kivy.uix.behaviors', 'kivy.uix.behaviors.focus',
    'kivy.uix.behaviors.togglebutton', 'kivy.uix.behaviors.button',
    'kivy.uix.screenmanager', 'kivy.uix.settings',
    'kivy.uix.dropdown', 'kivy.uix.spinner', 'kivy.uix.modalview',
    'kivy.uix.stencilview', 'kivy.uix.scatter',
    # kivy input
    'kivy.input', 'kivy.input.providers',
    'kivy.input.providers.wm_touch', 'kivy.input.providers.wm_pen',
    'kivy.input.providers.mouse',
    'kivy.input.postproc',
    # kivy misc
    'kivy.modules', 'kivy.storage', 'kivy.network',
    # kivymd
    'kivymd', 'kivymd.app', 'kivymd.theming', 'kivymd.font_definitions',
    'kivymd.uix', 'kivymd.uix.dialog', 'kivymd.uix.gridlayout',
    'kivymd.uix.floatlayout', 'kivymd.uix.boxlayout',
    'kivymd.uix.navigationbar', 'kivymd.uix.screen',
    'kivymd.uix.screenmanager', 'kivymd.uix.menu', 'kivymd.uix.menu.menu',
    'kivymd.uix.dropdownitem', 'kivymd.uix.button',
    'kivymd.uix.label', 'kivymd.uix.recycleview',
    'kivymd.uix.textfield', 'kivymd.uix.textfield.textfield',
    'kivymd.uix.progressindicator', 'kivymd.uix.scrollview',
    'kivymd.uix.tooltip',
    'kivymd.icon_definitions',
    'kivymd.dynamic_color',
    'kivymd.material_resources',
    # other deps
    'psutil',
    'pymem', 'pymem.process',
    'process_memory',
    'websockets', 'websockets.legacy', 'websockets.legacy.client',
    'websockets.client',
    'yaml',
    'platformdirs',
    'colorama',
    'typing_extensions',
    'win32timezone',
]

# Modules to exclude (reduce size)
excludes = [
    'matplotlib', 'numpy', 'pandas', 'scipy', 'tkinter',
    'unittest', 'test', 'setuptools', 'pip', 'wheel',
    'docutils', 'pygments',
]

a = Analysis(
    [r'{source_dir / "SSHDClient.py"}'],
    pathex=[r'{source_dir}'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[r'{runtime_hook}'],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='{exe_name}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
{kivy_deps_block}
    strip=False,
    upx=True,
    upx_exclude=[],
    name='{exe_name}',
)
"""

    spec_path.write_text(spec_content, encoding="utf-8")
    print(f"[OK] Generated spec: {spec_path}")
    print()

    # ── Run PyInstaller ───────────────────────────────────────────
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--log-level", "WARN",
        str(spec_path),
    ]

    print("Running PyInstaller...")
    print()
    result = subprocess.run(cmd, cwd=str(source_dir))

    if result.returncode != 0:
        print()
        print("[FAIL] PyInstaller build failed!")
        sys.exit(1)

    # ── Verify output ─────────────────────────────────────────────
    exe_folder = dist_dir / exe_name
    exe_path = exe_folder / f"{exe_name}.exe"
    if not exe_path.exists():
        exe_path = exe_folder / exe_name  # non-Windows

    if not exe_path.exists():
        print(f"[FAIL] Executable not found at {exe_path}")
        sys.exit(1)

    size_mb = exe_path.stat().st_size / (1024 * 1024)
    folder_size = sum(f.stat().st_size for f in exe_folder.rglob("*") if f.is_file()) / (1024 * 1024)

    print()
    print("=" * 60)
    print(f"[OK] Built successfully!")
    print(f"     Exe:         {exe_path} ({size_mb:.1f} MB)")
    print(f"     Folder:      {exe_folder} ({folder_size:.0f} MB total)")
    print("=" * 60)

    # Copy the exe to source dir so build_apworld.py can find it
    dest = source_dir / exe_path.name
    shutil.copy2(exe_path, dest)
    print(f"[OK] Copied exe to: {dest}")

    return exe_path


if __name__ == "__main__":
    build_client_exe()
