# -*- coding: utf-8 -*-
"""
绿果鉴 · 瑟瑟线  v2.0.0
TVBox Spider 单文件（模块加载，类名 Spider）

修复要点
  1. 列表解析改成「自适应」：从页面里自动识别列表项链接模式，
     不再用每个站写死的正则（写死正则正是上一版大面积没数据的主因）。
  2. 标题多路兜底：同一 URL 的所有 <a> 一起看 + title 属性 + h4/h6.title + img alt。
  3. 取流多路兜底：player_xxxx（含 base64/hex 加密）→ 相对 m3u8 → 绝对 m3u8
     → data-url → 播放页二次抓取 → iframe 交给壳。
  4. 站死了不再一片空白：返回一张说明卡，写清是哪一步断的。
"""

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

try:
    from base.spider import Spider as _BaseSpider
except Exception:
    class _BaseSpider(object):
        pass

try:
    from concurrent.futures import ThreadPoolExecutor
except Exception:
    ThreadPoolExecutor = None

__version__ = "2.0.0"

PC_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
MOB_UA = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")

TIMEOUT = 14
MAX_PAGE = 9999


# ============================================================
# 小工具
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
    def __init__(self, base, ua=None):
        self.base = _s(base).rstrip("/")
        self.ua = ua or MOB_UA
        self._ctx = None
        self._lock = threading.Lock()

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

    def get(self, url, ref=None, timeout=None, ua=None, tries=2):
        url = _abs(self.base + "/", url)
        last = None
        for n in range(max(1, tries)):
            try:
                hd = {"User-Agent": ua or self.ua,
                      "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                      "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                      "Accept-Encoding": "gzip, deflate",
                      "Referer": ref or (self.base + "/"),
                      "Connection": "close"}
                req = urllib.request.Request(url, headers=hd)
                r = urllib.request.urlopen(req, timeout=timeout or TIMEOUT,
                                           context=self._ssl())
                raw = r.read()
                enc = (r.headers.get("Content-Encoding") or "").lower()
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
                return r.geturl() or url, txt
            except Exception as e:
                last = e
                if n < tries - 1:
                    time.sleep(0.4 + 0.5 * n)
        raise last if last else RuntimeError("request failed")


# ============================================================
# 页面 → 列表项（自适应识别）
# ============================================================

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
    if len(t) < 3:
        return True
    if t in _JUNK_T or t.replace(" ", "") in _JUNK_T:
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
    """把 URL 归一成模式：长 id / 数字段都抹成占位符，用来聚合同类链接。"""
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


def _pic_of(blk, base):
    for p in (r'''data-original=["']([^"']+)''', r'''data-src=["']([^"']+)''',
              r'''data-echo=["']([^"']+)''', r'''data-lazy=["']([^"']+)''',
              r'''data-preview=["']([^"']+)''', r'''src=["']([^"']+)''',
              r'''style=["'][^"']*url\(([^)]+)\)'''):
        for m in re.finditer(p, blk, re.I):
            u = m.group(1).strip().strip("'\"")
            if not u or any(x in u.lower() for x in _BAD_IMG):
                continue
            return _abs(base, u)
    return ""


def _parse_list(h, base):
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
        nxt = items[i + 1]["s"] if i + 1 < len(items) else min(len(h), a["e"] + 1500)
        blk = h[max(0, a["s"] - 260):nxt]
        same = [items[j] for j in range(max(0, i - 6), min(len(items), i + 7)) if urls[j] == u]
        t = _title_of(a, blk, same)
        p = _pic_of(blk, base)
        if not t and not p:
            continue
        out.append({"url": u, "title": t, "pic": p, "blk": blk})
    # 大部分有标题时，丢掉无标题的残渣（轮播位那种）
    if out:
        got = sum(1 for x in out if x["title"])
        if got >= max(3, len(out) * 0.6):
            out = [x for x in out if x["title"]]
    return out


def _detect_cats(h):
    out, seen = [], set()
    for a in _anchors(h):
        u = a["u"]
        lu = u.lower()
        if not any(k in lu for k in ("/vodtype/", "/vod/show/", "/vodshow/",
                                     "/genre/", "/category/", "/class/",
                                     "/type/id/", "/arttype/")):
            continue
        t = a["t"] or a["a"]
        if _junk_title(t) or len(t) > 16:
            continue
        if t in seen:
            continue
        if not re.search(r"\d", u):
            continue
        seen.add(t)
        out.append((u, t))
    return out


