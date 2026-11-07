# -*- coding: utf-8 -*-
"""إعدادات المسارات والمفاتيح. تُحفظ بيانات البرنامج خارج مجلد التثبيت حتى لا تضيع عند التحديث."""
import json, os, secrets, sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(getattr(sys, "_MEIPASS", APP_DIR), "static") if getattr(sys, "frozen", False) else os.path.join(APP_DIR, "static")


def data_dir():
    d = os.environ.get("ATT_DATA")
    if not d:
        d = os.path.join(os.path.expanduser("~"), "AttendanceData") if getattr(sys, "frozen", False) else os.path.join(os.path.dirname(APP_DIR), "data")
    os.makedirs(d, exist_ok=True)
    return d


DATA = data_dir()
DB_PATH = os.path.join(DATA, "attendance.sqlite")
EXPORT_DIR = os.path.join(DATA, "exports")
CERT_DIR = os.path.join(DATA, "certs")
CONF_PATH = os.path.join(DATA, "config.json")
os.makedirs(EXPORT_DIR, exist_ok=True)

MODE = os.environ.get("ATT_MODE", "local")  # local = جهاز الدكتور | cloud = الخادم السحابي


def load_conf():
    c = {}
    if os.path.exists(CONF_PATH):
        try:
            with open(CONF_PATH, encoding="utf-8") as f:
                c = json.load(f)
        except Exception:
            c = {}
    changed = False
    for k, v in (("station_key", secrets.token_hex(16)), ("session_secret", secrets.token_hex(32)),
                 ("sync_key", ""), ("cloud_url", ""), ("station_name", "قاعة"), ("doctor_email", "")):
        if k not in c:
            c[k] = v
            changed = True
    # متغيرات البيئة تغلب الملف (مناسبة للسحابة)
    for env, k in (("SYNC_KEY", "sync_key"), ("CLOUD_URL", "cloud_url"), ("SESSION_SECRET", "session_secret"),
                   ("STATION_KEY", "station_key")):
        if os.environ.get(env):
            c[k] = os.environ[env]
    if changed:
        save_conf(c)
    return c


def save_conf(c):
    with open(CONF_PATH, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=2)
