/* تطبيق الطالب — يعمل بدون إنترنت.
   - الباركود على شاشة الدكتور هو رابط يفتحه الطالب بكاميرا الهاتف (أو يمسحه من داخل التطبيق).
   - الاسم يُختار مرة واحدة ويُربط بالجهاز.
   - إذا لا يوجد إنترنت يُحفظ الحضور على الهاتف ويُرسل تلقائياً عند عودة الاتصال. */
(() => {
"use strict";
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const AR_MAP = { "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ئ": "ي", "ة": "ه", "ؤ": "و", "ـ": "" };
// نفس دالة التوحيد المستخدمة في الخادم
const norm = s => String(s || "").normalize("NFKC").replace(/[ً-ٰٟ]/g, "").replace(/[أإآٱىئةؤـ]/g, c => AR_MAP[c]).toLowerCase().replace(/\s+/g, " ").trim();
const rid = () => (crypto.randomUUID ? crypto.randomUUID() : "d" + Math.random().toString(36).slice(2) + Date.now().toString(36));

// ───── تخزين محلي (IndexedDB + نسخة احتياطية في localStorage) ─────
const kv = (() => {
  let dbp;
  const open = () => dbp || (dbp = new Promise((res, rej) => {
    try { const r = indexedDB.open("att", 1); r.onupgradeneeded = () => r.result.createObjectStore("kv"); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); } catch (e) { rej(e); }
  }));
  const tx = async (mode, fn) => { const d = await open(); return new Promise((res, rej) => { const t = d.transaction("kv", mode); const o = fn(t.objectStore("kv")); t.oncomplete = () => res(o && o.result); t.onerror = () => rej(t.error); }); };
  return {
    async get(k, def) {
      try { const v = await tx("readonly", s => s.get(k)); if (v !== undefined) return v; } catch (e) {}
      try { const x = localStorage.getItem("att_" + k); if (x != null) return JSON.parse(x); } catch (e) {}
      return def;
    },
    async set(k, v) {
      try { await tx("readwrite", s => s.put(v, k)); } catch (e) {}
      try { localStorage.setItem("att_" + k, JSON.stringify(v)); } catch (e) {}
    },
  };
})();

const S = { device: null, me: null, meOk: false, roster: null, offset: null, lateHours: 48, queue: [], hist: [], base: "", org: "", grace: 10, tok: null, res: null, online: navigator.onLine, pick: null, grp: "", coh: null, maxWall: 0, swReady: false };
const save = () => Promise.all([kv.set("device", S.device), kv.set("me", S.me), kv.set("meOk", S.meOk), kv.set("queue", S.queue), kv.set("hist", S.hist.slice(0, 30)), kv.set("offset", S.offset), kv.set("maxWall", S.maxWall), kv.set("base", S.base)]);
const apiBase = () => (S.base || (window.APP_CONFIG && window.APP_CONFIG.base) || location.origin).replace(/\/$/, "");

async function api(path, body, timeout = 8000) {
  const ctl = new AbortController(); const to = setTimeout(() => ctl.abort(), timeout);
  const t0 = Date.now();
  try {
    const r = await fetch(apiBase() + path, { method: body ? "POST" : "GET", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined, signal: ctl.signal, cache: "no-store" });
    if (!r.ok) { let body = null; try { body = await r.json(); } catch (_) {} const er = new Error("http" + r.status); er.status = r.status; er.body = body; throw er; }
    const j = await r.json();
    if (typeof j.t === "number") { const t1 = Date.now(); S.offset = j.t * 1000 - (t1 - (t1 - t0) / 2); S.maxWall = Date.now(); }  // فرق ساعة الجهاز عن الخادم
    setNet(true);
    return j;
  } catch (e) { setNet(!!e.status); throw e; } finally { clearTimeout(to); }
}
const isNetErr = e => !(e && e.status);   // لا حالة HTTP = لا اتصال/مهلة (وليس ردّاً من الخادم)

// ───── اكتشاف الخادم تلقائياً ─────
// يفحص عنواناً: هل هو خادم الحضور فعلاً؟ (يستعمل /api/time لأنه مفتوح لـ CORS)
async function probe(base, ms = 3000) {
  const ctl = new AbortController(); const to = setTimeout(() => ctl.abort(), ms); const t0 = Date.now();
  try {
    const r = await fetch(base.replace(/\/$/, "") + "/api/time", { cache: "no-store", signal: ctl.signal });
    if (!r.ok) return null; const j = await r.json();
    return typeof j.t === "number" ? Date.now() - t0 : null;
  } catch (e) { return null; } finally { clearTimeout(to); }
}
const appMode = () => !!(window.Capacitor || (window.APP_CONFIG && window.APP_CONFIG.base));
// عناوين محتملة للخادم انطلاقاً من رابط الباركود (https على 5443 بشهادة ذاتية يرفضها التطبيق → نجرّب http على 5000 أولاً)
function serverCandidates(url) {
  let u; try { u = new URL(url); } catch (e) { return []; }
  const out = [];
  if (u.protocol === "https:" && (u.port === "5443")) out.push("http://" + u.hostname + ":5000");
  out.push(u.origin);
  return [...new Set(out)];
}
let adopting = false;
// إذا تغيّر عنوان جهاز الدكتور (IP) فالباركود نفسه يحمل العنوان الجديد: نتعلّمه ونحفظه دون تدخل أحد
async function adoptServerFromScan(raw) {
  if (adopting || !appMode()) return; const i = String(raw).indexOf("#"); if (i < 0) return;
  const head = String(raw).slice(0, i); if (!/^https?:\/\//i.test(head)) return;
  adopting = true;
  try {
    if (await probe(apiBase(), 2500) != null) return;          // العنوان الحالي يعمل → لا تغيير
    for (const c of serverCandidates(head)) {
      if (c === apiBase()) continue;
      if (await probe(c, 3000) != null) { S.base = c; await save(); setNet(true); await refreshRoster(); render(); flush(); return; }
    }
  } finally { adopting = false; }
}
function setNet(on) { S.online = on; paintNet(); }
function paintNet() { const n = $("#net"); if (!n) return; const any = S.online || S.internet; n.className = "net" + (any ? "" : " off"); n.title = S.online ? "متصل بخادم الحضور" : S.internet ? "متصل بالإنترنت (يُرسل الحضور بالإيميل)" : "لا توجد شبكة"; }
// فحص الإنترنت الحقيقي (أي شبكة: واي فاي أو بيانات) — لا يعتمد على خادم الدكتور
async function checkInternet() {
  let ok = navigator.onLine;
  if (ok) { const ctl = new AbortController(); const to = setTimeout(() => ctl.abort(), 4000); try { await fetch("https://www.gstatic.com/generate_204", { mode: "no-cors", cache: "no-store", signal: ctl.signal }); } catch (e) { ok = false; } finally { clearTimeout(to); } }
  const was = S.internet; S.internet = ok; paintNet();
  if (ok && !was) deliverPending();
  return ok;
}
const mailOnly = () => !!(window.APP_CONFIG && window.APP_CONFIG.mail_only);
const relayUrl = () => (window.APP_CONFIG && window.APP_CONFIG.relay) || S.relay || "";
const qitem = x => ({ id: x.id, code: x.code, t: x.t, i: x.i, sig: x.sig, student: x.student || "", sid: x.sid, age: x.age, elapsed: x.elapsed, ts: x.ts, unsynced: x.unsynced, dsig: x.dsig, pub: x.pub });
const mailPayload = items => btoa(unescape(encodeURIComponent(JSON.stringify({ v: 1, device_id: S.device, items: items.map(qitem) }))));
// إرسال تلقائي (بدون أي نقرة إضافية) عبر رابط الترحيل الذي يحوّل الدفعة إلى جيميل الدكتور
async function relaySend(items) {
  const u = relayUrl(); if (!u || !items.length) return false;
  const ctl = new AbortController(); const to = setTimeout(() => ctl.abort(), 15000);
  try {
    const r = await fetch(u, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ payload: mailPayload(items) }), signal: ctl.signal });
    if (!r.ok) return false; const j = await r.json().catch(() => ({})); return j.ok !== false;
  } catch (e) { return false; } finally { clearTimeout(to); }
}
function markSent(items) {
  const ids = new Set(items.map(x => x.id));
  for (const it of items) { S.hist = S.hist.filter(h => !(h.ts === it.ts && h.status === "queued")); addHist(it, { status: "sent" }); }
  S.queue = S.queue.filter(x => !ids.has(x.id));
}
async function deliverPending() {   // أول ما تتوفر شبكة: أرسل ما هو محفوظ
  if (!S.queue.length) return;
  if (!mailOnly() && S.online) return flush();
  if (!(S.internet || navigator.onLine)) return;
  if (relayUrl()) { while (S.queue.length) { const batch = S.queue.slice(0, 3); if (!(await relaySend(batch))) break; markSent(batch); } await save(); render(); }
  if (S.queue.length && !mailOnly()) flush();
}

