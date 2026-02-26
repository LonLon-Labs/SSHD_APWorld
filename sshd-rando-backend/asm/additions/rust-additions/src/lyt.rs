#![allow(non_camel_case_types)]
#![allow(non_snake_case)]
#![allow(unused)]

use crate::debug;
use crate::flag;
use crate::input;
use crate::item;
use crate::savefile;
use crate::settings;

use core::arch::asm;
use core::ffi::{c_char, c_int, c_void};
use static_assertions::assert_eq_size;
use wchar::wch;

// repr(C) prevents rust from reordering struct fields.
// packed(1) prevents rust from aligning structs to the size of the largest
// field.

// Using u64 or 64bit pointers forces structs to be 8-byte aligned.
// The vanilla code seems to be 4-byte aligned. To make extra sure, used
// packed(1) to force the alignment to match what you define.

// Always add an assert_eq_size!() macro after defining a struct to ensure it's
// the size you expect it to be.

// Lyt stuff
#[repr(C, packed(1))]
pub struct dLytMsgWindow {
    pub _0:       [u8; 0xA90],
    pub text_mgr: *mut TextMgr,
}
assert_eq_size!([u8; 0xA98], dLytMsgWindow);

#[repr(C, packed(1))]
pub struct dLytPauseDisp {
    pub _0:        [u8; 0xC5E],
    pub is_paused: bool,
    pub _1:        [u8; 0x11],
}
assert_eq_size!([u8; 0xC70], dLytPauseDisp);

// Text stuff
#[repr(C, packed(1))]
pub struct TextMgr {
    pub _0:                 [u8; 0x8AC],
    pub numeric_args:       [u32; 10],
    pub num_args_copy:      [u32; 10],
    pub _1:                 [u8; 0x20],
    pub vertical_scale:     f32,
    pub cursor_pos_y:       f32,
    pub msg_window_subtype: u8,
    pub _2:                 [u8; 0xCF],
    pub command_insert:     i32,
    pub string_args:        [[u16; 64]; 4],
}
assert_eq_size!([u8; 0xBF8], TextMgr);

// IMPORTANT: when using vanilla code, the start point must be declared in
// symbols.yaml and then added to this extern block.
extern "C" {
    static mut CURRENT_STAGE_NAME: [u8; 8];
    static dManager__sInstance: *mut c_void;
    static GLOBAL_TEXT_MGR: *mut TextMgr;
    static FILE_MGR: *mut savefile::FileMgr;
    static RANDOMIZER_SETTINGS: settings::RandomizerSettings;

    // Functions
    fn debugPrint_32(string: *const c_char, fstr: *const c_char, ...);
    fn set_string_arg(text_mgr: *mut TextMgr, arg: *const c_void, arg_num: u32);
    fn getTextMessageByLabel(
        param1: *mut c_void,
        param2: *mut c_void,
        param3: u32,
        param4: u32,
        param5: u32,
    ) -> *mut c_void;
    fn eventFlowTextProcessingRelated(
        param1: *mut c_void,
        param2: *mut c_void,
        text_string: *mut c_void,
        buffer: *mut c_void,
        buffer_size: i32,
        param6: u64,
    );
    fn get_msb_text_maybe(msbt_info: *mut c_void, tutorial_text_name: *mut c_void) -> *mut c_void;
    fn dLytHelp__stateNoneUpdate(dLytHelp: *mut c_void);
}

// IMPORTANT: when adding functions here that need to get called from the game,
// add `#[no_mangle]` and add a .global *symbolname* to
// additions/rust-additions.asm

#[no_mangle]
pub extern "C" fn set_top_dowsing_icon() -> u32 {
    unsafe {
        if &CURRENT_STAGE_NAME[..5] == b"F103\0" {
            return 0x11; // Tadtones
        }
        if flag::check_storyflag(271) != 0 {
            return 0x12; // Sandship
        }
        return 0x13; // Zelda
    }
}

const COMPLETE_TEXT: *const c_void = wch!(u16, "Completed\0").as_ptr() as *const c_void;
const INCOMPLETE_TEXT: *const c_void = wch!(u16, "Incomplete\0").as_ptr() as *const c_void;
const OBTAINED_TEXT: *const c_void = wch!(u16, "Obtained\0").as_ptr() as *const c_void;
const NOT_OBTAINED_TEXT: *const c_void = wch!(u16, "Not Obtained\0").as_ptr() as *const c_void;

