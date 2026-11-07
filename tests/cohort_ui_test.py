# -*- coding: utf-8 -*-
"""واجهة الطالب مع الكليات والأقسام: يختار الكلية ثم القسم ثم المرحلة، ثم يبحث/يختار الكروب ضمن طلاب تلك المرحلة فقط."""
import io, json, os, subprocess, sys, tempfile, time, urllib.request, http.cookiejar
HERE = os.path.dirname(os.path.abspath(__file__)); SRV = os.path.join(os.path.dirname(HERE), "server")
tmp = tempfile.mkdtemp(); os.environ["ATT_DATA"] = tmp; sys.path.insert(0, SRV)
PORT = 15066; BASE = "http://127.0.0.1:%d" % PORT
env = dict(os.environ, PORT=str(PORT), ADMIN_USER="admin", ADMIN_PASS="admin123", COOKIE_SECURE="0")
srv = subprocess.Popen([sys.executable, os.path.join(SRV, "runner.py")], env=env, cwd=SRV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
for _ in range(60):
    try: urllib.request.urlopen(BASE + "/api/health", timeout=1); break
    except Exception: time.sleep(.2)
OK = FAIL = 0
def check(n, c, x=""):
    global OK, FAIL
    if c: OK += 1; print("  ✓", n)
    else: FAIL += 1; print("  ✗", n, x)
jar = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
def call(m, p, d=None):
    r = urllib.request.Request(BASE + p, data=json.dumps(d).encode() if d is not None else None, method=m, headers={"Content-Type": "application/json"}); return json.loads(op.open(r).read().decode())
def upload(form, rows):
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active
    for r in rows: ws.append(r)
    b = io.BytesIO(); wb.save(b); bd = "XX"; parts = b""
    for k, v in form.items(): parts += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (bd, k, v)).encode()
    parts += ("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"s.xlsx\"\r\n\r\n" % bd).encode() + b.getvalue() + ("\r\n--%s--\r\n" % bd).encode()
    return json.loads(op.open(urllib.request.Request(BASE + "/api/admin/students/upload", data=parts, method="POST", headers={"Content-Type": "multipart/form-data; boundary=" + bd})).read().decode())
try:
    call("POST", "/api/admin/login", {"username": "admin", "password": "admin123"})
    k = call("POST", "/api/admin/colleges", {"name": "كلية العلوم"})["uid"]; k2 = call("POST", "/api/admin/colleges", {"name": "كلية الهندسة"})["uid"]
    d1 = call("POST", "/api/admin/departments", {"college_uid": k, "name": "الفيزياء", "stages": 3})["uid"]; d2 = call("POST", "/api/admin/departments", {"college_uid": k2, "name": "المدني", "stages": 4})["uid"]
    upload({"dept_uid": d1, "stage": "2", "kind": "practical"}, [["اسم الطالب", "الكروب"], ["احمد علي حسن", "A"], ["احمد كريم جاسم", "B"], ["زينب عباس", "A"]])
    upload({"dept_uid": d1, "stage": "1", "kind": "theory"}, [["اسم الطالب"], ["احمد مرحلة اولى"]])
    upload({"dept_uid": d2, "stage": "2", "kind": "theory"}, [["اسم الطالب"], ["احمد مدني ثاني"]])
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(); ctx = b.new_context(viewport={"width": 393, "height": 800}, is_mobile=True, locale="ar-IQ"); pg = ctx.new_page(); errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(BASE + "/s/"); pg.wait_for_selector("#kc")
        check("تظهر قوائم الكلية والقسم والمرحلة", pg.locator("#kc").count() == 1 and pg.locator("#kd").count() == 1 and pg.locator("#ks").count() == 1)
        pg.fill("#q", "احمد"); check("قبل اختيار القسم لا تظهر أسماء", pg.locator("#res .item[data-u]").count() == 0)
        pg.select_option("#kc", k); pg.select_option("#kd", d1); pg.select_option("#ks", "2")
        pg.fill("#q", "احمد"); n = pg.locator("#res .item[data-u]").count(); check("«احمد» ضمن فيزياء/م2 فقط = 2", n == 2, n)
        check("أزرار الكروب A و B فقط", pg.locator(".gbtn").all_inner_texts() == ["A", "B"], pg.locator(".gbtn").all_inner_texts())
        pg.click(".gbtn[data-g=B]"); n = pg.locator("#res .item[data-u]").count(); check("الكروب B + البحث = 1", n == 1, n)
        pg.screenshot(path="/tmp/ui/c1_cohort.png")
        pg.reload(); pg.wait_for_selector("#kc"); check("الاختيار محفوظ بعد إعادة الفتح", pg.input_value("#kd") == d1 and pg.input_value("#ks") == "2")
        pg.select_option("#ks", "1"); pg.fill("#q", "احمد"); names = pg.locator("#res .item b").all_inner_texts(); check("مرحلة 1 فيها طالب المرحلة الأولى فقط", len(names) == 1 and "اولى" in names[0], names)
        check("لا أخطاء JS", not errs, errs)
        b.close()
finally:
    srv.terminate()
print("\nنجح %d — فشل %d" % (OK, FAIL)); sys.exit(1 if FAIL else 0)
