# -*- coding: utf-8 -*-
"""توليد باركود متغيّر كل 30 ثانية (TOTP — RFC 6238) يعتمد على الساعة المحلية فقط، بلا إنترنت.
تشغيل:  python totp_qr.py --secret MYSECRET --lecture CS101-0001 [--step 30]
يطبع رمز اللحظة، ويحفظ qr_now.png إن كانت مكتبة qrcode مثبتة (pip install qrcode[pil])."""
import argparse, base64, hashlib, hmac, struct, time

def totp(secret: bytes, t=None, step=30, digits=8, algo=hashlib.sha1):
    c = int((time.time() if t is None else t) // step)
    h = hmac.new(secret, struct.pack(">Q", c), algo).digest()
    o = h[-1] & 0x0F
    return str((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** digits).zfill(digits)

def qr_payload(secret, lecture, step=30, t=None):
    """ما يُشفَّر داخل QR: المحاضرة + رقم الفترة + الرمز. يتحقق الخادم بإعادة الحساب (مع سماح ±1 فترة لفرق الساعات)."""
    now = time.time() if t is None else t
    slot = int(now // step)
    return "AT2.%s.%d.%s" % (lecture, slot, totp(secret, now, step))

def verify(secret, lecture, payload, step=30, window=1, t=None):
    try:
        tag, lec, slot, code = payload.split(".")
        slot = int(slot)
    except ValueError:
        return False
    now_slot = int((time.time() if t is None else t) // step)
    return tag == "AT2" and lec == lecture and abs(now_slot - slot) <= window and hmac.compare_digest(code, totp(secret, slot * step, step))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--secret", required=True); ap.add_argument("--lecture", required=True); ap.add_argument("--step", type=int, default=30)
    a = ap.parse_args(); sec = a.secret.encode()
    p = qr_payload(sec, a.lecture, a.step); print(p, "— يتبقى %d ثانية" % (a.step - time.time() % a.step))
    try:
        import qrcode; qrcode.make(p).save("qr_now.png"); print("حُفظ qr_now.png")
    except ImportError:
        print("(ثبّت qrcode لإنشاء صورة الباركود)")
