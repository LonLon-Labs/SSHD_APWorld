import hashlib
import shutil
import struct
import time
from constants.verificationconstants import BZS_FILE_HASHES
from patches.stagepatchhelper import patch_additional_properties
from util.arguments import get_program_args
from gui.dialogs.dialog_header import (
    get_progress_value_from_range,
    print_progress_text,
    update_progress_value,
)
from patches.conditionalpatchhandler import ConditionalPatchHandler
from patches.othermods import (
    get_resolved_game_file_path,
)
from sslib.bzs import parse_bzs, build_bzs, get_entry_from_bzs, get_highest_object_id
from sslib.utils import mask_shift_set, write_bytes_create_dirs
from sslib.yaml import yaml_load
from sslib.u8file import U8File
from logic.world import World

from collections import defaultdict
from pathlib import Path
import json
import os
import random

from constants.tboxsubtypes import VANILLA_TBOX_SUBTYPES
from constants.patchconstants import (
    DEFAULT_PATH,
    DEFAULT_PNT,
    DEFAULT_SOBJ,
    DEFAULT_OBJ,
    DEFAULT_SCEN,
    DEFAULT_PLY,
    DEFAULT_AREA,
    STAGE_OBJECT_NAMES,
    VALID_STAGE_PATCH_TYPES,
)

from filepathconstants import (
    BZS_TEMPLATE_PATH,
    CACHE_BZS_PATH,
    CACHE_OARC_PATH,
    CACHE_PATH,
    OTHER_MODS_PATH,
    STAGE_FILES_PATH,
    STAGE_PATCHES_PATH,
    EXTRACTS_PATH,
    OBJECTPACK_PATH,
)

args = get_program_args()

# OARCs needed for AP-delivered items. Added to every room's layer 0 ARCN so
# they load synchronously during stage transitions. This ensures correct 3D
# models for items received from the Archipelago network in any stage.
# Names are bare OARC names (no .arc extension), matching BZS ARCN format.
# Only includes OARCs NOT already in ObjectPack (those are globally available).
AP_ITEM_OARC_NAMES: frozenset[str] = frozenset({
    "Demo11_01",
    "GetSwordA", "GetHarp",
    "GetBowA", "GetBowB", "GetBowC",
    "GetHookShot", "GetBirdStatue", "SaveObjectA",
    "GetKeyBoss2A", "GetKeyBoss2B", "GetKeyBoss2C",
    "GetKeyKakera", "GetKeyBossA", "GetKeyBossB", "GetKeyBossC",
    "GetVacuum", "GetPachinkoA", "GetPachinkoB",
    "GetBeetleA", "GetBeetleB", "GetBeetleC", "GetBeetleD",
    "GetMoleGloveA", "GetMoleGloveB", "GetSeedSet",
    "GetBottleMuteki", "GetUroko", "GetMedal",
    "GetNetA", "GetNetB", "GetBottleHoly",
    "GetBottleKusuri", "GetBottleKusuriS",
    "GetBottleGuts", "GetBottleAir", "GetBombBag",
    "GetHeartUtuwa", "PutHeartUtuwa",
    "PutTriForceSingle", "GetTriForceSingle",
    "GetMapSea",
    "GetPurseB", "GetPurseC", "GetPurseD", "GetPurseE",
    "GetPouchA", "GetPouchB",
    "GetShieldWood", "GetShieldHylia",
    "GetBottleRepair", "GetBottleRepairS",
    "GetSpareSeedA", "GetSpareQuiverA", "GetSpareBombBagA",
    "GetWhip", "GetEarring",
    "GetKobunALetter", "GetTerryCage",
    "ArchipelagoItem", "ArchipelagoItem2",
    "KeyRing", "SkeletonKey",
    "GetGaragara", "PutGaragara",
    "GetSozaiC", "GetSozaiF", "GetSozaiH",
    "GetSozaiL", "GetSozaiN", "GetSozaiO", "GetSozaiP",
    "GetSekibanMapA", "GetSekibanMapB", "GetSekibanMapC",
    "GetSirenKey",
    "GetBottlePumpkin", "GetSeedLife", "GetFruitB",
    "GetSparePurse",
    "Onp", "DesertRobot", "RivalCmnAnm", "RivalNpcAnm",
    "GetBlueRupee", "GetRedRupee", "GetSilverRupee",
    "GetGoldRupee", "GetRupoor",
})

# Stages where the blanket AP_ITEM_OARC_NAMES injection is skipped even
# when check_patches exist.  These stages are loaded during the post-Demise
# ending cutscene chain (B400→F404→F402→credits) under high resource
# pressure; the extra ~80 OARCs cause a PANIC on SSystem::mDvd.
# Per-item OARCs from add_arcn_for_check are still applied so randomised
# check pickups display the correct model.
_SKIP_AP_OARC_STAGES: frozenset[str] = frozenset({"B400", "F400", "F402", "F403", "F404", "F405", "F407"})


# Story flags set by striking each of the 27 Goddess Cubes, in ascending order.
# The game's Rust additions (item.rs GODDESS_CUBE_STORYFLAGS) use the same order to
# index the GODDESS_CUBE_CUSTOM_FLAGS / GODDESS_CUBE_ITEM_IDS tables.
GODDESS_CUBE_STORYFLAGS: list[int] = [
    227, 228, 229, 230, 231, 234, 235, 236, 237, 238, 239, 240, 241, 242,
    243, 244, 245, 246, 247, 248, 249, 250, 251, 252, 254, 255, 256,
]


# The 26 "Bird Statues Give Items" locations, in the order the game's Rust additions
# (item.rs BIRD_STATUES) index the BIRD_STATUE_CUSTOM_FLAGS / BIRD_STATUE_ITEM_IDS
# tables. Same order as the AP location codes 2773911..=2773936.
BIRD_STATUE_LOCATION_NAMES: list[str] = [
    "Sealed Grounds - Sealed Grounds Bird Statue",
    "Sealed Grounds - Behind the Temple Bird Statue",
    "Faron Woods - Faron Woods Entry Bird Statue",
    "Faron Woods - In the Woods Bird Statue",
    "Faron Woods - Viewing Platform Bird Statue",
    "Deep Woods - Deep Woods Bird Statue",
    "Deep Woods - Forest Temple Bird Statue",
    "Faron Woods - Great Tree Bird Statue",
    "Lake Floria - Lake Floria Bird Statue",
    "Floria Waterfall - Floria Waterfall Bird Statue",
    "Eldin Volcano - Volcano Entrance Bird Statue",
    "Eldin Volcano - Volcano East Bird Statue",
    "Eldin Volcano - Volcano Ascent Bird Statue",
    "Eldin Volcano - Temple Entrance Bird Statue",
    "Lanayru Mine - Mine Entry Bird Statue",
    "Lanayru Desert - Desert Entrance Bird Statue",
    "Lanayru Desert - West Desert Bird Statue",
    "Lanayru Desert - Desert Gorge Bird Statue",
    "Temple of Time - Temple of Time Bird Statue",
    "Lanayru Desert - North Desert Bird Statue",
    "Lanayru Desert - Stone Cache Bird Statue",
    "Ancient Harbour - Ancient Harbour Bird Statue",
    "Skipper's Retreat - Skipper's Retreat Bird Statue",
    "Shipyard - Shipyard Bird Statue",
    "Pirate Stronghold - Pirate Stronghold Bird Statue",
    "Lanayru Gorge - Lanayru Gorge Bird Statue",
]


def patch_goddess_chest_spawn_flag(bzs: dict, spawn_storyflag: int):
    # Re-points the story flag that unlocks every vanilla Goddess Chest (TBox
    # subtype 3) in the given layer. Vanilla, this is the story flag set by
    # striking the chest's corresponding Goddess Cube.
    #
    # The chest passes its whole params2 to StoryflagManager::getFlag(u16), so
    # the flag is the LOW 16 BITS of params2 (verified in the game binary:
    # dAcTbox create reads actor+0x12C == param2 and calls getFlag with it).
    # NOTE: this overlaps bits 8-15, which is why patch_tbox must never write a
    # custom flag to bits 8-17 of a Goddess Chest (it would change the flag).
    #
    # This must run BEFORE patch_tbox modifies the chest's item id, since the
    # vanilla subtype is read from the vanilla item id.
    for tbox in bzs.get("OBJS", []):
        if tbox["name"] != "TBox":
            continue
        vanilla_itemid = tbox["anglez"] & 0x1FF
        try:
            vanilla_subtype = VANILLA_TBOX_SUBTYPES[vanilla_itemid]
        except (KeyError, IndexError):
            continue
        if vanilla_subtype != 3:
            continue
        tbox["params2"] = mask_shift_set(tbox["params2"], 0xFFFF, 0, spawn_storyflag)


def patch_tbox(
    bzs: dict, itemid: int, object_id_str: str, trapid: int, tbox_subtype: int,
    custom_flag: int = 0x3FF,
):
    id = int(object_id_str)
    tbox: dict | None = next(
        filter(lambda x: x["name"] == "TBox" and (x["anglez"] >> 9) == id, bzs["OBJS"]),
        None,
    )

    if tbox is None:
        raise Exception(f"No TBox with id '{id}' found to patch.")

    # Need to check this as itemid is the itemid of the fake item model when trapid > 0
    if trapid:
        trapbits = 254 - trapid
        # Unsets bit 0xF0000000 of params2
        tbox["params2"] = mask_shift_set(tbox["params2"], 0xF, 28, trapbits)
    else:
        # Makes sure the bit is set if not a trap
        tbox["params2"] = mask_shift_set(tbox["params2"], 0xF, 28, 0xF)

    original_itemid = tbox["anglez"] & 0x1FF

    # Patch chest subtype
    #
    ## 0 = Big Blue Chest
    ## 1 = Small Brown Chest
    ## 2 = Fancy Boss Key Chest
    ## 3 = Goddess Chest
    vanilla_tbox_subtype = VANILLA_TBOX_SUBTYPES[original_itemid]

    if vanilla_tbox_subtype == 3:
        # Goddess Chests (subtype 0x03) expect the signed negative number of
        # the item id for the item they have (for some reason)
        # 9 bits means 2^9 - 1 = 511
        #
        # For AP items (id > 215), store the AP item ID directly in anglez so
        # the game shows the Archipelago Item model (id 216) from the chest.
        # The AP custom_flag is written to params2 bits 18-27 (below) so
        # fix_tbox_traps can read it and propagate it through NEXT_CUSTOM_FLAG.
        # AP location completion is also detected via the vanilla tboxflag
        # polled by check_goddess_chest_flags.
        itemid = 511 - itemid
        tbox_subtype = 3
    elif tbox_subtype == -1:
        tbox_subtype = vanilla_tbox_subtype

    # For normal chests: encode AP custom_flag into params2 bits 8-17 (10 bits).
    # fix_tbox_traps reads bits 8-17 and propagates it to the spawned item actor.
    #
    # IMPORTANT: Do NOT write custom_flag to params2 bits 8-17 for Goddess Chests
    # (vanilla subtype 3). The game engine uses bits 8-17 as part of the TBox
    # spawn condition check — writing non-vanilla values causes goddess chests to
    # bypass their spawn_sceneflag gate and appear without the cube being struck.
    #
    # For goddess chests: encode AP custom_flag into params2 bits 18-27 instead.
    # Bits 18-27 are unused by vanilla and safe to use for our custom flag.
    # fix_tbox_traps reads bits 18-27 for goddess chests and propagates the flag
    # through NEXT_CUSTOM_FLAG → spawned_actor_traps → item actor param2.
    # AP location completion is ALSO detected via the vanilla tboxflag
    # (polled by check_goddess_chest_flags in the AP client).
    if vanilla_tbox_subtype != 3:
        tbox["params2"] = mask_shift_set(tbox["params2"], 0x3FF, 8, custom_flag)
    elif custom_flag != 0x3FF:
        # Goddess chest: store AP custom_flag in bits 18-27 (bits 8-17 reserved)
        tbox["params2"] = mask_shift_set(tbox["params2"], 0x3FF, 18, custom_flag)

    tbox["params1"] = mask_shift_set(tbox["params1"], 0x3, 4, tbox_subtype)

    # Patch itemid
    tbox["anglez"] = mask_shift_set(tbox["anglez"], 0x1FF, 0, itemid)

    # Return the vanilla chestflag for goddess chests so the caller
    # can build a mapping for the AP client to poll via FA.tboxflags.
    # chestflag = anglez >> 9 (upper 7 bits), stored in save as tboxflags[scene][flag//8] bit (flag%8).
    # (set_sceneflag = anglex & 0xFF is always 0xFF for goddess chests — cannot be used.)
    if vanilla_tbox_subtype == 3:
        return (tbox["anglez"] >> 9) & 0x7F
    return -1