# ============================================================
# 取流
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


def _play_of(h, base):
    """返回 (kind, url, from)；kind ∈ m3u8/mp4/iframe/empty"""
    # player_xxxx = {...}
    m = re.search(r"player_[a-z0-9]+\s*=\s*(\{.*?\})\s*[;<]", h, re.S)
    if m:
        try:
            j = json.loads(m.group(1).replace("\\/", "/"), strict=False)
        except Exception:
            j = {}
        if isinstance(j, dict):
            for k in ("url", "url_next", "video"):
                u = _s(j.get(k))
                if not u:
                    continue
                if _s(j.get("encrypt")) not in ("", "0", "null"):
                    u = _dec(u, j.get("encrypt")) or u
                u = _abs(base, u)
                if u.startswith("http") or u.startswith("magnet"):
                    kind = ("m3u8" if ".m3u8" in u else
                            "mp4" if ".mp4" in u else
                            "magnet" if u.startswith("magnet") else "iframe")
                    return kind, u, _s(j.get("from"))
    # data-url / data-video 直挂
    m = re.search(r'''data-(?:url|video|play|src)=["']([^"']{10,400})["']''', h, re.I)
    if m and (".m3u8" in m.group(1) or ".mp4" in m.group(1)):
        return ("m3u8" if ".m3u8" in m.group(1) else "mp4"), _abs(base, m.group(1)), ""
    # 绝对 m3u8
    m = re.search(r'''["']((?:https?:)?//[^"'\s\\<>]{8,300}?\.m3u8[^"'\s\\<>]*)["']''', h, re.I)
    if m:
        return "m3u8", _abs(base, m.group(1).replace("\\/", "/")), ""
    # 相对 m3u8
    m = re.search(r'''["'](/[^"'\s<>]{6,300}?\.m3u8[^"'\s<>]*)["']''', h, re.I)
    if m:
        return "m3u8", _abs(base, m.group(1)), ""
    # "url":"..." 兜底
    m = re.search(r'''["'](?:url|PlayUrl|playUrl|videoUrl)["']\s*[:=]\s*["']((?:https?:)?//[^"']{8,300}|/[^"']{8,300})["']''', h, re.I)
    if m:
        u = m.group(1)
        if not u.lower().endswith((".jpg", ".png", ".css", ".js", ".json")):
            return ("m3u8" if ".m3u8" in u else "iframe"), _abs(base, u), ""
    # iframe
    m = re.search(r'''<iframe[^>]+src=["']([^"']{12,400})["']''', h, re.I)
    if m:
        return "iframe", _abs(base, m.group(1)), ""
    return "empty", "", ""


def _find_play_link(h, base):
    for p in (r'''href=["']([^"']*?/vod/play/id/\d+/sid/\d+/nid/\d+/?[^"']*)["']''',
              r'''href=["']([^"']*?/vodplay/\d+-\d+-\d+/?[^"']*)["']''',
              r'''href=["']([^"']*?/vod/play/id/\d+/?[^"']*)["']''',
              r'''href=["']([^"']*?/play/\d+-\d+-\d+/?[^"']*)["']'''):
        m = re.search(p, h, re.I)
        if m:
            return _abs(base, m.group(1))
    return ""


