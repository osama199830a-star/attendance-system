# -*- coding: utf-8 -*-
import re, sqlite3, time, uuid, hashlib, unicodedata
from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY, username TEXT UNIQUE, pw_hash TEXT, must_change INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS courses(uid TEXT PRIMARY KEY, name TEXT, doctor_email TEXT, duration_sec INTEGER DEFAULT 0,
  deleted INTEGER DEFAULT 0, updated_at REAL, rev INTEGER DEFAULT 0, dirty INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS students(uid TEXT PRIMARY KEY, name TEXT, name_norm TEXT, grp TEXT, device_id TEXT,
  bound_at REAL, bind_epoch INTEGER DEFAULT 0, deleted INTEGER DEFAULT 0, updated_at REAL, rev INTEGER DEFAULT 0, dirty INTEGER DEFAULT 1);
CREATE INDEX IF NOT EXISTS ix_students_dev ON students(device_id);
CREATE TABLE IF NOT EXISTS lectures(uid TEXT PRIMARY KEY, code TEXT UNIQUE, course_uid TEXT, secret TEXT, start_ts REAL,
  end_ts REAL, interval_sec INTEGER, status TEXT, station TEXT, updated_at REAL, rev INTEGER DEFAULT 0, dirty INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS attendance(lecture_uid TEXT, student_uid TEXT, device_id TEXT, code TEXT, t REAL, slot_i INTEGER,
  sig TEXT, age REAL, queued INTEGER, status TEXT, reason TEXT, created_at REAL, updated_at REAL, rev INTEGER DEFAULT 0,
  dirty INTEGER DEFAULT 1, PRIMARY KEY(lecture_uid, student_uid));
CREATE INDEX IF NOT EXISTS ix_att_lec ON attendance(lecture_uid, status);
CREATE INDEX IF NOT EXISTS ix_att_status ON attendance(status);
CREATE INDEX IF NOT EXISTS ix_att_rev ON attendance(rev);
CREATE INDEX IF NOT EXISTS ix_att_dirty ON attendance(dirty);
CREATE INDEX IF NOT EXISTS ix_stu_rev ON students(rev);
CREATE INDEX IF NOT EXISTS ix_stu_del ON students(deleted, name_norm);
CREATE INDEX IF NOT EXISTS ix_lec_rev ON lectures(rev);
CREATE INDEX IF NOT EXISTS ix_lec_course ON lectures(course_uid, start_ts);
CREATE INDEX IF NOT EXISTS ix_crs_rev ON courses(rev);
CREATE TABLE IF NOT EXISTS colleges(uid TEXT PRIMARY KEY, name TEXT, deleted INTEGER DEFAULT 0, updated_at REAL, rev INTEGER DEFAULT 0, dirty INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS departments(uid TEXT PRIMARY KEY, college_uid TEXT, name TEXT, stages INTEGER DEFAULT 4, deleted INTEGER DEFAULT 0, updated_at REAL, rev INTEGER DEFAULT 0, dirty INTEGER DEFAULT 1);
CREATE INDEX IF NOT EXISTS ix_col_rev ON colleges(rev);
CREATE INDEX IF NOT EXISTS ix_dep_rev ON departments(rev);
CREATE TABLE IF NOT EXISTS auto_exports(lecture_uid TEXT PRIMARY KEY, at REAL);
CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY AUTOINCREMENT, to_addrs TEXT, cc TEXT, subject TEXT, body TEXT,
  attach_path TEXT, created_at REAL, sent_at REAL, tries INTEGER DEFAULT 0, last_error TEXT);
"""

DEFAULTS = {
    "org_name": "جامعة المعارف",
    "qr_interval": "3",          # كل كم ثانية يتغير الباركود (يحددها المسؤول)
    "scan_grace": "10",          # مهلة فتح الرابط بعد مسح الباركود (ثواني)
    "default_duration": "900",   # مدة المحاضرة الافتراضية (ثانية)
    "max_sync_delay_hours": "48",# أقصى تأخير مسموح لإرسال حضور غير متصل
    "allow_offline_scan": "1",   # قبول حضور الطلاب غير المتصلين
    "admin_email": "", "mail_doctor": "1", "auto_export": "0", "absence_limit": "25",
    "smtp_host": "smtp.gmail.com", "smtp_port": "465", "smtp_user": "", "smtp_pass": "",
}
SYNC_SETTINGS = ["org_name", "qr_interval", "scan_grace", "default_duration", "max_sync_delay_hours",
                 "allow_offline_scan", "admin_email", "mail_doctor", "absence_limit"]  # لا تُزامَن كلمات مرور البريد إلى أجهزة الدكاترة


import extras as _X
DEFAULTS.update(_X.EXTRA_DEFAULTS)
SYNC_SETTINGS.extend(k for k in _X.EXTRA_SYNC_SETTINGS if k not in SYNC_SETTINGS)


def connect():
    c = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    return c


def init():
    c = connect()
    c.executescript(SCHEMA)
    for col, ddl in (("role", "TEXT DEFAULT 'admin'"), ("email", "TEXT")):   # حسابات الدكاترة
        try:
            c.execute("ALTER TABLE admins ADD COLUMN %s %s" % (col, ddl))
        except Exception:
            pass
    for tbl, cols in (("admins", (("college_uid", "TEXT"), ("dept_uid", "TEXT"), ("perms", "TEXT DEFAULT ''"), ("can_delegate", "INTEGER DEFAULT 0"), ("parent_id", "INTEGER"), ("full_name", "TEXT"))),
                      ("courses", (("college_uid", "TEXT"), ("dept_uid", "TEXT"), ("stage", "INTEGER DEFAULT 0"), ("kind", "TEXT DEFAULT 'theory'"))),
                      ("students", (("college_uid", "TEXT"), ("dept_uid", "TEXT"), ("stage", "INTEGER DEFAULT 0")))):
        for col, ddl in cols:
            try:
                c.execute("ALTER TABLE %s ADD COLUMN %s %s" % (tbl, col, ddl))
            except Exception:
                pass
    _X.init_schema(c)
    c.execute("CREATE INDEX IF NOT EXISTS ix_stu_coh ON students(dept_uid, stage, deleted)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_crs_coh ON courses(dept_uid, stage)")
    for k, v in DEFAULTS.items():
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
    c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('_rev','0')")
    try:
        set_offset(float((c.execute("SELECT value FROM settings WHERE key='_clock_offset'").fetchone() or ["0"])[0]))
    except Exception:
        pass
    c.close()


def next_rev(c):
    c.execute("UPDATE settings SET value=CAST(value AS INTEGER)+1 WHERE key='_rev'")
    return int(c.execute("SELECT value FROM settings WHERE key='_rev'").fetchone()[0])


def cur_rev(c):
    return int(c.execute("SELECT value FROM settings WHERE key='_rev'").fetchone()[0])


def get_settings(c):
    return {r["key"]: r["value"] for r in c.execute("SELECT key,value FROM settings WHERE key NOT LIKE '\\_%' ESCAPE '\\'")}


def setting(c, k, default=None):
    r = c.execute("SELECT value FROM settings WHERE key=?", (k,)).fetchone()
    return r[0] if r else default


def set_setting(c, k, v):
    c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))


_AR_MAP = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ئ": "ي", "ة": "ه", "ؤ": "و", "ـ": ""})


def norm(s):
    """توحيد الاسم العربي للبحث والمطابقة (نفس الدالة موجودة في واجهة الطالب)."""
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"[ً-ٰٟ]", "", s)
    s = s.translate(_AR_MAP).lower()
    return re.sub(r"\s+", " ", s).strip()


def student_uid(name, grp, cohort=""):
    # معرّف ثابت يُشتق من الاسم والكروب (والقسم/المرحلة) → رفع نفس الملف في أي جهاز لا يكرر الطلاب
    return hashlib.sha1((norm(name) + "|" + norm(grp) + (("|" + cohort) if cohort else "")).encode()).hexdigest()[:16]


def new_uid():
    return uuid.uuid4().hex[:16]


OFFSET = 0.0   # فرق ساعة هذا الجهاز عن ساعة السحابة (يُقاس عند كل مزامنة)


def now():
    """الوقت المصحَّح: ساعة الجهاز + الفرق عن السحابة. كل الباركودات والتواقيت تستخدمه حتى لا تفسدها ساعة جهاز خاطئة."""
    return time.time() + OFFSET


def set_offset(x):
    global OFFSET
    OFFSET = float(x)
