#![allow(non_camel_case_types)]
#![allow(non_snake_case)]
#![allow(unused)]

use crate::actor;
use crate::debug;

use core::arch::asm;
use core::ffi::{c_char, c_void};
use static_assertions::assert_eq_size;

// repr(C) prevents rust from reordering struct fields.
// packed(1) prevents rust from aligning structs to the size of the largest
// field.

// Using u64 or 64bit pointers forces structs to be 8-byte aligned.
// The vanilla code seems to be 4-byte aligned. To make extra sure, used
// packed(1) to force the alignment to match what you define.

// Always add an assert_eq_size!() macro after defining a struct to ensure it's
// the size you expect it to be.

#[repr(C, packed(1))]
#[derive(Copy, Clone)]
pub struct Heap {
    pub vtable:       *mut HeapVtable,
    pub containHeap:  *mut Heap,
    pub mLink:        [u8; 0x10],
    pub heapHandle:   [u8; 0x8],
    pub mParentBlock: [u8; 0x8],
    pub mFlag:        u16,
    pub _0:           [u8; 0x2],
    pub mNode:        [u8; 0x10],
    pub _1:           [u8; 0x4],
    pub mChildren:    [u8; 0x14],
    pub _2:           [u8; 0x4],
    pub mName:        *const c_char,
}
assert_eq_size!([u8; 0x68], Heap);

#[repr(C, packed(1))]
#[derive(Copy, Clone)]
pub struct HeapVtable {
    pub dt1:                  extern "C" fn(heap: *mut Heap),
    pub dt2:                  extern "C" fn(heap: *mut Heap),
    pub get_heap_type:        extern "C" fn(heap: *mut Heap) -> u32,
    pub init_allocator:       extern "C" fn(heap: *mut Heap, allocator: u64, align: i32),
    pub alloc:                extern "C" fn(heap: *mut Heap, size: i32, alignment: i32) -> u64,
    pub free:                 extern "C" fn(heap: *mut Heap, to_free: *mut c_void) -> u64,
    pub destroy:              extern "C" fn(heap: *mut Heap),
    pub resize_for_m_block:   extern "C" fn(heap: *mut Heap, block: *mut c_void, size: i32) -> u32,
    pub get_total_free_size:  extern "C" fn(heap: *mut Heap) -> i32,
    pub get_allocatable_size: extern "C" fn(heap: *mut Heap, alignment: i32) -> i32,
    pub adjust:               extern "C" fn(heap: *mut Heap) -> i32,
}
assert_eq_size!([u8; 0x58], HeapVtable);

#[repr(C, packed(1))]
#[derive(Copy, Clone)]
pub struct RootHeapsMgr {
    pub vtable:             *mut RootHeapsMgrVtable,
    pub root_heap1_start:   u64,
    pub root_heap1_end:     u64,
    pub root_heap2_start:   u64,
    pub root_heap2_end:     u64,
    pub mem_size:           u64,
    pub root_heap1:         *mut Heap,
    pub root_heap2:         *mut Heap,
    pub debug_heap:         *mut Heap,
    pub egg_sys_heap:       *mut Heap, // ExpHeap
    pub current_thread:     *mut c_void,
    pub virt_start_maybe:   u64,
    pub system_heap_start:  u64,
    pub system_heap_size:   u64,
    pub graphics_fifo_size: u64,
    pub snd_audio_mgr:      *mut c_void,
    pub video:              *mut c_void,
    pub xfb_mgr:            *mut c_void,
    pub async_display:      *mut c_void,
    pub perf_view:          *mut c_void,
    pub scn_mgr:            *mut c_void,
}
assert_eq_size!([u8; 0xA8], RootHeapsMgr);