// ───── الباركود ─────
function parseFrag(text) {
  const i = String(text).indexOf("#"); const f = (i >= 0 ? text.slice(i + 1) : text).trim();
  const m = /^AT1\.([A-Z0-9]{4,10})\.(\d{9,11})\.(\d{1,3})\.([0-9a-f]{12})$/.exec(f);
  return m ? { code: m[1], t: +m[2], i: +m[3], sig: m[4] } : null;
}
function takeToken(tok) {
  if (!tok) return false;
  if (S.tok && S.tok.sig === tok.sig && S.tok.t === tok.t) return true;
  S.tok = Object.assign(tok, { wall: Date.now(), perf: performance.now() }); S.res = null; render(); return true;
}
// حماية: إذا رجّع الطالب ساعة هاتفه للخلف ليُظهر باركوداً قديماً كأنه جديد (وهو بلا إنترنت)
const clockBad = () => { const n = Date.now(); if (n > S.maxWall) S.maxWall = n; return n < S.maxWall - 30000; };
const synced = () => S.offset != null;
// عمر الباركود لحظة المسح (ثوانٍ). إن لم يزامن الهاتف ساعته بعد نفترض أنها صحيحة (فرق 0) ثم يصحّح الخادم العمر بدقة عند الإرسال
const tokAge = () => !S.tok ? null : (S.tok.wall + (S.offset || 0)) / 1000 - S.tok.t;
// حالة الباركود: fresh (سليم) | warn (الوقت غير متأكَّد منه محلياً ولن يُرفض الآن) | old (قديم مؤكَّد)
const tokState = () => {
  if (!S.tok) return null; if (clockBad()) return "clock"; const a = tokAge(), lim = S.tok.i + S.grace + 2;
  if (synced()) return (a <= lim && a >= -8) ? "fresh" : "old";
  return (a <= lim + 12 && a >= -20) ? "fresh" : "warn";
};

// ───── التسجيل ─────
async function register() {
  const tk = S.tok; if (!tk || !S.me) return;
  if (clockBad()) return showRes("bad", "ساعة الهاتف غير صحيحة (رُجّعت للخلف). فعّل «الوقت التلقائي» في الإعدادات واتصل بالإنترنت مرة واحدة ثم أعد المحاولة.");
  const age = tokAge(); const isSynced = synced();
  const elapsed = (performance.now() - tk.perf) / 1000;
  if (elapsed > 90 || (isSynced && (age > tk.i + S.grace + 2 || age < -8))) { S.tok = null; return showRes("bad", "انتهى مفعول هذا الباركود. وجّه الكاميرا نحو الشاشة وامسحه من جديد."); }
  const item = { id: rid(), code: tk.code, t: tk.t, i: tk.i, sig: tk.sig, student: S.me.u || "", sid: S.me.sid, age: +age.toFixed(2), elapsed: +elapsed.toFixed(2), queued: false, ts: Date.now(), wall: tk.wall, unsynced: !isSynced };
  $("#go") && ($("#go").disabled = true);
  await signItem(item);
  // زر واحد: يحفظ الحضور ثم يرسله بأفضل طريقة متاحة (خادم الدكتور ← إرسال تلقائي بالإيميل ← فتح البريد)
  if (!mailOnly() && (S.online || !S.internet)) {
    try {
      const r = await api("/api/student/submit", { device_id: S.device, items: [Object.assign({}, item, { sent_at: Date.now() })] }, 10000);
      S.tok = null; S.meOk = true; handleResult(item, r.results[0]); await save(); render(); return;
    } catch (e) {
      if (!isNetErr(e)) { S.tok = null; await save(); return showRes("bad", "❌ " + ((e.body && (e.body.error || e.body.message)) || "رفض الخادم الطلب (" + e.status + ")")); }
    }
  }
  item.queued = true; S.queue.push(item); S.tok = null; addHist(item, { status: "queued" }); await save();
  if (S.internet || navigator.onLine) {
    if (await relaySend([item])) { markSent([item]); await save(); return showRes("ok", "✅ أُرسل حضورك بالإيميل. يُسجَّل في الإكسل عند معالجة الدكتور للبريد."); }
    if (S.mailbox) { item.mailed = Date.now(); showRes("wait", "✓ حُفظ حضورك. اضغط «إرسال» في رسالة البريد التي فُتحت ليُسجَّل حضورك."); await save(); return mailAttendance([item]); }
    showRes("wait", "✓ حُفظ حضورك على هاتفك وسيُرسل تلقائياً عند توفر الخادم.");
  } else showRes("wait", "✓ حُفظ حضورك على هاتفك. سيُرسل تلقائياً أول ما تتوفر أي شبكة.");
  await save(); render();
}
function handleResult(item, r) {
  addHist(item, r);
  if (r.status === "ok") showRes("ok", "✅ تم تسجيل حضورك بنجاح");
  else if (r.status === "duplicate") showRes("ok", "✅ حضورك مسجّل مسبقاً في هذه المحاضرة");
  else if (r.status === "pending") showRes("ok", "✅ تم الإرسال — بانتظار التحقق في السحابة");
  else if (r.status === "guest_pending") { showRes("wait", "أنت مسجل في مجموعة أخرى. تم إرسال طلبك للموافقة."); loadInbox(); }
  else if (r.status === "guest_rejected") showRes("bad", "❌ رُفض طلب حضورك كضيف في هذه المحاضرة");
  else showRes("bad", "❌ " + (r.message || "تم رفض التسجيل"));
}
function addHist(it, r) { S.hist.unshift({ ts: it.ts, code: it.code, status: r.status, msg: r.message || "" }); S.hist = S.hist.slice(0, 30); }
function showRes(kind, text) { S.res = { kind, text }; render(); }

let flushing = false, flushFails = 0, flushTimer = null;
let binding = false;
// الربط الذي تأخر لعدم وجود اتصال: يكتمل تلقائياً أول ما يصل الهاتف للخادم
async function ensureBound() {
  if (mailOnly() || binding || !S.me || S.meOk || !S.me.u) return; binding = true;
  try {
    const r = await api("/api/student/bind", { device_id: S.device, student: S.me.u, pub: await myPub() }, 8000);
    if (r.ok) { S.meOk = true; await save(); render(); }
    else { const m = r.message || "تعذّر ربط الاسم"; S.me = null; S.meOk = false; await save(); await refreshRoster(); render(); showRes("bad", m + " — اختر اسمك الصحيح أو اطلب من الدكتور «فك الربط»."); }
  } catch (e) { /* لا اتصال بعد — نعيد المحاولة لاحقاً */ } finally { binding = false; }
}
async function flush() {
  if (!mailOnly()) { ensureBound(); upgradeLogin(); }
  if (mailOnly() || (!S.online && S.internet && relayUrl())) return deliverPending();
  // طلب أقدم من 9 أيام لا يمكن قبوله أبداً (أقصى مهلة 7 أيام بعد المحاضرة) فلا نُبقيه
  const cutoff = Date.now() - 9 * 24 * 3600 * 1000, dead = S.queue.filter(x => x.ts < cutoff);
  if (dead.length) { S.queue = S.queue.filter(x => x.ts >= cutoff); for (const it of dead) { S.hist = S.hist.filter(h => !(h.ts === it.ts && h.status === "queued")); addHist(it, { status: "rejected", message: "انتهت مهلة الإرسال" }); } save(); render(); }
  if (flushing || !S.queue.length) return; flushing = true;
  try {
    while (S.queue.length) {            // دفعات من 20 حتى يفرغ الطابور
      const r = await api("/api/student/submit", { device_id: S.device, items: S.queue.slice(0, 20).map(x => Object.assign({}, x, { sent_at: Date.now() })) }, 25000);
      for (const res of r.results) { const it = S.queue.find(x => x.id === res.id); if (it) { S.queue = S.queue.filter(x => x.id !== res.id); S.hist = S.hist.filter(h => !(h.ts === it.ts && h.status === "queued")); addHist(it, res); } }
      await save(); render(); flushFails = 0;
    }
  } catch (e) {
    if (e && e.status >= 400 && e.status < 500 && e.status !== 408 && e.status !== 429) {   // طلب مرفوض نهائياً: لا نُعيده إلى ما لا نهاية
      const dead = S.queue.splice(0, 20); for (const it of dead) { S.hist = S.hist.filter(h => !(h.ts === it.ts && h.status === "queued")); addHist(it, { status: "rejected", message: "رُفض من الخادم" }); }
      await save(); render(); flushing = false; if (S.queue.length) flush(); return;
    }
    flushFails = Math.min(flushFails + 1, 6);   // إعادة محاولة متدرجة: 5ث، 10، 20 … حتى دقيقتين
    clearTimeout(flushTimer); flushTimer = setTimeout(flush, Math.min(120000, 5000 * 2 ** (flushFails - 1)));
  } finally { flushing = false; }
}

