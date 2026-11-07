/* برنامج الدكتور — واجهة المحطة. يعمل مع الخادم المحلي المدمج، ولا يحتاج إنترنت. */
(() => {
"use strict";
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const AR = "٠١٢٣٤٥٦٧٨٩";
const ar = n => String(n).replace(/\d/g, d => AR[d]);
const pad = n => String(n).padStart(2, "0");
const S = { lec: null, mode: "lan", modeSet: false, zoom: 100, net: null, info: null, timer: null, url: "" };

async function api(path, body) {
  const r = await fetch(path, { method: body !== undefined ? "POST" : "GET", headers: { "Content-Type": "application/json" }, body: body !== undefined ? JSON.stringify(body) : undefined, cache: "no-store" });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || "خطأ " + r.status);
  return j;
}
const qrSrc = (d, l) => "/api/qr.svg?l=" + (l || "M") + "&d=" + encodeURIComponent(d);

function modal(html, mount) {
  $("#mbox").innerHTML = html; $("#modal").hidden = false;
  $("#modal").onclick = e => { if (e.target.id === "modal") closeModal(); };
  mount && mount();
}
const closeModal = () => { $("#modal").hidden = true; };

// ───── التحميل ─────
async function loadInfo() {
  const i = S.info = await api("/api/station/info");
  $("#title").textContent = "نظام الحضور بالباركود - " + (i.org || "جامعة المعارف");
  document.title = $("#title").textContent;
  const sel = $("#course"), cur = sel.value;
  sel.innerHTML = '<option value="">— اختر المادة —</option>' + i.courses.map(c => `<option value="${c.uid}" data-d="${c.duration_sec}">${esc(c.name)}</option>`).join("");
  if (cur && i.courses.some(c => c.uid === cur)) sel.value = cur;
}
async function loadNet() {
  try {
    const n = S.net = await api("/api/station/net");
    if (!S.modeSet) S.mode = n.cloud ? "public" : "lan";   // الرابط العام أولاً: يفتح من كاميرا الهاتف حتى بلا إنترنت (من الكاش) ويعمل لكل الطلاب
    if ($("#auto").checked || !$("#addr").value) $("#addr").value = n.lan;
    const pubOn = S.mode === "public" && n.cloud;
    const base = pubOn ? n.cloud : ($("#addr").value || n.lan);
    $("#url").textContent = base.replace(/^https?:\/\//, pubOn ? "https://" : "https://") + "/s/";
    $("#url").textContent = base + "/s/";
    const link = base + "/s/";
    if (S.smallFor !== link) { S.smallFor = link; $("#smallqr").src = qrSrc(link, "M"); }
    const off = !n.has_sync;
    const t = n.last_sync ? new Date(n.last_sync * 1000) : null;
    const hh = t ? pad(t.getHours()) + ":" + pad(t.getMinutes()) : "";
    let msg = "✓ البرنامج يعمل";
    if (off) msg += " — السحابة غير مضبوطة (يعمل محلياً فقط)";
    else if (n.unsynced) msg += ` — ${ar(n.unsynced)} سجل بانتظار المزامنة (يُرسل تلقائياً عند توفر الإنترنت)`;
    else msg += " — متزامن مع السحابة" + (hh ? " (آخر مزامنة " + ar(hh) + ")" : "");
    if (n.pending_mail) msg += ` — ${ar(n.pending_mail)} إيميل بانتظار الإرسال`;
    const el = $("#net"); el.textContent = msg; el.className = "net" + (n.unsynced || off ? " off" : "");
    $("#pub").textContent = S.mode === "public" ? "🌐 الرابط العام مفعّل (يعمل مع أي شبكة) — اضغط للتحويل إلى شبكة القاعة المحلية" : "🌐 رابط عام (يعمل مع 3G / 4G / 5G)";
  } catch (e) { $("#net").textContent = "تعذّر الاتصال بالخادم المحلي"; $("#net").className = "net off"; }
}

// ───── المحاضرة ─────
async function startLecture() {
  const course = $("#course").value;
  if (!course) return alert("اختر المادة أولاً");
  setRunning(true); $("#done").hidden = true; $("#bigqr").hidden = false; $("#line1").textContent = "جارٍ بدء المحاضرة…";   // استجابة فورية
  try {
    const r = await api("/api/station/lecture/start", { course_uid: course, duration_sec: +$("#dur").value || 0 });
    S.lec = r.lecture; S.course = r.course; S.url = "";
    tick(); S.timer = setInterval(tick, 500);
  } catch (e) { setRunning(false); $("#bigqr").hidden = true; $("#line1").textContent = "اضغط زر بدء المحاضرة"; alert(e.message); }
}
function setRunning(on) {
  $("#start").disabled = on; $("#end").disabled = !on; $("#course").disabled = on; $("#dur").disabled = on; $("#unbind").disabled = on;
}
let busy = false;
async function tick() {
  if (!S.lec || busy) return; busy = true;
  try {
    const base = S.mode === "public" ? "" : ($("#auto").checked ? "" : $("#addr").value.trim());
    const q = await api("/api/station/lecture/" + S.lec.uid + "/qr?mode=" + S.mode + (base ? "&base=" + encodeURIComponent(base) : ""));
    if (q.url !== S.url) { S.url = q.url; $("#bigqr").src = qrSrc(q.url, "L"); }
    const m = Math.floor(q.remaining / 60), s = q.remaining % 60;
    $("#line1").textContent = `المتبقي ${ar(pad(m) + ":" + pad(s))}   |   رمز المحاضرة: ${q.code}`;
    $("#line2").textContent = `عدد الحاضرين: ${ar(q.count)}`;
    $("#last").textContent = q.last.length ? "آخر الحاضرين: " + q.last.slice(0, 6).join(" ، ") : "";
    if (!q.active) await finish(q.count, true);
  } catch (e) { /* انقطاع لحظي */ } finally { busy = false; }
}
async function finish(count, auto) {
  if (!S.lec) return;
  clearInterval(S.timer); const lec = S.lec; S.lec = null;
  try { await api("/api/station/lecture/" + lec.uid + "/end", {}); } catch (e) {}
  setRunning(false); $("#bigqr").hidden = true; $("#done").hidden = false;
  $("#done").innerHTML = `${auto ? "انتهى وقت المحاضرة" : "تم إنهاء المحاضرة"}<br>${esc(S.course || "")}<br>عدد الحاضرين: ${ar(count ?? 0)}<br><span style="font-size:15px;color:#555;font-weight:400">يمكنك الآن تصدير ملف Excel</span>`;
  $("#line1").textContent = "اضغط زر بدء المحاضرة"; $("#line2").textContent = ""; $("#last").textContent = "";
  loadNet();
}
async function endLecture() {
  if (!S.lec) return;
  if (!confirm("إنهاء المحاضرة الآن؟")) return;
  let c = 0; try { c = (await api("/api/station/lecture/" + S.lec.uid + "/status")).count; } catch (e) {}
  finish(c, false);
}

// ───── التصدير ─────
async function doExport() {
  const course = $("#course").value;
  if (!course) return alert("اختر المادة التي تريد تصدير حضورها من القائمة");
  const name = $("#course").selectedOptions[0].textContent;
  const c = S.info.courses.find(x => x.uid === course);
  modal(`<h2>تصدير حضور «${esc(name)}»</h2><p>جارٍ إنشاء ملف Excel وإرساله…</p>`);
  try {
    const r = await api("/api/station/export", { course_uid: course });
    const mail = r.mail === "sent" ? `<p class="ok">✅ أُرسل الملف بالإيميل إلى: <span dir="ltr">${esc(c.doctor_email || "المسؤول")}</span></p>`
      : r.mail === "queued" ? `<p class="bad">📶 لا يوجد إنترنت الآن — حُفظ الملف وسيُرسل تلقائياً بالإيميل عند توفر الاتصال.</p>`
      : `<p class="bad">لم يُحدَّد إيميل للتدريسي ولا للمسؤول — الملف محفوظ على الجهاز فقط.</p>`;
    modal(`<h2>تم التصدير ✓</h2><p>${esc(r.filename)}</p><p class="small">محاضرات: ${ar(r.lectures)} — طلاب: ${ar(r.students)}</p>${mail}
      <div class="row"><button class="b blue" id="openf">فتح مجلد الملفات</button><button class="b brown" id="cl">إغلاق</button></div>`,
      () => { $("#cl").onclick = closeModal; $("#openf").onclick = () => api("/api/station/open-exports", {}).then(x => { $("#openf").textContent = x.path; }); });
  } catch (e) { modal(`<h2 class="bad">تعذّر التصدير</h2><p>${esc(e.message)}</p><div class="row"><button class="b brown" id="cl">إغلاق</button></div>`, () => $("#cl").onclick = closeModal); }
}

// ───── فك ربط طالب ─────
function unbindDlg() {
  modal(`<h2>فك ربط طالب بجهازه</h2><p class="small">يُستخدم إذا غيّر الطالب هاتفه أو سجّل باسم خطأ. ابحث بالاسم ثم اضغط «فك الربط».</p>
    <input id="uq" placeholder="اكتب جزءاً من الاسم…" autocomplete="off"><div id="ul"></div><div class="row"><button class="b brown" id="cl">إغلاق</button></div>`, () => {
    $("#cl").onclick = closeModal; const inp = $("#uq"); inp.focus();
    const load = async () => {
      const r = await api("/api/station/bound?q=" + encodeURIComponent(inp.value));
      $("#ul").innerHTML = r.students.length ? r.students.map(s => `<div class="li"><span>${esc(s.name)} <span class="small">(${esc(s.grp || "")})</span></span><button class="b red sm" data-u="${s.uid}">فك الربط</button></div>`).join("") : '<p class="small">لا توجد نتائج.</p>';
    };
    inp.oninput = load; load();
    $("#ul").onclick = async e => { const b = e.target.closest("button[data-u]"); if (!b || !confirm("فك ربط هذا الطالب؟ سيتمكن من اختيار اسمه من أي جهاز جديد.")) return; await api("/api/station/unbind", { student_uid: b.dataset.u }); load(); };
  });
}

// ───── إعدادات السحابة ─────
async function cfgDlg() {
  const c = await api("/api/station/config");
  modal(`<h2>ربط البرنامج بالسحابة</h2>
    <p class="small">السحابة تجعل الحضور المسجّل على هواتف الطلاب بلا إنترنت يصل لك، وتوحّد المواد والأسماء بين كل الدكاترة. اتركها فارغة إذا تعمل على شبكة القاعة فقط.</p>
    <label>رابط السحابة</label><input id="cu" dir="ltr" placeholder="https://attendance.example.com" value="${esc(c.cloud_url)}">
    <label>مفتاح المزامنة (يعطيك إياه المسؤول)</label><input id="ck" dir="ltr" type="password" placeholder="${c.has_sync_key ? "********" : ""}">
    <label>اسم هذا الجهاز / القاعة (اختياري)</label><input id="cn" value="${esc(c.station_name)}">
    <div class="row"><button class="b blue" id="cs">حفظ ومزامنة الآن</button><button class="b brown" id="cl">إغلاق</button></div><p id="cm" class="small"></p>`, () => {
    $("#cl").onclick = closeModal;
    $("#cs").onclick = async () => {
      const b = { cloud_url: $("#cu").value, station_name: $("#cn").value }; if ($("#ck").value) b.sync_key = $("#ck").value;
      await api("/api/station/config", b); $("#cm").textContent = "جارٍ المزامنة…";
      const r = await api("/api/station/sync", {}); $("#cm").innerHTML = r.ok === false ? `<span class="bad">لا يوجد اتصال: ${esc(r.error || "")}</span>` : '<span class="ok">✓ تمت المزامنة</span>';
      await loadInfo(); loadNet();
    };
  });
}

// ───── تهيئة الأزرار ─────
function setZoom(z) { S.zoom = Math.max(40, Math.min(220, z)); $("#bigqr").style.width = $("#bigqr").style.height = Math.round(340 * S.zoom / 100) + "px"; $("#zoom").textContent = "الحجم " + ar(S.zoom) + "%"; }
function fullscreen() {
  if (window.pywebview && window.pywebview.api && window.pywebview.api.fullscreen) return window.pywebview.api.fullscreen();
  if (document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen().catch(() => {});
}
$("#start").onclick = startLecture; $("#end").onclick = endLecture; $("#export").onclick = doExport; $("#unbind").onclick = unbindDlg; $("#cfg").onclick = cfgDlg;
$("#minus").onclick = () => setZoom(S.zoom - 10); $("#plus").onclick = () => setZoom(S.zoom + 10);
$("#full").onclick = fullscreen; document.addEventListener("keydown", e => { if (e.key === "F11") { e.preventDefault(); fullscreen(); } });
$("#admin").onclick = () => api("/api/station/open-admin", {});
$("#swap").onclick = () => { $("#auto").checked = true; $("#addr").readOnly = true; loadNet(); };
$("#auto").onchange = () => { $("#addr").readOnly = $("#auto").checked; if ($("#auto").checked) loadNet(); else $("#addr").focus(); };
$("#addr").onchange = loadNet;
$("#pub").onclick = () => {
  if (!S.net || !S.net.cloud) { alert("لم يُضبط رابط السحابة بعد. اضغط «☁ السحابة» وأدخل الرابط ومفتاح المزامنة."); return cfgDlg(); }
  S.mode = S.mode === "public" ? "lan" : "public"; S.modeSet = true; S.url = ""; loadNet();
};
$("#addr").readOnly = true;

(async () => {
  await loadInfo().catch(() => {});
  await loadNet();
  // إذا أُغلق البرنامج أو انقطع الكهرباء أثناء محاضرة جارية: نكمل نفس المحاضرة (نفس الرمز والحضور المسجّل)
  const act = S.info && S.info.active;
  if (act) { S.lec = { uid: act.uid }; S.course = act.course; $("#course").value = act.course_uid; $("#bigqr").hidden = false; setRunning(true); tick(); S.timer = setInterval(tick, 500); }
  setInterval(loadNet, 8000);
  setInterval(() => loadInfo().catch(() => {}), 30000);
  $("#course").onchange = () => { const o = $("#course").selectedOptions[0]; if (o && o.dataset.d) $("#dur").value = o.dataset.d; };
})();
})();
