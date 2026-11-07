# -*- coding: utf-8 -*-
"""حسابات الدكاترة وصلاحياتهم، التقارير، إنذار الغياب، وملف Excel (ملخص + ورقة لكل كروب)."""
import json, os, subprocess, sys, tempfile, time, urllib.request, urllib.error, http.cookiejar, io
HERE = os.path.dirname(os.path.abspath(__file__)); SRV = os.path.join(os.path.dirname(HERE), "server")
tmp = tempfile.mkdtemp(); os.environ["ATT_DATA"] = tmp; sys.path.insert(0, SRV)
import core
PORT = 15088; BASE = "http://127.0.0.1:%d" % PORT
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
class Cl:
    def __init__(s): s.o = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def req(s, m, p, d=None, raw=False):
        r = urllib.request.Request(BASE + p, data=json.dumps(d).encode() if d is not None else None, method=m, headers={"Content-Type": "application/json"})
        try: resp = s.o.open(r); body = resp.read(); return resp.status, (body if raw else json.loads(body.decode()))
        except urllib.error.HTTPError as e:
            try: return e.code, json.loads(e.read().decode())
            except Exception: return e.code, {}
try:
    ad = Cl(); ad.req("POST", "/api/admin/login", {"username": "admin", "password": "admin123"})
    c1 = ad.req("POST", "/api/admin/courses", {"name": "فيزياء", "doctor_email": "Dr1@uoa.edu.iq"})[1]["uid"]
    c2 = ad.req("POST", "/api/admin/courses", {"name": "كيمياء", "doctor_email": "dr2@uoa.edu.iq"})[1]["uid"]
    for n, g in (("علي حسن", "A"), ("زينب كريم", "A"), ("عمر ياسر", "B"), ("مريم علي", "B")): ad.req("POST", "/api/admin/students", {"name": n, "grp": g})
    studs = ad.req("GET", "/api/admin/students")[1]["students"]
    # محاضرتان لمادة فيزياء: علي حاضر مرتين، زينب مرة، عمر لا شيء
    lecs = []
    for k in range(2):
        l = ad.req("POST", "/api/station/lecture/start", {"course_uid": c1, "duration_sec": 600})[1]["lecture"]; lecs.append(l)
        ad.req("POST", "/api/station/lecture/%s/end" % l["uid"], {})
    def mark(lec, name): ad.req("POST", "/api/admin/attendance/toggle", {"lecture_uid": lec["uid"], "student_uid": next(s["uid"] for s in studs if s["name"] == name), "present": True})
    mark(lecs[0], "علي حسن"); mark(lecs[1], "علي حسن"); mark(lecs[0], "زينب كريم")
    l2 = ad.req("POST", "/api/station/lecture/start", {"course_uid": c2, "duration_sec": 600})[1]["lecture"]
    # ── الدكاترة ──
    s, r = ad.req("POST", "/api/admin/doctors", {"email": "dr1@uoa.edu.iq", "password": "pass1234"}); check("إضافة حساب دكتور", s == 200, r)
    check("إيميل مكرر مرفوض", ad.req("POST", "/api/admin/doctors", {"email": "dr1@uoa.edu.iq", "password": "pass1234"})[0] == 400)
    check("كلمة مرور قصيرة مرفوضة", ad.req("POST", "/api/admin/doctors", {"email": "x@y.iq", "password": "123"})[0] == 400)
    d = Cl(); s, r = d.req("POST", "/api/admin/login", {"username": "DR1@uoa.edu.iq", "password": "pass1234"}); check("دخول الدكتور (الإيميل غير حساس للحروف)", s == 200 and not r["must_change"], r)
    me = d.req("GET", "/api/admin/me")[1]; check("الدور = doctor", me["role"] == "doctor", me)
    cs = d.req("GET", "/api/admin/courses")[1]["courses"]; check("الدكتور يرى مادته فقط", [c["name"] for c in cs] == ["فيزياء"], cs)
    ls = d.req("GET", "/api/admin/lectures")[1]["lectures"]; check("محاضراته فقط (2)", len(ls) == 2, len(ls))
    check("محاضرة مادة غيره غير مرئية", d.req("GET", "/api/admin/lectures/%s" % l2["uid"])[0] == 404)
    check("تصدير مادة غيره ممنوع", d.req("GET", "/api/admin/export?course_uid=%s" % c2, raw=True)[0] == 403)
    check("تعديل حضور محاضرة غيره ممنوع", d.req("POST", "/api/admin/attendance/toggle", {"lecture_uid": l2["uid"], "student_uid": studs[0]["uid"], "present": True})[0] == 403)
    check("الدكتور لا يدير الدكاترة", d.req("GET", "/api/admin/doctors")[0] == 403)
    check("الدكتور لا يضيف مواد", d.req("POST", "/api/admin/courses", {"name": "x", "doctor_email": ""})[0] == 403)
    check("الدكتور لا يرى الطلاب/الإعدادات", d.req("GET", "/api/admin/students")[0] == 403 and d.req("GET", "/api/admin/settings")[0] == 403)
    sm = d.req("GET", "/api/admin/summary")[1]; check("ملخص الدكتور لمادته", sm["courses"] == 1 and sm["lectures"] == 2, sm)
    # ── التقارير ──
    rp = d.req("GET", "/api/admin/reports?course_uid=%s" % c1)[1]
    check("نظرة عامة: مادة واحدة", len(rp["overview"]) == 1)
    dt = rp["detail"]; check("المتوسط = 38% (100+50+0+0)/4 → 38", dt["avg"] in (37, 38), dt["avg"])
    check("المعرَّضون للحرمان: زينب (50%) وعمر ومريم (0%)", dt["risk_count"] == 3 and {x["name"] for x in dt["risky"]} == {"زينب كريم", "عمر ياسر", "مريم علي"}, dt["risky"])
    check("حسب الكروب A و B", [g["grp"] for g in dt["groups"]] == ["A", "B"])
    check("لا تفاصيل لمادة غيره", d.req("GET", "/api/admin/reports?course_uid=%s" % c2)[1]["detail"] is None)
    # ── Excel ──
    s, data = d.req("GET", "/api/admin/export?course_uid=%s" % c1, raw=True); check("الدكتور ينزّل Excel مادته", s == 200 and data[:2] == b"PK")
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(data)); check("أوراق: الحضور + ملخص + كروب A + كروب B", {"الحضور", "ملخص الكروبات", "كروب A", "كروب B"} <= set(wb.sheetnames), wb.sheetnames)
    ws = wb["الحضور"]; hdr = [c.value for c in ws[2]]; check("عمود الحالة", hdr[-1] == "الحالة", hdr)
    rows = {r[1].value: r[-1].value for r in ws.iter_rows(min_row=3)}; check("علي بلا إنذار وغيره بإنذار", rows["علي حسن"] == "—" and rows["زينب كريم"] == "إنذار غياب" and rows["عمر ياسر"] == "إنذار غياب", rows)
    check("ورقة كروب A فيها طالبان", sum(1 for _ in wb["كروب A"].iter_rows(min_row=2)) == 2)
    # الحد قابل للتعديل
    ad.req("PUT", "/api/admin/settings", {"absence_limit": 60}); dt2 = d.req("GET", "/api/admin/reports?course_uid=%s" % c1)[1]["detail"]
    check("رفع حد الإنذار إلى 60% يُخرج زينب", dt2["risk_count"] == 2, dt2["risk_count"])
    check("كلمة مرور خاطئة للدكتور مرفوضة", Cl().req("POST", "/api/admin/login", {"username": "dr1@uoa.edu.iq", "password": "bad"})[0] == 401)
    # تغيير كلمة مرور الدكتور من المسؤول
    did = ad.req("GET", "/api/admin/doctors")[1]["doctors"][0]["id"]; ad.req("PUT", "/api/admin/doctors/%d" % did, {"password": "newpass99"})
    check("كلمة المرور الجديدة تعمل", Cl().req("POST", "/api/admin/login", {"username": "dr1@uoa.edu.iq", "password": "newpass99"})[0] == 200)
    # تفريغ البرنامج
    check("التفريغ بدون كلمة التأكيد مرفوض", ad.req("POST", "/api/admin/wipe", {"what": "all"})[0] == 400)
    check("الدكتور لا يملك التفريغ", d.req("POST", "/api/admin/wipe", {"what": "all", "confirm": "تفريغ"})[0] == 403)
    r = ad.req("POST", "/api/admin/wipe", {"what": "attendance", "confirm": "تفريغ"}); check("تفريغ المحاضرات والحضور", r[0] == 200 and r[1]["attendance"] > 0, r)
    check("لا محاضرات بعد التفريغ", ad.req("GET", "/api/admin/summary")[1]["lectures"] == 0, ad.req("GET", "/api/admin/summary")[1])
    r = ad.req("POST", "/api/admin/wipe", {"what": "all", "confirm": "تفريغ"}); check("تفريغ الكل", r[0] == 200 and r[1]["students"] > 0, r)
    sm = ad.req("GET", "/api/admin/summary")[1]; check("لا طلاب ولا مواد بعد التفريغ", sm["students"] == 0 and sm["courses"] == 0, sm)
    check("الدخول ما زال يعمل", Cl().req("POST", "/api/admin/login", {"username": "dr1@uoa.edu.iq", "password": "newpass99"})[0] == 200)
finally:
    srv.terminate()
print("\nنجح %d — فشل %d" % (OK, FAIL)); sys.exit(1 if FAIL else 0)
