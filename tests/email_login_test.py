# -*- coding: utf-8 -*-
"""دخول الطالب بالرقم الجامعي/البريد فقط + رفع الأرقام بلا بريد + حضور الإيميل المتأخر (لا حاسبة شغالة)."""
import base64, email, io, json, os, sys, tempfile, time
tmp = tempfile.mkdtemp()
os.environ["ATT_DATA"] = tmp; os.environ["ADMIN_USER"], os.environ["ADMIN_PASS"] = "boss", "secret99"
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"))
import app as A, core, db as D, extras as X, mailsync
from openpyxl import Workbook
OK = FAIL = 0
def check(n, c, e=""):
    global OK, FAIL
    if c: OK += 1; print("  ✓", n)
    else: FAIL += 1; print("  ✗", n, e)
app = A.create_app(); adm = app.test_client()
adm.post("/api/admin/login", json={"username": "boss", "password": "secret99"})
c = D.connect(); n = time.time()
c.execute("INSERT INTO colleges(uid,name,updated_at,rev,dirty) VALUES('k1','كلية التقنيات الهندسية',?,1,1)", (n,))
c.execute("INSERT INTO departments(uid,college_uid,name,stages,updated_at,rev,dirty) VALUES('d1','k1','هندسة تقنيات الحاسوب',4,?,1,1)", (n,))
check("النطاق الافتراضي uoa.edu.iq", D.setting(c, "email_domain") == "uoa.edu.iq")
check("الرقم وحده يُكمَل بالنطاق", X.clean_email("1063004760", "uoa.edu.iq") == "1063004760@uoa.edu.iq")
check("البريد الكامل يُقبل", X.clean_email(" 1063004760@UOA.edu.iq ", "uoa.edu.iq") == "1063004760@uoa.edu.iq")
check("نطاق آخر مرفوض", X.clean_email("x@gmail.com", "uoa.edu.iq") is None)

def upload(rows, kind, stage=3, header=None):
    wb = Workbook(); ws = wb.active
    if header: ws.append(header)
    for r in rows: ws.append(r)
    b = io.BytesIO(); wb.save(b); b.seek(0)
    return adm.post("/api/admin/students/upload", data={"file": (b, "x.xlsx"), "dept_uid": "d1", "stage": str(stage), "kind": kind, "mode": "add"}, content_type="multipart/form-data").get_json()

print("رفع الأرقام")
r = upload([[1063004760], [1063004761.0], [1063004762]], "theory")
check("نظري: أرقام فقط → 3 طلاب وبريد لكل واحد تلقائياً", r["ok"] and r["total"] == 3 and r["emails"] == 3, r)
check("البريد = الرقم@uoa.edu.iq", c.execute("SELECT univ_email FROM students WHERE name='1063004761'").fetchone()[0] == "1063004761@uoa.edu.iq")
r = upload([[1063004760, "A1"], [1063004761, "A2"], [1063004762, "B1"]], "practical")
st = {x["name"]: x["grp"] for x in c.execute("SELECT name,grp FROM students")}
check("عملي: A1/A2/B1 تُحدَّث على نفس الطلاب", st == {"1063004760": "A1", "1063004761": "A2", "1063004762": "B1"}, st)
r = upload([[1063004770, "B"], [1063004771, "C"]], "theory")
check("نظري بحرف الكروب فقط (B, C)", {x["name"]: x["grp"] for x in c.execute("SELECT name,grp FROM students WHERE name IN ('1063004770','1063004771')")} == {"1063004770": "B", "1063004771": "C"})
r = upload([["محمد عبد السلام", "A1", "1063004999@uoa.edu.iq"]], "practical", header=["الاسم", "الكروب", "البريد الجامعي"])
check("رفع اسم + كروب + بريد", c.execute("SELECT univ_email,grp FROM students WHERE name='محمد عبد السلام'").fetchone()[:] == ("1063004999@uoa.edu.iq", "A1"), r)
r = adm.put("/api/admin/students/" + c.execute("SELECT uid FROM students WHERE name='1063004770'").fetchone()[0], json={"name": "1063004770", "grp": "B", "email": "1063004770@uoa.edu.iq"})
check("تعديل الطالب وحفظ البريد (الخطأ الذي ظهر في الصورة)", r.status_code == 200, r.get_json())

