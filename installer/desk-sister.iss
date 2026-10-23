; Desk Sister installer (Inno Setup 6). Built by devtools/build_installer.ps1:
;   ISCC /DVersion=0.1.16 /DSourceDir=<the PyInstaller one-folder build> installer\desk-sister.iss
; Per user, no administrator: into %LOCALAPPDATA%\Programs\DeskSister, where the single-file exe always lived,
; so the startup and desktop shortcuts that point there keep working. Config and memory in %APPDATA%\ClaudePet
; are never touched, also not by the uninstaller.

#ifndef Version
  #error Pass /DVersion=x.y.z
#endif
#ifndef SourceDir
  #error Pass /DSourceDir=<one-folder build>
#endif
#ifndef NumericVersion
  #define NumericVersion Version
#endif
#ifndef AppIdValue
  #define AppIdValue "{{9CE53F5B-A1AD-45A4-A120-B73694D33503}"
#endif

[Setup]
AppId={#AppIdValue}
AppName=Desk Sister
AppVersion={#Version}
AppVerName=Desk Sister {#Version}
AppPublisher=leto0309
AppPublisherURL=https://github.com/leto0309/desk-sister
AppSupportURL=https://github.com/leto0309/desk-sister/issues
AppUpdatesURL=https://github.com/leto0309/desk-sister/releases
VersionInfoVersion={#NumericVersion}
DefaultDirName={localappdata}\Programs\DeskSister
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Close a running Desk Sister (Restart Manager) before replacing her files; she is started again by [Run]
; or, for an in-app update, by the update helper.
CloseApplications=force
RestartApplications=no
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\desk-sister.exe
UninstallDisplayName=Desk Sister
OutputDir=..\dist
OutputBaseFilename=DeskSister-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ShowLanguageDialog=no
LanguageDetectionMethod=uilanguage

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[CustomMessages]
english.DesktopIcon=Create a desktop shortcut
chinesesimplified.DesktopIcon=创建桌面快捷方式

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
#ifdef FailForTest
; A test build only: one more file, copied last. A test puts a folder where it goes, so copying fails after the app's
; files went in, as a disk error would.
Source: "{#SourceDir}\desk-sister.exe"; DestDir: "{app}"; DestName: "fail-for-test.bin"
#endif

[Icons]
Name: "{autoprograms}\Desk Sister"; Filename: "{app}\desk-sister.exe"
Name: "{autodesktop}\Desk Sister"; Filename: "{app}\desk-sister.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\desk-sister.exe"; Description: "{cm:LaunchProgram,Desk Sister}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; What the program itself leaves next to the exe: in-app update leftovers.
Type: filesandordirs; Name: "{app}\_internal"
Type: filesandordirs; Name: "{app}\_internal.previous"
Type: files; Name: "{app}\desk-sister.exe.previous"
Type: files; Name: "{app}\desk-sister.old.exe"
Type: files; Name: "{app}\desk-sister.update*"
Type: files; Name: "{app}\DeskSister-Setup.update*"
Type: dirifempty; Name: "{app}"

[Code]
// Quit a Desk Sister running from {app} before her files are replaced or removed (copies elsewhere are left
// alone). Setup's own Restart Manager closes apps only after ssInstall, too late for setting files aside.
// Closed outright: her settings are saved as they change, so at most a minute of companion memory is lost.
function SetEnvironmentVariable(Name, Value: String): BOOL;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';

procedure CloseRunningCopies();
var
  ResultCode: Integer;
begin
  // The folder goes in an environment variable the child inherits; the command text is fixed (no quoting of paths).
  SetEnvironmentVariable('DESK_SISTER_APP', ExpandConstant('{app}') + '\');
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
              '-NoProfile -NonInteractive -Command "Get-Process desk-sister -ErrorAction SilentlyContinue | ' +
              'Where-Object { $_.Path -and $_.Path.StartsWith($env:DESK_SISTER_APP, ' +
              '[StringComparison]::OrdinalIgnoreCase) } | Stop-Process -Force; Start-Sleep -Seconds 2"',
              '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Log('Could not start PowerShell to close a running Desk Sister')
  else if ResultCode <> 0 then
    Log(Format('Closing a running Desk Sister ended with code %d', [ResultCode]));
end;

// The previous version is set aside before the new files go in (so nothing stale is left next to them), and put
// back if the install does not finish: Inno Setup's own rollback removes new files but cannot restore these.
var
  InstallDone, LibAside, ExeAside: Boolean;  // only what this run set aside is ever put back

function Previous(const Name: String): String;
begin
  Result := ExpandConstant('{app}\') + Name + '.previous';
end;

// A .previous left by an earlier run is not this run's: it is never restored. It is cleared only when the current
// item is there to take its place; if an earlier install was cut off right after setting it aside, it may be the only
// whole copy, so it is kept and this run leaves it alone.
function SetAside(const Name: String): Boolean;
begin
  Result := False;
  if not (DirExists(ExpandConstant('{app}\') + Name) or FileExists(ExpandConstant('{app}\') + Name)) then
    exit;
  if DirExists(Previous(Name)) then
    DelTree(Previous(Name), True, True, True)
  else if FileExists(Previous(Name)) then
    DeleteFile(Previous(Name));
  if RenameFile(ExpandConstant('{app}\') + Name, Previous(Name)) then
    Result := True
  else
    RaiseException('Could not set aside ' + Name);
end;

procedure PutBack(const Name: String; Aside: Boolean);
begin
  if not Aside or not (DirExists(Previous(Name)) or FileExists(Previous(Name))) then
    exit;
  if DirExists(ExpandConstant('{app}\') + Name) then
    DelTree(ExpandConstant('{app}\') + Name, True, True, True)
  else if FileExists(ExpandConstant('{app}\') + Name) then
    DeleteFile(ExpandConstant('{app}\') + Name);
  if not RenameFile(Previous(Name), ExpandConstant('{app}\') + Name) then
    Log('Could not put back ' + Name + '; it is kept as ' + Previous(Name));
end;

procedure Forget(const Name: String);
begin
  if DirExists(Previous(Name)) then
    DelTree(Previous(Name), True, True, True)
  else if FileExists(Previous(Name)) then
    DeleteFile(Previous(Name));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then begin
    CloseRunningCopies();
    LibAside := SetAside('_internal');
    ExeAside := SetAside('desk-sister.exe');
  end else if CurStep = ssPostInstall then begin
    InstallDone := True;
    // The in-app update passes /KEEPPREVIOUS=1 and deletes the kept version itself once the new one is up
    // (or puts it back if the new one will not start). A manual install deletes it now.
    if ExpandConstant('{param:KEEPPREVIOUS|0}') <> '1' then begin
      Forget('_internal');
      Forget('desk-sister.exe');
    end;
  end;
end;

#ifdef CancelForTest
// A test build only: gives up before installing, as a user cancelling at the last moment would.
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := 'Cancelled on purpose (test build)';
end;

#endif
procedure DeinitializeSetup();
begin
  if not InstallDone then begin
    PutBack('_internal', LibAside);
    PutBack('desk-sister.exe', ExeAside);
  end;
end;

// The "Start with Windows" shortcut belongs to this program only when it points at {app}\desk-sister.exe:
// removed then, left alone otherwise (a shortcut of the same name for something else is not ours).
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Link: String;
  Shell, Shortcut: Variant;
begin
  if CurUninstallStep = usUninstall then
    CloseRunningCopies();  // only once the uninstall is confirmed: a cancelled one leaves her running
  if CurUninstallStep <> usPostUninstall then
    exit;
  Link := ExpandConstant('{userstartup}\Desk Sister.lnk');
  if not FileExists(Link) then
    exit;
  try
    Shell := CreateOleObject('WScript.Shell');
    Shortcut := Shell.CreateShortcut(Link);
    if CompareText(Shortcut.TargetPath, ExpandConstant('{app}\desk-sister.exe')) = 0 then
      DeleteFile(Link);
  except
    Log('Could not check the startup shortcut: ' + GetExceptionMessage);
  end;
end;
