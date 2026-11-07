# -*- coding: utf-8 -*-
"""شهادة HTTPS ذاتية التوقيع للشبكة المحلية (ضرورية لتشغيل الكاميرا على الموبايل)."""
import datetime, ipaddress, os, socket
from config import CERT_DIR


_IP_CACHE = {"t": 0, "v": None, "busy": False}


def _scan_ips():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("10.255.255.255", 1))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:   # قد يتأخر كثيراً على ويندوز (DNS/NetBIOS) لذلك يُنفَّذ في خيط مع مهلة
        for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(i[4][0])
    except Exception:
        pass
    ips.discard("127.0.0.1")
    return sorted(ips)


def local_ips(max_age=60):
    """عناوين الجهاز: تُرجَع فوراً من الذاكرة دائماً، ويُحدَّث المسح في الخلفية (لا يُبطئ زر «بدء» أبداً)."""
    import threading, time
    now = time.time()
    if _IP_CACHE["v"] is None:                 # أول مرة فقط: ننتظر حتى ثانية واحدة
        _refresh_ips(wait=1.0)
    elif now - _IP_CACHE["t"] >= max_age and not _IP_CACHE["busy"]:
        _refresh_ips(wait=0)
    return list(_IP_CACHE["v"] or [])


def _refresh_ips(wait=0):
    import threading, time
    _IP_CACHE["busy"] = True

    def work():
        try:
            _IP_CACHE["v"], _IP_CACHE["t"] = _scan_ips(), time.time()
        finally:
            _IP_CACHE["busy"] = False
    th = threading.Thread(target=work, daemon=True)
    th.start()
    if wait:
        th.join(wait)


def lan_ip():
    ips = local_ips()
    for p in ("192.168.", "10.", "172."):
        for ip in ips:
            if ip.startswith(p):
                return ip
    return ips[0] if ips else "127.0.0.1"


def ensure_cert():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    os.makedirs(CERT_DIR, exist_ok=True)
    crt, key, ipf = (os.path.join(CERT_DIR, n) for n in ("server.crt", "server.key", "ips.txt"))
    ips = local_ips() + ["127.0.0.1"]
    if os.path.exists(crt) and os.path.exists(key) and os.path.exists(ipf):
        if open(ipf).read().split() == ips:
            return crt, key
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Attendance Local")])
    san = [x509.DNSName("localhost")] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    now = datetime.datetime.utcnow()
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(k.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .sign(k, hashes.SHA256()))
    with open(key, "wb") as f:
        f.write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                serialization.NoEncryption()))
    with open(crt, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    open(ipf, "w").write("\n".join(ips))
    return crt, key