#[no_mangle]
pub extern "C" fn __set_dungeon_string_and_numeric_args(complete_storyflag: u16, sceneindex: u16) {
    unsafe {
        // Check if dungeon is complete
        if flag::check_storyflag(complete_storyflag) == 0 {
            set_string_arg(GLOBAL_TEXT_MGR, INCOMPLETE_TEXT, 0)
        } else {
            set_string_arg(GLOBAL_TEXT_MGR, COMPLETE_TEXT, 0)
        }

        // If don't have boss key and haven't placed boss key
        if flag::check_global_dungeonflag(sceneindex, 7) == 0
            && flag::check_global_dungeonflag(sceneindex, 8) == 0
        {
            set_string_arg(GLOBAL_TEXT_MGR, NOT_OBTAINED_TEXT, 1)
        } else {
            set_string_arg(GLOBAL_TEXT_MGR, OBTAINED_TEXT, 1)
        }

        // Small Keys
        (*GLOBAL_TEXT_MGR).numeric_args[0] =
            ((*FILE_MGR).FA.dungeonflags[sceneindex as usize][1] & 0xF) as u32;
        (*GLOBAL_TEXT_MGR).numeric_args[1] =
            (((*FILE_MGR).FA.dungeonflags[sceneindex as usize][1] >> 4) & 0xF) as u32;

        // Map
        if flag::check_global_dungeonflag(sceneindex, 1) == 0 {
            set_string_arg(GLOBAL_TEXT_MGR, NOT_OBTAINED_TEXT, 2)
        } else {
            set_string_arg(GLOBAL_TEXT_MGR, OBTAINED_TEXT, 2)
        }
    }
}

#[no_mangle]
pub extern "C" fn check_help_index_bounds(dLytHelp: *mut c_void, mut help_index: u32) {
    if help_index <= 0x39 {
        help_index = 0x3A;
    }

    unsafe {
        asm!("mov x0, {0:x}", in(reg) dLytHelp);
        asm!("mov w1, {0:w}", in(reg) help_index);
    }
}

// ============================================================================
// UTF-16 string builder for composing help text at runtime
// ============================================================================
struct WStrBuf {
    buf: [u16; 64],
    pos: usize,
}

impl WStrBuf {
    fn new() -> Self {
        WStrBuf {
            buf: [0u16; 64],
            pos: 0,
        }
    }

    fn push_wstr(&mut self, s: &[u16]) {
        for &c in s {
            if c == 0 || self.pos >= 63 {
                break;
            }
            self.buf[self.pos] = c;
            self.pos += 1;
        }
    }

    fn push_u32(&mut self, val: u32) {
        if val == 0 {
            if self.pos < 63 {
                self.buf[self.pos] = b'0' as u16;
                self.pos += 1;
            }
            return;
        }
        let mut digits = [0u16; 10];
        let mut n = val;
        let mut count = 0;
        while n > 0 {
            digits[count] = b'0' as u16 + (n % 10) as u16;
            n /= 10;
            count += 1;
        }
        for i in (0..count).rev() {
            if self.pos < 63 {
                self.buf[self.pos] = digits[i];
                self.pos += 1;
            }
        }
    }

    fn as_ptr(&self) -> *const c_void {
        self.buf.as_ptr() as *const c_void
    }
}

// Helper: set a string arg from a WStrBuf
unsafe fn set_wstr_arg(buf: &WStrBuf, arg_num: u32) {
    set_string_arg(GLOBAL_TEXT_MGR, buf.as_ptr(), arg_num);
}

// Helper: compose "Label: Obtained/Not Obtained" into a WStrBuf
fn compose_obtained_line(label: &[u16], obtained: bool) -> WStrBuf {
    let mut buf = WStrBuf::new();
    buf.push_wstr(label);
    if obtained {
        buf.push_wstr(wch!(u16, "Obtained\0"));
    } else {
        buf.push_wstr(wch!(u16, "Not Obtained\0"));
    }
    buf
}

// Helper: compose "Label: X, Found Y/Z" into a WStrBuf
fn compose_keys_line(label: &[u16], held: u32, found: u32, total: u32) -> WStrBuf {
    let mut buf = WStrBuf::new();
    buf.push_wstr(label);
    buf.push_u32(held);
    buf.push_wstr(wch!(u16, ", Found \0"));
    buf.push_u32(found);
    buf.push_wstr(wch!(u16, "/\0"));
    buf.push_u32(total);
    buf
}

