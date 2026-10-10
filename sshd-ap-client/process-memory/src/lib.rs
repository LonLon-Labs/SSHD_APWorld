//! Cross-platform process memory access — a faithful Rust port of
//! `process_memory.py`.
//!
//! Linux: `/proc/<pid>/mem` + `/proc/<pid>/maps` (+ `smaps` for RSS-based
//! scan filtering), exactly like the Python backend.
//! Windows: `ReadProcessMemory` / `WriteProcessMemory` / `VirtualQueryEx`
//! via `windows-sys`, exactly like the pymem-based Python backend.
//!
//! # What's different from before
//! Because the game side now exposes ONE consolidated `AP_IPC_ROOT`
//! (see `ap-ipc`), this crate's `pattern_scan` only ever needs to run
//! ONCE per session — scanning directly for `ap_ipc::AP_IPC_MAGIC`, rather
//! than for a generic NSO header signature that then requires further
//! offset math, or for five-to-seven separate per-mailbox magics.

use std::io;
use std::time::{Duration, Instant};

#[derive(Debug, Clone)]
pub struct MemoryRegion {
    pub base:     usize,
    pub size:     usize,
    pub perms:    String, // e.g. "rw-p", "r-xp"
    pub pathname: String, // e.g. "/usr/lib/libc.so.6", "[heap]", ""
    pub rss:      i64,    // resident set size in bytes, -1 = unknown
}

impl MemoryRegion {
    pub fn is_readable(&self) -> bool {
        self.perms.starts_with('r')
    }
    pub fn is_writable(&self) -> bool {
        self.perms.len() > 1 && self.perms.as_bytes()[1] == b'w'
    }
    pub fn is_anonymous(&self) -> bool {
        self.pathname.is_empty()
    }
}

#[derive(Debug)]
pub enum MemError {
    NotAttached,
    Io(io::Error),
    ShortRead { addr: usize, expected: usize, got: usize },
    ShortWrite { addr: usize, expected: usize, wrote: usize },
    ProcessNotFound,
    PermissionDenied(String),
    Unsupported(String),
    /// `find_ap_ipc_root` couldn't locate a live `AP_IPC_ROOT` (yet). The text is
    /// a complete, user-presentable sentence; its wording is kept stable between
    /// retries so callers can de-duplicate log lines.
    RootNotFound(String),
}

impl std::fmt::Display for MemError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            MemError::NotAttached => write!(f, "not attached to a process"),
            MemError::Io(e) => write!(f, "I/O error: {e}"),
            MemError::ShortRead { addr, expected, got } => {
                write!(f, "short read at {addr:#x}: expected {expected}, got {got}")
            },
            MemError::ShortWrite { addr, expected, wrote } => {
                write!(f, "short write at {addr:#x}: expected {expected}, wrote {wrote}")
            },
            MemError::ProcessNotFound => write!(f, "process not found"),
            MemError::PermissionDenied(s) => write!(f, "permission denied: {s}"),
            MemError::Unsupported(s) => write!(f, "unsupported: {s}"),
            MemError::RootNotFound(s) => write!(f, "{s}"),
        }
    }
}
impl std::error::Error for MemError {}
impl From<io::Error> for MemError {
    fn from(e: io::Error) -> Self {
        MemError::Io(e)
    }
}

pub type MemResult<T> = Result<T, MemError>;

/// Backend-agnostic handle to an attached process.
pub trait ProcessMemory {
    fn read_bytes(&mut self, address: usize, size: usize) -> MemResult<Vec<u8>>;
    fn write_bytes(&mut self, address: usize, data: &[u8]) -> MemResult<()>;
    fn enumerate_regions(&mut self) -> MemResult<Vec<MemoryRegion>>;

    fn read_u8(&mut self, address: usize) -> MemResult<u8> {
        Ok(self.read_bytes(address, 1)?[0])
    }

    /// Reads up to `buf.len()` bytes at `address` into `buf` and returns how many
    /// were actually read (0 on failure). Unlike `read_bytes` this allocates
    /// nothing and keeps a PARTIAL read, so a scan can salvage everything up to
    /// the first unreadable page instead of throwing away the whole chunk (a
    /// page whose protection flipped between enumeration and read used to make
    /// the scan silently skip 4 MiB, which is one way a scan could miss the
    /// marker on one run and find it on the next).
    fn read_into(&mut self, address: usize, buf: &mut [u8]) -> usize {
        match self.read_bytes(address, buf.len()) {
            Ok(data) => {
                buf.copy_from_slice(&data);
                buf.len()
            },
            Err(_) => 0,
        }
    }

    /// Regions worth scanning for game data, IN THE ORDER they should be
    /// scanned (most likely home of guest RAM first). Backends override this
    /// with their own filtering/ordering; the default is every readable region.
    fn scannable_regions(&mut self) -> MemResult<Vec<MemoryRegion>> {
        Ok(self.enumerate_regions()?.into_iter().filter(|r| r.is_readable()).collect())
    }

    /// Scan every readable region for `pattern`, returning absolute
    /// addresses of each match. Mirrors `_manual_pattern_scan` in
    /// `process_memory.py` (naive substring search, 4 MiB chunks, 1-byte
    /// overlap at chunk boundaries so matches spanning a boundary aren't
    /// missed).
    fn pattern_scan(&mut self, pattern: &[u8]) -> MemResult<Vec<usize>> {
        const CHUNK: usize = 4 * 1024 * 1024;
        let mut results = Vec::new();
        for region in self.enumerate_regions()? {
            if !region.is_readable() {
                continue;
            }
            let mut pos = region.base;
            let end = region.base + region.size;
            while pos < end {
                let to_read = CHUNK.min(end - pos);
                let data = match self.read_bytes(pos, to_read) {
                    Ok(d) => d,
                    Err(_) => {
                        pos += to_read;
                        continue;
                    },
                };
                let mut offset = 0usize;
                while let Some(idx) = find_subslice(&data[offset..], pattern) {
                    let abs_idx = offset + idx;
                    results.push(pos + abs_idx);
                    offset = abs_idx + 1;
                    if offset >= data.len() {
                        break;
                    }
                }
                if to_read == CHUNK {
                    pos += to_read - pattern.len() + 1;
                } else {
                    pos += to_read;
                }
            }
        }
        Ok(results)
    }

    /// Convenience: scan for `pattern` and return a single, trustworthy
    /// address for it.
    ///
    /// The common case is exactly one hit, which is returned directly.
    /// More than one hit is also accepted, PROVIDED every hit's
    /// surrounding content is byte-identical: several Switch emulators
    /// (Ryujinx included) map the same guest RAM page into the host
    /// process at more than one virtual address ("memory mirroring") for
    /// performance reasons, so finding AP_IPC_MAGIC 2-3 times with
    /// identical content at each is expected there, not a sign of
    /// ambiguity -- every hit is an alias of the exact same underlying
    /// memory, so it doesn't matter which one we use; picking any of them
    /// reads/writes the same live data. If the hits' content actually
    /// DIFFERS, that's a genuine ambiguity (not mirroring) and this still
    /// errors out.
    fn pattern_scan_unique(&mut self, pattern: &[u8]) -> MemResult<usize> {
        const VERIFY_SIZE: usize = 256;

        let hits = self.pattern_scan(pattern)?;
        match hits.len() {
            0 => Err(MemError::Unsupported("pattern not found".into())),
            1 => Ok(hits[0]),
            _ => {
                let mut reference: Option<Vec<u8>> = None;
                for &addr in &hits {
                    let chunk = self.read_bytes(addr, VERIFY_SIZE)?;
                    match &reference {
                        None => reference = Some(chunk),
                        Some(r) if *r == chunk => {},
                        Some(_) => {
                            let addrs =
                                hits.iter().map(|a| format!("{a:#x}")).collect::<Vec<_>>().join(", ");
                            return Err(MemError::Unsupported(format!(
                                "pattern matched {} times at [{addrs}] with DIFFERING content -- \
                                 genuinely ambiguous, not just memory mirroring",
                                hits.len()
                            )));
                        },
                    }
                }
                Ok(hits[0])
            },
        }
    }
}

