"""
Logo patching for Archipelago SSHD patches.

This module handles patching the title screen and credits logos
to show Archipelago branding instead of the original randomizer logo.
"""

from pathlib import Path


def patch_archipelago_logo(romfs_output_path: Path, assets_path: Path, title2d_source: Path, endroll_source: Path, use_alt_logo: bool = False):
    """
    Patch the title screen and credits to show the Archipelago logo.
    
    Args:
        romfs_output_path: The output path for romfs files (e.g., temp_dir/romfs)
        assets_path: Path to the assets folder containing TPL files
        title2d_source: Path to the source Title2D.arc file
        endroll_source: Path to the source EndRoll.arc file
        use_alt_logo: If True, use the alternative Archipelago logo files
    """
    # Import sslib here so __init__.py has already added sshd-rando-backend to sys.path
    try:
        from sslib.u8file import U8File
        from sslib.utils import write_bytes_create_dirs
    except ImportError as e:
        print(f"Warning: sshd-rando not available, skipping logo patch (import error: {e})")
        return
        
    # Load custom Archipelago logo TPL files
    # Try multiple methods to handle both ZIP (Archipelago) and filesystem (dev) modes
    import pkgutil
    import importlib.resources
    
    logo_data = None
    rogo_03_data = None
    rogo_04_data = None
    
    # Select logo filenames based on whether the alternative logo is enabled
    alt_suffix = '_alt' if use_alt_logo else ''
    logo_tpl_filename = f'archipelago-logo{alt_suffix}.tpl'
    rogo_03_tpl_filename = f'archipelago-rogo_03{alt_suffix}.tpl'
    rogo_04_tpl_filename = f'archipelago-rogo_04{alt_suffix}.tpl'
    
    if use_alt_logo:
        print("[ArcPatcher] Using alternative Archipelago logo")
    
    # Try method 1: importlib.resources (best for ZIP files, Python 3.9+)
    try:
        if hasattr(importlib.resources, 'files'):
            assets = importlib.resources.files('worlds.sshd').joinpath('assets')
            logo_data = assets.joinpath(logo_tpl_filename).read_bytes()
            rogo_03_data = assets.joinpath(rogo_03_tpl_filename).read_bytes()
            rogo_04_data = assets.joinpath(rogo_04_tpl_filename).read_bytes()
            print("[ArcPatcher] Successfully loaded logo files from ZIP package")
    except Exception as e:
        print(f"[ArcPatcher] importlib.resources method failed: {e}")
        
    # Try method 2: pkgutil.get_data (fallback for older Python)
    if logo_data is None:
        try:
            logo_data = pkgutil.get_data("worlds.sshd.assets", logo_tpl_filename)
            rogo_03_data = pkgutil.get_data("worlds.sshd.assets", rogo_03_tpl_filename)
            rogo_04_data = pkgutil.get_data("worlds.sshd.assets", rogo_04_tpl_filename)
            
            if all([logo_data, rogo_03_data, rogo_04_data]):
                print("[ArcPatcher] Successfully loaded logo files via pkgutil")
            else:
                logo_data = None
        except Exception as e:
            print(f"[ArcPatcher] pkgutil method failed: {e}")
                
    # Try method 3: filesystem (for development environment)
    if logo_data is None:
        try:
            logo_tpl = assets_path / logo_tpl_filename
            rogo_03_tpl = assets_path / rogo_03_tpl_filename
            rogo_04_tpl = assets_path / rogo_04_tpl_filename
            
            print(f"[ArcPatcher] Trying filesystem method from: {assets_path}")
            
            if all(f.exists() for f in [logo_tpl, rogo_03_tpl, rogo_04_tpl]):
                logo_data = logo_tpl.read_bytes()
                rogo_03_data = rogo_03_tpl.read_bytes()
                rogo_04_data = rogo_04_tpl.read_bytes()
                print("[ArcPatcher] Successfully loaded logo files from filesystem")
            else:
                print(f"[ArcPatcher] Logo files not found in: {assets_path}")
        except Exception as e:
            print(f"[ArcPatcher] Filesystem method failed: {e}")
    
    # If we still don't have the logos, skip with a warning
    if not all([logo_data, rogo_03_data, rogo_04_data]):
        print("Warning: Custom Archipelago logo TPL files could not be loaded")
        print("  Using sshd-rando logos instead (already patched by sshd-rando)")
        return
    
    # Patch title screen logo
    if title2d_source.exists():
        print("Patching Title Screen Logo with Archipelago branding...")
        title_2d_arc = U8File.get_parsed_U8_from_path(title2d_source)
        title_2d_arc.set_file_data("timg/tr_wiiKing2Logo_00.tpl", logo_data)
        title_2d_arc.set_file_data("timg/th_rogo_03.tpl", rogo_03_data)
        title_2d_arc.set_file_data("timg/th_rogo_04.tpl", rogo_04_data)
        
        # Fix size of rogo stuff (makes the logo text shiny)
        if lyt_file := title_2d_arc.get_file_data("blyt/titleBG_00.brlyt"):
            # Changes the size of the P_loop_00, P_auraR_03, and P_auraR_00 lyt elements
            lyt_file = lyt_file.replace(
                b"\x43\xa4\xc0\x00\x43\x37\x00", b"\x43\xe6\x00\x00\x43\xa1\x80"
            )
            lyt_file = lyt_file.replace(
                b"\x41\x4c\x00\x00\xc2\x08", b"\x00\x00\x00\x00\x00\x00"
            )
            title_2d_arc.set_file_data("blyt/titleBG_00.brlyt", lyt_file)
        
        layout_output = romfs_output_path / "Layout"
        write_bytes_create_dirs(
            layout_output / "Title2D.arc", title_2d_arc.build_U8()
        )
        print(f"  ✓ Title screen logo patched: {layout_output / 'Title2D.arc'}")
    else:
        print(f"Warning: Title2D source not found at {title2d_source}")
    
    # Patch credits logo
    if endroll_source.exists():
        print("Patching Credits Logo with Archipelago branding...")
        endroll_arc = U8File.get_parsed_U8_from_path(endroll_source)
        endroll_arc.set_file_data("timg/th_zeldaRogoEnd_02.tpl", logo_data)
        endroll_arc.set_file_data("timg/th_rogo_03.tpl", rogo_03_data)
        endroll_arc.set_file_data("timg/th_rogo_04.tpl", rogo_04_data)
        
        # Fix size of rogo stuff (makes the logo text shiny)
        if lyt_file := endroll_arc.get_file_data("blyt/endTitle_00.brlyt"):
            # Changes the size of the P_loop_00, and P_auraR_00 lyt elements
            lyt_file = lyt_file.replace(
                b"\x40\x49\x99\x9a\x40\x49\x99\x9a\x43\x13\x80\x00\x42\xa2",
                b"\x3f\x80\x00\x00\x3f\x80\x00\x00\x44\x20\x00\x00\x43\xe0",
            )
            lyt_file = lyt_file.replace(
                b"\x41\x8c\x00\x00\xc2\x36",
                b"\x80\x00\x00\x00\x80\x00",
            )
            lyt_file = lyt_file.replace(
                b"\x41\x8c\x00\x00\xc2\x38",
                b"\x80\x00\x00\x00\x80\x00",
            )
            endroll_arc.set_file_data("blyt/endTitle_00.brlyt", lyt_file)
        
        layout_output = romfs_output_path / "Layout"
        write_bytes_create_dirs(
            layout_output / "EndRoll.arc", endroll_arc.build_U8()
        )
        print(f"  ✓ Credits logo patched: {layout_output / 'EndRoll.arc'}")
    else:
        print(f"Warning: EndRoll source not found at {endroll_source}")


