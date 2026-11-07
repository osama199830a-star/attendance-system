# -*- coding: utf-8 -*-
import json, os, subprocess, sys, tempfile, time, urllib.request, http.cookiejar, io, threading, http.server, socketserver
ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server", "static", "student"); SRV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server")
tmp = tempfile.mkdtemp(); BASE = "http://127.0.0.1:5000"; WPORT = 15233; DEAD = "http://127.0.0.1:9"
env = dict(os.environ, ATT_DATA=tmp, ADMIN_USER="admin", ADMIN_PASS="admin123", COOKIE_SECURE="0"); env.pop("PORT", None)
srv = subprocess.Popen([sys.executable, os.path.join(SRV, "runner.py")], env=env, cwd=SRV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
for _ in range(80):
    try: urllib.request.urlopen(BASE + "/api/health", timeout=1); break
    except Exception: time.sleep(.25)
class H(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
os.chdir(ASSETS)
socketserver.ThreadingTCPServer.allow_reuse_address = True
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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import core_frag
try:
    call("POST", "/api/admin/login", {"username": "admin", "password": "admin123"})
    cid = call("POST", "/api/admin/courses", {"name": "فيزياء", "doctor_email": "d@e.com"})["uid"]
    from openpyxl import Workbook
    wb = Workbook(); w = wb.active; w.append(["اسم الطالب", "الكروب"])
    for nm in ["ابرار خضير عباس جاسم", "ابراهيم ماجد ابراهيم حسين", "زينب علي حسن", "سارة محمد علي", "نور احمد كريم", "حيدر صالح مهدي"]: w.append([nm, "A"])
    bio = io.BytesIO(); wb.save(bio); bnd = "xx"
    body = ("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"s.xlsx\"\r\n\r\n" % bnd).encode() + bio.getvalue() + ("\r\n--%s--\r\n" % bnd).encode()
    op.open(urllib.request.Request(BASE + "/api/admin/students/upload", data=body, method="POST", headers={"Content-Type": "multipart/form-data; boundary=" + bnd}))
    lec = call("POST", "/api/station/lecture/start", {"course_uid": cid})["lecture"]
    roster = urllib.request.urlopen(BASE + "/api/student/roster").read()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(args=["--disable-web-security", "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
        def newpage(base, embedded):
            ctx = b.new_context(viewport={"width": 393, "height": 800}, is_mobile=True, has_touch=True, locale="ar-IQ", permissions=["camera"], service_workers="block")
            pg = ctx.new_page(); errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.route("**/config.js", lambda r: r.fulfill(body='window.APP_CONFIG = { base: "%s", embedded: %s };' % (base, "true" if embedded else "false"), content_type="application/javascript"))
            if embedded: pg.route("**/roster.json", lambda r: r.fulfill(body=roster, content_type="application/json"))
            pg.add_init_script("window.BarcodeDetector = class { constructor(){} async detect(){ return window.__raw ? [{rawValue: window.__raw}] : []; } };")
            return pg, errs
        # ── السيناريو A: العنوان صحيح ──
        pg, errs = newpage(BASE, False)
        pg.goto("http://127.0.0.1:%d/index.html" % WPORT); pg.wait_for_selector("#q", timeout=8000)
        pg.fill("#q", "ابرار"); pg.wait_for_selector("#res .item[data-u]"); pg.click("#res .item[data-u]"); pg.click("#yes"); pg.wait_for_selector(".pill.ok", timeout=6000)
        pg.evaluate("window.__raw=%s" % json.dumps(BASE + "/s/#" + core_frag.frag(lec))); pg.click("#scan"); pg.wait_for_selector("#go:not([disabled])", timeout=6000)
        pg.click("#go"); pg.wait_for_selector(".res.ok", timeout=6000)
        check("A) تسجيل عادي عبر المسح الداخلي (BarcodeDetector)", call("GET", "/api/station/lecture/%s/status" % lec["uid"])["count"] == 1)
        check("A) لا أخطاء JS", not errs, errs)
        # ── السيناريو B: عنوان قديم ميّت + الباركود يحمل العنوان الجديد (https:5443) ──
        pg, errs = newpage(DEAD, True)
        pg.goto("http://127.0.0.1:%d/index.html" % WPORT); pg.wait_for_selector("#q", timeout=8000)
        check("B) القائمة المضمّنة تعمل بلا اتصال بالخادم", pg.locator(".gbtn").count() >= 1)
        pg.fill("#q", "ابراهيم"); pg.wait_for_selector("#res .item[data-u]"); pg.click("#res .item[data-u]"); pg.click("#yes"); time.sleep(.5)
        pg.evaluate("window.__raw=%s" % json.dumps("https://127.0.0.1:5443/s/#" + core_frag.frag(lec))); pg.click("#scan")
        time.sleep(4.5)   # الفحص + التعلّم + تحميل الأسماء
        base_now = pg.evaluate("JSON.parse(localStorage.getItem('att_base')||'\"\"')")
        check("B) التطبيق تعلّم العنوان الجديد تلقائياً (http:5000 بدل https:5443)", base_now == BASE, base_now)
        pg.wait_for_selector("#go:not([disabled])", timeout=6000); pg.click("#go"); pg.wait_for_selector(".res", timeout=8000)
        txt = pg.inner_text(".res")
        check("B) الحضور وصل للخادم بعد التعلّم", call("GET", "/api/station/lecture/%s/status" % lec["uid"])["count"] == 2, txt)
        check("B) لا أخطاء JS", not errs, errs)
        # ── السيناريو C: لا قائمة أسماء + عنوان خاطئ → إدخال العنوان من الشاشة ──
        pg, errs = newpage(DEAD, False)
        pg.goto("http://127.0.0.1:%d/index.html" % WPORT); pg.wait_for_selector("#srv0", timeout=8000)
        check("C) شاشة الخطأ فيها حقل عنوان الخادم", True)
        pg.fill("#srv0", "127.0.0.1:5000"); pg.click("#srv0go")   # بلا http:// عمداً
        pg.wait_for_selector("#q", timeout=10000)
        check("C) بعد إدخال العنوان تُحمَّل الأسماء", pg.locator(".gbtn").count() >= 1)
        pg.fill("#srv0", "") if pg.locator("#srv0").count() else None

        # ── السيناريو D: باركود حقيقي (SVG من الخادم) كصورة → jsQR فقط ──
        import urllib.parse
        pg, errs = newpage(BASE, False)
        pg.add_init_script("delete window.BarcodeDetector;")
        pg.goto("http://127.0.0.1:%d/index.html" % WPORT); pg.wait_for_selector("#q", timeout=8000)
        pg.fill("#q", "زينب"); pg.wait_for_selector("#res .item[data-u]"); pg.click("#res .item[data-u]"); pg.click("#yes"); pg.wait_for_selector(".pill.ok", timeout=6000)
        data = BASE + "/s/#" + core_frag.frag(lec)
        svg = urllib.request.urlopen(BASE + "/api/qr.svg?d=" + urllib.parse.quote(data, safe="")).read()
        # نحوّل SVG إلى PNG عبر المتصفح نفسه (كما تفعل كاميرا الهاتف: صورة فيها الباركود)
        pg2 = b.new_context().new_page(); pg2.set_content('<body style="margin:0;background:#fff"><div style="padding:40px;width:520px">' + svg.decode() + '</div></body>')
        pg2.locator("div").screenshot(path="/tmp/qr_real.png"); 
        pg.set_input_files("input[type=file]", "/tmp/qr_real.png"); pg.wait_for_selector("#go:not([disabled])", timeout=8000)
        pg.click("#go"); pg.wait_for_selector(".res.ok", timeout=6000)
        check("D) قراءة باركود حقيقي من صورة بدون BarcodeDetector (يعمل في أي متصفح)", call("GET", "/api/station/lecture/%s/status" % lec["uid"])["count"] == 3)
        check("D) لا أخطاء JS", not errs, errs)

        # ── السيناريو E/F: الكاميرا الحية — (E) BarcodeDetector يرمي خطأ كما يحدث في بعض أجهزة أندرويد، (F) غير موجود ──
        def live(mode, who, expect):
            pg, errs = newpage(BASE, False)
            if mode == "throws": pg.add_init_script("window.BarcodeDetector = class { constructor(){} async detect(){ throw new Error('Barcode detection service unavailable'); } };")
            elif mode == "silent": pg.add_init_script("window.BarcodeDetector = class { constructor(){} async detect(){ return []; } };")
            else: pg.add_init_script("delete window.BarcodeDetector;")
            pg.goto("http://127.0.0.1:%d/index.html" % WPORT); pg.wait_for_selector("#q", timeout=8000)
            pg.on("request", lambda r: r.method=="POST" and print("   POST", r.url)); pg.fill("#q", who); pg.wait_for_selector("#res .item[data-u]"); pg.click("#res .item[data-u]"); pg.click("#yes"); pg.wait_for_selector(".pill.ok", timeout=6000)
            data = BASE + "/s/#" + core_frag.frag(lec)
            svg = urllib.request.urlopen(BASE + "/api/qr.svg?d=" + urllib.parse.quote(data, safe="")).read().decode()
            import base64
            uri = "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()
            # كاميرا وهمية: canvas.captureStream يرسم الباركود في إطار فيديو حقيقي (بدل صورة اختبار خضراء)
            pg.add_init_script("""(() => { const uri = %s; navigator.mediaDevices.getUserMedia = async () => {
                const cv = document.createElement('canvas'); cv.width = 640; cv.height = 480; const cx = cv.getContext('2d');
                const im = new Image(); im.src = uri; await im.decode();
                const draw = () => { cx.fillStyle = '#888'; cx.fillRect(0,0,640,480); cx.drawImage(im, 120, 40, 400, 400); requestAnimationFrame(draw); }; draw();
                return cv.captureStream(15); }; })();""" % json.dumps(uri))
            pg.reload(); pg.wait_for_selector("#scan", timeout=8000)
            pg.click("#scan"); pg.wait_for_selector("#go:not([disabled])", timeout=12000)
            pg.click("#go"); pg.wait_for_selector(".res", timeout=6000)
            return errs
        # نسجّل لطلاب مختلفين: ابرار(1) ابراهيم(2) زينب(3) — نضيف طلاباً جدداً للسيناريوهات
        for nm in ["سارة محمد علي", "نور احمد كريم", "حيدر صالح مهدي"]: pass

        for mode, who, exp, label in (("throws","سارة",4,"E) أندرويد: BarcodeDetector يفشل → jsQR يكمل"),("silent","نور",5,"E2) BarcodeDetector صامت لا يلتقط → jsQR يكمل"),("none","حيدر",6,"F) متصفح بلا BarcodeDetector (آيفون/فايرفوكس) → jsQR")):
            try:
                e = live(mode, who, exp)
                check(label, call("GET", "/api/station/lecture/%s/status" % lec["uid"])["count"] == exp, e)
            except Exception as ex:
                check(label, False, repr(ex)[:200])
        b.close()
finally:
    srv.terminate(); print("نجح %d — فشل %d" % (OK, FAIL))
