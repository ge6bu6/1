# -*- coding: utf-8 -*-

import base64
import binascii
import gzip
import html as _htmlmod
import io
import json
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
import http.client
import http.cookiejar

try:
    from base.spider import Spider as _BaseSpider
except Exception:
    class _BaseSpider(object):
        pass

try:
    from concurrent.futures import ThreadPoolExecutor
except Exception:
    ThreadPoolExecutor = None

__version__ = "2.0.5"

PC_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
MOB_UA = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")

TIMEOUT = 14
MAX_PAGE = 9999


# ============================================================

# ============================================================

def _s(v):
    if v is None:
        return ""
    if isinstance(v, bytes):
        try:
            return v.decode("utf-8", "ignore").strip()
        except Exception:
            return ""
    return str(v).strip()


def _txt(s):
    s = re.sub(r"<[^>]+>", " ", _s(s))
    s = _htmlmod.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _abs(base, u):
    u = _s(u)
    if not u:
        return ""
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("http"):
        return u
    try:
        return urllib.parse.urljoin(base or "/", u)
    except Exception:
        return u


def _b64(s):
    return base64.urlsafe_b64encode(_s(s).encode("utf-8")).decode("ascii").rstrip("=")


def _ub64(s):
    s = _s(s)
    try:
        s += "=" * (-len(s) % 4)
        return base64.urlsafe_b64decode(s.encode("ascii")).decode("utf-8", "ignore")
    except Exception:
        return ""


