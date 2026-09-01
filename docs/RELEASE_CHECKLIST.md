# FileSender Remote V3 — Release Checklist

Do not merge `feature/v3-supabase-remote` into `main` until every required release-gate item below has been verified on the real target environment.

## Repository

- [x] Remote V3 / Supabase is the authoritative architecture.
- [x] Normal product UI does not use the legacy LAN transport.
- [x] No pairing-code workflow.
- [x] No normal-use IP or port entry.
- [x] No Go Online / Go Offline controls.
- [x] FileSender Windows icon is wired into the build.
- [x] Supabase migrations are committed.
- [x] Build scripts target `FileSender.exe`.

## Automated validation

- [x] Other AI reported 103 tests passing at the 3.0.0 checkpoint.
- [x] Active Python source compile-checked in the repository workspace.
- [ ] Full active test suite re-run on final Windows environment.
- [ ] Confirm full active test suite exits cleanly without hangs.

## Supabase

- [ ] Username/password sign-up works against the live project.
- [ ] Username/password sign-in works.
- [ ] Session restoration works after restart.
- [ ] Station registration works.
- [ ] Heartbeat correctly produces Online/Offline state.
- [ ] RLS blocks cross-account access.
- [ ] Private `project-files` access works.
- [ ] Private `render-results` access works.
- [ ] Large/resumable transfer works with a real project.
- [ ] Cloud cleanup does not delete active/recoverable jobs.

## Render Station

- [ ] FileSender opens and automatically starts the station worker.
- [ ] Station shows Online while the app is open.
- [ ] Closing FileSender stops the worker/heartbeat and station becomes Offline.
- [ ] No hidden FileSender service/process remains after close.
- [ ] Local project storage location is configurable and persists.
- [ ] Automatic job acceptance works.
- [ ] Manual Accept/Reject works when automatic acceptance is disabled.
- [ ] Media Encoder is detected correctly.
- [ ] JSX agent installs automatically and loads correctly.
- [ ] Adobe scripting permission is enabled.
- [ ] Real render completes unattended.

## Sender

- [ ] No IP/port/pairing code required.
- [ ] Stations appear by name and status.
- [ ] Offline station disables SEND.
- [ ] Busy station remains sendable and queues jobs.
- [ ] Station status is rechecked immediately before job creation.
- [ ] `.prproj` drag-and-drop works.
- [ ] Premiere project-folder drag-and-drop works.
- [ ] External media warning works.
- [ ] Same project can be sent repeatedly.
- [ ] Sender original project remains unchanged.
- [ ] MP4 downloads to configured folder.
- [ ] Returned MP4 checksum is verified.

## Windows installer

- [ ] `dist_installer\FileSender.exe` builds successfully.
- [ ] Installer icon is correct.
- [ ] Installed application icon appears in title bar/taskbar/Start Menu.
- [ ] Sender PC does not need Python or developer tools after installation.
- [ ] Render Station installation works.
- [ ] Uninstall entry appears in Windows Settings -> Apps.
- [ ] Uninstall works from Windows Settings / Control Panel.
- [ ] Reinstall works.
- [ ] Upgrade over an existing installation works.

## Two-network end-to-end test

Use two real Windows PCs on different networks.

- [ ] Render Station starts first and shows Online.
- [ ] Sender sees the station remotely.
- [ ] Sender can upload a real Premiere project.
- [ ] Render Station downloads it.
- [ ] Media Encoder renders it.
- [ ] Render result uploads.
- [ ] Sender downloads and verifies the MP4.
- [ ] Render Station can process a second queued job.
- [ ] Same Premiere project can be submitted again as a new job.
- [ ] Closing the Render Station makes it Offline and blocks new SEND actions.
- [ ] Reopening it restores Online state and pending-job recovery.

## Release gate

Only after all required items above are complete should the branch be merged into `main` and treated as a release candidate.