fn find_subslice(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    if needle.is_empty() || needle.len() > haystack.len() {
        return None;
    }
    haystack.windows(needle.len()).position(|w| w == needle)
}

// ─────────────────────────────────────────────────────────────────────────
// AP_IPC_ROOT discovery
// ─────────────────────────────────────────────────────────────────────────
//
// Finding `AP_IPC_ROOT` used to mean "read every readable byte of the
// emulator, and demand that every hit looks identical". That was both slow
// (tens of seconds: most of an emulator process is not guest RAM, and RAM was
// walked once per alias) and flaky, because the marker legitimately appears
// more than once and NOT every copy is the live one:
//   * emulators map guest RAM at several host addresses (aliases: all live),
//   * the loader keeps pristine copies of the game's initial .data image
//     (dead: same bytes at first, but nothing ever updates them).
// Comparing the first 256 bytes of each hit can't tell those apart, so the
// outcome depended on timing ("pattern matched 4 times ... DIFFERING content"),
// and when the copies did happen to match, the client could end up attached to
// a dead one.
//
// The game rewrites `current_scene_index` every frame (see
// `item::refresh_ipc_addresses` on the game side), so a copy is LIVE exactly
// when it overwrites a sentinel we plant there. `find_ap_ipc_root` scans
// likely-guest-RAM regions first, probes each hit the moment it's found, and
// stops at the first live one. Candidates are cached in `RootSearch`, so
// retries and re-attaches after a hiccup don't rescan at all.

/// Bytes read per `read_into` call while scanning.
const SCAN_CHUNK: usize = 8 * 1024 * 1024;
/// Value planted in `current_scene_index` to test whether a copy is live. Not a
/// valid scene index (those are small, or 0xFFFF for "none").
const LIVENESS_SENTINEL: u16 = 0xA5A5;
/// How long to wait for the game to overwrite the sentinel. Generous, because
/// emulators can stutter badly (shader compiles etc.); returns as soon as any
/// copy answers, so this only costs time when nothing is live.
const LIVENESS_TIMEOUT: Duration = Duration::from_millis(750);
const LIVENESS_POLL: Duration = Duration::from_millis(10);
/// After a probe finds no live copy, don't probe the same candidates again for
/// this long (a paused emulator would otherwise stall the caller every retry).
const DEAD_PROBE_BACKOFF: Duration = Duration::from_secs(3);
/// A hit must have at least this many bytes of its region after it, or it can't
/// be a real `AP_IPC_ROOT` (everything up to `current_stage_name`).
const MIN_ROOT_BYTES: usize = ap_ipc::offsets::CURRENT_STAGE_NAME + 8;

/// Streams `regions` through `pattern`, calling `on_hit(mem, hit_address,
/// region_end)` for every match; stops early as soon as `on_hit` returns true.
/// Returns the number of bytes actually read.
///
/// One reusable buffer, SIMD substring search, and partial-read salvage (see
/// `ProcessMemory::read_into`).
pub fn scan_regions<M: ProcessMemory + ?Sized>(
    mem: &mut M,
    regions: &[MemoryRegion],
    pattern: &[u8],
    on_hit: &mut dyn FnMut(&mut M, usize, usize) -> bool,
) -> usize {
    scan_regions_chunked(mem, regions, pattern, SCAN_CHUNK, on_hit)
}

fn scan_regions_chunked<M: ProcessMemory + ?Sized>(
    mem: &mut M,
    regions: &[MemoryRegion],
    pattern: &[u8],
    chunk: usize,
    on_hit: &mut dyn FnMut(&mut M, usize, usize) -> bool,
) -> usize {
    if pattern.is_empty() {
        return 0;
    }
    let overlap = pattern.len() - 1;
    assert!(chunk > overlap, "scan chunk must be larger than the pattern");
    let finder = memchr::memmem::Finder::new(pattern);
    let mut buf = vec![0u8; chunk];
    let mut scanned = 0usize;

    for region in regions {
        let end = region.base + region.size;
        let mut pos = region.base;
        while pos < end {
            let want = chunk.min(end - pos);
            let got = mem.read_into(pos, &mut buf[..want]);
            scanned += got;

            let mut from = 0;
            while let Some(i) = finder.find(&buf[from..got]) {
                let abs = from + i;
                if on_hit(mem, pos + abs, end) {
                    return scanned;
                }
                from = abs + 1;
            }

            if got == want {
                if pos + want >= end {
                    break;
                }
                // Re-read the last `overlap` bytes so a match straddling the
                // chunk boundary isn't missed (and none can be found twice).
                pos += want - overlap;
            } else {
                // Short read: a page after `pos + got` is unreadable (its
                // protection changed since the regions were enumerated).
                // Skip just that page and carry on.
                pos = ((pos + got) & !0xFFF) + 0x1000;
            }
        }
    }
    scanned
}

fn has_marker<M: ProcessMemory + ?Sized>(mem: &mut M, addr: usize) -> bool {
    matches!(mem.read_bytes(addr, ap_ipc::AP_IPC_MAGIC.len()), Ok(b) if b == ap_ipc::AP_IPC_MAGIC)
}

/// Plants a sentinel in `current_scene_index` of every candidate and returns
/// the first one the running game overwrites (i.e. the live `AP_IPC_ROOT`;
/// any alias of it is equally good). Candidates the game didn't touch get
/// their original value back.
fn probe_live<M: ProcessMemory + ?Sized>(mem: &mut M, candidates: &[usize]) -> Option<usize> {
    let sentinel = LIVENESS_SENTINEL.to_le_bytes();

    // (root, field address, original value)
    let mut armed: Vec<(usize, usize, [u8; 2])> = Vec::new();
    for &root in candidates {
        let field = root + ap_ipc::offsets::CURRENT_SCENE_INDEX;
        let Ok(orig) = mem.read_bytes(field, 2) else { continue };
        if mem.write_bytes(field, &sentinel).is_ok() {
            armed.push((root, field, [orig[0], orig[1]]));
        }
    }
    if armed.is_empty() {
        return None;
    }

    let deadline = Instant::now() + LIVENESS_TIMEOUT;
    let mut live = None;
    'wait: loop {
        for &(root, field, _) in &armed {
            if let Ok(v) = mem.read_bytes(field, 2) {
                if v.as_slice() != sentinel {
                    live = Some(root);
                    break 'wait;
                }
            }
        }
        if Instant::now() >= deadline {
            break;
        }
        std::thread::sleep(LIVENESS_POLL);
    }

    // Put back anything the game never touched (dead copies).
    for &(_, field, orig) in &armed {
        if let Ok(v) = mem.read_bytes(field, 2) {
            if v.as_slice() == sentinel {
                let _ = mem.write_bytes(field, &orig);
            }
        }
    }
    live
}

/// Per-process memory of an `AP_IPC_ROOT` search. Keep one per emulator pid
/// and pass it to every `find_ap_ipc_root` call for that process.
pub struct RootSearch {
    candidates: Vec<usize>,
    next_probe: Option<Instant>,
    last_scan_finished: Option<Instant>,
    rescan_interval: Duration,
    scan_count: u32,
    last_scan_bytes: usize,
    last_scan_time: Duration,
}

impl RootSearch {
    pub fn new() -> Self {
        RootSearch {
            candidates: Vec::new(),
            next_probe: None,
            last_scan_finished: None,
            rescan_interval: Duration::from_secs(10),
            scan_count: 0,
            last_scan_bytes: 0,
            last_scan_time: Duration::ZERO,
        }
    }

    /// Every address where the marker has been seen (live aliases and dead copies).
    pub fn candidates(&self) -> &[usize] {
        &self.candidates
    }

    /// How many full memory scans this search has run.
    pub fn scan_count(&self) -> u32 {
        self.scan_count
    }

    /// (bytes read, wall time) of the most recent full scan.
    pub fn last_scan_summary(&self) -> (usize, Duration) {
        (self.last_scan_bytes, self.last_scan_time)
    }
}

impl Default for RootSearch {
    fn default() -> Self {
        Self::new()
    }
}