// ───── مفتاح تشفير الجهاز (ECDSA P-256) + البريد الجامعي + صندوق الطلبات ─────
// المفتاح الخاص غير قابل للتصدير ويبقى في IndexedDB (في تطبيق الأندرويد يمكن نقله لاحقاً إلى Keystore عبر إضافة أصلية)
let _dk = null;
async function devKey() {
  if (_dk) return _dk;
  try {
    if (!(window.crypto && crypto.subtle)) return null;
    let k = await kv.get("dkey", null);
    if (!k || !k.priv) {
      const kp = await crypto.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, false, ["sign"]);
      const jwk = await crypto.subtle.exportKey("jwk", kp.publicKey);
      k = { priv: kp.privateKey, pub: { kty: jwk.kty, crv: jwk.crv, x: jwk.x, y: jwk.y } };
      try { await kv.set("dkey", k); } catch (e) {}
    }
    _dk = k; return k;
  } catch (e) { return null; }
}
const myPub = async () => { const k = await devKey(); return k ? k.pub : undefined; };
async function signItem(item) {
  const k = await devKey(); if (!k) return item;
  try {
    const msg = new TextEncoder().encode([item.code, item.t, item.i, item.student, S.device].join("|"));
    const sig = new Uint8Array(await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, k.priv, msg));
    item.dsig = btoa(String.fromCharCode(...sig)); item.pub = k.pub;
  } catch (e) {}
  return item;
}
// دخول محلي (لا يحتاج خادماً): يُحفظ الرقم على الهاتف ويتحقق منه جهاز الدكتور عند معالجة البريد
async function localLogin(em, out) {
  let e = em.toLowerCase().replace(/\s/g, ""); if (!e.includes("@")) e += "@" + ((window.APP_CONFIG && window.APP_CONFIG.email_domain) || S.domain || "uoa.edu.iq");
  if (!/^[^@]+@[^@]+\.[a-z]{2,}$/.test(e)) { out.textContent = "اكتب رقمك الجامعي أو بريدك الجامعي الكامل"; return; }
  S.me = { u: "", n: e.split("@")[0], g: "", d: "", k: "", s: 0, sid: e }; S.meOk = true; await save(); render();
}
// إن دخل الطالب محلياً ثم وصل للخادم لاحقاً: نكمل التحقق وربط الجهاز وجلب القسم والمرحلة تلقائياً
async function upgradeLogin() {
  if (mailOnly() || !S.me || S.me.u || !S.me.sid || !S.online) return;
  try {
    const r = await api("/api/student/email-login", { email: S.me.sid, device_id: S.device, pub: await myPub() }, 8000);
    if (r.ok) { S.me = Object.assign({}, r.student, { sid: S.me.sid }); S.meOk = true; await save(); render(); }
  } catch (e) {}
}
async function emailLogin() {
  const em = ($("#em") && $("#em").value || "").trim(); const out = $("#emmsg"); if (!em) return;
  if (mailOnly()) return localLogin(em, out);
  out.textContent = "…";
  try {
    const r = await api("/api/student/email-login", { email: em, device_id: S.device, pub: await myPub() }, 10000);
    if (r.ok) { S.me = r.student; S.meOk = true; await save(); render(); return; }
    out.innerHTML = esc(r.message || "تعذّر التسجيل");
    if (r.can_request_change) { S.chgEmail = em; out.innerHTML += `<div style="margin-top:8px"><input id="chgr" type="text" placeholder="سبب تغيير الجهاز (فقدان / هاتف جديد)"><button id="chgsend" class="sec" style="margin-top:6px">إرسال طلب تغيير الجهاز</button></div>`; $("#chgsend").onclick = sendChange; }
  } catch (e) {
    if (isNetErr(e)) return localLogin(em, out);    // أي شبكة: لا يتوقف الدخول على شبكة الدكتور
    out.textContent = (e.body && e.body.error) || "تعذّر تسجيل الدخول";
  }
}
async function sendChange() {
  const out = $("#emmsg"); const reason = ($("#chgr").value || "").trim(); if (!reason) { out.textContent = "اكتب سبب التغيير"; return; }
  try { const r = await api("/api/student/device-request", { email: S.chgEmail, device_id: S.device, reason, pub: await myPub() }, 10000); out.textContent = r.message || "تم إرسال الطلب"; loadInbox(); }
  catch (e) { out.textContent = (e.body && e.body.error) || "تعذّر إرسال الطلب"; }
}
const ST_AR = { pending: "قيد الانتظار", approved: "تمت الموافقة", rejected: "مرفوض" };
async function loadInbox() {
  if (mailOnly()) return;
  try { S.inbox = await api("/api/student/inbox?device=" + encodeURIComponent(S.device), null, 6000); if (!S.me && S.inbox.device_requests.some(x => x.status === "approved")) { /* الجهاز فُعّل: يسجّل الدخول بالبريد */ } render(); } catch (e) {}
}
function inboxHtml() {
  const I = S.inbox; if (!I) return "";
  const rows = [];
  for (const d of I.device_requests || []) rows.push(`<div class="row"><span>طلب تغيير الجهاز</span><span class="pill ${d.status === "approved" ? "ok" : d.status === "rejected" ? "bad" : "wait"}">${ST_AR[d.status] || d.status}</span></div>${d.note ? `<div class="small">${esc(d.note)}</div>` : ""}`);
  for (const g of I.guest_requests || []) rows.push(`<div class="row"><span>${g.kind === "manual" ? "تسجيل يدوي" : "حضور كضيف"} ${esc(g.course || "")}</span><span class="pill ${g.status === "approved" ? "ok" : g.status === "rejected" ? "bad" : "wait"}">${ST_AR[g.status] || g.status}</span></div>${g.note ? `<div class="small">${esc(g.note)}</div>` : ""}`);
  for (const n of (I.notifications || []).slice(0, 5)) rows.push(`<div class="small">🔔 ${esc(n.title)}</div>`);
  return rows.length ? `<div class="card hist"><h2>طلباتي وإشعاراتي</h2>${rows.join("")}</div>` : "";
}

// إرسال الحضور المحفوظ بالإيميل (يفتح تطبيق البريد برسالة جاهزة؛ الطالب يضغط «إرسال» فقط). الخادم لا يثق بالمرسل بل بتواقيع الباركود والجهاز.
function mailAttendance(list) {
  const raw = mailPayload((Array.isArray(list) ? list : S.queue.slice(0, 3)));
  const body = "لا تعدّل هذه الرسالة وأرسلها كما هي.\n\nATT:" + raw + ":END";
  location.href = "mailto:" + encodeURIComponent(S.mailbox) + "?subject=" + encodeURIComponent("ATT-STU") + "&body=" + encodeURIComponent(body);
}