def patch_freestanding_item(
    bzs: dict,
    itemid: int,
    object_id_str: str,
    trapid: int,
    custom_flag: int,
    original_itemid: int,
):
    id = int(object_id_str, 0)
    freestanding_item: dict | None = next(
        filter(
            lambda x: x["name"] == "Item"
            and (((x["params1"] >> 10) & 0xFF) == id or x["id"] == id),
            bzs["OBJ "],
        ),
        None,
    )
    if freestanding_item is None:
        raise Exception(
            f"No freestanding item with id '{id}({hex(id)})' found to patch."
        )

    # Need to check this as itemid is the itemid of the fake item model when trapid > 0
    if trapid:
        trapbits = 254 - trapid
        # Unsets bit 0x000000F0 of params2
        freestanding_item["params2"] = mask_shift_set(
            freestanding_item["params2"], 0xF, 4, trapbits
        )
    else:
        # Makes sure the bit is set if not a trap
        freestanding_item["params2"] = mask_shift_set(
            freestanding_item["params2"], 0xF, 4, 0xF
        )

    freestanding_item["params1"] = mask_shift_set(
        freestanding_item["params1"], 0x1FF, 0, itemid
    )

    # Unset 9th bit of param1 to force a textbox for freestanding items.
    freestanding_item["params1"] = mask_shift_set(
        freestanding_item["params1"], 0x1, 9, 0
    )

    if custom_flag != -1:
        freestanding_item["params2"] = mask_shift_set(
            freestanding_item["params2"], 0x3FF, 8, custom_flag
        )
        freestanding_item["params2"] = mask_shift_set(
            freestanding_item["params2"], 0x3F, 18, original_itemid
        )


def patch_dusk_relic(
    bzs: dict,
    itemid: int,
    object_id_and_scene_flag_str: str,
    trapid: int,
    custom_flag: int = 0x3FF,
    original_itemid: int = 0,
) -> None:

    # Don't change anything if this is a dusk relic
    if itemid == 168:
        return

    object_id_str, sceneflag_str = object_id_and_scene_flag_str.split("-")
    id = int(object_id_str, 0)
    scene_flag = int(sceneflag_str, 0)

    freestanding_item: dict | None = next(
        filter(
            lambda x: x["name"] == "AncJwls" and x["id"] == id,
            bzs["OBJ "],
        ),
        None,
    )
    if freestanding_item is None:
        raise Exception(
            f"No freestanding item with id '{id}({hex(id)})' found to patch."
        )

    # Need to check this as itemid is the itemid of the fake item model when trapid > 0
    if trapid:
        trapbits = 254 - trapid
        # Unsets bit 0x000000F0 of params2
        freestanding_item["params2"] = mask_shift_set(
            freestanding_item["params2"], 0xF, 4, trapbits
        )
    else:
        # Makes sure the bit is set if not a trap
        freestanding_item["params2"] = mask_shift_set(
            freestanding_item["params2"], 0xF, 4, 0xF
        )

    # Change the actor into an Item instead of AncJwls
    freestanding_item["name"] = "Item"

    # Set the scene flag and item id to use in the params
    params1 = 0xFF9C0200
    params1 = mask_shift_set(params1, 0x1FF, 0, itemid)
    params1 = mask_shift_set(params1, 0xFF, 10, scene_flag)
    # Unset 9th bit of param1 to force a textbox for freestanding items.
    params1 = mask_shift_set(params1, 0x1, 9, 0)

    freestanding_item["params1"] = params1

    # Encode Archipelago custom_flag into params2 bits 8-17 (same as Item actors)
    if custom_flag != -1:
        freestanding_item["params2"] = mask_shift_set(
            freestanding_item["params2"], 0x3FF, 8, custom_flag
        )
        freestanding_item["params2"] = mask_shift_set(
            freestanding_item["params2"], 0x3F, 18, original_itemid
        )


def patch_bucha(
    bzs: dict, itemid: int, object_id_str: str, trapid: int,
    custom_flag: int = 0x3FF,
):
    id = int(object_id_str, 16)
    bucha: dict | None = next(
        filter(lambda x: x["name"] == "NpcKyuE" and x["id"] == id, bzs["OBJ "]), None
    )

    if bucha is None:
        raise Exception(f"Bucha's id '{id}' not found. Cannot patch this check.")

    # Need to check this as itemid is the itemid of the fake item model when trapid > 0
    if trapid:
        trapbits = 254 - trapid
        # Unsets bit 0x000000F0 of params2
        bucha["params2"] = mask_shift_set(bucha["params2"], 0xF, 4, trapbits)
    else:
        # Makes sure the bit is set if not a trap
        bucha["params2"] = mask_shift_set(bucha["params2"], 0xF, 4, 0xF)

    # Item id is 9 bits wide: params2 bits 8-16 (read by fix-bucha.asm: load + ubfx).
    bucha["params2"] = mask_shift_set(bucha["params2"], 0x1FF, 0x8, itemid)

    # Encode Archipelago custom_flag into params2 bits 18-27 (10 bits)
    # NOTE: bits 8-15 are occupied by itemid, so custom_flag uses
    # a higher range.  Requires matching ASM to read from this position.
    if custom_flag != 0x3FF:
        bucha["params2"] = mask_shift_set(bucha["params2"], 0x3FF, 18, custom_flag)


def patch_closet(
    bzs: dict, itemid: int, object_id_str: str, trapid: int, room: int, stage: str,
    custom_flag: int = 0x3FF,
):
    id = int(object_id_str, 16)
    closet: dict | None = next(
        filter(lambda x: x["name"] == "chest" and x["id"] == id, bzs["OBJ "]),
        None,
    )

    if closet is None:
        raise Exception(f"No closet with id '{id}' found to patch.")

    # Need to check this as itemid is the itemid of the fake item model when trapid > 0
    if trapid:
        trapbits = 254 - trapid
        # Unsets bit 0x000000F0 of params2
        closet["params2"] = mask_shift_set(closet["params2"], 0xF, 4, trapbits)
    else:
        # Makes sure the bit is set if not a trap
        closet["params2"] = mask_shift_set(closet["params2"], 0xF, 4, 0xF)

    # Encode Archipelago custom_flag into params2 bits 8-17 (10 bits)
    # This gets read by handle_closet_traps in Rust and propagated to the
    # spawned item actor via ACTORBASE_PARAM2, where unpack_custom_item_params
    # will extract it and call set_global_sceneflag for Archipelago detection.
    closet["params2"] = mask_shift_set(closet["params2"], 0x3FF, 8, custom_flag)

    # Mapping of each closet (scene, roomid, objectid) to the local scene flag we'll use
    unused_scene_flags: dict[tuple[str, int, int], int] = {
        ("F001r", 1, 0xFC08): 12,  # Link's Closet            0x10
        ("F001r", 1, 0xFC07): 24,  # Fledge's Closet          2x01
        ("F001r", 6, 0xFC07): 32,  # Zelda's Closet           5x01 (vanilla scene flag)
        ("F001r", 2, 0xFC03): 48,  # Groose's Closet          7x01
        ("F001r", 5, 0xFC05): 50,  # Owlan's Closet           7x04
        ("F001r", 4, 0xFC03): 57,  # Horwell's Closet         6x02
        ("F001r", 6, 0xFC06): 61,  # Karane's Closet          6x20
        ("F005r", 0, 0xFC0E): 81,  # O&P's Closet             Bx02
        ("F006r", 0, 0xFC16): 82,  # Kukiel's Closet          Bx04
        ("F013r", 0, 0xFC0E): 100,  # Sparrot's Closet        Dx10
        ("F014r", 0, 0xFC12): 101,  # Luv and Bertie's Closet Dx20
        ("F015r", 0, 0xFC10): 105,  # Gondo's Closet          Cx02
        ("F016r", 0, 0xFC28): 107,  # Pipit's Closet          Cx04
        ("F017r", 0, 0xFC1E): 116,  # Rupin's Closet          Fx10
        ("F018r", 0, 0xFC11): 117,  # Peater's Closet         Fx20
        ("F018r", 0, 0xFC12): 118,  # Peatrice's Closet       Fx40
        ("F011r", 0, 0xFC3B): 3,  # Pumm and Kina's Closet    1x08
        ("F301_5", 0, 0xFC0C): 0,  # Skipper's Closet         2x01
    }

    # Specify which scene flag to use
    closet["params1"] = mask_shift_set(
        closet["params1"], 0xFF, 0, unused_scene_flags[(stage, room, id)]
    )
    # Patch in the item: params1 bits 8-15 hold the low 8 bits of the id (that's what
    # the game's closet code reads). Ids >= 256 additionally clear params2 bit 18
    # (1 for every other closet) so handle_closet_traps rebuilds the full 9-bit id.
    closet["params1"] = mask_shift_set(closet["params1"], 0xFF, 8, itemid & 0xFF)
    closet["params2"] = mask_shift_set(
        closet["params2"], 0x1, 18, 0 if itemid >= 256 else 1
    )
    # Tell the closet to interpret the flag as a local scene flag
    closet["params1"] = mask_shift_set(closet["params1"], 0x1, 16, 1)


def patch_ac_key_boko(bzs: dict, itemid: int, object_id_str: str, trapid: int, custom_flag: int = 0x3FF):
    id = int(object_id_str, 16)
    boko: dict | None = next(
        filter(lambda x: x["name"] == "EBc" and x["id"] == id, bzs["OBJ "]), None
    )

    if boko is None:
        raise Exception(f"No Bokoblin (EBc) with id '{id}' found to patch.")

    # Need to check this as itemid is the itemid of the fake item model when trapid > 0
    if trapid:
        trapbits = 254 - trapid
        # Unsets bit 0x000000F0 of params2
        boko["params2"] = mask_shift_set(boko["params2"], 0xF, 8, trapbits)
    else:
        # Makes sure the bit is set if not a trap
        boko["params2"] = mask_shift_set(boko["params2"], 0xF, 8, 0xF)

    # Store the low 8 bits of the itemid in params2 bits 0-7 (ASM reads from offset
    # 0x12C). Ids >= 256 set tag 0 in params2 bits 22-23 so the shared trap hook
    # (traps.rs handle_ac_boko_and_heartco_and_digspot_traps) rebuilds the full id;
    # tag 3 (all ones, the unpatched default) means no extended id.
    boko["params2"] = mask_shift_set(boko["params2"], 0xFF, 0x0, itemid & 0xFF)
    boko["params2"] = mask_shift_set(
        boko["params2"], 0x3, 22, 0 if itemid >= 256 else 3
    )

    # Encode Archipelago custom_flag into params2 bits 12-21 (10 bits)
    # Always write (even 0x3FF sentinel) so vanilla bits are overwritten
    # with a known value.  Rust reads these via (param2 >> 12) & 0x3FF.
    boko["params2"] = mask_shift_set(
        boko["params2"], 0x3FF, 12, custom_flag
    )


