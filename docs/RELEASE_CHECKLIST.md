# FileSender — Release Checklist (3.x)

Tick an item only when it has been seen working on real Windows PCs with the
live Supabase project (a log or screenshot), not because tests pass.
Items already ticked were confirmed from real application logs and screenshots.

## Repository

- [x] No login screen; setup asks only for a PC name and a family code.
- [x] No pairing code, IP or port entry; no Go Online / Go Offline controls.
- [x] FileSender icon wired into the build.
- [x] Supabase migrations 001-007 committed; health check in `SUPABASE_CHECKLIST.txt`.
- [x] Build scripts produce `FileSender.exe`; preflight rejects damaged files.

## Automated validation

- [x] Full test suite passes on the Windows build PC (it gates the installer build).
- [ ] Full test suite passes at 3.3.0 on Windows (196 tests).

## Supabase (live project)

- [x] Project awake; URL and key match the app.
- [x] Migrations applied, including 007 (`server_time()` answers).
- [x] Silent sign-in to the family account works.
- [x] Station registration works.
- [x] Heartbeats reach Supabase.
- [ ] A second PC with the same family code sees the first as Online.
- [ ] A PC with a DIFFERENT family code does not see it (isolation).
- [ ] Private `project-files` upload/download works with a real project.
- [ ] Private `render-results` upload/download works.
- [ ] Large (chunked, resumable) transfer works.
- [ ] Cloud files of failed/cancelled jobs are removed after ~10 minutes.

## Render Station

- [x] Opening FileSender starts the station automatically.
- [x] Closing FileSender marks the station offline.
- [x] Adobe Media Encoder is detected (render backend: Adobe Media Encoder).
- [ ] No FileSender process remains after closing.
- [ ] Automatic job acceptance works.
- [ ] Manual Accept/Reject works with auto-accept turned off.
- [ ] Real render completes unattended (JSX agent loaded).
- [ ] Received-jobs list shows progress; Cancel render and Clear job work.

## Sender

- [ ] Only other PCs of the family are listed (never this PC).
- [ ] Offline PC disables SEND; Busy PC stays sendable.
- [ ] `.prproj` and project-folder drag-and-drop work.
- [ ] External-media and size warnings appear when they should.
- [ ] The same project can be sent again as a new job.
- [ ] The original project is unchanged afterwards.
- [ ] The MP4 arrives in the output folder, checksum verified.
- [ ] A failed send shows the reason and Retry works.

## Windows installer

- [x] `dist_installer\FileSender.exe` builds and installs.
- [ ] Installed app icon correct in title bar / taskbar / Start Menu.
- [ ] A PC without Python runs the installed app.
- [ ] Upgrade over an existing installation keeps the settings.
- [ ] Uninstall removes `%APPDATA%\FileSender` and asks about received projects.

## Two-house end-to-end test

- [ ] Render PC open and Online; sender sees it by name.
- [ ] Real project uploaded, downloaded, rendered, returned and verified.
- [ ] A second queued job also completes.
- [ ] Closing the render PC makes it Offline and blocks new sends.
- [ ] Reopening it restores Online and resumes pending jobs.

## Before 4.0

- [ ] Connection test (`docs/CONNECTION_TEST_GUIDE.txt`) run on both PCs; both
      result files saved.
