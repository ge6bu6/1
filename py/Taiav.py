# -*- coding: utf-8 -*-
# 🏠 站点: Taiav
# 👤 作者: 无聊
# 📅 日期: 2026-11-11
# 🌐 来源: 本地候选静态审计（站点来源见修改前备份）
import re
import json
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urljoin, urlencode

try:
    from base.spider import Spider as BaseSpider
except Exception:
    class BaseSpider:
        def __init__(self):
            pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

HOST = "https://taiav.com"

# ============ 标签分组（discover 页全量 499 标签，按语义归并 6 组） ============
TAG_MAKER = [
    ("糖心vlog", "糖心vlog"), ("麻豆传媒映画", "麻豆传媒映画"), ("蜜桃影像传媒", "蜜桃影像传媒"),
    ("星空无限传媒", "星空无限传媒"), ("香蕉视频", "香蕉视频"), ("杏吧", "杏吧"),
    ("天美传媒", "天美传媒"), ("精东影业", "精东影业"), ("皇家华人传媒", "皇家华人传媒"),
    ("焦點傳媒", "焦點傳媒"), ("起點傳媒", "起點傳媒"), ("性視界傳媒", "性視界傳媒"),
    ("大象传媒", "大象传媒"), ("兔子先生", "兔子先生"), ("放克娛樂", "放克娛樂"),
    ("糖心Vlog", "糖心Vlog"), ("扣扣傳媒", "扣扣傳媒"), ("公雞俱樂部", "公雞俱樂部"),
    ("SA國際傳媒", "SA國際傳媒"), ("麻豆US", "麻豆US"), ("PsychopornTW", "PsychopornTW"),
    ("果冻传媒出品", "果冻传媒出品"), ("PANS", "PANS"), ("水果派", "水果派"),
    ("Ed Mosaic", "Ed Mosaic"), ("爱神传媒", "爱神传媒"), ("JVID", "JVID"),
    ("91制片厂", "91制片厂"), ("91Fans", "91Fans"), ("91茄子", "91茄子"),
    ("91兔兔", "91兔兔"), ("91D先生", "91D先生"), ("91xx君", "91xx君"),
    ("91Lucky", "91Lucky"), ("絕對領域傳媒", "絕對領域傳媒"), ("渡邊傳媒", "渡邊傳媒"),
    ("抖阴", "抖阴"), ("紅斯燈影像", "紅斯燈影像"), ("葫蘆影業", "葫蘆影業"),
    ("烏托邦", "烏托邦"), ("蜜桃君", "蜜桃君"), ("内涵AV", "内涵AV"),
    ("小爱神", "小爱神"), ("天使映画", "天使映画"), ("十三号天使", "十三号天使"),
    ("逼哩逼哩", "逼哩逼哩"), ("果哥出品", "果哥出品"), ("三只狼傳媒", "三只狼傳媒"),
    ("MisAV", "MisAV"), ("不见星空", "不见星空"), ("甜心宝贝", "甜心宝贝"),
    ("西瓜影视", "西瓜影视"), ("辣椒原創", "辣椒原創"), ("麻麻傳媒", "麻麻傳媒"),
    ("汝工作室", "汝工作室"), ("乐播传媒", "乐播传媒"), ("杏吧王安全", "杏吧王安全"),
    ("老虎菜原创", "老虎菜原创"), ("天使もえ", "天使もえ"), ("冠希傳媒", "冠希傳媒"),
    ("杏吧欧阳克", "杏吧欧阳克"), ("猛料視頻傳媒", "猛料視頻傳媒"),
]

