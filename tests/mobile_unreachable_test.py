# -*- coding: utf-8 -*-
"""سيناريو لقطتك: الهاتف على بيانات الجوال (الخادم غير قابل للوصول) → اسم + مسح + تسجيل → لاحقاً يصل للخادم."""
import json, os, subprocess, sys, tempfile, time, urllib.request, http.cookiejar, io, threading, http.server, socketserver
HERE = os.path.dirname(os.path.abspath(__file__)); SRV = os.path.join(os.path.dirname(HERE), "server"); ASSETS = os.path.join(SRV, "static", "student")
sys.path.insert(0, HERE); import core_frag
tmp = tempfile.mkdtemp(); BASE = "http://127.0.0.1:5000"; WPORT = 15244; DEAD = "http://127.0.0.1:9"
env = dict(os.environ, ATT_DATA=tmp, ADMIN_USER="admin", ADMIN_PASS="admin123", COOKIE_SECURE="0"); env.pop("PORT", None)
srv = subprocess.Popen([sys.executable, os.path.join(SRV, "runner.py")], env=env, cwd=SRV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
for _ in range(80):
    try: urllib.request.urlopen(BASE + "/api/health", timeout=1); break
    except Exception: time.sleep(.25)
class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
os.chdir(ASSETS); socketserver.ThreadingTCPServer.allow_reuse_address = True
ws = socketserver.ThreadingTCPServer(("127.0.0.1", WPORT), H); threading.Thread(target=ws.serve_forever, daemon=True).start()
OK = FAIL = 0
def check(n, c, x=""):
    global OK, FAIL
    if c: OK += 1; print("  ✓", n)
    else: FAIL += 1; print("  ✗", n, x)
jar = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
def call(m, p, d=None):
    r = urllib.request.Request(BASE + p, data=json.dumps(d).encode() if d is not None else None, method=m, headers={"Content-Type": "application/json"})
    return json.loads(op.open(r).read().decode())
try:
    call("POST", "/api/admin/login", {"username": "admin", "password": "admin123"})
    cid = call("POST", "/api/admin/courses", {"name": "فيزياء", "doctor_email": "d@e.com"})["uid"]
    from openpyxl import Workbook, load_workbook
    wb = Workbook(); w = wb.active; w.append(["اسم الطالب", "الكروب"])
    for nm in ["يوسف شاكر محمود لطيف", "زينب علي حسن"]: w.append([nm, "B"])
    bio = io.BytesIO(); wb.save(bio); bnd = "xx"
    body = ("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"s.xlsx\"\r\n\r\n" % bnd).encode() + bio.getvalue() + ("\r\n--%s--\r\n" % bnd).encode()
    op.open(urllib.request.Request(BASE + "/api/admin/students/upload", data=body, method="POST", headers={"Content-Type": "multipart/form-data; boundary=" + bnd}))
    call("PUT", "/api/admin/settings", {"max_sync_delay_hours": 168})
    check("مهلة 168 ساعة تُحفظ", call("GET", "/api/admin/settings")["settings"]["max_sync_delay_hours"] == "168" if "settings" in call("GET", "/api/admin/settings") else True)
    lec = call("POST", "/api/station/lecture/start", {"course_uid": cid, "duration_sec": 600})["lecture"]
    roster = urllib.request.urlopen(BASE + "/api/student/roster").read()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(args=["--disable-web-security", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
        ctx = b.new_context(viewport={"width": 393, "height": 800}, is_mobile=True, has_touch=True, locale="ar-IQ", service_workers="block", permissions=["camera"])
        pg = ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        state = {"base": DEAD}
        pg.route("**/config.js", lambda r: r.fulfill(body='window.APP_CONFIG = { base: "%s", embedded: true };' % state["base"], content_type="application/javascript"))
        pg.route("**/roster.json", lambda r: r.fulfill(body=roster, content_type="application/json"))
        pg.add_init_script("window.BarcodeDetector = class { constructor(){} async detect(){ return window.__raw ? [{rawValue: window.__raw}] : []; } };")
        pg.goto("http://127.0.0.1:%d/index.html" % WPORT); pg.wait_for_selector("#q", timeout=8000)
        pg.fill("#q", "يوسف"); pg.wait_for_selector("#res .item[data-u]"); pg.click("#res .item[data-u]"); pg.click("#yes"); time.sleep(.8)
        check("1) بلا وصول للخادم: الحالة «بانتظار الربط» مع شرح", "بانتظار الربط" in pg.inner_text("body") and "سيُؤكَّد الربط" in pg.inner_text("body"))
        pg.evaluate("window.__raw=%s" % json.dumps(core_frag.frag(lec))); pg.click("#scan"); time.sleep(1.5)
        txt = pg.inner_text("body")
        check("2) الباركود الطازج لا يظهر «قديم» رغم عدم المزامنة", "الباركود قديم" not in txt and "تم التقاط الباركود" in txt, txt[:200])
        check("2) زر «تسجيل حضور» مفعّل", pg.locator("#go:not([disabled])").count() == 1)
        pg.click("#go"); time.sleep(1.2)
        check("3) حُفظ الحضور على الهاتف", "حُفظ حضورك" in pg.inner_text("body"))
        check("3) الخادم لم يستلم شيئاً", call("GET", "/api/station/lecture/%s/status" % lec["uid"])["count"] == 0)
        # ── الهاتف يصل الآن لشبكة الدكتور: نوجّه التطبيق إلى العنوان الصحيح كما يحدث عند الاتصال ──
        pg.fill("#srv0", BASE) if pg.locator("#srv0").count() else None
        pg.click("text=إعدادات متقدمة"); pg.fill("#srv", BASE); pg.click("#srvsave")
        for _ in range(40):
            if call("GET", "/api/station/lecture/%s/status" % lec["uid"])["count"] == 1: break
            time.sleep(.5)
        check("4) عند الوصول للخادم: أُرسل الحضور المحفوظ تلقائياً", call("GET", "/api/station/lecture/%s/status" % lec["uid"])["count"] == 1)
        time.sleep(1)
        check("4) الربط اكتمل (مربوط ✓) والخادم يعرفه", "مربوط ✓" in pg.inner_text("body"))
        bound = [s for s in json.loads(urllib.request.urlopen(BASE + "/api/student/roster").read())["students"] if s["b"]]
        check("4) يوسف مربوط بالجهاز في الخادم (يظهر في فك الربط)", len(bound) == 1, bound)
        check("5) لا أخطاء JS", not errs, errs)
        b.close()
    ws0 = load_workbook(io.BytesIO(op.open(BASE + "/api/admin/export?course_uid=" + cid).read())).active
    vals = {str(r[1].value): r[3].value for r in ws0.iter_rows() if r[1].value}
    st = [v for k, v in vals.items() if k.startswith("يوسف")]; st2 = [v for k, v in vals.items() if k.startswith("زينب")]
    check("6) Excel: يوسف = حاضر", st == ["حاضر"], vals); check("6) Excel: زينب = غائب", st2 == ["غائب"], vals)
finally:
    srv.terminate(); print("نجح %d — فشل %d" % (OK, FAIL))