def patch_heart_container(bzs: dict, itemid: int, trapid: int, custom_flag: int = 0x3FF):
    heart_container: dict | None = next(
        filter(lambda x: x["name"] == "HeartCo", bzs["OBJ "]), None
    )

    if heart_container is None:
        raise Exception(f"No heart container found to patch.")

    # Need to check this as itemid is the itemid of the fake item model when trapid > 0
    if trapid:
        trapbits = 254 - trapid
        # Unsets bit 0x000000F0 of params2
        heart_container["params2"] = mask_shift_set(
            heart_container["params2"], 0xF, 8, trapbits
        )
    else:
        # Makes sure the bit is set if not a trap
        heart_container["params2"] = mask_shift_set(
            heart_container["params2"], 0xF, 8, 0xF
        )

    # Low 8 bits of the itemid in params1 bits 16-23; ids >= 256 set tag 1 in
    # params2 bits 22-23 (see the boko patch / traps.rs); 3 = no extended id.
    heart_container["params1"] = mask_shift_set(
        heart_container["params1"], 0xFF, 16, itemid & 0xFF
    )
    heart_container["params2"] = mask_shift_set(
        heart_container["params2"], 0x3, 22, 1 if itemid >= 256 else 3
    )

    # Encode Archipelago custom_flag into params2 bits 12-21 (10 bits)
    # Always write (even 0x3FF sentinel) so vanilla bits are overwritten
    # with a known value.  Rust reads these via (param2 >> 12) & 0x3FF.
    heart_container["params2"] = mask_shift_set(
        heart_container.get("params2", 0xFFFFFFFF), 0x3FF, 12, custom_flag
    )


def patch_chandelier_item(bzs: dict, itemid: int, trapid: int, custom_flag: int = 0x3FF):
    chandelier: dict | None = next(
        filter(lambda x: x["name"] == "Chandel", bzs["OBJ "]), None
    )

    if chandelier is None:
        raise Exception(f"No chandelier found to patch.")

    # Don't use fake itemid yet, this needs patching properly first
    if trapid:
        itemid = 34  # rupoor

    # The chandelier's asm reads its item id with a single byte load (params1 bits
    # 8-15) and there is no spare instruction there to widen it, so ids >= 256 (the
    # Bird Statue unlock items) can't be placed here. The AP world forbids that
    # placement (EXTENDED_ITEM_ID_UNSUPPORTED_LOCATIONS in __init__.py); fail loudly
    # rather than silently placing the wrong item if it ever happens anyway.
    if itemid > 0xFF:
        raise Exception(
            f"Chandelier item id {itemid} doesn't fit in 8 bits; only item ids 0-255 "
            "can be placed on the chandelier."
        )

    chandelier["params1"] = mask_shift_set(chandelier["params1"], 0xFF, 8, itemid)

    # Encode Archipelago custom_flag into params2 bits 8-17 (10 bits)
    if custom_flag != 0x3FF:
        chandelier["params2"] = mask_shift_set(
            chandelier.get("params2", 0xFFFFFFFF), 0x3FF, 8, custom_flag
        )


def patch_tree_of_life(bzs: dict, itemid: int, trapid: int, custom_flag: int = 0x3FF):
    tree: dict | None = next(
        filter(lambda x: x["name"] == "FrtTree", bzs["OBJ "]), None
    )

    if tree is None:
        raise Exception(f"No FrtTree (Tree of Life) found to patch.")

    # Need to check this as itemid is the itemid of the fake item model when trapid > 0
    if trapid:
        trapbits = 254 - trapid
        # Unsets bit 0x000000F0 of params2
        tree["params2"] = mask_shift_set(tree["params2"], 0xF, 4, trapbits)
    # No need for other checks as params2 is always 0xFFFFFFFF

    # Item id: params1 bits 23-31 (9 bits). Read by Rust (spawn_tree_of_life_item).
    tree["params1"] = mask_shift_set(tree["params1"], 0x1FF, 23, itemid)

    # Encode Archipelago custom_flag into params2 bits 8-17 (10 bits)
    # The Rust spawn_tree_of_life_item() passes param2 directly to the spawned
    # dAcItem, so unpack_custom_item_params() will read it at the standard position.
    if custom_flag != 0x3FF:
        tree["params2"] = mask_shift_set(
            tree.get("params2", 0xFFFFFFFF), 0x3FF, 8, custom_flag
        )


def patch_digspot_item(bzs: dict, itemid: int, object_id_str: str, trapid: int, custom_flag: int = 0x3FF):
    id = int(object_id_str)
    digspot: dict | None = next(
        filter(
            lambda x: x["name"] == "Soil" and ((x["params1"] >> 4) & 0xFF) == id,
            bzs["OBJ "],
        ),
        None,
    )

    if digspot is None:
        raise Exception(f"No digspot with id '{id}' found to patch.")

    # Need to check this as itemid is the itemid of the fake item model when trapid > 0
    if trapid:
        trapbits = 254 - trapid
        # Unsets bit 0x000000F0 of params2
        digspot["params2"] = mask_shift_set(digspot["params2"], 0xF, 8, trapbits)
    else:
        # Makes sure the bit is set if not a trap
        digspot["params2"] = mask_shift_set(digspot["params2"], 0xF, 8, 0xF)

    # patch digspot to be the same as key piece digspots in all ways except it keeps it's initial sceneflag
    digspot["params1"] = (digspot["params1"] & 0xFF0) | 0xFF0B1004
    # Store the low 8 bits of the itemid in params2 bits 24-31 (ASM reads from offset
    # 0x12F). Bits 0-7 are preserved for vanilla dAcOsoil::init behaviour. Ids >= 256
    # set tag 2 in params2 bits 22-23 (see the boko patch / traps.rs); 3 = none.
    digspot["params2"] = mask_shift_set(digspot["params2"], 0xFF, 0x18, itemid & 0xFF)
    digspot["params2"] = mask_shift_set(
        digspot["params2"], 0x3, 22, 2 if itemid >= 256 else 3
    )

    # Encode Archipelago custom_flag into params2 bits 12-21 (10 bits)
    # Always write (even 0x3FF sentinel) so vanilla bits are overwritten
    # with a known value.  Rust reads these via (param2 >> 12) & 0x3FF.
    digspot["params2"] = mask_shift_set(
        digspot["params2"], 0x3FF, 12, custom_flag
    )


def patch_goddess_crest(bzs: dict, itemid: int, index: str, trapid: int, custom_flag: int = 0x3FF):
    crest: dict | None = next(filter(lambda x: x["name"] == "SwSB", bzs["OBJ "]), None)

    if crest is None:
        raise Exception(f"No goddess crest found to patch.")

    # Don't use fake itemid yet, this needs patching properly first
    if trapid:
        itemid = 34  # rupoor

    # Item ids are 9 bits wide. The low 8 bits stay in the original byte of each
    # field and the 9th bit lives in spare params2 bits 21-23 (crest rewards are
    # read by Rust, see handle_crest_hit_give_item / item_id_9bit).
    # Item IDs: params1[24:31] + params2[22], params1[16:23] + params2[21],
    # params2[24:31] + params2[23]
    #
    # IMPORTANT: Do NOT write Archipelago custom flags into params1 or params2.
    # The game engine reads low bits of params1 (and possibly params2) during
    # dAcOSwSwordBeam's init/update to control crest behaviour (hit detection,
    # reward-giving animation, etc.).  Overwriting those bits with custom flag
    # values corrupts the actor and prevents the game from ever reaching the
    # crest-hit hook at 0x7100930844.
    #
    # Custom flags for the three crest rewards are instead stored in the
    # CREST_CUSTOM_FLAGS Rust static (populated via init_global_variables)
    # and propagated to spawned item actors via the NEXT_CUSTOM_FLAG mechanism.
    hi_bit = (itemid >> 8) & 1
    low8 = itemid & 0xFF
    params2 = crest.get("params2", 0xFFFFFFFF)
    if index == "0":
        crest["params1"] = mask_shift_set(crest["params1"], 0xFF, 0x18, low8)
        params2 = mask_shift_set(params2, 0x1, 22, hi_bit)
    elif index == "1":
        crest["params1"] = mask_shift_set(crest["params1"], 0xFF, 0x10, low8)
        params2 = mask_shift_set(params2, 0x1, 21, hi_bit)
    elif index == "2":
        params2 = mask_shift_set(params2, 0xFF, 0x18, low8)
        params2 = mask_shift_set(params2, 0x1, 23, hi_bit)
    crest["params2"] = params2


def patch_squirrels(bzs: dict, itemid: int, object_id_str: str, trapid: int, custom_flag: int = 0x3FF):
    id = int(object_id_str, 16)

    squirrel_tag: dict | None = next(
        filter(lambda x: x["name"] == "MssbTag" and x["id"] == id, bzs["STAG"]), None
    )

    if squirrel_tag is None:
        raise Exception(f"No squirrel tag (MssbTag) found to patch.")

    # Don't use fake itemid yet, this needs patching properly first
    if trapid:
        itemid = 34  # rupoor

    # Item id: params2 bits 0-7 + bit 18 (9th bit), read by Rust (give_squirrel_item).
    # The 9th bit is always written so a vanilla 1 there is never misread.
    squirrel_tag["params2"] = mask_shift_set(squirrel_tag["params2"], 0xFF, 0, itemid & 0xFF)
    squirrel_tag["params2"] = mask_shift_set(
        squirrel_tag["params2"], 0x1, 18, (itemid >> 8) & 1
    )

    if custom_flag != 0x3FF:
        # AP mode: encode the 10-bit custom flag into bits 8-17 (same 3-part
        # encoding used by TgReact / tgreact_spawn_custom_item).
        squirrel_tag["params2"] = mask_shift_set(
            squirrel_tag["params2"], 0x3FF, 8, custom_flag
        )
    else:
        # Vanilla mode: encode the vanilla sceneflag into bits 8-15.
        squirrel_id_to_sceneflag = {
            0xFCC8: 88,  # 0xA 01
            0xFC9C: 89,  # 0xA 02
            0xFCA0: 90,  # 0xA 04
        }
        squirrel_tag["params2"] = mask_shift_set(
            squirrel_tag["params2"], 0xFF, 8, squirrel_id_to_sceneflag[id]
        )


def patch_tadtone_group(bzs: dict, itemid: int, groupid_str: str, trapid: int, custom_flag: int = 0x3FF):
    groupid = int(groupid_str, 0)
    clefs = filter(
        lambda x: x["name"] == "Clef" and ((x["params1"] >> 3) & 0x1F) == groupid,
        bzs["OBJ "],
    )

    # Don't use fake itemid yet, this needs patching properly first
    if trapid:
        itemid = 34  # rupoor

    # Item id is stored as the whole 9-bit value in the z rotation (u16).
    for clef in clefs:
        clef["anglez"] = mask_shift_set(clef["anglez"], 0xFFFF, 0, itemid)

        # Encode Archipelago custom_flag into params2 bits 8-17 (10 bits)
        if custom_flag != 0x3FF:
            clef["params2"] = mask_shift_set(
                clef.get("params2", 0xFFFFFFFF), 0x3FF, 8, custom_flag
            )


def patch_trial_gate(bzs: dict, itemid: int, trapid: int):
    trial_gate: dict | None = next(
        filter(lambda x: x["name"] == "WarpObj", bzs["OBJ "]), None
    )

    if trial_gate is None:
        raise Exception(f"No WarpObj found to patch.")

    # Don't use fake itemid yet, this needs patching properly first
    if trapid:
        itemid = 34  # rupoor

    # Item id: params1 bits 23-31 (9 bits). Read by Rust (archipelago_silent_realm_tear_fix).
    trial_gate["params1"] = mask_shift_set(trial_gate["params1"], 0x1FF, 0x17, itemid)


