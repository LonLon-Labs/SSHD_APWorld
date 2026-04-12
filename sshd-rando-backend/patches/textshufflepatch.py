"""
Text Shuffle Patch - Shuffles in-game text entries within MSBT files.

Modes:
  off              - No shuffling
  baby             - English only, shop/important text protected
  crazy            - All English text shuffled (sentences/paragraphs preserved)
  extreme          - All English text fully shuffled
  european_extreme - All Latin-script language text shuffled (sentences/paragraphs preserved)
  psychopath       - All Latin-script language text fully shuffled
"""

import random
import re

from constants.patchconstants import LANGUAGE_NAME_TO_FILE_ID
from filepathconstants import VANILLA_EVENT_FILE_PATHS
from gui.dialogs.dialog_header import print_progress_text
from logic.settings import SettingGet
from logic.world import World
from sslib.msb import ParsedMsb, parse_msb, build_msb
from sslib.u8file import U8File
from sslib.utils import write_bytes_create_dirs

# Latin-script language IDs (exclude zh_CN, ja_JP, ko_KR, ru_RU, zh_TW)
LATIN_LANGUAGE_IDS = {
    "en_US",
    "en_GB",
    "fr_FR",
    "fr_US",
    "de_DE",
    "it_IT",
    "nl_NL",
    "es_ES",
    "es_US",
}

ENGLISH_LANGUAGE_IDS = {
    "en_US",
    "en_GB",
}

# MSBT files that contain shop/functional text to protect in "baby" mode.
# These file stems (without .msbt extension) contain NPC dialogue for shops,
# item descriptions, or other gameplay-critical text.
PROTECTED_MSBT_STEMS = {
    "003-ItemGet",          # Item get text
    "006-8KenseiNormal",    # Fi hints/notes/required dungeons
    "008-System",           # System messages
    "101-Shop",             # Shop text
    "105-Terry",            # Beedle's Airshop text
    "107-Kanban",           # Signs/bulletin boards
}


def _decode_utf16be_safe(data: bytes) -> str:
    """Decode UTF-16BE bytes, stripping null terminators."""
    try:
        return data.decode("utf-16be").rstrip("\0")
    except Exception:
        return ""