fn root_not_found(candidates: usize) -> MemError {
    MemError::RootNotFound(if candidates == 0 {
        "AP_IPC_ROOT marker not found in the emulator's memory".to_string()
    } else {
        format!(
            "found {candidates} copy/copies of the AP_IPC_ROOT marker, but the game isn't updating \
             any of them (paused, or still booting?)"
        )
    })
}

/// Finds the LIVE `AP_IPC_ROOT` in `mem` and returns its address.
///
/// 1. Cached candidates from earlier calls are re-checked and probed first
///    (cheap: no scanning).
/// 2. Otherwise, at most once per `rescan_interval`, scans likely guest-RAM
///    regions first, probing each hit immediately and returning at the first
///    live one.
///
/// `Err(MemError::RootNotFound)` means "not yet": call again later (the error
/// text is stable between retries). Never returns a copy the game isn't
/// updating.
pub fn find_ap_ipc_root<M: ProcessMemory + ?Sized>(
    mem: &mut M,
    search: &mut RootSearch,
) -> MemResult<usize> {
    // Forget candidates that no longer hold the marker (game restarted,
    // memory remapped).
    search.candidates.retain(|&addr| has_marker(mem, addr));

    let mut known_dead: Vec<usize> = Vec::new();
    if !search.candidates.is_empty() && search.next_probe.map_or(true, |t| Instant::now() >= t) {
        match probe_live(mem, &search.candidates) {
            Some(addr) => {
                search.next_probe = None;
                return Ok(addr);
            },
            None => {
                known_dead = search.candidates.clone();
                search.next_probe = Some(Instant::now() + DEAD_PROBE_BACKOFF);
            },
        }
    }

    let scan_due = search.last_scan_finished.map_or(true, |t| t.elapsed() >= search.rescan_interval);
    if !scan_due {
        return Err(root_not_found(search.candidates.len()));
    }

    let started = Instant::now();
    let regions = mem.scannable_regions()?;
    let mut live: Option<usize> = None;
    let bytes = scan_regions(mem, &regions, &ap_ipc::AP_IPC_MAGIC, &mut |mem, addr, region_end| {
        if region_end - addr < MIN_ROOT_BYTES || known_dead.contains(&addr) {
            return false;
        }
        if !search.candidates.contains(&addr) {
            search.candidates.push(addr);
        }
        match probe_live(mem, &[addr]) {
            Some(root) => {
                live = Some(root);
                true
            },
            None => false,
        }
    });
    search.scan_count += 1;
    search.last_scan_bytes = bytes;
    search.last_scan_time = started.elapsed();
    search.last_scan_finished = Some(Instant::now());

    match live {
        Some(addr) => Ok(addr),
        None => Err(root_not_found(search.candidates.len())),
    }
}

/// Emulator process names this client knows how to attach to. Mirrors the
/// candidate list `SSHDClient.py` scans for.
pub const SUPPORTED_EMULATOR_NAMES: &[&str] =
    &["Ryujinx", "yuzu", "suyu", "sudachi", "eden"];

// ─────────────────────────────────────────────────────────────────────────
// Linux backend
// ─────────────────────────────────────────────────────────────────────────

#[cfg(target_os = "linux")]
pub mod linux {
    use super::*;
    use std::fs::{self, File, OpenOptions};
    use std::os::unix::fs::FileExt;

    const MIN_SCAN_REGION_SIZE: usize = 1024 * 1024; // 1 MiB, matches Python

    const SKIP_EXTENSIONS: &[&str] = &[
        ".so", ".py", ".pyc", ".pyo", ".dat", ".cache", ".bin", ".ttf", ".otf",
        ".ttc", ".gz", ".xz", ".zst", ".bz2", ".conf", ".locale", ".txt",
        ".json", ".xml", ".yaml", ".yml", ".png", ".jpg", ".svg", ".ico",
        ".dll", ".exe", ".pdb", ".mo", ".gmo",
    ];
    const SKIP_PATH_FRAGMENTS: &[&str] = &[
        "/usr/lib", "/usr/share", "/lib/", "/lib64/", "/etc/", "/nix/store",
        "/gnu/store", "/proc/", "/sys/",
    ];

    fn is_library_or_data(pathname: &str) -> bool {
        if pathname.is_empty() {
            return false; // anonymous — keep
        }
        if pathname.starts_with('[') {
            return false; // [heap], [anon:*], [stack], [vdso] — keep
        }
        if pathname.contains("memfd:") {
            return false;
        }
        if pathname.starts_with("/dev/") {
            return false;
        }
        let lower = pathname.to_lowercase();
        if SKIP_EXTENSIONS.iter().any(|ext| lower.ends_with(ext)) {
            return true;
        }
        if lower.contains(".so.") || lower.ends_with(".so") {
            return true;
        }
        SKIP_PATH_FRAGMENTS.iter().any(|frag| lower.contains(frag))
    }

    pub struct LinuxProcessMemory {
        pid: i32,
        mem_file: File,
    }

    impl LinuxProcessMemory {
        pub fn attach(pid: i32) -> MemResult<Self> {
            attach_ptrace(pid);
            let mem_path = format!("/proc/{pid}/mem");
            let mem_file = OpenOptions::new()
                .read(true)
                .write(true)
                .open(&mem_path)
                .map_err(|e| match e.kind() {
                    io::ErrorKind::PermissionDenied => MemError::PermissionDenied(format!(
                        "opening {mem_path}. Try 'sudo sysctl -w kernel.yama.ptrace_scope=0' \
                         or run this client with sudo."
                    )),
                    io::ErrorKind::NotFound => MemError::ProcessNotFound,
                    _ => MemError::Io(e),
                })?;
            Ok(LinuxProcessMemory { pid, mem_file })
        }

        fn parse_maps_line(line: &str) -> Option<(usize, usize, String, String)> {
            // "start-end perms offset dev inode [pathname]"
            let mut parts = line.splitn(6, ' ');
            let range = parts.next()?;
            let perms = parts.next()?.to_string();
            let (start_s, end_s) = range.split_once('-')?;
            let start = usize::from_str_radix(start_s, 16).ok()?;
            let end = usize::from_str_radix(end_s, 16).ok()?;
            // Skip offset, dev, inode; remaining (if any) is the pathname,
            // possibly with leading whitespace.
            let _offset = parts.next();
            let _dev = parts.next();
            let _inode = parts.next();
            let pathname = parts.next().unwrap_or("").trim().to_string();
            Some((start, end - start, perms, pathname))
        }

        fn get_rss_map(&self) -> std::collections::HashMap<usize, i64> {
            let mut map = std::collections::HashMap::new();
            let smaps_path = format!("/proc/{}/smaps", self.pid);
            let Ok(contents) = fs::read_to_string(&smaps_path) else {
                return map;
            };
            let mut current_start: Option<usize> = None;
            for line in contents.lines() {
                if let Some((start, _, _, _)) = Self::parse_maps_line(line) {
                    current_start = Some(start);
                    continue;
                }
                if let Some(start) = current_start {
                    if let Some(rest) = line.strip_prefix("Rss:") {
                        if let Some(kb_str) = rest.split_whitespace().next() {
                            if let Ok(kb) = kb_str.parse::<i64>() {
                                map.insert(start, kb * 1024);
                            }
                        }
                    }
                }
            }
            map
        }

        /// Regions worth scanning for game data: readable, not an obvious
        /// shared-library/data-file mapping, resident (RSS > 0) when RSS
        /// info is available, coalesced, and sorted by RSS descending.
        /// Mirrors `enumerate_scannable_regions()` in process_memory.py.
        pub fn enumerate_scannable_regions(&mut self) -> MemResult<Vec<MemoryRegion>> {
            let rss_map = self.get_rss_map();
            let mut raw = self.enumerate_regions()?;
            for r in &mut raw {
                r.rss = *rss_map.get(&r.base).unwrap_or(&0);
            }

            let mut candidates: Vec<MemoryRegion> = raw
                .into_iter()
                .filter(|r| r.is_readable() && !is_library_or_data(&r.pathname))
                .collect();

            let has_rss_info = candidates.iter().any(|r| r.rss > 0);
            if has_rss_info {
                candidates.retain(|r| r.rss > 0);
            }

            let mut coalesced: Vec<MemoryRegion> = Vec::new();
            for r in candidates {
                if let Some(prev) = coalesced.last_mut() {
                    if prev.perms == r.perms && prev.base + prev.size == r.base {
                        prev.size += r.size;
                        prev.rss = prev.rss.max(0) + r.rss.max(0);
                        continue;
                    }
                }
                coalesced.push(r);
            }

            let mut result: Vec<MemoryRegion> =
                coalesced.into_iter().filter(|r| r.size >= MIN_SCAN_REGION_SIZE).collect();
            result.sort_by(|a, b| b.rss.max(0).cmp(&a.rss.max(0)));
            Ok(result)
        }
    }