TAG_ACTOR = [
    ("主播", "主播"), ("Kiki_2025", "Kiki_2025"), ("斑斑", "斑斑"), ("孟若羽", "孟若羽"),
    ("吴芳宜", "吴芳宜"), ("Ellie", "Ellie"), ("苏畅", "苏畅"), ("小Q小K", "小Q小K"),
    ("夏晴子", "夏晴子"), ("HongKongDoll", "HongKongDoll"), ("小水水", "小水水"),
    ("李蓉蓉", "李蓉蓉"), ("吴梦梦", "吴梦梦"), ("饼干姐姐", "饼干姐姐"), ("沈娜娜", "沈娜娜"),
    ("柚子猫", "柚子猫"), ("NicoLove", "NicoLove"), ("狐不妖", "狐不妖"), ("金宝娜", "金宝娜"),
    ("辛尤里", "辛尤里"), ("粉味芒果", "粉味芒果"), ("桥本香菜", "桥本香菜"),
    ("李娜娜", "李娜娜"), ("情深叉喔", "情深叉喔"), ("深海杀人鲸", "深海杀人鲸"),
    ("NANA", "NANA"), ("仙儿媛", "仙儿媛"), ("艾熙", "艾熙"), ("米菲兔", "米菲兔"),
    ("下面有根棒棒糖", "下面有根棒棒糖"), ("优娜", "优娜"), ("温芮欣", "温芮欣"),
    ("羽芮", "羽芮"), ("kittyxkum", "kittyxkum"), ("季妍希", "季妍希"), ("林思妤", "林思妤"),
    ("吴文淇", "吴文淇"), ("黑亚当", "黑亚当"), ("room_103", "room_103"), ("捅主任", "捅主任"),
    ("AV Jiali", "AV Jiali"), ("Npxvip", "Npxvip"), ("米胡桃", "米胡桃"), ("懒懒猪", "懒懒猪"),
    ("YOSHIE", "YOSHIE"), ("TWIN", "TWIN"), ("粉色情人", "粉色情人"), ("莉娜", "莉娜"),
    ("艾玛", "艾玛"), ("Hanson", "Hanson"), ("刘玥", "刘玥"), ("Andmlove", "Andmlove"),
    ("宋南伊", "宋南伊"), ("凯蒂", "凯蒂"), ("糖糖", "糖糖"), ("波多野结衣", "波多野结衣"),
    ("苏语棠", "苏语棠"), ("小敏儿", "小敏儿"), ("Miuzxc", "Miuzxc"), ("萌崽儿", "萌崽儿"),
    ("宽哥DrSex", "宽哥DrSex"), ("米欧", "米欧"), ("恩凯", "恩凯"), ("苡若", "苡若"),
    ("娃娃", "娃娃"), ("米娜学姐", "米娜学姐"), ("凌薇", "凌薇"), ("露露", "露露"),
    ("香菱", "香菱"), ("乐奈子", "乐奈子"), ("狠台北", "狠台北"), ("梁佳芯", "梁佳芯"),
    ("篠田ゆう", "篠田ゆう"), ("LonelyMeow", "LonelyMeow"), ("梁芸菲", "梁芸菲"),
    ("applecptv", "applecptv"), ("驯鹿", "驯鹿"), ("艾秋", "艾秋"), ("唐雨菲", "唐雨菲"),
    ("韩棠", "韩棠"), ("Yui Peachpie", "Yui Peachpie"), ("樱樱", "樱樱"), ("秦可欣", "秦可欣"),
    ("捏面人啾啾", "捏面人啾啾"), ("猫爪影像", "猫爪影像"), ("唐伯虎", "唐伯虎"),
    ("林嫣", "林嫣"), ("小晚酱", "小晚酱"), ("噗噗", "噗噗"), ("白熙雨", "白熙雨"),
    ("夜夜", "夜夜"), ("玩偶姐姐", "玩偶姐姐"), ("张雅婷", "张雅婷"), ("小欣奈", "小欣奈"),
    ("白允儿", "白允儿"), ("冉冉学姐", "冉冉学姐"), ("宇宙列车", "宇宙列车"),
    ("苏樱花", "苏樱花"), ("姚宛儿", "姚宛儿"), ("尤莉", "尤莉"), ("魏乔安", "魏乔安"),
    ("玥可岚", "玥可岚"), ("李允熙", "李允熙"), ("管明美", "管明美"), ("狮子座", "狮子座"),
    ("NaomiiiHub", "NaomiiiHub"), ("周甯", "周甯"), ("樱空桃桃", "樱空桃桃"),
    ("锅锅酱", "锅锅酱"), ("雪千夏", "雪千夏"), ("小二先生", "小二先生"), ("闵儿", "闵儿"),
    ("安安老师", "安安老师"), ("Ashisyourlove", "Ashisyourlove"), ("可可", "可可"),
    ("香月怜", "香月怜"), ("小桃酱", "小桃酱"), ("倪娜", "倪娜"), ("苏清歌", "苏清歌"),
    ("费爵娜", "费爵娜"), ("泡沫浴", "泡沫浴"), ("玖玖", "玖玖"), ("赖畇希", "赖畇希"),
    ("苏念瑾", "苏念瑾"), ("Avove", "Avove"), ("小猫咪", "小猫咪"), ("鸡教练", "鸡教练"),
    ("唐茜", "唐茜"), ("徐蕾", "徐蕾"), ("艾悠", "艾悠"), ("宋雨川", "宋雨川"),
    ("钟宛冰", "钟宛冰"), ("Cola酱", "Cola酱"), ("明里つむぎ", "明里つむぎ"), ("欣欣", "欣欣"),
    ("曾强", "曾强"), ("你的小太阳", "你的小太阳"), ("亦可姐姐", "亦可姐姐"),
    ("三上悠亜", "三上悠亜"), ("派大星", "派大星"), ("Sweetie Fox", "Sweetie Fox"),
    ("松本いちか", "松本いちか"), ("OBOKOZU", "OBOKOZU"), ("甜甜", "甜甜"), ("美酱", "美酱"),
    ("浜崎真緒", "浜崎真緒"), ("yurinslittlepeach", "yurinslittlepeach"), ("Elle Lee", "Elle Lee"),
    ("楚梦舒", "楚梦舒"), ("铃木美咲", "铃木美咲"), ("大槻ひびき", "大槻ひびき"),
    ("琪琪", "琪琪"), ("林雅儿", "林雅儿"), ("小熊奈奈", "小熊奈奈"), ("黑椒盖饭", "黑椒盖饭"),
    ("DemiFairyTW", "DemiFairyTW"), ("露娜", "露娜"), ("Yuna", "Yuna"), ("Yua", "Yua"),
    ("黑杰克", "黑杰克"), ("芽芽", "芽芽"), ("Luna Okko", "Luna Okko"), ("苏小涵", "苏小涵"),
    ("sunwall", "sunwall"), ("医生琪琪", "医生琪琪"), ("舒可芯", "舒可芯"),
    ("八月未央", "八月未央"), ("工藤静香", "工藤静香"), ("神宮寺ナオ", "神宮寺ナオ"),
    ("林千夜", "林千夜"), ("鸡蛋饼", "鸡蛋饼"), ("羞羞兔", "羞羞兔"), ("是小桃呢", "是小桃呢"),
    ("白峰ミウ", "白峰ミウ"), ("北野未奈", "北野未奈"), ("蜜苏", "蜜苏"), ("めぐり", "めぐり"),
    ("沈湘妮", "沈湘妮"), ("深田えいみ", "深田えいみ"), ("许木学长", "许木学长"),
    ("菜菜最花", "菜菜最花"), ("Happy Sofia Nana", "Happy Sofia Nana"), ("Eva Elfie", "Eva Elfie"),
    ("爱玩熊熊", "爱玩熊熊"), ("佐美", "佐美"), ("跳跳羊", "跳跳羊"), ("橙子", "橙子"),
    ("白沛瑶", "白沛瑶"), ("森日向子", "森日向子"), ("Mia", "Mia"), ("邓紫晴", "邓紫晴"),
    ("FSS冯珊珊", "FSS冯珊珊"), ("小晗喵", "小晗喵"), ("犬九", "犬九"),
    ("黑猫露娜酱", "黑猫露娜酱"), ("樱花小猫", "樱花小猫"), ("一条肌肉狗", "一条肌肉狗"),
    ("Pussy Hunter", "Pussy Hunter"), ("黎儿", "黎儿"), ("北野爱", "北野爱"), ("葵司", "葵司"),
    ("小鹿酱", "小鹿酱"), ("菠萝啤", "菠萝啤"), ("晨汐", "晨汐"), ("杨晨晨", "杨晨晨"),
    ("deerlong", "deerlong"), ("爱丝袜的Vivian姐", "爱丝袜的Vivian姐"), ("荔枝", "荔枝"),
    ("多乙", "多乙"), ("美杜莎", "美杜莎"), ("Make性专家", "Make性专家"), ("斯文禽兽", "斯文禽兽"),
    ("奶咪", "奶咪"), ("乐乐", "乐乐"), ("佐山愛", "佐山愛"), ("阿朱", "阿朱"),
    ("鈴木さとみ", "鈴木さとみ"), ("楓ふうあ", "楓ふうあ"), ("兔美酱", "兔美酱"),
    ("MollyRedWolf", "MollyRedWolf"), ("美縫有約", "美縫有約"), ("晗wink", "晗wink"),
    ("yooheejade", "yooheejade"), ("西门吹穴", "西门吹穴"), ("师师", "师师"),
    ("Yuumeilyn", "Yuumeilyn"), ("水川堇", "水川堇"), ("董悦悦", "董悦悦"), ("RONA", "RONA"),
    ("雪霏", "雪霏"), ("苏娅", "苏娅"), ("寻小小", "寻小小"), ("乔安", "乔安"),
    ("张芸熙", "张芸熙"), ("袁子仪", "袁子仪"), ("青空ひかり", "青空ひかり"),
    ("佐々木あき", "佐々木あき"), ("星野兔", "星野兔"), ("Hidori rose", "Hidori rose"),
    ("涵涵", "涵涵"), ("御梦子", "御梦子"), ("紫蛋", "紫蛋"), ("晨晨", "晨晨"),
    ("雷梦娜", "雷梦娜"), ("小遥", "小遥"), ("施子涵", "施子涵"), ("miru", "miru"),
    ("李薇薇", "李薇薇"), ("七ツ森りり", "七ツ森りり"), ("白靖寒", "白靖寒"),
    ("小早川怜子", "小早川怜子"), ("通野未帆", "通野未帆"), ("JULIA", "JULIA"),
    ("浵卡Tokar", "浵卡Tokar"), ("喵叽小糯", "喵叽小糯"), ("梓怡学妹", "梓怡学妹"),
    ("瑶瑶", "瑶瑶"), ("西野加奈", "西野加奈"), ("困困狗", "困困狗"), ("仙仙桃", "仙仙桃"),
    ("MasukuChan", "MasukuChan"), ("猫猫碎冰冰", "猫猫碎冰冰"), ("桃乃木かな", "桃乃木かな"),
    ("姫咲はな", "姫咲はな"), ("山本しゅり", "山本しゅり"), ("莫夕慈", "莫夕慈"),
    ("花沢ひまり", "花沢ひまり"), ("桜空もも", "桜空もも"), ("奶咪酱", "奶咪酱"),
    ("波妮", "波妮"), ("神木麗", "神木麗"), ("江波りゅう", "江波りゅう"), ("夏禹熙", "夏禹熙"),
    ("本庄鈴", "本庄鈴"), ("苏璇", "苏璇"), ("优咪", "优咪"), ("铃木君", "铃木君"),
    ("鱿鱼", "鱿鱼"), ("美谷朱里", "美谷朱里"), ("菲菲", "菲菲"), ("麻酥酥", "麻酥酥"),
    ("娜美妖姬", "娜美妖姬"), ("桃桃", "桃桃"), ("猫先生", "猫先生"), ("酥酥", "酥酥"),
    ("ooxxblack", "ooxxblack"), ("蜡笔甜心", "蜡笔甜心"), ("嫩小兔", "嫩小兔"),
    ("Kovicki", "Kovicki"), ("小倉由菜", "小倉由菜"), ("涼森れむ", "涼森れむ"),
    ("王以欣", "王以欣"), ("Meriolchan", "Meriolchan"), ("梁幂", "梁幂"), ("林沁儿", "林沁儿"),
    ("弥生みづき", "弥生みづき"), ("相沢みなみ", "相沢みなみ"), ("白桃はな", "白桃はな"),
    ("绫波丽", "绫波丽"), ("天使もえ", "天使もえ"), ("司雨", "司雨"), ("宸荨樱桃", "宸荨樱桃"),
    ("橋本ありな", "橋本ありな"), ("翁雨澄", "翁雨澄"), ("胡子哥", "胡子哥"),
    ("棉花糖糖", "棉花糖糖"), ("喵喵", "喵喵"), ("点点", "点点"), ("奶凶大人", "奶凶大人"),
    ("Svet19", "Svet19"),
]

