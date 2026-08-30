# Development Workflow

## Branch model

```text
main
  └── develop
       ├── feature/<focused-feature>
       ├── fix/<focused-bug>
       └── chore/<maintenance>
```

### `main`
Stable baseline only. It should be buildable and tested.

### `develop`
Integration branch. Merge completed feature/fix work here after review and testing.

### Feature branches
Create one branch per coherent change. Examples:

- `feature/background-render`
- `feature/project-transfer`
- `feature/mp4-return`
- `fix/output-monitor-timeout`
- `chore/repository-organization`

Do not make unrelated changes in the same branch.

## Pull requests

A PR should state:

1. What changed.
2. Why it changed.
3. Which files/modules are affected.
4. How it was tested.
5. Any Windows/Premiere/Media Encoder testing that remains.

Use draft PRs for work that is not yet ready to merge.

## Commit style

Prefer focused messages such as:

```text
feat: add resumable project transfer
fix: reject unsafe manifest paths
refactor: isolate render backend interface
test: cover interrupted job recovery
docs: document Media Encoder setup
chore: clean repository layout
```

## AI-specific rule

Never assume a generated package is the source of truth merely because its file names match the repository. First compare it with the current branch and tests. Patch existing modules instead of replacing whole directories unless the task explicitly calls for a migration.

## Before merge

Run:

```powershell
python -m unittest discover -s tests -t .
```

For Windows packaging:

```powershell
scripts\build_windows.bat
```

For Media Encoder changes, also run the real Windows `--check` command and test with the installed Adobe versions.
