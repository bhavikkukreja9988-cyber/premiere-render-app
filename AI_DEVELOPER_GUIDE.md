# AI Developer Guide

Read this file before modifying the repository.

## 1. What this project is

A Windows desktop application for sending an Adobe Premiere Pro project folder over a home LAN to a render PC, rendering it with Adobe Media Encoder, and returning the finished MP4.

The application is intended to support two roles in one program:

- Sender — selects a project and sends it.
- Render Station — receives, queues, renders, and returns the result.

## 2. Branch rules

- `main`: stable, tested baseline. Avoid direct feature development here.
- `develop`: integration branch. Features should be tested here before release to `main`.
- `feature/<name>`: feature work. One clear objective per branch.
- `fix/<name>`: bug fixes.
- `chore/<name>`: tooling/documentation/repository maintenance.
- `archive/<name>` or the `archive/` directory: historical material only.

Start new work from the newest `develop` unless a task specifically targets the stable `main` branch.

## 3. Source-of-truth rules

The active application source is under `src/`. Documentation describes the intended architecture, but executable behavior is defined by the source and tests.

Do not treat files under `archive/` as active source.

Do not replace `src/`, `tests/`, `scripts/`, or `docs/` wholesale merely because a newer package contains similarly named files. Compare first, preserve working behavior, and make incremental changes.

## 4. Architecture boundaries

```text
ui
 ↓
core workflow / jobs
 ↓
network + transfer
 ↓
render pipeline
 ↓
Media Encoder integration
 ↓
output monitor
 ↓
return transfer
```

`src/core/` should remain independent of Qt and socket code wherever practical so it stays easy to test.

## 5. Development loop for an AI

Before editing:

1. Read this file.
2. Read `docs/REPOSITORY_MAP.md`.
3. Inspect the relevant source files, tests, and recent commits.
4. State which files actually need modification.

After editing:

1. Run the existing unit/integration tests.
2. Check imports and entry points.
3. Check that no generated files or secrets were added.
4. Summarize added, modified, deleted, and moved files.
5. For significant changes, create a focused pull request instead of merging directly into `main`.

## 6. Testing

Run:

```powershell
python -m unittest discover -s tests -t .
```

Tests must not be weakened or rewritten just to force a pass.

Real Premiere Pro / Media Encoder behavior cannot be proven by the pure-Python tests. Adobe integration must be verified on the Windows machine with the installed Adobe versions.

## 7. Current V2 work

`feature/v2-transfer-render-return` is an experimental/incomplete V2 branch. Its PR should not be merged until the complete V2 implementation is present and tested.

## 8. What not to commit

Never commit:

- `.venv/`
- `build/`
- `dist/`
- `__pycache__/`
- local logs
- machine-specific secrets or credentials
- real Premiere project/media assets

## 9. Definition of done for a feature

A change is ready for integration when the code is present in the correct module, tests cover the behavior, existing tests remain green, documentation is updated where behavior changed, and the change can be explained from the repository without relying on hidden conversation context.