TAG_THEME = [
    ("巨乳", "巨乳"), ("美腿", "美腿"), ("苗條", "苗條"), ("美尻", "美尻"),
    ("自慰", "自慰"), ("口交", "口交"), ("中出", "中出"), ("美少女", "美少女"),
    ("探花", "探花"), ("痴女", "痴女"), ("短髮", "短髮"), ("誘惑", "誘惑"),
    ("人妻", "人妻"), ("白虎", "白虎"), ("腳交", "腳交"), ("淫亂", "淫亂"),
    ("出軌", "出軌"), ("多P", "多P"), ("長身", "長身"), ("不倫", "不倫"),
    ("潮吹", "潮吹"), ("調教", "調教"), ("乳交", "乳交"), ("熟女", "熟女"),
    ("素人", "素人"), ("口爆", "口爆"), ("顏射", "顏射"), ("露出", "露出"),
    ("情侶", "情侶"), ("按摩", "按摩"), ("深喉", "深喉"), ("乳液", "乳液"),
    ("拘束", "拘束"), ("NTR", "NTR"), ("進犯", "進犯"), ("媚藥", "媚藥"),
    ("痙攣", "痙攣"), ("貧乳", "貧乳"), ("蘿莉原創", "蘿莉原創"), ("愛豆", "愛豆"),
    ("肛交", "肛交"), ("凌辱", "凌辱"), ("溫泉", "溫泉"), ("汽車", "汽車"),
    ("貧乳蘿莉", "貧乳蘿莉"), ("綑綁", "綑綁"), ("風俗娘", "風俗娘"), ("蘿莉", "蘿莉"),
    ("假日主题", "假日主题"), ("夫目前犯", "夫目前犯"), ("女同性戀", "女同性戀"),
    ("男M", "男M"), ("接吻", "接吻"), ("集團進犯", "集團進犯"), ("泥醉", "泥醉"),
    ("學校", "學校"), ("少女", "少女"), ("廁所", "廁所"), ("童貞", "童貞"),
    ("痴漢", "痴漢"), ("醫生", "醫生"), ("電車", "電車"), ("放尿", "放尿"),
    ("處女作-引退作", "處女作-引退作"), ("復仇", "復仇"), ("搜查官", "搜查官"),
    ("泳池", "泳池"), ("美容院", "美容院"), ("瞬間插入", "瞬間插入"), ("年齡差", "年齡差"),
    ("感謝祭", "感謝祭"), ("圖書館", "圖書館"), ("催眠", "催眠"), ("時間停止", "時間停止"),
    ("醜男", "醜男"), ("監獄", "監獄"), ("未亡人", "未亡人"), ("便利店", "便利店"),
    ("白菜妹妹", "白菜妹妹"), ("香草少女", "香草少女"),
]