def patch_tgreact(
    bzs: dict, itemid: int, object_id_str: str, trapid: int, custom_flag: int
):
    id = int(object_id_str, 16)

    tgreact: dict | None = next(
        filter(lambda x: x["name"] == "TgReact" and x["id"] == id, bzs["SOBJ"]), None
    )

    if tgreact is None:
        raise Exception(
            f"No tag reaction (TgReact) with id '{hex(id)}' found to patch."
        )

    # Need to check this as itemid is the itemid of the fake item model when trapid > 0
    if trapid:
        trapbits = 254 - trapid
        # Unsets bit 0x00780000 of params2
        tgreact["params2"] = mask_shift_set(tgreact["params2"], 0xF, 19, trapbits)
    else:
        # Makes sure the bit is set if not a trap
        tgreact["params2"] = mask_shift_set(tgreact["params2"], 0xF, 19, 0xF)

    # Move vanilla velocity type indicator to free space in params2
    if (tgreact["params1"] >> 8) & 0xFF == 0:
        tgreact["params2"] = mask_shift_set(tgreact["params2"], 1, 18, 1)
    else:
        tgreact["params2"] = mask_shift_set(tgreact["params2"], 1, 18, 0)

    # THEN, patch item id: params1 bits 8-15 + params2 bit 23 (9th bit, always
    # written; read by Rust, see item_id_9bit)
    tgreact["params1"] = mask_shift_set(tgreact["params1"], 0xFF, 8, itemid & 0xFF)
    tgreact["params2"] = mask_shift_set(tgreact["params2"], 0x1, 23, (itemid >> 8) & 1)

    if custom_flag != -1:
        tgreact["params2"] = mask_shift_set(tgreact["params2"], 0x3FF, 8, custom_flag)
    else:
        tgreact["params2"] = mask_shift_set(tgreact["params2"], 0x3FF, 8, 0x3FF)


def patch_pot(
    bzs: dict, itemid: int, object_id_str: str, trapid: int, custom_flag: int
):
    """Pot sanity (Tubo, dAcOtubo_c). Read by pot_spawn_custom_item in item.rs.

    A pot's param1 has no free bits, so everything goes in params2 (the top byte
    keeps the vanilla drop id and bits 0-23 are 0xFFFFFF in every vanilla pot):
      bits 0-7   item id (low 8 bits), bit 23 = 9th bit
      bits 8-17  custom flag (0x3FF = unpatched, vanilla drop)
      bit 18     velocity flag (item pops out of the pot)
      bits 19-22 trap id (0xF = not a trap)
    """
    id = int(object_id_str, 16)

    pot: dict | None = next(
        filter(lambda x: x["name"] == "Tubo" and x["id"] == id, bzs["OBJ "]), None
    )

    if pot is None:
        raise Exception(f"No pot (Tubo) with id '{hex(id)}' found to patch.")

    # Without a custom flag the check can't be tracked, so keep the vanilla drop
    if custom_flag == -1 or (custom_flag & 0x3FF) == 0x3FF:
        return

    # The pot's params2 only has room for the low 10 bits of the flag. The game
    # treats every pot flag as an extended (group 1, bit 10) flag, so a group 0
    # flag here would make the pot set a different location's flag.
    if not (custom_flag & 0x400):
        raise Exception(
            f"Pot '{hex(id)}' was given group 0 custom flag {custom_flag:#x}; "
            "pots must use group 1 flags (bit 10 set)."
        )
    custom_flag &= 0x3FF

    # Need to check this as itemid is the itemid of the fake item model when trapid > 0
    if trapid:
        trapbits = 254 - trapid
        pot["params2"] = mask_shift_set(pot["params2"], 0xF, 19, trapbits)
    else:
        pot["params2"] = mask_shift_set(pot["params2"], 0xF, 19, 0xF)

    # Item pops out of the pot
    pot["params2"] = mask_shift_set(pot["params2"], 1, 18, 1)

    pot["params2"] = mask_shift_set(pot["params2"], 0xFF, 0, itemid & 0xFF)
    pot["params2"] = mask_shift_set(pot["params2"], 0x1, 23, (itemid >> 8) & 1)
    pot["params2"] = mask_shift_set(pot["params2"], 0x3FF, 8, custom_flag)


def _f32_bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def patch_pumpkin(
    bzs: dict, itemid: int, object_id_str: str, trapid: int, custom_flag: int
) -> tuple[int, int, int, int] | None:
    """Pumpkin shuffle (Pumpkin, dAcPumpkin_c).

    Unlike pots, nothing is stored in the pumpkin's params: at runtime the
    actor's params1 and the low 16 bits of params2 are wiped by shared actor
    setup code, so anything written there never reaches the break routine. The
    BZS object is left untouched and this returns a table entry instead, keyed
    by the pumpkin's position (X/Z as raw f32 bits, which survive actor
    creation unchanged). The entries are written to the PUMPKIN_TABLE_* config
    block by init_global_variables and looked up by pot_spawn_custom_item in
    item.rs when the pumpkin is broken.

    Returns (px_bits, pz_bits, item_word, flag), or None to keep the vanilla
    drop. item_word: bits 0-8 item id, bits 9-12 trap nibble (0xF = not a
    trap). flag: the low 10 bits of the group 1 custom flag.
    """
    id = int(object_id_str, 16)

    pumpkin: dict | None = next(
        filter(lambda x: x["name"] == "Pumpkin" and x["id"] == id, bzs["OBJ "]), None
    )

    if pumpkin is None:
        raise Exception(f"No pumpkin (Pumpkin) with id '{hex(id)}' found to patch.")

    # Without a custom flag the check can't be tracked, so keep the vanilla drop
    if custom_flag == -1 or (custom_flag & 0x3FF) == 0x3FF:
        return None

    # Like pots, the game treats every pumpkin flag as an extended (group 1,
    # bit 10) flag; only the low 10 bits are stored.
    if not (custom_flag & 0x400):
        raise Exception(
            f"Pumpkin '{hex(id)}' was given group 0 custom flag {custom_flag:#x}; "
            "pumpkins must use group 1 flags (bit 10 set)."
        )
    custom_flag &= 0x3FF

    # Need to check this as itemid is the itemid of the fake item model when trapid > 0
    trap_nibble = (254 - trapid) if trapid else 0xF
    if not (0 <= trap_nibble <= 0xF):
        raise Exception(f"Pumpkin '{hex(id)}' has invalid trap id {trapid}.")
    if not (0 <= itemid <= 0x1FF):
        raise Exception(f"Pumpkin '{hex(id)}' has item id {itemid} that doesn't fit in 9 bits.")

    item_word = (itemid & 0x1FF) | (trap_nibble << 9)
    return (_f32_bits(pumpkin["posx"]), _f32_bits(pumpkin["posz"]), item_word, custom_flag)


def patch_big_pot(
    bzs: dict, itemid: int, object_id_str: str, trapid: int, custom_flag: int
) -> tuple[int, int, int, int] | None:
    """Big pot shuffle (BigTubo, dAcOTuboBig_c; actor profile TuboBig).

    All 15 big pots have identical params (params1 0xFFFFFFF0, params2
    0xFFFFFFFF: no scene flag, no drop id), so there is nothing per-pot to
    write into the BZS object. Like pumpkins, this leaves the object untouched
    and returns a table entry keyed by the pot's position (X/Z as raw f32
    bits). The entries are written to the BIG_POT_TABLE_* config block by
    init_global_variables and looked up by pot_spawn_custom_item in item.rs.

    Returns (px_bits, pz_bits, item_word, flag), or None to keep the vanilla
    behavior (no drop). item_word: bits 0-8 item id, bits 9-12 trap nibble
    (0xF = not a trap). flag: the low 10 bits of the group 1 custom flag.
    """
    id = int(object_id_str, 16)

    big_pot: dict | None = next(
        filter(lambda x: x["name"] == "BigTubo" and x["id"] == id, bzs["OBJ "]), None
    )

    if big_pot is None:
        raise Exception(f"No big pot (BigTubo) with id '{hex(id)}' found to patch.")

    # Without a custom flag the check can't be tracked, so keep the vanilla drop
    if custom_flag == -1 or (custom_flag & 0x3FF) == 0x3FF:
        return None

    # Like pots, the game treats every big pot flag as an extended (group 1,
    # bit 10) flag; only the low 10 bits are stored.
    if not (custom_flag & 0x400):
        raise Exception(
            f"Big pot '{hex(id)}' was given group 0 custom flag {custom_flag:#x}; "
            "big pots must use group 1 flags (bit 10 set)."
        )
    custom_flag &= 0x3FF

    trap_nibble = (254 - trapid) if trapid else 0xF
    if not (0 <= trap_nibble <= 0xF):
        raise Exception(f"Big pot '{hex(id)}' has invalid trap id {trapid}.")
    if not (0 <= itemid <= 0x1FF):
        raise Exception(f"Big pot '{hex(id)}' has item id {itemid} that doesn't fit in 9 bits.")

    item_word = (itemid & 0x1FF) | (trap_nibble << 9)
    return (_f32_bits(big_pot["posx"]), _f32_bits(big_pot["posz"]), item_word, custom_flag)


def patch_barrel(
    bzs: dict, itemid: int, object_id_str: str, trapid: int, custom_flag: int
) -> tuple[int, int, int, int] | None:
    """Barrel shuffle (Barrel, dAcOBarrel_c; actor profile OBJ_BARREL, 0x209).

    Barrel params2 is 0xFFFFFF in the low 24 bits for every barrel and the drop
    mode lives in params1, so there is nothing usable to write into the BZS
    object. Like pumpkins and big pots, this leaves the object untouched and
    returns a table entry keyed by the barrel's position (X/Z as raw f32 bits).
    The entries are written to the BARREL_TABLE_* config block by
    init_global_variables and looked up by pot_spawn_custom_item in item.rs.

    The same physical barrel can appear on several layers of a room with the
    same position (e.g. F001r and F303 layers 2/3/4); those share ONE table
    entry and one location, so only one of them has to be passed here.

    Returns (px_bits, pz_bits, item_word, flag), or None to keep the vanilla
    behavior. item_word: bits 0-8 item id, bits 9-12 trap nibble (0xF = not a
    trap). flag: the low 10 bits of the group 1 custom flag.
    """
    id = int(object_id_str, 16)

    barrel: dict | None = next(
        filter(lambda x: x["name"] == "Barrel" and x["id"] == id, bzs["OBJ "]), None
    )

    if barrel is None:
        raise Exception(f"No barrel (Barrel) with id '{hex(id)}' found to patch.")

    # Without a custom flag the check can't be tracked, so keep the vanilla behavior
    if custom_flag == -1 or (custom_flag & 0x3FF) == 0x3FF:
        return None

    # Like pots, the game treats every barrel flag as an extended (group 1,
    # bit 10) flag; only the low 10 bits are stored.
    if not (custom_flag & 0x400):
        raise Exception(
            f"Barrel '{hex(id)}' was given group 0 custom flag {custom_flag:#x}; "
            "barrels must use group 1 flags (bit 10 set)."
        )
    custom_flag &= 0x3FF

    trap_nibble = (254 - trapid) if trapid else 0xF
    if not (0 <= trap_nibble <= 0xF):
        raise Exception(f"Barrel '{hex(id)}' has invalid trap id {trapid}.")
    if not (0 <= itemid <= 0x1FF):
        raise Exception(f"Barrel '{hex(id)}' has item id {itemid} that doesn't fit in 9 bits.")

    item_word = (itemid & 0x1FF) | (trap_nibble << 9)
    return (_f32_bits(barrel["posx"]), _f32_bits(barrel["posz"]), item_word, custom_flag)


