# -*- coding: utf-8 -*-
#yyds
"""
bigboobbettys.com Chaturbate聚合直播站
- 播放：playerContent实时拉详情页提取hls_source m3u8直链
- 分类：按tags筛选在线女主播
"""
import re
from urllib.parse import quote

from base.spider import Spider as BaseSpider


class Spider(BaseSpider):

    def init(self, extend=''):
        self.host = 'https://bigboobbettys.com'
        self.ua = ('Mozilla/5.0 (Linux; Android 14; 22127RK46C) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36')
        self.cats = [
            ('BigBoobs',           '全部大胸'),
            ('BigBoobs,teen',      'Teen'),
            ('BigBoobs,milf',      'MILF'),
            ('BigBoobs,mature',    'Mature'),
            ('BigBoobs,bbw',       'BBW'),
            ('BigBoobs,latina',    'Latina'),
            ('BigBoobs,ebony',     'Ebony'),
            ('BigBoobs,asian',     'Asian'),
            ('BigBoobs,amateur',   'Amateur'),
            ('BigBoobs,blonde',    'Blonde'),
            ('BigBoobs,redhead',   'Redhead'),
            ('BigBoobs,anal',      'Anal'),
            ('BigBoobs,lesbian',   'Lesbian'),
            ('BigBoobs,cosplay',   'Cosplay'),
            ('BigBoobs,new',       'New'),
        ]

    def getName(self):
        return 'BigBoobBettys直播'

    def getDependence(self):
        return []

    def setExtendInfo(self, extend):
        return None

    def _get(self, url):
        return self.fetch(url, headers={
            'User-Agent': self.ua,
            'Referer': self.host + '/',
        })

    def _parse_list_html(self, html):
        out = []
        cards = re.findall(
            r'<a href="(https://bigboobbettys\.com/webcams/[^"]+?)"[^>]*class="video-link[^"]*"[^>]*>.*?'
            r'<img[^>]+src="([^"]+)"[^>]*alt="([^"]+)"',
            html, re.S)
        for href, thumb, alt in cards:
            m = re.search(r'/webcams/([^"-]+)-cam\.html', href)
            if not m:
                continue
            username = m.group(1)
            out.append({
                'vod_id': username,
                'vod_name': alt.replace(' webcam', '').strip() or username,
                'vod_pic': thumb,
                'vod_remarks': 'LIVE',
            })
        return out

    def homeContent(self, filter=None):
        classes = [{'type_name': name, 'type_id': tags}
                   for tags, name in self.cats]
        return {'class': classes, 'filters': {}, 'list': []}

    def homeVideoContent(self):
        url = (self.host + '/core/ajax.loadModels.php'
               '?gender%5B0%5D=f&status%5B0%5D=online&tags%5B0%5D=BigBoobs&page=1')
        r = self._get(url)
        return {'list': self._parse_list_html(r.text)}

    def categoryContent(self, tid, pg=1, extend=None, filter=None):
        pg = int(pg or 1)
        tags = tid
        url = (self.host + '/core/ajax.loadModels.php'
               f'?gender%5B0%5D=f&status%5B0%5D=online&tags%5B0%5D={quote(tags)}&page={pg}')
        r = self._get(url)
        items = self._parse_list_html(r.text)
        pagecount = 99 if 'loadMore' in r.text and len(items) > 0 else pg
        return {
            'list': items,
            'page': pg,
            'pagecount': pagecount,
            'limit': 30,
            'total': pagecount * 30,
        }

    def detailContent(self, ids):
        username = ids[0] if isinstance(ids, list) else ids
        pic = f'https://thumb.live.mmcdn.com/ri/{username}.jpg'
        vod = {
            'vod_id': username,
            'vod_name': username,
            'vod_pic': pic,
            'type_name': 'Live Cam',
            'vod_remarks': 'LIVE',
            'vod_content': f'Chaturbate直播 - {username}',
            'vod_play_from': '直播',
            'vod_play_url': f'直播${username}',
        }
        return {'list': [vod]}

    def _extract_hls(self, html):
        """从详情页提取hls_source m3u8"""
        m = re.search(r'hls_source\\u0022:\s*\\u0022(https?://.*?)\\u0022', html)
        if not m:
            # 兜底：直接搜llhls.m3u8
            m = re.search(r'(https?://[^\s\\"]*llhls\.m3u8[^\s\\"]*)', html)
        if not m:
            return None
        raw = m.group(1)
        raw = raw.replace('\\u002D', '-').replace('\\u003D', '=')
        raw = raw.replace('\\u0026', '&').replace('\\u002F', '/')
        raw = raw.replace('\\/', '/').replace('\\"', '"')
        return raw

    def playerContent(self, flag, id, vipFlags=None):
        username = id
        detail_url = f'{self.host}/webcams/{username}-cam.html'
        r = self._get(detail_url)
        hls = self._extract_hls(r.text)
        if not hls:
            return {'parse': 0, 'playUrl': '', 'url': '', 'header': {}}
        return {
            'parse': 0,
            'playUrl': '',
            'url': hls,
            'header': {
                'User-Agent': self.ua,
                'Referer': 'https://chaturbate.com/',
                'Origin': 'https://chaturbate.com',
            },
        }

    def searchContent(self, key, quick=1, pg=1):
        pg = int(pg or 1)
        url = (self.host + '/core/ajax.loadModels.php'
               f'?gender%5B0%5D=f&status%5B0%5D=online&page={pg}')
        r = self._get(url)
        items = self._parse_list_html(r.text)
        kw = key.lower().strip()
        return [x for x in items if kw in x['vod_name'].lower()]

    def localProxy(self, param):
        return {}

    def isVideoFormat(self, url):
        return True

    def manualVideoCheck(self):
        return False

    def destroy(self):
        pass
