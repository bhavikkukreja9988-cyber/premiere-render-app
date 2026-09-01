# PRAP/2 — wire protocol

Protocol version: `2`. Default TCP port `49872`, discovery UDP port `49873`.

## Framing

```
[4 bytes big-endian header length][UTF-8 JSON header][raw payload bytes]
```

Header shape:

```json
{"t": "file_chunk", "p": {"path": "footage/a.mov"}, "n": 1048576}
```

`n` is the payload length in bytes and is `0` for control messages. Binary data
is never base64-encoded, so a 200 GB folder costs no encoding overhead.

Limits: header ≤ 1 MiB, payload ≤ 16 MiB, default chunk 1 MiB.

## Session

The sender opens every connection. Phases are independent connections, so a
station reboot mid-render only costs a retry.

```
sender                          station
  |  hello {protocol, sender_name} ->
  |  <- hello_ok {name, port, busy, queue_length, requires_code, nonce, free_bytes, backend}
  |  auth {token = HMAC-SHA256(pairing_code, nonce)} ->
  |  <- auth_ok
```

The pairing code itself never crosses the wire.

### Submitting

```
  |  job_offer {spec, manifest[{path, size, mtime, sha256}]} ->
  |  <- job_accept {job_id, need: {path: offset}, chunk_size}
  |  file_begin {path, offset, size} ->
  |  file_chunk [payload] ->        (repeated)
  |  file_end {path, sha256} ->
  |  <- file_ok {path}
  |  transfer_done {job_id} ->
  |  <- job_queued {job_id, queue_length}
```

`need` is the resume map: files already present with a matching hash are
omitted, partial files carry the byte offset to continue from.

### Waiting and collecting

```
  |  status_req {job_id} ->     |  <- status {spec, state, progress, message, error, ...}
  |  result_fetch {job_id, offset} ->
  |  <- result_begin {filename, size, sha256}
  |  <- result_chunk [payload]  (repeated)
  |  <- result_end {job_id, size}
  |  result_ack {job_id, delete_remote} ->
  |  <- status {…state: complete}
  |  bye ->
```

`cancel {job_id}` is answered with `cancel_ok`. `ping` is answered with `pong`.
`presets_req` returns the station's Media Encoder preset names.

## Errors

Any message may be answered with:

```json
{"t": "error", "p": {"code": "unsafe_manifest", "message": "parent traversal rejected"}}
```

Codes: `protocol_mismatch`, `auth_failed`, `bad_offer`, `unsafe_manifest`,
`unsafe_path`, `insufficient_space`, `checksum_mismatch`, `verify_failed`,
`no_job`, `no_file`, `unknown_job`, `no_result`, `unknown_message`,
`protocol_error`, `internal_error`.

The receiving client raises `RemoteError` carrying the code.

## Discovery

The station broadcasts to `255.255.255.255:49873` every 2 seconds:

```json
{"magic": "premiere-render-app", "protocol": 2, "name": "RENDER-01",
 "port": 49872, "busy": false, "queue_length": 0, "requires_code": true,
 "free_bytes": 812000000000, "backend": "Adobe Media Encoder"}
```

Senders drop stations not heard from for 8 seconds. Broadcast is a convenience
only — a typed IP address bypasses it entirely.

## Security model

- Pairing code + nonce HMAC gates every operation after `hello`.
- Manifest paths are rejected if absolute, drive-qualified, UNC, containing
  `..`, using NT reserved device names, or holding characters Windows cannot
  store. Each write is re-checked with `safe_join` against the job root.
- Free-space is checked before accepting an offer.
- This is a LAN trust model: traffic is not encrypted. Do not expose port 49872
  to the internet.
