//! Terminal-output capture: mirrors everything this process prints to
//! stdout/stderr into a timestamped log file, like `SSHDClient.py`'s
//! `_enable_terminal_log_capture` / `TeeStream` did.
//!
//! The Python client wrote `sshd_client_YYYYMMDD_HHMMSS.log` into
//! `C:\ProgramData\Archipelago\logs\sshd` (on Windows). This does the same
//! for the Rust client, without touching any of the many `println!` /
//! `eprintln!` call sites (`worker.rs`'s `vlog!`/`log!`, `gui.rs`'s
//! `push_log`, every poller module, panics, ...): `init` swaps the process's
//! stdout and stderr for the write end of a pipe, and a background thread
//! copies whatever arrives on the pipe to
//! - the ORIGINAL console/terminal (so the console window behaves exactly as
//!   before, colors included), and
//! - the log file, with ANSI color escapes stripped (the Python log was plain
//!   text too).
//!
//! stdout and stderr share one pipe, so the interleaving in the file matches
//! what happened. Because of that, the echo to the terminal goes to the
//! original stdout for both streams (stderr text no longer lands on a
//! separately-redirected stderr; irrelevant for the normal console window).
//!
//! Best-effort throughout: if the log file or the redirect can't be set up,
//! the client keeps running with ordinary console output and says so.

use std::fs::{File, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

static LOG_PATH: OnceLock<PathBuf> = OnceLock::new();

/// Starts capturing terminal output to `<logs dir>/<prefix>_<timestamp>.log`.
/// Call once, early in `main` (after `colors::enable_ansi`). Returns the log
/// file's path, or `None` if capture couldn't be started. Safe to call more
/// than once; later calls just return the existing path.
pub fn init(prefix: &str) -> Option<PathBuf> {
    if let Some(path) = LOG_PATH.get() {
        return Some(path.clone());
    }

    let Some((path, file)) = open_log_file(prefix) else {
        eprintln!("[SSHD Client] Unable to create a writable logs directory; terminal output will not be logged.");
        return None;
    };

    if let Err(e) = sys::install_tee(file) {
        eprintln!("[SSHD Client] Failed to start terminal log capture ({e}); output will not be logged.");
        return None;
    }

    let _ = LOG_PATH.set(path.clone());
    println!("[SSHD Client] Terminal output is being logged to: {}", path.display());
    Some(path)
}

/// Path of the active log file, if capture is running.
#[allow(dead_code)]
pub fn log_path() -> Option<&'static Path> {
    LOG_PATH.get().map(PathBuf::as_path)
}

/// Candidate log directories, best first. Mirrors the Python client: the
/// Archipelago data/install folder's `logs/sshd`, then a `logs` folder beside
/// the executable (dev runs), then the temp directory as a last resort.
fn candidate_dirs() -> Vec<PathBuf> {
    let mut dirs: Vec<PathBuf> = Vec::new();

    #[cfg(windows)]
    if let Some(program_data) = std::env::var_os("PROGRAMDATA") {
        dirs.push(PathBuf::from(program_data).join("Archipelago").join("logs").join("sshd"));
    }

    for key in ["ARCHIPELAGO_DIR", "AP_DIR", "ARCHIPELAGO_HOME", "MULTIWORLDGG_ARCHIPELAGO_DIR"] {
        if let Some(value) = std::env::var_os(key) {
            let base = PathBuf::from(value);
            if base.exists() {
                dirs.push(base.join("logs").join("sshd"));
            }
        }
    }

    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            dirs.push(parent.join("logs").join("sshd"));
        }
    }

    dirs.push(std::env::temp_dir().join("archipelago").join("sshd").join("logs"));
    dirs
}

fn open_log_file(prefix: &str) -> Option<(PathBuf, File)> {
    let stamp = chrono::Local::now().format("%Y%m%d_%H%M%S");
    let file_name = format!("{prefix}_{stamp}.log");

    for dir in candidate_dirs() {
        if std::fs::create_dir_all(&dir).is_err() {
            continue;
        }
        let path = dir.join(&file_name);
        if let Ok(file) = OpenOptions::new().create(true).append(true).open(&path) {
            return Some((path, file));
        }
    }
    None
}

/// Removes ANSI escape sequences (`ESC [ ... <final byte>` and two-byte
/// `ESC x`) from a byte stream. Keeps its state between chunks, since a
/// sequence can straddle two reads from the pipe.
#[derive(Default)]
struct AnsiStripper {
    state: StripState,
}

