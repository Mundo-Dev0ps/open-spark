; Inno Setup script — Open Spark OBS plugin (Windows mini-installer).
;
; Drops the native .dll + data into the per-user OBS portable plugin
; dir (%APPDATA%\obs-studio\plugins\obs-open-spark\). No admin needed.
;
; Built in CI:
;   iscc /DMyAppVersion=%VER% /DSrcDir=artifact\windows packaging\windows\open-spark.iss
;
; Defaults let it also build locally after staging the artifact.

#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#ifndef SrcDir
  #define SrcDir "..\..\artifact\windows"
#endif

[Setup]
AppId={{B7E4B0F2-3C2A-4E2F-9C7E-0A5E0B1D9F10}
AppName=Open Spark (OBS plugin)
AppVersion={#MyAppVersion}
AppPublisher=Open Spark Contributors
AppPublisherURL=https://github.com/Mundo-Dev0ps/open-spark
DefaultDirName={userappdata}\obs-studio\plugins\obs-open-spark
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=obs-open-spark-setup
OutputDir=installer-out
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "{#SrcDir}\obs-plugins\64bit\obs-open-spark.dll"; \
  DestDir: "{app}\bin\64bit"; Flags: ignoreversion
Source: "{#SrcDir}\data\*"; DestDir: "{app}\data"; \
  Flags: ignoreversion recursesubdirs createallsubdirs

[Messages]
WelcomeLabel2=This installs the Open Spark plugin into OBS Studio.%n%nThe Open Spark backend is a separate Python app — see the project README.

[Run]
Filename: "https://github.com/Mundo-Dev0ps/open-spark#-install"; \
  Description: "Open setup instructions for the backend"; \
  Flags: postinstall shellexec nowait unchecked
