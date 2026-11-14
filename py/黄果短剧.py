# coding=utf-8
# ================== 短剧·涩涩·黄果短剧 · TVBox / 影视仓 ==================
# 🏷️ 源头：https://huangguoai.com
# 👤 作者：无聊  |  📅 2026-11-08  (v2 修复版)
# 🏷️ 平台：TVBox / 影视仓 / PeekPro · 只依赖标准库
# 🔍 站型：SSR + JSON API；站点已升级为「播放地址接口实时下发」
#          —— 旧版页面里的 videoSrc / epPlaySrcs 字段已恒为空，故 v1 只剩 1 集且无法播放。
# 🎬 修复要点：
#     1) 选集 = GET  /api/videos/{id}                          → episodes[] 全量集数（权威）
#     2) 播放 = POST /api/videos/{id}/episodes/{ep}/playback   → streams.main（实时签名 m3u8，逐集取）
#     3) 吃瓜 = GET /archives/{id}/ + POST /api/posts/{id}/playback → 正文图与视频（旧版取不到 data-src 图）
#     4) 封面 = AES-128-CBC 密文，统一走 localProxy 判魔数解密；T 表纯 Python 实现，与 pycryptodome 对拍一致
#     5) 榜单/专题/搜索按新 DOM 结构重解析，避开侧栏「猜你喜欢」重复卡片
# ==========================================================
import sys, re, json, time, ssl, gzip, io
import html as _html
import http.client, urllib.parse
from urllib.parse import quote, unquote, urlparse

sys.path.append('..')
try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider:
        def getName(self): return "黄果短剧"
        def init(self, extend=""): pass
        def homeContent(self, filter): return {"class": [], "filters": {}}
        def categoryContent(self, tid, pg, filter, extend):
            return {"list": [], "page": 1, "pagecount": 1, "limit": 20, "total": 0}
        def detailContent(self, ids): return {"list": []}
        def playerContent(self, flag, id, vipFlags=None):
            return {"parse": 0, "url": "", "header": {}}
        def searchContent(self, key, quick, pg="1"):
            return {"list": [], "page": 1, "pagecount": 1, "limit": 20, "total": 0}
        def isVideoFormat(self, url): return False
        def manualVideoCheck(self): return False
        def localProxy(self, param): return [404, "text/plain", b"", {}]


