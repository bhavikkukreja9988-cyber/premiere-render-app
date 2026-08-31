; FileSender.iss - Inno Setup script for Premiere Render App
; ---------------------------------------------------------------------------
; Produces the installer executable  FileSender.exe.
;
; It packages the one-folder PyInstaller build at
;   build_app\PremiereRenderApp\
; into a normal Windows installer that:
;   - shows Welcome -> install location -> Install -> Finish
;   - installs under Program Files by default (user-changeable)
;   - creates a Start Menu shortcut (and optional Desktop shortcut)
;   - registers a proper uninstaller in Settings > Apps / Programs & Features
;   - upgrades cleanly over a previous version
;
; Build it with the Inno Setup compiler:
;   ISCC.exe installer\FileSender.iss
; The build scripts do this for you.

#define AppName "Premiere Render App"
#define AppPublisher "Premiere Render App"
#define AppVersion "2.0.0"
#define AppExeName "PremiereRenderApp.exe"
; Source folder produced by PyInstaller (relative to this .iss file).
#define BuildDir "..\build_app\PremiereRenderApp"

[Setup]
; A stable GUID keeps upgrades and uninstall registration consistent. Do not
; change it between versions of this same app.
AppId={{7B1D3F62-2A44-4E8C-9D2E-2F7A1C9B4E10}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\PremiereRenderApp
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; The finished installer file:
OutputDir=..\dist_installer
OutputBaseFilename=FileSender
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
; Installing into Program Files needs elevation; this asks for it once.
PrivilegesRequired=admin
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; \
    GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
; Recursively include the entire PyInstaller one-folder build.
Source: "{#BuildDir}\*"; DestDir: "{app}"; \
    Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; \
    Tasks: desktopicon

[Run]
; Offer to launch the app when the wizard finishes.
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove leftover runtime files the app may have written next to itself.
Type: filesandordirs; Name: "{app}\logs"