def _page_url(u, pg):
    """给分类页拼第 pg 页地址。"""
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
# 站源
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
        ex.shutdown(wait=False, cancel_futures=True)
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

    @property
    def sess(self):
        if self._sess is None:
            self._sess = _Sess(self.base, self.ua)
        return self._sess

    # ---------- 分类 ----------
    def categories(self):
        if self.fixed_cats:
            return list(self.fixed_cats)
        if self._cats is not None:
            return self._cats
        self._cats = []
        try:
            b, h = self.sess.get(self.base + "/")
            got = _detect_cats(h)
            home = b.rstrip("/") + "/"
            self._cats = [(_abs(home, u), t) for u, t in got][:40]
        except Exception as e:
            self.last_err = "%s" % _s(e)[:80]
        return self._cats

    # ---------- 列表 ----------
    def home_list(self):
        try:
            b, h = self.sess.get(self.base + "/")
        except Exception as e:
            self.last_err = "首页打不开：%s" % _s(e)[:60]
            return []
        items = _parse_list(h, b)
        if not items:
            self.last_err = "首页没认出列表结构"
        return items

    def cat(self, cat_url, pg=1):
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
                return items
        if pg == 1:
            return self.home_list()
        return []

    # ---------- 详情 ----------
    def detail(self, url):
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
            pic = _pic_of(h[:15000], b)
        content = ""
        m = re.search(r'''<meta[^>]+name=["']description["'][^>]+content=["']([^"']{6,400})''', h, re.I)
        if m:
            content = _txt(m.group(1))[:240]
        kind, play, frm = _play_of(h, b)
        if kind == "empty":
            pl = _find_play_link(h, b)
            if pl and pl != b:
                try:
                    b2, h2 = self.sess.get(pl, ref=b)
                    kind, play, frm = _play_of(h2, b2)
                except Exception:
                    pass
        if not title:
            title = "%s · %s" % (self.name, url.rstrip("/").rsplit("/", 1)[-1])
        return {"title": title, "pic": pic, "content": content,
                "kind": kind, "play": play, "from": frm, "page": b}

    def play(self, url):
        d = self.detail(url)
        u = _s(d.get("play"))
        if not u:
            raise RuntimeError("这个站没给出可播地址（%s）" % (d.get("kind") or "空"))
        hd = {"User-Agent": self.ua, "Referer": d.get("page") or (self.base + "/")}
        return u, hd

    # ---------- 搜索 ----------
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


# ---------------- 站源清单 ----------------

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
    ("pornhub",  "PornHub",     "https://www.pornhub.com",  {"ua": PC_UA}),
    ("hsex",     "好色TV",      "https://hsex.tv",          {}),
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


# ============================================================
# Spider
# ============================================================

class Spider(_BaseSpider):

    def getName(self):
        return "绿果鉴·瑟瑟线 v2"

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

    def localProxy(self, param):
        return [404, "text/plain; charset=utf-8", b"no proxy"]

    proxy = localProxy

    # ---------- 首页 ----------
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
                ex = ThreadPoolExecutor(max_workers=10)
                fut = {ex.submit(self._cats, s): s for s in srcs}
                done, _ = _wait(fut.keys(), 8)
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

    # ---------- 分类 ----------
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

    # ---------- 详情 ----------
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
                              "vod_content": "原因：%s" % _s(e)[:120]}]}
        kind = d.get("kind") or "empty"
        if d.get("play") and kind != "empty":
            play_url = "播放$%s" % _did(sid, url)
        else:
            play_url = "嗅探播放$%s" % _did("sniff", url)
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

    # ---------- 搜索 ----------
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

    # ---------- 播放 ----------
    def playerContent(self, flag, id, vipFlags=None):
        sid, url = _did_split(id)
        if not url:
            return {"parse": 0, "playUrl": "", "url": "", "header": {}}
        if sid == "sniff":
            src = None
            for s in _sources():
                if url.startswith(s.base):
                    src = s
                    break
            try:
                if src:
                    d = src.detail(url)
                    u = _s(d.get("play"))
                    if u:
                        return {"parse": 0, "playUrl": "", "url": u,
                                "header": {"User-Agent": src.ua,
                                           "Referer": d.get("page") or src.base + "/"}}
            except Exception:
                pass
            return {"parse": 1, "playUrl": "", "url": url, "header": {}}
        src = _find(sid)
        if not src:
            return {"parse": 0, "playUrl": "", "url": "", "header": {}}
        try:
            u, hd = src.play(url)
        except Exception:
            return {"parse": 1, "playUrl": "", "url": url, "header": {}}
        if not u:
            return {"parse": 1, "playUrl": "", "url": url, "header": {}}
        if u.startswith("magnet:"):
            return {"parse": 0, "playUrl": "", "url": u, "header": {}}
        return {"parse": 0, "playUrl": "", "url": u, "header": dict(hd or {})}


# ============================================================
# 自检（命令行跑：python 本文件）
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