#[repr(C, packed(1))]
#[derive(Copy, Clone)]
pub struct RootHeapsMgrVtable {
    pub get_video_or_render_modeobj: extern "C" fn(rheaps_mgr: *mut RootHeapsMgr) -> u64,
    pub get_system_heap:             extern "C" fn(rheaps_mgr: *mut RootHeapsMgr) -> *mut Heap,
    pub get_display:                 extern "C" fn(rheaps_mgr: *mut RootHeapsMgr) -> u64,
    pub get_xfb_mgr:                 extern "C" fn(rheaps_mgr: *mut RootHeapsMgr) -> u64,
    pub get_perf_view:               extern "C" fn(rheaps_mgr: *mut RootHeapsMgr) -> u64,
    pub get_scene_mgr:               extern "C" fn(rheaps_mgr: *mut RootHeapsMgr) -> u64,
    pub get_snd_audio_mgr:           extern "C" fn(rheaps_mgr: *mut RootHeapsMgr) -> u64,
    pub on_begin_frame:              extern "C" fn(rheaps_mgr: *mut RootHeapsMgr) -> u64,
    pub on_end_frame:                extern "C" fn(rheaps_mgr: *mut RootHeapsMgr) -> u64,
    pub init_render_mode:            extern "C" fn(rheaps_mgr: *mut RootHeapsMgr) -> u64,
    pub initialize_inner:            extern "C" fn(rheaps_mgr: *mut RootHeapsMgr) -> u64,
    pub run:                         extern "C" fn(rheaps_mgr: *mut RootHeapsMgr) -> u64,
    pub initialize:                  extern "C" fn(rheaps_mgr: *mut RootHeapsMgr) -> u64,
}
assert_eq_size!([u8; 0x68], RootHeapsMgrVtable);

#[repr(C, packed(1))]
#[derive(Copy, Clone)]
pub struct ArcEntryTable {
    pub entries:        *mut [ArcEntry; 400],
    pub entry_count:    u16,
    pub _0:             [u8; 0x6],
    pub stage_arc_type: u64,
}
assert_eq_size!([u8; 0x18], ArcEntryTable);

#[repr(C, packed(1))]
#[derive(Copy, Clone)]
pub struct ArcMgr {
    pub vtable:        u64,
    pub entries_table: ArcEntryTable,
}
assert_eq_size!([u8; 0x20], ArcMgr);

#[repr(C, packed(1))]
#[derive(Copy, Clone)]
pub struct StageArcMgr {
    pub vtable:                         u64,
    pub stage_name:                     [c_char; 32],
    pub current_loading_stage_arc_name: [c_char; 32],
    pub stage_extra_layer_arc_name:     [c_char; 32],
    pub entries_table:                  ArcEntryTable,
}
assert_eq_size!([u8; 0x80], StageArcMgr);

#[repr(C, packed(1))]
#[derive(Copy, Clone)]
pub struct ArcEntry {
    pub arc_name:  [c_char; 32],
    pub ref_count: i16,
    pub _0:        [u8; 0x6],
    pub dvd_req:   u64,
    pub arc:       *mut Arc,
    pub heap:      *mut Heap,
    pub _1:        [u8; 0x18],
}
assert_eq_size!([u8; 0x58], ArcEntry);

#[repr(C, packed(1))]
#[derive(Copy, Clone)]
pub struct Arc {
    pub vtable:            u64,
    pub disposer:          [u8; 0x18],
    pub mount_type:        i32,
    pub ref_count:         i32,
    pub arc_start_address: u64,
    pub fst_start:         u64,
    pub file_start:        u64,
    pub entry_num:         u32,
    pub _0:                [u8; 0x4],
    pub fst_string_start:  *const c_char,
    pub fst_len:           i32,
    pub current_dir:       i32,
    pub dvd_entry_num:     i32,
    pub _1:                [u8; 0x4],
    pub nand_file:         u64,
    pub _2:                [u8; 0x20],
}
assert_eq_size!([u8; 0x88], Arc);

#[repr(C, packed(1))]
#[derive(Copy, Clone)]
pub struct xtxThing {
    pub unk_ptr:        u64,
    pub some_index:     u32,
    pub _0:             [u8; 0x4],
    pub file_extension: *const c_char,
    pub heap:           *mut Heap,
    pub align:          i32,
    pub _1:             [u8; 0x4],
    pub arc_name:       [u8; 32],
}
assert_eq_size!([u8; 0x48], xtxThing);

