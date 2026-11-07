# -*- coding: utf-8 -*-
"""الصفحة العامة بلا خادم: دخول برقم الطالب ← زر واحد يسجّل ويرسل (ترحيل تلقائي) ← أوفلاين ثم يُرسل عند توفر شبكة ← جهاز الدكتور يعالج البريد."""
import base64, email, json, os, subprocess, sys, tempfile, threading, time, functools, http.server, socketserver
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(); os.environ["ATT_DATA"] = os.path.join(tmp, "d"); os.environ["ADMIN_USER"], os.environ["ADMIN_PASS"] = "boss", "secret99"
sys.path.insert(0, os.path.join(ROOT, "server")); sys.path.insert(0, os.path.join(ROOT, "tests"))
import db as D, core, mailsync, core_frag
site = os.path.join(tmp, "site")
subprocess.run([sys.executable, os.path.join(ROOT, "tools", "build_static_site.py"), "--mailbox", "doc@gmail.com", "--out", site], check=True, capture_output=True)
OK = FAIL = 0
def check(n, c, x=""):
    global OK, FAIL
    if c: OK += 1; print("  ✓", n)
    else: FAIL += 1; print("  ✗", n, x)
D.init(); c = D.connect(); n = time.time()
c.execute("INSERT INTO courses(uid,name,doctor_email,updated_at,rev,dirty) VALUES('cr','شبكات','d@x',?,1,1)", (n,))
c.execute("INSERT INTO students(uid,name,name_norm,grp,univ_email,updated_at,rev,dirty) VALUES('st1','1063004760','1063004760','A1','1063004760@uoa.edu.iq',?,1,1)", (n,))
c.execute("INSERT INTO lectures(uid,code,course_uid,secret,start_ts,end_ts,interval_sec,status,station,grp,updated_at,rev,dirty) VALUES('L','ABC123','cr','secret',?,?,3,'active','','',?,1,1)", (n, n + 3600, n))
lec = dict(code="ABC123", secret="secret", interval_sec=3)
class H(http.server.SimpleHTTPRequestHandler):
    def __init__(s, *a, **k): super().__init__(*a, directory=site, **k)
    def log_message(s, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), H); PORT = srv.server_address[1]; threading.Thread(target=srv.serve_forever, daemon=True).start()
from playwright.sync_api import sync_playwright
posts = []
with sync_playwright() as pw:
    b = pw.chromium.launch(); ctx = b.new_context(viewport={"width": 393, "height": 800}, is_mobile=True, service_workers="block")
    ctx.route("https://www.gstatic.com/**", lambda r: r.fulfill(status=204, body=""))
    def relay(r):
        posts.append(json.loads(r.request.post_data)); r.fulfill(status=200, content_type="application/json", body='{"ok":true}')
    ctx.route("**/.netlify/functions/attend", relay)
    pg = ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto("http://127.0.0.1:%d/s/" % PORT); pg.wait_for_selector("#em")
    pg.fill("#em", "1063004760"); pg.click("#emgo"); pg.wait_for_selector(".me")
    check("دخول برقم الطالب بدون خادم", "1063004760" in pg.inner_text("#app"))
    pg.wait_for_function("document.querySelector('#net') && !document.querySelector('#net').classList.contains('off')", timeout=8000)
    check("المؤشر «متصل» بمجرد توفر أي شبكة (بلا خادم الدكتور)", True)
    pg.goto("http://127.0.0.1:%d/s/#%s" % (PORT, core_frag.frag(lec))); pg.wait_for_selector("#go:not([disabled])", timeout=8000)
    pg.click("#go"); pg.wait_for_selector(".res.ok", timeout=8000)
    check("زر واحد: سجّل وأرسل تلقائياً", len(posts) == 1 and "أُرسل حضورك بالإيميل" in pg.inner_text(".res"), posts)
    d = json.loads(base64.b64decode(posts[0]["payload"]))
    check("الدفعة تحمل الرقم الجامعي والجهاز والتوقيع", d["items"][0]["sid"] == "1063004760@uoa.edu.iq" and d["device_id"] and d["items"][0].get("dsig"))
    pay1 = posts[0]["payload"]
    # أوفلاين ثم عودة الشبكة
    pg.goto("http://127.0.0.1:%d/s/#%s" % (PORT, core_frag.frag(dict(lec, code="ABC123")))); pg.wait_for_selector("#go:not([disabled])")
    ctx.set_offline(True); pg.evaluate("window.dispatchEvent(new Event('offline'))")
    pg.click("#go"); pg.wait_for_timeout(600)
    check("بدون شبكة: يُحفظ على الهاتف ولا يضيع", "بانتظار الإنترنت" in pg.inner_text("#app") or "حُفظ حضورك" in pg.inner_text(".res"))
    n0 = len(posts); ctx.set_offline(False); pg.evaluate("window.dispatchEvent(new Event('online'))"); pg.wait_for_timeout(2500)
    check("أول ما تتوفر شبكة يُرسل تلقائياً", len(posts) == n0 + 1, (n0, len(posts)))
    check("لا أخطاء JS", not errs, errs)
    b.close()
srv.shutdown()
# جهاز الدكتور يعالج الإيميل لاحقاً
class FS:
    def __init__(s): s.sent = []
    def send(s, m): s.sent.append(m)
class FI:
    def __init__(s, m): s.m = m; s.seen = set()
    def __enter__(s): return s
    def __exit__(s, *a): pass
    def unseen(s, subj): return [(i, x) for i, x in enumerate(s.m) if i not in s.seen and x["Subject"].startswith(subj)]
    def mark_seen(s, i): s.seen.add(i)
def mail(p):
    m = email.message.EmailMessage(); m["Subject"] = "ATT-STU"; m["From"] = "Attendance <onboarding@resend.dev>"; m.set_content("ATT:" + p + ":END"); return email.message_from_bytes(m.as_bytes())
D.set_setting(c, "imap_host", "imap.fake")
fs = FS()
res = mailsync.receive_student_mails({"sync_key": "k"}, FI([mail(pay1)]), fs)
check("البريد المحوَّل يُسجَّل حضوراً عبر الرقم الجامعي", res[0] == 1 and c.execute("SELECT status FROM attendance WHERE student_uid='st1'").fetchone()[0] == "ok", res)
check("الجهاز يرتبط ويُسجَّل مفتاحه من أول حضور", c.execute("SELECT device_id FROM students WHERE uid='st1'").fetchone()[0] == d["device_id"] and c.execute("SELECT pub FROM device_keys WHERE student_uid='st1'").fetchone()[0])
check("لا ردّ على عنوان no-reply", not fs.sent)
d["items"][0]["sid"] = "9999999999@uoa.edu.iq"
res = mailsync.receive_student_mails({"sync_key": "k"}, FI([mail(base64.b64encode(json.dumps(d).encode()).decode())]), FS())
check("رقم غير مسجل يُرفض", res[0] == 0 and res[1] >= 1, res)
print("\nنجح %d — فشل %d" % (OK, FAIL)); sys.exit(1 if FAIL else 0)
