#define AppName "Koustav Laptop Battery Util"
#define ExeName "koustav-laptopbattery-util.exe"

[Setup]
AppId={{7B2E4C1A-5D3F-4E8B-9A61-2F0C8D4B7E19}
AppName={#AppName}
AppVersion=1.0.0
AppPublisher=Koustav
DefaultDirName={localappdata}\KoustavLaptopBatteryUtil
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=KoustavLaptopBatteryUtil-Setup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#ExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Files]
Source: "dist\{#ExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Run]
Filename: "{app}\{#ExeName}"; Parameters: "--install --quiet"; Flags: runhidden waituntilterminated
Filename: "{app}\{#ExeName}"; Description: "Start {#AppName} now"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{app}\{#ExeName}"; Parameters: "--uninstall --quiet"; Flags: runhidden waituntilterminated; RunOnceId: "KbuUninstall"
Filename: "{cmd}"; Parameters: "/c timeout /t 2 /nobreak"; Flags: runhidden waituntilterminated; RunOnceId: "KbuWait"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  rc: Integer;
begin
  if FileExists(ExpandConstant('{app}\{#ExeName}')) then
  begin
    Exec(ExpandConstant('{app}\{#ExeName}'), '--quit --quiet', '', SW_HIDE, ewWaitUntilTerminated, rc);
    Sleep(1500);
  end;
  Result := '';
end;
