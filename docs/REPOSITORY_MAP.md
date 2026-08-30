# Repository Map

This document is the first place an AI developer should look when navigating the project.

## Active tree

```text
premiere-render-app/
├── src/                    # application source
│   ├── core/               # business/domain logic; keep framework-free where possible
│   ├── network/            # LAN discovery, sessions, peer communication
│   ├── transfer/           # file/project transfer and chunking
│   ├── render/             # Media Encoder integration and output monitoring
│   ├── return_transfer/    # finished-video return flow
│   └── ui/                 # PySide6 desktop interface
├── tests/                  # stdlib unittest suite
├── scripts/                # Windows build/run scripts
├── docs/                   # architecture, setup, development documentation
├── archive/                # historical snapshots; never active source
├── .github/                # GitHub contribution/PR guidance
├── README.md               # project overview + quick start
├── AI_DEVELOPER_GUIDE.md   # AI development rules
└── requirements.txt        # runtime/build dependencies
```

## What belongs where

### `src/core/`
Pure application logic such as workflow state, configuration, job models, manifests, protocol definitions, project probing, workspace handling, and logging.

Do not import PySide6 into this layer. Avoid direct socket handling here unless the module is specifically the protocol abstraction.

### `src/network/`
Anything concerned with network listeners, sender/station sessions, LAN discovery, and peer information.

### `src/transfer/`
File transfer mechanics: manifests, chunking, progress, resume behavior, and sender-side transfer workers.

### `src/render/`
Render backends, Media Encoder integration, the Adobe ExtendScript agent, render queue management, and finished-output detection.

### `src/return_transfer/`
Logic for transferring a completed render back to the sender and verifying it.

### `src/ui/`
PySide6 windows, tabs, widgets, and UI-to-application bindings. Long-running work must stay off the Qt thread.

### `tests/`
Unit and integration tests. Tests should exercise behavior and remain runnable without real Adobe software whenever possible.

### `scripts/`
Developer/build entry points for Windows. Do not put application logic here.

### `docs/`
Human/AI-readable architecture and operational documentation. Keep it synchronized with actual behavior.

### `archive/`
Snapshots retained for history/comparison. Never import application code from this directory.

## File placement rule

Before creating a new module, ask whether an existing module already owns the responsibility. Prefer extending the existing module over creating near-duplicates such as `manager2.py`, `new_transfer.py`, or parallel V2 trees.

If a responsibility genuinely changes, document the new boundary in this file.

## Safe AI change pattern

```text
Read docs + relevant module
        ↓
Read relevant tests
        ↓
Make the smallest coherent change
        ↓
Run tests
        ↓
Update docs if behavior changed
        ↓
Commit to a focused feature/fix branch
```

## Historical material currently retained

`archive/latest_source/` is the older lightweight source snapshot preserved for comparison. It is not the active implementation.

The V2 experiment is kept on its feature branch rather than mixed into `main`.