// IMPORTANT: when using vanilla code, the start point must be declared in
// symbols.yaml and then added to this extern block.
extern "C" {
    static sCurrentHeap: *mut Heap;
    static mDvd__l_ArchiveHeap: *mut Heap;
    static mDvd__l_CommandHeap: *mut Heap;
    static mHeap__g_gameHeaps: [*mut Heap; 4];
    static mHeap__g_archiveHeap: *mut Heap;
    static mHeap__g_assertHeap: *mut Heap;
    static mHeap__g_commandHeap: *mut Heap;
    static mHeap__g_dylinkHeap: *mut Heap;
    static mHeap__s_SavedCurrentHeap: *mut Heap;
    static SOME_HEAP: *mut Heap;
    static WORK1_HEAP: *mut Heap;
    static WORK2_HEAP: *mut Heap;
    static WORK_EX_HEAP: *mut Heap;
    static LAYOUT_HEAP: *mut Heap;
    static LAYOUT_EX_HEAP: *mut Heap;
    static LAYOUT_EX2_HEAP: *mut Heap;
    static LAYOUT_RES_HEAP: *mut Heap;

    static ARC_MGR: *mut ArcMgr;
    pub static STAGE_ARC_MGR: *mut StageArcMgr;

    static mut NEXT_STAGE_NAME: [u8; 8];

    static mut BZS_STRING: [c_char; 32];

    // Functions
    fn debugPrint_128(string: *const c_char, fstr: *const c_char, ...);
    fn strcmp(s1: *const c_char, s2: *const c_char) -> i32;
    fn allocateNewActor(
        actorid: actor::ACTORID,
        connect_parent: *const actor::ActorTreeNode,
        actor_param1: u32,
        actor_group_type: u8,
    ) -> *mut actor::dBase;
    fn EGG__Archive__mount(p1: *mut c_void, p2: *mut Heap, p3: i32, p4: *const c_char) -> *mut Arc;
    fn dRawArcEntry_c__destroy(arc_entry: *mut ArcEntry, stage_arc_type: u64);
    fn dRawArcTable_c__getArcOrLoadFromDisk(
        arc_table: *mut ArcEntryTable,
        arc_name: *const c_char,
        parent_dir_name: *const c_char,
        heap: *mut Heap,
    ) -> bool;
    fn dRawArcTable_c__getDataFromOarc(
        arc_table: *mut c_void,
        arc_name: *const c_char,
        model_path: *const c_char,
    ) -> *mut c_void; // actually *mut ResFile
    fn dRawArcTable_c__addEntryFromParentArc(
        arc_table: *mut ArcEntryTable,
        arc_name: *mut ArcEntry,
        res_file_data: *mut c_void,
        heap: *mut Heap,
    );
}

// IMPORTANT: when adding functions here that need to get called from the game,
// add `#[no_mangle]` and add a .global *symbolname* to
// additions/rust-additions.asm

#[no_mangle]
pub extern "C" fn fix_memory_leak(
    u8File: *mut c_void,
    heap: *mut Heap,
    align: i32,
    xtx_thing_file_extension: *const c_char,
    xtx_thing: *mut xtxThing,
) -> u32 {
    unsafe {
        if xtx_thing.is_null() {
            return 0;
        }

        let mut arc_name = (*xtx_thing).arc_name;
        // debug::debug_print(arc_name.as_ptr() as *const c_char);

        if &arc_name[..6] == b"/oarc/" {
            let mut arc_name_len = 0_usize;

            for c in &arc_name[6..] {
                if *c == 0 {
                    break;
                }
                arc_name_len += 1;
            }

            // Only strip ".arc" when present. Avoid underflow/corruption on
            // unexpected short names.
            if arc_name_len >= 5 {
                let ext_start = 6 + arc_name_len - 4;
                if &arc_name[ext_start..(ext_start + 4)] == b".arc" {
                    arc_name[ext_start] = 0;
                }
            }

            let arc_name_cstr = arc_name[6..].as_ptr() as *const c_char;

            // Check if arc has already been loaded. Bound iteration to the
            // known table capacity to prevent out-of-bounds reads.
            if !ARC_MGR.is_null() && !(*ARC_MGR).entries_table.entries.is_null() {
                let mut current_entry_num = 0usize;
                let max_entries =
                    core::cmp::min((*ARC_MGR).entries_table.entry_count as usize, 400);

                while current_entry_num < max_entries {
                    let next_entry = (*(*ARC_MGR).entries_table.entries)[current_entry_num];
                    if next_entry.arc_name[0] == 0 {
                        break;
                    }

                    if strcmp(arc_name_cstr, next_entry.arc_name.as_ptr()) == 0
                        && next_entry.ref_count >= 1
                    {
                        // debug::debug_print_str(c"DUPLICATE: %s".as_ptr(), arc_name_cstr);
                        return (*xtx_thing).some_index;
                    }

                    current_entry_num += 1;
                }
            }
        }

        let new_arc = EGG__Archive__mount(u8File, heap, align, xtx_thing_file_extension);
        if !new_arc.is_null() {
            (*new_arc).ref_count = 0;
        }

        return (*xtx_thing).some_index;
    }
}

