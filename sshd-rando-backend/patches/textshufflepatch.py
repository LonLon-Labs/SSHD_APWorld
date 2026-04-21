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
    "003-ItemGet",  # Item get text
    "006-8KenseiNormal",  # Fi hints/notes/required dungeons
    "008-System",  # System messages
    "101-Shop",  # Shop text
    "105-Terry",  # Beedle's Airshop text
    "107-Kanban",  # Signs/bulletin boards
}


def _parse_segments(raw: bytes) -> list[tuple[str, bytes]]:
    """Parse TXT2 raw UTF-16BE bytes into text and control segments.

    Returns a list of ``('text', bytes)`` or ``('ctrl', bytes)`` tuples.

    Control sequences begin with the 0x000E code-unit and are self-delimiting:
    ``[0x000E][group:u16][type:u16][data_len:u16][data]``.
    The 0x000F code-unit is a two-byte reset marker.
    """
    segments: list[tuple[str, bytes]] = []
    i = 0
    text_start = 0
    length = len(raw)

    while i + 1 < length:
        cp = (raw[i] << 8) | raw[i + 1]
        if cp == 0x000E:
            # flush pending text
            if i > text_start:
                segments.append(("text", raw[text_start:i]))
            ctrl_start = i
            i += 6  # marker(2) + group(2) + type(2)
            if i + 1 < length:
                data_len = (raw[i] << 8) | raw[i + 1]
                i += 2 + data_len  # data_len field(2) + data bytes
            segments.append(("ctrl", raw[ctrl_start:i]))
            text_start = i
        elif cp == 0x000F:
            if i > text_start:
                segments.append(("text", raw[text_start:i]))
            segments.append(("ctrl", raw[i : i + 2]))
            i += 2
            text_start = i
        else:
            i += 2

    if text_start < length:
        segments.append(("text", raw[text_start:]))

    return segments


def _extract_plain_text(raw: bytes) -> str:
    """Return only the human-readable text from a TXT2 entry (controls stripped)."""
    text_bytes = b"".join(d for kind, d in _parse_segments(raw) if kind == "text")
    return text_bytes.decode("utf-16be", errors="replace").rstrip("\0")


def _rebuild_with_new_text(original_raw: bytes, new_text: str) -> bytes:
    """Replace readable text in a TXT2 entry while preserving all control sequences.

    The *new_text* is distributed proportionally across the original entry's
    text-segment positions so that control sequences (colours, choices,
    variable substitutions, animations, etc.) remain at their structural
    offsets.
    """
    segments = _parse_segments(original_raw)
    text_indices = [i for i, (kind, _) in enumerate(segments) if kind == "text"]

    if not text_indices:
        return original_raw

    orig_char_counts = [len(segments[i][1]) // 2 for i in text_indices]
    total_orig = sum(orig_char_counts)

    if total_orig == 0:
        return original_raw

    result = list(segments)
    char_pos = 0

    for seg_num, seg_idx in enumerate(text_indices):
        if seg_num < len(text_indices) - 1:
            share = max(
                1, round(len(new_text) * orig_char_counts[seg_num] / total_orig)
            )
            chunk = new_text[char_pos : char_pos + share]
            char_pos += share
        else:
            # last segment gets the remainder
            chunk = new_text[char_pos:]

        result[seg_idx] = ("text", chunk.encode("utf-16be"))

    return b"".join(d for _, d in result)


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences/paragraphs for structure-preserving shuffle."""
    # Split on sentence-ending punctuation followed by space/newline, or on double newlines
    parts = re.split(r"(?<=[.!?])\s+|\n\n+", text)
    return [p for p in parts if p.strip()]


def _shuffle_preserving_structure(texts: list[str], rng: random.Random) -> list[str]:
    """
    Shuffle sentences across entries while keeping per-entry sentence counts.
    """
    all_sentences: list[str] = []
    entry_sentence_counts: list[int] = []

    for text in texts:
        sentences = _split_sentences(text)
        entry_sentence_counts.append(max(1, len(sentences)))
        all_sentences.extend(sentences)

    rng.shuffle(all_sentences)

    result: list[str] = []
    idx = 0
    for count in entry_sentence_counts:
        if idx >= len(all_sentences):
            result.append("")
            continue

        chunk = all_sentences[idx : idx + count]
        idx += count
        result.append("\n".join(chunk))

    return result


def _shuffle_full(texts: list[str], rng: random.Random) -> list[str]:
    """Fully shuffle text entries - simple permutation."""
    shuffled = list(texts)
    rng.shuffle(shuffled)
    return shuffled


def _collect_texts_from_language(
    lang_id: str,
    output_dir,
    other_mods: list[str],
    protected_stems: set[str] | None = None,
) -> list[tuple[str, str, int, str]]:
    """
    Collect plain-text content from a language's MSBT files.

    Returns list of (arc_filename, msbt_path, text_index, plain_text_str).
    Control sequences are stripped from the returned text.
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

    entries: list[tuple[str, str, int, str]] = []

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
                plain = _extract_plain_text(text_bytes)
                if not plain.strip():
                    continue
                entries.append((event_path.name, event_file_path, i, plain))

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

    # Collect plain-text strings (control sequences stripped)
    all_texts: list[str] = []
    for src_lang in source_lang_ids:
        entries = _collect_texts_from_language(
            src_lang, output_dir, other_mods, protected
        )
        all_texts.extend(text for _, _, _, text in entries)

    print(
        f"[TextShuffle] Collected {len(all_texts)} text entries from {len(source_lang_ids)} languages"
    )
    if not all_texts:
        return

    # Shuffle the plain text strings
    if preserve_structure:
        shuffled_texts = _shuffle_preserving_structure(all_texts, rng)
    else:
        shuffled_texts = _shuffle_full(all_texts, rng)

    # Apply shuffled text back, preserving original control sequences
    _apply_shuffled_to_output(
        lang_id,
        output_dir,
        shuffled_texts,
        protected,
    )
    print(f"[TextShuffle] Applied {len(shuffled_texts)} shuffled entries to {lang_id}")


def _apply_shuffled_to_output(
    lang_id: str,
    output_dir,
    shuffled_pool: list[str],
    protected_stems: set[str] | None,
):
    """
    Write shuffled text into the active language's output MSBT files.

    For each eligible TXT2 entry the readable text is replaced with the next
    string from *shuffled_pool* while all MSBT control sequences (colours,
    choices, variables, animations, etc.) are preserved in their original
    structural positions.
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
                original_raw = parsed_msbt["TXT2"][i]
                plain = _extract_plain_text(original_raw)
                if not plain.strip():
                    continue

                if pool_idx < len(shuffled_pool):
                    parsed_msbt["TXT2"][i] = _rebuild_with_new_text(
                        original_raw, shuffled_pool[pool_idx]
                    )
                    pool_idx += 1
                    msbt_modified = True

            if msbt_modified:
                event_arc.set_file_data(event_file_path, build_msb(parsed_msbt))
                modified = True

        if modified:
            write_bytes_create_dirs(event_path, event_arc.build_U8())
