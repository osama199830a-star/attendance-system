# -*- coding: utf-8 -*-
"""مزامنة الحضور عبر البريد الإلكتروني (SMTP للإرسال + IMAP للاستلام).

الفكرة (حسب المواصفات):
  • لا رسالة لكل طالب: دفعة واحدة (Batch) لكل مزامنة تحتوي كل السجلات غير المرسلة، JSON مضغوط gzip.
  • كل دفعة لها Batch ID فريد وتوقيع HMAC-SHA256 بمفتاح المزامنة (sync_key) — لا نثق بعنوان المرسل أبداً.
  • الاستلام Idempotent: جدول mail_batches يمنع معالجة الدفعة مرتين (تُعاد رسالة التأكيد فقط).
  • لا تُعلَّم السجلات المحلية «مزامَنة» إلا بعد وصول رسالة تأكيد (ACK) موقّعة من الخادم. وإن لم يصل تأكيد تُعاد الدفعة نفسها.
  • مصادقة IMAP/SMTP: كلمة مرور تطبيق (App Password) أو رمز OAuth2 (XOAUTH2) عبر متغير البيئة MAIL_OAUTH2_TOKEN.
"""
import base64, email, email.utils, gzip, hashlib, hmac, imaplib, json, os, smtplib, ssl, time, uuid
from email.message import EmailMessage

import db as D
import core
import extras as X

SUBJ_BATCH, SUBJ_ACK = "ATT-BATCH", "ATT-ACK"
RESEND_AFTER = 3600       # إعادة إرسال الدفعة غير المؤكَّدة بعد ساعة
MAX_BATCH_ROWS = 4000


# ───────────── التوقيع ─────────────
def sign_body(key, batch_id, body):
    return hmac.new(key.encode(), (batch_id + "." + hashlib.sha256(body).hexdigest()).encode(), hashlib.sha256).hexdigest()


def pack(conf, batch_id, push, station):
    body = gzip.compress(json.dumps({"v": 1, "batch_id": batch_id, "station": station, "created": D.now(), "push": push}, ensure_ascii=False).encode("utf-8"))
    return body, sign_body(conf["sync_key"], batch_id, body)


def unpack(conf, batch_id, body, sig):
    """يُرجع dict الدفعة أو يرفع ValueError إن كان التوقيع/البنية غير صالحة."""
    if not conf.get("sync_key") or not hmac.compare_digest(sign_body(conf["sync_key"], batch_id, body), sig or ""):
        raise ValueError("bad_signature")
    try:
        data = json.loads(gzip.decompress(body).decode("utf-8"))
    except Exception:
        raise ValueError("bad_payload")
    if data.get("batch_id") != batch_id or not isinstance(data.get("push"), dict):
        raise ValueError("bad_payload")
    return data


# ───────────── النقل (قابل للاستبدال في الاختبارات) ─────────────
class SmtpTransport:
    def __init__(self, S):
        self.S = S

    def send(self, msg):
        S = self.S
        host, port = S.get("smtp_host") or "smtp.gmail.com", int(S.get("smtp_port") or 465)
        if not S.get("smtp_user"):
            raise RuntimeError("لم يُضبط بريد الإرسال (SMTP)")
        msg["From"] = S["smtp_user"]
        ctx = ssl.create_default_context()
        if port == 465:
            srv = smtplib.SMTP_SSL(host, port, context=ctx, timeout=30)
        else:
            srv = smtplib.SMTP(host, port, timeout=30)
            srv.starttls(context=ctx)
        try:
            tok = os.environ.get("MAIL_OAUTH2_TOKEN")
            if tok:
                srv.auth("XOAUTH2", lambda _=None: ("user=%s\x01auth=Bearer %s\x01\x01" % (S["smtp_user"], tok)))
            else:
                srv.login(S["smtp_user"], S.get("smtp_pass", ""))
            srv.send_message(msg)
        finally:
            try:
                srv.quit()
            except Exception:
                pass