print("دخول الطالب")
cl = app.test_client()
ro = cl.get("/api/student/roster").get_json()
check("القائمة العامة لا تكشف أسماء الطلاب", ro["students"] == [] and ro["login_mode"] == "email")
r = cl.post("/api/student/email-login", json={"email": "1063004760", "device_id": "phone-1"}).get_json()
check("الرقم فقط يكفي: يُعرف القسم والمرحلة والكروب", r["ok"] and r["student"]["d"] == "هندسة تقنيات الحاسوب" and r["student"]["s"] == 3 and r["student"]["g"] == "A1" and r["student"]["k"] == "كلية التقنيات الهندسية", r)
r = cl.get("/api/student/me?device=phone-1").get_json()
check("الهاتف يتذكر الحساب", r["student"]["n"] == "1063004760" and r["student"]["d"])
r = app.test_client().post("/api/student/email-login", json={"email": "1063004760@uoa.edu.iq", "device_id": "phone-2"}).get_json()
check("رقم مسجّل على هاتف آخر يُرفض مع خيار طلب التغيير", (not r["ok"]) and r["can_request_change"])
check("رقم غير موجود", app.test_client().post("/api/student/email-login", json={"email": "999999999", "device_id": "z"}).status_code == 404)

print("الإيميل يصل متأخراً (بدون حاسبة شغالة)")
D.set_setting(c, "imap_host", "imap.fake"); D.set_setting(c, "attendance_mailbox", "att@gmail.com")
c.execute("INSERT INTO courses(uid,name,doctor_email,college_uid,dept_uid,stage,kind,updated_at,rev,dirty) VALUES('cr','شبكات','d@x',?,?,3,'theory',?,1,1)", ("k1", "d1", n))
start = n - 3 * 86400
c.execute("INSERT INTO lectures(uid,code,course_uid,secret,start_ts,end_ts,interval_sec,status,station,grp,updated_at,rev,dirty) VALUES('lx','OLD123','cr','sec',?,?,3,'ended','',?,?,1,1)", (start, start + 900, "", n))
lec = c.execute("SELECT * FROM lectures WHERE uid='lx'").fetchone()
uid = c.execute("SELECT uid FROM students WHERE name='1063004760'").fetchone()[0]
t, i, sg = core.make_token(lec, at=start + 60)
print("   (t=%s)" % t)
class FakeSmtp:
    def __init__(s): s.sent = []
    def send(s, m): s.sent.append(m)
class FakeImap:
    def __init__(s, msgs): s.msgs, s.seen = msgs, set()
    def __enter__(s): return s
    def __exit__(s, *a): pass
    def unseen(s, subj): return [(k, m) for k, m in enumerate(s.msgs) if k not in s.seen and (m["Subject"] or "").startswith(subj)]
    def mark_seen(s, k): s.seen.add(k)
def mail(recv_ts):
    from email.utils import formatdate
    payload = {"v": 1, "device_id": "phone-1", "items": [{"id": "m1", "code": "OLD123", "t": t, "i": i, "sig": sg, "student": uid, "age": 1.0, "elapsed": 1.0, "unsynced": True}]}
    m = email.message.EmailMessage(); m["Subject"] = "ATT-STU"; m["From"] = "s@gmail.com"
    m["Received"] = "by 2002:a05:6a20 with SMTP id x; " + formatdate(recv_ts, usegmt=True)
    m.set_content("ATT:" + base64.b64encode(json.dumps(payload).encode()).decode() + ":END")
    return email.message_from_bytes(m.as_bytes())
if sg:
    res = mailsync.receive_student_mails({"sync_key": "k"}, FakeImap([mail(start + 3600)]), FakeSmtp())
    check("إيميل وصل جيميل بعد ساعة من المحاضرة ← يُحتسب حاضراً حتى لو فُتح البرنامج بعد 3 أيام", res[0] == 1 and c.execute("SELECT status FROM attendance WHERE student_uid=?", (uid,)).fetchone()[0] == "ok", res)
    c.execute("DELETE FROM attendance")
    res = mailsync.receive_student_mails({"sync_key": "k"}, FakeImap([mail(time.time() - 3600)]), FakeSmtp())
    check("إيميل وصل جيميل بعد انتهاء مهلة الاستلام ← يُرفض (متأخر جداً)", res[0] == 0 and res[1] == 1, res)
else:
    check("(تعذّر بناء رمز قديم)", False)
print("\nنجح %d — فشل %d" % (OK, FAIL)); sys.exit(1 if FAIL else 0)
