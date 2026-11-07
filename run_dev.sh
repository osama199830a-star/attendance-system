#!/bin/sh
# تشغيل تجريبي على لينكس/ماك: الخادم + افتح http://127.0.0.1:5000/station/ و /admin/
cd "$(dirname "$0")/server" && python3 runner.py
