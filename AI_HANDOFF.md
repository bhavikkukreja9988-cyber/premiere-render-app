# AI Developer Handoff

This repository has two supplied project states. The root working tree remains the fuller MVP implementation already present in the repository. The later source package is preserved under `archive/latest_source/` for comparison and recovery.

## Important development rules

1. Inspect the existing source before changing it.
2. Do NOT replace `src/`, `tests/`, or `scripts/` wholesale.
3. Prefer small, incremental patches.
4. Preserve working functionality unless a change is required and documented.
5. Run the existing tests before and after changes.
6. Keep Windows/Premiere Pro/Media Encoder behavior compatible with the existing architecture.
7. Before deleting or renaming files, explain the reason and identify affected imports/tests.
8. Record every modified, added, or deleted file in the development summary.

## Current engineering goal

Build a reliable workflow for:

ZIP/project reception -> extraction/validation -> Premiere project detection -> Adobe Media Encoder/Premiere automation -> render completion detection -> output verification -> completed/failed job handling.

Do not claim Media Encoder automation is complete until it has been tested on the actual Windows machine with the installed Adobe versions.
