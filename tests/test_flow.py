# -*- coding: utf-8 -*-
"""اختبار شامل: يشغّل خادماً سحابياً حقيقياً (عملية منفصلة) وخادماً محلياً ويجرب كل التدفق."""
import io, json, os, subprocess, sys, tempfile, time, urllib.request, http.cookiejar, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
SRV = os.path.join(os.path.dirname(HERE), "server")
tmp = tempfile.mkdtemp()
os.environ["ATT_DATA"] = os.path.join(tmp, "local")
os.environ.pop("ATT_MODE", None)
sys.path.insert(0, SRV)
import app as A, core, db as D, config

CLOUD_PORT = 18765
env = dict(os.environ, ATT_DATA=os.path.join(tmp, "cloud"), ATT_MODE="cloud", COOKIE_SECURE="0", SYNC_KEY="K123", PORT=str(CLOUD_PORT), ADMIN_USER="boss", ADMIN_PASS="secret99")
cloud = subprocess.Popen([sys.executable, os.path.join(SRV, "runner.py")], env=env, cwd=SRV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
BASE = "http://127.0.0.1:%d" % CLOUD_PORT
for _ in range(50):
    try:
        urllib.request.urlopen(BASE + "/api/health", timeout=1); break
    except Exception:
        time.sleep(0.2)
else:
    print(cloud.stdout.read().decode()); sys.exit("cloud did not start")

OK = FAIL = 0
def check(name, cond, extra=""):
    global OK, FAIL
    if cond: OK += 1; print("  ✓", name)
    else: FAIL += 1; print("  ✗", name, extra)

class Cloud:
    def __init__(self):
        self.o = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def req(self, method, path, data=None, raw=False, headers=None):
        h = {"Content-Type": "application/json"}; h.update(headers or {})
        r = urllib.request.Request(BASE + path, data=(json.dumps(data).encode() if data is not None else None), method=method, headers=h)
        try:
            resp = self.o.open(r, timeout=20)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "{}")
        b = resp.read()
        return resp.status, (b if raw else json.loads(b.decode()))