#[derive(Default, Clone, Copy, PartialEq, Eq)]
enum StripState {
    #[default]
    Normal,
    Esc,
    Csi,
}

impl AnsiStripper {
    fn feed(&mut self, input: &[u8], out: &mut Vec<u8>) {
        for &b in input {
            match self.state {
                StripState::Normal => {
                    if b == 0x1B {
                        self.state = StripState::Esc;
                    } else {
                        out.push(b);
                    }
                },
                StripState::Esc => {
                    self.state = if b == b'[' { StripState::Csi } else { StripState::Normal };
                },
                StripState::Csi => {
                    // CSI sequences end at a byte in 0x40..=0x7E.
                    if (0x40..=0x7E).contains(&b) {
                        self.state = StripState::Normal;
                    }
                },
            }
        }
    }
}

/// Copies everything from `reader` to the log file (ANSI-stripped, flushed
/// per chunk so a crash loses nothing) and to `echo`. Returns when the pipe
/// closes or errors.
fn tee_loop(mut reader: impl Read, mut file: File, mut echo: impl FnMut(&[u8])) {
    let _ = writeln!(
        file,
        "=== SSHD Archipelago client log started {} ===",
        chrono::Local::now().format("%Y-%m-%d %H:%M:%S")
    );

    let mut stripper = AnsiStripper::default();
    let mut buf = [0u8; 8192];
    let mut clean: Vec<u8> = Vec::with_capacity(8192);
    loop {
        let n = match reader.read(&mut buf) {
            Ok(0) => break,
            Ok(n) => n,
            Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
            Err(_) => break,
        };
        let chunk = &buf[..n];

        echo(chunk);

        clean.clear();
        stripper.feed(chunk, &mut clean);
        let _ = file.write_all(&clean);
        let _ = file.flush();
    }
}

#[cfg(windows)]
mod sys {
    use super::tee_loop;
    use std::fs::File;
    use std::io::{self, Write};
    use std::mem::ManuallyDrop;
    use std::os::windows::io::{FromRawHandle, RawHandle};
    use windows_sys::Win32::Foundation::{HANDLE, INVALID_HANDLE_VALUE};
    use windows_sys::Win32::System::Console::{
        GetConsoleMode, GetStdHandle, SetStdHandle, WriteConsoleW, STD_ERROR_HANDLE, STD_OUTPUT_HANDLE,
    };
    use windows_sys::Win32::System::Pipes::CreatePipe;

    fn is_valid(handle: HANDLE) -> bool {
        handle != 0 && handle != INVALID_HANDLE_VALUE
    }

    /// Writes captured bytes back to whatever stdout was before we replaced
    /// it: a real console (via `WriteConsoleW`, so UTF-8 text and ANSI
    /// colors render correctly regardless of the console code page) or a
    /// redirected handle (raw bytes).
    struct Echo {
        handle:     HANDLE,
        is_console: bool,
        /// Bytes of a UTF-8 character split across two pipe reads.
        pending:    Vec<u8>,
    }

    impl Echo {
        fn new(handle: HANDLE) -> Self {
            let is_console = is_valid(handle) && {
                let mut mode = 0u32;
                // SAFETY: `handle` is a valid handle; `mode` is a valid out pointer.
                unsafe { GetConsoleMode(handle, &mut mode) != 0 }
            };
            Echo { handle, is_console, pending: Vec::new() }
        }

        fn write(&mut self, bytes: &[u8]) {
            if !is_valid(self.handle) {
                return;
            }

            if !self.is_console {
                // SAFETY: borrowed handle, never closed (ManuallyDrop).
                let mut file = ManuallyDrop::new(unsafe { File::from_raw_handle(self.handle as RawHandle) });
                let _ = file.write_all(bytes);
                return;
            }

            self.pending.extend_from_slice(bytes);
            let cut = match std::str::from_utf8(&self.pending) {
                Ok(_) => self.pending.len(),
                // Incomplete character at the end: hold it for the next read.
                Err(e) if e.error_len().is_none() => e.valid_up_to(),
                // Genuinely invalid bytes: emit lossily rather than stall.
                Err(_) => self.pending.len(),
            };
            let text = String::from_utf8_lossy(&self.pending[..cut]).into_owned();
            self.pending.drain(..cut);

            let wide: Vec<u16> = text.encode_utf16().collect();
            let mut offset = 0;
            while offset < wide.len() {
                let count = (wide.len() - offset).min(16 * 1024) as u32;
                let mut written = 0u32;
                // SAFETY: pointer/length describe a live slice of `wide`.
                let ok = unsafe {
                    WriteConsoleW(self.handle, wide[offset..].as_ptr().cast(), count, &mut written, std::ptr::null())
                };
                if ok == 0 || written == 0 {
                    break;
                }
                offset += written as usize;
            }
        }
    }

