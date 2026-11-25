# -*- coding: utf-8 -*-
"""
SupJav (supjav.blog) —— TVBox / dr_py 爬虫源

站点结构（2026-11 实测）：
  列表   : /、/censored、/uncensored、/uncensored-leaked、/chinese、/amateur
           条目 = .box-item > .thumb > a[href='https://supjav.blog/video/{slug}']
           翻页 = ?page=N
  搜索   : /search?keyword=xxx&page=N              （表单字段名就是 keyword）
  详情   : /video/{slug}
           h1 标题、og:image 封面、.detail-item 里 Code/Release date/Runtime/
           Actresses/Genres，播放器是 iframe：
             https://upload18.to/play/index/{code}
  播放   : 该 iframe 页内嵌 window.PLAYER_CONFIG = {...}
           m3u8 在 helvid.com，带时效 token（约 30 分钟）与签名参数
           取流必须带 Accept + Sec-Fetch-Dest: empty（缺了 Cloudflare 直接 403）

所以本源策略：
  detailContent 把 iframe 地址当"集"下发给客户端；
  playerContent 现场去 iframe 页把 PLAYER_CONFIG.m3u8 抓出来，
  并把播放所需的请求头一并返回（TVBox 的 exo/ijk 会带到每个 m3u8/ts 请求）。
"""
import re
import json
import urllib.parse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3
from bs4 import BeautifulSoup

from base.spider import Spider

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


