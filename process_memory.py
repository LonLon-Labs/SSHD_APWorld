"""
Cross-platform process memory access.

On Windows, wraps pymem (ReadProcessMemory / WriteProcessMemory).
On Linux,  uses /proc/<pid>/mem + /proc/<pid>/maps (no extra dependencies).
On macOS,  uses mach vm_read / vm_write via ctypes (experimental).

Every back-end exposes the same thin interface used by the rest of the client:

    pm = ProcessMemory()
    pm.open_process_from_id(pid)
    data = pm.read_bytes(address, size)
    pm.write_bytes(address, data, len(data))
    pm.read_uchar(address) -> int
    pm.write_uchar(address, value)
    regions = pm.enumerate_regions()       # list of (base, size, perms_str)
    results = pm.pattern_scan(pattern)     # list of absolute addresses

On Windows, ``pm.process_handle`` is also available for callers that need the
raw HANDLE (e.g. existing ctypes / VirtualQueryEx code).
"""

from __future__ import annotations

import ctypes
import os
import re
import struct
import sys
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

IS_WINDOWS = sys.platform == "win32"
IS_LINUX   = sys.platform == "linux"
IS_MACOS   = sys.platform == "darwin"


class ProcessMemoryError(Exception):
    """Raised when a memory operation fails."""


# ---------------------------------------------------------------------------
# Region descriptor returned by enumerate_regions()
# ---------------------------------------------------------------------------

class MemoryRegion:
    """Describes a single contiguous virtual-memory region."""
    __slots__ = ("base", "size", "perms", "pathname", "rss")

    def __init__(self, base: int, size: int, perms: str, pathname: str = "",
                 rss: int = -1):
        self.base = base
        self.size = size
        self.perms = perms       # e.g. "rw-p", "r-xp"
        self.pathname = pathname  # e.g. "/usr/lib/libc.so.6", "[heap]", ""
        self.rss = rss            # Resident set size in bytes (-1 = unknown)

    @property
    def is_readable(self) -> bool:
        return "r" in self.perms

    @property
    def is_writable(self) -> bool:
        return "w" in self.perms

    @property
    def is_anonymous(self) -> bool:
        """True when the region has no file backing (anonymous mmap)."""
        return self.pathname == ""

    @property
    def is_file_backed(self) -> bool:
        """True when the region is backed by a regular file on disk."""
        return self.pathname != "" and not self.pathname.startswith("[")

    def __repr__(self) -> str:
        tag = f" {self.pathname}" if self.pathname else ""
        return f"MemoryRegion(0x{self.base:X}, 0x{self.size:X}, {self.perms!r}{tag})"


# ===================================================================
# Windows back-end (pymem)
# ===================================================================