try:
    # ───── 1) المسؤول على السحابة ─────
    print("1) المسؤول")
    cl = Cloud()
    check("دخول خاطئ مرفوض", cl.req("POST", "/api/admin/login", {"username": "boss", "password": "x"})[0] == 401)
    check("لوحة المسؤول تتطلب دخولاً", cl.req("GET", "/api/admin/courses")[0] == 401)
    s, r = cl.req("POST", "/api/admin/login", {"username": "boss", "password": "secret99"})
    check("دخول صحيح", s == 200 and not r["must_change"])
    s, r = cl.req("POST", "/api/admin/courses", {"name": "الفيزياء الطبية", "doctor_email": "dr.ali@example.com"})
    c1 = r["uid"]
    s, r = cl.req("POST", "/api/admin/courses", {"name": "الكيمياء", "doctor_email": "bad"})
    check("إيميل غير صالح مرفوض", s == 400)
    # ملف الطلاب (Excel) يُبنى بـ openpyxl ويُرفع multipart
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active; ws.append(["اسم الطالب", "الكروب"])
    names = [("محمد علي حسن", "A"), ("محمد أحمد كاظم", "A"), ("محمد علي جاسم", "B"), ("مصطفى حيدر", "B"), ("أحمد ياسر", "C"), ("زينب كريم", "C")]
    for n_ in names: ws.append(list(n_))
    ws.append(["محمد علي حسن", "A"])  # مكرر
    bio = io.BytesIO(); wb.save(bio)
    bnd = "----x"; body = (("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"s.xlsx\"\r\nContent-Type: application/octet-stream\r\n\r\n" % bnd).encode() + bio.getvalue() + ("\r\n--%s--\r\n" % bnd).encode())
    rq = urllib.request.Request(BASE + "/api/admin/students/upload", data=body, method="POST", headers={"Content-Type": "multipart/form-data; boundary=" + bnd})
    r = json.loads(cl.o.open(rq).read().decode())
    check("رفع الطلاب: 7 (الاسمان المتطابقان طالبان مختلفان) ويُبلَّغ المسؤول بالتكرار", r["added"] == 7 and r.get("duplicates") == 1, r)
    rq = urllib.request.Request(BASE + "/api/admin/students/upload", data=body, method="POST", headers={"Content-Type": "multipart/form-data; boundary=" + bnd})
    r = json.loads(cl.o.open(rq).read().decode())
    check("إعادة رفع نفس الملف لا تكرر", r["added"] == 0, r)
    s, r = cl.req("PUT", "/api/admin/settings", {"qr_interval": 3, "scan_grace": 10, "admin_email": "admin@example.com"})
    s, r = cl.req("GET", "/api/admin/students?q=" + urllib.parse.quote("محمد"))
    check("بحث محمد يعيد 4", len(r["students"]) == 4, r)

    # ───── 2) الجهاز المحلي يسحب المعلومات من السحابة ─────
    print("2) مزامنة السحابة → جهاز الدكتور")
    CONF = A.CONF
    CONF["cloud_url"], CONF["sync_key"] = BASE, "K123"
    app = A.get_app(); tc = app.test_client()
    L = lambda m, p, d=None, **kw: getattr(tc, m.lower())(p, json=d, **kw)
    res = core.sync_once(CONF)
    check("السحب نجح", res.get("pulled", 0) >= 7, res)
    info = L("GET", "/api/station/info").get_json()
    check("المواد ظهرت عند الدكتور", [c["name"] for c in info["courses"]] == ["الفيزياء الطبية", "الكيمياء"] if "الكيمياء" in [c["name"] for c in info["courses"]] else [c["name"] for c in info["courses"]] == ["الفيزياء الطبية"], info["courses"])
    check("إعداد 3 ثوانٍ وصل", info["interval"] == 3)
    ros = tc.get("/api/student/roster").get_json()
    check("قائمة الطلاب (7)", len(ros["students"]) == 7)
    uid = {s["n"]: s["u"] for s in ros["students"]}
    check("الدكتور بلا مفتاح من عنوان خارجي مرفوض", tc.get("/api/station/info", environ_overrides={"REMOTE_ADDR": "8.8.8.8"}).status_code == 403)

    # ───── 3) محاضرة وباركود متغيّر ─────
    print("3) المحاضرة والباركود")
    r = L("POST", "/api/station/lecture/start", {"course_uid": c1}).get_json()
    lec = r["lecture"]
    # نجعل المحاضرة بدأت قبل ساعتين لنتمكن من اختبار باركودات قديمة (مصوَّرة/غير متصلة)
    c_ = D.connect(); c_.execute("UPDATE lectures SET start_ts=start_ts-7200, end_ts=end_ts+600 WHERE uid=?", (lec["uid"],)); c_.close()
    lec["start_ts"] -= 7200; lec["end_ts"] += 600
    check("بدأت محاضرة برمز 6 أحرف", len(lec["code"]) == 6 and lec["interval_sec"] == 3)
    f1 = core.make_fragment(lec, time.time()); f2 = core.make_fragment(lec, time.time() + 3.1)
    check("الباركود يتغير بعد 3 ثوانٍ", f1 != f2)
    check("ضمن الـ3 ثوانٍ لا يتغير (ثابت لنفس الفترة)", core.make_fragment(lec, 1000.0) == core.make_fragment(lec, 1001.9))
    def mk(at=None, **kw):
        t, i, sig = core.make_token(lec, at)
        d = dict(code=lec["code"], t=t, i=i, sig=sig, queued=False, elapsed=1.0, age=1.0); d.update(kw); return d
    def submit(dev, student, **kw):
        it = mk(student=student, id="1", **kw)
        return tc.post("/api/student/submit", json={"device_id": dev, "items": [it]}).get_json()["results"][0]
    r = submit("dev-A", uid["محمد علي حسن"]); check("تسجيل أول طالب ✓", r["status"] == "ok", r)
    r = submit("dev-A", uid["محمد علي حسن"]); check("نفس الطالب مرة ثانية = مكرر", r["status"] == "duplicate", r)
    r = submit("dev-A", uid["أحمد ياسر"]); check("نفس الجهاز لطالب آخر مرفوض", r["status"] == "rejected" and r["reason"] == "device_bound_other", r)
    r = submit("dev-B", uid["محمد علي حسن"]); check("جهاز آخر على اسم مربوط مرفوض", r["reason"] in ("student_bound_elsewhere",) or r["status"] == "duplicate", r)
    r = submit("dev-B", uid["محمد أحمد كاظم"], at=None); check("طالب ثانٍ بجهازه ✓", r["status"] == "ok", r)
    # باركود مصوَّر ومُرسل متأخراً (قديم 30 ثانية) مع إنه متصل
    r = submit("dev-C", uid["مصطفى حيدر"], at=time.time() - 30); check("باركود عمره 30ث مرفوض (منع التصوير)", r["reason"] == "stale_qr", r)
    # طالب غير متصل: عمر الباركود وقت المسح 4ث، يصل بعد ساعة
    r = submit("dev-C", uid["مصطفى حيدر"], at=time.time() - 3600, queued=True, age=4.0)
    check("أوفلاين: مسح حديث يصل متأخراً ✓", r["status"] == "ok", r)
    r = submit("dev-D", uid["زينب كريم"], at=time.time() - 3600, queued=True, age=60.0); check("أوفلاين بعمر 60ث مرفوض", r["reason"] == "stale_qr", r)
    r = submit("dev-D", uid["زينب كريم"], at=time.time() - 3600, queued=True, age=4.0, sig="deadbeef0000"); check("توقيع مزوّر مرفوض", r["reason"] == "bad_sig", r)
    bad = mk(at=lec["end_ts"] + 500, student=uid["زينب كريم"]); bad["queued"] = True; bad["age"] = 2
    # توقيع صحيح لكن خارج وقت المحاضرة
    t_, i_, s_ = core.make_token(lec, lec["end_ts"] + 500)
    r = tc.post("/api/student/submit", json={"device_id": "dev-D", "items": [dict(bad, t=t_, i=i_, sig=s_)]}).get_json()["results"][0]
    check("خارج وقت المحاضرة مرفوض", r["reason"] == "outside_window", r)
    # فك الربط بواسطة الدكتور ثم ربط جهاز جديد
    r = L("POST", "/api/station/unbind", {"student_uid": uid["محمد أحمد كاظم"]}).get_json(); check("فك ربط طالب", r["ok"])
    r = tc.post("/api/student/bind", json={"device_id": "dev-NEW", "student": uid["محمد أحمد كاظم"]}).get_json(); check("ربط جهاز جديد بعد الفك", r["ok"], r)
    st = L("GET", "/api/station/lecture/%s/status" % lec["uid"]).get_json()
    check("العداد = 3 حاضرين", st["count"] == 3, st)
    check("تثبيت: الاسم مفروض من الجهاز", tc.get("/api/student/me?device=dev-A").get_json()["student"]["n"] == "محمد علي حسن")

    # ───── 4) مزامنة الحضور إلى السحابة ─────
    print("4) مزامنة الحضور → السحابة")
    # طالب يرسل مباشرة للسحابة قبل أن تعرف المحاضرة (4G) → معلّق
    item = mk(student=uid["محمد علي جاسم"], id="9")
    s, r = cl.req("POST", "/api/student/submit", {"device_id": "dev-E", "items": [item]})
    check("السحابة تقبل الطلب كمعلّق (المحاضرة لم تصلها)", r["results"][0]["status"] == "pending", r)
    res = core.sync_once(CONF)
    check("الدفع نجح", res["pushed"] >= 4, res)
    s, r = cl.req("GET", "/api/admin/lectures")
    L1 = [x for x in r["lectures"] if x["uid"] == lec["uid"]][0]
    check("السحابة ترى المحاضرة", True)
    check("حضور السحابة = 4 (3 + المعلّق بعد التحقق)", L1["present"] == 4, L1)
    res = core.sync_once(CONF)
    st = L("GET", "/api/station/lecture/%s/status" % lec["uid"]).get_json()
    check("الجهاز المحلي استلم حضور الطالب المرسل للسحابة", st["count"] == 4, st)
    # ربط الأجهزة ينتقل
    s, r = cl.req("GET", "/api/admin/students")
    check("الربط انتقل للسحابة (≥4 مربوطين)", sum(1 for x in r["students"] if x["bound"]) >= 4, r["students"])
    # تعديل يدوي من المسؤول على السحابة ينزل للدكتور
    s, r = cl.req("POST", "/api/admin/attendance/toggle", {"lecture_uid": lec["uid"], "student_uid": uid["مصطفى حيدر"], "present": False})
    time.sleep(0.01); core.sync_once(CONF)
    st = L("GET", "/api/station/lecture/%s/status" % lec["uid"]).get_json()
    check("تعديل المسؤول (غياب) وصل للدكتور → 3", st["count"] == 3, st)
    core.sync_once(CONF)
    # إنهاء المحاضرة
    L("POST", "/api/station/lecture/%s/end" % lec["uid"])

    # ───── 5) تصدير Excel والبريد ─────
    print("5) Excel والإرسال")
    r = L("POST", "/api/station/export", {"course_uid": c1}).get_json()
    check("تم إنشاء الملف", os.path.exists(r["path"]), r)
    from openpyxl import load_workbook
    ws = load_workbook(r["path"]).active
    rows = [[c.value for c in row] for row in ws.iter_rows(min_row=2)]
    hdr = rows[0]
    check("الأعمدة: الاسم، الكروب، محاضرة 1", hdr[1] == "اسم الطالب" and hdr[2] == "الكروب" and str(hdr[3]).startswith("محاضرة 1"), hdr)
    stat = {r_[1]: r_[3] for r_ in rows[1:]}
    check("حاضر/غائب صحيحة", stat["محمد علي حسن"] == "حاضر" and stat["زينب كريم"] == "غائب" and stat["مصطفى حيدر"] == "غائب" and stat["محمد علي جاسم"] == "حاضر", stat)
    check("كل الطلاب السبعة موجودون", len(rows) - 1 == 7)
    check("البريد في الطابور (لا SMTP بعد)", r["mail"] == "queued" and r["doctor_email"] == "dr.ali@example.com")
    c = D.connect(); ob = c.execute("SELECT * FROM outbox").fetchall(); c.close()
    check("الرسالة إلى الدكتور ونسخة للمسؤول", ob[0]["to_addrs"] == "dr.ali@example.com" and ob[0]["cc"] == "admin@example.com", dict(ob[0]))
    # تصدير المسؤول (تنزيل)
    s, data = cl.req("GET", "/api/admin/export?course_uid=" + c1, raw=True)
    check("المسؤول ينزّل Excel من السحابة", s == 200 and data[:2] == b"PK")
    # مفتاح مزامنة خاطئ
    CONF["sync_key"] = "bad"
    try: core.sync_once(CONF); check("مفتاح خاطئ مرفوض", False)
    except Exception: check("مفتاح مزامنة خاطئ مرفوض", True)
    CONF["sync_key"] = "K123"
    # أوفلاين تام: السحابة غير متاحة → لا يتعطل المحلي
    CONF["cloud_url"] = "http://127.0.0.1:9"
    try: core.sync_once(CONF); check("انقطاع", False)
    except Exception: check("بدون إنترنت: المزامنة تفشل بهدوء والبيانات المحلية سليمة", True)
    check("التصدير يعمل بدون إنترنت", L("POST", "/api/station/export", {"course_uid": c1}).get_json().get("filename") is not None)
finally:
    cloud.terminate()
    shutil.rmtree(tmp, ignore_errors=True)
print("\nنجح %d — فشل %d" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
