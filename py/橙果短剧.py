# -*- coding: utf-8 -*-
"""
"""
import os
import re
import json
import base64
import hashlib
from urllib.parse import quote
from typing import List, Dict, Any, Optional

try:
    import requests
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
except ImportError:
    requests = None
    AES = None
    unpad = None

# ===================== 配置区 =====================
SITE = "https://chengguodj.com"
API = "https://api2.chengguodj.com"

# 从前端 bundle 抓取的真实密钥
AES_KEY = b"2acf7e91e9864673"
AES_IV  = b"1c29882d3ddfcfd6"
SIGN_KEY = "5589d41f92a597d016b037ac37db243d"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
    "Referer": "https://chengguodj.com/",
    "Origin": "https://chengguodj.com",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# ===================== 加密 / 签名 =====================
def aes_decrypt(ct: bytes) -> bytes:
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    return unpad(cipher.decrypt(ct), AES.block_size)

def aes_encrypt(pt: bytes) -> bytes:
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    pad_len = AES.block_size - (len(pt) % AES.block_size)
    pt += bytes([pad_len]) * pad_len
    return cipher.encrypt(pt)

def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()

def md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()

def sign_payload(payload: Dict[str, Any]) -> str:
    filtered = {k: v for k, v in payload.items() if v != "" and k not in ("sign", "sign_type")}
    src = "&".join(f"{k}={v}" for k, v in sorted(filtered.items()))
    src += f"&key={SIGN_KEY}"
    return md5(sha256(src.encode()))

def aes_encrypt_payload(payload: Dict[str, Any]) -> bytes:
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    ct = aes_encrypt(data)
    return base64.b64encode(ct)

def aes_decrypt_response(b64: str) -> dict:
    ct = base64.b64decode(b64)
    pt = aes_decrypt(ct)
    return json.loads(pt.decode())

# ===================== HTTP 客户端 =====================
class HttpClient:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update(HEADERS)

    def post(self, url: str, payload: dict = None, params: dict = None) -> dict:
        try:
            enc = aes_encrypt_payload(payload or {})
            r = self.s.post(url, params=params, data=enc, timeout=10)
            if r.status_code != 200:
                return {}
            jr = r.json()
            if jr.get("errcode") == 0:
                if "data" in jr and isinstance(jr["data"], str):
                    return aes_decrypt_response(jr["data"])
                return jr.get("data", {})
            return jr.get("data", {}) or {}
        except Exception:
            return {}

    def get(self, url: str) -> dict:
        try:
            r = self.s.get(url, timeout=10)
            return r.json()
        except Exception:
            return {}

# ===================== 蚂蚁影视 Spider 接口 =====================
try:
    from base.spider import Spider
except Exception:
    class Spider:
        def init(self):
            pass

