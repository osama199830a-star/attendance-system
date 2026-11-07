# -*- coding: utf-8 -*-
"""اختبار واجهة الدكتور في متصفح حقيقي: بدء المحاضرة، تغيّر الباركود كل 3 ثوانٍ، عدّاد الحضور، التصدير."""
import json, os, subprocess, sys, tempfile, time, urllib.request, http.cookiejar
HERE = os.path.dirname(os.path.abspath(__file__)); SRV = os.path.join(os.path.dirname(HERE), "server")
tmp = tempfile.mkdtemp(); os.environ["ATT_DATA"] = tmp; sys.path.insert(0, SRV)
PORT = 15077; BASE = "http://127.0.0.1:%d" % PORT
env = dict(os.environ, PORT=str(PORT), ADMIN_USER="admin", ADMIN_PASS="admin123", COOKIE_SECURE="0")
srv = subprocess.Popen([sys.executable, os.path.join(SRV, "runner.py")], env=env, cwd=SRV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
for _ in range(60):
    try: urllib.request.urlopen(BASE + "/api/health", timeout=1); break
    except Exception: time.sleep(.2)
OUT = os.environ.get("SHOTS", "/tmp/station"); os.makedirs(OUT, exist_ok=True)
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
    call("POST", "/api/admin/settings".replace("/settings", "/settings"), None) if False else None
    for nm, em in (("الفيزياء الطبية", "dr.physics@uoa.edu.iq"), ("اللغة الإنكليزية", "dr.eng@uoa.edu.iq"), ("الحاسوب", "")):
        call("POST", "/api/admin/courses", {"name": nm, "doctor_email": em})
    for i, nm in enumerate(["محمد علي حسن", "محمد أحمد كاظم", "زينب حسين علي", "علي جاسم عباس"]):
        call("POST", "/api/admin/students", {"name": nm, "grp": "AB"[i % 2]})
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(); pg = b.new_page(viewport={"width": 1280, "height": 760}); errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(BASE + "/station/"); pg.wait_for_timeout(1200)
        opts = pg.eval_on_selector_all("#course option", "o=>o.map(x=>x.textContent)")
        check("المواد تظهر في القائمة المنسدلة", len(opts) == 4, opts)
        check("لا يوجد حقل اسم الدكتور ولا القاعة", pg.locator("text=اسم الدكتور").count() == 0 and pg.locator("text=القاعة").count() == 0)
        check("العنوان يُملأ تلقائياً", pg.input_value("#addr").startswith("https://"))
        pg.screenshot(path=OUT + "/1_idle.png")
        call("POST", "/api/station/config", {"cloud_url": "https://att.example.org"}); pg.wait_for_timeout(300); pg.reload(); pg.wait_for_timeout(1200)
        pg.select_option("#course", label="الفيزياء الطبية"); pg.click("#start"); pg.wait_for_timeout(1200)
        src1 = pg.get_attribute("#bigqr", "src"); pg.wait_for_timeout(3300); src2 = pg.get_attribute("#bigqr", "src")
        check("الباركود يتغير بعد 3 ثوانٍ", src1 != src2)
        import urllib.parse as _u
        check("الباركود يحمل الرابط العام (سحابة) تلقائياً", _u.unquote(src2).split("d=")[1].startswith("https://att.example.org/s/#AT1."), _u.unquote(src2)[:120])
        check("زر البدء معطّل أثناء المحاضرة", pg.is_disabled("#start") and not pg.is_disabled("#end"))
        txt = pg.inner_text("#line1"); check("المتبقي + رمز المحاضرة", "المتبقي" in txt and "رمز المحاضرة" in txt, txt)
        # طالب يسجّل
        roster = json.loads(urllib.request.urlopen(BASE + "/api/student/roster").read())["students"]
        info = call("GET", "/api/station/info")
        import re, urllib.parse
        qurl = urllib.parse.unquote(src2.split("d=")[1]); frag = qurl.split("#")[1]
        m = re.match(r"AT1\.(\w+)\.(\d+)\.(\d+)\.(\w+)", frag)
        res = call("POST", "/api/student/submit", {"device_id": "devA", "items": [{"id": "1", "code": m[1], "t": int(m[2]), "i": int(m[3]), "sig": m[4], "student": roster[0]["u"], "age": 1.0, "elapsed": 1.0, "queued": False}]})
        check("تسجيل طالب بالباركود الحي", res["results"][0]["status"] == "ok", res)
        pg.wait_for_timeout(1000); check("عدّاد الحاضرين = ١", "١" in pg.inner_text("#line2"), pg.inner_text("#line2"))
        pg.screenshot(path=OUT + "/2_running.png")
        pg.reload(); pg.wait_for_timeout(1800)
        check("إعادة فتح البرنامج أثناء محاضرة جارية تكمل نفس المحاضرة", not pg.is_disabled("#end") and "رمز المحاضرة" in pg.inner_text("#line1") and "١" in pg.inner_text("#line2"), pg.inner_text("#line1"))
        pg.once("dialog", lambda d: d.accept()); pg.click("#end"); pg.wait_for_timeout(1000)
        check("بعد الإنهاء: زر البدء يعمل", not pg.is_disabled("#start"))
        pg.screenshot(path=OUT + "/3_done.png")
        pg.click("#export"); pg.wait_for_timeout(1800)
        mt = pg.inner_text("#mbox"); check("التصدير يعمل ويُجدول الإيميل (أوفلاين)", "تم التصدير" in mt and ("بالإيميل" in mt or "بانتظار" in mt or "لا يوجد إنترنت" in mt), mt)
        pg.screenshot(path=OUT + "/4_export.png"); pg.click("#cl")
        pg.click("#unbind"); pg.wait_for_timeout(600); check("نافذة فك الربط تعرض الطالب المرتبط", "فك الربط" in pg.inner_text("#mbox") and roster[0]["n"] in pg.inner_text("#mbox"), pg.inner_text("#mbox")); pg.screenshot(path=OUT + "/5_unbind.png"); pg.click("#cl")
        check("لا أخطاء جافاسكربت", not errs, errs)
        # الصفحة ممنوعة من الشبكة الخارجية؟ (الاختبار من loopback فقط)
        b.close()
    print("\nنجح %d — فشل %d" % (OK, FAIL))
finally:
    srv.terminate()
sys.exit(1 if FAIL else 0)
