# -*- coding: utf-8 -*-
"""إضافات مواصفات «نظام الحضور الجامعي الذكي — Offline First» فوق النظام الحالي (نفس الواجهة ونفس الباركود المتغيّر).

المحتوى:
  1) الجداول الجديدة + الأعمدة المضافة (بريد جامعي، مجموعة المحاضرة)
  2) سجل تدقيق إداري لا يُعدَّل ولا يُحذف (سلسلة تجزئة + محفّزات قاعدة البيانات)
  3) الطالب الضيف (Pending / Approved / Rejected Guest) والتأخّر
  4) توقيع الجهاز (ECDSA P-256) والتحقق منه في الخادم
  5) طلبات تغيير الجهاز (ذرّية) والتسجيل بالبريد الجامعي
  6) تقارير المحاضرات + سلسلة اعتماد متسلسلة قابلة للتعديل
  7) إشعارات، تحديد محاولات، سجل نسخ احتياطي
"""
import base64, hashlib, json, os, re, time, uuid
import db as D

# ───────────────────────── الجداول ─────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS device_keys(student_uid TEXT PRIMARY KEY, device_id TEXT, pub TEXT,
  updated_at REAL, rev INTEGER DEFAULT 0, dirty INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS guest_requests(uid TEXT PRIMARY KEY, lecture_uid TEXT, student_uid TEXT, kind TEXT DEFAULT 'guest',
  home_grp TEXT, lec_grp TEXT, status TEXT DEFAULT 'pending', decided_by TEXT, decided_role TEXT, decided_at REAL, note TEXT,
  created_at REAL, updated_at REAL, rev INTEGER DEFAULT 0, dirty INTEGER DEFAULT 1);
CREATE INDEX IF NOT EXISTS ix_gr_rev ON guest_requests(rev);
CREATE INDEX IF NOT EXISTS ix_gr_status ON guest_requests(status, lecture_uid);
CREATE TABLE IF NOT EXISTS device_requests(uid TEXT PRIMARY KEY, student_uid TEXT, new_device_id TEXT, new_pub TEXT, reason TEXT, email TEXT,
  status TEXT DEFAULT 'pending', decided_by TEXT, decided_role TEXT, decided_at REAL, note TEXT,
  created_at REAL, updated_at REAL, rev INTEGER DEFAULT 0, dirty INTEGER DEFAULT 1);
CREATE INDEX IF NOT EXISTS ix_dr_rev ON device_requests(rev);
CREATE INDEX IF NOT EXISTS ix_dr_status ON device_requests(status, student_uid);
CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, actor TEXT, role TEXT, action TEXT, target TEXT,
  detail TEXT, decision TEXT, reason TEXT, prev_hash TEXT, hash TEXT);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, title TEXT, body TEXT, ref TEXT,
  to_role TEXT DEFAULT '', college_uid TEXT DEFAULT '', dept_uid TEXT DEFAULT '', to_email TEXT DEFAULT '', student_uid TEXT DEFAULT '',
  created_at REAL, read_at REAL);
