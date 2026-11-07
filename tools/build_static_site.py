# -*- coding: utf-8 -*-
"""يبني موقعاً ثابتاً (بلا خادم) يفتح من أي شبكة: صفحة الطالب + دالة إرسال الحضور إلى جيميل الدكتور.
الاستخدام:
  python tools/build_static_site.py --mailbox attendance.univ@gmail.com --org "جامعة المعارف" --out site
ثم ارفع مجلد site إلى Netlify (من GitHub، لأن الدوال تحتاج Git/CLI) أو أي استضافة ثابتة (بدون الدالة يبقى زر «فتح البريد»).
متغيرات Netlify المطلوبة للدالة: RESEND_API_KEY  و TO_EMAIL (جيميل الدكتور نفسه المسجَّل في حساب Resend)."""
import argparse, os, shutil, json

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "server", "static", "student")

FUNC = r'''// دالة Netlify: تستقبل دفعة الحضور من هاتف الطالب (من أي شبكة) وتحوّلها إلى جيميل الدكتور. لا تحتفظ بأي بيانات.
// يحقق جهاز الدكتور لاحقاً من توقيع الباركود وربط الجهاز قبل احتساب الحضور؛ لذلك لا خطر من رسالة مزوّرة.
const H = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "Content-Type", "Content-Type": "application/json" };
exports.handler = async (event) => {
  if (event.httpMethod === "OPTIONS") return { statusCode: 204, headers: H, body: "" };
  if (event.httpMethod !== "POST") return { statusCode: 405, headers: H, body: JSON.stringify({ ok: false }) };
  let p = "";
  try { p = String(JSON.parse(event.body || "{}").payload || ""); } catch (e) { return { statusCode: 400, headers: H, body: JSON.stringify({ ok: false }) }; }
  try {
    if (!/^[A-Za-z0-9+/=]{20,8000}$/.test(p)) throw new Error("format");
    const d = JSON.parse(Buffer.from(p, "base64").toString("utf8"));
    if (!d.device_id || !Array.isArray(d.items) || !d.items.length || d.items.length > 10) throw new Error("items");
    for (const it of d.items) if (!/^[A-Z0-9]{4,10}$/.test(it.code || "")) throw new Error("code");
  } catch (e) { return { statusCode: 400, headers: H, body: JSON.stringify({ ok: false, error: "bad payload" }) }; }
  const r = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { Authorization: "Bearer " + process.env.RESEND_API_KEY, "Content-Type": "application/json" },
    body: JSON.stringify({ from: process.env.FROM_EMAIL || "Attendance <onboarding@resend.dev>", to: [process.env.TO_EMAIL], subject: "ATT-STU", text: "ATT:" + p + ":END" }),
  });
  return { statusCode: r.ok ? 200 : 502, headers: H, body: JSON.stringify({ ok: r.ok }) };
};
'''

ap = argparse.ArgumentParser()
ap.add_argument("--mailbox", default="", help="اختياري: جيميل استقبال الحضور. إن تُرك فارغاً يأخذه الباركود نفسه من برنامج الدكتور")
ap.add_argument("--org", default="جامعة المعارف")
ap.add_argument("--domain", default="uoa.edu.iq")
ap.add_argument("--out", default="site")
ap.add_argument("--no-relay", action="store_true", help="بلا دالة الإرسال التلقائي (يبقى زر فتح البريد فقط)")
a = ap.parse_args()
out = os.path.abspath(a.out)
if os.path.exists(out):
    shutil.rmtree(out)
shutil.copytree(SRC, os.path.join(out, "s"))
cfg = {"base": "", "mail_only": True, "mailbox": a.mailbox, "org": a.org, "email_domain": a.domain, "relay": "" if (a.no_relay or not a.mailbox) else "/.netlify/functions/attend"}
open(os.path.join(out, "s", "config.js"), "w", encoding="utf-8").write("window.APP_CONFIG = %s;\n" % json.dumps(cfg, ensure_ascii=False))
open(os.path.join(out, "index.html"), "w", encoding="utf-8").write('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=/s/"><a href="/s/">/s/</a>')
open(os.path.join(out, "netlify.toml"), "w", encoding="utf-8").write('[build]\n  publish = "."\n  functions = "netlify/functions"\n[functions]\n  node_bundler = "esbuild"\n')
if not a.no_relay:
    os.makedirs(os.path.join(out, "netlify", "functions"))
    open(os.path.join(out, "netlify", "functions", "attend.js"), "w", encoding="utf-8").write(FUNC)
print("تم بناء الموقع في:", out)
print("الرابط الذي يضعه الباركود: https://<موقعك>  ← ضعه في «إعدادات الجامعة الذكية» (رابط الصفحة العام)")
print("رابط الإرسال التلقائي: https://<موقعك>/.netlify/functions/attend")
