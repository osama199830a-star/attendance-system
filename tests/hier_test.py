# -*- coding: utf-8 -*-
"""الكليات والأقسام والمراحل + تسلسل الصلاحيات: رئيس الجامعة ← عميد ← رئيس قسم ← مقرر ← تدريسي، ورفع الأسماء (نظري/عملي)."""
import json, os, subprocess, sys, tempfile, time, urllib.request, urllib.error, http.cookiejar, io
HERE = os.path.dirname(os.path.abspath(__file__)); SRV = os.path.join(os.path.dirname(HERE), "server")
tmp = tempfile.mkdtemp(); os.environ["ATT_DATA"] = tmp; sys.path.insert(0, SRV)
import core
PORT = 15077; BASE = "http://127.0.0.1:%d" % PORT
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
    def req(s, m, p, d=None, form=None, files=None):
        h = {"Content-Type": "application/json"}; data = json.dumps(d).encode() if d is not None else None
        if files is not None:
            bd = "XX"; parts = b""
            for k, v in (form or {}).items(): parts += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (bd, k, v)).encode()
            parts += ("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"s.xlsx\"\r\n\r\n" % bd).encode() + files + ("\r\n--%s--\r\n" % bd).encode()
            data, h = parts, {"Content-Type": "multipart/form-data; boundary=" + bd}
        r = urllib.request.Request(BASE + p, data=data, method=m, headers=h)
        try: resp = s.o.open(r); return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            try: return e.code, json.loads(e.read().decode())
            except Exception: return e.code, {}
    def login(s, u, p): return s.req("POST", "/api/admin/login", {"username": u, "password": p})[0]
def xlsx(rows):
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active
    for r in rows: ws.append(r)
    b = io.BytesIO(); wb.save(b); return b.getvalue()
