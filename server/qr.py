# -*- coding: utf-8 -*-
"""مولّد QR نقي بلغة بايثون (بدون أي مكتبة خارجية) — وضع البايتات، النسخ 1-14.
يُرجع مصفوفة وحدات (True = أسود). مبني على مواصفة ISO/IEC 18004."""

ECC_PER_BLOCK = [
    [-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30],
    [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24],
    [-1, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20],
    [-1, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24],
]
NUM_BLOCKS = [
    [-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4],
    [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9],
    [-1, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16],
    [-1, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16],
]
LEVELS = {"L": 0, "M": 1, "Q": 2, "H": 3}
FORMAT_BITS = {"L": 1, "M": 0, "Q": 3, "H": 2}
MAX_VERSION = 14


def _align_positions(ver):
    if ver == 1:
        return []
    n = ver // 7 + 2
    size = ver * 4 + 17
    step = 26 if ver == 32 else (ver * 4 + n * 2 + 1) // (n * 2 - 2) * 2
    res = [6]
    pos = size - 7
    tail = []
    for _ in range(n - 1):
        tail.append(pos)
        pos -= step
    return res + tail[::-1]


def _raw_modules(ver):
    size = ver * 4 + 17
    r = size * size - 8 * 8 * 3 - 15 * 2 - 1 - (size - 16) * 2
    if ver >= 2:
        n = ver // 7 + 2
        r -= (n - 1) ** 2 * 25 - ((n - 2) * 2 + (n - 2) * 2) * 0  # placeholder, corrected below
        r += 0
    return r


def _num_raw_data_modules(ver):
    result = (16 * ver + 128) * ver + 64
    if ver >= 2:
        n = ver // 7 + 2
        result -= (25 * n - 10) * n - 55
        if ver >= 7:
            result -= 36
    return result


def _num_data_codewords(ver, lvl):
    return _num_raw_data_modules(ver) // 8 - ECC_PER_BLOCK[lvl][ver] * NUM_BLOCKS[lvl][ver]


# ---- حقل غالوا GF(256) وريد-سولومون ----
_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _gmul(a, b):
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _rs_divisor(deg):
    res = [0] * (deg - 1) + [1]
    root = 1
    for _ in range(deg):
        for j in range(deg):
            res[j] = _gmul(res[j], root)
            if j + 1 < deg:
                res[j] ^= res[j + 1]
        root = _gmul(root, 2)
    return res


def _rs_remainder(data, divisor):
    res = [0] * len(divisor)
    for b in data:
        f = b ^ res.pop(0)
        res.append(0)
        for i, c in enumerate(divisor):
            res[i] ^= _gmul(c, f)
    return res


def _add_ecc_interleave(data, ver, lvl):
    nb = NUM_BLOCKS[lvl][ver]
    ecc_len = ECC_PER_BLOCK[lvl][ver]
    raw = _num_raw_data_modules(ver) // 8
    n_short = nb - raw % nb
    short_len = raw // nb
    blocks = []
    div = _rs_divisor(ecc_len)
    k = 0
    for i in range(nb):
        dlen = short_len - ecc_len + (0 if i < n_short else 1)
        d = data[k:k + dlen]
        k += dlen
        e = _rs_remainder(d, div)
        if i < n_short:
            d = d + [0]  # حشوة مؤقتة لمحاذاة التشابك
        blocks.append((d, e, i < n_short))
    out = []
    for i in range(len(blocks[0][0])):
        for d, e, padded in blocks:
            if not (i == len(d) - 1 and padded):
                out.append(d[i])
    for i in range(ecc_len):
        for d, e, padded in blocks:
            out.append(e[i])
    return out


class _Bits(list):
    def put(self, val, n):
        for i in range(n - 1, -1, -1):
            self.append((val >> i) & 1)


