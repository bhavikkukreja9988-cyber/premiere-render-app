# Building FileSender.exe — step by step

This guide turns the source code into **FileSender.exe**, the installer you (and
your family) run to install the app. You only do this once per new version.

You do **not** need to understand any of the code. Follow the steps in order.
If a step fails, the tools tell you what to fix, and the troubleshooting
section at the bottom covers the common cases.

> **Where this runs:** on a **Windows PC**. It cannot be done on a Mac or Linux
> machine, and no AI can produce the .exe for you — building a Windows program
> requires a Windows computer. Any Windows PC works; it does **not** need Adobe
> or Premiere installed just to build the installer.

---

## What you install first (two free programs, once)

### 1. Python (the language the app is written in)

1. Go to <https://www.python.org/downloads/>
2. Click the big yellow **Download Python** button.
3. Run the downloaded file.
4. **Important:** on the first screen, tick the box
   **“Add python.exe to PATH”** at the bottom, then click **Install Now**.
5. When it finishes, click **Close**.

### 2. Inno Setup (the tool that makes the installer)

1. Go to <https://jrsoftware.org/isdl.php>
2. Download **“Inno Setup 6”** (the stable version).
3. Run it and click through with the default options.

That’s everything. You never touch these two again.

---

## Building the installer

1. Unzip the project somewhere simple, for example your Desktop, so you have a
   folder like:

   ```
   C:\Users\You\Desktop\premiere-render-app\
   ```

2. Open that folder in File Explorer.

3. Go into the **`scripts`** folder.

4. Double-click **`build_installer.bat`**.

   A black window opens and starts working. It will, in order:
   check your PC, set up a private workspace, install what it needs, run the
   tests, build the app, and wrap it into the installer. This takes a few
   minutes the first time. Just let it run.

   *(If Windows shows a blue “Windows protected your PC” box, click
   **More info → Run anyway**. That box appears for any new .bat file.)*

5. When it finishes you’ll see:

   ```
   SUCCESS

   Your installer is ready:
       dist_installer\FileSender.exe
   ```

6. Your installer is at:

   ```
   premiere-render-app\dist_installer\FileSender.exe
   ```

That single file is what you install and share. Copy it to any Windows PC and
run it — those PCs do **not** need Python or anything else.

---

## Checking your PC first (optional but reassuring)

If you want to check everything is ready *before* building, double-click
**`scripts\preflight.py`** (or, in a terminal in the project folder, run
`python scripts\preflight.py`). It prints a tidy PASS/FAIL list and tells you
exactly what to install if anything is missing. The build script runs this
check automatically anyway.

---

## Installing the app from FileSender.exe

1. Run **FileSender.exe**.
2. Click through: **Welcome → choose location → Install → Finish**.
   The default location is fine.
3. The app is now installed like any normal program, with a Start Menu entry
   **Premiere Render App**.

### Uninstalling

Exactly like any other program — no commands, no scripts:

- **Windows Settings → Apps → Installed apps →** find **Premiere Render App →
  Uninstall**, or
- **Control Panel → Programs and Features →** select it → **Uninstall**.

---

## Troubleshooting

**“Python was not found” / “‘python’ is not recognized.”**
Python isn’t on PATH. Reinstall Python and make sure you tick
**“Add python.exe to PATH”** on the first screen, then try again.

**“Inno Setup compiler (ISCC) not found.”**
Install Inno Setup 6 from <https://jrsoftware.org/isdl.php> and re-run the
build.

**The black window shows `[FAIL]` lines.**
Read the lines under each `[FAIL]` — they say exactly what to do. Fix those,
then double-click `build_installer.bat` again.

**“Automated tests did not pass.”**
The build stops on purpose so you don’t ship something broken. Send the messages
in the window to whoever maintains the code.

**Windows SmartScreen warns about FileSender.exe when you run it.**
That happens for any program that isn’t code-signed. Click
**More info → Run anyway**. (Code signing is a paid certificate; it’s optional
and only removes that one warning.)

**It built once and I changed something — do I need to delete anything?**
No. Just run `build_installer.bat` again; it cleans its own previous output.

---

## What the build produces (for reference)

```
premiere-render-app\
├── build_app\PremiereRenderApp\      the built app (intermediate)
├── build_pyi\                        PyInstaller work files (intermediate)
├── .venv_build\                      the private build environment
└── dist_installer\
        └── FileSender.exe            <-- the installer you want
```

Only `dist_installer\FileSender.exe` matters. The rest are build by-products and
can be deleted; they’ll be recreated next time you build.
