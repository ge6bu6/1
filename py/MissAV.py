# -*- coding: utf-8 -*-
# ══════════════════════════════════════════════════════════════
# 判型记录(卡01;跨会话可读 —— 接手先读这段,别重新判一遍)
#   RE_TARGET   : 用户给的是 missav.com;该域 2025 年版权判决后被转移,
#                 现为 S3+CloudFront 静态落地页(ThisAV),无片单无播放,写不了。
#                 实际目录站为 missav.ws(候选镜像 missav123.com / missav.ai)。
#   RE_PATH     : 纯HTML 取数 + 详情页源码三级提取播放地址(见 extract_m3u8)
#   RE_OBSTACLE : Cloudflare JS 挑战(Just a moment,403)。机房出口 IP 全指纹
#                 403;真实浏览器/家庭出口实测可直接打开(2026-10-21 浏览器实测:
#                 目录、详情、点播均成功,播到 00:19/1:31:17)。
#                 可选:ext 传入 {"cookie":"cf_clearance=..."} 走 CF-Ares 固化 Cookie。
#   RE_EVIDENCE : 分类以 2026-10-21 站点导航全量实测为准:站内内容分类 37 条
#                 (去重 36,见 CATS,顺序照导航:日本AV/中文字幕/热门/索引/素人/无码/亚洲)。
#                 列表 /cn/{分类}?page=N 每页12条;详情 /cn/{番号小写};
#                 搜索 /cn/search/{关键词}?page=N(实测 ienf 有70页);
#                 女优索引 /cn/actresses 每页24位共1481页,女优页 /cn/actresses/{姓名}
#                 作品为标准视频卡片每页12张;类型索引每页36条共42页 /cn/genres/{名};
#                 发行商索引每页36家共72页 /cn/makers/{名};作品页均为卡片+?page=N。
#                 封面:站点卡片实测张张有图,统一 fourhoi.com/{slug}/cover-t.jpg
#                 (详情 og:image 为 cover-n.jpg)。旧版缺封面是解析漏抓懒加载图,
#                 v3 已修:多候选图优选 data-src、跳过占位图、兜底拼 cover-t。
#                 入口会 302 到 /dmNNN/ 轮换前缀,详情链接无前缀,故不写死前缀;
#                 播放:详情源码含倒序 token 串 'm3u8|...|com|surrit|https|video',
#                 反序拼接得 surrit.com/{uuid}/playlist.m3u8(公开客户端单元测试同法验证);
#                 画质档 720p/480p/360p/自动,自适应 HLS。
#   RE_PIC      : v4(2026-10-22):用户端实测图整批不加载。图本身没问题(浏览器直开
#                 fourhoi 封面 330x222 正常显示),故给每张图带壳系图片加载头
#                 (url@Referer=..@User-Agent=..);女优头像不在女优链接内,规律为
#                 fourhoi.com/actress/{数字编号}-t.jpg,解析改在条目周围版面找图;
#                 ext 可设 {"pic_proxy":1} 改走 wsrv.nl 图片代理做 A/B 对照。
#   RE_FOLDER   : 索引条目(女优/类型/发行商)按文件夹卡片下钻:条目带
#                 vod_tag=folder、vod_id=站内路径,点开走 categoryContent 出作品
#                 卡片网格(不是详情页集数列表);detailContent 保留展开兜底。
#   RE_CREATED  : 2026-10-21;v3 2026-10-22(分类全量/索引/封面);v4 2026-10-22(图片带头/头像/文件夹卡片)
# ══════════════════════════════════════════════════════════════
# TVBox 源 · MissAV
# 四壳协议(铁律):类名必须是 Spider,继承壳提供的 BaseSpider(base.spider);
# 无壳环境(本地自检)走回退定义。playerContent 的 header 必须是 dict。
# 自检:python3 shellsim.py 本文件 --run --strict(需能直连目标站的网络;
# 机房出口被 CF 拦时 L2/L3 会失败,那是出口问题,不是源的问题)

import gzip
import html as html_mod
import json
import re
import sys
import time
import urllib.parse
import urllib.request

try:
    sys.path.append("..")
    from base.spider import BaseSpider
except Exception:
    class BaseSpider:
        pass

SITE = {
    "name": "MissAV",
    # 域候选表:按顺序探活。missav.com 已排除(静态落地页,无内容)。
    "domains": ["https://missav.ws", "https://missav123.com", "https://missav.ai"],
    "headers": {"Referer": "https://missav.ws/"},
}

