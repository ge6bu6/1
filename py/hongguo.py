# -*- coding: utf-8 -*-
# ===========================================================================
#  红果短剧 TVBox Python 源  —— 全集 + 五档清晰度 + 内存流式代理版
#
#  链路：
#    分类/详情  → hongguoduanju.com 服务端渲染页面（含全部 vid_list，全集一次拿完）
#    播放模型   → api5-normal-*.fqnovel.com/novel/player/multi_video_model/v1/
#                 （gzip body + X-Gorgon/X-Helios/X-Argus/X-Ladon 全套签名）
#    播放地址   → 本地后台 HTTP 代理内存实时解密转发（无磁盘缓存占用，支持 Range 拖拽）
#
#  挂载：
#  {"key":"hongguo","name":"红果短剧","type":3,
#   "api":"clan://./py/hongguo_full.py","searchable":1,"quickSearch":1,"filterable":1}
# ===========================================================================

import base64
import gzip as _gzip
import hashlib
import io
import json
import random
import re
import socket
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

try:
    import requests
    _HAS_REQ = True
except Exception:
    _HAS_REQ = False

# ------------------------------------------------------------------ 常量
WEB = 'https://hongguoduanju.com'
API_HOSTS = [
    'api5-normal-sinfonlinea.fqnovel.com',
    'api5-normal-sinfonlineb.fqnovel.com',
    'api5-normal-lf.fqnovel.com',
    'api5-normal-hq.fqnovel.com',
    'api5-normal-lq.fqnovel.com',
]
AID = '8662'
APP_NAME = 'novelread'
VERSION_CODE = '74332'
VERSION_NAME = '7.4.3.32'

# 首次运行会自动注册；也可在 ext 里固定填下面的值
DEF_DEV = {
    'device_id': '2838319312671600',
    'iid': '2838319312675696',
    'install_id': '2838319312675696',
}

MODELS = ['25053RT47C', '23046PNC9C', '23127PN0CC',
          '22081212C', '2211133C', '23013RK75C', '24069RA21C']

UA_APP = ('com.phoenix.read/%s (Linux; U; Android 16; zh_CN; %%s; '
          'Build/BP2A.250605.031.A3; Cronet/TTNetVersion:8d40f833 2026-03-03 '
          'QuicVersion:21ac1950 2025-11-18)' % VERSION_CODE)
UA_WEB = ('Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 '
          '(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36')

SALT = bytes.fromhex(
    '4dd4c2e6b83162090e52b3c7a6733ba41cb2462b829ab58a196b39db57177524'
    'f49baf7f08e8d68d26a72e37c1a95a2f1f05a51892aef2949732b62a38aadd58')
MAGIC = bytes([116, 99, 5, 16, 0, 0])

# 分类：c: 走 /category，r: 走 /rank
CATS = [
    ('c:real-drama', '真人剧'), ('c:comic-drama', '漫剧'),
    ('c:ai-drama', 'AI剧'), ('c:comic', '漫画'),
    ('r:hot-drama', '热播总榜'), ('r:hot-real-drama', '真人剧榜'),
    ('r:hot-comic-drama', '漫剧榜'), ('r:hot-ai-drama', 'AI剧榜'),
    ('t:jx', '头条精选'),
    ('c:__diag__', '自检诊断'),
]

# 清晰度线路
QUALITIES = [('1080p', 4), ('720p', 3), ('540p', 2), ('480p', 1), ('360p', 0)]


# =============================== SM3 =======================================
_IV = [0x7380166F, 0x4914B2B9, 0x172442D7, 0xDA8A0600,
       0xA96F30BC, 0x163138AA, 0xE38DEE4D, 0xB0FB0E4E]


def _rotl(x, n):
    n &= 31
    return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF


def _p0(x):
    return x ^ _rotl(x, 9) ^ _rotl(x, 17)


def _p1(x):
    return x ^ _rotl(x, 15) ^ _rotl(x, 23)


def _sm3_cf(v, block):
    w = list(struct.unpack('>16I', block)) + [0] * 52
    for j in range(16, 68):
        w[j] = _p1(w[j - 16] ^ w[j - 9] ^ _rotl(w[j - 3], 15)) ^ _rotl(w[j - 13], 7) ^ w[j - 6]
    w1 = [w[j] ^ w[j + 4] for j in range(64)]
    a, b, c, d, e, f, g, h = v
    for j in range(64):
        t = 0x79CC4519 if j < 16 else 0x7A879D8A
        ss1 = _rotl((_rotl(a, 12) + e + _rotl(t, j)) & 0xFFFFFFFF, 7)
        ss2 = ss1 ^ _rotl(a, 12)
        if j < 16:
            ff, gg = a ^ b ^ c, e ^ f ^ g
        else:
            ff = (a & b) | (a & c) | (b & c)
            gg = (e & f) | (~e & g & 0xFFFFFFFF)
        tt1 = (ff + d + ss2 + w1[j]) & 0xFFFFFFFF
        tt2 = (gg + h + ss1 + w[j]) & 0xFFFFFFFF
        d, c, b, a = c, _rotl(b, 9), a, tt1
        h, g, f, e = g, _rotl(f, 19), e, _p0(tt2)
    return [v[0] ^ a, v[1] ^ b, v[2] ^ c, v[3] ^ d,
            v[4] ^ e, v[5] ^ f, v[6] ^ g, v[7] ^ h]


def sm3(data):
    bl = len(data) * 8
    data = data + b'\x80'
    while len(data) % 64 != 56:
        data += b'\x00'
    data += struct.pack('>Q', bl)
    v = _IV[:]
    for i in range(0, len(data), 64):
        v = _sm3_cf(v, data[i:i + 64])
    return struct.pack('>8I', *v)


# ============================= 纯 Python AES ===============================
_SBOX = bytes.fromhex(
    '637c777bf26b6fc53001672bfed7ab76ca82c97dfa5947f0add4a2af9ca472c0'
    'b7fd9326363ff7cc34a5e5f171d8311504c723c31896059a071280e2eb27b275'
    '09832c1a1b6e5aa0523bd6b329e32f8453d100ed20fcb15b6acbbe394a4c58cf'
    'd0efaafb434d338545f9027f503c9fa851a3408f929d38f5bcb6da2110fff3d2'
    'cd0c13ec5f974417c4a77e3d645d197360814fdc222a908846eeb814de5e0bdb'
    'e0323a0a4906245cc2d3ac629195e479e7c8376d8dd54ea96c56f4ea657aae08'
    'ba78252e1ca6b4c6e8dd741f4bbd8b8a703eb5664803f60e613557b986c11d9e'
    'e1f8981169d98e949b1e87e9ce5528df8ca1890dbfe6426841992d0fb054bb16')
_ISBOX = bytearray(256)
for _i, _v in enumerate(_SBOX):
    _ISBOX[_v] = _i
_ISBOX = bytes(_ISBOX)
_RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]


def _xtime(a):
    a <<= 1
    return (a ^ 0x1B) & 0xFF if a & 0x100 else a


def _mul(a, b):
    r = 0
    for _ in range(8):
        if b & 1:
            r ^= a
        b >>= 1
        a = _xtime(a)
    return r & 0xFF


