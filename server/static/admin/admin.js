/* لوحة المسؤول */
(() => {
"use strict";
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const root = $("#root");
let ME = null, TAB = "home";
const toast = (m, bad) => { const t = $("#toast"); t.textContent = m; t.className = "on" + (bad ? " err" : ""); clearTimeout(toast.h); toast.h = setTimeout(() => t.className = "", 3200); };
async function api(path, method = "GET", body, form) {
  const o = { method, credentials: "same-origin" };
  if (form) o.body = form; else if (body !== undefined) { o.headers = { "Content-Type": "application/json" }; o.body = JSON.stringify(body); }
  const r = await fetch(path, o);
  if (r.status === 401 && path !== "/api/admin/login") { ME = null; start(); throw new Error("انتهت الجلسة"); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || "خطأ " + r.status);
  return j;
}
const run = async (fn, okMsg) => { try { const r = await fn(); if (okMsg) toast(okMsg); return r; } catch (e) { toast(e.message, true); } };
const fmt = ts => ts ? new Date(ts * 1000).toLocaleString("ar-IQ", { dateStyle: "short", timeStyle: "short" }) : "—";
const modal = (html, onMount) => { const m = document.createElement("div"); m.className = "modal"; m.innerHTML = `<div class="card">${html}</div>`; m.onclick = e => { if (e.target === m) m.remove(); }; document.body.appendChild(m); onMount && onMount(m); return m; };

async function start() {
  ME = await api("/api/admin/me").catch(() => ({ admin: false }));
  if (!ME.admin) return loginView();
  if (ME.must_change) return changePw(true);
  shell();
}
function loginView() {
  root.innerHTML = `<div class="login"><div class="card"><h2 style="font-size:1.3rem">🎓 نظام الحضور بالباركود</h2><p class="mut">تسجيل دخول المسؤول</p>
    <input id="u" placeholder="اسم المستخدم" autocomplete="username" value="admin"><input id="p" type="password" placeholder="كلمة المرور" autocomplete="current-password">
    <button class="b" id="go" style="width:100%">دخول</button><p class="small mut">أول مرة؟ المستخدم <b>admin</b> وكلمة المرور <b>admin123</b> — سيُطلب منك تغييرها.</p></div></div>`;
  const go = () => run(async () => { await api("/api/admin/login", "POST", { username: $("#u").value, password: $("#p").value }); start(); });
  $("#go").onclick = go; $("#p").onkeydown = e => { if (e.key === "Enter") go(); }; $("#p").focus();
}
function changePw(force) {
  modal(`<h2>${force ? "غيّر كلمة المرور الافتراضية" : "تغيير كلمة المرور"}</h2><label>كلمة المرور الحالية</label><input id="o" type="password" style="width:100%"><label style="margin-top:8px">الجديدة (6 أحرف فأكثر)</label><input id="n" type="password" style="width:100%"><div class="row" style="margin-top:14px"><button class="b" id="s">حفظ</button></div>`, m => {
    $("#s").onclick = () => run(async () => { await api("/api/admin/password", "POST", { old: $("#o").value, new: $("#n").value }); m.remove(); start(); }, "تم تغيير كلمة المرور");
  }).onclick = e => { if (force) e.stopPropagation(); };
}
const ALLTABS = [["home", "الرئيسية"], ["org", "الكليات والأقسام"], ["courses", "المواد"], ["students", "الطلاب"], ["lectures", "المحاضرات والحضور"], ["reports", "التقارير"], ["users", "المستخدمون والصلاحيات"], ["req", "الطلبات والاعتماد"], ["audit", "سجل التدقيق"], ["settings", "الإعدادات"], ["adv", "إعدادات الجامعة الذكية"], ["mail", "البريد"]];
const can = p => (ME.perms || []).includes(p);
const showTab = k => ({
  home: () => true, org: () => ["admin", "dean"].includes(ME.role), courses: () => can("courses"),
  students: () => can("students") || can("unbind"), lectures: () => can("lectures"), reports: () => can("reports"),
  users: () => ["admin", "dean"].includes(ME.role) || (ME.role === "head" && (ME.delegate || can("doctors"))) || (ME.role === "rapporteur" && can("doctors")),
  req: () => true, audit: () => ["admin", "dean", "head"].includes(ME.role), adv: () => ME.role === "admin",
  settings: () => ME.role === "admin", mail: () => ME.role === "admin" }[k]());
const tabs = () => ALLTABS.filter(t => showTab(t[0]));
const TITLES = { admin: "لوحة رئيس الجامعة", dean: "لوحة عميد الكلية", head: "لوحة رئيس القسم", rapporteur: "لوحة مقرر القسم", doctor: "لوحة التدريسي" };
let ORG = { colleges: [], departments: [] };
const deptName = u => { const d = ORG.departments.find(x => x.uid === u); if (!d) return "—"; const c = ORG.colleges.find(x => x.uid === d.college_uid); return (c ? c.name + " / " : "") + d.name; };
const deptOpts = (sel, empty) => (empty ? `<option value="">${empty}</option>` : "") + ORG.colleges.map(c => `<optgroup label="${esc(c.name)}">${ORG.departments.filter(d => d.college_uid === c.uid).map(d => `<option value="${d.uid}" ${d.uid === sel ? "selected" : ""}>${esc(d.name)}</option>`).join("")}</optgroup>`).join("");
const stageOpts = (dept, sel) => { const d = ORG.departments.find(x => x.uid === dept); const n = d ? d.stages : 4; return Array.from({ length: n }, (_, i) => `<option value="${i + 1}" ${i + 1 === +sel ? "selected" : ""}>المرحلة ${i + 1}</option>`).join(""); };
const KIND = { theory: "نظري", practical: "عملي" };
const loadOrg = async () => { ORG = await api("/api/admin/org"); };
function shell() {
  root.innerHTML = `<header><h1>🎓 ${TITLES[ME.role] || "لوحة المسؤول"}</h1><div class="r"><button class="b s sm" id="qrb" title="اضغط لتكبير باركود صفحة الطالب" style="padding:3px;background:#fff"><img alt="QR" width="34" height="34" src="/api/qr.svg?d=${encodeURIComponent((ME.cloud_url || location.origin).replace(/\/+$/, "") + "/s/")}&l=L" style="display:block"></button><span>${esc(ME.user)}</span><button class="b s sm" id="pw">كلمة المرور</button><button class="b s sm" id="out">خروج</button></div></header>
    <nav>${tabs().map(([k, n]) => `<button data-t="${k}" class="${k === TAB ? "on" : ""}">${n}</button>`).join("")}</nav><main id="main"></main>`;
  $("#qrb").onclick = () => studentQR();
  $("#out").onclick = async () => { await api("/api/admin/logout", "POST"); start(); }; $("#pw").onclick = () => changePw(false);
  document.querySelectorAll("nav button").forEach(b => b.onclick = () => { TAB = b.dataset.t; shell(); });
  if (!tabs().some(t => t[0] === TAB)) TAB = "home";
  loadOrg().then(() => ({ home, org, courses, students, lectures, reports, users, settings, mail, req: reqTab, audit: auditTab, adv: advTab })[TAB]()).catch(e => toast(e.message, true));
}
const main = () => $("#main");
function studentQR() {
  const url = (ME.cloud_url || location.origin).replace(/\/+$/, "") + "/s/";
  const m = modal(`<h2>باركود صفحة الطالب</h2><p class="mut">يفتح به الطالب صفحة التسجيل (يُخزَّن في الهاتف للعمل بدون إنترنت).</p><div style="text-align:center"><img src="/api/qr.svg?d=${encodeURIComponent(url)}&l=M" style="width:min(80vw,380px);background:#fff;padding:10px;border-radius:12px"><div dir="ltr" style="margin:10px 0;font-weight:700;color:var(--blue);word-break:break-all">${esc(url)}</div></div><div class="row"><button class="b s" onclick="this.closest('.modal').remove()">إغلاق</button></div>`);
  m.firstChild.style.maxWidth = "440px";
}

// ───── الرئيسية ─────
async function home() {
  const s = await api("/api/admin/summary");
  main().innerHTML = `<div class="card"><h2>نظرة عامة</h2><div class="grid">
    <div class="stat"><b>${s.courses}</b><span>مواد</span></div><div class="stat"><b>${s.students}</b><span>طلاب</span></div>${ME.role === "doctor" ? "" : `<div class="stat"><b>${s.bound}</b><span>طلاب ربطوا أجهزتهم</span></div>`}
    <div class="stat"><b>${s.lectures}</b><span>محاضرات</span></div><div class="stat"><b>${s.attendance}</b><span>حضور مسجّل</span></div><div class="stat"><b>${s.outbox}</b><span>رسائل بريد معلّقة</span></div></div></div>
    <div class="card"><h2>المزامنة مع السحابة</h2><p>آخر مزامنة: <b>${s.last_sync ? fmt(s.last_sync) : "لم تتم"}</b> — تغييرات بانتظار الإرسال: <b>${s.dirty}</b> — حضور معلّق التحقق: <b>${s.pending}</b></p>
    ${ME.mode === "cloud" ? '<p class="mut">هذا هو الخادم السحابي: أجهزة الدكاترة تزامن معه تلقائياً.</p>' : `<p class="mut">رابط السحابة: <span dir="ltr">${esc(ME.cloud_url || "غير مضبوط (النظام يعمل محلياً فقط)")}</span></p><button class="b" id="sy">مزامنة الآن</button>`}</div>
    <div class="card"><h2>خطوات البدء</h2><ol style="line-height:2"><li>رئيس الجامعة: «الكليات والأقسام» ← أضف الكليات والأقسام وعدد مراحل كل قسم.</li><li>«المستخدمون والصلاحيات» ← عيّن عميد كل كلية؛ والعميد يعيّن رئيس القسم ومقرره والتدريسيين.</li><li>«المواد» ← أضف المادة مع القسم والمرحلة وإيميل التدريسي ونوعها نظري أو عملي.</li><li>«الطلاب» ← ارفع أسماء المرحلة (نظري: أسماء فقط، عملي: اسم + كروب).</li><li>التدريسي يفتح برنامج المحاضرة ويختار مادته ويضغط «بدء المحاضرة»، والطلاب يمسحون الباركود.</li></ol></div>`;
  const sy = $("#sy"); if (sy) sy.onclick = () => run(async () => { const r = await api("/api/admin/sync", "POST"); if (!r.ok) throw new Error(r.error); home(); }, "تمت المزامنة");
}

// ───── المواد ─────
const courseForm = (c, pre) => {
  const fixedDept = ["head", "rapporteur"].includes(ME.role);
  const dsel = c ? c.dept_uid : (ORG.departments[0] || {}).uid;
  return `<div class="row"><div><label>اسم المادة</label><input id="${pre}n" style="width:100%" value="${esc(c ? c.name : "")}"></div><div><label>إيميل التدريسي</label><input id="${pre}e" dir="ltr" style="width:100%" placeholder="doctor@uoa.edu.iq" value="${esc(c ? c.doctor_email : "")}"></div></div>
  <div class="row" style="margin-top:8px"><div><label>القسم</label>${fixedDept ? `<input disabled style="width:100%" value="${esc(deptName(dsel))}"><select id="${pre}dp" hidden><option value="${dsel}" selected></option></select>` : `<select id="${pre}dp" style="width:100%">${deptOpts(dsel, ME.role === "admin" ? "— بدون قسم (مادة عامة) —" : "")}</select>`}</div>
  <div class="fix"><label>المرحلة</label><select id="${pre}st">${stageOpts(dsel, c ? c.stage : 1)}</select></div>
  <div class="fix"><label>النوع</label><select id="${pre}k"><option value="theory" ${c && c.kind === "theory" || !c ? "selected" : ""}>نظري</option><option value="practical" ${c && c.kind === "practical" ? "selected" : ""}>عملي</option></select></div>
  <div class="fix"><label>مدة المحاضرة (دقيقة)</label><input id="${pre}d" type="number" min="0" style="width:100px" placeholder="افتراضي" value="${c && c.duration_sec ? Math.round(c.duration_sec / 60) : ""}"></div></div>`;
};
const courseVals = pre => ({ name: $("#" + pre + "n").value, doctor_email: $("#" + pre + "e").value, dept_uid: $("#" + pre + "dp").value, stage: +$("#" + pre + "st").value, kind: $("#" + pre + "k").value, duration_sec: +$("#" + pre + "d").value * 60 });
const bindDept = (pre, root = document) => { const dp = $("#" + pre + "dp", root); if (dp) dp.onchange = () => { $("#" + pre + "st", root).innerHTML = stageOpts(dp.value, 1); }; };
async function courses() {
  const { courses: cs } = await api("/api/admin/courses");
  const canEdit = can("courses");
  main().innerHTML = `${canEdit ? `<div class="card"><h2>إضافة مادة</h2>${courseForm(null, "a")}<div style="margin-top:12px"><button class="b g" id="add">إضافة المادة</button></div>${ORG.departments.length ? "" : '<div class="note">أضف الكليات والأقسام أولاً من تبويب «الكليات والأقسام» ليظهر القسم والمرحلة.</div>'}</div>` : ""}
  <div class="card"><h2>المواد (${cs.length})</h2><div class="tw"><table><thead><tr><th>المادة</th><th>الكلية / القسم</th><th>المرحلة</th><th>النوع</th><th>إيميل التدريسي</th><th>محاضرات</th><th></th></tr></thead><tbody>${cs.map(c => `<tr><td><b>${esc(c.name)}</b></td><td>${esc(c.dept_uid ? (c.college_name + " / " + c.dept_name) : "—")}</td><td>${c.stage || "—"}</td><td><span class="pill ${c.kind === "practical" ? "wait" : "ok"}">${KIND[c.kind] || "نظري"}</span></td><td dir="ltr" style="text-align:right">${esc(c.doctor_email || "—")}</td><td>${c.lectures}</td>
  <td><div class="acts">${can("reports") ? `<button class="b sm o" data-x="${c.uid}">تنزيل Excel</button><button class="b sm g" data-m="${c.uid}">إرسال للإيميل</button>` : ""}${canEdit ? `<button class="b sm s" data-e="${c.uid}">تعديل</button><button class="b sm r" data-d="${c.uid}">حذف</button>` : ""}</div></td></tr>`).join("") || '<tr><td colspan="7" class="mut">لا توجد مواد بعد</td></tr>'}</tbody></table></div></div>`;
  if (canEdit) { bindDept("a"); $("#add").onclick = () => run(async () => { await api("/api/admin/courses", "POST", courseVals("a")); courses(); }, "تمت إضافة المادة"); }
  main().onclick = e => {
    const b = e.target.closest("button[data-x],button[data-m],button[data-e],button[data-d]"); if (!b) return;
    const c = cs.find(x => x.uid === (b.dataset.x || b.dataset.m || b.dataset.e || b.dataset.d));
    if (b.dataset.x) location.href = "/api/admin/export?course_uid=" + c.uid;
    if (b.dataset.m) run(async () => { const r = await api("/api/admin/export/send", "POST", { course_uid: c.uid }); if (r.failed) throw new Error("تعذّر الإرسال الآن — حُفظ في البريد المعلّق وسيُعاد تلقائياً"); }, "تم إرسال الملف للإيميل");
    if (b.dataset.d && confirm("حذف المادة «" + c.name + "»؟ (سجلات حضورها تبقى محفوظة)")) run(async () => { await api("/api/admin/courses/" + c.uid, "DELETE"); courses(); }, "تم الحذف");
    if (b.dataset.e) modal(`<h2>تعديل المادة</h2>${courseForm(c, "b")}<div class="row" style="margin-top:14px"><button class="b" id="sv">حفظ</button></div>`, m => {
      bindDept("b", m); m.firstChild.style.maxWidth = "640px";
      $("#sv").onclick = () => run(async () => { await api("/api/admin/courses/" + c.uid, "PUT", courseVals("b")); m.remove(); courses(); }, "تم الحفظ");
    });
  };
}

// ───── الكليات والأقسام والمراحل ─────
async function org() {
  const isAdmin = ME.role === "admin";
  main().innerHTML = `${isAdmin ? `<div class="card"><h2>إضافة كلية</h2><div class="row"><div><input id="kn" placeholder="اسم الكلية" style="width:100%"></div><div class="fix"><button class="b g" id="ka">إضافة</button></div></div></div>` : ""}
  ${ORG.colleges.map(c => `<div class="card"><div class="row"><div><h2 style="margin:0">🏛 ${esc(c.name)}</h2></div>${isAdmin ? `<div class="fix"><button class="b sm s" data-ke="${c.uid}">تعديل الاسم</button> <button class="b sm r" data-kd="${c.uid}">حذف</button></div>` : ""}</div>
    <div class="tw" style="margin-top:10px"><table><thead><tr><th>القسم</th><th>عدد المراحل</th><th></th></tr></thead><tbody>${ORG.departments.filter(d => d.college_uid === c.uid).map(d => `<tr><td><b>${esc(d.name)}</b></td><td>${d.stages}</td><td><div class="acts"><button class="b sm s" data-de="${d.uid}">تعديل</button><button class="b sm r" data-dd="${d.uid}">حذف</button></div></td></tr>`).join("") || '<tr><td colspan="3" class="mut">لا توجد أقسام</td></tr>'}</tbody></table></div>
    <div class="row" style="margin-top:10px"><div><input data-dn="${c.uid}" placeholder="اسم قسم جديد" style="width:100%"></div><div class="fix"><select data-ds="${c.uid}">${[1, 2, 3, 4, 5, 6].map(n => `<option value="${n}" ${n === 4 ? "selected" : ""}>${n} مراحل</option>`).join("")}</select></div><div class="fix"><button class="b g" data-da="${c.uid}">+ قسم</button></div></div></div>`).join("") || '<div class="card"><p class="mut">لا توجد كليات بعد.</p></div>'}`;
  if (isAdmin) $("#ka").onclick = () => run(async () => { await api("/api/admin/colleges", "POST", { name: $("#kn").value }); await loadOrg(); org(); }, "تمت إضافة الكلية");
  main().onclick = e => {
    const b = e.target.closest("button"); if (!b) return; const d = b.dataset;
    if (d.da) run(async () => { await api("/api/admin/departments", "POST", { college_uid: d.da, name: $(`[data-dn="${d.da}"]`).value, stages: +$(`[data-ds="${d.da}"]`).value }); await loadOrg(); org(); }, "تمت إضافة القسم");
    if (d.ke) { const c = ORG.colleges.find(x => x.uid === d.ke); const n = prompt("اسم الكلية:", c.name); if (n) run(async () => { await api("/api/admin/colleges/" + c.uid, "PUT", { name: n }); await loadOrg(); org(); }, "تم الحفظ"); }
    if (d.kd && confirm("حذف الكلية؟")) run(async () => { await api("/api/admin/colleges/" + d.kd, "DELETE"); await loadOrg(); org(); }, "تم الحذف");
    if (d.de) { const x = ORG.departments.find(v => v.uid === d.de); const n = prompt("اسم القسم:", x.name); if (!n) return; const st = prompt("عدد المراحل (1-8):", x.stages); if (st) run(async () => { await api("/api/admin/departments/" + x.uid, "PUT", { name: n, stages: +st }); await loadOrg(); org(); }, "تم الحفظ"); }
    if (d.dd && confirm("حذف القسم؟")) run(async () => { await api("/api/admin/departments/" + d.dd, "DELETE"); await loadOrg(); org(); }, "تم الحذف");
  };
}

// ───── الطلاب ─────
let SQ = "", SG = "", SD = "", SS = "";
async function students() {
  const r = await api("/api/admin/students?q=" + encodeURIComponent(SQ) + "&group=" + encodeURIComponent(SG) + "&dept_uid=" + encodeURIComponent(SD) + "&stage=" + encodeURIComponent(SS));
  const fixed = ["head", "rapporteur"].includes(ME.role), canUp = can("students");
  const dsel = fixed ? ME.dept : (ORG.departments[0] || {}).uid || "";
  const deptPick = (id, withEmpty) => fixed ? `<input disabled style="width:100%" value="${esc(deptName(ME.dept))}"><select id="${id}" hidden><option value="${ME.dept}" selected></option></select>` : `<select id="${id}" style="width:100%">${deptOpts(dsel, withEmpty)}</select>`;
  main().innerHTML = `${canUp ? `<div class="card"><h2>رفع قائمة الطلاب (Excel)</h2>
    <div class="row"><div><label>القسم</label>${deptPick("ud", ME.role === "admin" ? "— بدون قسم (قائمة عامة) —" : "")}</div><div class="fix"><label>المرحلة</label><select id="us">${stageOpts(dsel, 1)}</select></div></div>
    <div class="row" style="margin-top:10px"><div><label>نوع القائمة</label><select id="uk" style="width:100%"><option value="theory">نظري — أسماء الطلاب فقط (عمود واحد)</option><option value="practical">عملي — الاسم ثم الكروب (A/B/C/D)</option></select></div>
    <div class="fix"><label>الطريقة</label><select id="mode"><option value="merge">إضافة الجدد فقط</option><option value="replace">استبدال قائمة هذه المرحلة</option></select></div></div>
    <div class="row" style="margin-top:10px"><div><input type="file" id="f" accept=".xlsx" style="width:100%"></div><div class="fix"><button class="b g" id="up">رفع</button></div><div class="fix"><a class="b s" id="tpl" style="text-decoration:none;display:inline-block;padding:10px 14px;border-radius:9px;background:#e4eaf6;color:#2c5599;font-weight:600" href="/api/admin/students/template">تنزيل نموذج</a></div></div>
    <p class="small mut" id="uhint"></p></div>` : ""}
  <div class="card"><h2>الطلاب (${r.total})</h2><div class="row"><div><input id="q" placeholder="بحث بالاسم…" style="width:100%" value="${esc(SQ)}"></div>${fixed ? "" : `<div class="fix"><select id="fd"><option value="">كل الأقسام</option>${deptOpts(SD)}</select></div>`}<div class="fix"><select id="fs"><option value="">كل المراحل</option>${[1, 2, 3, 4, 5, 6, 7, 8].map(n => `<option value="${n}" ${String(n) === SS ? "selected" : ""}>مرحلة ${n}</option>`).join("")}</select></div><div class="fix"><select id="g"><option value="">كل الكروبات</option>${r.groups.filter(Boolean).map(g => `<option ${g === SG ? "selected" : ""}>${esc(g)}</option>`).join("")}</select></div>${canUp ? '<div class="fix"><button class="b s" id="addst">+ إضافة طالب</button></div>' : ""}</div>
  <div class="tw" style="margin-top:10px"><table><thead><tr><th>#</th><th>الاسم</th><th>القسم</th><th>المرحلة</th><th>الكروب</th><th>البريد الجامعي</th><th>الجهاز</th><th></th></tr></thead><tbody>${r.students.map((s, i) => `<tr><td>${i + 1}</td><td>${esc(s.name)}</td><td>${esc(s.dept_name || "—")}</td><td>${s.stage || "—"}</td><td>${esc(s.grp || "—")}</td><td dir="ltr" style="text-align:right">${esc(s.univ_email || "—")}</td><td>${s.bound ? '<span class="pill ok">مربوط</span>' : '<span class="pill gray">غير مربوط</span>'}</td><td><div class="acts">${s.bound && can("unbind") ? `<button class="b sm o" data-u="${s.uid}">فك الربط</button>` : ""}${canUp ? `<button class="b sm s" data-e="${s.uid}">تعديل</button><button class="b sm r" data-d="${s.uid}">حذف</button>` : ""}</div></td></tr>`).join("") || '<tr><td colspan="8" class="mut">لا توجد نتائج</td></tr>'}</tbody></table></div>${r.students.length >= 1000 ? '<p class="small mut">يعرض أول 1000 نتيجة — استخدم البحث.</p>' : ""}</div>`;
  if (canUp) {
    const hint = () => { $("#uhint").textContent = $("#uk").value === "theory" ? "نظري: ارفع الرقم الجامعي (مثل 1063004760) وبجانبه الحرف A/B/C/D إن أردت. يُكوَّن البريد @uoa.edu.iq تلقائياً، ويمكن إضافة عمود «البريد الجامعي»." : "عملي: ارفع الرقم الجامعي ثم الكروب (A1, A2, B1…). إن كان الطالب مرفوعاً سابقاً في النظري يُحدَّث كروبه ولا يتكرر."; $("#tpl").href = "/api/admin/students/template?kind=" + $("#uk").value; };
    $("#uk").onchange = hint; hint();
    const ud = $("#ud"); ud.onchange = () => { $("#us").innerHTML = stageOpts(ud.value, 1); };
    $("#up").onclick = () => { const f = $("#f").files[0]; if (!f) return toast("اختر ملف Excel أولاً", true); const fd = new FormData(); fd.append("file", f); fd.append("mode", $("#mode").value); fd.append("kind", $("#uk").value); fd.append("dept_uid", ud.value); fd.append("stage", $("#us").value);
      run(async () => { const j = await api("/api/admin/students/upload", "POST", undefined, fd); toast(`أُضيف ${j.added} طالب جديد${j.updated ? "، وحُدّث " + j.updated : ""}${j.removed ? "، وحُذف " + j.removed : ""}${j.skipped ? "، وتُجوهل " + j.skipped + " صف فارغ" : ""}${j.no_group ? "، " + j.no_group + " بلا كروب" : ""}`); students(); }); };
    $("#addst").onclick = () => modal(`<h2>إضافة طالب</h2><label>الاسم</label><input id="an" style="width:100%"><label style="margin-top:8px">القسم</label>${deptPick("ad", ME.role === "admin" ? "— بدون قسم —" : "")}<label style="margin-top:8px">المرحلة</label><select id="as" style="width:100%">${stageOpts(dsel, 1)}</select><label style="margin-top:8px">الكروب (للعملي، اختياري)</label><input id="ag" style="width:100%"><div class="row" style="margin-top:14px"><button class="b" id="sv">إضافة</button></div>`, m => { $("#ad", m).onchange = e => { $("#as", m).innerHTML = stageOpts(e.target.value, 1); }; $("#sv").onclick = () => run(async () => { await api("/api/admin/students", "POST", { name: $("#an").value, grp: $("#ag").value, dept_uid: $("#ad").value, stage: +$("#as").value }); m.remove(); students(); }, "تمت الإضافة"); });
  }
  let h; $("#q").oninput = e => { clearTimeout(h); h = setTimeout(() => { SQ = e.target.value; students().then(() => { const q = $("#q"); q.focus(); q.setSelectionRange(q.value.length, q.value.length); }); }, 300); };
  $("#g").onchange = e => { SG = e.target.value; students(); }; $("#fs").onchange = e => { SS = e.target.value; students(); }; if ($("#fd")) $("#fd").onchange = e => { SD = e.target.value; students(); };
  main().onclick = e => {
    const b = e.target.closest("button[data-u],button[data-e],button[data-d]"); if (!b) return; const s = r.students.find(x => x.uid === (b.dataset.u || b.dataset.e || b.dataset.d));
    if (b.dataset.u && confirm("فك ربط جهاز الطالب «" + s.name + "»؟ سيستطيع اختيار اسمه من جهاز جديد.")) run(async () => { await api("/api/admin/students/" + s.uid + "/unbind", "POST"); students(); }, "تم فك الربط");
    if (b.dataset.d && confirm("حذف الطالب «" + s.name + "»؟")) run(async () => { await api("/api/admin/students/" + s.uid, "DELETE"); students(); }, "تم الحذف");
    if (b.dataset.e) modal(`<h2>تعديل الطالب</h2><label>الاسم</label><input id="en" style="width:100%" value="${esc(s.name)}"><label style="margin-top:8px">الكروب</label><input id="eg" style="width:100%" value="${esc(s.grp)}"><label style="margin-top:8px">البريد الجامعي</label><input id="ee" dir="ltr" style="width:100%" value="${esc(s.univ_email || "")}"><div class="row" style="margin-top:14px"><button class="b" id="sv">حفظ</button></div>`, m => $("#sv").onclick = () => run(async () => { await api("/api/admin/students/" + s.uid, "PUT", { name: $("#en").value, grp: $("#eg").value, email: $("#ee").value }); m.remove(); students(); }, "تم الحفظ"));
  };
}

// ───── المحاضرات ─────
async function lectures() {
  const [{ lectures: ls }, { courses: cs }] = await Promise.all([api("/api/admin/lectures"), api("/api/admin/courses")]);
  main().innerHTML = `<div class="card"><h2>المحاضرات (${ls.length})</h2><div class="tw"><table><thead><tr><th>المادة</th><th>الوقت</th><th>الرمز</th><th>الحاضرون</th><th>مرفوض</th><th>الحالة</th><th></th></tr></thead><tbody>${ls.map(l => `<tr><td><b>${esc(l.course || "—")}</b></td><td>${fmt(l.start_ts)}</td><td dir="ltr">${esc(l.code)}</td><td><b>${l.present}</b></td><td>${l.rejected ? `<span class="pill bad">${l.rejected}</span>` : "0"}</td><td>${l.status === "ended" ? '<span class="pill gray">منتهية</span>' : '<span class="pill ok">جارية</span>'}</td><td><button class="b sm s" data-l="${l.uid}">التفاصيل</button></td></tr>`).join("") || '<tr><td colspan="7" class="mut">لا توجد محاضرات بعد</td></tr>'}</tbody></table></div></div>`;
  main().onclick = e => { const b = e.target.closest("button[data-l]"); if (b) lectureDetail(b.dataset.l); };
}
async function lectureDetail(uid) {
  const r = await api("/api/admin/lectures/" + uid); const L = r.lecture;
  const present = r.students.filter(s => s.status === "ok").length;
  const m = modal(`<h2>${esc(L.course || "")} — ${fmt(L.start_ts)}</h2><p>الحاضرون: <b>${present}</b> من ${r.students.length}</p><div class="row"><div><input id="lq" placeholder="بحث…" style="width:100%"></div></div>
    <div class="tw" style="margin-top:8px;max-height:50vh"><table><thead><tr><th>الاسم</th><th>الكروب</th><th>الحالة</th><th></th></tr></thead><tbody id="lt"></tbody></table></div><div style="text-align:left;margin:6px 0"><button class="b s sm" onclick="this.closest('.modal').remove()">إغلاق ✕</button></div><p class="small mut">«تعديل» يدوي: يسجل حضور طالب نسي أو يُلغي حضوراً مشكوكاً فيه.</p>`);
  m.firstChild.style.maxWidth = "720px";
  const draw = () => { const q = $("#lq", m).value.trim(); $("#lt", m).innerHTML = r.students.filter(s => !q || s.name.includes(q)).map(s => `<tr><td>${esc(s.name)}</td><td>${esc(s.grp)}</td><td>${s.status === "ok" ? '<span class="pill ok">حاضر</span>' + (s.queued ? ' <span class="pill wait">غير متصل</span>' : "") : s.status === "rejected" ? `<span class="pill bad">مرفوض</span> <span class="small">${esc(s.reason_ar)}</span>` : s.status === "pending" ? '<span class="pill wait">معلّق</span>' : '<span class="pill gray">غائب</span>'}</td><td><button class="b sm ${s.status === "ok" ? "r" : "g"}" data-s="${s.uid}" data-p="${s.status === "ok" ? 0 : 1}">${s.status === "ok" ? "جعله غائباً" : "تسجيل حضور"}</button></td></tr>`).join(""); };
  draw(); $("#lq", m).oninput = draw;
  m.onclick = e => { if (e.target === m) return m.remove(); const b = e.target.closest("button[data-s]"); if (!b) return; run(async () => { await api("/api/admin/attendance/toggle", "POST", { lecture_uid: uid, student_uid: b.dataset.s, present: b.dataset.p === "1" }); m.remove(); lectureDetail(uid); }, "تم التعديل"); };
}


// ───── التقارير والرسوم ─────
const barRow = (label, pct, extra = "") => `<div class="brow"><span class="bl">${esc(label)}</span><div class="bar"><i style="width:${Math.max(2, pct)}%;background:${pct >= 75 ? "var(--green)" : pct >= 50 ? "var(--amber)" : "var(--red)"}"></i></div><b>${pct}%</b>${extra}</div>`;
let RC = "", RG = "";
async function reports() {
  const r = await api("/api/admin/reports" + (RC ? "?course_uid=" + encodeURIComponent(RC) + (RG ? "&group=" + encodeURIComponent(RG) : "") : ""));
  const ov = r.overview, d = r.detail;
  main().innerHTML = `<div class="card"><h2>نسبة الحضور لكل مادة</h2>${ov.length ? ov.map(o => `<div class="orow" data-c="${o.uid}">${barRow(o.name, o.avg, `<span class="small mut">${o.lectures} محاضرة · ${o.students} طالب${o.risk ? ` · <b style="color:var(--red)">${o.risk} إنذار</b>` : ""}</span>`)}</div>`).join("") : '<p class="mut">لا توجد مواد بعد.</p>'}
    <p class="small mut">اضغط على مادة لعرض التفاصيل.</p></div>
    ${d ? `<div class="card"><div class="row"><div><h2 style="margin:0">${esc(d.course)}</h2></div><div class="fix"><select id="rg"><option value="">كل الكروبات</option>${d.groups.length ? "" : ""}${[...new Set((RGS || []).concat(d.groups.map(g => g.grp)))].map(g => `<option ${g === RG ? "selected" : ""}>${esc(g)}</option>`).join("")}</select></div>
      <div class="fix"><button class="b o" id="rx">تنزيل Excel</button></div></div>
      <div class="grid" style="margin-top:12px"><div class="stat"><b>${d.avg}%</b><span>متوسط الحضور</span></div><div class="stat"><b>${d.lectures}</b><span>محاضرات</span></div><div class="stat"><b>${d.students}</b><span>طلاب</span></div><div class="stat"><b style="color:var(--red)">${d.risk_count}</b><span>إنذار (غياب أكثر من ${d.limit}%)</span></div></div>
      <h3>حسب الكروب</h3>${d.groups.map(g => barRow("كروب " + g.grp, g.avg, `<span class="small mut">${g.students} طالب${g.risk ? " · " + g.risk + " إنذار" : ""}</span>`)).join("") || '<p class="mut">—</p>'}
      <h3>حسب المحاضرة</h3>${d.per_lecture.map((l, i) => barRow("م" + (i + 1) + " · " + fmt(l.t), d.students ? Math.round(l.present * 100 / d.students) : 0, `<span class="small mut">${l.present}</span>`)).join("") || '<p class="mut">لا محاضرات.</p>'}
      <h3>الطلاب المعرَّضون للحرمان (غياب أكثر من ${d.limit}%)</h3>
      ${d.risky.length ? `<div class="tw"><table><thead><tr><th>الاسم</th><th>الكروب</th><th>حضر</th><th>غاب</th><th>النسبة</th></tr></thead><tbody>${d.risky.map(x => `<tr><td>${esc(x.name)}</td><td>${esc(x.grp)}</td><td>${x.present}</td><td>${x.absent}</td><td><span class="pill bad">${x.pct}%</span></td></tr>`).join("")}</tbody></table></div>` : '<p class="mut">لا يوجد طالب متجاوز للحد.</p>'}</div>` : ""}`;
  if (d) RGS = [...new Set((RGS || []).concat(d.groups.map(g => g.grp)))];
  main().onclick = e => { const o = e.target.closest(".orow"); if (o) { RC = o.dataset.c; RG = ""; RGS = []; reports(); } };
  if (d) { $("#rg").onchange = e => { RG = e.target.value; reports(); }; $("#rx").onclick = () => location.href = "/api/admin/export?course_uid=" + RC + (RG ? "&group=" + encodeURIComponent(RG) : ""); }
}
let RGS = [];

// ───── المستخدمون والصلاحيات ─────
async function users() {
  const r = await api("/api/admin/users"); const PL = r.perm_labels;
  const roles = { admin: [["dean", "عميد كلية"], ["head", "رئيس قسم"], ["rapporteur", "مقرر قسم"], ["doctor", "تدريسي"]], dean: [["head", "رئيس قسم"], ["rapporteur", "مقرر قسم"], ["doctor", "تدريسي"]],
    head: ME.delegate ? [["rapporteur", "مقرر قسم"], ["doctor", "تدريسي"]] : [["doctor", "تدريسي"]], rapporteur: [["doctor", "تدريسي"]] }[ME.role] || [];
  const ceiling = ["admin", "dean"].includes(ME.role) ? Object.keys(PL) : r.my_perms;
  const permBoxes = (sel, pre) => ceiling.map(k => `<label class="sw" style="margin:3px 0;color:inherit"><input type="checkbox" data-pm="${pre}" value="${k}" ${sel.includes(k) ? "checked" : ""}> ${esc(PL[k])}</label>`).join("");
  const picked = pre => [...document.querySelectorAll(`[data-pm="${pre}"]:checked`)].map(x => x.value);
  const fixedDept = ["head", "rapporteur"].includes(ME.role);
  main().innerHTML = `<div class="card"><h2>إضافة مستخدم</h2><p class="mut">${ME.role === "admin" ? "رئيس الجامعة يعيّن عميد كل كلية؛ والعميد يعيّن رئيس القسم ومقرره والتدريسيين ويحدد صلاحياتهم." : ME.role === "dean" ? "عميد الكلية: تحكم كامل بكليته. حدّد صلاحيات رئيس القسم، وبزر «تفويض المقرر» تسمح له بتحديد صلاحيات مقرر القسم." : "حسب ما منحك العميد."}</p>
    <div class="row"><div class="fix"><label>النوع</label><select id="ur">${roles.map(([k, n]) => `<option value="${k}">${n}</option>`).join("")}</select></div><div><label id="ul">اسم المستخدم</label><input id="uu" dir="ltr" style="width:100%"></div><div><label>الاسم الكامل (اختياري)</label><input id="un" style="width:100%"></div><div><label>كلمة المرور (6+)</label><input id="up" type="password" style="width:100%"></div></div>
    <div class="row" style="margin-top:8px" id="scope"><div id="cdiv"><label>الكلية</label><select id="uc" style="width:100%">${ORG.colleges.map(c => `<option value="${c.uid}">${esc(c.name)}</option>`).join("")}</select></div><div id="ddiv"><label>القسم</label>${fixedDept ? `<input disabled style="width:100%" value="${esc(deptName(ME.dept))}">` : `<select id="ud2" style="width:100%">${deptOpts("", ME.role === "admin" ? "— بدون قسم —" : "")}</select>`}</div></div>
    <div id="pdiv" style="margin-top:10px"><label>الصلاحيات</label><div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(230px,1fr))">${permBoxes([], "new")}</div>
    ${["admin", "dean"].includes(ME.role) ? '<label class="sw" id="delg" style="margin-top:8px;color:inherit"><input type="checkbox" id="ucd"> تفويض رئيس القسم بتحديد صلاحيات مقرر القسم</label>' : ""}</div>
    <div style="margin-top:12px"><button class="b g" id="uadd">إضافة</button></div></div>
  <div class="card"><h2>المستخدمون (${r.users.length})</h2><div class="tw"><table><thead><tr><th>المستخدم</th><th>النوع</th><th>النطاق</th><th>الصلاحيات</th><th></th></tr></thead><tbody>${r.users.map(u => `<tr><td dir="ltr" style="text-align:right"><b>${esc(u.username)}</b>${u.full_name ? `<br><span class="small mut" dir="rtl">${esc(u.full_name)}</span>` : ""}</td><td>${esc(u.role_ar)}${u.can_delegate ? ' <span class="pill wait">مفوَّض</span>' : ""}</td><td class="small">${esc(u.dept_uid ? deptName(u.dept_uid) : (ORG.colleges.find(c => c.uid === u.college_uid) || {}).name || "—")}${u.role === "doctor" ? `<br>${u.courses} مادة` : ""}</td><td class="small">${u.role === "dean" ? "كل صلاحيات الكلية" : u.role === "doctor" ? "مواده فقط" : u.perms.map(k => esc(PL[k])).join("، ") || "—"}</td>
    <td><div class="acts">${["head", "rapporteur"].includes(u.role) ? `<button class="b sm s" data-p="${u.id}">الصلاحيات</button>` : ""}<button class="b sm o" data-r="${u.id}">كلمة مرور</button><button class="b sm r" data-x="${u.id}">حذف</button></div></td></tr>`).join("") || '<tr><td colspan="5" class="mut">لا يوجد مستخدمون بعد</td></tr>'}</tbody></table></div></div>`;
  const upd = () => { const k = $("#ur").value; $("#ul").textContent = k === "doctor" ? "الإيميل الجامعي" : "اسم المستخدم"; $("#cdiv").hidden = !(k === "dean"); $("#ddiv").hidden = k === "dean"; $("#pdiv").hidden = !["head", "rapporteur"].includes(k); const dl = $("#delg"); if (dl) dl.hidden = k !== "head"; };
  $("#ur").onchange = upd; upd();
  $("#uadd").onclick = () => run(async () => { const k = $("#ur").value, v = $("#uu").value.trim();
    await api("/api/admin/users", "POST", { role: k, username: v, email: k === "doctor" ? v : "", full_name: $("#un").value, password: $("#up").value, college_uid: $("#uc") ? $("#uc").value : "", dept_uid: $("#ud2") ? $("#ud2").value : "", perms: picked("new"), can_delegate: !!($("#ucd") && $("#ucd").checked) }); users(); }, "تمت الإضافة");
  main().onclick = e => {
    const b = e.target.closest("button[data-p],button[data-r],button[data-x]"); if (!b) return; const u = r.users.find(x => String(x.id) === (b.dataset.p || b.dataset.r || b.dataset.x));
    if (b.dataset.x && confirm("حذف حساب «" + u.username + "»؟")) run(async () => { await api("/api/admin/users/" + u.id, "DELETE"); users(); }, "تم الحذف");
    if (b.dataset.r) { const pw = prompt("كلمة المرور الجديدة (6 أحرف فأكثر):"); if (pw) run(async () => { await api("/api/admin/users/" + u.id, "PUT", { password: pw }); }, "تم تغيير كلمة المرور"); }
    if (b.dataset.p) modal(`<h2>صلاحيات ${esc(u.username)}</h2>${permBoxes(u.perms, "ed")}${u.role === "head" && ["admin", "dean"].includes(ME.role) ? `<label class="sw" style="margin-top:8px;color:inherit"><input type="checkbox" id="edg" ${u.can_delegate ? "checked" : ""}> تفويضه بتحديد صلاحيات مقرر القسم</label>` : ""}<div class="row" style="margin-top:14px"><button class="b" id="sv">حفظ</button></div>`, m => {
      $("#sv").onclick = () => run(async () => { await api("/api/admin/users/" + u.id, "PUT", { perms: picked("ed"), can_delegate: !!($("#edg") && $("#edg").checked) }); m.remove(); users(); }, "تم الحفظ"); });
  };
}

// ───── الإعدادات ─────
async function settings() {
  const { settings: S, conf } = await api("/api/admin/settings");
  main().innerHTML = `<div class="card"><h2>الباركود والحضور</h2><div class="row">
    <div><label>تغيّر الباركود كل (ثانية)</label><input id="qr_interval" type="number" min="1" max="60" value="${esc(S.qr_interval)}" style="width:100%"></div>
    <div><label>مهلة فتح الرابط بعد مسحه (ثانية)</label><input id="scan_grace" type="number" min="1" value="${esc(S.scan_grace)}" style="width:100%"></div>
    <div><label>مدة المحاضرة الافتراضية (دقيقة)</label><input id="default_duration" type="number" min="1" value="${Math.round(S.default_duration / 60)}" style="width:100%"></div>
    <div><label>مهلة استلام الحضور بعد انتهاء المحاضرة — وقت التصدير (من 24 إلى 168 ساعة)</label><select id="max_sync_delay_hours" style="width:100%">${[24, 48, 72, 96, 120, 144, 168].map(h => `<option value="${h}" ${Math.min(168, Math.max(24, +S.max_sync_delay_hours || 48)) === h ? "selected" : ""}>${h} ساعة${h % 24 === 0 ? " (" + h / 24 + (h / 24 === 1 ? " يوم)" : " أيام)") : ""}</option>`).join("")}</select></div></div>
    <div class="row" style="margin-top:12px"><div><label>إنذار الغياب: يُلوَّن الطالب في Excel والتقارير إذا تجاوز غيابه (٪) — 0 لإيقافه</label><input id="absence_limit" type="number" min="0" max="100" value="${esc(S.absence_limit || "25")}" style="width:100%"></div></div>
    <div class="sw" style="margin-top:12px"><input type="checkbox" id="auto_export" ${S.auto_export === "1" ? "checked" : ""}><label style="margin:0;color:inherit">تصدير التقرير وإرساله تلقائياً بالإيميل عند انتهاء مهلة الاستلام (على السحابة)</label></div>
    <div class="sw" style="margin-top:12px"><input type="checkbox" id="mail_doctor" ${S.mail_doctor !== "0" ? "checked" : ""}><label style="margin:0;color:inherit">إرسال تقرير Excel لإيميل التدريسي مباشرة (وإلا يصل إليك أنت فقط لتحوّله له)</label></div>
    <div class="sw" style="margin-top:12px"><input type="checkbox" id="allow_offline_scan" ${S.allow_offline_scan === "1" ? "checked" : ""}><label style="margin:0;color:inherit">السماح بتسجيل الحضور بدون إنترنت على هاتف الطالب (يُرسل لاحقاً)</label></div>
    <div class="note">⏱ الباركود صالح مدة التغيير + المهلة (مثلاً 3 + 10 = 13 ثانية بعد ظهوره). كلما قلّلت المهلة صعُب إرسال الباركود لطالب غائب، وكلما زادت ارتاح الطلاب بطيئو الفتح.</div></div>
    <div class="card"><h2>المؤسسة والبريد</h2><div class="row"><div><label>اسم الجامعة (يظهر في التقارير)</label><input id="org_name" value="${esc(S.org_name)}" style="width:100%"></div><div><label>إيميل المسؤول (يصله نسخة من كل تقرير)</label><input id="admin_email" dir="ltr" value="${esc(S.admin_email)}" style="width:100%"></div></div>
    <h3>حساب الإرسال (SMTP)</h3><div class="row"><div><label>الخادم</label><input id="smtp_host" dir="ltr" value="${esc(S.smtp_host)}" style="width:100%"></div><div class="fix"><label>المنفذ</label><input id="smtp_port" dir="ltr" value="${esc(S.smtp_port)}" style="width:90px"></div><div><label>الإيميل المرسِل</label><input id="smtp_user" dir="ltr" value="${esc(S.smtp_user)}" style="width:100%"></div><div><label>كلمة مرور التطبيق</label><input id="smtp_pass" type="password" dir="ltr" value="${esc(S.smtp_pass)}" style="width:100%"></div></div>
    <div class="note">لـ Gmail: فعّل التحقق بخطوتين ثم أنشئ «App Password» من حساب Google واستخدمه هنا (لا تستخدم كلمة مرورك الأصلية). يُحفظ على خادم السحابة فقط ولا يُنسخ لأجهزة الدكاترة؛ وإن لم يتوفر إنترنت يبقى التقرير في «البريد» حتى يُرسل تلقائياً.</div></div>
    <button class="b g" id="save">حفظ الإعدادات</button>
    <div class="card" style="margin-top:18px;border:1px solid #d33"><h2 style="color:#d33">منطقة الخطر — تفريغ البرنامج</h2><p class="mut">يُحذف نهائياً من كل الأجهزة عند المزامنة. تبقى حسابات الدخول والإعدادات. لا يمكن التراجع (توجد نسخة احتياطية يومية على الجهاز).</p>
    <button class="b" id="wipe_att" style="background:#e67e22">حذف المحاضرات وسجلات الحضور فقط</button> <button class="b" id="wipe_all" style="background:#d33">تفريغ كل شيء (الطلاب والمواد والحضور)</button></div>`;
  const wipe = what => run(async () => {
    const t = prompt("للتأكيد اكتب كلمة: تفريغ"); if (t === null) return;
    const r = await api("/api/admin/wipe", "POST", { confirm: t, what });
    toast("تم التفريغ — حضور " + r.attendance + " ، محاضرات " + r.lectures + (r.students !== undefined ? " ، طلاب " + r.students + " ، مواد " + r.courses : ""));
  });
  $("#wipe_att").onclick = () => wipe("attendance"); $("#wipe_all").onclick = () => wipe("all");
  $("#save").onclick = () => run(async () => {
    const v = id => $("#" + id).value; const b = { org_name: v("org_name"), admin_email: v("admin_email"), qr_interval: v("qr_interval"), scan_grace: v("scan_grace"), default_duration: +v("default_duration") * 60, max_sync_delay_hours: v("max_sync_delay_hours"), allow_offline_scan: $("#allow_offline_scan").checked ? "1" : "0", mail_doctor: $("#mail_doctor").checked ? "1" : "0", absence_limit: v("absence_limit"), auto_export: $("#auto_export").checked ? "1" : "0", smtp_host: v("smtp_host"), smtp_port: v("smtp_port"), smtp_user: v("smtp_user"), smtp_pass: v("smtp_pass") };
    await api("/api/admin/settings", "PUT", b);
  }, "تم حفظ الإعدادات — ستصل أجهزة الدكاترة عند المزامنة القادمة");
}

// ───── البريد ─────
async function mail() {
  const { items } = await api("/api/admin/outbox");
  main().innerHTML = `<div class="card"><h2>صندوق الصادر</h2><p class="mut">كل «تصدير Excel» يُحفظ هنا ثم يُرسل فوراً، وإن لم يتوفر إنترنت أو فشل الإرسال يُعاد تلقائياً كل نصف دقيقة.</p><button class="b" id="rt">إعادة المحاولة الآن</button>
  <div class="tw" style="margin-top:10px"><table><thead><tr><th>الوقت</th><th>إلى</th><th>الموضوع</th><th>الحالة</th></tr></thead><tbody>${items.map(m => `<tr><td>${fmt(m.created_at)}</td><td dir="ltr" style="text-align:right">${esc(m.to_addrs)}</td><td>${esc(m.subject)}</td><td>${m.sent_at ? '<span class="pill ok">أُرسل</span>' : `<span class="pill wait">معلّق</span> <span class="small">${esc(m.last_error || "")}</span>`}</td></tr>`).join("") || '<tr><td colspan="4" class="mut">لا توجد رسائل</td></tr>'}</tbody></table></div></div>`;
  $("#rt").onclick = () => run(async () => { const r = await api("/api/admin/outbox", "POST"); toast(`أُرسل ${r.sent} — فشل ${r.failed}`, r.failed > 0); mail(); });
}
// ───── الطلبات والاعتماد (ضيوف، تغيير أجهزة، تقارير) ─────
const STAT = { pending: ["بانتظار القرار", "wait"], approved: ["موافَق", "ok"], rejected: ["مرفوض", "bad"], in_review: ["قيد الاعتماد", "wait"] };
const pill = st => { const x = STAT[st] || [st, "gray"]; return `<span class="pill ${x[1]}">${x[0]}</span>`; };
async function decide(url, label) {
  const note = prompt(label + "\nالملاحظة / السبب (إلزامي عند الرفض):", "");
  return note;
}
async function reqTab() {
  const [rq, rp, nt] = await Promise.all([api("/api/admin/x/requests?status=pending"), api("/api/admin/x/reports"), api("/api/admin/x/notifications")]);
  const dec = rq.can_decide;
  const btns = (kind, id) => dec ? `<div class="acts"><button class="b sm g" data-k="${kind}" data-id="${id}" data-d="approved">موافقة</button><button class="b sm r" data-k="${kind}" data-id="${id}" data-d="rejected">رفض</button></div>` : "";
  main().innerHTML = `${nt.items.length ? `<div class="card"><h2>🔔 الإشعارات</h2>${nt.items.slice(0, 8).map(n => `<div class="small">• <b>${esc(n.title)}</b> ${esc(n.body || "")} <span class="mut">${fmt(n.created_at)}</span></div>`).join("")}</div>` : ""}
    <div class="card"><h2>طلبات الطلبة الضيوف / التسجيل اليدوي (${rq.guests.length})</h2><div class="tw"><table><thead><tr><th>الطالب</th><th>مجموعته</th><th>المحاضرة</th><th>النوع</th><th>الوقت</th><th></th></tr></thead><tbody>${rq.guests.map(g => `<tr><td>${esc(g.name)}</td><td>${esc(g.home_grp || "—")}</td><td>${esc(g.course || "")} ${g.lec_grp ? "(" + esc(g.lec_grp) + ")" : ""}</td><td>${g.kind === "manual" ? "يدوي بالبريد" : "ضيف"}</td><td>${fmt(g.created_at)}</td><td>${btns("guest-requests", g.uid)}</td></tr>`).join("") || '<tr><td colspan="6" class="mut">لا توجد طلبات</td></tr>'}</tbody></table></div></div>
    <div class="card"><h2>طلبات تغيير الجهاز (${rq.device.length})</h2><div class="tw"><table><thead><tr><th>الطالب</th><th>البريد</th><th>السبب</th><th>الوقت</th><th></th></tr></thead><tbody>${rq.device.map(d => `<tr><td>${esc(d.name)}</td><td dir="ltr">${esc(d.email || d.univ_email || "")}</td><td>${esc(d.reason)}</td><td>${fmt(d.created_at)}</td><td>${btns("device-requests", d.uid)}</td></tr>`).join("") || '<tr><td colspan="5" class="mut">لا توجد طلبات</td></tr>'}</tbody></table></div>${dec ? "" : '<p class="small mut">البتّ في هذه الطلبات لرئيس القسم والعميد ورئيس الجامعة.</p>'}</div>
    <div class="card"><h2>تقارير المحاضرات وسلسلة الاعتماد</h2><div class="tw"><table><thead><tr><th>رقم التقرير</th><th>المادة</th><th>الحضور</th><th>الحالة</th><th>بانتظار</th><th>سجل الموافقات</th><th></th></tr></thead><tbody>${rp.reports.map(r => `<tr><td dir="ltr">${esc(r.number)}</td><td>${esc(r.summary.course || "")}</td><td>${r.summary.present}/${r.summary.total} (${r.summary.pct}%)</td><td>${pill(r.status)}</td><td>${r.status === "in_review" ? esc(rp.role_ar[r.waiting_for] || "") : "—"}</td><td class="small">${r.history.map(h => `${esc(h.position)}: ${h.decision === "approved" ? "✔" : "✖"} ${esc(h.full_name || h.user)}`).join("<br>") || "—"}</td><td><div class="acts"><a class="b sm s" href="/api/admin/x/reports/${r.uid}/file">Excel</a>${r.mine && r.status === "in_review" ? `<button class="b sm g" data-k="reports" data-id="${r.uid}" data-d="approved">اعتماد</button><button class="b sm r" data-k="reports" data-id="${r.uid}" data-d="rejected">رفض</button>` : ""}</div></td></tr>`).join("") || '<tr><td colspan="7" class="mut">لا توجد تقارير بعد. تُنشأ تلقائياً بعد انتهاء مهلة الاستلام، أو من «المحاضرات والحضور».</td></tr>'}</tbody></table></div></div>`;
  main().onclick = e => {
    const b = e.target.closest("button[data-k]"); if (!b) return;
    const d = b.dataset.d; const note = prompt((d === "approved" ? "تأكيد الموافقة" : "سبب الرفض (إلزامي)") + ":", "");
    if (note === null) return;
    run(async () => { await api(`/api/admin/x/${b.dataset.k}/${b.dataset.id}/decide`, "POST", { decision: d, note }); reqTab(); }, "تم تسجيل القرار");
  };
}
async function auditTab() {
  const r = await api("/api/admin/x/audit");
  main().innerHTML = `<div class="card"><h2>سجل التدقيق الإداري</h2>${ME.role === "admin" ? `<p>${r.chain_ok ? '<span class="pill ok">سلسلة السجل سليمة ✓</span>' : `<span class="pill bad">تم اكتشاف تلاعب عند السجل رقم ${r.broken_at}</span>`}</p>` : ""}<p class="small mut">لا يمكن تعديل هذا السجل أو حذفه حتى من المسؤول. آخر 300 عملية.</p><div class="tw"><table><thead><tr><th>الوقت</th><th>المستخدم</th><th>الدور</th><th>العملية</th><th>الهدف</th><th>القرار</th><th>السبب</th></tr></thead><tbody>${r.items.map(a => `<tr><td>${fmt(a.ts)}</td><td>${esc(a.actor)}</td><td>${esc(a.role)}</td><td dir="ltr" style="text-align:right">${esc(a.action)}</td><td dir="ltr" style="text-align:right">${esc((a.target || "").slice(0, 24))}</td><td>${esc(a.decision || "")}</td><td>${esc(a.reason || "")}</td></tr>`).join("")}</tbody></table></div></div>`;
}
async function advTab() {
  const [{ settings: S }, { chain, roles }, bk] = await Promise.all([api("/api/admin/settings"), api("/api/admin/x/chain"), api("/api/admin/x/backups")]);
  const chk = (id, label, v) => `<div class="sw" style="margin-top:10px"><input type="checkbox" id="${id}" ${v === "1" ? "checked" : ""}><label style="margin:0;color:inherit">${label}</label></div>`;
  const inp = (id, label, v, extra = "") => `<div><label>${label}</label><input id="${id}" dir="ltr" value="${esc(v ?? "")}" style="width:100%" ${extra}></div>`;
  main().innerHTML = `<div class="card"><h2>الحضور والأجهزة</h2><div class="row">${inp("email_domain", "نطاق البريد الجامعي المسموح (مثال: university.edu.iq)", S.email_domain)}${inp("late_after_min", "يُعدّ متأخراً بعد (دقيقة من بداية المحاضرة، 0 = تعطيل)", S.late_after_min, 'type="number" min="0"')}${inp("report_hour", "ساعة إنشاء التقارير التلقائية (0-23، الافتراضي 2 فجراً)", S.report_hour, 'type="number" min="0" max="23"')}</div>
    ${chk("require_device_sig", "إلزام جهاز الطالب بمفتاح تشفير معتمد (فعّله بعد أن يحدّث الطلاب التطبيق ويسجّلوا الدخول مرة)", S.require_device_sig)}${chk("report_mode", "إرسال التقارير تلقائياً بدون أي زر اعتماد (Zero-Click) للدكتور ورئيس القسم والعميد ورئيس الجامعة", S.report_mode === "auto" ? "1" : "0")}${chk("manual_checkin", "السماح بالتسجيل اليدوي بالبريد الجامعي (يحتاج موافقة المسؤول)", S.manual_checkin)}</div>
    <div class="card"><h2>سلسلة اعتماد التقارير (بالترتيب)</h2><p class="small mut">لا ينتقل التقرير للمرحلة التالية إلا بعد موافقة المرحلة الحالية. حدّد المراحل المطلوبة:</p><div class="row">${Object.keys(roles).map(k => `<label style="display:flex;gap:6px;align-items:center;margin:0"><input type="checkbox" class="ch" value="${k}" ${chain.includes(k) ? "checked" : ""}> ${esc(roles[k])}</label>`).join("")}</div><p class="small mut">الترتيب الثابت: التدريسي ← مقرر القسم/منسق المادة ← رئيس القسم ← العميد ← رئيس الجامعة.</p></div>
    <div class="card"><h2>الدخول من أي شبكة (صفحة عامة + إرسال تلقائي)</h2><div class="row">${inp("public_url", "رابط الصفحة العام للباركود (مثال: https://hadir.netlify.app)", S.public_url)}${inp("relay_url", "رابط الإرسال التلقائي (مثال: https://hadir.netlify.app/.netlify/functions/attend)", S.relay_url)}</div><p class="small mut">بدونهما يفتح الباركود من شبكة الدكتور فقط. طريقة إنشاء الموقع: انظر README_SMART_AR.md (tools/build_static_site.py).</p></div>
    <div class="card"><h2>المزامنة عبر البريد الإلكتروني (IMAP/SMTP)</h2>${chk("mail_sync", "تفعيل مزامنة الحضور بالدفعات الموقّعة عبر البريد", S.mail_sync)}<div class="row" style="margin-top:10px">${inp("attendance_mailbox", "بريد استلام الدفعات (attendance@university.edu.iq)", S.attendance_mailbox)}${inp("imap_host", "خادم IMAP", S.imap_host)}${inp("imap_port", "منفذ IMAP", S.imap_port)}</div><div class="row" style="margin-top:8px">${inp("imap_user", "مستخدم IMAP", S.imap_user)}<div><label>كلمة مرور IMAP (App Password)</label><input id="imap_pass" type="password" value="${esc(S.imap_pass || "")}" style="width:100%"></div>${inp("imap_folder", "المجلد", S.imap_folder)}</div><p class="small mut">إعدادات SMTP في تبويب «الإعدادات». يحتاج مفتاح المزامنة SYNC_KEY نفسه على الخادم والأجهزة. للـ OAuth2 اضبط متغير البيئة MAIL_OAUTH2_TOKEN.</p></div>
    <button class="b g" id="saveadv">حفظ</button>
    <div class="card" style="margin-top:18px"><h2>النسخ الاحتياطي</h2><p class="small mut">نسخة يومية تلقائية مع فحص سلامة، تُحفظ آخر ${esc(S.backup_keep)} نسخة. الاستعادة: <span dir="ltr">python tools/restore_backup.py</span></p><div class="tw"><table><thead><tr><th>الوقت</th><th>الملف</th><th>الحجم</th><th>النتيجة</th></tr></thead><tbody>${bk.items.map(x => `<tr><td>${fmt(x.ts)}</td><td dir="ltr">${esc(x.file)}</td><td>${Math.round(x.size / 1024)} KB</td><td>${x.ok ? '<span class="pill ok">سليمة</span>' : '<span class="pill bad">فشل: ' + esc(x.detail) + "</span>"}</td></tr>`).join("") || '<tr><td colspan="4" class="mut">لا نسخ بعد</td></tr>'}</tbody></table></div></div>`;
  $("#saveadv").onclick = () => run(async () => {
    const v = id => $("#" + id).value, c = id => ($("#" + id).checked ? "1" : "0");
    await api("/api/admin/settings", "PUT", { public_url: v("public_url"), relay_url: v("relay_url"), email_domain: v("email_domain"), late_after_min: v("late_after_min"), report_hour: v("report_hour"), require_device_sig: c("require_device_sig"), report_mode: $("#report_mode").checked ? "auto" : "approval", manual_checkin: c("manual_checkin"), mail_sync: c("mail_sync"), attendance_mailbox: v("attendance_mailbox"), imap_host: v("imap_host"), imap_port: v("imap_port"), imap_user: v("imap_user"), imap_pass: v("imap_pass"), imap_folder: v("imap_folder") });
    const chs = [...document.querySelectorAll(".ch:checked")].map(x => x.value);
    await api("/api/admin/x/chain", "PUT", { chain: ["doctor", "rapporteur", "head", "dean", "admin"].filter(x => chs.includes(x)) });
  }, "تم الحفظ");
}
start();
})();
