@echo off
chcp 65001 >nul
title نظام الحضور - الخادم المحلي (لا تغلق هذه النافذة)
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python غير مثبت. ثبّته من python.org ^(فعّل Add Python to PATH^) ثم أعد التشغيل.
  pause & exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo تجهيز البيئة لأول مرة ^(يحتاج إنترنت مرة واحدة^)...
  python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
  if errorlevel 1 ( echo فشل التثبيت & pause & exit /b 1 )
)
echo.
echo  ===== نظام الحضور بالباركود - تشغيل محلي =====
echo  شاشة الدكتور : http://127.0.0.1:5000/station/
echo  لوحة الإدارة : http://127.0.0.1:5000/admin/
echo  صفحة الطالب  : https://عنوان-هذا-الجهاز:5443/s/  ^(يظهر في الباركود^)
echo.
start "" http://127.0.0.1:5000/station/
cd server
"..\.venv\Scripts\python.exe" runner.py
pause