    impl ProcessMemory for LinuxProcessMemory {
        fn read_into(&mut self, address: usize, buf: &mut [u8]) -> usize {
            self.mem_file.read_at(buf, address as u64).unwrap_or(0)
        }

        fn scannable_regions(&mut self) -> MemResult<Vec<MemoryRegion>> {
            self.enumerate_scannable_regions()
        }

        fn read_bytes(&mut self, address: usize, size: usize) -> MemResult<Vec<u8>> {
            let mut buf = vec![0u8; size];
            let n = self.mem_file.read_at(&mut buf, address as u64)?;
            if n != size {
                return Err(MemError::ShortRead { addr: address, expected: size, got: n });
            }
            Ok(buf)
        }

        fn write_bytes(&mut self, address: usize, data: &[u8]) -> MemResult<()> {
            let n = self.mem_file.write_at(data, address as u64)?;
            if n != data.len() {
                return Err(MemError::ShortWrite {
                    addr:     address,
                    expected: data.len(),
                    wrote:    n,
                });
            }
            Ok(())
        }

        fn enumerate_regions(&mut self) -> MemResult<Vec<MemoryRegion>> {
            let maps_path = format!("/proc/{}/maps", self.pid);
            let contents = fs::read_to_string(&maps_path).map_err(|_| MemError::ProcessNotFound)?;
            let mut regions = Vec::new();
            for line in contents.lines() {
                if let Some((base, size, perms, pathname)) = Self::parse_maps_line(line) {
                    regions.push(MemoryRegion { base, size, perms, pathname, rss: -1 });
                }
            }
            Ok(regions)
        }

        /// Override: use the RSS/library-filtered region set, matching
        /// `_LinuxProcessMemory.pattern_scan` calling
        /// `enumerate_scannable_regions()` instead of `enumerate_regions()`.
        fn pattern_scan(&mut self, pattern: &[u8]) -> MemResult<Vec<usize>> {
            const CHUNK: usize = 4 * 1024 * 1024;
            let mut results = Vec::new();
            for region in self.enumerate_scannable_regions()? {
                let mut pos = region.base;
                let end = region.base + region.size;
                while pos < end {
                    let to_read = CHUNK.min(end - pos);
                    let data = match self.read_bytes(pos, to_read) {
                        Ok(d) => d,
                        Err(_) => {
                            pos += to_read;
                            continue;
                        },
                    };
                    let mut offset = 0usize;
                    while let Some(idx) = find_subslice(&data[offset..], pattern) {
                        let abs_idx = offset + idx;
                        results.push(pos + abs_idx);
                        offset = abs_idx + 1;
                        if offset >= data.len() {
                            break;
                        }
                    }
                    if to_read == CHUNK {
                        pos += to_read - pattern.len() + 1;
                    } else {
                        pos += to_read;
                    }
                }
            }
            Ok(results)
        }
    }

    /// Attach + immediately detach via ptrace. On kernels with
    /// `yama.ptrace_scope >= 1` this is what makes `/proc/<pid>/mem`
    /// readable/writable for the rest of our process's lifetime, exactly
    /// as `process_memory.py`'s `_attach_ptrace` does. Best-effort: if it
    /// fails (e.g. no libc, no permission), we proceed anyway — opening
    /// `/proc/<pid>/mem` will simply fail later with a clear error if
    /// ptrace really was required.
    fn attach_ptrace(pid: i32) {
        const PTRACE_ATTACH: u32 = 16;
        const PTRACE_DETACH: u32 = 17;
        unsafe {
            if libc::ptrace(PTRACE_ATTACH, pid, 0, 0) == -1 {
                return;
            }
            let mut status = 0;
            libc::waitpid(pid, &mut status, 0);
            libc::ptrace(PTRACE_DETACH, pid, 0, 0);
        }
    }

    /// Find a running process by name (matches against `/proc/<pid>/comm`
    /// and the `/proc/<pid>/exe` basename), returning the first PID found
    /// among `SUPPORTED_EMULATOR_NAMES`-style candidates.
    pub fn find_process_by_names(names: &[&str]) -> Option<i32> {
        find_processes_by_names(names).first().map(|p| p.0)
    }

    /// Like `find_process_by_names`, but returns EVERY matching process
    /// (pid + comm name) so callers can try each one.
    pub fn find_processes_by_names(names: &[&str]) -> Vec<(i32, String)> {
        let mut found = Vec::new();
        let Ok(entries) = fs::read_dir("/proc") else { return found };
        for entry in entries.flatten() {
            let file_name = entry.file_name();
            let Some(pid_str) = file_name.to_str() else { continue };
            let Ok(pid) = pid_str.parse::<i32>() else { continue };

            let comm_path = format!("/proc/{pid}/comm");
            if let Ok(comm) = fs::read_to_string(&comm_path) {
                let comm = comm.trim();
                if names.iter().any(|n| comm.eq_ignore_ascii_case(n)) {
                    found.push((pid, comm.to_string()));
                }
            }
        }
        found
    }
}

// ─────────────────────────────────────────────────────────────────────────
// Windows backend
// ─────────────────────────────────────────────────────────────────────────

#[cfg(target_os = "windows")]
pub mod windows {
    use super::*;
    use std::ffi::OsString;
    use std::os::windows::ffi::OsStringExt;
    use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
    use windows_sys::Win32::System::Diagnostics::Debug::{ReadProcessMemory, WriteProcessMemory};
    use windows_sys::Win32::System::Diagnostics::ToolHelp::{
        CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W,
        TH32CS_SNAPPROCESS,
    };
    use windows_sys::Win32::System::Memory::{
        VirtualQueryEx, MEMORY_BASIC_INFORMATION, MEM_COMMIT, MEM_IMAGE, MEM_MAPPED, PAGE_GUARD,
    };
    use windows_sys::Win32::System::Threading::{
        OpenProcess, PROCESS_QUERY_INFORMATION, PROCESS_VM_OPERATION, PROCESS_VM_READ,
        PROCESS_VM_WRITE,
    };

    pub struct WindowsProcessMemory {
        handle: HANDLE,
    }

    impl WindowsProcessMemory {
        pub fn attach(pid: u32) -> MemResult<Self> {
            // Best-effort, once per run: lets an elevated client open processes
            // owned by other users / higher-integrity contexts.
            static DEBUG_PRIV: std::sync::Once = std::sync::Once::new();
            DEBUG_PRIV.call_once(enable_debug_privilege);

            let access = PROCESS_QUERY_INFORMATION
                | PROCESS_VM_READ
                | PROCESS_VM_WRITE
                | PROCESS_VM_OPERATION;
            let handle = unsafe { OpenProcess(access, 0, pid) };
            if handle == 0 {
                // Must be read immediately, before any other Win32 call.
                let err = io::Error::last_os_error();
                return Err(match err.raw_os_error() {
                    Some(5) => MemError::PermissionDenied(format!(
                        "OpenProcess on pid {pid} was denied (Windows error 5, ACCESS_DENIED). \
                         If running as Administrator doesn't help, security software or an \
                         anti-cheat driver may be blocking memory access to the emulator, or \
                         the emulator is running as a different user / in a sandbox."
                    )),
                    // ERROR_INVALID_PARAMETER: the pid no longer exists.
                    Some(87) => MemError::ProcessNotFound,
                    _ => MemError::Io(io::Error::new(
                        err.kind(),
                        format!("OpenProcess on pid {pid} failed: {err}"),
                    )),
                });
            }
            Ok(WindowsProcessMemory { handle })
        }
    }