# 分类全量(2026-10-21 站点导航实测 37 条,无码流出在两个下拉各出现一次,去重后 36)
CATS = [
    {"type_id": "new", "type_name": "最近更新"},
    {"type_id": "release", "type_name": "新作上市"},
    {"type_id": "chinese-subtitle", "type_name": "中文字幕"},
    {"type_id": "today-hot", "type_name": "今日热门"},
    {"type_id": "weekly-hot", "type_name": "本周热门"},
    {"type_id": "monthly-hot", "type_name": "本月热门"},
    {"type_id": "uncensored-leak", "type_name": "无码流出"},
    {"type_id": "actresses", "type_name": "女优一览"},
    {"type_id": "actresses/ranking", "type_name": "女优排行"},
    {"type_id": "genres", "type_name": "类型"},
    {"type_id": "makers", "type_name": "发行商"},
    {"type_id": "genres/VR", "type_name": "VR"},
    {"type_id": "siro", "type_name": "SIRO"},
    {"type_id": "luxu", "type_name": "LUXU"},
    {"type_id": "gana", "type_name": "GANA"},
    {"type_id": "maan", "type_name": "PRESTIGE PREMIUM"},
    {"type_id": "scute", "type_name": "S-CUTE"},
    {"type_id": "ara", "type_name": "ARA"},
    {"type_id": "fc2", "type_name": "FC2"},
    {"type_id": "heyzo", "type_name": "HEYZO"},
    {"type_id": "tokyohot", "type_name": "东京热"},
    {"type_id": "1pondo", "type_name": "一本道"},
    {"type_id": "caribbeancom", "type_name": "Caribbeancom"},
    {"type_id": "caribbeancompr", "type_name": "Caribbeancompr"},
    {"type_id": "10musume", "type_name": "10musume"},
    {"type_id": "pacopacomama", "type_name": "pacopacomama"},
    {"type_id": "gachinco", "type_name": "Gachinco"},
    {"type_id": "xxxav", "type_name": "XXX-AV"},
    {"type_id": "marriedslash", "type_name": "人妻斩"},
    {"type_id": "naughty4610", "type_name": "顽皮4610"},
    {"type_id": "naughty0930", "type_name": "顽皮0930"},
    {"type_id": "madou", "type_name": "麻豆传媒"},
    {"type_id": "twav", "type_name": "TWAV"},
    {"type_id": "furuke", "type_name": "Furuke"},
    {"type_id": "klive", "type_name": "韩国直播"},
    {"type_id": "clive", "type_name": "中国直播"},
]

# 索引型分类:本身是名单页(女优/类型/发行商),不是片单
INDEX_TIDS = {"actresses", "actresses/ranking", "genres", "makers"}
INDEX_PREFIX = {"actresses": "actresses", "actresses/ranking": "actresses",
                "genres": "genres", "makers": "makers"}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TIMEOUT = 15
RETRY = 2

RESERVED = {"release", "new", "actresses", "genres", "makers", "search",
            "chinese-subtitle", "uncensored-leak", "login", "register",
            "history", "playlists", "tags", "dm", "vip", "saved",
            "today-hot", "weekly-hot", "monthly-hot"}

PLACEHOLDER_HINTS = ("data:image", "placeholder", "lazy", "loading", "blank",
                     "spinner", "1x1", "pixel", ".svg", "noimage", "no-image",
                     "default.jpg", "grey", "gray")


def _dec(raw):
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", "ignore")


def txt_of(s):
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s or "")
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html_mod.unescape(s)).strip()


PIC_REFERER = "https://missav.ws/"


def pic_url(url, proxy=False):
    """图片地址加工:此壳系图片加载器认 URL 尾缀请求头(url@Referer=..@User-Agent=..),
    裸地址请求在图床侧常被拒(用户端实测整批不加载)。proxy 时改走 wsrv.nl 图片代理。"""
    if not url:
        return ""
    if proxy:
        bare = re.sub(r"^https?://", "", str(url).split("@")[0])
        return "https://wsrv.nl/?url=" + urllib.parse.quote(bare, safe="")
    if "@" in url:
        return url
    return "%s@Referer=%s@User-Agent=%s" % (url, PIC_REFERER, UA)