CREATE INDEX IF NOT EXISTS ix_nt_student ON notifications(student_uid, id);
CREATE TABLE IF NOT EXISTS reports(uid TEXT PRIMARY KEY, number TEXT UNIQUE, lecture_uid TEXT UNIQUE, course_uid TEXT, college_uid TEXT, dept_uid TEXT,
  doctor_email TEXT, status TEXT DEFAULT 'in_review', step INTEGER DEFAULT 0, chain TEXT, file_name TEXT, summary TEXT, created_by TEXT,
  created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS report_approvals(id INTEGER PRIMARY KEY AUTOINCREMENT, report_uid TEXT, report_number TEXT, step INTEGER, role TEXT,
  user TEXT, full_name TEXT, user_email TEXT, position TEXT, decision TEXT, note TEXT, ts REAL);
CREATE TRIGGER IF NOT EXISTS ra_no_update BEFORE UPDATE ON report_approvals BEGIN SELECT RAISE(ABORT, 'report_approvals is append-only'); END;
CREATE TRIGGER IF NOT EXISTS ra_no_delete BEFORE DELETE ON report_approvals BEGIN SELECT RAISE(ABORT, 'report_approvals is append-only'); END;
CREATE TABLE IF NOT EXISTS mail_batches(batch_id TEXT, direction TEXT, n_rows INTEGER DEFAULT 0, status TEXT, marks TEXT, detail TEXT,
  created_at REAL, updated_at REAL, PRIMARY KEY(batch_id, direction));
CREATE TABLE IF NOT EXISTS throttle(k TEXT, ts REAL);
CREATE INDEX IF NOT EXISTS ix_th ON throttle(k, ts);
CREATE TABLE IF NOT EXISTS backup_log(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, file TEXT, size INTEGER, ok INTEGER, detail TEXT);
"""

EXTRA_DEFAULTS = {
    "email_domain": "uoa.edu.iq",   # نطاق البريد الجامعي الثابت؛ الطالب يكتب رقمه فقط ويُكمَل تلقائياً
    "student_login_mode": os.environ.get("ATT_STUDENT_LOGIN", "email"),   # email = دخول الطالب بالبريد فقط | pick = اختيار الاسم (قديم)
    "late_after_min": "15",         # بعد كم دقيقة من بدء المحاضرة يُعدّ الطالب «متأخراً» (0 = تعطيل)
    "require_device_sig": "0",      # 1 = رفض أي حضور من جهاز بلا مفتاح تشفير معتمد
    "approval_chain": "doctor,rapporteur,head,dean,admin",   # سلسلة اعتماد التقارير (قابلة للتعديل)
    "report_mode": "approval",      # approval = سلسلة اعتماد | auto = إرسال تلقائي صفري التدخل (Zero-Click) للدكتور ورئيس القسم والعميد ورئيس الجامعة
    "report_hour": "2",             # ساعة التقارير التلقائية اليومية (2 = الثانية فجراً بتوقيت بغداد)
    "mail_sync": "0",               # 1 = مزامنة الحضور عبر البريد (IMAP/SMTP) بدل/مع HTTP
    "imap_host": "", "imap_port": "993", "imap_user": "", "imap_pass": "", "imap_folder": "INBOX",
    "public_url": "",               # رابط الصفحة العام الثابت (Netlify/GitHub Pages…) الذي يضعه الباركود ليفتح من أي شبكة
    "relay_url": "",                # رابط الإرسال التلقائي (دالة الترحيل) الذي يرسل حضور الطالب إلى الجيميل بلا نقرة
    "attendance_mailbox": "",       # بريد استلام الدفعات مثل attendance@university.edu.iq
    "manual_checkin": "1",          # السماح بالتسجيل اليدوي بالبريد الجامعي (يحتاج موافقة)
    "backup_keep": "14",
}
EXTRA_SYNC_SETTINGS = ["late_after_min", "require_device_sig", "email_domain"]
SECRET_SETTINGS = ("imap_pass",)

ROLES = ("doctor", "rapporteur", "head", "dean", "admin")
ROLE_AR = {"doctor": "التدريسي", "rapporteur": "مقرر القسم / منسق المادة", "head": "رئيس القسم", "dean": "العميد", "admin": "رئيس الجامعة"}

REASONS = {
    "late": "متأخر", "guest_pending": "طالب ضيف — بانتظار الموافقة", "guest_approved": "ضيف تمت الموافقة عليه",
    "guest_rejected": "طلب الضيف مرفوض", "manual_pending": "تسجيل يدوي — بانتظار الموافقة", "manual_approved": "تسجيل يدوي معتمد",
    "bad_device_sig": "هذا الجهاز غير معتمد لحسابك", "device_key_missing": "هذا الجهاز غير معتمد لحسابك (لا مفتاح تشفير)",
}


def init_schema(c):
    c.executescript(SCHEMA)
    for tbl, col, ddl in (("students", "univ_email", "TEXT"), ("lectures", "grp", "TEXT DEFAULT ''")):
        try:
            c.execute("ALTER TABLE %s ADD COLUMN %s %s" % (tbl, col, ddl))
        except Exception:
            pass
    c.execute("CREATE INDEX IF NOT EXISTS ix_stu_email ON students(univ_email)")
    for k, v in EXTRA_DEFAULTS.items():
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
    c.execute("UPDATE settings SET value='uoa.edu.iq' WHERE key='email_domain' AND value IN ('','university.edu.iq')")


# ───────────────────────── التدقيق ─────────────────────────
def audit(c, actor, role, action, target="", detail="", decision="", reason=""):
    """سجل إداري متسلسل بالتجزئة: أي تعديل لاحق على صف قديم يكسر السلسلة ويُكتشف في verify_audit."""
    prev = c.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    prev = prev[0] if prev else ""
    ts = round(time.time(), 3)
    row = [str(x or "") for x in (ts, actor, role, action, target, str(detail or "")[:500], decision, str(reason or "")[:500])]
    h = hashlib.sha256(("|".join([prev] + row)).encode()).hexdigest()
    c.execute("INSERT INTO audit_log(ts,actor,role,action,target,detail,decision,reason,prev_hash,hash) VALUES(?,?,?,?,?,?,?,?,?,?)",
              (ts, row[1], row[2], row[3], row[4], row[5], row[6], row[7], prev, h))


def verify_audit(c):
    """يُرجع None إن كانت السلسلة سليمة، وإلا رقم أول سجل مخرَّب."""
    prev = ""
    for r in c.execute("SELECT * FROM audit_log ORDER BY id"):
        row = [str(x or "") for x in (r["ts"], r["actor"], r["role"], r["action"], r["target"], r["detail"], r["decision"], r["reason"])]
        h = hashlib.sha256(("|".join([prev] + row)).encode()).hexdigest()
        if r["prev_hash"] != prev or r["hash"] != h:
            return r["id"]
        prev = r["hash"]
    return None


# ───────────────────────── الإشعارات والتحديد ─────────────────────────
def notify(c, kind, title, body="", ref="", to_role="", college="", dept="", email="", student=""):
    c.execute("INSERT INTO notifications(kind,title,body,ref,to_role,college_uid,dept_uid,to_email,student_uid,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
              (kind, title, body, ref, to_role, college or "", dept or "", (email or "").lower(), student or "", time.time()))


def throttle_over(c, key, limit, window):
    c.execute("DELETE FROM throttle WHERE ts<?", (time.time() - 86400,))
    n = c.execute("SELECT COUNT(*) FROM throttle WHERE k=? AND ts>?", (key, time.time() - window)).fetchone()[0]
    return n >= limit


def throttle_hit(c, key):
    c.execute("INSERT INTO throttle(k,ts) VALUES(?,?)", (key, time.time()))


def throttle_clear(c, key):
    c.execute("DELETE FROM throttle WHERE k=?", (key,))


# ───────────────────────── البريد الجامعي ─────────────────────────
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def clean_email(s, domain=""):
    """يقبل بريداً كاملاً أو الرقم الجامعي فقط (يُلحَق به @النطاق تلقائياً)."""
    s = (s or "").strip().lower().replace(" ", "")
    domain = (domain or "").strip().lower().lstrip("@")
    if s and "@" not in s and domain and re.fullmatch(r"[a-z0-9._\-]{3,40}", s):
        s = s + "@" + domain
    if not EMAIL_RE.match(s):
        return None
    if domain and not (s.endswith("@" + domain) or s.endswith("." + domain)):
        return None
    return s


# ───────────────────────── الطالب الضيف والتأخّر ─────────────────────────
def grp_match(lec_grp, st_grp):
    """المحاضرة لـ A1 والطالب B1 → غير مطابق (ضيف). المحاضرة لـ A (نظري) تشمل A1 وA2…  الفارغ = لا قيد."""
    lg, sg = D.norm(lec_grp), D.norm(st_grp)
    if not lg or not sg or lg == sg:
        return True
    if re.fullmatch(r"[^\W\d_]", lg) and sg.startswith(lg) and sg[len(lg):].isdigit():
        return True
    return False


def finalize_status(c, lec, st, status, reason, t, S, kind="guest"):
    """يُطبَّق بعد نجاح التحقق من الباركود: يحوّل الحضور إلى «ضيف بانتظار الموافقة» أو يضع علامة تأخّر."""
    if status != "ok":
        return status, reason
    try:
        keys = lec.keys()
        lgrp = lec["grp"] if "grp" in keys else ""
    except Exception:
        lgrp = ""
    gid = hashlib.sha1((lec["uid"] + "|" + st["uid"]).encode()).hexdigest()[:16]
    gr = c.execute("SELECT status FROM guest_requests WHERE uid=?", (gid,)).fetchone()
    if gr:   # للطالب قرار سابق على هذه المحاضرة
        if gr["status"] == "approved":
            return "ok", "guest_approved"
        if gr["status"] == "rejected":
            return "guest_rejected", "guest_rejected"
        return "guest_pending", "guest_pending"
    if lgrp and not grp_match(lgrp, st["grp"]):
        n = D.now()
        c.execute("""INSERT OR IGNORE INTO guest_requests(uid,lecture_uid,student_uid,kind,home_grp,lec_grp,status,created_at,updated_at,rev,dirty)
                     VALUES(?,?,?,?,?,?,'pending',?,?,?,1)""", (gid, lec["uid"], st["uid"], "guest", st["grp"] or "", lgrp, n, n, D.next_rev(c)))
        notify(c, "guest", "طلب طالب ضيف", "%s (مجموعة %s) سجّل في محاضرة مجموعة %s" % (st["name"], st["grp"], lgrp), ref=gid,
               college=st["college_uid"], dept=st["dept_uid"])
        return "guest_pending", "guest_pending"
    try:
        late = int(float(S.get("late_after_min", 15) or 0))
    except Exception:
        late = 0
    if late > 0 and t - float(lec["start_ts"]) > late * 60:
        return "ok", "late"
    return "ok", ""


# ───────────────────────── توقيع الجهاز ─────────────────────────
def email_hint(domain):
    return "اكتب الرقم الجامعي أو البريد الكامل (ينتهي بـ @%s)" % ((domain or "").lstrip("@") or "university.edu.iq")


def student_card(c, st):
    dp = c.execute("SELECT d.name AS dn,k.name AS kn FROM departments d LEFT JOIN colleges k ON k.uid=d.college_uid WHERE d.uid=?", (st["dept_uid"] or "",)).fetchone()
    return {"u": st["uid"], "n": st["name"], "g": st["grp"] or "", "d": dp["dn"] if dp else "", "k": dp["kn"] if dp else "", "s": int(st["stage"] or 0)}


def _b64u(s):
    s = s + "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s.encode())


def verify_dsig(pub_jwk, msg, sig_b64):
    """يتحقق من توقيع ECDSA P-256 (الصيغة الخام r||s الناتجة عن WebCrypto)."""
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec, utils
        jwk = json.loads(pub_jwk) if isinstance(pub_jwk, str) else pub_jwk
        if jwk.get("kty") != "EC" or jwk.get("crv") != "P-256":
            return False
        pk = ec.EllipticCurvePublicNumbers(int.from_bytes(_b64u(jwk["x"]), "big"), int.from_bytes(_b64u(jwk["y"]), "big"), ec.SECP256R1()).public_key()
        raw = base64.b64decode(sig_b64)
        if len(raw) != 64:
            return False
        pk.verify(utils.encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")), msg, ec.ECDSA(hashes.SHA256()))
        return True
    except Exception:
        return False


def sig_message(item, device_id):
    stu = item.get("sig_student") if item.get("sig_student") is not None else item.get("student", "")   # الموقَّع على الهاتف (قد يكون فارغاً قبل أن يُعرَّف الطالب من رقمه)
    return ("%s|%s|%s|%s|%s" % (item.get("code", ""), item.get("t", ""), item.get("i", ""), stu, device_id)).encode()


def norm_pub(p):
    """يقبل JWK كنص أو كائن ويُرجع نصاً مرتّباً (أو None إن لم يكن مفتاح P-256 صالحاً)."""
    try:
        j = json.loads(p) if isinstance(p, str) else dict(p)
        if j.get("kty") == "EC" and j.get("crv") == "P-256" and j.get("x") and j.get("y"):
            return json.dumps({"kty": "EC", "crv": "P-256", "x": j["x"], "y": j["y"]}, sort_keys=True, separators=(",", ":"))
    except Exception:
        pass
    return None


def set_key(c, student_uid, device_id, pub):
    n = D.now()
    c.execute("""INSERT INTO device_keys(student_uid,device_id,pub,updated_at,rev,dirty) VALUES(?,?,?,?,?,1)
                 ON CONFLICT(student_uid) DO UPDATE SET device_id=excluded.device_id,pub=excluded.pub,updated_at=excluded.updated_at,rev=excluded.rev,dirty=1""",
              (student_uid, device_id, pub or "", n, D.next_rev(c)))


def clear_key(c, student_uid):
    if c.execute("SELECT 1 FROM device_keys WHERE student_uid=?", (student_uid,)).fetchone():
        set_key(c, student_uid, "", "")


def enroll_key(c, st, device_id, pub):
    """تسجيل المفتاح العام عند ربط الجهاز (مرة واحدة؛ تغييره يحتاج طلب تغيير جهاز موافَقاً عليه)."""
    p = norm_pub(pub) if pub else None
    if not p:
        return
    cur = c.execute("SELECT pub,device_id FROM device_keys WHERE student_uid=?", (st["uid"],)).fetchone()
    if cur and cur["pub"]:
        return
    set_key(c, st["uid"], device_id, p)


def check_device_sig(c, st, device_id, item, S):
    """(ok, reason). جهاز له مفتاح معتمد → التوقيع إلزامي. جهاز قديم بلا مفتاح → يُقبل ما لم يُفعَّل require_device_sig."""
    cur = c.execute("SELECT pub,device_id FROM device_keys WHERE student_uid=?", (st["uid"],)).fetchone()
    msg = sig_message(item, device_id)
    if cur and cur["pub"]:
        if cur["device_id"] and cur["device_id"] != device_id:
            return False, "bad_device_sig"
        return (True, "") if verify_dsig(cur["pub"], msg, item.get("dsig") or "") else (False, "bad_device_sig")
    p = norm_pub(item.get("pub")) if item.get("pub") else None
    if p and verify_dsig(p, msg, item.get("dsig") or ""):
        set_key(c, st["uid"], device_id, p)       # أول استخدام لجهاز قديم: نعتمد مفتاحه (ثقة عند أول استخدام)
        return True, ""
    if str(S.get("require_device_sig", "0")) == "1":
        return False, "device_key_missing"
    return True, ""


# ───────────────────────── تقارير المحاضرات وسلسلة الاعتماد ─────────────────────────
def get_chain(S):
    ch = [x.strip() for x in str(S.get("approval_chain") or "").split(",") if x.strip() in ROLES]
    seen, out = set(), []
    for x in ch:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out or ["doctor", "head", "dean"]


def lecture_summary(c, lec, course):
    import core
    S = D.get_settings(c)
    w, a = core.cohort_filter(course)
    studs = c.execute("SELECT uid,grp FROM students WHERE deleted=0" + w, a).fetchall()
    uids = {r["uid"] for r in studs}
    att = c.execute("SELECT student_uid,status,reason FROM attendance WHERE lecture_uid=?", (lec["uid"],)).fetchall()
    present_reg = sum(1 for r in att if r["status"] == "ok" and r["student_uid"] in uids and r["reason"] != "guest_approved")
    late = sum(1 for r in att if r["status"] == "ok" and r["reason"] == "late")
    g_ok = sum(1 for r in att if r["status"] == "ok" and r["reason"] == "guest_approved")
    g_pend = sum(1 for r in att if r["status"] == "guest_pending")
    g_rej = sum(1 for r in att if r["status"] == "guest_rejected")
    total = len(uids)
    dept = c.execute("SELECT d.name AS dn,k.name AS kn FROM departments d LEFT JOIN colleges k ON k.uid=d.college_uid WHERE d.uid=?", (course["dept_uid"] or "",)).fetchone()
    doc = c.execute("SELECT full_name,username FROM admins WHERE lower(trim(email))=lower(trim(?)) LIMIT 1", (course["doctor_email"] or "",)).fetchone()
    return {"university": S.get("org_name", ""), "college": dept["kn"] if dept else "", "department": dept["dn"] if dept else "",
            "stage": int(course["stage"] or 0), "course": course["name"], "doctor": (doc["full_name"] or doc["username"]) if doc else (course["doctor_email"] or ""),
            "doctor_email": course["doctor_email"] or "", "group": lec["grp"] if "grp" in lec.keys() else "", "lecture_code": lec["code"],
            "start": lec["start_ts"], "end": lec["end_ts"], "total": total, "present": present_reg + g_ok, "present_regular": present_reg,
            "absent": max(0, total - present_reg), "late": late, "guests_approved": g_ok, "guests_pending": g_pend, "guests_rejected": g_rej,
            "pct": round((present_reg + g_ok) * 100 / total, 1) if total else 0.0}


def create_report(c, conf, lecture_uid, actor="system"):
    import core
    from openpyxl import load_workbook
    from openpyxl.styles import Alignment, Font
    lec = c.execute("SELECT * FROM lectures WHERE uid=? AND status!='deleted'", (lecture_uid,)).fetchone()
    if not lec:
        raise ValueError("المحاضرة غير موجودة")
    ex = c.execute("SELECT * FROM reports WHERE lecture_uid=?", (lecture_uid,)).fetchone()
    if ex:
        return ex
    course = c.execute("SELECT * FROM courses WHERE uid=?", (lec["course_uid"],)).fetchone()
    if not course:
        raise ValueError("المادة غير موجودة")
    from config import EXPORT_DIR
    S = D.get_settings(c)
    chain = get_chain(S)
    n = c.execute("SELECT COUNT(*) FROM reports").fetchone()[0] + 1
    number = "RPT-%s-%04d" % (time.strftime("%Y%m%d", time.gmtime(lec["start_ts"] + 3 * 3600)), n)
    while c.execute("SELECT 1 FROM reports WHERE number=?", (number,)).fetchone():
        n += 1
        number = "RPT-%s-%04d" % (time.strftime("%Y%m%d", time.gmtime(lec["start_ts"] + 3 * 3600)), n)
    fname = "%s_%s.xlsx" % (number, core.safe_name(course["name"]))
    path = os.path.join(EXPORT_DIR, fname)
    core.build_export(c, course["uid"], path, date_from=lec["start_ts"], date_to=lec["start_ts"])
    sm = lecture_summary(c, lec, course)
    wb = load_workbook(path)
    ws = wb.create_sheet("ملخص التقرير", 0)
    ws.sheet_view.rightToLeft = True
    rows = [("رقم التقرير", number), ("الجامعة", sm["university"]), ("الكلية", sm["college"]), ("القسم", sm["department"]), ("المرحلة", sm["stage"]),
            ("المادة", sm["course"]), ("التدريسي", sm["doctor"]), ("المجموعة", sm["group"] or "—"), ("تاريخ المحاضرة", core.fmt_ts(sm["start"])[:10]),
            ("بداية المحاضرة", core.fmt_ts(sm["start"])[11:]), ("نهاية المحاضرة", core.fmt_ts(sm["end"])[11:]), ("العدد الكلي للطلبة", sm["total"]),
            ("عدد الحاضرين", sm["present"]), ("عدد الغائبين", sm["absent"]), ("عدد المتأخرين", sm["late"]), ("الضيوف الموافق عليهم", sm["guests_approved"]),
            ("طلبات الضيوف المعلقة", sm["guests_pending"]), ("طلبات الضيوف المرفوضة", sm["guests_rejected"]), ("نسبة الحضور %", sm["pct"])]
    for i, (k, v) in enumerate(rows, 1):
        ws.cell(i, 1, k).font = Font(bold=True, size=14)
        ws.cell(i, 2, v).font = Font(size=14)
        ws.cell(i, 2).alignment = Alignment(horizontal="center")
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 36
    wb.save(path)
    uid = D.new_uid()
    now_ = time.time()
    c.execute("""INSERT INTO reports(uid,number,lecture_uid,course_uid,college_uid,dept_uid,doctor_email,status,step,chain,file_name,summary,created_by,created_at,updated_at)
                 VALUES(?,?,?,?,?,?,?,?,0,?,?,?,?,?,?)""", (uid, number, lecture_uid, course["uid"], course["college_uid"] or "", course["dept_uid"] or "",
                                                          (course["doctor_email"] or "").lower(), "in_review", json.dumps(chain), fname, json.dumps(sm, ensure_ascii=False), actor, now_, now_))
    audit(c, actor, "system" if actor == "system" else "", "report.create", number, "lecture=%s" % lecture_uid)
    _notify_step(c, conf, uid, 0)
    return c.execute("SELECT * FROM reports WHERE uid=?", (uid,)).fetchone()


def _notify_step(c, conf, report_uid, step):
    import core
    r = c.execute("SELECT * FROM reports WHERE uid=?", (report_uid,)).fetchone()
    chain = json.loads(r["chain"])
    if step >= len(chain):
        return
    role = chain[step]
    title = "تقرير بانتظار اعتمادك: " + r["number"]
    notify(c, "report", title, "المرحلة: " + ROLE_AR.get(role, role), ref=report_uid, to_role=role, college=r["college_uid"], dept=r["dept_uid"],
           email=r["doctor_email"] if role == "doctor" else "")
    # بريد تنبيه (بلا روابط اعتماد مباشرة: يجب الدخول بحساب موثّق إلى لوحة الاعتماد)
    to = []
    if role == "doctor":
        to = [r["doctor_email"]] if r["doctor_email"] else []
    else:
        q, a = "SELECT email FROM admins WHERE role=? AND COALESCE(email,'')!=''", [role]
        if role in ("head", "rapporteur"):
            q += " AND dept_uid=?"
            a.append(r["dept_uid"])
        elif role == "dean":
            q += " AND college_uid=?"
            a.append(r["college_uid"])
        to = [x[0] for x in c.execute(q, a)]
    if to:
        core.enqueue_mail(c, ",".join(to), "", title, "السلام عليكم،\nالتقرير %s بانتظار اعتمادك (%s).\nادخل إلى لوحة النظام بحسابك ← تبويب «الطلبات والاعتماد»." % (r["number"], ROLE_AR.get(role, role)), None)


def in_scope(role, session, rep_or_student):
    """هل يملك المستخدم الحالي نطاقاً على هذا الكيان (يملك college_uid/dept_uid)؟"""
    if role == "admin":
        return True
    if role == "dean":
        return (rep_or_student["college_uid"] or "") == (session.get("college") or "-")
    if role in ("head", "rapporteur"):
        return (rep_or_student["dept_uid"] or "") == (session.get("dept") or "-")
    return False


def decide_report(c, conf, report_uid, user, decision, note):
    """user: dict(username, full_name, email, role, college, dept). يُرجع (ok, message)."""
    r = c.execute("SELECT * FROM reports WHERE uid=?", (report_uid,)).fetchone()
    if not r:
        return False, "التقرير غير موجود"
    if r["status"] != "in_review":
        return False, "التقرير ليس قيد الاعتماد"
    chain = json.loads(r["chain"])
    step = int(r["step"])
    need = chain[step]
    if user["role"] != need:
        return False, "هذه المرحلة تخصّ: " + ROLE_AR.get(need, need)
    ok_scope = (need == "admin") or (need == "doctor" and (user["email"] or "").strip().lower() == (r["doctor_email"] or "")) or \
               (need == "dean" and (user["college"] or "-") == (r["college_uid"] or "")) or (need in ("head", "rapporteur") and (user["dept"] or "-") == (r["dept_uid"] or ""))
    if not ok_scope:
        return False, "التقرير خارج نطاق صلاحيتك"
    if decision not in ("approved", "rejected"):
        return False, "قرار غير صالح"
    if decision == "rejected" and not (note or "").strip():
        return False, "اكتب سبب الرفض"
    now_ = time.time()
    c.execute("INSERT INTO report_approvals(report_uid,report_number,step,role,user,full_name,user_email,position,decision,note,ts) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
              (report_uid, r["number"], step, need, user["username"], user["full_name"], user["email"], ROLE_AR.get(need, need), decision, (note or "")[:500], now_))
    audit(c, user["username"], need, "report.decision", r["number"], "step=%d" % step, decision, note or "")
    if decision == "rejected":
        c.execute("UPDATE reports SET status='rejected',updated_at=? WHERE uid=?", (now_, report_uid))
        notify(c, "report", "رُفض التقرير " + r["number"], note or "", ref=report_uid, to_role="doctor", email=r["doctor_email"])
        return True, "تم رفض التقرير"
    if step + 1 >= len(chain):
        c.execute("UPDATE reports SET status='approved',step=?,updated_at=? WHERE uid=?", (step + 1, now_, report_uid))
        notify(c, "report", "اعتُمد التقرير نهائياً " + r["number"], "", ref=report_uid, to_role="doctor", email=r["doctor_email"])
        return True, "اعتُمد التقرير نهائياً"
    c.execute("UPDATE reports SET step=?,updated_at=? WHERE uid=?", (step + 1, now_, report_uid))
    _notify_step(c, conf, report_uid, step + 1)
    return True, "تم الاعتماد وانتقل التقرير إلى: " + ROLE_AR.get(chain[step + 1], chain[step + 1])


def auto_dispatch(c, conf, rep):
    """Zero-Click: يرسل Excel التقرير فوراً إلى الدكتور ورئيس القسم والعميد ورئيس الجامعة حسب الهيكل المبرمج، دون أي زر اعتماد."""
    import core
    from config import EXPORT_DIR
    to = [rep["doctor_email"]] if rep["doctor_email"] else []
    q = c.execute("""SELECT email FROM admins WHERE COALESCE(email,'')!='' AND (
                       role='admin' OR (role='dean' AND college_uid=?) OR (role IN ('head','rapporteur') AND dept_uid=?))""", (rep["college_uid"] or "-", rep["dept_uid"] or "-"))
    for (em,) in q:
        if em.lower() not in [x.lower() for x in to]:
            to.append(em)
    sm = json.loads(rep["summary"] or "{}")
    if to:
        body = "السلام عليكم،\nتقرير حضور تلقائي رقم %s\nالمادة: %s — التدريسي: %s\nالحضور: %s من %s (%s%%) — الغياب: %s — المتأخرون: %s\n%s" % (
            rep["number"], sm.get("course", ""), sm.get("doctor", ""), sm.get("present"), sm.get("total"), sm.get("pct"), sm.get("absent"), sm.get("late"), sm.get("university", ""))
        core.enqueue_mail(c, to[0], ",".join(to[1:]), "تقرير الحضور — %s — %s" % (sm.get("course", ""), rep["number"]), body, os.path.join(EXPORT_DIR, rep["file_name"]))
    n = time.time()
    chain = json.loads(rep["chain"])
    c.execute("INSERT INTO report_approvals(report_uid,report_number,step,role,user,full_name,user_email,position,decision,note,ts) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
              (rep["uid"], rep["number"], len(chain), "system", "system", "إرسال تلقائي", "", "النظام", "auto", "أُرسل إلى: " + ", ".join(to), n))
    c.execute("UPDATE reports SET status='approved',step=?,updated_at=? WHERE uid=?", (len(chain), n, rep["uid"]))
    audit(c, "system", "system", "report.auto_send", rep["number"], "to=%d" % len(to))


def run_daily_reports(conf, force=False):
    """بعد انتهاء مهلة الاستلام (24 ساعة فأكثر) تُنشأ تقارير المحاضرات تلقائياً وتُرسل لسلسلة الاعتماد. تُنفَّذ مرة يومياً عند report_hour (2 فجراً)."""
    import core
    c = D.connect()
    try:
        S = D.get_settings(c)
        tz = core.TZ
        from datetime import datetime
        nowl = datetime.now(tz)
        try:
            hr = int(S.get("report_hour", 2))
        except Exception:
            hr = 2
        key = "_last_daily_report"
        today = nowl.strftime("%Y-%m-%d")
        if not force and (nowl.hour != hr or D.setting(c, key, "") == today):
            return 0
        wait = core.late_hours(S) * 3600
        due = c.execute("""SELECT uid FROM lectures WHERE end_ts + ? < ? AND status!='deleted'
                           AND NOT EXISTS (SELECT 1 FROM reports r WHERE r.lecture_uid=lectures.uid)""", (wait, D.now())).fetchall()
        n = 0
        for r in due:
            try:
                c.execute("BEGIN IMMEDIATE")
                rep = create_report(c, conf, r["uid"])
                if S.get("report_mode") == "auto":
                    auto_dispatch(c, conf, rep)
                c.execute("COMMIT")
                n += 1
            except Exception:
                try:
                    c.execute("ROLLBACK")
                except Exception:
                    pass
        D.set_setting(c, key, today)
        return n
    finally:
        c.close()


# ───────────────────────── النسخ الاحتياطي (مع سجل وفحص) ─────────────────────────
def backup_verified(keep=14):
    """نسخة يومية + فحص integrity_check للنسخة + تسجيل النتيجة. يُرجع True إن أُنشئت نسخة جديدة."""
    import sqlite3
    from config import DATA, DB_PATH
    from datetime import datetime
    d = os.path.join(DATA, "backups")
    os.makedirs(d, exist_ok=True)
    name = os.path.join(d, "attendance_%s.sqlite" % datetime.now().strftime("%Y%m%d"))
    if os.path.exists(name):
        return False
    ok, detail = 1, "ok"
    src = sqlite3.connect(DB_PATH, timeout=30)
    dst = sqlite3.connect(name)
    try:
        src.backup(dst)
        dst.commit()
        res = dst.execute("PRAGMA integrity_check").fetchone()[0]
        if res != "ok":
            ok, detail = 0, res
    except Exception as e:
        ok, detail = 0, str(e)[:200]
    finally:
        dst.close()
        src.close()
    size = os.path.getsize(name) if os.path.exists(name) else 0
    if not ok:
        try:
            os.remove(name)
        except OSError:
            pass
    c = D.connect()
    try:
        c.execute("INSERT INTO backup_log(ts,file,size,ok,detail) VALUES(?,?,?,?,?)", (time.time(), os.path.basename(name), size, ok, detail))
    finally:
        c.close()
    for f in sorted(x for x in os.listdir(d) if x.startswith("attendance_"))[:-keep]:
        try:
            os.remove(os.path.join(d, f))
        except OSError:
            pass
    return bool(ok)
