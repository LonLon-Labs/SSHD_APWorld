from constants.itemconstants import *
from constants.patchconstants import (
    FLOW_ADD_VARIATIONS,
    LANGUAGE_NAME_TO_FILE_ID,
    SWITCH_ADD_VARIATIONS,
    PARAM1_ALIASES,
    PARAM2_ALIASES,
    DEFAULT_FLOW_TYPE_LOOKUP,
)

from filepathconstants import (
    EVENT_FILE_PATH_TAILS,
    EVENT_PATCHES_PATH,
    VANILLA_EVENT_FILE_PATHS,
)

from collections import defaultdict
from pathlib import Path
from gui.dialogs.dialog_header import (
    get_progress_value_from_range,
    update_progress_value,
)
from logic.settings import SettingGet
from patches.conditionalpatchhandler import ConditionalPatchHandler
from patches.othermods import get_resolved_game_file_path

from sslib.msb import (
    ParsedMsb,
    parse_msb,
    build_msb,
    add_msbf_branch,
    process_control_sequences,
)
from sslib.u8file import U8File
from sslib.utils import write_bytes_create_dirs
from sslib.yaml import yaml_load
from util.text import get_text_data


class EventPatchError(RuntimeError):
    pass


class EventPatchHandler:
    def __init__(self, output_path: Path, other_mods: list[str]):
        self.event_output_paths: dict[str, Path] = {
            tail.name: output_path / tail for tail in EVENT_FILE_PATH_TAILS
        }
        self.event_patches: dict[str, list[dict]] = yaml_load(EVENT_PATCHES_PATH)  # type: ignore
        self.check_patches: dict[str, list[tuple[str, int, int]]] = defaultdict(list)
        self.flow_label_to_index_mapping = {}
        self.text_label_to_index_mapping = {}
        self.other_mods = other_mods

    def append_to_event_patches(self, file_name: str, event_patch: dict):
        if file_name not in self.event_patches:
            self.event_patches[file_name] = []
        self.event_patches[file_name].append(event_patch)

    def find_event(self, file_name: str, event_name: str) -> dict | None:
        return next(
            (
                patch
                for patch in self.event_patches[file_name]
                if patch["name"] == event_name
            ),
            None,
        )

    def handle_event_patches(
        self, onlyif_handler: ConditionalPatchHandler, language: SettingGet
    ):
        language_event_path = VANILLA_EVENT_FILE_PATHS[
            LANGUAGE_NAME_TO_FILE_ID[language.value()]
        ]
        event_paths = tuple(language_event_path.glob("*.arc"))
        total_event_file_count = len(event_paths)

        for event_path in event_paths:
            file_name = event_path.parts[-1]
            modified_event_path = (
                self.event_output_paths[LANGUAGE_NAME_TO_FILE_ID[language.value()]]
                / file_name
            )

            resolved_event_path, mod = get_resolved_game_file_path(
                event_path, self.other_mods
            )

            try:
                event_arc = U8File.get_parsed_U8_from_path(resolved_event_path)

                # patch text files first
                for event_file_path in filter(
                    lambda name: name[-1] == "t", event_arc.get_all_paths()
                ):
                    msbt_file_name = event_file_path.split("/")[-1]
                    if msbt_file_name[:-5] in self.event_patches:
                        print(f"Patching {msbt_file_name}")
                        msbt_data = event_arc.get_file_data(event_file_path)

                        if not msbt_data:
                            raise TypeError("Expected type bytes but found None")

                        parsed_msbt = parse_msb(msbt_data)
                        assert len(parsed_msbt["TXT2"]) == len(parsed_msbt["ATR1"])

                        for patch in self.event_patches[msbt_file_name[:-5]]:
                            if statement := patch.get("onlyif", False):
                                if not onlyif_handler.evaluate_onlyif(statement):
                                    continue

                            # handle text patches here
                            if patch["type"] == "textadd":
                                self.text_add(
                                    msbt=parsed_msbt,
                                    text_add=patch,
                                    msbt_file_name=msbt_file_name,
                                    lang=language_event_path.name,
                                )
                            elif patch["type"] == "textpatch":
                                self.text_patch(
                                    msbt=parsed_msbt,
                                    text_patch=patch,
                                    lang=language_event_path.name,
                                )

                        event_arc.set_file_data(event_file_path, build_msb(parsed_msbt))

                for event_file_path in filter(
                    lambda name: name[-1] == "f", event_arc.get_all_paths()
                ):
                    msbf_file_name = event_file_path.split("/")[-1]

                    if (
                        msbf_file_name[:-5] in self.event_patches
                        or msbf_file_name[:-5] in self.check_patches
                        or msbf_file_name == "003-ItemGet.msbf"
                    ):
                        print(f"Patching {msbf_file_name}")

                        if (
                            event_file_data := event_arc.get_file_data(event_file_path)
                        ) is None:
                            raise TypeError(
                                "Event file data incorrect. Expected bytes but found None."
                            )

                        parsed_msbf = parse_msb(event_file_data)

                        if msbf_file_name[:-5] in self.event_patches:
                            self.create_flow_label_to_index_mapping(
                                flow_patches=self.event_patches[msbf_file_name[:-5]],
                                msbf=parsed_msbf,
                                onlyif_handler=onlyif_handler,
                            )

                            for patch in self.event_patches[msbf_file_name[:-5]]:
                                if statement := patch.get("onlyif", False):
                                    if not onlyif_handler.evaluate_onlyif(statement):
                                        continue

                                if (
                                    patch["type"]
                                    in FLOW_ADD_VARIATIONS + SWITCH_ADD_VARIATIONS
                                ):
                                    self.flow_add(msbf=parsed_msbf, flow_add=patch)
                                elif patch["type"] == "flowpatch":
                                    self.flow_patch(msbf=parsed_msbf, flow_patch=patch)
                                elif patch["type"] == "entryadd":
                                    self.entry_add(msbf=parsed_msbf, entry_add=patch)

                        if msbf_file_name[:-5] in self.check_patches:
                            print(f"[EventPatch] Found {len(self.check_patches[msbf_file_name[:-5]])} check patches for {msbf_file_name}")
                            for eventid, itemid, trapid, custom_flag in self.check_patches[
                                msbf_file_name[:-5]
                            ]:
                                print(f"[EventPatch] Processing event in {msbf_file_name}: eventid={eventid}, itemid={itemid}, custom_flag={custom_flag:#x}")
                                
                                if not eventid.isnumeric():
                                    index = self.flow_label_to_index_mapping.get(
                                        eventid, None
                                    )

                                    if index is None:
                                        raise EventPatchError(
                                            f'Flow label "{eventid}" not found when patching event check.\nFile: {msbf_file_name}.\nEventID: {eventid}.\nItemID: {itemid}.'
                                        )

                                    eventid = index

                                eventid = int(eventid)

                                trapbits = 0

                                # +1 allows 0 == not a trap so spawned NPC items don't break
                                if trapid:
                                    trapbits = (254 - trapid) + 1

                                # Inverted so a value of 0 == not a trap
                                # 11 cos signed numbers are bleh
                                itemid |= (trapbits & 0xF) << 11

                                parsed_msbf["FLW3"]["flow"][eventid]["param2"] = itemid

                                # Inject set_global_flag flow node after giveitem (for Archipelago multiworld detection)
                                # Uses CUSTOM event command 80 (subType=0, param3=80) which calls
                                # flag::set_global_sceneflag() or flag::set_global_dungeonflag() in Rust
                                # based on the flag_space_trigger parameter (param4).
                                # The vanilla setsceneflag command (param3=2) only sets LOCAL scene flags
                                # which don't work for arbitrary scenes 6/13/16/19
                                if custom_flag != 0x3FF:
                                    CUSTOM_FLAG_SCENES = [6, 13, 16, 19]
                                    scene_selector = (custom_flag >> 7) & 0x3
                                    actual_scene_index = CUSTOM_FLAG_SCENES[scene_selector]
                                    flag_index = custom_flag & 0x7F
                                    flag_space_trigger = (custom_flag >> 9) & 0x1
                                    
                                    # Get where the giveitem was going to chain to
                                    original_next_index = parsed_msbf["FLW3"]["flow"][eventid].get("next", -1)
                                    
                                    # Create flow node using custom event command 80 (set_global_flag)
                                    # subType=0 routes through the custom event command handler in event.rs
                                    # param3=80 dispatches to our set_global_flag command
                                    # param4=flag_space_trigger (0=sceneflag, 1=dungeonflag)
                                    setflag_flow = {
                                        "type": "type3",
                                        "subType": 0,
                                        "param1": flag_index,          # flag index (0-127)
                                        "param2": actual_scene_index,  # actual scene index (6, 13, 16, or 19)
                                        "param3": 80,                  # custom command: set_global_flag
                                        "param4": flag_space_trigger,  # 0=sceneflag, 1=dungeonflag
                                        "param5": 0,
                                        "next": original_next_index,
                                    }
                                    
                                    # Append new flow node and redirect giveitem to it
                                    new_flow_index = len(parsed_msbf["FLW3"]["flow"])
                                    parsed_msbf["FLW3"]["flow"].append(setflag_flow)
                                    parsed_msbf["FLW3"]["flow"][eventid]["next"] = new_flow_index
                                    
                                    print(f"[EventPatch] Injected set_global_flag(cmd80) for event {eventid}: scene={actual_scene_index}, flag={flag_index}, flag_space={flag_space_trigger} (flow {new_flow_index} -> {original_next_index})")

                        # ============================================================
                        # Beedle purchase storyflag injection
                        # Inject set_storyflag commands into 105-Terry.msbf
                        # purchase flows via FEN1 redirect: each FEN1 entry
                        # now points to our set_storyflag node, which chains
                        # to the original flow start.
                        # Must run AFTER event_patches (so rando-added entries
                        # 105_39/105_40 exist) and AFTER check_patches.
                        # ============================================================
                        if msbf_file_name == "105-Terry.msbf":
                            from constants.shopconstants import BEEDLE_PURCHASE_STORYFLAGS

                            flows = parsed_msbf["FLW3"]["flow"]

                            # Build FEN1 name -> entry object mapping
                            fen1_entries = {}
                            if "FEN1" in parsed_msbf:
                                for group in parsed_msbf["FEN1"]:
                                    for entry in group:
                                        fen1_entries[entry["name"]] = entry

                            injected_count = 0
                            for fen1_name, storyflag in BEEDLE_PURCHASE_STORYFLAGS.items():
                                if fen1_name not in fen1_entries:
                                    print(f"[BeedleSF] Skipping {fen1_name} (not in FEN1)")
                                    continue

                                fen1_entry = fen1_entries[fen1_name]
                                start_node_idx = fen1_entry["value"]
                                start_node = flows[start_node_idx]

                                # The FEN1 entry must point to a "start"-type node.
                                # The event system requires start nodes as entry points;
                                # inserting a type3 node BEFORE the start node won't execute.
                                # Fix: insert our set_storyflag AFTER the start node by
                                # redirecting start_node.next -> new_node -> original_next.
                                if start_node["type"] != "start":
                                    print(f"[BeedleSF] WARNING: {fen1_name} -> flow[{start_node_idx}] is type '{start_node['type']}', not 'start'! Skipping.")
                                    continue

                                original_first_cmd = start_node.get("next", -1)

                                # Create set_storyflag node: type3 sub=0 param3=0 → vanilla set_storyflag
                                setflag_flow = {
                                    "type": "type3",
                                    "subType": 0,
                                    "param1": 0,
                                    "param2": storyflag,
                                    "param3": 0,
                                    "param4": 0,
                                    "param5": 0,
                                    "next": original_first_cmd,
                                }

                                new_idx = len(flows)
                                flows.append(setflag_flow)

                                # Redirect start node's next to our new node
                                # FEN1 entry remains pointing to start node (unchanged)
                                start_node["next"] = new_idx
                                injected_count += 1

                                print(f"[BeedleSF] Start-next redirect: {fen1_name} -> flow[{start_node_idx}](start, next={new_idx}) -> flow[{new_idx}](set_storyflag {storyflag}) -> flow[{original_first_cmd}]")

                            # Diagnostic: dump flow chain for 105_31 and 105_32
                            for diag_name in ("105_31", "105_32"):
                                if diag_name in fen1_entries:
                                    start = fen1_entries[diag_name]["value"]
                                    print(f"[BeedleSF-Diag] Flow chain for {diag_name} starting at flow[{start}]:")
                                    idx = start
                                    visited_diag = set()
                                    step = 0
                                    while idx >= 0 and idx < len(flows) and idx not in visited_diag and step < 15:
                                        visited_diag.add(idx)
                                        node = flows[idx]
                                        print(f"[BeedleSF-Diag]   [{step}] flow[{idx}]: type={node['type']} sub={node['subType']} p1={node['param1']} p2={node['param2']} p3={node['param3']} p4={node['param4']} p5={node['param5']} next={node.get('next', -1)}")
                                        if node["type"] in ("type3", "type1", "start"):
                                            idx = node.get("next", -1)
                                        else:
                                            print(f"[BeedleSF-Diag]   (switch/branch at flow[{idx}], stopping linear traversal)")
                                            break
                                        step += 1

                            print(f"[BeedleSF] Injected {injected_count}/{len(BEEDLE_PURCHASE_STORYFLAGS)} purchase storyflags into 105-Terry.msbf (start-next redirect)")

                        if msbf_file_name == "003-ItemGet.msbf":
                            handle_progressive_items(parsed_msbf)

                        event_arc.set_file_data(event_file_path, build_msb(parsed_msbf))
            except Exception as e:
                if mod:
                    e.add_note(
                        f'This was caused by the "{mod}" mod. This mod is currently incompatible with the randomizer.'
                    )
                raise e

            write_bytes_create_dirs(modified_event_path, event_arc.build_U8())

            patched_event_file_count = event_paths.index(event_path)
            progress_value = get_progress_value_from_range(
                90, 6, patched_event_file_count, total_event_file_count
            )
            update_progress_value(progress_value)

    def create_flow_label_to_index_mapping(
        self,
        flow_patches: list[dict],
        msbf: ParsedMsb,
        onlyif_handler: ConditionalPatchHandler,
    ):
        self.flow_label_to_index_mapping = {}
        next_index = len(msbf["FLW3"]["flow"])

        for flow_add in filter(
            lambda patch: patch["type"] in FLOW_ADD_VARIATIONS + SWITCH_ADD_VARIATIONS,
            flow_patches,
        ):
            if statement := flow_add.get("onlyif", False):
                if not onlyif_handler.evaluate_onlyif(statement):
                    continue

            self.flow_label_to_index_mapping[flow_add["name"]] = next_index
            next_index += 1

    def flow_add(self, msbf: ParsedMsb, flow_add: dict):
        assert (
            len(msbf["FLW3"]["flow"])
            == self.flow_label_to_index_mapping[flow_add["name"]]
        ), f"Index must be the next value in the flow, expected {len(msbf['FLW3']['flow'])} got {self.flow_label_to_index_mapping[flow_add['name']]}"

        if flow_add["type"] in DEFAULT_FLOW_TYPE_LOOKUP:
            new_flow = DEFAULT_FLOW_TYPE_LOOKUP[flow_add["type"]].copy()
        else:
            print(
                f"ERROR: Unhandled type {flow_add['type']} in flowadd {flow_add['name']}, did you forget to add type to lookup in patchconstants.py?"
            )
            return

        for prop, value in flow_add["flow"].items():
            if prop == "next" and not isinstance(value, int):
                flow_index = self.flow_label_to_index_mapping.get(value, None)

                if flow_index is None:
                    raise EventPatchError(
                        f"Flow label \"{value}\" not found in file.\nPatch: {flow_add['name']}."
                    )

                value = flow_index

            if prop == "param4" and not isinstance(value, int):
                flow_index = self.text_label_to_index_mapping.get(value, None)

                if flow_index is None:
                    raise Exception(
                        f"Text with label '{value}' not found.\nError caused by this patch: {flow_add['name']}.\nDid you forget to add a 'textadd' patch for this text?"
                    )

                value = flow_index
            # handle macro properties
            if prop in PARAM1_ALIASES:
                new_flow["param1"] = value
                continue

            if prop in PARAM2_ALIASES:
                new_flow["param2"] = value
                continue

            new_flow[prop] = value

        if flow_add["type"] in FLOW_ADD_VARIATIONS:
            msbf["FLW3"]["flow"].append(new_flow)
        elif flow_add["type"] in SWITCH_ADD_VARIATIONS:
            new_flow["type"] = "switch"
            cases = flow_add["cases"]

            for i, _ in enumerate(cases):
                value = cases[i]

                if not isinstance(value, int):
                    flow_index = self.flow_label_to_index_mapping.get(value, None)
                    if flow_index is None:
                        raise EventPatchError(
                            f"Flow label \"{value}\" not found in file.\nPatch: {flow_add['name']}."
                        )

                    cases[i] = flow_index

            add_msbf_branch(msbf=msbf, switch=new_flow, branchpoints=cases)

    def flow_patch(self, msbf: ParsedMsb, flow_patch: dict):
        flow_object = msbf["FLW3"]["flow"][flow_patch["index"]]

        for prop, value in flow_patch.get("flow", {}).items():
            if prop == "next" and not isinstance(value, int):
                flow_index = self.flow_label_to_index_mapping.get(value, None)

                if flow_index is None:
                    raise EventPatchError(
                        f"Flow label \"{value}\" not found in file.\nPatch: {flow_patch['name']}."
                    )

                value = flow_index

            if prop == "param4" and not isinstance(value, int):
                flow_index = self.text_label_to_index_mapping.get(value, None)

                if flow_index is None:
                    raise Exception(
                        f"Text with label '{value}' not found.\nError caused by this patch: {flow_patch['name']}.\nDid you forget to add a 'textadd' patch for this text?"
                    )

                value = flow_index

            flow_object[prop] = value

        if flow_object["type"] == "switch":
            cases = flow_patch.get("cases", None)

            if cases:
                assert len(cases) == flow_object["param4"]
                branch_start = flow_object["param5"]

                for i, case in enumerate(cases):
                    if not isinstance(case, int):
                        case = self.flow_label_to_index_mapping.get(case, None)

                        if case is None:
                            raise EventPatchError(
                                f"Flow label \"{case}\" not found in file.\nPatch: {flow_patch['name']}."
                            )

                    msbf["FLW3"]["branch_points"][branch_start + i] = case

    def entry_add(self, msbf: ParsedMsb, entry_add: dict):
        value = entry_add["entry"]["value"]

        if not isinstance(value, int):
            flow_index = self.flow_label_to_index_mapping.get(value, None)

            if flow_index is None:
                raise EventPatchError(
                    f"Flow label \"{value}\" not found in file.\nPatch: {entry_add['entry']}."
                )

            value = flow_index

        new_entry = {
            "name": entry_add["entry"]["name"],
            "value": value,
        }
        entry_point_hash = entrypoint_hash(
            entry_add["entry"]["name"], len(msbf["FEN1"])
        )
        bucket = msbf["FEN1"][entry_point_hash]
        for existing_entry in bucket:
            if existing_entry.get("name") == new_entry["name"]:
                existing_entry["value"] = new_entry["value"]
                return
        bucket.append(new_entry)

    def text_add(self, msbt: ParsedMsb, text_add: dict, msbt_file_name: str, lang: str):
        text_index = len(msbt["TXT2"])
        self.text_label_to_index_mapping[text_add["name"]] = text_index
        msbt["TXT2"].append(
            process_control_sequences(get_text_data(text_add["name"]).get(lang)).encode(
                "utf-16be"
            )
        )

        # Had to add a 0 to the end to satisfy BuildMSB's length requirement, if text adds end up breaking, this may be overwriting a param?
        msbt["ATR1"].append(
            [text_add.get("textboxtype", 1), text_add.get("unk2", 0), 0]
        )
        entry_name = "%s:%d" % (msbt_file_name[-3:], text_index)
        new_entry = {
            "name": entry_name,
            "value": text_index,
        }
        entry_point_hash = entrypoint_hash(entry_name, len(msbt["LBL1"]))
        msbt["LBL1"][entry_point_hash].append(new_entry)

    def text_patch(self, msbt: ParsedMsb, text_patch: dict, lang: str):
        msbt["TXT2"][text_patch["index"]] = process_control_sequences(
            get_text_data(text_patch["name"]).get(lang)
        ).encode("utf-16be")

        # Allow patching other textbox data
        current_text_atr1_data = msbt["ATR1"][text_patch["index"]]

        if (textbox_type := text_patch.get("textboxtype", None)) is not None:
            current_text_atr1_data[0] = textbox_type
        if (unk2 := text_patch.get("unk2", None)) is not None:
            current_text_atr1_data[1] = unk2

        msbt["ATR1"][text_patch["index"]] = current_text_atr1_data

    def add_check_patch(self, event_file: str, eventid: str, itemid: int, trapid: int, custom_flag: int):
        self.check_patches[event_file].append((eventid, itemid, trapid, custom_flag))