class ImapTransport:
    def __init__(self, S):
        self.S = S
        self.m = None

    def __enter__(self):
        S = self.S
        self.m = imaplib.IMAP4_SSL(S.get("imap_host"), int(S.get("imap_port") or 993), ssl_context=ssl.create_default_context(), timeout=25)
        tok = os.environ.get("MAIL_OAUTH2_TOKEN")
        user = S.get("imap_user") or S.get("smtp_user")
        if tok:
            self.m.authenticate("XOAUTH2", lambda _: ("user=%s\x01auth=Bearer %s\x01\x01" % (user, tok)).encode())
        else:
            self.m.login(user, S.get("imap_pass") or S.get("smtp_pass", ""))
        self.m.select(S.get("imap_folder") or "INBOX")
        return self

    def __exit__(self, *a):
        try:
            self.m.logout()
        except Exception:
            pass

    def unseen(self, subject):
        typ, data = self.m.search(None, "UNSEEN", "SUBJECT", '"%s"' % subject)
        out = []
        for num in (data[0].split() if data and data[0] else []):
            typ, d = self.m.fetch(num, "(BODY.PEEK[])")
            out.append((num, email.message_from_bytes(d[0][1])))
        return out

    def mark_seen(self, num):
        self.m.store(num, "+FLAGS", "\\Seen")


# ───────────── الإرسال (من القاعة/الجهاز) ─────────────
def _msg(to, subject, body_text, attach=None, name=None, sig=None):
    m = EmailMessage()
    m["To"] = to
    m["Subject"] = subject
    if sig:
        m["X-ATT-Sig"] = sig
    m.set_content(body_text)
    if attach is not None:
        m.add_attachment(attach, maintype="application", subtype="gzip", filename=name)
    return m


