# -*- coding: utf-8 -*-
"""
看日片 (com.kanripian.app) -> TVBox Python 爬虫
================================================
适配 TVBox / 影视仓 / OK影视 等支持 py 插件的壳子（base.spider 接口）。

特点：
  * 纯标准库实现，不依赖 requests / lxml；
  * 自动在 macapi1~3 的 .com/.top 六个域名间切换；
  * 首页 = 60+ 个片库（含日片库和常规影视库）；
  * 搜索 = 全库聚合（一次请求拿到所有库的结果）；
  * 详情/播放走统一索引，直出 m3u8，无需解析。

用法（壳子支持 py 插件时）：
  1. 把本文件放进壳子的 py 插件目录（或在配置里用 py:// 指向它）；
  2. 站点配置：{"key":"kanripian","name":"看日片","type":3,
                "api":"py://kanripian_spider.py","searchable":1,
                "quickSearch":1,"filterable":1}
  3. ext 可留空；也可写 JSON：{"home_db":"155","search_dbs":12}

若壳子不支持 py，可直接用同目录的 kanripian_api.py 起一个
maccms 接口，再用 type=1 添加 http://<手机IP>:8080/api.php/provide/vod/
"""

import gzip
import json
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

try:  # 宿主的 base.spider 存在时继承它，不存在也能独立跑
    from base.spider import Spider as _BaseSpider
except Exception:  # noqa: BLE001
    class _BaseSpider(object):
        pass

HOSTS = [
    "https://macapi1.com",
    "https://macapi2.com",
    "https://macapi3.com",
    "https://macapi1.top",
    "https://macapi2.top",
    "https://macapi3.top",
]

UA = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36")

HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Encoding": "gzip",
    "Referer": "https://macapi1.com/",
}

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def _clean(text):
    if not text:
        return ""
    text = TAG_RE.sub(" ", str(text))
    return WS_RE.sub(" ", text).strip()


