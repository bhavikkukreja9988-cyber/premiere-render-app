# Remote V3 cleanup status

This file records the repository cleanup performed after the Remote V3 handoff was uploaded.

## Target architecture

Remote V3 is the primary product architecture:

Sender PC <-> Supabase <-> Render Station PC

The two PCs may be on different networks and in different locations.

## Removed from the normal Remote V3 documentation/UI

The final product must not require or expose as normal workflow:

- LAN-only connection requirements
- Manual IP entry
- Manual port entry
- Pairing codes
- Go Online / Go Offline controls
- Public TCP/UDP port forwarding

The Render Station's local IP may remain visible only as informational/debug data.

## Authentication

The user-facing login is username + password only. The implementation may internally map the username to a synthetic Supabase email because Supabase Auth uses email/password accounts. The synthetic address is not exposed to users.

## Settings cleanup

`src/ui/settings_panel.py` no longer exposes legacy LAN pairing/port controls in the normal Settings UI. It exposes the Remote V3 station identity, automatic job acceptance, retention, Media Encoder, Sender output, and account settings.

Legacy configuration fields may remain temporarily because old LAN modules are still present for migration/reference. They must not be used by the Remote V3 path.

## Documentation cleanup

The following documents now describe Remote V3 rather than the old LAN architecture:

- `README.md`
- `AI_DEVELOPER_GUIDE.md`
- `docs/ARCHITECTURE.md`
- `docs/PROTOCOL.md`
- `docs/SETUP_WINDOWS.md`

## Legacy code

`src/network/` remains in the repository as migration/reference code for now. It is not the Remote V3 transport and must not be extended as the primary path.

Before final release, the legacy path should either be removed or fully isolated so a normal user cannot accidentally select it.

## Verification still required

This cleanup does not mean the application is production-ready. Real validation is still required for:

- Live Supabase project
- Username/password authentication
- Two different physical networks
- Large resumable transfer
- Offline Send behavior
- Real Windows UI
- Real Premiere Pro / Adobe Media Encoder
- Full installed FileSender.exe workflow