def _load_oarc_asset(oarc_filename: str, assets_path: Path) -> bytes | None:
    """Load an OARC asset file from ZIP package, pkgutil, or filesystem."""
    import pkgutil
    import importlib.resources

    oarc_data = None

    # Try method 1: importlib.resources (ZIP packages)
    try:
        if hasattr(importlib.resources, 'files'):
            assets = importlib.resources.files('worlds.sshd').joinpath('assets')
            oarc_data = assets.joinpath(oarc_filename).read_bytes()
            print(f"[ArcPatcher] Loaded {oarc_filename} from ZIP package")
    except Exception:
        pass

    # Try method 2: pkgutil.get_data (fallback)
    if oarc_data is None:
        try:
            oarc_data = pkgutil.get_data("worlds.sshd.assets", oarc_filename)
            if oarc_data:
                print(f"[ArcPatcher] Loaded {oarc_filename} via pkgutil")
        except Exception:
            pass

    # Try method 3: filesystem (development)
    if oarc_data is None:
        try:
            oarc_path = assets_path / oarc_filename
            if oarc_path.exists():
                oarc_data = oarc_path.read_bytes()
                print(f"[ArcPatcher] Loaded {oarc_filename} from filesystem: {oarc_path}")
        except Exception:
            pass

    return oarc_data


