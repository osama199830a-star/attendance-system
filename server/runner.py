# -*- coding: utf-8 -*-
"""تشغيل الخادم: HTTP للتحكم المحلي + HTTPS للطلاب (شهادة ذاتية) أو خلف وكيل في السحابة."""
import os, ssl, threading
from werkzeug.serving import make_server
import app as A, certs, config
import logging, sys

# النسخة المثبّتة (بدون نافذة أوامر) ليس لها stdout؛ نكتب السجل في ملف ونُسكِت سجلات الطلبات حتى لا تبطئ الخادم
if sys.stdout is None or sys.stderr is None:
    _f = open(os.path.join(config.DATA, "server.log"), "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or _f
    sys.stderr = sys.stderr or _f
logging.getLogger("werkzeug").setLevel(logging.ERROR)


def serve_local(http_port=5000, https_port=5443):
    application = A.get_app()
    s1 = make_server("0.0.0.0", http_port, application, threaded=True)
    threading.Thread(target=s1.serve_forever, daemon=True).start()   # HTTP يعمل فوراً (واجهة الدكتور والمسؤول)
    servers = [s1]

    def https():   # الشهادة والمنفذ الآمن في الخلفية حتى لا يتأخر فتح البرنامج
        try:
            crt, key = certs.ensure_cert()
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(crt, key)
            s2 = make_server("0.0.0.0", https_port, application, threaded=True, ssl_context=ctx)
            servers.append(s2)
            s2.serve_forever()
        except Exception as e:
            print("تحذير: تعذّر تشغيل HTTPS:", e)
    threading.Thread(target=https, daemon=True).start()
    threading.Timer(3.0, A.start_workers).start()   # المزامنة والنسخ الاحتياطي بعد اكتمال الفتح
    return servers


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "0"))
    if port or config.MODE == "cloud":  # سحابة: منفذ واحد خلف HTTPS الخاص بالمنصة
        A.get_app().run("0.0.0.0", port or 8000, threaded=True)
    else:
        serve_local()
        print("الخادم يعمل — لوحة المسؤول: http://127.0.0.1:5000/admin/")
        threading.Event().wait()
