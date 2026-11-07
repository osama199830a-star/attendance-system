/* قارئ QR مكتوب بالكامل داخل المشروع (بدون أي مكتبة خارجية) — يعمل بدون إنترنت على أي متصفح/WebView.
   الاستخدام: QRDecode(rgbaData, width, height) → نص الباركود أو null.
   يدعم: وضع البايتات (UTF-8)، النسخ 1–14، المستويات L/M/Q/H، التدوير والمنظور، تصحيح الأخطاء Reed-Solomon. */
(function (root) {
"use strict";
// ───── جداول (نفس جداول المولّد في الخادم) ─────
const ECC_PER_BLOCK = [
  [-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30],
  [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24],
  [-1, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20],
  [-1, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24]];
const NUM_BLOCKS = [
  [-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4],
  [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9],
  [-1, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16],
  [-1, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16]];
const FMT_BITS = [1, 0, 3, 2];            // L M Q H  → رمز المستوى داخل معلومات الصيغة
const MAXV = 14;

// ───── حقل غالوا ─────
const EXP = new Uint8Array(512), LOG = new Uint8Array(256);
(function () { let x = 1; for (let i = 0; i < 255; i++) { EXP[i] = x; LOG[x] = i; x <<= 1; if (x & 0x100) x ^= 0x11d; } for (let i = 255; i < 512; i++) EXP[i] = EXP[i - 255]; })();
const gmul = (a, b) => (a === 0 || b === 0) ? 0 : EXP[LOG[a] + LOG[b]];
const gdiv = (a, b) => a === 0 ? 0 : EXP[(LOG[a] + 255 - LOG[b]) % 255];

// يصحح الكتلة في مكانها. يرجع true إن نجح.
function rsCorrect(cw, nEcc) {
  const n = cw.length, S = new Array(nEcc).fill(0); let bad = false;
  for (let j = 0; j < nEcc; j++) { let s = 0; for (let i = 0; i < n; i++) s = gmul(s, EXP[j]) ^ cw[i]; S[j] = s; if (s) bad = true; }
  if (!bad) return true;
  // Berlekamp–Massey
  let C = [1], B = [1], L = 0, m = 1, b = 1;
  for (let i = 0; i < nEcc; i++) {
    let d = S[i]; for (let j = 1; j <= L; j++) d ^= gmul(C[j] || 0, S[i - j]);
    if (d === 0) { m++; continue; }
    const T = C.slice(), coef = gdiv(d, b);
    while (C.length < B.length + m) C.push(0);
    for (let j = 0; j < B.length; j++) C[j + m] ^= gmul(coef, B[j]);
    if (2 * L <= i) { L = i + 1 - L; B = T; b = d; m = 1; } else m++;
  }
  if (L * 2 > nEcc) return false;
  // Chien: مواقع الأخطاء (القوة = n-1-index)
  const pos = [];
  for (let i = 0; i < n; i++) { const xinv = EXP[(255 - ((n - 1 - i) % 255)) % 255]; let v = 0, p = 1; for (let j = 0; j <= L; j++) { v ^= gmul(C[j] || 0, p); p = gmul(p, xinv); } if (v === 0) pos.push(i); }
  if (pos.length !== L) return false;
  // Forney: Ω = S(x)Λ(x) mod x^nEcc
  const omega = new Array(nEcc).fill(0);
  for (let i = 0; i < nEcc; i++) for (let j = 0; j <= Math.min(i, L); j++) omega[i] ^= gmul(C[j] || 0, S[i - j]);
  for (const i of pos) {
    const X = EXP[(n - 1 - i) % 255], Xinv = EXP[(255 - ((n - 1 - i) % 255)) % 255];
    let num = 0, p = 1; for (let j = 0; j < nEcc; j++) { num ^= gmul(omega[j], p); p = gmul(p, Xinv); }
    const lx = (255 - ((n - 1 - i) % 255)) % 255; let den = 0; for (let j = 1; j <= L; j += 2) den ^= gmul(C[j] || 0, EXP[(lx * (j - 1)) % 255]);
    if (den === 0) return false;
    cw[i] ^= gmul(X, gdiv(num, den));
  }
  for (let j = 0; j < nEcc; j++) { let s = 0; for (let i = 0; i < n; i++) s = gmul(s, EXP[j]) ^ cw[i]; if (s) return false; }
  return true;
}

// ───── صور: رمادي + عتبة محلية ─────
function binarize(d, w, h) {
  const g = new Uint8Array(w * h);
  for (let i = 0, j = 0; i < g.length; i++, j += 4) g[i] = (d[j] * 77 + d[j + 1] * 150 + d[j + 2] * 29) >> 8;
  const W = w + 1, I = new Float64Array(W * (h + 1));
  for (let y = 0; y < h; y++) { let row = 0; for (let x = 0; x < w; x++) { row += g[y * w + x]; I[(y + 1) * W + x + 1] = I[y * W + x + 1] + row; } }
  const r = Math.max(6, Math.round(Math.min(w, h) / 16)), bin = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) {
    const y0 = Math.max(0, y - r), y1 = Math.min(h, y + r + 1);
    for (let x = 0; x < w; x++) {
      const x0 = Math.max(0, x - r), x1 = Math.min(w, x + r + 1);
      const sum = I[y1 * W + x1] - I[y0 * W + x1] - I[y1 * W + x0] + I[y0 * W + x0], mean = sum / ((x1 - x0) * (y1 - y0));
      bin[y * w + x] = g[y * w + x] < mean - Math.max(10, mean * 0.06) ? 1 : 0;
    }
  }
  bin.g = g; bin.I = I; bin.W = W;   // نحتفظ بالرمادي والتكامل للعينات الدقيقة لاحقاً
  return bin;
}

// ───── كشف مربعات التحديد (finder) ─────
const near = (v, m, tol) => Math.abs(v - m) <= m * tol;
function ratioOK(a, b, c, d, e) {
  const t = a + b + c + d + e; if (t < 7) return 0; const m = t / 7;
  return (near(a, m, .6) && near(b, m, .6) && near(c, 3 * m, .6) && near(d, m, .6) && near(e, m, .6)) ? m : 0;
}
// يقيس النمط 1:1:3:1:1 على خط يمر بـ(x,y) باتجاه (dx,dy) ويرجع {m, off} (الإزاحة لمركز الشريط الأوسط)
function crossCheck(bin, w, h, x, y, dx, dy) {
  const at = k => { const xx = Math.round(x + dx * k), yy = Math.round(y + dy * k); return (xx < 0 || yy < 0 || xx >= w || yy >= h) ? -1 : bin[yy * w + xx]; };
  if (at(0) !== 1) return null;
  const run = (start, step, col) => { let k = start, n = 0; while (at(k) === col) { k += step; n++; if (n > 400) break; } return [n, k]; };
  const [c1, k1] = run(0, 1, 1), [c0, k0] = run(-1, -1, 1);  // الشريط الأسود الأوسط
  const cLen = c1 + c0, cStart = k0 + 1, cEnd = k1 - 1;
  const [b1] = run(cEnd + 1, 1, 0), [b0] = run(cStart - 1, -1, 0);
  const [e1] = run(cEnd + 1 + b1, 1, 1), [a1] = run(cStart - 1 - b0, -1, 1);
  const m = ratioOK(a1, b0, cLen, b1, e1); if (!m) return null;
  return { m, off: (cStart + cEnd) / 2 };
}
function findFinders(bin, w, h) {
  const cands = [];
  for (let y = 0; y < h; y += 1) {
    const runs = [], starts = []; let cur = bin[y * w], s = 0;
    for (let x = 1; x <= w; x++) { const v = x < w ? bin[y * w + x] : 1 - cur; if (v !== cur) { runs.push(x - s); starts.push(s); s = x; cur = v; } }
    const first = bin[y * w];   // لون أول شريط
    for (let i = 0; i + 4 < runs.length; i++) {
      if ((first ^ (i & 1)) !== 1) continue;   // نبدأ من شريط أسود
      const m0 = ratioOK(runs[i], runs[i + 1], runs[i + 2], runs[i + 3], runs[i + 4]); if (!m0) continue;
      const cx = starts[i + 2] + runs[i + 2] / 2 - 0.5;
      const v = crossCheck(bin, w, h, Math.round(cx), y, 0, 1); if (!v) continue;
      const cy = y + v.off, hh = crossCheck(bin, w, h, Math.round(cx), Math.round(cy), 1, 0); if (!hh) continue;
      const fx = Math.round(cx) + hh.off, m = (m0 + v.m + hh.m) / 3;
      let hit = false;
      for (const c of cands) if (Math.abs(c.x - fx) < c.m * 1.2 && Math.abs(c.y - cy) < c.m * 1.2 && near(c.m, m, .5)) { c.x = (c.x * c.n + fx) / (c.n + 1); c.y = (c.y * c.n + cy) / (c.n + 1); c.m = (c.m * c.n + m) / (c.n + 1); c.n++; hit = true; break; }
      if (!hit) cands.push({ x: fx, y: cy, m, n: 1 });
    }
  }
  return cands.filter(c => c.n >= 2);
}
const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
function pickTriples(c) {
  c.sort((a, b) => b.n - a.n); c = c.slice(0, 12); const out = [];
  for (let i = 0; i < c.length; i++) for (let j = i + 1; j < c.length; j++) for (let k = j + 1; k < c.length; k++) {
    const P = [c[i], c[j], c[k]], ms = P.map(p => p.m), mx = Math.max(...ms), mn = Math.min(...ms); if (mx / mn > 1.7) continue;
    const d = [dist(P[0], P[1]), dist(P[0], P[2]), dist(P[1], P[2])], s = d.slice().sort((a, b) => a - b);
    if (s[0] < 1 || Math.abs(s[0] - s[1]) > 0.35 * s[1] || Math.abs(s[2] - s[0] * 1.414) > 0.35 * s[0] * 1.414) continue;
    out.push({ P, score: (P[0].n + P[1].n + P[2].n) / (1 + Math.abs(s[0] - s[1]) / s[1]) });
  }
  return out.sort((a, b) => b.score - a.score).slice(0, 4).map(o => o.P);
}
function orderTriple(P) {
  const d01 = dist(P[0], P[1]), d02 = dist(P[0], P[2]), d12 = dist(P[1], P[2]); let tl, a, b;
  if (d12 >= d01 && d12 >= d02) { tl = P[0]; a = P[1]; b = P[2]; } else if (d02 >= d01 && d02 >= d12) { tl = P[1]; a = P[0]; b = P[2]; } else { tl = P[2]; a = P[0]; b = P[1]; }
  const cross = (a.x - tl.x) * (b.y - tl.y) - (a.y - tl.y) * (b.x - tl.x);
  return cross > 0 ? { tl, tr: a, bl: b } : { tl, tr: b, bl: a };
}

// ───── تحويل المنظور ─────
function homography(src, dst) {   // src: وحدات، dst: بكسلات → مصفوفة 3x3 (h) تحول src إلى dst
  const A = [], B = [];
  for (let i = 0; i < 4; i++) { const [x, y] = src[i], [u, v] = dst[i]; A.push([x, y, 1, 0, 0, 0, -u * x, -u * y]); B.push(u); A.push([0, 0, 0, x, y, 1, -v * x, -v * y]); B.push(v); }
  const n = 8; for (let i = 0; i < n; i++) A[i].push(B[i]);
  for (let i = 0; i < n; i++) {
    let p = i; for (let r = i + 1; r < n; r++) if (Math.abs(A[r][i]) > Math.abs(A[p][i])) p = r;
    if (Math.abs(A[p][i]) < 1e-12) return null; [A[i], A[p]] = [A[p], A[i]];
    for (let r = 0; r < n; r++) if (r !== i) { const f = A[r][i] / A[i][i]; for (let c = i; c <= n; c++) A[r][c] -= f * A[i][c]; }
  }
  const h = []; for (let i = 0; i < n; i++) h.push(A[i][n] / A[i][i]); h.push(1); return h;
}
const proj = (h, x, y) => { const k = h[6] * x + h[7] * y + h[8]; return [(h[0] * x + h[1] * y + h[2]) / k, (h[3] * x + h[4] * y + h[5]) / k]; };

// يبحث عن نمط المحاذاة (1:1:1:1:1) قرب الموضع المتوقع
function findAlignment(bin, w, h, px, py, m) {
  const R = Math.round(m * 5), best = []; 
  for (let y = Math.max(0, Math.round(py) - R); y <= Math.min(h - 1, Math.round(py) + R); y++) {
    const runs = [], starts = []; let cur = bin[y * w + Math.max(0, Math.round(px) - R)], s = Math.max(0, Math.round(px) - R); const xe = Math.min(w - 1, Math.round(px) + R);
    const col0 = cur;
    for (let x = s + 1; x <= xe; x++) { if (bin[y * w + x] !== cur) { runs.push(x - s); starts.push(s); s = x; cur = bin[y * w + x]; } }
    for (let i = 0; i + 4 < runs.length; i++) {
      if ((col0 ^ (i & 1)) !== 1) continue;
      const r = runs.slice(i, i + 5), mm = r.reduce((a, b) => a + b, 0) / 5;
      if (!r.every(v => near(v, mm, .6)) || !near(mm, m, .7)) continue;
      const cx = starts[i + 2] + r[2] / 2 - 0.5;
      const v = crossAlign(bin, w, h, Math.round(cx), y); if (!v) continue;
      best.push({ x: cx, y: y + v, d: Math.hypot(cx - px, y + v - py) });
    }
  }
  if (!best.length) return null; best.sort((a, b) => a.d - b.d);
  const f = best.filter(b => Math.hypot(b.x - best[0].x, b.y - best[0].y) < m * 1.5), ax = f.reduce((a, b) => a + b.x, 0) / f.length, ay = f.reduce((a, b) => a + b.y, 0) / f.length;
  return { x: ax, y: ay };
}
function crossAlign(bin, w, h, x, y) {
  const at = k => (y + k < 0 || y + k >= h) ? -1 : bin[(y + k) * w + x];
  if (at(0) !== 1) return 0;
  let u = 0; while (at(-u - 1) === 1) u++; let d = 0; while (at(d + 1) === 1) d++;
  const wu = (() => { let k = -u - 1, n = 0; while (at(k) === 0 && n < 100) { k--; n++; } return n; })(), wd = (() => { let k = d + 1, n = 0; while (at(k) === 0 && n < 100) { k++; n++; } return n; })();
  const mm = (u + d + 1);
  if (!near(wu, mm, .7) || !near(wd, mm, .7)) return 0;
  return (d - u) / 2;
}

// ───── بنية الرمز ─────
function alignPositions(ver) {
  if (ver === 1) return [];
  const n = Math.floor(ver / 7) + 2, size = ver * 4 + 17, step = (ver === 32) ? 26 : Math.floor((ver * 4 + n * 2 + 1) / (n * 2 - 2)) * 2;
  const res = [6], tail = []; let pos = size - 7; for (let i = 0; i < n - 1; i++) { tail.push(pos); pos -= step; } return res.concat(tail.reverse());
}
function funcMask(ver) {
  const n = ver * 4 + 17, f = new Uint8Array(n * n), set = (x, y) => { if (x >= 0 && y >= 0 && x < n && y < n) f[y * n + x] = 1; };
  for (let i = 0; i < 9; i++) for (let j = 0; j < 9; j++) set(i, j);                      // أعلى اليسار: مربع + فاصل + صيغة
  for (let i = 0; i < 8; i++) for (let j = 0; j < 9; j++) set(n - 1 - i, j);             // أعلى اليمين
  for (let i = 0; i < 9; i++) for (let j = 0; j < 8; j++) set(i, n - 1 - j);             // أسفل اليسار
  for (let i = 0; i < n; i++) { set(6, i); set(i, 6); }
  const ap = alignPositions(ver);
  for (let a = 0; a < ap.length; a++) for (let b = 0; b < ap.length; b++) { if ((a === 0 && b === 0) || (a === 0 && b === ap.length - 1) || (a === ap.length - 1 && b === 0)) continue; for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) set(ap[a] + dx, ap[b] + dy); }
  if (ver >= 7) for (let i = 0; i < 6; i++) for (let j = 0; j < 3; j++) { set(n - 11 + j, i); set(i, n - 11 + j); }
  return f;
}
const MASKS = [(x, y) => (x + y) % 2 === 0, (x, y) => y % 2 === 0, (x, y) => x % 3 === 0, (x, y) => (x + y) % 3 === 0, (x, y) => (((x / 3) | 0) + ((y / 2) | 0)) % 2 === 0,
  (x, y) => (x * y) % 2 + (x * y) % 3 === 0, (x, y) => ((x * y) % 2 + (x * y) % 3) % 2 === 0, (x, y) => (((x + y) % 2) + ((x * y) % 3)) % 2 === 0];
