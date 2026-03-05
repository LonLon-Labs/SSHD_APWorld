"""
Logo patching for Archipelago SSHD patches.

This module handles patching the title screen and credits logos
to show Archipelago branding instead of the original randomizer logo.
"""

from pathlib import Path
import sys

# Add sshd-rando to path for utilities
SSHD_RANDO_PATH = Path(__file__).parent.parent.parent / "sshd-rando"
if SSHD_RANDO_PATH.exists():
    sys.path.insert(0, str(SSHD_RANDO_PATH))

try:
    from sslib.u8file import U8File
    from sslib.utils import write_bytes_create_dirs
    HAS_SSHD_RANDO = True
except ImportError:
    HAS_SSHD_RANDO = False


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
    if not HAS_SSHD_RANDO:
        print("Warning: sshd-rando not available, skipping logo patch")
        return
    
    # Select logo filenames based on whether the alternative logo is enabled
    alt_suffix = '_alt' if use_alt_logo else ''
    if use_alt_logo:
        print("[ArcPatcher] Using alternative Archipelago logo")
        
    # Load custom Archipelago logo TPL files
    logo_tpl = assets_path / f"archipelago-logo{alt_suffix}.tpl"
    rogo_03_tpl = assets_path / f"archipelago-rogo_03{alt_suffix}.tpl"
    rogo_04_tpl = assets_path / f"archipelago-rogo_04{alt_suffix}.tpl"
    
    if not all(f.exists() for f in [logo_tpl, rogo_03_tpl, rogo_04_tpl]):
        print("Warning: Custom Archipelago logo TPL files not found in assets folder")
        print(f"  Expected: {logo_tpl}")
        print(f"  Expected: {rogo_03_tpl}")
        print(f"  Expected: {rogo_04_tpl}")
        return
        
    logo_data = logo_tpl.read_bytes()
    rogo_03_data = rogo_03_tpl.read_bytes()
    rogo_04_data = rogo_04_tpl.read_bytes()
    
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