class Spider(Spider):
    def getName(self):
        return "橙果短剧"

    def init(self, extend=""):
        try:
            super().init(extend)
        except Exception:
            pass
        self.http = HttpClient()
        self._dramas_cache = {}
        self.lines = [
            {"code": "yuanchuang", "name": "橙果原创"},
            {"code": "aiduanju", "name": "AI短剧"},
            {"code": "zhenren", "name": "真人短剧"},
            {"code": "mogai", "name": "AI魔改"},
            {"code": "manju", "name": "AI漫剧"},
        ]
        self.line_map = {l["code"]: l["name"] for l in self.lines}

    def _fix_pic_url(self, cover_obj: Any) -> str:
        """解析真实图片地址，并转成站点官方的 /_img 解密代理地址。

        根因：pic.sugfew.cn 返回的封面是 AES-CBC 密文（cover.encrypted=true），
        站点前端用 media_key 解密后才能显示；壳端图片引擎只会渲染明文图片，
        直接给密文 URL 必然显示占位图。

        解法：站点 SSR 自带解密代理端点
            https://chengguodj.com/_img/{base64(原图URL)}.jpeg
        服务端解密后返回明文 image/jpeg，且无 Referer/UA 防盗链（已实测）。
        """
        if not cover_obj:
            return ""
        pic_url = ""
        if isinstance(cover_obj, str):
            pic_url = cover_obj.strip()
        elif isinstance(cover_obj, dict):
            for k in ("url", "source_url", "file_path", "path", "src", "thumb", "original"):
                v = cover_obj.get(k)
                if isinstance(v, str) and v.strip():
                    pic_url = v.strip()
                    break
        elif isinstance(cover_obj, list) and cover_obj:
            return self._fix_pic_url(cover_obj[0])

        if not pic_url:
            return ""

        # 补齐协议与域名
        if pic_url.startswith("//"):
            pic_url = "https:" + pic_url
        elif not pic_url.startswith("http"):
            if not pic_url.startswith("/"):
                pic_url = "/" + pic_url
            pic_url = SITE + pic_url

        # 密文图 → 站点官方解密代理；b64 中的 + / 需转义防止被路由或 query 误解
        b64 = base64.b64encode(pic_url.encode()).decode()
        b64 = quote(b64, safe="")
        return f"{SITE}/_img/{b64}.jpeg"

    def homeContent(self, filter, *args):
        cate_list = [{"type_name": l["name"], "type_id": l["code"]} for l in self.lines]
        return {"class": cate_list}

    def categoryContent(self, tid, pg, filter, extend, *args):
        pg = int(pg) if str(pg).isdigit() else 1
        page_size = 30
        params = {"page": pg, "sort": "hot"}
        if tid:
            params["line"] = tid
        data = self.http.post(f"{API}/api/v1/dramas", {"page": pg, "sort": "hot"}, params=params)
        inner = data.get("data", {}) if isinstance(data, dict) else {}
        items = []
        for d in inner.get("items", []):
            slug = d.get("slug", "")
            title = d.get("title", "")
            total_eps = int(d.get("total_episodes") or d.get("episodes") or 0)
            
            raw_cover = (
                d.get("cover") or 
                d.get("cover_url") or 
                d.get("poster") or 
                d.get("poster_url") or 
                d.get("thumb") or 
                d.get("image")
            )
            pic = self._fix_pic_url(raw_cover)
            
            if slug:
                self._dramas_cache[slug] = {
                    "title": title,
                    "pic": pic,
                    "total_episodes": total_eps,
                }

            items.append({
                "vod_id": slug,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": f"{total_eps}集" if total_eps else "",
                "vod_content": title,
            })
        pagination = inner.get("pagination", {})
        total = int(pagination.get("total", 0))
        page_count = int(pagination.get("pagecount", 0)) or ((total + page_size - 1) // page_size)
        return {
            "list": items,
            "page": pg,
            "pagecount": page_count,
            "limit": page_size,
            "total": total,
        }

    def homeVideoContent(self, *args):
        return {}

    def searchContent(self, key, quick, pg="1", **kwargs):
        # 兼容壳端 searchContent(key, quick, pg) 三参调用；老壳两参时 quick 位置会传 pg
        pg = str(pg) if str(pg).isdigit() and str(pg) != "0" else (str(quick) if str(quick).isdigit() else "1")
        pg = int(pg)
        quick = False
        page_size = 30
        params = {"page": pg, "sort": "hot"}
        data = self.http.post(f"{API}/api/v1/dramas", {"page": pg, "sort": "hot"}, params=params)
        inner = data.get("data", {}) if isinstance(data, dict) else {}
        items = []
        for d in inner.get("items", []):
            if key.lower() in d.get("title", "").lower():
                slug = d.get("slug", "")
                title = d.get("title", "")
                total_eps = int(d.get("total_episodes") or d.get("episodes") or 0)
                raw_cover = d.get("cover") or d.get("cover_url") or d.get("poster")
                pic = self._fix_pic_url(raw_cover)
                if slug:
                    self._dramas_cache[slug] = {
                        "title": title,
                        "pic": pic,
                        "total_episodes": total_eps,
                    }
                items.append({
                    "vod_id": slug,
                    "vod_name": title,
                    "vod_pic": pic,
                    "vod_remarks": f"{total_eps}集" if total_eps else "",
                    "vod_content": title,
                })
        start = (pg - 1) * page_size
        end = start + page_size
        page_items = items[start:end]
        page_count = (len(items) + page_size - 1) // page_size
        return {
            "list": page_items,
            "page": pg,
            "pagecount": page_count,
            "limit": page_size,
            "total": len(items),
        }

    def detailContent(self, ids, *args):
        slug = ids if isinstance(ids, str) else (ids[0] if ids else "")
        cached = self._dramas_cache.get(slug, {})
        title = cached.get("title", "")
        pic = cached.get("pic", "")
        total_ep = cached.get("total_episodes", 0)

        data = {}
        try:
            data = self.http.post(f"{API}/api/v1/dramas/{slug}", {"slug": slug})
            if not data:
                r = self.http.s.get(f"{API}/api/v1/dramas/{slug}", timeout=5)
                if r.status_code == 200:
                    jr = r.json()
                    if jr.get("errcode") == 0 and "data" in jr:
                        data = aes_decrypt_response(jr["data"]) if isinstance(jr["data"], str) else jr["data"]
        except Exception:
            pass

        d = data.get("data", {}) if isinstance(data, dict) and data.get("data") else (data if isinstance(data, dict) else {})
        if not title:
            title = d.get("title", "") or slug
        if not pic:
            raw_cover = d.get("cover") or d.get("cover_url") or d.get("poster")
            pic = self._fix_pic_url(raw_cover)

        api_total = int(d.get("total_episodes") or d.get("total_episode_count") or d.get("episodes_count") or 0)
        if api_total > 0:
            total_ep = api_total

        if total_ep <= 1:
            try:
                web_res = self.http.s.get(f"{SITE}/drama/{slug}", timeout=5)
                if web_res.status_code == 200:
                    m = re.search(r'共\s*(\d+)\s*集', web_res.text) or re.search(r'(\d+)\s*集全', web_res.text)
                    if m:
                        total_ep = int(m.group(1))
                    if not pic:
                        m_img = re.search(r'property=["\']og:image["\'] content=["\']([^"\']+)["\']', web_res.text)
                        if m_img:
                            pic = self._fix_pic_url(m_img.group(1))
            except Exception:
                pass

        if total_ep <= 1:
            total_ep = 30

        eps = []
        episodes_list = d.get("episodes") or []
        if isinstance(episodes_list, list) and len(episodes_list) > 1:
            for idx, ep in enumerate(episodes_list, start=1):
                if isinstance(ep, dict):
                    num = ep.get("number") or ep.get("ep") or ep.get("episode") or idx
                    eps.append(f"第{num}集${SITE}/play/{slug}/ep-{num}/")
                else:
                    eps.append(f"第{idx}集${SITE}/play/{slug}/ep-{idx}/")

        if len(eps) <= 1:
            eps = []
            for i in range(1, total_ep + 1):
                full_url = f"{SITE}/play/{slug}/ep-{i}/"
                eps.append(f"第{i}集${full_url}")

        line_obj = d.get("line")
        line_name = line_obj.get("name", "") if isinstance(line_obj, dict) else str(line_obj or "橙果短剧")
        tags = [t.get("name", "") for t in (d.get("tags") or []) if isinstance(t, dict)]

        vod = {
            "vod_id": slug,
            "vod_name": title,
            "vod_pic": pic,
            "vod_remarks": f"共{total_ep}集",
            "vod_content": f"线路：{line_name}\n标签：{'、'.join(tags) if tags else '短剧'}\n{title}",
            "vod_play_from": "橙果短剧",
            "vod_play_url": "#".join(eps),
        }
        return {"list": [vod]}

    def playerContent(self, flag, id, vipFlags=None):
        if not id:
            return {}
        url = id.split("$")[-1] if "$" in id else id
        url = url.strip()
        if url.startswith("/"):
            url = SITE + url
        m3u8 = self._resolve_m3u8(url)
        return {
            "parse": 0,
            "playUrl": "",
            "url": m3u8 or url,
            "header": {
                "User-Agent": HEADERS["User-Agent"],
                "Referer": SITE + "/",
                "Origin": SITE,
            }
        }

    def _resolve_m3u8(self, play_url: str) -> str:
        """从 /api/v1/dramas/{slug}/episodes/{ep} 获取真实 m3u8 地址"""
        try:
            m = re.search(r'/play/([^/]+)/ep-(\d+)/?', play_url)
            if not m:
                return ""
            slug = m.group(1)
            ep = m.group(2)
            data = self.http.s.post(f"{API}/api/v1/dramas/{slug}/episodes/{ep}", json={}, timeout=10)
            jr = data.json()
            if jr.get("errcode") == 0 and "data" in jr and isinstance(jr["data"], str):
                dec = aes_decrypt_response(jr["data"])
                media = dec.get("data", {}).get("media", {}) if isinstance(dec, dict) else {}
                if isinstance(media, dict):
                    src = media.get("source_url") or media.get("h265_url") or media.get("url")
                    if src:
                        return src
        except Exception:
            pass
        return ""

# ===================== 本地调试入口 =====================
if __name__ == "__main__":
    sp = Spider()
    sp.init()
    print("插件加载成功")