    impl WindowsProcessMemory {
        /// Regions to scan for `AP_IPC_ROOT`, in scan order.
        ///
        /// Differences from `enumerate_scannable_regions`:
        /// - Adjacent readable regions are MERGED before the size filter.
        ///   Emulators flip page protections constantly (write tracking, JIT),
        ///   which makes `VirtualQueryEx` report guest RAM as many small
        ///   fragments; filtering each fragment by size could drop the very
        ///   fragment holding `AP_IPC_ROOT`.
        /// - The size floor is the size of `AP_IPC_ROOT` itself, not an
        ///   arbitrary 1 MiB.
        /// - `MEM_MAPPED` regions (where emulators put guest RAM) come first,
        ///   largest first, then `MEM_PRIVATE`. The first live hit ends the
        ///   scan, so this is what turns a ~minute-long full walk into a few
        ///   seconds. Loaded modules (`MEM_IMAGE`) are never scanned.
        fn scan_order_regions(&mut self) -> MemResult<Vec<MemoryRegion>> {
            const READABLE: &[u32] = &[0x02, 0x04, 0x08, 0x20, 0x40, 0x80];

            // (base, size, is_mapped)
            let mut spans: Vec<(usize, usize, bool)> = Vec::new();
            let mut address: u64 = 0x10000;
            let max_address: u64 = 0x7FFF_FFFF_FFFF;

            unsafe {
                while address < max_address {
                    let mut mbi: MEMORY_BASIC_INFORMATION = std::mem::zeroed();
                    let result = VirtualQueryEx(
                        self.handle,
                        address as *const _,
                        &mut mbi,
                        std::mem::size_of::<MEMORY_BASIC_INFORMATION>(),
                    );
                    if result == 0 {
                        address += 0x1000;
                        continue;
                    }

                    let rbase = mbi.BaseAddress as u64;
                    let rsize = mbi.RegionSize as u64;
                    if rsize == 0 {
                        address += 0x1000;
                        continue;
                    }

                    let base_prot = mbi.Protect & 0xFF;
                    let usable = mbi.State == MEM_COMMIT
                        && READABLE.contains(&base_prot)
                        && (mbi.Protect & PAGE_GUARD) == 0
                        && mbi.Type != MEM_IMAGE;
                    if usable {
                        let mapped = mbi.Type == MEM_MAPPED;
                        let extends = matches!(
                            spans.last(),
                            Some(prev) if prev.2 == mapped && (prev.0 + prev.1) as u64 == rbase
                        );
                        if extends {
                            spans.last_mut().unwrap().1 += rsize as usize;
                        } else {
                            spans.push((rbase as usize, rsize as usize, mapped));
                        }
                    }

                    address = rbase + rsize;
                }
            }

            spans.retain(|s| s.1 >= ap_ipc::offsets::TOTAL_SIZE);
            spans.sort_by(|a, b| b.2.cmp(&a.2).then(b.1.cmp(&a.1)));
            Ok(spans
                .into_iter()
                .map(|(base, size, mapped)| MemoryRegion {
                    base,
                    size,
                    perms: "rw-p".to_string(),
                    pathname: if mapped { "[mapped]" } else { "[private]" }.to_string(),
                    rss: -1,
                })
                .collect())
        }
    }

    impl Drop for WindowsProcessMemory {
        fn drop(&mut self) {
            unsafe {
                CloseHandle(self.handle);
            }
        }
    }

    /// Enables `SeDebugPrivilege` on this process's token, if we hold it
    /// (elevated administrators do, but it's disabled by default). Silent
    /// no-op on failure -- `attach` reports the real error if access is
    /// still denied.
    fn enable_debug_privilege() {
        use windows_sys::Win32::Security::{
            AdjustTokenPrivileges, LookupPrivilegeValueW, LUID_AND_ATTRIBUTES,
            SE_PRIVILEGE_ENABLED, TOKEN_ADJUST_PRIVILEGES, TOKEN_PRIVILEGES,
        };
        use windows_sys::Win32::System::Threading::{GetCurrentProcess, OpenProcessToken};
        unsafe {
            let mut token: HANDLE = 0;
            if OpenProcessToken(GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES, &mut token) == 0 {
                return;
            }
            let name: Vec<u16> = "SeDebugPrivilege\0".encode_utf16().collect();
            let mut luid = std::mem::zeroed();
            if LookupPrivilegeValueW(std::ptr::null(), name.as_ptr(), &mut luid) != 0 {
                let tp = TOKEN_PRIVILEGES {
                    PrivilegeCount: 1,
                    Privileges: [LUID_AND_ATTRIBUTES { Luid: luid, Attributes: SE_PRIVILEGE_ENABLED }],
                };
                AdjustTokenPrivileges(
                    token,
                    0,
                    &tp,
                    0,
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                );
            }
            CloseHandle(token);
        }
    }

    /// Minimum region size worth scanning — mirrors `MIN_SCAN_REGION_SIZE`
    /// on the Linux side. Cuts out the very large number of small
    /// (sub-1-MiB) heap/stack/metadata regions every process has, which
    /// cost real time (one `ReadProcessMemory` call each) but are never
    /// realistic homes for `AP_IPC_ROOT`.
    const MIN_SCAN_REGION_SIZE: usize = 1024 * 1024; // 1 MiB, matches Linux

    impl WindowsProcessMemory {
        /// Regions worth scanning for game data: readable, committed, and
        /// NOT a loaded PE module (`MEM_IMAGE` — every loaded .exe/.dll's
        /// code and data, which can easily add up to several hundred MB
        /// for an emulator plus its runtime, but can never be guest RAM).
        /// `MEM_PRIVATE` and `MEM_MAPPED` regions are both kept: emulators
        /// commonly back guest RAM with anonymous/pagefile-backed mapped
        /// memory (mapping the same pages at multiple host addresses for
        /// "fastmem"/mirroring purposes — see `pattern_scan_unique`'s docs),
        /// so excluding `MEM_MAPPED` outright risks missing it entirely.
        /// Also drops anything under `MIN_SCAN_REGION_SIZE`, matching the
        /// Linux backend. This is what makes the one-time `AP_IPC_ROOT`
        /// scan take a fraction of its previous time: on a typical
        /// Ryujinx/yuzu process the loaded-module set alone is a very
        /// large chunk of the readable address space this scan used to
        /// walk through byte-for-byte for no reason.
        pub fn enumerate_scannable_regions(&mut self) -> MemResult<Vec<MemoryRegion>> {
            const READABLE: &[u32] = &[0x02, 0x04, 0x08, 0x20, 0x40, 0x80];
            const WRITABLE: &[u32] = &[0x04, 0x08, 0x40, 0x80];
            const EXECUTABLE: &[u32] = &[0x10, 0x20, 0x40, 0x80];

            let mut regions = Vec::new();
            let mut address: u64 = 0x10000;
            let max_address: u64 = 0x7FFF_FFFF_FFFF;

            unsafe {
                loop {
                    if address >= max_address {
                        break;
                    }
                    let mut mbi: MEMORY_BASIC_INFORMATION = std::mem::zeroed();
                    let result = VirtualQueryEx(
                        self.handle,
                        address as *const _,
                        &mut mbi,
                        std::mem::size_of::<MEMORY_BASIC_INFORMATION>(),
                    );
                    if result == 0 {
                        address += 0x1000;
                        continue;
                    }

                    let rbase = mbi.BaseAddress as u64;
                    let rsize = mbi.RegionSize as u64;
                    if rsize == 0 {
                        address += 0x1000;
                        continue;
                    }

                    let base_prot = mbi.Protect & 0xFF;
                    let is_committed = mbi.State == MEM_COMMIT;
                    let is_readable =
                        READABLE.contains(&base_prot) && (mbi.Protect & PAGE_GUARD) == 0;
                    let is_module_image = mbi.Type == MEM_IMAGE;

                    if is_committed
                        && is_readable
                        && !is_module_image
                        && (rsize as usize) >= MIN_SCAN_REGION_SIZE
                    {
                        let mut perms = String::from("r");
                        perms.push(if WRITABLE.contains(&base_prot) { 'w' } else { '-' });
                        perms.push(if EXECUTABLE.contains(&base_prot) { 'x' } else { '-' });
                        perms.push('p');
                        regions.push(MemoryRegion {
                            base:     rbase as usize,
                            size:     rsize as usize,
                            perms,
                            pathname: String::new(),
                            rss:      -1,
                        });
                    }

                    address = rbase + rsize;
                }
            }
            Ok(regions)
        }
    }

