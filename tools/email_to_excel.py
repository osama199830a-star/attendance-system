# -*- coding: utf-8 -*-
"""سحب إيميلات الحضور (IMAP) ← جدول pandas ← Excel منسّق ← إرسال تلقائي عبر SMTP للدكتور ورئيس القسم والعميد ورئيس الجامعة.
مثال (يُشغَّل من Cron كل 24 ساعة):
  python email_to_excel.py --imap imap.gmail.com --user att@gmail.com --pass APP_PASSWORD --to dr@u.edu head@u.edu dean@u.edu pres@u.edu
اختبار بلا بريد:  python email_to_excel.py --eml-dir ./mails --out out.xlsx --no-send
تنبيه: هذا السكربت يجمع ويرسل فقط. التحقق من توقيع الباركود وربط الجهاز يتم في خادم النظام (mailsync.py) وهو الذي يُنصح بتشغيله فعلياً."""
import argparse, base64, email, glob, imaplib, json, os, re, smtplib, ssl, time
from email.message import EmailMessage
import pandas as pd

PAT = re.compile(r"ATT:([A-Za-z0-9+/=_\-]+):END")

def parse_message(msg):
    body = ""
    for p in (msg.walk() if msg.is_multipart() else [msg]):
        if p.get_content_type() == "text/plain":
            body += p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8", "replace")
    m = PAT.search(body.replace("\r", "").replace("\n", ""))
    if not m:
        return []
    d = json.loads(base64.b64decode(m.group(1) + "=" * (-len(m.group(1)) % 4)))
    return [{"student": it.get("sid") or it.get("student"), "lecture_code": it.get("code"), "slot_time": it.get("t"), "device": d.get("device_id", "")[:8],
             "received": msg.get("Date", "")} for it in d.get("items", [])]

def fetch_imap(host, user, pwd, folder="INBOX"):
    rows = []
    with imaplib.IMAP4_SSL(host, 993, ssl_context=ssl.create_default_context(), timeout=30) as M:
        M.login(user, pwd); M.select(folder)
        _, data = M.search(None, "UNSEEN", "SUBJECT", '"ATT-STU"')
        for n in data[0].split():
            _, d = M.fetch(n, "(RFC822)")
            rows += parse_message(email.message_from_bytes(d[0][1]))
            M.store(n, "+FLAGS", "\\Seen")
    return rows

def build_excel(rows, path):
    df = pd.DataFrame(rows, columns=["student", "lecture_code", "slot_time", "device", "received"]).drop_duplicates(["student", "lecture_code"])
    df["slot_time"] = pd.to_datetime(df["slot_time"], unit="s", utc=True).dt.tz_convert("Asia/Baghdad").dt.strftime("%Y-%m-%d %H:%M:%S")
    df = df.rename(columns={"student": "الطالب", "lecture_code": "المحاضرة", "slot_time": "وقت المسح", "device": "الجهاز", "received": "وقت الاستلام"})
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="الحضور")
        ws = w.sheets["الحضور"]; ws.sheet_view.rightToLeft = True
        from openpyxl.styles import Font, PatternFill
        for c in ws[1]:
            c.font = Font(bold=True, size=14, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="1F3A8A")
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = 28
            for c in col[1:]:
                c.font = Font(size=14)
    return len(df)

def send(smtp_host, user, pwd, to, path, n):
    m = EmailMessage(); m["From"] = user; m["To"] = ", ".join(to); m["Subject"] = "تقرير الحضور اليومي — %s" % time.strftime("%Y-%m-%d")
    m.set_content("مرفق تقرير الحضور التلقائي (%d سجل)." % n)
    m.add_attachment(open(path, "rb").read(), maintype="application", subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=os.path.basename(path))
    with smtplib.SMTP_SSL(smtp_host, 465, context=ssl.create_default_context(), timeout=30) as s:
        s.login(user, pwd); s.send_message(m)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--imap", default="imap.gmail.com"); ap.add_argument("--smtp", default="smtp.gmail.com")
    ap.add_argument("--user"); ap.add_argument("--pass", dest="pwd"); ap.add_argument("--to", nargs="*", default=[])
    ap.add_argument("--eml-dir"); ap.add_argument("--out", default="attendance_%s.xlsx" % time.strftime("%Y%m%d")); ap.add_argument("--no-send", action="store_true")
    a = ap.parse_args()
    rows = []
    if a.eml_dir:
        for f in glob.glob(os.path.join(a.eml_dir, "*.eml")):
            rows += parse_message(email.message_from_bytes(open(f, "rb").read()))
    else:
        rows = fetch_imap(a.imap, a.user, a.pwd)
    n = build_excel(rows, a.out); print("سجلات:", n, "←", a.out)
    if n and not a.no_send and a.to:
        send(a.smtp, a.user, a.pwd, a.to, a.out, n); print("أُرسل إلى", ", ".join(a.to))
