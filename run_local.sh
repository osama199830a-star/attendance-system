#!/bin/sh
# تشغيل محلي كموقع ويب (لينكس/ماك): نفس البرنامج بدون EXE
cd "$(dirname "$0")"
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }
cd server && ../.venv/bin/python runner.py