    impl ProcessMemory for WindowsProcessMemory {
        /// Keeps a partial read: `ReadProcessMemory` reports how many bytes it
        /// copied before hitting an inaccessible page (ERROR_PARTIAL_COPY).
        fn read_into(&mut self, address: usize, buf: &mut [u8]) -> usize {
            let mut read: usize = 0;
            unsafe {
                ReadProcessMemory(
                    self.handle,
                    address as *const _,
                    buf.as_mut_ptr() as *mut _,
                    buf.len(),
                    &mut read,
                );
            }
            read.min(buf.len())
        }

        fn scannable_regions(&mut self) -> MemResult<Vec<MemoryRegion>> {
            self.scan_order_regions()
        }

        fn read_bytes(&mut self, address: usize, size: usize) -> MemResult<Vec<u8>> {
            let mut buf = vec![0u8; size];
            let mut read: usize = 0;
            let ok = unsafe {
                ReadProcessMemory(
                    self.handle,
                    address as *const _,
                    buf.as_mut_ptr() as *mut _,
                    size,
                    &mut read,
                )
            };
            if ok == 0 || read != size {
                return Err(MemError::ShortRead { addr: address, expected: size, got: read });
            }
            Ok(buf)
        }

        fn write_bytes(&mut self, address: usize, data: &[u8]) -> MemResult<()> {
            let mut written: usize = 0;
            let ok = unsafe {
                WriteProcessMemory(
                    self.handle,
                    address as *const _,
                    data.as_ptr() as *const _,
                    data.len(),
                    &mut written,
                )
            };
            if ok == 0 || written != data.len() {
                return Err(MemError::ShortWrite {
                    addr:     address,
                    expected: data.len(),
                    wrote:    written,
                });
            }
            Ok(())
        }

        fn enumerate_regions(&mut self) -> MemResult<Vec<MemoryRegion>> {
            const READABLE: &[u32] = &[0x02, 0x04, 0x08, 0x20, 0x40, 0x80];
            const WRITABLE: &[u32] = &[0x04, 0x08, 0x40, 0x80];
            const EXECUTABLE: &[u32] = &[0x10, 0x20, 0x40, 0x80];

            let mut regions = Vec::new();
            let mut address: u64 = 0x10000;
            let max_address: u64 = 0x7FFF_FFFF_FFFF;

            unsafe {
                loop {
                    if address >= max_address {
                        break;
                    }
                    let mut mbi: MEMORY_BASIC_INFORMATION = std::mem::zeroed();
                    let result = VirtualQueryEx(
                        self.handle,
                        address as *const _,
                        &mut mbi,
                        std::mem::size_of::<MEMORY_BASIC_INFORMATION>(),
                    );
                    if result == 0 {
                        address += 0x1000;
                        continue;
                    }

                    let rbase = mbi.BaseAddress as u64;
                    let rsize = mbi.RegionSize as u64;
                    if rsize == 0 {
                        address += 0x1000;
                        continue;
                    }

                    let base_prot = mbi.Protect & 0xFF;
                    let is_committed = mbi.State == MEM_COMMIT;
                    let is_readable =
                        READABLE.contains(&base_prot) && (mbi.Protect & PAGE_GUARD) == 0;

                    if is_committed && is_readable {
                        let mut perms = String::from("r");
                        perms.push(if WRITABLE.contains(&base_prot) { 'w' } else { '-' });
                        perms.push(if EXECUTABLE.contains(&base_prot) { 'x' } else { '-' });
                        perms.push('p');
                        regions.push(MemoryRegion {
                            base:     rbase as usize,
                            size:     rsize as usize,
                            perms,
                            pathname: String::new(),
                            rss:      -1,
                        });
                    }

                    address = rbase + rsize;
                }
            }
            Ok(regions)
        }

        /// Override: scan only `enumerate_scannable_regions()`'s filtered
        /// set (skips loaded-module images and sub-1-MiB regions) instead
        /// of every readable region, matching the Linux backend's own
        /// override of this same default trait method. This is the
        /// change that takes the one-time `AP_IPC_ROOT` scan from ~30s
        /// down to a fraction of that on Windows.
        fn pattern_scan(&mut self, pattern: &[u8]) -> MemResult<Vec<usize>> {
            const CHUNK: usize = 4 * 1024 * 1024;
            let mut results = Vec::new();
            for region in self.enumerate_scannable_regions()? {
                let mut pos = region.base;
                let end = region.base + region.size;
                while pos < end {
                    let to_read = CHUNK.min(end - pos);
                    let data = match self.read_bytes(pos, to_read) {
                        Ok(d) => d,
                        Err(_) => {
                            pos += to_read;
                            continue;
                        },
                    };
                    let mut offset = 0usize;
                    while let Some(idx) = find_subslice(&data[offset..], pattern) {
                        let abs_idx = offset + idx;
                        results.push(pos + abs_idx);
                        offset = abs_idx + 1;
                        if offset >= data.len() {
                            break;
                        }
                    }
                    if to_read == CHUNK {
                        pos += to_read - pattern.len() + 1;
                    } else {
                        pos += to_read;
                    }
                }
            }
            Ok(results)
        }
    }

    /// Find a running process by (case-insensitive, extension-optional)
    /// image name, e.g. "Ryujinx" matches "Ryujinx.exe".
    pub fn find_process_by_names(names: &[&str]) -> Option<u32> {
        find_processes_by_names(names).first().map(|p| p.0)
    }

