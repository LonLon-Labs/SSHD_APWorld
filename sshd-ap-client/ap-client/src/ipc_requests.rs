//! Shared request/response round trips over the `AP_IPC_ROOT` mailboxes
//! for `/flag`, `/warp`, and `/spawn_actor` (`/spawn_demise`), ported from
//! `SSHDClient.py`'s `request_flag_operation` / `request_warp_operation` /
//! `request_spawn_actor`.
//!
//! `flag_request` here supersedes (and is used to implement)
//! `crate::flag_request_get` in `main.rs`, which only ever issued
//! `FLAG_OP_GET` requests for the location pollers (`beedle_shop.rs`).
//! That function is kept as a thin wrapper for those existing callers.

use std::thread;
use std::time::Duration;

use ap_ipc::offsets;
use process_memory::{MemError, ProcessMemory};

/// How long to poll for `rust-additions` to service a request before
/// giving up, matching the Python client's 1-second `timeout` default for
/// flag/warp requests.
const POLL_ATTEMPTS: u32 = 50;
const POLL_INTERVAL: Duration = Duration::from_millis(20);

/// Performs one `flag_request` round trip (write request, wait for
/// `rust-additions` to service it on its next frame, read the response)
/// for any of `FLAG_OP_GET`/`FLAG_OP_SET`/`FLAG_OP_UNSET`, and returns
/// `response_value`. Mirrors `SSHDClient.py`'s `request_flag_operation`
/// (which intentionally does NOT poke flag bits directly -- some flag IDs
/// are actually multi-bit counters, and only the game's own FlagMgr code
/// knows which is which).
pub fn flag_request(
    mem: &mut impl ProcessMemory,
    root_addr: usize,
    flag_type: u8,
    operation: u8,
    flag_id: u16,
    value: u16,
    scene_index: u16,
) -> Result<u32, MemError> {
    let addr = root_addr + offsets::FLAG_REQUEST;
    let req = ap_ipc::ApFlagRequest {
        magic: [0; 4],
        pending: 1,
        flag_type,
        operation,
        _pad0: 0,
        flag_id,
        value,
        scene_index,
        response_ready: 0,
        _pad1: 0,
        response_value: 0,
    };
    mem.write_bytes(addr, &ap_ipc::bytes::write(&req))?;

    for _ in 0..POLL_ATTEMPTS {
        let raw = mem.read_bytes(addr, std::mem::size_of::<ap_ipc::ApFlagRequest>())?;
        let resp: ap_ipc::ApFlagRequest = ap_ipc::bytes::read(&raw);
        if resp.response_ready != 0 {
            return Ok(resp.response_value);
        }
        thread::sleep(POLL_INTERVAL);
    }
    Err(MemError::Unsupported("timed out waiting for rust-additions to service the flag_request".into()))
}

/// Ask the Rust side to warp: either a Fi-style warp-to-start
/// (`WARP_MODE_START`), or a direct warp to an explicit stage/layer
/// (`WARP_MODE_STAGE`). Returns the `response_code` (0 = ok, 1 = failed).
/// Mirrors `SSHDClient.py`'s `request_warp_operation`.
pub fn warp_request(
    mem: &mut impl ProcessMemory,
    root_addr: usize,
    mode: u8,
    stage_code: &str,
    layer: u8,
) -> Result<u8, MemError> {
    warp_request_ex(mem, root_addr, mode, stage_code, layer, 0, 0, None, None)
}

/// Like `warp_request`, but also sets the destination `room` and `entrance`
/// (0 = default), and optionally an explicit `night` / `trial` value
/// (`None` = unspecified: day, and the game's automatic trial detection).
pub fn warp_request_ex(
    mem: &mut impl ProcessMemory,
    root_addr: usize,
    mode: u8,
    stage_code: &str,
    layer: u8,
    room: u8,
    entrance: u8,
    night: Option<bool>,
    trial: Option<bool>,
) -> Result<u8, MemError> {
    let addr = root_addr + offsets::WARP_REQUEST;

    let mut stage_name = [0u8; 8];
    let stage_bytes = stage_code.as_bytes();
    let n = stage_bytes.len().min(8);
    stage_name[..n].copy_from_slice(&stage_bytes[..n]);

    let mut flags = 0u8;
    if let Some(night) = night {
        flags |= ap_ipc::WARP_FLAG_NIGHT_SET;
        if night {
            flags |= ap_ipc::WARP_FLAG_NIGHT;
        }
    }
    if let Some(trial) = trial {
        flags |= ap_ipc::WARP_FLAG_TRIAL_SET;
        if trial {
            flags |= ap_ipc::WARP_FLAG_TRIAL;
        }
    }

    let req = ap_ipc::ApWarpRequest {
        magic: [0; 4],
        pending: 1,
        mode,
        layer,
        room,
        stage_name,
        response_ready: 0,
        response_code: 0,
        entrance,
        flags,
    };
    mem.write_bytes(addr, &ap_ipc::bytes::write(&req))?;

    for _ in 0..POLL_ATTEMPTS {
        let raw = mem.read_bytes(addr, std::mem::size_of::<ap_ipc::ApWarpRequest>())?;
        let resp: ap_ipc::ApWarpRequest = ap_ipc::bytes::read(&raw);
        if resp.response_ready != 0 {
            return Ok(resp.response_code);
        }
        thread::sleep(POLL_INTERVAL);
    }
    Err(MemError::Unsupported("timed out waiting for rust-additions to service the warp_request".into()))
}

/// Sets a one-shot request to spawn `actor_id` in the current stage. This
/// is fire-and-forget -- `ApSpawnRequest` has no response fields, mirroring
/// `SSHDClient.py`'s `request_spawn_actor` (which also never waits for a
/// reply).
pub fn spawn_request(
    mem: &mut impl ProcessMemory,
    root_addr: usize,
    actor_id: u16,
    actor_param1: u32,
    actor_param2: u32,
    oarc_name: &str,
) -> Result<(), MemError> {
    let addr = root_addr + offsets::SPAWN_REQUEST;

    let mut oarc = [0u8; 32];
    let oarc_bytes = oarc_name.as_bytes();
    let n = oarc_bytes.len().min(31); // leave room for the null terminator
    oarc[..n].copy_from_slice(&oarc_bytes[..n]);

    let req = ap_ipc::ApSpawnRequest {
        magic: [0; 4],
        request: 1,
        _pad0: [0; 1],
        actorid: actor_id,
        actor_param1,
        actor_param2,
        oarc_name: oarc,
    };
    mem.write_bytes(addr, &ap_ipc::bytes::write(&req))
}
