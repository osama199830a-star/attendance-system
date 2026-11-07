# -*- coding: utf-8 -*-
"""نقاط API الجديدة. تُسجَّل من app.create_app عبر register(app, H) حيث H = أدوات التطبيق (db, J, err, role, session, need …)."""
import hashlib, json, os, time
from flask import request, send_file, session

import db as D
import core
import extras as X


def register(app, H):
    db, J, err, role, need, CONF, MODE = H["db"], H["J"], H["err"], H["role"], H["need"], H["CONF"], H["MODE"]

    def me():
        return {"username": session.get("admin") or "", "full_name": session.get("full_name") or "", "email": session.get("email") or "",
                "role": role(), "college": session.get("college") or "", "dept": session.get("dept") or ""}

    def ip():
        return (request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0] or "?").strip()

    # ═════════ الطالب ═════════
    @app.route("/api/student/email-login", methods=["POST"])
    def s_email_login():
        """تسجيل الطالب ببريده الجامعي الرسمي: يجب أن يكون البريد ضمن قائمة الطلبة المعتمدة. يُربط الحساب بجهاز واحد فقط."""
        b = request.get_json(force=True, silent=True) or {}
        dev = str(b.get("device_id", ""))[:80]
        c = db()
        try:
            S = D.get_settings(c)
            if X.throttle_over(c, "elogin:" + ip(), 20, 600):
                return err("محاولات كثيرة. انتظر بضع دقائق", 429)
            em = X.clean_email(b.get("email"), S.get("email_domain", ""))
            if not em or not dev:
                return err(X.email_hint(S.get("email_domain", "")))
            X.throttle_hit(c, "elogin:" + ip())
            st = c.execute("SELECT * FROM students WHERE lower(univ_email)=? AND deleted=0", (em,)).fetchone()
            if not st:
                return err("هذا البريد غير موجود في قاعدة الطلبة المعتمدة", 404)
            c.execute("BEGIN IMMEDIATE")
            ok, why = core.claim_device(c, st, dev)
            if ok:
                X.enroll_key(c, st, dev, b.get("pub"))
            c.execute("COMMIT")
            if not ok:
                msg = "هذا البريد الجامعي مسجّل مسبقاً على جهاز آخر. يتطلب تغيير الجهاز موافقة العميد أو رئيس القسم." if why == "student_bound_elsewhere" else core.REASONS.get(why, "")
                return J(ok=False, reason=why, message=msg, can_request_change=(why == "student_bound_elsewhere"))
            return J(ok=True, student=X.student_card(c, st), t=D.now())
        finally:
            c.close()

    @app.route("/api/student/device-request", methods=["POST"])
    def s_device_request():
        """طلب تغيير الهاتف (فقد/جهاز جديد). يُسجَّل الجهاز الجديد «معلّقاً» ولا يُفعَّل إلا بموافقة رئيس القسم/العميد."""
        b = request.get_json(force=True, silent=True) or {}
        dev, reason = str(b.get("device_id", ""))[:80], (b.get("reason") or "").strip()[:300]
        c = db()
        try:
            S = D.get_settings(c)
            if X.throttle_over(c, "dreq:" + ip(), 10, 3600):
                return err("محاولات كثيرة", 429)
            X.throttle_hit(c, "dreq:" + ip())
            em = X.clean_email(b.get("email"), S.get("email_domain", ""))
            if not dev or not reason or not em:
                return err("اكتب رقمك الجامعي وسبب تغيير الجهاز")
            st = c.execute("SELECT * FROM students WHERE lower(univ_email)=? AND deleted=0", (em,)).fetchone()
            if not st:
                return err("هذا البريد غير موجود في قاعدة الطلبة المعتمدة", 404)
            if st["device_id"] == dev:
                return err("هذا الجهاز هو جهازك المعتمد أصلاً")
            other = c.execute("SELECT 1 FROM students WHERE device_id=? AND uid!=? AND deleted=0", (dev, st["uid"])).fetchone()
            if other:
                return err("هذا الجهاز مرتبط بحساب طالب آخر")
            pend = c.execute("SELECT uid FROM device_requests WHERE student_uid=? AND status='pending'", (st["uid"],)).fetchone()
            n = D.now()
            pub = X.norm_pub(b.get("pub")) or ""
            c.execute("BEGIN IMMEDIATE")
            if pend:
                c.execute("UPDATE device_requests SET new_device_id=?,new_pub=?,reason=?,updated_at=?,rev=?,dirty=1 WHERE uid=?", (dev, pub, reason, n, D.next_rev(c), pend["uid"]))
                uid = pend["uid"]
            else:
                uid = D.new_uid()
                c.execute("""INSERT INTO device_requests(uid,student_uid,new_device_id,new_pub,reason,email,status,created_at,updated_at,rev,dirty)
                             VALUES(?,?,?,?,?,?,'pending',?,?,?,1)""", (uid, st["uid"], dev, pub, reason, em, n, n, D.next_rev(c)))
                X.notify(c, "device", "طلب تغيير جهاز", "%s: %s" % (st["name"], reason), ref=uid, college=st["college_uid"], dept=st["dept_uid"])
            X.audit(c, em, "student", "device.request", st["uid"], reason)
            c.execute("COMMIT")
            return J(ok=True, uid=uid, message="تم إرسال طلبك إلى رئيس القسم/العميد. ستصلك النتيجة هنا.")
        finally:
            c.close()

    @app.route("/api/student/manual-checkin", methods=["POST"])
    def s_manual():
        """تسجيل حضور بديل بالبريد الجامعي + رمز المحاضرة المعروض على الشاشة. لا يُحتسب حضوراً إلا بموافقة المسؤول (ضوابط تحقق)."""
        b = request.get_json(force=True, silent=True) or {}
        dev = str(b.get("device_id", ""))[:80]
        c = db()
        try:
            S = D.get_settings(c)
            if S.get("manual_checkin", "1") != "1":
                return err("هذه الميزة معطّلة", 403)
            if X.throttle_over(c, "manual:" + ip(), 15, 900):
                return err("محاولات كثيرة", 429)
            X.throttle_hit(c, "manual:" + ip())
            em = X.clean_email(b.get("email"), S.get("email_domain", ""))
            st = c.execute("SELECT * FROM students WHERE lower(univ_email)=? AND deleted=0", (em or "",)).fetchone()
            code = str(b.get("code", "")).strip().upper()
            lec = c.execute("SELECT * FROM lectures WHERE code=? AND status='active' AND end_ts>?", (code, D.now())).fetchone()
            if not st or not lec:
                return err("البريد أو رمز المحاضرة غير صحيح، أو المحاضرة مغلقة")
            if st["device_id"] and st["device_id"] != dev:
                return J(ok=False, message="هذا الجهاز غير معتمد لحسابك")
            old = c.execute("SELECT status FROM attendance WHERE lecture_uid=? AND student_uid=?", (lec["uid"], st["uid"])).fetchone()
            if old and old["status"] in ("ok", "guest_pending", "manual_pending"):
                return J(ok=True, status="duplicate", message="حضورك مسجّل أو قيد المراجعة مسبقاً")
            n = D.now()
            gid = hashlib.sha1((lec["uid"] + "|" + st["uid"]).encode()).hexdigest()[:16]
            c.execute("BEGIN IMMEDIATE")
            c.execute("""INSERT INTO attendance(lecture_uid,student_uid,device_id,code,t,slot_i,status,reason,created_at,updated_at,rev,dirty,queued)
                         VALUES(?,?,?,?,?,?,'manual_pending','manual_pending',?,?,?,1,0)
                         ON CONFLICT(lecture_uid,student_uid) DO UPDATE SET status='manual_pending',reason='manual_pending',updated_at=excluded.updated_at,rev=excluded.rev,dirty=1""",
                      (lec["uid"], st["uid"], dev, code, int(n), int(lec["interval_sec"]), n, n, D.next_rev(c)))
            c.execute("""INSERT OR REPLACE INTO guest_requests(uid,lecture_uid,student_uid,kind,home_grp,lec_grp,status,created_at,updated_at,rev,dirty)
                         VALUES(?,?,?,?,?,?,'pending',?,?,?,1)""", (gid, lec["uid"], st["uid"], "manual", st["grp"] or "", lec["grp"] or "", n, n, D.next_rev(c)))
            X.notify(c, "guest", "تسجيل يدوي بالبريد", "%s سجّل يدوياً بالبريد الجامعي" % st["name"], ref=gid, college=st["college_uid"], dept=st["dept_uid"])
            c.execute("COMMIT")
            return J(ok=True, status="manual_pending", message="تم إرسال طلبك للموافقة.")
        finally:
            c.close()

    @app.route("/api/student/inbox")
    def s_inbox():
        """حالة طلبات الطالب وإشعاراته: يُعرَّف بمعرّف جهازه (المعتمد أو الجديد المعلّق)."""
        dev = request.args.get("device", "")[:80]
        c = db()
        try:
            st = c.execute("SELECT uid FROM students WHERE device_id=? AND deleted=0", (dev,)).fetchone() if dev else None
            drs = c.execute("SELECT uid,student_uid,status,reason,note,created_at,decided_at FROM device_requests WHERE new_device_id=? ORDER BY created_at DESC LIMIT 5", (dev,)).fetchall() if dev else []
            suid = st["uid"] if st else (drs[0]["student_uid"] if drs else None)
            grs, nts = [], []
            if suid:
                grs = c.execute("""SELECT g.uid,g.status,g.kind,g.note,g.created_at,g.decided_at,COALESCE(co.name,'') AS course FROM guest_requests g
                                   LEFT JOIN lectures l ON l.uid=g.lecture_uid LEFT JOIN courses co ON co.uid=l.course_uid
                                   WHERE g.student_uid=? ORDER BY g.created_at DESC LIMIT 10""", (suid,)).fetchall()
                nts = c.execute("SELECT kind,title,body,created_at FROM notifications WHERE student_uid=? ORDER BY id DESC LIMIT 15", (suid,)).fetchall()
            return J(device_requests=[dict(r) for r in drs], guest_requests=[dict(r) for r in grs], notifications=[dict(r) for r in nts], t=D.now())
        finally:
            c.close()

    # ═════════ المسؤولون ═════════
    DECIDERS = ("admin", "dean", "head")

    def scope_sql(alias):
        r = role()
        if r == "admin":
            return "", []
        if r == "dean":
            return " AND %s.college_uid=?" % alias, [session.get("college") or "-"]
        if r == "head":
            return " AND %s.dept_uid=?" % alias, [session.get("dept") or "-"]
        return " AND 0", []

    @app.route("/api/admin/x/requests")
    @need()
    def x_requests():
        c = db()
        try:
            if role() not in DECIDERS + ("rapporteur",):
                return J(device=[], guests=[], can_decide=False)
            w, a = scope_sql("s")
            st = request.args.get("status", "pending")
            cond = "" if st == "all" else " AND d.status='%s'" % ("pending" if st not in ("approved", "rejected") else st)
            dev = c.execute("""SELECT d.*,s.name,s.grp,s.univ_email FROM device_requests d JOIN students s ON s.uid=d.student_uid
                               WHERE 1=1""" + cond + w + " ORDER BY d.created_at DESC LIMIT 200", a).fetchall()
            gcond = cond.replace("d.status", "g.status")
            gst = c.execute("""SELECT g.*,s.name,s.grp,s.univ_email,COALESCE(co.name,'') AS course FROM guest_requests g JOIN students s ON s.uid=g.student_uid
                               LEFT JOIN lectures l ON l.uid=g.lecture_uid LEFT JOIN courses co ON co.uid=l.course_uid
                               WHERE 1=1""" + gcond + w + " ORDER BY g.created_at DESC LIMIT 200", a).fetchall()
            return J(device=[dict(r) for r in dev], guests=[dict(r) for r in gst], can_decide=role() in DECIDERS)
        finally:
            c.close()

    @app.route("/api/admin/x/device-requests/<uid>/decide", methods=["POST"])
    @need()
    def x_dev_decide(uid):
        b = request.get_json(force=True, silent=True) or {}
        decision, note = b.get("decision"), (b.get("note") or "").strip()[:400]
        if role() not in DECIDERS:
            return err("ليست لديك صلاحية البت في طلبات تغيير الأجهزة", 403)
        if decision not in ("approved", "rejected"):
            return err("قرار غير صالح")
        if decision == "rejected" and not note:
            return err("اكتب سبب الرفض")
        c = db()
        try:
            c.execute("BEGIN IMMEDIATE")   # عملية ذرّية: إلغاء القديم + تفعيل الجديد + القرار + التدقيق معاً أو لا شيء
            try:
                r = c.execute("SELECT * FROM device_requests WHERE uid=?", (uid,)).fetchone()
                st = c.execute("SELECT * FROM students WHERE uid=?", (r["student_uid"],)).fetchone() if r else None
                if not r or not st:
                    c.execute("ROLLBACK")
                    return err("الطلب غير موجود", 404)
                if not X.in_scope(role(), session, st):
                    c.execute("ROLLBACK")
                    return err("خارج صلاحيتك", 403)
                if r["status"] != "pending":
                    c.execute("ROLLBACK")
                    return err("تم البت في هذا الطلب سابقاً")
                n = D.now()
                if decision == "approved":
                    taken = c.execute("SELECT 1 FROM students WHERE device_id=? AND uid!=? AND deleted=0", (r["new_device_id"], st["uid"])).fetchone()
                    if taken:
                        c.execute("ROLLBACK")
                        return err("الجهاز الجديد مرتبط بطالب آخر")
                    c.execute("UPDATE students SET device_id=?,bound_at=?,bind_epoch=bind_epoch+1,updated_at=?,rev=?,dirty=1 WHERE uid=?",
                              (r["new_device_id"], n, n, D.next_rev(c), st["uid"]))
                    X.set_key(c, st["uid"], r["new_device_id"], r["new_pub"] or "")
                c.execute("UPDATE device_requests SET status=?,decided_by=?,decided_role=?,decided_at=?,note=?,updated_at=?,rev=?,dirty=1 WHERE uid=?",
                          (decision, session.get("admin"), role(), n, note, n, D.next_rev(c), uid))
                X.audit(c, session.get("admin"), role(), "device.change", st["uid"], "old=%s new=%s" % ((st["device_id"] or "")[:8], (r["new_device_id"] or "")[:8]), decision, note)
                X.notify(c, "device", "تمت الموافقة على تغيير جهازك" if decision == "approved" else "رُفض طلب تغيير جهازك", note, ref=uid, student=st["uid"])
                c.execute("COMMIT")
            except Exception:
                try:
                    c.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            return J(ok=True)
        finally:
            c.close()

    @app.route("/api/admin/x/guest-requests/<uid>/decide", methods=["POST"])
    @need()
    def x_guest_decide(uid):
        b = request.get_json(force=True, silent=True) or {}
        decision, note = b.get("decision"), (b.get("note") or "").strip()[:400]
        if role() not in DECIDERS:
            return err("ليست لديك صلاحية البت في طلبات الضيوف", 403)
        if decision not in ("approved", "rejected"):
            return err("قرار غير صالح")
        if decision == "rejected" and not note:
            return err("اكتب سبب الرفض")
        c = db()
        try:
            c.execute("BEGIN IMMEDIATE")
            try:
                g = c.execute("SELECT * FROM guest_requests WHERE uid=?", (uid,)).fetchone()
                st = c.execute("SELECT * FROM students WHERE uid=?", (g["student_uid"],)).fetchone() if g else None
                if not g or not st:
                    c.execute("ROLLBACK")
                    return err("الطلب غير موجود", 404)
                lec = c.execute("SELECT l.*,c.college_uid AS ccol,c.dept_uid AS cdept FROM lectures l LEFT JOIN courses c ON c.uid=l.course_uid WHERE l.uid=?", (g["lecture_uid"],)).fetchone()
                # الضيف قد يكون من قسم آخر: يُسمح لمن له نطاق على الطالب أو على المحاضرة
                if not (X.in_scope(role(), session, st) or (lec and X.in_scope(role(), session, {"college_uid": lec["ccol"], "dept_uid": lec["cdept"]}))):
                    c.execute("ROLLBACK")
                    return err("خارج صلاحيتك", 403)
                if g["status"] != "pending":
                    c.execute("ROLLBACK")
                    return err("تم البت في هذا الطلب سابقاً")
                n = D.now()
                c.execute("UPDATE guest_requests SET status=?,decided_by=?,decided_role=?,decided_at=?,note=?,updated_at=?,rev=?,dirty=1 WHERE uid=?",
                          (decision, session.get("admin"), role(), n, note, n, D.next_rev(c), uid))
                if decision == "approved":
                    a_status, a_reason = "ok", ("manual_approved" if g["kind"] == "manual" else "guest_approved")
                else:
                    a_status, a_reason = "guest_rejected", "guest_rejected"
                c.execute("UPDATE attendance SET status=?,reason=?,updated_at=?,rev=?,dirty=1 WHERE lecture_uid=? AND student_uid=?",
                          (a_status, a_reason, n, D.next_rev(c), g["lecture_uid"], g["student_uid"]))
                X.audit(c, session.get("admin"), role(), "guest.decide" if g["kind"] == "guest" else "manual.decide", st["uid"], "lecture=%s" % g["lecture_uid"], decision, note)
                X.notify(c, "guest", "تمت الموافقة على حضورك" if decision == "approved" else "رُفض طلب حضورك", note, ref=uid, student=st["uid"])
                c.execute("COMMIT")
            except Exception:
                try:
                    c.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            return J(ok=True)
        finally:
            c.close()

    # ── التقارير والاعتماد ──
    @app.route("/api/admin/x/reports")
    @need()
    def x_reports():
        c = db()
        try:
            r = role()
            q, a = "SELECT * FROM reports WHERE 1=1", []
            if r == "dean":
                q += " AND college_uid=?"; a.append(session.get("college") or "-")
            elif r in ("head", "rapporteur"):
                q += " AND dept_uid=?"; a.append(session.get("dept") or "-")
            elif r == "doctor":
                q += " AND doctor_email=?"; a.append((session.get("email") or "").lower())
            rows = c.execute(q + " ORDER BY created_at DESC LIMIT 200", a).fetchall()
            out = []
            for x in rows:
                d = dict(x)
                chain = json.loads(d["chain"])
                d["chain"] = chain
                d["summary"] = json.loads(d["summary"] or "{}")
                d["waiting_for"] = chain[x["step"]] if x["status"] == "in_review" and x["step"] < len(chain) else ""
                d["mine"] = d["waiting_for"] == r
                d["history"] = [dict(h) for h in c.execute("SELECT step,role,full_name,user,user_email,position,decision,note,ts FROM report_approvals WHERE report_uid=? ORDER BY id", (x["uid"],))]
                out.append(d)
            return J(reports=out, role_ar=X.ROLE_AR)
        finally:
            c.close()

    @app.route("/api/admin/x/reports/create", methods=["POST"])
    @need("reports")
    def x_report_create():
        b = request.get_json(force=True, silent=True) or {}
        c = db()
        try:
            lec = c.execute("SELECT course_uid FROM lectures WHERE uid=?", (b.get("lecture_uid", ""),)).fetchone()
            if not lec or not H["can_course"](c, lec["course_uid"]):
                return err("المحاضرة غير موجودة أو خارج صلاحيتك", 403)
            c.execute("BEGIN IMMEDIATE")
            try:
                rep = X.create_report(c, CONF, b["lecture_uid"], session.get("admin"))
                c.execute("COMMIT")
            except Exception:
                try:
                    c.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            return J(ok=True, number=rep["number"], uid=rep["uid"])
        except ValueError as e:
            return err(str(e))
        finally:
            c.close()

    @app.route("/api/admin/x/reports/<uid>/decide", methods=["POST"])
    @need()
    def x_report_decide(uid):
        b = request.get_json(force=True, silent=True) or {}
        c = db()
        try:
            c.execute("BEGIN IMMEDIATE")
            try:
                ok, msg = X.decide_report(c, CONF, uid, me(), b.get("decision"), b.get("note"))
                c.execute("COMMIT" if ok else "ROLLBACK")
            except Exception:
                try:
                    c.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            return (J(ok=True, message=msg) if ok else err(msg, 403))
        finally:
            c.close()

    @app.route("/api/admin/x/reports/<uid>/file")
    @need()
    def x_report_file(uid):
        c = db()
        try:
            r = c.execute("SELECT * FROM reports WHERE uid=?", (uid,)).fetchone()
            if not r:
                return err("غير موجود", 404)
            rl = role()
            if not (rl == "admin" or X.in_scope(rl, session, r) or (rl == "doctor" and (session.get("email") or "").lower() == (r["doctor_email"] or ""))):
                return err("خارج صلاحيتك", 403)
            from config import EXPORT_DIR
            p = os.path.join(EXPORT_DIR, os.path.basename(r["file_name"]))
            if not os.path.exists(p):
                return err("الملف غير موجود على هذا الخادم", 404)
            return send_file(p, as_attachment=True, download_name=r["file_name"])
        finally:
            c.close()

    # ── الإشعارات وسجل التدقيق ──
    @app.route("/api/admin/x/notifications")
    @need()
    def x_notifs():
        c = db()
        try:
            r = role()
            q, a = "SELECT * FROM notifications WHERE student_uid='' AND (to_role='' OR to_role=?)", [r]
            if r == "dean":
                q += " AND (college_uid='' OR college_uid=?)"; a.append(session.get("college") or "-")
            elif r in ("head", "rapporteur"):
                q += " AND (dept_uid='' OR dept_uid=?)"; a.append(session.get("dept") or "-")
            elif r == "doctor":
                q += " AND (to_email='' OR to_email=?)"; a.append((session.get("email") or "").lower())
            rows = c.execute(q + " ORDER BY id DESC LIMIT 60", a).fetchall()
            return J(items=[dict(x) for x in rows])
        finally:
            c.close()

    @app.route("/api/admin/x/audit")
    @need()
    def x_audit():
        if role() not in ("admin", "dean", "head"):
            return err("ليست لديك صلاحية الاطلاع على سجل التدقيق", 403)
        c = db()
        try:
            rows = c.execute("SELECT id,ts,actor,role,action,target,detail,decision,reason FROM audit_log ORDER BY id DESC LIMIT 300").fetchall()
            bad = X.verify_audit(c) if role() == "admin" else None
            return J(items=[dict(x) for x in rows], chain_ok=bad is None, broken_at=bad)
        finally:
            c.close()

    @app.route("/api/admin/x/chain", methods=["GET", "PUT"])
    @need()
    def x_chain():
        c = db()
        try:
            if request.method == "PUT":
                if role() != "admin":
                    return err("تعديل سلسلة الاعتماد لرئيس الجامعة فقط", 403)
                b = request.get_json(force=True, silent=True) or {}
                ch = [x for x in (b.get("chain") or []) if x in X.ROLES]
                if not ch:
                    return err("اختر مرحلة اعتماد واحدة على الأقل")
                c.execute("BEGIN IMMEDIATE")
                D.set_setting(c, "approval_chain", ",".join(dict.fromkeys(ch)))
                X.audit(c, session.get("admin"), role(), "settings.chain", "approval_chain", ",".join(ch))
                c.execute("COMMIT")
            return J(chain=X.get_chain(D.get_settings(c)), roles=X.ROLE_AR)
        finally:
            c.close()

    @app.route("/api/admin/x/backups")
    @need(top=True)
    def x_backups():
        c = db()
        try:
            return J(items=[dict(r) for r in c.execute("SELECT * FROM backup_log ORDER BY id DESC LIMIT 30")])
        finally:
            c.close()