def patch_academy_bell(bzs: dict, itemid: int, trapid: int, custom_flag: int = 0x3FF):

    academy_bell: dict | None = next(
        filter(lambda x: x["name"] == "Bell", bzs["OBJ "]), None
    )

    if academy_bell is None:
        raise Exception(f"No Bell found to patch.")

    # Don't use fake itemid yet, this needs patching properly first
    if trapid:
        itemid = 34  # rupoor

    # Item id: params1 bits 0-7 + params2 bit 18 (9th bit, always written; read
    # by Rust, see item_id_9bit)
    academy_bell["params1"] = mask_shift_set(academy_bell["params1"], 0xFF, 0, itemid & 0xFF)
    academy_bell["params2"] = mask_shift_set(
        academy_bell.get("params2", 0xFFFFFFFF), 0x1, 18, (itemid >> 8) & 1
    )

    # Encode Archipelago custom_flag into params2 bits 8-17 (10 bits)
    if custom_flag != 0x3FF:
        academy_bell["params2"] = mask_shift_set(
            academy_bell.get("params2", 0xFFFFFFFF), 0x3FF, 8, custom_flag
        )


def patch_hrphint(bzs: dict, itemid: int, object_id_str: str, trapid: int, custom_flag: int = 0x3FF):
    id = int(object_id_str, 16)

    hrphint: dict | None = next(
        filter(lambda x: x["name"] == "HrpHint" and x["id"] == id, bzs["OBJ "]), None
    )

    if hrphint is None:
        raise Exception(
            f"No gossip stone (HrpHint) with id '{hex(id)}' found to patch."
        )

    # Need to check this as itemid is the itemid of the fake item model when trapid > 0
    if trapid:
        trapbits = 254 - trapid
        # Unsets bit 0x000000F0 of params2
        hrphint["params2"] = mask_shift_set(hrphint["params2"], 0xF, 0, trapbits)
    else:
        # Makes sure the bit is set if not a trap
        hrphint["params2"] = mask_shift_set(hrphint["params2"], 0xF, 0, 0xF)

    # Item id: params2 bits 4-11 + bit 22 (9th bit, always written; read by Rust,
    # see item_id_9bit)
    hrphint["params2"] = mask_shift_set(hrphint["params2"], 0xFF, 4, itemid & 0xFF)
    hrphint["params2"] = mask_shift_set(hrphint["params2"], 0x1, 22, (itemid >> 8) & 1)

    # Encode AP custom_flag (10 bits) into bits 12-21.
    # Sentinel 0x3FF means no AP flag (vanilla sceneflag path in Rust).
    hrphint["params2"] = mask_shift_set(hrphint["params2"], 0x3FF, 12, custom_flag)


def object_add(bzs: dict, object_add: dict, nextid: int) -> int:
    layer = object_add.get("layer", None)
    object_type: str = object_add["objtype"].ljust(4)
    obj: dict = object_add["object"]
    return_nextid_increment = 0

    # populate with default object as a base
    if object_type in ["SOBS", "SOBJ", "STAS", "STAG", "SNDT"]:
        new_object = DEFAULT_SOBJ.copy()
    elif object_type in ["OBJS", "OBJ ", "DOOR"]:
        new_object = DEFAULT_OBJ.copy()
    elif object_type == "SCEN":
        new_object = DEFAULT_SCEN.copy()
    elif object_type == "PLY ":
        new_object = DEFAULT_PLY.copy()
    elif object_type == "AREA":
        new_object = DEFAULT_AREA.copy()
    else:
        raise Exception(
            f"Cannot add object with unknown objtype: {object_type}.\nObject: {obj}\nPatch: {object_add}"
        )

    # check index to verify new index is the next available index
    if "index" in obj:
        if layer is None:
            object_list = bzs.get(object_type, [])
        else:
            object_list = bzs["LAY "][f"l{layer}"].get(object_type, [])

        if len(object_list) != obj["index"]:
            raise Exception(
                f"Cannot use wrong index on added object: {json.dumps(object_add)}"
            )

    # Assign the name first so additional properties can be listed in any order
    if obj_name := obj.get("name"):
        new_object["name"] = obj_name

    # populate provided properties
    for prop, value in obj.items():
        if prop in new_object:
            new_object[prop] = value

            if prop == "id":
                new_object["id"] = (new_object["id"] & ~0x3FF) | (
                    nextid + return_nextid_increment
                )
                return_nextid_increment += 1
        # Allow creating new objects that *need* a known id
        elif prop == "hardcoded_id":
            new_object["id"] = value
        else:
            patch_additional_properties(obj=new_object, prop=prop, value=value)

    if new_object.get("id") == 0:
        new_object["id"] = nextid + return_nextid_increment
        return_nextid_increment += 1

    # Prevent ammo pots getting ids that collide with viewclip indexes
    if new_object.get("name") == "Tubo":
        id = new_object.get("id", -1)

        if id != -1 and id < 0xF000:
            new_object["id"] = id | 0xF000

    # creates list for object types if don't already exist in bzs
    if layer is None:
        if object_type not in bzs:  # check
            bzs[object_type] = []

        object_list = bzs[object_type]
    else:
        if object_type not in bzs["LAY "][f"l{layer}"]:
            bzs["LAY "][f"l{layer}"][object_type] = []

        object_list = bzs["LAY "][f"l{layer}"][object_type]

    # add object name to objn if it's some type of actor
    if object_type in STAGE_OBJECT_NAMES:
        # Add layer if it doesn't already exist
        if not bzs["LAY "].get(f"l{layer}"):
            bzs["LAY "][f"l{layer}"] = []

        if not "OBJN" in bzs["LAY "][f"l{layer}"]:
            bzs["LAY "][f"l{layer}"]["OBJN"] = []

        objn = bzs["LAY "][f"l{layer}"]["OBJN"]

        if (obj_name := obj.get("name")) is None:
            raise Exception(
                f"Cannot add an object without a name field (actor name).\nObject: {obj}\nPatch: {object_add}"
            )

        if not obj_name in objn:
            objn.append(obj_name)

    object_list.append(new_object)
    return return_nextid_increment


def object_handle_list_props(object: dict, ids: list, current_id_index: int) -> dict:
    new_object = object.copy()
    new_object["ids"] = []
    new_object["id"] = ids[current_id_index]

    # Allows batch handling of objects across multiple layers
    if len(layers := object.get("layers", [])) > 0:
        if not isinstance(layers, list):
            raise Exception(
                f"Cannot handle object as property 'layers' is not a list: {object}."
            )

        if len(layers) != len(ids):
            raise Exception(
                f"Cannot handle object as number of layers is different to number of ids: {object}."
            )

        new_object["layers"] = []
        new_object["layer"] = layers[current_id_index]

    # Allows batch handling of objects across multiple rooms
    if len(rooms := object.get("rooms", [])) > 0:
        assert isinstance(rooms, list)

        if len(rooms) != len(ids):
            raise Exception(
                f"Cannot handle object as number of rooms is different to number of ids: {object}."
            )

        new_object["rooms"] = []
        new_object["room"] = rooms[current_id_index]

    # Allows batch handling of objects of different types
    if len(objtypes := object.get("objtypes", [])) > 0:
        assert isinstance(objtypes, list)

        if len(objtypes) != len(ids):
            raise Exception(
                f"Cannot handle object as number of rooms is different to number of ids: {object}."
            )

        new_object["objtypes"] = []
        new_object["objtype"] = objtypes[current_id_index]

    if not isinstance(new_object["layer"], int):
        raise Exception(
            f"Cannot handle object with a non-integer layer ({new_object['layer']}).\nObject: {new_object}\nPatch: {object}"
        )

    if not isinstance(new_object["room"], int):
        raise Exception(
            f"Cannot handle object with a non-integer room ({new_object['room']}).\nObject: {new_object}\nPatch: {object}"
        )

    if not isinstance(new_object["objtype"], str):
        raise Exception(
            f"Cannot handle object with a non-string objtype ({new_object['objtype']}).\nObject: {new_object}\nPatch: {object}"
        )

    return new_object


def object_delete(bzs: dict, object_delete: dict):
    ids: list = object_delete.get("ids", [])
    start_obj_id = object_delete.get("startid")
    end_obj_id = object_delete.get("endid")

    if id := object_delete.get("id"):
        ids.append(id)

    if start_obj_id and end_obj_id:
        if start_obj_id > end_obj_id:
            raise Exception(
                f"Cannot perform objdelete because startid ({start_obj_id}) is bigger than endid ({end_obj_id})."
            )

        for obj_id in range(start_obj_id, end_obj_id + 1):
            ids.append(obj_id)

    for id_index in range(len(ids)):
        object_to_delete = object_handle_list_props(object_delete, ids, id_index)
        obj = get_entry_from_bzs(bzs=bzs, object_def=object_to_delete, remove=True)

        if obj is None:
            raise Exception(
                f"Cannot find object:\nObject {obj}\nPatch: {object_delete}"
            )


def object_patch(bzs: dict, object_patch: dict):
    obj = get_entry_from_bzs(bzs=bzs, object_def=object_patch)

    if obj is not None:
        for prop, value in object_patch["object"].items():
            if prop in obj:
                obj[prop] = value
            else:
                patch_additional_properties(obj=obj, prop=prop, value=value)


def object_move(bzs: dict, object_move: dict, nextid: int) -> int:
    ids: list = object_move.get("ids", [])
    start_obj_id = object_move.get("startid")
    end_obj_id = object_move.get("endid")

    if id := object_move.get("id"):
        ids.append(id)

    if start_obj_id and end_obj_id:
        if start_obj_id > end_obj_id:
            raise Exception(
                f"Cannot perform objmove because startid ({start_obj_id}) is bigger than endid ({end_obj_id})."
            )

        for obj_id in range(start_obj_id, end_obj_id + 1):
            ids.append(obj_id)

    destination_layer = object_move["destlayer"]
    return_nextid_increment = 0

    for id_index in range(len(ids)):
        object_to_move = object_handle_list_props(object_move, ids, id_index)

        obj = get_entry_from_bzs(bzs=bzs, object_def=object_to_move, remove=True)

        if obj is None:
            raise Exception(
                f"Cannot find object to move: {object_to_move}.\nPatch: {object_move}"
            )

        object_type = object_to_move["objtype"].ljust(4)

        # Allow moving objects that *need* a specific id
        if hardcoded_id := object_move.get("hardcoded_id"):
            obj["id"] = hardcoded_id + id_index
        else:
            obj["id"] = (obj["id"] & ~0x3FF) | nextid
            return_nextid_increment += 1
            nextid += 1

        if not object_type in bzs["LAY "][f"l{destination_layer}"]:
            bzs["LAY "][f"l{destination_layer}"][object_type] = []

        bzs["LAY "][f"l{destination_layer}"][object_type].append(obj)

        if not "OBJN" in bzs["LAY "][f"l{destination_layer}"]:
            bzs["LAY "][f"l{destination_layer}"]["OBJN"] = []

        objn = bzs["LAY "][f"l{destination_layer}"]["OBJN"]

        if not obj["name"] in objn:
            objn.append(obj["name"])

    return return_nextid_increment


def pathadd(bzs: dict, path: dict):
    next_pnt = len(bzs["PNT "])

    new_path = DEFAULT_PATH.copy()
    new_path["pnt_start_idx"] = next_pnt
    new_path["pnt_total_count"] = len(path["pnts"])
    bzs["PATH"].append(new_path)

    pnts_to_add = path["pnts"]

    for pnt in pnts_to_add:
        new_pnt = DEFAULT_PNT.copy()

        for key, val in pnt.items():
            if key in new_pnt:
                new_pnt[key] = val

        bzs["PNT "].append(new_pnt)


