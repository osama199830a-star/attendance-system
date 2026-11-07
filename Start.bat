@echo off
chcp 65001 >nul
title نظام الحضور بالباركود
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python غير مثبت. ثبّته من python.org (فعّل Add to PATH) ثم أعد التشغيل.
  pause & exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo تجهيز البرنامج أول مرة (يحتاج إنترنت مرة واحدة)...
  python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
)
".venv\Scripts\python.exe" start_local.py
pause
