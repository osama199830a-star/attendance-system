# -*- coding: utf-8 -*-
"""استعادة قاعدة البيانات من نسخة احتياطية.
الاستخدام:  python tools/restore_backup.py            ← يعرض النسخ المتوفرة
           python tools/restore_backup.py attendance_20261101.sqlite
أوقف الخادم قبل الاستعادة. تُحفظ القاعدة الحالية باسم attendance.before_restore.sqlite أولاً."""
import os, shutil, sqlite3, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))
import config

bdir = os.path.join(config.DATA, "backups")
files = sorted(f for f in os.listdir(bdir)) if os.path.isdir(bdir) else []
if len(sys.argv) < 2:
    print("النسخ المتوفرة في", bdir)
    for f in files:
        print("  ", f, round(os.path.getsize(os.path.join(bdir, f)) / 1024), "KB")
    sys.exit(0)
src = os.path.join(bdir, os.path.basename(sys.argv[1]))
if not os.path.exists(src):
    sys.exit("النسخة غير موجودة: " + src)
chk = sqlite3.connect(src).execute("PRAGMA integrity_check").fetchone()[0]
if chk != "ok":
    sys.exit("النسخة تالفة: " + chk)
if os.path.exists(config.DB_PATH):
    shutil.copy2(config.DB_PATH, config.DB_PATH + ".before_restore")
for ext in ("-wal", "-shm"):
    if os.path.exists(config.DB_PATH + ext):
        os.remove(config.DB_PATH + ext)
shutil.copy2(src, config.DB_PATH)
print("تمت الاستعادة من", os.path.basename(src), "— شغّل الخادم الآن.")