def make_progressive_item_events(
    msbf: ParsedMsb,
    base_item_start: int,
    item_text_indexes: tuple,
    itemids: list,
    storyflags: list,
):
    if len(item_text_indexes) != len(itemids) or len(item_text_indexes) != len(
        storyflags
    ):
        raise Exception(
            "item_text_indexes must be the same length as itemids and storyflags to make a progressive item"
        )

    flow_index = len(msbf["FLW3"]["flow"])
    msbf["FLW3"]["flow"][base_item_start]["next"] = flow_index

    for index in range(len(item_text_indexes) - 1, 0, -1):
        branch = DEFAULT_FLOW_TYPE_LOOKUP["checkstoryflag"].copy()
        branch["param2"] = storyflags[index - 1]
        add_msbf_branch(
            msbf=msbf, switch=branch, branchpoints=[(flow_index + 1), (flow_index + 3)]
        )

        event = DEFAULT_FLOW_TYPE_LOOKUP["giveitem"].copy()
        event["param2"] = itemids[index]
        event["next"] = flow_index + 2
        msbf["FLW3"]["flow"].append(event)

        event = DEFAULT_FLOW_TYPE_LOOKUP["setstoryflag"].copy()
        event["param2"] = storyflags[index]
        event["next"] = item_text_indexes[index]
        msbf["FLW3"]["flow"].append(event)

        flow_index += 3

    event = DEFAULT_FLOW_TYPE_LOOKUP["setstoryflag"].copy()
    event["param2"] = storyflags[0]
    event["next"] = item_text_indexes[0]
    msbf["FLW3"]["flow"].append(event)


