# -*- coding: utf-8 -*-
import base64, io, json, os, threading, time
from functools import wraps

from flask import Flask, jsonify, request, session, send_file, send_from_directory, redirect, abort, Response
from werkzeug.security import check_password_hash, generate_password_hash

import re
import config, core, db as D, qr as QR
import extras as X
import routes_x

CONF = config.load_conf()
MODE = config.MODE


def create_app():
    D.init()
    app = Flask(__name__, static_folder=None)
    app.secret_key = CONF["session_secret"]
    app.config.update(SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True, MAX_CONTENT_LENGTH=20 * 1024 * 1024,
                      SESSION_COOKIE_SECURE=(MODE == "cloud" and os.environ.get("COOKIE_SECURE", "1") != "0"))
    if MODE == "cloud":   # خلف وكيل HTTPS الخاص بالمنصة
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    c = D.connect()
    if not c.execute("SELECT 1 FROM admins").fetchone():
        user, pw = os.environ.get("ADMIN_USER", "admin"), os.environ.get("ADMIN_PASS")
        c.execute("INSERT INTO admins(username,pw_hash,must_change) VALUES(?,?,?)",
                  (user, generate_password_hash(pw or "admin123"), 0 if pw else 1))
    c.close()

    # ── أدوات ──
    def db():
        return D.connect()

    def J(**kw):
        return jsonify(kw)

    def err(msg, code=400):
        return jsonify(error=msg), code

    PERMS = {"courses": "إدارة المواد", "students": "رفع وإدارة الطلاب", "doctors": "حسابات الدكاترة",
             "reports": "التقارير والتصدير", "lectures": "عرض المحاضرات وتعديل الحضور", "unbind": "فك ربط أجهزة الطلاب"}
    RANK = {"admin": 0, "dean": 1, "head": 2, "rapporteur": 3, "doctor": 4}
    ROLE_AR = {"admin": "رئيس الجامعة (مسؤول النظام)", "dean": "عميد كلية", "head": "رئيس قسم", "rapporteur": "مقرر قسم", "doctor": "تدريسي"}

    def role():
        return session.get("role", "admin")

    def eff_perms():
        r = role()
        if r in ("admin", "dean"):
            return set(PERMS)
        if r == "doctor":
            return {"lectures", "reports"}
        return set(session.get("perms") or [])

    def has(perm):
        return perm in eff_perms()

    def need(perm=None, top=False):
        """top=True: لرئيس الجامعة فقط. perm: صلاحية مطلوبة. بدونهما: أي مستخدم مسجّل."""
        def deco(f):
            @wraps(f)
            def w(*a, **k):
                if not session.get("admin"):
                    return err("يجب تسجيل الدخول", 401)
                if top and role() != "admin":
                    return err("هذه الصفحة لرئيس الجامعة فقط", 403)
                if perm and not has(perm):
                    return err("ليست لديك صلاحية: " + PERMS.get(perm, perm), 403)
                return f(*a, **k)
            return w
        return deco

    admin_required = need(top=True)
    staff_required = need()

    def is_doctor():
        return role() == "doctor"

    def course_scope(alias=""):
        """شرط SQL (وسيطاته) يحصر المواد بصلاحية المستخدم: العميد = كليته، رئيس/مقرر القسم = قسمه، التدريسي = مواده."""
        a = alias + "." if alias else ""
        r = role()
        if r == "admin":
            return "", []
        if r == "dean":
            return " AND %scollege_uid=?" % a, [session.get("college") or "-"]
        if r in ("head", "rapporteur"):
            return " AND %sdept_uid=?" % a, [session.get("dept") or "-"]
        return " AND lower(trim(%sdoctor_email))=?" % a, [(session.get("email") or "").strip().lower()]

    def student_scope():
        r = role()
        if r == "admin":
            return "", []
        if r == "dean":
            return " AND college_uid=?", [session.get("college") or "-"]
        if r in ("head", "rapporteur"):
            return " AND dept_uid=?", [session.get("dept") or "-"]
        return " AND 0", []

    def my_course_uids(c):
        """None = كل المواد (رئيس الجامعة)، وإلا قائمة المواد المسموحة."""
        if role() == "admin":
            return None
        w, a = course_scope()
        return [r[0] for r in c.execute("SELECT uid FROM courses WHERE deleted=0" + w, a)]

    def can_course(c, uid):
        m = my_course_uids(c)
        return m is None or uid in m

    def can_student(c, uid):
        w, a = student_scope()
        return bool(c.execute("SELECT 1 FROM students WHERE uid=?" + w, [uid] + a).fetchone())

    def dept_in_scope(c, dept_uid):
        d = c.execute("SELECT * FROM departments WHERE uid=? AND deleted=0", (dept_uid,)).fetchone()
        if not d:
            return None
        r = role()
        if r == "admin" or (r == "dean" and d["college_uid"] == session.get("college")) or (r in ("head", "rapporteur") and d["uid"] == session.get("dept")):
            return d
        return None

    def station_required(f):
        @wraps(f)
        def w(*a, **k):
            ok = request.headers.get("X-Station-Key") == CONF["station_key"]
            if MODE != "cloud" and request.remote_addr in ("127.0.0.1", "::1"):
                ok = True
            if not ok:
                return err("غير مصرّح لهذه المحطة", 403)
            return f(*a, **k)
        return w

    def sync_required(f):
        @wraps(f)
        def w(*a, **k):
            if not CONF.get("sync_key") or request.headers.get("X-Sync-Key") != CONF["sync_key"]:
                return err("مفتاح المزامنة غير صحيح", 403)
            return f(*a, **k)
        return w

    @app.after_request
    def cors(resp):
        if request.path.startswith("/api/student") or request.path in ("/api/time", "/api/health"):
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
            resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
            resp.headers["Access-Control-Allow-Private-Network"] = "true"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if request.path.startswith("/api/admin"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.before_request
    def csrf_guard():
        """حماية CSRF: الطلبات المغيِّرة للحالة في /api/admin يجب أن تأتي من نفس الموقع (Origin/Referer) + كوكي SameSite."""
        if request.method in ("POST", "PUT", "DELETE", "PATCH") and request.path.startswith("/api/admin"):
            o = request.headers.get("Origin") or request.headers.get("Referer") or ""
            if o:
                from urllib.parse import urlparse
                if urlparse(o).netloc != request.host:
                    return err("طلب من موقع غير موثوق", 403)

    @app.after_request
    def audit_hook(resp):
        """كل عملية إدارية ناجحة (إضافة/تعديل/حذف) تُسجَّل في سجل التدقيق تلقائياً: المستخدم، الدور، الوقت، العملية."""
        try:
            if (request.method in ("POST", "PUT", "DELETE") and request.path.startswith("/api/admin/") and resp.status_code < 400
                    and session.get("admin") and not request.path.startswith("/api/admin/x/") and request.path not in ("/api/admin/login", "/api/admin/logout")):
                c = D.connect()
                try:
                    X.audit(c, session.get("admin"), session.get("role", "admin"), request.method + " " + request.path, "", "ip=" + (request.remote_addr or ""))
                finally:
                    c.close()
        except Exception:
            pass
        return resp

    @app.route("/api/<path:_p>", methods=["OPTIONS"])
    def preflight(_p):
        return ("", 204)

    # ── الصفحات الثابتة ──
    @app.route("/")
    def home():
        return redirect("/s/")

    @app.route("/s/")
    @app.route("/s/<path:p>")
    def student_static(p="index.html"):
        resp = send_from_directory(os.path.join(config.STATIC_DIR, "student"), p or "index.html")
        if p in ("sw.js", "index.html", ""):
            resp.headers["Cache-Control"] = "no-cache"
        if p == "sw.js":
            resp.headers["Service-Worker-Allowed"] = "/s/"
        return resp

    @app.route("/admin/")
    @app.route("/admin/<path:p>")
    def admin_static(p="index.html"):
        resp = send_from_directory(os.path.join(config.STATIC_DIR, "admin"), p or "index.html")
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.route("/admin")
    def admin_redir():
        return redirect("/admin/")

    @app.route("/api/qr.svg")
    def qr_svg():
        data = request.args.get("d", "")
        if not data or len(data) > 400:
            abort(400)
        return Response(QR.to_svg(QR.encode(data, request.args.get("l", "M"))), mimetype="image/svg+xml")

    @app.route("/api/time")
    def api_time():
        return J(t=D.now())

    @app.route("/api/health")
    def health():
        return J(ok=True, mode=MODE)

    # ═════════ واجهة الطالب ═════════
    _roster_cache = {}

    @app.route("/api/student/roster")
    def roster():
        """قائمة الأسماء: ETag + gzip حتى لا يثقل آلاف الطلاب الخادم."""
        import gzip
        c = db()
        try:
            mx, cnt = c.execute("SELECT COALESCE(MAX(rev),0), COUNT(*) FROM students").fetchone()
            ox = c.execute("SELECT (SELECT COALESCE(MAX(rev),0) FROM colleges)*1000003+(SELECT COALESCE(MAX(rev),0) FROM departments)").fetchone()[0]
            S = D.get_settings(c)
            import zlib
            etag = 'W/"%s-%s-%x"' % (mx, cnt, zlib.crc32(("%s|%s|%s" % (S.get("org_name", "") + S.get("attendance_mailbox", "") + S.get("student_login_mode", "") + S.get("relay_url", ""), S.get("scan_grace", ""), core.late_hours(S))).encode("utf-8")))
            etag = etag[:-1] + "-%x\"" % ox
            if request.headers.get("If-None-Match") == etag:
                r = Response(status=304)
                r.headers["ETag"] = etag
                return r
            ent = _roster_cache.get(etag)
            if ent is None:
                rows = c.execute("SELECT uid,name,grp,device_id,dept_uid,stage FROM students WHERE deleted=0 ORDER BY dept_uid,stage,grp,name_norm").fetchall()
                org = {"colleges": [{"u": r["uid"], "n": r["name"]} for r in c.execute("SELECT uid,name FROM colleges WHERE deleted=0 ORDER BY name")],
                       "depts": [{"u": r["uid"], "c": r["college_uid"], "n": r["name"], "s": r["stages"]} for r in c.execute("SELECT uid,college_uid,name,stages FROM departments WHERE deleted=0 ORDER BY name")]}
                raw = json.dumps({"org_tree": org, "students": [dict({"u": r["uid"], "n": r["name"], "g": r["grp"], "b": 1 if r["device_id"] else 0}, **({"d": r["dept_uid"], "s": r["stage"]} if r["dept_uid"] else {})) for r in (rows if S.get("student_login_mode", "email") == "pick" else [])],
                                  "org": S.get("org_name", ""), "mailbox": S.get("attendance_mailbox", ""), "relay": S.get("relay_url", ""), "email_domain": S.get("email_domain", ""), "login_mode": S.get("student_login_mode", "email"), "grace": float(S.get("scan_grace", 10)), "late_hours": core.late_hours(S)}, ensure_ascii=False).encode("utf-8")
                ent = (raw, gzip.compress(raw, 5))
                _roster_cache.clear()
                _roster_cache[etag] = ent
            body = ent[1] if "gzip" in request.headers.get("Accept-Encoding", "") else ent[0]
            r = Response(body, mimetype="application/json")
            if body is ent[1]:
                r.headers["Content-Encoding"] = "gzip"
            r.headers["ETag"] = etag
            r.headers["Vary"] = "Accept-Encoding"
            r.headers["Cache-Control"] = "no-cache"
            return r
        finally:
            c.close()

    @app.route("/api/student/me")
    def me():
        dev = request.args.get("device", "")
        c = db()
        try:
            r = c.execute("SELECT * FROM students WHERE device_id=? AND deleted=0", (dev,)).fetchone() if dev else None
            return J(student=(X.student_card(c, r) if r else None), t=D.now())
        finally:
            c.close()

    @app.route("/api/student/bind", methods=["POST"])
    def bind():
        b = request.get_json(force=True, silent=True) or {}
        c = db()
        try:
            c.execute("BEGIN IMMEDIATE")
            st = c.execute("SELECT * FROM students WHERE uid=? AND deleted=0", (b.get("student", ""),)).fetchone()
            if not st or not b.get("device_id"):
                c.execute("ROLLBACK")
                return err("الطالب غير موجود")
            ok, why = core.claim_device(c, st, b["device_id"])
            if ok:
                X.enroll_key(c, st, b["device_id"], b.get("pub"))
            c.execute("COMMIT")
            return J(ok=ok, reason=why, message=core.REASONS.get(why, ""), t=D.now(), can_request_change=(why == "student_bound_elsewhere"))
        finally:
            c.close()

    @app.route("/api/student/submit", methods=["POST"])
    def submit():
        b = request.get_json(force=True, silent=True) or {}
        dev, items = str(b.get("device_id", ""))[:80], b.get("items") or []
        if not dev or not isinstance(items, list) or len(items) > 50:
            return err("طلب غير صالح")
        c = db()
        out = []
        try:
            for it in items:
                c.execute("BEGIN IMMEDIATE")
                try:
                    r = core.record_scan(c, dev, it)
                    c.execute("COMMIT")
                except Exception:
                    c.execute("ROLLBACK")
                    raise
                r["message"] = core.REASONS.get(r.get("reason", ""), "")
                r["id"] = it.get("id")
                out.append(r)
            return J(results=out, t=D.now())
        finally:
            c.close()

    # ═════════ محطة الدكتور (برنامج سطح المكتب) ═════════
    @app.route("/api/station/info")
    @station_required
    def st_info():
        c = db()
        try:
            S = D.get_settings(c)
            de = (CONF.get("doctor_email") or "").strip().lower()
            courses = [dict(r) for r in c.execute("""SELECT c.uid,c.name,c.doctor_email,c.duration_sec,c.stage,c.kind,COALESCE(d.name,'') AS dept_name,COALESCE(k.name,'') AS college_name
                 FROM courses c LEFT JOIN departments d ON d.uid=c.dept_uid LEFT JOIN colleges k ON k.uid=c.college_uid WHERE c.deleted=0 """ + ("AND lower(trim(c.doctor_email))=? " if de else "") + "ORDER BY c.name", [de] if de else [])]
            for r in courses:
                r["label"] = r["name"] + ((" — %s / م%d / %s" % (r["dept_name"], r["stage"], "عملي" if r["kind"] == "practical" else "نظري")) if r["dept_name"] else "")
            for r in courses:
                r["duration_sec"] = int(r["duration_sec"] or S.get("default_duration", 900))
            act = c.execute("""SELECT l.uid, l.course_uid, l.end_ts, l.start_ts, c.name FROM lectures l JOIN courses c ON c.uid=l.course_uid
                               WHERE l.status='active' AND l.end_ts>? ORDER BY l.start_ts DESC LIMIT 1""", (D.now(),)).fetchone()
            return J(org=S.get("org_name", ""), interval=int(S.get("qr_interval", 3)), courses=courses,
                     cloud_url=CONF.get("cloud_url", ""), last_sync=int(D.setting(c, "_last_sync", "0")),
                     station=CONF.get("station_name", ""), doctor_email=CONF.get("doctor_email", ""),
                     active=({"uid": act["uid"], "course_uid": act["course_uid"], "course": act["name"]} if act else None))
        finally:
            c.close()

    @app.route("/api/station/lecture/start", methods=["POST"])
    @station_required
    def st_start():
        b = request.get_json(force=True, silent=True) or {}
        c = db()
        try:
            course = c.execute("SELECT * FROM courses WHERE uid=? AND deleted=0", (b.get("course_uid", ""),)).fetchone()
            if not course:
                return err("اختر المادة أولاً")
            S = D.get_settings(c)
            dur = int(course["duration_sec"] or S.get("default_duration", 900))
            try:
                if int(b.get("duration_sec") or 0) > 0:
                    dur = min(int(b["duration_sec"]), 6 * 3600)
            except Exception:
                pass
            n = D.now()
            import secrets as _s
            code = "".join(_s.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
            lec = dict(uid=D.new_uid(), code=code, course_uid=course["uid"], secret=_s.token_hex(16), start_ts=n, end_ts=n + dur,
                       interval_sec=max(1, int(S.get("qr_interval", 3))), status="active", station=CONF.get("station_name", ""),
                       grp=" ".join(str(b.get("grp") or "").split())[:20])
            c.execute("INSERT INTO lectures(uid,code,course_uid,secret,start_ts,end_ts,interval_sec,status,station,grp,updated_at,rev,dirty) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1)",
                      (lec["uid"], code, lec["course_uid"], lec["secret"], n, lec["end_ts"], lec["interval_sec"], "active", lec["station"], lec["grp"], n, D.next_rev(c)))
            return J(lecture=lec, course=course["name"])
        finally:
            c.close()

    @app.route("/api/station/lecture/<uid>/end", methods=["POST"])
    @station_required
    def st_end(uid):
        c = db()
        try:
            n = D.now()
            c.execute("UPDATE lectures SET status='ended', end_ts=MIN(end_ts,?), updated_at=?, rev=?, dirty=1 WHERE uid=?", (n, n, D.next_rev(c), uid))
            return J(ok=True)
        finally:
            c.close()

    @app.route("/api/station/lecture/<uid>/status")
    @station_required
    def st_status(uid):
        c = db()
        try:
            n = c.execute("SELECT COUNT(*) FROM attendance WHERE lecture_uid=? AND status='ok'", (uid,)).fetchone()[0]
            last = [r[0] for r in c.execute("SELECT s.name FROM attendance a JOIN students s ON s.uid=a.student_uid WHERE a.lecture_uid=? AND a.status='ok' ORDER BY a.created_at DESC LIMIT 8", (uid,))]
            return J(count=n, last=last, t=D.now())
        finally:
            c.close()

    @app.route("/api/station/bound")
    @station_required
    def st_bound():
        q = D.norm(request.args.get("q", ""))
        c = db()
        try:
            rows = c.execute("SELECT uid,name,grp FROM students WHERE deleted=0 AND device_id IS NOT NULL AND name_norm LIKE ? ORDER BY name_norm LIMIT 200", ("%" + q + "%",)).fetchall()
            return J(students=[dict(r) for r in rows])
        finally:
            c.close()

    def unbind(c, uid):
        n = D.now()
        c.execute("UPDATE students SET device_id=NULL, bound_at=NULL, bind_epoch=bind_epoch+1, updated_at=?, rev=?, dirty=1 WHERE uid=?", (n, D.next_rev(c), uid))
        X.clear_key(c, uid)
        X.audit(c, session.get("admin") or "station", session.get("role", "station"), "device.unbind", uid)

    @app.route("/api/station/unbind", methods=["POST"])
    @station_required
    def st_unbind():
        b = request.get_json(force=True, silent=True) or {}
        c = db()
        try:
            unbind(c, b.get("student_uid", ""))
            return J(ok=True)
        finally:
            c.close()

    @app.route("/api/station/pull-mail", methods=["POST"])
    @station_required
    def st_pull_mail():
        """زر «اجلب الحضور من الإيميل الآن»."""
        import mailsync
        try:
            ok_n, bad_n, msgs = mailsync.receive_student_mails(CONF)
        except Exception as e:
            return err("تعذّر الاتصال بالبريد: %s" % str(e)[:120])
        return J(ok=True, accepted=ok_n, rejected=bad_n, messages=msgs)

    @app.route("/api/station/export", methods=["POST"])
    @station_required
    def st_export():
        b = request.get_json(force=True, silent=True) or {}
        try:
            core.sync_once(CONF)  # نجلب أحدث حضور من السحابة إن وُجد إنترنت
        except Exception:
            pass
        try:   # حضور الطلاب المرسَل بالإيميل ينتظر في الجيميل حتى يُفتح البرنامج: نجلبه قبل التصدير
            import mailsync
            _c0 = D.connect(); _S0 = D.get_settings(_c0); _c0.close()
            if _S0.get("imap_host") and _S0.get("attendance_mailbox"):
                mailsync.receive_student_mails(CONF)
        except Exception:
            pass
        c = db()
        try:
            r = core.export_and_mail(c, CONF, b.get("course_uid", ""))
        except ValueError as e:
            return err(str(e))
        finally:
            c.close()
        mail = None
        if r["mail_id"]:
            try:
                res = core.flush_outbox(CONF)
                mail = "sent" if res["sent"] else "queued"
            except Exception:
                mail = "queued"
        r["mail"] = mail
        return J(**r)

    @app.route("/api/station/sync", methods=["POST"])
    @station_required
    def st_sync():
        try:
            return J(ok=True, **core.sync_once(CONF))
        except Exception as e:
            return J(ok=False, error=str(e)[:200])


    # ── واجهة برنامج الدكتور (تُفتح داخل نافذة البرنامج على نفس الجهاز فقط) ──
    def loopback_only(f):
        @wraps(f)
        def w(*a, **k):
            if MODE == "cloud" or request.remote_addr not in ("127.0.0.1", "::1"):
                abort(404)
            return f(*a, **k)
        return w

    @app.route("/station/")
    @app.route("/station/<path:p>")
    @loopback_only
    def station_static(p="index.html"):
        resp = send_from_directory(os.path.join(config.STATIC_DIR, "station"), p or "index.html")
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    def student_urls():
        import certs
        ip = certs.lan_ip()
        _c = D.connect()
        try:
            pub = (D.setting(_c, "public_url", "") or "").strip()
        finally:
            _c.close()
        cloud = (CONF.get("cloud_url") or pub or "").rstrip("/")
        return {"ip": ip, "lan": "https://%s:5443" % ip, "lan_http": "http://%s:5000" % ip, "cloud": cloud}

    @app.route("/api/station/net")
    @station_required
    def st_net():
        u = student_urls()
        c = db()
        try:
            return J(**u, last_sync=int(D.setting(c, "_last_sync", "0")), has_sync=bool(CONF.get("cloud_url") and CONF.get("sync_key")),
                     station=CONF.get("station_name", ""), pending_mail=c.execute("SELECT COUNT(*) FROM outbox WHERE sent_at IS NULL").fetchone()[0],
                     unsynced=c.execute("SELECT (SELECT COUNT(*) FROM attendance WHERE dirty=1)+(SELECT COUNT(*) FROM lectures WHERE dirty=1)").fetchone()[0])
        finally:
            c.close()

    @app.route("/api/station/config", methods=["GET", "POST"])
    @station_required
    def st_config():
        if request.method == "POST":
            b = request.get_json(force=True, silent=True) or {}
            for k in ("cloud_url", "sync_key", "station_name", "doctor_email"):
                if k in b and isinstance(b[k], str):
                    v = b[k].strip()
                    if k == "sync_key" and v == "********":
                        continue
                    CONF[k] = v.rstrip("/") if k == "cloud_url" else v
            config.save_conf({k: CONF.get(k, "") for k in ("station_key", "session_secret", "sync_key", "cloud_url", "station_name", "doctor_email")})
        return J(cloud_url=CONF.get("cloud_url", ""), has_sync_key=bool(CONF.get("sync_key")), station_name=CONF.get("station_name", ""), doctor_email=CONF.get("doctor_email", ""))

    @app.route("/api/station/lecture/<uid>/qr")
    @station_required
    def st_qr(uid):
        """نص الباركود الحالي (يتغير كل interval ثانية). mode=lan|public."""
        c = db()
        try:
            lec = c.execute("SELECT * FROM lectures WHERE uid=?", (uid,)).fetchone()
            if not lec:
                return err("المحاضرة غير موجودة", 404)
            n = D.now()
            u = student_urls()
            mode = request.args.get("mode", "lan")
            base = u["cloud"] if mode == "public" and u["cloud"] else u["lan"]
            custom = request.args.get("base", "").strip().rstrip("/")
            if mode != "public" and custom.startswith(("http://", "https://")) and len(custom) < 120:
                base = custom
            frag = core.make_fragment(lec, n)
            active = lec["status"] == "active" and n <= lec["end_ts"]
            cnt = c.execute("SELECT COUNT(*) FROM attendance WHERE lecture_uid=? AND status='ok'", (uid,)).fetchone()[0]
            last = [r[0] for r in c.execute("SELECT s.name FROM attendance a JOIN students s ON s.uid=a.student_uid WHERE a.lecture_uid=? AND a.status='ok' ORDER BY a.created_at DESC LIMIT 12", (uid,))]
            qs = ""
            if mode == "public" and u["cloud"]:   # الصفحة العامة تأخذ بريد الاستلام ورابط الإرسال من الباركود نفسه
                from urllib.parse import urlencode
                _S = D.get_settings(c)
                prm = {k: v for k, v in (("m", _S.get("attendance_mailbox", "")), ("r", _S.get("relay_url", ""))) if v}
                qs = ("?" + urlencode(prm)) if prm else ""
            return J(url="%s/s/%s#%s" % (base, qs, frag), active=active, remaining=max(0, int(lec["end_ts"] - n)), code=lec["code"],
                     count=cnt, last=last, interval=lec["interval_sec"], t=n)
        finally:
            c.close()

    @app.route("/api/station/open-exports", methods=["POST"])
    @station_required
    def st_open_exports():
        try:
            if os.name == "nt":
                os.startfile(config.EXPORT_DIR)  # type: ignore[attr-defined]
        except Exception:
            pass
        return J(path=config.EXPORT_DIR)

    @app.route("/api/station/open-admin", methods=["POST"])
    @station_required
    def st_open_admin():
        import webbrowser
        webbrowser.open("http://127.0.0.1:5000/admin/")
        return J(ok=True)

    # ═════════ المزامنة بين الأجهزة والسحابة ═════════
    @app.route("/api/sync/exchange", methods=["POST"])
    @sync_required
    def sync_exchange():
        b = request.get_json(force=True, silent=True) or {}
        c = db()
        try:
            c.execute("BEGIN IMMEDIATE")
            upto = D.cur_rev(c)
            pull = core.collect_since(c, int(b.get("since", 0)), upto)
            core.merge_rows(c, b.get("push") or {}, clean=False)
            core.verify_pending(c)
            S = D.get_settings(c)
            c.execute("COMMIT")
            return J(pull=pull, rev=upto, settings={k: S[k] for k in D.SYNC_SETTINGS if k in S}, t=D.now())
        except Exception:
            try:
                c.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            c.close()

    @app.route("/api/sync/mail", methods=["POST"])
    @sync_required
    def sync_mail():
        b = request.get_json(force=True, silent=True) or {}
        c = db()
        try:
            S = D.get_settings(c)
            if not (S.get("smtp_user") and S.get("smtp_pass")):
                return err("لم يُضبط بريد الإرسال في السحابة", 400)
            data = base64.b64decode(b["data"]) if b.get("data") else None
            core._smtp_send(S, b.get("to", ""), b.get("cc", ""), b.get("subject", ""), b.get("body", ""), b.get("filename", "attendance.xlsx"), data)
            return J(ok=True)
        except Exception as e:
            return err(str(e)[:200], 500)
        finally:
            c.close()

    # ═════════ لوحة المسؤول ═════════
    @app.route("/api/admin/me")
    def a_me():
        return J(admin=bool(session.get("admin")), user=session.get("admin"), role=session.get("role", "admin"), must_change=bool(session.get("must_change")), mode=MODE,
                 role_ar=ROLE_AR.get(session.get("role", "admin"), ""), perms=sorted(eff_perms()), delegate=bool(session.get("delegate")) or role() in ("admin", "dean"),
                 college=session.get("college", ""), dept=session.get("dept", ""),
                 cloud_url=CONF.get("cloud_url", ""))

    @app.route("/api/admin/login", methods=["POST"])
    def a_login():
        b = request.get_json(force=True, silent=True) or {}
        c = db()
        try:
            _tk = "login:%s:%s" % ((request.remote_addr or "?"), (b.get("username", "") or "").strip().lower())
            if X.throttle_over(c, _tk, 6, 900):
                X.audit(c, b.get("username", ""), "", "login.locked", "", "ip=" + (request.remote_addr or ""))
                return err("تم إيقاف الدخول مؤقتاً بسبب محاولات خاطئة كثيرة. حاول بعد 15 دقيقة", 429)
            r = c.execute("SELECT * FROM admins WHERE lower(username)=lower(?)", (b.get("username", "").strip(),)).fetchone()
            if not r or not check_password_hash(r["pw_hash"], b.get("password", "")):
                time.sleep(0.6)
                X.throttle_hit(c, _tk)
                X.audit(c, b.get("username", ""), "", "login.fail", "", "ip=" + (request.remote_addr or ""))
                return err("اسم المستخدم أو كلمة المرور خطأ", 401)
            X.throttle_clear(c, _tk)
            X.audit(c, r["username"], (r["role"] if "role" in r.keys() and r["role"] else "admin"), "login.ok", "", "ip=" + (request.remote_addr or ""))
            session.permanent = False
            session["full_name"] = (r["full_name"] if "full_name" in r.keys() else "") or ""
            session["admin"] = r["username"]
            session["uid"] = r["id"]
            session["role"] = (r["role"] if "role" in r.keys() and r["role"] else "admin")
            session["email"] = (r["email"] if "email" in r.keys() else "") or ""
            session["college"] = r["college_uid"] or ""
            session["dept"] = r["dept_uid"] or ""
            session["perms"] = [x for x in (r["perms"] or "").split(",") if x in PERMS]
            session["delegate"] = bool(r["can_delegate"])
            session["must_change"] = bool(r["must_change"])
            return J(ok=True, must_change=bool(r["must_change"]))
        finally:
            c.close()

    @app.route("/api/admin/logout", methods=["POST"])
    def a_logout():
        session.clear()
        return J(ok=True)

    @app.route("/api/admin/password", methods=["POST"])
    @staff_required
    def a_pw():
        b = request.get_json(force=True, silent=True) or {}
        c = db()
        try:
            r = c.execute("SELECT * FROM admins WHERE username=?", (session["admin"],)).fetchone()
            if not check_password_hash(r["pw_hash"], b.get("old", "")):
                return err("كلمة المرور الحالية خطأ")
            if len(b.get("new", "")) < 6:
                return err("كلمة المرور الجديدة قصيرة (6 أحرف على الأقل)")
            c.execute("UPDATE admins SET pw_hash=?, must_change=0 WHERE id=?", (generate_password_hash(b["new"]), r["id"]))
            session["must_change"] = False
            return J(ok=True)
        finally:
            c.close()

    @app.route("/api/admin/summary")
    @staff_required
    def a_summary():
        c = db()
        try:
            mine = my_course_uids(c)
            if mine is not None:
                ph = ",".join("?" * len(mine)) or "''"
                qq = lambda sql: c.execute(sql % ph, mine).fetchone()[0]
                if role() == "doctor":
                    nst = 0
                    for cu in c.execute("SELECT * FROM courses WHERE uid IN (%s)" % ph, mine).fetchall():
                        w, a = core.cohort_filter(cu)
                        nst += c.execute("SELECT COUNT(*) FROM students WHERE deleted=0" + w, a).fetchone()[0]
                    bound = 0
                else:
                    w, a = student_scope()
                    nst = c.execute("SELECT COUNT(*) FROM students WHERE deleted=0" + w, a).fetchone()[0]
                    bound = c.execute("SELECT COUNT(*) FROM students WHERE deleted=0 AND device_id IS NOT NULL" + w, a).fetchone()[0]
                return J(courses=len(mine), students=nst, bound=bound,
                         lectures=qq("SELECT COUNT(*) FROM lectures WHERE course_uid IN (%s) AND status!='deleted'"),
                         attendance=qq("SELECT COUNT(*) FROM attendance a JOIN lectures l ON l.uid=a.lecture_uid WHERE a.status='ok' AND l.course_uid IN (%s)"),
                         pending=0, dirty=0, outbox=0, last_sync=0,
                         colleges=c.execute("SELECT COUNT(*) FROM colleges WHERE deleted=0").fetchone()[0], departments=c.execute("SELECT COUNT(*) FROM departments WHERE deleted=0").fetchone()[0])
            q = lambda sql: c.execute(sql).fetchone()[0]
            return J(courses=q("SELECT COUNT(*) FROM courses WHERE deleted=0"), students=q("SELECT COUNT(*) FROM students WHERE deleted=0"),
                     bound=q("SELECT COUNT(*) FROM students WHERE deleted=0 AND device_id IS NOT NULL"),
                     lectures=q("SELECT COUNT(*) FROM lectures WHERE status!='deleted'"), attendance=q("SELECT COUNT(*) FROM attendance WHERE status='ok'"),
                     pending=q("SELECT COUNT(*) FROM attendance WHERE status='pending'"),
                     dirty=q("SELECT (SELECT COUNT(*) FROM attendance WHERE dirty=1)+(SELECT COUNT(*) FROM lectures WHERE dirty=1)"),
                     outbox=q("SELECT COUNT(*) FROM outbox WHERE sent_at IS NULL"), last_sync=int(D.setting(c, "_last_sync", "0")),
                     colleges=q("SELECT COUNT(*) FROM colleges WHERE deleted=0"), departments=q("SELECT COUNT(*) FROM departments WHERE deleted=0"))
        finally:
            c.close()

    # الهيكل: الكليات والأقسام والمراحل
    @app.route("/api/admin/org")
    @staff_required
    def a_org():
        c = db()
        try:
            cols = [dict(r) for r in c.execute("SELECT uid,name FROM colleges WHERE deleted=0 ORDER BY name")]
            deps = [dict(r) for r in c.execute("SELECT uid,college_uid,name,stages FROM departments WHERE deleted=0 ORDER BY name")]
            r = role()
            if r == "dean":
                cols = [x for x in cols if x["uid"] == session.get("college")]
                deps = [x for x in deps if x["college_uid"] == session.get("college")]
            elif r in ("head", "rapporteur"):
                deps = [x for x in deps if x["uid"] == session.get("dept")]
                cols = [x for x in cols if x["uid"] in {d["college_uid"] for d in deps}]
            elif r == "doctor":
                w, ar = course_scope()
                du = {x[0] for x in c.execute("SELECT dept_uid FROM courses WHERE deleted=0" + w, ar)}
                deps = [x for x in deps if x["uid"] in du]
                cols = [x for x in cols if x["uid"] in {d["college_uid"] for d in deps}]
            return J(colleges=cols, departments=deps)
        finally:
            c.close()

    @app.route("/api/admin/colleges", methods=["POST"])
    @admin_required
    def a_college_add():
        b = request.get_json(force=True, silent=True) or {}
        name = " ".join((b.get("name") or "").split())
        if not name:
            return err("اكتب اسم الكلية")
        c = db()
        try:
            if c.execute("SELECT 1 FROM colleges WHERE deleted=0 AND lower(name)=lower(?)", (name,)).fetchone():
                return err("هذه الكلية موجودة")
            uid = D.new_uid()
            c.execute("INSERT INTO colleges(uid,name,updated_at,rev,dirty) VALUES(?,?,?,?,1)", (uid, name, D.now(), D.next_rev(c)))
            return J(ok=True, uid=uid)
        finally:
            c.close()

    @app.route("/api/admin/colleges/<uid>", methods=["PUT", "DELETE"])
    @admin_required
    def a_college(uid):
        c = db()
        try:
            n = D.now()
            if request.method == "DELETE":
                if c.execute("SELECT 1 FROM departments WHERE college_uid=? AND deleted=0", (uid,)).fetchone():
                    return err("احذف أقسام الكلية أولاً")
                c.execute("UPDATE colleges SET deleted=1,updated_at=?,rev=?,dirty=1 WHERE uid=?", (n, D.next_rev(c), uid))
            else:
                name = " ".join(((request.get_json(force=True, silent=True) or {}).get("name") or "").split())
                if not name:
                    return err("اكتب اسم الكلية")
                c.execute("UPDATE colleges SET name=?,updated_at=?,rev=?,dirty=1 WHERE uid=?", (name, n, D.next_rev(c), uid))
            return J(ok=True)
        finally:
            c.close()

    @app.route("/api/admin/departments", methods=["POST"])
    @staff_required
    def a_dept_add():
        if role() not in ("admin", "dean"):
            return err("إضافة الأقسام لرئيس الجامعة أو عميد الكلية", 403)
        b = request.get_json(force=True, silent=True) or {}
        name = " ".join((b.get("name") or "").split())
        col = session.get("college") if role() == "dean" else (b.get("college_uid") or "")
        try:
            stages = int(b.get("stages") or 4)
        except Exception:
            stages = 4
        if not name:
            return err("اكتب اسم القسم")
        if not 1 <= stages <= 8:
            return err("عدد المراحل من 1 إلى 8")
        c = db()
        try:
            if not c.execute("SELECT 1 FROM colleges WHERE uid=? AND deleted=0", (col,)).fetchone():
                return err("اختر الكلية")
            if c.execute("SELECT 1 FROM departments WHERE deleted=0 AND college_uid=? AND lower(name)=lower(?)", (col, name)).fetchone():
                return err("هذا القسم موجود في الكلية")
            uid = D.new_uid()
            c.execute("INSERT INTO departments(uid,college_uid,name,stages,updated_at,rev,dirty) VALUES(?,?,?,?,?,?,1)", (uid, col, name, stages, D.now(), D.next_rev(c)))
            return J(ok=True, uid=uid)
        finally:
            c.close()

    @app.route("/api/admin/departments/<uid>", methods=["PUT", "DELETE"])
    @staff_required
    def a_dept(uid):
        if role() not in ("admin", "dean"):
            return err("غير مسموح", 403)
        c = db()
        try:
            d = dept_in_scope(c, uid)
            if not d:
                return err("غير موجود", 404)
            n = D.now()
            if request.method == "DELETE":
                if c.execute("SELECT 1 FROM courses WHERE dept_uid=? AND deleted=0", (uid,)).fetchone() or c.execute("SELECT 1 FROM students WHERE dept_uid=? AND deleted=0", (uid,)).fetchone():
                    return err("القسم فيه مواد أو طلاب. احذفها أولاً")
                c.execute("UPDATE departments SET deleted=1,updated_at=?,rev=?,dirty=1 WHERE uid=?", (n, D.next_rev(c), uid))
            else:
                b = request.get_json(force=True, silent=True) or {}
                name = " ".join((b.get("name") or d["name"]).split())
                try:
                    stages = int(b.get("stages") or d["stages"])
                except Exception:
                    stages = d["stages"]
                if not name or not 1 <= stages <= 8:
                    return err("بيانات غير صحيحة")
                c.execute("UPDATE departments SET name=?,stages=?,updated_at=?,rev=?,dirty=1 WHERE uid=?", (name, stages, n, D.next_rev(c), uid))
            return J(ok=True)
        finally:
            c.close()

    # المواد
    def course_fields(c, b, existing=None):
        """يتحقق من حقول المادة (القسم/المرحلة/النوع) ضمن صلاحية المستخدم. يعيد (حقول, خطأ)."""
        name, email = (b.get("name") or "").strip(), (b.get("doctor_email") or "").strip()
        if not name:
            return None, "اكتب اسم المادة"
        if email and "@" not in email:
            return None, "البريد الإلكتروني غير صحيح"
        kind = b.get("kind") or (existing["kind"] if existing else "theory")
        if kind not in ("theory", "practical"):
            return None, "نوع المادة: نظري أو عملي"
        dept = b.get("dept_uid") if "dept_uid" in b else (existing["dept_uid"] if existing else "")
        if role() in ("head", "rapporteur"):
            dept = session.get("dept")
        stage, col = 0, ""
        if dept:
            d = dept_in_scope(c, dept)
            if not d:
                return None, "القسم غير صحيح أو خارج صلاحيتك"
            col = d["college_uid"]
            try:
                stage = int(b.get("stage") if "stage" in b else (existing["stage"] if existing else 1))
            except Exception:
                stage = 0
            if not 1 <= stage <= int(d["stages"] or 4):
                return None, "المرحلة من 1 إلى %d" % int(d["stages"] or 4)
        elif role() != "admin":
            return None, "اختر القسم والمرحلة"
        return dict(name=name, email=email, kind=kind, dept=dept or "", college=col, stage=stage), None

    @app.route("/api/admin/courses", methods=["GET", "POST"])
    @staff_required
    def a_courses():
        c = db()
        try:
            if request.method == "POST":
                if not has("courses"):
                    return err("ليست لديك صلاحية: إدارة المواد", 403)
                f, e = course_fields(c, request.get_json(force=True, silent=True) or {})
                if e:
                    return err(e)
                b = request.get_json(force=True, silent=True) or {}
                uid = D.new_uid()
                c.execute("INSERT INTO courses(uid,name,doctor_email,duration_sec,college_uid,dept_uid,stage,kind,updated_at,rev,dirty) VALUES(?,?,?,?,?,?,?,?,?,?,1)",
                          (uid, f["name"], f["email"], int(b.get("duration_sec") or 0), f["college"], f["dept"], f["stage"], f["kind"], D.now(), D.next_rev(c)))
                return J(ok=True, uid=uid)
            rows = c.execute("""SELECT c.uid,c.name,c.doctor_email,c.duration_sec,c.college_uid,c.dept_uid,c.stage,c.kind,
                 COALESCE(d.name,'') AS dept_name, COALESCE(k.name,'') AS college_name,
                 (SELECT COUNT(*) FROM lectures l WHERE l.course_uid=c.uid AND l.status!='deleted') AS lectures
                 FROM courses c LEFT JOIN departments d ON d.uid=c.dept_uid LEFT JOIN colleges k ON k.uid=c.college_uid WHERE c.deleted=0 ORDER BY k.name,d.name,c.stage,c.name""").fetchall()
            mine = my_course_uids(c)
            return J(courses=[dict(r) for r in rows if mine is None or r["uid"] in mine])
        finally:
            c.close()

    @app.route("/api/admin/courses/<uid>", methods=["PUT", "DELETE"])
    @need("courses")
    def a_course(uid):
        c = db()
        try:
            if not can_course(c, uid):
                return err("خارج صلاحيتك", 403)
            n = D.now()
            if request.method == "DELETE":
                c.execute("UPDATE courses SET deleted=1, updated_at=?, rev=?, dirty=1 WHERE uid=?", (n, D.next_rev(c), uid))
            else:
                ex = c.execute("SELECT * FROM courses WHERE uid=?", (uid,)).fetchone()
                b = request.get_json(force=True, silent=True) or {}
                f, e = course_fields(c, b, ex)
                if e:
                    return err(e)
                c.execute("UPDATE courses SET name=?, doctor_email=?, duration_sec=?, college_uid=?, dept_uid=?, stage=?, kind=?, updated_at=?, rev=?, dirty=1 WHERE uid=?",
                          (f["name"], f["email"], int(b.get("duration_sec") or 0), f["college"], f["dept"], f["stage"], f["kind"], n, D.next_rev(c), uid))
            return J(ok=True)
        finally:
            c.close()

    # الطلاب
    def cohort_args(c, src):
        """القسم والمرحلة لرفع/إضافة الطلاب. يعيد (cohort|None, error). رئيس الجامعة فقط يستطيع ترك القسم فارغاً (قائمة عامة قديمة)."""
        dept = src.get("dept_uid") or ""
        if role() in ("head", "rapporteur"):
            dept = session.get("dept") or ""
        if not dept:
            return (None, None) if role() == "admin" else (None, "اختر القسم والمرحلة")
        d = dept_in_scope(c, dept)
        if not d:
            return None, "القسم غير صحيح أو خارج صلاحيتك"
        try:
            st = int(src.get("stage") or 0)
        except Exception:
            st = 0
        if not 1 <= st <= int(d["stages"] or 4):
            return None, "اختر المرحلة (1 إلى %d)" % int(d["stages"] or 4)
        return (d["college_uid"], d["uid"], st), None

    @app.route("/api/admin/students", methods=["GET", "POST"])
    @need("students")
    def a_students():
        c = db()
        try:
            if request.method == "POST":
                b = request.get_json(force=True, silent=True) or {}
                name, grp = " ".join((b.get("name") or "").split()), (b.get("grp") or "").strip()
                if not name:
                    return err("اكتب اسم الطالب")
                coh, e = cohort_args(c, b)
                if e:
                    return err(e)
                uid = D.student_uid(name, "" if coh else grp, ("%s:%d" % (coh[1], coh[2])) if coh else "")
                if c.execute("SELECT 1 FROM students WHERE uid=? AND deleted=0", (uid,)).fetchone():
                    return err("هذا الطالب موجود مسبقاً")
                add_students(c, [(name, grp, uid)], cohort=coh, kind="practical" if grp else "theory")
                if b.get("email"):
                    em = X.clean_email(b.get("email"), D.setting(c, "email_domain", ""))
                    if not em:
                        return err("البريد الجامعي غير صحيح — " + X.email_hint(D.setting(c, "email_domain", "")))
                    c.execute("UPDATE students SET univ_email=?,updated_at=?,rev=?,dirty=1 WHERE uid=?", (em, D.now(), D.next_rev(c), uid))
                return J(ok=True)
            sw, sa = student_scope()
            q = D.norm(request.args.get("q", ""))
            grp = request.args.get("group", "")
            sql, args = "SELECT s.uid,s.name,s.grp,s.stage,s.dept_uid,COALESCE(d.name,'') AS dept_name,s.device_id IS NOT NULL AS bound, COALESCE(s.univ_email,'') AS univ_email FROM students s LEFT JOIN departments d ON d.uid=s.dept_uid WHERE s.deleted=0", []
            sw2 = sw.replace(" college_uid", " s.college_uid").replace(" dept_uid", " s.dept_uid")
            sql += sw2; args += sa
            if q:
                sql += " AND s.name_norm LIKE ?"
                args.append("%" + q + "%")
            if grp:
                sql += " AND s.grp=?"
                args.append(grp)
            if request.args.get("dept_uid"):
                sql += " AND s.dept_uid=?"
                args.append(request.args["dept_uid"])
            if request.args.get("stage"):
                sql += " AND s.stage=?"
                args.append(int(request.args["stage"]))
            rows = c.execute(sql + " ORDER BY d.name,s.stage,s.grp,s.name_norm LIMIT 1000", args).fetchall()
            groups = [r[0] for r in c.execute("SELECT DISTINCT grp FROM students WHERE deleted=0" + sw + " ORDER BY grp", sa)]
            total = c.execute("SELECT COUNT(*) FROM students WHERE deleted=0" + sw, sa).fetchone()[0]
            return J(students=[dict(r) for r in rows], groups=groups, total=total)
        finally:
            c.close()

    def add_students(c, items, replace=False, cohort=None, kind="theory"):
        """cohort=(college,dept,stage) أو None (قائمة عامة قديمة). النظري: الأسماء فقط. العملي: يحدّث كروب الطالب الموجود."""
        n = D.now()
        added = updated = removed = 0
        c.execute("BEGIN IMMEDIATE")
        try:
            seen = set()
            col, dep, stg = cohort if cohort else ("", "", 0)
            for item in items:
                name, grp, uid = item[0], item[1], item[2]
                seen.add(uid)
                cur = c.execute("SELECT deleted,grp FROM students WHERE uid=?", (uid,)).fetchone()
                if cur is None:
                    c.execute("INSERT INTO students(uid,name,name_norm,grp,college_uid,dept_uid,stage,updated_at,rev,dirty) VALUES(?,?,?,?,?,?,?,?,?,1)",
                              (uid, name, D.norm(name), grp, col, dep, stg, n, D.next_rev(c)))
                    added += 1
                elif cur["deleted"]:
                    c.execute("UPDATE students SET deleted=0,name=?,name_norm=?,grp=?,college_uid=?,dept_uid=?,stage=?,updated_at=?,rev=?,dirty=1 WHERE uid=?",
                              (name, D.norm(name), grp or cur["grp"] or "", col, dep, stg, n, D.next_rev(c), uid))
                    updated += 1
                elif cohort and kind == "practical" and (grp or "") != (cur["grp"] or ""):
                    c.execute("UPDATE students SET grp=?,updated_at=?,rev=?,dirty=1 WHERE uid=?", (grp, n, D.next_rev(c), uid))
                    updated += 1
                elif cohort and kind == "theory" and grp and not (cur["grp"] or ""):
                    c.execute("UPDATE students SET grp=?,updated_at=?,rev=?,dirty=1 WHERE uid=?", (grp, n, D.next_rev(c), uid))
                    updated += 1
            if replace:
                if cohort:
                    old = c.execute("SELECT uid FROM students WHERE deleted=0 AND dept_uid=? AND stage=?", (dep, stg)).fetchall()
                else:
                    old = c.execute("SELECT uid FROM students WHERE deleted=0 AND COALESCE(dept_uid,'')=''").fetchall()
                for r in old:
                    if r["uid"] not in seen:
                        c.execute("UPDATE students SET deleted=1,updated_at=?,rev=?,dirty=1 WHERE uid=?", (n, D.next_rev(c), r["uid"]))
                        removed += 1
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
        return added, updated, removed

    @app.route("/api/admin/students/upload", methods=["POST"])
    @need("students")
    def a_upload():
        f = request.files.get("file")
        if not f:
            return err("اختر ملف Excel")
        c = db()
        try:
            coh, e = cohort_args(c, request.form)
            if e:
                return err(e)
            kind = request.form.get("kind") or "theory"
            if kind not in ("theory", "practical"):
                return err("اختر نوع القائمة: نظري أو عملي")
            from openpyxl import load_workbook
            try:
                wb = load_workbook(io.BytesIO(f.read()), read_only=True, data_only=True)
            except Exception:
                return err("الملف ليس Excel صالحاً (.xlsx)")
            ws = wb.active
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
            if not rows:
                return err("الملف فارغ")
            ni, gi, start, ei = 0, 1, 0, -1
            head = [D.norm(str(x or "")) for x in rows[0]]
            for k, h in enumerate(head):
                if h in ("name", "الاسم", "اسم الطالب", "اسم", "student name", "اسم الطالب الرباعي"):
                    ni, start = k, 1
                if h in ("group", "كروب", "الكروب", "المجموعه", "شعبه", "الشعبه", "grp"):
                    gi, start = k, 1
                if h in ("email", "e-mail", "mail", "البريد", "البريد الجامعي", "الايميل", "الإيميل", "ايميل", "بريد", "university email"):
                    ei, start = k, 1
            items, skipped, occ, dup, nogrp = [], 0, {}, 0, 0
            emails, bad_email, _dom = {}, 0, D.setting(c, "email_domain", "")
            for r in rows[start:]:
                def _cell(v):
                    if isinstance(v, float) and v.is_integer():
                        v = int(v)
                    return str(v).strip() if v is not None else ""
                name = _cell(r[ni]) if len(r) > ni else ""
                grp = _cell(r[gi]) if len(r) > gi else ""
                if not name or name == "None":
                    skipped += 1
                    continue
                name = " ".join(name.split())
                if coh:
                    # القائمة الخاصة بقسم/مرحلة: المعرّف من الاسم فقط، فيحدّث الرفع العملي كروب الطالب نفسه ولا يكرره
                    k = D.norm(name)
                    occ[k] = occ.get(k, 0) + 1
                    uid = D.student_uid(name if occ[k] == 1 else "%s#%d" % (name, occ[k]), "", "%s:%d" % (coh[1], coh[2]))
                    if kind == "practical" and not grp:
                        nogrp += 1
                else:
                    k = (D.norm(name), D.norm(grp))
                    occ[k] = occ.get(k, 0) + 1
                    uid = D.student_uid(name if occ[k] == 1 else "%s#%d" % (name, occ[k]), grp)
                dup += occ[k] > 1
                items.append((name, grp, uid))
                if ei >= 0 and len(r) > ei and r[ei]:
                    em = X.clean_email(_cell(r[ei]), _dom)
                    if em:
                        emails[uid] = em
                    else:
                        bad_email += 1
                elif _dom and re.fullmatch(r"\d{4,15}", name):   # الرقم الجامعي = اسم الطالب ← البريد تلقائياً
                    emails[uid] = "%s@%s" % (name, _dom)
            if not items:
                return err("لم أجد أسماء. العمود الأول = اسم الطالب" + ("، الثاني = الكروب" if kind == "practical" else ""))
            a, u, rm = add_students(c, items, replace=request.form.get("mode") == "replace", cohort=coh, kind=kind)
            _used, em_set = set(), 0
            for _uid, _em in emails.items():
                if _em in _used or c.execute("SELECT 1 FROM students WHERE lower(univ_email)=? AND uid!=? AND deleted=0", (_em, _uid)).fetchone():
                    bad_email += 1
                    continue
                _used.add(_em)
                c.execute("UPDATE students SET univ_email=?,updated_at=?,rev=?,dirty=1 WHERE uid=?", (_em, D.now(), D.next_rev(c), _uid))
                em_set += 1
            return J(ok=True, added=a, restored=u, updated=u, removed=rm, skipped=skipped, total=len(items), duplicates=dup, no_group=nogrp, emails=em_set, bad_emails=bad_email)
        finally:
            c.close()

    @app.route("/api/admin/students/template")
    def a_template():
        from openpyxl import Workbook
        practical = request.args.get("kind") == "practical"
        wb = Workbook()
        ws = wb.active
        ws.sheet_view.rightToLeft = True
        if practical:
            ws.append(["اسم الطالب", "الكروب"])
            ws.append(["محمد علي حسن", "A"])
            ws.append(["محمد أحمد كاظم", "B"])
        else:
            ws.append(["اسم الطالب"])
            ws.append(["محمد علي حسن"])
            ws.append(["محمد أحمد كاظم"])
        ws.column_dimensions["A"].width = 40
        bio = io.BytesIO()
        wb.save(bio)
        bio.seek(0)
        return send_file(bio, as_attachment=True, download_name="students_template.xlsx")

    @app.route("/api/admin/students/<uid>", methods=["PUT", "DELETE"])
    @need("students")
    def a_student(uid):
        c = db()
        try:
            if not can_student(c, uid):
                return err("خارج صلاحيتك", 403)
            n = D.now()
            if request.method == "DELETE":
                c.execute("UPDATE students SET deleted=1, updated_at=?, rev=?, dirty=1 WHERE uid=?", (n, D.next_rev(c), uid))
            else:
                b = request.get_json(force=True, silent=True) or {}
                name = " ".join((b.get("name") or "").split())
                if not name:
                    return err("اكتب الاسم")
                c.execute("UPDATE students SET name=?, name_norm=?, grp=?, updated_at=?, rev=?, dirty=1 WHERE uid=?",
                          (name, D.norm(name), (b.get("grp") or "").strip(), n, D.next_rev(c), uid))
                if "email" in b:
                    em = X.clean_email(b.get("email"), D.setting(c, "email_domain", "")) if (b.get("email") or "").strip() else ""
                    if em is None:
                        return err("البريد الجامعي غير صحيح — " + X.email_hint(D.setting(c, "email_domain", "")))
                    dup = c.execute("SELECT 1 FROM students WHERE lower(univ_email)=? AND uid!=? AND deleted=0", (em, uid)).fetchone() if em else None
                    if dup:
                        return err("هذا البريد مستخدم لطالب آخر")
                    c.execute("UPDATE students SET univ_email=?,updated_at=?,rev=?,dirty=1 WHERE uid=?", (em, D.now(), D.next_rev(c), uid))
            return J(ok=True)
        finally:
            c.close()

    @app.route("/api/admin/students/<uid>/unbind", methods=["POST"])
    @need("unbind")
    def a_unbind(uid):
        c = db()
        try:
            if not can_student(c, uid):
                return err("خارج صلاحيتك", 403)
            unbind(c, uid)
            return J(ok=True)
        finally:
            c.close()

    # المحاضرات والحضور
    @app.route("/api/admin/lectures")
    @need("lectures")
    def a_lectures():
        c = db()
        try:
            sql = """SELECT l.uid,l.code,l.start_ts,l.end_ts,l.status,l.station,c.name AS course,c.uid AS course_uid,
                 (SELECT COUNT(*) FROM attendance a WHERE a.lecture_uid=l.uid AND a.status='ok') AS present,
                 (SELECT COUNT(*) FROM attendance a WHERE a.lecture_uid=l.uid AND a.status='rejected') AS rejected
                 FROM lectures l LEFT JOIN courses c ON c.uid=l.course_uid"""
            args = []
            sql += " WHERE l.status!='deleted'"
            if request.args.get("course"):
                sql += " AND l.course_uid=?"
                args.append(request.args["course"])
            rows = c.execute(sql + " ORDER BY l.start_ts DESC LIMIT 600", args).fetchall()
            mine = my_course_uids(c)
            return J(lectures=[dict(r) for r in rows if mine is None or r["course_uid"] in mine])
        finally:
            c.close()

    @app.route("/api/admin/lectures/<uid>")
    @need("lectures")
    def a_lecture(uid):
        c = db()
        try:
            lec = c.execute("SELECT l.*,c.name AS course FROM lectures l LEFT JOIN courses c ON c.uid=l.course_uid WHERE l.uid=?", (uid,)).fetchone()
            if not lec or not can_course(c, lec["course_uid"]):
                return err("غير موجودة", 404)
            _co = c.execute("SELECT * FROM courses WHERE uid=?", (lec["course_uid"],)).fetchone()
            _w, _a = core.cohort_filter(_co)
            rows = c.execute("""SELECT s.uid,s.name,s.grp,a.status,a.reason,a.queued,a.age FROM students s
                 LEFT JOIN attendance a ON a.student_uid=s.uid AND a.lecture_uid=? WHERE s.deleted=0""" + _w.replace(" dept_uid", " s.dept_uid") + " ORDER BY s.grp,s.name_norm", [uid] + _a).fetchall()
            return J(lecture={k: lec[k] for k in ("uid", "code", "course", "start_ts", "end_ts", "status")},
                     students=[dict(r, reason_ar=core.REASONS.get(r["reason"] or "", "")) for r in rows])
        finally:
            c.close()

    @app.route("/api/admin/attendance/toggle", methods=["POST"])
    @need("lectures")
    def a_toggle():
        b = request.get_json(force=True, silent=True) or {}
        c = db()
        try:
            lc = c.execute("SELECT course_uid FROM lectures WHERE uid=?", (b.get("lecture_uid"),)).fetchone()
            if not lc or not can_course(c, lc["course_uid"]):
                return err("غير مسموح", 403)
            n = D.now()
            st = "ok" if b.get("present") else "rejected"
            reason = "" if b.get("present") else "manual_absent"
            c.execute("""INSERT INTO attendance(lecture_uid,student_uid,status,reason,created_at,updated_at,rev,dirty,queued) VALUES(?,?,?,?,?,?,?,1,0)
                 ON CONFLICT(lecture_uid,student_uid) DO UPDATE SET status=excluded.status,reason=excluded.reason,updated_at=excluded.updated_at,rev=excluded.rev,dirty=1""",
                      (b.get("lecture_uid"), b.get("student_uid"), st, reason, n, n, D.next_rev(c)))
            return J(ok=True)
        finally:
            c.close()


    # ═════════ حسابات الدكاترة والتقارير ═════════
    def user_row(c, r):
        d = {"id": r["id"], "username": r["username"], "email": r["email"] or "", "role": r["role"], "role_ar": ROLE_AR.get(r["role"], r["role"]),
             "full_name": r["full_name"] or "", "college_uid": r["college_uid"] or "", "dept_uid": r["dept_uid"] or "",
             "perms": [x for x in (r["perms"] or "").split(",") if x in PERMS], "can_delegate": bool(r["can_delegate"])}
        if r["role"] == "doctor":
            d["courses"] = c.execute("SELECT COUNT(*) FROM courses WHERE deleted=0 AND lower(trim(doctor_email))=?", ((r["email"] or "").lower(),)).fetchone()[0]
        return d

    def can_manage(c, t):
        """هل يستطيع المستخدم الحالي إدارة الحساب t (صف admins)؟ العميد يدير كليته، رئيس القسم (بتفويض) يدير مقرري قسمه، ومن يملك صلاحية الدكاترة يدير الدكاترة ضمن نطاقه."""
        me, tr = role(), t["role"]
        if t["id"] == session.get("uid") or me == "doctor" or tr == "admin":
            return False
        if me == "admin":
            return True
        if tr == "doctor":
            if not has("doctors"):
                return False
            if me == "dean":
                return (t["college_uid"] or "") == session.get("college")
            return (t["dept_uid"] or "") == session.get("dept")
        if me == "dean":
            return RANK[tr] > 1 and (t["college_uid"] or "") == session.get("college")
        if me == "head":
            return tr == "rapporteur" and bool(session.get("delegate")) and (t["dept_uid"] or "") == session.get("dept")
        return False

    def clean_perms(b, ceiling):
        want = b.get("perms")
        if isinstance(want, str):
            want = want.split(",")
        return [p for p in PERMS if p in (want or []) and p in ceiling]

    @app.route("/api/admin/users", methods=["GET", "POST"])
    @staff_required
    def a_users():
        me = role()
        if me == "doctor" or (me == "rapporteur" and not has("doctors")):
            return err("ليست لديك صلاحية إدارة المستخدمين", 403)
        if me == "head" and not session.get("delegate") and not has("doctors"):
            return err("لم يمنحك العميد صلاحية تحديد مقرر القسم", 403)
        c = db()
        try:
            if request.method == "GET":
                rows = c.execute("SELECT * FROM admins ORDER BY role,username").fetchall()
                out = [user_row(c, r) for r in rows if r["role"] != "admin" and (can_manage(c, r) or r["id"] == session.get("uid"))]
                return J(users=out, perm_labels=PERMS, my_perms=sorted(eff_perms()))
            b = request.get_json(force=True, silent=True) or {}
            tr = b.get("role") or ("doctor" if request.path.endswith("/doctors") else "")
            if tr not in ("dean", "head", "rapporteur", "doctor"):
                return err("نوع الحساب غير صحيح")
            allowed = {"admin": ("dean", "head", "rapporteur", "doctor"), "dean": ("head", "rapporteur", "doctor"),
                       "head": ("rapporteur", "doctor") if session.get("delegate") else ("doctor",), "rapporteur": ("doctor",)}.get(me, ())
            if tr == "doctor" and not has("doctors"):
                return err("ليست لديك صلاحية: حسابات الدكاترة", 403)
            if tr == "rapporteur" and me == "head" and not session.get("delegate"):
                return err("لم يمنحك العميد صلاحية تحديد مقرر القسم", 403)
            if tr not in allowed:
                return err("لا يمكنك إنشاء هذا النوع من الحسابات", 403)
            em, pw = (b.get("email") or "").strip().lower(), b.get("password") or ""
            uname = (b.get("username") or em).strip()
            if tr == "doctor":
                uname = em
            if not uname or len(uname) < 3:
                return err("اكتب اسم المستخدم (3 أحرف فأكثر)" if tr != "doctor" else "اكتب إيميل الدكتور الجامعي بشكل صحيح")
            if (em or tr == "doctor") and ("@" not in em or "." not in em):
                return err("اكتب الإيميل بشكل صحيح")
            if len(pw) < 6:
                return err("كلمة المرور 6 أحرف على الأقل")
            if c.execute("SELECT 1 FROM admins WHERE lower(username)=lower(?)", (uname,)).fetchone():
                return err("اسم المستخدم موجود مسبقاً")
            # النطاق
            col, dep = "", ""
            if tr == "dean":
                col = b.get("college_uid") or ""
                if not c.execute("SELECT 1 FROM colleges WHERE uid=? AND deleted=0", (col,)).fetchone():
                    return err("اختر الكلية")
            else:
                if me == "admin" or me == "dean":
                    dep = b.get("dept_uid") or ""
                    if tr == "doctor" and not dep and me == "admin":
                        dep = ""
                    elif not dept_in_scope(c, dep):
                        return err("اختر القسم")
                else:
                    dep = session.get("dept")
                if dep:
                    col = c.execute("SELECT college_uid FROM departments WHERE uid=?", (dep,)).fetchone()[0]
                elif me == "dean":
                    col = session.get("college")
            # الصلاحيات: العميد يحدد بحرية، رئيس القسم لا يتجاوز صلاحياته
            ceiling = set(PERMS) if me in ("admin", "dean") else eff_perms()
            perms = clean_perms(b, ceiling) if tr in ("head", "rapporteur") else []
            delegate = 1 if (tr == "head" and b.get("can_delegate") and me in ("admin", "dean")) else 0
            c.execute("INSERT INTO admins(username,pw_hash,must_change,role,email,college_uid,dept_uid,perms,can_delegate,parent_id,full_name) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (uname, generate_password_hash(pw), 0 if tr == "doctor" else 1, tr, em, col, dep, ",".join(perms), delegate, session.get("uid"), (b.get("full_name") or "").strip()))
            return J(ok=True)
        finally:
            c.close()

    @app.route("/api/admin/users/<int:uid>", methods=["PUT", "DELETE"])
    @staff_required
    def a_user(uid):
        c = db()
        try:
            t = c.execute("SELECT * FROM admins WHERE id=?", (uid,)).fetchone()
            if not t or not can_manage(c, t):
                return err("غير موجود أو خارج صلاحيتك", 404)
            if request.method == "DELETE":
                c.execute("DELETE FROM admins WHERE id=?", (uid,))
                return J(ok=True)
            b = request.get_json(force=True, silent=True) or {}
            sets, args = [], []
            if b.get("password"):
                if len(b["password"]) < 6:
                    return err("كلمة المرور 6 أحرف على الأقل")
                sets += ["pw_hash=?", "must_change=1"]
                args.append(generate_password_hash(b["password"]))
            if "full_name" in b:
                sets.append("full_name=?"); args.append((b.get("full_name") or "").strip())
            if t["role"] in ("head", "rapporteur") and "perms" in b:
                ceiling = set(PERMS) if role() in ("admin", "dean") else eff_perms()
                sets.append("perms=?"); args.append(",".join(clean_perms(b, ceiling)))
            if t["role"] == "head" and "can_delegate" in b and role() in ("admin", "dean"):
                sets.append("can_delegate=?"); args.append(1 if b["can_delegate"] else 0)
            if sets:
                c.execute("UPDATE admins SET %s WHERE id=?" % ",".join(sets), args + [uid])
            return J(ok=True)
        finally:
            c.close()

    # توافق مع الواجهة القديمة: حسابات الدكاترة
    @app.route("/api/admin/doctors", methods=["GET", "POST"])
    @need("doctors")
    def a_doctors():
        if request.method == "POST":
            return a_users()
        c = db()
        try:
            out = [user_row(c, r) for r in c.execute("SELECT * FROM admins WHERE role='doctor' ORDER BY username").fetchall() if can_manage(c, r)]
            return J(doctors=out)
        finally:
            c.close()

    @app.route("/api/admin/doctors/<int:did>", methods=["PUT", "DELETE"])
    @need("doctors")
    def a_doctor(did):
        return a_user(did)

    @app.route("/api/admin/reports")
    @need("reports")
    def a_reports():
        c = db()
        try:
            mine = my_course_uids(c)
            rows = c.execute("SELECT uid,name FROM courses WHERE deleted=0 ORDER BY name").fetchall()
            courses = [r for r in rows if mine is None or r["uid"] in mine]
            want = request.args.get("course_uid")
            overview = []
            for r in courses:
                st = core.course_stats(c, r["uid"])
                overview.append({"uid": r["uid"], "name": r["name"], "lectures": st["lectures"], "students": st["students"], "avg": st["avg"], "risk": st["risk_count"]})
            detail = None
            if want and any(r["uid"] == want for r in courses):
                detail = core.course_stats(c, want, request.args.get("group") or None)
                detail["course"] = next(r["name"] for r in courses if r["uid"] == want)
            return J(overview=overview, detail=detail)
        finally:
            c.close()

    core.REASONS["manual_absent"] = "تعديل يدوي من المسؤول"

    # الإعدادات
    @app.route("/api/admin/wipe", methods=["POST"])
    @admin_required
    def a_wipe():
        """تفريغ البيانات (علامات حذف تُزامَن لكل الأجهزة). what=attendance: المحاضرات والحضور فقط، what=all: كل شيء عدا حسابات الدخول والإعدادات."""
        b = request.get_json(force=True, silent=True) or {}
        if (b.get("confirm") or "").strip() != "تفريغ":
            return J(error="اكتب كلمة «تفريغ» للتأكيد"), 400
        what = b.get("what") or "all"
        if what not in ("all", "attendance"):
            return J(error="خيار غير صالح"), 400
        c = db()
        try:
            c.execute("BEGIN IMMEDIATE")
            n = D.now()
            cnt = {}
            tabs = [("attendance", "status", "'deleted'", "1=1", None), ("lectures", "status", "'deleted'", "1=1", None)]
            if what == "all":
                tabs += [("students", "deleted", "1", "deleted=0", None), ("courses", "deleted", "1", "deleted=0", None), ("departments", "deleted", "1", "deleted=0", None), ("colleges", "deleted", "1", "deleted=0", None)]
            for t, col, val, cond, _ in tabs:
                if t == "attendance":
                    rows = c.execute("SELECT lecture_uid,student_uid FROM attendance WHERE COALESCE(status,'')!='deleted'").fetchall()
                    for r in rows:
                        c.execute("UPDATE attendance SET status='deleted',updated_at=?,rev=?,dirty=1 WHERE lecture_uid=? AND student_uid=?", (n, D.next_rev(c), r[0], r[1]))
                    cnt[t] = len(rows)
                else:
                    rows = c.execute("SELECT uid FROM %s WHERE %s%s" % (t, cond, " AND status!='deleted'" if t == "lectures" else "")).fetchall()
                    for r in rows:
                        c.execute("UPDATE %s SET %s=%s,updated_at=?,rev=?,dirty=1 WHERE uid=?" % (t, col, val), (n, D.next_rev(c), r[0]))
                    cnt[t] = len(rows)
            c.execute("DELETE FROM auto_exports")
            c.execute("DELETE FROM outbox WHERE sent_at IS NULL")
            c.execute("COMMIT")
            return J(ok=True, **cnt)
        except Exception:
            try: c.execute("ROLLBACK")
            except Exception: pass
            raise
        finally:
            c.close()

    @app.route("/api/admin/settings", methods=["GET", "PUT"])
    @admin_required
    def a_settings():
        c = db()
        try:
            if request.method == "PUT":
                b = request.get_json(force=True, silent=True) or {}
                for k, v in b.items():
                    if k in D.DEFAULTS:
                        if k in ("smtp_pass", "imap_pass") and v == "********":
                            continue
                        if k == "late_after_min":
                            try:
                                v = str(min(600, max(0, int(float(v)))))
                            except Exception:
                                return err("قيمة التأخير غير صحيحة")
                        if k == "report_hour":
                            try:
                                v = str(min(23, max(0, int(float(v)))))
                            except Exception:
                                return err("ساعة التقرير غير صحيحة")
                        if k in ("public_url", "relay_url"):
                            v = (v or "").strip()
                            if v and not v.startswith(("http://", "https://")):
                                return err("الرابط يجب أن يبدأ بـ https://")
                        if k == "email_domain":
                            v = (v or "").strip().lower().lstrip("@")
                        if k == "report_mode":
                            v = "auto" if v == "auto" else "approval"
                        if k in ("require_device_sig", "mail_sync", "manual_checkin"):
                            v = "1" if str(v) in ("1", "true", "True") else "0"
                        if k == "absence_limit":
                            try:
                                v = str(min(100, max(0, int(float(v)))))
                            except Exception:
                                return err("نسبة الغياب غير صحيحة")
                        if k in ("qr_interval", "scan_grace", "default_duration", "max_sync_delay_hours"):
                            try:
                                v = int(float(v))
                                if k == "max_sync_delay_hours":
                                    v = min(168, max(24, v))   # مهلة استلام الحضور: 24 ساعة … 168 ساعة (7 أيام)
                                v = str(max(1, v))
                            except Exception:
                                return err("قيمة غير صحيحة في " + k)
                        D.set_setting(c, k, v)
                return J(ok=True)
            S = D.get_settings(c)
            for _k in ("smtp_pass", "imap_pass"):
                if S.get(_k):
                    S[_k] = "********"
            return J(settings=S, conf={"cloud_url": CONF.get("cloud_url", ""), "has_sync_key": bool(CONF.get("sync_key")), "mode": MODE})
        finally:
            c.close()

    # التصدير والبريد
    @app.route("/api/admin/export")
    @need("reports")
    def a_export():
        c = db()
        try:
            if not can_course(c, request.args.get("course_uid", "")):
                return err("غير مسموح", 403)
            from config import EXPORT_DIR
            course = c.execute("SELECT name FROM courses WHERE uid=?", (request.args.get("course_uid", ""),)).fetchone()
            if not course:
                return err("اختر المادة")
            path = os.path.join(EXPORT_DIR, "tmp_%s.xlsx" % D.new_uid())
            core.build_export(c, request.args["course_uid"], path, group=request.args.get("group") or None)
            data = open(path, "rb").read()
            os.remove(path)
            return send_file(io.BytesIO(data), as_attachment=True, download_name="attendance_%s.xlsx" % D.new_uid()[:6],
                             mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        finally:
            c.close()

    @app.route("/api/admin/export/send", methods=["POST"])
    @need("reports")
    def a_export_send():
        b = request.get_json(force=True, silent=True) or {}
        c = db()
        try:
            if not can_course(c, b.get("course_uid", "")):
                return err("غير مسموح", 403)
            r = core.export_and_mail(c, CONF, b.get("course_uid", ""))
        except ValueError as e:
            return err(str(e))
        finally:
            c.close()
        res = core.flush_outbox(CONF)
        return J(ok=True, sent=res["sent"], failed=res["failed"], filename=r["filename"])

    @app.route("/api/admin/backup")
    @admin_required
    def a_backup():
        """نسخة احتياطية كاملة لقاعدة البيانات (SQLite) للتنزيل."""
        import sqlite3, tempfile
        from config import DB_PATH
        tmp = os.path.join(tempfile.gettempdir(), "att_backup_%s.sqlite" % D.new_uid())
        src, dst = sqlite3.connect(DB_PATH, timeout=30), sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        data = open(tmp, "rb").read()
        os.remove(tmp)
        return send_file(io.BytesIO(data), as_attachment=True, download_name="attendance_backup_%s.sqlite" % time.strftime("%Y%m%d_%H%M"), mimetype="application/octet-stream")

    @app.route("/api/admin/outbox", methods=["GET", "POST"])
    @admin_required
    def a_outbox():
        if request.method == "POST":
            return J(**core.flush_outbox(CONF))
        c = db()
        try:
            rows = c.execute("SELECT id,to_addrs,subject,created_at,sent_at,tries,last_error FROM outbox ORDER BY id DESC LIMIT 50").fetchall()
            return J(items=[dict(r) for r in rows])
        finally:
            c.close()

    @app.route("/api/admin/sync", methods=["POST"])
    @admin_required
    def a_sync():
        try:
            return J(ok=True, **core.sync_once(CONF))
        except Exception as e:
            return J(ok=False, error="لا يوجد اتصال بالسحابة: " + str(e)[:150])

    routes_x.register(app, dict(db=db, J=J, err=err, role=role, need=need, CONF=CONF, MODE=MODE, can_course=can_course))
    return app


def start_workers(interval=30):
    """خيط خلفي: مزامنة السحابة وإرسال البريد المعلّق كلما توفر الإنترنت."""
    def loop():
        while True:
            try:
                if CONF.get("cloud_url") and CONF.get("sync_key") and MODE != "cloud":
                    core.sync_once(CONF)
            except Exception:
                pass
            try:
                core.flush_outbox(CONF)
            except Exception:
                pass
            try:
                if MODE == "cloud" or not CONF.get("cloud_url"):
                    core.run_auto_exports(CONF)
            except Exception:
                pass
            try:
                if MODE == "cloud" or not CONF.get("cloud_url"):
                    X.run_daily_reports(CONF)          # تقارير 2:00 فجراً بعد انتهاء مهلة الاستلام
            except Exception:
                pass
            _S = {}
            try:
                _c = D.connect()
                _S = D.get_settings(_c); _c.close()
                if _S.get("mail_sync") == "1" and CONF.get("sync_key"):
                    import mailsync
                    if _S.get("attendance_mailbox"):
                        mailsync.send_pending(CONF)
                        if _S.get("imap_host"):
                            mailsync.process_acks(CONF)
                    if MODE == "cloud" and _S.get("imap_host"):
                        mailsync.receive_batches(CONF)
                if _S.get("imap_host") and _S.get("attendance_mailbox"):
                    import mailsync
                    mailsync.receive_student_mails(CONF)   # حضور الطلاب المرسَل بالإيميل (القاعة تنتظر البريد)
            except Exception:
                pass
            try:
                X.backup_verified(int(_S.get("backup_keep", 14) or 14))
            except Exception:
                pass
            time.sleep(interval)
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t


app = None


def get_app():
    global app
    if app is None:
        app = create_app()
    return app
