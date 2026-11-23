# -*- coding: utf-8 -*-
# ===========================================================================
#  黄果漫剧（huangguo）TVBox Python 源
#
#  站点画像（2026-11-22 实测）：
#    - 前端：ssp 自研站，非 MacCMS；导航 /ai-manju/ /lifan-dongman/ /duanju/ /riman/ /hanman/
#    - 视频分类接口：GET /api/videos/category/{slug}?sort=new|hot&page=N&size=18
#    - 视频详情接口：GET /api/videos/{id}              → 元数据 + episodes[]
#    - 单集播放接口：GET /api/videos/{id}/play?ep=N    → video_url（m3u8，AES-128）
#    - 搜索：GET /search/video/{kw}/{page}/（SSR，20 条/页）
#    - 漫画 /riman/ /hanman/ /comic/{id}/ 为 SSR HTML，章节图在 hg-reader-pages
#    - 专题 /topics/、排行榜 /ranks/{hot,potential,recommend}/
#
#  动态地址（用户要求）：
#    - 永久发布页 https://huangguoac.pages.dev/publish.js
#        urls      → 当前主域名（如 euqrdibc.cc）
#        subdomains→ 前缀池（thu/pku/...，实测该域为泛解析）
#        foreverUrls→ huangguoac.com / huangguoac.net
#    - 先探测种子域名，再按发布页域名+随机前缀生成候选，全部探活后才设为 self._base；
#      请求失败自动换域，整池失败重新解析发布页。
#
#  挂载示例：
#   {"key":"huangguo","name":"黄果漫剧","type":3,"api":"...","searchable":1,
#    "quickSearch":1,"filterable":1}
#   ext 可选 {"host":"https://xxx.euqrdibc.cc"} 固定入口。
# ===========================================================================

import html as _html
import json
import random
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request

try:
    from lxml import etree as _etree
except Exception:
    _etree = None

from base.spider import Spider

UA = ('Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36')

PUBLISH_URL = 'https://huangguoac.pages.dev/publish.js'
SEED_HOSTS = [
    'https://ow9e.gkvscakgx.cc',
    'https://njjf5.gkvscakgx.cc',
    'https://huangguoac.com',
    'https://huangguoac.net',
]
LEGACY_SUFFIXES = ['gkvscakgx.cc', 'euqrdibc.cc']
SUB_HINTS = ['thu', 'pku', 'fdu', 'sjtu', 'zju', 'nju', 'xmu', 'sysu']

# tid 直接使用站点 slug
CATS = [
    ('ai-manju', '原创漫剧'),
    ('lifan-dongman', '里番动漫'),
    ('duanju', '成人短剧'),
    ('riman', '成人日漫'),
    ('hanman', '成人韩漫'),
    ('topics', '专题'),
    ('ranks', '排行榜'),
]
VIDEO_TIDS = ('ai-manju', 'lifan-dongman', 'duanju')
COMIC_TIDS = ('riman', 'hanman')
RANK_SORTS = [('hot', '热门榜'), ('potential', '潜力榜'), ('recommend', '推荐榜')]
PAGE_SIZE = 18
SEARCH_SIZE = 20