def handle_progressive_items(msbf: ParsedMsb):
    # Progressive Mitts
    make_progressive_item_events(
        msbf,
        93,
        (35, 231),
        ITEM_ITEMFLAGS[PROGRESSIVE_MITTS],
        ITEM_STORYFLAGS[PROGRESSIVE_MITTS],
    )

    # Progressive Swords
    make_progressive_item_events(
        msbf,
        136,
        (77, 608, 75, 78, 74, 73),
        ITEM_ITEMFLAGS[PROGRESSIVE_SWORD],
        ITEM_STORYFLAGS[PROGRESSIVE_SWORD],
    )

    # Progressive Beetles
    make_progressive_item_events(
        msbf,
        96,
        (38, 178, 177, 176),
        ITEM_ITEMFLAGS[PROGRESSIVE_BEETLE],
        ITEM_STORYFLAGS[PROGRESSIVE_BEETLE],
    )

    # Progressive Bows
    make_progressive_item_events(
        msbf,
        127,
        (68, 163, 162),
        ITEM_ITEMFLAGS[PROGRESSIVE_BOW],
        ITEM_STORYFLAGS[PROGRESSIVE_BOW],
    )

    # Progressive Slingshots
    make_progressive_item_events(
        msbf,
        97,
        (39, 237),
        ITEM_ITEMFLAGS[PROGRESSIVE_SLINGSHOT],
        ITEM_STORYFLAGS[PROGRESSIVE_SLINGSHOT],
    )

    # Progressive Bug Nets
    make_progressive_item_events(
        msbf,
        20,
        (18, 309),
        ITEM_ITEMFLAGS[PROGRESSIVE_BUG_NET],
        ITEM_STORYFLAGS[PROGRESSIVE_BUG_NET],
    )

    # Progressive Pouches
    make_progressive_item_events(
        msbf,
        258,
        (254, 253, 253, 253, 253),
        ITEM_ITEMFLAGS[PROGRESSIVE_POUCH],
        ITEM_STORYFLAGS[PROGRESSIVE_POUCH],
    )

    # Progressive Wallets
    make_progressive_item_events(
        msbf,
        250,
        (246, 245, 244, 255),
        ITEM_ITEMFLAGS[PROGRESSIVE_WALLET],
        ITEM_STORYFLAGS[PROGRESSIVE_WALLET],
    )

    # Song of the Hero parts
    make_progressive_item_events(
        msbf,
        474,
        (472, 471, 475, 477),
        ITEM_ITEMFLAGS[SOTH_PART],
        ITEM_STORYFLAGS[SOTH_PART],
    )


def entrypoint_hash(name: str, entries: int) -> int:
    hash = 0

    for char in name:
        hash = (hash * 0x492 + ord(char)) & 0xFFFFFFFF

    return hash % entries
