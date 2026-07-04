; Inno Setup script for PyReconstruct.
; Built in CI as:  ISCC /DPYR_VERSION=<version> packaging\windows\PyReconstruct.iss
; Expects the PyInstaller one-folder output at  <repo>\dist\PyReconstruct\

#ifndef PYR_VERSION
  #define PYR_VERSION "0.0.0"
#endif

[Setup]
; Fixed AppId => re-running the installer upgrades the existing install in place
; (this is what the in-app updater relies on).
AppId={{A1B2C3D4-E5F6-47A8-9B0C-1D2E3F4A5B6C}}
AppName=PyReconstruct
AppVersion={#PYR_VERSION}
AppPublisher=SynapseWeb
DefaultDirName={autopf}\PyReconstruct
DefaultGroupName=PyReconstruct
UninstallDisplayIcon={app}\PyReconstruct.exe
OutputDir=Output
OutputBaseFilename=PyReconstruct-{#PYR_VERSION}-Windows-x86_64-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Per-user install: no admin/UAC needed, and the updater can re-run it cleanly.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
; Close a running PyReconstruct so its files aren't locked during an upgrade.
CloseApplications=yes
RestartApplications=no

[InstallDelete]
; In-place upgrades (fixed AppId) copy the new onedir tree over the old one.
; Without this, files present in the old tree but not the new (renamed or
; dropped DLLs, removed modules in _internal, old Qt plugins) are left behind
; and the frozen runtime can load stale code — a classic PyInstaller-onedir
; upgrade failure that only reproduces on upgraded installs. Delete the
; PyInstaller payload before copying; user data must never live in {app}.
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\*.dll"

[Files]
Source: "..\..\dist\PyReconstruct\*"; DestDir: "{app}"; \
    Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\PyReconstruct"; Filename: "{app}\PyReconstruct.exe"
Name: "{autodesktop}\PyReconstruct"; Filename: "{app}\PyReconstruct.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; \
    GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\PyReconstruct.exe"; Description: "Launch PyReconstruct"; \
    Flags: nowait postinstall skipifsilent