class Spider(BaseSpider):
    name = "短剧·涩涩·黄果短剧"
    host = "https://huangguoai.com"

    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
          "AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/120.0.0.0 Safari/537.36")

    # 封面 AES-128-CBC 密钥（站点 crypto-image-config；密文头 4fe897a4…）
    IMG_KEY = b'f5d965df75336270'
    IMG_IV = b'97b60394abc2fbe1'
    # 站点的 WebP 派生图床（crypto-image-config.cdn.webp）：同路径 + ".webp"，体积约为原图 1/3
    WEBP_BASE = 'https://new2.drleao.cn'
    WEBP_HOSTS = {'pic.drleao.cn', 'new.drleao.cn', 'image.drleao.cn',
                  'pic.aluxvl.cn', 'huangguoai.com'}
    # 壳代理前缀契约：三参数缺一不可（do=py 触发回调 / type=img 标记图片 / url= 真实图）
    PROXY_IMG_PREFIX = "proxy://do=py&type=img&url="

    # 集地址内部标记：hgdj|{视频id}|{集号}
    EP_PREFIX = "hgdj"
    # 吃瓜视频标记：hgdjpost|{帖子id}|{序号}
    POST_PREFIX = "hgdjpost"

    def __init__(self):
        super().__init__()
        self.base_cates = [
            {"id": "ai-duanju",   "name": "🎬 AI成人短剧"},
            {"id": "ai-manju",    "name": "🎬 AI成人漫剧"},
            {"id": "ai-huanlian", "name": "🎬 AI换脸"},
            {"id": "ai-mogai",    "name": "🎬 AI魔改"},
        ]
        self._recommend_cache = None
        self._topics_cache = None
        self._tags_cache = None
        self._cache = {}                # GET 文本短缓存（key -> (过期时间, 文本)）
        self._stream_ok_hosts = set()   # 已校验过取流的 CDN 主机（避免每次播放都探）
        self._play_hdrs = {}            # host -> 取流请求头（代理重写 m3u8 时要用）

    # ── 生命周期 ──────────────────────────────────────────
    def init(self, *args, **kwargs):
        # extend 支持 {"api_base": "https://..."} 换入口
        try:
            raw = ''
            for a in args:
                if isinstance(a, str) and a.strip():
                    raw = a.strip()
            if not raw and isinstance(kwargs.get('extend'), str):
                raw = kwargs['extend'].strip()
            if raw:
                cfg = json.loads(raw)
                if isinstance(cfg, dict) and cfg.get('api_base'):
                    self.host = str(cfg['api_base']).rstrip('/')
        except Exception:
            pass

    def getName(self):
        return self.name

    def getHeaders(self):
        return {"User-Agent": self.UA, "Referer": self.host + "/",
                "Accept": "application/json, text/html, */*",
                "Accept-Encoding": "gzip"}

    def getDependence(self):
        return []

    def destroy(self):
        pass

    def isVip(self):
        return False

    # ══════════════════════════════════════════════════════
    #  HTTP 基础（标准库 http.client）
    # ══════════════════════════════════════════════════════
    def _req(self, method, path_or_url, params=None, data=None,
             headers=None, timeout=15):
        """统一请求，返回 (status, bytes)；失败返回 (None, None)。"""
        url = path_or_url
        if not url.startswith('http'):
            url = self.host + url
        if params:
            sep = '&' if '?' in url else '?'
            url += sep + urllib.parse.urlencode(params)
        u = urlparse(url)
        host = u.hostname
        if not host:
            return None, None
        port = u.port or (443 if u.scheme == 'https' else 80)
        hdr = dict(self.getHeaders())
        if headers:
            hdr.update(headers)
        conn = None
        try:
            if u.scheme == 'https':
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)
            else:
                conn = http.client.HTTPConnection(host, port, timeout=timeout)
            full = u.path + (('?' + u.query) if u.query else '')
            conn.request(method, full or '/', body=data, headers=hdr)
            r = conn.getresponse()
            body = r.read()
            if (r.getheader('Content-Encoding', '') or '').lower() == 'gzip':
                try:
                    body = gzip.GzipFile(fileobj=io.BytesIO(body)).read()
                except Exception:
                    pass
            return r.status, body
        except Exception:
            return None, None
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    # 短 TTL 列表/详情缓存：壳来回切分类、切筛选时不再重复打站
    CACHE_TTL = 30
    CACHE_MAX = 240

    def _get_text(self, path, params=None, headers=None, retry=1, ttl=None):
        key = None
        if ttl is None:
            ttl = self.CACHE_TTL
        if ttl > 0 and not headers:
            key = "%s|%s" % (path, urllib.parse.urlencode(params or {}))
            hit = self._cache.get(key)
            if hit and hit[0] > time.time():
                return hit[1]
        for _ in range(retry + 1):
            st, body = self._req('GET', path, params, headers=headers)
            if st == 200 and body is not None:
                txt = None
                for enc in ('utf-8', 'gbk', 'gb18030'):
                    try:
                        txt = body.decode(enc)
                        break
                    except Exception:
                        continue
                if txt is None:
                    txt = body.decode('utf-8', 'ignore')
                # 软 404：站点常以 200 + 「页面未找到」页面应答，不能当数据用
                if self._looks_error(txt):
                    return None
                if key:
                    if len(self._cache) >= self.CACHE_MAX:
                        try:
                            oldest = min(self._cache.items(), key=lambda kv: kv[1][0])[0]
                            self._cache.pop(oldest, None)
                        except Exception:
                            self._cache.clear()
                    self._cache[key] = (time.time() + ttl, txt)
                return txt
            time.sleep(0.25)
        return None

    @staticmethod
    def _looks_error(txt):
        """软 404 / 盾页 / 空数据页识别（翻页越翻越空、标题变成页脚文字都靠它挡）"""
        if not txt:
            return True
        head = txt[:4000]
        for mark in ('页面未找到', '页面不存在', '内容不存在', '该页面不存在',
                     '系统维护', '正在维护', '请稍后再试', '访问受限'):
            if mark in head:
                return True
        return False

    def _get_json(self, path, params=None, retry=1):
        txt = self._get_text(path, params, retry=retry)
        if txt:
            try:
                return json.loads(txt)
            except Exception:
                pass
        return None

    def _post_json(self, path, payload=None, timeout=15):
        body = json.dumps(payload if payload is not None else {}).encode('utf-8')
        st, raw = self._req('POST', path, data=body, timeout=timeout,
                            headers={"Content-Type": "application/json"})
        if st == 200 and raw:
            try:
                return json.loads(raw.decode('utf-8', 'ignore'))
            except Exception:
                return None
        return None

    def _get_bin(self, url, timeout=15):
        st, body = self._req('GET', url, timeout=timeout)
        if st != 200 or not body:
            return None
        return body

    # ══════════════════════════════════════════════════════
    #  图片（封面）处理
    # ══════════════════════════════════════════════════════
    def _wrap_pic(self, pic):
        """封面统一走 localProxy（先判魔数，密文才解密），避免解析失败白屏。"""
        if not pic:
            return ""
        pic = _html.unescape(str(pic))
        pic = pic.replace("\\u0026", "&").replace("&amp;", "&").strip()
        if pic.startswith("//"):
            pic = "https:" + pic
        elif pic.startswith("/"):
            pic = self.host + pic
        if not pic.startswith("http") or pic.startswith(self.host):
            return pic
        return self._pic_proxy(pic)

    def _pic_proxy(self, pic, kind="img"):
        """代理地址：壳给了回环基址就用回环，否则用 proxy:// 自定义协议"""
        q = urllib.parse.quote(pic, safe="")
        try:
            base = self.getProxyUrl()
        except Exception:
            base = None
        if base:
            sep = '&' if '?' in base else '?'
            return base + sep + "type=%s&url=%s" % (kind, q)
        if kind == "img":
            return self.PROXY_IMG_PREFIX + q
        return "proxy://do=py&type=%s&url=%s" % (kind, q)

    # ══════════════════════════════════════════════════════
    #  homeContent
    # ══════════════════════════════════════════════════════
    def homeContent(self, filter={}):
        result = {"class": [], "filters": {}, "list": []}
        result["class"].append({"type_id": "recommend", "type_name": "⭐精选推荐"})
        tags = self._get_tags()
        tag_values = [{"n": "全部", "v": ""}] + [{"n": t["name"], "v": t["slug"]} for t in tags]
        for c in self.base_cates:
            result["class"].append({"type_id": c["id"], "type_name": c["name"]})
            result["filters"][c["id"]] = [
                {"key": "sort", "name": "排序", "value": [
                    {"n": "最新更新", "v": "latest"},
                    {"n": "当前热播", "v": "hot"},
                    {"n": "随机推荐", "v": "random"},
                ]},
                {"key": "tag", "name": "题材", "value": tag_values},
            ]

        topics = self._get_topics()
        if topics:
            result["class"].append({"type_id": "topics", "type_name": "📚专题合集"})
            result["filters"]["topics"] = [{
                "key": "topic", "name": "专题",
                "value": [{"n": t["name"], "v": t["slug"]} for t in topics],
            }]

        result["class"].append({"type_id": "ranks", "type_name": "📊排行榜"})
        result["filters"]["ranks"] = [{
            "key": "rank_type", "name": "榜单", "value": [
                {"n": "🔥 热播榜", "v": "hot"},
                {"n": "⭐ 推荐榜", "v": "recommend"},
                {"n": "🚀 潜力榜", "v": "potential"},
            ]
        }]

        result["class"].append({"type_id": "chigua", "type_name": "🍉黄果吃瓜"})
        result["filters"]["chigua"] = [{
            "key": "cate", "name": "分类", "value": [
                {"n": "全部", "v": "all"},
                {"n": "热门吃瓜", "v": "remen"},
                {"n": "AI原创", "v": "yuanchuang"},
            ]
        }]

        # 首页推荐位（必须有 list，否则首页空白）
        try:
            data = self._get_json("/api/videos/category/ai-duanju",
                                  params={"page": 1, "size": 20, "sort": "latest"})
            items = ((data or {}).get("data") or {}).get("items") or []
            seen = set()
            for it in items:
                vid = str(it.get("id", ""))
                if not vid or vid in seen:
                    continue
                seen.add(vid)
                result["list"].append({
                    "vod_id": vid,
                    "vod_name": it.get("title", ""),
                    "vod_pic": self._wrap_pic(it.get("cover", "")),
                    "vod_remarks": self._remarks(it),
                })
        except Exception:
            result["list"] = []
        return result

    def _get_tags(self):
        """题材标签（/api/tags，按热度取前 30）"""
        if self._tags_cache is not None:
            return self._tags_cache
        tags = []
        try:
            data = self._get_json("/api/tags")
            cats = ((data or {}).get("data") or {}).get("categories") or []
            pool = {}
            for c in cats:
                for t in (c.get("tags") or []):
                    slug = t.get("slug")
                    if not slug or slug in pool:
                        continue
                    pool[slug] = {"slug": slug, "name": t.get("name") or slug,
                                  "hot": t.get("hot_score") or 0}
            tags = sorted(pool.values(), key=lambda x: -x["hot"])[:30]
        except Exception:
            tags = []
        self._tags_cache = tags
        return tags

    def _get_topics(self):
        if self._topics_cache is not None:
            return self._topics_cache
        topics = []
        try:
            html = self._get_text("/topics/")
            if html:
                for slug, name in re.findall(
                        r'href="/topics/([a-z0-9\-]+)/"[^>]*>.*?hg-topic-card__title">([^<]+)<',
                        html, re.DOTALL):
                    name = _html.unescape(name).strip()
                    if not name or name in (t["name"] for t in topics):
                        continue
                    topics.append({"slug": slug, "name": name})
        except Exception:
            topics = []
        self._topics_cache = topics
        return topics

    # ══════════════════════════════════════════════════════
    #  homeVideoContent
    # ══════════════════════════════════════════════════════
    def homeVideoContent(self):
        if self._recommend_cache is not None:
            return {"list": self._recommend_cache}
        try:
            data = self._get_json("/api/videos/category/ai-duanju",
                                  params={"page": 1, "size": 20, "sort": "latest"})
            items = ((data or {}).get("data") or {}).get("items") or []
            vids, seen = [], set()
            for it in items:
                vid = str(it.get("id", ""))
                if not vid or vid in seen:
                    continue
                seen.add(vid)
                vids.append({
                    "vod_id": vid, "vod_name": it.get("title", ""),
                    "vod_pic": self._wrap_pic(it.get("cover", "")),
                    "vod_remarks": self._remarks(it),
                })
            self._recommend_cache = vids
            return {"list": vids}
        except Exception:
            return {"list": []}

    @staticmethod
    def _remarks(item):
        if not item:
            return ""
        ep = item.get("episode_count") or 0
        if item.get("is_finished"):
            return "全%s集" % ep if ep else "已完结"
        return ("更新至%s集" % ep) if ep else ""

    # ══════════════════════════════════════════════════════
    #  categoryContent
    # ══════════════════════════════════════════════════════
    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = max(int(pg or 1), 1)
        except Exception:
            pg = 1
        ext = extend if isinstance(extend, dict) else {}
        if tid == "recommend":
            # 精选推荐按「当前热播」真翻页（首页 list 另由 homeVideoContent 提供）
            return self._category_api(self.base_cates[0]["id"], "hot", pg)
        if tid == "ranks":
            return self._category_ranks(ext.get("rank_type", "hot"), pg)
        if tid == "topics":
            return self._category_topics(ext.get("topic", ""), pg)
        if tid == "chigua":
            return self._category_chigua(ext.get("cate", "all"), pg)
        tag = str(ext.get("tag") or "").strip()
        if tag:
            return self._category_tag(tag, pg)
        sort = ext.get("sort", "latest")
        if sort == "random":
            return self._category_api(tid, "random", 1)
        return self._category_api(tid, sort, pg)

    def _category_api(self, base_id, sort, page):
        per = 20
        result = {"list": [], "page": page, "pagecount": 1, "limit": per, "total": 0}
        data = self._get_json("/api/videos/category/%s" % base_id,
                              params={"page": page, "size": per, "sort": sort})
        d = (data or {}).get("data") or {}
        items = d.get("items") or []
        seen = set()
        for it in items:
            vid = str(it.get("id", ""))
            if not vid or vid in seen:
                continue
            seen.add(vid)
            result["list"].append({
                "vod_id": vid,
                "vod_name": it.get("title", ""),
                "vod_pic": self._wrap_pic(it.get("cover", "")),
                "vod_remarks": self._remarks(it),
            })
        pg = d.get("pagination") or {}
        result["total"] = pg.get("total") or len(result["list"])
        result["pagecount"] = max(1, int(pg.get("pages") or (page + 1 if len(result["list"]) >= per else page)))
        return result

    # ── SSR 卡片解析（榜单/专题/标签/搜索页共用）──────────
    @staticmethod
    def _grid_slice(doc, marker='hg-card-grid'):
        """只取主列表容器，避开侧栏「猜你喜欢」重复卡片"""
        if not doc:
            return ""
        i = doc.find(marker)
        if i < 0:
            return doc
        seg = doc[i:]
        j = seg.find(marker, 10)
        if j > 0:
            seg = seg[:j]
        k = seg.find('<footer')
        if k > 0:
            seg = seg[:k]
        return seg

    def _parse_drama_cards(self, doc):
        seg = self._grid_slice(doc)
        vids, seen = [], set()
        for chunk in seg.split('<div class="hg-drama-card"')[1:]:
            vm = re.search(r'data-track-item-id="(\d+)"', chunk)
            tm = re.search(r'data-track-title="([^"]+)"', chunk)
            if not vm and not tm:
                continue
            cm = re.search(r'<img[^>]*data-src="([^"]+)"', chunk) or \
                 re.search(r'<img[^>]*src="(https?://[^"]+)"', chunk)
            cover = _html.unescape(cm.group(1)) if cm else ""
            if 'placeholder' in cover:
                cover = ""
            title = _html.unescape(tm.group(1)).strip() if tm else ""
            if not title:
                tm2 = re.search(r'alt="([^"]+)"', chunk)
                title = _html.unescape(tm2.group(1)).strip() if tm2 else ""
            vid = vm.group(1) if vm else ""
            if not vid:
                hm = re.search(r'href="/video/(\d+)/"', chunk)
                vid = hm.group(1) if hm else ""
            if not vid or vid in seen:
                continue
            seen.add(vid)
            remark = ""
            sm = re.search(r'hg-drama-card__score">([^<]+)<', chunk)
            if sm:
                remark = sm.group(1).strip()
            em = re.search(r'data-ep-base="([^"]+)"', chunk)
            if em and em.group(1).strip():
                remark = (remark + " " + em.group(1).strip()).strip()
            vids.append({
                "vod_id": vid,
                "vod_name": title,
                "vod_pic": self._wrap_pic(cover) if cover else "",
                "vod_remarks": remark,
            })
        return vids

    def _category_ranks(self, rank_type, page):
        per = 20
        result = {"list": [], "page": page, "pagecount": 1, "limit": per, "total": 0}
        if rank_type not in ("hot", "recommend", "potential"):
            rank_type = "hot"
        if page > 1:
            # 榜单是单页 SSR（/ranks/x/page/2/ 为 404），没有第 2 页
            return result
        doc = self._get_text("/ranks/%s/" % rank_type)
        if not doc:
            return result
        seg = doc[doc.find('hg-rank-list'):] if 'hg-rank-list' in doc else doc
        seen = set()
        for chunk in seg.split('<div class="hg-rank-item"')[1:]:
            vm = re.search(r'data-track-id="(\d+)"', chunk)
            if not vm:
                hm = re.search(r'href="/video/(\d+)/"', chunk)
                if not hm:
                    continue
                vid = hm.group(1)
            else:
                vid = vm.group(1)
            if vid in seen:
                continue
            seen.add(vid)
            tm = re.search(r'data-track-title="([^"]+)"', chunk)
            title = _html.unescape(tm.group(1)).strip() if tm else ""
            if not title:
                tm2 = re.search(r'hg-rank-item__title"><a[^>]*>([^<]+)<', chunk)
                title = _html.unescape(tm2.group(1)).strip() if tm2 else ""
            cm = re.search(r'<img[^>]*data-src="([^"]+)"', chunk)
            cover = _html.unescape(cm.group(1)) if cm else ""
            if 'placeholder' in cover:
                cover = ""
            dm = re.search(r'hg-rank-item__desc">([^<]+)<', chunk)
            desc = _html.unescape(dm.group(1)).strip() if dm else ""
            remark = ""
            sm = re.search(r'([\d.]+分)', chunk)
            if sm:
                remark = sm.group(1)
            em = re.search(r'(全\d+集|更新至\d+集)', chunk)
            if em:
                remark = (remark + " " + em.group(1)).strip()
            result["list"].append({
                "vod_id": vid, "vod_name": title,
                "vod_pic": self._wrap_pic(cover) if cover else "",
                "vod_remarks": remark, "vod_content": desc,
            })
        result["total"] = len(result["list"])
        result["pagecount"] = 1
        return result

    def _category_topics(self, topic_slug, page):
        result = {"list": [], "page": page, "pagecount": 1, "limit": 24, "total": 0}
        if not topic_slug:
            # 未选专题时用第一个专题兜底，避免「分类无数据」
            ts = self._get_topics()
            if ts:
                topic_slug = ts[0]["slug"]
        if not topic_slug or page > 1:
            # 专题页单页直出（/topics/{slug}/page/2/ 为 404）
            return result
        doc = self._get_text("/topics/%s/" % topic_slug)
        if not doc:
            return result
        result["list"] = self._parse_drama_cards(doc)
        result["total"] = len(result["list"])
        result["pagecount"] = 1
        return result

    def _category_tag(self, slug, page):
        per = 20
        result = {"list": [], "page": page, "pagecount": 1, "limit": per, "total": 0}
        where = "/tag/%s/" % slug
        if page > 1:
            if not slug:
                return result
            where = "/tag/%s/page/%s/" % (slug, str(page))
        doc = self._get_text(where)
        if not doc:
            return result
        result["list"] = self._parse_drama_cards(doc)
        pm = re.search(r'data-pages="(\d+)"', doc)
        pages = int(pm.group(1)) if pm else 0
        result["pagecount"] = pages if pages else (page + 1 if len(result["list"]) >= per else page)
        result["total"] = len(result["list"])
        return result

    def _category_chigua(self, cate, page):
        per = 12
        result = {"list": [], "page": page, "pagecount": 1, "limit": per, "total": 0}
        if cate == "remen":
            base = "/chigua/remen/"
        elif cate == "yuanchuang":
            base = "/chigua/yuanchuang/"
        else:
            base = "/chigua/"
        if page <= 1:
            path = base
        elif base == "/chigua/":
            # 全部：/chigua/page/N/
            path = base + "page/%s/" % str(page)
        else:
            # 子分类：/chigua/remen/N/（不是 page/N/）
            path = base + "%s/" % str(page)
        doc = self._get_text(path)
        if not doc:
            return result
        seen = set()
        for chunk in doc.split('<a class="hg-post-card"')[1:]:
            hm = re.search(r'href="/archives/(\d+)/"', chunk)
            if not hm:
                continue
            pid = hm.group(1)
            if pid in seen:
                continue
            seen.add(pid)
            tm = re.search(r'<h3>(.*?)</h3>', chunk, re.DOTALL)
            title = _html.unescape(re.sub(r'<[^>]+>', '', tm.group(1))).strip() if tm else "吃瓜%s" % pid
            im = re.search(r'<img[^>]*data-src="([^"]+)"', chunk) or \
                 re.search(r'<img[^>]*src="(https?://[^"]+)"', chunk)
            pic = self._wrap_pic(_html.unescape(im.group(1))) if im else ""
            dm = re.search(r'hg-post-card__date">([^<]+)<', chunk)
            date = dm.group(1).strip() if dm else ""
            result["list"].append({
                "vod_id": "archives_%s" % pid,
                "vod_name": title,
                "vod_pic": pic,
                "vod_remarks": date,
            })
        pm = re.search(r'data-pages="(\d+)"', doc)
        pages = int(pm.group(1)) if pm else 0
        result["pagecount"] = pages if pages else (page + 1 if len(result["list"]) >= per else page)
        result["total"] = len(result["list"])
        return result

    # ══════════════════════════════════════════════════════
    #  detailContent
    # ══════════════════════════════════════════════════════
    def detailContent(self, ids):
        if isinstance(ids, (list, tuple)):
            if not ids:
                return {"list": []}
            vid = str(ids[0]).strip()
        else:
            vid = str(ids).strip()
        if not vid:
            return {"list": []}
        if vid.startswith("archives_"):
            return self._detail_archives(vid.replace("archives_", ""))
        return self._detail_video(vid)

    @staticmethod
    def _clean_title(t):
        t = _html.unescape(t or "").strip()
        t = re.sub(r'\s*[-|_]\s*(黄果短剧|短剧视频在线观看|AI成人短剧).*$', '', t)
        return t.strip()

    def _detail_video(self, vid):
        result = {"list": []}
        data = {}
        try:
            j = self._get_json("/api/videos/%s" % vid)
            data = ((j or {}).get("data") or {})
        except Exception:
            data = {}

        title = self._clean_title(data.get("title"))
        cover = data.get("cover") or ""
        desc_parts = []
        if data.get("description"):
            desc_parts.append(str(data["description"]).strip())
        if data.get("tags"):
            desc_parts.append("题材：" + " / ".join([str(t) for t in data["tags"]]))
        author = ((data.get("author") or {}).get("name")) or ""
        if author:
            desc_parts.append("作者：" + author)
        cnt = data.get("counts") or {}
        if cnt:
            desc_parts.append("热度：%s  收藏：%s  点赞：%s" % (
                cnt.get("hot", "-"), cnt.get("collect", "-"), cnt.get("like", "-")))

        # ── 无 API 时退回网页解析 ──
        html = None
        if not data:
            html = self._get_text("/video/%s/" % vid) or ""
            if not title:
                tm = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
                title = self._clean_title(tm.group(1)) if tm else vid
            if not cover:
                cm = re.search(r'property="og:image"\s+content="([^"]+)"', html)
                cover = cm.group(1) if cm else ""
            if not desc_parts:
                dm = re.search(r'<meta\s+name="description"\s+content="([^"]+)"', html)
                if dm:
                    desc_parts.append(_html.unescape(dm.group(1)).strip())

        # ── 选集：以接口 episodes[] 为权威 ──
        eps = data.get("episodes") or []
        ep_nums = []
        for e in eps:
            try:
                n = int(e.get("ep_num") or 0)
            except Exception:
                n = 0
            if n > 0 and (e.get("status") in (None, 1)):
                ep_nums.append(n)
        if not ep_nums:
            try:
                total = int(data.get("episode_count") or 0)
            except Exception:
                total = 0
            if total > 0:
                ep_nums = list(range(1, total + 1))
        if not ep_nums:
            # 网页兜底：从 trackingEpisodes 拿集号
            if html is None:
                html = self._get_text("/video/%s/" % vid) or ""
            tm = re.search(r'"trackingEpisodes"\s*:\s*\{(.*?)\}\s*,\s*"trackingVideo"', html or "", re.DOTALL)
            if tm:
                ep_nums = sorted({int(x) for x in re.findall(r'"(\d+)"\s*:\s*\{', tm.group(1))})
        if not ep_nums:
            ep_nums = [1]

        segs = ["第%d集$%s|%s|%d" % (n, self.EP_PREFIX, vid, n) for n in ep_nums]
        result["list"].append({
            "vod_id": vid,
            "vod_name": title or vid,
            "vod_pic": self._wrap_pic(cover),
            "vod_content": "\n".join([p for p in desc_parts if p]),
            "vod_year": "",
            "vod_area": "",
            "vod_remarks": ("全%d集" % len(ep_nums)) + ("" if data.get("is_finished") else "·连载"),
            "vod_play_from": "黄果短剧",
            "vod_play_url": "#".join(segs),
        })
        return result

    def _detail_archives(self, post_id):
        result = {"list": []}
        doc = self._get_text("/archives/%s/" % post_id)
        if not doc:
            return result

        tm = re.search(r'<h1[^>]*class="hg-post-detail__title"[^>]*>(.*?)</h1>', doc, re.DOTALL)
        if not tm:
            tm = re.search(r'<h1[^>]*>(.*?)</h1>', doc, re.DOTALL)
        if not tm:
            tm = re.search(r'<title>(.*?)</title>', doc, re.DOTALL)
        title = self._clean_title(re.sub(r'<[^>]+>', '', tm.group(1))) if tm else "吃瓜%s" % post_id

        bm = re.search(r'<div class="hg-post-detail__body[^"]*"(.*?)(?:<div class="hg-post-detail__tags|<div class="hg-post-detail__nav|</article>|<footer)',
                       doc, re.DOTALL)
        body = bm.group(1) if bm else ""

        # 正文文字
        desc = ""
        if body:
            txt = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', body, flags=re.DOTALL)
            txt = re.sub(r'<(video|source|iframe|img)[^>]*>', '', txt)
            txt = re.sub(r'<[^>]+>', ' ', txt)
            txt = _html.unescape(txt)
            txt = re.sub(r'\s+', ' ', txt).strip()
            desc = txt[:1200]

        # 正文图（懒加载真图在 data-src）
        imgs = []
        for m in re.finditer(r'<img[^>]+>', body or doc):
            tag = m.group(0)
            um = re.search(r'data-src="([^"]+)"', tag) or re.search(r'src="(https?://[^"]+)"', tag)
            if not um:
                continue
            u = _html.unescape(um.group(1))
            if 'placeholder' in u or 'logo' in u.lower() or '/static/' in u:
                continue
            imgs.append(u)
        imgs = list(dict.fromkeys(imgs))

        pic = imgs[0] if imgs else ""
        if not pic:
            pm = re.search(r'property="og:image"\s+content="([^"]+)"', doc)
            pic = _html.unescape(pm.group(1)) if pm else ""

        # 正文视频（接口实时下发）
        videos = []
        try:
            j = self._post_json("/api/posts/%s/playback" % post_id)
            for v in (((j or {}).get("data") or {}).get("videos") or []):
                u = (v or {}).get("url")
                if u and str(u).startswith("http"):
                    videos.append(u.replace("\\u0026", "&"))
        except Exception:
            pass
        if not videos:
            # 兜底：页面里直接出现的 m3u8/mp4
            for m in re.finditer(r'(https?://[^\s"\'<>]+\.(?:m3u8|mp4)[^\s"\'<>]*)', doc):
                u = _html.unescape(m.group(1)).replace('&amp;', '&')
                if u not in videos:
                    videos.append(u)

        lines, urls = [], []
        if videos:
            segs = []
            for i, u in enumerate(videos):
                name = "视频" if len(videos) == 1 else "视频%d" % (i + 1)
                segs.append("%s$%s|%s|%d" % (name, self.POST_PREFIX, post_id, i))
            lines.append("黄果视频")
            urls.append("#".join(segs))
        if imgs:
            segs = ["图%d$%s" % (i + 1, self._wrap_pic(u)) for i, u in enumerate(imgs)]
            lines.append("黄果图集")
            urls.append("#".join(segs))
        if not lines:
            lines.append("黄果视频")
            urls.append("第1集$%s/%s/%s/" % (self.host, "archives", post_id))

        result["list"].append({
            "vod_id": "archives_%s" % post_id,
            "vod_name": title,
            "vod_pic": self._wrap_pic(pic),
            "vod_content": desc or "吃瓜内容",
            "vod_remarks": ("视频%d" % len(videos)) if videos else ("图集%d" % len(imgs)),
            "vod_play_from": "$$$".join(lines),
            "vod_play_url": "$$$".join(urls),
        })
        return result

    # ══════════════════════════════════════════════════════
    #  searchContent
    # ══════════════════════════════════════════════════════
    def searchContent(self, key, quick, pg="1"):
        result = {"list": [], "page": 1, "pagecount": 1, "limit": 20, "total": 0}
        try:
            page = max(int(pg or 1), 1)
        except Exception:
            page = 1
        data = self._get_json("/api/search", params={"q": key, "page": page, "size": 20})
        d = (data or {}).get("data") or {}
        items = d.get("items") or []
        seen = set()
        for it in items:
            vid = str(it.get("id", ""))
            if not vid or vid in seen:
                continue
            seen.add(vid)
            result["list"].append({
                "vod_id": vid,
                "vod_name": it.get("title", ""),
                "vod_pic": self._wrap_pic(it.get("cover", "")),
                "vod_remarks": self._remarks(it),
            })
        pgd = d.get("pagination") or {}
        result["page"] = page
        result["total"] = pgd.get("total") or len(result["list"])
        result["pagecount"] = max(1, int(pgd.get("pages") or (page + 1 if len(result["list"]) >= 20 else page)))
        return result

    # ══════════════════════════════════════════════════════
    #  playerContent
    # ══════════════════════════════════════════════════════
    def _play_header(self, cdn=None):
        hdr = {"User-Agent": self.UA, "Referer": self.host + "/"}
        if isinstance(cdn, dict) and cdn.get("m3u8Enabled") and cdn.get("authKey") and cdn.get("authValue"):
            hdr[str(cdn["authKey"])] = str(cdn["authValue"])
            if cdn.get("app"):
                hdr["x-cdn-app"] = str(cdn["app"])
        return hdr

    # ── 播放流校验：url 非空 ≠ 能播；顺带把相对路径 m3u8 兜到代理里重写 ──
    @staticmethod
    def _m3u8_abs(base_url, text):
        """把 m3u8 里的相对 URI / 分片改成绝对地址（壳不认相对路径）"""
        out, changed = [], False
        for line in text.splitlines():
            s = line.strip()
            if not s:
                out.append(line)
                continue
            if s.startswith('#'):
                m = re.search(r'URI="([^"]+)"', s)
                if m and not re.match(r'^[a-zA-Z][a-zA-Z0-9+.\-]*://', m.group(1)):
                    s = s.replace(m.group(1), urllib.parse.urljoin(base_url, m.group(1)))
                    changed = True
                out.append(s)
            elif re.match(r'^[a-zA-Z][a-zA-Z0-9+.\-]*://', s):
                out.append(s)
            else:
                out.append(urllib.parse.urljoin(base_url, s))
                changed = True
        return "\n".join(out) + "\n", changed

    def _sniff_play(self, url, hdr=None, timeout=8):
        """取首 1KB 判型：m3u8 / ts / image / html / bin / ''（探测失败）"""
        h = dict(hdr or {})
        h["Range"] = "bytes=0-1023"
        st, body = self._req('GET', url, headers=h, timeout=timeout)
        if st not in (200, 206) or not body:
            return '', ''
        b = body[:1024]
        low = b[:200].lower()
        if b[:7] == b'#EXTM3U' or b'#extm3u' in low:
            return 'm3u8', b.decode('utf-8', 'ignore')
        if b[:1] == b'\x47':
            return 'ts', ''
        if b[:8] == b'\x89PNG\r\n\x1a\n' or b[:2] == b'\xff\xd8' or b[:4] == b'RIFF':
            return 'image', ''
        if b'<html' in low or b'<!doctype' in low or b'<script' in low:
            return 'html', ''
        return 'bin', ''

    def _check_stream(self, url, hdr):
        """首播校验：失败一律 fail-open（不因探测抖动把能播的源判死）"""
        u = urlparse(url)
        host = u.hostname or ''
        if host in self._stream_ok_hosts:
            return url
        kind, text = self._sniff_play(url, hdr)
        if kind == 'm3u8':
            abs_text, changed = self._m3u8_abs(url, text)
            self._stream_ok_hosts.add(host)
            if changed:
                # 相对路径：走代理把重写后的播放列表递给壳
                try:
                    self._play_hdrs[host] = dict(hdr or {})
                except Exception:
                    pass
                return self._pic_proxy(url, kind="m3u8")
            return url
        if kind in ('html', 'image'):
            # 拿到盾页/图片：不是视频流
            return ''
        self._stream_ok_hosts.add(host)
        return url

    def _video_playback(self, vid, ep=1):
        """返回 (m3u8_url, cdn_dict)"""
        try:
            ep = int(ep or 1)
        except Exception:
            ep = 1
        url, cdn = "", {}
        for attempt in range(2):
            j = self._post_json("/api/videos/%s/episodes/%s/playback" % (vid, str(ep)))
            d = (j or {}).get("data") or {}
            if isinstance(d, list):
                d = {}
            url = ((d.get("streams") or {}).get("main")) or ""
            if url:
                return url.replace("\\u0026", "&"), (d.get("cdn") or {})
            time.sleep(0.4)
        # 兜底：详情接口自带第1集地址
        if ep == 1:
            j2 = self._get_json("/api/videos/%s" % vid)
            d2 = ((j2 or {}).get("data") or {})
            u2 = d2.get("video_url") or ""
            if u2:
                return u2.replace("\\u0026", "&"), {}
        return "", {}

    def _post_playback(self, pid, idx=0):
        try:
            idx = int(idx or 0)
        except Exception:
            idx = 0
        j = self._post_json("/api/posts/%s/playback" % pid)
        d = (j or {}).get("data") or {}
        vids = d.get("videos") or []
        if 0 <= idx < len(vids):
            return str((vids[idx] or {}).get("url") or "").replace("\\u0026", "&"), (d.get("cdn") or {})
        if vids:
            return str((vids[0] or {}).get("url") or "").replace("\\u0026", "&"), (d.get("cdn") or {})
        return "", {}

    def playerContent(self, flag, id, vipFlags=None):
        result = {"parse": 0, "url": "", "header": self._play_header()}
        raw = str(id or "").strip()
        if not raw:
            return result
        # 兼容壳传入 "第N集$xxx" 的完整片段
        if '$' in raw and not raw.startswith('http'):
            raw = raw.split('$')[-1].strip()

        url, cdn = "", {}
        if raw.startswith(self.EP_PREFIX + '|'):
            p = raw.split('|')
            vid = p[1] if len(p) > 1 else ""
            ep = p[2] if len(p) > 2 else "1"
            if vid:
                url, cdn = self._video_playback(vid, ep)
                if not url and ep != "1":
                    # 不静默回落到第 1 集（会串集），交给壳打开对应剧集页
                    print("hg: ep%s 取流失败 (%s)" % (ep, vid))
                elif not url:
                    url, cdn = self._video_playback(vid, 1)
        elif raw.startswith(self.POST_PREFIX + '|'):
            p = raw.split('|')
            pid = p[1] if len(p) > 1 else ""
            idx = p[2] if len(p) > 2 else "0"
            if pid:
                url, cdn = self._post_playback(pid, idx)
        elif raw.startswith("archives_"):
            d = self._detail_archives(raw.replace("archives_", ""))
            line = (d.get("list") or [{}])[0].get("vod_play_url", "").split("$$$")[0]
            seg = line.split("#")[0]
            if '$' in seg:
                sub = seg.split('$', 1)[1]
                if sub.startswith(self.POST_PREFIX + '|'):
                    p = sub.split('|')
                    url, cdn = self._post_playback(p[1], p[2] if len(p) > 2 else 0)
                elif sub.startswith("http"):
                    url = sub
        elif raw.startswith("http"):
            url = raw.replace("\\u0026", "&")
        elif re.match(r'^\d+$', raw):
            url, cdn = self._video_playback(raw, 1)

        if url:
            hdr = self._play_header(cdn)
            checked = self._check_stream(url, hdr)
            if checked:
                result["url"] = checked
                result["header"] = hdr
                return result
            print("hg: 取流返回非视频内容，改用壳解析 (%s)" % url[:70])
        # 取不到直链：交给壳解析网页
        result["parse"] = 1
        if raw.startswith(self.EP_PREFIX + '|'):
            p = raw.split('|')
            vid = p[1] if len(p) > 1 else ""
            ep = p[2] if len(p) > 2 else "1"
            if ep and ep != "1":
                result["url"] = "%s/video/%s/ep-%s/" % (self.host, vid, ep)
            else:
                result["url"] = "%s/video/%s/" % (self.host, vid)
        elif raw.startswith("archives_"):
            result["url"] = "%s/archives/%s/" % (self.host, raw.replace("archives_", ""))
        elif re.match(r'^\d+$', raw):
            result["url"] = "%s/video/%s/" % (self.host, raw)
        else:
            result["url"] = self.host + "/"
        return result

    # ══════════════════════════════════════════════════════
    #  辅助 & 代理
    # ══════════════════════════════════════════════════════
    def isVideoFormat(self, url):
        if not url:
            return False
        return bool(re.search(r'\.(m3u8|mp4|avi|flv|mkv|ts)\b', url, re.I) or "m3u8" in url.lower())

    def manualVideoCheck(self):
        return False

    def localProxy(self, param):
        # 壳契约：proxy://do=py&type=img&url=<quote(真实url)>
        typ, url = "", ""
        try:
            if isinstance(param, dict):
                typ = str(param.get("type") or "")
                url = str(param.get("url") or "")
            elif isinstance(param, str):
                p = param
                if p.startswith("proxy://"):
                    p = p[len("proxy://"):]
                if p.startswith("?"):
                    p = p[1:]
                qs = urllib.parse.parse_qs(p)
                typ = (qs.get("type") or [""])[0]
                url = (qs.get("url") or [""])[0]
            elif isinstance(param, (list, tuple)) and len(param) == 2:
                typ, url = str(param[0]), str(param[1])
        except Exception:
            return [404, "text/plain", b"bad param", {}]

        if typ not in ("img", "m3u8"):
            return [404, "text/plain", b"not found", {}]

        img_url = unquote(url)
        if not img_url.startswith("http"):
            return [400, "text/plain", b"missing url", {}]

        if typ == "m3u8":
            # 只用于「相对路径播放列表」兜底：抓下来改绝对地址再交给壳
            hdr = {"User-Agent": self.UA, "Referer": self.host + "/"}
            try:
                host = urlparse(img_url).hostname or ''
                if host in self._play_hdrs:
                    hdr.update(self._play_hdrs[host])
            except Exception:
                pass
            st, raw = self._req('GET', img_url, headers=hdr, timeout=15)
            if st != 200 or not raw:
                return [404, "text/plain", b"fetch failed", {}]
            text = raw.decode('utf-8', 'ignore')
            fixed, _ = self._m3u8_abs(img_url, text)
            return [200, "application/vnd.apple.mpegurl", fixed.encode('utf-8'), {}]

        last_raw = None
        for cand in self._img_candidates(img_url):
            raw = self._get_bin(cand, timeout=10)
            if not raw or len(raw) < 32 or raw[:1] == b'<':
                continue
            if self._is_img_head(raw):
                return [200, self._img_mime(raw), raw, {}]
            dec = self._aes_cbc_decrypt(raw)
            if dec:
                pad = dec[-1] if dec else 0
                if 1 <= pad <= 16 and len(dec) >= pad and all(b == pad for b in dec[-pad:]):
                    dec = dec[:-pad]
                if self._is_img_head(dec):
                    return [200, self._img_mime(dec), dec, {}]
                if last_raw is None:
                    last_raw = dec
            elif last_raw is None:
                last_raw = raw
        if last_raw:
            return [200, self._img_mime(last_raw), last_raw, {}]
        # 站方缺图/全候选失败：回占位图 200，避免真机裂图
        return [200, "image/png", self._placeholder(), {}]

    _PLACEHOLDER = None
    # 64x64 深灰占位图（站方缺图时返回，避免壳里裂图）
    _PLACEHOLDER_B64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAABOElEQVR42u3ZxXUDARAE0Q5H"
        "uKRlFCyDJFP+qbiD8KWfJ4Jf98Ju5+z37uHgHY/+6RSczxfHCV038rzY95MgSC+XLAzzKCri"
        "uEySKk3rLGvy/FoUt7K8V9Wjrtum6a7X/nYb7vfx8Zjadu66pe/XYdjG8TlNr3l+L8vHun5u"
        "29fz+f16/fyVC+l6upCupwvperqQrqcL6Xq6kK6nC+l6upCupwvperqQrqcL6Xq6kK6nC+l6"
        "upCupwvperqQrqcL6Xq6kK6nC+l6upCupwvperqQrqcL6Xq6kK6nC+l6upCupwvperqQrqcL"
        "6Xq6kK6nC+l6upCupwvperqQrqcL6Xq6kK6nC+l6upCupwvperqwT2yf2D6xfWL7xPaJ7RPb"
        "J7ZPbJ/YPrF9YvvE9ontE9sntk/8Lz/xL+bikyYK6cqoAAAAAElFTkSuQmCC"
    )

    @classmethod
    def _placeholder(cls):
        if cls._PLACEHOLDER is None:
            import base64
            try:
                cls._PLACEHOLDER = base64.b64decode(cls._PLACEHOLDER_B64)
            except Exception:
                cls._PLACEHOLDER = b''
        return cls._PLACEHOLDER

    # 当前站点的图床主域（命中即不再试镜像域，避免无谓超时叠加）
    GOOD_IMG_HOSTS = {'pic.drleao.cn', 'new2.drleao.cn', 'new.drleao.cn', 'image.drleao.cn'}

    def _img_candidates(self, url):
        """图源候选顺序：原图（带签名）→ 去签名原图 → CDN WebP 派生 →（旧域才试）同路径镜像
        实测该站 .webp 派生多为原图的 1.2~1.5 倍，只作兜底。"""
        out = [url]
        bare = url.split('?')[0]
        if bare != url:
            out.append(bare)
        try:
            u = urlparse(url)
            h = (u.hostname or '').lower()
            if h in self.WEBP_HOSTS and u.path:
                out.append(self.WEBP_BASE + u.path + '.webp')
            if h not in self.GOOD_IMG_HOSTS and u.path:
                for fb in ('pic.drleao.cn', 'new.drleao.cn'):
                    out.append('https://%s%s' % (fb, u.path))
        except Exception:
            pass
        seen, res = set(), []
        for u in out:
            if u not in seen:
                seen.add(u)
                res.append(u)
        return res

    @staticmethod
    def _is_img_head(b):
        return bool(b and (
            b[:8] == b'\x89PNG\r\n\x1a\n' or
            b[:2] == b'\xff\xd8' or
            (b[:4] == b'RIFF' and len(b) > 12 and b[8:12] == b'WEBP') or
            b[:6] in (b'GIF87a', b'GIF89a')))

    @staticmethod
    def _img_mime(b):
        if b[:8] == b'\x89PNG\r\n\x1a\n':
            return "image/png"
        if b[:2] == b'\xff\xd8':
            return "image/jpeg"
        if b[:4] == b'RIFF' and len(b) > 12 and b[8:12] == b'WEBP':
            return "image/webp"
        if b[:6] in (b'GIF87a', b'GIF89a'):
            return "image/gif"
        return "image/jpeg"

    def _aes_cbc_decrypt(self, data):
        """AES-128-CBC 解密；宿主带 pycryptodome 时走 C 实现加速（可选，缺失自动回退）。"""
        lib = self._aes_lib()
        if lib is not None:
            try:
                return lib.new(self.IMG_KEY, lib.MODE_CBC, self.IMG_IV).decrypt(data)
            except Exception:
                pass
        return self._pure_aes_cbc(data)

    @staticmethod
    def _aes_lib():
        """可选加速库（不写死依赖：宿主没有就走纯 Python 实现）"""
        if Spider._AES_CACHE is None:
            try:
                Spider._AES_CACHE = __import__('Crypto.Cipher.AES', fromlist=['new'])
            except Exception:
                Spider._AES_CACHE = False
        return Spider._AES_CACHE or None
    # ── 纯 Python AES-128-CBC（T 表加速；真机没有 pycryptodome 时使用）──
    # 已在真实密文上与 pycryptodome 逐字节对拍一致（verify.py 第 6 组）
    _AES_CACHE = None
    _TABLES = None
    _INV_SBOX = None

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
    _RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36]

    @staticmethod
    def _gmul(x, y):
        p = 0
        for _ in range(8):
            if y & 1:
                p ^= x
            hi = x & 0x80
            x = (x << 1) & 0xff
            if hi:
                x ^= 0x1b
            y >>= 1
        return p

    @classmethod
    def _tables(cls):
        """Td0..Td3（含逆 S 盒）+ 逆 S 盒 + InvMixColumns 用的乘法表，只建一次"""
        if cls._TABLES is not None:
            return cls._TABLES
        inv = [0] * 256
        for i, v in enumerate(cls._SBOX):
            inv[v] = i
        td0 = []
        for i in range(256):
            s = inv[i]
            b = ((s << 1) ^ (0x1b if s & 0x80 else 0)) & 0xff
            c = ((b << 1) ^ (0x1b if b & 0x80 else 0)) & 0xff
            e = ((c << 1) ^ (0x1b if c & 0x80 else 0)) & 0xff
            v14 = e ^ c ^ b
            v13 = e ^ c ^ s
            v11 = e ^ b ^ s
            v09 = e ^ s
            td0.append((v14 << 24) | (v09 << 16) | (v13 << 8) | v11)
        rot8 = lambda v: ((v >> 8) | (v << 24)) & 0xffffffff
        td1 = [rot8(v) for v in td0]
        td2 = [rot8(v) for v in td1]
        td3 = [rot8(v) for v in td2]
        mul = {n: [cls._gmul(x, n) for x in range(256)] for n in (0x0e, 0x09, 0x0d, 0x0b)}
        cls._INV_SBOX = inv
        cls._TABLES = (td0, td1, td2, td3, inv, mul)
        return cls._TABLES

    @classmethod
    def _round_keys(cls, key):
        """AES-128 密钥扩展 + 等价逆密码的轮密钥变换（首末轮不变）"""
        td0, td1, td2, td3, inv, mul = cls._tables()
        m14, m09, m13, m11 = mul[0x0e], mul[0x09], mul[0x0d], mul[0x0b]

        def mix_word(w):
            b0, b1 = (w >> 24) & 0xff, (w >> 16) & 0xff
            b2, b3 = (w >> 8) & 0xff, w & 0xff
            return (((m14[b0] ^ m11[b1] ^ m13[b2] ^ m09[b3]) << 24) |
                    ((m09[b0] ^ m14[b1] ^ m11[b2] ^ m13[b3]) << 16) |
                    ((m13[b0] ^ m09[b1] ^ m14[b2] ^ m11[b3]) << 8) |
                    (m11[b0] ^ m13[b1] ^ m09[b2] ^ m14[b3])) & 0xffffffff

        sbox = cls._SBOX
        rcon = cls._RCON
        w = [list(key[i:i + 4]) for i in range(0, 16, 4)]
        for i in range(4, 44):
            t = list(w[i - 1])
            if i % 4 == 0:
                t = t[1:] + t[:1]
                t = [sbox[b] for b in t]
                t[0] ^= rcon[i // 4 - 1]
            w.append([w[i - 4][j] ^ t[j] for j in range(4)])
        rk = []
        for r in range(11):
            k = w[r * 4:r * 4 + 4]
            rk.append([
                (k[0][0] << 24) | (k[0][1] << 16) | (k[0][2] << 8) | k[0][3],
                (k[1][0] << 24) | (k[1][1] << 16) | (k[1][2] << 8) | k[1][3],
                (k[2][0] << 24) | (k[2][1] << 16) | (k[2][2] << 8) | k[2][3],
                (k[3][0] << 24) | (k[3][1] << 16) | (k[3][2] << 8) | k[3][3],
            ])
        for r in range(1, 10):
            rk[r] = [mix_word(x) for x in rk[r]]
        return rk

    def _pure_aes_cbc(self, data):
        """AES-128-CBC 解密（T 表实现，约 0.7MB/s；一次性建表）"""
        key = self.IMG_KEY
        iv = self.IMG_IV
        if len(key) != 16 or len(iv) != 16:
            return b''
        n = (len(data) // 16) * 16
        if n <= 0:
            return b''
        td0, td1, td2, td3, inv, _mul = self._tables()
        rk = self._round_keys(key)
        k10, k9 = rk[10], rk[9]
        k0 = rk[0]
        out = bytearray(n)
        prev = int.from_bytes(iv, 'big')
        from_bytes = int.from_bytes
        pos = 0
        for i in range(0, n, 16):
            blk = from_bytes(data[i:i + 16], 'big')
            t0 = ((blk >> 96) ^ k10[0]) & 0xffffffff
            t1 = (((blk >> 64) & 0xffffffff) ^ k10[1]) & 0xffffffff
            t2 = (((blk >> 32) & 0xffffffff) ^ k10[2]) & 0xffffffff
            t3 = ((blk & 0xffffffff) ^ k10[3]) & 0xffffffff
            rk_ = k9
            for r in range(9, 0, -1):
                s0 = td0[t0 >> 24] ^ td1[(t3 >> 16) & 0xff] ^ td2[(t2 >> 8) & 0xff] ^ td3[t1 & 0xff] ^ rk_[0]
                s1 = td0[t1 >> 24] ^ td1[(t0 >> 16) & 0xff] ^ td2[(t3 >> 8) & 0xff] ^ td3[t2 & 0xff] ^ rk_[1]
                s2 = td0[t2 >> 24] ^ td1[(t1 >> 16) & 0xff] ^ td2[(t0 >> 8) & 0xff] ^ td3[t3 & 0xff] ^ rk_[2]
                s3 = td0[t3 >> 24] ^ td1[(t2 >> 16) & 0xff] ^ td2[(t1 >> 8) & 0xff] ^ td3[t0 & 0xff] ^ rk_[3]
                t0, t1, t2, t3 = s0 & 0xffffffff, s1 & 0xffffffff, s2 & 0xffffffff, s3 & 0xffffffff
                rk_ = rk[r - 1]
            s0 = (((inv[t0 >> 24] << 24) | (inv[(t3 >> 16) & 0xff] << 16) |
                   (inv[(t2 >> 8) & 0xff] << 8) | inv[t1 & 0xff]) ^ k0[0] ^ ((prev >> 96) & 0xffffffff)) & 0xffffffff
            s1 = (((inv[t1 >> 24] << 24) | (inv[(t0 >> 16) & 0xff] << 16) |
                   (inv[(t3 >> 8) & 0xff] << 8) | inv[t2 & 0xff]) ^ k0[1] ^ ((prev >> 64) & 0xffffffff)) & 0xffffffff
            s2 = (((inv[t2 >> 24] << 24) | (inv[(t1 >> 16) & 0xff] << 16) |
                   (inv[(t0 >> 8) & 0xff] << 8) | inv[t3 & 0xff]) ^ k0[2] ^ ((prev >> 32) & 0xffffffff)) & 0xffffffff
            s3 = (((inv[t3 >> 24] << 24) | (inv[(t2 >> 16) & 0xff] << 16) |
                   (inv[(t1 >> 8) & 0xff] << 8) | inv[t0 & 0xff]) ^ k0[3] ^ (prev & 0xffffffff)) & 0xffffffff
            prev = blk
            out[pos:pos + 4] = s0.to_bytes(4, 'big')
            out[pos + 4:pos + 8] = s1.to_bytes(4, 'big')
            out[pos + 8:pos + 12] = s2.to_bytes(4, 'big')
            out[pos + 12:pos + 16] = s3.to_bytes(4, 'big')
            pos += 16
        return bytes(out)


# ── 本地自检（TVBox 以模块方式加载，此块不会执行）──────────────────
if __name__ == '__main__':
    s = Spider()
    s.init("")
    _h = s.homeContent(False)
    print("name:", s.getName(), "| class:", len(_h.get("class") or []),
          "| home:", len(_h.get("list") or []))
    _c = s.categoryContent("ai-duanju", 1, False, {"sort": "latest"})
    print("category:", len(_c.get("list") or []), "pages:", _c.get("pagecount"))
    if _c.get("list"):
        _d = s.detailContent([_c["list"][0]["vod_id"]])
        _one = (_d.get("list") or [{}])[0]
        _segs = (_one.get("vod_play_url") or "").split("#")
        print("detail:", _one.get("vod_name"), "| 集数:", len(_segs))
        if _segs:
            _p = s.playerContent(_one.get("vod_play_from", "").split("$$$")[0],
                                 _segs[0].split("$")[1])
            print("play:", _p.get("parse"), str(_p.get("url"))[:70])
    _q = s.searchContent("女", False, 1)
    print("search:", len(_q.get("list") or []))