TAG_CLOTH = [
    ("黑絲", "黑絲"), ("絲襪", "絲襪"), ("過膝襪", "過膝襪"), ("吊帶襪", "吊帶襪"),
    ("漁網", "漁網"), ("Cosplay", "Cosplay"), ("眼鏡娘", "眼鏡娘"), ("OL", "OL"),
    ("迷你裙", "迷你裙"), ("肉絲", "肉絲"), ("校服", "校服"), ("運動裝", "運動裝"),
    ("女僕", "女僕"), ("JK", "JK"), ("護士", "護士"), ("旗袍", "旗袍"),
    ("兔女郎", "兔女郎"), ("女教師", "女教師"), ("和服", "和服"), ("獸耳", "獸耳"),
    ("水着", "水着"), ("家庭教師", "家庭教師"), ("空姐", "空姐"), ("婚紗", "婚紗"),
    ("家政婦", "家政婦"),
]

TAG_AREA = [
    ("中国", "中国"), ("金髪洋物", "金髪洋物"), ("台湾", "台湾"), ("Korean Bj", "Korean Bj"),
    ("Korean", "Korean"), ("Thailand", "Thailand"), ("香港美少女", "香港美少女"),
    ("黑人", "黑人"), ("Vietnam", "Vietnam"), ("Asian萝莉", "Asian萝莉"),
    ("日本", "日本"), ("Philippines", "Philippines"),
]

