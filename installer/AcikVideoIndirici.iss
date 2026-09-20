; Açık Video İndirici v7.4.1 - Inno Setup kurulum betiği
; Sürüm, APP_VERSION ve extension manifest ile birlikte artırılır (README kural 1/22).
; Derleme: installer/KURULUM-OLUSTUR.bat veya "ISCC.exe AcikVideoIndirici.iss"

#define MyAppName "Açık Video İndirici"
#define MyAppVersion "7.4.1"
#define MyAppPublisher "Acik Video Indirici"
#define MyAppURL "https://github.com/ramazannbala/acik-video-indirici"
#define MyAppExeName "AcikVideoIndirici.exe"

[Setup]
AppId={{9F2E4C7A-6B1D-4A3E-8C5F-2D7A0B9E1436}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\AcikVideoIndirici
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
OutputDir=Output
OutputBaseFilename=Acik-Video-Indirici-Kurulum-{#MyAppVersion}
SetupIconFile=assets\app.ico
WizardImageFile=assets\wizard-left.bmp
WizardSmallImageFile=assets\wizard-small.bmp
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
PrivilegesRequired=admin
ShowLanguageDialog=auto
LanguageDetectionMethod=uilanguage
VersionInfoVersion={#MyAppVersion}.0
VersionInfoProductName={#MyAppName}
; Ayarlar/geçmiş %APPDATA% altında tutulur; kurulum-kaldırma bunlara dokunmaz.

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; PyInstaller onefile çıktısı (tek EXE, Python gerektirmez)
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; Tarayıcı eklentisi, kurulum klasöründe klasör olarak taşınır
Source: "..\extension\*"; DestDir: "{app}\extension"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Tarayıcı Eklentisi Klasörü"; Filename: "{app}\extension"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