#[no_mangle]
pub extern "C" fn load_custom_bzs(
    arc_table: *mut ArcEntryTable,
    arc_name: *const c_char,
    parent_dir_name: *const c_char,
    heap: *mut Heap,
) {
    unsafe {
        dRawArcTable_c__getArcOrLoadFromDisk(arc_table, arc_name, parent_dir_name, heap);

        // Skip preloading "bzs" for the first BOOT_SKIP_CALLS invocations of
        // this hook. During cold boot the arc/stage infrastructure is still
        // being initialized; adding a "bzs" ArcEntry into a not-yet-ready
        // table can leave neighbouring entries in a state that later crashes
        // the game's own code (observed as a null-pointer strlen crash deep
        // in vanilla arc-lookup code). Real gameplay calls this hook on every
        // stage load, far more than a few times, so this only affects boot.
        static mut LOAD_BZS_CALL_COUNT: u32 = 0;
        const LOAD_BZS_BOOT_SKIP_CALLS: u32 = 8;
        LOAD_BZS_CALL_COUNT = LOAD_BZS_CALL_COUNT.saturating_add(1);
        if LOAD_BZS_CALL_COUNT <= LOAD_BZS_BOOT_SKIP_CALLS {
            return;
        }

        // Only preload the "bzs" arc when the arc table's entries array is
        // properly initialized. On the title screen at first boot the entries
        // pointer is garbage (~0x67M); adding a "bzs" ArcEntry into that
        // state corrupts the arc table and causes crashes in downstream code.
        let entries_addr = (*arc_table).entries as usize;
        if entries_addr != 0 && entries_addr < 0x40000000 {
            dRawArcTable_c__getArcOrLoadFromDisk(
                arc_table,
                c"bzs".as_ptr(),
                c"Stage".as_ptr(),
                heap,
            );
        }
    }
}

// Thin assembly wrapper: preserves caller-saved registers x3–x18 AND the
// NZCV condition flags around the use_custom_bzs Rust implementation.
//
// Hook 83 replaces a bare `ldrh w23,[x0,#8]` instruction, which does NOT
// affect flags. The game code that follows the `bl` to this hook may
// branch on flags set by an EARLIER instruction (before the call), relying
// on them surviving the call untouched. Our Rust impl executes strcmp/cmp
// internally, which clobbers NZCV, sending the game down an unintended
// (crashing) code path on the title screen regardless of our hook's logic.
// Saving/restoring x3-x18 alone was not sufficient; NZCV must be preserved
// too so the post-hook CPU state exactly matches what the original ldrh
// would have left.
core::arch::global_asm!(
    ".global use_custom_bzs",
    "use_custom_bzs:",
    "    sub  sp,  sp,  #160",
    "    stp  x30, x3,  [sp,   #0]",
    "    stp  x4,  x5,  [sp,  #16]",
    "    stp  x6,  x7,  [sp,  #32]",
    "    stp  x8,  x9,  [sp,  #48]",
    "    stp  x10, x11, [sp,  #64]",
    "    stp  x12, x13, [sp,  #80]",
    "    stp  x14, x15, [sp,  #96]",
    "    stp  x16, x17, [sp, #112]",
    "    str  x18,      [sp, #128]",
    "    mrs  x3,  nzcv",
    "    str  x3,       [sp, #136]",
    "    bl   use_custom_bzs_impl",
    "    ldr  x3,       [sp, #136]",
    "    msr  nzcv, x3",
    "    ldr  x18,      [sp, #128]",
    "    ldp  x16, x17, [sp, #112]",
    "    ldp  x14, x15, [sp,  #96]",
    "    ldp  x12, x13, [sp,  #80]",
    "    ldp  x10, x11, [sp,  #64]",
    "    ldp  x8,  x9,  [sp,  #48]",
    "    ldp  x6,  x7,  [sp,  #32]",
    "    ldp  x4,  x5,  [sp,  #16]",
    "    ldp  x30, x3,  [sp,   #0]",
    "    add  sp,  sp,  #160",
    "    ret",
);

