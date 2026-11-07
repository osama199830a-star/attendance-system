// ينسخ واجهة الطالب إلى www ويكتب رابط السحابة داخل التطبيق (متغير البيئة CLOUD_URL)
const fs = require("fs"), path = require("path");
const src = path.join(__dirname, "..", "..", "server", "static", "student");
const dst = path.join(__dirname, "..", "www");
fs.rmSync(dst, { recursive: true, force: true });
fs.cpSync(src, dst, { recursive: true });
const url = (process.env.CLOUD_URL || "").replace(/\/+$/, "");
const rf0 = path.join(__dirname, "..", "roster.json");
fs.writeFileSync(path.join(dst, "config.js"), `window.APP_CONFIG = { base: ${JSON.stringify(url)}, embedded: ${fs.existsSync(rf0)} };\n`);
// داخل التطبيق لا نستخدم service worker (الملفات محلية أصلاً)
fs.writeFileSync(path.join(dst, "sw.js"), "self.addEventListener('fetch',()=>{});\n");
// قائمة الأسماء المضمّنة (اختيارية): تُنسخ داخل التطبيق ليعمل من أول فتح بلا اتصال
const rf = path.join(__dirname, "..", "roster.json");
if (fs.existsSync(rf)) { fs.copyFileSync(rf, path.join(dst, "roster.json")); console.log("roster.json embedded:", JSON.parse(fs.readFileSync(rf, "utf8")).students.length, "students"); }
console.log("www ready, base =", url || "(فارغ — يُدخل من إعدادات التطبيق)");