    pub fn install_tee(log_file: File) -> io::Result<()> {
        // SAFETY: plain Win32 calls with valid out pointers; the handles
        // created here are intentionally kept open for the process lifetime
        // (they become the process's stdout/stderr).
        unsafe {
            let orig_out = GetStdHandle(STD_OUTPUT_HANDLE);
            let orig_err = GetStdHandle(STD_ERROR_HANDLE);

            let mut read: HANDLE = 0;
            let mut write: HANDLE = 0;
            if CreatePipe(&mut read, &mut write, std::ptr::null(), 64 * 1024) == 0 {
                return Err(io::Error::last_os_error());
            }

            let reader = File::from_raw_handle(read as RawHandle);
            // Echo to the original stdout (or stderr if there was no stdout).
            let echo_handle = if is_valid(orig_out) { orig_out } else { orig_err };
            let mut echo = Echo::new(echo_handle);

            std::thread::Builder::new().name("filelog-tee".into()).spawn(move || {
                tee_loop(reader, log_file, |chunk| echo.write(chunk));
                // Pipe ended unexpectedly: hand the original handles back so
                // later prints can't block on a pipe nobody is draining.
                SetStdHandle(STD_OUTPUT_HANDLE, orig_out);
                SetStdHandle(STD_ERROR_HANDLE, orig_err);
            })?;

            if SetStdHandle(STD_OUTPUT_HANDLE, write) == 0 || SetStdHandle(STD_ERROR_HANDLE, write) == 0 {
                let err = io::Error::last_os_error();
                SetStdHandle(STD_OUTPUT_HANDLE, orig_out);
                SetStdHandle(STD_ERROR_HANDLE, orig_err);
                return Err(err);
            }
        }
        Ok(())
    }
}

#[cfg(unix)]
mod sys {
    use super::tee_loop;
    use std::fs::File;
    use std::io::{self, Write};
    use std::os::unix::io::FromRawFd;

    pub fn install_tee(log_file: File) -> io::Result<()> {
        // SAFETY: plain libc fd manipulation; every fd created here is
        // either handed to a `File` or deliberately kept as stdout/stderr.
        unsafe {
            let mut fds = [0i32; 2];
            if libc::pipe(fds.as_mut_ptr()) != 0 {
                return Err(io::Error::last_os_error());
            }
            let (read_fd, write_fd) = (fds[0], fds[1]);

            let orig_out = libc::dup(1);
            let orig_err = libc::dup(2);
            if orig_out < 0 || orig_err < 0 {
                let err = io::Error::last_os_error();
                libc::close(read_fd);
                libc::close(write_fd);
                return Err(err);
            }

            let reader = File::from_raw_fd(read_fd);
            let mut echo = File::from_raw_fd(orig_out);

            std::thread::Builder::new().name("filelog-tee".into()).spawn(move || {
                tee_loop(reader, log_file, |chunk| {
                    let _ = echo.write_all(chunk);
                });
                // Pipe ended unexpectedly: restore the original stdout/stderr.
                libc::dup2(orig_out, 1);
                libc::dup2(orig_err, 2);
            })?;

            if libc::dup2(write_fd, 1) < 0 || libc::dup2(write_fd, 2) < 0 {
                let err = io::Error::last_os_error();
                libc::dup2(orig_out, 1);
                libc::dup2(orig_err, 2);
                libc::close(write_fd);
                return Err(err);
            }
            libc::close(write_fd);
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn strip(chunks: &[&[u8]]) -> String {
        let mut s = AnsiStripper::default();
        let mut out = Vec::new();
        for c in chunks {
            s.feed(c, &mut out);
        }
        String::from_utf8(out).unwrap()
    }

    #[test]
    fn strips_color_codes() {
        assert_eq!(strip(&[b"\x1b[31mred\x1b[0m plain"]), "red plain");
    }

    #[test]
    fn strips_sequences_split_across_chunks() {
        assert_eq!(strip(&[b"a\x1b[3", b"8;2;1;2;3mb"]), "ab");
    }

    #[test]
    fn keeps_utf8_and_newlines() {
        assert_eq!(strip(&["héllo → ok\n".as_bytes()]), "héllo → ok\n");
    }
}
