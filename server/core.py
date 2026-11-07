# -*- coding: utf-8 -*-
"""منطق النظام: التحقق من الباركود، ربط الأجهزة، المزامنة، تصدير Excel، البريد."""
import base64, hashlib, hmac, io, json, os, smtplib, ssl, time, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import db as D
import extras as X

# ───────────────────────── الباركود المتغيّر ─────────────────────────

def sign(secret, code, t, i):
    return hmac.new(secret.encode(), ("%s|%d|%d" % (code, int(t), int(i))).encode(), hashlib.sha256).hexdigest()[:12]


def make_token(lec, at=None):
    """رمز الباركود للحظة الحالية: (t, i, sig). يتغير كل i ثانية."""
    at = D.now() if at is None else at
    i = int(lec["interval_sec"])
    t = int(at // i * i)
    return t, i, sign(lec["secret"], lec["code"], t, i)


def make_fragment(lec, at=None):
    t, i, sig = make_token(lec, at)
    return "AT1.%s.%d.%d.%s" % (lec["code"], t, i, sig)


def late_hours(S):
    """مهلة استلام الحضور بعد نهاية المحاضرة (ساعة): يحددها الدكتور من 24 إلى 168 ساعة (7 أيام)."""
    try:
        return min(168.0, max(24.0, float(S.get("max_sync_delay_hours", 48))))
    except Exception:
        return 48.0


def check_scan(lec, t, i, sig, age, queued, created_at, S):
    """يُرجع (status, reason). age = عمر الباركود لحظة المسح (ثواني)."""
    if not hmac.compare_digest(sign(lec["secret"], lec["code"], t, i), sig or ""):
        return "rejected", "bad_sig"
    if t < lec["start_ts"] - i - 1 or t > lec["end_ts"] + i + 1:
        return "rejected", "outside_window"
    # مهلة استلام الحضور المتأخر (وقت التصدير الذي يحدده المسؤول) تُحسب من نهاية المحاضرة
    if created_at > lec["end_ts"] + late_hours(S) * 3600:
        return "rejected", "too_late"
    grace = float(S.get("scan_grace", 10))
    if queued and S.get("allow_offline_scan", "1") != "1":
        return "rejected", "offline_not_allowed"
    limit = i + grace + (0 if queued else 3)
    if age is None or age > limit or age < -8:
        return "rejected", "stale_qr"
    return "ok", ""


REASONS = {
    "bad_sig": "باركود غير صالح", "outside_window": "خارج وقت المحاضرة", "too_late": "انتهت مهلة استلام الحضور لهذه المحاضرة",
    "offline_not_allowed": "التسجيل غير المتصل غير مسموح", "stale_qr": "الباركود منتهٍ (صوّر أو أُرسل متأخراً)",
    "unknown_student": "الطالب غير موجود",
    **X.REASONS, "device_bound_other": "هذا الجهاز مرتبط بطالب آخر",
    "student_bound_elsewhere": "هذا الاسم مرتبط بجهاز آخر", "not_enrolled": "هذه المحاضرة ليست لقسمك أو مرحلتك", "": "",
}


def claim_device(c, st, device_id):
    other = c.execute("SELECT uid FROM students WHERE device_id=? AND uid!=? AND deleted=0", (device_id, st["uid"])).fetchone()
    if other:
        return False, "device_bound_other"
    if st["device_id"] and st["device_id"] != device_id:
        return False, "student_bound_elsewhere"
    if not st["device_id"]:
        n = D.now()
        c.execute("UPDATE students SET device_id=?, bound_at=?, updated_at=?, rev=?, dirty=1 WHERE uid=?",
                  (device_id, n, n, D.next_rev(c), st["uid"]))
    return True, ""


def record_scan(c, device_id, item, recv_ts=None):
    """يسجّل مسحاً واحداً. يُرجع dict(status, reason).
    recv_ts: وقت وصول رسالة البريد (يحدده خادم البريد لا الهاتف) عندما يُعالَج الحضور لاحقاً من الإيميل؛ يُستعمل لفحص مهلة الاستلام."""
    S = D.get_settings(c)
    n = D.now()
    if not item.get("student") and item.get("sid"):      # دخل الطالب برقمه بلا خادم: نعرّفه من بريده الجامعي
        _em = X.clean_email(str(item["sid"]), S.get("email_domain", ""))
        _r = c.execute("SELECT uid FROM students WHERE lower(univ_email)=? AND deleted=0", (_em or "",)).fetchone()
        if not _r:
            return {"status": "rejected", "reason": "unknown_student"}
        item = dict(item, sig_student=item.get("student", ""), student=_r["uid"])
    if recv_ts:
        n = float(recv_ts)
        item = dict(item, sent_at=float(recv_ts) * 1000.0)
    code, student = str(item.get("code", "")), str(item.get("student", ""))
    try:
        t, i = int(item["t"]), int(item["i"])
    except Exception:
        return {"status": "rejected", "reason": "bad_sig"}
    sig = str(item.get("sig", ""))
    queued = bool(item.get("queued"))
    st = c.execute("SELECT * FROM students WHERE uid=? AND deleted=0", (student,)).fetchone()
    if not st:
        return {"status": "rejected", "reason": "unknown_student"}
    ok, why = claim_device(c, st, device_id)
    if not ok:
        return {"status": "rejected", "reason": why}
    ok, why = X.check_device_sig(c, st, device_id, item, S)   # توقيع مفتاح الجهاز (ECDSA)
    if not ok:
        return {"status": "rejected", "reason": why}
    try:
        if queued:
            age = float(item.get("age"))
            # هاتف لم يزامن ساعته مع الخادم قبل المسح: الخادم يصحّح العمر بنفسه.
            # age_claimed = ساعة_الهاتف_وقت_المسح − t  (بافتراض فرق 0)،  والفرق الحقيقي δ = ساعة_الخادم_الآن − ساعة_الهاتف_الآن
            # فالعمر الحقيقي = age_claimed + δ — فلا تنفع ساعة هاتف مضبوطة خطأً ولا صورة قديمة للباركود.
            if item.get("unsynced"):
                sent = float(item.get("sent_at")) / 1000.0
                age = age + (n - sent)
        else:  # عمر الباركود محسوب بساعة الخادم (أدق من ساعة الجهاز)
            age = n - float(item.get("elapsed", 0)) - t
    except Exception:
        age = None
    lec = c.execute("SELECT * FROM lectures WHERE code=?", (code,)).fetchone()
    old = None
    if lec:
        co = c.execute("SELECT dept_uid,stage FROM courses WHERE uid=?", (lec["course_uid"],)).fetchone()
        if co and co["dept_uid"] and st["dept_uid"] and (st["dept_uid"] != co["dept_uid"] or int(st["stage"] or 0) != int(co["stage"] or 0)):
            return {"status": "rejected", "reason": "not_enrolled"}
        old = c.execute("SELECT status FROM attendance WHERE lecture_uid=? AND student_uid=?", (lec["uid"], student)).fetchone()
        if old and old["status"] == "ok":
            return {"status": "duplicate", "reason": ""}
        if old and old["status"] in ("guest_pending", "manual_pending"):
            return {"status": old["status"], "reason": old["status"]}
        status, reason = check_scan(lec, t, i, sig, age, queued, n, S)
        status, reason = X.finalize_status(c, lec, st, status, reason, t, S)   # ضيف/متأخر
        luid = lec["uid"]
    else:  # المحاضرة لم تصل بعد إلى هذا الخادم (مزامنة لاحقة) — نحفظ الطلب للتحقق لاحقاً
        status, reason, luid = "pending", "", "code:" + code
    c.execute("""INSERT INTO attendance(lecture_uid,student_uid,device_id,code,t,slot_i,sig,age,queued,status,reason,created_at,updated_at,rev,dirty)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                 ON CONFLICT(lecture_uid,student_uid) DO UPDATE SET device_id=excluded.device_id,t=excluded.t,slot_i=excluded.slot_i,
                 sig=excluded.sig,age=excluded.age,queued=excluded.queued,status=excluded.status,reason=excluded.reason,
                 updated_at=excluded.updated_at,rev=excluded.rev,dirty=excluded.dirty""",
              (luid, student, device_id, code, t, i, sig, age, int(queued), status, reason, n, n, D.next_rev(c), 0 if status == "pending" else 1))
    return {"status": status, "reason": reason}


def verify_pending(c):
    """بعد وصول محاضرات جديدة: نتحقق من الحضور المعلّق."""
    S = D.get_settings(c)
    rows = c.execute("SELECT * FROM attendance WHERE status='pending'").fetchall()
    cnt = 0
    for r in rows:
        lec = c.execute("SELECT * FROM lectures WHERE code=?", (r["code"],)).fetchone()
        if not lec:
            continue
        status, reason = check_scan(lec, int(r["t"]), int(r["slot_i"]), r["sig"], r["age"], bool(r["queued"]), r["created_at"], S)
        _st = c.execute("SELECT * FROM students WHERE uid=?", (r["student_uid"],)).fetchone()
        if _st:
            status, reason = X.finalize_status(c, lec, _st, status, reason, int(r["t"]), S)
        n = D.now()
        ex = c.execute("SELECT status FROM attendance WHERE lecture_uid=? AND student_uid=?", (lec["uid"], r["student_uid"])).fetchone()
        if ex and ex["status"] == "ok":      # مسجَّل أصلاً: لا نُنزل حالته بسبب نسخة معلّقة
            c.execute("DELETE FROM attendance WHERE lecture_uid=? AND student_uid=?", (r["lecture_uid"], r["student_uid"]))
            continue
        c.execute("DELETE FROM attendance WHERE lecture_uid=? AND student_uid=?", (lec["uid"], r["student_uid"]))
        c.execute("UPDATE attendance SET lecture_uid=?, status=?, reason=?, updated_at=?, rev=?, dirty=1 WHERE lecture_uid=? AND student_uid=?",
                  (lec["uid"], status, reason, n, D.next_rev(c), r["lecture_uid"], r["student_uid"]))
        cnt += 1
    return cnt


# ───────────────────────── المزامنة ─────────────────────────
TABLES = {
    "colleges": ("uid", ["name", "deleted"]),
    "departments": ("uid", ["college_uid", "name", "stages", "deleted"]),
    "courses": ("uid", ["name", "doctor_email", "duration_sec", "deleted", "college_uid", "dept_uid", "stage", "kind"]),
    "lectures": ("uid", ["code", "course_uid", "secret", "start_ts", "end_ts", "interval_sec", "status", "station", "grp"]),
    "students": ("uid", ["name", "name_norm", "grp", "deleted", "college_uid", "dept_uid", "stage", "univ_email"]),
    "device_keys": ("student_uid", ["device_id", "pub"]),
    "guest_requests": ("uid", ["lecture_uid", "student_uid", "kind", "home_grp", "lec_grp", "status", "decided_by", "decided_role", "decided_at", "note", "created_at"]),
    "device_requests": ("uid", ["student_uid", "new_device_id", "new_pub", "reason", "email", "status", "decided_by", "decided_role", "decided_at", "note", "created_at"]),
    "attendance": (("lecture_uid", "student_uid"), ["device_id", "code", "t", "slot_i", "sig", "age", "queued", "status", "reason", "created_at"]),
}


def _keycols(t):
    k = TABLES[t][0]
    return list(k) if isinstance(k, tuple) else [k]


def _cols(t):
    return _keycols(t) + TABLES[t][1] + ["updated_at"] + (["device_id", "bound_at", "bind_epoch"] if t == "students" else [])


def row_dict(r, t):
    cols = _cols(t)
    return {k: r[k] for k in dict.fromkeys(cols)}


def collect_dirty(c):
    out, marks = {}, []
    for t in TABLES:
        where = "dirty=1" + (" AND status!='pending'" if t == "attendance" else "")
        rows = c.execute("SELECT * FROM %s WHERE %s" % (t, where)).fetchall()
        out[t] = [row_dict(r, t) for r in rows]
        for r in rows:
            marks.append((t, [r[k] for k in _keycols(t)], r["updated_at"]))
    return out, marks


def mark_clean(c, marks):
    for t, key, upd in marks:
        cond = " AND ".join("%s=?" % k for k in _keycols(t))
        c.execute("UPDATE %s SET dirty=0 WHERE %s AND updated_at=?" % (t, cond), key + [upd])


def collect_since(c, since, upto):
    out = {}
    for t in TABLES:
        where = "rev>? AND rev<=?" + (" AND status!='pending'" if t == "attendance" else "")
        out[t] = [row_dict(r, t) for r in c.execute("SELECT * FROM %s WHERE %s" % (t, where), (since, upto)).fetchall()]
    return out


def merge_rows(c, rows_by_table, clean=True):
    """دمج صفوف قادمة من النظير. يُرجع عدد الصفوف التي تغيّرت."""
    changed = 0
    for t, rows in rows_by_table.items():
        if t not in TABLES:
            continue
        kc = _keycols(t)
        fields = TABLES[t][1]
        for r in rows:
            key = [r.get(k) for k in kc]
            if any(v is None for v in key):
                continue
            cond = " AND ".join("%s=?" % k for k in kc)
            cur = c.execute("SELECT * FROM %s WHERE %s" % (t, cond), key).fetchone()
            inc_upd = float(r.get("updated_at") or 0)
            d = 0 if clean else 1
            if t == "lectures" and not cur:
                dup = c.execute("SELECT uid FROM lectures WHERE code=?", (r.get("code"),)).fetchone()
                if dup:
                    continue
            if not cur:
                cols = kc + fields + ["updated_at", "rev", "dirty"]
                vals = key + [r.get(f) for f in fields] + [inc_upd, D.next_rev(c), d]
                if t == "students":
                    cols += ["device_id", "bound_at", "bind_epoch"]
                    vals += [r.get("device_id"), r.get("bound_at"), int(r.get("bind_epoch") or 0)]
                c.execute("INSERT INTO %s(%s) VALUES(%s)" % (t, ",".join(cols), ",".join("?" * len(cols))), vals)
                changed += 1
                continue
            did = False
            if inc_upd > (cur["updated_at"] or 0):
                sets = ",".join("%s=?" % f for f in fields) + ",updated_at=?,rev=?,dirty=?"
                c.execute("UPDATE %s SET %s WHERE %s" % (t, sets, cond),
                          [r.get(f) for f in fields] + [inc_upd, D.next_rev(c), d] + key)
                did = True
            if t == "students":
                ie, ce = int(r.get("bind_epoch") or 0), int(cur["bind_epoch"] or 0)
                take = False
                if ie > ce:
                    take = True
                elif ie == ce and r.get("device_id") and r.get("device_id") != cur["device_id"]:
                    take = (not cur["device_id"]) or (float(r.get("bound_at") or 1e18) < float(cur["bound_at"] or 1e18))
                if take:
                    c.execute("UPDATE students SET device_id=?,bound_at=?,bind_epoch=?,rev=?,dirty=? WHERE uid=?",
                              (r.get("device_id"), r.get("bound_at"), ie, D.next_rev(c), d, r["uid"]))
                    did = True
            changed += 1 if did else 0
    return changed


def http_json(url, payload, key, timeout=25):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "X-Sync-Key": key})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def sync_once(conf):
    """مزامنة ثنائية الاتجاه مع السحابة. يُرجع dict ملخص أو يرفع استثناء عند انقطاع الإنترنت."""
    base = (conf.get("cloud_url") or "").rstrip("/")
    if not base or not conf.get("sync_key"):
        return {"skipped": True}
    c = D.connect()
    try:
        since = int(D.setting(c, "_cloud_rev", "0"))
        push, marks = collect_dirty(c)
        t0 = time.time()
        resp = http_json(base + "/api/sync/exchange", {"since": since, "push": push}, conf["sync_key"])
        t1 = time.time()
        c.execute("BEGIN IMMEDIATE")
        try:
            # تصحيح ساعة الجهاز بساعة السحابة (إلا أثناء محاضرة جارية حتى لا يقفز الباركود)
            if resp.get("t") and (t1 - t0) < 6:
                off = float(resp["t"]) - (t0 + t1) / 2
                busy = c.execute("SELECT 1 FROM lectures WHERE status='active' AND end_ts>? LIMIT 1", (D.now(),)).fetchone()
                if not busy:
                    off = 0.0 if abs(off) < 1.0 else off
                    D.set_offset(off)
                    D.set_setting(c, "_clock_offset", off)
            ch = merge_rows(c, resp.get("pull", {}), clean=True)
            for k, v in (resp.get("settings") or {}).items():
                if k in D.SYNC_SETTINGS:
                    D.set_setting(c, k, v)
            mark_clean(c, marks)
            verify_pending(c)
            D.set_setting(c, "_cloud_rev", int(resp["rev"]))
            D.set_setting(c, "_last_sync", int(D.now()))
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
        return {"pushed": sum(len(v) for v in push.values()), "pulled": ch}
    finally:
        c.close()