// ───── قائمة الأسماء والبحث ─────
const syncTime = () => api("/api/time", null, 6000).catch(() => {});   // يضبط فرق الساعة (S.offset) لحساب عمر الباركود أوفلاين
async function refreshRoster() {
  if (mailOnly()) return;
  syncTime();
  try {
    const r = await api("/api/student/roster");
    S.roster = { students: r.students.map(s => Object.assign(s, { nn: norm(s.n) })), org_tree: r.org_tree || null, at: Date.now() };
    S.org = r.org || ""; S.loginMode = r.login_mode || "email"; await kv.set("loginMode", S.loginMode); S.mailbox = r.mailbox || S.mailbox || ""; await kv.set("mailbox", S.mailbox); S.relay = r.relay || S.relay || ""; await kv.set("relay", S.relay); if (r.email_domain) { S.domain = r.email_domain; await kv.set("domain", S.domain); } S.grace = r.grace || 10; S.lateHours = r.late_hours || S.lateHours;
    await kv.set("roster", S.roster); await kv.set("org", S.org); await kv.set("grace", S.grace); await kv.set("late", S.lateHours);
    if (!S.me) { try { const m = await api("/api/student/me?device=" + encodeURIComponent(S.device)); if (m.student) { S.me = m.student; S.meOk = true; } } catch (e) {} }
    await save(); return true;
  } catch (e) { return false; }
}
// مطابقة موضعية: كل كلمة مكتوبة تطابق بداية الكلمة المقابلة في الاسم. الكلمات السابقة للأخيرة تُطابَق كاملة.
function matches(s, q) {
  const qt = q.split(" "); const nt = s.nn.split(" ");
  for (let i = 0; i < qt.length; i++) {
    if (qt[i] === "") continue;
    if (!nt[i]) return false;
    if (i < qt.length - 1 ? nt[i] !== qt[i] : !nt[i].startsWith(qt[i])) return false;
  }
  return true;
}
function hl(name, q) {   // تمييز الجزء المطابق
  const qt = q.split(" ").filter(Boolean); if (!qt.length) return esc(name);
  const words = name.split(" ");
  return words.map((w, i) => { const n = norm(w); const t = qt[i]; if (t && n.startsWith(t)) { let k = 0, c = 0; while (k < w.length && c < t.length) { if (norm(w[k]) !== "") c += norm(w[k]).length; k++; } return "<mark>" + esc(w.slice(0, k)) + "</mark>" + esc(w.slice(k)); } return esc(w); }).join(" ");
}
// القائمة حسب (الكلية ← القسم ← المرحلة) التي يختارها الطالب. null = لم يختر بعد.
function hasOrg() { const o = S.roster && S.roster.org_tree; return !!(o && o.depts && o.depts.length); }
function loadCoh() { try { return JSON.parse(localStorage.getItem("att_coh") || "{}"); } catch (e) { return {}; } }
function saveCoh() { try { localStorage.setItem("att_coh", JSON.stringify(S.coh)); } catch (e) { } }
function cohortList() {
  const R = S.roster; if (!hasOrg()) return R.students;
  const c = S.coh || {}; if (!c.d || !c.s) return null;
  return R.students.filter(x => x.d === c.d && String(x.s) === String(c.s));
}
function results(qraw) {
  const q = norm(qraw).replace(/^\s+/, "") + (/\s$/.test(qraw) ? " " : "");
  const base = cohortList(); if (base === null) return { list: [], more: 0, q: "", empty: true, needCoh: true };
  const all = S.grp ? base.filter(s => (s.g || "—") === S.grp) : base;
  if (!q.trim()) return S.grp ? { list: all.slice(0, 60), more: Math.max(0, all.length - 60), q: "" } : { list: [], more: 0, q: "", empty: true };
  let list = all.filter(s => matches(s, q));
  let fb = false;
  if (!list.length) { const toks = norm(qraw).split(" ").filter(Boolean); list = all.filter(s => toks.every(t => s.nn.includes(t))); fb = true; }
  return { list: list.slice(0, 60), more: Math.max(0, list.length - 60), q: fb ? "" : q, fb };
}
function drawResults() {
  const box = $("#res"); if (!box) return;
  const r = results($("#q").value);
  box.innerHTML = r.list.length ? r.list.map(s => `<div class="item${s.b ? " dis" : ""}" data-u="${s.u}"><span><b>${hl(s.n, r.q)}</b>${s.b ? '<br><span class="small">مسجّل على جهاز آخر</span>' : ""}</span><span class="badge">${esc(s.g || "—")}</span></div>`).join("") + (r.more ? `<div class="item dis"><span class="small">… و${r.more} نتيجة أخرى، أكمل الكتابة لتضييق البحث</span></div>` : "")
    : (r.needCoh ? '<div class="item dis"><span>اختر كليتك وقسمك ومرحلتك أولاً</span></div>' : r.empty ? '<div class="item dis"><span>اكتب اسمك في خانة البحث أو اختر كروبك</span></div>' : '<div class="item dis"><span>لا توجد نتيجة. تأكد من الإملاء أو راجع المسؤول.</span></div>');
}

async function choose(u) {
  const st = S.roster.students.find(s => s.u === u); if (!st || st.b) return;
  S.pick = st; render();
}
async function confirmPick() {
  const st = S.pick; if (!st) return;
  S.me = { u: st.u, n: st.n, g: st.g }; S.meOk = false; S.pick = null;
  try {
    const r = await api("/api/student/bind", { device_id: S.device, student: st.u, pub: await myPub() });
    if (!r.ok) { S.me = null; await save(); await refreshRoster(); render(); return showRes("bad", r.message || "تعذّر ربط الاسم"); }
    S.meOk = true;
  } catch (e) {
    if (!isNetErr(e)) { S.me = null; await save(); await refreshRoster(); render(); return showRes("bad", (e.body && (e.body.error || e.body.message)) || "تعذّر ربط الاسم"); }
    /* بدون إنترنت: يُربط عند أول إرسال */
  }
  await save(); render();
}