def patch_archipelago_item_oarc(romfs_output_path: Path, assets_path: Path, model_setting: str = "archipelago_logo"):
    """
    Place the custom ArchipelagoItem OARC(s) into the cache/oarc folder
    so the existing arc patching pipeline picks it up and writes it
    to romfs/Object/NX/ automatically.

    model_setting: "letter", "archipelago_logo", or "unofficial_archipelago_logo"
    """
    if model_setting == "letter":
        # Letter mode uses GetKobunALetter which is already extracted from the game
        print("[ArcPatcher] Using Letter model — no custom OARC needed")
        return

    try:
        from sslib.utils import write_bytes_create_dirs
        from filepathconstants import CACHE_OARC_PATH
        import nlzss11
    except ImportError as e:
        print(f"Warning: sshd-rando not available, skipping item OARC patch (import error: {e})")
        return

    # Always load BOTH custom OARCs into cache — the stage patcher adds both
    # to every stage's object list, and the game selects the right one at
    # runtime based on archipelago_item_model in RANDOMIZER_SETTINGS.
    arcs_to_load = [
        ("ArchipelagoItem.arc.LZ", "ArchipelagoItem.arc"),
        ("ArchipelagoItem2.arc.LZ", "ArchipelagoItem2.arc"),
    ]

    for oarc_filename, cache_name in arcs_to_load:
        oarc_data = _load_oarc_asset(oarc_filename, assets_path)

        if oarc_data is None:
            print(f"Warning: {oarc_filename} not found in assets, skipping custom item model")
            continue

        # Decompress the LZ data to get the raw .arc for the cache
        decompressed = nlzss11.decompress(oarc_data)

        # Write to cache/oarc/ so patch_object_folder() picks it up
        cache_arc_path = CACHE_OARC_PATH / cache_name
        write_bytes_create_dirs(cache_arc_path, decompressed)
        print(f"  ✓ Custom {cache_name} placed in cache: {cache_arc_path}")


def patch_key_item_oarcs(assets_path: Path):
    """
    Place the KeyRing and SkeletonKey OARC models into the cache/oarc folder
    so the stage patching pipeline picks them up for use in item get animations.

    The assets folder contains:
      - KeyRing.arc.LZ
      - SkeletonKey.arc.LZ

    Both OARCs are always loaded unconditionally so they are available
    regardless of which key-ring/skeleton-key mode the player uses.
    """
    try:
        from sslib.utils import write_bytes_create_dirs
        from filepathconstants import CACHE_OARC_PATH
        import nlzss11
    except ImportError as e:
        print(f"Warning: sshd-rando not available, skipping key item OARC patch (import error: {e})")
        return

    # (source asset filename, cache target)
    arcs_to_load = [
        ("KeyRing.arc.LZ", "KeyRing.arc"),
        ("SkeletonKey.arc.LZ", "SkeletonKey.arc"),
    ]

    for primary_filename, cache_name in arcs_to_load:
        oarc_data = _load_oarc_asset(primary_filename, assets_path)

        if oarc_data is None:
            print(f"Warning: {primary_filename} not found in assets, skipping key item model")
            continue

        decompressed = nlzss11.decompress(oarc_data)
        cache_arc_path = CACHE_OARC_PATH / cache_name
        write_bytes_create_dirs(cache_arc_path, decompressed)
        print(f"  ✓ Custom {cache_name} placed in cache: {cache_arc_path}")