def _expand_key(key):
    nk = len(key) // 4
    nr = nk + 6
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    for i in range(nk, 4 * (nr + 1)):
        t = list(w[i - 1])
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[x] for x in t]
            t[0] ^= _RCON[i // nk - 1]
        elif nk > 6 and i % nk == 4:
            t = [_SBOX[x] for x in t]
        w.append([w[i - nk][j] ^ t[j] for j in range(4)])
    return w, nr


def _enc_block(block, w, nr):
    s = [[block[r + 4 * c] for c in range(4)] for r in range(4)]
    for c in range(4):
        for r in range(4):
            s[r][c] ^= w[c][r]
    for rnd in range(1, nr + 1):
        for r in range(4):
            for c in range(4):
                s[r][c] = _SBOX[s[r][c]]
        for r in range(1, 4):
            s[r] = s[r][r:] + s[r][:r]
        if rnd != nr:
            for c in range(4):
                a = [s[r][c] for r in range(4)]
                s[0][c] = _mul(a[0], 2) ^ _mul(a[1], 3) ^ a[2] ^ a[3]
                s[1][c] = a[0] ^ _mul(a[1], 2) ^ _mul(a[2], 3) ^ a[3]
                s[2][c] = a[0] ^ a[1] ^ _mul(a[2], 2) ^ _mul(a[3], 3)
                s[3][c] = _mul(a[0], 3) ^ a[1] ^ a[2] ^ _mul(a[3], 2)
        for c in range(4):
            for r in range(4):
                s[r][c] ^= w[rnd * 4 + c][r]
    return bytes(s[r][c] for c in range(4) for r in range(4))


def _dec_block(block, w, nr):
    s = [[block[r + 4 * c] for c in range(4)] for r in range(4)]
    for c in range(4):
        for r in range(4):
            s[r][c] ^= w[nr * 4 + c][r]
    for rnd in range(nr - 1, -1, -1):
        for r in range(1, 4):
            s[r] = s[r][-r:] + s[r][:-r]
        for r in range(4):
            for c in range(4):
                s[r][c] = _ISBOX[s[r][c]]
        for c in range(4):
            for r in range(4):
                s[r][c] ^= w[rnd * 4 + c][r]
        if rnd != 0:
            for c in range(4):
                a = [s[r][c] for r in range(4)]
                s[0][c] = _mul(a[0], 14) ^ _mul(a[1], 11) ^ _mul(a[2], 13) ^ _mul(a[3], 9)
                s[1][c] = _mul(a[0], 9) ^ _mul(a[1], 14) ^ _mul(a[2], 11) ^ _mul(a[3], 13)
                s[2][c] = _mul(a[0], 13) ^ _mul(a[1], 9) ^ _mul(a[2], 14) ^ _mul(a[3], 11)
                s[3][c] = _mul(a[0], 11) ^ _mul(a[1], 13) ^ _mul(a[2], 9) ^ _mul(a[3], 14)
    return bytes(s[r][c] for c in range(4) for r in range(4))


def aes_cbc_encrypt(key, iv, data):
    w, nr = _expand_key(key)
    out, prev = b'', iv
    for i in range(0, len(data) - len(data) % 16, 16):
        blk = bytes(a ^ b for a, b in zip(data[i:i + 16], prev))
        prev = _enc_block(blk, w, nr)
        out += prev
    return out


def aes_cbc_decrypt(key, iv, data):
    w, nr = _expand_key(key)
    out, prev = b'', iv
    for i in range(0, len(data) - len(data) % 16, 16):
        blk = data[i:i + 16]
        dec = _dec_block(blk, w, nr)
        out += bytes(a ^ b for a, b in zip(dec, prev))
        prev = blk
    return out


# =============================== 工具 ======================================
def md5(b):
    return hashlib.md5(b).digest()


def sha512(b):
    return hashlib.sha512(b).digest()


def le32(n):
    return struct.pack('<I', n & 0xFFFFFFFF)


def le64(n):
    return struct.pack('<Q', n & 0xFFFFFFFFFFFFFFFF)


def rotr64(x, n):
    n &= 63
    return ((x >> n) | (x << (64 - n))) & 0xFFFFFFFFFFFFFFFF


def b64d(s):
    s = (s or '').replace('-', '+').replace('_', '/')
    s += '=' * (-len(s) % 4)
    return base64.b64decode(s)


def gzipb(data):
    if not isinstance(data, bytes):
        data = data.encode('utf-8')
    buf = io.BytesIO()
    with _gzip.GzipFile(fileobj=buf, mode='wb', mtime=0) as f:
        f.write(data)
    return buf.getvalue()


def ungzip(raw):
    if raw[:2] == b'\x1f\x8b':
        try:
            return _gzip.decompress(raw)
        except Exception:
            return raw
    return raw


def q_enc(v):
    return urllib.parse.quote(str(v), safe='.-*_').replace('+', '%20').replace('%7E', '~')


def build_query(params):
    return '&'.join('%s=%s' % (q_enc(k), q_enc(v)) for k, v in params.items())


def trace_id():
    u = '%032x' % random.getrandbits(128)
    return '00-%s-%s-01' % (u, u[:16])


# ============================ 设备画像 =====================================
def device_params():
    return {
        'ac': 'wifi', 'aid': AID, 'app_name': APP_NAME,
        'channel': '69310258a', 'ssmix': 'a', 'device_platform': 'android',
        'os': 'android', 'language': 'zh', 'compliance_status': '0',
        'need_personal_recommend': '1', 'player_so_load': '1', 'host_abi': 'arm64-v8a',
    }


def build_params(dev, model):
    p = {}
    p['device_id'] = dev.get('device_id') or DEF_DEV['device_id']
    p['iid'] = dev.get('iid') or DEF_DEV['iid']
    p['install_id'] = dev.get('install_id') or p['iid']
    p.update(device_params())
    for k in ('version_code', 'manifest_version_code', 'update_version_code', 'pv_player'):
        p[k] = VERSION_CODE
    p['version_name'] = VERSION_NAME
    return p


# ============================== 签名 =======================================
def m998a(seed, data):
    v = seed & 0xFFFFFFFF
    for i, b in enumerate(data):
        if i & 1 == 0:
            v = (((v << 6) & 0xFFFFFFFF) ^ ((v >> 4) ^ v)) ^ b
        else:
            v = ((((v << 12) & 0xFFFFFFFF) | b) ^ ((v >> 7) ^ v)) ^ 0xFFFFFFFF
        v &= 0xFFFFFFFF
    return v


def _rc4_var(key, data):
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) & 0xFF
        s[i] = s[j]                       # APK 变体：单向赋值
    out = bytearray(len(data))
    i = k = 0
    while i < len(data):
        i1 = i + 1
        k = (k + s[i1]) & 0xFF
        v = s[k & 0xFF]
        s[i1] = v
        out[i] = data[i] ^ s[(v + v) & 0xFF]
        i = i1
    return bytes(out)


def _bitrev8(v):
    r = 0
    for i in range(8):
        r = (r << 1) | ((v >> i) & 1)
    return r


