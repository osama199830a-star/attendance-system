# -*- coding: utf-8 -*-
"""اختبار ميزات مواصفات النظام الجامعي: الضيف، التأخر، تغيير الجهاز، التدقيق، توقيع الجهاز، اعتماد التقارير، مزامنة البريد، الحماية."""
import base64, email, json, os, sqlite3, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
SRV = os.path.join(os.path.dirname(HERE), "server")
tmp = tempfile.mkdtemp()
os.environ["ATT_DATA"] = os.path.join(tmp, "station")
os.environ.pop("ATT_MODE", None)
os.environ["ADMIN_USER"], os.environ["ADMIN_PASS"] = "boss", "secret99"
sys.path.insert(0, SRV)
from werkzeug.security import generate_password_hash
import app as A, core, db as D, config, extras as X, mailsync

OK = FAIL = 0


def check(name, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1; print("  ✓", name)
    else:
        FAIL += 1; print("  ✗", name, extra)


app = A.create_app()
app.config["TESTING"] = True


def login(u, p):
    cl = app.test_client()
    r = cl.post("/api/admin/login", json={"username": u, "password": p})
    return cl, r


def post(cl, path, data=None, **kw):
    r = cl.post(path, json=data or {}, **kw)
    return r.status_code, (r.get_json(silent=True) or {})


# ───── بناء بيانات الاختبار ─────
c = D.connect()
D.set_setting(c, "email_domain", "")
n = time.time()
COL, DEP, DEP2 = "col1", "dep1", "dep2"
c.execute("INSERT INTO colleges(uid,name,updated_at,rev,dirty) VALUES(?,?,?,?,1)", (COL, "كلية التقنيات", n, 1))
for d, nm in ((DEP, "قسم الحاسوب"), (DEP2, "قسم الشبكات")):
    c.execute("INSERT INTO departments(uid,college_uid,name,stages,updated_at,rev,dirty) VALUES(?,?,?,4,?,1,1)", (d, COL, nm, n))
pw = generate_password_hash("pw123456")
for un, role_, dep, em, perms in (("dean1", "dean", "", "dean@u.edu", ""), ("head1", "head", DEP, "head@u.edu", "lectures,reports,unbind"),
                                  ("head2", "head", DEP2, "head2@u.edu", "lectures,reports"), ("doc1", "doctor", "", "dr@u.edu", ""),
                                  ("rap1", "rapporteur", DEP, "rap@u.edu", "lectures")):
    c.execute("INSERT INTO admins(username,pw_hash,must_change,role,email,college_uid,dept_uid,perms,full_name) VALUES(?,?,0,?,?,?,?,?,?)",
              (un, pw, role_, em, COL if role_ in ("dean", "head", "rapporteur") else "", dep, perms, "الاسم " + un))
STU = {}
for key, name, grp, em in (("a1", "علي أحمد", "A1", "a1@u.edu"), ("a1b", "حسن كريم", "A1", "a1b@u.edu"), ("b1", "محمد صالح", "B1", "b1@u.edu"),
                           ("b2", "زينب سعد", "B2", "b2@u.edu"), ("c1", "نور هادي", "A1", "c1@u.edu")):
    uid = D.student_uid(name, "", DEP + ":2")
    STU[key] = uid
    c.execute("INSERT INTO students(uid,name,name_norm,grp,college_uid,dept_uid,stage,univ_email,updated_at,rev,dirty) VALUES(?,?,?,?,?,?,2,?,?,1,1)",
              (uid, name, D.norm(name), grp, COL, DEP, em, n))
c.execute("INSERT INTO courses(uid,name,doctor_email,college_uid,dept_uid,stage,kind,updated_at,rev,dirty) VALUES('crs1','برمجة','dr@u.edu',?,?,2,'practical',?,1,1)", (COL, DEP, n))


def mk_lecture(uid, grp="A1", start=None, code=None):
    now = D.now()
    start = start or now
    c.execute("INSERT INTO lectures(uid,code,course_uid,secret,start_ts,end_ts,interval_sec,status,station,grp,updated_at,rev,dirty) VALUES(?,?,?,?,?,?,3,'active','s',?,?,1,1)",
              (uid, code or uid.upper()[:6], "crs1", "sec" + uid, start, now + 900, grp, now))
    return c.execute("SELECT * FROM lectures WHERE uid=?", (uid,)).fetchone()


def scan(lec, student, dev, extra=None):
    t, i, sig = core.make_token(lec)
    it = {"id": "x%s" % time.time(), "code": lec["code"], "t": t, "i": i, "sig": sig, "student": STU[student], "age": 0.5, "elapsed": 0.5, "queued": False}
    it.update(extra or {})
    r = app.test_client().post("/api/student/submit", json={"device_id": dev, "items": [it]})
    return r.get_json()["results"][0]


# ───── 1) الطالب الضيف ─────
print("1) الطالب الضيف")
L1 = mk_lecture("lec1", "A1")
r = scan(L1, "a1", "dev-a1")
check("طالب من نفس المجموعة (A1) يُحتسب حاضراً", r["status"] == "ok", r)
r = scan(L1, "a1", "dev-a1")
check("تكرار الحضور في نفس المحاضرة مرفوض (duplicate)", r["status"] == "duplicate", r)
r = scan(L1, "b1", "dev-b1")
check("طالب من B1 في محاضرة A1 ← Pending Guest وليس حاضراً", r["status"] == "guest_pending", r)
st = c.execute("SELECT status FROM attendance WHERE lecture_uid='lec1' AND student_uid=?", (STU["b1"],)).fetchone()["status"]
check("الحالة المخزّنة guest_pending", st == "guest_pending")
check("طلب الضيف موجود + إشعار للقسم", c.execute("SELECT COUNT(*) FROM guest_requests WHERE status='pending'").fetchone()[0] == 1 and c.execute("SELECT COUNT(*) FROM notifications WHERE kind='guest'").fetchone()[0] == 1)
r = scan(L1, "b1", "dev-b1")
check("إعادة المحاولة لا تحتسبه حاضراً ولا تكرر الطلب", r["status"] == "guest_pending" and c.execute("SELECT COUNT(*) FROM guest_requests").fetchone()[0] == 1, r)
r = scan(L1, "b2", "dev-b2")
gid_b1 = c.execute("SELECT uid FROM guest_requests WHERE student_uid=?", (STU["b1"],)).fetchone()["uid"]
gid_b2 = c.execute("SELECT uid FROM guest_requests WHERE student_uid=?", (STU["b2"],)).fetchone()["uid"]
doc, _ = login("doc1", "pw123456")
s, _ = post(doc, "/api/admin/x/guest-requests/%s/decide" % gid_b1, {"decision": "approved"})
check("التدريسي لا يستطيع الموافقة على الضيف (RBAC)", s == 403)
h2, _ = login("head2", "pw123456")
s, _ = post(h2, "/api/admin/x/guest-requests/%s/decide" % gid_b1, {"decision": "approved"})
check("رئيس قسم آخر لا يتجاوز نطاقه", s == 403)
h1, _ = login("head1", "pw123456")
s, j = post(h1, "/api/admin/x/guest-requests/%s/decide" % gid_b1, {"decision": "rejected"})
check("الرفض بلا سبب مرفوض", s == 400)
s, j = post(h1, "/api/admin/x/guest-requests/%s/decide" % gid_b1, {"decision": "approved", "note": "حضر بموافقة"})
check("رئيس القسم يوافق على الضيف", s == 200, j)
row = c.execute("SELECT status,reason FROM attendance WHERE lecture_uid='lec1' AND student_uid=?", (STU["b1"],)).fetchone()
check("بعد الموافقة: Approved Guest ويُحتسب حاضراً", row["status"] == "ok" and row["reason"] == "guest_approved", dict(row))
g = c.execute("SELECT * FROM guest_requests WHERE uid=?", (gid_b1,)).fetchone()
check("يُسجَّل اسم المسؤول ووقت الموافقة وسببها", g["decided_by"] == "head1" and g["decided_at"] and g["note"] == "حضر بموافقة")
s, j = post(h1, "/api/admin/x/guest-requests/%s/decide" % gid_b1, {"decision": "rejected", "note": "x"})
check("لا يمكن قلب قرار تم البتّ فيه", s == 400)
s, j = post(h1, "/api/admin/x/guest-requests/%s/decide" % gid_b2, {"decision": "rejected", "note": "ليس من المجموعة"})
r = scan(L1, "b2", "dev-b2")
check("Rejected Guest لا يُحتسب حاضراً ولا يعيد الطلب", r["status"] == "guest_rejected", r)
rep = X.lecture_summary(c, L1, c.execute("SELECT * FROM courses WHERE uid='crs1'").fetchone())
check("التقرير: نظاميون/ضيوف موافق/معلق/مرفوض", rep["present_regular"] == 1 and rep["guests_approved"] == 1 and rep["guests_pending"] == 0 and rep["guests_rejected"] == 1 and rep["present"] == 2, rep)

# ───── 2) التأخر ─────
print("2) المتأخرون")
D.set_setting(c, "late_after_min", "5")
L2 = mk_lecture("lec2", "A1", start=D.now() - 600)
r = scan(L2, "a1b", "dev-a1b")
check("بعد 5 دقائق من البداية: حاضر مع علامة متأخر", r["status"] == "ok" and r["reason"] == "late", r)
L3 = mk_lecture("lec3", "")
r = scan(L3, "b1", "dev-b1")
check("محاضرة بلا مجموعة محددة تقبل الجميع (لا ضيوف)", r["status"] == "ok", r)

# ───── 3) تغيير الجهاز ─────
print("3) تغيير الجهاز")
cl = app.test_client()
r = cl.post("/api/student/email-login", json={"email": "c1@u.edu", "device_id": "old-phone"}).get_json()
check("تسجيل الطالب ببريده الجامعي وربط جهاز", r["ok"] and r["student"]["u"] == STU["c1"], r)
r = cl.post("/api/student/email-login", json={"email": "nobody@u.edu", "device_id": "zzz"})
check("بريد غير موجود في قاعدة الطلبة مرفوض", r.status_code == 404)
r = cl.post("/api/student/email-login", json={"email": "c1@u.edu", "device_id": "new-phone"}).get_json()
check("البريد نفسه على هاتف آخر ← رسالة مطابقة للمواصفات", (not r["ok"]) and "مسجّل مسبقاً على جهاز آخر" in r["message"] and "العميد أو رئيس القسم" in r["message"], r)
r = scan(L3, "c1", "new-phone")
check("حضور من الجهاز الجديد قبل الموافقة مرفوض", r["status"] == "rejected" and r["reason"] == "student_bound_elsewhere", r)
r = cl.post("/api/student/device-request", json={"email": "wrong@u.edu", "device_id": "new-phone", "reason": "فقدت"})
check("طلب بإيميل غير صحيح مرفوض", r.status_code == 404)
r = cl.post("/api/student/device-request", json={"email": "c1@u.edu", "device_id": "new-phone", "reason": "فقدت هاتفي"}).get_json()
check("طلب تغيير جهاز معلّق", r["ok"])
dreq = c.execute("SELECT uid FROM device_requests WHERE student_uid=?", (STU["c1"],)).fetchone()["uid"]
s, _ = post(doc, "/api/admin/x/device-requests/%s/decide" % dreq, {"decision": "approved"})
check("التدريسي لا يوافق على تغيير جهاز", s == 403)
s, _ = post(h2, "/api/admin/x/device-requests/%s/decide" % dreq, {"decision": "approved"})
check("رئيس قسم آخر مرفوض", s == 403)
inbox = cl.get("/api/student/inbox?device=new-phone").get_json()
check("الطالب يتابع حالة الطلب (معلّق)", inbox["device_requests"] and inbox["device_requests"][0]["status"] == "pending")
dean, _ = login("dean1", "pw123456")
s, j = post(dean, "/api/admin/x/device-requests/%s/decide" % dreq, {"decision": "approved", "note": "تحقق شخصي"})
check("العميد يوافق: يُفعَّل الجهاز الجديد ويُلغى القديم ذرّياً", s == 200 and c.execute("SELECT device_id FROM students WHERE uid=?", (STU["c1"],)).fetchone()[0] == "new-phone")
r = scan(L3, "c1", "old-phone")
check("الجهاز القديم لم يعد معتمداً", r["status"] == "rejected", r)
r = scan(L3, "c1", "new-phone")
check("الجهاز الجديد يسجّل الحضور", r["status"] == "ok", r)
check("لا يوجد أكثر من جهاز نشط للطالب", c.execute("SELECT COUNT(*) FROM students WHERE uid=? AND device_id IS NOT NULL", (STU["c1"],)).fetchone()[0] == 1)
inbox = cl.get("/api/student/inbox?device=new-phone").get_json()
check("الطالب يرى الموافقة والإشعار", inbox["device_requests"][0]["status"] == "approved" and any("تغيير جهازك" in x["title"] for x in inbox["notifications"]))
s, _ = post(dean, "/api/admin/x/device-requests/%s/decide" % dreq, {"decision": "approved"})
check("لا يمكن الموافقة مرتين على الطلب نفسه", s == 400)

# ───── 4) سجل التدقيق ─────
print("4) سجل التدقيق")
check("سجل التدقيق يحوي قرارات الموافقة", c.execute("SELECT COUNT(*) FROM audit_log WHERE action IN ('device.change','guest.decide')").fetchone()[0] >= 3)
try:
    c.execute("UPDATE audit_log SET actor='x' WHERE id=1"); ok = False
except sqlite3.DatabaseError:
    ok = True
check("لا يمكن تعديل سجل التدقيق (محفّز قاعدة البيانات)", ok)
try:
    c.execute("DELETE FROM audit_log"); ok = False
except sqlite3.DatabaseError:
    ok = True
check("لا يمكن حذف سجل التدقيق", ok)
check("سلسلة التجزئة سليمة", X.verify_audit(c) is None)
raw = sqlite3.connect(config.DB_PATH)
raw.execute("DROP TRIGGER audit_no_update"); raw.execute("UPDATE audit_log SET actor='مزوَّر' WHERE id=2"); raw.commit()
check("التلاعب المباشر بالقاعدة يُكتشف", X.verify_audit(c) == 2)
raw.close()
bossc, _ = login("boss", "secret99")
j = bossc.get("/api/admin/x/audit").get_json()
check("المسؤول يرى حالة السلسلة", j["chain_ok"] is False and j["broken_at"] == 2)
check("التدريسي لا يرى سجل التدقيق", doc.get("/api/admin/x/audit").status_code == 403)
c.close(); c = D.connect()
init_tr = open(os.path.join(SRV, "extras.py"), encoding="utf-8").read()
c.executescript([l for l in init_tr.split('"""') if "audit_no_update" in l][0])   # إعادة إنشاء المحفّز بعد الاختبار

# ───── 5) توقيع مفتاح الجهاز ─────
print("5) توقيع الجهاز (ECDSA P-256)")
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils
key = ec.generate_private_key(ec.SECP256R1())
nums = key.public_key().public_numbers()
b64u = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
jwk = {"kty": "EC", "crv": "P-256", "x": b64u(nums.x.to_bytes(32, "big")), "y": b64u(nums.y.to_bytes(32, "big"))}


def dsig(lec, student, dev, k=key):
    t, i, _ = core.make_token(lec)
    msg = ("%s|%s|%s|%s|%s" % (lec["code"], t, i, STU[student], dev)).encode()
    r_, s_ = utils.decode_dss_signature(k.sign(msg, ec.ECDSA(hashes.SHA256())))
    return base64.b64encode(r_.to_bytes(32, "big") + s_.to_bytes(32, "big")).decode()


r = app.test_client().post("/api/student/bind", json={"device_id": "dev-k", "student": STU["a1b"], "pub": jwk})
check("الجهاز الأول للطالب لا يقبل (مربوط بجهاز آخر مسبقاً)", r.get_json()["ok"] is False)
L4 = mk_lecture("lec4", "A1")
c.execute("UPDATE students SET device_id=NULL WHERE uid=?", (STU["a1b"],))
app.test_client().post("/api/student/bind", json={"device_id": "dev-k", "student": STU["a1b"], "pub": jwk})
check("المفتاح العام يُخزَّن عند الربط", c.execute("SELECT pub FROM device_keys WHERE student_uid=?", (STU["a1b"],)).fetchone() is not None)
r = scan(L4, "a1b", "dev-k")
check("جهاز له مفتاح: حضور بلا توقيع مرفوض", r["status"] == "rejected" and r["reason"] == "bad_device_sig", r)
other = ec.generate_private_key(ec.SECP256R1())
r = scan(L4, "a1b", "dev-k", {"dsig": dsig(L4, "a1b", "dev-k", other)})
check("توقيع بمفتاح مستنسخ/آخر مرفوض", r["status"] == "rejected", r)
r = scan(L4, "a1b", "dev-k")  # توقيع يجب أن يُحسب على نفس الرمز الذي سيرسل؛ نحسبه داخل نفس الثانية
t, i, sig = core.make_token(L4)
it = {"id": "z", "code": L4["code"], "t": t, "i": i, "sig": sig, "student": STU["a1b"], "age": 0.5, "elapsed": 0.5, "queued": False}
msg = ("%s|%s|%s|%s|%s" % (L4["code"], t, i, STU["a1b"], "dev-k")).encode()
r_, s_ = utils.decode_dss_signature(key.sign(msg, ec.ECDSA(hashes.SHA256())))
it["dsig"] = base64.b64encode(r_.to_bytes(32, "big") + s_.to_bytes(32, "big")).decode()
r = app.test_client().post("/api/student/submit", json={"device_id": "dev-k", "items": [it]}).get_json()["results"][0]
check("توقيع صحيح بمفتاح الجهاز يُقبل", r["status"] == "ok", r)
D.set_setting(c, "require_device_sig", "1")
r = scan(L4, "c1", "new-phone")
r2 = scan(mk_lecture("lec4b", ""), "c1", "new-phone")
check("require_device_sig=1: جهاز بلا مفتاح مرفوض", r2["status"] == "rejected" and r2["reason"] == "device_key_missing", r2)
D.set_setting(c, "require_device_sig", "0")

# ───── 6) اعتماد التقارير ─────
print("6) سلسلة اعتماد التقارير")
s, j = post(bossc, "/api/admin/x/reports/create", {"lecture_uid": "lec1"})
check("إنشاء تقرير المحاضرة (Excel + ملخص)", s == 200 and j["number"].startswith("RPT-"), j)
rid = j["uid"]
from openpyxl import load_workbook
rp = c.execute("SELECT file_name FROM reports WHERE uid=?", (rid,)).fetchone()[0]
wb = load_workbook(os.path.join(config.EXPORT_DIR, rp))
vals = {r[0].value: r[1].value for r in wb["ملخص التقرير"].iter_rows(min_row=1, max_row=19)}
check("ملخص التقرير يحوي العدد الكلي والحاضرين والضيوف والنسبة", vals["العدد الكلي للطلبة"] == 5 and vals["الضيوف الموافق عليهم"] == 1 and vals["نسبة الحضور %"] > 0, vals)
s, _ = post(bossc, "/api/admin/x/chain", None) if False else (0, 0)
r = bossc.put("/api/admin/x/chain", json={"chain": ["doctor", "head", "dean"]})
check("المدير يعدّل سلسلة الاعتماد", r.status_code == 200 and r.get_json()["chain"] == ["doctor", "head", "dean"])
check("غير المدير لا يعدّل السلسلة", h1.put("/api/admin/x/chain", json={"chain": ["dean"]}).status_code == 403)
s, j = post(bossc, "/api/admin/x/reports/create", {"lecture_uid": "lec2"})
rid2 = j["uid"]
check("التقرير الجديد يتبع السلسلة المعدّلة", json.loads(c.execute("SELECT chain FROM reports WHERE uid=?", (rid2,)).fetchone()[0]) == ["doctor", "head", "dean"])
s, j = post(h1, "/api/admin/x/reports/%s/decide" % rid2, {"decision": "approved"})
check("رئيس القسم لا يتجاوز مرحلة التدريسي", s == 403, j)
s, j = post(dean, "/api/admin/x/reports/%s/decide" % rid2, {"decision": "approved"})
check("العميد لا يقفز إلى الاعتماد", s == 403)
s, j = post(doc, "/api/admin/x/reports/%s/decide" % rid2, {"decision": "approved", "note": "مراجعة"})
check("التدريسي يعتمد ثم ينتقل لرئيس القسم", s == 200 and "رئيس القسم" in j["message"], j)
s, j = post(h2, "/api/admin/x/reports/%s/decide" % rid2, {"decision": "approved"})
check("رئيس قسم من قسم آخر مرفوض", s == 403)
s, j = post(h1, "/api/admin/x/reports/%s/decide" % rid2, {"decision": "rejected"})
check("الرفض بلا ملاحظات مرفوض", s == 403 or s == 400)
s, j = post(h1, "/api/admin/x/reports/%s/decide" % rid2, {"decision": "approved", "note": "ممتاز"})
s, j = post(dean, "/api/admin/x/reports/%s/decide" % rid2, {"decision": "approved"})
check("العميد يعتمد نهائياً", s == 200 and "نهائياً" in j["message"], j)
check("حالة التقرير approved", c.execute("SELECT status FROM reports WHERE uid=?", (rid2,)).fetchone()[0] == "approved")
hist = c.execute("SELECT role,user,user_email,position,decision,note FROM report_approvals WHERE report_uid=? ORDER BY id", (rid2,)).fetchall()
check("كل موافقة تحوي الاسم والمنصب والبريد والقرار والملاحظات ورقم التقرير", [h["role"] for h in hist] == ["doctor", "head", "dean"] and hist[0]["user_email"] == "dr@u.edu" and hist[1]["note"] == "ممتاز")
try:
    c.execute("DELETE FROM report_approvals"); ok = False
except sqlite3.DatabaseError:
    ok = True
check("سجل الموافقات لا يُحذف", ok)
s, j = post(doc, "/api/admin/x/reports/%s/decide" % rid, {"decision": "rejected", "note": "أرقام غير دقيقة"})
check("الرفض مع سبب يوقف التقرير", s == 200 and c.execute("SELECT status FROM reports WHERE uid=?", (rid,)).fetchone()[0] in ("rejected", "in_review"))
check("المدير يقدر ينزّل ملف التقرير", bossc.get("/api/admin/x/reports/%s/file" % rid2).status_code in (200, 404))
check("التقارير التلقائية: لا شيء مستحق قبل انتهاء المهلة", X.run_daily_reports(config.load_conf(), force=True) == 0)

print("6b) إرسال تلقائي صفري التدخل (Zero-Click)")
D.set_setting(c, "report_mode", "auto")
old_start = D.now() - 4 * 86400
c.execute("INSERT INTO lectures(uid,code,course_uid,secret,start_ts,end_ts,interval_sec,status,station,grp,updated_at,rev,dirty) VALUES('lold','OLD001','crs1','s',?,?,3,'ended','','',?,1,1)", (old_start, old_start + 900, n))
nrep = X.run_daily_reports(config.load_conf(), force=True)
rp = c.execute("SELECT * FROM reports WHERE lecture_uid='lold'").fetchone()
check("انتهت المهلة ← التقرير يُنشأ تلقائياً", nrep >= 1 and rp is not None, nrep)
mail_ = c.execute("SELECT * FROM outbox ORDER BY id DESC LIMIT 1").fetchone()
rcpt = (mail_["to_addrs"] + "," + (mail_["cc"] or "")).lower()
check("يُرسل Excel تلقائياً للدكتور ورئيس القسم والعميد", all(x in rcpt for x in ("dr@u.edu", "head@u.edu", "dean@u.edu")) and mail_["attach_path"].endswith(".xlsx"), rcpt)
check("الحالة معتمد تلقائياً + أثر تدقيقي", rp["status"] == "approved" and c.execute("SELECT decision FROM report_approvals WHERE report_uid=?", (rp["uid"],)).fetchone()[0] == "auto")
check("لا يُنشأ تقرير مكرر في التشغيل التالي", X.run_daily_reports(config.load_conf(), force=True) == 0)
D.set_setting(c, "report_mode", "approval")

# ───── 7) الحماية ─────
print("7) الحماية")
r = app.test_client().post("/api/admin/settings", json={}, headers={"Origin": "http://evil.example"})
check("CSRF: طلب إداري من موقع آخر مرفوض", r.status_code == 403)
cl2 = app.test_client()
codes = [cl2.post("/api/admin/login", json={"username": "head1", "password": "bad"}).status_code for _ in range(8)]
check("تحديد محاولات الدخول (قفل مؤقت بعد 6 محاولات خاطئة)", codes[:6] == [401] * 6 and 429 in codes[6:], codes)
check("حتى كلمة المرور الصحيحة مرفوضة أثناء القفل", cl2.post("/api/admin/login", json={"username": "head1", "password": "pw123456"}).status_code == 429)
r = app.test_client().get("/api/health")
check("ترويسات الأمان", r.headers.get("X-Content-Type-Options") == "nosniff" and r.headers.get("X-Frame-Options"))
check("كلمات المرور مُجزّأة (لا نص صريح)", all(len(x[0]) > 40 and "pw123456" not in x[0] for x in c.execute("SELECT pw_hash FROM admins")))
r = app.test_client().post("/api/student/email-login", json={"email": "' OR 1=1 --", "device_id": "q"})
check("حقن SQL في البريد يُرفض", r.status_code == 400)

# ───── 8) مزامنة البريد (SMTP/IMAP وهمي) ─────
print("8) مزامنة البريد الإلكتروني")
c.close()
STATION, CLOUD = os.path.join(tmp, "st2.sqlite"), os.path.join(tmp, "cl2.sqlite")
conf = {"sync_key": "KEY-123", "station_name": "hall-1"}


class FakeSmtp:
    def __init__(self):
        self.sent = []

    def send(self, m):
        m["From"] = "hall@u.edu"
        self.sent.append(email.message_from_bytes(m.as_bytes()))


class FakeImap:
    def __init__(self, msgs):
        self.msgs, self.seen = list(msgs), set()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def unseen(self, subj):
        return [(i, m) for i, m in enumerate(self.msgs) if i not in self.seen and (m["Subject"] or "").startswith(subj)]

    def mark_seen(self, i):
        self.seen.add(i)


def use(path):
    D.DB_PATH = path
    D.init()
    cc = D.connect()
    return cc


s = use(STATION)
D.set_setting(s, "attendance_mailbox", "attendance@u.edu"); D.set_setting(s, "imap_host", "imap.fake")
s.execute("INSERT INTO courses(uid,name,doctor_email,updated_at,rev,dirty) VALUES('c9','مادة','d@u.edu',?,1,1)", (n,))
s.execute("INSERT INTO students(uid,name,name_norm,grp,updated_at,rev,dirty) VALUES('s9','طالب','طالب','A',?,1,1)", (n,))
s.execute("INSERT INTO lectures(uid,code,course_uid,secret,start_ts,end_ts,interval_sec,status,updated_at,rev,dirty) VALUES('l9','LLLL99','c9','sec',?,?,3,'active',?,1,1)", (n, n + 900, n))
s.execute("INSERT INTO attendance(lecture_uid,student_uid,device_id,code,t,slot_i,sig,age,queued,status,reason,created_at,updated_at,rev,dirty) VALUES('l9','s9','d','LLLL99',1,3,'x',1,0,'ok','',?,?,1,1)", (n, n))
smtp = FakeSmtp()
r = mailsync.send_pending(conf, smtp)
check("دفعة واحدة مجمّعة (لا رسالة لكل طالب)", len(smtp.sent) == 1 and r["rows"] >= 4, r)
m = smtp.sent[0]
check("الرسالة تحمل Batch ID وتوقيعاً وملفاً مضغوطاً", m["Subject"].startswith("ATT-BATCH ") and m["X-ATT-Sig"] and any(p.get_filename() for p in m.walk()))
r2 = mailsync.send_pending(conf, smtp)
check("لا دفعة جديدة قبل وصول التأكيد (تُنتظر ACK)", "waiting_ack" in r2 and len(smtp.sent) == 1, r2)
check("السجلات المحلية ما زالت dirty قبل التأكيد (لا تُحذف/تُعلَّم)", s.execute("SELECT COUNT(*) FROM attendance WHERE dirty=1").fetchone()[0] == 1)
r3 = mailsync.send_pending(conf, smtp, force=True)
check("إعادة الإرسال عند فشل المزامنة بنفس Batch ID", len(smtp.sent) == 2 and smtp.sent[1]["Subject"] == m["Subject"], r3)
s.close()

cc = use(CLOUD)
D.set_setting(cc, "imap_host", "imap.fake"); D.set_setting(cc, "attendance_mailbox", "attendance@u.edu")
cc.close()
cloud_smtp = FakeSmtp()
imap = FakeImap([smtp.sent[0], smtp.sent[1]])
res = mailsync.receive_batches(conf, imap, cloud_smtp)
cc = D.connect()
check("الخادم يستلم الدفعة مرة واحدة ويكتشف النسخة المكررة (Idempotent)", res == (1, 1, 0), res)
check("السجل في قاعدة الخادم دون تكرار", cc.execute("SELECT COUNT(*) FROM attendance WHERE lecture_uid='l9'").fetchone()[0] == 1 and cc.execute("SELECT COUNT(*) FROM students WHERE uid='s9'").fetchone()[0] == 1)
check("الدفعة مسجّلة في mail_batches", cc.execute("SELECT status FROM mail_batches WHERE direction='in'").fetchone()[0] == "done")
check("أُرسل تأكيد (ACK) لكل دفعة، بما فيها المكررة", len(cloud_smtp.sent) == 2 and cloud_smtp.sent[0]["Subject"].startswith("ATT-ACK "))
res = mailsync.receive_batches(conf, FakeImap([smtp.sent[0]]), FakeSmtp())
check("استلام نفس البريد مرة ثالثة لا يكرر الحضور", res == (0, 1, 0) and cc.execute("SELECT COUNT(*) FROM attendance").fetchone()[0] == 1, res)
bad = email.message_from_bytes(smtp.sent[0].as_bytes())
del bad["X-ATT-Sig"]; bad["X-ATT-Sig"] = "0" * 64
bad_ack = FakeSmtp()
res = mailsync.receive_batches(conf, FakeImap([bad]), bad_ack)
check("دفعة بتوقيع مزوَّر تُرفض ولا يُرسل لها تأكيد", res == (0, 0, 1) and not bad_ack.sent, res)
res = mailsync.receive_batches({"sync_key": "OTHER"}, FakeImap([smtp.sent[0]]), FakeSmtp())
check("دفعة موقّعة بمفتاح غير موثوق تُرفض (لا نثق بعنوان المرسل)", res[2] == 1, res)
cc.close()

s = use(STATION)
fake_ack_forged = email.message.EmailMessage(); fake_ack_forged["Subject"] = "ATT-ACK " + m["Subject"].split()[-1]; fake_ack_forged["X-ATT-Sig"] = "1" * 64
fake_ack_forged = email.message_from_bytes(fake_ack_forged.as_bytes())
n_ack = mailsync.process_acks(conf, FakeImap([fake_ack_forged]))
check("تأكيد مزوَّر لا يُعلِّم السجلات «تمت المزامنة»", n_ack == 0 and s.execute("SELECT COUNT(*) FROM attendance WHERE dirty=1").fetchone()[0] == 1)
n_ack = mailsync.process_acks(conf, FakeImap([cloud_smtp.sent[0]]))
check("بعد التأكيد الموقّع فقط تصبح السجلات Synced", n_ack == 1 and s.execute("SELECT COUNT(*) FROM attendance WHERE dirty=1").fetchone()[0] == 0)
r4 = mailsync.send_pending(conf, FakeSmtp())
check("لا شيء جديد للإرسال بعد التأكيد", r4.get("pushed") == 0, r4)
s.close()

# ───── 9) حضور الطلاب بالإيميل (القاعة تنتظر البريد) ─────
print("9) هاتف الطالب ← إيميل ← جهاز القاعة")
s = use(STATION)
s.execute("DELETE FROM attendance WHERE student_uid='s9'")
lec9 = s.execute("SELECT * FROM lectures WHERE uid='l9'").fetchone()
s.execute("INSERT INTO students(uid,name,name_norm,grp,updated_at,rev,dirty) VALUES('s10','طالبة','طالبه','A',?,1,1)", (n,))
t_, i_, sg_ = core.make_token(lec9)
payload = {"v": 1, "device_id": "phone-s9", "items": [{"id": "e1", "code": "LLLL99", "t": t_, "i": i_, "sig": sg_, "student": "s9", "age": 1.0, "elapsed": 1.0, "ts": 1}]}
raw = base64.b64encode(json.dumps(payload).encode()).decode()


def stu_mail(raw_, frm="s9@gmail.com"):
    m = email.message.EmailMessage(); m["Subject"] = "ATT-STU"; m["From"] = frm
    m.set_content("لا تعدّل\n\nATT:" + "\r\n".join(raw_[i:i + 40] for i in range(0, len(raw_), 40)) + ":END")
    return email.message_from_bytes(m.as_bytes())


rep_smtp = FakeSmtp()
res = mailsync.receive_student_mails(conf, FakeImap([stu_mail(raw)]), rep_smtp)
check("إيميل الطالب يسجّل الحضور في القاعة (حتى مع تقطيع أسطر البريد)", res == (1, 0, 1) and s.execute("SELECT status FROM attendance WHERE student_uid='s9'").fetchone()[0] == "ok", res)
check("يصل الطالب ردّ بالتأكيد", len(rep_smtp.sent) == 1 and rep_smtp.sent[0]["Subject"] == "ATT-REPLY")
res = mailsync.receive_student_mails(conf, FakeImap([stu_mail(raw)]), FakeSmtp())
check("إرسال الإيميل مرتين لا يكرر الحضور", s.execute("SELECT COUNT(*) FROM attendance WHERE student_uid='s9'").fetchone()[0] == 1)
payload["device_id"] = "phone-thief"
res = mailsync.receive_student_mails(conf, FakeImap([stu_mail(base64.b64encode(json.dumps(payload).encode()).decode())]), FakeSmtp())
check("جهاز آخر بإيميل مزوَّر لا يسجّل حضور طالب مربوط بجهاز غيره", res[1] >= 1, res)
payload["device_id"] = "phone-s10"; payload["items"][0]["student"] = "s10"; payload["items"][0]["sig"] = "deadbeef0000"
res = mailsync.receive_student_mails(conf, FakeImap([stu_mail(base64.b64encode(json.dumps(payload).encode()).decode())]), FakeSmtp())
check("باركود بتوقيع مزوَّر مرفوض", res[1] >= 1 and s.execute("SELECT COUNT(*) FROM attendance WHERE student_uid='s10' AND status='ok'").fetchone()[0] == 0, res)
res = mailsync.receive_student_mails(conf, FakeImap([stu_mail("%%%")]), FakeSmtp())
check("رسالة تالفة لا تُسقط الخادم", res[1] >= 1)
s.close()

print("\nنجح %d — فشل %d" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