// ───── المسح من داخل التطبيق ─────
let scanning = false, stopScanFn = null;
const _cv = document.createElement("canvas"), _cx = _cv.getContext("2d", { willReadFrequently: true });
// فكّ QR بمكتبة jsQR (أو القارئ المدمج) — تعمل على كل المتصفحات وبلا إنترنت
function jsqrDecode(src, sw, sh, maxW, both) {
  if (!window.jsQR || !sw || !sh) return null;
  const w = Math.min(maxW, sw), h = Math.max(1, Math.round(w * sh / sw)); _cv.width = w; _cv.height = h;
  _cx.drawImage(src, 0, 0, w, h);
  const d = _cx.getImageData(0, 0, w, h);
  const q = window.jsQR(d.data, w, h, { inversionAttempts: both ? "attemptBoth" : "dontInvert" });
  return q ? q.data : null;
}
async function decodePhoto(file) {
  let bmp;
  try { bmp = await createImageBitmap(file); } catch (e) { bmp = await new Promise((res, rej) => { const im = new Image(); im.onload = () => res(im); im.onerror = rej; im.src = URL.createObjectURL(file); }); }
  const sw = bmp.width || bmp.naturalWidth, sh = bmp.height || bmp.naturalHeight;
  for (const mw of [1000, 1600, 700, 450]) { const r = jsqrDecode(bmp, sw, sh, mw, true); if (r) return r; }
  if ("BarcodeDetector" in window) { try { const r = await new BarcodeDetector({ formats: ["qr_code"] }).detect(bmp); if (r && r[0]) return r[0].rawValue; } catch (e) {} }
  return null;
}
async function onPhoto(file) {
  if (!file) return; showRes("wait", "⏳ جاري قراءة الصورة…");
  const raw = await decodePhoto(file).catch(() => null); const tk = raw && parseFrag(raw);
  if (tk) { S.res = null; takeToken(tk); adoptServerFromScan(raw); }
  else showRes("bad", "لم أستطع قراءة الباركود من الصورة. اقترب من الشاشة وصوّر الباركود كاملاً وبوضوح ثم أعد المحاولة.");
}
const camErrText = e => {
  const n = e && e.name;
  if (n === "NotAllowedError" || n === "SecurityError" || n === "PermissionDeniedError") return "لم يُسمح بالكاميرا. فعّل إذن الكاميرا من إعدادات المتصفح/التطبيق ثم أعد المحاولة، أو استعمل «🖼️ التقاط صورة للباركود».";
  if (n === "NotFoundError" || n === "OverconstrainedError") return "لم أجد كاميرا في هذا الجهاز. استعمل «🖼️ التقاط صورة للباركود».";
  if (n === "NotReadableError" || n === "AbortError") return "الكاميرا مشغولة بتطبيق آخر. أغلق التطبيقات التي تستعملها ثم أعد المحاولة.";
  return "تعذّر فتح الكاميرا: " + ((e && (e.message || e.name)) || e);
};
async function startScan() {
  const cap = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.BarcodeScanner;
  if (cap) {
    try {
      await cap.requestPermissions();
      try { const a = await cap.isGoogleBarcodeScannerModuleAvailable(); if (!a.available) await cap.installGoogleBarcodeScannerModule(); } catch (e) {}
      const r = await cap.scan({ formats: ["QR_CODE"] });
      const raw = r && r.barcodes && r.barcodes[0] && (r.barcodes[0].rawValue || r.barcodes[0].displayValue);
      if (raw && takeToken(parseFrag(raw))) { adoptServerFromScan(raw); return; } showRes("bad", "هذا ليس باركود الحضور.");
    } catch (e) { showRes("bad", "تعذّر فتح الكاميرا: " + (e.message || e)); }
    return;
  }
  if (scanning) return;
  if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia) || window.isSecureContext === false)
    return showRes("wait", "الكاميرا داخل الصفحة تحتاج اتصالاً آمناً (HTTPS). استعمل زر «🖼️ التقاط صورة للباركود» أو كاميرا الهاتف العادية وافتح الرابط.");
  const video = $("#cam"); scanning = true; let stream = null, lastErr = null;
  for (const c of [{ video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false }, { video: { facingMode: "environment" }, audio: false }, { video: true, audio: false }]) {
    try { stream = await navigator.mediaDevices.getUserMedia(c); break; } catch (e) { lastErr = e; if (e && (e.name === "NotAllowedError" || e.name === "SecurityError" || e.name === "PermissionDeniedError")) break; }
  }
  if (!stream) { scanning = false; return showRes("bad", camErrText(lastErr)); }
  video.setAttribute("playsinline", ""); video.setAttribute("webkit-playsinline", ""); video.muted = true; video.srcObject = stream; video.hidden = false;
  try { await video.play(); } catch (e) {}
  $("#scanhost").hidden = false; $("#stopscan").hidden = false; $("#scanhost").appendChild(video);
  let det = null; if ("BarcodeDetector" in window) { try { det = new BarcodeDetector({ formats: ["qr_code"] }); } catch (e) { det = null; } }
  let n = 0, detFails = 0;
  const stop = () => { scanning = false; stopScanFn = null; try { stream.getTracks().forEach(t => t.stop()); } catch (e) {} video.srcObject = null; video.hidden = true; document.body.appendChild(video); };
  stopScanFn = stop;
  $("#stopscan").onclick = () => { stop(); render(); };
  const loop = async () => {
    if (!scanning) return;
    try {
      if (video.videoWidth) {
        let raw = null;
        // BarcodeDetector موجود في أندرويد كروم لكنه قد يفشل بصمت (بدون خدمات Google) → إن فشل أو لم يلتقط نكمل بـ jsQR دائماً
        if (det) { try { const r = await det.detect(video); if (r && r[0]) raw = r[0].rawValue; } catch (e) { if (++detFails >= 3) det = null; } }
        if (!raw && (!det || (n++ % 2 === 0))) raw = jsqrDecode(video, video.videoWidth, video.videoHeight, 800, false);
        const tk = raw && parseFrag(raw);
        if (tk) { stop(); takeToken(tk); adoptServerFromScan(raw); return; }
      }
    } catch (e) {}
    setTimeout(loop, 110);
  };
  loop();
}
document.addEventListener("visibilitychange", () => { if (document.hidden && stopScanFn) { stopScanFn(); render(); } });
// مدخل الصورة خارج #app حتى لا يُهدم أثناء فتح كاميرا النظام
const photoInput = (() => { const fi = document.createElement("input"); fi.type = "file"; fi.accept = "image/*"; fi.setAttribute("capture", "environment"); fi.hidden = true; fi.onchange = () => { const f = fi.files && fi.files[0]; fi.value = ""; onPhoto(f); }; document.body.appendChild(fi); return fi; })();


