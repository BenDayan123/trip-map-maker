; Inno Setup script — packages the built desktop app into a friendly Setup.exe.
; Prereqs: run build_exe.bat first (creates dist\My Maps Generator\), and install Inno
; Setup 6 (https://jrsoftware.org/isdl.php). Then run build_installer.bat.

#define AppName "My Maps Generator"
#define AppExe "My Maps Generator.exe"
#define AppVersion "1.1.2"
#define AppPublisher "My Maps Generator"

[Setup]
; Identity stays the ORIGINAL AppName so installs made before the rename are
; upgraded in place instead of appearing as a second app. Never change this.
AppId=Trip Map Maker
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
; Per-user install → no admin prompt (UAC), friendlier for a non-technical admin.
PrivilegesRequired=lowest
DefaultDirName={autopf}\MyMapsGenerator
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
OutputDir=installer
OutputBaseFilename=TripMapMaker-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
; The in-app self-update runs this installer with /SILENT after the app has
; already killed itself (Restart Manager couldn't reliably close the pywebview
; host + its Streamlit child, which left updates hanging). Still ask RM to close
; any straggler holding a file.
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; Everything PyInstaller produced (the exe + its _internal folder).
Source: "dist\My Maps Generator\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName} now"; Flags: nowait postinstall skipifsilent
; Silent run = the in-app self-update, which killed the app before installing.
; Relaunch it so the update finishes on the new version by itself.
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: WizardSilent
