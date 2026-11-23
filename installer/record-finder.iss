; ============================================================================
;  记录检索器 —— Inno Setup 安装脚本
;
;  设计要点：
;    * 默认装到「用户目录」，不需要管理员权限，普通用户双击就能装完；
;    * 程序本体装到 {app}，用户数据放在 %LOCALAPPDATA%\RecordFinder，
;      升级/重装都不会碰数据；卸载时单独询问要不要删数据；
;    * 安装前检测程序是否在运行，避免文件占用；
;    * 支持静默安装 /VERYSILENT，方便批量部署。
;
;  编译：ISCC.exe installer\record-finder.iss
; ============================================================================

#define MyAppName "记录检索器"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "RecordFinder"
#define MyAppExeName "记录检索器.exe"
#define MyAppDirName "RecordFinder"

[Setup]
; AppId 决定「同一个程序」的身份：升级时靠它识别旧版本，千万不要随意改
AppId={{8F3A2C41-6D5E-4B7A-9C21-3E5D8A6B0F42}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
VersionInfoDescription={#MyAppName} 安装程序
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

DefaultDirName={autopf}\{#MyAppDirName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=auto

; 普通用户即可安装，全程不弹 UAC（默认装到用户目录）
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
; 默认按系统界面语言自动选中文，不再多弹一个语言选择框
ShowLanguageDialog=no

OutputDir=..\dist\installer
OutputBaseFilename=记录检索器-{#MyAppVersion}-安装程序
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

Compression=lzma2/max
SolidCompression=yes
LZMANumBlockThreads=2
WizardStyle=modern
WizardImageFile=assets\WizModernImage.bmp
WizardSmallImageFile=assets\WizModernSmallImage.bmp
WizardImageStretch=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
InfoBeforeFile=assets\before.txt

[Languages]
Name: "chinese"; MessagesFile: "languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
chinese.DiskSpaceMBLabel=至少需要 %1 MB 的可用磁盘空间。

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; DestName: "使用说明.md"; Flags: ignoreversion
Source: "..\installer\assets\license.txt"; DestDir: "{app}"; DestName: "许可说明.txt"; Flags: ignoreversion
Source: "..\samples\端子清单.xlsx"; DestDir: "{app}\示例数据"; Flags: ignoreversion
Source: "..\samples\传感器清单.xlsx"; DestDir: "{app}\示例数据"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Comment: "搜一个词定位到那一行"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; Comment: "搜一个词定位到那一行"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 注意：这里故意不删 {app}\data。
; 程序装在用户目录时该目录可写，早期版本会把数据放这里；
; 直接删会连用户数据一起抹掉，所以交给 [Code] 里的卸载逻辑按需询问处理。

[Registry]
; 程序靠这两个键判断自己是「安装版」还是「绿色版」，
; 安装版必须把数据放到 DataPath，绝不能落在会被卸载清空的安装目录里
Root: HKCU; Subkey: "Software\{#MyAppDirName}"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\{#MyAppDirName}"; ValueType: string; ValueName: "DataPath"; ValueData: "{%LOCALAPPDATA}\{#MyAppDirName}"; Flags: uninsdeletekey

[Code]
const
  DATA_DIR = 'RecordFinder';

var
  DataPath: String;

{ ---------- 工具函数 ---------- }

function GetDataDir(): String;
begin
  Result := ExpandConstant('{localappdata}\' + DATA_DIR);
end;

function DataHasContent(const Dir: String): Boolean;
var
  FindRec: TFindRec;
begin
  Result := False;
  if not DirExists(Dir) then
    Exit;
  if FindFirst(AddBackslash(Dir) + '*', FindRec) then
  begin
    try
      repeat
        if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
        begin
          Result := True;
          Exit;
        end;
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
end;

{ 程序是否正在运行

  做法：tasklist 过滤出目标进程名，输出到临时文件再读回来。
  判断依据是输出里有没有 ".exe"：
    · 正在运行 → 每个进程一行，含 imagename（形如 记录检索器.exe）
    · 没在运行 → 只有一句提示语（中英文都不含 ".exe"）
  这样不需要关心控制台代码页，中英文系统都适用。 }
function AppIsRunning(): Boolean;
var
  ResultCode: Integer;
  TempFile: String;
  Content: AnsiString;
  Cmd: String;
begin
  Result := False;
  TempFile := ExpandConstant('{tmp}\rf_tasklist.txt');
  Cmd := '/c tasklist /FI "IMAGENAME eq {#MyAppExeName}" /NH > "' + TempFile + '"';
  if not Exec(ExpandConstant('{cmd}'), Cmd, '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Exit;
  if not FileExists(TempFile) then
    Exit;
  if LoadStringFromFile(TempFile, Content) then
    Result := Pos('.exe', Lowercase(String(Content))) > 0;
  DeleteFile(TempFile);
end;

{ 结束进程，方便覆盖安装 }
procedure KillApp();
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{cmd}'), '/c taskkill /IM "{#MyAppExeName}" /F',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(600);
end;

{ ---------- 生命周期 ---------- }

procedure InitializeWizard();
begin
  DataPath := GetDataDir();
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if AppIsRunning() then
  begin
    if MsgBox('检测到「{#MyAppName}」正在运行，需要先关闭它才能继续安装。' + #13#10#13#10 +
              '要现在自动关闭吗？', mbConfirmation, MB_YESNO) = IDYES then
      KillApp()
    else
      Result := '请手动关闭程序后再继续安装。';
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    { 数据目录在用户目录下，这里只是确保存在，绝不覆盖已有数据 }
    ForceDirectories(DataPath);
  end;
end;

{ 卸载时：先确认程序已关闭 }
function InitializeUninstall(): Boolean;
begin
  Result := True;
  if AppIsRunning() then
  begin
    if MsgBox('「{#MyAppName}」正在运行，需要先关闭它才能卸载。' + #13#10#13#10 +
              '要现在自动关闭吗？', mbConfirmation, MB_YESNO) = IDYES then
      KillApp()
    else
      Result := False;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  LegacyData: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    if DataHasContent(DataPath) then
    begin
      if MsgBox('是否同时删除你的数据？' + #13#10#13#10 +
                '数据位置：' + DataPath + #13#10 +
                '（里面是你导入的项目清单和检索记录）' + #13#10#13#10 +
                '选择「是」= 一并删除，无法恢复' + #13#10 +
                '选择「否」= 保留数据，以后重装可以继续用',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      begin
        DelTree(DataPath, True, True, True);
      end;
    end;

    { 兼容早期版本：数据曾经可能落在安装目录的 data 下，同样询问 }
    LegacyData := ExpandConstant('{app}\data');
    if DataHasContent(LegacyData) then
    begin
      if MsgBox('在程序目录里还发现了一份旧数据：' + #13#10 + LegacyData + #13#10#13#10 +
                '要一起删除吗？', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(LegacyData, True, True, True);
    end;
  end;
end;
