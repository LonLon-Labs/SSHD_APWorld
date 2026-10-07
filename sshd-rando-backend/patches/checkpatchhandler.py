import logging
import random
from constants.itemconstants import (
    BIRD_STATUE_UNLOCK_FLAG_RESERVED_COUNT,
    CTMC_ITEMS_TO_FILTER_OUT,
    ITEMS_NOT_TO_TRAP,
)
from constants.patchconstants import (
    STAGE_PATCH_PATH_REGEX,
    EVENT_PATCH_PATH_REGEX,
    OARC_ADD_PATH_REGEX,
    SHOP_PATCH_PATH_REGEX,
)
from constants.shopconstants import *
from gui.dialogs.dialog_header import print_progress_text
from logic.location import Location
from logic.world import World

from patches.asmpatchhandler import ASMPatchHandler
from patches.eventpatchhandler import EventPatchHandler
from patches.stagepatchhandler import BIRD_STATUE_LOCATION_NAMES, StagePatchHandler

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logic.item import Item

# Story flag that gates the spawning of every Goddess Chest whenever the chests are
# unlocked independently of their cubes. It is the single source of truth: writing 1
# activates all Goddess Chests and writing 0 deactivates them. In
# "unlocked_after_goddess_sword" mode the game's main loop sets it once story flag 907
# (Goddess Sword / Progressive Sword 2) is set (see
# handle_goddess_chest_unlock_flag in mainloop.rs).
GODDESS_CHEST_UNLOCK_STORYFLAG = 95


# Item id of the generic "Archipelago Item" placeholder
AP_PLACEHOLDER_ITEMID = 216

# Custom flag "group" bit (bit 10 of the full custom flag ID). Group 0 is the
# original 10-bit space (scene indexes 6/13/16/19). Group 1 lives in the
# extended save-file pages (scene indexes 26-29, scene space only) and is only
# ever used by pots and pumpkins, whose params2 stores just the low 10 bits (the
# group is implicit for a Tubo or Pumpkin). Keep in sync with CUSTOM_FLAG_GROUP1
# in item.rs, the
# ap-ipc crate, the Python client and _build_custom_flag_mapping in the APWorld.
CUSTOM_FLAG_GROUP1 = 0x400

# Local IDs available to group 1: selector (bits 7-8) 0-3, bit 9 (flag space) is
# always 0, bit within page 0-126. Local ID 0 means "no flag" to the game's item
# handler, and every (i & 0x7F) == 0x7F is skipped, as in group 0. That leaves
# 4 * 127 - 1 = 507 IDs.
GROUP1_LOCAL_FLAGS = [i for i in range(1, 512) if (i & 0x7F) != 0x7F]

# Story flag set by striking each Goddess Cube (matches GODDESS_CUBE_STORYFLAGS in
# stagepatchhandler.py and GODDESS_CUBE_STORY_FLAGS in the apworld's Locations.py)
GODDESS_CUBE_NAME_TO_STORYFLAG: dict[str, int] = {
    "Deep Woods - Goddess Cube Near Goron": 227,
    "Deep Woods - Goddess Cube in front of Temple": 228,
    "Eldin Volcano - Goddess Cube at Eldin Entrance": 229,
    "Lanayru Desert - Goddess Cube in Sand Oasis": 230,
    "Faron Woods - Goddess Cube on East Great Tree with Clawshots Target": 231,
    "Eldin Volcano - Goddess Cube near Mogma Turf Entrance": 234,
    "Lanayru Mine - Goddess Cube behind First Landing Robot": 235,
    "Faron Woods - Goddess Cube on East Great Tree with Rope": 236,
    "Eldin Volcano - Goddess Cube East of Temple": 237,
    "Skipper's Retreat - Goddess Cube on Southwest Pillar": 238,
    "Lanayru Gorge - Goddess Cube near Sandfalls": 239,
    "Volcano Summit - Goddess Cube in Lava Lake": 240,
    "Faron Woods - Goddess Cube on West Great Tree near Exit": 241,
    "Eldin Volcano - Goddess Cube on Sand Slide": 242,
    "Pirate Stronghold - Goddess Cube on top of Shark Head": 243,
    "Deep Woods - Goddess Cube on top of Temple": 244,
    "Eldin Volcano - Goddess Cube behind Bombable Rock West of Temple": 245,
    "Lanayru Desert - Goddess Cube in Secret Passageway": 246,
    "Lanayru Desert - Goddess Cube near Caged Robot": 247,
    "Volcano Summit - Goddess Cube near Fire Sanctuary Entrance": 248,
    "Floria Waterfall - Goddess Cube on High Ledge": 249,
    "Skyview Spring - Goddess Cube behind Crest": 250,
    "Volcano Summit - Goddess Cube at Summit Waterfall": 251,
    "Temple of Time - Goddess Cube on High Platform North of Tree": 252,
    "Lake Floria - Goddess Cube near Bird Statue": 254,
    "Mogma Turf - Goddess Cube on Raised Pillar": 255,
    "Ancient Harbour - Goddess Cube in North Cave": 256,
}