try:
    ad = Cl(); check("دخول رئيس الجامعة", ad.login("admin", "admin123") == 200)
    k1 = ad.req("POST", "/api/admin/colleges", {"name": "كلية العلوم"})[1]["uid"]; k2 = ad.req("POST", "/api/admin/colleges", {"name": "كلية الهندسة"})[1]["uid"]
    check("اسم كلية مكرر مرفوض", ad.req("POST", "/api/admin/colleges", {"name": "كلية العلوم"})[0] == 400)
    d1 = ad.req("POST", "/api/admin/departments", {"college_uid": k1, "name": "الفيزياء", "stages": 4})[1]["uid"]
    d1b = ad.req("POST", "/api/admin/departments", {"college_uid": k1, "name": "الكيمياء", "stages": 3})[1]["uid"]
    d2 = ad.req("POST", "/api/admin/departments", {"college_uid": k2, "name": "المدني", "stages": 5})[1]["uid"]
    check("مراحل القسم > 8 مرفوض", ad.req("POST", "/api/admin/departments", {"college_uid": k1, "name": "س", "stages": 9})[0] == 400)
    # عميد
    check("إنشاء عميد بلا كلية مرفوض", ad.req("POST", "/api/admin/users", {"role": "dean", "username": "dean1", "password": "secret1"})[0] == 400)
    check("إنشاء عميد كلية العلوم", ad.req("POST", "/api/admin/users", {"role": "dean", "username": "dean1", "password": "secret1", "college_uid": k1})[0] == 200)
    ad.req("POST", "/api/admin/users", {"role": "dean", "username": "dean2", "password": "secret2", "college_uid": k2})
    dn = Cl(); check("دخول العميد", dn.login("dean1", "secret1") == 200)
    org = dn.req("GET", "/api/admin/org")[1]; check("العميد يرى كليته وأقسامها فقط", [c["name"] for c in org["colleges"]] == ["كلية العلوم"] and len(org["departments"]) == 2, org)
    check("العميد لا يضيف كلية", dn.req("POST", "/api/admin/colleges", {"name": "x"})[0] == 403)
    dn_dep = dn.req("POST", "/api/admin/departments", {"college_uid": k2, "name": "الحاسبات", "stages": 4}); check("العميد يضيف قسماً (يُجبر على كليته)", dn_dep[0] == 200)
    check("العميد لا يضيف عميداً", dn.req("POST", "/api/admin/users", {"role": "dean", "username": "dx", "password": "secret1", "college_uid": k1})[0] == 403)
    check("العميد لا يضيف رئيس قسم في كلية أخرى", dn.req("POST", "/api/admin/users", {"role": "head", "username": "hx", "password": "secret1", "dept_uid": d2})[0] == 400)
    check("إنشاء رئيس قسم بتفويض", dn.req("POST", "/api/admin/users", {"role": "head", "username": "head1", "password": "secret1", "dept_uid": d1, "perms": ["courses", "students", "lectures", "reports"], "can_delegate": True})[0] == 200)
    check("إنشاء رئيس قسم بلا تفويض", dn.req("POST", "/api/admin/users", {"role": "head", "username": "head2", "password": "secret1", "dept_uid": d1b, "perms": ["courses", "students"]})[0] == 200)
    # مواد
    dn_c = dn.req("POST", "/api/admin/courses", {"name": "ميكانيك", "doctor_email": "dr1@uoa.edu.iq", "dept_uid": d1, "stage": 1, "kind": "theory"}); check("العميد ينشئ مادة نظرية", dn_c[0] == 200, dn_c)
    check("مرحلة خارج عدد مراحل القسم مرفوضة", dn.req("POST", "/api/admin/courses", {"name": "x", "dept_uid": d1b, "stage": 4, "kind": "theory"})[0] == 400)
    check("نوع مادة خاطئ مرفوض", dn.req("POST", "/api/admin/courses", {"name": "x", "dept_uid": d1, "stage": 1, "kind": "zzz"})[0] == 400)
    check("العميد لا ينشئ مادة في قسم كلية أخرى", dn.req("POST", "/api/admin/courses", {"name": "x", "dept_uid": d2, "stage": 1, "kind": "theory"})[0] == 400)
    ad_c = ad.req("POST", "/api/admin/courses", {"name": "إنشاءات", "doctor_email": "dr9@uoa.edu.iq", "dept_uid": d2, "stage": 1, "kind": "practical"})[1]["uid"]
    names = [d["name"] for d in dn.req("GET", "/api/admin/courses")[1]["courses"]]; check("العميد لا يرى مواد كلية أخرى", names == ["ميكانيك"], names)
    check("العميد لا يعدّل مادة كلية أخرى", dn.req("PUT", "/api/admin/courses/%s" % ad_c, {"name": "هك", "dept_uid": d2, "stage": 1, "kind": "theory"})[0] == 403)
    # رئيس القسم: رفع أسماء نظري
    hd = Cl(); hd.login("head1", "secret1")
    r = hd.req("POST", "/api/admin/students/upload", {"dept_uid": ""}, form={"stage": "1", "kind": "theory"}, files=xlsx([["اسم الطالب"], ["علي حسن كاظم"], ["زينب كريم جاسم"], ["عمر ياسر عباس"], ["مريم علي صالح"]]))
    check("رئيس القسم يرفع أسماء نظري (القسم يُفرض من حسابه)", r[0] == 200 and r[1]["added"] == 4, r)
    r = hd.req("POST", "/api/admin/students/upload", form={"stage": "1", "kind": "practical"}, files=xlsx([["اسم الطالب", "الكروب"], ["علي حسن كاظم", "A"], ["زينب كريم جاسم", "A"], ["عمر ياسر عباس", "B"], ["مريم علي صالح", "B"], ["حسين عادل", "B"]]))
    check("الرفع العملي: يحدّث الكروبات ويضيف الجديد بلا تكرار", r[0] == 200 and r[1]["added"] == 1 and r[1]["updated"] == 4, r)
    sts = hd.req("GET", "/api/admin/students")[1]; check("5 طلاب بكروبات A/B", sts["total"] == 5 and sts["groups"] == ["A", "B"], sts)
    r = hd.req("POST", "/api/admin/students/upload", form={"stage": "9", "kind": "theory"}, files=xlsx([["x"], ["a b c"]])); check("مرحلة غير صحيحة مرفوضة", r[0] == 400)
    r = hd.req("POST", "/api/admin/students/upload", form={"stage": "2", "kind": "theory"}, files=xlsx([["اسم الطالب"], ["علي حسن كاظم"]])); check("نفس الاسم في مرحلة أخرى طالب مستقل", r[0] == 200 and r[1]["added"] == 1, r)
    r = hd.req("POST", "/api/admin/students/upload", form={"stage": "1", "kind": "theory", "mode": "replace"}, files=xlsx([["اسم الطالب"], ["علي حسن كاظم"], ["زينب كريم جاسم"]]))
    check("استبدال المرحلة 1 يحذف الباقي فيها فقط", r[0] == 200 and r[1]["removed"] == 3, r)
    check("المرحلة 2 لم تتأثر", hd.req("GET", "/api/admin/students?stage=2")[1]["total"] >= 1 and len(hd.req("GET", "/api/admin/students?stage=2")[1]["students"]) == 1)
    hd.req("POST", "/api/admin/students/upload", form={"stage": "1", "kind": "practical"}, files=xlsx([["اسم الطالب", "الكروب"], ["عمر ياسر عباس", "B"], ["مريم علي صالح", "B"], ["حسين عادل", "B"]]))
    # تفويض: رئيس القسم يحدد مقرر القسم ضمن صلاحياته فقط
    r = hd.req("POST", "/api/admin/users", {"role": "rapporteur", "username": "rap1", "password": "secret1", "perms": ["lectures", "doctors", "unbind"]})
    check("رئيس القسم (مفوّض) ينشئ مقرراً", r[0] == 200, r)
    rp = Cl(); rp.login("rap1", "secret1")
    me = rp.req("GET", "/api/admin/me")[1]; check("صلاحيات المقرر لا تتجاوز صلاحيات رئيس القسم (بلا doctors/unbind)", me["perms"] == ["lectures"] and me["role"] == "rapporteur", me)
    check("المقرر لا ينشئ مواد", rp.req("POST", "/api/admin/courses", {"name": "x", "doctor_email": "a@b.c", "stage": 1, "kind": "theory"})[0] == 403)
    check("المقرر لا يرفع طلاباً", rp.req("POST", "/api/admin/students", {"name": "طالب جديد", "stage": 1})[0] == 403)
    check("المقرر يرى محاضرات قسمه", rp.req("GET", "/api/admin/lectures")[0] == 200)
    check("المقرر لا يرى التقارير (لم تُمنح)", rp.req("GET", "/api/admin/reports")[0] == 403)
    h2 = Cl(); h2.login("head2", "secret1")
    check("رئيس قسم بلا تفويض لا ينشئ مقرراً", h2.req("POST", "/api/admin/users", {"role": "rapporteur", "username": "rapx", "password": "secret1", "perms": ["lectures"]})[0] == 403)
    check("رئيس القسم بلا صلاحية الدكاترة لا ينشئ دكتوراً", h2.req("POST", "/api/admin/users", {"role": "doctor", "email": "dx@uoa.edu.iq", "password": "secret1"})[0] == 403)
    check("رئيس القسم لا يعدّل صلاحيات رئيس قسم آخر", hd.req("PUT", "/api/admin/users/%d" % [u for u in dn.req("GET", "/api/admin/users")[1]["users"] if u["username"] == "head2"][0]["id"], {"perms": ["courses"]})[0] == 404)
    users = dn.req("GET", "/api/admin/users")[1]["users"]; check("العميد يرى رئيسَي القسم والمقرر", {u["username"] for u in users} >= {"head1", "head2", "rap1"})
    h1id = [u for u in users if u["username"] == "head1"][0]["id"]
    check("العميد يعدّل صلاحيات رئيس القسم", dn.req("PUT", "/api/admin/users/%d" % h1id, {"perms": ["courses", "students", "lectures", "reports", "doctors"]})[0] == 200)
    # تدريسي
    check("العميد ينشئ تدريسياً في قسمه", dn.req("POST", "/api/admin/users", {"role": "doctor", "email": "dr1@uoa.edu.iq", "password": "secret1", "dept_uid": d1})[0] == 200)
    dr = Cl(); dr.login("dr1@uoa.edu.iq", "secret1")
    check("التدريسي يرى مادته فقط", [c["name"] for c in dr.req("GET", "/api/admin/courses")[1]["courses"]] == ["ميكانيك"])
    check("التدريسي لا يرى الطلاب ولا يرفع", dr.req("GET", "/api/admin/students")[0] == 403 and dr.req("POST", "/api/admin/users", {"role": "doctor", "email": "z@z.zz", "password": "secret1"})[0] == 403)
    # تسجيل حضور: طالب قسم آخر يُرفض
    cu = dn_c[1]["uid"]
    lec = ad.req("POST", "/api/station/lecture/start", {"course_uid": cu, "duration_sec": 600})[1]["lecture"]
    stu = {s["name"]: s["uid"] for s in hd.req("GET", "/api/admin/students?stage=1")[1]["students"]}
    ad.req("POST", "/api/admin/students", {"name": "طالب مدني", "dept_uid": d2, "stage": 1})
    other = [s for s in ad.req("GET", "/api/admin/students?dept_uid=%s" % d2)[1]["students"]][0]["uid"]
    def sub(dev, st):
        t, i, sig = core.make_token(lec); it = dict(code=lec["code"], t=t, i=i, sig=sig, queued=False, elapsed=1.0, age=1.0, student=st, id="1")
        return ad.req("POST", "/api/student/submit", {"device_id": dev, "items": [it]})[1]["results"][0]
    r = sub("devA", stu["علي حسن كاظم"]); check("طالب القسم والمرحلة يسجَّل", r["status"] == "ok", r)
    r = sub("devB", other); check("طالب قسم آخر يُرفض (not_enrolled)", r["reason"] == "not_enrolled", r)
    # التصدير: طلاب مرحلة المادة فقط
    from openpyxl import load_workbook
    req = urllib.request.Request(BASE + "/api/admin/export?course_uid=" + cu); 
    data = dn.o.open(req).read(); ws = load_workbook(io.BytesIO(data))["الحضور"]
    ns = [r[1].value for r in ws.iter_rows(min_row=3) if r[1].value]; check("Excel المادة يضم طلاب القسم/المرحلة فقط (5)", len(ns) == 5 and "طالب مدني" not in ns, ns)
    # الرئيس يحذف المقرر؛ مقرر محذوف لا يدخل
    rid = [u for u in dn.req("GET", "/api/admin/users")[1]["users"] if u["username"] == "rap1"][0]["id"]
    check("حذف المقرر", dn.req("DELETE", "/api/admin/users/%d" % rid)[0] == 200 and Cl().login("rap1", "secret1") == 401)
    # نسخة احتياطية
    req = urllib.request.Request(BASE + "/api/admin/backup"); b = ad.o.open(req).read(); check("تنزيل نسخة احتياطية SQLite", b[:6] == b"SQLite")
    check("العميد لا ينزّل النسخة الاحتياطية", dn.req("GET", "/api/admin/backup")[0] == 403)
    check("العميد لا يفرّغ البرنامج", dn.req("POST", "/api/admin/wipe", {"confirm": "تفريغ"})[0] == 403)
    # الروستر للطالب فيه الهيكل
    ro = json.loads(urllib.request.urlopen(BASE + "/api/student/roster").read().decode()); check("قائمة الطالب فيها الكليات والأقسام وقسم/مرحلة كل طالب", len(ro["org_tree"]["colleges"]) == 2 and any(s.get("d") == d1 and s.get("s") == 1 for s in ro["students"]), list(ro)[:4])
finally:
    srv.terminate()
print("\nنجح %d — فشل %d" % (OK, FAIL)); sys.exit(1 if FAIL else 0)