# ───────────────────────── تصدير Excel ─────────────────────────
TZ = timezone(timedelta(hours=3))  # توقيت العراق (لا يوجد توقيت صيفي)


def fmt_ts(ts):
    return datetime.fromtimestamp(ts, TZ).strftime("%Y-%m-%d %H:%M")


def build_export(c, course_uid, path, group=None, date_from=None, date_to=None):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
    from openpyxl.utils import get_column_letter
    course = c.execute("SELECT * FROM courses WHERE uid=?", (course_uid,)).fetchone()
    if not course:
        raise ValueError("المادة غير موجودة")
    q, args = "SELECT * FROM lectures WHERE course_uid=?", [course_uid]
    if date_from:
        q += " AND start_ts>=?"
        args.append(date_from)
    if date_to:
        q += " AND start_ts<=?"
        args.append(date_to)
    lectures = c.execute(q + " ORDER BY start_ts", args).fetchall()
    sq, sa = "SELECT * FROM students WHERE deleted=0", []
    _w, _a = cohort_filter(course); sq += _w; sa += _a
    if group:
        sq += " AND grp=?"
        sa.append(group)
    students = c.execute(sq + " ORDER BY grp, name_norm", sa).fetchall()
    present = set()
    if lectures:
        marks = ",".join("?" * len(lectures))
        for r in c.execute("SELECT lecture_uid,student_uid FROM attendance WHERE status='ok' AND lecture_uid IN (%s)" % marks,
                           [l["uid"] for l in lectures]):
            present.add((r[0], r[1]))
    wb = Workbook()
    ws = wb.active
    ws.title = "الحضور"
    ws.sheet_view.rightToLeft = True
    head = ["#", "اسم الطالب", "الكروب"] + ["محاضرة %d\n%s" % (k + 1, fmt_ts(l["start_ts"])) for k, l in enumerate(lectures)] + ["عدد الحضور", "عدد الغياب", "النسبة %", "الحالة"]
    ws.append(["%s — %s" % (D.setting(c, "org_name", ""), course["name"])])
    ws.append(head)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(4, len(head)))
    ws["A1"].font = Font(bold=True, size=14, color="FFFFFF")
    ws["A1"].fill = PatternFill("solid", fgColor="2C5599")
    ws["A1"].alignment = Alignment(horizontal="center")
    thin = Side(style="thin", color="B0B7C3")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    green, red = PatternFill("solid", fgColor="D5F0DA"), PatternFill("solid", fgColor="F8D7DA")
    for cell in ws[2]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="2C5599")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = box
    nl = len(lectures)
    limit = float(D.setting(c, "absence_limit", "25") or 0)
    amber = PatternFill("solid", fgColor="FFE3B3")
    grp_stats = {}
    for idx, s in enumerate(students, 1):
        row = [idx, s["name"], s["grp"]]
        cnt = 0
        for l in lectures:
            p = (l["uid"], s["uid"]) in present
            cnt += p
            row.append("حاضر" if p else "غائب")
        pct = round(cnt * 100 / nl) if nl else 0
        risk = bool(nl and limit and (nl - cnt) * 100 / nl > limit)
        row += [cnt, nl - cnt, pct, ("إنذار غياب" if risk else "—")]
        gs = grp_stats.setdefault(s["grp"] or "—", [0, 0, 0])
        gs[0] += 1; gs[1] += pct; gs[2] += 1 if risk else 0
        ws.append(row)
        r = ws.max_row
        for col in range(1, len(row) + 1):
            cell = ws.cell(r, col)
            cell.border = box
            cell.alignment = Alignment(horizontal="center") if col != 2 else Alignment(horizontal="right")
            if 4 <= col < 4 + nl:
                cell.fill = green if cell.value == "حاضر" else red
            elif risk and (col == 2 or col > 3 + nl):
                cell.fill = amber
                cell.font = Font(bold=True, color="8A4B00")
    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 38
    ws.column_dimensions["C"].width = 10
    for col in range(4, len(head) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 16 if col < 4 + nl else 13
    ws.row_dimensions[2].height = 34
    ws.freeze_panes = "D3"
    ws2 = wb.create_sheet("المحاضرات")
    ws2.sheet_view.rightToLeft = True
    ws2.append(["#", "الوقت", "رمز المحاضرة", "عدد الحاضرين", "الحالة"])
    for k, l in enumerate(lectures, 1):
        n_ok = sum(1 for s in students if (l["uid"], s["uid"]) in present)
        ws2.append([k, fmt_ts(l["start_ts"]), l["code"], n_ok, "منتهية" if l["status"] == "ended" else "جارية/غير مغلقة"])
    for cell in ws2[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="2C5599")
    for col, w in zip("ABCDE", (5, 20, 16, 14, 18)):
        ws2.column_dimensions[col].width = w
    # ورقة ملخص + ورقة لكل كروب
    ws3 = wb.create_sheet("ملخص الكروبات", 1)
    ws3.sheet_view.rightToLeft = True
    ws3.append(["الكروب", "عدد الطلاب", "متوسط الحضور %", "طلاب بإنذار غياب"])
    for g in sorted(grp_stats):
        n_, tot, rk = grp_stats[g]
        ws3.append([g, n_, round(tot / n_) if n_ else 0, rk])
    alln = sum(v[0] for v in grp_stats.values())
    ws3.append(["الكل", alln, round(sum(v[1] for v in grp_stats.values()) / alln) if alln else 0, sum(v[2] for v in grp_stats.values())])
    for cell in ws3[1]:
        cell.font = Font(bold=True, color="FFFFFF"); cell.fill = PatternFill("solid", fgColor="2C5599"); cell.alignment = Alignment(horizontal="center")
    for cell in ws3[ws3.max_row]:
        cell.font = Font(bold=True)
    for col, w in zip("ABCD", (14, 14, 18, 20)):
        ws3.column_dimensions[col].width = w
    if len(grp_stats) > 1 and not group:
        hdr = [cell.value for cell in ws[2]]
        for g in sorted(grp_stats):
            wg = wb.create_sheet("كروب %s" % str(g)[:20])
            wg.sheet_view.rightToLeft = True
            wg.append(hdr)
            k = 0
            for row in ws.iter_rows(min_row=3, values_only=False):
                if (row[2].value or "—") == g:
                    k += 1
                    wg.append([k] + [cell.value for cell in row[1:]])
                    for cell_src, cell_dst in zip(row, wg[wg.max_row]):
                        cell_dst.fill = cell_src.fill.copy(); cell_dst.font = cell_src.font.copy()
                        cell_dst.alignment = cell_src.alignment.copy(); cell_dst.border = cell_src.border.copy()
            for cell in wg[1]:
                cell.font = Font(bold=True, color="FFFFFF"); cell.fill = PatternFill("solid", fgColor="2C5599")
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            wg.column_dimensions["B"].width = 38
            wg.freeze_panes = "D2"
    wb.save(path)
    return {"course": course["name"], "doctor_email": course["doctor_email"], "lectures": nl, "students": len(students)}


def cohort_filter(course):
    """شرط SQL لطلاب المادة: طلاب نفس القسم والمرحلة. المواد القديمة بلا قسم تشمل الجميع."""
    if course is not None and course["dept_uid"]:
        return " AND dept_uid=? AND stage=?", [course["dept_uid"], int(course["stage"] or 0)]
    return "", []


def course_stats(c, course_uid, group=None):
    """إحصاءات المادة: متوسط الحضور، حسب الكروب، حسب المحاضرة، والمعرَّضون للحرمان."""
    limit = float(D.setting(c, "absence_limit", "25") or 0)
    lecs = c.execute("SELECT uid,start_ts,code FROM lectures WHERE course_uid=? AND status!='deleted' ORDER BY start_ts", (course_uid,)).fetchall()
    sq, sa = "SELECT uid,name,grp FROM students WHERE deleted=0", []
    _cs = c.execute("SELECT * FROM courses WHERE uid=?", (course_uid,)).fetchone()
    _w, _a = cohort_filter(_cs); sq += _w; sa += _a
    if group:
        sq += " AND grp=?"; sa.append(group)
    studs = c.execute(sq + " ORDER BY grp,name_norm", sa).fetchall()
    ok = {}
    if lecs:
        marks = ",".join("?" * len(lecs))
        for r in c.execute("SELECT lecture_uid,student_uid FROM attendance WHERE status='ok' AND lecture_uid IN (%s)" % marks, [l["uid"] for l in lecs]):
            ok.setdefault(r[1], set()).add(r[0])
    nl = len(lecs)
    per_lec = [{"code": l["code"], "t": l["start_ts"], "present": sum(1 for s in studs if l["uid"] in ok.get(s["uid"], ()))} for l in lecs]
    groups, risky, tot = {}, [], 0
    for s in studs:
        n_ok = len(ok.get(s["uid"], ()))
        pct = round(n_ok * 100 / nl) if nl else 0
        tot += pct
        g = groups.setdefault(s["grp"] or "—", {"students": 0, "sum": 0, "risk": 0})
        g["students"] += 1; g["sum"] += pct
        if nl and limit and (nl - n_ok) * 100 / nl > limit:
            g["risk"] += 1
            risky.append({"name": s["name"], "grp": s["grp"], "present": n_ok, "absent": nl - n_ok, "pct": pct})
    risky.sort(key=lambda r: r["pct"])
    return {"lectures": nl, "students": len(studs), "avg": round(tot / len(studs)) if studs else 0, "limit": limit,
            "per_lecture": per_lec, "groups": [{"grp": k, "students": v["students"], "avg": round(v["sum"] / v["students"]) if v["students"] else 0, "risk": v["risk"]} for k, v in sorted(groups.items())],
            "risky": risky[:200], "risk_count": len(risky)}


def safe_name(s):
    return "".join(ch if ch.isalnum() or ch in " _-" else "_" for ch in s).strip().replace(" ", "_")[:60] or "course"


# ───────────────────────── البريد ─────────────────────────

def enqueue_mail(c, to, cc, subject, body, attach_path):
    c.execute("INSERT INTO outbox(to_addrs,cc,subject,body,attach_path,created_at) VALUES(?,?,?,?,?,?)",
              (to or "", cc or "", subject, body, attach_path, D.now()))
    return c.execute("SELECT last_insert_rowid()").fetchone()[0]


def _smtp_send(S, to, cc, subject, body, fname, data):
    msg = EmailMessage()
    msg["From"] = S["smtp_user"]
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
    msg.set_content(body)
    if data:
        msg.add_attachment(data, maintype="application", subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=fname)
    port = int(S.get("smtp_port") or 465)
    if port == 465:
        with smtplib.SMTP_SSL(S["smtp_host"], port, context=ssl.create_default_context(), timeout=30) as s:
            s.login(S["smtp_user"], S["smtp_pass"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(S["smtp_host"], port, timeout=30) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(S["smtp_user"], S["smtp_pass"])
            s.send_message(msg)


def flush_outbox(conf):
    """يرسل الرسائل المعلّقة: مباشرة عبر SMTP المحلي، أو عبر السحابة إن لم يُضبط بريد محلي."""
    c = D.connect()
    sent = failed = 0
    try:
        S = D.get_settings(c)
        for m in c.execute("SELECT * FROM outbox WHERE sent_at IS NULL ORDER BY id").fetchall():
            try:
                data = open(m["attach_path"], "rb").read() if m["attach_path"] and os.path.exists(m["attach_path"]) else None
                fname = os.path.basename(m["attach_path"]) if m["attach_path"] else "attendance.xlsx"
                if S.get("smtp_user") and S.get("smtp_pass"):
                    _smtp_send(S, m["to_addrs"], m["cc"], m["subject"], m["body"], fname, data)
                elif conf.get("cloud_url") and conf.get("sync_key"):
                    http_json(conf["cloud_url"].rstrip("/") + "/api/sync/mail",
                              {"to": m["to_addrs"], "cc": m["cc"], "subject": m["subject"], "body": m["body"], "filename": fname,
                               "data": base64.b64encode(data).decode() if data else ""}, conf["sync_key"], timeout=60)
                else:
                    raise RuntimeError("لم يُضبط بريد الإرسال (SMTP) ولا السحابة")
                c.execute("UPDATE outbox SET sent_at=?, tries=tries+1, last_error=NULL WHERE id=?", (D.now(), m["id"]))
                sent += 1
            except Exception as e:
                c.execute("UPDATE outbox SET tries=tries+1, last_error=? WHERE id=?", (str(e)[:300], m["id"]))
                failed += 1
    finally:
        c.close()
    return {"sent": sent, "failed": failed}


def export_and_mail(c, conf, course_uid, **kw):
    course = c.execute("SELECT * FROM courses WHERE uid=?", (course_uid,)).fetchone()
    if not course:
        raise ValueError("المادة غير موجودة")
    from config import EXPORT_DIR
    fname = "حضور_%s_%s.xlsx" % (safe_name(course["name"]), datetime.now(TZ).strftime("%Y%m%d_%H%M"))
    path = os.path.join(EXPORT_DIR, fname)
    info = build_export(c, course_uid, path, **kw)
    S = D.get_settings(c)
    doc, adm = course["doctor_email"], S.get("admin_email", "")
    if S.get("mail_doctor", "1") == "1":   # يصل للدكتور + نسخة للمسؤول
        to, cc = doc, adm
    else:                                   # يصل للمسؤول فقط ليحوّله هو للدكتور
        to, cc = adm, ""
    mail_id = None
    if to or cc:
        body = "السلام عليكم،\nمرفق ملف Excel بحضور مادة «%s».\nعدد المحاضرات: %d — عدد الطلاب: %d\nإيميل التدريسي: %s\n%s" % (
            course["name"], info["lectures"], info["students"], doc or "—", S.get("org_name", ""))
        mail_id = enqueue_mail(c, to or cc, cc if to else "", "تقرير الحضور — %s" % course["name"], body, path)
    return {"path": path, "filename": fname, "mail_id": mail_id, **info}


# ───────────────────────── تصدير تلقائي عند انتهاء مهلة الاستلام ─────────────────────────

def run_auto_exports(conf):
    """بعد (نهاية المحاضرة + مهلة الاستلام) يُصدَّر تقرير المادة ويُرسل تلقائياً مرة واحدة. يعمل على السحابة (أو الجهاز المحلي إن لم تُضبط سحابة)."""
    c = D.connect()
    try:
        S = D.get_settings(c)
        if S.get("auto_export", "0") != "1":
            return 0
        n = D.now()
        wait = late_hours(S) * 3600
        due = c.execute("""SELECT l.uid, l.course_uid FROM lectures l
                           WHERE l.end_ts + ? < ? AND l.status!='deleted'
                             AND NOT EXISTS (SELECT 1 FROM auto_exports a WHERE a.lecture_uid=l.uid)""", (wait, n)).fetchall()
        courses = {}
        for r in due:
            courses.setdefault(r["course_uid"], []).append(r["uid"])
        done = 0
        for cu, luids in courses.items():
            if not c.execute("SELECT 1 FROM courses WHERE uid=? AND deleted=0", (cu,)).fetchone():
                for lu in luids:
                    c.execute("INSERT OR IGNORE INTO auto_exports VALUES(?,?)", (lu, n))
                continue
            export_and_mail(c, conf, cu)
            for lu in luids:
                c.execute("INSERT OR IGNORE INTO auto_exports VALUES(?,?)", (lu, n))
            done += 1
        return done
    finally:
        c.close()


def backup_db(keep=7):
    """نسخة احتياطية يومية لقاعدة البيانات (آخر 7 نسخ)."""
    import sqlite3
    from config import DATA, DB_PATH
    d = os.path.join(DATA, "backups")
    os.makedirs(d, exist_ok=True)
    name = os.path.join(d, "attendance_%s.sqlite" % datetime.now(TZ).strftime("%Y%m%d"))
    if os.path.exists(name):
        return False
    src = sqlite3.connect(DB_PATH, timeout=30)
    dst = sqlite3.connect(name)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    for f in sorted(os.listdir(d))[:-keep]:
        try:
            os.remove(os.path.join(d, f))
        except OSError:
            pass
    return True
