@echo off
REM يبني AttendanceDoctor.exe على ويندوز (يحتاج Python 3.11+). النتيجة في dist\AttendanceDoctor
cd /d "%~dp0\.."
python -m pip install -r desktop\requirements.txt || exit /b 1
python -m PyInstaller --noconfirm --clean --windowed --name AttendanceDoctor --icon desktop\icon.ico ^
  --paths server --add-data "server\static;static" ^
  --hidden-import app --hidden-import core --hidden-import db --hidden-import config --hidden-import qr --hidden-import certs --hidden-import runner ^
  --collect-submodules webview --collect-submodules openpyxl ^
  desktop\main.py || exit /b 1
echo.
echo تم. شغّل dist\AttendanceDoctor\AttendanceDoctor.exe  — أو ابنِ المثبّت بـ Inno Setup من desktop\installer.iss