// Helper: compose "Label: X / Y" into a WStrBuf
fn compose_count_line(label: &[u16], count: u32, total: u32) -> WStrBuf {
    let mut buf = WStrBuf::new();
    buf.push_wstr(label);
    buf.push_u32(count);
    buf.push_wstr(wch!(u16, " / \0"));
    buf.push_u32(total);
    buf
}

/// Set the string args for page 0x3D (Sky Keep, Items, Gorge).
/// All content is now composed as full strings via string args 0-3.
unsafe fn set_help_page_3d_args(help_number: u32) {
    match help_number {
        1 => {
            // Title: Sky Keep
            let title = WStrBuf {
                buf: {
                    let mut b = [0u16; 64];
                    let s = wch!(u16, "Sky Keep\0");
                    let mut i = 0;
                    while i < s.len() && s[i] != 0 {
                        b[i] = s[i];
                        i += 1;
                    }
                    b
                },
                pos: 0,
            };
            set_string_arg(GLOBAL_TEXT_MGR, title.as_ptr(), 3);

            // Line 0: Status
            let sk_scenflag = RANDOMIZER_SETTINGS.sky_keep_beaten_sceneflag;
            let complete = if sk_scenflag != -1 {
                flag::check_global_sceneflag(20, sk_scenflag as u16) != 0
            } else {
                true
            };
            let line0 = compose_obtained_line(wch!(u16, "Status: \0"), complete);
            set_wstr_arg(&line0, 0);

            // Line 1: Small Keys
            let held = ((*FILE_MGR).FA.dungeonflags[17][1] & 0xF) as u32;
            let found = (((*FILE_MGR).FA.dungeonflags[17][1] >> 4) & 0xF) as u32;
            let line1 = compose_keys_line(wch!(u16, "Small Keys: \0"), held, found, 1);
            set_wstr_arg(&line1, 1);

            // Line 2: Map
            let has_map = flag::check_global_dungeonflag(17, 1) != 0;
            let line2 = compose_obtained_line(wch!(u16, "Map: \0"), has_map);
            set_wstr_arg(&line2, 2);
        },
        2 => {
            // Title: Items
            let title = WStrBuf {
                buf: {
                    let mut b = [0u16; 64];
                    let s = wch!(u16, "Items\0");
                    let mut i = 0;
                    while i < s.len() && s[i] != 0 {
                        b[i] = s[i];
                        i += 1;
                    }
                    b
                },
                pos: 0,
            };
            set_string_arg(GLOBAL_TEXT_MGR, title.as_ptr(), 3);

            // Line 0: Spiral Charge
            let has_spiral = flag::check_itemflag(flag::ITEMFLAGS::BIRD_STATUETTE) != 0;
            let line0 = compose_obtained_line(wch!(u16, "Spiral Charge: \0"), has_spiral);
            set_wstr_arg(&line0, 0);

            // Line 1: Scrapper
            let has_scrapper = flag::check_storyflag(323) != 0;
            let line1 = compose_obtained_line(wch!(u16, "Scrapper: \0"), has_scrapper);
            set_wstr_arg(&line1, 1);

            // Line 2: Tadtones
            let tadtones = flag::check_storyflag(953);
            let mut line2 = WStrBuf::new();
            line2.push_wstr(wch!(u16, "Group of Tadtones: \0"));
            line2.push_u32(tadtones);
            set_wstr_arg(&line2, 2);
        },
        3 => {
            // Title: Gorge
            let title = WStrBuf {
                buf: {
                    let mut b = [0u16; 64];
                    let s = wch!(u16, "Gorge\0");
                    let mut i = 0;
                    while i < s.len() && s[i] != 0 {
                        b[i] = s[i];
                        i += 1;
                    }
                    b
                },
                pos: 0,
            };
            set_string_arg(GLOBAL_TEXT_MGR, title.as_ptr(), 3);

            // Line 0: Life Tree Fruit
            let has_fruit = flag::check_itemflag(flag::ITEMFLAGS::LIFE_TREE_FRUIT) != 0
                || flag::check_storyflag(462) != 0;
            let line0 = compose_obtained_line(wch!(u16, "Life Tree Fruit: \0"), has_fruit);
            set_wstr_arg(&line0, 0);

            // Line 1: Seedling
            let has_seedling = flag::check_itemflag(flag::ITEMFLAGS::LIFE_TREE_SEEDLING) != 0
                || flag::check_storyflag(750) != 0;
            let line1 = compose_obtained_line(wch!(u16, "Seedling: \0"), has_seedling);
            set_wstr_arg(&line1, 1);

            // Line 2: Lanayru Caves Keys
            let held = ((*FILE_MGR).FA.dungeonflags[9][1] & 0xF) as u32;
            let found = (((*FILE_MGR).FA.dungeonflags[9][1] >> 4) & 0xF) as u32;
            let line2 = compose_keys_line(wch!(u16, "Caves Keys: \0"), held, found, 2);
            set_wstr_arg(&line2, 2);
        },
        _ => {},
    }
}

