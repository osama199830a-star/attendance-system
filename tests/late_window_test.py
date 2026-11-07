# -*- coding: utf-8 -*-
"""اختبار منطق الخادم: مهلة استلام الحضور 24–168 ساعة + تصحيح الخادم لوقت هاتف لم يتزامن + منع الصور القديمة."""
import os, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); SRV = os.path.join(os.path.dirname(HERE), "server")
tmp = tempfile.mkdtemp(); os.environ["ATT_DATA"] = os.path.join(tmp, "local"); os.environ.pop("ATT_MODE", None); sys.path.insert(0, SRV)
import db as D, core
D.init(); c = D.connect()
OK = FAIL = 0
def check(n, cond, x=""):
    global OK, FAIL
    if cond: OK += 1; print("  ✓", n)
    else: FAIL += 1; print("  ✗", n, x)
n0 = D.now()
c.execute("INSERT INTO courses(uid,name) VALUES('c1','فيزياء')")
for k in range(1, 9):
    c.execute("INSERT INTO students(uid,name,name_norm,grp) VALUES(?,?,?,?)", ("s%d" % k, "طالب %d" % k, "طالب %d" % k, "A"))
def lecture(code, start, end):
    c.execute("INSERT INTO lectures(uid,code,course_uid,secret,start_ts,end_ts,interval_sec,status) VALUES(?,?,?,?,?,?,3,'active')", ("L" + code, code, "c1", "sec" + code, start, end))
    return dict(code=code, secret="sec" + code)
def item(lec, stu, t, wall_phone, sent_phone, unsynced=True, offset=0.0):
    """ينشئ ما يرسله التطبيق: age = (wall + offset) − t، و sent_at = ساعة الهاتف لحظة الإرسال."""
    return dict(id="x", code=lec["code"], t=t, i=3, sig=core.sign(lec["secret"], lec["code"], t, 3), student=stu, queued=True,
                age=wall_phone + offset - t, unsynced=unsynced, sent_at=sent_phone * 1000)

# ── 1) مهلة الاستلام: بعد نهاية المحاضرة بـ 167 ساعة مقبول، بـ 169 مرفوض (الإعداد 168) ──
S168 = {"max_sync_delay_hours": "168"}; S24 = {"max_sync_delay_hours": "24"}
lec = dict(secret="s", code="K", start_ts=1000.0, end_ts=2000.0)
sig = core.sign("s", "K", 1500, 3)
check("168س: بعد 167 ساعة من النهاية = مقبول", core.check_scan(lec, 1500, 3, sig, 1, True, 2000 + 167 * 3600, S168)[0] == "ok")
check("168س: بعد 169 ساعة = مرفوض (too_late)", core.check_scan(lec, 1500, 3, sig, 1, True, 2000 + 169 * 3600, S168) == ("rejected", "too_late"))
check("24س: بعد 23 ساعة مقبول", core.check_scan(lec, 1500, 3, sig, 1, True, 2000 + 23 * 3600, S24)[0] == "ok")
check("24س: بعد 25 ساعة مرفوض", core.check_scan(lec, 1500, 3, sig, 1, True, 2000 + 25 * 3600, S24) == ("rejected", "too_late"))
check("قيمة قديمة 1 ساعة تُرفع تلقائياً إلى 24", core.late_hours({"max_sync_delay_hours": "1"}) == 24.0)
check("قيمة 500 تُخفض إلى 168", core.late_hours({"max_sync_delay_hours": "500"}) == 168.0)

# ── 2) هاتف لم يزامن ساعته: ساعته متقدمة ساعة كاملة، لكن الباركود طازج → مقبول بعد تصحيح الخادم ──
n = D.now(); L = lecture("AAA111", n - 1000, n + 600)
t = int(n // 3 * 3)
r = core.record_scan(c, "dev1", item(L, "s1", t, wall_phone=n + 3600 + 1, sent_phone=n + 3600 + 2))
check("ساعة هاتف متقدمة ساعة + باركود طازج + لم يتزامن = حاضر", r["status"] == "ok", r)

# ── 3) هاتف ساعته صحيحة تماماً لكن الباركود صورة قديمة (قبل 120 ثانية) → يُرفض ──
t_old = int((n - 120) // 3 * 3)
r = core.record_scan(c, "dev2", item(L, "s2", t_old, wall_phone=n, sent_phone=n + 5))
check("صورة باركود عمرها دقيقتان (ساعة صحيحة) = مرفوض stale", r == {"status": "rejected", "reason": "stale_qr"}, r)

# ── 4) هاتف ساعته متأخرة 10 دقائق لكن الباركود طازج → مقبول (الخادم يحسب الفرق) ──
t = int(D.now() // 3 * 3); R = D.now()
r = core.record_scan(c, "dev3", item(L, "s3", t, wall_phone=R - 600, sent_phone=R - 600 + 2))
check("ساعة هاتف متأخرة 10 دقائق + باركود طازج = حاضر", r["status"] == "ok", r)

# ── 5) المتزامن (له offset) يبقى يُحسب بعمره المرسل كما كان ──
t = int(D.now() // 3 * 3)
r = core.record_scan(c, "dev4", item(L, "s4", t, wall_phone=D.now(), sent_phone=D.now(), unsynced=False, offset=0))
check("هاتف متزامن: age المرسل يُعتمد (حاضر)", r["status"] == "ok", r)

# ── 6) تكرار وإعادة إرسال ──
r2 = core.record_scan(c, "dev4", item(L, "s4", t, wall_phone=D.now(), sent_phone=D.now(), unsynced=False))
check("إعادة إرسال نفس الحضور = duplicate لا خطأ", r2["status"] == "duplicate", r2)

# ── 7) ربط اسم محجوز لجهاز آخر ──
r = core.record_scan(c, "devX", item(L, "s1", t, wall_phone=D.now(), sent_phone=D.now()))
check("اسم مربوط بجهاز آخر = مرفوض", r["reason"] in ("student_bound_elsewhere",) or r["status"] == "duplicate", r)
print("نجح %d — فشل %d" % (OK, FAIL)); sys.exit(1 if FAIL else 0)