// ───── اللغة: عربي / English ─────
const EN = {
  "الدخول بالبريد الجامعي": "Sign in with university email", "دخول": "Sign in", "طلباتي وإشعاراتي": "My requests & notifications", "قيد الانتظار": "Pending", "تمت الموافقة": "Approved", "مرفوض": "Rejected",
  "أنت مسجل في مجموعة أخرى. تم إرسال طلبك للموافقة.": "You belong to another group. Your request was sent for approval.", "إرسال طلب تغيير الجهاز": "Send device change request", "طلب تغيير الجهاز": "Device change request",
  "هذا الجهاز غير معتمد لحسابك": "This device is not approved for your account", "تم تسجيل حضورك بنجاح": "Your attendance was recorded", "المحاضرة مغلقة": "Lecture is closed",
  "١. ": "1. ", "٢. ": "2. ",
  "نظام الحضور بالباركود": "Barcode Attendance", "تسجيل حضور": "Check in", "📷 مسح الباركود": "📷 Scan barcode",
  "اضغط «📷 مسح الباركود» ووجّه الكاميرا نحو شاشة الدكتور (يعمل حتى بدون إنترنت أو واي فاي).": "Tap “📷 Scan barcode” and point the camera at the lecturer's screen (works even without internet or Wi-Fi).",
  "ثم اضغط «تسجيل حضور».": "Then tap “Check in”.",
  "✅ جاهز للتسجيل بدون إنترنت — يمكنك مسح الباركود بكاميرا الهاتف العادية أو من هنا": "✅ Ready to check in offline — scan with the phone's normal camera or from here",
  "⚠️ ابقَ متصلاً بالإنترنت لحظات الآن ليكتمل تجهيز الهاتف للعمل بدون إنترنت": "⚠️ Stay online for a moment so your phone can get ready to work offline",
  "👋 أهلاً بك — اختر اسمك": "👋 Welcome — choose your name",
  "تفعل هذا مرة واحدة فقط. اكتب أول حرف من اسمك وسيضيق البحث مع كل حرف: الاسم الأول ثم اسم الأب…": "You do this only once. Type the first letters of your name; the search narrows with every letter: first name, then father's name…",
  "ابحث باسمك: مثال  محمد ع": "Search your name",
  "أو اختر من القائمة المنسدلة": "Or pick from the dropdown", "— اختر اسمك —": "— Choose your name —",
  "تأكيد الاسم": "Confirm your name", "نعم، هذا اسمي": "Yes, this is me", "رجوع": "Back", "الكروب": "Group", "كروب": "Group",
  "⚠️ سيُربط هذا الجهاز بهذا الاسم ولا يمكن تغييره بعد ذلك إلا عن طريق المسؤول. لا تسجّل باسم زميلك.": "⚠️ This device will be linked to this name and can only be changed by the administrator. Do not use a classmate's name.",
  "مربوط ✓": "Linked ✓", "بانتظار الربط": "Pending link", "تم التقاط الباركود ✓": "Barcode captured ✓", "الباركود قديم ✗": "Barcode is outdated ✗", "ساعة الهاتف غير صحيحة ✗": "Phone clock is wrong ✗",
  "رمز المحاضرة": "Lecture code", "امسح الشاشة مجدداً": "scan the screen again", "آخر عملياتي": "My recent activity",
  "حاضر": "Present", "مسجّل": "Registered", "أُرسل": "Sent", "بانتظار الإنترنت": "Waiting for internet", "مرفوض": "Rejected",
  "حضور بانتظار الإرسال": "check-ins waiting to be sent", "سيُرسل تلقائياً عند توفر الإنترنت.": "They will be sent automatically when internet is available.", "إرسال الآن": "Send now",
  "⚙️ إعدادات متقدمة": "⚙️ Advanced settings", "حفظ": "Save", "إيقاف الكاميرا": "Stop camera", "🖼️ التقاط صورة للباركود": "🖼️ Take a photo of the barcode", "⏳ جاري قراءة الصورة…": "⏳ Reading the photo…", "معرّف الجهاز": "Device ID",
  "عنوان الخادم (للمسؤول/الدعم فقط)": "Server address (admin/support only)",
  "✅ تم تسجيل حضورك بنجاح": "✅ Your attendance was recorded", "✅ حضورك مسجّل مسبقاً في هذه المحاضرة": "✅ You are already marked present in this lecture",
  "✅ تم الإرسال — بانتظار التحقق في السحابة": "✅ Sent — awaiting verification in the cloud",
  "✓ حُفظ حضورك على هاتفك. الإنترنت يعمل لكن خادم الحضور لم يُجب الآن، وسيُرسل تلقائياً عند توفره.": "✓ Saved on your phone. Internet is up but the attendance server did not answer; it will be sent automatically.",
  "✓ حُفظ حضورك على هاتفك. لا يوجد إنترنت الآن، وسيُرسل تلقائياً عند توفره.": "✓ Saved on your phone. No internet now; it will be sent automatically when available.",
  "انتهى مفعول هذا الباركود. وجّه الكاميرا نحو الشاشة وامسحه من جديد.": "This barcode has expired. Point the camera at the screen and scan again.",
  "هذا ليس باركود الحضور.": "This is not an attendance barcode.", "تم رفض التسجيل": "Check-in was rejected",
  "لم تُحمَّل قائمة الأسماء بعد": "The names list hasn't been loaded yet", "لا توجد نتيجة. تأكد من الإملاء أو راجع المسؤول.": "No result. Check the spelling or contact the administrator.",
  "مسجّل على جهاز آخر": "Registered on another device", "بدون اتصال": "Offline", "الخادم غير قابل للوصول": "Server unreachable", "متصل": "Online",
  "ساعة الهاتف غير صحيحة (رُجّعت للخلف). فعّل «الوقت التلقائي» في الإعدادات واتصل بالإنترنت مرة واحدة ثم أعد المحاولة.": "Your phone's clock is wrong (set backwards). Turn on automatic time in Settings, connect to the internet once, and try again.",
  "افتح التطبيق مرة واحدة وأنت متصل بالإنترنت لمزامنة الوقت ثم أعد المحاولة.": "Open the app once while online to sync the time, then try again.",
  "لم يُسمح بالكاميرا. فعّل إذن الكاميرا من إعدادات المتصفح.": "Camera access was denied. Allow the camera in your browser settings.",
  "تعذّر فتح الكاميرا": "Could not open the camera", "تعذّر ربط الاسم": "Could not link the name",
  "باركود غير صالح": "Invalid barcode", "خارج وقت المحاضرة": "Outside lecture time", "انتهت مهلة استلام الحضور لهذه المحاضرة": "The deadline to receive attendance for this lecture has passed",
  "الباركود منتهٍ (صوّر أو أُرسل متأخراً)": "Barcode expired (photographed or sent late)", "الطالب غير موجود": "Student not found",
  "هذا الجهاز مرتبط بطالب آخر": "This device is linked to another student", "هذا الاسم مرتبط بجهاز آخر": "This name is linked to another device",
  "التسجيل غير المتصل غير مسموح": "Offline check-in is not allowed",
  "اختبار الاتصال وحفظ العنوان": "Test connection & save address", "عنوان الخادم الحالي:": "Current server address:", "⏳ جاري الاختبار…": "⏳ Testing…",
  "❌ لا يمكن الوصول إلى الخادم على هذا العنوان. تأكد أنك على نفس شبكة الدكتور وأن البرنامج شغّال.": "❌ Cannot reach the server at this address. Make sure you are on the lecturer's network and the program is running.",
  "رُفض من الخادم": "Rejected by server", "انتهت مهلة الإرسال": "Sending period expired",
  "⏳ لم يصل هاتفك للخادم بعد؛ سيُؤكَّد الربط تلقائياً عند الاتصال بشبكة الدكتور/الإنترنت، ويمكنك التسجيل الآن وسيُحفظ حضورك.": "⏳ Your phone has not reached the server yet; the link will be confirmed automatically once connected. You can register now and your attendance will be saved.",
};
const ENK = Object.keys(EN).sort((a, b) => b.length - a.length);
let LANG = "ar";
function trText(t) { let o = t; for (const k of ENK) if (o.includes(k)) o = o.split(k).join(EN[k]); return o; }
function applyLang() {
  document.documentElement.lang = LANG; document.documentElement.dir = LANG === "en" ? "ltr" : "rtl";
  const b = $("#lang"); if (b) b.textContent = LANG === "en" ? "عربي" : "EN";
  if (LANG !== "en") return;
  const w = document.createTreeWalker($("#app"), NodeFilter.SHOW_TEXT); let n;
  while ((n = w.nextNode())) { const v = n.nodeValue; if (/[؀-ۿ]/.test(v)) { const r = trText(v); if (r !== v) n.nodeValue = r; } }
  $("#app").querySelectorAll("[placeholder],[title]").forEach(e => { for (const a of ["placeholder", "title"]) { const v = e.getAttribute(a); if (v) e.setAttribute(a, trText(v)); } });
  const t = $(".title"); if (t) { const org = $("#org"); t.firstChild.nodeValue = "Barcode Attendance "; if (org) org.textContent = ""; }
}
function render() { render0(); applyLang(); }