#[no_mangle]
pub extern "C" fn use_custom_bzs_impl(
    arc_table: *mut ArcEntryTable,
    arc_name: *const c_char,
    model_path: *const c_char,
) -> *mut ArcEntryTable {
    unsafe {
        // Skip remapping for the first BOOT_SKIP_CALLS invocations of this
        // hook overall. During cold boot, the game calls this hook only a
        // handful of times while the stage/arc infrastructure is still being
        // initialized; the "bzs" arc entry (and neighbouring entries in the
        // same table) can pass our pointer-range/structural validation while
        // still not being truly ready, causing the game's OWN subsequent
        // code (in the same vanilla function, further down) to dereference
        // an uninitialized entry name and crash inside strlen. Real gameplay
        // calls this hook far more than a few times per stage load, so a
        // small fixed skip count safely covers cold boot without affecting
        // normal remapping later.
        static mut BOOT_CALL_COUNT: u32 = 0;
        const BOOT_SKIP_CALLS: u32 = 64;
        BOOT_CALL_COUNT = BOOT_CALL_COUNT.saturating_add(1);
        let past_boot_window = BOOT_CALL_COUNT > BOOT_SKIP_CALLS;

        let is_stage_bzs = strcmp(model_path, (*c"dat/stage.bzs").as_ptr()) == 0;
        let is_room_bzs = !is_stage_bzs && strcmp(model_path, (*c"dat/room.bzs").as_ptr()) == 0;

        // Validate ALL of NEXT_STAGE_NAME[0..4] to distinguish a properly
        // initialized stage name from a partially-initialized one.
        let is_valid_stage = NEXT_STAGE_NAME[0..4]
            .iter()
            .all(|&c| (c >= b'A' && c <= b'Z') || (c >= b'0' && c <= b'9'));

        // NOTE: CURRENT_STAGE_NAME/CURRENT_LAYER are NOT used here. They lag
        // behind during legitimate stage transitions (e.g. loading a save
        // from the title screen into a dungeon can leave CURRENT_STAGE_NAME
        // == "F000" for a brief window while the target stage's bzs arc is
        // already being resolved), causing false positives that break real
        // gameplay transitions. We rely purely on structural validation of
        // the Arc object itself instead.
        //
        // Only remap if the "bzs" arc is fully loaded with a valid, properly
        // mounted arc object.
        //
        // Three layers of validation (threshold 0x40000000 = 1 GB range check,
        // plus structural ordering):
        //  1. arc_table.entries must be a plausible heap address. On early
        //     title-screen boot this field is an uninitialised value ~0x68M.
        //  2. The "bzs" ArcEntry.arc pointer must also be valid.
        //  3. The Arc's internal offsets (arc_start_address, fst_start, file_start)
        //     must be non-zero, in-range, AND in ascending order (arc_start_address <=
        //     fst_start <= file_start), matching the structural layout of a genuinely
        //     mounted archive. Uninitialized garbage values are extremely unlikely to
        //     satisfy this ordering.
        //
        // All checks read POINTER VALUES only — they never dereference the
        // questionable address — so they cannot fault.
        let mut bzs_found = false;
        let entries_addr = (*arc_table).entries as usize;
        if entries_addr != 0 && entries_addr < 0x40000000 {
            let max_entries = core::cmp::min((*arc_table).entry_count as usize, 400);
            for i in 0..max_entries {
                let entry = (*(*arc_table).entries)[i];
                if entry.arc_name[0] == 0 {
                    break;
                }
                if strcmp(entry.arc_name.as_ptr(), c"bzs".as_ptr()) == 0
                    && !entry.arc.is_null()
                    && (entry.arc as usize) < 0x40000000
                    && {
                        let arc_start = (*entry.arc).arc_start_address as usize;
                        let fst = (*entry.arc).fst_start as usize;
                        let file_data = (*entry.arc).file_start as usize;
                        arc_start != 0
                            && arc_start < 0x40000000
                            && fst != 0
                            && fst < 0x40000000
                            && file_data != 0
                            && file_data < 0x40000000
                            && arc_start <= fst
                            && fst <= file_data
                    }
                {
                    bzs_found = true;
                    break;
                }
            }
        }

        if (is_stage_bzs || is_room_bzs) && bzs_found && is_valid_stage && past_boot_window {
            if is_stage_bzs {
                let new_arc_name = (*c"bzs").as_ptr();
                let mut current_char_index = 0;

                for character in b"dat/" {
                    BZS_STRING[current_char_index] = *character as i8;
                    current_char_index += 1;
                }

                let mut found_string_terminator = false;
                for stage_char in &mut NEXT_STAGE_NAME[0..6] {
                    if !found_string_terminator && *stage_char != 0 {
                        BZS_STRING[current_char_index] = *stage_char as i8;
                        current_char_index += 1;
                    } else {
                        found_string_terminator = true;
                    }
                }

                for character in b"_stage.bzs\0" {
                    BZS_STRING[current_char_index] = *character as i8;
                    current_char_index += 1;
                }

                asm!("mov x2, {0:x}", in(reg) &BZS_STRING);
                asm!("mov x1, {0:x}", in(reg) new_arc_name);
            } else if is_room_bzs {
                let new_arc_name = (*c"bzs").as_ptr();
                let mut current_char_index = 0;

                for character in b"dat/" {
                    BZS_STRING[current_char_index] = *character as i8;
                    current_char_index += 1;
                }

                let mut found_string_terminator = false;
                for stage_char in &mut NEXT_STAGE_NAME[0..8] {
                    if !found_string_terminator && *stage_char != 0 {
                        BZS_STRING[current_char_index] = *stage_char as i8;
                        current_char_index += 1;
                    } else {
                        found_string_terminator = true;
                    }
                }

                for character in b"_room_" {
                    BZS_STRING[current_char_index] = *character as i8;
                    current_char_index += 1;
                }

                let indexable_arc_name = core::slice::from_raw_parts(arc_name, 16);
                let mut roomid_char_index = 0;

                while roomid_char_index < 15 && indexable_arc_name[roomid_char_index] != 0 {
                    roomid_char_index += 1;
                }

                if roomid_char_index >= 2 && indexable_arc_name[roomid_char_index - 2] != 48 {
                    BZS_STRING[current_char_index] =
                        indexable_arc_name[roomid_char_index - 2] as i8;
                    current_char_index += 1;
                }
                if roomid_char_index >= 1 {
                    BZS_STRING[current_char_index] =
                        indexable_arc_name[roomid_char_index - 1] as i8;
                    current_char_index += 1;
                }

                for character in b".bzs\0" {
                    BZS_STRING[current_char_index] = *character as i8;
                    current_char_index += 1;
                }

                asm!("mov x2, {0:x}", in(reg) &BZS_STRING);
                asm!("mov x1, {0:x}", in(reg) new_arc_name);
            }
        } else {
            // not a bzs path, uninit stage name, or title screen: use vanilla path
            asm!("mov x2, {0:x}", in(reg) model_path);
            asm!("mov x1, {0:x}", in(reg) arc_name);
        }

        asm!("mov x0, {0:x}", in(reg) arc_table);

        // Replaced instructions
        asm!("ldrh w23, [x0, #0x8]");

        return arc_table;
    }
}