def send_pending(conf, smtp=None, force=False):
    """يجمع كل السجلات غير المرسلة في دفعة واحدة ويرسلها. يُرجع dict ملخصاً. لا يمسح شيئاً محلياً قبل التأكيد."""
    c = D.connect()
    try:
        S = D.get_settings(c)
        to = S.get("attendance_mailbox")
        if not to or not conf.get("sync_key"):
            return {"skipped": True}
        smtp = smtp or SmtpTransport(S)
        # 1) دفعة سابقة لم تُؤكَّد: نعيد إرسال الدفعة نفسها (Idempotent عند الاستلام)
        old = c.execute("SELECT * FROM mail_batches WHERE direction='out' AND status='sent' ORDER BY created_at LIMIT 1").fetchone()
        if old and not force and time.time() - old["updated_at"] < RESEND_AFTER:
            return {"waiting_ack": old["batch_id"]}
        if old:
            push = json.loads(old["detail"])
            bid = old["batch_id"]
            n_rows = old["n_rows"]
        else:
            push, marks = core.collect_dirty(c)
            n_rows = sum(len(v) for v in push.values())
            if not n_rows:
                return {"pushed": 0}
            bid = uuid.uuid4().hex
            mk = json.dumps([[t, k, u] for t, k, u in marks])
            c.execute("INSERT INTO mail_batches(batch_id,direction,n_rows,status,marks,detail,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                      (bid, "out", n_rows, "sent", mk, json.dumps(push, ensure_ascii=False), time.time(), time.time()))
        body, sig = pack(conf, bid, push, conf.get("station_name", ""))
        smtp.send(_msg(to, "%s %s" % (SUBJ_BATCH, bid), "Attendance batch %s (%d rows)" % (bid, n_rows), body, "batch_%s.json.gz" % bid, sig))
        c.execute("UPDATE mail_batches SET updated_at=? WHERE batch_id=? AND direction='out'", (time.time(), bid))
        return {"sent": bid, "rows": n_rows}
    finally:
        c.close()


def process_acks(conf, imap=None):
    """يقرأ رسائل ATT-ACK الموقّعة؛ عند التأكيد فقط تُعلَّم السجلات المحلية «تمت المزامنة»."""
    c = D.connect()
    n = 0
    try:
        S = D.get_settings(c)
        if not S.get("imap_host"):
            return 0
        with (imap or ImapTransport(S)) as im:
            for num, msg in im.unseen(SUBJ_ACK):
                try:
                    bid = (msg["Subject"] or "").split()[-1]
                    sig = msg.get("X-ATT-Sig", "")
                    exp = hmac.new(conf["sync_key"].encode(), ("ACK." + bid).encode(), hashlib.sha256).hexdigest()
                    if not hmac.compare_digest(exp, sig):
                        continue            # تأكيد غير موثّق: نتجاهله ولا نعلّم شيئاً
                    row = c.execute("SELECT * FROM mail_batches WHERE batch_id=? AND direction='out'", (bid,)).fetchone()
                    if row and row["status"] == "sent":
                        c.execute("BEGIN IMMEDIATE")
                        core.mark_clean(c, [(t, k, u) for t, k, u in json.loads(row["marks"])])
                        c.execute("UPDATE mail_batches SET status='acked',detail='',updated_at=? WHERE batch_id=? AND direction='out'", (time.time(), bid))
                        c.execute("COMMIT")
                        n += 1
                    im.mark_seen(num)
                except Exception:
                    try:
                        c.execute("ROLLBACK")
                    except Exception:
                        pass
        return n
    finally:
        c.close()


# ───────────── الاستلام (الخادم) ─────────────
def receive_batches(conf, imap=None, smtp=None):
    """يقرأ ATT-BATCH غير المقروءة، يتحقق من التوقيع ومن عدم التكرار، يدمجها، ثم يرسل ACK. يُرجع (جديدة, مكررة, مرفوضة)."""
    c = D.connect()
    new = dup = bad = 0
    try:
        S = D.get_settings(c)
        if not S.get("imap_host"):
            return (0, 0, 0)
        smtp = smtp or SmtpTransport(S)
        with (imap or ImapTransport(S)) as im:
            for num, msg in im.unseen(SUBJ_BATCH):
                bid = (msg["Subject"] or "").split()[-1] if msg["Subject"] else ""
                sender = email.utils.parseaddr(msg.get("From", ""))[1]
                try:
                    att = next((p for p in msg.walk() if p.get_filename()), None)
                    if not att or not bid:
                        raise ValueError("no_attachment")
                    body = att.get_payload(decode=True)
                    data = unpack(conf, bid, body, msg.get("X-ATT-Sig", ""))
                except Exception as e:
                    bad += 1
                    c.execute("INSERT OR IGNORE INTO mail_batches(batch_id,direction,n_rows,status,detail,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                              (bid or uuid.uuid4().hex, "in", 0, "rejected", str(e)[:120], time.time(), time.time()))
                    im.mark_seen(num)
                    continue
                seen = c.execute("SELECT 1 FROM mail_batches WHERE batch_id=? AND direction='in' AND status='done'", (bid,)).fetchone()
                if seen:
                    dup += 1
                else:
                    c.execute("BEGIN IMMEDIATE")
                    try:
                        core.merge_rows(c, data["push"], clean=False)
                        core.verify_pending(c)
                        c.execute("INSERT OR REPLACE INTO mail_batches(batch_id,direction,n_rows,status,detail,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                                  (bid, "in", sum(len(v) for v in data["push"].values()), "done", sender, time.time(), time.time()))
                        c.execute("COMMIT")
                        new += 1
                    except Exception:
                        c.execute("ROLLBACK")
                        raise
                # تأكيد الاستلام (يُعاد أيضاً للمكرَّر حتى يتوقف المرسل عن إعادة الدفعة)
                ack_to = sender or S.get("attendance_mailbox")
                if ack_to:
                    exp = hmac.new(conf["sync_key"].encode(), ("ACK." + bid).encode(), hashlib.sha256).hexdigest()
                    smtp.send(_msg(ack_to, "%s %s" % (SUBJ_ACK, bid), "ack", None, None, exp))
                im.mark_seen(num)
        return (new, dup, bad)
    finally:
        c.close()


# ───────────── حضور الطلاب المرسَل بالإيميل (من هواتفهم) ─────────────
import re as _re
_STU_RE = _re.compile(r"ATT:([A-Za-z0-9+/=_\-]+):END")


def _body_text(msg):
    parts = [msg] if not msg.is_multipart() else list(msg.walk())
    out = []
    for p in parts:
        if p.get_content_type() == "text/plain" and not p.get_filename():
            try:
                out.append(p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8", "replace"))
            except Exception:
                pass
    return "\n".join(out)


def _recv_ts(msg):
    """وقت وصول الرسالة إلى خادم البريد (أعلى ترويسة Received يضيفها الخادم المستلم، لا الهاتف)؛ لا يتجاوز الآن."""
    from email.utils import parsedate_to_datetime
    ts = None
    try:
        h = (msg.get_all("Received") or [""])[0]
        ts = parsedate_to_datetime(str(h).rsplit(";", 1)[1].strip()).timestamp()
    except Exception:
        try:
            ts = parsedate_to_datetime(msg["Date"]).timestamp()
        except Exception:
            ts = None
    return min(ts, time.time()) if ts else time.time()


def receive_student_mails(conf, imap=None, smtp=None):
    """جهاز القاعة ينتظر رسائل ATT-STU من هواتف الطلاب ويسجّل حضورهم بنفس فحوص الباركود والجهاز.
    لا نثق بعنوان المرسل: الحماية = توقيع الباركود (HMAC) + ربط الجهاز + توقيع مفتاح الجهاز. يُرجع (مقبول, مرفوض, رسائل)."""
    import base64 as b64
    c = D.connect()
    ok_n = bad_n = msgs = 0
    try:
        S = D.get_settings(c)
        if not S.get("imap_host"):
            return (0, 0, 0)
        with (imap or ImapTransport(S)) as im:
            for num, msg in im.unseen("ATT-STU"):
                msgs += 1
                results = []
                try:
                    m = _STU_RE.search(_body_text(msg).replace("\r", "").replace("\n", ""))
                    data = json.loads(b64.b64decode(m.group(1) + "=" * (-len(m.group(1)) % 4)).decode("utf-8")) if m else None
                    dev = str((data or {}).get("device_id", ""))[:80]
                    items = (data or {}).get("items") or []
                    if not data or not dev or not isinstance(items, list) or len(items) > 10:
                        raise ValueError("bad")
                    recv = _recv_ts(msg)
                    for it in items:
                        it = dict(it, queued=True)
                        if not it.get("student") and it.get("sid"):     # صفحة عامة بلا خادم: الطالب يُعرَّف برقمه/بريده
                            em = X.clean_email(str(it["sid"]), S.get("email_domain", ""))
                            row = c.execute("SELECT uid FROM students WHERE lower(univ_email)=? AND deleted=0", (em or "",)).fetchone()
                            if not row:
                                results.append({"status": "rejected", "reason": "unknown_student"}); bad_n += 1
                                continue
                            it["sig_student"] = it.get("student", "")
                            it["student"] = row["uid"]
                        c.execute("BEGIN IMMEDIATE")
                        try:
                            r = core.record_scan(c, dev, it, recv_ts=recv)
                            c.execute("COMMIT")
                        except Exception:
                            c.execute("ROLLBACK")
                            raise
                        results.append(r)
                        if r["status"] in ("ok", "duplicate", "guest_pending"):
                            ok_n += 1
                        else:
                            bad_n += 1
                except Exception:
                    bad_n += 1
                    results = [{"status": "rejected", "reason": "bad_mail"}]
                im.mark_seen(num)
                to = email.utils.parseaddr(msg.get("From", ""))[1]
                if to and smtp is not False and not to.lower().endswith(("resend.dev", "noreply", "no-reply")) and "no-reply" not in to.lower():
                    try:
                        good = sum(1 for r in results if r["status"] in ("ok", "duplicate"))
                        txt = "تم تسجيل حضورك (%d)." % good if good else "تعذّر قبول الحضور: " + "؛ ".join(sorted({core.REASONS.get(r.get("reason", ""), r.get("reason", "")) or r["status"] for r in results}))
                        (smtp or SmtpTransport(S)).send(_msg(to, "ATT-REPLY", txt))
                    except Exception:
                        pass
        return (ok_n, bad_n, msgs)
    finally:
        c.close()
