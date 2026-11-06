//! ACTORID resolution for `/spawn_actor` and `/spawn_demise`, ported from
//! `SSHDClient.py`'s `_load_actorid_map` / `resolve_actor_id`.
//!
//! Just like the Python client, this does NOT hardcode any ACTORID
//! values. Instead it looks for `rust-additions/src/actor.rs` (the same
//! file `_load_actorid_map` reads) relative to a few plausible locations
//! and parses `pub enum ACTORID { NAME = 0x1234, ... }` out of it by hand
//! (no `regex` dependency pulled in just for this). If that file can't be
//! found -- e.g. the `sshd-rando-backend` submodule/checkout this repo
//! was built from doesn't have it checked out, which is *also* true of
//! the Python client's copy at the time this was ported -- name lookups
//! simply come back empty and only numeric ACTORIDs (decimal or
//! `0x`-prefixed hex) can be used. This is a straight port of that
//! existing limitation, not a new one introduced here.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

/// Relative path (from a repo root candidate) to the file that declares
/// `pub enum ACTORID`. Mirrors the path `_load_actorid_map` reads in
/// `SSHDClient.py`.
const ACTOR_RS_RELATIVE: &str = "sshd-rando-backend/asm/additions/rust-additions/src/actor.rs";

/// Candidate roots to look for `ACTOR_RS_RELATIVE` under, tried in order.
/// `CARGO_MANIFEST_DIR` (this crate's own source directory) covers `cargo
/// run`/`cargo test`; the executable's own directory (and a couple of
/// ancestors, to cover `target/debug`/`target/release`) covers a built
/// binary; the current working directory covers being launched from the
/// repo root (e.g. by the Archipelago Launcher).
fn candidate_roots() -> Vec<PathBuf> {
    let mut roots = Vec::new();

    // sshd-ap-client/ap-client -> sshd-ap-client -> SSHD_APWorld (repo root)
    roots.push(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..").join(".."));

    if let Ok(exe) = std::env::current_exe() {
        let mut dir = exe.parent().map(Path::to_path_buf);
        for _ in 0..5 {
            if let Some(d) = dir.clone() {
                roots.push(d.clone());
                dir = d.parent().map(Path::to_path_buf);
            }
        }
    }

    if let Ok(cwd) = std::env::current_dir() {
        roots.push(cwd);
    }

    roots
}

/// Finds `actor.rs` under any candidate root, if it exists anywhere.
fn find_actor_rs() -> Option<PathBuf> {
    for root in candidate_roots() {
        let candidate = root.join(ACTOR_RS_RELATIVE);
        if candidate.is_file() {
            return Some(candidate);
        }
    }
    None
}

/// Hand-rolled parse of `pub enum ACTORID { NAME = 0x1234, OTHER = 56, ... }`
/// out of `text`, mirroring `_load_actorid_map`'s regex
/// (`^\s*([A-Z0-9_]+)\s*=\s*(0x[0-9A-Fa-f]+|\d+)\s*,\s*$`) closely enough
/// for this file's actual formatting without pulling in the `regex` crate.
fn parse_actorid_enum(text: &str) -> HashMap<String, u16> {
    let mut map = HashMap::new();

    let Some(enum_start) = text.find("enum ACTORID") else { return map };
    let Some(body_start) = text[enum_start..].find('{') else { return map };
    let body_start = enum_start + body_start + 1;
    let Some(body_end_rel) = text[body_start..].find('}') else { return map };
    let body = &text[body_start..body_start + body_end_rel];

    for raw_line in body.lines() {
        let line = raw_line.trim().trim_end_matches(',').trim();
        if line.is_empty() || line.starts_with("//") {
            continue;
        }
        let Some((name, value)) = line.split_once('=') else { continue };
        let name = name.trim();
        let value = value.trim();
        if name.is_empty() || !name.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') {
            continue;
        }
        let parsed = if let Some(hex) = value.strip_prefix("0x").or_else(|| value.strip_prefix("0X")) {
            u16::from_str_radix(hex, 16).ok()
        } else {
            value.parse::<u16>().ok()
        };
        if let Some(v) = parsed {
            map.insert(name.to_uppercase(), v);
        }
    }

    map
}

/// Loads the ACTORID name -> value map, or an empty map if `actor.rs`
/// can't be found. Cheap enough (a handful of file-existence checks plus
/// one file read) to call once per `/spawn_actor` invocation rather than
/// caching -- this also means editing/updating `actor.rs` takes effect
/// immediately without restarting the client, matching the Python
/// client's behavior of re-reading nothing (it only loads this once at
/// startup, but for us that distinction doesn't matter given how rarely
/// this command is used).
pub fn load_actorid_map() -> HashMap<String, u16> {
    let Some(path) = find_actor_rs() else { return HashMap::new() };
    match std::fs::read_to_string(&path) {
        Ok(text) => parse_actorid_enum(&text),
        Err(_) => HashMap::new(),
    }
}

/// Resolve an ACTORID from an enum name (e.g. "B_LASTBOSS") or an integer
/// literal (decimal or `0x`-prefixed hex), mirroring
/// `SSHDContext.resolve_actor_id` in `SSHDClient.py`. Name lookups only
/// succeed if `actor.rs` could be found (see module docs) -- `actor_map`
/// is otherwise empty and only numeric IDs resolve.
pub fn resolve_actor_id(actor_map: &HashMap<String, u16>, token: &str) -> Option<u16> {
    let token = token.trim();
    if token.is_empty() {
        return None;
    }

    if let Some(hex) = token.strip_prefix("0x").or_else(|| token.strip_prefix("0X")) {
        if let Ok(v) = u32::from_str_radix(hex, 16) {
            return (v <= 0xFFFF).then_some(v as u16);
        }
    } else if let Ok(v) = token.parse::<u32>() {
        return (v <= 0xFFFF).then_some(v as u16);
    }

    actor_map.get(&token.to_uppercase()).copied()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_simple_enum_body() {
        let text = r#"
            #[repr(u16)]
            pub enum ACTORID {
                B_LASTBOSS = 0x01D0,
                SOME_OTHER = 42,
            }
        "#;
        let map = parse_actorid_enum(text);
        assert_eq!(map.get("B_LASTBOSS"), Some(&0x01D0));
        assert_eq!(map.get("SOME_OTHER"), Some(&42));
    }

    #[test]
    fn resolve_numeric_literals_without_map() {
        let map = HashMap::new();
        assert_eq!(resolve_actor_id(&map, "0x1D0"), Some(0x1D0));
        assert_eq!(resolve_actor_id(&map, "464"), Some(464));
        assert_eq!(resolve_actor_id(&map, "B_LASTBOSS"), None);
    }

    #[test]
    fn resolve_name_from_map() {
        let mut map = HashMap::new();
        map.insert("B_LASTBOSS".to_string(), 0x01D0);
        assert_eq!(resolve_actor_id(&map, "b_lastboss"), Some(0x01D0));
    }
}