class Spider(_BaseSpider):
    # ------------------------------------------------------------------ 基础
    def __init__(self):
        self.name = "看日片"
        self.extend = ""
        self._host = 0
        self._cache = {}
        self._db_cache = (0, [])

    def init(self, extend=""):
        self.extend = extend or ""
        try:
            self._cfg = json.loads(extend) if extend and extend.strip().startswith("{") else {}
        except Exception:  # noqa: BLE001
            self._cfg = {}
        return None

    def getName(self):
        return self.name

    # ------------------------------------------------------------------ HTTP
    def _http_json(self, path, params=None, timeout=15, cache=0):
        key = path + "?" + urllib.parse.urlencode(params or {})
        if cache:
            hit = self._cache.get(key)
            if hit and time.time() - hit[0] < cache:
                return hit[1]

        query = urllib.parse.urlencode(params) if params else ""
        last = None
        for i in range(len(HOSTS)):
            idx = (self._host + i) % len(HOSTS)
            url = HOSTS[idx] + path + (("?" + query) if query else "")
            try:
                req = urllib.request.Request(url, headers=HEADERS)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw = resp.read()
                    if resp.headers.get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
                data = json.loads(raw.decode("utf-8", "ignore"))
                self._host = idx
                if cache and isinstance(data, dict):
                    self._cache[key] = (time.time(), data)
                return data
            except Exception as exc:  # noqa: BLE001
                last = exc
                continue
        if last:
            pass
        return None

    # ------------------------------------------------------------------ 数据
    def _dbs(self, refresh=False):
        ts, data = self._db_cache
        if not refresh and data and time.time() - ts < 3600:
            return data
        j = self._http_json("/maccms/databases", timeout=15, cache=1800)
        dbs = []
        if isinstance(j, dict):
            for d in j.get("databases") or []:
                db = (d.get("dbname") or "").strip()
                if not db or not re.match(r"^[A-Za-z0-9_]+$", db):
                    continue
                if int(d.get("data_count") or 0) <= 0:
                    continue
                name = (d.get("name") or db).strip()
                count = int(d.get("data_count") or 0)
                dbs.append({
                    "db": db,
                    "name": name,
                    "count": count,
                    "type": d.get("type") or "av",
                })
        if not dbs:  # 兜底，接口挂了也能用
            dbs = [{"db": "155", "name": "155", "count": 0, "type": "av"}]
        dbs.sort(key=lambda x: -x["count"])
        self._db_cache = (time.time(), dbs)
        return dbs

    @staticmethod
    def _kind_of(group_key):
        return "movies" if str(group_key).startswith("wk:movies:") else "av"

    def _make_vid(self, item, db=""):
        gk = item.get("group_key") or (item.get("detail") or {}).get("id") or ""
        vid = item.get("vod_id") or ""
        return "%s|%s|%s" % (db, vid, gk)

    def _item(self, x, db=""):
        pic = x.get("vod_pic") or x.get("vod_pic_thumb") or x.get("vod_pic_original") or ""
        return {
            "vod_id": self._make_vid(x, db),
            "vod_name": _clean(x.get("vod_name")),
            "vod_pic": pic,
            "vod_remarks": _clean(x.get("vod_remarks") or x.get("vod_duration")),
            "vod_year": str(x.get("vod_year") or ""),
            "vod_area": _clean(x.get("vod_area")),
            "type_name": _clean(x.get("type_name")),
        }

    # ------------------------------------------------------------------ 接口
    def homeContent(self, filter=False):
        # 分类和首页推荐并发拉，减少首屏等待
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_db = pool.submit(self._dbs)
            f_home = pool.submit(self._http_json, "/maccms/meili/v2/list/av",
                                 {"page": 1}, 15, 600)
            try:
                dbs = f_db.result(timeout=20)
            except Exception:  # noqa: BLE001
                dbs = []
            try:
                j = f_home.result(timeout=20)
            except Exception:  # noqa: BLE001
                j = None

        classes = [
            {"type_id": "av", "type_name": "🔞 日片 最新"},
            {"type_id": "movies", "type_name": "🎬 影视 最新"},
        ]
        for d in dbs:
            label = d["name"]
            if d["count"]:
                label += "(%s)" % self._fmt_count(d["count"])
            classes.append({"type_id": d["db"], "type_name": label})

        home_list = []
        if isinstance(j, dict):
            home_list = [self._item(x) for x in (j.get("list") or [])]

        return {"class": classes, "filters": {}, "list": home_list}

    def homeVideoContent(self):
        j = self._http_json("/maccms/meili/v2/list/av", {"page": 1}, timeout=15, cache=600)
        if not isinstance(j, dict):
            return {"list": []}
        return {"list": [self._item(x) for x in (j.get("list") or [])]}

    def categoryContent(self, tid, pg, filter=False, extend=None):
        tid = str(tid or "").strip()
        extend = extend or {}
        try:
            page = max(1, int(pg))
        except Exception:  # noqa: BLE001
            page = 1

        if tid in ("av", "movies"):
            j = self._http_json("/maccms/meili/v2/list/" + tid,
                                {"page": page}, timeout=20, cache=300)
            db = ""
        else:
            params = {"page": page}
            cat = str(extend.get("cat") or "").strip()
            if cat.isdigit():
                params["t"] = cat
            j = self._http_json("/maccms/json/" + tid, params, timeout=20, cache=300)
            db = tid

        if not isinstance(j, dict):
            return {"page": page, "pagecount": 1, "limit": 20, "total": 0, "list": []}

        items = [self._item(x, db) for x in (j.get("list") or [])]
        total = int(j.get("total") or len(items))
        limit = int(j.get("limit") or 20)
        pagecount = int(j.get("pagecount") or 0) or max(1, (total + limit - 1) // limit)
        return {"page": page, "pagecount": pagecount, "limit": limit,
                "total": total, "list": items}

    def searchContent(self, key, quick=False, pg=1, category=""):
        try:
            page = max(1, int(pg))
        except Exception:  # noqa: BLE001
            page = 1
        key = (key or "").strip()
        if not key:
            return {"list": []}

        out, seen = [], set()

        def _one(kind):
            j = self._http_json("/maccms/meili/v2/search/" + kind,
                                {"wd": key, "page": page}, timeout=20, cache=120)
            return kind, j

        with ThreadPoolExecutor(max_workers=2) as pool:
            futs = [pool.submit(_one, k) for k in ("av", "movies")]
            for fut in futs:
                try:
                    kind, j = fut.result(timeout=25)
                except Exception:  # noqa: BLE001
                    continue
                if not isinstance(j, dict):
                    continue
                for x in j.get("list") or []:
                    gk = x.get("group_key") or ""
                    if gk and gk in seen:
                        continue
                    seen.add(gk)
                    out.append(self._item(x))

        return {"list": out[:60], "page": page}

    def detailContent(self, ids):
        try:
            raw = ids[0] if isinstance(ids, (list, tuple)) else ids
        except Exception:  # noqa: BLE001
            raw = ""
        raw = str(raw or "")
        parts = raw.split("|")
        db = parts[0] if len(parts) > 0 else ""
        vid = parts[1] if len(parts) > 1 else ""
        gk = parts[2] if len(parts) > 2 else ""

        j = None
        if gk:
            kind = self._kind_of(gk)
            j = self._http_json("/maccms/meili/v2/detail/" + kind,
                                {"group_key": gk}, timeout=20, cache=600)
        if (not isinstance(j, dict) or not j.get("list")) and db and vid:
            j = self._http_json("/maccms/json/" + db,
                                {"ac": "detail", "ids": vid}, timeout=20, cache=600)
        if not isinstance(j, dict) or not j.get("list"):
            return {"list": []}

        d = j["list"][0]
        play_from, play_url = self._normalize_plays(d)

        vod = {
            "vod_id": raw,
            "vod_name": _clean(d.get("vod_name")),
            "vod_pic": d.get("vod_pic") or d.get("vod_pic_thumb") or "",
            "vod_remarks": _clean(d.get("vod_remarks")),
            "vod_year": str(d.get("vod_year") or ""),
            "vod_area": _clean(d.get("vod_area")),
            "vod_lang": _clean(d.get("vod_lang")),
            "vod_actor": _clean(d.get("vod_actor")),
            "vod_director": _clean(d.get("vod_director")),
            "vod_content": _clean(d.get("vod_content") or d.get("vod_blurb")),
            "type_name": _clean(d.get("type_name")),
            "vod_play_from": play_from,
            "vod_play_url": play_url,
            "vod_score": str(d.get("vod_score") or ""),
            "vod_duration": str(d.get("vod_duration") or ""),
        }
        return {"list": [vod]}

    def playerContent(self, flag, id, vipFlags=None):
        url = str(id or "").strip()
        if url.startswith("//"):
            url = "https:" + url
        return {
            "parse": 0,
            "jx": 0,
            "url": url,
            "header": {"User-Agent": UA},
        }

    # ------------------------------------------------------------------ 工具
    @staticmethod
    def _normalize_plays(d):
        frm = str(d.get("vod_play_from") or "").strip()
        urls = str(d.get("vod_play_url") or "").strip()
        if not urls:
            return frm or "默认", ""

        lines_from = frm.split("$$$") if frm else []
        lines_url = urls.split("$$$")
        out_from, out_url = [], []
        for i, line in enumerate(lines_url):
            episodes = []
            for ep in line.split("#"):
                ep = ep.strip()
                if not ep:
                    continue
                if "$" in ep:
                    name, addr = ep.split("$", 1)
                else:
                    name, addr = "正片", ep
                addr = addr.strip()
                if not addr:
                    continue
                episodes.append("%s$%s" % (name.strip() or "正片", addr))
            if not episodes:
                continue
            name = lines_from[i].strip() if i < len(lines_from) else "线路%d" % (i + 1)
            out_from.append(name or "线路%d" % (i + 1))
            out_url.append("#".join(episodes))

        return "$$$".join(out_from), "$$$".join(out_url)

    @staticmethod
    def _fmt_count(n):
        try:
            n = int(n)
        except Exception:  # noqa: BLE001
            return str(n)
        if n >= 10000:
            return "%.1f万" % (n / 10000.0)
        return str(n)

    def isVideoFormat(self, url):
        u = str(url or "").lower()
        return ".m3u8" in u or ".mp4" in u or ".flv" in u


# 兼容部分壳子直接读取模块级变量
spider = Spider()
