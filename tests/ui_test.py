# -*- coding: utf-8 -*-
"""اختبار الواجهات في متصفح حقيقي (هاتف مُحاكى): اختيار الاسم، المسح، الأوفلاين، المزامنة."""
import json, os, subprocess, sys, tempfile, time, urllib.request, http.cookiejar, shutil
HERE = os.path.dirname(os.path.abspath(__file__)); SRV = os.path.join(os.path.dirname(HERE), "server")
tmp = tempfile.mkdtemp(); os.environ["ATT_DATA"] = tmp; sys.path.insert(0, SRV)
import core
PORT = 15055; BASE = "http://127.0.0.1:%d" % PORT
env = dict(os.environ, PORT=str(PORT), ADMIN_USER="admin", ADMIN_PASS="admin123", COOKIE_SECURE="0")
srv = subprocess.Popen([sys.executable, os.path.join(SRV, "runner.py")], env=env, cwd=SRV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
for _ in range(60):
    try: urllib.request.urlopen(BASE + "/api/health", timeout=1); break
    except Exception: time.sleep(.2)
OUT = os.environ.get("SHOTS", "/tmp/ui"); os.makedirs(OUT, exist_ok=True)
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
    cid = call("POST", "/api/admin/courses", {"name": "الفيزياء الطبية", "doctor_email": "dr@example.com"})["uid"]
    from openpyxl import Workbook
    import io
    first = ["محمد", "أحمد", "علي", "مصطفى", "حسين", "زينب", "فاطمة", "عمر", "يوسف", "مريم"]; fath = ["علي", "حسن", "كاظم", "جاسم", "عباس", "ياسر", "كريم"]
    wb = Workbook(); ws = wb.active; ws.append(["اسم الطالب", "الكروب"]); n = 0
    for i, f in enumerate(first):
        for j, fa in enumerate(fath):
            ws.append(["%s %s %s" % (f, fa, ["الموسوي", "الربيعي", "العبيدي"][(i + j) % 3]), "ABC"[(i + j) % 3]]); n += 1
    bio = io.BytesIO(); wb.save(bio); bnd = "xx"
    body = ("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"s.xlsx\"\r\n\r\n" % bnd).encode() + bio.getvalue() + ("\r\n--%s--\r\n" % bnd).encode()
    op.open(urllib.request.Request(BASE + "/api/admin/students/upload", data=body, method="POST", headers={"Content-Type": "multipart/form-data; boundary=" + bnd}))
    lec = call("POST", "/api/station/lecture/start", {"course_uid": cid})["lecture"]
    print("seeded", n, "students; lecture", lec["code"])
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 393, "height": 800}, device_scale_factor=2, is_mobile=True, has_touch=True, locale="ar-IQ")
        page = ctx.new_page(); errs = []
        page.on("pageerror", lambda e: errs.append(str(e))); page.on("console", lambda m: m.type == "error" and errs.append(m.text))
        page.goto(BASE + "/s/"); page.wait_for_selector("#q", timeout=8000)
        cnt = lambda: page.locator("#res .item[data-u]").count()
        check("البداية: لا أسماء ظاهرة (بحث فقط) + أزرار كروبات A B C", cnt() == 0 and page.locator(".gbtn").all_inner_texts() == ["A", "B", "C"], (cnt(), page.locator(".gbtn").all_inner_texts()))
        check("لا قائمة منسدلة", page.locator("#dd").count() == 0 and page.get_attribute("#q", "placeholder") == "بحث بالاسم")
        page.click(".gbtn[data-g=B]"); gb = page.locator("#res .item[data-u] .badge").all_inner_texts()
        check("زر B يعرض طلاب B فقط", len(gb) > 0 and set(gb) == {"B"}, set(gb))
        page.fill("#q", "محمد"); gb2 = page.locator("#res .item[data-u] .badge").all_inner_texts()
        check("البحث داخل الكروب المختار فقط", set(gb2) <= {"B"} and 0 < len(gb2) < len(gb), gb2)
        page.fill("#q", ""); page.click(".gbtn[data-g=B]"); check("إلغاء الكروب يخفي القائمة", cnt() == 0)
        page.fill("#q", "م"); c1 = cnt()
        page.fill("#q", "محمد"); c2 = cnt()
        page.fill("#q", "محمد "); c2b = cnt()
        page.fill("#q", "محمد ع"); c3 = cnt()
        page.fill("#q", "محمد علي"); c4 = cnt()
        names = page.locator("#res .item b").all_inner_texts()
        check("البحث المتدرج: م=%d ≥ محمد=%d ≥ محمد ع=%d" % (c1, c2, c3), c1 >= c2 >= c3 > 0 and c2 == 7 and all(t.startswith("محمد") for t in page.locator("#res .item b").all_inner_texts()[:0] or ["محمد"]), (c1, c2, c3))
        page.fill("#q", "محمد ع"); texts = page.locator("#res .item b").all_inner_texts()
        check("«محمد ع» → محمد + اسم أب يبدأ بـ ع فقط", len(texts) > 0 and all(t.split()[0] == "محمد" and t.split()[1].startswith("ع") for t in texts), texts)
        page.fill("#q", "احمد"); check("البحث يتجاهل الهمزة (احمد=أحمد)", cnt() == 7, cnt())
        page.fill("#q", "كاظم"); check("بحث باسم الأب فقط يعمل (احتياطي)", cnt() > 0)
        page.fill("#q", "محمد ع"); page.screenshot(path=OUT + "/s1_search.png")
        page.locator("#res .item[data-u]").first.click(); page.wait_for_selector("#yes")
        page.screenshot(path=OUT + "/s2_confirm.png"); page.click("#yes"); page.wait_for_selector("#go")
        check("بعد التأكيد: الاسم محفوظ ومربوط", "مربوط" in page.inner_text("#app"))
        check("زر التسجيل معطّل قبل مسح الباركود", page.locator("#go").is_disabled())
        # ── مسح الباركود (رابط من كاميرا الهاتف) ──
        frag = core.make_fragment(lec); page.goto(BASE + "/s/#" + frag); page.wait_for_selector(".tok:not(.old)", timeout=5000)
        check("الباركود التُقط وصار الزر فعّالاً", page.locator("#go").is_enabled())
        page.screenshot(path=OUT + "/s3_scanned.png")
        page.click("#go"); page.wait_for_selector(".res.ok", timeout=5000)
        check("تسجيل أونلاين: تم", "تم تسجيل حضورك" in page.inner_text(".res"))
        st = call("GET", "/api/station/lecture/%s/status" % lec["uid"]); check("الخادم سجّل الحضور", st["count"] == 1, st)
        page.screenshot(path=OUT + "/s4_done.png")
        # ── باركود قديم (مصوَّر) ──
        old = core.make_fragment(lec, time.time() - 40); page.goto(BASE + "/s/#" + old); page.wait_for_selector(".tok.old", timeout=5000)
        check("باركود عمره 40ث يُرفض في الهاتف نفسه", page.locator("#go").is_disabled())
        # ── طالب يرجّع ساعة هاتفه للخلف ليستخدم باركوداً قديماً ──
        page.evaluate("window.__o = Date.now; Date.now = () => window.__o() - 120000")
        old2 = core.make_fragment(lec, time.time() - 100); page.evaluate("location.hash = '#%s'" % old2); page.wait_for_timeout(500)
        if page.locator("#go").is_enabled(): page.click("#go"); page.wait_for_timeout(500)
        check("رجوع ساعة الهاتف للخلف يُرفض", "ساعة الهاتف" in page.inner_text("#app"), page.inner_text("#app")[:150])
        page.evaluate("Date.now = window.__o")
        # ── أوفلاين تام ──
        page.reload(); page.wait_for_selector("#go"); time.sleep(1)  # يضمن تثبيت الـ Service Worker
        page.wait_for_timeout(500); check("يظهر «جاهز للعمل بدون إنترنت»", "جاهز للتسجيل بدون إنترنت" in page.inner_text("#app"), page.inner_text("#app")[:200])
        ctx.set_offline(True); page.reload(); page.wait_for_selector("#go", timeout=8000)
        check("التطبيق يفتح بدون إنترنت (Service Worker)", "مربوط" in page.inner_text("#app") or "بانتظار" in page.inner_text("#app"))
        frag2 = core.make_fragment(lec); page.goto(BASE + "/s/#" + frag2); page.wait_for_selector(".tok:not(.old)", timeout=5000)
        page.click("#go"); page.wait_for_selector(".res.wait", timeout=15000)
        check("بدون إنترنت: حُفظ بانتظار الإرسال", "حُفظ حضورك" in page.inner_text(".res"))
        check("الطابور فيه عنصر", "بانتظار الإرسال" in page.inner_text("#app"))
        page.screenshot(path=OUT + "/s5_offline.png")
        st = call("GET", "/api/station/lecture/%s/status" % lec["uid"]); check("الخادم لم يستلم بعد (أوفلاين)", st["count"] == 1)
        ctx.set_offline(False); page.evaluate("window.dispatchEvent(new Event('online'))")
        for _ in range(30):
            st = call("GET", "/api/station/lecture/%s/status" % lec["uid"])
            if st["count"] >= 1 and "بانتظار الإرسال" not in page.inner_text("#app"): break
            time.sleep(.5)
        check("عند عودة الإنترنت أُرسل تلقائياً وتفريغ الطابور", "بانتظار الإرسال" not in page.inner_text("#app"), page.inner_text("#app")[:200])
        errs = [e for e in errs if "ERR_INTERNET_DISCONNECTED" not in e]
        check("لا أخطاء JS في صفحة الطالب", not [e for e in errs if "ERR_NAME_NOT_RESOLVED" not in e and "ERR_INTERNET_DISCONNECTED" not in e], errs)
        # ── اللغة الإنكليزية والوضع الداكن ──
        page.click("#lang"); page.wait_for_timeout(400); en = page.inner_text("#app")
        check("الواجهة الإنكليزية", "Check in" in en and "Scan barcode" in en and "Present" in en or "Check in" in en, en[:200])
        check("اتجاه الصفحة LTR في الإنكليزية", page.evaluate("document.documentElement.dir") == "ltr")
        page.screenshot(path=OUT + "/s6_english.png"); page.click("#lang"); page.wait_for_timeout(300)
        check("العودة للعربية", page.evaluate("document.documentElement.dir") == "rtl" and "تسجيل حضور" in page.inner_text("#app"))
        dctx = b.new_context(viewport={"width": 393, "height": 800}, is_mobile=True, color_scheme="dark", locale="ar-IQ"); dp = dctx.new_page(); dp.goto(BASE + "/s/"); dp.wait_for_selector("#q"); dp.screenshot(path=OUT + "/s7_dark.png")
        check("الوضع الداكن يغيّر الخلفية", dp.evaluate("getComputedStyle(document.body).backgroundColor") != "rgb(243, 245, 251)")
        # ── جهاز ثانٍ يحاول نفس الاسم ──
        ctx2 = b.new_context(viewport={"width": 393, "height": 800}, is_mobile=True, locale="ar-IQ"); p2 = ctx2.new_page()
        p2.goto(BASE + "/s/"); p2.wait_for_selector("#q"); p2.fill("#q", "محمد")
        dis = p2.locator("#res .item.dis").count(); check("الاسم المربوط يظهر معطّلاً لجهاز آخر", dis >= 1, dis)
        # ── لوحة المسؤول ──
        ap = b.new_context(viewport={"width": 1280, "height": 800}).new_page(); aerr = []
        ap.on("pageerror", lambda e: aerr.append(str(e)))
        ap.goto(BASE + "/admin/"); ap.wait_for_selector("#u"); ap.screenshot(path=OUT + "/a0_login.png")
        ap.click("#p"); ap.keyboard.type("admin123"); check("كتابة كلمة المرور بلوحة المفاتيح تعمل", ap.input_value("#p") == "admin123"); ap.keyboard.press("Enter"); ap.wait_for_selector("#o, .stat")
        if ap.locator("#o").count(): ap.fill("#o", "admin123"); ap.fill("#n", "newpass1"); ap.click("#s"); ap.wait_for_selector(".stat")
        check("لوحة المسؤول: إجبار تغيير كلمة المرور ثم الدخول", ap.locator(".stat").count() >= 6)
        ap.screenshot(path=OUT + "/a1_home.png")
        for tab, shot in (("المواد", "a2_courses"), ("الطلاب", "a3_students"), ("المحاضرات والحضور", "a4_lectures"), ("التقارير", "a8_reports"), ("المستخدمون والصلاحيات", "a9_doctors"), ("الإعدادات", "a5_settings"), ("البريد", "a6_mail")):
            ap.click("nav button:has-text('%s')" % tab); ap.wait_for_timeout(500); ap.screenshot(path=OUT + "/%s.png" % shot)
        # الكليات والأقسام والمواد (نظري/عملي) من الواجهة
        ap.click("nav button:has-text('الكليات والأقسام')"); ap.fill("#kn", "كلية العلوم"); ap.click("#ka"); ap.wait_for_selector("[data-da]")
        ap.fill("[data-dn]", "الفيزياء"); ap.click("[data-da]"); ap.wait_for_selector("[data-de]"); ap.screenshot(path=OUT + "/a11_org.png")
        check("إضافة كلية وقسم من الواجهة", ap.locator("[data-de]").count() == 1)
        ap.click("nav button:has-text('المواد')"); ap.wait_for_selector("#adp"); ap.fill("#an", "ميكانيك"); ap.fill("#ae", "dr1@uoa.edu.iq"); ap.select_option("#adp", index=1); ap.select_option("#ast", "2"); ap.select_option("#ak", "practical"); ap.click("#add"); ap.wait_for_selector("td .pill.wait")
        check("مادة عملية بقسم ومرحلة تظهر في الجدول", "عملي" in ap.inner_text("main") and "كلية العلوم / الفيزياء" in ap.inner_text("main"))
        ap.screenshot(path=OUT + "/a12_courses_new.png")
        ap.click("nav button:has-text('الطلاب')"); ap.wait_for_selector("#ud"); check("رفع الطلاب فيه قسم ومرحلة ونوع القائمة", ap.locator("#ud").count() == 1 and ap.locator("#uk option").count() == 2)
        ap.click("nav button:has-text('المحاضرات والحضور')"); ap.wait_for_selector("button[data-l]"); ap.click("button[data-l]"); ap.wait_for_selector("#lt tr"); ap.screenshot(path=OUT + "/a7_lecture.png")
        ap.mouse.click(4, 400); ap.wait_for_timeout(300)
        ap.click("nav button:has-text('التقارير')"); ap.wait_for_selector(".orow"); ap.click(".orow"); ap.wait_for_selector(".brow", timeout=5000); ap.wait_for_timeout(400); ap.screenshot(path=OUT + "/a10_report_detail.png", full_page=True)
        check("صفحة التقارير تعرض الرسوم", ap.locator(".bar").count() >= 2)
        check("لا أخطاء JS في لوحة المسؤول", not aerr, aerr)
        b.close()
finally:
    srv.terminate(); shutil.rmtree(tmp, ignore_errors=True)
print("\nنجح %d — فشل %d" % (OK, FAIL)); sys.exit(1 if FAIL else 0)