const FORMATS = (() => { const out = []; for (let e = 0; e < 4; e++) for (let m = 0; m < 8; m++) { const d = (FMT_BITS[e] << 3) | m; let r = d; for (let i = 0; i < 10; i++) r = (r << 1) ^ ((r >> 9) * 0x537); out.push({ e, m, bits: ((d << 10) | (r & 0x3ff)) ^ 0x5412 }); } return out; })();
const popc = v => { let c = 0; while (v) { c += v & 1; v >>= 1; } return c; };
function readFormat(M, n) {
  const g = (x, y) => M[y * n + x] ? 1 : 0; let a = 0, b = 0;
  for (let i = 0; i <= 5; i++) a |= g(8, i) << i; a |= g(8, 7) << 6; a |= g(8, 8) << 7; a |= g(7, 8) << 8; for (let i = 9; i < 15; i++) a |= g(14 - i, 8) << i;
  for (let i = 0; i < 8; i++) b |= g(n - 1 - i, 8) << i; for (let i = 8; i < 15; i++) b |= g(8, n - 15 + i) << i;
  let best = null, bd = 99; for (const f of FORMATS) { const d = Math.min(popc(f.bits ^ a), popc(f.bits ^ b)); if (d < bd) { bd = d; best = f; } }
  return bd <= 3 ? best : null;
}
function decodeMatrix(M, n, ver) {
  const fmt = readFormat(M, n); if (!fmt) return null;
  const f = funcMask(ver), mk = MASKS[fmt.m], bits = []; let up = true;
  for (let x = n - 1; x >= 1; x -= 2) { if (x === 6) x = 5; for (let k = 0; k < n; k++) { const y = up ? n - 1 - k : k; for (let c = 0; c < 2; c++) { const xx = x - c; if (!f[y * n + xx]) bits.push((M[y * n + xx] ? 1 : 0) ^ (mk(xx, y) ? 1 : 0)); } } up = !up; }
  const rawCw = Math.floor(((16 * ver + 128) * ver + 64 - (ver >= 2 ? ((25 * (Math.floor(ver / 7) + 2) - 10) * (Math.floor(ver / 7) + 2) - 55) : 0) - (ver >= 7 ? 36 : 0)) / 8);
  const cw = []; for (let i = 0; i < rawCw; i++) { let v = 0; for (let j = 0; j < 8; j++) v = (v << 1) | bits[i * 8 + j]; cw.push(v); }
  const nb = NUM_BLOCKS[fmt.e][ver], ecc = ECC_PER_BLOCK[fmt.e][ver], dataTotal = rawCw - ecc * nb, short = nb - (rawCw % nb);
  // إعادة الفك من التشابك
  const lens = []; for (let i = 0; i < nb; i++) lens.push(Math.floor(rawCw / nb) + (i < short ? 0 : 1) - ecc);
  const B = lens.map(l => new Array(l + ecc)); let p = 0;
  const maxData = Math.max(...lens); for (let i = 0; i < maxData; i++) for (let b = 0; b < nb; b++) if (i < lens[b]) B[b][i] = cw[p++];
  for (let i = 0; i < ecc; i++) for (let b = 0; b < nb; b++) B[b][lens[b] + i] = cw[p++];
  const data = [];
  for (let b = 0; b < nb; b++) { if (!rsCorrect(B[b], ecc)) return null; for (let i = 0; i < lens[b]; i++) data.push(B[b][i]); }
  // قراءة المقاطع
  let bp = 0; const rd = k => { let v = 0; for (let i = 0; i < k; i++) { v = (v << 1) | ((data[bp >> 3] >> (7 - (bp & 7))) & 1); bp++; } return v; };
  let out = []; const totalBits = data.length * 8;
  while (bp + 4 <= totalBits) {
    const mode = rd(4); if (mode === 0) break;
    if (mode === 4) { const len = rd(ver < 10 ? 8 : 16); for (let i = 0; i < len; i++) out.push(rd(8)); }
    else if (mode === 7) { rd(8); }   // ECI
    else return null;
  }
  try { return new TextDecoder("utf-8").decode(new Uint8Array(out)); } catch (e) { return String.fromCharCode.apply(null, out); }
}

