import sys; 
import hmac, hashlib, time
def frag(lec):
    # مطابقة core.make_fragment (بدون استيراد db لتفادي إعداد المسارات)
    i = int(lec["interval_sec"]); t = int(time.time() // i * i)
    sig = hmac.new(lec["secret"].encode(), ("%s|%d|%d" % (lec["code"], t, i)).encode(), hashlib.sha256).hexdigest()[:12]
    return "AT1.%s.%d.%d.%s" % (lec["code"], t, i, sig)