// ───── العرض ─────
const fmtT = ts => new Date(ts).toLocaleString(LANG === "en" ? "en-GB" : "ar-IQ", { hour: "2-digit", minute: "2-digit", day: "numeric", month: "numeric" });
function render0() {
  const app = $("#app"); if (!app) return;
  $("#org").textContent = S.org ? "— " + S.org : "";
  if (scanning) return;
  const wasPick = app.dataset.mode === "pick"; app.dataset.mode = "";
  const q0 = $("#q") ? $("#q").value : "";
  if (S.me || S.loginMode === "pick") app.dataset.em = "";
  if (!S.me && S.loginMode === "email") {   // الطالب يدخل برقمه الجامعي/بريده فقط، والباقي يُؤخذ من حسابه
    app.dataset.mode = "";
    if (app.dataset.em === "1" && $("#em") && !S.res) return;       // لا نُعيد بناء الصفحة أثناء كتابته
    app.dataset.em = "1";
    app.innerHTML = `<div class="card"><h2>🎓 تسجيل الدخول</h2><p class="mut">اكتب رقمك الجامعي (أو بريدك الجامعي الكامل) ثم اضغط دخول. يُحدَّد القسم والمرحلة والكروب تلقائياً.</p>
      <input id="em" type="text" inputmode="email" dir="ltr" placeholder="1063004760" autocomplete="username" autocapitalize="off" spellcheck="false">
      <button id="emgo" class="go" style="margin-top:10px">دخول</button><div id="emmsg" class="small" style="margin-top:8px"></div></div>${inboxHtml()}`;
    $("#emgo").onclick = emailLogin; $("#em").onkeydown = e => { if (e.key === "Enter") emailLogin(); };
    return;
  }
  if (!S.roster && S.loginMode !== "email") {
    app.innerHTML = `<div class="card center"><div class="big">📶</div><h2>لم تُحمَّل قائمة الأسماء بعد</h2><p>اتصل بالإنترنت (أو بشبكة القاعة) مرة واحدة فقط لتحميل القائمة، وبعدها يعمل التطبيق بدون إنترنت.</p><button id="retry">إعادة المحاولة</button>
      <p class="small" style="margin-top:14px">عنوان الخادم الحالي:</p><input id="srv0" type="text" dir="ltr" value="${esc(apiBase())}" placeholder="http://192.168.1.10:5000"><button id="srv0go" class="sec" style="margin-top:8px">اختبار الاتصال وحفظ العنوان</button><p id="srv0msg" class="small"></p></div>`;
    $("#retry").onclick = async () => { app.innerHTML = '<div class="card center"><div class="spin"></div></div>'; await refreshRoster(); render(); };
    $("#srv0go").onclick = () => testAndSaveServer($("#srv0").value, $("#srv0msg"));
    return;
  }
  if (!S.me) {
    if (S.pick) {
      const p = S.pick;
      app.innerHTML = `<div class="card"><h2>تأكيد الاسم</h2><div class="me"><div class="avatar">${esc(p.n[0])}</div><div><div class="n">${esc(p.n)}</div><div class="g">الكروب: ${esc(p.g || "—")}</div></div></div>
        <p class="mut">⚠️ سيُربط هذا الجهاز بهذا الاسم ولا يمكن تغييره بعد ذلك إلا عن طريق المسؤول. لا تسجّل باسم زميلك.</p>
        <button id="yes" class="go">نعم، هذا اسمي</button><button id="no" class="ghost">رجوع</button></div>`;
      $("#yes").onclick = confirmPick; $("#no").onclick = () => { S.pick = null; render(); }; return;
    }
    S.coh = S.coh || loadCoh();
    const org = hasOrg() ? S.roster.org_tree : null;
    if (org) { const d = org.depts.find(x => x.u === S.coh.d); if (!d) S.coh = { c: S.coh.c && org.colleges.some(k => k.u === S.coh.c) ? S.coh.c : "", d: "", s: "" }; else if (+S.coh.s > d.s) S.coh.s = ""; }
    const base = cohortList() || [];
    const gl = [...new Set(base.map(s => s.g).filter(Boolean))].sort();
    if (S.grp && !gl.includes(S.grp)) S.grp = "";
    const cohHtml = org ? `<div class="coh"><select id="kc"><option value="">الكلية</option>${org.colleges.map(k => `<option value="${k.u}" ${k.u === S.coh.c ? "selected" : ""}>${esc(k.n)}</option>`).join("")}</select>
      <select id="kd"><option value="">القسم</option>${org.depts.filter(d => d.c === S.coh.c).map(d => `<option value="${d.u}" ${d.u === S.coh.d ? "selected" : ""}>${esc(d.n)}</option>`).join("")}</select>
      <select id="ks"><option value="">المرحلة</option>${(() => { const d = org.depts.find(x => x.u === S.coh.d); return d ? Array.from({ length: d.s }, (_, i) => `<option value="${i + 1}" ${String(i + 1) === String(S.coh.s) ? "selected" : ""}>المرحلة ${i + 1}</option>`).join("") : ""; })()}</select></div>` : "";
    const glSig = gl.join("|") + "#" + (org ? JSON.stringify(S.coh) + "#" + org.colleges.length + "." + org.depts.length : "");
    // تحديث القائمة بالخلفية لا يُعيد بناء الصفحة أثناء كتابة الطالب (كان يُغلق لوحة المفاتيح ويُفقد التركيز)
    if (wasPick && app.dataset.gl === glSig && $("#q") && $("#res") && !S.res) { app.dataset.mode = "pick"; drawResults(); return; }
    app.dataset.mode = "pick"; app.dataset.gl = glSig;
    app.innerHTML = `<div class="card"><h2>👋 أهلاً بك — اختر اسمك</h2>${cohHtml}
      <input id="q" type="search" placeholder="بحث بالاسم" autocomplete="off" autocapitalize="off" spellcheck="false">
      <div class="grps" id="grps">${gl.map(g => `<button type="button" class="gbtn${S.grp === g ? " on" : ""}" data-g="${esc(g)}">${esc(g)}</button>`).join("")}</div>
      <div class="list" id="res"></div>${S.res ? `<div class="res ${S.res.kind}">${esc(S.res.text)}</div>` : ""}</div>
      <div class="card"><h2>🎓 الدخول بالبريد الجامعي</h2><input id="em" type="email" dir="ltr" placeholder="student@university.edu.iq" autocomplete="email"><button id="emgo" class="go" style="margin-top:8px">دخول</button><div id="emmsg" class="small" style="margin-top:6px"></div></div>${inboxHtml()}`;
    $("#emgo").onclick = emailLogin;
    const q = $("#q"); q.value = q0; q.oninput = drawResults; drawResults();
    if (org) { const sv = () => { saveCoh(); S.grp = ""; render(); };
      $("#kc").onchange = e => { S.coh = { c: e.target.value, d: "", s: "" }; sv(); }; $("#kd").onchange = e => { S.coh.d = e.target.value; S.coh.s = ""; sv(); }; $("#ks").onchange = e => { S.coh.s = e.target.value; sv(); }; }
    $("#grps").onclick = e => { const b = e.target.closest(".gbtn"); if (!b) return; S.grp = S.grp === b.dataset.g ? "" : b.dataset.g; document.querySelectorAll(".gbtn").forEach(x => x.classList.toggle("on", x.dataset.g === S.grp)); drawResults(); };
    $("#res").onclick = e => { const it = e.target.closest(".item[data-u]"); if (it) choose(it.dataset.u); };
    return;
  }
  const tst = tokState(), fresh = tst === "fresh" || tst === "warn", bad = tst === "old" || tst === "clock";
  const hist = S.hist.slice(0, 8).map(h => `<div class="row"><span>${fmtT(h.ts)} · ${esc(h.code)}</span><span class="pill ${h.status === "ok" || h.status === "duplicate" || h.status === "pending" || h.status === "sent" ? "ok" : h.status === "queued" ? "wait" : "bad"}">${h.status === "ok" ? "حاضر" : h.status === "duplicate" ? "مسجّل" : h.status === "pending" || h.status === "sent" ? "أُرسل" : h.status === "queued" ? "بانتظار الإنترنت" : esc(h.msg || "مرفوض")}</span></div>`).join("");
  app.innerHTML = `
    <div class="card"><div class="me"><div class="avatar">${esc(S.me.n[0])}</div><div style="flex:1"><div class="n">${esc(S.me.n)}</div><div class="g">${esc([S.me.k, S.me.d, S.me.s ? "المرحلة " + S.me.s : "", S.me.g ? "الكروب " + S.me.g : ""].filter(Boolean).join(" • ") || "—")}</div></div><span class="pill ${S.meOk ? "ok" : "wait"}">${S.meOk ? "مربوط ✓" : "بانتظار الربط"}</span>${S.meOk ? "" : `<div class="small" style="flex-basis:100%;margin-top:6px">⏳ لم يصل هاتفك للخادم بعد؛ سيُؤكَّد الربط تلقائياً عند الاتصال بشبكة الدكتور/الإنترنت، ويمكنك التسجيل الآن وسيُحفظ حضورك.</div>`}</div></div>
    <div class="card">
      ${S.tok ? `<div class="tok ${bad ? "old" : ""}"><span class="dot"></span><div><b>${tst === "clock" ? "ساعة الهاتف غير صحيحة ✗" : tst === "old" ? "الباركود قديم ✗" : "تم التقاط الباركود ✓"}</b><div class="small">رمز المحاضرة: ${esc(S.tok.code)}${tst === "old" ? " — امسح الشاشة مجدداً" : ""}</div>${tst === "clock" ? `<div class="small">رُجّعت ساعة الهاتف للخلف. فعّل «الوقت التلقائي» في إعدادات الهاتف، واتصل بالإنترنت مرة واحدة، ثم امسح الباركود من جديد.</div>` : ""}${tst === "warn" ? `<div class="small">⚠️ هاتفك لم يتصل بالخادم بعد فلا يمكن التأكد من الوقت الآن. اضغط «تسجيل حضور» فيُحفظ ويتحقق الخادم من حداثة الباركود عند الاتصال. إن كان وقت هاتفك مختلفاً فعّل «الوقت التلقائي».</div>` : ""}</div></div>`
        : `<p>١. اضغط «📷 مسح الباركود» ووجّه الكاميرا نحو شاشة الدكتور (يعمل حتى بدون إنترنت أو واي فاي).<br>٢. ثم اضغط «تسجيل حضور».</p>`}
      <p class="small ${(S.swReady || window.Capacitor) && S.roster ? "okline" : "warnline"}">${(S.swReady || window.Capacitor) && S.roster ? "✅ جاهز للتسجيل بدون إنترنت — يمكنك مسح الباركود بكاميرا الهاتف العادية أو من هنا" : (window.isSecureContext === false ? "ℹ️ يعمل الحضور بدون إنترنت طالما بقيت هذه الصفحة مفتوحة (استعمل «🖼️ التقاط صورة للباركود»)، ويُحفظ على هاتفك ويُرسل تلقائياً عند الاتصال." : "⚠️ ابقَ متصلاً بالإنترنت لحظات الآن ليكتمل تجهيز الهاتف للعمل بدون إنترنت")}</p>
      <button id="go" class="${fresh ? "go" : "sec"}" ${fresh ? "" : "disabled"}>تسجيل حضور</button>
      ${S.res ? `<div class="res ${S.res.kind}">${esc(S.res.text)}</div>` : ""}
      <div style="height:8px"></div><button id="scan" class="go">📷 مسح الباركود</button><button id="photobtn" class="ghost" style="margin-top:8px">🖼️ التقاط صورة للباركود</button>
      <div id="scanhost" class="scanbox" ${scanning ? "" : "hidden"}></div><button id="stopscan" class="ghost" hidden>إيقاف الكاميرا</button>
    </div>
    ${S.queue.length ? `<div class="card"><span class="pill wait">${S.queue.length} حضور بانتظار الإرسال</span> <span class="small">سيُرسل تلقائياً عند توفر الإنترنت أو شبكة الدكتور، وفي أي وقت خلال ${S.lateHours} ساعة بعد انتهاء المحاضرة (المهلة التي حددها الدكتور).</span><button id="sync" class="sec" style="margin-top:8px">إرسال الآن</button>${S.mailbox ? `<button id="mailsend" class="ghost" style="margin-top:8px">📧 إرسال حضوري بالإيميل (إن لم يتوفر خادم)</button>` : ""}</div>` : ""}
    ${hist ? `<div class="card hist"><h2>آخر عملياتي</h2>${hist}</div>` : ""}${inboxHtml()}
    <details class="card"><summary>⚙️ إعدادات متقدمة</summary><p class="small">عنوان الخادم (للمسؤول/الدعم فقط)</p><input id="srv" type="text" value="${esc(S.base)}" placeholder="${esc(apiBase())}" dir="ltr"><button id="srvsave" class="sec" style="margin-top:8px">اختبار الاتصال وحفظ العنوان</button><p id="srvmsg" class="small"></p><p class="small">معرّف الجهاز: ${esc((S.device || "").slice(0, 8))}</p></details>`;
  $("#go").onclick = register; $("#scan").onclick = startScan; $("#photobtn").onclick = () => photoInput.click();
  const sy = $("#sync"); if (sy) sy.onclick = () => flush();
  const ms = $("#mailsend"); if (ms) ms.onclick = () => mailAttendance();
  $("#srvsave").onclick = () => testAndSaveServer($("#srv").value, $("#srvmsg"));
}