class Spider(Spider):
    name = '黄果漫剧'
    host = 'ow9e.gkvscakgx.cc'

    # ------------------------------------------------------------ 生命周期
    def __init__(self):
        self._cfg_host = ''
        self._base = ''
        self._domains = []
        self._resolving = False
        self._cache = {}

    def init(self, extend=''):
        self.extend = extend
        self._cfg_host = ''
        try:
            cfg = {}
            if extend:
                cfg = json.loads(extend) if isinstance(extend, str) else dict(extend)
            if cfg.get('host'):
                h = str(cfg['host']).strip().rstrip('/')
                if h and not h.startswith('http'):
                    h = 'https://' + h
                self._cfg_host = h
        except Exception as e:
            self._log('init config error: %s' % e)
        return self

    def destroy(self):
        self._cache = {}

    def getName(self):
        return self.name

    # ------------------------------------------------------------ 基础工具
    def _log(self, msg):
        try:
            print(f"[huangguo] {msg}", file=sys.stderr)
        except Exception:
            pass

    @staticmethod
    def _loads(txt):
        if not txt:
            return None
        t = txt.strip()
        if not t or t.startswith('<'):
            return None
        try:
            return json.loads(t)
        except Exception:
            return None

    @staticmethod
    def _ok(d):
        return isinstance(d, dict) and int(d.get('status') or 0) == 1

    def _headers(self, json_mode=False):
        h = {
            'User-Agent': UA,
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Referer': (self._base or 'https://ow9e.gkvscakgx.cc') + '/',
        }
        if json_mode:
            h['Accept'] = 'application/json, text/plain, */*'
        else:
            h['Accept'] = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        return h

    def _http_get(self, url, headers=None, timeout=10):
        """优先宿主 fetch，其次 requests / urllib，保证本地与壳内都能跑。"""
        h = self._headers()
        if headers:
            h.update(headers)
        if hasattr(self, 'fetch'):
            try:
                r = self.fetch(url, headers=h, timeout=timeout)
            except TypeError:
                try:
                    r = self.fetch(url, None, None, h, timeout)
                except Exception:
                    r = None
            except Exception:
                r = None
            if isinstance(r, bytes):
                r = r.decode('utf-8', 'replace')
            if isinstance(r, str) and r.strip():
                return r
        try:
            import requests
            r = requests.get(url, headers=h, timeout=timeout, verify=False)
            if r.status_code == 200 and r.text.strip():
                return r.text
        except Exception:
            pass
        try:
            req = urllib.request.Request(url, headers=h)
            ctx = ssl._create_unverified_context()
            return urllib.request.urlopen(req, timeout=timeout, context=ctx).read().decode('utf-8', 'replace')
        except Exception:
            return ''

    def _cached_get(self, url, headers=None, ttl=120):
        now = time.time()
        hit = self._cache.get(url)
        if hit and now - hit[0] < ttl:
            return hit[1]
        txt = self._http_get(url, headers)
        if txt:
            self._cache[url] = (now, txt)
        return txt

    @staticmethod
    def _fix_url(u):
        if not u:
            return ''
        u = _html.unescape(u).strip()
        if u.startswith('//'):
            return 'https:' + u
        return u

    # pic.qnlycc.cn 下发的是 AES-128-CBC/NoPadding 加密流（站内 crypto-worker 解密），
    # 同一路径在明文图床 imgpublic.ycomesc.live 上可直取原图
    @staticmethod
    def _pic(u):
        u = Spider._fix_url(u)
        m = re.match(r'^https?://(?:[a-z0-9-]+\.)*qnlycc\.cn(/[^?#]*)?', u, re.I)
        if not m:
            return u
        return 'https://imgpublic.ycomesc.live' + (m.group(1) or '')

    # ------------------------------------------------------------ 动态地址
    def _add_candidate(self, out, u):
        if not u:
            return
        u = str(u).strip().rstrip('/')
        if not u:
            return
        if not u.startswith('http'):
            u = 'https://' + u
        if u not in out:
            out.append(u)

    def _publish_candidates(self):
        out = []
        txt = self._cached_get(PUBLISH_URL, {'Accept': '*/*'}, ttl=600)
        if not txt:
            return out
        suffix = []
        prefix = []
        forever = []
        for m in re.finditer(r'urls\s*=\s*\[(.*?)\]', txt, re.S):
            for d in re.findall(r'[\'"]([a-z0-9][a-z0-9.\-]*\.[a-z]{2,})/?[\'"]', m.group(1)):
                if d not in suffix:
                    suffix.append(d)
        for m in re.finditer(r'subdomains\s*=\s*\[(.*?)\]', txt, re.S):
            for s in re.findall(r'[\'"]([a-z0-9]{2,12})[\'"]', m.group(1)):
                if s not in prefix:
                    prefix.append(s)
        for m in re.finditer(r'(?:foreverUrls|otherUrls)\s*=\s*\[(.*?)\]', txt, re.S):
            for u in re.findall(r'[\'"](https?://[^\'"]+)[\'"]', m.group(1)):
                if u not in forever:
                    forever.append(u)

        for s in suffix:
            if s not in LEGACY_SUFFIXES:
                LEGACY_SUFFIXES.append(s)
        if not prefix:
            prefix = list(SUB_HINTS)
        # 发布页给的前缀池优先，随机补几个泛解析前缀
        sample = prefix[:]
        random.shuffle(sample)
        sample = sample[:4]
        chars = 'abcdefghijklmnopqrstuvwxyz0123456789'
        for _ in range(2):
            sample.append(''.join(random.choice(chars) for _ in range(5)))
        for pre in sample:
            for suf in LEGACY_SUFFIXES[:3]:
                self._add_candidate(out, 'https://%s.%s' % (pre, suf))
        for u in forever:
            self._add_candidate(out, u)
        return out

    def _candidates(self):
        out = []
        self._add_candidate(out, self._cfg_host)
        for h in SEED_HOSTS:
            self._add_candidate(out, h)
        for h in self._publish_candidates():
            self._add_candidate(out, h)
        return out

    def _probe(self, base):
        txt = self._http_get(
            base + '/api/videos/category/ai-manju?page=1&size=1',
            {'Accept': 'application/json'}, 8)
        return self._ok(self._loads(txt))

    def _resolve(self):
        if self._resolving:
            return self._base
        self._resolving = True
        try:
            cands = self._candidates()
            for base in cands[:10]:
                if self._probe(base):
                    self._base = base
                    self._domains = [base] + [c for c in cands if c != base]
                    self._log('base -> %s' % base)
                    return base
            self._log('resolve failed (%d candidates)' % len(cands))
        except Exception as e:
            self._log('resolve error: %s' % e)
        finally:
            self._resolving = False
        return self._base

    def _ensure_base(self):
        if not self._base or not self._domains:
            self._resolve()
        return self._base

    def _rotate(self):
        if len(self._domains) > 1:
            self._domains.append(self._domains.pop(0))
            self._base = self._domains[0]

    def _get_json(self, path):
        self._ensure_base()
        bases = list(self._domains) or [self._base]
        for i, base in enumerate(bases[:6]):
            d = self._loads(self._cached_get(base + path, {'Accept': 'application/json'}))
            if isinstance(d, dict):
                if self._base != base:
                    self._base = base
                    self._domains = [base] + [b for b in self._domains if b != base]
                return d
            self._rotate()
        self._resolve()
        if self._base:
            return self._loads(self._cached_get(self._base + path, {'Accept': 'application/json'}))
        return None

    def _get_html(self, path):
        self._ensure_base()
        bases = list(self._domains) or [self._base]
        for _ in range(min(len(bases), 6)):
            base = self._domains[0] if self._domains else self._base
            txt = self._cached_get(base + path)
            if txt and len(txt) > 1000 and ('黄果漫剧' in txt or 'hg-comic-feed-card' in txt):
                if self._base != base:
                    self._base = base
                return txt
            self._rotate()
        self._resolve()
        if self._base:
            return self._cached_get(self._base + path)
        return ''

    # ------------------------------------------------------------ 列表解析
    def _parse_cards(self, h, limit=0, kind=None):
        out = []
        seen = set()
        if not h:
            return out
        if _etree is not None:
            try:
                doc = _etree.HTML(h)
                for div in doc.xpath('//div[contains(@class,"hg-comic-feed-card")]'):
                    href = ''
                    for x in div.xpath('.//a/@href'):
                        if re.search(r'/(?:video|comic)/\d+/', x):
                            href = x
                            break
                    m = re.search(r'/(video|comic)/(\d+)/', href) if href else None
                    if not m or (kind and m.group(1) != kind):
                        continue
                    if m.group(1) == 'comic':
                        vid = 'c' + m.group(2)
                    else:
                        vid = m.group(2)
                    if vid in seen:
                        continue
                    seen.add(vid)
                    title = ''.join(div.xpath('.//h3//text()')).strip()
                    pic = div.xpath('.//img/@data-src') or div.xpath('.//img/@src')
                    rem = ''.join(div.xpath('.//span[contains(@class,"hg-comic-feed-card__episode")]//text()')).strip()
                    out.append({
                        'vod_id': vid,
                        'vod_name': _html.unescape(title),
                        'vod_pic': self._pic(pic[0]) if pic else '',
                        'vod_remarks': _html.unescape(rem),
                    })
                    if limit and len(out) >= limit:
                        break
            except Exception as e:
                self._log('etree cards failed: %s' % e)
                out = []
                seen = set()
            if out:
                return out
        for part in re.split(r'<div class="hg-comic-feed-card"', h)[1:]:
            m = re.search(r'href="/(video|comic)/(\d+)/"', part[:1200])
            if not m or (kind and m.group(1) != kind):
                continue
            vid = ('c' + m.group(2)) if m.group(1) == 'comic' else m.group(2)
            if vid in seen:
                continue
            seen.add(vid)
            tm = re.search(r'<h3>(.*?)</h3>', part, re.S)
            title = _html.unescape(re.sub(r'<[^>]+>', '', tm.group(1))).strip() if tm else ''
            cm = re.search(r'data-src="([^"]+)"', part) or re.search(r'<img[^>]+src="([^"]+)"', part)
            cover = self._pic(cm.group(1)) if cm else ''
            em = re.search(r'class="hg-comic-feed-card__episode"[^>]*>(.*?)</span>', part, re.S)
            remark = _html.unescape(re.sub(r'<[^>]+>', '', em.group(1))).strip() if em else ''
            out.append({
                'vod_id': vid,
                'vod_name': title,
                'vod_pic': cover,
                'vod_remarks': remark,
            })
            if limit and len(out) >= limit:
                break
        return out

    def _active_panel(self, h):
        m = re.search(r'<div class="hg-comic-card-grid is-active"[^>]*>', h)
        if not m:
            return h
        nxt = h.find('<div class="hg-comic-card-grid', m.end())
        return h[m.start():nxt if nxt > m.start() else len(h)]

    def _page_total(self, h):
        m = re.search(r'data-pages="(\d+)"', h)
        if m:
            return int(m.group(1))
        m = re.search(r'共\s*<strong>(\d+)</strong>', h)
        if m:
            return max(1, (int(m.group(1)) + SEARCH_SIZE - 1) // SEARCH_SIZE)
        return 1

    # ------------------------------------------------------------ 漫画/专题/榜单
    def _comic_category(self, tid, page):
        path = '/%s/' % tid if page <= 1 else '/%s/%d/' % (tid, page)
        full = self._get_html(path)
        h = self._active_panel(full)
        items = self._parse_cards(h, PAGE_SIZE, 'comic')
        pages = self._page_total(full)
        return {
            'page': page,
            'pagecount': pages or (1 if items else 0),
            'limit': PAGE_SIZE,
            'total': pages * PAGE_SIZE if pages else len(items),
            'list': items,
        }

    def _topics_index(self):
        h = self._get_html('/topics/')
        out = []
        seen = set()
        if not h:
            return {'page': 1, 'pagecount': 0, 'limit': 1, 'total': 0, 'list': out}
        for m in re.finditer(r'<a class="hg-topic-card" href="/topics/([a-z0-9-]+)/">([\s\S]*?)</a>', h):
            slug = m.group(1)
            if slug in seen:
                continue
            seen.add(slug)
            blk = m.group(2)
            t = re.search(r'<h3[^>]*hg-topic-card__title[^>]*>([\s\S]*?)</h3>', blk)
            meta = re.search(r'<p class="hg-topic-card__meta">([\s\S]*?)</p>', blk)
            img = re.search(r'data-src="([^"]+)"', blk)
            out.append({
                'vod_id': 'topic:' + slug,
                'vod_name': _html.unescape(re.sub(r'<[^>]+>', '', t.group(1))).strip() if t else slug,
                'vod_pic': self._pic(img.group(1)) if img else '',
                'vod_remarks': re.sub(r'<[^>]+>', '', meta.group(1)).strip() if meta else '',
                'vod_tag': 'folder',
            })
        return {
            'page': 1,
            'pagecount': 1 if out else 0,
            'limit': len(out) or 1,
            'total': len(out),
            'list': out,
        }

    def _topic_items(self, slug):
        if not re.match(r'^[a-z0-9-]+$', slug or ''):
            return []
        h = self._get_html('/topics/%s/' % slug)
        if not h:
            return []
        a = h.find('专题收录作品')
        if a < 0:
            return []
        b = h.find('相关推荐', a)
        seg = h[a:b] if b > a else h[a:]
        return self._parse_cards(seg)

    def _rank_items(self, sort):
        h = self._get_html('/ranks/%s/' % sort)
        out = []
        seen = set()
        if not h:
            return out
        for part in re.split(r'data-rank-item', h)[1:]:
            mm = re.search(r'data-track-id="(\d+)"', part[:300])
            if not mm:
                continue
            rid = mm.group(1)
            if rid in seen:
                continue
            seen.add(rid)
            seg = part[:2600]
            tm = re.search(r'data-track-title="([^"]*)"', part[:300])
            hm = re.search(r'href="/(video|comic)/%s/"' % rid, seg)
            pm = re.search(r'data-src="([^"]+)"', seg)
            cm = re.search(r'<span class="hg-rank-cate">([^<]*)</span>', seg)
            tm2 = re.search(r'data-track-type-name="([^"]*)"', part[:300])
            um = re.search(r'(更新至\d+集|已完结|全\d+集)', seg)
            vid = ('c' + rid) if (hm and hm.group(1) == 'comic') else rid
            cat = (cm.group(1).strip() if cm else (tm2.group(1).strip() if tm2 else ''))
            rem = ' '.join([x for x in [cat, (um.group(1) if um else '')] if x])
            out.append({
                'vod_id': vid,
                'vod_name': _html.unescape(tm.group(1)) if tm else '',
                'vod_pic': self._pic(pm.group(1)) if pm else '',
                'vod_remarks': rem,
            })
        return out

    def _comic_detail(self, cid):
        h = self._get_html('/comic/%s/' % cid)
        if not h:
            return None
        t = re.search(r'<h1[^>]*>([\s\S]*?)</h1>', h)
        title = _html.unescape(re.sub(r'<[^>]+>', '', t.group(1))).strip() if t else ''
        if not title:
            return None
        cover = re.search(r'property="og:image" content="([^"]+)"', h)
        desc = re.search(r'<p class="hg-web-detail__desc"[^>]*>([\s\S]*?)</p>', h)
        desc_txt = _html.unescape(re.sub(r'<[^>]+>', '', desc.group(1))).strip() if desc else ''
        desc_txt = re.sub(r'^作品简介[:：]\s*', '', desc_txt)
        hero = re.search(r'<p class="hg-comic-hero-line"[^>]*>([\s\S]*?)</p>', h)
        hero_txt = re.sub(r'<[^>]+>', ' ', hero.group(1)) if hero else ''
        remark = ''
        cm = re.search(r'(\d+)\s*话', hero_txt)
        if '已完结' in hero_txt:
            remark = '已完结'
        elif cm:
            remark = '连载至%d话' % int(cm.group(1))
        tags = [_html.unescape(x).strip() for x in
                re.findall(r'<a class="hg-tag"[^>]*>([^<]+)</a>', h)]
        chapters = []
        seen = set()
        for m in re.finditer(r'href="/comic/%s/chapter/(\d+)/"' % cid, h):
            n = int(m.group(1))
            if n not in seen:
                seen.add(n)
                chapters.append(n)
        chapters.sort()
        return {
            'title': title,
            'cover': cover.group(1) if cover else '',
            'desc': desc_txt,
            'remark': remark,
            'tags': [x for x in tags if x],
            'chapters': chapters,
        }

    def _comic_detail_content(self, vid):
        cid = vid[1:]
        d = self._comic_detail(cid)
        if not d or not d.get('chapters'):
            return {'list': []}
        parts = ['%02d$c%s-%d' % (n, cid, n) for n in d['chapters']]
        vod = {
            'vod_id': vid,
            'vod_name': d.get('title') or ('漫画%s' % cid),
            'vod_pic': self._pic(d.get('cover') or ''),
            'vod_content': d.get('desc') or '',
            'vod_remarks': d.get('remark') or '',
            'vod_play_from': '黄果漫画',
            'vod_play_url': "#".join(parts),
            'vod_tag': ','.join(d.get('tags') or []),
            'vod_player': 'pics',
        }
        return {'list': [vod]}

    def _chapter_images(self, h):
        if not h:
            return []
        m = re.search(r'<div class="hg-reader-pages"[^>]*>([\s\S]*?)</div>', h)
        blk = m.group(1) if m else h
        pairs = re.findall(r'<img[^>]*data-src="([^"]+)"[^>]*data-page-no="(\d+)"', blk)
        if not pairs:
            rev = re.findall(r'<img[^>]*data-page-no="(\d+)"[^>]*data-src="([^"]+)"', blk)
            pairs = [(u, n) for n, u in rev]
        pairs.sort(key=lambda x: int(x[1]))
        out = []
        for u, _ in pairs:
            u = self._pic(u)
            if u and u not in out:
                out.append(u)
        return out

    def _comic_play(self, pid):
        m = re.match(r'^c(\d+)(?:-(\d+))?$', pid)
        cid = m.group(1)
        n = int(m.group(2) or 1)
        h = self._get_html('/comic/%s/chapter/%d/' % (cid, n))
        urls = self._chapter_images(h)
        if not urls:
            return {'parse': 0, 'playUrl': '', 'url': '', "header": {'User-Agent': UA}}
        return {
            'parse': 0,
            'playUrl': '',
            'url': 'pics://' + '&&'.join(urls),
            "header": {
                'User-Agent': UA,
                'Referer': (self._base or 'https://ow9e.gkvscakgx.cc') + '/',
            },
        }

    # ------------------------------------------------------------ 六接口
    def homeContent(self, filter):
        classes = [{'type_id': tid, 'type_name': name} for tid, name in CATS]
        try:
            sort_vals = [{'n': '最新更新', 'v': 'new'}, {'n': '最多播放', 'v': 'hot'}]
            filters = {}
            for tid, _ in CATS:
                if tid in VIDEO_TIDS:
                    vals = list(sort_vals)
                    if tid == 'ai-manju':
                        vals.append({'n': '原创精选', 'v': 'original'})
                    filters[tid] = [{'key': 'sort', 'name': '排序', 'value': vals}]
                elif tid == 'ranks':
                    filters[tid] = [{'key': 'sort', 'name': '榜单',
                                     'value': [{'n': n, 'v': v} for v, n in RANK_SORTS]}]
            return {'class': classes, 'filters': filters}
        except Exception as e:
            self._log('homeContent error: %s' % e)
            return {'class': classes, 'filters': {}}

    def homeVideoContent(self):
        items = []
        seen = set()
        for tid in VIDEO_TIDS:
            cards = self._category_api(tid, 1, 'new', 6)
            for it in cards:
                if it['vod_id'] not in seen:
                    seen.add(it['vod_id'])
                    items.append(it)
        return {'list': items}

    def _category_data(self, tid, page, sort, size=PAGE_SIZE):
        q = 'sort=%s&page=%d&size=%d' % (urllib.parse.quote(sort or 'new'), page, size)
        if sort == 'original':
            q = 'sort=hot&is_original=1&page=%d&size=%d' % (page, size)
        d = self._get_json('/api/videos/category/%s?%s' % (urllib.parse.quote(tid), q))
        if not self._ok(d):
            return [], 0, 0
        data = d.get('data') or {}
        pg_info = data.get('pagination') or {}
        out = []
        for it in (data.get('items') or []):
            try:
                vid = str(it.get('id') or '')
                if not vid:
                    continue
                cover = self._pic(it.get('cover') or '')
                ec = int(it.get('episode_count') or 0)
                remark = '已完结' if it.get('is_finished') else ('更新至%d集' % ec if ec else '')
                out.append({
                    'vod_id': vid,
                    'vod_name': _html.unescape(str(it.get('title') or '')),
                    'vod_pic': cover,
                    'vod_remarks': remark,
                })
            except Exception:
                continue
        return out, int(pg_info.get('pages') or 0), int(pg_info.get('total') or 0)

    def _category_api(self, tid, page, sort, size=PAGE_SIZE):
        return self._category_data(tid, page, sort, size)[0]

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = int(pg)
        except Exception:
            page = 1
        if page < 1:
            page = 1
        tid = str(tid or '').strip()
        sort = 'new'
        try:
            if isinstance(extend, dict) and extend.get('sort'):
                sort = str(extend.get('sort'))
            elif isinstance(extend, str) and extend.strip().startswith('{'):
                sort = str(json.loads(extend).get('sort') or 'new')
        except Exception:
            sort = 'new'

        if tid.startswith('topic:'):
            items = self._topic_items(tid[6:])
            return {'page': 1, 'pagecount': 1 if items else 0,
                    'limit': len(items) or 1, 'total': len(items), 'list': items}
        if tid == 'topics':
            return self._topics_index()
        if tid == 'ranks':
            if sort not in ('hot', 'potential', 'recommend'):
                sort = 'hot'
            items = self._rank_items(sort)
            return {'page': 1, 'pagecount': 1 if items else 0,
                    'limit': len(items) or 1, 'total': len(items), 'list': items}
        if tid in COMIC_TIDS:
            return self._comic_category(tid, page)
        if tid not in VIDEO_TIDS:
            tid = VIDEO_TIDS[0]
        if sort not in ('new', 'hot', 'original'):
            sort = 'new'

        items, pagecount, total = self._category_data(tid, page, sort, PAGE_SIZE)
        if not items:
            path = '/%s/' % tid if page <= 1 else '/%s/%d/' % (tid, page)
            h = self._get_html(path)
            h = self._active_panel(h)
            items = self._parse_cards(h, PAGE_SIZE)
            pagecount = self._page_total(h)
            total = pagecount * PAGE_SIZE
        return {
            'page': page,
            'pagecount': pagecount or (1 if items else 0),
            'limit': PAGE_SIZE,
            'total': total,
            'list': items,
        }

    def _extract_id(self, ids):
        if isinstance(ids, (list, tuple)):
            ids = ids[0] if ids else ''
        m = re.search(r'c?\d+', str(ids or '').strip(), re.I)
        return m.group(0) if m else ''

    def _video_detail(self, vid):
        d = self._get_json('/api/videos/%s' % vid)
        if self._ok(d) and isinstance(d.get('data'), dict):
            return d.get('data')
        # 兜底：详情页 videoInitialData
        h = self._get_html('/video/%s/' % vid)
        m = re.search(r'<script id="videoInitialData"[^>]*>(.*?)</script>', h, re.S)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
        if _etree is not None and h:
            try:
                doc = _etree.HTML(h)
                title = ''.join(doc.xpath('//h1//text()')).strip()
                if title:
                    desc = ''.join(doc.xpath(
                        '//div[contains(@class,"hg-play__panel-desc")]//text()')).strip()
                    cover = doc.xpath('//meta[@property="og:image"]/@content')
                    eps = []
                    seen = set()
                    for href in doc.xpath('//a[contains(@href,"/ep-")]/@href'):
                        mm = re.search(r'/ep-(\d+)/', href)
                        if not mm or mm.group(1) in seen:
                            continue
                        seen.add(mm.group(1))
                        n = int(mm.group(1))
                        eps.append({'ep_num': n, 'title': '第%d集' % n})
                    eps.sort(key=lambda x: x['ep_num'])
                    return {
                        'title': title,
                        'description': desc,
                        'cover': self._pic(cover[0]) if cover else '',
                        'episodes': eps,
                        'episode_count': len(eps),
                    }
            except Exception as e:
                self._log('detail html fallback failed: %s' % e)
        return None

    def detailContent(self, ids):
        vid = self._extract_id(ids)
        if not vid:
            return {'list': []}
        if vid[:1].lower() == 'c' and vid[1:].isdigit():
            return self._comic_detail_content(vid)
        d = self._video_detail(vid)
        if not d:
            return {'list': []}
        try:
            total = int(d.get('episode_count') or 0)
        except Exception:
            total = 0
        eps = d.get('episodes') or []
        nums = []
        for e in eps:
            try:
                n = int(e.get('ep_num') or 0)
            except Exception:
                continue
            if n > 0 and str(e.get('status')) != '0':
                nums.append(n)
        if not nums:
            nums = list(range(1, max(total, 1) + 1))
        parts = ['%02d$%s-%d' % (n, vid, n) for n in nums]
        if total <= 0:
            total = len(nums)
        if d.get('is_finished'):
            remark = '已完结'
        elif total:
            remark = '更新至%d集' % total
        else:
            remark = ''
        created = str(d.get('created_at') or '')
        author = d.get('author') or {}
        tags = d.get('tags') or []
        vod = {
            'vod_id': vid,
            'vod_name': _html.unescape(str(d.get('title') or '')),
            'vod_pic': self._pic(str(d.get('cover') or '')),
            'vod_content': _html.unescape(str(d.get('description') or '')),
            'vod_year': created[:4],
            'vod_actor': str(author.get('name') or ''),
            'vod_remarks': remark,
            'vod_play_from': '$$$'.join(['黄果HLS']),
            'vod_play_url': '$$$'.join(["#".join(parts)]),
            'vod_tag': ','.join([str(t) for t in tags if t]),
        }
        if d.get('score'):
            vod['vod_score'] = str(d.get('score'))
        return {'list': [vod]}

    def searchContent(self, key, quick, pg='1'):
        try:
            page = int(pg)
        except Exception:
            page = 1
        if page < 1:
            page = 1
        kw = urllib.parse.quote(str(key or '').strip())
        if not kw:
            return {'list': [], 'page': 1, 'pagecount': 0, 'limit': SEARCH_SIZE, 'total': 0}
        path = '/search/video/%s/' % kw if page <= 1 else '/search/video/%s/%d/' % (kw, page)
        h = self._get_html(path)
        items = self._parse_cards(h)
        if not items and page <= 1:
            h = self._get_html('/search/?keyword=%s' % kw)
            items = self._parse_cards(h)
        pagecount = self._page_total(h) if h else 0
        return {
            'list': items,
            'page': page,
            'pagecount': pagecount,
            'limit': SEARCH_SIZE,
            'total': pagecount * SEARCH_SIZE if pagecount else len(items),
        }

    def _parse_play_id(self, pid):
        s = str(pid or '').strip()
        m = re.match(r'^(\d+)[-#](\d+)$', s)
        if m:
            return m.group(1), int(m.group(2))
        m = re.search(r'(\d+)', s)
        return (m.group(1) if m else ''), 1

    def _play_from_html(self, h, ep):
        if not h:
            return ''
        m = re.search(r'<script id="videoInitialData"[^>]*>(.*?)</script>', h, re.S)
        if m:
            try:
                d = json.loads(m.group(1))
                u = (d.get('epPlaySrcs') or {}).get(str(ep)) or d.get('videoSrc') or ''
                if u:
                    return self._fix_url(u)
            except Exception:
                pass
        m = re.search(r'data-play-src="([^"]+)"', h)
        if m:
            return self._fix_url(m.group(1))
        m = re.search(r'"videoSrc"\s*:\s*"([^"]+)"', h)
        if m:
            return self._fix_url(m.group(1))
        m = re.search(r'var\s+now\s*=\s*["\']([^"\']+)["\']', h)
        if m and ('.m3u8' in m.group(1) or '.mp4' in m.group(1)):
            return self._fix_url(m.group(1))
        m = re.search(r'var\s+player_data\s*=\s*(\{.*?\})\s*[;,<]', h, re.S)
        if m:
            try:
                pd = json.loads(m.group(1))
                u = pd.get('url') or pd.get('video') or ''
                if u:
                    return self._fix_url(u)
            except Exception:
                pass
        return ''

    def playerContent(self, flag, id, vipFlags):
        try:
            pid = str(id or '').strip()
            if re.match(r'^c\d+(?:-\d+)?$', pid):
                return self._comic_play(pid)
            vid, ep = self._parse_play_id(id)
            url = ''
            if vid:
                d = self._get_json('/api/videos/%s/play?ep=%d' % (vid, ep))
                if self._ok(d):
                    url = str((d.get('data') or {}).get('video_url') or '')
                if not url:
                    path = '/video/%s/' % vid if ep <= 1 else '/video/%s/ep-%d/' % (vid, ep)
                    url = self._play_from_html(self._get_html(path), ep)
            if not url:
                return {'parse': 0, 'playUrl': '', 'url': str(id or ''),
                        "header": {'User-Agent': UA}}
            url = self._fix_url(url)
            bare = url.split('?', 1)[0].split('#', 1)[0].lower()
            direct = bare.endswith('.m3u8') or bare.endswith('.mp4')
            return {
                'parse': 0 if direct else 1,
                'playUrl': '',
                'url': url,
                "header": {
                    'User-Agent': UA,
                    'Referer': (self._base or 'https://ow9e.gkvscakgx.cc') + '/',
                },
            }
        except Exception as e:
            self._log('playerContent error: %s' % e)
            return {'parse': 0, 'playUrl': '', 'url': str(id or ''),
                    "header": {'User-Agent': UA}}