def determine_check_patches(
    world: World,
    stage_patch_handler: StagePatchHandler,
    event_patch_handler: EventPatchHandler,
    asm_patch_handler: ASMPatchHandler,
):
    print_progress_text("Creating Location Patches")

    # Decide which story flag gates the spawning of Goddess Chests.
    #  - locked_until_struck: leave vanilla (each chest is gated by its cube)
    #  - unlocked_after_goddess_sword: story flag 95, which the game sets once the
    #    Goddess Sword story flag (907) is set
    #  - unlocked_from_start: story flag 95
    goddess_chest_unlock = world.setting("goddess_chest_unlock")
    if goddess_chest_unlock in (
        "unlocked_after_goddess_sword",
        "unlocked_from_start",
    ):
        stage_patch_handler.goddess_chest_spawn_storyflag = (
            GODDESS_CHEST_UNLOCK_STORYFLAG
        )
    else:
        stage_patch_handler.goddess_chest_spawn_storyflag = None

    # Custom flags currently use 10 total bits as follows
    # in order of most significant to least significant bits:

    # - (1 bit) flag_space_trigger: Used to denote whether this flag is using
    # the unused scene flag space or the unused dungeon flag space

    # - (2 bits) scene index / dungeon index: Used to denote which unused scene/dungeon index the
    # flag is in. There are a total of 4 unused indexes for both scene flags and dungeon flags.
    # Since each index can hold 128 bits, this gives us a total of 1,024 flags to use.

    # - (7 bits) flag: The flag within the unused flag space. Can be any value from 0-127.
    # 128 is used to indicate there being no custom flag (so really we can have up to 1,016 flags)
    #
    # Custom flag IDs 0 to BIRD_STATUE_UNLOCK_FLAG_RESERVED_COUNT - 1 are reserved for the
    # Bird Statue unlock flags (scene flag space, first unused scene index). They are never
    # handed out to locations. Keep this in sync with the AP world's custom flag pool.
    custom_flags = [
        i
        for i in range(BIRD_STATUE_UNLOCK_FLAG_RESERVED_COUNT, 1024)
        if (i & 0x7F) != 0x7F
    ]
    custom_flags.reverse()

    # Pot sanity draws from the group 1 pool instead (see CUSTOM_FLAG_GROUP1)
    group1_flags = [CUSTOM_FLAG_GROUP1 | i for i in GROUP1_LOCAL_FLAGS]
    group1_flags.reverse()

    location_table = world.location_table

    # Remove flags already injected by Archipelago to prevent collisions.
    # AP assigns from the high end; the patcher assigns from the low end.
    # This depletion is defense-in-depth in case the pools ever overlap.
    injected_flags = {
        loc.custom_flag for loc in location_table.values()
        if hasattr(loc, 'custom_flag') and loc.custom_flag != 0x3FF
    }
    if injected_flags:
        custom_flags = [f for f in custom_flags if f not in injected_flags]
        group1_flags = [f for f in group1_flags if f not in injected_flags]

    # A set is okay here because it doesn't touch any randomization
    playthrough_items = set()

    for sphere in world.playthrough_spheres:
        for location in sphere:
            playthrough_items.add(location.current_item.name)

    for location in location_table.values():
        item = location.current_item

        # Deal with items with custom flags
        # Check if Archipelago already injected a custom flag (for multiworld)
        if hasattr(location, 'custom_flag') and location.custom_flag != 0x3FF:
            # Use the pre-injected custom flag from Archipelago
            custom_flag = location.custom_flag
        elif "Custom Flag" in location.types:
            # Assign a new custom flag for vanilla sshd-rando locations. Pots use
            # the extended group 1 pool when they're actually shuffled; with pots
            # off the old group 0 draw is kept so existing seeds don't shift.
            if "Pots" in location.types and world.setting("pot_shuffle") != "off":
                custom_flag = group1_flags.pop()
            elif (
                "Pumpkins" in location.types
                and world.setting("pumpkin_shuffle") != "off"
            ):
                # Pumpkins share the extended group 1 pool with pots
                custom_flag = group1_flags.pop()
            elif "Pumpkins" in location.types:
                # Unshuffled pumpkins are never patched. Pumpkin shuffle is new,
                # so there are no existing seeds to keep stable: burn nothing.
                custom_flag = 0x3FF
            elif "Pots" in location.types:
                # Unshuffled pots are never patched, so their flag is never used.
                # Keep burning a group 0 flag while any are left so existing
                # seeds don't shift, but don't fail when the pool runs dry (the
                # AP world already injects a flag for every shuffled location).
                custom_flag = custom_flags.pop() if custom_flags else 0x3FF
            else:
                custom_flag = custom_flags.pop()
            location.custom_flag = custom_flag
        else:
            # No custom flag needed
            custom_flag = 0x3FF

        # Only pots and pumpkins can carry a group 1 flag (their params2 has no
        # room for the group bit, so the game treats every pot/pumpkin flag as
        # group 1), and every shuffled one must carry one. A mismatch would make
        # a check set another location's flag.
        if custom_flag != 0x3FF:
            is_group1 = bool(custom_flag & CUSTOM_FLAG_GROUP1)
            is_pot = "Pots" in location.types
            is_pumpkin = "Pumpkins" in location.types
            is_group1_type = is_pot or is_pumpkin
            group1_off = (
                world.setting("pot_shuffle") == "off"
                if is_pot
                else world.setting("pumpkin_shuffle") == "off"
            )
            if is_group1 and not is_group1_type:
                raise Exception(
                    f'"{location.name}" has group 1 custom flag {custom_flag:#x} '
                    "but isn't a pot or pumpkin."
                )
            # With the shuffle off the location is never patched, so its flag is unused
            if is_group1_type and not group1_off and not is_group1:
                raise Exception(
                    f'"{location.name}" has group 0 custom flag '
                    f"{custom_flag:#x}; pots and pumpkins must use group 1."
                )

        original_itemid = 0

        if "Stamina Fruits" in location.types:
            original_itemid = 1

            # Don't patch anything if the stamina fruit is vanilla
            if location.current_item == location.world.get_item("Stamina Fruit"):
                continue

        # Don't patch closets if they're off
        if (
            "Closets" in location.types
            and world.setting("npc_closet_shuffle") == "vanilla"
        ):
            continue

        # Don't patch pots if they're off
        if "Pots" in location.types and world.setting("pot_shuffle") == "off":
            continue

        # Don't patch pumpkins if they're off
        if (
            "Pumpkins" in location.types
            and world.setting("pumpkin_shuffle") == "off"
        ):
            continue

        # Deal with traps
        trapid = 0
        trap_oarcs = None
        item_oarcs = []

        if item is not None:
            if item.name.endswith("Trap"):
                trapid = item.id

                trap_oarcs = item.oarcs

                # Don't use items that don't have usable models
                trappable_items = [
                    item
                    for item in world.item_table.values()
                    if item.id < 200  # exclude custom items
                    and item.name not in ITEMS_NOT_TO_TRAP
                    and item.shop_arc_name is not None
                    and item.shop_model_name is not None
                ]

                trappable_items_setting = world.setting("trappable_items")

                if trappable_items_setting == "major_items":
                    trappable_items = [
                        item for item in trappable_items if item.is_major_item
                    ]
                elif trappable_items_setting == "non_major_items":
                    trappable_items = [
                        item for item in trappable_items if not item.is_major_item
                    ]

                # Getting potion models from NPCs is broken rn
                # Fi counts as an NPC for this so also include Crest
                if "NPC" in location.types or "Crests" in location.types:
                    trappable_items = [
                        item for item in trappable_items if not "Potion" in item.name
                    ]

                item = random.choice(trappable_items)

            # Combine item.oarcs with trap_oarcs
            item_oarcs = []
            if item.oarcs:
                if isinstance(item.oarcs, list):
                    item_oarcs += item.oarcs
                else:
                    item_oarcs.append(item.oarcs)
            else:
                # Item has no model (bugs, some treasures). The Rust code
                # will fall back to "GetRupee" which is in the ObjectPack
                # and always loaded, so no ARCN entry is needed. But we
                # still need to make sure the item spawns properly, so
                # add GetRupee as a safety net in case the stage doesn't
                # have it from ObjectPack for some reason.
                item_oarcs.append("GetRupee")

            if trap_oarcs:
                if isinstance(trap_oarcs, list):
                    item_oarcs += trap_oarcs
                else:
                    item_oarcs.append(trap_oarcs)

            logging.getLogger("").debug(
                f'Trapped item at "{location}" assigned model of "{item}".'
            )

        # Decoupled Goddess Cubes: striking a cube gives the item at runtime. The
        # game's main loop watches the cube's story flag and, once it is set, spawns
        # this item (with the AP custom flag) so Link plays the normal item-get
        # animation. The tables are filled in via init_global_variables.
        if (
            "Goddess Cube" in location.types
            and world.setting("decouple_goddess_cubes_and_chests") == "on"
            and item is not None
        ):
            cube_storyflag = GODDESS_CUBE_NAME_TO_STORYFLAG.get(location.name)
            if cube_storyflag is not None:
                if custom_flag == 0x3FF:
                    # Standalone (non-AP) generation never injects a flag
                    custom_flag = custom_flags.pop()
                    location.custom_flag = custom_flag
                # Trap items are stored as their real trap id (250-254) rather than
                # the random substitute model's id; the game's cube handler gives
                # those as a real trap actor (a Rupoor with the trap param) so the
                # effect actually fires.
                cube_itemid = trapid if trapid != 0 else item.id
                stage_patch_handler.add_goddess_cube_item(
                    cube_storyflag, cube_itemid, custom_flag
                )

        # Bird Statues Give Items: touching a statue gives the item at runtime, the
        # same way decoupled Goddess Cubes do. The game's main loop watches the
        # statue's flag and, once it is set, spawns this item (with the AP custom
        # flag) so Link plays the normal item-get animation. Trap items are stored
        # as their real trap id (250-254) so the game gives a real trap actor.
        if (
            "Bird Statues" in location.types
            and world.setting("bird_statues_give_items") == "on"
            and item is not None
            and location.name in BIRD_STATUE_LOCATION_NAMES
        ):
            if custom_flag == 0x3FF:
                # Standalone (non-AP) generation never injects a flag
                custom_flag = custom_flags.pop()
                location.custom_flag = custom_flag
            statue_itemid = trapid if trapid != 0 else item.id
            stage_patch_handler.add_bird_statue_item(
                BIRD_STATUE_LOCATION_NAMES.index(location.name),
                statue_itemid,
                custom_flag,
            )

        for path in location.patch_paths:
            if stage_patch_match := STAGE_PATCH_PATH_REGEX.match(path):
                stage = stage_patch_match.group("stage")
                room = int(stage_patch_match.group("room"))
                layer = int(stage_patch_match.group("layer"))
                object_name = stage_patch_match.group("objectName")
                objectid = stage_patch_match.group("objectID")
                tbox_subtype = -1

                if object_name == "TBox":
                    if (
                        world.setting("chest_type_matches_contents").value()
                        == "all_contents"
                    ):
                        if item.is_major_item:
                            if len(item.chain_locations) > 0:
                                if (
                                    len(
                                        [
                                            loc
                                            for loc in item.chain_locations
                                            if loc.progression
                                        ]
                                    )
                                    > 0
                                ):
                                    tbox_subtype = 0
                                else:
                                    tbox_subtype = 1
                            else:
                                tbox_subtype = 0
                        else:
                            tbox_subtype = 1

                    if world.setting("chest_type_matches_contents").value() != "off":
                        if (
                            item.name in CTMC_ITEMS_TO_FILTER_OUT
                            and item.name not in playthrough_items
                        ):
                            tbox_subtype = 1
                        elif item.is_boss_key:
                            tbox_subtype = 2
                        elif item.is_dungeon_small_key:
                            if (
                                world.setting("small_keys_in_fancy_chests").value()
                                == "on"
                            ):
                                tbox_subtype = 2
                            else:
                                tbox_subtype = 0
                        elif item.is_dungeon_map:
                            tbox_subtype = 1

                    # If the post-boko base sword pull chest would CTMC into
                    # a small brown chest actually make it a big blue chest.
                    if stage == "F201_1" and objectid == "73" and tbox_subtype == 1:
                        tbox_subtype = 0

                for oarc in item_oarcs:
                    stage_patch_handler.add_arcn_for_check(stage, layer, room, oarc)

                stage_patch_handler.add_check_patch(
                    stage,
                    room,
                    object_name,
                    layer,
                    objectid,
                    item.id,
                    trapid,
                    custom_flag,
                    original_itemid,
                    tbox_subtype,
                )

            if event_patch_match := EVENT_PATCH_PATH_REGEX.match(path):
                event_file = event_patch_match.group("eventFile")
                eventid = event_patch_match.group("eventID")
                event_patch_handler.add_check_patch(
                    event_file, eventid, item.id, trapid, custom_flag
                )

            if oarc_add_match := OARC_ADD_PATH_REGEX.match(path):
                stage = oarc_add_match.group("stage")
                room = int(oarc_add_match.group("room"))
                layer = int(oarc_add_match.group("layer"))

                for oarc in item_oarcs:
                    stage_patch_handler.add_arcn_for_check(stage, layer, room, oarc)

            if shop_match := SHOP_PATCH_PATH_REGEX.match(path):
                shop_index = int(shop_match.group("index"))
                stage = "F002r"  # Beedle's Airshop
                layer = 0
                room = 0  # Shops are always room 0

                if shop_index < 20 or shop_index >= 30:
                    stage = "F004r"  # Bazaar

                for oarc in item_oarcs:
                    stage_patch_handler.add_arcn_for_check(stage, layer, room, oarc)

                create_shop_data(
                    world, asm_patch_handler, location, shop_index, item, trapid
                )


