; FileSender.iss - Inno Setup script for the FileSender Windows installer
;
; Builds dist_installer\FileSender.exe from build_app\FileSender\.
; The installed application is also named FileSender.exe.

#define AppName "FileSender"
#define AppPublisher "FileSender"
#define AppVersion "3.2.0"
#define AppExeName "FileSender.exe"
#define BuildDir "..\build_app\FileSender"
#define AppIcon "..\assets\FileSender.ico"

[Setup]
AppId={{7B1D3F62-2A44-4E8C-9D2E-2F7A1C9B4E10}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\FileSender
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist_installer
OutputBaseFilename=FileSender
SetupIconFile={#AppIcon}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
PrivilegesRequired=admin
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; This only covers files inside the install folder itself (Program Files).
; The app's real user data lives in %APPDATA%\FileSender and is handled in
; [Code] below, because it needs a checkbox (received projects can be several
; GB) and Inno's declarative [UninstallDelete] can't ask the user anything.

[Code]
var
  DeleteProjectsFolder: Boolean;
  CachedWorkspaceDir: String;

function GetAppDataPath(): String;
begin
  Result := ExpandConstant('{userappdata}') + '\FileSender';
end;

{ Pull a flat string value out of config.json by key. Not a real JSON parser
  - our config file only ever has flat "key": "value" pairs, so simple string
  search is enough and avoids needing a JSON library in Pascal Script. }
function ExtractJSONString(const JsonText, Key: String): String;
var
  SearchStr, Rest: String;
  StartPos, EndPos: Integer;
begin
  Result := '';
  SearchStr := '"' + Key + '"';
  StartPos := Pos(SearchStr, JsonText);
  if StartPos = 0 then Exit;
  Rest := Copy(JsonText, StartPos + Length(SearchStr), Length(JsonText));
  StartPos := Pos(':', Rest);
  if StartPos = 0 then Exit;
  Rest := Copy(Rest, StartPos + 1, Length(Rest));
  StartPos := Pos('"', Rest);
  if StartPos = 0 then Exit;
  Rest := Copy(Rest, StartPos + 1, Length(Rest));
  EndPos := Pos('"', Rest);
  if EndPos = 0 then Exit;
  Result := Copy(Rest, 1, EndPos - 1);
end;

function ReadWorkspaceDir(): String;
var
  ConfigPath, AllText: String;
  Lines: TArrayOfString;
  I: Integer;
begin
  Result := '';
  ConfigPath := GetAppDataPath() + '\config.json';
  if not FileExists(ConfigPath) then Exit;
  if not LoadStringsFromFile(ConfigPath, Lines) then Exit;
  AllText := '';
  for I := 0 to GetArrayLength(Lines) - 1 do
    AllText := AllText + Lines[I] + #13#10;
  Result := ExtractJSONString(AllText, 'workspace_dir');
end;

{ Recursive folder size in bytes, purely for the confirmation text. Returns 0
  on anything unreadable rather than raising - this must never block or fail
  the uninstall itself, it's only informational. }
function GetDirSize(const Path: String): Int64;
var
  FindRec: TFindRec;
  FullPath: String;
begin
  Result := 0;
  if not DirExists(Path) then Exit;
  if FindFirst(Path + '\*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
        begin
          FullPath := Path + '\' + FindRec.Name;
          if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) <> 0 then
            Result := Result + GetDirSize(FullPath)
          else
            Result := Result + (Int64(FindRec.SizeHigh) shl 32) + FindRec.SizeLow;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

function FormatBytes(const Bytes: Int64): String;
begin
  if Bytes >= 107374182 then           { >= 0.1 GB }
    Result := Format('%.1f GB', [Bytes / 1073741824.0])
  else
    Result := Format('%.0f MB', [Bytes / 1048576.0]);
end;

{ Asks, with a real checkbox, whether received render-station projects should
  also be deleted. Only shown when there actually is something to delete -
  a Sender-only install with no workspace folder never sees this. }
function InitializeUninstall(): Boolean;
var
  Size: Int64;
  Form: TSetupForm;
  InfoLabel: TNewStaticText;
  CheckBox: TNewCheckBox;
  OKButton, CancelButton: TNewButton;
begin
  Result := True;
  DeleteProjectsFolder := False;
  CachedWorkspaceDir := ReadWorkspaceDir();

  if (CachedWorkspaceDir = '') or (not DirExists(CachedWorkspaceDir)) then
    Exit;                              { nothing extra to ask about }

  Size := GetDirSize(CachedWorkspaceDir);
  if Size = 0 then Exit;

  { Inno Setup 6.6.0+ signature: the size is fixed when the form is created
    and ClientWidth/ClientHeight are read-only afterwards. The last two
    arguments stop the dialog stretching with WizardSizePercent. }
  Form := CreateCustomForm(ScaleX(420), ScaleY(170), True, True);
  try
    Form.Caption := 'Uninstall FileSender';
    { No Position/BorderStyle needed: CreateCustomForm already makes a
      dialog-style form that centres itself when shown. }

    InfoLabel := TNewStaticText.Create(Form);
    InfoLabel.Parent := Form;
    InfoLabel.Left := ScaleX(16);
    InfoLabel.Top := ScaleY(16);
    InfoLabel.Width := Form.ClientWidth - ScaleX(32);
    InfoLabel.AutoSize := False;
    InfoLabel.WordWrap := True;
    InfoLabel.Height := ScaleY(80);
    InfoLabel.Caption :=
      'FileSender also has received Premiere projects stored at:' + #13#10 +
      CachedWorkspaceDir + #13#10#13#10 +
      'This is currently using ' + FormatBytes(Size) + '.';

    CheckBox := TNewCheckBox.Create(Form);
    CheckBox.Parent := Form;
    CheckBox.Left := ScaleX(16);
    CheckBox.Top := InfoLabel.Top + InfoLabel.Height + ScaleY(4);
    CheckBox.Width := Form.ClientWidth - ScaleX(32);
    CheckBox.Height := ScaleY(17);
    CheckBox.Caption := 'Also delete these received projects';
    CheckBox.Checked := False;         { default to keeping data, not losing it }

    OKButton := TNewButton.Create(Form);
    OKButton.Parent := Form;
    OKButton.Width := ScaleX(75);
    OKButton.Height := ScaleY(23);
    OKButton.Left := Form.ClientWidth - ScaleX(166);
    OKButton.Top := Form.ClientHeight - ScaleY(39);
    OKButton.Caption := 'Continue';
    OKButton.ModalResult := mrOK;
    OKButton.Default := True;

    CancelButton := TNewButton.Create(Form);
    CancelButton.Parent := Form;
    CancelButton.Width := ScaleX(75);
    CancelButton.Height := ScaleY(23);
    CancelButton.Left := Form.ClientWidth - ScaleX(83);
    CancelButton.Top := Form.ClientHeight - ScaleY(39);
    CancelButton.Caption := 'Cancel';
    CancelButton.ModalResult := mrCancel;
    CancelButton.Cancel := True;

    Form.ActiveControl := OKButton;

    if Form.ShowModal() = mrOK then
      DeleteProjectsFolder := CheckBox.Checked
    else
      Result := False;                 { Cancel aborts the whole uninstall }
  finally
    Form.Free();
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    { Received projects, only if the user opted in above. Read from the
      value cached during InitializeUninstall, since config.json (read by
      ReadWorkspaceDir) is about to be deleted along with the rest of
      %APPDATA%\FileSender a few lines down. }
    if DeleteProjectsFolder and (CachedWorkspaceDir <> '')
       and DirExists(CachedWorkspaceDir) then
      DelTree(CachedWorkspaceDir, True, True, True);

    { The app's own data is always removed: config, session, logs, the Media
      Encoder agent's queue/status files, and the plugin hand-off inbox.
      None of it is useful once the app is gone, and leaving it behind means
      a future reinstall silently inherits an old family code or device
      name instead of running first-run setup fresh. }
    DelTree(GetAppDataPath(), True, True, True);
  end;
end;
