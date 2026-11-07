# -*- coding: utf-8 -*-
"""اختبار ضغط: مئات الطلاب يسجّلون في نفس اللحظة (قبل/بعد انتهاء المهلة) + إرسال طوابير أوفلاين."""
import json, os, subprocess, sys, tempfile, time, urllib.request, http.cookiejar, threading, statistics, io
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__)); SRV = os.path.join(os.path.dirname(HERE), "server")
N = int(os.environ.get("N", "600")); CONC = int(os.environ.get("CONC", "150"))
tmp = tempfile.mkdtemp(); os.environ["ATT_DATA"] = tmp; sys.path.insert(0, SRV)
import core
PORT = 15066; BASE = "http://127.0.0.1:%d" % PORT
code = "import runner,threading;runner.serve_local(%d,%d);threading.Event().wait()" % (PORT, PORT + 1)
env = dict(os.environ, ADMIN_USER="admin", ADMIN_PASS="admin123", COOKIE_SECURE="0")
srv = subprocess.Popen([sys.executable, "-c", code], env=env, cwd=SRV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
for _ in range(80):
    try: urllib.request.urlopen(BASE + "/api/health", timeout=1); break
    except Exception: time.sleep(.2)
jar = http.cookiejar.CookieJar(); op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
def call(m, p, d=None, t=30):
    r = urllib.request.Request(BASE + p, data=json.dumps(d).encode() if d is not None else None, method=m, headers={"Content-Type": "application/json"})
    return json.loads(op.open(r, timeout=t).read().decode())
OK = FAIL = 0
def check(n, c, x=""):
    global OK, FAIL
    if c: OK += 1; print("  ✓", n)
    else: FAIL += 1; print("  ✗", n, x)
try:
    call("POST", "/api/admin/login", {"username": "admin", "password": "admin123"})
    cid = call("POST", "/api/admin/courses", {"name": "ضغط", "doctor_email": "d@x.iq"})["uid"]
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active; ws.append(["الاسم", "الكروب"])
    for i in range(N): ws.append(["طالب رقم %d بن فلان" % i, "ABC"[i % 3]])
    bio = io.BytesIO(); wb.save(bio); bnd = "xx"
    body = ("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"s.xlsx\"\r\n\r\n" % bnd).encode() + bio.getvalue() + ("\r\n--%s--\r\n" % bnd).encode()
    t0 = time.time(); op.open(urllib.request.Request(BASE + "/api/admin/students/upload", data=body, method="POST", headers={"Content-Type": "multipart/form-data; boundary=" + bnd}))
    print("رفع %d طالب: %.2fs" % (N, time.time() - t0))
    lec = call("POST", "/api/station/lecture/start", {"course_uid": cid, "duration_sec": 3600})["lecture"]
    roster = call("GET", "/api/student/roster")["students"]; check("القائمة كاملة", len(roster) == N, len(roster))
    lat = []; errs = []
    def one(i):
        s = roster[i]; dev = "dev%d" % i; t = time.time()
        try:
            tok = core.make_token(lec); 
            b = call("POST", "/api/student/bind", {"device_id": dev, "student": s["u"]}, 60)
            it = {"id": str(i), "code": lec["code"], "t": tok[0], "i": tok[1], "sig": tok[2], "student": s["u"], "age": 1.0, "elapsed": 1.0, "queued": False}
            r = call("POST", "/api/student/submit", {"device_id": dev, "items": [it]}, 60)["results"][0]
            lat.append(time.time() - t)
            if not (b["ok"] and r["status"] == "ok"): errs.append((i, b, r))
        except Exception as e: errs.append((i, repr(e)))
    t0 = time.time()
    with ThreadPoolExecutor(CONC) as ex: list(ex.map(one, range(N)))
    dt = time.time() - t0
    lat.sort(); p95 = lat[int(len(lat) * .95) - 1] if lat else 99
    print("تسجيل %d طالب بالتزامن (%d اتصال): %.1fs — متوسط %.2fs — p95 %.2fs" % (N, CONC, dt, statistics.mean(lat) if lat else 0, p95))
    check("كل الطلاب سُجّلوا بلا أخطاء", not errs and len(lat) == N, errs[:3])
    st = call("GET", "/api/station/lecture/%s/status" % lec["uid"]); check("العدّاد = %d" % N, st["count"] == N, st)
    check("p95 أقل من 5 ثوانٍ", p95 < 5, p95)
    # طوابير أوفلاين: كل طالب أرسل لمحاضرة ثانية دفعة واحدة
    lec2 = call("POST", "/api/station/lecture/start", {"course_uid": cid, "duration_sec": 3600})["lecture"]
    def queued(k):
        items = []
        for j in range(k, min(k + 20, N)):
            tok = core.make_token(lec2); items.append({"id": "q%d" % j, "code": lec2["code"], "t": tok[0], "i": tok[1], "sig": tok[2], "student": roster[j]["u"], "age": 2.0, "queued": True})
        # كل عنصر من جهازه الصحيح
        return [call("POST", "/api/student/submit", {"device_id": "dev%d" % int(it["id"][1:]), "items": [it]}, 60)["results"][0]["status"] for it in items]
    t0 = time.time()
    with ThreadPoolExecutor(30) as ex: res = sum(ex.map(queued, range(0, N, 20)), [])
    print("إرسال %d حضوراً أوفلاين: %.1fs" % (len(res), time.time() - t0))
    check("كل الطوابير قُبلت", res.count("ok") == N, {k: res.count(k) for k in set(res)})
    t0 = time.time(); r = call("POST", "/api/station/export", {"course_uid": cid}, 120); print("تصدير Excel (%d طالب × 2 محاضرة): %.1fs" % (N, time.time() - t0))
    check("التصدير نجح", r["students"] == N and r["lectures"] == 2, r)
    # تكرار: نفس الطالب يرسل مرتين
    tok = core.make_token(lec); r = call("POST", "/api/student/submit", {"device_id": "dev0", "items": [{"id": "d", "code": lec["code"], "t": tok[0], "i": tok[1], "sig": tok[2], "student": roster[0]["u"], "age": 1.0, "elapsed": 1.0}]})["results"][0]
    check("التكرار لا يضاعف الحضور", r["status"] == "duplicate", r)
finally:
    srv.terminate()
print("\nنجح %d — فشل %d" % (OK, FAIL)); sys.exit(1 if FAIL else 0)