def layer_override(bzs: dict, patch: dict):
    layer_override = [
        {
            "story_flag": override["story_flag"],
            "night": override["night"],
            "layer": override["layer"],
        }
        for override in patch["override"]
    ]

    bzs["LYSE"] = layer_override


def arcn_add(bzs: dict, patch: dict):
    arcn: list[str] | None = patch.get("arcn", None)

    if arcn == None:
        raise Exception(
            f"Could not find 'arcn' from patch. Did you typo the 'arcn' field?\nPatch: {patch}"
        )

    arcn_set: set[str] = set(bzs.get("ARCN", []))
    arcn_set |= set(arcn)
    bzs["ARCN"] = list(arcn_set)
    # print(patch["layer"], patch["room"], bzs["ARCN"])


class StagePatchHandler:
    # Stage names where goddess chests reside → scene index in the 26-scene array.
    # Goddess chests only exist in Skyloft (F000/F004r → scene 0)
    # and The Sky / Thunderhead (F020/F023 → scene 21).
    GODDESS_STAGE_TO_SCENE: dict[str, int] = {
        "F000": 0,
        "F004r": 0,
        "F020": 21,
        "F023": 21,
    }

    def __init__(self, output_path: Path, other_mods: list[str] = []):
        self.base_output_path = output_path
        self.stage_output_path = self.base_output_path / "Stage"
        self.stage_patches: dict[str, list[dict]] = yaml_load(STAGE_PATCHES_PATH)  # type: ignore
        self.check_patches: dict[str, list[tuple]] = defaultdict(list)
        self.other_mods = other_mods
        # Populated during handle_stage_patches(): custom_flag → [scene_index, chestflag]
        # Used by the AP client to detect goddess chest completions via FA.tboxflags[scene][chestflag//8] bit (chestflag%8)
        self.goddess_chest_scene_flags: dict[int, list[int]] = {}
        # Crest custom flags: [flag_for_index_0, flag_for_index_1, flag_for_index_2]
        # Populated during handle_stage_patches() when SwSB check patches are processed.
        # Written to the CREST_CUSTOM_FLAGS Rust static via init_global_variables.
        self.crest_custom_flags: list[int] = [0x3FF, 0x3FF, 0x3FF]
        # Decoupled Goddess Cubes: story flag -> (item id, AP custom flag).
        # Written to the GODDESS_CUBE_* Rust statics via init_global_variables;
        # the game hands out the item when the cube's story flag gets set.
        self.goddess_cube_items: dict[int, tuple[int, int]] = {}
        # Bird Statues Give Items: statue index (BIRD_STATUE_LOCATION_NAMES) ->
        # (item id, AP custom flag). Written to the BIRD_STATUE_* Rust statics via
        # init_global_variables; the game hands out the item when the statue is touched.
        self.bird_statue_items: dict[int, tuple[int, int]] = {}
        # Pumpkin Shuffle: (px_bits, pz_bits, item_word, flag) per patched pumpkin,
        # keyed in the game by the pumpkin's position. Written to the PUMPKIN_TABLE_*
        # config block via init_global_variables (see patch_pumpkin).
        self.pumpkin_entries: list[tuple[int, int, int, int]] = []
        # Big Pot Shuffle: (px_bits, pz_bits, item_word, flag) per patched big pot,
        # keyed in the game by position. Written to the BIG_POT_TABLE_* config block
        # via init_global_variables (see patch_big_pot). Max 16 entries.
        self.big_pot_entries: list[tuple[int, int, int, int]] = []
        # Barrel Shuffle: (px_bits, pz_bits, item_word, flag) per patched barrel,
        # keyed in the game by position. Written to the BARREL_TABLE_* config block
        # via init_global_variables (see patch_barrel). Max 192 entries.
        self.barrel_entries: list[tuple[int, int, int, int]] = []
        # Global symbol initializers consumed by ASM global init.
        # Format: {"type": "symbol", "symbol": <name>, "value": <int>}.
        self.global_patches: list[dict] = []
        # Story flag that gates the spawning of every Goddess Chest, or None to
        # leave the vanilla per-chest gate (the chest's Goddess Cube) untouched.
        # Set by determine_check_patches based on the Goddess Chest Unlock setting.
        self.goddess_chest_spawn_storyflag: int | None = None

    def add_goddess_cube_item(self, storyflag: int, itemid: int, custom_flag: int):
        self.goddess_cube_items[storyflag] = (itemid, custom_flag)

    def add_bird_statue_item(self, statue_index: int, itemid: int, custom_flag: int):
        self.bird_statue_items[statue_index] = (itemid, custom_flag)

    def get_bird_statue_arrays(self) -> tuple[list[int], list[int]]:
        # (custom flags, item ids), one entry per statue in BIRD_STATUE_LOCATION_NAMES
        # order. Unused slots are 0x3FF (no custom flag), which the game skips.
        flags = [0x3FF] * len(BIRD_STATUE_LOCATION_NAMES)
        items = [0] * len(BIRD_STATUE_LOCATION_NAMES)
        for index, (itemid, custom_flag) in self.bird_statue_items.items():
            items[index], flags[index] = itemid, custom_flag
        return flags, items

    def get_goddess_cube_arrays(self) -> tuple[list[int], list[int]]:
        # (custom flags, item ids), one entry per cube in GODDESS_CUBE_STORYFLAGS
        # order. Unused slots are 0x3FF (no custom flag), which the game skips.
        flags = [0x3FF] * len(GODDESS_CUBE_STORYFLAGS)
        items = [0] * len(GODDESS_CUBE_STORYFLAGS)
        for index, storyflag in enumerate(GODDESS_CUBE_STORYFLAGS):
            if storyflag in self.goddess_cube_items:
                items[index], flags[index] = self.goddess_cube_items[storyflag]
        return flags, items

    def handle_stage_patches(self, onlyif_handler: ConditionalPatchHandler):
        for stage in self.stage_patches:
            for patch in self.stage_patches[stage]:
                if not patch.get("type"):
                    raise Exception(f"Patch doesn't have a 'type' field: {patch}")
                if patch["type"] not in VALID_STAGE_PATCH_TYPES:
                    exception_str = (
                        f"Invalid patch with type '{patch['type']}' found.\n"
                    )
                    exception_str += f"Valid patch types: {VALID_STAGE_PATCH_TYPES}\n"
                    exception_str += f"Patch: {patch}"
                    raise Exception(exception_str)

        # Pre-emptively remove unecessary patches since we can't pass
        # the onlyif_handler to other worker processes
        print("Removing unecessary patches")
        self.remove_unnecessary_patches(onlyif_handler)

        start_stage_patching_time = time.process_time()

        bzs_u8 = U8File.get_parsed_U8_from_path(BZS_TEMPLATE_PATH)
        bzs_cache_stage_paths = list(CACHE_BZS_PATH.glob("*"))

        for current_stage_num, bzs_cache_path in enumerate(bzs_cache_stage_paths):
            stage_name = bzs_cache_path.name
            patches = self.stage_patches.get(stage_name, [])
            object_patches = []

            print(f"Patching Stage: {stage_name}")

            # handle layer overrides
            layer_override_patches = list(
                filter(lambda patch: patch["type"] == "layeroverride", patches)
            )

            if len(layer_override_patches) > 1:
                raise Exception(
                    f"Multiple layeroverrides found. {len(layer_override_patches)} layer overrides found for stage {stage_name}, expected 1."
                )

            stage_bzs_bytes = (bzs_cache_path / "stage.bzs").read_bytes()
            stage_bzs = parse_bzs(stage_bzs_bytes)

            if len(layer_override_patches) == 1:
                layer_override(bzs=stage_bzs, patch=layer_override_patches[0])

            bzs_u8.add_file_data(f"dat/{stage_name}_stage.bzs", build_bzs(stage_bzs))

            for obj_patch in filter(
                lambda patch: patch["type"]
                in [
                    "objadd",
                    "objdelete",
                    "objpatch",
                    "objmove",
                    "pathadd",
                    "arcnadd",
                ],
                patches,
            ):
                object_patches.append(obj_patch)

            for room_bzs_path in (CACHE_BZS_PATH / stage_name).glob("room*"):
                roomid = int(room_bzs_path.name.split(".bzs")[0][5:])

                obj_patches_for_current_room = list(
                    filter(
                        lambda patch: patch.get("room") == roomid,
                        object_patches,
                    )
                )
                check_patches_for_current_room = list(
                    filter(
                        lambda patch: patch[0] == roomid,
                        self.check_patches[stage_name],
                    )
                )

                room_bzs_bytes = room_bzs_path.read_bytes()
                room_bzs = parse_bzs(room_bzs_bytes)

                # Inject AP item OARCs into every room's layer 0 for every
                # stage except explicitly excluded stages (e.g. F402).
                #
                # This guarantees Archipelago network items always have their
                # models available regardless of whether the room has local
                # randomized check patches.
                #
                # IMPORTANT: the room's in-game ARCN slot table has a limited
                # capacity (see _SKIP_AP_OARC_STAGES above - exceeding it can
                # even crash on some stages). Building the final list from a
                # Python set and converting back with list() gives a
                # hash-randomized order that varies between generations, so
                # if a room's total OARC count ever exceeds that capacity,
                # WHICH oarcs get silently dropped becomes non-deterministic -
                # this is why the Archipelago Item model sometimes displayed
                # correctly and sometimes fell back to the default icon.
                # Sorting keeps the result stable across runs, and puts
                # ArchipelagoItem / ArchipelagoItem2 (both starting with 'A')
                # near the front of the list, ahead of the many vanilla
                # "Get..." oarc names, so they're the last to be dropped if
                # a room's OARC count ever does exceed the engine's limit.
                if stage_name not in _SKIP_AP_OARC_STAGES:
                    l0 = room_bzs["LAY "]["l0"]
                    l0_arcn = set(l0.get("ARCN", []))
                    l0_arcn |= AP_ITEM_OARC_NAMES
                    l0["ARCN"] = sorted(l0_arcn)

                nextid = get_highest_object_id(bzs=room_bzs) + 1

                for patch in obj_patches_for_current_room:
                    patch_type = patch.get("type", None)
                    if patch_type == None:
                        raise Exception(
                            f"Patch is missing a 'type' field and cannot be processed.\nPatch: {patch}"
                        )
                    elif type(patch_type) != str:
                        raise Exception(
                            f"Patch field 'type' is not a string. Found '{type(patch_type)}' instead.\nPatch{patch}"
                        )

                    if patch_type == "objadd":
                        nextid += object_add(
                            bzs=room_bzs,
                            object_add=patch,
                            nextid=nextid,
                        )
                    elif patch_type == "objdelete":
                        object_delete(bzs=room_bzs, object_delete=patch)
                    elif patch_type == "objpatch":
                        object_patch(bzs=room_bzs, object_patch=patch)
                    elif patch_type == "objmove":
                        nextid += object_move(
                            bzs=room_bzs,
                            object_move=patch,
                            nextid=nextid,
                        )
                    elif patch_type == "pathadd":
                        pathadd(bzs=room_bzs, path=patch)
                    elif patch_type == "arcnadd":
                        arcn_add(
                            bzs=room_bzs["LAY "][f"l{patch['layer']}"], patch=patch
                        )
                    else:
                        raise Exception(
                            f"Unsupported patch type '{patch_type}' found.\nPatch: {patch}"
                        )

                if self.goddess_chest_spawn_storyflag is not None:
                    for layer_bzs in room_bzs["LAY "].values():
                        patch_goddess_chest_spawn_flag(
                            layer_bzs, self.goddess_chest_spawn_storyflag
                        )

                for (
                    room,
                    object_name,
                    layer,
                    objectid,
                    itemid,
                    trapid,
                    custom_flag,
                    original_itemid,
                    tbox_subtype,
                ) in check_patches_for_current_room:
                    if object_name == "TBox":
                        goddess_chestflag = patch_tbox(
                            room_bzs["LAY "][f"l{layer}"],
                            itemid,
                            objectid,
                            trapid,
                            tbox_subtype,
                            custom_flag,
                        )
                        # If this was a goddess chest, record the chestflag
                        # so the AP client can poll FA.tboxflags for completion.
                        if goddess_chestflag >= 0 and custom_flag != 0x3FF:
                            scene_index = self.GODDESS_STAGE_TO_SCENE.get(stage_name)
                            if scene_index is not None:
                                self.goddess_chest_scene_flags[custom_flag] = [
                                    scene_index, goddess_chestflag
                                ]
                    elif object_name == "Item":
                        patch_freestanding_item(
                            room_bzs["LAY "][f"l{layer}"],
                            itemid,
                            objectid,
                            trapid,
                            custom_flag,
                            original_itemid,
                        )
                    elif object_name == "AncJwls":
                        patch_dusk_relic(
                            room_bzs["LAY "][f"l{layer}"],
                            itemid,
                            objectid,
                            trapid,
                            custom_flag,
                            original_itemid,
                        )
                    elif object_name == "NpcKyuE":
                        patch_bucha(
                            room_bzs["LAY "][f"l{layer}"],
                            itemid,
                            objectid,
                            trapid,
                            custom_flag,
                        )
                    elif object_name == "chest":
                        patch_closet(
                            room_bzs["LAY "][f"l{layer}"],
                            itemid,
                            objectid,
                            trapid,
                            room,
                            stage_name,
                            custom_flag,
                        )
                    elif object_name == "EBc":
                        patch_ac_key_boko(
                            room_bzs["LAY "][f"l{layer}"],
                            itemid,
                            objectid,
                            trapid,
                            custom_flag,
                        )
                    elif object_name == "HeartCo":
                        patch_heart_container(
                            room_bzs["LAY "][f"l{layer}"],
                            itemid,
                            trapid,
                            custom_flag,
                        )
                    elif object_name == "Chandel":
                        patch_chandelier_item(
                            room_bzs["LAY "][f"l{layer}"],
                            itemid,
                            trapid,
                            custom_flag,
                        )
                    elif object_name == "Soil":
                        patch_digspot_item(
                            room_bzs["LAY "][f"l{layer}"],
                            itemid,
                            objectid,
                            trapid,
                            custom_flag,
                        )
                    elif object_name == "SwSB":
                        patch_goddess_crest(
                            room_bzs["LAY "][f"l{layer}"],
                            itemid,
                            objectid,
                            trapid,
                            custom_flag,
                        )
                        # Store crest custom flags for the CREST_CUSTOM_FLAGS
                        # Rust static (populated via init_global_variables).
                        idx = int(objectid)
                        print(f"[StagePatch] CREST DEBUG: SwSB objectid={objectid} idx={idx} custom_flag=0x{custom_flag:03X} itemid={itemid}")
                        if 0 <= idx <= 2 and custom_flag != 0x3FF:
                            self.crest_custom_flags[idx] = custom_flag
                    elif object_name == "MssbTag":
                        patch_squirrels(
                            room_bzs["LAY "][f"l{layer}"],
                            itemid,
                            objectid,
                            trapid,
                            custom_flag,
                        )
                    elif object_name == "WarpObj":
                        patch_trial_gate(
                            room_bzs["LAY "][f"l{layer}"],
                            itemid,
                            trapid,
                        )
                    elif object_name == "TgReact":
                        patch_tgreact(
                            room_bzs["LAY "][f"l{layer}"],
                            itemid,
                            objectid,
                            trapid,
                            custom_flag,
                        )
                    elif object_name == "Tubo":
                        patch_pot(
                            room_bzs["LAY "][f"l{layer}"],
                            itemid,
                            objectid,
                            trapid,
                            custom_flag,
                        )
                    elif object_name == "Pumpkin":
                        pumpkin_entry = patch_pumpkin(
                            room_bzs["LAY "][f"l{layer}"],
                            itemid,
                            objectid,
                            trapid,
                            custom_flag,
                        )
                        if pumpkin_entry is not None:
                            for existing in self.pumpkin_entries:
                                if existing[0] == pumpkin_entry[0] and existing[1] == pumpkin_entry[1]:
                                    raise Exception(
                                        f"Two pumpkins share the position {pumpkin_entry[0]:#010x}/{pumpkin_entry[1]:#010x}; "
                                        "the position-keyed pumpkin table needs unique positions."
                                    )
                            self.pumpkin_entries.append(pumpkin_entry)
                    elif object_name == "BigTubo":
                        big_pot_entry = patch_big_pot(
                            room_bzs["LAY "][f"l{layer}"],
                            itemid,
                            objectid,
                            trapid,
                            custom_flag,
                        )
                        if big_pot_entry is not None:
                            for existing in self.big_pot_entries:
                                if existing[0] == big_pot_entry[0] and existing[1] == big_pot_entry[1]:
                                    raise Exception(
                                        f"Two big pots share the position {big_pot_entry[0]:#010x}/{big_pot_entry[1]:#010x}; "
                                        "the position-keyed big pot table needs unique positions."
                                    )
                            if len(self.big_pot_entries) >= 16:
                                raise Exception(
                                    "More than 16 big pots have items; BIG_POT_TABLE_ENTRIES only holds 16."
                                )
                            self.big_pot_entries.append(big_pot_entry)
                    elif object_name == "Barrel":
                        barrel_entry = patch_barrel(
                            room_bzs["LAY "][f"l{layer}"],
                            itemid,
                            objectid,
                            trapid,
                            custom_flag,
                        )
                        if barrel_entry is not None:
                            for existing in self.barrel_entries:
                                if existing[0] == barrel_entry[0] and existing[1] == barrel_entry[1]:
                                    raise Exception(
                                        f"Two barrels share the position {barrel_entry[0]:#010x}/{barrel_entry[1]:#010x}; "
                                        "the position-keyed barrel table needs unique positions (the same "
                                        "barrel on several layers must be one location)."
                                    )
                            if len(self.barrel_entries) >= 192:
                                raise Exception(
                                    "More than 192 barrels have items; BARREL_TABLE_ENTRIES only holds 192."
                                )
                            self.barrel_entries.append(barrel_entry)
                    elif object_name == "Bell":
                        patch_academy_bell(
                            room_bzs["LAY "][f"l{layer}"],
                            itemid,
                            trapid,
                            custom_flag,
                        )
                    elif object_name == "Clef":
                        patch_tadtone_group(
                            room_bzs["LAY "][f"l{layer}"],
                            itemid,
                            objectid,
                            trapid,
                            custom_flag,
                        )
                    elif object_name == "FrtTree":
                        patch_tree_of_life(
                            room_bzs["LAY "][f"l{layer}"],
                            itemid,
                            trapid,
                            custom_flag,
                        )
                    elif object_name == "HrpHint":
                        patch_hrphint(
                            room_bzs["LAY "][f"l{layer}"],
                            itemid,
                            objectid,
                            trapid,
                            custom_flag,
                        )
                    else:
                        print(
                            f"Object name: {object_name} not currently supported for check patching."
                        )

                bzs_u8.add_file_data(
                    f"dat/{stage_name}_room_{roomid}.bzs", build_bzs(room_bzs)
                )

            update_progress_value(
                get_progress_value_from_range(
                    80, 20, current_stage_num, len(bzs_cache_stage_paths)
                )
            )

        write_bytes_create_dirs(
            self.base_output_path / "Stage" / "bzs.arc", bzs_u8.build_U8()
        )

        print(
            f"Patching stages took {(time.process_time() - start_stage_patching_time)} seconds"
        )

    def remove_unnecessary_patches(
        self, onlyif_handler: ConditionalPatchHandler
    ) -> None:
        for patches in self.stage_patches.values():
            for patch in patches.copy():
                if statement := patch.get("onlyif", False):
                    if not onlyif_handler.evaluate_onlyif(statement):
                        patches.remove(patch)

    def __extract_bzs_files(self, stage_file_paths):
        for current_stage_file_num, stage_path in enumerate(stage_file_paths):
            stage_name = stage_path.name
            # Ignore non-stage files
            if stage_name not in BZS_FILE_HASHES:
                continue

            print_progress_text(f"Checking cached files for stage: {stage_name}")
            bzs_stage_dir_path = CACHE_BZS_PATH / stage_name
            bzs_stage_dir_path.mkdir(parents=True, exist_ok=True)

            files_to_extract: list[str] = []

            for bzs_file_name in BZS_FILE_HASHES[stage_name]:
                bzs_stage_file_path = bzs_stage_dir_path / bzs_file_name

                if (
                    not bzs_stage_file_path.exists()
                    or BZS_FILE_HASHES[stage_name][bzs_file_name]
                    != hashlib.sha256(bzs_stage_file_path.read_bytes()).hexdigest()
                ):
                    files_to_extract.append(bzs_file_name)

            if len(files_to_extract) > 0:
                for bzs_file_name in files_to_extract:
                    print_progress_text(f"Extracting {bzs_file_name} for {stage_name}")
                    bzs_stage_file_path = bzs_stage_dir_path / bzs_file_name

                    if bzs_stage_file_path.exists():
                        bzs_stage_file_path.unlink()

                    full_stage_path = stage_path / "NX" / f"{stage_name}_stg_l0.arc.LZ"
                    stage_u8 = U8File.get_parsed_U8_from_path(full_stage_path)

                    if bzs_file_name.endswith("stage.bzs"):
                        bzs = stage_u8.get_file_data("dat/stage.bzs")
                    else:
                        roomid = bzs_file_name.split(".bzs")[0][-2:]

                        if roomid.startswith("_"):
                            roomid = "0" + roomid[-1]

                        room_u8 = stage_u8.get_parsed_U8_from_this_U8(
                            f"rarc/{stage_name}_r{roomid}.arc"
                        )
                        bzs = room_u8.get_file_data("dat/room.bzs")

                    if bzs is None:
                        raise Exception(
                            f"Failed to extract data from stage {stage_name}.\nCould not read bzs data for {bzs_stage_file_path}."
                        )

                    if (
                        BZS_FILE_HASHES[stage_name][bzs_file_name]
                        != hashlib.sha256(bzs).hexdigest()
                    ):
                        raise Exception(
                            f"The bzs data extracted from stage {stage_name} is not correct and cannot be used. Please verify your stage files are correct and try again."
                        )

                    bzs_stage_file_path.write_bytes(bzs)

            update_progress_value(
                get_progress_value_from_range(
                    40, 10, current_stage_file_num, len(stage_file_paths)
                )
            )

    def create_cache(self):
        start_cache_time = time.process_time()

        extracts: dict[dict, dict] = yaml_load(EXTRACTS_PATH)  # type: ignore
        CACHE_PATH.mkdir(parents=True, exist_ok=True)
        CACHE_OARC_PATH.mkdir(parents=True, exist_ok=True)
        CACHE_BZS_PATH.mkdir(parents=True, exist_ok=True)

        self.__extract_bzs_files(stage_file_paths=list(STAGE_FILES_PATH.glob("*")))

        print(
            f"Verifying bzs cache took {(time.process_time() - start_cache_time)} seconds"
        )
        start_arc_patching_time = time.process_time()

        mods = [""]  # Empty string represents default game extract
        mods.extend(self.other_mods)

        default_objectpack_u8 = U8File.get_parsed_U8_from_path(OBJECTPACK_PATH)

        # Remove mod cache each time to prevent old mod files from lingering
        for cache_path in CACHE_OARC_PATH.glob("*"):
            if cache_path.is_dir():
                shutil.rmtree(cache_path)

        for mod in mods:
            cache_oarc_path = CACHE_OARC_PATH / mod
            cache_oarc_path.mkdir(parents=True, exist_ok=True)

            objectpack_path, _ = get_resolved_game_file_path(
                OBJECTPACK_PATH, self.other_mods, mod
            )

            for current_extract_num, extract in enumerate(extracts):
                # objectpack is a special case (not a stage)
                if "objectpack" in extract and objectpack_path.exists():
                    arcs = extract["objectpack"]
                    arcs_not_in_cache = [
                        arc_name
                        for arc_name in arcs
                        if not (cache_oarc_path / f"{arc_name}.arc").exists()
                    ]

                    if len(arcs_not_in_cache) == 0:
                        continue

                    # Allow mod makers to put objectpack arcs in "ModName/oarc"
                    mod_object_path = OTHER_MODS_PATH / mod / "oarc"

                    if mod and mod_object_path.exists():
                        for arc_path in mod_object_path.glob("*.arc"):
                            arc_name = arc_path.name
                            shutil.copyfile(
                                mod_object_path / arc_name,
                                cache_oarc_path / arc_name,
                            )
                            print_progress_text(f"Copying {mod}/{arc_name}")

                    # If a mod doesn't have an objectpack, then skip it
                    if mod and OBJECTPACK_PATH.samefile(objectpack_path):
                        continue

                    objectpack_u8 = U8File.get_parsed_U8_from_path(objectpack_path)
                    oarc_path = objectpack_u8.get_oarc_path()

                    for arc_name in arcs_not_in_cache:
                        arc_data = objectpack_u8.get_file_data(
                            f"{oarc_path}/{arc_name}.arc"
                        )

                        if not arc_data:
                            raise TypeError(
                                f"Expected type bytes but found None for {mod}/{arc_name}."
                            )

                        # If we're extracting arcs from a mod, don't rewrite
                        # the arcs if they're the same as the original game
                        if mod:
                            default_arc_data = default_objectpack_u8.get_file_data(
                                f"oarc/{arc_name}.arc"
                            )
                            if arc_data == default_arc_data:
                                continue

                        print_progress_text(
                            f"Extracting {mod + '/' if mod else ''}{arc_name}"
                        )
                        (cache_oarc_path / f"{arc_name}.arc").write_bytes(arc_data)
                else:
                    stage = extract["stage"]

                    for layer in extract["layers"]:
                        layerid = layer["layerid"]
                        arcs = layer["oarcs"]

                        all_already_in_cache = all(
                            ((cache_oarc_path / f"{arc}.arc").exists() for arc in arcs)
                        )

                        if all_already_in_cache:
                            continue

                        original_stage_path = (
                            STAGE_FILES_PATH
                            / f"{stage}"
                            / "NX"
                            / f"{stage}_stg_l{layerid}.arc.LZ"
                        )
                        stage_path, _ = get_resolved_game_file_path(
                            original_stage_path, self.other_mods, mod
                        )

                        # If this mod doesn't have the specified stage file, then skip it
                        if mod and os.path.samefile(original_stage_path, stage_path):
                            continue

                        stage_u8 = U8File.get_parsed_U8_from_path(stage_path)
                        oarc_path = stage_u8.get_oarc_path()

                        # If we're extracting from a mod, get the original game's stage file to compare arcs against
                        if mod:
                            original_stage_u8 = U8File.get_parsed_U8_from_path(
                                original_stage_path
                            )

                        for arc_name in arcs:
                            arc_data = stage_u8.get_file_data(
                                f"{oarc_path}/{arc_name}.arc"
                            )

                            if not arc_data:
                                raise TypeError(
                                    f"Expected type bytes but found None for {mod}/{arc_name}."
                                )

                            # If we're extracting arcs from a mod, don't cache them if they're the same as the base game
                            if mod:
                                default_arc_data = original_stage_u8.get_file_data(
                                    f"oarc/{arc_name}.arc"
                                )
                                if arc_data == default_arc_data:
                                    continue

                            print_progress_text(
                                f"Extracting {mod + '/' if mod else ''}{arc_name}"
                            )
                            (cache_oarc_path / f"{arc_name}.arc").write_bytes(arc_data)

                if mod == "":
                    update_progress_value(
                        get_progress_value_from_range(
                            45, 5, current_extract_num, len(extracts)
                        )
                    )

        # Once we've extracted all the arcs, look for conflicts between different mods
        mod_arcs = {}
        for mod in self.other_mods:
            for arc in (CACHE_OARC_PATH / mod).glob("*"):
                if arc.name in mod_arcs:
                    raise Exception(
                        f'Mods "{mod_arcs[arc.name]}" and "{mod}" conflict and cannot be used together.'
                    )
                mod_arcs[arc.name] = mod

        end_cache_time = time.process_time()
        print(
            f"Arc extraction took {(end_cache_time - start_arc_patching_time)} seconds"
        )
        print(
            f"Total cache building took {(end_cache_time - start_cache_time)} seconds"
        )

    def add_arcn_for_check(self, stage: str, layer: int, room: int, arcn: str):
        if self.stage_patches.get(stage, None) == None:
            self.stage_patches[stage] = []

        self.stage_patches[stage].append(
            {
                "type": "arcnadd",
                "layer": layer,
                "room": room,
                "arcn": [arcn],
            }
        )

    def add_check_patch(
        self,
        stage: str,
        room: int,
        object_name: str,
        layer: int,
        objectid: str,
        itemid: int,
        trapid: int = 0,
        custom_flag: int = -1,
        original_itemid: int = 0,
        tbox_subtype: int = -1,
    ):
        self.check_patches[stage].append(
            (
                room,
                object_name,
                layer,
                objectid,
                itemid,
                trapid,
                custom_flag,
                original_itemid,
                tbox_subtype,
            )
        )

    def add_global_patch(self, patch: dict):
        patch_type = patch.get("type")
        if patch_type != "symbol":
            raise Exception(
                f"Unsupported global patch type '{patch_type}'. Patch: {patch}"
            )

        symbol = patch.get("symbol")
        if not isinstance(symbol, str) or symbol == "":
            raise Exception(f"Global symbol patch missing valid symbol. Patch: {patch}")

        value = patch.get("value")
        if not isinstance(value, int):
            raise Exception(f"Global symbol patch missing valid integer value. Patch: {patch}")

        self.global_patches.append(patch)

    def get_global_symbol_values(self) -> dict[str, int]:
        values: dict[str, int] = {}
        for patch in self.global_patches:
            if patch.get("type") == "symbol":
                symbol = patch.get("symbol")
                value = patch.get("value")
                if isinstance(symbol, str) and isinstance(value, int):
                    values[symbol] = value
        return values

    def add_entrance_patch(
        self,
        exit_stage: str,
        exit_scen_index: int,
        exit_room: int,
        spawn_stage: str,
        spawn_layer: int,
        spawn_room: int,
        spawn_entrance: int,
    ):
        if exit_stage not in self.stage_patches:
            self.stage_patches[exit_stage] = []

        self.stage_patches[exit_stage].append(
            {
                "name": f"Entrance Patch - {exit_stage} to {spawn_stage}",
                "type": "objpatch",
                "index": exit_scen_index,
                "room": exit_room,
                "objtype": "SCEN",
                "object": {
                    "name": spawn_stage,
                    "layer": spawn_layer,
                    "room": spawn_room,
                    "entrance": spawn_entrance,
                },
            }
        )