class _WindowsProcessMemory:
    """Thin wrapper around pymem for Windows."""

    def __init__(self):
        import pymem as _pymem
        import pymem.process as _pymem_process   # noqa: F401 – ensure available
        self._pymem_mod = _pymem
        self._pm: Optional[_pymem.Pymem] = None
        self._pid: Optional[int] = None

    # -- attach -----------------------------------------------------------

    def open_process_from_id(self, pid: int):
        self._pm = self._pymem_mod.Pymem()
        self._pm.open_process_from_id(pid)
        self._pid = pid

    # -- raw handle (for VirtualQueryEx callers) --------------------------

    @property
    def process_handle(self):
        if self._pm is None:
            raise ProcessMemoryError("Not attached to a process")
        return self._pm.process_handle

    # -- read / write -----------------------------------------------------

    def read_bytes(self, address: int, size: int) -> bytes:
        return self._pm.read_bytes(address, size)

    def read_uchar(self, address: int) -> int:
        return self._pm.read_uchar(address)

    def write_bytes(self, address: int, data: bytes, length: int):
        self._pm.write_bytes(address, data, length)

    def write_uchar(self, address: int, value: int):
        self._pm.write_uchar(address, value)

    # -- region enumeration -----------------------------------------------

    def enumerate_regions(self) -> List[MemoryRegion]:
        """Use VirtualQueryEx to enumerate committed, readable regions."""
        MEM_COMMIT = 0x1000
        READABLE = {0x02, 0x04, 0x08, 0x20, 0x40, 0x80}
        PAGE_GUARD = 0x100

        class MEMORY_BASIC_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BaseAddress",       ctypes.c_uint64),
                ("AllocationBase",    ctypes.c_uint64),
                ("AllocationProtect", ctypes.c_uint32),
                ("__alignment1",      ctypes.c_uint32),
                ("RegionSize",        ctypes.c_uint64),
                ("State",             ctypes.c_uint32),
                ("Protect",           ctypes.c_uint32),
                ("Type",              ctypes.c_uint32),
                ("__alignment2",      ctypes.c_uint32),
            ]

        kernel32 = ctypes.windll.kernel32
        handle = self.process_handle
        mbi = MEMORY_BASIC_INFORMATION()
        address = 0x10000
        max_address = 0x7FFFFFFFFFFF
        regions: List[MemoryRegion] = []

        while address < max_address:
            result = kernel32.VirtualQueryEx(
                handle,
                ctypes.c_uint64(address),
                ctypes.byref(mbi),
                ctypes.sizeof(mbi),
            )
            if result == 0:
                address += 0x1000
                continue

            rbase = mbi.BaseAddress
            rsize = mbi.RegionSize
            if rsize == 0:
                address += 0x1000
                continue

            base_prot = mbi.Protect & 0xFF
            is_committed = mbi.State == MEM_COMMIT
            is_readable = (base_prot in READABLE) and not (mbi.Protect & PAGE_GUARD)

            if is_committed and is_readable:
                perms = "r"
                if base_prot in {0x04, 0x08, 0x40, 0x80}:
                    perms += "w"
                else:
                    perms += "-"
                if base_prot in {0x10, 0x20, 0x40, 0x80}:
                    perms += "x"
                else:
                    perms += "-"
                perms += "p"
                regions.append(MemoryRegion(rbase, rsize, perms))

            address = rbase + rsize

        return regions

    # -- pattern scan -----------------------------------------------------

    def pattern_scan(self, pattern: bytes) -> List[int]:
        """Scan the entire process for *pattern*, return list of addresses."""
        try:
            from pymem import pattern as _pat
            found = _pat.pattern_scan_all(self.process_handle, pattern)
            if found is None:
                return []
            return found if isinstance(found, list) else [found]
        except Exception:
            # Fall back to manual scan via enumerate_regions
            return self._manual_pattern_scan(pattern)

    # -- manual fallback --------------------------------------------------

    def _manual_pattern_scan(self, pattern: bytes) -> List[int]:
        results: List[int] = []
        chunk_size = 4 * 1024 * 1024
        for region in self.enumerate_regions():
            if not region.is_readable:
                continue
            pos = region.base
            end = region.base + region.size
            while pos < end:
                to_read = min(chunk_size, end - pos)
                try:
                    data = self.read_bytes(pos, to_read)
                except Exception:
                    pos += to_read
                    continue
                offset = 0
                while True:
                    idx = data.find(pattern, offset)
                    if idx == -1:
                        break
                    results.append(pos + idx)
                    offset = idx + 1
                # overlap for patterns crossing chunk boundary
                if to_read == chunk_size:
                    pos += to_read - len(pattern) + 1
                else:
                    pos += to_read
        return results


# ===================================================================
# Linux back-end (/proc/<pid>/mem)
# ===================================================================

