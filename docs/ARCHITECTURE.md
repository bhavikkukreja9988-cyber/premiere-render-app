# Architecture

Layers, top to bottom. Each layer only talks to the one below it.

```
UI  (PySide6 tabs: Send a project / Render station / Log)
 |
Core Workflow  (Workflow state machine, JobStore)
 |
Network Layer  (RenderStation server, StationDiscovery, SenderClient)
 |
Transfer Engine  (SendWorker, chunked upload/return, resume + verify)
 |
Render Pipeline  (RenderManager queue, RenderBackend)
 |
Media Encoder  (ExtendScript agent, background launch)
 |
Output Monitor  (detect the finished MP4)
 |
Return Transfer  (stream the MP4 back to the Sender)
```

## Main flow

```
Premiere project folder (Sender PC)
      |
      v
scan + hash + upload only what's missing
      |
      v
Render Station: verify -> queue
      |
      v
Media Encoder renders in the background
      |
      v
Output Monitor sees the finished MP4
      |
      v
Sender pulls the MP4 back, verifies, saves
```

## Two roles, one app

The Sender and the Render Station are the same program in different modes. The
Sender opens every connection; the Station only ever responds. That is why only
the Station needs an inbound firewall rule, and why a Sender can disconnect
during a long render and reconnect later to collect the result.

## Trust and safety

- A 6-digit pairing code gates every operation (HMAC challenge/response; the
  code itself never crosses the wire).
- Every path in a transfer manifest is validated (no absolute paths, no drive
  letters, no `..`, no reserved names) before anything is written.
- Every file is checksummed (SHA-256) on arrival and on return.
- Home-LAN trust model: traffic is not encrypted; don't expose the ports to the
  internet.

See `PROTOCOL.md` for the exact message flow and `SETUP_WINDOWS.md` for setup.
