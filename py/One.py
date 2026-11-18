# 一点播 — TVBox Python Spider
# 由 CatVod 爬虫 JAR（com.github.catvod.spider.csp_One）反编译改写，逻辑 1:1。
#
# 站点：Flutter 应用后端，API v2.5（请求体 AES 加密、响应 AES 加密或明文 JSON）。
#   引导：先并行试 v2.5/bootstrap，失败再串行逐个试，最后拉引导配置 /box/api/config?channel=Channel
#         （AES 解密 + zlib 解压，取 token_one）
#   列表：/v2.5/article/discovery（model_id + demand_tag_id，按月分页）
#   图集/漫画列表：/v2.5/series/album/list、/v2.5/series/manga/list
#   详情：/v2.5/article/detail；选集：/v2.5/series/chapters
#   搜索：/v2.5/article/search
#   播放：video_download（完整片 MP4）、video_file（正片/预告）、video_hls /
#         video_hls_h265、audio_file；相对地址按引导配置的域名展开，
#         播单里多线路标“ 线路N”。
#
# 分类（type_id → 名称）：6_3 国产、6_2 日本、6_1 欧美、6_5 新作、
#                         3_3 4K独播、6_4 直播、manga 漫画、album 写真
#
# ext 写法（init 的 extend 参数，& 或 ; 或换行分隔，键小写）：
#   token=<你的有效 token>      覆盖引导配置里的 token_one（它只有 7 天有效期）
#   api=https://有效API域名/    覆盖 API 域名（换后端）
#   line=<引导线路地址>        换引导配置线路
#   net=proxy,proxy=http://ip:端口   走代理（原版只在诊断文案里提，没实现；py 版真做了）
#   uuid= / userkey= / ip= / platform=   签名参数覆盖
#   months=12                   分类按月回溯几个月（默认 12）
#   cooldown=20                 初始化失败后冷却秒数（默认 20）
#   mediaua= / playref=1        播放请求头 UA / Referer+Origin
#   ua= / imgtimeout=15         图片代理 UA / 超时秒数
#   host=a.com,b.com            localProxy 允许的额外图片域名
#
# Auth.check() 原样保留：GET https://pan.meil.wang/f/bZ4U1/nat.txt，
# 手动跟随最多 5 次重定向（301/302/303/307），响应体 trim 后必须等于 "ayingtvbox"，
# 最多重试 3 次，结果缓存。校验失败时各接口行为与原版一致：返回空 {}，
# localProxy 返回 404。
# SelfCheck（校验 JAR 自身 DEX 签名防篡改）对 .py 文件没有意义，没有移植。
#
# 反编译缺失、按原版同类代码补齐的地方（已在注释里标【补】）：
#   1) searchContent 的结果循环体在反编译产物里丢了，按 categoryContent 视频分支补。
#   2) M() 里拼请求体 k=v&k=v 的循环体丢了，按缓存键的同格式补。
#   3) M() 明文 JSON 成功分支没有显式代码，按加密分支的 code 0/200 判定补。
#   4) localProxy 带签名 k 的成功分支丢了，按“签名通过则不限域名直接取图”补。
#   5) net=proxy、img=direct 在原版代码里只出现在诊断文案中，并无实现；
#      py 版把 net=proxy 真做了，img=direct 不用做——图片地址本来就是直链。
#
# 加密全部用纯 Python 实现（TVBox 里不一定有 pycryptodome）：
#   AES-128/CBC/NoPadding，请求加密 key/iv 与响应解密 key/iv 与原版一致；
#   配置解密后还要 zlib 解压；图片代理先试 AES 解密再验魔数。

import base64
import concurrent.futures
import hashlib
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

try:
    import requests
except ImportError:
    requests = None

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider:
        pass

# ---------------------------------------------------------------- 固定常量
SITE_NAME = "一点播"
CHECK_URL = "https://pan.meil.wang/f/bZ4U1/nat.txt"
CHECK_EXPECT = "ayingtvbox"

APP_VERSION = "1.6.0"
UA_CHROME = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
UA_DART = "Dart/3.4 (dart:io)"
UA_AUTH = "Mozilla/5.0 (Linux; Android 14)"

DEFAULT_API = "https://api.em1oifd0.com/"
# line= 可切换的 API 域名（v）
LINE_HOSTS = [
    "https://api.3459381.com/",
    "https://api.61c76a0.com/",
    "https://api.87735d5.com/",
    "https://api.c6dd5cc.com/",
    "https://api.j7y675.com/",
    "https://api.em1oifd0.com/",
]
# 引导配置线路（w）
CONFIG_HOSTS = [
    "http://198.44.248.101:9672/",
    "http://198.44.248.102:9672/",
    "http://122.10.20.249:9672/",
]
# bootstrap 并行探测的域名（H）
BOOTSTRAP_HOSTS = [
    "https://api.2b37894.com",
    "https://api.35a46dd.com",
    "https://api.43b8477.com",
    "https://api.5ce3771.com",
    "https://api.61c76a0.com",
    "https://api.632d809.com",
    "https://api.3459381.com",
    "https://api.em1oifd0.com",
    "https://api.j7y675.com",
]
# 图片域名（I）
IMG_HOSTS = [
    "https://imgpw807.s7n7ue8.com",
    "https://imgpw807.2u7qzt7.com",
    "https://img807.hkq57tt.com",
]
# 兜底域名（J）
FALLBACK_HOSTS = [
    "https://46e9nz.mfpt8g.com",
    "https://f86xxm.upmf83.com",
]
FALLBACK_VIDEO = "https://gund9tfy.bx7qxb.com"
FALLBACK_IMG = "https://q3vp74ws02jp.gdliren123.com"
# 图片地址含这些域名时只取 path 部分再拼新域名（M）
IMG_STRIP_DOMAINS = [
    "gdliren123.com",
    "u3wwetf.com",
    "m6qzbb4.com",
    "bdsy56.com",
    "gzjsqx.com",
    "k8b3rsp.com",
]
PREVIEW_MARKERS = ["preview", "trailer", "sample", "_pv.", "pv_"]
PROXY_SIGN_TAG = "one.tvp.pic.v2026"

# AES key / iv（原版常量，功能必需）
KEY_REQ = b"l*bv%Ziq000Biaog"      # z：v2.5 请求加密 / 响应解密
IV_REQ = b"8597506002939249"       # A
KEY_CFG = b"dnf45as45fs1ace1"      # x：引导配置解密
IV_CFG = b"dn5as4fs1ac5f4e1"       # y
KEY_IMG = b"saIZXc4yMvq0Iz56"      # C：图片代理解密
IV_IMG = b"kbJYtBJUECT0oyjo"       # D
SIGN_SALT = "m4n2hjPeYWkD6tFpqKF^3HO^h24P@idT"  # B：签名盐

CATEGORIES = [
    ("6_3", "国产"),
    ("6_2", "日本"),
    ("6_1", "欧美"),
    ("6_5", "新作"),
    ("3_3", "4K独播"),
    ("6_4", "直播"),
    ("manga", "漫画"),
    ("album", "写真"),
]
CAT_IDS = {tid for tid, _ in CATEGORIES}

DIAG_GUIDE = (
    "排查顺序：\n"
    "1) 提示「凭证已过期 / Expired token」→ 是站点令牌失效（不是本源的错）：\n"
    "   ext 填  token=你的有效令牌\n"
    "   或  ext 填  api=有效API域名   （换后端）\n"
    "2) 连不上站点 → ext 填  net=proxy  并配 proxy=代理地址\n"
    "3) 提示签名/授权失败 → 引导配置没取到，ext 加  line=备用引导线路  换线再试\n"
    "4) 提示 image/图片 400/403 → 是本地代理没起来，ext 填  img=direct\n"
    "5) 都不行 → 把这条【诊断】截图发我，照原因改"
)

