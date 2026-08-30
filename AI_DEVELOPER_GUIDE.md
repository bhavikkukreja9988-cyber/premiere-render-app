# AI Developer Guide

Read this before modifying the project. Continue from this architecture; do not
redesign it unless a requirement forces the change.

## What this app is

A home-network tool. Person A sends a Premiere project folder to a render PC;
the render PC renders it in Adobe Media Encoder and sends the MP4 back. It is
for family use — no server, no accounts, no payments, nothing running when the
app is closed.

## Invariants (do not break these)

1. **Sender + Render Station = the same application.** One executable, two tabs.
2. **The app only works while it is open.** No Windows services, no scheduled
   tasks.
3. **The Sender drives every exchange.** The station never dials back to the
   sender, so only the station needs an inbound firewall rule.
4. **The render must not disturb the render-PC operator.** Media Encoder is
   launched minimised, below-normal priority, without focus, and the agent
   starts the batch unattended. Keep it that way.
5. **Nothing from the network is trusted.** Every path is validated before a
   byte is written; every file is checksummed on arrival and on return.
6. **`src/core` has no Qt and no sockets.** It is pure, tested Python. Network,
   render and UI sit on top of it.

## Module map

The original prototype names are kept; the stubs are now real implementations.

```
src/
  main.py                  entry point (GUI / --station / --check)
  app.py                   PremiereRenderApp launcher class
  core/                    pure logic, unit-tested, no Qt / no sockets
    protocol.py            framed messages, message types, pairing HMAC
    manifest.py            folder scan, hashing, path safety, resume diff
    jobs.py                JobSpec / JobRecord / JobState / JobStore
    workflow.py            high-level Workflow state machine (UI binds to this)
    workspace.py           render-station directory layout
    config.py              persisted settings + platform paths
    project_probe.py       reads sequence names out of a .prproj
    log.py                 rotating file log + in-app ring buffer
  network/
    session.py             RenderStation server + ClientSession
                           (+ NetworkSession / Peer helpers)
    discovery.py           UDP beacon (station) and listener (sender)
  transfer/
    transfer_engine.py     SenderClient (one conversation), SendWorker
                           (whole job), TransferEngine (progress tracker)
    chunk_manager.py       chunk split + file iterator
  render/
    media_encoder.py       AME discovery, agent install, submit + monitor,
                           background launch
    pipeline.py            RenderBackend interface, AmeBackend, ManualBackend,
                           RenderManager (queue worker)
    output_monitor.py      watch an output folder for a finished MP4
    jsx/PremiereRenderAgent.jsx   ExtendScript agent that runs inside AME
  return_transfer/
    return_manager.py      pull one job's MP4 back to a local folder
  ui/                      PySide6 only; talks to the layers below via signals
tests/                     stdlib unittest, no third-party deps, no Qt needed
```

## Threading rules

- Long work never runs on the Qt thread. Workers are `threading.Thread`.
- Workers reach the UI only through Qt signals; never touch a widget from a
  worker thread.
- `JobStore` is the single source of truth on the station and is lock-guarded.

## Job lifecycle

```
created -> transferring -> queued -> rendering -> encoded -> returning -> complete
                                 \-> failed / cancelled
```

`JobStore` re-queues anything left in `rendering`/`returning` after a restart,
because Media Encoder can't resume a half-finished batch item.

## How Media Encoder is driven

AME has no supported command line, so we install `PremiereRenderAgent.jsx` into
`%APPDATA%\Adobe\Startup Scripts CC\Adobe Media Encoder\`. AME runs it at
startup; it polls a queue folder, adds each job to the batch, starts it, and
writes status files back. Python watches both the status files and the output
file, so a missed script event never strands a job. If the agent can't run, the
station falls back to `ManualBackend` (operator renders, drops the file in the
job's `output/`; the return still happens automatically).

## Adding a render backend

Subclass `RenderBackend` in `render/pipeline.py`, implement `available()` and
`render()`. `render()` must honour the `cancel()` callback, report through
`progress(fraction, message)`, return the produced file, and raise `RenderError`
on failure. Register it in `build_backend()`.

## Testing

```
python -m unittest discover -s tests -t .
```

Tests must keep passing without PySide6 and without a network. `test_end_to_end`
starts a real station on an ephemeral port with a stub backend — extend it
whenever you touch the protocol. Don't edit tests to force a pass.

## Remaining milestones (from the original build order)

1. Production UI polish and a proper first-run wizard.
2. Test on two real Windows PCs with Premiere + Media Encoder.
3. Signed Windows installer (Inno Setup) over the PyInstaller output.
4. Optional: render several sequences from one project; auto-pick the least
   busy station.
