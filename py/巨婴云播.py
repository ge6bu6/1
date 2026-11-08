import re, json, base64
try:
    import requests as _requests
except Exception:
    _requests = None


def _html_unescape(s):
    import html as _h
    return _h.unescape(s) if s else s


class Spider:
    def __init__(self):
        self.site = "https://vhd823jr7ypw.ngyouxi.com"
        self.name = "巨婴云播"
        self.header = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; SM-S9080) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Referer": self.site,
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        self.s = self.session = self.sess = _requests.Session() if _requests else None
        self._extend = {}
        self._home = None
        self._cats_cache = None
        self._pc_cache = {}

    def getDependence(self):
        return []

    def manualVideoCheck(self):
        return False

    def isVideoFormat(self, url):
        if not url:
            return False
        u = str(url).lower()
        return u.endswith((".m3u8", ".mp4", ".flv", ".mkv", ".ts", ".avi")) or "m3u8" in u

    def destroy(self):
        pass

    def action(self, action):
        return {}

    def _get(self, url, referer=None):
        h = dict(self.header)
        if referer:
            h["Referer"] = referer
        if self.s is not None:
            try:
                r = self.s.get(url, headers=h, timeout=12, allow_redirects=True)
                if r.status_code < 400:
                    return r.text
            except Exception:
                pass
        try:
            import urllib.request
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=12) as resp:
                return resp.read().decode("utf-8", "ignore")
        except Exception:
            return ""

    def _u(self, u):
        if not u:
            return u
        u = u.strip()
        if u.startswith("//"):
            return "https:" + u
        if u.startswith("http"):
            return u
        if u.startswith("/"):
            m = re.match(r"(https?://[^/]+)", self.site)
            return (m.group(1) if m else self.site) + u
        return self.site.rstrip("/") + "/" + u.lstrip("/")

    def _dec_page(self, raw):
        if not raw:
            return ""
        try:
            from urllib.parse import unquote
            m = re.search(r'var a="([^"]+)"', raw)
            if not m:
                return raw
            s = unquote(m.group(1))
            b = base64.b64decode(s)
            return unquote(b.decode("utf-8", "ignore"))
        except Exception:
            return raw

    def _dec_api(self, raw):
        try:
            from urllib.parse import unquote
            j = json.loads(raw)
            c = j.get("content", "")
            if not c:
                return ""
            b = base64.b64decode(c)
            return unquote(b.decode("utf-8", "ignore"))
        except Exception:
            return ""

    def _get_dec(self, url, referer=None):
        return self._dec_page(self._get(url, referer=referer))

    def _home_html(self):
        if self._home is None:
            self._home = self._get_dec(self.site)
        return self._home or ""

    def _cats(self):
        if self._cats_cache is not None:
            return self._cats_cache
        html = self._home_html()
        out = []
        seen = set()
        for m in re.finditer(r'<a[^>]+href="/list/video/(CC[0-9A-Za-z]+)\.html"[^>]*>(.*?)</a>', html, re.S):
            cid = m.group(1)
            name = _html_unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
            if not name or name.startswith("更多") or len(name) > 16:
                continue
            if cid in seen:
                continue
            seen.add(cid)
            out.append({"type_id": cid, "type_name": name})
        self._cats_cache = out
        return out

    GROUPS = [("精选推荐", 0, 6), ("国产AV", 6, 10), ("日本AV", 16, 10), ("欧美AV", 26, 4), ("H动漫", 30, 6), ("国产精品组", 36, 7), ("影视组", 43, 6)]

    def _group_classes(self):
        return [{"type_id": "g:" + str(i), "type_name": n} for i, (n, _, _) in enumerate(self.GROUPS)]

    def _group_filters(self):
        flat = self._cats()
        fl = {}
        for i, (n, st, cnt) in enumerate(self.GROUPS):
            subs = flat[st:st + cnt]
            if not subs:
                continue
            fl["g:" + str(i)] = [{"key": "sub", "name": "分类", "value": [{"n": c["type_name"], "v": c["type_id"]} for c in subs]}]
        return fl

    def _resolve_cid(self, tid, extend=None):
        tid = str(tid).strip()
        m = re.search(r'(CC[0-9A-Za-z]+)', tid)
        if m:
            return m.group(1)
        gm = re.match(r'g:(\d+)', tid)
        if gm:
            gi = int(gm.group(1))
            flat = self._cats()
            if 0 <= gi < len(self.GROUPS):
                _, st, cnt = self.GROUPS[gi]
                subs = flat[st:st + cnt]
                if subs:
                    sel = None
                    if isinstance(extend, dict):
                        sel = extend.get("sub")
                    if sel:
                        sm = re.search(r'(CC[0-9A-Za-z]+)', str(sel))
                        if sm:
                            return sm.group(1)
                    return subs[0]["type_id"]
        return tid

    def _items(self, html):
        out = []
        seen = set()
        if not html:
            return out
        for bm in re.finditer(r'<a[^>]*class=["\']?label vlink["\']?[^>]*>([\s\S]*?)</a>', html):
            block = bm.group(0)
            hm = re.search(r'href=["\']?(/video/[^"\'\s>]+)["\']?', block)
            im = re.search(r'<img[^>]+src=["\']?([^"\'\s>]+)["\']?', block)
            tm = re.search(r'<div[^>]*class=["\']?title["\']?>([^<]+)</div>', block)
            if not (hm and tm):
                continue
            vid = self._u(hm.group(1))
            if vid in seen:
                continue
            seen.add(vid)
            out.append({
                "vod_id": vid,
                "vod_name": _html_unescape(tm.group(1)).strip(),
                "vod_pic": self._u(im.group(1)) if im else "",
                "vod_remarks": "",
            })
        return out

    def init(self, extend=""):
        self._extend = {}
        if isinstance(extend, dict):
            self._extend = extend
        elif isinstance(extend, str) and extend.strip():
            try:
                e = json.loads(extend)
                if isinstance(e, dict):
                    self._extend = e
            except Exception:
                pass

    def homeContent(self, filter=None):
        cats = self._group_classes()
        filters = self._group_filters()
        vod_list = self._items(self._home_html())
        return {"class": cats, "filters": filters, "list": vod_list}

    def homeVideoContent(self):
        return {"list": self._items(self._home_html())}

    def categoryContent(self, tid, pg=1, filter=None, extend=None):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        tid = str(tid).strip()
        cid = self._resolve_cid(tid, extend)
        list_url = self.site.rstrip("/") + "/list/video/" + cid + ".html"
        if pg == 1:
            html = self._get_dec(list_url)
            if not html:
                return {"list": [], "page": pg, "pagecount": 1, "limit": 20, "total": 0}
            vod_list = self._items(html)
            pagecount = 1
            pm = re.search(r'list_page\s*=\s*"(\d+)"', html)
            if pm:
                pagecount = int(pm.group(1))
            elif len(vod_list) >= 20:
                pagecount = pg + 1
            self._pc_cache[cid] = pagecount
            return {"list": vod_list, "page": pg, "pagecount": pagecount, "limit": 20, "total": pagecount * 20}
        api_url = self.site.rstrip("/") + "/xapi/list/loadmore/" + cid + "/video/" + str(pg)
        raw = self._get(api_url, referer=list_url)
        html = self._dec_api(raw)
        if not html:
            return {"list": [], "page": pg, "pagecount": 1, "limit": 20, "total": 0}
        vod_list = self._items(html)
        pagecount = self._pc_cache.get(cid, 0)
        if not pagecount:
            home = self._get_dec(list_url)
            pm = re.search(r'list_page\s*=\s*"(\d+)"', home) if home else None
            pagecount = int(pm.group(1)) if pm else (pg + 1 if len(vod_list) >= 20 else pg)
            self._pc_cache[cid] = pagecount
        return {"list": vod_list, "page": pg, "pagecount": pagecount, "limit": 20, "total": pagecount * 20}

    def detailContent(self, ids):
        vid = ids
        if isinstance(ids, (list, tuple)):
            vid = ids[0] if ids else ""
        vid = str(vid).strip()
        m = re.search(r'/video/([A-Za-z0-9]+)(?:/\d+)?\.html', vid)
        if m:
            vid = m.group(1)
        elif re.search(r'^[A-Za-z0-9]+$', vid):
            pass
        else:
            return {"list": []}
        url = self.site.rstrip("/") + "/video/" + vid + ".html"
        html = self._get_dec(url)
        if not html:
            return {"list": []}
        title = ""
        tm = re.search(r'<div class="video_info_box">\s*<div class="title">(.*?)</div>', html, re.S)
        if not tm:
            tm = re.search(r'<div class="title">(.*?)</div>', html, re.S)
        if tm:
            title = _html_unescape(re.sub(r"<[^>]+>", "", tm.group(1))).strip()
            title = re.sub(r"\s*-\s*第\d+集\s*$", "", title)
        pic = ""
        vurl = ""
        dm = re.search(r'id="dplayers"[^>]*>', html)
        if dm:
            tag = dm.group(0)
            pm = re.search(r'vpic="([^"]*)"', tag)
            if pm:
                pic = self._u(pm.group(1))
            um = re.search(r'vurl="([^"]*)"', tag)
            if um:
                vurl = _html_unescape(um.group(1)).strip()
        eps = []
        if vurl:
            parts = [p.strip() for p in vurl.split("#") if p.strip()]
            if len(parts) == 1:
                eps.append("正片$" + self._u(parts[0]))
            else:
                for i, p in enumerate(parts):
                    eps.append("第%d集$%s" % (i + 1, self._u(p)))
        return {"list": [{"vod_id": vid, "vod_name": title, "vod_pic": pic,
                          "vod_content": "", "vod_play_from": self.name,
                          "vod_play_url": "#".join(eps)}]}

    def searchContent(self, key, quick=False, pg="1"):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        try:
            from urllib.parse import quote
            url = self.site.rstrip("/") + "/xapi/search/data/" + str(pg) + "/video/" + quote(str(key))
        except Exception:
            return {"list": []}
        raw = self._get(url, referer=self.site + "/search.html")
        html = self._dec_api(raw)
        if not html:
            return {"list": []}
        return {"list": self._items(html)}

    def playerContent(self, flag, ids, vipFlags=None):
        url = ids
        if isinstance(ids, (list, tuple)):
            url = ids[0] if ids else ""
        url = str(url or "").strip()
        if not url:
            return {"parse": 0, "url": "", "header": dict(self.header)}
        if not url.startswith("http"):
            url = self._u(url)
        u = url.lower()
        if u.endswith((".m3u8", ".mp4", ".flv", ".mkv", ".ts", ".avi")) or "m3u8" in u:
            return {"parse": 0, "url": url, "header": dict(self.header)}
        m = re.search(r'/video/([A-Za-z0-9]+)(?:/(\d+))?\.html', url)
        if not m:
            return {"parse": 0, "url": "", "header": dict(self.header)}
        vid = m.group(1)
        ep = int(m.group(2)) if m.group(2) else 1
        html = self._get_dec(self.site.rstrip("/") + "/video/" + vid + ".html")
        dm = re.search(r'id="dplayers"[^>]*vurl="([^"]*)"', html) if html else None
        if not dm:
            return {"parse": 0, "url": "", "header": dict(self.header)}
        parts = [p.strip() for p in _html_unescape(dm.group(1)).split("#") if p.strip()]
        if not parts:
            return {"parse": 0, "url": "", "header": dict(self.header)}
        idx = ep - 1 if 0 < ep <= len(parts) else 0
        return {"parse": 0, "url": self._u(parts[idx]), "header": dict(self.header)}

    def localProxy(self, param):
        u = param.get("url", "") if isinstance(param, dict) else ""
        if not u:
            return [403, "text/plain", b"", None]
        h = dict(self.header)
        if self.s is not None:
            try:
                r = self.s.get(u, headers=h, timeout=15)
                return [200, r.headers.get("Content-Type", "application/octet-stream"), r.content, None]
            except Exception:
                pass
        try:
            import urllib.request
            req = urllib.request.Request(u, headers=h)
            with urllib.request.urlopen(req, timeout=15) as resp:
                return [200, resp.headers.get("Content-Type", "application/octet-stream"), resp.read(), None]
        except Exception:
            return [403, "text/plain", b"", None]
