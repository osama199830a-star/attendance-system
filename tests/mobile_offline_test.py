# -*- coding: utf-8 -*-
"""سيناريو الطالب الكامل من كاميرا الهاتف: يفتح الرابط (hash) → أوفلاين يحفظ → عند الاتصال يُرسل → Excel «حاضر»."""
import json, os, subprocess, sys, tempfile, time, urllib.request, http.cookiejar, io
SRV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"); tmp = tempfile.mkdtemp(); BASE = "http://127.0.0.1:5000"
env = dict(os.environ, ATT_DATA=tmp, ADMIN_USER="admin", ADMIN_PASS="admin123", COOKIE_SECURE="0"); env.pop("PORT", None)
srv = subprocess.Popen([sys.executable, os.path.join(SRV, "runner.py")], env=env, cwd=SRV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
for _ in range(80):
    try: urllib.request.urlopen(BASE + "/api/health", timeout=1); break
    except Exception: time.sleep(.25)
OK = FAIL = 0
def check(n, c, x=""):
    global OK, FAIL
    if c: OK += 1; print("  ✓", n)
    else: FAIL += 1; print("  ✗", n, x)
jar = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
def call(m, p, d=None):
    r = urllib.request.Request(BASE + p, data=json.dumps(d).encode() if d is not None else None, method=m, headers={"Content-Type": "application/json"})
    return json.loads(op.open(r).read().decode())
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import core_frag
try:
    call("POST", "/api/admin/login", {"username": "admin", "password": "admin123"})
    cid = call("POST", "/api/admin/courses", {"name": "فيزياء", "doctor_email": "d@e.com"})["uid"]
    from openpyxl import Workbook, load_workbook
    wb = Workbook(); w = wb.active; w.append(["اسم الطالب", "الكروب"])
    for nm in ["ابرار خضير عباس", "زينب علي حسن", "سارة محمد علي"]: w.append([nm, "A"])
    bio = io.BytesIO(); wb.save(bio); bnd = "xx"
    body = ("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"s.xlsx\"\r\n\r\n" % bnd).encode() + bio.getvalue() + ("\r\n--%s--\r\n" % bnd).encode()
    op.open(urllib.request.Request(BASE + "/api/admin/students/upload", data=body, method="POST", headers={"Content-Type": "multipart/form-data; boundary=" + bnd}))
    lec = call("POST", "/api/station/lecture/start", {"course_uid": cid, "duration_sec": 600})["lecture"]
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        def student(name):
            ctx = b.new_context(viewport={"width": 393, "height": 800}, is_mobile=True, has_touch=True, locale="ar-IQ"); pg = ctx.new_page(); errs = []
            pg.on("pageerror", lambda e: errs.append(str(e))); return ctx, pg, errs
        # طالب 1: أونلاين كامل
        c1, p1, e1 = student("a"); p1.goto(BASE + "/s/"); p1.wait_for_selector("#q")
        p1.fill("#q", "ابرار"); p1.wait_for_selector("#res .item[data-u]"); p1.click("#res .item[data-u]"); p1.click("#yes"); p1.wait_for_selector(".pill.ok")
        p1.goto(BASE + "/s/#" + core_frag.frag(lec)); p1.wait_for_selector("#go:not([disabled])", timeout=6000); p1.click("#go"); p1.wait_for_selector(".res.ok", timeout=6000)
        check("1) أونلاين: يسجّل فوراً", "تم تسجيل" in p1.inner_text(".res"))
        # طالب 2: يفتح التطبيق أونلاين مرة، ثم يقطع الشبكة (أوفلاين تام)
        c2, p2, e2 = student("b"); p2.goto(BASE + "/s/"); p2.wait_for_selector("#q")
        p2.fill("#q", "زينب"); p2.wait_for_selector("#res .item[data-u]"); p2.click("#res .item[data-u]"); p2.click("#yes"); p2.wait_for_selector(".pill.ok")
        p2.wait_for_selector("text=جاهز للتسجيل بدون إنترنت", timeout=8000)
        c2.set_offline(True)
        p2.goto(BASE + "/s/#" + core_frag.frag(lec))   # يفتح الصفحة من كاش Service Worker بلا شبكة
        p2.wait_for_selector("#go:not([disabled])", timeout=8000); p2.click("#go")
        p2.wait_for_selector(".res.wait", timeout=6000)
        check("2) أوفلاين: الصفحة فُتحت من الكاش وحُفظ الحضور على الهاتف", "حُفظ حضورك" in p2.inner_text(".res"))
        check("2) الخادم لم يستلمه بعد", call("GET", "/api/station/lecture/%s/status" % lec["uid"])["count"] == 1)
        c2.set_offline(False); p2.evaluate("window.dispatchEvent(new Event('online'))")
        for _ in range(40):
            if call("GET", "/api/station/lecture/%s/status" % lec["uid"])["count"] == 2: break
            time.sleep(.5)
        check("3) عند عودة الإنترنت أُرسل تلقائياً", call("GET", "/api/station/lecture/%s/status" % lec["uid"])["count"] == 2)
        check("3) لا أخطاء JS", not (e1 or e2), (e1, e2))
        b.close()
    r = op.open(BASE + "/api/admin/export?course_uid=" + cid).read()
    ws = load_workbook(io.BytesIO(r)).active
    rows = {str(x[1].value): [c.value for c in x] for x in ws.iter_rows(min_row=1) if x[1].value}
    def st(prefix):
        for k, v in rows.items():
            if k.startswith(prefix): return v[3]
    check("4) Excel: ابرار (أونلاين) = حاضر", st("ابرار") == "حاضر", st("ابرار"))
    check("4) Excel: زينب (أوفلاين ثم أُرسل) = حاضر", st("زينب") == "حاضر", st("زينب"))
    check("4) Excel: سارة (لم تسجّل) = غائب", st("سارة") == "غائب", st("سارة"))
finally:
    srv.terminate(); print("نجح %d — فشل %d" % (OK, FAIL))