function sampleGrid(bin, w, h, H, n, m) {
  const g = bin.g, I = bin.I, W = bin.W, M = new Uint8Array(n * n), R = Math.max(6, Math.round(m * 3.5));
  const gray = (x, y) => {   // استيفاء ثنائي الخطية
    if (x < 0 || y < 0 || x > w - 1 || y > h - 1) return -1; const x0 = Math.floor(x), y0 = Math.floor(y), x1 = Math.min(w - 1, x0 + 1), y1 = Math.min(h - 1, y0 + 1), fx = x - x0, fy = y - y0;
    return g[y0 * w + x0] * (1 - fx) * (1 - fy) + g[y0 * w + x1] * fx * (1 - fy) + g[y1 * w + x0] * (1 - fx) * fy + g[y1 * w + x1] * fx * fy;
  };
  const mean = (x, y) => { const xi = Math.round(x), yi = Math.round(y), x0 = Math.max(0, xi - R), x1 = Math.min(w, xi + R + 1), y0 = Math.max(0, yi - R), y1 = Math.min(h, yi + R + 1);
    return (I[y1 * W + x1] - I[y0 * W + x1] - I[y1 * W + x0] + I[y0 * W + x0]) / ((x1 - x0) * (y1 - y0)); };
  for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) {
    const [cx, cy] = proj(H, c + .5, r + .5); let v = gray(cx, cy); if (v < 0) continue;
    let s = v * 2, k = 2; for (const [dx, dy] of [[.25, 0], [-.25, 0], [0, .25], [0, -.25]]) { const [x, y] = proj(H, c + .5 + dx, r + .5 + dy), q = gray(x, y); if (q >= 0) { s += q; k++; } }
    M[r * n + c] = (s / k) < mean(cx, cy) ? 1 : 0;
  }
  return M;
}
// حجم الوحدة (module) الحقيقي على محور الرمز نفسه (القياس الأفقي يُكبَّر عند التدوير)
function axisModule(bin, w, h, p, q) {
  const L = Math.hypot(q.x - p.x, q.y - p.y), dx = (q.x - p.x) / L, dy = (q.y - p.y) / L; let phase = 0;
  for (let k = 0; k < p.m * 6 * 4; k++) {
    const t = k / 4, x = Math.round(p.x + dx * t), y = Math.round(p.y + dy * t); if (x < 0 || y < 0 || x >= w || y >= h) return 0;
    const v = bin[y * w + x]; if ((phase % 2 === 0) !== (v === 1)) { phase++; if (phase === 3) return t / 3.5; }
  }
  return 0;
}
// تحسين موضع مركز النمط (مربع تحديد أو محاذاة) بالمطابقة مع القالب المثالي على الرمادي — دقة أقل من بكسل
function refineCenter(bin, w, h, p, u, v, kind) {
  const g = bin.g, half = kind === "f" ? 3.5 : 2.5;
  const gray = (x, y) => { if (x < 0 || y < 0 || x > w - 1 || y > h - 1) return null; const x0 = Math.floor(x), y0 = Math.floor(y), x1 = Math.min(w - 1, x0 + 1), y1 = Math.min(h - 1, y0 + 1), fx = x - x0, fy = y - y0;
    return g[y0 * w + x0] * (1 - fx) * (1 - fy) + g[y0 * w + x1] * fx * (1 - fy) + g[y1 * w + x0] * (1 - fx) * fy + g[y1 * w + x1] * fx * fy; };
  const pts = [];   // نقاط القالب (في إحداثيات الوحدات) مع قيمتها المتوقعة
  for (let a = -half; a <= half + 1e-9; a += 0.5) for (let b = -half; b <= half + 1e-9; b += 0.5) {
    const r = Math.max(Math.abs(a), Math.abs(b)); let t;
    if (kind === "f") t = r <= 1.5 ? 1 : r <= 2.5 ? -1 : 1; else t = r <= 0.5 ? 1 : r <= 1.5 ? -1 : 1;
    if (Math.abs(r - 1.5) < 0.26 || Math.abs(r - 2.5) < 0.26 && kind === "f" || Math.abs(r - 0.5) < 0.26 && kind === "a" || Math.abs(r - 1.5) < 0.26 && kind === "a") continue;  // نتجاهل الحواف الضبابية
    pts.push([a, b, t]);
  }
  const score = (cx, cy) => { let sum = 0, cnt = 0, acc = []; for (const [a, b, t] of pts) { const x = cx + u.x * a + v.x * b, y = cy + u.y * a + v.y * b, q = gray(x, y); if (q === null) return -1e9; acc.push(q); } const mean = acc.reduce((x, y) => x + y, 0) / acc.length; let k = 0; for (const [, , t] of pts) { sum += t * (mean - acc[k++]); cnt++; } return sum / cnt; };
  const ml = Math.hypot(u.x, u.y);
  let best = { x: p.x, y: p.y, s: score(p.x, p.y) };
  for (const [step, R] of [[ml * 0.5, ml * 1.6], [ml * 0.15, ml * 0.6], [ml * 0.05, ml * 0.2]]) {
    const cx0 = best.x, cy0 = best.y;
    for (let dx = -R; dx <= R + 1e-9; dx += step) for (let dy = -R; dy <= R + 1e-9; dy += step) { const sc = score(cx0 + dx, cy0 + dy); if (sc > best.s) best = { x: cx0 + dx, y: cy0 + dy, s: sc }; }
  }
  return best;
}
function tryTriple(bin, w, h, T) {
  const o = orderTriple(T); let { tl, tr, bl } = o;
  const mu = axisModule(bin, w, h, tl, tr), mv = axisModule(bin, w, h, tl, bl), m = (mu && mv) ? (mu + mv) / 2 : (tl.m + tr.m + bl.m) / 3;
  const d = (dist(tl, tr) + dist(tl, bl)) / 2 / m + 7;
  const v0 = Math.round((d - 17) / 4), tried = [];
  for (const v of [v0, v0 - 1, v0 + 1]) {
    if (v < 1 || v > MAXV || tried.includes(v)) continue; tried.push(v);
    const n = 17 + 4 * v;
    let u = { x: (tr.x - tl.x) / (n - 7), y: (tr.y - tl.y) / (n - 7) }, vv = { x: (bl.x - tl.x) / (n - 7), y: (bl.y - tl.y) / (n - 7) };
    // تحسين مراكز المربعات الثلاثة
    const R = [tl, tr, bl].map(q => { const r = refineCenter(bin, w, h, q, u, vv, "f"); return { x: r.x, y: r.y, m: q.m }; });
    const tl2 = R[0], tr2 = R[1], bl2 = R[2];
    u = { x: (tr2.x - tl2.x) / (n - 7), y: (tr2.y - tl2.y) / (n - 7) }; vv = { x: (bl2.x - tl2.x) / (n - 7), y: (bl2.y - tl2.y) / (n - 7) };
    const at = (mx, my) => ({ x: tl2.x + u.x * (mx - 3.5) + vv.x * (my - 3.5), y: tl2.y + u.y * (mx - 3.5) + vv.y * (my - 3.5) });
    const base = [[[3.5, 3.5], tl2], [[n - 3.5, 3.5], tr2], [[3.5, n - 3.5], bl2]], variants = [];
    if (v >= 2) {
      const pa = at(n - 6.5, n - 6.5), a1 = refineCenter(bin, w, h, pa, u, vv, "a");
      if (a1.s > 8) variants.push([[n - 6.5, n - 6.5], { x: a1.x, y: a1.y }]);
    }
    variants.push([[n - 3.5, n - 3.5], at(n - 3.5, n - 3.5)]);
    for (const extra of variants) {
      const pts = base.concat([extra]), H = homography(pts.map(q => q[0]), pts.map(q => [q[1].x, q[1].y])); if (!H) continue;
      const res = decodeMatrix(sampleGrid(bin, w, h, H, n, m), n, v); if (res !== null) return res;
    }
  }
  return null;
}
function QRDecode(data, w, h) {
  const bin = binarize(data, w, h), c = findFinders(bin, w, h); if (c.length < 3) return null;
  for (const T of pickTriples(c)) { const r = tryTriple(bin, w, h, T); if (r !== null) return r; }
  return null;
}
root.QRDecode = QRDecode;
// واجهة مطابقة لمكتبة jsQR حتى يعمل الكود نفسه معها أو بدونها
if (!root.jsQR) root.jsQR = (d, w, h) => { const t = QRDecode(d, w, h); return t === null ? null : { data: t }; };
})(typeof window !== "undefined" ? window : globalThis);