class _LinuxProcessMemory:
    """Process memory access via /proc/<pid>/mem on Linux.

    Performance notes
    -----------------
    Ryujinx (.NET JIT) typically maps thousands of regions.  The vast majority
    are tiny, file-backed (shared libraries, fonts, locale data …) or special
    kernel mappings ([vdso], [stack], …).  The game's emulated RAM lives in a
    handful of **large anonymous** (rw-p, no pathname) regions.

    ``enumerate_regions()`` already captures the pathname so callers (and
    ``enumerate_scannable_regions()``) can filter cheaply before doing any I/O.

    ``os.pread()`` is used instead of lseek+read to halve the syscall count.
    """

    # Regions smaller than this are skipped by enumerate_scannable_regions().
    # Ryujinx's emulated guest RAM is always tens/hundreds of MB.
    _MIN_SCAN_REGION_SIZE = 1 * 1024 * 1024  # 1 MB

    def __init__(self):
        self._pid: Optional[int] = None
        self._mem_fd: Optional[int] = None

    # -- attach -----------------------------------------------------------

    def open_process_from_id(self, pid: int):
        self._pid = pid
        mem_path = f"/proc/{pid}/mem"
        try:
            self._attach_ptrace(pid)
            self._mem_fd = os.open(mem_path, os.O_RDWR)
        except PermissionError:
            raise ProcessMemoryError(
                f"Permission denied opening {mem_path}.  "
                "Try running 'sudo sysctl -w kernel.yama.ptrace_scope=0' "
                "or run the client with 'sudo'."
            )
        except FileNotFoundError:
            raise ProcessMemoryError(
                f"Process {pid} does not exist (no {mem_path})."
            )

    @staticmethod
    def _attach_ptrace(pid: int):
        """
        Attach to the target process via ptrace so that /proc/<pid>/mem
        becomes accessible on systems with ``ptrace_scope >= 1``.

        We immediately detach again — the kernel remembers that we once
        attached, which is enough to keep /proc/<pid>/mem readable for
        the lifetime of our process (on most kernels >= 3.x).
        """
        import ctypes
        import ctypes.util

        PTRACE_ATTACH  = 16
        PTRACE_DETACH  = 17

        libc_name = ctypes.util.find_library("c")
        if not libc_name:
            return

        libc = ctypes.CDLL(libc_name, use_errno=True)
        if libc.ptrace(PTRACE_ATTACH, pid, 0, 0) == -1:
            return

        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass

        libc.ptrace(PTRACE_DETACH, pid, 0, 0)

    # -- raw handle surrogate (not used on Linux) -------------------------

    @property
    def process_handle(self):
        """Not applicable on Linux, but exposed for API compatibility."""
        return self._pid

    # -- read / write (uses pread/pwrite — one syscall each) --------------

    def read_bytes(self, address: int, size: int) -> bytes:
        if self._mem_fd is None:
            raise ProcessMemoryError("Not attached to a process")
        try:
            data = os.pread(self._mem_fd, size, address)
            if len(data) != size:
                raise ProcessMemoryError(
                    f"Short read at 0x{address:X}: expected {size}, got {len(data)}"
                )
            return data
        except OSError as exc:
            raise ProcessMemoryError(
                f"read_bytes(0x{address:X}, {size}) failed: {exc}"
            ) from exc

    def read_uchar(self, address: int) -> int:
        return self.read_bytes(address, 1)[0]

    def write_bytes(self, address: int, data: bytes, length: int):
        if self._mem_fd is None:
            raise ProcessMemoryError("Not attached to a process")
        try:
            written = os.pwrite(self._mem_fd, data[:length], address)
            if written != length:
                raise ProcessMemoryError(
                    f"Short write at 0x{address:X}: expected {length}, wrote {written}"
                )
        except OSError as exc:
            raise ProcessMemoryError(
                f"write_bytes(0x{address:X}, {length}) failed: {exc}"
            ) from exc

    def write_uchar(self, address: int, value: int):
        self.write_bytes(address, bytes([value & 0xFF]), 1)

    # -- region enumeration via /proc/<pid>/maps and smaps ----------------

    # Matches: "start-end perms offset dev inode [pathname]"
    _MAPS_RE = re.compile(
        r"^([0-9a-fA-F]+)-([0-9a-fA-F]+)\s+(\S+)\s+\S+\s+\S+\s+\S+\s*(.*)"
    )

    def enumerate_regions(self) -> List[MemoryRegion]:
        """Parse /proc/<pid>/maps to enumerate memory regions."""
        if self._pid is None:
            raise ProcessMemoryError("Not attached to a process")
        regions: List[MemoryRegion] = []
        maps_path = f"/proc/{self._pid}/maps"
        try:
            with open(maps_path, "r") as f:
                for line in f:
                    m = self._MAPS_RE.match(line)
                    if not m:
                        continue
                    start = int(m.group(1), 16)
                    end   = int(m.group(2), 16)
                    perms = m.group(3)        # e.g. "rw-p"
                    pathname = m.group(4).strip()  # e.g. "/usr/lib/libc.so.6"
                    regions.append(MemoryRegion(start, end - start, perms, pathname))
        except FileNotFoundError:
            raise ProcessMemoryError(f"{maps_path} not found — process gone?")
        return regions

    def _get_rss_map(self) -> dict:
        """Parse /proc/<pid>/smaps and return ``{region_start: rss_bytes}``.

        On a typical Ryujinx process with ~11 000 map entries the smaps file
        is ~1-2 MB.  Parsing it takes <50 ms, vastly cheaper than reading
        hundreds of GB of uncommitted pages.

        Falls back to an empty dict if smaps is unreadable (e.g. permissions).
        """
        rss_map: dict = {}
        smaps_path = f"/proc/{self._pid}/smaps"
        current_start = None
        try:
            with open(smaps_path, "r") as f:
                for line in f:
                    # Header line for a new region
                    m = self._MAPS_RE.match(line)
                    if m:
                        current_start = int(m.group(1), 16)
                        continue
                    # Rss line (in kB)
                    if current_start is not None and line.startswith("Rss:"):
                        # "Rss:              1234 kB\n"
                        parts = line.split()
                        if len(parts) >= 2:
                            try:
                                rss_map[current_start] = int(parts[1]) * 1024
                            except ValueError:
                                pass
        except (FileNotFoundError, PermissionError):
            pass  # smaps not available — caller will scan all pages
        return rss_map

    def enumerate_regions_with_rss(self) -> List[MemoryRegion]:
        """Like ``enumerate_regions()`` but populates the ``rss`` field.

        Uses /proc/<pid>/smaps to determine how many bytes of each region
        are actually resident in physical memory.  Regions with ``rss == 0``
        are entirely uncommitted and can be skipped during scanning.
        """
        regions = self.enumerate_regions()
        rss_map = self._get_rss_map()
        for r in regions:
            r.rss = rss_map.get(r.base, 0)
        return regions

    # File extensions / path fragments that identify shared-library or
    # data-file mappings we never need to scan for game memory.
    _SKIP_EXTENSIONS = (
        '.so', '.py', '.pyc', '.pyo',
        '.dat', '.cache', '.bin',
        '.ttf', '.otf', '.ttc',
        '.gz', '.xz', '.zst', '.bz2',
        '.conf', '.locale', '.txt', '.json', '.xml', '.yaml', '.yml',
        '.png', '.jpg', '.svg', '.ico',
        '.dll', '.exe', '.pdb',
        '.mo', '.gmo',  # gettext
    )
    _SKIP_PATH_FRAGMENTS = (
        '/usr/lib', '/usr/share', '/lib/', '/lib64/',
        '/etc/', '/nix/store', '/gnu/store',
        '/proc/', '/sys/',
    )

    @staticmethod
    def _is_library_or_data(pathname: str) -> bool:
        """Return True if *pathname* is clearly a shared library or data file.

        These are things like ``/usr/lib/libc.so.6`` or ``/usr/share/locale/…``.
        We keep anonymous regions, ``[heap]``, ``[anon:…]``, ``/memfd:…``,
        ``/dev/shm/…``, and anything else that could plausibly hold game RAM.
        """
        if not pathname:
            return False                    # anonymous — keep
        if pathname.startswith('['):
            return False                    # [heap], [anon:*], [stack], [vdso] — keep
        if 'memfd:' in pathname:
            return False                    # memfd anonymous file — keep
        if pathname.startswith('/dev/'):
            return False                    # /dev/shm etc. — keep

        # Check known library/data extensions (handles .so.6 via checking each
        # dot-separated suffix: .so.6 → we check '.6' then '.so.6')
        lower = pathname.lower()
        for ext in _LinuxProcessMemory._SKIP_EXTENSIONS:
            if lower.endswith(ext):
                return True
        # Catch versioned .so files like libfoo.so.1.2.3
        if '.so.' in lower or lower.endswith('.so'):
            return True

        # Check known uninteresting path prefixes
        for frag in _LinuxProcessMemory._SKIP_PATH_FRAGMENTS:
            if frag in lower:
                return True

        return False

    def enumerate_scannable_regions(
        self, min_size: int = 0, *, include_file_backed: bool = False,
    ) -> List[MemoryRegion]:
        """Return only the regions worth scanning for game data.

        Filters applied (in order):
          1. Must be readable.
          2. Skip regions that are clearly shared-library or data-file
             mappings (e.g. ``/usr/lib/libc.so.6``).  Keeps anonymous
             regions, ``[heap]``, ``/memfd:*``, ``/dev/shm/*``, etc.
             Pass *include_file_backed=True* to disable this filter.
          3. Must have RSS > 0 (pages actually resident in physical memory).
             This is the key optimisation for Linux: .NET / Ryujinx reserves
             hundreds of GB of virtual address space via mmap but only a small
             fraction is ever faulted in.  Reading uncommitted pages returns
             zeros but still costs ~4 MB of kernel memset + copy per chunk.
             Skipping regions with 0 RSS avoids all of that.
          4. Must be >= *min_size* bytes (default: _MIN_SCAN_REGION_SIZE).
          5. Adjacent qualifying regions with identical permissions are
             **coalesced** into one, reducing iteration overhead.
          6. Results are sorted by RSS descending so the most populated
             (= most likely to contain game data) regions are scanned first.

        On a typical Ryujinx process this reduces thousands of regions /
        hundreds of GB down to a handful of regions totaling a few GB.
        """
        if min_size <= 0:
            min_size = self._MIN_SCAN_REGION_SIZE

        # Use smaps to get RSS info — takes ~50 ms, saves minutes of I/O
        raw = self.enumerate_regions_with_rss()

        # Step 1-2: readable + not a library/data file
        if include_file_backed:
            candidates = [r for r in raw if r.is_readable]
        else:
            candidates = [
                r for r in raw
                if r.is_readable and not self._is_library_or_data(r.pathname)
            ]

        # Step 3: drop regions with no resident pages (RSS == 0)
        # If smaps wasn't available (rss == -1 for all), keep everything.
        has_rss_info = any(r.rss > 0 for r in candidates)
        if has_rss_info:
            candidates = [r for r in candidates if r.rss > 0]

        # Step 4: coalesce adjacent regions (they often fragment)
        coalesced: List[MemoryRegion] = []
        for r in candidates:
            if coalesced and coalesced[-1].perms == r.perms \
                    and coalesced[-1].base + coalesced[-1].size == r.base:
                prev = coalesced[-1]
                coalesced[-1] = MemoryRegion(
                    prev.base,
                    prev.size + r.size,
                    prev.perms,
                    rss=max(prev.rss, 0) + max(r.rss, 0),
                )
            else:
                coalesced.append(r)

        # Step 5: size filter
        result = [r for r in coalesced if r.size >= min_size]

        # Step 6: sort by RSS descending — scan most populated regions first
        result.sort(key=lambda r: r.rss if r.rss >= 0 else 0, reverse=True)

        return result

    # -- pattern scan -----------------------------------------------------

    def pattern_scan(self, pattern: bytes) -> List[int]:
        """Scan all readable regions for *pattern*."""
        return self._manual_pattern_scan(pattern)

    def _manual_pattern_scan(self, pattern: bytes) -> List[int]:
        results: List[int] = []
        chunk_size = 4 * 1024 * 1024
        for region in self.enumerate_scannable_regions():
            pos = region.base
            end = region.base + region.size
            while pos < end:
                to_read = min(chunk_size, end - pos)
                try:
                    data = self.read_bytes(pos, to_read)
                except Exception:
                    pos += to_read
                    continue
                offset = 0
                while True:
                    idx = data.find(pattern, offset)
                    if idx == -1:
                        break
                    results.append(pos + idx)
                    offset = idx + 1
                if to_read == chunk_size:
                    pos += to_read - len(pattern) + 1
                else:
                    pos += to_read
        return results

    # -- cleanup ----------------------------------------------------------

    def close(self):
        if self._mem_fd is not None:
            try:
                os.close(self._mem_fd)
            except OSError:
                pass
            self._mem_fd = None
        self._pid = None

    def __del__(self):
        self.close()


# ===================================================================
# Public factory
# ===================================================================

def ProcessMemory():
    """
    Return a platform-appropriate process memory accessor.

    Calling code should treat the return value duck-typed; all back-ends
    expose the same public methods.
    """
    if IS_WINDOWS:
        return _WindowsProcessMemory()
    elif IS_LINUX:
        return _LinuxProcessMemory()
    else:
        raise ProcessMemoryError(
            f"Unsupported platform: {sys.platform}.  "
            "Only Windows and Linux are currently supported."
        )
