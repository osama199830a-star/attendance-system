#!/bin/bash
# تثبيت الخادم على Ubuntu Server (بدون Docker): sudo bash ubuntu_setup.sh
set -e
apt-get update && apt-get install -y python3 python3-venv python3-pip
APP=/opt/attendance
mkdir -p $APP && cp -r server cloud requirements.txt tools $APP/ 2>/dev/null || cp -r . $APP/
cd $APP && python3 -m venv .venv && .venv/bin/pip install -r cloud/requirements.txt
[ -f $APP/.env ] || { cp .env.example $APP/.env 2>/dev/null || true; echo "عدّل $APP/.env (ADMIN_PASS و SYNC_KEY) ثم أعد تشغيل الخدمة"; }
cat > /etc/systemd/system/attendance.service <<S
[Unit]
Description=Attendance server
After=network.target
[Service]
WorkingDirectory=$APP/server
EnvironmentFile=$APP/.env
Environment=ATT_MODE=cloud ATT_DATA=/var/lib/attendance
ExecStart=$APP/.venv/bin/gunicorn wsgi:application -b 0.0.0.0:8000 -w 1 --threads 8 --timeout 90
Restart=always
[Install]
WantedBy=multi-user.target
S
mkdir -p /var/lib/attendance
systemctl daemon-reload && systemctl enable --now attendance
echo "يعمل على المنفذ 8000. ضع خلفه Nginx/Caddy لـ HTTPS (مثال: caddy reverse-proxy --from attendance.univ.edu.iq --to :8000)"