// When loading arcs from a stage file, try looking at romfs/ModReplace first.
#[no_mangle]
pub extern "C" fn prefer_object_folder_for_stage_arcs(
    arc_table: *mut ArcEntryTable,
    arc_entry: *mut ArcEntry,
    mut res_file_data: *mut c_void,
    heap: *mut Heap,
) {
    unsafe {
        let result = dRawArcTable_c__getArcOrLoadFromDisk(
            arc_table,
            &(*arc_entry).arc_name as *const c_char,
            c"ModReplace".as_ptr(),
            WORK2_HEAP,
        );

        if !result {
            dRawArcTable_c__addEntryFromParentArc(arc_table, arc_entry, res_file_data, heap);
        }
    }
}

// Having the replaced instructions in a separate function ensures that the
// original instructions don't get ignored in
// prefer_modreplace_for_general_arcs because of the params.
#[no_mangle]
pub extern "C" fn setup_registers_for_general_modreplace() {
    unsafe {
        asm!(
            "mov x22, x3",
            "mov x24, x2",
            "mov x19, x1",
            "mov x21, x0",
            "mov w27, wzr",
            "mov x20, x26",
        );
    }
}

// When loading an arc with dRawArcTable_c__getArcOrLoadFromDisk,
// try looking in romfs/ModReplace for the arc first.
#[no_mangle]
pub extern "C" fn prefer_modreplace_for_general_arcs(
    arc_table: *mut ArcEntryTable,
    arc_name: *mut c_char,
    parent_dir_name: *const c_char,
    heap: *mut Heap,
) -> bool {
    unsafe {
        let mod_replace_str = c"ModReplace".as_ptr();

        if strcmp(parent_dir_name, mod_replace_str) != 0 {
            return dRawArcTable_c__getArcOrLoadFromDisk(
                arc_table,
                arc_name,
                mod_replace_str,
                heap,
            );
        }

        return false;
    }
}

