# Repository organization — Remote V3

The repository is organized around the production Remote V3 architecture.

## Production tree

```text
src/
  core/       pure business logic
  remote/     Supabase/cloud services and transfer
  render/     Media Encoder/render pipeline
  ui/         PySide6 application UI

supabase/
  migrations/ reproducible database/RLS/realtime/storage setup
  functions/  backend functions only when actually required

tests/        active production tests
scripts/      Windows build and preflight scripts
installer/    PyInstaller and Inno Setup configuration
assets/       FileSender Windows icon
docs/         authoritative documentation
archive/      historical/reference material only
```

## Excluded from production source

The old direct-LAN implementation is not a production dependency. It used direct TCP/UDP transport, LAN discovery, manual IP/ports and pairing-code authentication. Those mechanisms are not part of Remote V3.

Legacy material may remain under `archive/` for reference, but nothing under that directory should be imported by the production application or packaged by the installer.

## Clean-tree rules

Do not commit:

- `.venv/` or `.venv_build/`
- `build_app/`
- `build_pyi/`
- `dist/` or `dist_installer/`
- `__pycache__/` or `*.pyc`
- runtime logs
- local session/config files
- Supabase local state
- secret credentials

The active documentation must describe Remote V3 consistently. If a handoff ZIP reintroduces old LAN instructions, replace those documents with the current Remote V3 versions rather than allowing conflicting instructions to accumulate.