def _mask_fn(m):
    return [
        lambda x, y: (x + y) % 2 == 0,
        lambda x, y: y % 2 == 0,
        lambda x, y: x % 3 == 0,
        lambda x, y: (x + y) % 3 == 0,
        lambda x, y: (x // 3 + y // 2) % 2 == 0,
        lambda x, y: x * y % 2 + x * y % 3 == 0,
        lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
        lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
    ][m]


def _format_bits(lvl_name, mask):
    data = FORMAT_BITS[lvl_name] << 3 | mask
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    return (data << 10 | rem) ^ 0x5412


def _version_bits(ver):
    rem = ver
    for _ in range(12):
        rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
    return ver << 12 | rem


def _build(ver, lvl_name, codewords, mask):
    size = ver * 4 + 17
    M = [[False] * size for _ in range(size)]
    F = [[False] * size for _ in range(size)]  # وحدات وظيفية (لا تُقنَّع)

    def setf(x, y, v):
        M[y][x] = v
        F[y][x] = True

    for i in range(size):
        setf(6, i, i % 2 == 0)
        setf(i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < size and 0 <= y < size:
                    d = max(abs(dx), abs(dy))
                    setf(x, y, d not in (2, 4))
    pos = _align_positions(ver)
    for i, cy in enumerate(pos):
        for j, cx in enumerate(pos):
            if (i == 0 and j == 0) or (i == 0 and j == len(pos) - 1) or (i == len(pos) - 1 and j == 0):
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    setf(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)
    # حجز مناطق المعلومات
    fb = _format_bits(lvl_name, mask)
    for i in range(6):
        setf(8, i, (fb >> i) & 1)
    setf(8, 7, (fb >> 6) & 1)
    setf(8, 8, (fb >> 7) & 1)
    setf(7, 8, (fb >> 8) & 1)
    for i in range(9, 15):
        setf(14 - i, 8, (fb >> i) & 1)
    for i in range(8):
        setf(size - 1 - i, 8, (fb >> i) & 1)
    for i in range(8, 15):
        setf(8, size - 15 + i, (fb >> i) & 1)
    setf(8, size - 8, True)
    if ver >= 7:
        vb = _version_bits(ver)
        for i in range(18):
            bit = (vb >> i) & 1
            a, b = size - 11 + i % 3, i // 3
            setf(a, b, bit)
            setf(b, a, bit)
    # وضع البيانات بالتعرج
    bits = []
    for cw in codewords:
        for i in range(7, -1, -1):
            bits.append((cw >> i) & 1)
    fn = _mask_fn(mask)
    k = 0
    right = size - 1
    up = True
    while right >= 1:
        if right == 6:
            right = 5
        rng = range(size - 1, -1, -1) if up else range(size)
        for y in rng:
            for dx in (0, 1):
                x = right - dx
                if not F[y][x]:
                    bit = bits[k] if k < len(bits) else 0
                    k += 1
                    M[y][x] = bool(bit) ^ fn(x, y)
        up = not up
        right -= 2
    return M


def _penalty(M):
    n = len(M)
    score = 0
    for grid in (M, [list(r) for r in zip(*M)]):
        for row in grid:
            run, prev = 1, row[0]
            for v in row[1:]:
                if v == prev:
                    run += 1
                else:
                    if run >= 5:
                        score += run - 2
                    run, prev = 1, v
            if run >= 5:
                score += run - 2
    for y in range(n - 1):
        for x in range(n - 1):
            if M[y][x] == M[y][x + 1] == M[y + 1][x] == M[y + 1][x + 1]:
                score += 3
    pat1 = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0]
    pat2 = pat1[::-1]
    for grid in (M, [list(r) for r in zip(*M)]):
        for row in grid:
            r = [1 if v else 0 for v in row]
            for i in range(n - 10):
                w = r[i:i + 11]
                if w == pat1 or w == pat2:
                    score += 40
    dark = sum(sum(1 for v in r if v) for r in M)
    k = abs(dark * 20 - n * n * 10) // (n * n)
    score += k * 10
    return score


def encode(text, level="M"):
    """يُرجع مصفوفة (list of list of bool)."""
    data = text.encode("utf-8")
    lvl = LEVELS[level]
    for ver in range(1, MAX_VERSION + 1):
        cap = _num_data_codewords(ver, lvl) * 8
        cc = 8 if ver < 10 else 16
        if 4 + cc + len(data) * 8 <= cap:
            break
    else:
        raise ValueError("النص أطول من سعة الباركود")
    bb = _Bits()
    bb.put(0b0100, 4)
    bb.put(len(data), cc)
    for b in data:
        bb.put(b, 8)
    cap = _num_data_codewords(ver, lvl) * 8
    bb.put(0, min(4, cap - len(bb)))
    bb.put(0, (-len(bb)) % 8)
    pad = 0xEC
    while len(bb) < cap:
        bb.put(pad, 8)
        pad ^= 0xEC ^ 0x11
    cws = [int("".join(map(str, bb[i:i + 8])), 2) for i in range(0, len(bb), 8)]
    allcw = _add_ecc_interleave(cws, ver, lvl)
    best, best_s = None, None
    for m in range(8):
        M = _build(ver, level, allcw, m)
        s = _penalty(M)
        if best_s is None or s < best_s:
            best, best_s = M, s
    return best


def to_svg(matrix, border=4, dark="#000", light="#fff"):
    n = len(matrix)
    parts = []
    for y, row in enumerate(matrix):
        x = 0
        while x < n:
            if row[x]:
                s = x
                while x < n and row[x]:
                    x += 1
                parts.append("M%d,%dh%dv1h-%dz" % (s + border, y + border, x - s, x - s))
            else:
                x += 1
    total = n + border * 2
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" shape-rendering="crispEdges">'
            '<rect width="100%%" height="100%%" fill="%s"/><path d="%s" fill="%s"/></svg>'
            % (total, total, light, "".join(parts), dark))