async function testAndSaveServer(v, msgEl) {
  v = String(v || "").trim().replace(/\/+$/, "");
  if (v && !/^https?:\/\//i.test(v)) v = "http://" + v;                       // 192.168.1.5:5000 → http://192.168.1.5:5000
  if (msgEl) msgEl.textContent = "⏳ جاري الاختبار…";
  const ms = await probe(v || apiBase(), 4000);
  if (ms == null) { if (msgEl) msgEl.textContent = "❌ لا يمكن الوصول إلى الخادم على هذا العنوان. تأكد أنك على نفس شبكة الدكتور وأن البرنامج شغّال."; return; }
  S.base = v; await save();
  if (msgEl) msgEl.textContent = "✅ الاتصال سليم (" + ms + " ms) — جاري تحميل الأسماء…";
  await refreshRoster(); setNet(true); render(); flush();
}

// ───── التشغيل ─────
async function boot() {
  S.device = await kv.get("device", null) || rid();
  S.me = await kv.get("me", null); S.meOk = await kv.get("meOk", false); S.queue = await kv.get("queue", []); S.hist = await kv.get("hist", []);
  S.offset = await kv.get("offset", null); S.maxWall = await kv.get("maxWall", 0); S.base = await kv.get("base", ""); {   // إن أُعيد بناء التطبيق بعنوان جديد فلا يتغلّب العنوان القديم المحفوظ
    const cfg = (window.APP_CONFIG && window.APP_CONFIG.base) || ""; const prev = await kv.get("cfgBase", null);
    if (prev !== null && prev !== cfg) S.base = ""; await kv.set("cfgBase", cfg); }
  S.org = await kv.get("org", ""); S.grace = await kv.get("grace", 10); S.lateHours = await kv.get("late", 48);
  S.roster = await kv.get("roster", null); S.mailbox = await kv.get("mailbox", ""); S.loginMode = await kv.get("loginMode", null); S.relay = await kv.get("relay", "");
  S.domain = await kv.get("domain", "");
  try {   // الباركود العام يحمل بريد الاستلام ورابط الإرسال: لا حاجة لتعديل أي إعداد في الصفحة
    const q = new URLSearchParams(location.search), m = (q.get("m") || "").trim(), r = (q.get("r") || "").trim();
    if (/^[^@\s]+@[^@\s]+\.[a-z]{2,}$/i.test(m)) { S.mailbox = m; await kv.set("mailbox", m); }
    if (/^https:\/\//.test(r)) { S.relay = r; await kv.set("relay", r); }
  } catch (e) {}
  if (mailOnly()) { S.loginMode = "email"; S.mailbox = (window.APP_CONFIG && window.APP_CONFIG.mailbox) || S.mailbox; }
  if (!S.roster && (window.Capacitor || (window.APP_CONFIG && window.APP_CONFIG.embedded))) {   // التطبيق يحمل قائمة أسماء مضمّنة (roster.json) فيعمل من أول فتح بلا اتصال
    try {
      const r = await (await fetch("roster.json", { cache: "no-store" })).json();
      if (r && Array.isArray(r.students) && r.students.length) {
        S.roster = { students: r.students.map(s => Object.assign(s, { nn: norm(s.n) })), org_tree: r.org_tree || null, at: 0 };
        S.org = r.org || S.org; S.grace = r.grace || S.grace; S.loginMode = r.login_mode || "pick"; await kv.set("loginMode", S.loginMode);
        await kv.set("roster", S.roster); await kv.set("org", S.org); await kv.set("grace", S.grace);
      }
    } catch (e) {}
  }
  LANG = await kv.get("lang", "ar");
  const lb = $("#lang"); if (lb) lb.onclick = async () => { LANG = LANG === "en" ? "ar" : "en"; await kv.set("lang", LANG); render(); };
  try { navigator.storage && navigator.storage.persist && navigator.storage.persist(); } catch (e) {}   // لا يحذف المتصفح الطابور
  await save();
  if ("serviceWorker" in navigator && window.isSecureContext) navigator.serviceWorker.register("sw.js", { scope: "./" }).catch(() => {});
  if ("serviceWorker" in navigator) navigator.serviceWorker.ready.then(() => { S.swReady = true; render(); }).catch(() => {});
  takeFragmentFromUrl();   // الباركود جاء كرابط من كاميرا الهاتف
  render();
  const ok = await refreshRoster();   // يحدّث الأسماء وفرق الوقت
  if (S.tok) S.tok.wall = Date.now() - (performance.now() - S.tok.perf);
  render(); flush(); loadInbox();
  setInterval(loadInbox, 60000);
  setInterval(() => { clockBad(); save(); }, 20000);
  setInterval(() => { flush(); if (S.tok && !tokFresh()) render(); }, 15000);
  setInterval(refreshRoster, 10 * 60 * 1000);
  window.addEventListener("online", () => { checkInternet(); if (!mailOnly()) refreshRoster().then(() => { render(); flush(); }); });
  window.addEventListener("offline", () => { S.internet = false; paintNet(); });
  checkInternet(); setInterval(checkInternet, 12000);
  window.addEventListener("offline", () => setNet(false));
  window.addEventListener("hashchange", () => { takeFragmentFromUrl(); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { flush(); render(); } });
}
const tokFresh = () => { const st = tokState(); return st === "fresh" || st === "warn"; };
function takeFragmentFromUrl() {
  const tk = parseFrag(location.hash.slice(1));
  if (tk) { history.replaceState(null, "", location.pathname + location.search); takeToken(tk); }
}
boot();
})();
