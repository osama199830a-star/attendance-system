; مثبّت ويندوز — Inno Setup 6.  الأمر: iscc desktop\installer.iss
[Setup]
AppName=نظام الحضور بالباركود - جامعة المعارف
AppVersion=2.0
AppPublisher=Al-Maarif University
DefaultDirName={autopf}\AttendanceDoctor
DefaultGroupName=نظام الحضور
OutputDir=..\dist_installer
OutputBaseFilename=AttendanceDoctor-Setup
SetupIconFile=icon.ico
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
UninstallDisplayIcon={app}\AttendanceDoctor.exe

[Files]
Source: "..\dist\AttendanceDoctor\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\نظام الحضور بالباركود"; Filename: "{app}\AttendanceDoctor.exe"
Name: "{autodesktop}\نظام الحضور بالباركود"; Filename: "{app}\AttendanceDoctor.exe"

[Run]
; السماح لهواتف الطلاب بالوصول عبر شبكة القاعة (HTTP 5000 / HTTPS 5443)
Filename: "netsh"; Parameters: "advfirewall firewall add rule name=""Attendance Server"" dir=in action=allow protocol=TCP localport=5000,5443 profile=any"; Flags: runhidden
Filename: "{app}\AttendanceDoctor.exe"; Description: "تشغيل البرنامج الآن"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "netsh"; Parameters: "advfirewall firewall delete rule name=""Attendance Server"""; Flags: runhidden
