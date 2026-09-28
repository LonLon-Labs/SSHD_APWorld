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
        VirtualQueryEx, MEMORY_BASIC_INFORMATION, MEM_COMMIT, MEM_IMAGE, PAGE_GUARD,
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

#[cfg(target_os = "linux")]
pub use linux::{find_process_by_names, find_processes_by_names, LinuxProcessMemory};

#[cfg(target_os = "windows")]
pub use windows::{find_process_by_names, find_processes_by_names, WindowsProcessMemory};

#[cfg(test)]
mod tests {
    use super::*;

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
