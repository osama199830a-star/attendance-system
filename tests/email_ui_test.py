# -*- coding: utf-8 -*-
"""واجهة الطالب الجديدة: رقم جامعي فقط → يظهر القسم والمرحلة والكروب، ثم حضور بالباركود."""
import io, json, os, subprocess, sys, tempfile, time, urllib.request, http.cookiejar
SRV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server")
tmp = tempfile.mkdtemp(); BASE = "http://127.0.0.1:5000"
env = dict(os.environ, ATT_DATA=tmp, ADMIN_USER="admin", ADMIN_PASS="admin123", COOKIE_SECURE="0"); env.pop("PORT", None); env.pop("ATT_STUDENT_LOGIN", None)
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
    col = call("POST", "/api/admin/colleges", {"name": "كلية التقنيات الهندسية"}); 
    col_uid = col.get("uid") or call("GET", "/api/admin/org")["colleges"][0]["uid"]
    dep = call("POST", "/api/admin/departments", {"college_uid": col_uid, "name": "هندسة تقنيات الحاسوب", "stages": 4}); dep_uid = dep.get("uid")
    if not dep_uid: dep_uid = [d for d in call("GET", "/api/admin/org")["departments"]][0]["uid"]
    cid = call("POST", "/api/admin/courses", {"name": "شبكات", "doctor_email": "d@e.com", "dept_uid": dep_uid, "stage": 3})["uid"]
    from openpyxl import Workbook
    wb = Workbook(); w = wb.active
    for n in (1063004760, 1063004761): w.append([n])
    bio = io.BytesIO(); wb.save(bio); bnd = "xx"
    fields = "".join('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (bnd, k, v) for k, v in (("dept_uid", dep_uid), ("stage", "3"), ("kind", "theory")))
    body = fields.encode() + ('--%s\r\nContent-Disposition: form-data; name="file"; filename="s.xlsx"\r\n\r\n' % bnd).encode() + bio.getvalue() + ("\r\n--%s--\r\n" % bnd).encode()
    r = json.loads(op.open(urllib.request.Request(BASE + "/api/admin/students/upload", data=body, method="POST", headers={"Content-Type": "multipart/form-data; boundary=" + bnd})).read())
    check("رفع الأرقام فقط", r["ok"] and r["emails"] == 2, r)
    lec = call("POST", "/api/station/lecture/start", {"course_uid": cid})["lecture"]
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(); ctx = b.new_context(viewport={"width": 393, "height": 800}, is_mobile=True, locale="ar-IQ", service_workers="block")
        pg = ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(BASE + "/s/"); pg.wait_for_selector("#em", timeout=8000)
        check("شاشة الدخول: حقل واحد فقط (لا قوائم ولا بحث)", pg.locator("select").count() == 0 and pg.locator("#q").count() == 0)
        pg.fill("#em", "1063004760"); pg.click("#emgo")
        pg.wait_for_selector(".me", timeout=8000)
        txt = pg.inner_text("#app")
        check("يظهر القسم والمرحلة تلقائياً", "هندسة تقنيات الحاسوب" in txt and "المرحلة 3" in txt and "1063004760" in txt, txt[:200])
        pg.goto(BASE + "/s/#" + core_frag.frag(lec)); pg.wait_for_selector("#go:not([disabled])", timeout=8000); pg.click("#go"); pg.wait_for_selector(".res.ok", timeout=8000)
        check("تسجيل الحضور بنقرة واحدة بعد الدخول", True)
        pg.reload(); pg.wait_for_selector(".me", timeout=8000)
        check("بعد إعادة فتح الصفحة يبقى مسجّلاً", "1063004760" in pg.inner_text("#app"))
        check("لا أخطاء JS", not errs, errs)
        # ── الدخول من أي شبكة: الصفحة محمَّلة لكن خادم الدكتور غير قابل للوصول ──
        ctx2 = b.new_context(viewport={"width": 393, "height": 800}, is_mobile=True, locale="ar-IQ", service_workers="block")
        ctx2.route("https://www.gstatic.com/**", lambda r: r.fulfill(status=204, body=""))
        pg2 = ctx2.new_page(); errs2 = []; pg2.on("pageerror", lambda e: errs2.append(str(e)))
        pg2.goto(BASE + "/s/?m=doc%40gmail.com"); pg2.wait_for_selector("#em")
        ctx2.route("**/api/**", lambda r: r.abort())
        pg2.fill("#em", "1063004761"); pg2.click("#emgo"); pg2.wait_for_selector(".me", timeout=8000)
        check("الدخول يعمل حتى لو خادم الدكتور غير قابل للوصول (أي شبكة)", "1063004761" in pg2.inner_text("#app"))
        pg2.goto(BASE + "/s/?m=doc%40gmail.com#" + core_frag.frag(lec)); pg2.wait_for_selector("#go:not([disabled])", timeout=8000)
        pg2.click("#go"); pg2.wait_for_selector(".res", timeout=8000)
        check("زر واحد يحفظ ويجهّز رسالة البريد (بريد الدكتور جاء من رابط الباركود)", "اضغط «إرسال»" in pg2.inner_text(".res"), pg2.inner_text(".res"))
        check("لا أخطاء JS (الدخول المحلي)", not [e for e in errs2], errs2)
        b.close()
    call("PUT", "/api/admin/settings", {"public_url": "https://hadir.example.app", "attendance_mailbox": "doc@gmail.com", "relay_url": "https://hadir.example.app/.netlify/functions/attend"})
    q = call("GET", "/api/station/lecture/%s/qr?mode=public" % lec["uid"])
    check("باركود الرابط العام يحمل بريد الاستلام ورابط الإرسال", q["url"].startswith("https://hadir.example.app/s/?m=doc%40gmail.com&r=") and "#AT1." in q["url"], q["url"])
finally:
    srv.terminate()
print("\nنجح %d — فشل %d" % (OK, FAIL)); sys.exit(1 if FAIL else 0)
