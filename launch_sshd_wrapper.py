"""
Launcher wrapper for SSHD Archipelago Client (Cross-platform)
"""
import zipfile
import sys
import os
from pathlib import Path

# Find .apworld file (cross-platform)
try:
    from platform_utils import get_custom_worlds_dir
    apworld_dir = get_custom_worlds_dir()
except ImportError:
    if sys.platform == "win32":
        apworld_dir = Path("C:/ProgramData/Archipelago/custom_worlds")
    elif sys.platform == "linux":
        apworld_dir = Path.home() / ".local" / "share" / "Archipelago" / "custom_worlds"
    else:
        apworld_dir = Path.home() / "Library" / "Application Support" / "Archipelago" / "custom_worlds"

APWORLD_PATH = apworld_dir / "sshd.apworld"

if not APWORLD_PATH.exists():
    print(f"ERROR: sshd.apworld not found at {APWORLD_PATH}")
    print(f"Expected location: {apworld_dir}")
    sys.exit(1)

# Add Archipelago lib directory to sys.path for dependencies
if sys.platform == "win32":
    lib_dir = Path("C:/ProgramData/Archipelago/lib")
elif sys.platform == "linux":
    lib_dir = Path.home() / ".local" / "share" / "Archipelago" / "lib"
else:
    lib_dir = Path.home() / "Library" / "Application Support" / "Archipelago" / "lib"

if lib_dir.exists():
    sys.path.insert(0, str(lib_dir))

# Add kivy-deps DLL directories to PATH BEFORE any imports (Windows only)
if sys.platform == "win32":
    dll_paths_added = []
    
    # Check system Python site-packages for kivy-deps (most common location)
    try:
        import site
        for site_pkg in site.getsitepackages():
            site_path = Path(site_pkg)
            # Check common kivy-deps locations
            for dep in ['sdl2', 'glew']:
                check_paths = [
                    site_path / 'share' / dep / 'bin',
                    site_path / 'kivy_deps' / dep / 'bin',
                ]
                for check_path in check_paths:
                    if check_path.exists():
                        # Python 3.8+ requires os.add_dll_directory() on Windows
                        try:
                            os.add_dll_directory(str(check_path))
                            dll_paths_added.append(str(check_path))
                        except (AttributeError, OSError):
                            # Fallback for older Python or if add_dll_directory fails
                            os.environ['PATH'] = str(check_path) + os.pathsep + os.environ.get('PATH', '')
                            dll_paths_added.append(str(check_path))
    except Exception as e:
        pass
    
    # Also check lib directory if it exists
    if lib_dir.exists():
        for dep in ['sdl2', 'glew']:
            check_paths = [
                lib_dir / 'share' / dep / 'bin',
                lib_dir / 'kivy_deps' / dep / 'bin',
                lib_dir / f'kivy_deps.{dep}' / 'share' / f'kivy_deps-{dep}' / 'bin',
            ]
            for check_path in check_paths:
                if check_path.exists():
                    try:
                        os.add_dll_directory(str(check_path))
                        dll_paths_added.append(str(check_path))
                    except (AttributeError, OSError):
                        os.environ['PATH'] = str(check_path) + os.pathsep + os.environ.get('PATH', '')
                        dll_paths_added.append(str(check_path))

sys.path.insert(0, str(APWORLD_PATH))

# Preserve command-line arguments (remove wrapper script name, keep client args)
# sys.argv[0] will be launch_sshd_wrapper.py, we want to replace it with SSHDClient.py
if len(sys.argv) > 1:
    client_args = sys.argv[1:]  # Keep any arguments passed to wrapper (like --nogui)
    sys.argv = [f'{APWORLD_PATH}/sshd/SSHDClient.py'] + client_args
else:
    sys.argv = [f'{APWORLD_PATH}/sshd/SSHDClient.py']

# Extract and execute SSHDClient
zf = zipfile.ZipFile(str(APWORLD_PATH))
code = zf.read('sshd/SSHDClient.py').decode('utf-8')

# Execute with proper context - must include builtins for imports to work
exec(code, {
    '__name__': '__main__',
    '__file__': f'{APWORLD_PATH}/sshd/SSHDClient.py',
    '__package__': 'sshd',
    '__builtins__': __builtins__
})