    /// Like `find_process_by_names`, but returns EVERY matching process
    /// (pid + exe name), so callers can try each one instead of committing
    /// to whichever happens to be listed first.
    pub fn find_processes_by_names(names: &[&str]) -> Vec<(u32, String)> {
        unsafe {
            let snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
            if snapshot == 0 || snapshot == -1i32 as isize as HANDLE {
                return Vec::new();
            }
            let mut entry: PROCESSENTRY32W = std::mem::zeroed();
            entry.dwSize = std::mem::size_of::<PROCESSENTRY32W>() as u32;

            let mut found: Vec<(u32, String)> = Vec::new();
            if Process32FirstW(snapshot, &mut entry) != 0 {
                loop {
                    let len = entry.szExeFile.iter().position(|&c| c == 0).unwrap_or(0);
                    let exe_name = OsString::from_wide(&entry.szExeFile[..len])
                        .to_string_lossy()
                        .to_string();
                    let stem = exe_name.strip_suffix(".exe").unwrap_or(&exe_name);
                    if names.iter().any(|n| stem.eq_ignore_ascii_case(n)) {
                        found.push((entry.th32ProcessID, exe_name.clone()));
                    }
                    if Process32NextW(snapshot, &mut entry) == 0 {
                        break;
                    }
                }
            }
            CloseHandle(snapshot);
            found
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────
// macOS backend
// ─────────────────────────────────────────────────────────────────────────

/// Uses the Mach VM APIs (`task_for_pid` + `mach_vm_*`). Note that macOS
/// only hands out a task port for another process if the caller is root,
/// or the target is debuggable (`get-task-allow`) and the caller is an
/// authorized developer-tools process. In practice: run the client with
/// `sudo`. Emulators shipped with the hardened runtime and without
/// `get-task-allow` may still refuse, even for root, if SIP applies.
#[cfg(target_os = "macos")]
pub mod macos {
    use super::*;
    use std::os::raw::c_int;
    use std::process::Command;

    type MachPort = u32;
    type KernReturn = i32;

    const VM_REGION_BASIC_INFO_64: c_int = 9;
    /// `sizeof(vm_region_basic_info_data_64_t) / sizeof(int)`
    const VM_REGION_BASIC_INFO_COUNT_64: u32 = 9;
    const VM_PROT_READ: i32 = 1;
    const VM_PROT_WRITE: i32 = 2;
    const VM_PROT_EXECUTE: i32 = 4;

    const MIN_SCAN_REGION_SIZE: usize = 1024 * 1024; // 1 MiB, matches Linux/Windows

    extern "C" {
        static mach_task_self_: MachPort;

        fn task_for_pid(target_tport: MachPort, pid: c_int, t: *mut MachPort) -> KernReturn;
        fn mach_port_deallocate(task: MachPort, name: MachPort) -> KernReturn;
        fn mach_vm_region(
            target_task: MachPort,
            address: *mut u64,
            size: *mut u64,
            flavor: c_int,
            info: *mut i32,
            info_cnt: *mut u32,
            object_name: *mut MachPort,
        ) -> KernReturn;
        fn mach_vm_read_overwrite(
            target_task: MachPort,
            address: u64,
            size: u64,
            data: u64,
            out_size: *mut u64,
        ) -> KernReturn;
        fn mach_vm_write(
            target_task: MachPort,
            address: u64,
            data: usize,
            data_cnt: u32,
        ) -> KernReturn;
    }

    pub struct MacOsProcessMemory {
        task: MachPort,
    }

    impl MacOsProcessMemory {
        pub fn attach(pid: i32) -> MemResult<Self> {
            let mut task: MachPort = 0;
            let kr = unsafe { task_for_pid(mach_task_self_, pid, &mut task) };
            if kr != 0 {
                return Err(match kr {
                    // KERN_FAILURE (5) is what task_for_pid returns when
                    // the security policy refuses; KERN_INVALID_ARGUMENT (4)
                    // when the pid doesn't exist.
                    4 => MemError::ProcessNotFound,
                    5 => MemError::PermissionDenied(format!(
                        "task_for_pid({pid}) was refused. Run this client with sudo. If that \
                         still fails, the emulator's hardened runtime / SIP is blocking task \
                         access."
                    )),
                    _ => MemError::Io(io::Error::new(
                        io::ErrorKind::Other,
                        format!("task_for_pid({pid}) failed with kern_return {kr}"),
                    )),
                });
            }
            Ok(MacOsProcessMemory { task })
        }

        /// Regions worth scanning: readable and at least `MIN_SCAN_REGION_SIZE`.
        pub fn enumerate_scannable_regions(&mut self) -> MemResult<Vec<MemoryRegion>> {
            Ok(self
                .enumerate_regions()?
                .into_iter()
                .filter(|r| r.is_readable() && r.size >= MIN_SCAN_REGION_SIZE)
                .collect())
        }
    }

    impl Drop for MacOsProcessMemory {
        fn drop(&mut self) {
            unsafe {
                mach_port_deallocate(mach_task_self_, self.task);
            }
        }
    }

    impl ProcessMemory for MacOsProcessMemory {
        fn scannable_regions(&mut self) -> MemResult<Vec<MemoryRegion>> {
            self.enumerate_scannable_regions()
        }

        fn read_bytes(&mut self, address: usize, size: usize) -> MemResult<Vec<u8>> {
            let mut buf = vec![0u8; size];
            let mut out: u64 = 0;
            let kr = unsafe {
                mach_vm_read_overwrite(
                    self.task,
                    address as u64,
                    size as u64,
                    buf.as_mut_ptr() as u64,
                    &mut out,
                )
            };
            if kr != 0 || out as usize != size {
                return Err(MemError::ShortRead {
                    addr:     address,
                    expected: size,
                    got:      if kr == 0 { out as usize } else { 0 },
                });
            }
            Ok(buf)
        }

        fn write_bytes(&mut self, address: usize, data: &[u8]) -> MemResult<()> {
            let kr = unsafe {
                mach_vm_write(self.task, address as u64, data.as_ptr() as usize, data.len() as u32)
            };
            if kr != 0 {
                return Err(MemError::ShortWrite {
                    addr:     address,
                    expected: data.len(),
                    wrote:    0,
                });
            }
            Ok(())
        }

        fn enumerate_regions(&mut self) -> MemResult<Vec<MemoryRegion>> {
            let mut regions = Vec::new();
            let mut address: u64 = 0;
            loop {
                let mut size: u64 = 0;
                let mut info = [0i32; 12];
                let mut count: u32 = VM_REGION_BASIC_INFO_COUNT_64;
                let mut object_name: MachPort = 0;
                let kr = unsafe {
                    mach_vm_region(
                        self.task,
                        &mut address,
                        &mut size,
                        VM_REGION_BASIC_INFO_64,
                        info.as_mut_ptr(),
                        &mut count,
                        &mut object_name,
                    )
                };
                if kr != 0 || size == 0 {
                    break; // KERN_INVALID_ADDRESS once past the last region
                }
                let prot = info[0]; // vm_region_basic_info_64.protection
                let mut perms = String::new();
                perms.push(if prot & VM_PROT_READ != 0 { 'r' } else { '-' });
                perms.push(if prot & VM_PROT_WRITE != 0 { 'w' } else { '-' });
                perms.push(if prot & VM_PROT_EXECUTE != 0 { 'x' } else { '-' });
                perms.push('p');
                regions.push(MemoryRegion {
                    base: address as usize,
                    size: size as usize,
                    perms,
                    pathname: String::new(),
                    rss: -1,
                });
                address = match address.checked_add(size) {
                    Some(a) => a,
                    None => break,
                };
            }
            Ok(regions)
        }

        /// Override: scan only large readable regions, like the other backends.
        fn pattern_scan(&mut self, pattern: &[u8]) -> MemResult<Vec<usize>> {
            const CHUNK: usize = 4 * 1024 * 1024;
            let mut results = Vec::new();
            for region in self.enumerate_scannable_regions()? {
                let mut pos = region.base;
                let end = region.base + region.size;
                while pos < end {
                    let to_read = CHUNK.min(end - pos);
                    let data = match self.read_bytes(pos, to_read) {
                        Ok(d) => d,
                        Err(_) => {
                            pos += to_read;
                            continue;
                        },
                    };
                    let mut offset = 0usize;
                    while let Some(idx) = find_subslice(&data[offset..], pattern) {
                        let abs_idx = offset + idx;
                        results.push(pos + abs_idx);
                        offset = abs_idx + 1;
                        if offset >= data.len() {
                            break;
                        }
                    }
                    if to_read == CHUNK {
                        pos += to_read - pattern.len() + 1;
                    } else {
                        pos += to_read;
                    }
                }
            }
            Ok(results)
        }
    }

    /// Find a running process by executable name (case-insensitive,
    /// basename of the `ps` command path).
    pub fn find_process_by_names(names: &[&str]) -> Option<i32> {
        find_processes_by_names(names).first().map(|p| p.0)
    }

    /// Every matching process (pid + executable name). Uses `ps` rather
    /// than libproc so there's no extra FFI surface to get wrong.
    pub fn find_processes_by_names(names: &[&str]) -> Vec<(i32, String)> {
        let mut found = Vec::new();
        let Ok(output) = Command::new("ps").args(["-axo", "pid=,comm="]).output() else {
            return found;
        };
        let text = String::from_utf8_lossy(&output.stdout);
        for line in text.lines() {
            let line = line.trim_start();
            let Some((pid_s, comm)) = line.split_once(char::is_whitespace) else { continue };
            let Ok(pid) = pid_s.parse::<i32>() else { continue };
            let comm = comm.trim();
            let exe = comm.rsplit('/').next().unwrap_or(comm);
            if names.iter().any(|n| exe.eq_ignore_ascii_case(n)) {
                found.push((pid, exe.to_string()));
            }
        }
        found
    }
}

#[cfg(target_os = "linux")]
pub use linux::{find_process_by_names, find_processes_by_names, LinuxProcessMemory};

#[cfg(target_os = "macos")]
pub use macos::{find_process_by_names, find_processes_by_names, MacOsProcessMemory};

#[cfg(target_os = "windows")]
pub use windows::{find_process_by_names, find_processes_by_names, WindowsProcessMemory};

#[cfg(test)]
mod tests {
    use super::*;

    /// In-memory stand-in for a process: one flat region at `base`.
    struct MockMem {
        base:       usize,
        data:       Vec<u8>,
        /// Root offsets (into `data`) that behave like the running game: they put
        /// the real value straight back into `current_scene_index` after a write.
        live_roots: Vec<usize>,
        /// Byte range of `data` that can't be read (a page that went away).
        bad:        Option<std::ops::Range<usize>>,
    }

    impl MockMem {
        fn new(base: usize, size: usize) -> Self {
            MockMem { base, data: vec![0u8; size], live_roots: vec![], bad: None }
        }

        fn put_root(&mut self, offset: usize, scene: u16) {
            self.data[offset..offset + 8].copy_from_slice(&ap_ipc::AP_IPC_MAGIC);
            self.data[offset + 8..offset + 10].copy_from_slice(&9u16.to_le_bytes());
            let f = offset + ap_ipc::offsets::CURRENT_SCENE_INDEX;
            self.data[f..f + 2].copy_from_slice(&scene.to_le_bytes());
        }

        fn index(&self, address: usize, len: usize) -> Option<usize> {
            address.checked_sub(self.base).filter(|s| s + len <= self.data.len())
        }
    }

    impl ProcessMemory for MockMem {
        fn read_bytes(&mut self, address: usize, size: usize) -> MemResult<Vec<u8>> {
            let err = MemError::ShortRead { addr: address, expected: size, got: 0 };
            let start = self.index(address, size).ok_or(err)?;
            if let Some(bad) = &self.bad {
                if start < bad.end && start + size > bad.start {
                    return Err(MemError::ShortRead { addr: address, expected: size, got: 0 });
                }
            }
            Ok(self.data[start..start + size].to_vec())
        }

        fn read_into(&mut self, address: usize, buf: &mut [u8]) -> usize {
            let Some(start) = self.index(address, buf.len()) else { return 0 };
            let mut got = buf.len();
            if let Some(bad) = &self.bad {
                if start < bad.end && start + got > bad.start {
                    got = bad.start.saturating_sub(start);
                }
            }
            buf[..got].copy_from_slice(&self.data[start..start + got]);
            got
        }

        fn write_bytes(&mut self, address: usize, bytes: &[u8]) -> MemResult<()> {
            let err = MemError::ShortWrite { addr: address, expected: bytes.len(), wrote: 0 };
            let start = self.index(address, bytes.len()).ok_or(err)?;
            self.data[start..start + bytes.len()].copy_from_slice(bytes);
            for &root in &self.live_roots {
                if start == root + ap_ipc::offsets::CURRENT_SCENE_INDEX {
                    self.data[start..start + 2].copy_from_slice(&0xFFFFu16.to_le_bytes());
                }
            }
            Ok(())
        }

        fn enumerate_regions(&mut self) -> MemResult<Vec<MemoryRegion>> {
            Ok(vec![MemoryRegion {
                base:     self.base,
                size:     self.data.len(),
                perms:    "rw-p".to_string(),
                pathname: String::new(),
                rss:      -1,
            }])
        }
    }

    #[test]
    fn scan_finds_matches_across_chunk_boundaries() {
        let pat = ap_ipc::AP_IPC_MAGIC;
        let mut mem = MockMem::new(0x1000, 100);
        for off in [12usize, 50, 92] {
            mem.data[off..off + 8].copy_from_slice(&pat);
        }
        let regions = mem.enumerate_regions().unwrap();
        let mut hits = Vec::new();
        scan_regions_chunked(&mut mem, &regions, &pat, 16, &mut |_, addr, _| {
            hits.push(addr);
            false
        });
        assert_eq!(hits, vec![0x1000 + 12, 0x1000 + 50, 0x1000 + 92]);
    }

    #[test]
    fn scan_salvages_around_an_unreadable_page() {
        let pat = ap_ipc::AP_IPC_MAGIC;
        let mut mem = MockMem::new(0x10_0000, 0x4000);
        mem.data[0x100..0x108].copy_from_slice(&pat);
        mem.data[0x3000..0x3008].copy_from_slice(&pat);
        mem.bad = Some(0x1000..0x2000);
        let regions = mem.enumerate_regions().unwrap();
        let mut hits = Vec::new();
        // One chunk spans the bad page; both matches must still be found.
        scan_regions_chunked(&mut mem, &regions, &pat, 0x4000, &mut |_, addr, _| {
            hits.push(addr);
            false
        });
        assert_eq!(hits, vec![0x10_0000 + 0x100, 0x10_0000 + 0x3000]);
    }

    #[test]
    fn scan_stops_when_callback_says_so() {
        let pat = ap_ipc::AP_IPC_MAGIC;
        let mut mem = MockMem::new(0, 200);
        for off in [10usize, 60, 120] {
            mem.data[off..off + 8].copy_from_slice(&pat);
        }
        let regions = mem.enumerate_regions().unwrap();
        let mut hits = 0;
        scan_regions_chunked(&mut mem, &regions, &pat, 32, &mut |_, _, _| {
            hits += 1;
            true
        });
        assert_eq!(hits, 1);
    }

    #[test]
    fn root_search_picks_the_live_copy_over_a_dead_one() {
        let base = 0x10000;
        let mut mem = MockMem::new(base, 0x20000);
        // Dead (pristine) copy first so it is probed first, live one after.
        mem.put_root(0x1000, 7);
        mem.put_root(0x8000, 0xFFFF);
        mem.live_roots.push(0x8000);

        let mut search = RootSearch::new();
        let found = find_ap_ipc_root(&mut mem, &mut search).unwrap();
        assert_eq!(found, base + 0x8000);
        assert_eq!(search.scan_count(), 1);
        assert_eq!(search.candidates().len(), 2);

        // The dead copy must have its original value restored.
        let f = 0x1000 + ap_ipc::offsets::CURRENT_SCENE_INDEX;
        assert_eq!(&mem.data[f..f + 2], &7u16.to_le_bytes());

        // A second call answers from the cache without rescanning.
        let again = find_ap_ipc_root(&mut mem, &mut search).unwrap();
        assert_eq!(again, found);
        assert_eq!(search.scan_count(), 1);
    }

    #[test]
    fn root_search_never_returns_a_dead_copy() {
        let mut mem = MockMem::new(0x10000, 0x20000);
        mem.put_root(0x1000, 7);

        let mut search = RootSearch::new();
        let err = find_ap_ipc_root(&mut mem, &mut search).unwrap_err();
        assert!(matches!(err, MemError::RootNotFound(_)));
        assert_eq!(search.candidates().len(), 1);

        // Immediate retry: no rescan, no second probe stall, same message.
        let again = find_ap_ipc_root(&mut mem, &mut search).unwrap_err();
        assert_eq!(err.to_string(), again.to_string());
        assert_eq!(search.scan_count(), 1);
    }

    #[test]
    fn root_search_reports_nothing_found() {
        let mut mem = MockMem::new(0x10000, 0x20000);
        let mut search = RootSearch::new();
        let err = find_ap_ipc_root(&mut mem, &mut search).unwrap_err();
        assert!(matches!(err, MemError::RootNotFound(_)));
        assert!(search.candidates().is_empty());
    }

    #[test]
    fn find_subslice_basic() {
        assert_eq!(find_subslice(b"hello world", b"world"), Some(6));
        assert_eq!(find_subslice(b"hello world", b"xyz"), None);
        assert_eq!(find_subslice(b"aaaa", b"aa"), Some(0));
        assert_eq!(find_subslice(b"", b"a"), None);
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn can_attach_to_self_and_read_own_memory() {
        // Sanity check the whole Linux plumbing (ptrace-attach-detach,
        // /proc/<pid>/mem open, pread) against our OWN process, which is
        // always available in CI/sandboxes without needing a real target.
        let pid = std::process::id() as i32;
        let mut pm = linux::LinuxProcessMemory::attach(pid).expect("attach to self");
        let regions = pm.enumerate_regions().expect("enumerate regions");
        assert!(!regions.is_empty(), "expected at least one mapped region");

        // Find some readable region and read a few bytes from it.
        let region = regions.iter().find(|r| r.is_readable() && r.size >= 16).unwrap();
        let data = pm.read_bytes(region.base, 16).expect("read_bytes");
        assert_eq!(data.len(), 16);
    }
}
