#ifndef AppVersion
  #define AppVersion "2.3.1.2"
#endif
#ifndef SourceExe
  #define SourceExe "..\build_tmp\winui-publish\ImageToPDF.WinUI.exe"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{8E6A3D21-7C4B-4F92-A51E-3B90D4E8C210}
AppName=画像PDF変換ツール
AppVersion={#AppVersion}
AppVerName=画像PDF変換ツール v{#AppVersion}
VersionInfoVersion={#AppVersion}
AppPublisher=burugou05-wq
AppSupportURL=https://github.com/burugou05-wq/PDF_conversion
AppUpdatesURL=https://github.com/burugou05-wq/PDF_conversion/releases
DefaultDirName={autopf}\ImageToPDF
DefaultGroupName=画像PDF変換ツール
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
OutputDir={#OutputDir}
OutputBaseFilename=ImageToPDF-Setup-v{#AppVersion}-Windows-x64
SetupIconFile=..\app_icon.ico
UninstallDisplayIcon={app}\ImageToPDF.exe
UninstallDisplayName=画像PDF変換ツール
Compression=lzma2/fast
SolidCompression=no
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceExe}"; DestDir: "{app}"; DestName: "ImageToPDF.exe"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\画像PDF変換ツール"; Filename: "{app}\ImageToPDF.exe"
Name: "{autodesktop}\画像PDF変換ツール"; Filename: "{app}\ImageToPDF.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ImageToPDF.exe"; Description: "{cm:LaunchProgram,画像PDF変換ツール}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\ImageToPDF.exe"; Flags: nowait skipifnotsilent; Check: ShouldAutoLaunch

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\ImageToPDF"

[Code]
function ShouldAutoLaunch: Boolean;
begin
  Result := ExpandConstant('{param:AUTOLAUNCH|0}') = '1';
end;