# ---------------------------------------------------------------- 基础工具
def _m(v):
    return "" if v is None else str(v).strip()


def _n(v):
    try:
        return int(_m(v))
    except Exception:
        return 0


def _as_list(v):
    return v if isinstance(v, list) else []


def _as_map(v):
    return v if isinstance(v, dict) else {}


def _d(n, s):
    """h.d：去 $ # 换行再截断（n<=0 不截断）。"""
    s = ("" if s is None else str(s)).replace("$", " ").replace("#", " ").replace("\r", " ").replace("\n", " ").strip()
    if n > 0 and len(s) > n:
        s = s[:n]
    return s


def _md5(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _b64dec(s):
    """h.c：base64 解码（先标准后 urlsafe，自动补 =）。"""
    s = _m(s)
    pad = (-len(s) % 4) % 4
    s += "=" * pad
    try:
        return base64.b64decode(s)
    except Exception:
        return base64.urlsafeb64decode(s)


def _host_of(url):
    """h.h：取 host（去 scheme、路径、端口，小写）。"""
    u = _m(url)
    i = u.find("://")
    if i >= 0:
        u = u[i + 3:]
    i = u.find("/")
    if i >= 0:
        u = u[:i]
    i = u.find(":")
    if i >= 0:
        u = u[:i]
    return u.lower()


def _is_hijack(text):
    """u()：响应是不是 html 跳转劫持页（只看前 600 字符）。"""
    t = (text or "")[:600].lower()
    return ("<html" in t or "hao123" in t or "gotob2" in t
            or ("<script" in t and "</html>" in t))


def _jwt_exp(token):
    """b.b：JWT 的 exp（秒）。解析失败返回 0。"""
    try:
        parts = str(token).split(".")
        if len(parts) < 2:
            return 0
        payload = _b64dec(parts[1]).decode("utf-8")
        obj = json.loads(payload)
        if isinstance(obj, dict):
            return int(str(obj.get("exp") or 0).strip() or 0)
    except Exception:
        return 0
    return 0


def _jwt_payload(token):
    try:
        parts = str(token).split(".")
        if len(parts) < 2:
            return {}
        obj = json.loads(_b64dec(parts[1]).decode("utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _rand_uuid():
    """z()：随机 UUID（4-4-4-12 形，版本位 4，变体位 a）。"""
    import random
    hx = "".join(random.choice("0123456789abcdef") for _ in range(32))
    return "%s-%s-4%s-a%s-%s" % (hx[0:8], hx[8:12], hx[13:16], hx[17:20], hx[20:32])


def _now():
    return int(time.time())


def _month_ago(n):
    """D(n)：当前往前 n 个月的 YYYY-MM。"""
    t = time.localtime()
    y, m = t.tm_year, t.tm_mon - n
    while m <= 0:
        m += 12
        y -= 1
    return "%04d-%02d" % (y, m)


def _ensure_slash(u):
    """E()：去尾部 / 后补一个 /；空返回 ''。"""
    s = _m(u)
    while s.endswith("/"):
        s = s[:-1]
    return s + "/" if s else ""


def _join(sep, items):
    return sep.join(str(x) for x in items)

# ---------------------------------------------------------------- 纯 Python AES-128
_SBOX = [
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
_INV_SBOX = [0] * 256
for _i, _v in enumerate(_SBOX):
    _INV_SBOX[_v] = _i
_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36]


def _xtime(a):
    a &= 0xff
    return ((a << 1) ^ 0x1b) & 0xff if a & 0x80 else (a << 1) & 0xff


def _gmul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xtime(a)
        b >>= 1
    return r


def _expand_key(key):
    w = [list(key[i * 4:(i + 1) * 4]) for i in range(4)]
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = [_SBOX[t[1]] ^ _RCON[i // 4 - 1], _SBOX[t[2]], _SBOX[t[3]], _SBOX[t[0]]]
        w.append([w[i - 4][j] ^ t[j] for j in range(4)])
    return w


def _add_rk(state, w, rnd):
    for c in range(4):
        for r in range(4):
            state[r][c] ^= w[rnd * 4 + c][r]


def _sub(state, box):
    for r in range(4):
        for c in range(4):
            state[r][c] = box[state[r][c]]


def _shift(state, inv=False):
    for r in range(1, 4):
        row = [state[r][c] for c in range(4)]
        n = -r if inv else r
        row = row[n % 4:] + row[:n % 4]
        for c in range(4):
            state[r][c] = row[c]


def _mix(state, inv=False):
    for c in range(4):
        a = [state[r][c] for r in range(4)]
        if inv:
            state[0][c] = _gmul(a[0], 14) ^ _gmul(a[1], 11) ^ _gmul(a[2], 13) ^ _gmul(a[3], 9)
            state[1][c] = _gmul(a[0], 9) ^ _gmul(a[1], 14) ^ _gmul(a[2], 11) ^ _gmul(a[3], 13)
            state[2][c] = _gmul(a[0], 13) ^ _gmul(a[1], 9) ^ _gmul(a[2], 14) ^ _gmul(a[3], 11)
            state[3][c] = _gmul(a[0], 11) ^ _gmul(a[1], 13) ^ _gmul(a[2], 9) ^ _gmul(a[3], 14)
        else:
            state[0][c] = _gmul(a[0], 2) ^ _gmul(a[1], 3) ^ a[2] ^ a[3]
            state[1][c] = a[0] ^ _gmul(a[1], 2) ^ _gmul(a[2], 3) ^ a[3]
            state[2][c] = a[0] ^ a[1] ^ _gmul(a[2], 2) ^ _gmul(a[3], 3)
            state[3][c] = _gmul(a[0], 3) ^ a[1] ^ a[2] ^ _gmul(a[3], 2)


def _aes_block(key, block, encrypt=True):
    w = _expand_key(key)
    s = [[block[c * 4 + r] for c in range(4)] for r in range(4)]
    if encrypt:
        _add_rk(s, w, 0)
        for rnd in range(1, 10):
            _sub(s, _SBOX)
            _shift(s)
            _mix(s)
            _add_rk(s, w, rnd)
        _sub(s, _SBOX)
        _shift(s)
        _add_rk(s, w, 10)
    else:
        _add_rk(s, w, 10)
        for rnd in range(9, 0, -1):
            _sub(s, _INV_SBOX)
            _shift(s, inv=True)
            _add_rk(s, w, rnd)
            _mix(s, inv=True)
        _sub(s, _INV_SBOX)
        _shift(s, inv=True)
        _add_rk(s, w, 0)
    return bytes(s[r][c] for c in range(4) for r in range(4))


def _pkcs7_pad(data):
    n = 16 - (len(data) % 16)
    return data + bytes([n]) * n


def _pkcs7_unpad(data):
    """b.d：去 PKCS7 填充，非法填充抛错。"""
    if not data:
        return data
    n = data[-1] & 0xff
    if n < 1 or n > 16 or n > len(data):
        raise ValueError("invalid cipher padding")
    for i in range(n):
        if (data[len(data) - 1 - i] & 0xff) != n:
            raise ValueError("invalid cipher padding")
    return data[:-n]


def _aes_cbc(data, key, iv, encrypt=True):
    """b.a：AES/CBC/NoPadding；加密时先补 PKCS7。"""
    if encrypt:
        data = _pkcs7_pad(data)
    out = bytearray()
    prev = iv
    for i in range(0, len(data), 16):
        blk = data[i:i + 16]
        if encrypt:
            x = bytes(blk[j] ^ prev[j] for j in range(16))
            enc = _aes_block(key, x, True)
            out += enc
            prev = enc
        else:
            dec = _aes_block(key, blk, False)
            out += bytes(dec[j] ^ prev[j] for j in range(16))
            prev = blk
    return bytes(out)

# ---------------------------------------------------------------- HTTP 层
def _no_verify_ctx():
    return ssl._create_unverified_context()


def _http_post(url, headers, body, timeout=8, proxies=None):
    """h.i：POST，返回 (status, bytes)。失败返回 (0, b'')。"""
    if requests is not None:
        try:
            with requests.Session() as s:
                r = s.post(url, headers=headers, data=body, timeout=timeout,
                           allow_redirects=True, verify=False, proxies=proxies)
                return r.status_code, r.content or b""
        except Exception:
            return 0, b""
    import urllib.request
    import urllib.error
    try:
        req = urllib.request.Request(url, data=body if body is not None else b"",
                                     headers=headers or {}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout, context=_no_verify_ctx()) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read()
        except Exception:
            return e.code, b""
    except Exception:
        return 0, b""


def _http_get(url, headers, timeout=15, proxies=None):
    """s() 同款 GET，返回 (status, bytes)。失败返回 (0, b'')。"""
    if requests is not None:
        try:
            with requests.Session() as s:
                r = s.get(url, headers=headers, timeout=timeout,
                          allow_redirects=True, verify=False, proxies=proxies)
                return r.status_code, r.content or b""
        except Exception:
            return 0, b""
    import urllib.request
    import urllib.error
    try:
        req = urllib.request.Request(url, headers=headers or {}, method="GET")
        with urllib.request.urlopen(req, timeout=timeout, context=_no_verify_ctx()) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read()
        except Exception:
            return e.code, b""
    except Exception:
        return 0, b""


# Auth.check()：原样保留。手动跟随最多 5 次重定向，最多重试 3 次，结果缓存。
_auth_ok = None


def auth_check(proxies=None):
    global _auth_ok
    if _auth_ok is not None:
        return _auth_ok
    ok = False
    for _ in range(3):
        if _auth_once(proxies):
            ok = True
            break
    _auth_ok = ok
    return ok


def _auth_once(proxies=None):
    url = CHECK_URL
    try:
        for _ in range(5):
            status, body, loc = _auth_get(url, proxies)
            if status in (301, 302, 303, 307):
                if not loc:
                    return False
                url = urllib.parse.urljoin(url, loc)
                continue
            if status == 200:
                try:
                    return body.decode("utf-8").strip() == CHECK_EXPECT
                except Exception:
                    return False
            return False
        return False
    except Exception:
        return False


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _auth_get(url, proxies=None):
    """一次 Auth GET：返回 (status, body, Location)。"""
    import urllib.request
    import urllib.error
    headers = {"User-Agent": UA_AUTH}
    if requests is not None:
        try:
            with requests.Session() as s:
                r = s.get(url, headers=headers, timeout=(10, 15),
                          allow_redirects=False, verify=False, proxies=proxies)
                return r.status_code, r.content or b"", r.headers.get("Location") or ""
        except Exception:
            return 0, b"", ""
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        opener = urllib.request.build_opener(NoRedirect())
        with opener.open(req, timeout=15, context=_no_verify_ctx()) as resp:
            return resp.status, resp.read(), resp.headers.get("Location") or ""
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read(), e.headers.get("Location") or ""
        except Exception:
            return e.code, b"", ""
    except Exception:
        return 0, b"", ""


try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass


def _sniff_mime(data, strict=False):
    """r()：按魔数认图片类型，失败返回 ''。"""
    if not data or len(data) < 4:
        return ""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(data) >= 8 and data[:8] == b"\x89PNG\r\n\x1a\n":
        if not strict:
            return "image/png"
        if len(data) >= 4 and data[-4:] == b"\xaeB`\x82":
            return "image/png"
        return ""
    if data[:6] in (b"GIF87a", b"GIF89a"):
        if not strict:
            return "image/gif"
        if data[-1:] == b";":
            return "image/gif"
        return ""
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return ""

# ---------------------------------------------------------------- Spider
class Spider(BaseSpider):
    def __init__(self):
        self.ext = {}        # a：init 解析的 ext
        self.booted = False  # b
        self.fail_at = 0     # c：上次初始化失败时间
        self.fail_msg = ""   # d：上次初始化失败信息
        self.cfg = {}        # f：引导配置 JSON
        self.domains = {}    # g：bootstrap 的 domain
        self.uuid = ""       # h
        self.token = ""      # i
        self.j = {}          # j：api 名 → host
        self.cfg_host = ""   # k：上次可用的引导配置 host
        self.api_base = ""   # l：上次可用的 API base（带 /）
        self.cache = {}      # m：{key: [ts, value]}
        self.blacklist = set()  # n：被劫持的 host
        self.expired = False    # o：凭证过期标记
        self.warn = ""       # p：m() 返回的警告（token 过期提示）
        self.jwt = None      # q：当前 token 的 JWT payload
        self.last_refresh = 0   # e：上次刷新引导的时间

    # -- 基础
    def getName(self):
        return SITE_NAME

    def getDependence(self):
        return ""

    def destroy(self):
        return

    def init(self, extend=""):
        ext = {}
        for part in re.split(r"[&\n;]+", extend or ""):
            part = part.strip()
            if not part:
                continue
            i = part.find("=")
            if i < 0:
                ext[part.lower()] = "1"
            else:
                ext[part[:i].strip().lower()] = part[i + 1:].strip()
        self.ext = ext
        self.booted = False
        self.fail_at = 0
        self.fail_msg = ""
        self.cfg_host = ""
        self.api_base = ""
        self.cache = {}
        self.blacklist = set()
        self.domains = {}
        self.uuid = ""
        self.expired = False
        self.warn = ""
        self.jwt = None

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def _proxies(self):
        """ext net=proxy + proxy=地址 时走代理（原版只在诊断文案里提，py 版真做了）。"""
        if _m(self.ext.get("net")) == "proxy":
            p = _m(self.ext.get("proxy"))
            if p:
                return {"http": p, "https": p}
        return None

    # -- 缓存 g(ttl, key)
    def _cache_get(self, ttl, key):
        ent = self.cache.get(key)
        if ent is None or ttl <= 0 or (_now() - ent[0]) >= ttl:
            return None
        return ent

    def _cache_put(self, key, value):
        self.cache[key] = [_now(), value]

    # -- 签名参数 G(token)
    def _sign_params(self, token):
        ts = str(_now())
        if self.jwt is None:
            self.jwt = _jwt_payload(self.token) if self.token else {}
        uuid = _m(self.ext.get("uuid")) or _m(self.jwt.get("uuid"))
        if not uuid:
            uuid = self.uuid or _rand_uuid()
        self.uuid = uuid
        userkey = _m(self.ext.get("userkey")) or _m(self.ext.get("user_key"))
        ip = _m(self.ext.get("ip")) or _m(self.jwt.get("ip")) or "0.0.0.0"
        platform = _m(self.ext.get("platform")) or "3"
        if token is None:
            token = self.token
        raw = "%s.%s.%s.%s.%s" % (ip, platform, ts, userkey, uuid)
        sign = _md5(_md5(raw) + SIGN_SALT)
        return {
            "ip": ip,
            "uuid": uuid,
            "timestamp": ts,
            "platform": platform,
            "token": token,
            "sign": sign,
            "user-key": userkey,
            "app-version": APP_VERSION,
            "User-Agent": UA_CHROME,
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded",
        }

    # -- 响应解析 H(text)
    def _parse_resp(self, text):
        """明文 JSON 直接解析；否则 base64 解后 AES 解密再解析。失败返回 None。"""
        t = (text or "").strip()
        if not t:
            return None
        if t.startswith("{"):
            try:
                return json.loads(t)
            except Exception:
                return None
        try:
            raw = _b64dec(t)
        except Exception:
            return None
        if len(raw) % 16 != 0:
            return None
        try:
            plain = _pkcs7_unpad(_aes_cbc(raw, KEY_REQ, IV_REQ, encrypt=False))
            return json.loads(plain.decode("utf-8"))
        except Exception:
            return None

    # -- 引导配置解密 h(bytes)
    @staticmethod
    def _decrypt_config(raw):
        """AES 解密（key x / iv y）→ zlib 解压 → JSON，必须是 dict。"""
        plain = _pkcs7_unpad(_aes_cbc(raw, KEY_CFG, IV_CFG, encrypt=False))
        obj = json.loads(zlib.decompress(plain).decode("utf-8"))
        if not isinstance(obj, dict):
            raise ValueError("box config 不是 JSON 对象")
        return obj

    # -- bootstrap 探测 b(base, headers)
    def _probe(self, base, headers):
        """POST {base}v2.5/bootstrap；成功返回 [base, json]，否则 None。"""
        try:
            status, body = _http_post(_ensure_slash(base) + "v2.5/bootstrap",
                                      headers, b"", timeout=8, proxies=self._proxies())
        except Exception:
            return None
        if status >= 400:
            return None
        if not body:
            return None
        try:
            text = body.decode("utf-8").strip()
        except Exception:
            return None
        if _is_hijack(text):
            return None
        obj = self._parse_resp(text)
        if not isinstance(obj, dict):
            return None
        if _m(obj.get("code")) != "200":
            return None
        token = _m(_as_map(_as_map(obj.get("data")).get("user")).get("token"))
        if not token:
            return None
        return [base, obj]

    def _bootstrap_hosts(self):
        """并行/串行引导共用的域名列表（ext api → 上次配置 → 内置线路）。"""
        hosts = []
        for h in [self.ext.get("api"), self.cfg_host] + BOOTSTRAP_HOSTS + LINE_HOSTS:
            u = _ensure_slash(h)
            if u and u not in hosts:
                hosts.append(u)
        return hosts[:12]

    def _apply_bootstrap(self, base, obj):
        """bootstrap 成功后落盘：token / domain / 媒体域名。"""
        data = _as_map(obj.get("data"))
        token = _m(_as_map(data.get("user")).get("token"))
        if not token:
            return False
        self.domains = _as_map(data.get("domain"))
        self.token = token
        self.api_base = base
        self.cfg_host = base
        one = self._first_domain("api") or self.api_base or DEFAULT_API
        one_img = self._first_domain("flutter_img") or (IMG_HOSTS[0] if IMG_HOSTS else FALLBACK_IMG)
        one_video = self._first_domain("video") or (FALLBACK_HOSTS[0] if FALLBACK_HOSTS else FALLBACK_VIDEO)
        self.j = {"one": one, "one_img": one_img, "one_video": one_video}
        self.jwt = None
        self.blacklist = set()
        self.expired = False
        return True

    # -- 快速引导 f()
    def _bootstrap_fast(self):
        """并行探测 API 域名（4 线程，15 秒），首个成功即用。"""
        hosts = self._bootstrap_hosts()
        headers = self._sign_params("")
        found = [None]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            futs = {ex.submit(self._probe, h, headers): h for h in hosts}
            try:
                for fut in concurrent.futures.as_completed(futs, timeout=15):
                    try:
                        r = fut.result()
                    except Exception:
                        r = None
                    if r is not None:
                        found[0] = r
                        break
            except Exception:
                pass
            for f in futs:
                f.cancel()
        if found[0] is None:
            return False
        return self._apply_bootstrap(found[0][0], found[0][1])

    def _bootstrap_serial(self):
        """串行探测（并行被出口限流时用）：逐个 POST v2.5/bootstrap，首个成功即用。"""
        headers = self._sign_params("")
        for h in self._bootstrap_hosts()[:8]:
            try:
                r = self._probe(h, headers)
            except Exception:
                r = None
            if r is not None and self._apply_bootstrap(r[0], r[1]):
                return True
        return False

    def _bootstrap_any(self):
        """先并行、再串行：任一成功即用。"""
        return self._bootstrap_fast() or self._bootstrap_serial()

    def _first_domain(self, key):
        """o(key)：domain 里第一个非空值（列表或标量）。"""
        v = self.domains.get(key)
        if isinstance(v, list):
            for x in v:
                if _m(x):
                    return _m(x)
            return ""
        return _m(v)

    # -- 引导配置 e()
    def _bootstrap_config(self):
        """拉 /box/api/config?channel=Channel 取 token_one。"""
        self.last_refresh = _now()
        if not self.uuid:
            self.uuid = self.ext.get("uuid") or _rand_uuid()
        if self._bootstrap_any():
            return
        cand = []
        line = _m(self.ext.get("line"))
        if line:
            cand.append(line)
        for h in CONFIG_HOSTS:
            if h != line:
                cand.append(h)
        if self.cfg_host and self.cfg_host not in cand:
            cand.insert(0, self.cfg_host)
        best = None
        last_err = None
        for host in cand:
            host = host.strip()
            if not host:
                continue
            try:
                url = _ensure_slash(host) + "box/api/config?channel=Channel"
                status, body = _http_post(
                    url, {"Content-Type": "application/x-www-form-urlencoded"},
                    b"", timeout=8, proxies=self._proxies())
                if status >= 400 or not body:
                    raise Exception("line HTTP %s" % status)
                cfg = self._decrypt_config(body)
                data = _as_map(cfg.get("data"))
                if not isinstance(data, dict):
                    raise Exception("invalid config shape")
                token_one = ""
                for item in _as_list(data.get("token")):
                    it = _as_map(item)
                    if _m(it.get("name")) == "token_one":
                        token_one = _m(it.get("token"))
                        break
                if not token_one:
                    raise Exception("config 里没有 token_one")
                exp = _jwt_exp(token_one)
                if best is None or exp > best[0]:
                    best = (exp, cfg, host, token_one)
                if exp > 0 and exp > _now():
                    break
            except Exception as e:
                last_err = e
        if best is not None:
            _, cfg, host, token_one = best
            self.cfg = cfg
            self.cfg_host = host
            self.token = token_one
            self.api_base = host + "/"
            self.jwt = None
            self.blacklist = set()
            j = {}
            for item in _as_list(_as_map(cfg.get("data")).get("api")):
                it = _as_map(item)
                name = _m(it.get("name"))
                if name:
                    j[name] = _m(it.get("host"))
            self.j = j
            return
        raise Exception(str(last_err) if last_err is not None else "bootstrap unavailable")

    # -- 初始化守门 m()
    def _ensure_boot(self):
        """返回 '' 表示就绪；否则返回失败/过期提示（调用方展示诊断卡）。"""
        if self.booted:
            return self.warn
        if self.fail_at > 0:
            cd = 20.0
            try:
                cd = float(_m(self.ext.get("cooldown")) or 20)
            except Exception:
                cd = 20.0
            if (_now() - self.fail_at) < cd:
                return self.fail_msg or "初始化失败"
        try:
            self._bootstrap_config()
        except Exception as e:
            self.fail_msg = "初始化失败: %s: %s" % (
                type(e).__name__, _d(120, str(e)))
            self.fail_at = _now()
            return self.fail_msg
        tok = _m(self.ext.get("token"))
        if tok:
            self.token = tok
            self.jwt = None
            self.expired = False
        self.booted = True
        self.fail_at = 0
        self.fail_msg = ""
        self.warn = self._token_warn()
        return self.warn

    def _token_warn(self):
        """n()：token 过期提示；没过期返回 ''。"""
        exp = _jwt_exp(self.token)
        if exp > 0:
            days = (_now() - exp) // 86400
            if days < 0:
                return ""
            self.expired = True
            return ("站点凭证已过期 %d 天（引导配置里的 token 是别人账号的旧 JWT，"
                    "有效期仅 7 天）｜修复：ext 填 token=有效token 或 "
                    "api=https://有效API域名/") % days
        if self.expired:
            return "站点凭证已过期(Expired token)，请在 ext 填 token=有效token"
        return ""

    # -- 核心请求 M(path, params, ttl)
    def _request(self, path, params, ttl):
        """POST 加密请求，多域名轮询；失败抛错（调用方包成诊断卡）。"""
        params = dict(params or {})
        key = path + "|" + "&".join("%s=%s" % (k, params[k])
                                    for k in sorted(params))
        if ttl > 0:
            ent = self._cache_get(ttl, key)
            if ent is not None and isinstance(ent[1], dict):
                return ent[1]
        body = ""
        if params:
            # 【补】拼请求体 k=v&k=v 的循环体在反编译产物里丢了，按缓存键同格式补。
            body = "&".join("%s=%s" % (k, params[k]) for k in params)
        enc = ""
        if body:
            enc = base64.b64encode(
                _aes_cbc(body.encode("utf-8"), KEY_REQ, IV_REQ, encrypt=True)
            ).decode("ascii")
        errs = []
        last_exc = None
        for attempt in range(2):
            hosts = self._api_hosts()
            for host in hosts:
                try:
                    status, raw = _http_post(
                        host + path.lstrip("/"), self._sign_params(None),
                        enc.encode("utf-8"), timeout=8, proxies=self._proxies())
                    if status >= 400:
                        raise Exception("HTTP %s" % status)
                    text = raw.decode("utf-8").strip() if raw else ""
                    if _is_hijack(text):
                        self.blacklist.add(host)
                        raise Exception("host 已被劫持(返回 html 跳转页)")
                    if not text.startswith("{"):
                        dec = _b64dec(text)
                        if len(dec) % 16 != 0:
                            raise Exception("响应不是 16 字节对齐的密文（多半是劫持页）")
                        try:
                            plain = _pkcs7_unpad(
                                _aes_cbc(dec, KEY_REQ, IV_REQ, encrypt=False))
                            obj = json.loads(plain.decode("utf-8"))
                        except Exception:
                            raise Exception("空响应(该域名不可用)")
                        if not isinstance(obj, dict) or (
                                "code" not in obj and "data" not in obj):
                            raise Exception("空响应(该域名不可用)")
                        code = _m(obj.get("code"))
                        if code not in ("0", "200"):
                            raise Exception("服务端 %s: %s" % (
                                code, _d(80, _m(obj.get("message")))))
                        self.api_base = host
                        if ttl > 0:
                            self._cache_put(key, obj)
                        return obj
                    # 【补】明文 JSON 成功分支在反编译产物里没有显式代码，
                    # 按加密分支的 code 0/200 判定补；401 / expired / 登录走过期流程。
                    obj = json.loads(text)
                    if not isinstance(obj, dict):
                        raise Exception("空响应(该域名不可用)")
                    code = _m(obj.get("code"))
                    msg = _m(obj.get("message"))
                    if code in ("0", "200"):
                        self.api_base = host
                        if ttl > 0:
                            self._cache_put(key, obj)
                        return obj
                    if code == "401" or "expired" in msg.lower() or "登录" in msg:
                        self.expired = True
                        raise Exception("凭证已过期(Expired token)")
                    raise Exception("服务端 %s: %s" % (code, _d(80, msg)))
                except Exception as e:
                    last_exc = e
                    errs.append("%s %s: %s" % (
                        host.replace("https://", "").replace("http://", "").split("/")[0],
                        type(e).__name__, _d(70, str(e))))
            if attempt == 0 and (_now() - self.last_refresh) >= 20:
                self.last_refresh = _now()
                if self._bootstrap_any():
                    self.booted = True
                    self.fail_at = 0
                    self.fail_msg = ""
                    self.warn = self._token_warn()
                    errs = []
                    continue
            break
        raise Exception(" | ".join(errs) if errs else (
            str(last_exc) if last_exc is not None else "request 失败"))

    def _api_hosts(self):
        """M() 的域名轮询：ext api → 上次可用 → 引导 one → line 域名，最多 3 个。"""
        cand = []
        api = _m(self.ext.get("api"))
        if api:
            cand.append(api)
        if self.api_base:
            cand.append(self.api_base)
        one = _m(self.j.get("one")) or DEFAULT_API
        cand.append(one)
        cand.extend(LINE_HOSTS)
        out = []
        for h in cand:
            u = _ensure_slash(h)
            if u and u not in out and u not in self.blacklist:
                out.append(u)
        if not out:
            out = [_ensure_slash(api or LINE_HOSTS[0])]
        return out[:3]

    # -- 媒体域名 B(kind)
    def _media_bases(self, kind):
        if kind == "video":
            keys = ["video", "flutter_video_download", "flutter_video_play", "audio_download"]
        elif kind == "hls":
            keys = ["video_hls", "audio_hls"]
        else:
            keys = ["audio", "flutter_audio_download"]
        out = []
        for k in keys:
            for v in _as_list(self.domains.get(k)):
                u = _m(v)
                while u.endswith("/"):
                    u = u[:-1]
                if u and u not in out:
                    out.append(u)
        if not out and kind == "video":
            one_video = _m(self.j.get("one_video"))
            if one_video:
                u = one_video
                while u.endswith("/"):
                    u = u[:-1]
                if u:
                    out.append(u)
            for h in FALLBACK_HOSTS:
                if h not in out:
                    out.append(h)
        return out[:6]

    # -- 相对地址展开 a(url, kind)
    def _fix_media(self, url, kind):
        u = _m(url)
        if not u.startswith("http://") and not u.startswith("https://"):
            if not u:
                return ""
            bases = self._media_bases(kind)
            if not bases:
                return ""
            return bases[0] + ("" if u.startswith("/") else "/") + u
        return u

    # -- 播放条目展开 L(list, url, name, desc)
    def _expand_play(self, out, url, name, desc):
        u = _m(url)
        if not u:
            return
        if u.startswith("http://") or u.startswith("https://"):
            out.append([name, u, desc])
            return
        bases = self._media_bases("video")
        for i, b in enumerate(bases[:5]):
            nm = name + (" 线路%d" % (i + 1) if len(bases) > 1 else "")
            out.append([nm, b + ("" if u.startswith("/") else "/") + u, desc])

    # -- 是否预览 v(map)
    def _is_preview(self, item):
        if item is None:
            return True
        if _m(item.get("video_download")):
            return False
        vf = _m(item.get("video_file"))
        pv = _m(item.get("preview_video"))
        if not vf:
            return bool(pv)
        if not pv or pv != vf:
            low = vf.lower()
            return any(mk in low for mk in PREVIEW_MARKERS)
        return True

    # -- 播放列表 P(map)
    def _play_entries(self, item):
        out = []
        preview = self._is_preview(item)
        vd = _m(item.get("video_download"))
        vf = _m(item.get("video_file"))
        self._expand_play(out, vd, "完整片", "完整版 MP4 · 可拖动")
        if vf and vf != vd:
            if preview:
                self._expand_play(out, vf, "预告", "预告片（非完整版）")
            else:
                self._expand_play(out, vf, "正片", "MP4 · 可拖动")
        if not out or preview:
            for key, nm in (("video_hls", "HLS 备用"), ("video_hls_h265", "HLS H265 备用")):
                u = _m(item.get(key))
                if u:
                    out.append([nm, self._fix_media(u, "hls"), "加密清单，可能播不了"])
        af = _m(item.get("audio_file"))
        if af:
            out.append(["音频", self._fix_media(af, "audio"), "音频"])
        if not out:
            pv = _m(item.get("preview_video"))
            if pv:
                self._expand_play(out, pv, "预览", "预览片段")
        seen = set()
        dedup = []
        for e in out:
            if e[1] and e[1] not in seen:
                seen.add(e[1])
                dedup.append(e)
        return dedup

    # -- 图片地址修正 t(url)
    def _fix_img(self, url):
        u = _m(url)
        if not u:
            return ""
        bases = []
        for v in _as_list(self.domains.get("flutter_img")):
            s = _m(v)
            if s:
                bases.append(s)
        bases.extend(IMG_HOSTS)
        bases = [b.rstrip("/") for b in bases if b.rstrip("/")]
        if u.startswith("http://") or u.startswith("https://"):
            for d in IMG_STRIP_DOMAINS:
                if d in u:
                    i = u.find("://")
                    j = u.find("/", i + 3)
                    if j >= 0:
                        end = len(u)
                        q = u.find("?", j)
                        if q >= 0:
                            end = q
                        h = u.find("#", j)
                        if 0 <= h < end:
                            end = h
                        u = u[j:end]
                    else:
                        u = "/"
                    break
            if u.startswith("http"):
                return u
            if not u.startswith("/"):
                return u
        if bases:
            return bases[0] + ("" if u.startswith("/") else "/") + u
        host = _m(self.j.get("one_img")) or FALLBACK_IMG
        host = host.rstrip("/")
        u = u.lstrip("/")
        return host + "/" + u if host else ""

    # -- 图集 J(map)
    def _images(self, item):
        text = _m(item.get("content")) or _m(item.get("description"))
        imgs = []
        for m in re.finditer(r"<img[^>]+src=[\"']([^\"']+)[\"']", text):
            u = _m(m.group(1))
            if u:
                if not u.startswith("http://") and not u.startswith("https://"):
                    u = self._fix_img(u)
                imgs.append(u)
        if not imgs:
            for key in ("multiple_pic", "multi_pic_thumbnail800", "multi_pic_thumbnail"):
                v = item.get(key)
                if isinstance(v, list):
                    cand = [_m(x) for x in v if _m(x)]
                elif _m(v).startswith("["):
                    cand = re.findall(r"[\"']([^\"']*)[\"']", _m(v))
                else:
                    cand = []
                if cand:
                    for u in cand:
                        if not u.startswith("http://") and not u.startswith("https://"):
                            u = self._fix_img(u)
                        if u and u not in imgs:
                            imgs.append(u)
                    if imgs:
                        break
        imgs = [x for x in imgs if x]
        if not imgs:
            return ""
        return "pics://" + "&&".join(imgs)

    # -- 视频卡片 w(map)
    def _card_video(self, item):
        if item is None:
            return None
        vid = _m(item.get("id"))
        if not vid:
            return None
        remarks = _d(20, _m(item.get("video_length")))
        if not remarks and self._is_preview(item) and (
                _m(item.get("preview_video")) or _m(item.get("video_file"))):
            remarks = "预告"
        return {
            "vod_id": vid,
            "vod_name": _d(80, _m(item.get("title"))),
            "vod_pic": self._fix_img(_m(item.get("thumb")) or _m(item.get("thumbnail"))),
            "vod_remarks": remarks,
            "vod_year": _d(4, _m(item.get("published_at"))),
            "vod_content": _d(0, _m(item.get("description"))),
            "vod_play_from": "One",
            "vod_play_url": "正片$%s" % vid,
        }

    # -- 图集/漫画卡片 N(kind, item)
    def _card_album(self, kind, item):
        vid = ("m:" if kind == "manga" else "a:") + _m(item.get("id"))
        return {
            "vod_id": vid,
            "vod_name": _d(80, _m(item.get("title"))),
            "vod_pic": self._fix_img(_m(item.get("thumb")) or _m(item.get("thumbnail"))),
            "vod_remarks": _d(10, _m(item.get("latest_at"))),
            "vod_year": _d(4, _m(item.get("first_at"))),
            "vod_content": "作者: " + _d(40, _m(item.get("author"))),
            "vod_play_from": "漫画" if kind == "manga" else "写真",
            "vod_play_url": "全篇$%s" % vid,
        }

    # -- 文章发现 C(model, tag, published_at, size)
    def _discovery(self, model, tag, published_at, size):
        key = "mi|%s|%s|%s" % (model, tag, published_at)
        ent = self._cache_get(900, key)
        if ent is not None:
            state = dict(ent[1])
        else:
            state = {"rows": [], "pages": 0, "done": False}
        need = max(20, size)
        max_pages = min(4, (need + 99) // 100)
        pub = published_at
        while not state["done"] and state["pages"] < max_pages:
            nxt = state["pages"] + 1
            params = {
                "demand_tag_id": str(tag),
                "model_id": str(model),
                "page": str(nxt),
                "published_at": pub,
                "size": "100",
                "sort": "published_at",
            }
            rows = _as_list(self._request("v2.5/article/discovery", params, 900).get("data"))
            if not rows:
                break
            state["rows"] = state["rows"] + rows
            state["pages"] = nxt
            if len(rows) < 100:
                state["done"] = True
            pub = published_at
        self._cache_put(key, state)
        return list(state["rows"])

    # -- 分类分页 q(model, tag, page)
    def _paginate(self, model, tag, page):
        offset = (max(1, page) - 1) * 20
        try:
            months = int(_m(self.ext.get("months")) or 12)
        except Exception:
            months = 12
        months = max(0, months)
        empty = 0
        for i in range(months):
            try:
                rows = self._discovery(model, tag, _month_ago(i), offset + 20)
            except Exception:
                if i == 0:
                    raise
                break
            if not rows:
                empty += 1
                if i > 0 and empty >= 3:
                    return None
            elif offset < len(rows):
                return rows[offset:min(len(rows), offset + 20)]
            else:
                offset -= len(rows)
                empty = 0
        return None

    # -- 系列选集 i(series_id, vod)
    def _detail_series(self, series_id, vod):
        try:
            if not re.fullmatch(r"\d+", str(series_id)):
                return None
            data = _as_map(self._request(
                "v2.5/series/chapters", {"series_id": str(series_id)}, 900).get("data"))
            chapters = _as_list(data.get("chapters"))
            entries = []
            for ch in chapters:
                ch = _as_map(ch)
                cid = _m(ch.get("id"))
                if not cid:
                    continue
                title = _m(ch.get("title")) or "第%s集" % _m(ch.get("chapter"))
                title = _d(30, title)
                for e in self._play_entries(ch)[:3]:
                    entries.append("%s %s$%s" % (title, e[0], e[1]))
                entries.append("%s$%s" % (title, cid))
            if not entries:
                return None
            vod["vod_play_from"] = "One"
            vod["vod_play_url"] = "#".join(entries)
            vod["vod_remarks"] = "共%d集" % len(chapters)
            return {"list": [vod]}
        except Exception as e:
            import sys
            print("detail_series err:", e, file=sys.stderr)
            return None

    # -- 图集/漫画详情 j(series_id, prefix)
    def _detail_album(self, series_id, prefix):
        data = _as_map(self._request(
            "v2.5/series/chapters", {"series_id": str(series_id)}, 900).get("data"))
        chapters = _as_list(data.get("chapters"))
        entries = []
        for ch in chapters:
            ch = _as_map(ch)
            cid = _m(ch.get("id"))
            if not cid:
                continue
            title = _m(ch.get("title")) or "第%s话" % _m(ch.get("chapter"))
            entries.append("%s$%s" % (_d(40, title), cid))
        vod = {
            "vod_id": str(series_id),
            "vod_name": _d(80, _m(data.get("title"))),
            "vod_pic": self._fix_img(_m(data.get("thumb"))),
            "vod_year": _d(4, _m(data.get("first_at"))),
            "vod_area": "",
            "vod_class": "",
            "vod_director": "",
            "vod_actor": _d(40, _m(data.get("author"))),
            "vod_content": _d(0, _m(data.get("description"))),
            "vod_remarks": "共%d话" % len(chapters),
            "vod_play_from": "漫画" if prefix == "m" else "写真",
            "vod_play_url": "#".join(entries),
        }
        return {"list": [vod]}

    # -- 诊断卡 l/k
    @staticmethod
    def _diag_card(title, reason, guide=DIAG_GUIDE):
        return {
            "vod_id": "diag",
            "vod_name": "【诊断】" + _d(40, title),
            "vod_pic": "",
            "vod_remarks": "看简介",
            "vod_year": "",
            "vod_content": "▸ " + _d(120, title) + "\n\n原因：" + _d(200, reason) + "\n\n" + guide,
            "vod_play_from": "",
            "vod_play_url": "",
        }

    @classmethod
    def _diag_page(cls, page, title, reason):
        return {
            "page": page,
            "pagecount": page,
            "limit": 20,
            "total": 1,
            "list": [cls._diag_card(title, reason)],
        }

    # -- 图片代理 s(url)
    def _fetch_img(self, url):
        ua = _m(self.ext.get("ua")) or UA_CHROME
        try:
            to = int(_m(self.ext.get("imgtimeout")) or 15)
        except Exception:
            to = 15
        return _http_get(url, {"User-Agent": ua}, timeout=to, proxies=self._proxies())

    # -- localProxy 允许的 host d()
    def _allowed_img_hosts(self):
        hosts = set()
        for key, fb in (("one_img", FALLBACK_IMG), ("one_video", FALLBACK_VIDEO)):
            h = _host_of(_m(self.j.get(key)) or fb)
            if h:
                hosts.add(h)
        for key in ("flutter_img", "resource", "image", "image_low", "video",
                    "video_hls", "flutter_video_play", "flutter_video_download",
                    "audio", "audio_download", "audio_hls"):
            for v in _as_list(self.domains.get(key)):
                h = _host_of(v)
                if h:
                    hosts.add(h)
        for h in _m(self.ext.get("host")).split(","):
            h = _host_of(h.strip())
            if h:
                hosts.add(h)
        return hosts

    # ================================================================ 公开接口
    def homeContent(self, filter=False, *args, **kwargs):
        if not auth_check(self._proxies()):
            return {}
        classes = [{"type_id": tid, "type_name": name} for tid, name in CATEGORIES]
        out = {"class": classes, "filters": {}}
        warn = self._ensure_boot()
        lst = []
        if warn:
            lst.append(self._diag_card(
                "源未就绪", warn,
                "ext 可填 line= 换引导线路；连不上就 net=proxy,proxy=http://ip:端口"))
        out["list"] = lst
        return out

    def homeVideoContent(self):
        if not auth_check(self._proxies()):
            return {}
        lst = []
        if not self._ensure_boot():
            try:
                model, tag = CATEGORIES[3][0].split("_")  # 6_5 新作
                rows = self._discovery(_n(model), _n(tag), _month_ago(0), 0)
                seen = set()
                for item in rows:
                    vid = _m(_as_map(item).get("id"))
                    if vid and vid not in seen:
                        seen.add(vid)
                        card = self._card_video(_as_map(item))
                        if card:
                            lst.append(card)
                lst = lst[:20]
            except Exception:
                lst = []
        return {"list": lst}

    def categoryContent(self, tid, pg, filter=False, extend=None, *args, **kwargs):
        page = max(1, _n(pg) or 1)
        tid = _m(tid)
        if tid not in CAT_IDS:
            tid = CATEGORIES[0][0]
        if not auth_check(self._proxies()):
            return {}
        warn = self._ensure_boot()
        if warn:
            return self._diag_page(page, "源未就绪", warn)
        try:
            if tid in ("manga", "album"):
                path = ("v2.5/series/manga/list" if tid == "manga"
                        else "v2.5/series/album/list")
                data = self._request(path, {"page": str(page), "size": "20"}, 300)
                lst = []
                for item in _as_list(data.get("data")):
                    item = _as_map(item)
                    if _m(item.get("id")):
                        lst.append(self._card_album(tid, item))
                return {
                    "page": page,
                    "pagecount": page + 1 if len(lst) >= 20 else page,
                    "limit": 20,
                    "total": len(lst),
                    "list": lst,
                }
            model, tag = tid.split("_")
            rows = self._paginate(_n(model), _n(tag), page)
            lst = []
            if rows:
                seen = set()
                for item in rows:
                    item = _as_map(item)
                    vid = _m(item.get("id"))
                    if vid and vid not in seen:
                        seen.add(vid)
                        card = self._card_video(item)
                        if card:
                            lst.append(card)
            return {
                "page": page,
                "pagecount": page + 1 if rows and len(rows) >= 20 else page,
                "limit": 20,
                "total": len(lst),
                "list": lst,
            }
        except Exception as e:
            return self._diag_page(page, "列表拉取失败",
                                   "%s: %s" % (type(e).__name__, str(e)))

    def detailContent(self, ids, *args, **kwargs):
        if isinstance(ids, (list, tuple)):
            vid = ids[0] if ids else ""
        else:
            vid = str(ids)
        vid = _m(vid)
        if not auth_check(self._proxies()):
            return {}
        warn = self._ensure_boot()
        if warn:
            return {"list": [self._diag_card(
                "源未就绪", warn, "ext 可填 line= 换引导线路")]}
        try:
            prefix = ""
            if vid.startswith("m:") or vid.startswith("a:"):
                prefix = vid[0]
                vid = vid[2:]
            if not re.fullmatch(r"\d+", vid):
                return {"list": [self._diag_card(
                    "详情参数不对", "id=" + vid, "换个条目再点一次")]}
            sid = int(vid)
            if not prefix:
                data = _as_map(self._request(
                    "v2.5/article/detail", {"id": str(sid)}, 900).get("data"))
                vod = self._card_video(data) or {}
                vod["vod_id"] = str(sid)
                vod["vod_director"] = "小迷弟的小弟"
                entries = self._play_entries(data)
                series_id = _m(data.get("series_id")) or _m(data.get("series"))
                if not entries and series_id:
                    got = self._detail_series(series_id, vod)
                    if got is not None:
                        return got
                pics = self._images(data)
                srcs = []
                urls = []
                if entries:
                    srcs.append("One")
                    urls.append("#".join("%s$%s" % (e[0], e[1]) for e in entries))
                if pics:
                    srcs.append("图集")
                    urls.append("图集$%s" % pics)
                if not srcs:
                    vod["vod_remarks"] = "无视频源" if not self._is_preview(data) else "预览"
                vod["vod_play_from"] = "$$$".join(srcs)
                vod["vod_play_url"] = "$$$".join(urls)
                return {"list": [vod]}
            return self._detail_album(sid, prefix)
        except Exception as e:
            return {"list": [self._diag_card(
                "详情请求失败", "%s: %s" % (type(e).__name__, str(e)),
                "换个分类再点一次；还不行截图这条发我")]}

    def searchContent(self, key, quick=False, pg="1", *args, **kwargs):
        page = max(1, _n(pg) or 1)
        if not auth_check(self._proxies()):
            return {}
        warn = self._ensure_boot()
        if warn:
            return self._diag_page(page, "源未就绪", warn)
        try:
            data = self._request("v2.5/article/search", {
                "keyword": key or "",
                "page": str(page),
                "size": "20",
            }, 180)
            # 【补】结果循环在反编译产物里丢了，按 categoryContent 视频分支补：
            # data 去重后转 w() 卡片，满 20 条则 pagecount+1。
            lst = []
            seen = set()
            for item in _as_list(data.get("data")):
                item = _as_map(item)
                vid = _m(item.get("id"))
                if vid and vid not in seen:
                    seen.add(vid)
                    card = self._card_video(item)
                    if card:
                        lst.append(card)
            return {
                "page": page,
                "pagecount": page + 1 if len(lst) >= 20 else page,
                "limit": 20,
                "total": len(lst),
                "list": lst,
            }
        except Exception as e:
            return self._diag_page(page, "搜索失败",
                                   "%s: %s" % (type(e).__name__, str(e)))

    def playerContent(self, flag, id, vipFlags, *args, **kwargs):
        if not auth_check(self._proxies()):
            return {}
        pid = _m(id)
        out = {"parse": 0, "playUrl": "", "url": "", "header": {}}
        try:
            if pid.startswith("pics://"):
                out["url"] = pid
                out["header"] = self._play_headers()
                return out
            if pid.startswith("http://") or pid.startswith("https://"):
                out["url"] = pid
                out["header"] = {}
                return out
            warn = self._ensure_boot()
            if warn:
                out["error"] = warn
                return out
            last = pid.split("$")[-1]
            if last.startswith("m:") or last.startswith("a:"):
                last = last[2:]
            if re.fullmatch(r"\d+", last):
                data = _as_map(self._request(
                    "v2.5/article/detail", {"id": str(int(last))}, 900).get("data"))
                entries = self._play_entries(data)
                if entries:
                    out["url"] = entries[0][1]
                    out["header"] = self._play_headers()
                    return out
                pics = self._images(data)
                if pics:
                    out["url"] = pics
                    out["header"] = self._play_headers()
                    return out
                out["error"] = "该条目没有可播放的正片"
                return out
            out["error"] = "无法识别的播放 id"
            return out
        except Exception as e:
            out["url"] = ""
            out["header"] = {}
            out["error"] = "%s: %s" % (type(e).__name__, str(e))
            return out

    def _play_headers(self):
        """A()：播放请求头。mediaua 覆盖 UA；playref=1 时加 Referer/Origin。"""
        ua = _m(self.ext.get("mediaua")) or UA_DART
        h = {"User-Agent": ua}
        if _m(self.ext.get("playref")) == "1":
            ref = _m(self.j.get("one")) or DEFAULT_API
            h["Referer"] = ref
            h["Origin"] = ref.rstrip("/")
        return h

    def liveContent(self, url):
        return {}

    def localProxy(self, param):
        if not auth_check(self._proxies()):
            return [404, "text/plain", "not found"]
        try:
            p = _m(param)
            url = ""
            key = ""
            if p.startswith("{"):
                try:
                    obj = json.loads(p)
                except Exception:
                    obj = {}
                url = _m(obj.get("url"))
                key = _m(obj.get("k"))
            else:
                for part in p.split("&"):
                    if "=" in part:
                        k, v = part.split("=", 1)
                        v = urllib.parse.unquote_plus(v)
                        if k == "url":
                            url = v
                        elif k == "k":
                            key = v
            if not url.startswith("http://") and not url.startswith("https://"):
                try:
                    url = urllib.parse.unquote(url)
                except Exception:
                    pass
            if not url.startswith("http://") and not url.startswith("https://"):
                return [400, "text/plain", "invalid proxy URL"]
            parsed = urllib.parse.urlparse(url)
            if parsed.username or parsed.fragment:
                return [400, "text/plain", "proxy url is not allowed"]
            if not key:
                allowed = self._allowed_img_hosts()
                if not allowed and not self.j:
                    self._ensure_boot()
                    allowed = self._allowed_img_hosts()
                if allowed and _host_of(url) not in allowed:
                    return [403, "text/plain", "proxy host is not allowed"]
            else:
                expect = _md5("one-img|%s|%s" % (url, PROXY_SIGN_TAG))[:16]
                if key != expect:
                    return [400, "text/plain", "proxy url is not allowed"]
            status, body = self._fetch_img(url)
            if status >= 400:
                return [502, "text/plain", "proxy upstream HTTP %s" % status]
            if not body:
                return [502, "text/plain", "proxy image integrity check failed"]
            for data, strict in ((self._decrypt_img(body), False), (body, True)):
                if data:
                    mime = _sniff_mime(data, strict)
                    if mime:
                        return [200, mime, data]
            return [502, "text/plain", "proxy image integrity check failed"]
        except Exception as e:
            return [502, "text/plain",
                    "proxy error: %s" % type(e).__name__]

    def _decrypt_img(self, body):
        """图片先试 AES 解密（key C / iv D），失败返回 None。"""
        try:
            return _pkcs7_unpad(_aes_cbc(body, KEY_IMG, IV_IMG, encrypt=False))
        except Exception:
            return None


if __name__ == "__main__":
    # 1) AES 自检（FIPS-197 向量）
    _k = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    _p = bytes.fromhex("00112233445566778899aabbccddeeff")
    _c = _aes_block(_k, _p, True)
    assert _c.hex() == "69c4e0d86a7b0430d8cdb78070b4c55a", _c.hex()
    assert _aes_block(_k, _c, False) == _p
    _k2 = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
    _p2 = bytes.fromhex("3243f6a8885a308d313198a2e0370734")
    assert _aes_block(_k2, _p2, True).hex() == "3925841d02dc09fbdc118597196a0b32"
    print("AES self-test OK")
    print("auth:", auth_check())
    sp = Spider()
    sp.init("")
    home = sp.homeContent(False)
    print("home classes:", [(c["type_id"], c["type_name"]) for c in home.get("class", [])])
    print("home list(diag?):", json.dumps(home.get("list", []), ensure_ascii=False)[:300])
    hv = sp.homeVideoContent()
    print("homeVideo:", len(hv.get("list", [])), hv.get("list", [])[:1])
    cat = sp.categoryContent("6_3", 1, False, {})
    print("category 6_3 国产:", len(cat.get("list", [])), cat.get("list", [])[:1])
    if cat.get("list"):
        vid = cat["list"][0].get("vod_id", "")
        print("detail for", vid)
        d = sp.detailContent([vid])
        print(json.dumps(d, ensure_ascii=False)[:900])
        if d.get("list") and d["list"][0].get("vod_play_url"):
            first = d["list"][0]["vod_play_url"].split("$$$")[0].split("#")[0].split("$", 1)[-1]
            print("player:", json.dumps(sp.playerContent("One", first, []), ensure_ascii=False)[:600])
    print("search:", len(sp.searchContent("test", False, "1").get("list", [])))
