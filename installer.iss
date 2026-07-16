; Inno Setup script — packages the built desktop app into a friendly Setup.exe.
; Prereqs: run build_exe.bat first (creates dist\TripMapMaker\), and install Inno
; Setup 6 (https://jrsoftware.org/isdl.php). Then run build_installer.bat.

#define AppName "Trip Map Maker"
#define AppExe "TripMapMaker.exe"
#define AppVersion "1.0.1"
#define AppPublisher "Trip Map Maker"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
; Per-user install → no admin prompt (UAC), friendlier for a non-technical admin.
PrivilegesRequired=lowest
DefaultDirName={autopf}\TripMapMaker
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
; In-app self-update runs this installer with /SILENT /CLOSEAPPLICATIONS
; /RESTARTAPPLICATIONS. Restart Manager then closes the running app, replaces
; its files, and relaunches it — so an update needs no manual reinstall.
CloseApplications=yes
RestartApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; Everything PyInstaller produced (the exe + its _internal folder).
Source: "dist\TripMapMaker\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName} now"; Flags: nowait postinstall skipifsilent
