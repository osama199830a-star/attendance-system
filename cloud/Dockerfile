FROM python:3.12-slim
WORKDIR /app
COPY cloud/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server/ /app/server/
RUN python -c "import urllib.request as u;u.urlretrieve('https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.js','/app/server/static/student/jsqr.js')" || true
ENV ATT_MODE=cloud ATT_DATA=/data PYTHONUNBUFFERED=1
VOLUME /data
WORKDIR /app/server
# عامل واحد + خيوط: قاعدة SQLite واحدة، ولا نريد إرسال الإيميلات مرتين
CMD gunicorn wsgi:application -b 0.0.0.0:${PORT:-8000} -w 1 --threads 8 --timeout 90
