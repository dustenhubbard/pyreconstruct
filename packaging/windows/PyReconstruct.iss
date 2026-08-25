; Inno Setup script for PyReconstruct.
; Built in CI as:  ISCC /DPYR_VERSION=<version> packaging\windows\PyReconstruct.iss
; Expects the PyInstaller one-folder output at  <repo>\dist\PyReconstruct\

#ifndef PYR_VERSION
  #define PYR_VERSION "0.0.0"
#endif

; Flavor: CI passes /DPYR_FLAVOR=dev when packaging/FLAVOR says so. The Dev
; app is a separate product -- its own AppId, name, install dir, and icon --
; so it installs beside stable and the two upgrade independently. The asset
; keeps the "PyReconstruct-<ver>-<platform>" shape the in-app updater parses,
; with the -Dev marker trailing the platform tag.
#ifdef PYR_FLAVOR
  #if PYR_FLAVOR == "dev"
    #define PYR_APPID "{{0C76AF3D-BB20-4EDB-99FC-2B9244E213F7}}"
    #define PYR_NAME "PyReconstruct Dev"
    #define PYR_PROGID "PyReconstructDev.jser"
    #define PYR_OUTBASE "PyReconstruct-" + PYR_VERSION + "-Windows-x86_64-Dev-Setup"
  #endif
#endif
#ifndef PYR_NAME
  #define PYR_APPID "{{A1B2C3D4-E5F6-47A8-9B0C-1D2E3F4A5B6C}}"
  #define PYR_NAME "PyReconstruct"
  #define PYR_PROGID "PyReconstruct.jser"
  #define PYR_OUTBASE "PyReconstruct-" + PYR_VERSION + "-Windows-x86_64-Setup"
#endif

[Setup]
; Fixed AppId => re-running the installer upgrades the existing install in place
; (this is what the in-app updater relies on).
AppId={#PYR_APPID}
AppName={#PYR_NAME}
AppVersion={#PYR_VERSION}
AppPublisher=SynapseWeb
DefaultDirName={autopf}\{#PYR_NAME}
DefaultGroupName={#PYR_NAME}
UninstallDisplayIcon={app}\{#PYR_NAME}.exe
OutputDir=Output
OutputBaseFilename={#PYR_OUTBASE}
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
; The .jser association below; tells Explorer to refresh its file-type cache.
ChangesAssociations=yes

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
Source: "..\..\dist\{#PYR_NAME}\*"; DestDir: "{app}"; \
    Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#PYR_NAME}"; Filename: "{app}\{#PYR_NAME}.exe"
Name: "{autodesktop}\{#PYR_NAME}"; Filename: "{app}\{#PYR_NAME}.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; \
    GroupDescription: "Additional shortcuts:"

[Registry]
; Associate .jser with this install. HKA is per-user here (PrivilegesRequired
; is lowest), so stable and Dev can each hold their own ProgID without UAC.
; OpenWithProgids (not a bare default value) so an existing user choice for
; .jser is respected; a fresh machine opens .jser with this app directly.
Root: HKA; Subkey: "Software\Classes\.jser\OpenWithProgids"; \
    ValueType: string; ValueName: "{#PYR_PROGID}"; ValueData: ""; \
    Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKA; Subkey: "Software\Classes\.jser"; ValueType: string; \
    ValueName: ""; ValueData: "{#PYR_PROGID}"; Flags: createvalueifdoesntexist
Root: HKA; Subkey: "Software\Classes\{#PYR_PROGID}"; ValueType: string; \
    ValueName: ""; ValueData: "PyReconstruct series"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\{#PYR_PROGID}\DefaultIcon"; \
    ValueType: string; ValueName: ""; ValueData: "{app}\{#PYR_NAME}.exe,0"
Root: HKA; Subkey: "Software\Classes\{#PYR_PROGID}\shell\open\command"; \
    ValueType: string; ValueName: ""; \
    ValueData: """{app}\{#PYR_NAME}.exe"" ""%1"""

[Run]
Filename: "{app}\{#PYR_NAME}.exe"; Description: "Launch {#PYR_NAME}"; \
    Flags: nowait postinstall skipifsilent