def x_gorgon(query, body=b'', now_ms=None, rnd16=None):
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    ts = (now_ms // 1000) & 0xFFFFFFFF
    bmd5 = md5(body) if body else bytes(16)
    q = query
    for off in range(128):
        q = query + ('&' if query else '') + '_rticket=%d' % (now_ms + off)
        h = m998a(m998a(539167016, sm3(q.encode())), bmd5)
        if (m998a(h, le32(ts)) & 15) % 3 == 0:
            break
    if rnd16 is None:
        rnd16 = random.getrandbits(16)
    hi, lo = (rnd16 >> 8) & 0xFF, rnd16 & 0xFF
    key = bytes([74, 64, 22, hi, 71, 108, 1, lo])
    payload = md5(q.encode())[:4] + bmd5[:4] + bytes(4) + le32(67503104) + struct.pack('>I', ts)
    c = bytearray(_rc4_var(key, payload))
    n = len(c)
    for i in range(n):
        b = c[i] & 0xFF
        a = ((b >> 4) | (b << 4)) & 0xFF
        c[i] = _bitrev8((c[(i + 1) % n] & 0xFF) ^ a) ^ 0xEB
    out = bytearray(b'\x84\x04' + bytes([rnd16 & 0xFF, hi, 64, 1]) + bytes(c))
    out[4] = 0
    out[5] = 0x81
    return out.hex(), q, (now_ms + off)


def x_helios(now_ms=None, rnd32=None):
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    ts = (now_ms // 1000) & 0xFFFFFFFF
    if rnd32 is None:
        rnd32 = random.getrandbits(32)
    hexstr = md5(le32(rnd32) + AID.encode()).hex()
    stage = [struct.unpack('<Q', hexstr[i * 8:i * 8 + 8].encode())[0] for i in range(4)]
    keys, buf = [], stage[2:]
    v0, v1 = stage[0], stage[1]
    for i in range(34):
        w = ((rotr64(v1, 8) + v0) & 0xFFFFFFFFFFFFFFFF) ^ i
        buf.append(w)
        v0 = rotr64(v0, 61) ^ w
        keys.append(v0)
        v1 = buf.pop(0)
    msg = ('%d-646637794-%s' % (ts, AID)).encode()
    pad = 16 - len(msg) % 16
    msg += bytes([pad]) * pad
    acc = le32(rnd32)
    for off in range(0, len(msg), 16):
        l = struct.unpack('<Q', msg[off:off + 8])[0]
        r = struct.unpack('<Q', msg[off + 8:off + 16])[0]
        for i in range(34):
            r = (keys[i] ^ ((rotr64(r, 8) + l) & 0xFFFFFFFFFFFFFFFF)) & 0xFFFFFFFFFFFFFFFF
            l = rotr64(l, 61) ^ r
        acc += le64(l) + le64(r)
    return base64.b64encode(acc).decode()


def sign_headers(params, body, model):
    now = int(time.time() * 1000)
    ts = now // 1000
    rnd16 = random.getrandbits(16)
    g, q, tick = x_gorgon(build_query(params) + '&ts=%d' % ts, body, now, rnd16)
    return {
        'User-Agent': UA_APP % model,
        'Accept': 'application/json; charset=utf-8,application/x-protobuf',
        'x-ss-req-ticket': str(tick),
        'x-tt-request-tag': 't=0;n=0',
        'sdk-version': '2',
        'passport-sdk-version': '6031190',
        'x-xs-from-web': '0',
        'x-khronos': str(ts),
        'x-ladon': base64.b64encode(bytes(random.getrandbits(8) for _ in range(4))).decode(),
        'x-argus': base64.b64encode(le32(ts)).decode(),
        'x-gorgon': g,
        'x-helios': x_helios(now, random.getrandbits(32)),
        'x-medusa': g,
        'x-ss-dp': AID,
        'x-vc-bdturing-sdk-version': '4.0.3.cn',
        'x-neptune': '-11|50:51:59',
        'lc': '101',
        'Content-Encoding': 'gzip',
        'Content-Type': 'application/json; charset=UTF-8',
    }, q


# ========================== tt-data 加密 / 注册 ============================
def tt_data_encrypt(plain):
    gz = gzipb(plain)
    rnd = bytes(random.getrandbits(8) for _ in range(32))
    km = sha512(sha512(rnd) + SALT)
    body = sha512(gz) + gz
    pad = 16 - len(body) % 16
    body += bytes([pad]) * pad
    return MAGIC + rnd + aes_cbc_encrypt(km[:16], km[16:32], body)


def seed_decrypt(seed_b64, blob_b64):
    """key_seed 解链（AbstractC0527s1.m1423b）"""
    blob = b64d(blob_b64)
    if len(blob) < 20 or blob[0] != 0xA8 or blob[2] != 1 or blob[3] != 0:
        raise ValueError('seed blob 头非法')
    km = sha512(sha512(b64d(seed_b64)) + SALT)
    n = ((len(blob) - 4) // 16) * 16
    pt = aes_cbc_decrypt(km[:16], km[16:32], blob[4:4 + n])
    if pt:
        pad = pt[-1]
        if 1 <= pad < 17:
            pt = pt[:-pad]
    return pt.rstrip(b'\x00').decode('utf-8', 'ignore')


# ============================== 网络层 =====================================
def _http(method, url, headers=None, body=None, timeout=25):
    h = dict(headers or {})
    if _HAS_REQ:
        r = requests.request(method, url, headers=h, data=body, timeout=timeout)
        r.encoding = 'utf-8'
        return r.status_code, r.content
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.getcode(), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _get_text(url, headers=None):
    h = {'User-Agent': UA_WEB, 'Accept': 'text/html,application/json,*/*',
         'Accept-Language': 'zh-CN,zh;q=0.9', 'Accept-Encoding': 'gzip'}
    if headers:
        h.update(headers)
    code, raw = _http('GET', url, h)
    return ungzip(raw).decode('utf-8', 'ignore')


# =========================== 官网 SSR 解析 =================================
def _router(html):
    m = re.search(r'_ROUTER_DATA\s*=\s*', html)
    if not m:
        return None
    try:
        return json.JSONDecoder().raw_decode(html[m.end():])[0]
    except Exception:
        return None


def _pic(u):
    return str(u or '').replace('\\/', '/').replace('\\u002F', '/')


def _item_cat(it):
    return {
        'vod_id': str(it.get('series_id') or ''),
        'vod_name': str(it.get('series_name') or it.get('series_title') or ''),
        'vod_pic': _pic(it.get('series_cover')),
        'vod_remarks': str(it.get('episode_right_text') or
                            ('全%s集' % it['episode_cnt'] if it.get('episode_cnt') else '')),
        'vod_content': str(it.get('series_intro') or ''),
    }


def _item_home(it):
    return {
        'vod_id': str(it.get('series_id') or it.get('seriesId') or it.get('id') or ''),
        'vod_name': str(it.get('series_title') or it.get('title') or ''),
        'vod_pic': _pic(it.get('series_cover') or it.get('cover')),
        'vod_remarks': str(it.get('episode_right_text') or
                            ('全%s集' % it['episode_cnt'] if it.get('episode_cnt') else '')),
        'vod_content': str(it.get('series_intro') or ''),
    }


def _item_search(it):
    vd = it.get('video_data') if isinstance(it.get('video_data'), dict) else it
    if not vd:
        vd = it
    return {
        'vod_id': str(vd.get('series_id') or it.get('keyword') or ''),
        'vod_name': str(vd.get('series_title') or it.get('name') or ''),
        'vod_pic': _pic(vd.get('series_cover')),
        'vod_remarks': str(vd.get('episode_right_text') or
                            ('全%s集' % vd['episode_cnt'] if vd.get('episode_cnt') else '')),
        'vod_content': str(vd.get('series_intro') or ''),
    }


def _playable_codec(mp4):
    """只有视频轨用 bvc2 私有编码时才不可播；bv2C 是其专属配置 box"""
    return b'bv2C' not in mp4


def _pick_spade(item):
    """spade_a 可能在 item 顶层，也可能在 encrypt_info 里"""
    if not isinstance(item, dict):
        return None
    if isinstance(item.get('spade_a'), str) and item['spade_a']:
        return item['spade_a']
    ei = item.get('encrypt_info')
    if isinstance(ei, str):
        try:
            ei = json.loads(ei)
        except Exception:
            ei = None
    if isinstance(ei, dict) and isinstance(ei.get('spade_a'), str) and ei['spade_a']:
        return ei['spade_a']
    return None


def _dedup(items):
    out, seen = [], set()
    for v in items:
        if v['vod_id'] and v['vod_id'] not in seen:
            seen.add(v['vod_id'])
            out.append(v)
    return out


# ============================== 番茄 API ===================================
class TgApi(object):
    def __init__(self, dev=None):
        self.dev = dict(dev or {})
        self.model = random.choice(MODELS)
        self.host_i = 0

    def video_model(self, vid, quality_slot=None):
        """返回 video_model 字典（含 video_list / fallback_api）"""
        biz = {
            'detail_page_version': 0,
            'device_level': 3,
            'disable_digg_stat': False,
            'disable_video_relate_book': False,
            'need_all_video_definition': True,
            'need_mp4_align': False,
            'use_os_player': False,
            'use_server_dns': True,
            'use_server_dns_scene': 'cold_start_stage',
            'video_platform': 1024,
        }
        obj = {
            'biz_param': biz,
            'dr_scene': 'player',
            'mixed_video_id_map': {'1004': [str(vid)]},
        }
        body = gzipb(json.dumps(obj, separators=(',', ':')))
        last = None
        for i in range(len(API_HOSTS)):
            host = API_HOSTS[(self.host_i + i) % len(API_HOSTS)]
            params = build_params(self.dev, self.model)
            h, q = sign_headers(params, body, self.model)
            h['x-ss-stub'] = md5(body).hex().upper()
            try:
                code, raw = _http('POST', 'https://%s/novel/player/multi_video_model/v1/?%s'
                                  % (host, q), h, body, 25)
                if not raw:
                    last = 'empty'
                    continue
                d = json.loads(raw.decode('utf-8', 'ignore'))
                data = d.get('data') or {}
                item = data.get(str(vid)) or {}
                vm = item.get('video_model')
                if isinstance(vm, str):
                    vm = json.loads(vm)
                if vm and vm.get('video_list'):
                    self.host_i = (self.host_i + i) % len(API_HOSTS)
                    return vm
                last = d.get('BaseResp', {}).get('StatusMessage') or 'no-model'
            except Exception as e:
                last = '%s' % type(e).__name__
        raise IOError('播放模型获取失败: %s' % last)

    def play_urls(self, vm, with_key=False):
        """把 video_model 变成 {清晰度: 明文直链}；with_key=True 时附带各档 spade_a"""
        fa = vm.get('fallback_api')
        if isinstance(fa, dict):
            fa = fa.get('fallback_api') or fa.get('url')
        out = {}
        keys = {}
        # 1) 优先走 fallback_api（返回带 key_seed 的加密链）
        if isinstance(fa, str) and fa.startswith('http'):
            try:
                txt = _get_text(fa, {'User-Agent': UA_APP % self.model})
                d = json.loads(txt)
                data = (d.get('video_info') or {}).get('data') or {}
                seed = data.get('key_seed')
                vl = data.get('video_list') or {}
                if seed and isinstance(vl, dict):
                    for _k, v in vl.items():
                        mu = v.get('main_url')
                        if not mu:
                            continue
                        try:
                            url = seed_decrypt(seed, mu)
                        except Exception:
                            url = mu
                        if url.startswith('http'):
                            df = str(v.get('definition') or 'auto')
                            out[df] = url
                            sa = _pick_spade(v)
                            if sa:
                                keys[df] = sa
            except Exception:
                pass
        # 2) 兜底：模型里直接暴露的 main_url
        if not out:
            for v in (vm.get('video_list') or []):
                mu = v.get('main_url')
                if isinstance(mu, str) and mu.startswith('http'):
                    meta = v.get('video_meta') or {}
                    if isinstance(meta, str):
                        try:
                            meta = json.loads(meta)
                        except Exception:
                            meta = {}
                    df = str(meta.get('definition') or 'auto')
                    out[df] = mu
                    sa = _pick_spade(v)
                    if sa:
                        keys[df] = sa
        if with_key:
            return out, keys
        return out


# ======================================================================
#  今日头条「精选」—— a_bogus 签名 + PC 推荐流（支持滚动翻页）
# ======================================================================
class _ABogus(object):
    """头条 a_bogus 签名（纯 Python，SM3 + RC4 + 自定义 base64）"""
    __end_string = "cus"
    __str = {
        "s0": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=",
        "s1": "Dkdpgh4ZKsQB80/Mfvw36XI1R25+WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe=",
        "s2": "Dkdpgh4ZKsQB80/Mfvw36XI1R25-WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe=",
        "s3": "ckdp1h4ZKsUB80/Mfvw36XIgR25+WQAlEi7NLboqYTOPuzmFjJnryx9HVGDaStCe",
        "s4": "Dkdpgh2ZmsQB80/MfvV36XI1R45-WUAlEixNLwoqYTOPuzKFjJnry79HbGcaStCe",
    }

    def __init__(self, user_agent, platform='Win32'):
        self.user_agent = user_agent
        self.ua_code = self._ua_code(user_agent)
        self.browser = self._browser_info(platform)
        self.browser_len = len(self.browser)
        self.browser_code = [ord(c) for c in self.browser]

    @staticmethod
    def _sm3_arr(data):
        b = data.encode('utf-8') if isinstance(data, str) else bytes(bytearray(data))
        return list(sm3(b))

    def _ua_code(self, ua):
        key = ''.join(chr(int(n)) for n in [0.00390625, 1, 14])
        return self._sm3_arr(self._result(self._rc4(ua, key), 's3'))

    @staticmethod
    def _rand_list(b=170, c=85, d=0, e=0, f=0, g=0):
        r = random.random() * 10000
        v = [r, int(r) & 255, int(r) >> 8]
        return [v[1] & b | d, v[1] & c | e, v[2] & b | f, v[2] & c | g]

    def _str1(self):
        a = self._rand_list(170, 85, 1, 2, 5, 45 & 170)
        b = self._rand_list(170, 85, 1, 0, 0, 0)
        c = self._rand_list(170, 85, 1, 0, 5, 0)
        return ''.join(chr(x) for x in a + b + c)

    @staticmethod
    def _browser_info(platform):
        iw = random.randint(1280, 1920)
        ih = random.randint(720, 1080)
        ow = random.randint(iw, 1920)
        oh = random.randint(ih, 1080)
        vals = [iw, ih, ow, oh, 0, random.choice((0, 30)), 0, 0,
                ow, oh, ow, oh, iw, ih, 24, 24, platform]
        return '|'.join(str(x) for x in vals)

    @staticmethod
    def _rc4(plain, key):
        s = list(range(256))
        j = 0
        for i in range(256):
            j = (j + s[i] + ord(key[i % len(key)])) % 256
            s[i], s[j] = s[j], s[i]
        i = j = 0
        out = []
        for k in range(len(plain)):
            i = (i + 1) % 256
            j = (j + s[i]) % 256
            s[i], s[j] = s[j], s[i]
            out.append(chr(s[(s[i] + s[j]) % 256] ^ ord(plain[k])))
        return ''.join(out)

    def _result(self, s, e='s4'):
        table = self.__str[e]
        r = []
        for i in range(0, len(s), 3):
            if i + 2 < len(s):
                n = (ord(s[i]) << 16) | (ord(s[i + 1]) << 8) | ord(s[i + 2])
            elif i + 1 < len(s):
                n = (ord(s[i]) << 16) | (ord(s[i + 1]) << 8)
            else:
                n = ord(s[i]) << 16
            for j, k in zip(range(18, -1, -6), (0xFC0000, 0x03F000, 0x0FC0, 0x3F)):
                if j == 6 and i + 1 >= len(s):
                    break
                if j == 0 and i + 2 >= len(s):
                    break
                r.append(table[(n & k) >> j])
        r.append('=' * ((4 - len(r) % 4) % 4))
        return ''.join(r)

    def _method_code(self, method='GET'):
        return self._sm3_arr(self._sm3_arr(method + self.__end_string))

    def _params_code(self, params):
        return self._sm3_arr(self._sm3_arr(params + self.__end_string))

    @staticmethod
    def _list4(a, b, c, d, e, f, g, h, i, j, k, m, n, o, p, q, r):
        return [44, a, 0, 0, 0, 0, 24, b, n, 0, c, d, 0, 0, 0, 1, 0, 239,
                e, o, f, g, 0, 0, 0, 0, h, 0, 0, 14, i, j, 0, k, m, 3, p, 1, q, 1, r, 0, 0, 0]

    def _str2_list(self, url_params, method='GET'):
        st = int(time.time() * 1000)
        et = st + random.randint(4, 8)
        pa = self._params_code(url_params)
        ma = self._method_code(method)
        return self._list4(
            (et >> 24) & 255, pa[21], self.ua_code[23],
            (et >> 16) & 255, pa[22], self.ua_code[24],
            (et >> 8) & 255, et & 255,
            (st >> 24) & 255, (st >> 16) & 255, (st >> 8) & 255, st & 255,
            ma[21], ma[22],
            int(et / 256 / 256 / 256 / 256),
            int(st / 256 / 256 / 256 / 256),
            self.browser_len,
        )

    def _str2(self, url_params, method='GET'):
        arr = self._str2_list(url_params, method)
        chk = 0
        for x in arr:
            chk ^= x
        arr.extend(self.browser_code)
        arr.append(chk)
        return self._rc4(''.join(chr(x) for x in arr), 'y')

    def generate(self, params):
        s = self._str1() + self._str2(urllib.parse.urlencode(params))
        return self._result(s, 's4')


class ToutiaoFeed(object):
    """今日头条 PC 推荐流（精选，支持分页滚动）"""
    UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
          '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
    FEED_API = 'https://www.toutiao.com/api/pc/list/feed'
    CHANNEL_ID = '94349560412'

    def __init__(self):
        self._ab = _ABogus(self.UA, 'Win32')
        self._items = {}
        self._seen_ids = set()
        self._last_cursor = 0

    @staticmethod
    def _mstoken():
        pool = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
        return ''.join(random.choice(pool) for _ in range(107)) + '=='

    def _headers(self):
        return {
            'User-Agent': self.UA,
            'Referer': 'https://www.toutiao.com/',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }

    def _fetch(self, offset, cursor=0):
        params = {
            'min_behot_time': str(cursor),
            'offset': str(offset),
            'channel_id': self.CHANNEL_ID,
            'category': 'pc_profile_channel',
            'disable_raw_data': 'true',
            'client_extra_params': '{"playparam":"codec_type:0,enable_dash:1,unwatermark:1"}',
            'aid': '24',
            'app_name': 'toutiao_web',
            'msToken': self._mstoken(),
        }
        try:
            sign = self._ab.generate(params)
            query = urllib.parse.urlencode(params) + '&a_bogus=' + \
                urllib.parse.urlencode({'a_bogus': sign})[8:]
            code, raw = _http('GET', self.FEED_API + '?' + query, self._headers(), None, 12)
            if not raw:
                return []
            data = json.loads(raw.decode('utf-8', 'ignore'))
        except Exception:
            return []
        items = data.get('data') or []
        now = int(time.time())
        for it in items:
            iid = str(it.get('item_id') or '')
            if iid:
                self._items[iid] = {'item': it, 'ts': now}
        return items

    def _sample(self, start=0, pages=8, step=10, cursor=0):
        try:
            from concurrent.futures import ThreadPoolExecutor
            offs = [start + i * step for i in range(pages)]
            out, seen = [], set()
            with ThreadPoolExecutor(max_workers=6) as pool:
                for items in pool.map(lambda o: self._fetch(o, cursor), offs):
                    for it in items:
                        iid = str(it.get('item_id') or '')
                        if iid and iid not in seen:
                            seen.add(iid)
                            out.append(it)
            return out
        except Exception:
            out, seen = [], set()
            for i in range(pages):
                for it in self._fetch(start + i * step, cursor):
                    iid = str(it.get('item_id') or '')
                    if iid and iid not in seen:
                        seen.add(iid)
                        out.append(it)
            return out

    @staticmethod
    def _first_url(obj):
        if not obj:
            return ''
        if isinstance(obj, str):
            return obj
        for u in (obj.get('url_list') or []):
            if isinstance(u, dict):
                u = u.get('url') or ''
            if u:
                return u
        return ''

    def _play(self, it):
        v = it.get('video') or {}
        url = self._first_url(v.get('play_addr')) or self._first_url(v.get('download_addr'))
        return url, int(v.get('url_expire') or 0), int(v.get('duration') or 0)

    def _cover(self, it):
        v = it.get('video') or {}
        u = self._first_url(v.get('origin_cover')) or self._first_url(v.get('dynamic_cover'))
        if u:
            return u
        for key in ('large_image_list', 'thumb_image_list', 'first_frame_image_list'):
            lst = it.get(key) or []
            if lst:
                u = self._first_url(lst[0])
                if u:
                    return u
        return self._first_url(it.get('image_url'))

    @staticmethod
    def _clean_title(t):
        if not t:
            return ''
        raw = t
        x = re.sub(r'#[^#\s]{1,40}#?', ' ', t)
        x = re.sub(r'\s+', ' ', x).strip(' -|')
        x = re.sub(r'[\s，,]*了?短剧[\s，,]*$', '', x).strip()
        if not x:
            x = re.sub(r'[#\s]+', ' ', raw).strip()[:40]
        return x or '头条视频'

    def list_vods(self, page=1):
        """按页动态拉取推荐流，支持前端无限滚动下一页"""
        if page <= 1:
            self._seen_ids.clear()
            self._last_cursor = 0

        # 每页前进 80 个 offset 步长，同时结合历史时间游标保证拉取新内容
        start_offset = (page - 1) * 80
        items = self._sample(start=start_offset, pages=8, step=10, cursor=self._last_cursor)

        vods = []
        n = (page - 1) * 30
        min_behot = self._last_cursor

        for it in items:
            behot = int(it.get('behot_time') or 0)
            if behot > 0 and (min_behot == 0 or behot < min_behot):
                min_behot = behot

            url, expire, dur = self._play(it)
            if not url:
                continue
            if dur and dur < 30:      # 30 秒以下的资讯短视频跳过
                continue
            iid = str(it.get('item_id') or '')
            if not iid or iid in self._seen_ids:
                continue
            self._seen_ids.add(iid)
            n += 1
            title = self._clean_title(it.get('title') or '')
            remark = ('%d分钟' % (dur // 60)) if dur >= 60 else ('%d秒' % dur if dur else '')
            vods.append({
                'vod_id': 'tt_' + iid,
                'vod_name': title if len(title) >= 4 else ('头条视频 %02d' % n),
                'vod_pic': self._cover(it),
                'vod_remarks': remark,
                'vod_content': it.get('abstract') or title,
                '_dur': dur,
            })

        if min_behot > 0:
            self._last_cursor = min_behot

        vods.sort(key=lambda v: -int(v.get('_dur') or 0))
        return vods

    def find(self, item_id):
        rec = self._items.get(item_id)
        if rec:
            return rec['item']
        self._sample(0, 12, 10, 0)
        rec = self._items.get(item_id)
        return rec['item'] if rec else None


# ========================= CENC 解密核心 =============================
def _boxes(buf, start, end):
    off = start
    while off + 8 <= end:
        size = struct.unpack('>I', buf[off:off + 4])[0]
        typ = buf[off + 4:off + 8]
        hdr = 8
        if size == 1:
            size = struct.unpack('>Q', buf[off + 8:off + 16])[0]
            hdr = 16
        elif size == 0:
            size = end - off
        if size < hdr or off + size > end:
            return
        yield typ, off, size, hdr
        off += size


def _child(buf, start, end, name):
    for typ, off, size, hdr in _boxes(buf, start, end):
        if typ == name:
            return off, size, hdr
    return None


def _track_stbl(buf, moov_off, moov_size, want_video=True):
    """返回 (stbl 区间, 是否 encv/enca)"""
    for typ, off, size, hdr in _boxes(buf, moov_off + moov_hdr(buf, moov_off), moov_off + moov_size):
        if typ != b'trak':
            continue
        mdia = _child(buf, off + hdr, off + size, b'mdia')
        if not mdia:
            continue
        minf = _child(buf, mdia[0] + mdia[2], mdia[0] + mdia[1], b'minf')
        if not minf:
            continue
        stbl = _child(buf, minf[0] + minf[2], minf[0] + minf[1], b'stbl')
        if not stbl:
            continue
        stsd = _child(buf, stbl[0] + stbl[2], stbl[0] + stbl[1], b'stsd')
        enc = False
        if stsd:
            for t2, o2, s2, h2 in _boxes(buf, stsd[0] + stsd[2] + 8, stsd[0] + stsd[1]):
                if t2 in (b'encv', b'enca'):
                    enc = True
        is_video = b'vmhd' in buf[minf[0]:minf[0] + minf[1]]
        if is_video == want_video:
            return (stbl[0], stbl[1], stbl[2]), enc
    return None, False


def moov_hdr(buf, off):
    size = struct.unpack('>I', buf[off:off + 4])[0]
    return 16 if size == 1 else 8


def _parse_track(buf, stbl):
    s_off, s_size, s_hdr = stbl
    lo, hi = s_off + s_hdr, s_off + s_size
    stsz = _child(buf, lo, hi, b'stsz')
    stco = _child(buf, lo, hi, b'stco')
    stsc = _child(buf, lo, hi, b'stsc')
    senc = _child(buf, lo, hi, b'senc')
    if not (stsz and stco):
        return None
    # stsz
    p = stsz[0] + stsz[2]
    fixed = struct.unpack('>I', buf[p + 4:p + 8])[0]
    count = struct.unpack('>I', buf[p + 8:p + 12])[0]
    if fixed == 0:
        sizes = list(struct.unpack('>%dI' % count, buf[p + 12:p + 12 + 4 * count]))
    else:
        sizes = [fixed] * count
    # stco
    p = stco[0] + stco[2]
    nch = struct.unpack('>I', buf[p + 4:p + 8])[0]
    chunks = list(struct.unpack('>%dI' % nch, buf[p + 8:p + 8 + 4 * nch]))
    # stsc
    p = stsc[0] + stsc[2]
    n = struct.unpack('>I', buf[p + 4:p + 8])[0]
    entries = [struct.unpack('>III', buf[p + 8 + i * 12:p + 20 + i * 12]) for i in range(n)]
    # senc
    ivs = []
    if senc:
        p = senc[0] + senc[2]
        flags = int.from_bytes(buf[p + 1:p + 4], 'big')
        cnt = struct.unpack('>I', buf[p + 4:p + 8])[0]
        pos = p + 8
        has_sub = bool(flags & 2)
        for _ in range(cnt):
            ivs.append(buf[pos:pos + 8])
            pos += 8
            if has_sub:
                sc = struct.unpack('>H', buf[pos:pos + 2])[0]
                pos += 2 + sc * 6
    # sample -> chunk 偏移
    offs = []
    si = 0
    for ci, chunk_off in enumerate(chunks):
        per = None
        for k in range(len(entries)):
            first = entries[k][0]
            nxt = entries[k + 1][0] if k + 1 < len(entries) else 10 ** 9
            if first - 1 <= ci < nxt - 1:
                per = entries[k][1]
                break
        if per is None:
            per = entries[-1][1] if entries else 0
        o = chunk_off
        for _ in range(per):
            if si >= len(sizes):
                break
            offs.append(o)
            o += sizes[si]
            si += 1
        if si >= len(sizes):
            break
    return {'sizes': sizes, 'offsets': offs, 'ivs': ivs}


# ---------------- 纯 Python AES 加速（T-table） ----------------
def _build_tables():
    sb = _SBOX
    te0 = [0] * 256
    for x in range(256):
        s0 = sb[x]
        s2 = ((s0 << 1) ^ 0x1B) & 0xFF if s0 & 0x80 else (s0 << 1) & 0xFF
        s3 = s2 ^ s0
        te0[x] = (s2 << 24) | (s0 << 16) | (s0 << 8) | s3
    return te0


_TE0 = None


def _enc_block_fast(block, rk):
    """16 字节块加密，rk 为扁平轮密钥列表（每轮 4 个 32 位字）"""
    global _TE0
    if _TE0 is None:
        _TE0 = _build_tables()
    te = _TE0
    s0 = int.from_bytes(block[0:4], 'big') ^ rk[0]
    s1 = int.from_bytes(block[4:8], 'big') ^ rk[1]
    s2 = int.from_bytes(block[8:12], 'big') ^ rk[2]
    s3 = int.from_bytes(block[12:16], 'big') ^ rk[3]
    n = len(rk)
    for r in range(4, n - 4, 4):
        t0 = te[(s0 >> 24) & 255] ^ (((te[(s1 >> 16) & 255]) >> 8) | ((te[(s1 >> 16) & 255]) << 24) & 0xFFFFFFFF)
        t0 ^= (((te[(s2 >> 8) & 255]) >> 16) | ((te[(s2 >> 8) & 255]) << 16) & 0xFFFFFFFF)
        t0 ^= (((te[s3 & 255]) >> 24) | ((te[s3 & 255]) << 8) & 0xFFFFFFFF) ^ rk[r]
        t1 = te[(s1 >> 24) & 255] ^ (((te[(s2 >> 16) & 255]) >> 8) | ((te[(s2 >> 16) & 255]) << 24) & 0xFFFFFFFF)
        t1 ^= (((te[(s3 >> 8) & 255]) >> 16) | ((te[(s3 >> 8) & 255]) << 16) & 0xFFFFFFFF)
        t1 ^= (((te[s0 & 255]) >> 24) | ((te[s0 & 255]) << 8) & 0xFFFFFFFF) ^ rk[r + 1]
        t2 = te[(s2 >> 24) & 255] ^ (((te[(s3 >> 16) & 255]) >> 8) | ((te[(s3 >> 16) & 255]) << 24) & 0xFFFFFFFF)
        t2 ^= (((te[(s0 >> 8) & 255]) >> 16) | ((te[(s0 >> 8) & 255]) << 16) & 0xFFFFFFFF)
        t2 ^= (((te[s1 & 255]) >> 24) | ((te[s1 & 255]) << 8) & 0xFFFFFFFF) ^ rk[r + 2]
        t3 = te[(s3 >> 24) & 255] ^ (((te[(s0 >> 16) & 255]) >> 8) | ((te[(s0 >> 16) & 255]) << 24) & 0xFFFFFFFF)
        t3 ^= (((te[(s1 >> 8) & 255]) >> 16) | ((te[(s1 >> 8) & 255]) << 16) & 0xFFFFFFFF)
        t3 ^= (((te[s2 & 255]) >> 24) | ((te[s2 & 255]) << 8) & 0xFFFFFFFF) ^ rk[r + 3]
        s0, s1, s2, s3 = t0 & 0xFFFFFFFF, t1 & 0xFFFFFFFF, t2 & 0xFFFFFFFF, t3 & 0xFFFFFFFF
    sb = _SBOX
    out = bytearray(16)
    for i, (a, b, c, d, k) in enumerate((
            (s0, s1, s2, s3, rk[-4]), (s1, s2, s3, s0, rk[-3]),
            (s2, s3, s0, s1, rk[-2]), (s3, s0, s1, s2, rk[-1]))):
        v = (sb[(a >> 24) & 255] << 24) | (sb[(b >> 16) & 255] << 16) | \
            (sb[(c >> 8) & 255] << 8) | sb[d & 255]
        v ^= k
        out[4 * i:4 * i + 4] = (v & 0xFFFFFFFF).to_bytes(4, 'big')
    return bytes(out)


def _flat_round_keys(key):
    w, nr = _expand_key(key)
    flat = []
    for r in range(nr + 1):
        for c in range(4):
            flat.append((w[r * 4 + c][0] << 24) | (w[r * 4 + c][1] << 16) |
                        (w[r * 4 + c][2] << 8) | w[r * 4 + c][3])
    return flat


def _detect_aes():
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher  # noqa
        return 'cryptography'
    except Exception:
        pass
    try:
        from Crypto.Cipher import AES  # noqa
        return 'pycryptodome'
    except Exception:
        pass
    return 'python'


_AES_BACKEND = None


def _aes_ctr(key, iv, data):
    global _AES_BACKEND
    if _AES_BACKEND in (None, 'cryptography'):
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            c = Cipher(algorithms.AES(key), modes.CTR(iv + b'\x00' * 8)).encryptor()
            _AES_BACKEND = 'cryptography'
            return c.update(data) + c.finalize()
        except Exception:
            pass
    if _AES_BACKEND in (None, 'pycryptodome'):
        try:
            from Crypto.Cipher import AES
            from Crypto.Util import Counter
            ctr = Counter.new(64, prefix=iv, initial_value=0)
            _AES_BACKEND = 'pycryptodome'
            return AES.new(key, AES.MODE_CTR, counter=ctr).decrypt(data)
        except Exception:
            pass
    # 纯 Python 兜底（T-table 加速）
    _AES_BACKEND = 'python'
    rk = _flat_round_keys(key)
    n = len(data)
    out = bytearray(n)
    nblk = (n + 15) // 16
    for i in range(nblk):
        off = i * 16
        ks = _enc_block_fast(iv + i.to_bytes(8, 'big'), rk)
        chunk = data[off:off + 16]
        out[off:off + len(chunk)] = bytes(x ^ y for x, y in zip(chunk, ks))
    return bytes(out)


def decrypt_mp4(buf, key_v, key_a=None):
    """返回解密后的 mp4 字节；encv/enca 改名为 hvc1/mp4a"""
    out = bytearray(buf)
    moov = None
    for typ, off, size, hdr in _boxes(buf, 0, len(buf)):
        if typ == b'moov':
            moov = (off, size, hdr)
            break
    if not moov:
        raise ValueError('找不到 moov')
    stat = {}
    for is_video in (True, False):
        stbl, enc = _track_stbl(buf, moov[0], moov[1], is_video)
        if not stbl or not enc:
            continue
        info = _parse_track(buf, stbl)
        if not info:
            continue
        key = key_v if is_video else (key_a or key_v)
        n = min(len(info['sizes']), len(info['offsets']), len(info['ivs']))
        for i in range(n):
            o = info['offsets'][i]
            ln = info['sizes'][i]
            if o + ln > len(buf):
                break
            out[o:o + ln] = _aes_ctr(key, info['ivs'][i], bytes(buf[o:o + ln]))
        stat['video' if is_video else 'audio'] = n
    # 用 sinf/frma 里的原始格式回填 encv/enca（可能是 avc1 也可能是 hvc1）
    mv = bytearray(out[moov[0]:moov[0] + moov[1]])
    for enc_tag in (b'encv', b'enca'):
        pos = 0
        while True:
            i = mv.find(enc_tag, pos)
            if i < 0:
                break
            size = struct.unpack('>I', bytes(mv[i - 4:i]))[0]
            seg_end = min(len(mv), i - 4 + size)
            j = mv.find(b'frma', i, seg_end)
            if j > 0 and j + 8 <= len(mv):
                orig = bytes(mv[j + 4:j + 8])
                if orig.isalnum():
                    mv[i:i + 4] = orig
                    stat.setdefault('renamed', []).append((enc_tag.decode(), orig.decode()))
            pos = i + 4
    out[moov[0]:moov[0] + moov[1]] = mv
    return bytes(out), stat


# ======================= 本地 HTTP 内存解密代理服务 ========================
class _ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class _StreamHandler(BaseHTTPRequestHandler):
    spider_ref = None

    def log_message(self, format, *args):
        # 屏蔽控制台高频请求日志
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != '/play':
            self.send_error(404, 'Not Found')
            return

        qs = urllib.parse.parse_qs(parsed.query)
        vid = (qs.get('vid') or [''])[0]
        qname = (qs.get('q') or ['720p'])[0]

        if not vid or not self.spider_ref:
            self.send_error(400, 'Missing vid')
            return

        try:
            plain = self.spider_ref._fetch_and_decrypt_mem(vid, qname)
            total_len = len(plain)

            # 解析 Range 头以支持进度条拖动与标准 MP4 流式播放
            range_hdr = self.headers.get('Range')
            if range_hdr and range_hdr.startswith('bytes='):
                m = re.match(r'bytes=(\d+)-(\d*)', range_hdr)
                if m:
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else total_len - 1
                    end = min(end, total_len - 1)
                    if start > end or start >= total_len:
                        self.send_response(416)
                        self.send_header('Content-Range', 'bytes */%d' % total_len)
                        self.end_headers()
                        return
                    chunk = plain[start:end + 1]
                    self.send_response(206)
                    self.send_header('Content-Type', 'video/mp4')
                    self.send_header('Content-Length', str(len(chunk)))
                    self.send_header('Content-Range', 'bytes %d-%d/%d' % (start, end, total_len))
                    self.send_header('Accept-Ranges', 'bytes')
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    self.wfile.write(chunk)
                    return

            self.send_response(200)
            self.send_header('Content-Type', 'video/mp4')
            self.send_header('Content-Length', str(total_len))
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(plain)
        except Exception as e:
            if self.spider_ref:
                self.spider_ref.last_err = 'proxy_err: %s: %s' % (type(e).__name__, str(e)[:60])
            try:
                self.send_error(502, str(e))
            except Exception:
                pass


# ============================== TVBox 接口 =================================
class Spider(object):

    def __init__(self):
        self.api = TgApi()
        self.extend = ''
        self.last_err = ''
        self.tt = ToutiaoFeed()
        self._proxy_port = 0
        self._server = None
        self._mem_lock = threading.Lock()
        # 仅保留当前正在播放的一条视频在内存中，防止同一集多次 Range 请求重复拉取解密，切换即覆盖
        self._current_stream = {'key': None, 'data': None}

    def _start_proxy_server(self):
        """启动本地后台 HTTP 内存流代理服务"""
        if self._proxy_port > 0:
            return self._proxy_port

        handler = type('BoundStreamHandler', (_StreamHandler,), {'spider_ref': self})
        server = _ThreadedHTTPServer(('127.0.0.1', 0), handler)
        self._proxy_port = server.server_address[1]
        self._server = server

        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        return self._proxy_port

    def init(self, extend=''):
        self.extend = extend or ''
        try:
            if extend and extend.strip().startswith('{'):
                cfg = json.loads(extend)
                for k in ('device_id', 'iid', 'install_id'):
                    if cfg.get(k):
                        self.api.dev[k] = str(cfg[k])
        except Exception:
            pass
        self._start_proxy_server()
        return None

    # ---------- 首页 ----------
    def homeContent(self, filter):
        res = {'class': [{'type_id': k, 'type_name': n} for k, n in CATS]}
        if filter:
            topics = []
            try:
                d = _router(_get_text(WEB + '/category/real-drama')) or {}
                sel = (((d.get('loaderData') or {}).get('category_$') or {}).get('selectorList')) or []
                topics.append({'key': 'topic', 'name': '全部', 'value': ''})
                for row in sel:
                    for it in (row.get('items') or []):
                        ids = it.get('category_json_ids') or []
                        if it.get('show_name') and ids:
                            topics.append({'key': 'topic', 'name': str(it['show_name']),
                                           'value': str(ids[0])})
            except Exception:
                topics = [{'key': 'topic', 'name': '全部', 'value': ''}]
            res['filters'] = {k: topics for k, _n in CATS if k.startswith('c:')}
        try:
            res['list'] = self._home()
        except Exception:
            res['list'] = []
        return res

    def _home(self):
        d = _router(_get_text(WEB + '/')) or {}
        secs = (((d.get('loaderData') or {}).get('page') or {}).get('homeSections')) or []
        out = []
        for s in secs:
            for it in (s.get('video_list') or []):
                v = _item_home(it)
                if v['vod_id']:
                    out.append(v)
        return _dedup(out)[:60]

    def homeVideoContent(self):
        try:
            return {'list': self._home()}
        except Exception:
            return {'list': []}

    # ---------- 分类 / 榜单 ----------
    def categoryContent(self, tid, pg, filter, extend):
        tid = str(tid or '')
        topic = ''
        if isinstance(extend, dict):
            topic = str(extend.get('topic') or '')
        try:
            page = int(pg or 1)
        except Exception:
            page = 1

        # 头条精选（滚动翻页）
        if tid in ('t:jx', 't:', '__tt__'):
            try:
                vods = self.tt.list_vods(page=page)
            except Exception as e:
                self.last_err = 'toutiao:%s' % type(e).__name__
                vods = []
            out = []
            for v in vods:
                vv = dict(v)
                vv.pop('_dur', None)
                out.append(vv)
            return {
                'list': out,
                'page': page,
                'pagecount': 999 if out else page,
                'limit': len(out) or 20,
                'total': 9999,
            }

        if tid in ('c:__diag__', '__diag__'):
            items = self._diag()
            return {'list': items, 'page': 1, 'pagecount': 1,
                    'limit': len(items), 'total': len(items)}

        items, pages = [], 1
        try:
            if tid.startswith('r:'):
                items, pages = self._rank(tid[2:], page)
            else:
                items, pages = self._cat(tid[2:] if tid.startswith('c:') else tid, page, topic)
        except Exception:
            pass
        return {'list': items, 'page': page,
                'pagecount': max(pages, page if items else 1),
                'limit': len(items), 'total': len(items) * max(pages, 1)}

    def _diag(self):
        """自检：每一步单独测，结果直接显示在列表里"""
        out = []
        t0 = time.time()
        try:
            g, _q, _t = x_gorgon('a=1', b'')
            out.append(('1 签名算法', 'OK %dms' % int((time.time() - t0) * 1000)))
        except Exception as e:
            out.append(('1 签名算法', 'FAIL %s' % type(e).__name__))

        try:
            html = _get_text(WEB + '/detail?series_id=7671966197985856536')
            out.append(('2 官网连通', 'OK %dKB' % (len(html) // 1024)))
        except Exception as e:
            out.append(('2 官网连通', 'FAIL %s' % type(e).__name__))

        vid = '7671977925326949400'
        try:
            t0 = time.time()
            vm = self.api.video_model(vid)
            n = len(vm.get('video_list') or [])
            out.append(('3 播放模型', 'OK %d档 %dms' % (n, int((time.time() - t0) * 1000))))
        except Exception as e:
            out.append(('3 播放模型', 'FAIL %s' % str(e)[:30]))
            vm = None

        if vm:
            try:
                urls = self.api.play_urls(vm)
                out.append(('4 解链', 'OK %d档' % len(urls)))
                u = list(urls.values())[0]
                if _HAS_REQ:
                    r = requests.get(u, headers={'Range': 'bytes=0-63'}, timeout=15, stream=True)
                    code, head = r.status_code, r.raw.read(8)
                else:
                    code, raw = _http('GET', u, {'Range': 'bytes=0-63'}, None, 15)
                    head = raw[:8]
                out.append(('5 直链取流', '%s ftyp=%s' % (code, head[4:8] == b'ftyp')))
            except Exception as e:
                out.append(('4 解链', 'FAIL %s' % type(e).__name__))

        try:
            from cryptography.hazmat.primitives.ciphers import Cipher  # noqa
            env_aes = 'cryptography'
        except Exception:
            try:
                from Crypto.Cipher import AES  # noqa
                env_aes = 'pycryptodome'
            except Exception:
                env_aes = 'python(慢)'
        try:
            t0 = time.time()
            tv = self.tt.list_vods(page=1)
            out.append(('6 头条精选', 'OK %d条 %dms' % (len(tv), int((time.time() - t0) * 1000))))
        except Exception as e:
            out.append(('6 头条精选', 'FAIL %s' % type(e).__name__))

        port = self._start_proxy_server()
        out.append(('本地代理端口', '127.0.0.1:%d (无磁盘缓存)' % port))
        out.append(('运行环境', 'requests=%s | AES=%s' % (_HAS_REQ, env_aes)))
        out.append(('最近播放', self.last_err or '(未播放过)'))
        out.append(('设备号', self.api.dev.get('device_id') or DEF_DEV['device_id']))
        return [{'vod_id': 'diag%d' % i, 'vod_name': '%s  %s' % (n, v),
                 'vod_pic': '', 'vod_remarks': v, 'vod_content': ''}
                for i, (n, v) in enumerate(out)]

    def _cat(self, ct, page, topic):
        url = '%s/category/%s?page=%d' % (WEB, ct, page)
        if topic:
            url += '&category_json_ids=' + topic
        d = _router(_get_text(url)) or {}
        box = ((d.get('loaderData') or {}).get('category_$')) or {}
        items = [_item_cat(it) for it in (box.get('recommendList') or [])]
        pages = int((box.get('pagination') or {}).get('totalPages') or 1)
        return _dedup(items), pages

    def _rank(self, key, page):
        d = _router(_get_text('%s/rank/%s?page=%d' % (WEB, key, page))) or {}
        box = None
        for k, v in (d.get('loaderData') or {}).items():
            if k != 'rank_layout' and isinstance(v, dict):
                box = v
                break
        rl = ((box or {}).get('content') or {}).get('rankList') or []
        items = [_item_home(it) for it in rl]
        return _dedup(items), (2 if len(items) >= 20 else 1)

    # ---------- 搜索 ----------
    def searchContent(self, key, quick, pg='1'):
        try:
            page = int(pg or 1)
        except Exception:
            page = 1
        out = []
        try:
            url = '%s/api/search/result?query=%s&page=%d' % (WEB, urllib.parse.quote(key), page)
            d = json.loads(_get_text(url, {'Accept': 'application/json'}))
            for it in (d.get('searchList') or []):
                v = _item_search(it)
                if v['vod_id']:
                    out.append(v)
        except Exception:
            pass
        return {'list': _dedup(out)}

    # ---------- 详情 ----------
    def detailContent(self, ids):
        sid = str(ids[0] if isinstance(ids, (list, tuple)) else ids)
        if sid.startswith('tt_'):
            return self._tt_detail(sid[3:])
        box = {}
        try:
            d = _router(_get_text('%s/detail?series_id=%s' % (WEB, sid))) or {}
            box = self._walk(d)
        except Exception:
            box = {}
        name = box.get('series_name') or ('红果短剧 %s' % sid)
        vids = box.get('vid_list') or []
        if vids and isinstance(vids[0], list):
            vids = vids[0]
        vids = [str(x) for x in vids if str(x).isdigit()]
        remark = box.get('episode_right_text') or ''
        cnt = box.get('episode_cnt') or len(vids)
        if not remark and cnt:
            remark = '全%s集' % cnt
        if not vids:
            vids = ['']

        froms, urls = [], []
        for qname, _slot in QUALITIES:
            eps = []
            for i, vid in enumerate(vids):
                eps.append('第%d集·%s$%s' % (i + 1, qname, vid))
            froms.append(qname)
            urls.append('#'.join(eps))

        return {'list': [{
            'vod_id': sid,
            'vod_name': name,
            'vod_pic': _pic(box.get('series_cover')),
            'vod_content': box.get('series_intro') or '',
            'vod_remarks': remark,
            'vod_play_from': '$$$'.join(froms),
            'vod_play_url': '$$$'.join(urls),
        }]}

    def _walk(self, d):
        box = {}

        def w(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k in ('series_name', 'series_cover', 'series_intro', 'episode_cnt',
                             'episode_right_text', 'vid_list') and k not in box and v not in (None, '', []):
                        box[k] = v
                    w(v)
            elif isinstance(o, list):
                for v in o:
                    w(v)
        w(d)
        return box

    # ---------- 播放与内存流式解密 ----------
    def _play_url_of(self, vid, qname):
        """返回 (直链, 该档对应的 spade_a)"""
        vm = self.api.video_model(vid)
        urls, keys = self.api.play_urls(vm, with_key=True)
        if not urls:
            raise IOError('无播放地址')
        order = [qname, '720p', '540p', '480p', '360p', '1080p']
        pick = None
        for k in order:
            if k in urls:
                pick = k
                break
        if pick is None:
            pick = list(urls.keys())[0]
        return urls[pick], keys.get(pick)

    @staticmethod
    def _spade_key(spade_a):
        """AbstractC0474h3：spade_a -> 16 字节 AES key"""
        blob = b64d(spade_a)
        if len(blob) < 5:
            raise ValueError('spade_a 长度非法')
        i_min = min((len(blob) - ((blob[0] ^ blob[1]) ^ blob[2])) + 47, len(blob) - 1)
        if i_min < 33:
            raise ValueError('spade_a 长度不足')
        k = bytearray(blob[1:i_min + 1])
        odd, even = 85, 246
        for i in range(len(k)):
            v = k[i] & 0xFF
            src = odd if (i & 1) else even
            if i & 1:
                odd = v
            else:
                even = v
            k[i] = ((-21) - bin(i).count('1') + (src ^ v)) & 0xFF
        return bytes.fromhex(bytes(k[1:33]).decode('utf-8', 'ignore'))

    def _fetch_and_decrypt_mem(self, vid, qname):
        """内存拉取并解密指定剧集，不写本地文件"""
        cache_key = '%s_%s' % (vid, qname)
        with self._mem_lock:
            if self._current_stream['key'] == cache_key and self._current_stream['data']:
                return self._current_stream['data']

            url, spade = self._play_url_of(vid, qname)
            key = self._spade_key(spade) if spade else None
            if not key:
                raise IOError('无 spade_a')

            code, raw = _http('GET', url, {'User-Agent': UA_APP % self.api.model}, None, 120)
            if not raw or len(raw) < 100000:
                raise IOError('下载失败 %s' % code)

            # 私有编码(bvc2)无法播放 -> 自动换 1080p
            if not _playable_codec(raw) and qname != '1080p':
                u2, sp2 = self._play_url_of(vid, '1080p')
                k2 = self._spade_key(sp2) if sp2 else None
                c2, r2 = _http('GET', u2, {'User-Agent': UA_APP % self.api.model}, None, 120)
                if r2 and len(r2) > 100000 and _playable_codec(r2):
                    raw, key = r2, k2

            plain, stat = decrypt_mp4(raw, key)
            self.last_err = 'mem_stream_ok backend=%s stat=%s' % (_AES_BACKEND, stat)

            # 仅覆盖保留当前这一条在内存，切换集数自动释放上一集内存
            self._current_stream['key'] = cache_key
            self._current_stream['data'] = plain
            return plain

    def _tt_detail(self, item_id):
        it = self.tt.find(item_id)
        if not it:
            return {'list': []}
        url, expire, dur = self.tt._play(it)
        title = self.tt._clean_title(it.get('title') or '')
        remark = ('%d分钟' % (dur // 60)) if dur >= 60 else ('%d秒' % dur if dur else '')
        return {'list': [{
            'vod_id': 'tt_' + item_id,
            'vod_name': title or '头条视频',
            'vod_pic': self.tt._cover(it),
            'vod_content': it.get('abstract') or title,
            'vod_remarks': remark,
            'vod_play_from': '头条',
            'vod_play_url': '正片$tt_%s@@%s' % (item_id, url),
        }]}

    def playerContent(self, flag, pid, vipFlags):
        pid = str(pid).strip()
        # 头条：id 里已带直链，直接返回播放
        if 'tt_' in pid or '@@' in pid:
            raw = pid
            if '@@' in raw:
                raw = raw.split('@@', 1)[1]
            if raw.startswith('http'):
                return {'parse': 0, 'playUrl': '', 'url': raw,
                        'header': {'User-Agent': ToutiaoFeed.UA,
                                   'Referer': 'https://www.toutiao.com/'}}
            return {'parse': 1, 'playUrl': '', 'url': pid, 'header': {}}

        if '|' in pid:
            vid, qname = pid.split('|')[0], pid.split('|')[1]
        else:
            vid = pid
            qname = str(flag or '480p').strip() or '480p'
            if qname.endswith('P'):
                qname = qname[:-1] + 'p'

        # 无加密加速库时自动改小档位，避免纯 Python 解密耗时过长
        if _detect_aes() == 'python' and qname not in ('360p', '480p'):
            qname = '360p'

        # 确保本地 HTTP 服务已启动，返回本地代理流地址
        port = self._start_proxy_server()
        proxy_url = 'http://127.0.0.1:%d/play?vid=%s&q=%s' % (
            port, urllib.parse.quote(vid), urllib.parse.quote(qname)
        )
        return {
            'parse': 0,
            'playUrl': '',
            'url': proxy_url,
            'header': {},
        }

    def localProxy(self, param):
        return None


# ============================== 自检 =======================================
if __name__ == '__main__':
    assert sm3(b'abc').hex() == '66c7f0f462eeedd9d1f2d46bdc10e4e24167c4875cf2f7a2297da02b8f4ba8e0'
    print('[OK] SM3')
    sp = Spider()
    sp.init('')
    print('分类:', [n for _k, n in CATS])
    print('首页:', len(sp.homeContent(False).get('list', [])), '条')
    print('头条精选第1页:', len(sp.categoryContent('t:jx', '1', False, {})['list']), '条')
    print('头条精选第2页:', len(sp.categoryContent('t:jx', '2', False, {})['list']), '条')
    s = sp.searchContent('重生', False, '1')
    print('搜索:', len(s['list']), '条')
    sid = s['list'][0]['vod_id'] if s['list'] else '7671966197985856536'
    d = sp.detailContent([sid])['list'][0]
    print('详情:', d['vod_name'], '| 线路:', d['vod_play_from'])
    pid = d['vod_play_url'].split('$$$')[0].split('#')[0].split('$')[1]
    print('播放代理地址:', sp.playerContent('1080p', pid, []))