TAG_PLAT = [
    ("Onlyfans", "Onlyfans"), ("錄像", "錄像"), ("SWAG", "SWAG"), ("Fansly", "Fansly"),
    ("中文字幕", "中文字幕"), ("Hentai", "Hentai"), ("其他", "其他"), ("網友分享", "網友分享"),
    ("4小時以上", "4小時以上"), ("3P", "3P"), ("FC2", "FC2"),
]

# 标签大组：前缀 -> (显示名, 图标, 标签列表)
TAG_GROUPS = {
    'maker': ('🏢片商传媒', TAG_MAKER),
    'actor': ('👩女优演员', TAG_ACTOR),
    'theme': ('🔥题材玩法', TAG_THEME),
    'cloth': ('👗服装装扮', TAG_CLOTH),
    'area': ('🌍地区国籍', TAG_AREA),
    'plat': ('⭐平台专区', TAG_PLAT),
}


class Spider(BaseSpider):

    def init(self, extend=""):
        self.extend = extend or ""
        try:
            self.cfg = json.loads(extend) if extend.strip().startswith('{') else {}
        except Exception:
            self.cfg = {}
        self.host = self.cfg.get("host", HOST).rstrip('/')
        self.headers = {"User-Agent": UA, "Referer": self.host + "/"}
        self._seen = {}  # 分页去重：key -> set

    def getName(self):
        return 'Taiav'

    def getDependence(self):
        return []

    def isVip(self):
        return False

    def getHeaders(self):
        return {"User-Agent": UA, "Referer": self.host + "/"}

    def destroy(self):
        pass

    def isVideoFormat(self, url):
        return any(x in (url or '').lower() for x in ['.m3u8', '.mp4', '.flv', '.mkv', '.ts', '.mpd'])

    def manualVideoCheck(self):
        return False

    # ---- 网络层 ----
    def _fetch(self, url):
        import urllib.request
        import gzip
        u = url if url.startswith('http') else self.host + url
        req = urllib.request.Request(u, headers=self.headers)
        try:
            resp = urllib.request.urlopen(req, timeout=15)
            data = resp.read()
            if resp.headers.get('Content-Encoding') == 'gzip':
                data = gzip.decompress(data)
            return data
        except Exception:
            return b''

    def _text(self, url):
        d = self._fetch(url)
        if not d:
            return ''
        for enc in ('utf-8', 'gbk', 'big5'):
            try:
                return d.decode(enc)
            except Exception:
                continue
        return d.decode('utf-8', 'ignore')

    # ---- 首页 ----
    def homeContent(self, filter):
        classes = [
            {'type_id': 'cat_root', 'type_name': '🎬影片分类'},
            {'type_id': 'grp_maker', 'type_name': '🏢片商传媒'},
            {'type_id': 'grp_actor', 'type_name': '👩女优演员'},
            {'type_id': 'grp_theme', 'type_name': '🔥题材玩法'},
            {'type_id': 'grp_cloth', 'type_name': '👗服装装扮'},
            {'type_id': 'grp_area', 'type_name': '🌍地区国籍'},
            {'type_id': 'grp_plat', 'type_name': '⭐平台专区'},
        ]
        filters = {'cat_root': [{'key': 'sub', 'name': '分类', 'value': [
            {'n': '无码', 'v': 'cat_无码'}, {'n': '有码', 'v': 'cat_有码'},
            {'n': '国产AV', 'v': 'cat_国产AV'}, {'n': '网红主播', 'v': 'cat_网红主播'}
        ]}]}
        return {'class': classes, 'filters': filters, 'list': self._home_videos()}

    def homeVideoContent(self):
        return {'list': self._home_videos()}

    def _home_videos(self):
        html = self._text('/cn/')
        return self._cards(html)

    # ---- 分类列表 + 翻页（含标签大组文件夹 + 标签内容） ----
    def categoryContent(self, tid, pg, filter, extend):
        page = max(1, int(pg)) if str(pg).isdigit() else 1

        # 标签大组文件夹：返回该组下的标签 folder 列表
        if tid.startswith('grp_'):
            return self._group_folders(tid[4:], page)
        if tid == 'cat_root':
            selected = (extend or {}).get('sub', '') if isinstance(extend, dict) else ''
            if selected.startswith('cat_'):
                tid = selected
            else:
                tid = 'cat_无码'

        key = 'cat_%s' % tid
        if page == 1:
            self._seen[key] = set()
        seen = self._seen.setdefault(key, set())

        if tid.startswith('cat_'):
            path = '/cn/category/' + quote(tid[4:])
        elif tid.startswith('tag_'):
            path = '/cn/tag/' + quote(tid[4:])
        else:
            return {'list': [], 'page': page, 'pagecount': 1, 'limit': 20, 'total': 0}

        url = '%s?page=%d' % (path, page)
        html = self._text(url)
        videos = self._cards(html)
        videos = [v for v in videos if v['vod_id'] not in seen]
        for v in videos:
            seen.add(v['vod_id'])
        # Taiav 标签/分类实测固定每页 15 条；不能用 20 条判断末页。
        return {'list': videos, 'page': page,
                'pagecount': page + 1 if len(videos) >= 15 else page,
                'limit': 15, 'total': 0}

    def _group_folders(self, gname, page):
        """标签大组 → 标签 folder 列表（分页，每页 60 个）"""
        info = TAG_GROUPS.get(gname)
        if not info:
            return {'list': [], 'page': page, 'pagecount': 1, 'limit': 0, 'total': 0}
        _, tags = info
        per = 60
        total_pages = (len(tags) + per - 1) // per
        start = (page - 1) * per
        chunk = tags[start:start + per]

        def folder_item(pair):
            name, label = pair
            # 用该标签第一页首个视频封面作为文件夹封面；取不到时留空，不能伪造图片。
            cover = ''
            try:
                html = self._text('/cn/tag/%s?page=1' % quote(name, safe=''))
                cards = self._cards(html)
                if cards:
                    cover = cards[0].get('vod_pic') or ''
            except Exception:
                cover = ''
            return {
                'vod_id': 'tag_%s' % name,
                'vod_name': label,
                'vod_pic': cover,
                'vod_remarks': '标签',
                'vod_tag': 'folder',
                'style': {'type': 'rect', 'ratio': 1.0},
            }

        with ThreadPoolExecutor(max_workers=4) as pool:
            folders = list(pool.map(folder_item, chunk))
        return {'list': folders, 'page': page, 'pagecount': total_pages,
                'limit': per, 'total': len(tags)}

    # ---- 详情 ----
    def detailContent(self, ids):
        if ids is None or ids == "" or (isinstance(ids, (list, tuple)) and (not ids or ids[0] is None or ids[0] == "")):
            return {"list": []}
        vid = (ids[0] if isinstance(ids, (list, tuple)) else ids) if isinstance(ids, (list, tuple)) else str(ids)
        vid = str(vid).strip()
        # 文件夹（标签）→ 转 categoryContent 展示该标签内容列表
        if vid.startswith('grp_'):
            return self.categoryContent(vid, 1, False, {})
        if vid.startswith('tag_'):
            # 文件夹点击在部分壳中只消费详情第一页，不会继续调用 categoryContent。
            # 这里主动合并后续分页，避免文件夹内只显示首 20 条。
            tag = vid[4:]
            return {'list': self._tag_all(tag, max_pages=20)}
        html = self._text('/cn/movie/' + vid)
        vod = self._detail(html, vid)
        return {'list': [vod]}

    def _tag_cover(self, tag):
        try:
            cards = self._cards(self._text('/cn/tag/%s?page=1' % quote(tag, safe='')))
            return cards[0].get('vod_pic', '') if cards else ''
        except Exception:
            return ''

    def _tag_all(self, tag, max_pages=20):
        """文件夹详情合并有限页，兼容不会二次触发分页的壳。"""
        out = []
        seen = set()
        for page in range(1, max_pages + 1):
            cards = self._cards(self._text('/cn/tag/%s?page=%d' % (quote(tag, safe=''), page)))
            fresh = [v for v in cards if v.get('vod_id') not in seen]
            for v in fresh:
                seen.add(v.get('vod_id'))
            out.extend(fresh)
            if len(cards) < 15 or not fresh:
                break
        return out

    def _detail(self, html, vid):
        name = ''
        pic = ''
        content = ''
        tag = ''
        m = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
        if m:
            name = m.group(1).strip()
        if not name:
            m = re.search(r'<title>([^<]*)</title>', html)
            if m:
                name = m.group(1).strip()
        m = re.search(r'<img[^>]+src="([^"]+)"[^>]+alt="[^"]*"[^>]*>', html)
        if m:
            pic = m.group(1)
        # 简介
        m = re.search(r'视频简介[^<]*</[^>]*>\s*<[^>]*>\s*<[^>]*>\s*<p[^>]*>([\s\S]*?)</p>', html)
        if m:
            content = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        if not content:
            m = re.search(r'<p class="uk-margin-small-top">([\s\S]*?)</p>', html)
            if m:
                content = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        # 标签（过滤热度数字）
        tags = re.findall(r'/cn/tag/([^"\'?]+)"[^>]*>([^<]+)</a>', html)
        tag_names = []
        for _, t in tags[:15]:
            t = re.sub(r'\s*\(\d+\)', '', t).strip()
            t = re.sub(r'\s*·\s*\d+$', '', t).strip()
            if t and t not in tag_names:
                tag_names.append(t)
        tag = ','.join(tag_names)

        play_from, play_url = self._build_play(vid)
        vod = {
            'vod_id': vid,
            'vod_name': name or vid,
            'vod_pic': pic,
            'vod_content': content,
            'vod_actor': '',
            'vod_tag': tag,
            'vod_play_from': play_from,
            'vod_play_url': play_url,
        }
        return vod

    def _build_play(self, vid):
        m3u8 = self._get_m3u8(vid)
        if m3u8:
            play_from = '🔵高清720P'
            play_url = '播放$' + m3u8
        else:
            play_from = '🔵高清720P'
            play_url = '播放$' + vid
        return play_from, play_url

    def _get_m3u8(self, vid):
        url = '/api/getmovie?type=1280&id=%s' % vid
        txt = self._text(url)
        if not txt:
            return None
        try:
            data = json.loads(txt)
        except Exception:
            return None
        m3u8 = data.get('m3u8')
        if not m3u8:
            return None
        if m3u8.startswith('http'):
            return m3u8
        return self.host + m3u8

    # ---- 搜索 ----
    def searchContent(self, key, quick, pg="1"):
        page = max(1, int(pg)) if str(pg).isdigit() else 1
        url = '/cn/search?q=%s&page=%d' % (quote(key), page)
        html = self._text(url)
        return {'list': self._cards(html), 'page': page}

    # ---- 播放解析 ----
    def playerContent(self, flag, id, vipFlags=None):
        url = id
        if not id.startswith('http'):
            url = self._get_m3u8(id) or id
        return {'parse': 0, 'url': url,
                'header': {'User-Agent': UA, 'Referer': self.host + '/'}}

    # ---- 卡片解析 ----
    def _cards(self, html):
        videos = []
        seen = set()
        for m in re.finditer(r'<div data-id=\'(?:\")?([a-f0-9]{20,})(?:\")?\'.*?<img[^>]+src="([^"]+)"[^>]+alt="([^"]+)"', html, re.S):
            vid = m.group(1)
            pic = m.group(2)
            name = m.group(3).strip()
            if vid in seen:
                continue
            seen.add(vid)
            videos.append({
                'vod_id': vid,
                'vod_name': name,
                'vod_pic': pic,
                'vod_remarks': '',
            })
        return videos