#[no_mangle]
pub extern "C" fn debug_print_heap_info(heap: *mut Heap, heap_identifier: *const c_char) {
    debug::debug_print_str(c"Heap info for: %s".as_ptr(), heap_identifier);
    if !heap.is_null() {
        debug::debug_print(c"Heap Name:".as_ptr());
        debug::debug_print(unsafe { (*heap).mName });
        debug::debug_print_num(c"Total Free Size: %d".as_ptr(), unsafe {
            ((*(*heap).vtable).get_total_free_size)(heap)
        } as usize);
    } else {
        debug::debug_print(c"Is nullptr:".as_ptr());
    }
    debug::debug_print(c"".as_ptr());
}

#[no_mangle]
pub extern "C" fn debug_print_all_heap_info() {
    let heaps = unsafe {
        [
            (sCurrentHeap, c"sCurrentHeap".as_ptr()),
            (mDvd__l_ArchiveHeap, c"mDvd__l_ArchiveHeap".as_ptr()),
            (mDvd__l_CommandHeap, c"mDvd__l_CommandHeap".as_ptr()),
            (mHeap__g_archiveHeap, c"mHeap__g_archiveHeap".as_ptr()),
            (mHeap__g_assertHeap, c"mHeap__g_assertHeap".as_ptr()),
            (mHeap__g_commandHeap, c"mHeap__g_commandHeap".as_ptr()),
            (mHeap__g_dylinkHeap, c"mHeap__g_dylinkHeap".as_ptr()),
            (
                mHeap__s_SavedCurrentHeap,
                c"mHeap__s_SavedCurrentHeap".as_ptr(),
            ),
            (WORK1_HEAP, c"WORK1_HEAP".as_ptr()),
            (WORK2_HEAP, c"WORK2_HEAP".as_ptr()),
            (WORK_EX_HEAP, c"WORK_EX_HEAP".as_ptr()),
            (LAYOUT_HEAP, c"LAYOUT_HEAP".as_ptr()),
            (LAYOUT_EX_HEAP, c"LAYOUT_EX_HEAP".as_ptr()),
            (LAYOUT_EX2_HEAP, c"LAYOUT_EX2_HEAP".as_ptr()),
            (LAYOUT_RES_HEAP, c"LAYOUT_RES_HEAP".as_ptr()),
            (mHeap__g_gameHeaps[0], c"mHeap__g_gameHeaps[0]".as_ptr()),
            (mHeap__g_gameHeaps[1], c"mHeap__g_gameHeaps[1]".as_ptr()),
        ]
    };

    debug::debug_print(c"".as_ptr());
    debug::debug_print(c"Heap Info:".as_ptr());
    debug::debug_print(c"".as_ptr());

    for (heap, heap_identifier) in heaps {
        debug_print_heap_info(heap, heap_identifier);
    }
}
