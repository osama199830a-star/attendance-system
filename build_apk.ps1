# ============================================================
#  بناء تطبيق الطالب (APK) على ويندوز بأمر واحد
#  الاستعمال (PowerShell داخل مجلد المشروع):
#    powershell -ExecutionPolicy Bypass -File build_apk.ps1 -ServerUrl "http://192.168.10.209:5000"
#
#  -ServerUrl : عنوان برنامج الدكتور على الشبكة. استعمل http وبمنفذ 5000
#               (وليس https:5443 لأن شهادته ذاتية والتطبيق يرفضها).
#               إن كان لديك سيرفر سحابي ضع رابطه https هنا بدلاً من ذلك.
#  يحتاج إنترنت مرة واحدة فقط أثناء البناء. أول مرة ١٥–٣٠ دقيقة.
# ============================================================
param(
  [Alias("CloudUrl")][string]$ServerUrl = "",
  [string]$RosterFile = ""     # ملف الأسماء (roster.json). إن لم يُحدد يُجلب تلقائياً من الخادم
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
function Has($c) { return [bool](Get-Command $c -ErrorAction SilentlyContinue) }
function Refresh-Path { $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User") }
function Write-NoBom($path, $text) { [System.IO.File]::WriteAllText((Join-Path (Get-Location) $path), $text, (New-Object System.Text.UTF8Encoding($false))) }

if ($root -match "[^\x00-\x7F]" -or $root -match "\s") {
  Write-Warning "مسار المشروع فيه مسافات أو حروف عربية وقد يفشل Gradle. الأفضل نسخ المجلد إلى مسار بسيط مثل C:\attendance-system"
}
if ($ServerUrl -eq "") { Write-Warning "لم تحدد -ServerUrl: سيُطلب من الطالب كتابة العنوان يدوياً من الإعدادات المتقدمة. الأفضل تحديده الآن." }
if ($ServerUrl -match "^https://\d+\.\d+\.\d+\.\d+") { Write-Warning "العنوان HTTPS على IP محلي (شهادة ذاتية) والتطبيق سيرفضه. استعمل http://IP:5000" }

if ($ServerUrl -ne "") {
  try { Invoke-WebRequest ($ServerUrl.TrimEnd("/") + "/api/time") -UseBasicParsing -TimeoutSec 8 | Out-Null; Write-Host "الخادم يردّ على $ServerUrl" -ForegroundColor Green }
  catch { Write-Warning "الخادم لا يردّ الآن على $ServerUrl — تأكد أن برنامج الدكتور شغّال وأنك على نفس الشبكة. سيكتمل البناء ويمكن تغيير العنوان لاحقاً من داخل التطبيق (إعدادات متقدمة) أو يتعلّمه التطبيق تلقائياً من الباركود." }
}

# ── 1) الأدوات: Node و Java 17 ──
if (-not (Has node)) { Write-Host "تثبيت Node.js ..."; winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements; Refresh-Path }
if (-not (Has java)) { Write-Host "تثبيت Java 17 ..."; winget install -e --id EclipseAdoptium.Temurin.17.JDK --accept-source-agreements --accept-package-agreements; Refresh-Path }
if (-not (Has node) -or -not (Has java)) { throw "أغلق PowerShell وافتحه من جديد ثم أعد تشغيل الأمر (لتحديث المسارات)." }

# ── 2) أدوات أندرويد (SDK) ──
$sdk = Join-Path $env:LOCALAPPDATA "Android\Sdk"
$sm = Join-Path $sdk "cmdline-tools\latest\bin\sdkmanager.bat"
if (-not (Test-Path $sm)) {
  Write-Host "تنزيل أدوات أندرويد ..."
  New-Item -ItemType Directory -Force $sdk | Out-Null
  $zip = Join-Path $env:TEMP "cmdtools.zip"
  Invoke-WebRequest "https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip" -OutFile $zip
  $tmp = Join-Path $env:TEMP "cmdtools"; Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
  Expand-Archive $zip $tmp -Force
  New-Item -ItemType Directory -Force (Join-Path $sdk "cmdline-tools") | Out-Null
  Move-Item (Join-Path $tmp "cmdline-tools") (Join-Path $sdk "cmdline-tools\latest") -Force
}
$env:ANDROID_HOME = $sdk; $env:ANDROID_SDK_ROOT = $sdk
Write-Host "قبول التراخيص وتثبيت الحزم ..."
(1..30 | ForEach-Object { "y" }) | & $sm --licenses | Out-Null
& $sm "platform-tools" "platforms;android-34" "build-tools;34.0.0"

# ── 3) واجهة الطالب → مشروع Capacitor ──
Set-Location (Join-Path $root "mobile")
$env:CLOUD_URL = $ServerUrl
npm install
if ($LASTEXITCODE -ne 0) { throw "فشل npm install" }
# قائمة الأسماء: تُضمَّن داخل التطبيق ليعمل من أول فتح بدون اتصال
if ($RosterFile -ne "") { Copy-Item $RosterFile "roster.json" -Force }
elseif ($ServerUrl -ne "") {
  try { Invoke-WebRequest ($ServerUrl.TrimEnd("/") + "/api/student/roster") -UseBasicParsing -TimeoutSec 20 -OutFile "roster.json" }
  catch { Write-Warning "تعذّر جلب الأسماء من $ServerUrl (هل الخادم شغّال وأنت على شبكته؟). سيُبنى التطبيق بدون أسماء مضمّنة." }
}
if (Test-Path "roster.json") {
  try { $n = (Get-Content "roster.json" -Raw -Encoding UTF8 | ConvertFrom-Json).students.Count; Write-Host "عدد الأسماء المضمّنة: $n" } catch { Write-Warning "ملف roster.json غير صالح، حُذف."; Remove-Item "roster.json" -Force }
}
node scripts/prepare.js
if (-not (Test-Path "android")) { npx cap add android; if ($LASTEXITCODE -ne 0) { throw "فشل cap add android" } }

# أيقونة التطبيق
New-Item -ItemType Directory -Force "assets" | Out-Null
Copy-Item (Join-Path $root "assets\icon-1024.png") "assets\icon-only.png" -Force
Copy-Item (Join-Path $root "assets\icon-1024.png") "assets\icon-foreground.png" -Force
try { npx capacitor-assets generate --android --iconBackgroundColor "#2c5599" --iconBackgroundColorDark "#2c5599" } catch { Write-Warning "تخطّي توليد الأيقونة (غير مهم)" }
npx cap sync android
if ($LASTEXITCODE -ne 0) { throw "فشل cap sync" }

# رقم إصدار أعلى في كل بناء حتى يُثبَّت فوق القديم دون حذفه (فيبقى ربط الاسم والحضور المحفوظ)
$gr = "android\app\build.gradle"
if (Test-Path $gr) {
  $g = [System.IO.File]::ReadAllText((Join-Path (Get-Location) $gr))
  $vc = [int]([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() / 60)
  $g = $g -replace 'versionCode \d+', "versionCode $vc" -replace 'versionName "[^"]*"', 'versionName "2.1"'
  Write-NoBom $gr $g
}

# ── 4) صلاحيات: الكاميرا + السماح باتصال HTTP على الشبكة المحلية ──
$man = "android\app\src\main\AndroidManifest.xml"
$x = [System.IO.File]::ReadAllText((Join-Path (Get-Location) $man))
if ($x -notmatch "android.permission.CAMERA") {
  $x = $x -replace "</manifest>", "    <uses-permission android:name=`"android.permission.CAMERA`" />`n</manifest>"
}
if ($x -notmatch "usesCleartextTraffic") {
  $x = $x -replace "<application", "<application android:usesCleartextTraffic=`"true`""
}
Write-NoBom $man $x
Write-NoBom "android\local.properties" ("sdk.dir=" + ($sdk -replace "\\","/") + "`n")

# ── 5) البناء ──
Set-Location android
.\gradlew.bat assembleDebug --no-daemon
if ($LASTEXITCODE -ne 0) { throw "فشل البناء — أرسل لي نص الخطأ أعلاه." }
$apk = "app\build\outputs\apk\debug\app-debug.apk"
if (-not (Test-Path $apk)) { throw "لم يُنتَج ملف APK — أرسل لي نص الخطأ أعلاه." }
$out = Join-Path ([Environment]::GetFolderPath("Desktop")) "Attendance-Student.apk"
Copy-Item $apk $out -Force
Write-Host ""
Write-Host "تم! الملف على سطح المكتب: $out" -ForegroundColor Green
Write-Host "العنوان المدمج في التطبيق: $ServerUrl"
