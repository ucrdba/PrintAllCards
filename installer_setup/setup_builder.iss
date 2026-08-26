; Inno Setup Script for Student Photo Print Automator
; Note: Install Inno Setup 6 (https://jrsoftware.org/isdl.php) and compile this script to generate an installer setup.exe!

#define MyAppName "Student Photo Print Automator"
; Keep in step with APP_VERSION in ..ersion.py - the Inno Setup preprocessor
; cannot import Python, so this is the one place the version is duplicated.
#define MyAppVersion "1.2"
#define MyAppPublisher "UCRDBA"
#define MyAppURL "https://github.com/ucrdba/PrintAllCards"
#define MyAppExeName "StudentPhotoPrintAutomator.exe"

[Setup]
AppId={{52E4A0BC-1F44-4529-9AE6-3C84EFE7AD77}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
; The bundled EXE is a 64-bit PyInstaller build. Without this, Setup runs in
; 32-bit mode and {autopf} resolves to "Program Files (x86)", putting a 64-bit
; application in the 32-bit directory.
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
OutputBaseFilename=StudentPhotoPrintAutomator_Setup_v{#MyAppVersion}
SetupIconFile=..\app_icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\User_Guide.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autoprograms}\User Guide & Reference"; Filename: "{app}\User_Guide.txt"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
