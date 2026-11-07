# -*- coding: utf-8 -*-
"""برنامج الدكتور (Windows): يشغّل الخادم المحلي المدمج ثم يفتح واجهة المحطة في نافذة مستقلة.
يعمل بدون إنترنت. عند توفر الإنترنت يزامن الحضور مع السحابة ويرسل إيميلات Excel المعلّقة."""
import os, subprocess, sys, threading, time, urllib.request, webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "server"))

URL = "http://127.0.0.1:5000/station/"
TITLE = "نظام الحضور بالباركود - جامعة المعارف"


def healthy():
    try:
        urllib.request.urlopen("http://127.0.0.1:5000/api/health", timeout=1.5)
        return True
    except Exception:
        return False


def start_server():
    if healthy():          # نسخة أخرى تعمل أصلاً → نكتفي بفتح النافذة
        return
    import runner
    runner.serve_local()
    for _ in range(100):
        if healthy():
            return
        time.sleep(0.1)


class Api:
    def __init__(self):
        self.window = None
        self.full = False

    def fullscreen(self):
        if self.window:
            self.window.toggle_fullscreen()


def edge_app_mode():
    """بديل إن لم يتوفر WebView2: نافذة تطبيق من Edge/Chrome."""
    for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"):
        if os.path.exists(p):
            prof = os.path.join(os.path.expanduser("~"), "AttendanceData", "browser-profile")
            subprocess.Popen([p, "--app=" + URL, "--user-data-dir=" + prof, "--start-maximized"])
            return True
    return False


def selftest():
    """فحص آلي بعد البناء: يشغّل الخادم ويطلب الصفحات الأساسية ثم يخرج (0 = سليم)."""
    start_server()
    for path in ("/api/health", "/station/", "/admin/", "/s/", "/api/station/net"):
        urllib.request.urlopen("http://127.0.0.1:5000" + path, timeout=10).read()
    import webview  # noqa: F401  (يتأكد أن مكتبة النافذة مضمّنة)
    return 0


def main():
    if "--selftest" in sys.argv:
        try:
            code, msg = selftest(), "SELFTEST OK"
        except Exception as e:
            code, msg = 1, "SELFTEST FAILED: " + repr(e)
        import config   # النسخة المبنية بلا نافذة أوامر: النتيجة تُكتب في ملف
        with open(os.path.join(config.DATA, "selftest.txt"), "w", encoding="utf-8") as f:
            f.write(msg)
        os._exit(code)
    try:
        import webview
        api = Api()
        loading = ("<html dir='rtl'><body style='margin:0;display:flex;align-items:center;justify-content:center;height:100vh;"
                   "font-family:Segoe UI,Tahoma,sans-serif;background:#2c5599;color:#fff;font-size:26px'>"
                   "<div style='text-align:center'>جاري تشغيل نظام الحضور…<div style='font-size:15px;opacity:.8;margin-top:10px'>لحظات</div></div></body></html>")
        api.window = webview.create_window(TITLE, html=loading, width=1280, height=760, min_size=(900, 600), js_api=api)

        def boot():      # النافذة تظهر فوراً، والخادم يبدأ في الخلفية فلا يظهر «لا يستجيب»
            try:
                start_server()
                for _ in range(100):
                    if healthy():
                        break
                    time.sleep(0.1)
                api.window.load_url(URL)
            except Exception:
                pass
        webview.start(boot)
    except Exception:
        start_server()
        if not edge_app_mode():
            webbrowser.open(URL)
        threading.Event().wait()      # يبقى الخادم شغالاً ما دامت النافذة مفتوحة في وضع المتصفح


if __name__ == "__main__":
    main()
