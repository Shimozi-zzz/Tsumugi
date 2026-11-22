; Tsumugi Windows Installer Script (Inno Setup 6)
; 用法（仓库根目录）：
;   ISCC.exe /DAppVersion=0.9.0 /DReleaseTag=v0.9.0 packaging\installer.iss
;
; 数据安全保证：
;   - 应用运行期数据（tsumugi.db、封面、音视频、存档备份）均存放在 {app}\data\
;   - 打包输入目录 dist\Tsumugi 不包含 data\，且本脚本绝不配置 [UninstallDelete] 清理 data\
;   - 因此无论是覆盖升级还是卸载重装，均不会删除用户的 {app}\data\ 目录

#ifndef AppVersion
  #define AppVersion "0.9.0"
#endif

#ifndef ReleaseTag
  #define ReleaseTag "v" + AppVersion
#endif

#ifndef SourceDir
  #define SourceDir "..\dist\Tsumugi"
#endif

#ifndef OutputDir
  #define OutputDir "..\release_assets"
#endif

[Setup]
AppId={{8F6E1D92-4C3A-4E7B-9A25-7D2B1F8E4C10}
AppName=Tsumugi
AppVersion={#AppVersion}
AppVerName=Tsumugi {#ReleaseTag}
AppPublisher=Tsumugi
AppPublisherURL=https://github.com/Shimozi/tsumugi-platform
AppSupportURL=https://github.com/Shimozi/tsumugi-platform/issues
AppUpdatesURL=https://github.com/Shimozi/tsumugi-platform/releases
DefaultDirName={localappdata}\Programs\Tsumugi
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=Tsumugi-Setup-{#ReleaseTag}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=no
UninstallDisplayName=Tsumugi
UninstallDisplayIcon={app}\Tsumugi.exe
SetupIconFile=tsumugi.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Tsumugi"; Filename: "{app}\Tsumugi.exe"
Name: "{autodesktop}\Tsumugi"; Filename: "{app}\Tsumugi.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Tsumugi.exe"; Description: "{cm:LaunchProgram,Tsumugi}"; Flags: nowait postinstall skipifsilent
