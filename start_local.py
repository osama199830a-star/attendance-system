# -*- coding: utf-8 -*-
"""تشغيل محلي بنقرة واحدة: يشغّل الخادم ويفتح موقع الدكتور في المتصفح (نفس الواجهات تماماً)."""
import os, sys, threading, time, urllib.request, webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "server"))
URL = "http://127.0.0.1:5000/station/"


def healthy():
    try:
        urllib.request.urlopen("http://127.0.0.1:5000/api/health", timeout=1.5)
        return True
    except Exception:
        return False


def main():
    if not healthy():
        import runner
        runner.serve_local()
        for _ in range(150):
            if healthy():
                break
            time.sleep(0.1)
        else:
            print("تعذّر تشغيل الخادم (هل المنفذ 5000 مشغول؟)"); input(); return
    print("نظام الحضور يعمل — لوحة الدكتور:", URL)
    print("لوحة المسؤول: http://127.0.0.1:5000/admin/   (أغلق هذه النافذة لإيقاف البرنامج)")
    if not os.environ.get("ATT_NO_BROWSER"):
        webbrowser.open(URL)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
