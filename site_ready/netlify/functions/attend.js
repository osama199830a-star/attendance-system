// دالة Netlify: تستقبل دفعة الحضور من هاتف الطالب (من أي شبكة) وتحوّلها إلى جيميل الدكتور. لا تحتفظ بأي بيانات.
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
