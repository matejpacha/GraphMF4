; GraphMF4 — InnoSetup installer script
;
; Prerequisites:
;   1. Run PyInstaller first:  pyinstaller GraphMF4.spec --clean --noconfirm
;   2. Open this file in InnoSetup IDE and click Build, OR run from command line:
;        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" GraphMF4.iss
;
; Output: installer\GraphMF4_Setup_1.0.0.exe  (~90-100 MB, lzma2 compressed)

#define AppName      "GraphMF4"
#define AppVersion   "1.0.0"
#define AppPublisher "GraphMF4"
#define AppExe       "GraphMF4.exe"
#define AppId        "{{6F3A2D85-C419-4B7E-A8D3-E5F1C2B94A70}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppVerName={#AppName} {#AppVersion}

; Install to %LocalAppData%\Programs\GraphMF4 — no admin required
DefaultDirName={autopf}\{#AppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

DefaultGroupName={#AppName}
DisableProgramGroupPage=yes

; Output
OutputDir=installer
OutputBaseFilename={#AppName}_Setup_{#AppVersion}
SetupIconFile=src\icon\mf4_icon_multi.ico

; Compression
Compression=lzma2/max
SolidCompression=yes

; UI
WizardStyle=modern
ShowLanguageDialog=no

; Metadata shown in Programs & Features
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName} {#AppVersion}

; Architecture
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

; ── Optional tasks ──────────────────────────────────────────────────────────
[Tasks]
Name: "desktopicon"; \
  Description: "Create a &desktop shortcut"; \
  GroupDescription: "Additional shortcuts:"; \
  Flags: unchecked
Name: "fileassoc"; \
  Description: "Associate &.gmf4proj files with {#AppName}"; \
  GroupDescription: "File associations:"

; ── Files ───────────────────────────────────────────────────────────────────
[Files]
; Everything PyInstaller produced
Source: "dist\{#AppName}\*"; \
  DestDir: "{app}"; \
  Flags: ignoreversion recursesubdirs createallsubdirs

; ── Shortcuts ───────────────────────────────────────────────────────────────
[Icons]
Name: "{userprograms}\{#AppName}"; \
  Filename: "{app}\{#AppExe}"; \
  IconFilename: "{app}\{#AppExe}"

Name: "{userdesktop}\{#AppName}"; \
  Filename: "{app}\{#AppExe}"; \
  IconFilename: "{app}\{#AppExe}"; \
  Tasks: desktopicon

; ── .gmf4proj file association (HKCU — no admin needed) ─────────────────────
[Registry]
; Extension → ProgID
Root: HKCU; \
  Subkey: "Software\Classes\.gmf4proj"; \
  ValueType: string; ValueName: ""; ValueData: "GraphMF4.Project"; \
  Flags: uninsdeletevalue; Tasks: fileassoc

; ProgID definition
Root: HKCU; \
  Subkey: "Software\Classes\GraphMF4.Project"; \
  ValueType: string; ValueName: ""; ValueData: "GraphMF4 Project"; \
  Flags: uninsdeletekey; Tasks: fileassoc

; Icon for .gmf4proj files in Explorer
Root: HKCU; \
  Subkey: "Software\Classes\GraphMF4.Project\DefaultIcon"; \
  ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"; \
  Tasks: fileassoc

; Open command — passes the file path as argument to the exe
Root: HKCU; \
  Subkey: "Software\Classes\GraphMF4.Project\shell\open\command"; \
  ValueType: string; ValueName: ""; \
  ValueData: """{app}\{#AppExe}"" ""%1"""; \
  Tasks: fileassoc

; ── Post-install ─────────────────────────────────────────────────────────────
[Run]
; Optionally launch the app after installation
Filename: "{app}\{#AppExe}"; \
  Description: "Launch {#AppName}"; \
  Flags: nowait postinstall skipifsilent

; ── Code: refresh Explorer shell after file association change ────────────────
[Code]
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    // Notify Explorer to reload file type icons/associations
    RegWriteStringValue(
      HKCU,
      'Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.gmf4proj\UserChoice',
      'ProgId', 'GraphMF4.Project');
end;