def create_shuffled_trial_object_patches(
    world: World, stage_patch_handler: StagePatchHandler
) -> None:
    print_progress_text("Patching trial objects")

    # Go through each stage and collect all the item object positions
    silent_realm_stages = ["S000", "S100", "S200", "S300"]
    shuffle = world.setting("random_trial_object_positions")

    for stage in silent_realm_stages:
        shuffle_objects: list[tuple[int, int]] = []
        shuffle_positions: list[dict[str, float]] = []

        dusk_relic_objects: list[tuple[int, int]] = []
        dusk_relic_positions: list[dict[str, float]] = []

        # Go through all the rooms in the silent realm to collect each item
        for room_bzs_path in (CACHE_BZS_PATH / stage).glob("room*"):
            room_id = int(room_bzs_path.name.split(".bzs")[0][5:])
            room_bzs_bytes = room_bzs_path.read_bytes()
            room_bzs = parse_bzs(room_bzs_bytes)

            for obj in room_bzs["LAY "]["l2"].get("OBJ ", []):

                # Shuffle dusk relics amongst each other even if the shuffle is off. If trial treasuresanity is on
                # this gives the illusion that random dusk relics were chosen for items when in reality we just
                # switched around their positions
                if obj["name"] == "AncJwls" and shuffle.is_any_of("none", "simple"):
                    dusk_relic_objects.append((obj["id"], room_id))
                    dusk_relic_positions.append(
                        {"x": obj["posx"], "y": obj["posy"], "z": obj["posz"]}
                    )

                itemid = obj["params1"] & 0xFF
                if (
                    obj["name"] == "AncJwls" and shuffle.is_any_of("advanced", "full")
                ) or (
                    obj["name"] == "Item"
                    and (
                        (itemid == 0x2A and shuffle == "full")
                        or (
                            itemid == 0x2F
                            and shuffle.is_any_of("simple", "advanced", "full")
                        )
                        or (
                            itemid in (0x2B, 0x2C, 0x2D, 0x2E)
                            and shuffle.is_any_of("simple", "advanced", "full")
                        )
                    )
                ):
                    shuffle_objects.append((obj["id"], room_id))
                    shuffle_positions.append(
                        {"x": obj["posx"], "y": obj["posy"], "z": obj["posz"]}
                    )

        # Once we've collected all the objects and positions we're going to shuffle, shuffle them
        for patch_objects, patch_positions in [
            (dusk_relic_objects, dusk_relic_positions),
            (shuffle_objects, shuffle_positions),
        ]:

            # Shuffle the trial objects for this stage
            random.shuffle(patch_objects)
            assert len(patch_objects) == len(patch_positions)

            # Then pop a position off the list of positions to match with each object
            for object_id, room_id in patch_objects:
                pos = patch_positions.pop()
                position_patch = {
                    "name": f"Position shuffle for {object_id} on {stage}",
                    "type": "objpatch",
                    "id": object_id,
                    "room": room_id,
                    "layer": 2,
                    "objtype": "OBJ",
                    "object": {
                        "posx": pos["x"],
                        "posy": pos["y"],
                        "posz": pos["z"],
                    },
                }

                if stage not in stage_patch_handler.stage_patches:
                    stage_patch_handler.stage_patches[stage] = []

                stage_patch_handler.stage_patches[stage].append(position_patch)


def create_demise_patches(
    world: World, stage_patch_handler: StagePatchHandler
) -> None:
    """Add extra Demise bosses to B400 via stage patches.

    This avoids live runtime spawning, which can cause model/state issues.
    """
    demise_count = world.setting("demise_count").value_as_number()
    if demise_count <= 1:
        return

    if "B400" not in stage_patch_handler.stage_patches:
        stage_patch_handler.stage_patches["B400"] = []

    orig_demise = {
        "params1": 0xFFFFFFC0,
        "params2": 0xFFFFFFFF,
        "posx": 0,
        "posy": 0,
        "posz": -500,
        "anglex": 0,
        "angley": 0,
        "anglez": 0,
        "id": 0xFC00,
        "name": "BLasBos",
    }

    # Vanilla includes one Demise already. Add (demise_count - 1) extras.
    for idx in range(1, demise_count):
        demise = orig_demise.copy()
        demise["posy"] = 1000 * idx
        stage_patch_handler.stage_patches["B400"].append(
            {
                "name": f"Demise add {idx}",
                "type": "objadd",
                "room": 0,
                "layer": 1,
                "objtype": "OBJ",
                "object": demise,
            }
        )