class Spider(Spider):
    name = "SupJav"
    base_url = "https://supjav.blog"
    site_url = "https://supjav.blog"
    timeout = 15

    headers = {
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://supjav.blog/",
    }

    # 分类：type_id 直接就是路径段
    CLASS_MAP = [
        ("censored", "Censored"),
        ("uncensored", "Uncensored"),
        ("uncensored-leaked", "Uncensored Leaked"),
        ("chinese", "Chinese AV"),
        ("amateur", "Amateur"),
    ]

    # 视频流需要的请求头（Cloudflare 按此判定，缺 Sec-Fetch-Dest 会 403）
    STREAM_HEADERS = {
        "User-Agent": _UA,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "cross-site",
    }

    # 可选：需要解析接口时填这里，如 "https://jx.xxx/player/?url="
    PARSE_API = ""

    # ---------------- 基础设施 ----------------
    def init(self, extend=""):
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.session.verify = False
        retry = Retry(total=2, backoff_factor=0.6,
                      status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=frozenset(["GET"]))
        adapter = HTTPAdapter(max_retries=retry, pool_connections=16, pool_maxsize=16)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def _fetch(self, url, referer=None, headers=None):
        try:
            hd = dict(headers or {})
            if referer:
                hd["Referer"] = referer
            resp = self.session.get(url, timeout=self.timeout, headers=hd or None)
            if resp.status_code != 200:
                print("[%s] HTTP %s %s" % (self.name, resp.status_code, url))
                return None
            resp.encoding = "utf-8"
            return resp.text
        except Exception as e:
            print("[%s] 请求失败 %s: %s" % (self.name, url, e))
            return None

    def _abs(self, url):
        if not url:
            return ""
        url = url.strip()
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("http"):
            return url
        if url.startswith("/"):
            return self.base_url + url
        return self.base_url + "/" + url

    # ---------------- 列表 ----------------
    def _parse_items(self, soup):
        out, seen = [], set()
        for box in soup.select(".box-item"):
            try:
                a = box.select_one(".thumb a[href]") or box.select_one("a[href]")
                if not a:
                    continue
                href = a.get("href") or ""
                # 首页/详情用 /video/{slug}；分类页用 video.php?slug={slug}
                m = (re.search(r"/video/([A-Za-z0-9_\-\.]+)", href)
                     or re.search(r"[?&]slug=([A-Za-z0-9_\-\.]+)", href))
                if not m:
                    continue
                slug = m.group(1)
                if slug in seen:
                    continue

                img = box.find("img")
                pic = ""
                if img:
                    pic = img.get("data-src") or img.get("src") or ""
                pic = self._abs(pic)

                d = box.select_one(".detail a") or a
                title = (d.get("title") if d else "") or (d.get_text(strip=True) if d else "")
                if not title and img:
                    title = img.get("alt", "")
                title = re.sub(r"\s+", " ", title or "").strip()
                if not slug or not title:
                    continue

                code = ""
                mc = re.match(r"([A-Za-z]+-\d+)", title)
                if mc:
                    code = mc.group(1).upper()

                seen.add(slug)
                out.append({
                    "vod_id": slug,
                    "vod_name": title,
                    "vod_pic": pic,
                    "vod_remarks": code,
                })
            except Exception:
                continue
        return out

    def homeContent(self, filter=False):
        result = {"class": [{"type_id": tid, "type_name": tname}
                            for tid, tname in self.CLASS_MAP],
                  "list": [], "filters": {}}
        html = self._fetch(self.base_url)
        if not html:
            return result
        result["list"] = self._parse_items(BeautifulSoup(html, "html.parser"))[:40]
        return result

    def homeVideoContent(self):
        return self.homeContent()

    # ---------------- 分类 ----------------
    def categoryContent(self, tid, pg, filter=False, extend=None):
        pg = int(pg) if str(pg).isdigit() else 1
        tid = str(tid).strip("/") or "censored"
        url = "%s/%s?page=%s" % (self.base_url, tid, pg)
        result = {"list": [], "page": pg, "pagecount": 1, "limit": 24, "total": 0}

        html = self._fetch(url)
        if not html:
            return result
        soup = BeautifulSoup(html, "html.parser")
        result["list"] = self._parse_items(soup)

        # 页数：取分页区最大 ?page=N
        maxpg = pg
        for a in soup.select("a[href*='page=']"):
            m = re.search(r"[?&]page=(\d+)", a.get("href") or "")
            if m:
                n = int(m.group(1))
                if pg <= n < 20000:
                    maxpg = max(maxpg, n)
        result["pagecount"] = maxpg if maxpg > pg else (pg + 1 if result["list"] else pg)
        result["total"] = len(result["list"]) * result["pagecount"]
        return result

    # ---------------- 详情 ----------------
    def detailContent(self, ids):
        vod_id = ids[0] if isinstance(ids, list) and ids else ids
        slug = str(vod_id).strip()
        m = re.search(r"/video/([A-Za-z0-9_\-\.]+)", slug)
        if m:
            slug = m.group(1)
        slug = slug.strip("/")
        if not slug:
            return {"list": []}

        url = "%s/video/%s" % (self.base_url, slug)
        html = self._fetch(url)
        if not html:
            return {"list": []}
        soup = BeautifulSoup(html, "html.parser")

        h1 = soup.find("h1")
        title = re.sub(r"\s+", " ", h1.get_text(" ", strip=True)) if h1 else slug

        pic = ""
        og = soup.find("meta", property="og:image")
        if og:
            pic = self._abs(og.get("content", ""))
        if not pic:
            img = soup.select_one(".thumb img") or soup.find("img")
            if img:
                pic = self._abs(img.get("data-src") or img.get("src") or "")

        desc = soup.select_one(".description p")
        content = re.sub(r"\s+", " ", desc.get_text(" ", strip=True)) if desc else ""

        # 元数据：Code / Release date / Runtime / Actresses
        code = year = area = actor = type_name = ""
        for row in soup.select(".detail-item > div"):
            spans = row.find_all("span", recursive=False)
            if len(spans) >= 2:
                k = spans[0].get_text(strip=True).rstrip(":：").lower()
                v = spans[1].get_text(" ", strip=True)
                if k.startswith("code"):
                    code = v
                elif "release" in k:
                    year = v
                elif "runtime" in k:
                    area = v
                elif "actress" in k or "actor" in k:
                    actor = v
        genres = [a.get_text(strip=True) for a in soup.select(".detail-item .genre a.tag")]
        type_name = ",".join(genres)

        # 播放：iframe → upload18.to/play/index/{code}
        play_url = ""
        ifr = soup.select_one("#player iframe[src]") or soup.find("iframe", src=True)
        if ifr:
            play_url = self._abs(ifr.get("src"))
        if not play_url and code:
            play_url = "https://upload18.to/play/index/%s" % code.lower()

        eps = "%s$%s" % (code or slug, play_url) if play_url else ""

        return {"list": [{
            "vod_id": slug,
            "vod_name": title,
            "vod_pic": pic,
            "vod_content": content,
            "vod_actor": actor,
            "vod_director": "",
            "vod_type": type_name,
            "vod_year": year,
            "vod_area": area,
            "vod_remarks": code,
            "vod_play_from": "SupJav" if eps else "",
            "vod_play_url": eps,
        }]}

    # ---------------- 搜索 ----------------
    def searchContent(self, key, quick=False, pg=1):
        pg = int(pg) if str(pg).isdigit() else 1
        result = {"list": [], "page": pg, "pagecount": 1, "limit": 24, "total": 0}
        key = (key or "").strip()
        if not key:
            return result
        url = "%s/search?keyword=%s&page=%s" % (
            self.base_url, urllib.parse.quote(key), pg)
        html = self._fetch(url)
        if not html:
            return result
        soup = BeautifulSoup(html, "html.parser")
        result["list"] = self._parse_items(soup)
        result["total"] = len(result["list"])
        result["pagecount"] = pg + 1 if result["list"] else pg
        return result

    # ---------------- 播放 ----------------
    @staticmethod
    def _json_after(html, marker):
        """取 marker（如 window.PLAYER_CONFIG = ）后面那个完整 JSON 对象。"""
        i = html.find(marker)
        if i < 0:
            return {}
        j = html.find("{", i)
        if j < 0:
            return {}
        depth, end = 0, -1
        for k, ch in enumerate(html[j:j + 300000], start=j):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = k + 1
                    break
        if end < 0:
            return {}
        blob = html[j:end]
        try:
            return json.loads(blob)
        except Exception:
            # 兜底：把 \u0026 / \/ 还原后再试
            try:
                return json.loads(blob.replace("\\u0026", "&").replace("\\/", "/"))
            except Exception:
                return {}

    def _resolve_m3u8(self, play_page):
        """从 upload18 播放器页取真实 m3u8。"""
        html = self._fetch(play_page, referer=self.base_url + "/")
        if not html:
            return ""
        # 1) 标准输出的 PLAYER_CONFIG
        cfg = self._json_after(html, "window.PLAYER_CONFIG")
        url = (cfg or {}).get("m3u8") or ""
        if not url:
            # 2) 正则兜底，直接找 m3u8 地址（含转义形式）
            m = re.search(r"""(?:m3u8|src)\s*[:=]\s*["'](https?://[^"']+?\.m3u8[^"']*)["']""", html)
            if m:
                url = m.group(1)
        if not url:
            m = re.search(r"""(https?://[^\s"'<>\\]+?\.m3u8[^\s"'<>]*)""", html)
            url = m.group(1) if m else ""
        return url.replace("\\u0026", "&").replace("\\/", "/")

    def playerContent(self, flag, id, vipFlags=None):
        play_page = self._abs(id)
        fallback_header = {
            "User-Agent": _UA,
            "Referer": self.base_url + "/",
            "Origin": "https://supjav.blog",
        }

        if not play_page:
            return {"parse": 1, "playUrl": "", "url": "", "header": fallback_header}

        m3u8 = self._resolve_m3u8(play_page)
        if m3u8:
            header = dict(self.STREAM_HEADERS)
            header["Referer"] = "https://upload18.to/"
            header["Origin"] = "https://upload18.to"
            return {"parse": 0, "playUrl": "", "url": m3u8, "header": header}

        if self.PARSE_API:
            return {"parse": 1,
                    "playUrl": self.PARSE_API + urllib.parse.quote(play_page, safe=""),
                    "url": play_page, "header": fallback_header}

        # 取不到流：把播放器页丢回去，至少能提示用户
        return {"parse": 1, "playUrl": "", "url": play_page, "header": fallback_header}

    def isVideoFormat(self, url):
        url = url or ""
        if re.search(r"\.(m3u8|mp4|ts|flv)(\?|$)", url, re.I):
            return True
        # SupJav 的流地址是 base64 路径：helvid.com/m/L3Yv...（解码后是 playlist.m3u8）
        return "helvid.com/m/" in url or "/playlist.m3u8" in url

    def manualVideoCheck(self):
        return False

    def localProxy(self, params):
        """
        可选调试通道：把带云盾校验的请求搬到这里发。
        params 形如 {"url": "..."}；返回 [状态码, Content-Type, 内容字节]。
        注意：只中继请求本身，不做播放列表改写，正式播放请让客户端直连 + header。
        """
        url = ""
        if isinstance(params, dict):
            url = params.get("url") or params.get("site") or ""
        if not url.startswith("http"):
            return None
        try:
            r = self.session.get(url, headers=self.STREAM_HEADERS, timeout=self.timeout)
            return [r.status_code, r.headers.get("Content-Type", "application/octet-stream"),
                    r.content]
        except Exception as e:
            print("[%s] localProxy 失败: %s" % (self.name, e))
            return None