def pick_window_images(page_html, win_start, win_end, anchor_start, prefer=""):
    """在版面窗口里收集候选图:prefer 子串命中的靠前,其次按离锚点距离排序。
    返回 URL 列表,调用方按顺序取第一个未被占用的,防相邻条目串图。"""
    page_html = page_html or ""
    seg_start = max(0, win_start)
    seg = page_html[seg_start:win_end]
    anchor_off = max(0, anchor_start - seg_start)
    best = {}
    for m in re.finditer(r"<img[^>]*>", seg, re.I):
        tag = m.group(0)
        for attr in ("data-src", "data-original", "data-lazy-src", "data-url", "src"):
            mm = re.search(attr + r"\s*=\s*[\"']([^\"']+)[\"']", tag, re.I)
            if mm:
                u = mm.group(1).strip()
                low = u.lower()
                if u and not any(h in low for h in PLACEHOLDER_HINTS):
                    if u.startswith("//"):
                        u = "https:" + u
                    elif u.startswith("/"):
                        u = "https://missav.ws" + u
                    if u.startswith("http"):
                        key = (0 if (prefer and prefer in u) else 1,
                               abs(m.start() - anchor_off))
                        if u not in best or key < best[u]:
                            best[u] = key
                break
    return [u for u, _ in sorted(best.items(), key=lambda kv: kv[1])]


def pick_image(body):
    """从卡片 HTML 里挑真实封面。旧版只抓第一个 src,懒加载站会抓到占位图。
    规矩:收集全部候选(data-* 懒加载地址优先于 src),跳过占位/图标,
    fourhoi 的图优先,相对地址补全。"""
    cands = []
    for m in re.finditer(r"<img[^>]*>", body or "", re.I):
        tag = m.group(0)
        for attr in ("data-src", "data-original", "data-lazy-src", "data-url", "src"):
            mm = re.search(attr + r"\s*=\s*[\"']([^\"']+)[\"']", tag, re.I)
            if mm:
                cands.append((0 if attr.startswith("data-") else 1, mm.group(1).strip()))
                break
    good = []
    for prio, url in cands:
        low = url.lower()
        if not url or any(h in low for h in PLACEHOLDER_HINTS):
            continue
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = "https://missav.ws" + url
        if not url.startswith("http"):
            continue
        good.append((0 if "fourhoi.com" in url else 1, prio, url))
    if not good:
        return ""
    good.sort()
    return good[0][2]


