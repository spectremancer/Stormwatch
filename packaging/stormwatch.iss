#define AppVersion "1.1.0"
[Setup]
AppId={{AB143CE1-EA18-4BDE-BBB3-BF83A47BF8EF}
AppName=Stormwatch
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Stormwatch
DefaultGroupName=Stormwatch
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Stormwatch-{#AppVersion}-Setup
SetupIconFile=..\icon.ico
UninstallDisplayIcon={app}\Stormwatch.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
[Files]
Source: "..\dist\main.exe"; DestDir: "{app}"; DestName: "Stormwatch.exe"; Flags: ignoreversion
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
[Icons]
Name: "{group}\Stormwatch"; Filename: "{app}\Stormwatch.exe"
Name: "{autodesktop}\Stormwatch"; Filename: "{app}\Stormwatch.exe"; Tasks: desktopicon
[UninstallDelete]
Type: files; Name: "{app}\Stormwatch.exe"
[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Command, Expected, Quoted: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'Stormwatch', Command) then
    begin
      Command := Lowercase(Trim(Command));
      Expected := Lowercase(ExpandConstant('{app}\Stormwatch.exe'));
      Quoted := '"' + Expected + '"';
      if (Command = Expected) or (Copy(Command, 1, Length(Quoted)) = Quoted) or
         (Copy(Command, 1, Length(Expected) + 1) = Expected + ' ') then
        RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'Stormwatch');
    end;
  end;
end;
