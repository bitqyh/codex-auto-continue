; Inno Setup script for the Windows installer.
; Build: ISCC.exe /DAppVersion=<version> installer\codex-auto-continue.iss
; The .exe produced here is the artifact submitted to SignPath Foundation.

#ifndef AppVersion
#define AppVersion "0.0.0"
#endif

#define AppName "Codex Auto Continue"
#define AppPublisher "Codex Auto Continue contributors"
#define AppExeName "CodexContinue"

[Setup]
AppId={{6F2B7E52-6B0B-4B0A-9B2E-6C6C0C5B7A11}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\Codex Auto Continue
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
SourceDir=..
OutputDir=dist
OutputBaseFilename=CodexContinue-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\ui\windows-tray\assets\CodexContinue.ico
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startup"; Description: "开机自动启动托盘"; GroupDescription: "附加任务："; Flags: unchecked
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: unchecked

[Files]
Source: "dist\CodexContinue-{#AppVersion}-win-x64\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{userprograms}\{#AppName}"; Filename: "{app}\ui\windows-tray\CodexContinueTray.vbs"; WorkingDir: "{app}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\ui\windows-tray\CodexContinueTray.vbs"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\ui\windows-tray\CodexContinueTray.vbs"; WorkingDir: "{app}"; Tasks: startup

[Run]
Filename: "{app}\ui\windows-tray\CodexContinueTray.vbs"; Description: "启动托盘"; Flags: postinstall nowait skipifsilent shellexec

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