class Spider(BaseSpider):
    # 类属性给默认值:壳不先调 init() 时也不炸;init() 里再按 ext 覆盖
    ext = {}
    cookie = ""
    pic_proxy = False
    base = SITE["domains"][0]

    def getName(self):
        return SITE["name"]

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
            # ext 可选:{"cookie": "cf_clearance=xxx; ...", "domain": "https://missav.ws"}
            self.cookie = str(self.ext.get("cookie") or "")
            self.pic_proxy = bool(self.ext.get("pic_proxy"))
            dom = str(self.ext.get("domain") or "")
            if dom.startswith("http"):
                self.base = dom.rstrip("/")

    # ── 网络 ────────────────────────────────────────────────
    def http_get(self, url, tries=None):
        """GET 并跟随跳转(/dmNNN/ 前缀由服务端跳转决定,源不写死)。失败换候选域重试。"""
        tries = RETRY if tries is None else tries
        urls = [url]
        m = re.match(r"(https?://[^/]+)(/.*)", url or "")
        if m:
            for d in SITE["domains"]:
                cand = d.rstrip("/") + m.group(2)
                if cand != url:
                    urls.append(cand)
        for u in urls:
            for attempt in range(tries):
                try:
                    req = urllib.request.Request(u)
                    req.add_header("User-Agent", UA)
                    req.add_header("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.6")
                    for k, v in SITE["headers"].items():
                        req.add_header(k, v)
                    if self.cookie:
                        req.add_header("Cookie", self.cookie)
                    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                        raw = r.read()
                        if raw[:2] == b"\x1f\x8b":
                            raw = gzip.decompress(raw)
                        text = _dec(raw)
                        if "just a moment" in text.lower() and len(text) < 12000:
                            raise ValueError("cloudflare challenge")
                        return text
                except Exception:
                    time.sleep(0.4 * (attempt + 1))
        return ""

    # ── 视频卡片解析 ────────────────────────────────────────
    def parse_list(self, page_html):
        """抽视频卡片。按番号聚合缩略图锚与标题锚,封面用 pick_image 优选,
        抓不到就按 fourhoi.com/{番号}/cover-t.jpg 兜底,保证张张有封面。
        番号规则:含 -数字(如 ienf-464 / fc2-ppv-2777644 / 200gana-3185)。"""
        cards = {}
        order = []
        pat = re.compile(
            r'<a[^>]+href=[\"\']?(https?://[^\"\'\s>]+/(?:dm\d+/)?cn/([a-z0-9][a-z0-9\-]*))[\"\']?[^>]*>(.*?)</a>',
            re.S | re.I)
        for m in pat.finditer(page_html or ""):
            code, body = m.group(2).lower(), m.group(3)
            if code in RESERVED or not re.search(r"-\d", code):
                continue
            url = "https://missav.ws/cn/" + code
            if code not in cards:
                cards[code] = {"vod_id": url, "vod_name": "", "vod_pic": "", "vod_remarks": ""}
                order.append(code)
            card = cards[code]
            pic = pick_image(body)
            if pic and not card["vod_pic"]:
                card["vod_pic"] = pic
            dur = re.search(r"\b(\d{1,2}:\d{2}(?::\d{2})?)\b", body or "")
            if dur and not card["vod_remarks"]:
                card["vod_remarks"] = dur.group(1)
            title = txt_of(body)
            if len(title) > len(card["vod_name"]):
                card["vod_name"] = title
        out = []
        for code in order:
            card = cards[code]
            if not card["vod_pic"]:
                card["vod_pic"] = "https://fourhoi.com/%s/cover-t.jpg" % code
            card["vod_pic"] = pic_url(card["vod_pic"], self.pic_proxy)
            if not card["vod_name"]:
                card["vod_name"] = code.upper()
            card["vod_name"] = card["vod_name"][:120]
            out.append(card)
        if not out:
            out = self.parse_generic(page_html)
        return out

    def parse_generic(self, page_html):
        """兜底解析:番号规则对不上的页(如直播区),有图有字的站内锚就成卡。"""
        out, seen = [], set()
        pat = re.compile(r'<a[^>]+href=[\"\']?((?:https?://[^\"\'\s>]+)?/[^\"\'\s>]+)[\"\']?[^>]*>(.*?)</a>',
                         re.S | re.I)
        for m in pat.finditer(page_html or ""):
            href, body = m.group(1), m.group(2)
            pic = pick_image(body)
            title = txt_of(body)
            if not pic or len(title) < 2:
                continue
            if href.startswith("/"):
                href = "https://missav.ws" + href
            href = re.sub(r"//[^/]+/(dm\d+/)(cn/)", r"//missav.ws/\2", href)
            if href in seen or "missav" not in href:
                continue
            seen.add(href)
            out.append({"vod_id": href, "vod_name": title[:120],
                        "vod_pic": pic_url(pic, self.pic_proxy), "vod_remarks": ""})
        return out[:24]

    # ── 索引解析(女优/类型/发行商名单) ──────────────────────
    def parse_index(self, page_html, prefix):
        """抽名单卡片(女优/类型/发行商)。要点:
        - 条目是文件夹卡片:vod_tag=folder、vod_id=站内路径,点开走
          categoryContent 出她的作品卡片网格,不进播放页集数列表。
        - 女优头像不在女优链接标签内(实测在周围版面,规律
          fourhoi.com/actress/{编号}-t.jpg),故图在条目周围窗口里找,
          已被上一位占用的图不复用,防串图。"""
        page_html = page_html or ""
        pat = re.compile(
            r'<a[^>]+href=[\"\']?(https?://[^\"\'\s>]+/(?:dm\d+/)?cn/' + prefix +
            r'/([^\"\'\s>/]+))[\"\']?[^>]*>(.*?)</a>', re.S | re.I)
        matches = list(pat.finditer(page_html))
        out, seen, used = [], set(), set()
        for m in matches:
            slug, body = m.group(2), m.group(3)
            name = urllib.parse.unquote(slug)
            if not name or name in ("ranking",) or slug in seen:
                continue
            seen.add(slug)
            pic = pick_image(body)
            prefer = "/actress/" if prefix == "actresses" else ""
            if (prefer and prefer not in pic) or not pic:
                for cand in pick_window_images(page_html, m.start() - 1600,
                                               m.end() + 1600, m.start(), prefer):
                    if cand not in used:
                        pic = cand
                        break
            if pic:
                used.add(pic)
            text = txt_of(body)
            disp = name
            mm = re.match(r"(.+?)\s*\d[\d,]*\s*条影片", text)
            if mm and len(mm.group(1)) <= len(name) + 4:
                disp = mm.group(1).strip() or name
            remarks = ""
            cm = re.search(r"([\d,]+)\s*条影片", text)
            if cm:
                remarks = cm.group(1) + " 部"
            ym = re.search(r"\b(19|20)\d{2}\b", text)
            if prefix == "actresses" and ym:
                remarks = (remarks + " · " if remarks else "") + ym.group(0) + " 出道"
            out.append({"vod_id": "/cn/%s/%s" % (prefix, slug),
                        "vod_name": disp,
                        "vod_pic": pic_url(pic, self.pic_proxy),
                        "vod_remarks": remarks, "vod_tag": "folder"})
        return out

    def build_filters(self):
        """给索引分类建筛选:取名单第一页条目做选项。选中后 categoryContent
        直接返回该条目的作品卡片(而不是名单)。取不到就只留「索引浏览」。"""
        filters = {}
        for tid in ("actresses", "genres", "makers"):
            prefix = INDEX_PREFIX[tid]
            page_html = self.http_get("%s/cn/%s" % (self.base, tid), tries=1)
            vals = [{"n": "索引浏览", "v": ""}]
            for item in self.parse_index(page_html, prefix)[:36]:
                vals.append({"n": item["vod_name"],
                             "v": item["vod_id"].replace("https://missav.ws", "")})
            filters[tid] = [{"key": "sub", "name": "选择", "value": vals}]
        if "actresses" in filters:
            filters["actresses/ranking"] = filters["actresses"]
        return filters

    # ── 播放地址提取 ────────────────────────────────────────
    def extract_m3u8(self, page_html):
        """详情页播放地址三级提取(2026-10-21 经公开客户端 missav_api 同法交叉验证):
        1) 倒序 token 串 'm3u8|....|com|surrit|https|video' 反序拼 surrit playlist
        2) 页面直写的 .../playlist.m3u8
        3) 任意 surrit.com/{uuid}/ 资源地址反推 playlist.m3u8"""
        text = page_html or ""
        m = re.search(r"'m3u8(.*?)video", text, re.S)
        if m:
            parts = m.group(1).split("|")[::-1]
            if len(parts) >= 9 and parts[2] and parts[3]:
                return "%s://%s.%s/%s-%s-%s-%s-%s/playlist.m3u8" % (
                    parts[1], parts[2], parts[3], parts[4], parts[5],
                    parts[6], parts[7], parts[8])
        m = re.search(r"https?://[^\s\"']+/playlist\.m3u8", text)
        if m:
            return m.group(0)
        m = re.search(r"https?:[\\/]+surrit\.com[\\/]+([a-f0-9\-]+)[\\/]+", text)
        if m:
            return "https://surrit.com/%s/playlist.m3u8" % m.group(1)
        m = re.search(r"https?://[^\s\"']+\.m3u8[^\s\"']*", text)
        if m:
            return m.group(0)
        return ""

    # ── TVBox 接口 ──────────────────────────────────────────
    def homeContent(self, filter):
        result = {"class": CATS, "list": []}
        if filter:
            try:
                result["filters"] = self.build_filters()
            except Exception:
                result["filters"] = {}
        return result

    def homeVideoContent(self):
        page_html = self.http_get(self.base + "/cn/release")
        return {"list": self.parse_list(page_html)}

    def categoryContent(self, tid, pg, filter, extend):
        pg = str(pg or "1")
        tid = str(tid or "")
        # 文件夹卡片下钻:tid 是条目站内路径(actresses/类型/发行商的某一条)
        drill = ""
        if tid.startswith("/cn/"):
            drill = tid
        elif tid.startswith("http"):
            mm = re.search(r"(/cn/(?:actresses|genres|makers)/[^/?#]+)", tid)
            drill = mm.group(1) if mm else ""
        elif re.match(r"^(actresses|genres|makers)/[^/]+$", tid):
            drill = "/cn/" + tid
        if drill and re.match(r"^/cn/(actresses|genres|makers)/[^/]+$", drill):
            items = self.parse_list(self.http_get("%s%s?page=%s" % (self.base, drill, pg)))
            return {"list": items, "page": int(pg),
                    "pagecount": 9999 if items else int(pg),
                    "limit": len(items) or 12, "total": 999999}
        sub = ""
        if isinstance(extend, dict):
            sub = str(extend.get("sub") or "")
        if sub:
            # 筛选选中了女优/类型/发行商条目:直接给她的作品卡片,可翻页
            url = "%s%s?page=%s" % (self.base, sub, pg)
            items = self.parse_list(self.http_get(url))
            return {"list": items, "page": int(pg),
                    "pagecount": 9999 if items else int(pg),
                    "limit": len(items) or 12, "total": 999999}
        if tid in INDEX_TIDS:
            # 名单页本身:女优/类型/发行商卡片,pg 翻名单页
            url = "%s/cn/%s?page=%s" % (self.base, tid, pg)
            items = self.parse_index(self.http_get(url), INDEX_PREFIX[tid])
            return {"list": items, "page": int(pg),
                    "pagecount": 9999 if items else int(pg),
                    "limit": len(items) or 24, "total": 999999}
        url = "%s/cn/%s?page=%s" % (self.base, tid, pg)
        items = self.parse_list(self.http_get(url))
        return {"list": items, "page": int(pg),
                "pagecount": 9999 if items else int(pg),
                "limit": len(items) or 12, "total": 999999}

    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, list) else ids
        if vid and vid.startswith("/"):
            vid = "https://missav.ws" + vid
        # 名单条目页(女优/类型/发行商):展开成她的作品选集,每集由 playerContent 解析真流
        mm = re.search(r"/cn/(actresses|genres|makers)/([^/]+)$", vid or "")
        if mm:
            page_html = self.http_get(vid)
            works = self.parse_list(page_html)
            name = urllib.parse.unquote(mm.group(2))
            eps = []
            for w in works:
                eps.append("%s$%s" % (w["vod_name"], w["vod_id"]))
            vod = {"vod_id": vid, "vod_name": name,
                   "vod_pic": works[0]["vod_pic"] if works else "",
                   "vod_content": "共 %d 部作品(第一页);用分类筛选可按卡片翻页看全部" % len(works),
                   "vod_play_from": "作品列表",
                   "vod_play_url": "#".join(eps) if eps else ("网页播放$" + vid)}
            return {"list": [vod]}
        page_html = self.http_get(vid)
        title = ""
        m = re.search(r'property="og:title"\s+content="([^"]+)"', page_html or "")
        if m:
            title = html_mod.unescape(m.group(1)).strip()
        if not title:
            m = re.search(r"<h1[^>]*>(.*?)</h1>", page_html or "", re.S)
            if m:
                title = txt_of(m.group(1))
        pic = ""
        m = re.search(r'property="og:image"\s+content="([^"]+)"', page_html or "")
        if m:
            pic = m.group(1)
        if not pic:
            code = (vid or "").rstrip("/").split("/")[-1]
            pic = "https://fourhoi.com/%s/cover-n.jpg" % code
        tags = ""
        m = re.search(r'name="keywords"\s+content="([^"]+)"', page_html or "")
        if m:
            tags = html_mod.unescape(m.group(1)).strip()
        year = ""
        m = re.search(r'property="og:video:release_date"\s+content="([^"]+)"', page_html or "")
        if m:
            year = m.group(1)[:4]
        play = self.extract_m3u8(page_html)
        play_url = ("正片$" + play) if play else ("网页播放$" + vid)
        vod = {"vod_id": vid, "vod_name": title or vid.rstrip("/").split("/")[-1].upper(),
               "vod_pic": pic_url(pic, self.pic_proxy), "vod_year": year, "vod_content": tags,
               "vod_play_from": "MissAV", "vod_play_url": play_url}
        return {"list": [vod]}

    def searchContent(self, key, quick=False, pg="1"):
        pg = str(pg or "1")
        url = "%s/cn/search/%s?page=%s" % (
            self.base, urllib.parse.quote(str(key).strip().lower()), pg)
        items = self.parse_list(self.http_get(url))
        return {"list": items, "page": int(pg)}

    def playerContent(self, flag, id, vipFlags):
        url = id
        parse = 0
        if url and ".m3u8" not in url:
            # 选集/兜底给的是详情页地址时再提取一次;仍失败则交网页解析兜底
            found = self.extract_m3u8(self.http_get(url))
            if found:
                url = found
            else:
                parse = 1
        head = {"User-Agent": UA, "Referer": SITE["headers"]["Referer"]}
        if self.cookie:
            head["Cookie"] = self.cookie
        # 四壳协议:header 必须是 dict,不要拼成字符串
        return {"parse": parse, "url": url, "header": head}