/// Set the string args for page 0x3A (Archipelago check statistics).
/// Reads from AP_CHECK_STATS buffer written by the Python client.
unsafe fn set_help_page_stats_args(help_number: u32) {
    let stats = &item::AP_CHECK_STATS;
    let nc = stats.normal_checked as u32;
    let nt = stats.normal_total as u32;
    let ac = stats.ap_checked as u32;
    let at = stats.ap_total as u32;

    match help_number {
        1 => {
            // Card 0a: Normal Checks
            let mut title = WStrBuf::new();
            title.push_wstr(wch!(u16, "Normal Checks\0"));
            set_string_arg(GLOBAL_TEXT_MGR, title.as_ptr(), 3);

            let line0 = compose_count_line(wch!(u16, "Picked Up: \0"), nc, nt);
            set_wstr_arg(&line0, 0);

            // Empty lines
            let empty = WStrBuf::new();
            set_wstr_arg(&empty, 1);
            set_wstr_arg(&empty, 2);
        },
        2 => {
            // Card 0b: Archipelago Item Checks
            let mut title = WStrBuf::new();
            title.push_wstr(wch!(u16, "Archipelago Checks\0"));
            set_string_arg(GLOBAL_TEXT_MGR, title.as_ptr(), 3);

            let line0 = compose_count_line(wch!(u16, "Picked Up: \0"), ac, at);
            set_wstr_arg(&line0, 0);

            let empty = WStrBuf::new();
            set_wstr_arg(&empty, 1);
            set_wstr_arg(&empty, 2);
        },
        3 => {
            // Card 0c: Combined Totals
            let mut title = WStrBuf::new();
            title.push_wstr(wch!(u16, "Check Totals\0"));
            set_string_arg(GLOBAL_TEXT_MGR, title.as_ptr(), 3);

            let line0 = compose_count_line(wch!(u16, "Normal: \0"), nc, nt);
            set_wstr_arg(&line0, 0);

            let line1 = compose_count_line(wch!(u16, "Archipelago: \0"), ac, at);
            set_wstr_arg(&line1, 1);

            let line2 = compose_count_line(wch!(u16, "Total: \0"), nc + ac, nt + at);
            set_wstr_arg(&line2, 2);
        },
        _ => {},
    }
}

#[no_mangle]
pub extern "C" fn set_help_menu_strings(param1: *mut c_void, help_index: u32) {
    unsafe {
        let help_number: u32;
        asm!("mov {0:w}, w28", out(reg) help_number);

        match help_index {
            0x3A => {
                // Stats page (cards 0a, 0b, 0c)
                set_help_page_stats_args(help_number);
            },
            0x3B => {
                match help_number {
                    1 => {
                        // Skyview Temple
                        __set_dungeon_string_and_numeric_args(5, 11)
                    },
                    2 => {
                        // Earth Temple
                        __set_dungeon_string_and_numeric_args(7, 14);
                        (*GLOBAL_TEXT_MGR).numeric_args[0] =
                            flag::check_itemflag(flag::ITEMFLAGS::KEY_PIECE_COUNTER);
                    },
                    3 => {
                        // Lanayru Mining Facility
                        __set_dungeon_string_and_numeric_args(935, 17);
                    },
                    _ => {},
                }
            },
            0x3C => {
                match help_number {
                    1 => {
                        // Ancient Cistern
                        __set_dungeon_string_and_numeric_args(900, 12);
                    },
                    2 => {
                        // Sandship
                        __set_dungeon_string_and_numeric_args(15, 18);
                    },
                    3 => {
                        // Check if Fire Sanctuary is complete
                        __set_dungeon_string_and_numeric_args(901, 15);
                    },
                    _ => {},
                }
            },
            0x3D => {
                // Sky Keep / Items / Gorge — now fully string-arg-based
                set_help_page_3d_args(help_number);
            },
            _ => {},
        }

        // Normalize help_index to w1 for vanilla text rendering code.
        // Pages 0x3A and 0x3D both use page 2's text entries (indices 155-163).
        let w1: u32 = match help_index {
            0x3A => 2, // stats page shares 0x3D's text templates
            0x3B => 0,
            0x3C => 1,
            0x3D => 2,
            _ => 0,
        };
        asm!("mov x0, {0:x}", in(reg) param1);
        asm!("mov w1, {0:w}", in(reg) w1);
    }
}

