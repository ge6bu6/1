import base64
import gzip
import html as html_mod
import json
import re
import sys
import time
import urllib.parse
import urllib.request

try:
    import hashlib
    import hmac
    import os
    _HAS_CRYPTO = True
except Exception:
    _HAS_CRYPTO = False

try:
    sys.path.append("..")
    from base.spider import BaseSpider
except Exception:
    class BaseSpider:
        pass

BASE = "https://huangguoai.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
TIMEOUT = 20
RETRY = 3
PIC_KEY = b"f5d965df75336270"
PIC_IV = b"97b60394abc2fbe1"
SITE_KEY = "hghub"

CATS = [
    {"type_id": "ai-duanju", "type_name": "AI成人短剧"},
    {"type_id": "ai-manju", "type_name": "AI成人漫剧"},
    {"type_id": "ai-huanlian", "type_name": "AI换脸"},
    {"type_id": "ai-mogai", "type_name": "AI魔改"},
    {"type_id": "chigua", "type_name": "黄果吃瓜"},
]

SBOX = [
    0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5, 0x30, 0x01, 0x67, 0x2b, 0xfe, 0xd7, 0xab, 0x76,
    0xca, 0x82, 0xc9, 0x7d, 0xfa, 0x59, 0x47, 0xf0, 0xad, 0xd4, 0xa2, 0xaf, 0x9c, 0xa4, 0x72, 0xc0,
    0xb7, 0xfd, 0x93, 0x26, 0x36, 0x3f, 0xf7, 0xcc, 0x34, 0xa5, 0xe5, 0xf1, 0x71, 0xd8, 0x31, 0x15,
    0x04, 0xc7, 0x23, 0xc3, 0x18, 0x96, 0x05, 0x9a, 0x07, 0x12, 0x80, 0xe2, 0xeb, 0x27, 0xb2, 0x75,
    0x09, 0x83, 0x2c, 0x1a, 0x1b, 0x6e, 0x5a, 0xa0, 0x52, 0x3b, 0xd6, 0xb3, 0x29, 0xe3, 0x2f, 0x84,
    0x53, 0xd1, 0x00, 0xed, 0x20, 0xfc, 0xb1, 0x5b, 0x6a, 0xcb, 0xbe, 0x39, 0x4a, 0x4c, 0x58, 0xcf,
    0xd0, 0xef, 0xaa, 0xfb, 0x43, 0x4d, 0x33, 0x85, 0x45, 0xf9, 0x02, 0x7f, 0x50, 0x3c, 0x9f, 0xa8,
    0x51, 0xa3, 0x40, 0x8f, 0x92, 0x9d, 0x38, 0xf5, 0xbc, 0xb6, 0xda, 0x21, 0x10, 0xff, 0xf3, 0xd2,
    0xcd, 0x0c, 0x13, 0xec, 0x5f, 0x97, 0x44, 0x17, 0xc4, 0xa7, 0x7e, 0x3d, 0x64, 0x5d, 0x19, 0x73,
    0x60, 0x81, 0x4f, 0xdc, 0x22, 0x2a, 0x90, 0x88, 0x46, 0xee, 0xb8, 0x14, 0xde, 0x5e, 0x0b, 0xdb,
    0xe0, 0x32, 0x3a, 0x0a, 0x49, 0x06, 0x24, 0x5c, 0xc2, 0xd3, 0xac, 0x62, 0x91, 0x95, 0xe4, 0x79,
    0xe7, 0xc8, 0x37, 0x6d, 0x8d, 0xd5, 0x4e, 0xa9, 0x6c, 0x56, 0xf4, 0xea, 0x65, 0x7a, 0xae, 0x08,
    0xba, 0x78, 0x25, 0x2e, 0x1c, 0xa6, 0xb4, 0xc6, 0xe8, 0xdd, 0x74, 0x1f, 0x4b, 0xbd, 0x8b, 0x8a,
    0x70, 0x3e, 0xb5, 0x66, 0x48, 0x03, 0xf6, 0x0e, 0x61, 0x35, 0x57, 0xb9, 0x86, 0xc1, 0x1d, 0x9e,
    0xe1, 0xf8, 0x98, 0x11, 0x69, 0xd9, 0x8e, 0x94, 0x9b, 0x1e, 0x87, 0xe9, 0xce, 0x55, 0x28, 0xdf,
    0x8c, 0xa1, 0x89, 0x0d, 0xbf, 0xe6, 0x42, 0x68, 0x41, 0x99, 0x2d, 0x0f, 0xb0, 0x54, 0xbb, 0x16,
]
INV_SBOX = [0] * 256
for _i, _v in enumerate(SBOX):
    INV_SBOX[_v] = _i
RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36]


def _gmul(a, b):
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        hi = a & 0x80
        a = (a << 1) & 0xff
        if hi:
            a ^= 0x1b
        b >>= 1
    return p


def _gmul_table(c):
    return [_gmul(i, c) for i in range(256)]


_GM2 = _gmul_table(2)
_GM3 = _gmul_table(3)
_GM9 = _gmul_table(9)
_GM11 = _gmul_table(11)
_GM13 = _gmul_table(13)
_GM14 = _gmul_table(14)


def _expand(key):
    w = [list(key[i * 4:(i + 1) * 4]) for i in range(4)]
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = [SBOX[t[1]] ^ RCON[i // 4 - 1], SBOX[t[2]], SBOX[t[3]], SBOX[t[0]]]
        w.append([w[i - 4][j] ^ t[j] for j in range(4)])
    return w


def _inv_shift_rows(s):
    return [
        s[0], s[13], s[10], s[7],
        s[4], s[1], s[14], s[11],
        s[8], s[5], s[2], s[15],
        s[12], s[9], s[6], s[3],
    ]


def _inv_sub_bytes(s):
    return [INV_SBOX[b] for b in s]


def _inv_mix_columns(s):
    out = [0] * 16
    for c in range(4):
        col = s[c * 4:(c + 1) * 4]
        out[c * 4 + 0] = _GM14[col[0]] ^ _GM11[col[1]] ^ _GM13[col[2]] ^ _GM9[col[3]]
        out[c * 4 + 1] = _GM9[col[0]] ^ _GM14[col[1]] ^ _GM11[col[2]] ^ _GM13[col[3]]
        out[c * 4 + 2] = _GM13[col[0]] ^ _GM9[col[1]] ^ _GM14[col[2]] ^ _GM11[col[3]]
        out[c * 4 + 3] = _GM11[col[0]] ^ _GM13[col[1]] ^ _GM9[col[2]] ^ _GM14[col[3]]
    return out


def _add_round_key(s, w, rnd):
    return [s[i] ^ w[rnd * 4 + i // 4][i % 4] for i in range(16)]


def _aes128_decrypt_block(block, w):
    s = list(block)
    s = _add_round_key(s, w, 10)
    for rnd in range(9, 0, -1):
        s = _inv_shift_rows(s)
        s = _inv_sub_bytes(s)
        s = _add_round_key(s, w, rnd)
        s = _inv_mix_columns(s)
    s = _inv_shift_rows(s)
    s = _inv_sub_bytes(s)
    s = _add_round_key(s, w, 0)
    return bytes(s)


def _aes128_cbc_decrypt(data, key, iv):
    if len(data) % 16 != 0 or len(key) != 16 or len(iv) != 16:
        return b""
    w = _expand(key)
    out = bytearray()
    prev = iv
    for off in range(0, len(data), 16):
        block = data[off:off + 16]
        dec = _aes128_decrypt_block(block, w)
        out.extend(bytes(a ^ b for a, b in zip(dec, prev)))
        prev = block
    return bytes(out)


_P256_P = 0xffffffff00000001000000000000000000000000ffffffffffffffffffffffff
_P256_A = _P256_P - 3
_P256_GX = 0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296
_P256_GY = 0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5
_P256_N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551
_P256_G = (_P256_GX, _P256_GY)
_ENC_PROTO = "dx150-edge-v1"
_ENC_SCOPE = "playback"
_ENC_SESSIONS = {}


def _ec_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % _P256_P == 0:
        return None
    if p1 == p2:
        lam = (3 * x1 * x1 + _P256_A) * pow(2 * y1, _P256_P - 2, _P256_P) % _P256_P
    else:
        lam = (y2 - y1) * pow(x2 - x1, _P256_P - 2, _P256_P) % _P256_P
    x3 = (lam * lam - x1 - x2) % _P256_P
    y3 = (lam * (x1 - x3) - y1) % _P256_P
    return (x3, y3)


def _ec_mul(k, pt):
    r = None
    while k:
        if k & 1:
            r = _ec_add(r, pt)
        pt = _ec_add(pt, pt)
        k >>= 1
    return r


def _expand256(key):
    w = [list(key[i * 4:(i + 1) * 4]) for i in range(8)]
    for i in range(8, 60):
        t = list(w[i - 1])
        if i % 8 == 0:
            t = [SBOX[t[1]] ^ RCON[i // 8 - 1], SBOX[t[2]], SBOX[t[3]], SBOX[t[0]]]
        elif i % 8 == 4:
            t = [SBOX[t[0]], SBOX[t[1]], SBOX[t[2]], SBOX[t[3]]]
        w.append([w[i - 8][j] ^ t[j] for j in range(4)])
    return w


def _shift_rows(s):
    return [s[0], s[5], s[10], s[15], s[4], s[9], s[14], s[3],
            s[8], s[13], s[2], s[7], s[12], s[1], s[6], s[11]]


def _mix_columns(s):
    out = [0] * 16
    for c in range(4):
        col = s[c * 4:(c + 1) * 4]
        out[c * 4 + 0] = _GM2[col[0]] ^ _GM3[col[1]] ^ col[2] ^ col[3]
        out[c * 4 + 1] = col[0] ^ _GM2[col[1]] ^ _GM3[col[2]] ^ col[3]
        out[c * 4 + 2] = col[0] ^ col[1] ^ _GM2[col[2]] ^ _GM3[col[3]]
        out[c * 4 + 3] = _GM3[col[0]] ^ col[1] ^ col[2] ^ _GM2[col[3]]
    return out


def _aes256_encrypt_block(block, w):
    s = [block[i] ^ w[i // 4][i % 4] for i in range(16)]
    for rnd in range(1, 14):
        s = [SBOX[b] for b in s]
        s = _shift_rows(s)
        s = _mix_columns(s)
        s = [s[i] ^ w[rnd * 4 + i // 4][i % 4] for i in range(16)]
    s = [SBOX[b] for b in s]
    s = _shift_rows(s)
    s = [s[i] ^ w[56 + i // 4][i % 4] for i in range(16)]
    return bytes(s)


def _ghash(h, aad, ct):
    def _pad(b):
        return b + b"\x00" * ((-len(b)) % 16)
    def _mul128(x, y):
        z = 0
        v = y
        for i in range(128):
            if (x >> (127 - i)) & 1:
                z ^= v
            if v & 1:
                v = (v >> 1) ^ 0xe1000000000000000000000000000000
            else:
                v >>= 1
        return z
    data = _pad(aad) + _pad(ct)
    data += (len(aad) * 8).to_bytes(8, "big") + (len(ct) * 8).to_bytes(8, "big")
    hint = int.from_bytes(h, "big")
    y = 0
    for off in range(0, len(data), 16):
        y = _mul128(y ^ int.from_bytes(data[off:off + 16], "big"), hint)
    return y.to_bytes(16, "big")


def _gcm_encrypt(key, iv, aad, data):
    w = _expand256(key)
    h = _aes256_encrypt_block(b"\x00" * 16, w)
    j0 = iv + b"\x00\x00\x00\x01"
    out = bytearray()
    ctr = 2
    for off in range(0, len(data), 16):
        blk = data[off:off + 16]
        ks = _aes256_encrypt_block(iv + ctr.to_bytes(4, "big"), w)
        out.extend(bytes(a ^ b for a, b in zip(blk, ks)))
        ctr += 1
    ct = bytes(out)
    s = _ghash(h, aad, ct)
    tag = bytes(a ^ b for a, b in zip(s, _aes256_encrypt_block(j0, w)))
    return ct, tag


def _gcm_decrypt(key, iv, aad, ct, tag):
    w = _expand256(key)
    h = _aes256_encrypt_block(b"\x00" * 16, w)
    j0 = iv + b"\x00\x00\x00\x01"
    s = _ghash(h, aad, ct)
    expect = bytes(a ^ b for a, b in zip(s, _aes256_encrypt_block(j0, w)))
    if expect != tag:
        raise ValueError("tag mismatch")
    out = bytearray()
    ctr = 2
    for off in range(0, len(ct), 16):
        blk = ct[off:off + 16]
        ks = _aes256_encrypt_block(iv + ctr.to_bytes(4, "big"), w)
        out.extend(bytes(a ^ b for a, b in zip(blk, ks)))
        ctr += 1
    return bytes(out)


def _hkdf_sha256(salt, ikm, info):
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()


def _b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64u(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _post_json_raw(url, obj):
    data = json.dumps(obj).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": UA, "Content-Type": "application/json",
        "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


class _EncSession:
    def __init__(self, base):
        d = int.from_bytes(os.urandom(32), "big") % (_P256_N - 1) + 1
        qx, qy = _ec_mul(d, _P256_G)
        pub = b"\x04" + qx.to_bytes(32, "big") + qy.to_bytes(32, "big")
        hello = _post_json_raw(base + "/api/playback/request",
                               {"v": 1, "type": "hello", "client_pub": _b64u(pub)})
        if hello.get("v") != 1 or hello.get("type") != "hello":
            raise ValueError("bad hello")
        self.kid = hello["kid"]
        self.sid = hello["sid"]
        self.site = hello["site"]
        salt = _unb64u(hello["salt"])
        srv = _unb64u(hello["server_pub"])
        if len(salt) != 32 or len(srv) != 65 or srv[0] != 4:
            raise ValueError("bad hello keys")
        sx = int.from_bytes(srv[1:33], "big")
        sy = int.from_bytes(srv[33:65], "big")
        shared = _ec_mul(d, (sx, sy))
        secret = shared[0].to_bytes(32, "big")
        self.info = "\n".join([_ENC_PROTO, _ENC_SCOPE, self.site, self.kid, self.sid])
        self.req_key = _hkdf_sha256(salt, secret, (self.info + "\nreq").encode())
        self.res_key = _hkdf_sha256(salt, secret, (self.info + "\nres").encode())
        self.clock_off = int(hello["server_time"]) - int(time.time())
        self.expires = int(time.time()) + (int(hello["expires_at"]) - int(hello["server_time"])) - 10
        self.seq = 0
        self.base = base

    def alive(self):
        return time.time() < self.expires and self.seq < 16000

    def call(self, method, path, body=b"", ctype=""):
        self.seq += 1
        seq = self.seq
        ts = int(time.time()) + self.clock_off
        iv = b"\x00" * 8 + seq.to_bytes(4, "big")
        aad_req = (self.info + "\nreq\n%d\n%d" % (seq, ts)).encode()
        aad_res = (self.info + "\nres\n%d\n%d" % (seq, ts)).encode()
        pkt = {"method": method, "path": path,
               "body": base64.b64encode(body).decode(), "content_type": ctype}
        plain = json.dumps({"request": pkt}, separators=(",", ":")).encode()
        ct, tag = _gcm_encrypt(self.req_key, iv, aad_req, plain)
        res = _post_json_raw(self.base + "/api/playback/request", {
            "v": 1, "type": "call", "kid": self.kid, "sid": self.sid,
            "seq": seq, "ts": ts, "ciphertext": _b64u(ct + tag)})
        if res.get("v") != 1 or res.get("type") != "result":
            raise ValueError("bad result")
        if res.get("sid") != self.sid or res.get("kid") != self.kid:
            raise ValueError("session mismatch")
        if res.get("seq") != seq or res.get("ts") != ts:
            raise ValueError("seq mismatch")
        raw = _unb64u(res["ciphertext"])
        inner = json.loads(_gcm_decrypt(self.res_key, iv, aad_res, raw[:-16], raw[-16:]).decode())
        if inner.get("status") != 200:
            return {}
        body = inner.get("body") or ""
        if not body:
            return {}
        try:
            return json.loads(base64.b64decode(body).decode("utf-8", "ignore"))
        except Exception:
            return {}


def _magic_mime(data):
    if not data:
        return ""
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:4] == b"GIF8":
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return ""


def _decode_pic(data):
    if not data:
        return data
    mime = _magic_mime(data)
    if mime:
        if mime == "image/jpeg":
            end = data.rfind(b"\xff\xd9")
            if end > 0:
                return data[:end + 2]
        return data
    if len(data) % 16 != 0:
        return data
    plain = _aes128_cbc_decrypt(data, PIC_KEY, PIC_IV)
    if not plain:
        return data
    pad = plain[-1]
    if 1 <= pad <= 16 and plain[-pad:] == bytes([pad]) * pad:
        plain = plain[:-pad]
    if not _magic_mime(plain):
        return data
    if _magic_mime(plain) == "image/jpeg":
        end = plain.rfind(b"\xff\xd9")
        if end > 0:
            return plain[:end + 2]
    return plain


def _pic_proxy(url):
    url = str(url or "").strip()
    if not url:
        return ""
    if url.startswith("proxy://"):
        return url
    return "proxy://do=py&siteKey=%s&u=%s" % (
        SITE_KEY, urllib.parse.quote(url, safe=""))


def _fetch_bytes(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": BASE + "/", "Accept": "image/*,*/*"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def _dec(raw):
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", "ignore")


def _strip_html(s):
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s or "")
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html_mod.unescape(s)).strip()


def _to_int(v, default=0):
    try:
        return int(v)
    except Exception:
        try:
            return int(float(v))
        except Exception:
            return default


def _card(item):
    if not isinstance(item, dict):
        return None
    vid = item.get("id")
    if vid is None:
        return None
    title = str(item.get("title") or "").strip()
    if not title:
        return None
    ep = _to_int(item.get("episode_count"), 0)
    score = item.get("score")
    remarks = ""
    if ep:
        remarks = "%d集" % ep
    if score not in (None, "", 0, "0"):
        remarks = (remarks + " " if remarks else "") + "%s分" % score
    created = str(item.get("created_at") or "")
    return {
        "vod_id": str(vid),
        "vod_name": title,
        "vod_pic": _pic_proxy(item.get("cover") or ""),
        "vod_remarks": remarks.strip(),
        "vod_year": created[:4] if len(created) >= 4 else "",
        "vod_content": str(item.get("description") or "")[:300],
    }


def _post_card(item):
    if not isinstance(item, dict):
        return None
    pid = item.get("id")
    if pid is None:
        return None
    title = str(item.get("title") or "").strip()
    if not title:
        return None
    tags = item.get("tags") or []
    remarks = ""
    if isinstance(tags, list) and tags:
        remarks = str(tags[0])
    created = str(item.get("created_at") or "")
    return {
        "vod_id": "post:%s" % pid,
        "vod_name": title,
        "vod_pic": _pic_proxy(item.get("cover") or ""),
        "vod_remarks": remarks,
        "vod_year": created[:4] if len(created) >= 4 else "",
        "vod_content": str(item.get("desc") or "")[:300],
    }


class Spider(BaseSpider):
    ext = {}
    base = BASE

    def getName(self):
        return "HGhub"

    def getDependence(self):
        return []

    def isVideoFormat(self, url):
        return bool(url) and (".m3u8" in url or ".mp4" in url)

    def manualVideoCheck(self):
        return False

    def destroy(self):
        return

    def init(self, extend=""):
        try:
            self.ext = json.loads(extend) if extend else {}
        except Exception:
            self.ext = {}
        if isinstance(self.ext, dict):
            dom = str(self.ext.get("domain") or "")
            if dom.startswith("http"):
                self.base = dom.rstrip("/")

    def http_get(self, url):
        for attempt in range(RETRY):
            try:
                req = urllib.request.Request(url)
                req.add_header("User-Agent", UA)
                req.add_header("Accept", "application/json")
                req.add_header("Referer", self.base + "/")
                with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                    raw = r.read()
                    if raw[:2] == b"\x1f\x8b":
                        raw = gzip.decompress(raw)
                    return _dec(raw)
            except Exception:
                time.sleep(0.5 * (attempt + 1))
        return ""

    def api_get(self, path):
        text = self.http_get(self.base + path)
        if not text:
            return {}
        try:
            data = json.loads(text)
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        if data.get("status") not in (None, 1):
            return {}
        inner = data.get("data")
        if isinstance(inner, dict):
            return inner
        return data

    def _enc_session(self):
        if not _HAS_CRYPTO:
            return None
        sess = _ENC_SESSIONS.get(self.base)
        if sess is not None and sess.alive():
            return sess
        for attempt in range(2):
            try:
                sess = _EncSession(self.base)
                break
            except Exception:
                sess = None
                if attempt == 0:
                    time.sleep(1)
        if sess is None:
            return None
        _ENC_SESSIONS[self.base] = sess
        return sess

    def _enc_call(self, method, path, body=b"", ctype=""):
        sess = self._enc_session()
        if sess is None:
            return {}
        try:
            return sess.call(method, path, body, ctype)
        except Exception:
            _ENC_SESSIONS.pop(self.base, None)
            sess = self._enc_session()
            if sess is None:
                return {}
            try:
                return sess.call(method, path, body, ctype)
            except Exception:
                return {}

    def _play_video(self, vid, ep):
        try:
            data = self._enc_call("POST", "/api/videos/%s/episodes/%s/playback" % (
                urllib.parse.quote(str(vid), safe=""),
                urllib.parse.quote(str(ep), safe="")))
            inner = data.get("data") or {}
            streams = inner.get("streams") or {}
            return str(streams.get("main") or streams.get("preview") or streams.get("hevc") or "")
        except Exception:
            return ""

    def _play_post(self, pid):
        try:
            data = self._enc_call("POST", "/api/posts/%s/playback" % urllib.parse.quote(str(pid), safe=""))
            inner = data.get("data") or {}
            videos = inner.get("videos") or []
            if videos and isinstance(videos[0], dict):
                return str(videos[0].get("url") or "")
            return ""
        except Exception:
            return ""

    def homeContent(self, filter=""):
        return {"class": CATS, "list": []}

    def homeVideoContent(self):
        data = self.api_get("/api/videos?page=1&size=20")
        items = data.get("items") or []
        out = []
        for it in items:
            card = _card(it)
            if card:
                out.append(card)
        return {"list": out}

    def categoryContent(self, tid, pg, filter, extend):
        pg = _to_int(pg, 1)
        if pg < 1:
            pg = 1
        tid = str(tid or "")
        if isinstance(extend, str):
            try:
                extend = json.loads(extend) if extend else {}
            except Exception:
                extend = {}
        if tid == "chigua":
            data = self.api_get("/api/posts?page=%d&size=20" % pg)
            items = data.get("items") or []
            out = []
            for it in items:
                card = _post_card(it)
                if card:
                    out.append(card)
        else:
            data = self.api_get("/api/videos/category/%s?page=%d&size=20" % (
                urllib.parse.quote(tid, safe=""), pg))
            items = data.get("items") or []
            out = []
            for it in items:
                card = _card(it)
                if card:
                    out.append(card)
        pageinfo = data.get("pagination") or {}
        pages = _to_int(pageinfo.get("pages"), pg if out else pg)
        total = _to_int(pageinfo.get("total"), len(out))
        return {"list": out, "page": pg, "pagecount": pages,
                "limit": 20, "total": total}

    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, list) else ids
        vid = str(vid or "").strip()
        if vid.startswith("post:"):
            pid = vid.split(":", 1)[1]
            data = self.api_get("/api/posts/%s" % urllib.parse.quote(pid, safe=""))
            if not data:
                return {"list": []}
            content = str(data.get("desc") or "")
            if not content:
                content = _strip_html(str(data.get("content") or ""))[:1000]
            tags = data.get("tags") or []
            vod = {
                "vod_id": vid,
                "vod_name": str(data.get("title") or ""),
                "vod_pic": _pic_proxy(data.get("cover") or ""),
                "vod_content": content,
                "vod_type": "黄果吃瓜",
            }
            if isinstance(tags, list) and tags:
                vod["vod_tag"] = ",".join(str(t) for t in tags[:8])
            vod["vod_play_from"] = "在线播放"
            vod["vod_play_url"] = "正片$post:%s" % pid
            return {"list": [vod]}
        data = self.api_get("/api/videos/%s" % urllib.parse.quote(vid, safe=""))
        if not data:
            return {"list": []}
        episodes = data.get("episodes") or []
        eps = []
        for ep in episodes:
            if not isinstance(ep, dict):
                continue
            num = _to_int(ep.get("ep_num"), 0)
            if num < 1:
                continue
            eps.append("第%d集$%s:%d" % (num, vid, num))
        if not eps:
            eps.append("第1集$%s:1" % vid)
        author = data.get("author") or {}
        crumbs = data.get("breadcrumb") or []
        typename = ""
        if isinstance(crumbs, list) and crumbs and isinstance(crumbs[0], dict):
            typename = str(crumbs[0].get("name") or "")
        tags = data.get("tags") or []
        created = str(data.get("created_at") or "")
        score = data.get("score")
        remarks = ""
        if score not in (None, "", 0, "0"):
            remarks = "%s分" % score
        vod = {
            "vod_id": str(vid),
            "vod_name": str(data.get("title") or ""),
            "vod_pic": _pic_proxy(data.get("cover") or ""),
            "vod_content": str(data.get("description") or ""),
            "vod_year": created[:4] if len(created) >= 4 else "",
            "vod_remarks": remarks,
            "vod_type": typename,
            "vod_play_from": "在线播放",
            "vod_play_url": "#".join(eps),
        }
        if isinstance(author, dict) and author.get("name"):
            vod["vod_actor"] = str(author.get("name"))
        if isinstance(tags, list) and tags:
            vod["vod_tag"] = ",".join(str(t) for t in tags[:8])
        return {"list": [vod]}

    def searchContent(self, key, quick=False, pg="1"):
        pg = _to_int(pg, 1)
        if pg < 1:
            pg = 1
        key = str(key or "").strip()
        if not key:
            return {"list": [], "page": pg}
        data = self.api_get("/api/search?q=%s&page=%d&size=20" % (
            urllib.parse.quote(key), pg))
        items = data.get("items") or []
        out = []
        for it in items:
            card = _card(it)
            if card:
                out.append(card)
        pageinfo = data.get("pagination") or {}
        pages = _to_int(pageinfo.get("pages"), pg if out else pg)
        return {"list": out, "page": pg, "pagecount": pages}

    def playerContent(self, flag, id, vipFlags):
        raw = str(id or "").strip()
        head = {"User-Agent": UA, "Referer": self.base + "/"}
        url = ""
        if raw.startswith("http") and (".m3u8" in raw or ".mp4" in raw):
            url = raw
        elif raw.startswith("post:"):
            url = self._play_post(raw.split(":", 1)[1])
        elif re.match(r"^\d+:\d+$", raw):
            vid, ep = raw.split(":", 1)
            url = self._play_video(vid, ep)
            if not url:
                data = self.api_get("/api/videos/%s/play?ep=%s&page_texts=0" % (
                    urllib.parse.quote(vid, safe=""), urllib.parse.quote(ep, safe="")))
                url = str(data.get("video_url") or data.get("video_url_hevc") or "")
        elif raw.startswith("http"):
            url = raw
        if not url:
            return {"parse": 1, "url": raw, "header": head}
        return {"parse": 0, "playUrl": url, "url": url, "header": head}

    def localProxy(self, param=None):
        try:
            p = param
            if isinstance(p, str):
                try:
                    p = json.loads(p)
                except Exception:
                    p = dict(urllib.parse.parse_qsl(p))
            if not isinstance(p, dict):
                p = {}
            target = p.get("u") or p.get("url") or ""
            if isinstance(target, list):
                target = target[0] if target else ""
            target = urllib.parse.unquote(str(target or "").strip())
            if not target.startswith("http"):
                return [404, "text/plain", "", {}, 0]
            raw = _fetch_bytes(target)
            raw = _decode_pic(raw)
            mime = _magic_mime(raw)
            if not mime:
                mime = "image/jpeg"
            return [200, mime, base64.b64encode(raw).decode("ascii"), {}, 1]
        except Exception:
            return [502, "text/plain", "", {}, 0]

    def action(self, action=None):
        return {}