def append_dungeon_item_patches(event_patch_handler: EventPatchHandler):
    print_progress_text("Creating Dungeon Item Patches")

    DUNGEON_SKEY_ITEMIDS = (
        200,
        201,
        202,
        203,
        204,
        205,
        206,
    )
    DUNGEON_MAP_ITEMIDS = (
        207,
        208,
        209,
        210,
        211,
        212,
        213,
    )
    DUNGEON_SKEY_SCENEINDEXES = {
        200: 11,  # Skyview Temple
        201: 17,  # Lanayru Mining Facility
        202: 12,  # Ancient Cistern
        203: 15,  # Fire Sanctuary
        204: 18,  # Sandship
        205: 20,  # Sky Keep
        206: 9,  # Lanayru Gorge & Caves
    }

    # Patch the pre-existing entry for the Skyview Small Key (003_200).
    svt_small_key_text_patch = {
        "name": f"Skyview Temple Small Key Text",
        "type": "textpatch",
        "index": 251,
    }
    svt_goto_small_key_count_patch = {
        "name": f"Goto Skyview Temple Small Key Count",
        "type": "flowpatch",
        "index": 498,
        "flow": {
            "next": f"Get Skyview Temple Small Key Count",
        },
    }
    svt_small_key_count_patch = {
        "name": f"Get Skyview Temple Small Key Count",
        "type": "flowadd",
        "flow": {
            "type": "type3",
            "next": 496,
            "param1": DUNGEON_SKEY_SCENEINDEXES[200],
            "param3": 78,  # custom command: get small key count
        },
    }
    event_patch_handler.append_to_event_patches("003-ItemGet", svt_small_key_text_patch)
    event_patch_handler.append_to_event_patches(
        "003-ItemGet", svt_goto_small_key_count_patch
    )
    event_patch_handler.append_to_event_patches(
        "003-ItemGet", svt_small_key_count_patch
    )

    for itemid in DUNGEON_SKEY_ITEMIDS + DUNGEON_MAP_ITEMIDS:
        textadd_patch = {
            "name": f"Item {itemid} Text",
            "type": "textadd",
            "textboxtype": 5,
            "unk2": 1,
        }

        flowadd_patch = {
            "name": f"Show Item {itemid} Text",
            "type": "flowadd",
            "flow": {
                "type": "type1",
                "next": -1,
                "param3": 3,
                "param4": f"Item {itemid} Text",
            },
        }

        if itemid in DUNGEON_SKEY_ITEMIDS:
            entryadd_patch = {
                "name": f"Item {itemid} Entry",
                "type": "entryadd",
                "entry": {
                    "name": f"003_{itemid}",
                    "value": f"Get {itemid} Small Key Count",
                },
            }
            small_key_count_patch = {
                "name": f"Get {itemid} Small Key Count",
                "type": "flowadd",
                "flow": {
                    "type": "type3",
                    "next": f"Show Item {itemid} Text",
                    "param1": DUNGEON_SKEY_SCENEINDEXES[itemid],
                    "param3": 78,  # custom command: get small key count
                },
            }
            event_patch_handler.append_to_event_patches(
                "003-ItemGet", small_key_count_patch
            )
        else:
            entryadd_patch = {
                "name": f"Item {itemid} Entry",
                "type": "entryadd",
                "entry": {
                    "name": f"003_{itemid}",
                    "value": f"Show Item {itemid} Text",
                },
            }

        event_patch_handler.append_to_event_patches("003-ItemGet", textadd_patch)
        event_patch_handler.append_to_event_patches("003-ItemGet", flowadd_patch)
        event_patch_handler.append_to_event_patches("003-ItemGet", entryadd_patch)


def create_shop_data(
    world: World,
    asm_patch_handler: ASMPatchHandler,
    location: Location,
    shop_index: int,
    item: "Item",
    trapid: int,
):
    itemid = item.id
    item_price = world.shop_prices[location.name]
    trapbits = 0xF

    if trapid > 0:
        trapbits = 254 - trapid

    asm_patch_handler.add_shop_data(
        shop_index,
        BUY_DECIDE_SCALES.get(itemid, DEFAULT_BUY_DECIDE_SCALE),
        PUT_SCALES.get(itemid, DEFAULT_PUT_SCALE),
        TARGET_ARROW_HEIGHT_OFFSETS.get(shop_index, -1),
        itemid,
        item_price,
        EVENT_ENTRYPOINTS.get(shop_index, -1),
        NEXT_SHOP_INDEXES.get(shop_index, -1),
        0xFFFF,
        item.shop_arc_name,
        item.shop_model_name,
        DISPLAY_HEIGHT_OFFSETS.get(itemid, DEFAULT_DISPLAY_HEIGHT_OFFSET),
        trapbits,
        SOLD_OUT_STORYFLAGS.get(shop_index, -1),
    )