#[no_mangle]
pub extern "C" fn left_justify_help_text() {
    unsafe {
        asm!(
            "add x20, x19, x20, LSL #0x3",
            "ldr x0, [x20, #0x548]",
            "strb wzr, [x0, #0x13c]",
            "ldr x0, [x20, #0x560]",
            "strb wzr, [x0, #0x13c]",
            "ldr x0, [x20, #0x518]"
        );
    }
}

#[no_mangle]
pub extern "C" fn custom_help_menu_state_change(dLytHelp: *mut c_void) -> u32 {
    if input::check_button_pressed_down(input::BUTTON_INPUTS::DPAD_LEFT_BUTTON) {
        return 2; // Close help menu
    }

    if !input::check_button_pressed_down(input::BUTTON_INPUTS::DPAD_RIGHT_BUTTON) {
        return 0; // Continue as normal
    }

    // Trigger stateIn again
    unsafe {
        asm!("mov x0, {0:x}", in(reg) dLytHelp);
        asm!("mov w8, #1");
        asm!("str w8, [x0, #0x5a0]");

        // Increment help_index
        let mut help_index: u32;
        asm!("ldr {0:w}, [x0, #0x5a4]", out(reg) help_index);
        if help_index == 0x3D {
            help_index = 0;
        } else if help_index <= 0x39 {
            help_index = 0x3A;
        } else {
            help_index += 1;
        }
        asm!("str {0:w}, [x0, #0x5a4]", in(reg) help_index);

        if help_index == 0 {
            return 2; // Close help menu
        }

        dLytHelp__stateNoneUpdate(dLytHelp)
    }

    return 1; // Ret, don't close help menu
}

// Adapted from SDR:
// https://github.com/ssrando/ssrando/blob/029545b5e1d73ef515a1d61fc69b572946d45399/asm/custom-functions/src/rando/mod.rs#L614
#[no_mangle]
extern "C" fn get_tablet_keyframe_count() -> c_int {
    // The tablet frames effectively start with a Gray Code, the continuation of
    // which looks like this:
    //
    // Count     Emerald   Ruby      Amber     As Index
    // 0         0         0         0         0
    // 1         1         0         0         1
    // 2         1         1         0         3
    // 3         1         1         1         7
    // 4         1         0         1         5
    // 5         0         0         1         4
    // 6         0         1         1         6
    // 7         0         1         0         2

    const TABLET_BITMAP_TO_KEYFRAME: [u8; 8] = [0, 1, 7, 2, 5, 4, 6, 3];

    let item_bitmap = flag::check_itemflag(flag::ITEMFLAGS::EMERALD_TABLET) as usize
        | ((flag::check_itemflag(flag::ITEMFLAGS::RUBY_TABLET) as usize) << 1)
        | ((flag::check_itemflag(flag::ITEMFLAGS::AMBER_TABLET) as usize) << 2);

    return TABLET_BITMAP_TO_KEYFRAME[item_bitmap & 0x7] as i32;
}

#[no_mangle]
extern "C" fn override_inventory_caption_item_text(
    string: *const c_char,
    fstr: *const c_char,
    mut itemid: u32,
) {
    unsafe {
        // Is tablet
        if itemid == 177 || itemid == 178 || itemid == 179 {
            // Use a the same system as in get_tablet_keyframe_count
            // Item ids 181 -> 185 are unused in vanilla. Rando replaces them
            const TABLET_BITMAP_TO_TEXTID: [u32; 8] = [999, 177, 184, 178, 182, 181, 183, 179];

            let item_bitmap = flag::check_itemflag(flag::ITEMFLAGS::EMERALD_TABLET) as usize
                | ((flag::check_itemflag(flag::ITEMFLAGS::RUBY_TABLET) as usize) << 1)
                | ((flag::check_itemflag(flag::ITEMFLAGS::AMBER_TABLET) as usize) << 2);

            itemid = TABLET_BITMAP_TO_TEXTID[item_bitmap & 0x7];
        }
        debugPrint_32(string, fstr, itemid);
        asm!("mov x8, {0:x}", in(reg) dManager__sInstance);
    }
}