_ENT = [("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
        ("&quot;", '"'), ("&#39;", "'"), ("&apos;", "'"), ("&ldquo;", '"'),
        ("&rdquo;", '"'), ("&middot;", "·"), ("&hellip;", "…")]


def _ent(s):
    s = _s(s)
    for a, b in _ENT:
        s = s.replace(a, b)
    return _htmlmod.unescape(s)


# ============================================================
# HTTP
# ============================================================

class _Sess(object):
    def __init__(self, base, ua=None, timeout=None):
        self.base = _s(base).rstrip("/")
        self.ua = ua or MOB_UA
        self._timeout = timeout
        self._ctx = None
        self._opener = None
        self.jar = http.cookiejar.CookieJar()
        self._lock = threading.Lock()
        self._req = None
        self._req_ok = False
        try:
            import requests as _rq
            self._req = _rq
            self._session = _rq.Session()
            self._req_ok = True
        except Exception:
            self._session = None

    def post(self, url, data=None, ref=None, timeout=None):
        url = _abs(self.base + "/", url)
        if self._req_ok and self._session is not None:
            hd = {"User-Agent": self.ua,
                  "Accept": "application/json,*/*",
                  "Content-Type": "application/json",
                  "Referer": ref or (self.base + "/")}
            with self._lock:
                r = self._session.post(url, json=data, headers=hd,
                                       timeout=timeout or TIMEOUT, verify=False)
            try:
                return r.url or url, r.json()
            except Exception:
                return r.url or url, r.text or ""
        import json as _js
        body = _js.dumps(data or {}).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("User-Agent", self.ua)
        req.add_header("Content-Type", "application/json")
        req.add_header("Referer", ref or (self.base + "/"))
        ctx = self._ssl()
        with urllib.request.urlopen(req, timeout=timeout or self._timeout or TIMEOUT, context=ctx) as r:
            raw = r.read().decode("utf-8", "ignore")
        try:
            return url, _js.loads(raw)
        except Exception:
            return url, raw

    def _ssl(self):
        if self._ctx is None:
            try:
                c = ssl.create_default_context()
                c.check_hostname = False
                c.verify_mode = ssl.CERT_NONE
                try:
                    c.set_ciphers("DEFAULT@SECLEVEL=1")
                except Exception:
                    pass
                self._ctx = c
            except Exception:
                self._ctx = ssl._create_unverified_context()
        return self._ctx

    def _get_opener(self):
        if self._opener is None:
            try:
                h = urllib.request.HTTPSHandler(context=self._ssl())
            except Exception:
                h = urllib.request.HTTPSHandler()
            self._opener = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(self.jar), h)
        return self._opener

    def get(self, url, ref=None, timeout=None, ua=None, tries=3):
        url = _abs(self.base + "/", url)
        if self._req_ok and self._session is not None:
            last = None
            for n in range(max(1, tries)):
                try:
                    hd = {"User-Agent": ua or self.ua,
                          "Accept": "text/html,application/xhtml+xml,application/json,*/*;q=0.8",
                          "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                          "Referer": ref or (self.base + "/")}
                    with self._lock:
                        r = self._session.get(url, headers=hd,
                                              timeout=timeout or self._timeout or TIMEOUT,
                                              verify=False)
                    txt = r.text or ""
                    try:
                        enc0 = (r.encoding or "").lower()
                        enc_ap = (r.apparent_encoding or "").lower()
                        if enc0 in ("iso-8859-1", "latin-1") and enc_ap.startswith("utf"):
                            txt = r.content.decode("utf-8", "ignore")
                    except Exception:
                        pass
                    if txt.count("\ufffd") > 30:
                        try:
                            enc = r.apparent_encoding
                            if enc:
                                txt = r.content.decode(enc, "ignore")
                        except Exception:
                            pass
                    return r.url or url, txt
                except Exception as e:
                    last = e
                    if n < tries - 1:
                        time.sleep(0.4 + 0.5 * n)
            raise last if last else RuntimeError("request failed")
        last = None
        for n in range(max(1, tries)):
            try:
                hd = {"User-Agent": ua or self.ua,
                      "Accept": "text/html,application/xhtml+xml,application/json,*/*;q=0.8",
                      "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                      "Accept-Encoding": "gzip, deflate",
                      "Referer": ref or (self.base + "/")}
                req = urllib.request.Request(url, headers=hd)
                try:
                    r = self._get_opener().open(req, timeout=timeout or TIMEOUT)
                    raw = r.read()
                    final = r.geturl() or url
                except http.client.IncompleteRead as e:
                    raw = e.partial or b""
                    if not raw:
                        raise
                    final = url
                enc = ""
                try:
                    enc = (r.headers.get("Content-Encoding") or "").lower()
                except Exception:
                    enc = ""
                if enc == "gzip":
                    try:
                        raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
                    except Exception:
                        pass
                elif enc == "deflate":
                    try:
                        raw = zlib.decompress(raw)
                    except Exception:
                        try:
                            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                        except Exception:
                            pass
                elif enc == "br":
                    try:
                        import brotli
                        raw = brotli.decompress(raw)
                    except Exception:
                        pass
                txt = raw.decode("utf-8", "ignore")
                if txt.count("\ufffd") > 30:
                    for e in ("gbk", "gb18030", "big5"):
                        try:
                            t2 = raw.decode(e)
                            if t2.count("\ufffd") < txt.count("\ufffd"):
                                txt = t2
                                break
                        except Exception:
                            pass
                return final, txt
            except Exception as e:
                last = e
                if n < tries - 1:
                    time.sleep(0.4 + 0.5 * n)
        raise last if last else RuntimeError("request failed")

_NAV = ("/vodtype/", "/vodshow/", "/label/", "/search", "/vodsearch", "/topic",
        "/arttype", "/map/", "/index/index", "/art/", "/help/", "/ad.",
        "/tags/", "/artists/", "/page/", "/show/", "/type/id/", "/index.php/label/",
        "/user/", "/login", "/index.php/user/", "/tag/", "/center", "/my",
        "javascript:", "mailto:")

_JUNK_T = ("立即观看", "立即播放", "在线播放", "播放", "更多", "详情", "收藏", "喜欢",
           "首页", "全部", "查看", "下载", "分享", "评论", "上一篇", "下一篇",
           "热门", "推荐", "最新", "更多>", ">>", "›", "‹", "上一页", "下一页",
           "免费观看", "点击播放", "立即观看", "广告", "登录", "注册")

_BAD_IMG = (".gif", ".svg", "logo", "noimage", "nopic", "loading", "lazyload",
            "blank", "default", "poster_loading", "placeholder", "avatar")

_KIND = ("/play", "/detail", "/vodplay", "/videos/", "/drama/", "/watch",
         "/video/", "/mov/", "/post/", "/v/")
_LIST_BAD = ("/type", "/show", "/list", "/category", "/label", "/class", "/sort")


def _junk_title(t):
    t = _s(t).lstrip("▶►●○■□◆◇★☆·•|—_ -")
    if len(t) < 2:
        return True
    if t in _JUNK_T or t.replace(" ", "") in _JUNK_T:
        return True
    if t.startswith("\u66f4\u591a") or t.startswith("\u67e5\u770b\u66f4\u591a"):
        return True
    if re.fullmatch(r"[\d\s:.\-/]+", t):
        return True
    if set(t) <= set("-><!- "):
        return True
    return False


def _anchors(h):
    out = []
    for m in re.finditer(r"<a\b([^>]*)>(.*?)</a>", h, re.S | re.I):
        att = m.group(1)
        hm = re.search(r'''href\s*=\s*["']([^"']+)["']''', att, re.I)
        if not hm:
            continue
        tm = re.search(r'''title\s*=\s*["']([^"']*)["']''', att, re.I)
        out.append({"u": hm.group(1).strip(),
                    "t": _txt(m.group(2)),
                    "a": _txt(tm.group(1)) if tm else "",
                    "s": m.start(), "e": m.end()})
    return out


def _key(u):
    p = re.sub(r"^https?://[^/]+", "", u)
    p = re.split(r"[?#]", p)[0]
    segs = []
    for seg in p.split("/"):
        if (re.search(r"\d", seg)
                or re.fullmatch(r"[0-9a-fA-F]{6,}", seg)
                or (len(seg) >= 8 and re.search(r"[A-Z]", seg) and re.search(r"[a-z]", seg))):
            segs.append("H")
        else:
            segs.append(seg)
    return "/".join(segs)[:80]


def _detect_items(h, base):
    groups, order = {}, []
    for a in _anchors(h):
        u = a["u"]
        lu = u.lower()
        if u.startswith("#") or lu.startswith(("javascript", "mailto")):
            continue
        if any(k in lu for k in _NAV):
            continue
        if not re.search(r"\d|/[0-9a-zA-Z_\-]{4,}/?$", u):
            continue
        k = _key(u)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(a)
    cand = []
    for k in order:
        g = groups[k]
        if len(g) < 5:
            continue
        kl = k.lower()
        sc = float(len(g))
        is_kind = any(x in kl for x in _KIND)
        if is_kind:
            sc *= 3.0
        if any(x in kl for x in _LIST_BAD):
            sc *= 0.12
        cand.append((sc, is_kind, k, g))
    if not cand:
        return []
    kind_cand = [c for c in cand if c[1]]
    pool = kind_cand or cand
    pool.sort(key=lambda x: -x[0])
    return pool[0][3]


def _title_of(a, blk, all_a):
    cands = []
    for g in all_a:
        cands.append(g["a"])
        cands.append(g["t"])
    cands.append(a["a"])
    cands.append(a["t"])
    for p in (r'''alt=["']([^"']{3,120})["']''',
              r'''class=["'][^"']*(?:title|vodname|video-name|desc|name)[^"']*["'][^>]*>(?:<[^>]+>)*([^<]{3,120})''',
              r"<h[2-6][^>]*>(.*?)</h[2-6]>",
              r'''title=["']([^"']{3,120})["']'''):
        for m in re.finditer(p, blk, re.S | re.I):
            cands.append(_txt(m.group(1)))
    for c in cands:
        c = _txt(c)
        if not _junk_title(c):
            return c[:120]
    return ""


def _pic_score(u, tag):
    lu = _s(u).lower()
    if not u or lu.startswith("data:"):
        return -100
    if any(x in lu for x in (".js", ".css", ".json")):
        return -100
    sc = 0
    if re.search(r"\.(jpg|jpeg|png|webp|avif)(\?|#|$)", lu):
        sc += 10
    if "poster" in tag.lower():
        sc += 5
    if any(x in lu for x in ("upload", "pics", "cover", "poster", "thumb", "vod")):
        sc += 3
    if any(x in lu for x in ("badge", "icon", "free.png", "hits.png", "logo", "avatar")):
        sc -= 10
    if any(x in lu for x in (".mp4", ".mov", ".m3u8")):
        sc -= 20
    return sc

def _pic_of(blk, base):
    cands = []
    for m in re.finditer(r"<img\b[^>]*>", blk, re.I | re.S):
        tag = m.group(0)
        for attr in ("data-original", "data-src", "data-lazy", "data-echo", "data-preview", "poster"):
            mm = re.search(attr + r'''\s*=\s*["']([^"']+)["']''', tag, re.I)
            if mm:
                cands.append((mm.group(1), tag))
        for attr in ("data-srcset", "srcset"):
            mm = re.search(attr + r'''\s*=\s*["']([^"']+)["']''', tag, re.I)
            if mm:
                parts = [p.strip().split()[0] for p in mm.group(1).split(",") if p.strip()]
                if parts:
                    cands.append((parts[-1], tag))
        mm = re.search(r'''\bsrc\s*=\s*["']([^"']+)["']''', tag, re.I)
        if mm:
            cands.append((mm.group(1), tag))
    for m in re.finditer(r"<video\b[^>]*>", blk, re.I | re.S):
        mm = re.search(r'''poster\s*=\s*["']([^"']+)["']''', m.group(0), re.I)
        if mm:
            cands.append((mm.group(1), m.group(0)))
    for m in re.finditer(r"url\(\s*['\"]?([^)'\"]+)", blk, re.I):
        cands.append((m.group(1), "style"))
    for m in re.finditer(r'''["']?((?:https?:)?//[^"'\s<>]+\.(?:jpg|jpeg|png|webp|avif)[^"'\s<>]*)''', blk, re.I):
        cands.append((m.group(1), "bare"))
    for m in re.finditer(r'''(/[^"'\s<>]+\.(?:jpg|jpeg|png|webp|avif)[^"'\s<>]*)''', blk, re.I):
        cands.append((m.group(1), "bare"))
    best = ""
    best_sc = -100
    for u, tag in cands:
        u = _s(u).strip().strip("'\"")
        if not u or any(x in u.lower() for x in _BAD_IMG):
            continue
        sc = _pic_score(u, tag)
        if sc > best_sc:
            best_sc = sc
            best = u
    if best_sc < 0:
        return ""
    return _abs(base, best)


def _parse_list(h, base):
    if "pornhub" in _s(base):
        out, seen = [], set()
        for a in _anchors(h):
            u = a["u"]
            if "view_video.php" not in u or "viewkey" not in u:
                continue
            fu = urllib.parse.urljoin(base, u)
            if fu in seen:
                continue
            seen.add(fu)
            blk = h[max(0, a["s"] - 1200):a["e"] + 1200]
            t = _txt(a["t"] or a["a"])
            if not t:
                m = re.search(r'''alt=["']([^"']+)''', blk)
                if m:
                    t = _txt(m.group(1))
            p = _pic_of(blk, base)
            if t:
                out.append({"url": fu, "title": t, "pic": p, "blk": blk})
        if len(out) >= 5:
            return out
    if "hsex" in _s(base):
        _groups = {}
        for _a in _anchors(h):
            _u = _a["u"]
            if not re.fullmatch(r"video-\d+\.htm", _u):
                continue
            _fu = urllib.parse.urljoin(base, _u)
            _t = _txt(_a["t"] or _a["a"])
            if re.fullmatch(r"\d+:\d+(\s+HD)?", _t):
                continue
            if _fu not in _groups or len(_t) > len(_groups[_fu][0]):
                _blk = h[max(0, _a["s"] - 1200):_a["e"] + 1200]
                _groups[_fu] = (_t, _blk)
        _out = []
        for _fu, (_t, _blk) in _groups.items():
            if _t:
                _out.append({"url": _fu, "title": _t, "pic": _pic_of(_blk, base), "blk": _blk})
        if len(_out) >= 5:
            return _out
    items = _detect_items(h, base)
    if not items:
        return []
    urls = [urllib.parse.urljoin(base, a["u"]) for a in items]
    out, seen = [], set()
    for i, a in enumerate(items):
        u = urls[i]
        if u in seen:
            continue
        seen.add(u)
        nxt = items[i + 1]["s"] if i + 1 < len(items) else min(len(h), a["e"] + 1200)
        prev_end = items[i - 1]["e"] if i > 0 else 0
        blk = h[max(prev_end, a["s"] - 1200):nxt]
        same = [items[j] for j in range(max(0, i - 6), min(len(items), i + 7)) if urls[j] == u]
        t = _title_of(a, blk, same)
        p = _pic_of(blk, base)
        if not t and not p:
            continue
        out.append({"url": u, "title": t, "pic": p, "blk": blk})

    if out:
        got = sum(1 for x in out if x["title"])
        if got >= max(3, len(out) * 0.6):
            out = [x for x in out if x["title"]]
    return out


def _clean_cat_title(t):
    t = _txt(t)
    t = re.sub(r"[\ue000-\uf8ff]", "", t)
    t = re.sub(r"^\d+\s*", "", t)
    return t.strip()

def _detect_cats(h):
    out, seen_url, seen_title = [], set(), set()
    for a in _anchors(h):
        u = a["u"]
        lu = u.lower()
        if not any(k in lu for k in ("/vodtype/", "/vod/show/", "/vodshow/",
                                     "/vod/type/", "/vod/index.html", "/genre/", "/genres/",
                                     "/category/", "/categories/",
                                     "/class/", "/type/id/", "/channels/",
                                     "/channel/", "/pornstars/", "/models/",
                                     "/actresses/", "/actress/", "/stars/",
                                     "/tags/", "/tag/", "/list/", "/sort/")):
            continue
        if "/arttype/" in lu:
            continue
        t = _clean_cat_title(a["t"] or a["a"])
        if _junk_title(t) or len(t) > 32:
            continue
        if t.startswith("\u66f4\u591a") or t.startswith("\u67e5\u770b\u66f4\u591a"):
            continue
        if u in seen_url:
            continue
        seen_url.add(u)
        out.append((u, t))
    return out


# ============================================================

# ============================================================

def _dec(u, enc):
    e = _s(enc).lower()
    u = _s(u)
    if e in ("", "0", "null"):
        return u
    try:
        if e == "1":
            return base64.b64decode(u + "=" * (-len(u) % 4)).decode("utf-8", "ignore")
        if e == "2":
            return urllib.parse.unquote(u)
        if e == "3":
            return binascii.unhexlify(u).decode("utf-8", "ignore")
    except Exception:
        return ""
    return u


def _clean_stream(u, base):
    u = _s(u).replace("\\/", "/").replace("\\u0026", "&").replace("\\&", "&")
    u = u.strip().strip("\"'<> \t\r\n")
    u = re.split(r'["\'\s<>]+', u)[0] if u else ""
    if u.startswith("//"):
        u = "https:" + u
    if not u.startswith("http") and not u.startswith("magnet:"):
        u = _abs(base, u)
    return u

def _stream_kind(u):
    lu = _s(u).lower().split("?")[0]
    if ".m3u8" in lu:
        return "m3u8"
    if ".mp4" in lu:
        return "mp4"
    if u.startswith("magnet:"):
        return "magnet"
    return ""

def _walk_streams(obj, out):
    if isinstance(obj, str):
        s = _s(obj)
        if ".m3u8" in s or ".mp4" in s:
            out.append(s)
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk_streams(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _walk_streams(v, out)

def _balanced_json(h, start):
    depth = 0
    in_str = False
    esc = False
    for k in range(start, len(h)):
        ch = h[k]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return h[start:k + 1]
    return ""

def _balanced_json_array(h, start):
    depth = 0
    in_str = False
    esc = False
    for k in range(start, len(h)):
        ch = h[k]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return h[start:k + 1]
    return ""

def _try_json(s):
    try:
        return json.loads(s.replace("\\/", "/"), strict=False)
    except Exception:
        return None

def _player_jsons(h):
    out = []
    for m in re.finditer(r"player_[A-Za-z0-9_]+\s*=\s*\{", h):
        b = _balanced_json(h, m.end() - 1)
        if b:
            j = _try_json(b)
            if isinstance(j, dict):
                out.append(j)
    for m in re.finditer(r"\b(?:DPlayer|Artplayer|ckplayer|Aliplayer|jwplayer|videojs)\b[^\\{]{0,300}?\{", h, re.I):
        b = _balanced_json(h, m.end() - 1)
        if b:
            j = _try_json(b)
            if isinstance(j, dict):
                out.append(j)
    return out

def _dec_any(u, enc):
    u = _s(u)
    e = _s(enc).lower()
    if e in ("", "0", "null"):
        return u
    d = _dec(u, enc)
    if d:
        return d
    try:
        return base64.b64decode(u + "=" * (-len(u) % 4)).decode("utf-8", "ignore") or u
    except Exception:
        return u

def _extract_direct(h, base):
    _mi = h.find("mediaDefinitions")
    if _mi >= 0:
        _br = h.find("[", _mi)
        if _br >= 0:
            _bj = _balanced_json_array(h, _br)
            _defs = _try_json(_bj) if _bj else None
            if isinstance(_defs, list):
                _best = None
                for _d in _defs:
                    if not isinstance(_d, dict):
                        continue
                    _vu = _clean_stream(_s(_d.get("videoUrl")), base)
                    if not _vu or not _stream_kind(_vu):
                        continue
                    try:
                        _q = int(str(_d.get("quality") or "0").strip() or 0)
                    except Exception:
                        _q = 0
                    _is_hls = 1 if _d.get("format") == "hls" else 0
                    _key = (_is_hls, _q)
                    if _best is None or _key > _best[0]:
                        _best = (_key, _vu)
                if _best:
                    return _stream_kind(_best[1]), _best[1], ""
    for j in _player_jsons(h):
        enc = j.get("encrypt")
        cands = []
        for k in ("url", "url_next", "video", "src", "file", "playUrl", "stream"):
            if j.get(k):
                cands.append(j.get(k))
        extra = []
        _walk_streams(j, extra)
        cands.extend(extra)
        for c in cands:
            if isinstance(c, dict):
                sub = []
                _walk_streams(c, sub)
                cands.extend(sub)
                continue
            u = _dec_any(c, enc) if enc not in (None, "", "0", "null") else _s(c)
            u = _clean_stream(u, base)
            if u and _stream_kind(u):
                return _stream_kind(u), u, _s(j.get("from"))
    for p in (r"<video[^>]+src=[\"']([^\"']+)[\"']",
              r"<source[^>]+src=[\"']([^\"']+)[\"']",
              r'''data-(?:url|video|play|src)=["']([^"']{10,600})["']'''):
        for m in re.finditer(p, h, re.I):
            u = _clean_stream(m.group(1), base)
            if u and _stream_kind(u):
                return _stream_kind(u), u, ""
    for m in re.finditer(r'''["']((?:https?:)?//[^"'\s\\<>]{8,600}?\.(?:m3u8|mp4)[^"'\s\\<>]*)["']''', h, re.I):
        u = _clean_stream(m.group(1), base)
        if u and _stream_kind(u):
            return _stream_kind(u), u, ""
    for m in re.finditer(r'''["'](/[^"'\s<>]{6,600}?\.(?:m3u8|mp4)[^"'\s<>]*)["']''', h, re.I):
        u = _clean_stream(m.group(1), base)
        if u and _stream_kind(u):
            return _stream_kind(u), u, ""
    for m in re.finditer(r'''["'](?:url|src|file|videoUrl|playUrl|stream|m3u8|mp4)["']\s*[:=]\s*["']([^"']{8,600})["']''', h, re.I):
        u = _clean_stream(m.group(1), base)
        if u and _stream_kind(u):
            return _stream_kind(u), u, ""
    for m in re.finditer(r"[A-Za-z0-9+/=_-]{80,}", h):
        s = m.group(0)
        if ".m3u8" in s or ".mp4" in s:
            continue
        try:
            d = base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode("utf-8", "ignore")
        except Exception:
            continue
        if ".m3u8" in d or ".mp4" in d:
            mm = re.search(r"(https?://[^\s\"'<>]+?\.(?:m3u8|mp4)[^\s\"'<>]*)", d)
            if mm:
                u = _clean_stream(mm.group(1), base)
                if u and _stream_kind(u):
                    return _stream_kind(u), u, ""
    for m in re.finditer(r"\b[0-9a-fA-F]{80,}\b", h):
        try:
            d = binascii.unhexlify(m.group(0)).decode("utf-8", "ignore")
        except Exception:
            continue
        if ".m3u8" in d or ".mp4" in d:
            mm = re.search(r"(https?://[^\s\"'<>]+?\.(?:m3u8|mp4)[^\s\"'<>]*)", d)
            if mm:
                u = _clean_stream(mm.group(1), base)
                if u and _stream_kind(u):
                    return _stream_kind(u), u, ""
    return "empty", "", ""

def _play_of(h, base):
    return _extract_direct(h, base)

def _find_play_links(h, base):
    scored = []
    for m in re.finditer(r'''href=["']([^"']+)["']''', h, re.I):
        u = _abs(base, m.group(1))
        lu = u.lower()
        if not any(k in lu for k in ("/vod/play", "/vodplay", "/play/", "/play?",
                                     "/watch", "/player", "/embed", "/video/play",
                                     "/drama/play")):
            continue
        if any(k in lu for k in ("/vodtype", "/vodshow", "/type/", ".css", ".js", ".jpg", ".png")):
            continue
        sc = 0
        if "/vod/play/id/" in lu:
            sc = 3
        elif "/vodplay/" in lu:
            sc = 2
        else:
            sc = 1
        scored.append((sc, u))
    scored.sort(key=lambda x: -x[0])
    out = []
    for _, u in scored:
        if u not in out:
            out.append(u)
    return out

def _find_iframes(h, base):
    out = []
    for m in re.finditer(r'''<iframe[^>]+src=["']([^"']{12,600})["']''', h, re.I):
        u = _abs(base, m.group(1))
        if u and u not in out:
            out.append(u)
    return out

def _find_api_candidates(h, base):
    out = []
    for m in re.finditer(r'''["']([^"']*?/api/[^"']*?)["']''', h, re.I):
        u = _abs(base, m.group(1))
        lu = u.lower()
        if any(k in lu for k in ("play", "video", "stream", "get", "m3u8", "url")):
            if u not in out:
                out.append(u)
    return out

def _find_play_link(h, base):
    links = _find_play_links(h, base)
    return links[0] if links else ""

def _page_url(u, pg):
    if pg <= 1:
        return u
    out = [u]
    if "?" in u:
        out.append("%s&page=%d" % (u, pg))
        out.append("%s&p=%d" % (u, pg))
    else:
        out.append("%s?page=%d" % (u, pg))
        if u.endswith(".html"):
            out.append(u[:-5] + "/page/%d.html" % pg)
            out.append(u.rsplit("/", 1)[0] + "/page/%d.html" % pg)
        elif u.endswith("/"):
            out.append(u + "page/%d/" % pg)
            out.append(u + "page/%d.html" % pg)
        else:
            out.append(u + "/page/%d/" % pg)
    return out


# ============================================================

# ============================================================

SEARCH_DEADLINE = 12


def _wait(futs, timeout):
    if ThreadPoolExecutor:
        try:
            from concurrent.futures import wait as _w
            return _w(list(futs), timeout=timeout)
        except Exception:
            pass
    return [], []


def _shut(ex):
    if ex is None:
        return
    try:
        ex.shutdown(wait=False)
    except TypeError:
        try:
            ex.shutdown(wait=False)
        except Exception:
            pass
    except Exception:
        pass


class _Src(object):
    def __init__(self, sid, name, base, opt=None):
        self.id = sid
        self.name = name
        self.base = _s(base).rstrip("/")
        self.opt = opt or {}
        self.ua = self.opt.get("ua") or MOB_UA
        self._sess = None
        self._cats = None
        self.last_err = ""
        self.fixed_cats = self.opt.get("cats")
        self._detail_cache = {}

    @property
    def sess(self):
        if self._sess is None:
            self._sess = _Sess(self.base, self.ua, self.opt.get("timeout"))
        return self._sess


    def categories(self):
        if self.fixed_cats:
            return [(_abs(self.base, u), t) for u, t in self.fixed_cats]
        if self._cats is not None:
            return self._cats
        try:
            b, h = self.sess.get(self.base + "/", timeout=10, tries=2)
            got = _detect_cats(h)
            home = b.rstrip("/") + "/"
            cats = [(_abs(home, u), t) for u, t in got][:40]
            cats = [(u, t) for u, t in cats if "help." not in u]
            if self.id == "javbus" and len(cats) < 10:
                try:
                    b2, h2 = self.sess.get(self.base + "/genre", timeout=10, tries=2)
                    g2 = [(_abs(b2, u), t) for u, t in _detect_cats(h2)]
                    if len(g2) > len(cats):
                        cats = g2[:40]
                except Exception:
                    pass
            if self.id == "pornhub" and len(cats) < 5:
                try:
                    b2, h2 = self.sess.get(self.base + "/categories", timeout=10, tries=2)
                    g2 = [(_abs(b2, u), t) for u, t in _detect_cats(h2)
                          if "help." not in u]
                    if g2:
                        cats = g2[:40]
                except Exception:
                    pass
            if self.id == "rb91":
                expanded = []
                for cu, ct in cats:
                    path = urllib.parse.urlparse(cu).path.rstrip("/")
                    if path in ("/categories", "/channels"):
                        try:
                            b2, h2 = self.sess.get(cu, timeout=10, tries=2)
                            seen2 = set()
                            for a in _anchors(h2):
                                au = _abs(b2, a["u"])
                                ap = urllib.parse.urlparse(au).path
                                if not re.fullmatch(r"/(?:categories|channels)/[^/]+/", ap):
                                    continue
                                at = _clean_cat_title(a["t"] or a["a"])
                                at = re.sub(r"\s+\d[\d,\.Kk]*\s*\d*%?\s*$", "", at).strip()
                                if _junk_title(at) or len(at) > 32:
                                    continue
                                if au in seen2:
                                    continue
                                seen2.add(au)
                                expanded.append((au, at))
                        except Exception:
                            pass
                    else:
                        expanded.append((cu, ct))
                seen3, dedup = set(), []
                for cu, ct in expanded:
                    if cu in seen3:
                        continue
                    seen3.add(cu)
                    dedup.append((cu, ct))
                cats = dedup[:40]
            if cats:
                self._cats = cats
            else:
                self.last_err = "no categories found"
            return cats
        except Exception as e:
            self.last_err = "%s" % _s(e)[:80]
            return []

    def detail_pic(self, url):
        try:
            b, h = self.sess.get(url, ref=self.base + "/", timeout=10, tries=2)
        except Exception:
            return ""
        m = re.search(r'''<meta[^>]+property=["']og:image["'][^>]+content=["']([^"']+)''', h, re.I)
        if m:
            return _abs(b, m.group(1))
        m = re.search(r'''<meta[^>]+name=["']twitter:image["'][^>]+content=["']([^"']+)''', h, re.I)
        if m:
            return _abs(b, m.group(1))
        return _pic_of(h[:50000], b)

    def _fill_pics(self, items):
        empties = [x for x in items if not x.get("pic")][:20]
        if not empties or not ThreadPoolExecutor:
            return items
        ex = None
        try:
            ex = ThreadPoolExecutor(max_workers=6)
            fut = {ex.submit(self.detail_pic, x["url"]): x for x in empties}
            done, _ = _wait(fut.keys(), 12)
            for f in done:
                try:
                    p = f.result() if not f.exception() else ""
                except Exception:
                    p = ""
                if p:
                    fut[f]["pic"] = p
        except Exception:
            pass
        finally:
            if ex is not None:
                try:
                    ex.shutdown(wait=False)
                except Exception:
                    pass
        return items

    def home_list(self):
        try:
            b, h = self.sess.get(self.base + "/")
        except Exception as e:
            self.last_err = "首页打不开：%s" % _s(e)[:60]
            return []
        items = _parse_list(h, b)
        if not items:
            self.last_err = "首页没认出列表结构"
        return self._fill_pics(items)

    def cat(self, cat_url, pg=1):
        if self.id == "tangxin" and _s(cat_url).rstrip("/") == self.base + "/artists":
            try:
                b, h = self.sess.get(cat_url)
            except Exception:
                return []
            out, seen = [], set()
            for a in _anchors(h):
                au = _abs(b, a["u"])
                if not re.fullmatch(r"https?://[^/]+/artists/[^/]+/", au):
                    continue
                if au in seen:
                    continue
                seen.add(au)
                t = _txt(a["t"] or a["a"]).split()[0] if _txt(a["t"] or a["a"]) else ""
                if not t or _junk_title(t):
                    continue
                blk = h[max(0, a["s"] - 600):a["e"] + 200]
                out.append({"url": au, "title": t, "pic": _pic_of(blk, b), "blk": blk})
            return out
        pg = max(1, int(pg or 1))
        urls = _page_url(cat_url or (self.base + "/"), pg)
        if pg == 1:
            urls = [urls] if isinstance(urls, str) else urls
            urls = urls[:1]
        for u in urls:
            try:
                b, h = self.sess.get(u)
            except Exception as e:
                self.last_err = "列表页打不开：%s" % _s(e)[:60]
                continue
            items = _parse_list(h, b)
            if items:
                return self._fill_pics(items)
        if pg == 1 and _s(cat_url or "").rstrip("/") in (self.base, self.base + "/"):
            return self.home_list()
        return []

    def detail(self, url):
        try:
            import time as _tm
            _c = self._detail_cache.get(url)
            if _c and _tm.time() - _c[0] < 600:
                return dict(_c[1])
        except Exception:
            pass
        b, h = self.sess.get(url)
        title = ""
        m = re.search(r"<title>(.*?)</title>", h, re.S)
        if m:
            title = _txt(m.group(1))
            title = re.split(r"\s*[-|_—]\s*(?:在线播放|详情介绍|免费|高清|HD)", title)[0].strip() or title
        pic = ""
        m = re.search(r'''<meta[^>]+property=["']og:image["'][^>]+content=["']([^"']+)''', h, re.I)
        if m:
            pic = _abs(b, m.group(1))
        if not pic:
            m = re.search(r'''<meta[^>]+name=["']twitter:image["'][^>]+content=["']([^"']+)''', h, re.I)
            if m:
                pic = _abs(b, m.group(1))
        if not pic:
            pic = _pic_of(h[:50000], b)
        content = ""
        m = re.search(r'''<meta[^>]+name=["']description["'][^>]+content=["']([^"']{6,400})''', h, re.I)
        if m:
            content = _txt(m.group(1))[:240]
        kind, play, frm = _extract_direct(h, b)
        play_page = b
        iframe = ""
        if kind == "empty":
            for pl in _find_play_links(h, b)[:3]:
                if pl == b:
                    continue
                try:
                    b2, h2 = self.sess.get(pl, ref=b)
                except Exception:
                    continue
                k2, p2, f2 = _extract_direct(h2, b2)
                if k2 in ("m3u8", "mp4", "magnet"):
                    kind, play, frm, play_page = k2, p2, f2, b2
                    break
                if kind == "empty":
                    for ifr in _find_iframes(h2, b2)[:2]:
                        if not iframe:
                            iframe = ifr
        if kind == "empty":
            for api in _find_api_candidates(h, b)[:3]:
                try:
                    b2, h2 = self.sess.get(api, ref=b)
                except Exception:
                    continue
                j = _try_json(h2.strip())
                if isinstance(j, dict):
                    found = []
                    _walk_streams(j, found)
                    for c in found:
                        u = _clean_stream(c, b2)
                        if u and _stream_kind(u):
                            kind, play, play_page = _stream_kind(u), u, b2
                            break
                    if kind != "empty":
                        break
        if kind == "empty":
            if not iframe:
                iframes = _find_iframes(h, b)
                if iframes:
                    iframe = iframes[0]
            for ifr in ([iframe] if iframe else [])[:1]:
                try:
                    b2, h2 = self.sess.get(ifr, ref=b)
                except Exception:
                    continue
                k2, p2, f2 = _extract_direct(h2, b2)
                if k2 in ("m3u8", "mp4", "magnet"):
                    kind, play, frm, play_page = k2, p2, f2, b2
                    break
            if kind == "empty" and iframe:
                kind, play, play_page = "iframe", iframe, iframe
        episodes = None
        if self.id == "cdj":
            dm = re.search(r"data-drama-id=[\"'](\d+)", h)
            pm = re.search(r'<script id="player-data"[^>]*>(.*?)</script>', h, re.S)
            seqs = []
            if pm:
                try:
                    seqs = [str(x.get("seq")) for x in json.loads(pm.group(1)) if x.get("seq")]
                except Exception:
                    seqs = []
            if dm and seqs:
                host = b.rstrip("/")
                episodes = [("第%s集" % s, "cdj://%s/%s/%s" % (host, dm.group(1), s)) for s in seqs]
        if episodes is None and self.id == "tangxin" and re.search(r"/artists/[^/]+/", url):
            vids = _parse_list(h, b)
            if len(vids) >= 3:
                episodes = [(x["title"], x["url"]) for x in vids[:30]]
        if episodes is None and kind == "empty":
            pth = urllib.parse.urlparse(url).path
            if re.fullmatch(r"/(?:categories|channels)/[^/]+/", pth):
                vids = [x for x in _parse_list(h, b) if "/videos/" in x["url"]]
                if len(vids) >= 3:
                    episodes = [(x["title"], x["url"]) for x in vids[:30]]
        if not title:
            title = "%s · %s" % (self.name, url.rstrip("/").rsplit("/", 1)[-1])
        ret = {"title": title, "pic": pic, "content": content,
               "kind": "episodes" if episodes else kind, "play": play, "from": frm, "page": b,
               "play_page": play_page, "iframe": iframe, "episodes": episodes}
        try:
            import time as _tm2
            if ret["kind"] in ("m3u8", "mp4", "magnet", "iframe", "episodes"):
                self._detail_cache[url] = (_tm2.time(), dict(ret))
        except Exception:
            pass
        return ret

    def play_full(self, url):
        if _s(url).startswith("cdj://"):
            try:
                _p = _s(url)[6:].split("/")
                host = "/".join(_p[:3]) if _p[0] in ("http:", "https:") else _p[0]
                if not host.startswith("http"):
                    host = "https://" + host
                rest = [x for x in _p if x and x not in ("http:", "https:") and "://" not in x]
                did_, seq_ = rest[-2], rest[-1]
                import uuid as _uuid
                view = _uuid.uuid4().hex
                _b, j = self.sess.post(host + "/api/play",
                                       {"drama_id": int(did_), "seq": seq_, "view": view},
                                       ref=host + "/", timeout=15)
                if isinstance(j, dict) and j.get("ok") and j.get("src"):
                    src = _abs(host + "/", j["src"])
                    hd = {"User-Agent": self.ua, "Referer": host + "/", "Accept": "*/*"}
                    try:
                        parts = []
                        for c in self.sess._session.cookies:
                            if host.split("://")[-1] in (c.domain or "") or (c.domain or "").lstrip(".") in host:
                                parts.append("%s=%s" % (c.name, c.value))
                        if parts:
                            hd["Cookie"] = "; ".join(parts)
                    except Exception:
                        pass
                    return "m3u8", src, hd, host + "/", ""
            except Exception:
                pass
            return "empty", "", {}, url, ""
        d = self.detail(url)
        kind = d.get("kind") or "empty"
        u = _s(d.get("play"))
        pp = d.get("play_page") or url
        if kind in ("m3u8", "mp4"):
            hd = {"User-Agent": self.ua, "Referer": pp,
                  "Origin": self.base, "Accept": "*/*"}
            return kind, u, hd, pp, ""
        if kind == "magnet":
            return kind, u, {}, pp, ""
        if kind == "iframe":
            return kind, u, {}, pp, u
        return "empty", "", {}, pp, d.get("iframe") or ""

    def play(self, url):
        kind, u, hd, pp, ifr = self.play_full(url)
        if kind in ("m3u8", "mp4", "magnet") and u:
            return u, hd
        raise RuntimeError("no playable stream found")

    def search(self, key):
        key = _s(key)
        if not key:
            return []
        q = urllib.parse.quote(key)
        tpls = self.opt.get("search") or (
            "/index.php/vod/search.html?wd=%s",
            "/index.php/vod/search.html?searchword=%s",
            "/vodsearch/%s----------.html",
            "/index.php/vod/search/wd/%s.html",
            "/search?q=%s",
            "/search/?q=%s",
        )
        for t in tpls:
            try:
                b, h = self.sess.get(self.base + (t % q))
            except Exception:
                continue
            items = _parse_list(h, b)
            if items:
                return items
        return []




SITES = [
    ("xyxss",    "校园性事",    "https://48m.xyxss.cyou",   {}),
    ("xslrxx",   "性色撩人",    "https://aeg.xslrxx.mom",   {}),
    ("guochan",  "黄果短剧",    "https://guochan01.sbs",    {}),
    ("lichun",   "丽春院",      "https://lichunyuan1.buzz", {}),
    ("luyitian", "撸一天",      "https://luyitian.com",     {}),
    ("ririlu",   "日日撸",      "https://ririlu.cc",        {}),
    ("weimei",   "唯美精品",    "https://shiresm.lol",      {}),
    ("toptv",    "TOPTV",       "https://toptv15.cyou",     {}),
    ("llsp",     "榴莲视频",    "https://www.llsp.me",      {}),
    ("xqxq1",    "热播福利",    "https://xqxq1.cc",         {}),
    ("youavhub", "Youavhub",    "https://youavhub.com",     {}),
    ("missav",   "MissAV",      "https://missav.app",       {}),
    ("yese",     "夜色A片網",   "https://yese.co",          {}),
    ("av2",      "2AV",         "https://www.2av.com",
     {"cats": [("https://www.2av.com/", "最新"),
               ("https://www.2av.com/video/", "全部影片")]}),
    ("dsd",      "懂色帝",      "https://www.dsd.com.se",   {}),
    ("hsck",     "黄色仓库",    "https://hsck.cc",          {}),
    ("javbobo",  "JavBobo",     "https://javbobo.com",      {}),
    ("tangxin",  "糖心Vlog",    "https://tangxinvlog.pro",
     {"cats": [("https://tangxinvlog.pro/videos/", "最新"),
               ("https://tangxinvlog.pro/artists/", "博主")]}),
    ("javbus",   "JavBus",      "https://www.javbus.com",   {}),
    ("javdb",    "JavDB",       "https://javdb.com",        {}),
    ("rb91",     "91热爆",      "https://www.91rb.net",     {}),
    ("pornhub",  "PornHub",     "https://cn.pornhub.com",  {"ua": PC_UA}),
    ("hsex",     "好色TV",      "https://hsex.tv",
     {"timeout": 30, "cats": [("https://hsex.tv/list-1.htm", "最新"),
               ("https://hsex.tv/top7_list-1.htm", "周榜"),
               ("https://hsex.tv/top_list-1.htm", "月榜"),
               ("https://hsex.tv/5min_list-1.htm", "5分钟"),
               ("https://hsex.tv/long_list-1.htm", "10分钟+"),
               ("https://hsex.tv/hot_list-1.htm", "最热")]}),
    ("cdj",      "超短剧",      "https://www.shanekids.com",
     {"ua": PC_UA, "cats": [("https://www.shanekids.com/", "最新"),
               ("https://www.shanekids.com/explore", "探索"),
               ("https://www.shanekids.com/explore?sort=new", "最新上架"),
               ("https://www.shanekids.com/rank", "排行榜")]}),
]

_SOURCES = None
_LOCK = threading.Lock()


def _sources():
    global _SOURCES
    if _SOURCES is None:
        with _LOCK:
            if _SOURCES is None:
                _SOURCES = [_Src(*x) for x in SITES]
    return _SOURCES


def _find(sid):
    for s in _sources():
        if s.id == sid:
            return s
    return None


def _tid(sid, cat=""):
    return "%s::c::%s" % (sid, _b64(cat))


def _did(sid, url):
    return "%s::d::%s" % (sid, _b64(url))


def _tid_split(tid):
    sid, _, b = _s(tid).partition("::c::")
    return sid, _ub64(b)


def _did_split(did):
    sid, _, b = _s(did).partition("::d::")
    return sid, _ub64(b)


def _item(sid, url, title, pic="", remark=""):
    return {"vod_id": _did(sid, url),
            "vod_name": _txt(title)[:120] or "未命名",
            "vod_pic": _s(pic),
            "vod_remarks": _s(remark) or "在线",
            "vod_content": ""}


def _err_item(sid, name, msg):
    return _item(sid, "ERR::" + name, "【%s】%s" % (name, msg), "", "点我看原因")


def _validate_stream(u, hd):
    try:
        import requests as _rq
        r = _rq.get(u, timeout=7, verify=False,
                    headers={**dict(hd or {}), "Range": "bytes=0-1023"})
        raw = r.content[:2048] if r.content else b""
        if r.status_code in (401, 403, 404, 410):
            return False
        if u.lower().split("?")[0].endswith(".m3u8"):
            if b"#EXTM3U" in raw or b"#EXTINF" in raw:
                return True
            return r.status_code in (200, 206)
        return r.status_code in (200, 206, 302)
    except Exception:
        pass
    try:
        req = urllib.request.Request(u, headers=dict(hd or {}))
        req.add_header("Range", "bytes=0-1023")
        ctx = ssl._create_unverified_context()
        r = urllib.request.urlopen(req, timeout=7, context=ctx)
        raw = r.read(2048)
        if u.lower().split("?")[0].endswith(".m3u8"):
            if b"#EXTM3U" in raw or b"#EXTINF" in raw:
                return True
            return r.status in (200, 206)
        return r.status in (200, 206, 302)
    except urllib.error.HTTPError as e:
        return e.code not in (401, 403, 404, 410)
    except Exception:
        return True

# ============================================================
# Spider
# ============================================================

class Spider(_BaseSpider):

    def getName(self):
        return "聚果鉴"

    def getDependence(self):
        return []

    def action(self, action=None):
        return {}

    def init(self, extend=""):
        self.extend = _s(extend)
        return {}

    def destroy(self):
        return {}

    def isVideoFormat(self, url):
        u = _s(url).lower()
        return any(k in u for k in (".m3u8", ".mp4", ".flv", ".mkv", ".ts"))

    def manualVideoCheck(self):
        return False

    def localProxy(self, param=None):
        return [404, "text/plain; charset=utf-8", b"no proxy"]

    proxy = localProxy


    def _cats(self, src):
        try:
            c = src.categories()
            if c:
                return c[:40]
        except Exception:
            pass
        return []

    def homeContent(self, filter=False):
        srcs = _sources()
        cats_map = {}
        if ThreadPoolExecutor:
            ex = None
            try:
                ex = ThreadPoolExecutor(max_workers=12)
                fut = {ex.submit(self._cats, s): s for s in srcs}
                done, _ = _wait(fut.keys(), 30)
                for f in fut:
                    s = fut[f]
                    if f in done and not f.exception():
                        cats_map[s.id] = f.result()
                    else:
                        cats_map.setdefault(s.id, [])
            except Exception:
                cats_map = {}
            finally:
                _shut(ex)
        classes, filters = [], {}
        for s in srcs:
            tid = _tid(s.id)
            classes.append({"type_id": tid, "type_name": s.name})
            opts = [{"n": "全部", "v": _b64(s.base + "/")}]
            seen = set()
            for cu, cn in (cats_map.get(s.id) or []):
                if cn in seen:
                    continue
                seen.add(cn)
                opts.append({"n": cn, "v": _b64(cu)})
            if len(opts) > 1:
                filters[tid] = [{"key": "cat", "name": "分类", "value": opts}]
        vods = []
        try:
            first = srcs[0]
            vods = [_item(first.id, x["url"], x["title"], x["pic"]) for x in first.home_list()[:30]]
        except Exception:
            pass
        return {"class": classes, "list": vods, "filters": filters}

    def homeVideoContent(self):
        try:
            first = _sources()[0]
            return {"list": [_item(first.id, x["url"], x["title"], x["pic"])
                             for x in first.home_list()[:30]]}
        except Exception:
            return {"list": []}


    def categoryContent(self, tid, pg="1", filter=False, extend=None):
        sid, cat = _tid_split(tid)
        src = _find(sid)
        if not src:
            return {"list": [], "page": 1, "pagecount": 1, "limit": 20, "total": 0}
        try:
            pg = max(1, int(pg))
        except Exception:
            pg = 1
        ext = extend
        if isinstance(ext, str) and ext:
            try:
                ext = json.loads(ext)
            except Exception:
                ext = {}
        if isinstance(ext, dict):
            v = _s(ext.get("cat"))
            if v:
                cat = _ub64(v) or v
        if not cat:
            cat = src.base + "/"
        try:
            items = src.cat(cat, pg)
        except Exception as e:
            items = []
            src.last_err = "%s" % _s(e)[:80]
        if not items and pg == 1:
            items = [_err_item(src.id, src.name, src.last_err or "这站这会儿没返回数据")]
            return {"list": items, "page": 1, "pagecount": 1, "limit": 20, "total": 1}
        vods = [_item(src.id, x["url"], x["title"], x["pic"]) for x in items]
        more = len(vods) >= 8
        return {"list": vods, "page": pg,
                "pagecount": MAX_PAGE if more else pg,
                "limit": 20, "total": 999999 if more else len(vods)}


    def detailContent(self, ids):
        did = ids[0] if isinstance(ids, (list, tuple)) and ids else _s(ids)
        sid, url = _did_split(did)
        src = _find(sid)
        if not src:
            return {"list": []}
        if url.startswith("ERR::"):
            name = url[5:]
            s = _find(sid)
            return {"list": [{"vod_id": did, "vod_name": "%s 这会儿没数据" % name,
                              "vod_pic": "", "vod_remarks": "点开看原因",
                              "vod_content": (s.last_err if s else "") or "这站当前没返回数据"}]}
        try:
            d = src.detail(url)
        except Exception as e:
            return {"list": [{"vod_id": did, "vod_name": "加载失败",
                              "vod_pic": "", "vod_remarks": "错误",
                              "vod_content": "原因：%s" % _s(e)[:120],
                              "vod_play_from": src.name,
                              "vod_play_url": "\u55c5\u63a2\u64ad\u653e$%s" % _did("sniff", url)}]}
        kind = d.get("kind") or "empty"
        eps = d.get("episodes")
        if eps:
            play_url = "#".join("%s$%s" % (t, _did(sid, u)) for t, u in eps)
            return {"list": [{
                "vod_id": did,
                "vod_name": d.get("title") or "未命名",
                "vod_pic": d.get("pic") or "",
                "vod_remarks": "共%d集" % len(eps),
                "vod_content": (d.get("content") or "") + ("\n[%s]" % src.name if src.name else ""),
                "vod_play_from": src.name,
                "vod_play_url": play_url,
            }]}
        if kind in ("m3u8", "mp4"):
            play_url = "\u64ad\u653e$%s" % _did(sid, "stream::" + _s(d.get("play")) + "::" + _s(d.get("page") or url))
        elif kind in ("magnet",):
            play_url = "\u64ad\u653e$%s" % _did(sid, url)
        elif kind == "iframe":
            target = d.get("play") or url
            play_url = "\u55c5\u63a2\u64ad\u653e$%s" % _did("sniff", target)
        else:
            play_url = "\u55c5\u63a2\u64ad\u653e$%s" % _did("sniff", url)
        return {"list": [{
            "vod_id": did,
            "vod_name": d.get("title") or "未命名",
            "vod_pic": d.get("pic") or "",
            "vod_remarks": {"m3u8": "直链", "mp4": "直链", "magnet": "磁力",
                            "iframe": "嗅探"}.get(kind, "无直链"),
            "vod_content": (d.get("content") or "") + ("\n[%s]" % src.name if src.name else ""),
            "vod_play_from": src.name,
            "vod_play_url": play_url,
        }]}

    def _search_one(self, src, key):
        try:
            return src.search(key) or []
        except Exception:
            return []

    def searchContent(self, key, quick=False, pg="1"):
        key = _s(key)
        if not key:
            return {"list": []}
        try:
            if int(pg) > 1:
                return {"list": []}
        except Exception:
            pass
        srcs = _sources()
        out, seen = [], set()
        if ThreadPoolExecutor:
            ex = None
            try:
                ex = ThreadPoolExecutor(max_workers=12)
                fut = {ex.submit(self._search_one, s, key): s for s in srcs}
                done, _pending = _wait(fut.keys(), SEARCH_DEADLINE)
                for f in done:
                    s = fut[f]
                    if f.exception():
                        continue
                    for v in (f.result() or [])[:10]:
                        if v["url"] in seen:
                            continue
                        seen.add(v["url"])
                        out.append(_item(s.id, v["url"],
                                         "[%s] %s" % (s.name, v["title"]), v["pic"]))
                        if len(out) >= 200:
                            break
                    if len(out) >= 200:
                        break
            except Exception:
                pass
            finally:
                _shut(ex)
        return {"list": out}


    def playerContent(self, flag, id, vipFlags=None):
        sid, url = _did_split(id)
        if not url:
            return {"parse": 0, "playUrl": "", "url": "", "header": {}}
        if _s(url).startswith("stream::"):
            _parts = _s(url)[8:].rsplit("::", 1)
            _stream = _parts[0]
            _ref = _parts[1] if len(_parts) > 1 else ""
            _src = _find(sid)
            _hd = {"User-Agent": (_src.ua if _src else MOB_UA),
                   "Referer": _ref, "Origin": (_src.base if _src else ""), "Accept": "*/*"}
            if _stream_kind(_stream):
                return {"parse": 0, "playUrl": "", "url": _stream, "header": _hd}
            return {"parse": 1, "playUrl": "", "url": _ref or _stream, "header": {}}
        if sid == "sniff":
            src = None
            for s in _sources():
                if url.startswith(s.base):
                    src = s
                    break
            if src:
                try:
                    kind, u, hd, pp, ifr = src.play_full(url)
                    if kind in ("m3u8", "mp4") and u and _validate_stream(u, hd):
                        return {"parse": 0, "playUrl": "", "url": u, "header": dict(hd)}
                    if kind == "magnet" and u:
                        return {"parse": 0, "playUrl": "", "url": u, "header": {}}
                    if kind == "iframe" and u:
                        return {"parse": 1, "playUrl": "", "url": u, "header": {}}
                except Exception:
                    pass
            return {"parse": 1, "playUrl": "", "url": url, "header": {}}
        src = _find(sid)
        if not src:
            return {"parse": 1, "playUrl": "", "url": url, "header": {}}
        try:
            kind, u, hd, pp, ifr = src.play_full(url)
        except Exception:
            return {"parse": 1, "playUrl": "", "url": url, "header": {}}
        if kind in ("m3u8", "mp4") and u:
            if _validate_stream(u, hd):
                return {"parse": 0, "playUrl": "", "url": u, "header": dict(hd or {})}
            return {"parse": 1, "playUrl": "", "url": pp or url, "header": {}}
        if kind == "magnet" and u:
            return {"parse": 0, "playUrl": "", "url": u, "header": {}}
        if kind == "iframe" and u:
            return {"parse": 1, "playUrl": "", "url": u, "header": {}}
        return {"parse": 1, "playUrl": "", "url": pp or url, "header": {}}

# ============================================================

# ============================================================

def selftest(only=None):
    import sys
    ok = 0
    tot = 0
    for s in _sources():
        if only and s.id not in only:
            continue
        tot += 1
        line = ["-" * 8, "%-10s %s" % (s.id, s.base)]
        try:
            cats = s.categories()
            line.append("  分类 %d" % len(cats))
            items = s.home_list()
            line.append("  首页条目 %d" % len(items))
            if items:
                line.append("   例：%s" % items[0]["title"][:40])
                cat_page = cats[0][0] if cats else s.base + "/"
                ci = s.cat(cat_page, 1)
                line.append("  分类页条目 %d" % len(ci))
                d = s.detail(items[0]["url"])
                line.append("  详情：%s | %s" % (d["title"][:30], d["kind"]))
                if d["play"]:
                    line.append("        %s" % d["play"][:110])
                if d["kind"] in ("m3u8", "mp4"):
                    ok += 1
            else:
                line.append("  ! %s" % (s.last_err or "无条目"))
        except Exception as e:
            line.append("  ! 异常 %s" % _s(e)[:80])
        print("\n".join(line), flush=True)
    print("=" * 30)
    print("可直链播放的站：%d / %d" % (ok, tot))


if __name__ == "__main__":
    import sys
    selftest(sys.argv[1:] or None)