def _is_control_sequence_heavy(text: str) -> bool:
    """Check if text is mostly control sequences (not human-readable)."""
    if not text:
        return True
    # Control chars in range 0x0E are MSBT control sequences
    control_count = sum(1 for c in text if ord(c) < 0x20 and c not in "\n\r")
    total = len(text)
    if total == 0:
        return True
    return control_count / total > 0.5


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences/paragraphs for structure-preserving shuffle."""
    # Split on sentence-ending punctuation followed by space/newline, or on double newlines
    parts = re.split(r"(?<=[.!?])\s+|\n\n+", text)
    return [p for p in parts if p.strip()]


def _shuffle_preserving_structure(texts: list[bytes], rng: random.Random) -> list[bytes]:
    """
    Shuffle text entries while preserving sentence/paragraph structure.
    Extracts sentences from all entries, shuffles them, then redistributes
    back maintaining the original entry count and approximate structure.
    """
    decoded = []
    entry_sentence_counts = []

    for raw in texts:
        text = _decode_utf16be_safe(raw)
        sentences = _split_sentences(text)
        entry_sentence_counts.append(max(1, len(sentences)))
        decoded.extend(sentences)

    rng.shuffle(decoded)

    # Redistribute sentences back into entries
    result = []
    idx = 0
    for count in entry_sentence_counts:
        if idx >= len(decoded):
            # Ran out of sentences, use empty string
            result.append("".encode("utf-16be"))
            continue

        chunk = decoded[idx : idx + count]
        idx += count
        combined = "\n".join(chunk)
        result.append(combined.encode("utf-16be"))

    return result


def _shuffle_full(texts: list[bytes], rng: random.Random) -> list[bytes]:
    """Fully shuffle text entries - just permute the entire list."""
    shuffled = list(texts)
    rng.shuffle(shuffled)
    return shuffled


def _collect_texts_from_language(
    lang_id: str,
    output_dir,
    other_mods: list[str],
    protected_stems: set[str] | None = None,
) -> list[tuple[str, str, int, bytes]]:
    """
    Collect all text entries from a language's MSBT files in the output directory.

    Returns list of (arc_filename, msbt_event_file_path, text_index, raw_text_bytes).
    If protected_stems is set, entries from those files are excluded.
    """
    from filepathconstants import EVENT_FILE_PATH_TAILS

    # Find the output path for this language
    output_event_path = None
    for tail in EVENT_FILE_PATH_TAILS:
        if tail.name == lang_id:
            output_event_path = output_dir / tail
            break

    if output_event_path is None or not output_event_path.exists():
        # Fall back to vanilla files if output doesn't exist for this language
        if lang_id not in VANILLA_EVENT_FILE_PATHS:
            return []
        output_event_path = VANILLA_EVENT_FILE_PATHS[lang_id]

    entries = []

    for event_path in sorted(output_event_path.glob("*.arc")):
        try:
            event_arc = U8File.get_parsed_U8_from_path(event_path)
        except Exception:
            continue

        for event_file_path in filter(
            lambda name: name[-1] == "t", event_arc.get_all_paths()
        ):
            msbt_file_name = event_file_path.split("/")[-1]
            stem = msbt_file_name[:-5]  # Remove .msbt

            if protected_stems and stem in protected_stems:
                continue

            msbt_data = event_arc.get_file_data(event_file_path)
            if not msbt_data:
                continue

            try:
                parsed_msbt = parse_msb(msbt_data)
            except Exception:
                continue

            for i, text_bytes in enumerate(parsed_msbt["TXT2"]):
                text_str = _decode_utf16be_safe(text_bytes)
                # Skip empty or control-sequence-heavy entries
                if not text_str.strip() or _is_control_sequence_heavy(text_str):
                    continue
                entries.append((event_path.name, event_file_path, i, text_bytes))

    return entries


def apply_text_shuffle(
    world: World,
    output_dir,
    other_mods: list[str],
    language: SettingGet,
):
    """
    Apply text shuffle based on the world's text_shuffle setting.
    This runs AFTER dynamic text patches and event patches have been applied.
    It reads the patched output files and shuffles text in-place.
    """
    shuffle_mode = world.setting("text_shuffle").value()
    if shuffle_mode == "off":
        return

    print_progress_text("Shuffling Text")
    print(f"[TextShuffle] Shuffle mode: {shuffle_mode}")

    # Use the world's seed for deterministic shuffling
    seed_str = world.config.seed if hasattr(world.config, "seed") else "textshuffle"
    rng = random.Random(f"text_shuffle_{seed_str}")

    lang_id = LANGUAGE_NAME_TO_FILE_ID[language.value()]

    # Determine which languages to pull text from
    if shuffle_mode in ("baby", "crazy", "extreme"):
        source_lang_ids = ENGLISH_LANGUAGE_IDS & {lang_id}
        if not source_lang_ids:
            source_lang_ids = {lang_id} if lang_id in ENGLISH_LANGUAGE_IDS else set()
            if not source_lang_ids:
                return  # Non-English language selected with English-only mode
    elif shuffle_mode in ("european_extreme", "psychopath"):
        source_lang_ids = LATIN_LANGUAGE_IDS
    else:
        return

    preserve_structure = shuffle_mode in ("crazy", "european_extreme")
    protected = PROTECTED_MSBT_STEMS if shuffle_mode == "baby" else None

    # Collect all eligible text entries from source languages
    all_text_bytes = []
    for src_lang in source_lang_ids:
        entries = _collect_texts_from_language(
            src_lang, output_dir, other_mods, protected
        )
        all_text_bytes.extend(raw for _, _, _, raw in entries)

    print(f"[TextShuffle] Collected {len(all_text_bytes)} text entries from {len(source_lang_ids)} languages")
    if not all_text_bytes:
        return

    # Shuffle the collected texts
    if preserve_structure:
        shuffled_texts = _shuffle_preserving_structure(all_text_bytes, rng)
    else:
        shuffled_texts = _shuffle_full(all_text_bytes, rng)

    # Now apply shuffled text back to the active language's output files
    _apply_shuffled_to_output(
        lang_id, output_dir, shuffled_texts, protected,
    )
    print(f"[TextShuffle] Applied {len(shuffled_texts)} shuffled entries to {lang_id}")


def _apply_shuffled_to_output(
    lang_id: str,
    output_dir,
    shuffled_pool: list[bytes],
    protected_stems: set[str] | None,
):
    """
    Apply shuffled text to the output MSBT files for the active language.
    Reads the already-patched output files, replaces eligible text entries
    with shuffled text from the pool, and writes them back.
    """
    from filepathconstants import EVENT_FILE_PATH_TAILS

    # Find the output path for this language
    output_event_path = None
    for tail in EVENT_FILE_PATH_TAILS:
        if tail.name == lang_id:
            output_event_path = output_dir / tail
            break

    if output_event_path is None or not output_event_path.exists():
        return

    pool_idx = 0

    for event_path in sorted(output_event_path.glob("*.arc")):
        try:
            event_arc = U8File.get_parsed_U8_from_path(event_path)
        except Exception:
            continue

        modified = False

        for event_file_path in filter(
            lambda name: name[-1] == "t", event_arc.get_all_paths()
        ):
            msbt_file_name = event_file_path.split("/")[-1]
            stem = msbt_file_name[:-5]

            if protected_stems and stem in protected_stems:
                continue

            msbt_data = event_arc.get_file_data(event_file_path)
            if not msbt_data:
                continue

            try:
                parsed_msbt = parse_msb(msbt_data)
            except Exception:
                continue

            msbt_modified = False

            for i in range(len(parsed_msbt["TXT2"])):
                text_str = _decode_utf16be_safe(parsed_msbt["TXT2"][i])
                if not text_str.strip() or _is_control_sequence_heavy(text_str):
                    continue

                if pool_idx < len(shuffled_pool):
                    parsed_msbt["TXT2"][i] = shuffled_pool[pool_idx]
                    pool_idx += 1
                    msbt_modified = True

            if msbt_modified:
                event_arc.set_file_data(event_file_path, build_msb(parsed_msbt))
                modified = True

        if modified:
            write_bytes_create_dirs(event_path, event_arc.build_U8())


