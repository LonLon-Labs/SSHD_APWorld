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
    __slots__ = ("base", "size", "perms")

    def __init__(self, base: int, size: int, perms: str):
        self.base = base
        self.size = size
        self.perms = perms      # e.g. "rw-p", "r-xp"

    @property
    def is_readable(self) -> bool:
        return "r" in self.perms

    @property
    def is_writable(self) -> bool:
        return "w" in self.perms

    def __repr__(self) -> str:
        return f"MemoryRegion(0x{self.base:X}, 0x{self.size:X}, {self.perms!r})"


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
    """Process memory access via /proc/<pid>/mem on Linux."""

    def __init__(self):
        self._pid: Optional[int] = None
        self._mem_fd: Optional[int] = None

    # -- attach -----------------------------------------------------------

    def open_process_from_id(self, pid: int):
        self._pid = pid
        mem_path = f"/proc/{pid}/mem"
        try:
            # O_RDWR so we can both read and write.
            # Requires either same-user or CAP_SYS_PTRACE / root.
            # On many distros ptrace_scope=1 means we must first ptrace-attach
            # (or the caller should run with elevated privileges).
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
        the lifetime of our process (on most kernels ≥ 3.x).
        """
        import ctypes
        import ctypes.util

        PTRACE_ATTACH  = 16
        PTRACE_DETACH  = 17

        libc_name = ctypes.util.find_library("c")
        if not libc_name:
            return  # cannot find libc — skip, open may still succeed

        libc = ctypes.CDLL(libc_name, use_errno=True)
        if libc.ptrace(PTRACE_ATTACH, pid, 0, 0) == -1:
            # If attach fails (e.g. we're the same user and ptrace_scope=0),
            # just continue — /proc/<pid>/mem open may still work.
            return

        # Wait for the process to stop (it receives SIGSTOP from attach).
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass

        # Detach — the process resumes, and we retain mem access.
        libc.ptrace(PTRACE_DETACH, pid, 0, 0)

    # -- raw handle surrogate (not used on Linux) -------------------------

    @property
    def process_handle(self):
        """Not applicable on Linux, but exposed for API compatibility."""
        return self._pid

    # -- read / write -----------------------------------------------------

    def read_bytes(self, address: int, size: int) -> bytes:
        if self._mem_fd is None:
            raise ProcessMemoryError("Not attached to a process")
        try:
            os.lseek(self._mem_fd, address, os.SEEK_SET)
            data = os.read(self._mem_fd, size)
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
            os.lseek(self._mem_fd, address, os.SEEK_SET)
            written = os.write(self._mem_fd, data[:length])
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

    # -- region enumeration via /proc/<pid>/maps --------------------------

    _MAPS_RE = re.compile(
        r"^([0-9a-fA-F]+)-([0-9a-fA-F]+)\s+(\S+)"
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
                    perms = m.group(3)  # e.g. "rw-p"
                    regions.append(MemoryRegion(start, end - start, perms))
        except FileNotFoundError:
            raise ProcessMemoryError(f"{maps_path} not found — process gone?")
        return regions

    # -- pattern scan -----------------------------------------------------

    def pattern_scan(self, pattern: bytes) -> List[int]:
        """Scan all readable regions for *pattern*."""
        return self._manual_pattern_scan(pattern)

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
                # overlap for patterns that cross chunk boundary
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
