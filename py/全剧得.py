# coding = utf-8
#!/usr/bin/python
import re
import json
import time
import hmac
import hashlib
import urllib.parse
import requests
from base.spider import Spider


class Spider(Spider):

    def __init__(self):
        self.name = "全剧得"
        self.hosts = [
            'http://m51.gotto.top',
            'http://m51.goweb.vip',
            'http://mkk.gotto.xyz'
        ]
        self.host_index = 0
        self.host = self.hosts[self.host_index]
        self.img_host = 'https://r.tvtvd.com'
        self.timeout = 15
        self.header = {
            'User-Agent': 'okhttp/4.1.0',
            'Accept': '*/*',
            'Connection': 'keep-alive'
        }
        self.session = requests.Session()
        self.session.headers.update(self.header)
        self._types_cache = None
        self._types_ts = 0

    def getName(self):
        return self.name

    def init(self, extend=''):
        if extend:
            try:
                ext = json.loads(extend) if isinstance(extend, str) else extend
                if isinstance(ext, dict):
                    hs = ext.get('hosts')
                    if isinstance(hs, list) and hs:
                        self.hosts = hs
                    if ext.get('host'):
                        self.hosts = [ext['host']] + self.hosts
                    if ext.get('img'):
                        self.img_host = ext['img']
                    if ext.get('kkdy_token'):
                        self._kkdy_token = ext['kkdy_token']
            except Exception:
                pass
        if not hasattr(self, '_kkdy_token'):
            self._kkdy_token = ''
        self._kkdy_map = getattr(self, '_kkdy_map', {})
        self._enc_map = {}
        self.host_index = 0
        self.host = self.hosts[self.host_index]
        try:
            import threading
            threading.Thread(target=self._warm_index, daemon=True).start()
        except Exception:
            pass
        return self.getName()

    def _warm_index(self):
        try:
            self._kkdy_index()
        except Exception:
            pass

    def isVideoFormat(self, url):
        return bool(re.search(r'\.(m3u8|mp4|flv|mkv|ts)(\?|$)', url, re.I))

    def manualVideoCheck(self):
        return 0

    def _switch_host(self):
        self.host_index = (self.host_index + 1) % len(self.hosts)
        self.host = self.hosts[self.host_index]

    def _get(self, path, params=None):
        last_err = None
        for _ in range(len(self.hosts)):
            try:
                url = self.host + path
                r = self.session.get(url, params=params, timeout=self.timeout)
                if r.status_code == 200 and r.text.strip():
                    data = r.json()
                    if isinstance(data, dict) and data.get('code') == 200:
                        return data.get('data')
                last_err = 'bad response'
            except Exception as e:
                last_err = str(e)
            self._switch_host()
        return None

    def _pic(self, pic):
        p = (pic or '').strip()
        if not p:
            return ''
        if p.startswith('http'):
            return p
        return self.img_host + '/' + p.lstrip('/')

    def _card(self, v):
        vid = str(v.get('vod_id', ''))
        return {
            'vod_id': vid,
            'vod_name': v.get('vod_name', ''),
            'vod_pic': self._pic(v.get('vod_pic')),
            'vod_remarks': v.get('vod_remarks', ''),
            'vod_year': v.get('vod_year', ''),
            'vod_area': v.get('vod_area', ''),
            'vod_score': v.get('vod_score', '')
        }

    def _map_list(self, data):
        if not data:
            return []
        lst = data.get('list') if isinstance(data, dict) else data
        if not isinstance(lst, list):
            return []
        return [self._card(v) for v in lst if isinstance(v, dict) and v.get('vod_id')]

    def _types(self):
        now = time.time()
        if self._types_cache and now - self._types_ts < 600:
            return self._types_cache
        data = self._get('/api.php/v1.vod/types')
        result = {}
        if data and isinstance(data.get('list'), list):
            for t in data['list']:
                tid = str(t.get('type_id'))
                extend = t.get('type_extend') or {}
                filters = []
                for key, label in (('class', '类型'), ('area', '地区'), ('lang', '语言'), ('year', '年份')):
                    raw = (extend.get(key) or '').strip()
                    if not raw:
                        continue
                    vals = [x.strip() for x in raw.split(',') if x.strip()]
                    if not vals:
                        continue
                    opts = [{'n': '全部', 'v': ''}] + [{'n': v, 'v': v} for v in vals]
                    filters.append({'key': key, 'name': label, 'value': opts})
                sort_opts = [
                    {'n': '全部排序', 'v': ''},
                    {'n': '最多播放', 'v': 'hits'},
                    {'n': '最近更新', 'v': 'time'},
                    {'n': '最多收藏', 'v': 'store_num'},
                    {'n': '最高评分', 'v': 'score'}
                ]
                filters.append({'key': 'by', 'name': '排序', 'value': sort_opts})
                result[tid] = filters
        if result:
            self._types_cache = result
            self._types_ts = now
        return result

    def homeContent(self, filter):
        data = self._get('/api.php/v1.vod/types')
        classes = []
        if data and isinstance(data.get('list'), list):
            for t in sorted(data['list'], key=lambda x: x.get('type_sort', 0)):
                classes.append({
                    'type_id': str(t.get('type_id')),
                    'type_name': t.get('type_name', '')
                })
        result = {'class': classes}
        if filter:
            filters = self._types()
            if filters:
                result['filters'] = filters
        home = self._get('/api.php/v1.vod', {'type': '1', 'limit': '24', 'page': '1'})
        result['list'] = self._map_list(home)
        return result

    def homeVideoContent(self):
        home = self._get('/api.php/v1.vod', {'type': '1', 'limit': '24', 'page': '1'})
        return {'list': self._map_list(home)}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if str(pg).isdigit() else 1
        limit = 30
        extend = extend or {}
        params = {
            'type': str(tid),
            'class': extend.get('class', ''),
            'area': extend.get('area', ''),
            'lang': extend.get('lang', ''),
            'year': extend.get('year', ''),
            'by': extend.get('by', ''),
            'limit': str(limit),
            'page': str(page)
        }
        params = {k: v for k, v in params.items() if v}
        data = self._get('/api.php/v1.vod', params)
        items = self._map_list(data)
        got = len(items)
        pagecount = page if got < limit else page + 1
        return {
            'list': items,
            'page': page,
            'pagecount': pagecount,
            'limit': limit,
            'total': 999999
        }

    def detailContent(self, ids):
        vod_id = str(ids[0])
        data = self._get('/api.php/v1.vod/detail', {'vod_id': vod_id})
        if not data or not isinstance(data, dict):
            return {'list': []}
        v = data
        play_from = (v.get('vod_play_from') or '')
        play_url = (v.get('vod_play_url') or '')
        froms = [x for x in play_from.split('$$$') if x]
        urls = [x for x in play_url.split('$$$') if x]
        shows = []
        play_list = []
        line_map = {'wjm3u8': '直连m3u8', 'qiyi': '爱奇艺', 'BBA': 'KK超级VIP', 'NBY': 'NBY蓝光', 'YYNB': 'YY云播'}
        vod_name = v.get('vod_name', '')
        for i, frm in enumerate(froms):
            seg = urls[i] if i < len(urls) else ''
            eps = [e for e in seg.split('#') if '$' in e]
            if not eps:
                continue
            shows.append(line_map.get(frm, frm))
            play_list.append(eps)
        if not shows:
            return {'list': []}
        self._pending_name = vod_name
        self._pending_channel = str(v.get('type_id') or '1')
        if not hasattr(self, '_enc_map'):
            self._enc_map = {}
        for eps in play_list:
            for e in eps:
                if '$' in e and not e.partition('$')[2].startswith('http'):
                    self._enc_map[e.partition('$')[2]] = ''
        need_fill = any('$' in e and not e.partition('$')[2].startswith('http') for eps in play_list for e in eps)
        if not need_fill:
            cj0 = []
            try:
                cj0 = self._cj_search(vod_name)
            except Exception:
                cj0 = []
            for nm, eps in cj0:
                label = nm + '线路'
                if label not in shows:
                    shows.append(label)
                    play_list.append(eps)
            need_fill = False
        if need_fill:
            kid2 = ''
            try:
                kid2 = self._kkdy_find_id(vod_name, self._pending_channel)
            except Exception:
                kid2 = ''
            if kid2:
                try:
                    shows2, urls2 = self._kkdy_build_lines(kid2)
                except Exception:
                    shows2, urls2 = [], []
                if shows2:
                    new_shows = []
                    new_list = []
                    for si, sname in enumerate(shows):
                        eps0 = play_list[si]
                        if all(e.partition('$')[2].startswith('http') for e in eps0 if '$' in e):
                            new_shows.append(sname)
                            new_list.append(eps0)
                    for si, sname in enumerate(shows2):
                        if sname not in new_shows:
                            new_shows.append(sname)
                            new_list.append(urls2[si])
                    shows = new_shows
                    play_list = new_list
            cj = []
            try:
                cj = self._cj_search(vod_name)
            except Exception:
                cj = []
            for nm, eps in cj:
                label = nm + '线路'
                if label not in shows:
                    shows.append(label)
                    play_list.append(eps)
            if cj:
                best = max(cj, key=lambda x: len(x[1]))
                for eps in play_list:
                    for li, e in enumerate(eps):
                        if li >= len(best[1]):
                            break
                        if '$' in e and not e.partition('$')[2].startswith('http'):
                            u = best[1][li][best[1][li].index('$')+1:]
                            if u:
                                eps[li] = eps[li].partition('$')[0] + '$' + u
            for eps in play_list:
                for e in eps:
                    if '$' in e and not e.partition('$')[2].startswith('http'):
                        self._enc_map[e.partition('$')[2]] = ''
        joined = ['#'.join(eps) for eps in play_list]
        item = {
            'vod_id': vod_id,
            'vod_name': v.get('vod_name', ''),
            'vod_pic': self._pic(v.get('vod_pic')),
            'type_name': v.get('vod_class', ''),
            'vod_year': v.get('vod_year', ''),
            'vod_area': v.get('vod_area', ''),
            'vod_lang': v.get('vod_lang', ''),
            'vod_remarks': v.get('vod_remarks', ''),
            'vod_actor': v.get('vod_actor', ''),
            'vod_director': v.get('vod_director', ''),
            'vod_score': str(v.get('vod_score', '')),
            'vod_content': re.sub(r'<[^>]+>', '', v.get('vod_content') or v.get('vod_blurb') or ''),
            'vod_play_from': '$$$'.join(shows),
            'vod_play_url': '$$$'.join(joined)
        }
        return {'list': [item]}

    def _kkdy_find_id(self, name, channel='1'):
        want = name.strip()
        wn = self._norm_name(want)
        idx = self._kkdy_index()
        kid = idx.get(want, '')
        if kid:
            return kid
        for t, i in idx.items():
            tn = self._norm_name(t)
            if tn == wn or (len(wn) >= 4 and (wn in tn or tn == wn[:len(tn)])):
                return i
        import os
        try:
            fp2 = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kkdy_release_index.json')
            if os.path.exists(fp2):
                rel = json.load(open(fp2, encoding='utf-8'))
                if want in rel:
                    return rel[want]
                for t, i in rel.items():
                    tn = self._norm_name(t)
                    if tn == wn:
                        return i
        except Exception:
            pass
        chans = [channel] + [c for c in ('1', '2', '3', '4') if c != channel]
        cats = ['剧情', '喜剧', '动作', '科幻', '悬疑', '动画', '爱情', '恐怖', '战争', '奇幻', '冒险', '犯罪', '惊悚']
        for ch in chans:
            for cat in cats:
                r = self._kkdy_capi('/vod/channel/list.capi', {'channelId': ch, 'category': cat, 'page': '1'})
                for it in ((r.get('data') or {}).get('items') or []):
                    t = (it.get('title') or '').strip()
                    if t and (t in want or want in t):
                        return str(it['id'])
        return ''

    def _kkdy_index(self):
        cached = getattr(self, '_kkdy_index_cache', None)
        ts = getattr(self, '_kkdy_index_ts', 0)
        if cached is not None and time.time() - ts < 86400:
            return cached
        import os
        try:
            fp = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kkdy_index.json')
            if os.path.exists(fp) and time.time() - os.path.getmtime(fp) < 86400:
                with open(fp, encoding='utf-8') as f:
                    index = json.load(f)
                if index:
                    self._kkdy_index_cache = index
                    self._kkdy_index_ts = time.time()
                    return index
        except Exception:
            pass
        index = {}
        try:
            cats = ['剧情', '剧情 / 惊悚 / 犯罪', '动作', '动作 / 动画 / 家庭 / 奇幻 / 冒险', '动作片', '喜剧片', '恐怖', '恐怖片', '惊悚', '战争', '犯罪', '电影', '纪录片',
                    '台湾剧', '国产', '国产剧', '日本剧', '欧美剧', '泰剧', '泰国剧', '海外剧', '韩国剧', '香港剧',
                    '冒险', '剧情片', '动漫', '动画', '喜剧 / 爱情 / 动画', '国产动漫', '奇幻', '悬疑', '日韩动漫', '欧美动漫', '爱情', '科幻', '日本动漫',
                    'Comedy', 'Reality-TV', '中国综艺', '其他剧', '大陆综艺', '家庭', '日剧', '日韩综艺', '欧美综艺', '港台综艺', '真人秀', '纪录片', '综艺', '脱口秀', '访谈', '音乐']
            for ch in ('1', '2', '3', '4'):
                for cat in cats:
                    r = self._kkdy_capi('/vod/channel/list.capi', {'channelId': ch, 'category': cat, 'page': '1'})
                    for it in ((r.get('data') or {}).get('items') or []):
                        t = (it.get('title') or '').strip()
                        if t and it.get('id') and t not in index:
                            index[t] = str(it['id'])
        except Exception:
            pass
        try:
            import os
            fp2 = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'kkdy_release_index.json')
            if os.path.exists(fp2):
                rel = json.load(open(fp2, encoding='utf-8'))
                for t, i in rel.items():
                    if t not in index:
                        index[t] = i
        except Exception:
            pass
        try:
            for bid in range(10000, 10060):
                r = self._kkdy_capi('/vod/block/streamViews.capi', {'blockId': str(bid), 'vodId': '0', 'channelId': '0'})
                for b in ((r.get('data') or {}).get('blocks') or []):
                    for it in (b.get('data') or []):
                        t = (it.get('title') or '').strip()
                        if t and it.get('id') and t not in index:
                            index[t] = str(it['id'])
        except Exception:
            pass
        if index:
            self._kkdy_index_cache = index
            self._kkdy_index_ts = time.time()
            try:
                with open(fp, 'w', encoding='utf-8') as f:
                    json.dump(index, f, ensure_ascii=False)
            except Exception:
                pass
        return index

    def _kkdy_episode_urls(self, kid):
        det = self._kkdy_capi('/v2/vod/detail.capi', {'vodId': str(kid)})
        dd = det.get('data') or {}
        by_idx = {}
        sources = []
        for src in dd.get('playSources') or []:
            lst = src.get('list') or []
            ev = ''
            if lst:
                ev = lst[0].get('episodeVodId') or src.get('episodeVodId') or ''
            else:
                ev = src.get('episodeVodId') or ''
            if ev:
                sources.append((src.get('siteId', ''), src.get('name', ''), str(ev)))
            for it in lst:
                for pu in (it.get('playUrls') or []):
                    u = pu.get('url')
                    if u and u.startswith('http'):
                        idx = it.get('index') or 0
                        if idx not in by_idx:
                            by_idx[idx] = u
        for site, name, ev in sources[:4]:
            if len(by_idx) > 0 and by_idx:
                break
            try:
                ep = self._kkdy_capi('/v2/vod/episodes.capi', {'vodId': str(kid), 'siteId': site, 'episodeVodId': ev})
                for it in (ep.get('data') or []):
                    for pu in (it.get('playUrls') or []):
                        u = pu.get('url')
                        if u and u.startswith('http'):
                            idx = it.get('index') or 0
                            if idx not in by_idx:
                                by_idx[idx] = u
            except Exception:
                continue
        return by_idx

    def _kkdy_multi_sources(self, kid):
        det = self._kkdy_capi('/v2/vod/detail.capi', {'vodId': str(kid)})
        dd = det.get('data') or {}
        out = []
        for src in dd.get('playSources') or []:
            lst = src.get('list') or []
            ev = ''
            if lst:
                ev = lst[0].get('episodeVodId') or src.get('episodeVodId') or ''
            else:
                ev = src.get('episodeVodId') or ''
            if ev:
                out.append((src.get('siteId', ''), src.get('name', '') or src.get('siteId', ''), str(ev)))
        return out

    def _kkdy_build_lines(self, kid):
        det = self._kkdy_capi('/v2/vod/detail.capi', {'vodId': str(kid)})
        dd = det.get('data') or {}
        shows = []
        segs = []
        for src in dd.get('playSources') or []:
            site = src.get('siteId', '')
            name = src.get('name', '') or site
            lst = src.get('list') or []
            ev = ''
            if lst:
                ev = lst[0].get('episodeVodId') or src.get('episodeVodId') or ''
            else:
                ev = src.get('episodeVodId') or ''
            eps = []
            if lst:
                for it in lst:
                    u = ''
                    for pu in (it.get('playUrls') or []):
                        if pu.get('url') and pu.get('url').startswith('http'):
                            u = pu['url']
                            break
                    eps.append(str(it.get('title') or '第%s集' % it.get('index')) + '$' + (u or ''))
            elif ev:
                try:
                    ep = self._kkdy_capi('/v2/vod/episodes.capi', {'vodId': str(kid), 'siteId': site, 'episodeVodId': str(ev)})
                    for it in (ep.get('data') or []):
                        u = ''
                        for pu in (it.get('playUrls') or []):
                            if pu.get('url') and pu.get('url').startswith('http'):
                                u = pu['url']
                                break
                        eps.append(str(it.get('title') or '第%s集' % it.get('index')) + '$' + (u or ''))
                except Exception:
                    continue
            eps = [e for e in eps if not e.endswith('$')]
            if eps:
                shows.append(name)
                segs.append(eps)
        return shows, segs

    def _norm_name(self, s):
        import re as _re
        return _re.sub(r'[\s·・:：、,\-—_()（）\[\]【】]+', '', str(s or ''))

    def _cj_search(self, name):
        import urllib.parse as up
        apis = [
            ('暴风', 'https://bfzyapi.com/api.php/provide/vod/?ac=detail&wd='),
            ('量子', 'https://cj.lziapi.com/api.php/provide/vod/?ac=detail&wd='),
            ('红牛', 'https://www.hongniuzy3.com/api.php/provide/vod/?ac=detail&wd='),
            ('极速', 'https://jszyapi.com/api.php/provide/vod/?ac=detail&wd='),
            ('新浪', 'https://api.xinlangapi.com/xinlangapi.php/provide/vod/?ac=detail&wd='),
        ]
        want = name.strip()
        wn = self._norm_name(want)
        kws = [want]
        short = wn[:4] if len(wn) >= 4 else wn
        if short and short != wn and len(short) >= 2:
            kws.append(short)
        out = []
        seen = set()
        for nm, api in apis:
            hits = []
            for kw in kws:
                try:
                    r = self.session.get(api + up.quote(kw), timeout=self.timeout)
                    d = r.json()
                    for it in (d.get('list') or []):
                        t = (it.get('vod_name') or '').strip()
                        tn = self._norm_name(t)
                        if not tn:
                            continue
                        if tn == wn or tn in wn or wn in tn or (len(wn) >= 4 and (wn[:4] in tn or tn[:4] in wn)):
                            eps = []
                            for seg in (it.get('vod_play_url') or '').split('$$$'):
                                for e in seg.split('#'):
                                    if '$' in e:
                                        en, _, eu = e.partition('$')
                                        if eu.startswith('http'):
                                            eps.append(en + '$' + eu)
                            if eps and t not in seen:
                                seen.add(t)
                                hits.append(eps)
                except Exception:
                    continue
                if hits:
                    break
            for eps in hits:
                out.append((nm, eps))
        return out

    def _kkdy_fill(self, vod_name, seg_lists, channel='1'):
        try:
            if not vod_name:
                return
            want = vod_name.strip()
            idx = self._kkdy_index()
            kid = idx.get(want, '')
            if not kid:
                kid = self._kkdy_find_id(vod_name, channel)
            if not kid:
                return
            by_idx = self._kkdy_episode_urls(kid)
            if not by_idx:
                return
            for eps in seg_lists:
                for li, e in enumerate(eps):
                    if '$' not in e:
                        continue
                    name, _, tail = e.partition('$')
                    if tail.startswith('http'):
                        continue
                    u = by_idx.get(li + 1)
                    if u:
                        eps[li] = name + '$' + u
                        em = getattr(self, '_enc_map', None)
                        if em is not None:
                            em[tail] = u
        except Exception:
            pass

    def searchContent(self, key, quick=True, pg='1'):
        return self.searchContentPage(key, quick, pg)

    def _kkdy_capi(self, path, biz):
        import urllib.parse as up
        from Crypto.Cipher import AES
        key_b = b'ayt5wy5afwmwrpb19k9s3psx3dymyd0n'
        iv_b = b'b3t069ijy7pirw0j'
        mac_b = b'te@9fs#5tbf8#dx7zw8nx'
        did, dct, uid = 'e6edcf0842f85bc8', '1714091338933', '5631734'
        fixed = {'os': 'android', 'appId': 'kkdy', 'userChannel': 'c1', 'userLevel': '2'}
        allp = dict(biz)
        allp.update(fixed)
        raw_s = '&'.join(k + '=' + str(allp[k]) for k in sorted(allp))
        ts = str(int(time.time() * 1000))
        dev_s = 'appId=kkdy&deviceCreatedAt=' + dct + '&deviceId=' + did + '&userId=' + uid
        ss = 'get|' + path + '|' + raw_s + '|' + ts + '|' + dev_s + '|'
        sign = hmac.new(mac_b, ss.encode(), hashlib.sha1).hexdigest()
        url_s = '&'.join(k + '=' + up.quote(str(allp[k]), safe='') for k in sorted(allp))
        u = 'https://vcache.qvfic.com' + path + '?' + url_s
        h = {
            'User-Agent': 'com.kk.ysk3.tz12063k/3.1.2 Dalvik/2.1.0 (Linux; U; Android 10; Pixel 3 Build/QQ3A.200805.001)',
            'appId': 'kkdy',
            'os': 'android',
            'appVersion': '3.1.2',
            'package': 'com.kk.ysk3.tz12063k',
            'deviceId': did,
            'deviceCreatedAt': dct,
            'userId': uid,
            'channelId': 'c1',
            'x-d-video': '1',
            'ts': ts,
            'sign': sign
        }
        if getattr(self, '_kkdy_token', ''):
            h['X-Token'] = self._kkdy_token
        r = requests.get(u, headers=h, timeout=self.timeout)
        raw = r.content
        dec = AES.new(key_b, AES.MODE_CBC, iv_b).decrypt(raw[:len(raw) // 16 * 16])
        pad = dec[-1]
        if 1 <= pad <= 16 and all(b == pad for b in dec[-pad:]):
            dec = dec[:-pad]
        return json.loads(dec)

    def _kkdy_resolve_pending(self, enc_id):
        try:
            u = getattr(self, '_enc_map', {}).get(enc_id, '')
            if u:
                return u
            name = getattr(self, '_pending_name', '')
            ch = getattr(self, '_pending_channel', '1')
            if not name:
                return ''
            kid = self._kkdy_find_id(name, ch)
            if not kid:
                return ''
            by_idx = self._kkdy_episode_urls(kid)
            for v in by_idx.values():
                if v and v.startswith('http'):
                    em = getattr(self, '_enc_map', None)
                    if em is not None:
                        em[enc_id] = v
                    return v
            return ''
        except Exception:
            return ''

    def searchContentPage(self, key, quick, pg):
        page = int(pg) if str(pg).isdigit() else 1
        data = self._get('/api.php/v1.vod', {
            'wd': key,
            'limit': '20',
            'page': str(page)
        })
        items = self._map_list(data)
        pagecount = page if len(items) < 20 else page + 1
        return {
            'list': items,
            'page': page,
            'pagecount': pagecount,
            'limit': 20,
            'total': 999999
        }

    def playerContent(self, flag, id, vipFlags):
        parse = 0
        url = id
        header = {
            'User-Agent': 'okhttp/4.1.0',
            'Referer': self.host
        }
        if id.startswith('ETH-') or id.startswith('NBY-') or id.startswith('YYNB-'):
            if id in getattr(self, '_kkdy_resolved', {}):
                u = self._kkdy_resolved[id]
                if u and u.startswith('http'):
                    return {'parse': 0, 'url': u, 'header': header, 'danmaku': ''}
            url = self._kkdy_resolve_pending(id)
            if url and url.startswith('http'):
                self._kkdy_resolved[id] = url
                return {'parse': 0, 'url': url, 'header': header, 'danmaku': ''}
            return {'parse': 1, 'url': id, 'header': header, 'danmaku': ''}
        if not id.startswith('http'):
            parse = 1
        elif not re.search(r'\.(m3u8|mp4|flv|mkv|ts)(\?|$)', id.split('?')[0], re.I):
            if re.search(r'(iqiyi|qq\.com|youku|mgtv|bilibili|sohu|pptv|letv|le\.com)', id):
                parse = 1
            else:
                parse = 1
        if 'm3u8' in url:
            header['User-Agent'] = 'okhttp/4.1.0'
        return {'parse': parse, 'url': url, 'header': header, 'danmaku': ''}

    def localProxy(self, param):
        return [200, 'text/plain', '', '']
