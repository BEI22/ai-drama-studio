"""Deterministic heuristics powering :class:`MockLLMProvider`.

These are **not** AI. They are small, deterministic rules that turn a story text
into structurally valid Bible content so the whole pipeline can be exercised
without an API key (PRD section 37 item 8, "Mock LLM Provider").

Nothing here is imported by business code -- only by the mock provider, which is
selected via ``LLM_PROVIDER=mock``. Every result is tagged so the UI can say so
out loud rather than passing heuristic output off as model output.
"""

from __future__ import annotations

import re
from collections import Counter

# --------------------------------------------------------------------------- #
# Names
# --------------------------------------------------------------------------- #
# Common Chinese surnames, used only to *anchor* candidate name matches.
SURNAMES = (
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐"
    "费廉岑薛雷贺倪汤滕殷罗毕郝安常乐于时傅皮卞齐康伍余元卜顾孟平黄"
    "和穆萧尹姚邵汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁"
    "杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌"
    "霍虞万支柯管卢莫房裘缪干解应宗丁宣邓郁单杭洪包诸左石崔吉钮龚程"
    "邢滑裴陆荣翁荀羊惠甄曲封芮储段富巫乌焦巴牧隗山谷车侯全班仰秋仲"
    "伊宫宁仇栾暴甘厉戎祖武符刘景詹束龙叶幸司韶郜黎蓟薄印宿白怀蒲鄂"
    "索咸籍赖卓蔺屠蒙池乔胥能苍双闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍桑"
    "桂濮牛寿通边扈燕冀浦尚农温别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易"
    "慎戈廖庾终暨居衡步都耿满弘匡国文寇广禄阙东欧殳沃利蔚越夔隆师巩"
    "聂晁勾敖融冷訾辛阚那简饶空曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺"
    "权逯盖益桓公"
)

# Tokens that look like names but are ordinary words. Kept deliberately broad:
# a false positive here surfaces as a bogus character in the UI.
_NAME_STOPWORDS = {
    "时间",
    "时代",
    "时候",
    "自己",
    "自觉",
    "人生",
    "人口",
    "决定",
    "决心",
    "意外",
    "意识",
    "重新",
    "年轻",
    "年初",
    "开始",
    "开学",
    "开放",
    "大学",
    "大门",
    "大力",
    "大概",
    "大家",
    "中学",
    "高中",
    "学生",
    "学习",
    "学校",
    "老师",
    "老实",
    "老人",
    "同学",
    "同时",
    "朋友",
    "世界",
    "世上",
    "生活",
    "生命",
    "生意",
    "工作",
    "心情",
    "心里",
    "感觉",
    "感情",
    "事情",
    "事实",
    "问题",
    "方法",
    "方向",
    "结果",
    "结局",
    "未来",
    "过去",
    "现在",
    "现场",
    "一直",
    "一切",
    "一样",
    "突然",
    "然后",
    "然而",
    "因为",
    "原因",
    "所以",
    "但是",
    "如果",
    "虽然",
    "已经",
    "可以",
    "可能",
    "应该",
    "需要",
    "知道",
    "觉得",
    "希望",
    "想要",
    "回来",
    "回去",
    "出来",
    "起来",
    "下来",
    "上去",
    "十分",
    "分开",
    "分明",
    "白日",
    "白天",
    "白色",
    "从容",
    "从来",
    "内心",
    "必然",
    "必须",
    "的确",
    "目标",
    "目的",
    "成功",
    "成为",
    "成长",
    "城市",
    "城府",
    "外面",
    "外公",
    "外国",
    "里面",
    "里头",
    "前方",
    "前后",
    "后面",
    "机会",
    "机器",
    "骨头",
    "高明",
    "高度",
    "高兴",
    "阳光",
    "风雨",
    "风景",
    "风华",
    "面前",
    "面对",
    "面条",
    "平台",
    "平等",
    "平常",
    "平时",
    "平安",
    "生存",
    "生长",
    "国家",
    "国际",
    "国内",
    "文化",
    "文明",
    "文字",
    "文章",
    "舞台",
    "能力",
    "看见",
    "看法",
    "看到",
    "语气",
    "语言",
    "语文",
    "忽然",
    "忽视",
    "得到",
    "得意",
    "好处",
    "好奇",
    "学期",
    "学问",
    "事业",
    "事件",
    "事故",
    "经过",
    "经济",
    "直接",
    "直觉",
    "真实",
    "真相",
    "发现",
    "发生",
    "发展",
    "发达",
    "结束",
    "结论",
    "东西",
    "东边",
    "南方",
    "南边",
    "北方",
    "北边",
    "西方",
    "西边",
    "上空",
    "上下",
    "上面",
    "下面",
    "左右",
    "左面",
    "右面",
    "里外",
    "理由",
    "理发",
    "管道",
    "管子",
    "管理",
    "沉默",
    "沉睡",
    "沉淀",
    "确定",
    "确认",
    "确切",
    "全部",
    "全力",
    "全新",
    "完全",
    "完成",
    "明月",
    "明天",
    "明明",
    "明白",
    "明星",
    "星星",
    "晚上",
    "晚点",
    "早点",
    "早已",
}

# Characters that routinely follow a name in prose (verbs, particles,
# prepositions). Used to (a) trim an over-greedy 3-char match back to 2 chars and
# (b) detect that a name is being *used* as a person rather than being a fragment
# of an ordinary word.
_NON_NAME_TAIL = set(
    "的了是在有和与就都也还太更最不没要说答道问应喊叫把被让给对从向到过坐站着笑看听想看拿放开关做走跑来去回出入上下前后里头尾"
    "时候们吧呢啊哦嗯么什么这那哪他她它们个位次点种样样"
)

# Verbs that a *person* subject typically performs. A candidate followed by one
# of these is almost certainly a character.
_PERSON_ACTION = set(
    "说道问答喊叫哭笑坐站走跑看望听想推拉抬低点摇伸转沉叹停愣怔皱咬握松睁闭念读写拿放沉默伸手转身抬头低头点头摇头"
)

# Language markers that make a name unambiguous regardless of frequency.
_QUOTED_RE = re.compile(r"[「『“\"'《]([\u4e00-\u9fa5]{2,4})[」』”\"'》]")
_SURNAME_RE = re.compile(rf"[{SURNAMES}][\u4e00-\u9fa5]{{1,2}}")

# Role keywords, checked in order; first hit wins.
_ROLE_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("主角", "主人公", "少年", "年轻人", "青年", "男主", "女主"), "PROTAGONIST"),
    (("反派", "敌手", "对手", "宿敌", "敌人", "boss"), "ANTAGONIST"),
    (("导师", "师父", "师傅", "教授", "长辈", "老者"), "MENTOR"),
    (("恋人", "女友", "男友", "妻子", "丈夫", "情人"), "LOVE_INTEREST"),
)


def extract_names(text: str, *, limit: int = 30) -> list[str]:
    """Return candidate character names, most prominent first.

    Candidates must be **surname-anchored**: the first character has to be a real
    Chinese surname. That removes most of the noise the naive version produced
    (``澈没有`` from "林澈没有说话", ``笑着`` from "笑着说"), because 澈 and 笑 are
    not surnames.

    Surname anchoring is necessary but not sufficient -- plenty of ordinary words
    also start with a surname character (宿舍门, 游戏错, 边的座, 郁郁而, 班主任).
    So a candidate additionally needs **structural evidence**:

    * a person-ish verb immediately after it (``赵明达推``, ``苏晚坐``,
      ``周老师走``) -- accepted outright;
    * or, for a 2-char name, at least two mentions.

    Three-character candidates are held to the verb-evidence bar alone, because
    greedy matching makes them the main source of over-capture.

    Ranking is by raw mention count (with the verb signal as a tiebreak), which is
    the best available proxy for "who is the protagonist".
    """

    def trim(token: str) -> str:
        """Drop a trailing function word from a greedy 3-char match."""
        if len(token) == 3 and token[2] in _NON_NAME_TAIL:
            return token[:2]
        return token

    mentions: Counter[str] = Counter()
    for match in _SURNAME_RE.finditer(text):
        mentions[trim(match.group(0))] += 1

    evidence: Counter[str] = Counter()
    for token in list(mentions):
        hits = re.findall(rf"{re.escape(token)}(?=[{''.join(_PERSON_ACTION)}])", text)
        if hits:
            evidence[token] += len(hits)

    for match in _QUOTED_RE.finditer(text):
        quoted = trim(match.group(1))
        if quoted in mentions:
            evidence[quoted] += 1

    def is_plausible(name: str) -> bool:
        if len(name) < 2 or name in _NAME_STOPWORDS:
            return False
        if evidence[name]:
            return True
        # No verb signal: only a repeatedly-mentioned 2-char name qualifies.
        return len(name) == 2 and mentions[name] >= 2

    ranked = sorted(
        (name for name in mentions if is_plausible(name)),
        # Most-mentioned first, then verb evidence, then a stable name order.
        key=lambda name: (-mentions[name], -evidence[name], name),
    )

    # Drop a candidate that is only a fragment of a stronger one
    # ("赵明" when "赵明达" is already accepted).
    accepted: list[str] = []
    for name in ranked:
        if any(name != other and name in other for other in accepted):
            continue
        accepted.append(name)
        if len(accepted) >= limit:
            break

    return accepted


def infer_role(name: str, context: str) -> str:
    """Guess a role from how the name is described near its occurrences."""
    window_before = ""
    index = context.find(name)
    if index > 0:
        window_before = context[max(0, index - 60) : index]

    for keywords, role in _ROLE_HINTS:
        if any(keyword in window_before for keyword in keywords):
            return role
    return "SUPPORTING"


# --------------------------------------------------------------------------- #
# Locations
# --------------------------------------------------------------------------- #
# Ordered most-specific-first so 大学图书馆 wins over 图书馆.
_LOCATION_KEYWORDS: tuple[str, ...] = (
    "大学图书馆",
    "图书馆",
    "自习室",
    "实验室",
    "阶梯教室",
    "教室",
    "教学楼",
    "大学宿舍",
    "学校宿舍",
    "宿舍楼",
    "宿舍",
    "食堂",
    "操场",
    "体育馆",
    "篮球场",
    "足球场",
    "游泳馆",
    "校门口",
    "校园",
    "大学",
    "高中",
    "初中",
    "学校",
    "幼儿园",
    "会议室",
    "办公室",
    "写字楼",
    "公司",
    "工厂",
    "车间",
    "仓库",
    "客厅",
    "卧室",
    "厨房",
    "阳台",
    "卫生间",
    "书房",
    "出租屋",
    "公寓",
    "老宅",
    "房子",
    "天台",
    "楼顶",
    "楼梯间",
    "走廊",
    "电梯",
    "地下车库",
    "停车场",
    "咖啡厅",
    "咖啡馆",
    "奶茶店",
    "餐厅",
    "饭馆",
    "酒吧",
    "网吧",
    "便利店",
    "超市",
    "商场",
    "市场",
    "书店",
    "电影院",
    "医院",
    "诊所",
    "药房",
    "警局",
    "派出所",
    "法院",
    "银行",
    "邮局",
    "火车站",
    "汽车站",
    "地铁站",
    "机场",
    "码头",
    "车站",
    "地铁",
    "公园",
    "广场",
    "街道",
    "巷子",
    "胡同",
    "天桥",
    "河边",
    "湖边",
    "海边",
    "江边",
    "山上",
    "山谷",
    "森林",
    "田野",
    "村口",
    "村庄",
    "乡下",
    "田地",
    "酒店",
    "宾馆",
    "客栈",
    "度假村",
    "民宿",
    "武馆",
    "书院",
    "衙门",
    "擂台",
    "拍卖场",
    "赌场",
    "皇宫",
    "王宫",
    "城堡",
    "神殿",
    "祭坛",
    "宗门",
    "洞府",
    "秘境",
    "飞船",
    "太空站",
    "地下城",
    "废墟",
    "基地",
    "家里",
    "屋里",
    "房间",
)

_TIME_HINTS: tuple[tuple[str, str], ...] = (
    ("凌晨", "凌晨"),
    ("清晨", "清晨"),
    ("早晨", "清晨"),
    ("早上", "清晨"),
    ("上午", "上午"),
    ("中午", "正午"),
    ("下午", "下午"),
    ("傍晚", "傍晚"),
    ("黄昏", "黄昏"),
    ("晚上", "夜晚"),
    ("深夜", "深夜"),
    ("夜里", "深夜"),
    ("雨天", "雨天"),
    ("下雨", "雨天"),
    ("雪天", "雪天"),
    ("半夜", "深夜"),
)

_LIGHTING_HINTS: tuple[tuple[str, str], ...] = (
    ("阳光", "明亮的自然日光"),
    ("阳光明媚", "明亮通透的日光"),
    ("夕阳", "暖橙色夕阳余晖"),
    ("月色", "清冷月光"),
    ("月光", "清冷月光"),
    ("台灯", "暖黄色台灯照明"),
    ("灯光", "室内灯光"),
    ("烛光", "摇曳烛光"),
    ("昏暗", "低照度、阴影浓重"),
    ("明亮", "明亮通透"),
    ("阴暗", "阴冷暗调"),
    ("霓虹", "霓虹灯光"),
)


def extract_locations(text: str, *, limit: int = 30) -> list[str]:
    """Return location names found in the story, in order of first appearance.

    Matching is longest-first with overlap suppression: in "大学宿舍" the compound
    wins and a bare "大学" is not also reported, and "出租屋里" yields the room
    rather than a stray token.
    """
    spans: list[tuple[int, int, str]] = []

    # Longest keywords first so a compound beats its own prefixes.
    for keyword in sorted(_LOCATION_KEYWORDS, key=len, reverse=True):
        start = 0
        while True:
            index = text.find(keyword, start)
            if index < 0:
                break
            spans.append((index, index + len(keyword), keyword))
            start = index + 1

    # At the same position prefer the longer span.
    spans.sort(key=lambda span: (span[0], -(span[1] - span[0])))

    accepted: list[tuple[int, int, str]] = []
    seen_names: set[str] = set()
    for start, end, name in spans:
        if name in seen_names:
            continue
        if any(
            not (end <= other_start or start >= other_end) for other_start, other_end, _ in accepted
        ):
            continue
        # "宿舍" in "推开宿舍门" is the same set as the already-accepted
        # "大学宿舍" -- report one location, not two.
        if any(name in other or other in name for other in seen_names):
            continue
        accepted.append((start, end, name))
        seen_names.add(name)

    accepted.sort(key=lambda span: span[0])
    return [name for _, _, name in accepted[:limit]]


def sentence_containing(text: str, keyword: str) -> str:
    """The sentence around ``keyword``, for use as a scene description."""
    index = text.find(keyword)
    if index < 0:
        return ""
    start = max(
        (text.rfind(mark, 0, index) for mark in "。！？\n；"),
        default=-1,
    )
    end_candidates = [pos for pos in (text.find(mark, index) for mark in "。！？\n；") if pos >= 0]
    end = min(end_candidates) + 1 if end_candidates else len(text)
    return text[start + 1 : end].strip()


def match_time(text: str) -> str | None:
    for needle, label in _TIME_HINTS:
        if needle in text:
            return label
    return None


def match_lighting(text: str) -> str | None:
    for needle, label in _LIGHTING_HINTS:
        if needle in text:
            return label
    return None


# --------------------------------------------------------------------------- #
# Story Bible derivation
# --------------------------------------------------------------------------- #
_GENRE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("重生", "都市重生"),
    ("回到", "都市重生"),
    ("重回", "都市重生"),
    ("十年前", "都市重生"),
    ("穿越", "穿越"),
    ("修仙", "玄幻修仙"),
    ("修真", "玄幻修仙"),
    ("校园", "校园"),
    ("大学", "校园"),
    ("职场", "职场"),
    ("商战", "商战"),
    ("悬疑", "悬疑"),
    ("凶手", "悬疑"),
    ("侦探", "悬疑"),
    ("破案", "悬疑"),
    ("星际", "科幻"),
    ("机甲", "科幻"),
    ("末日", "末日废土"),
    ("丧尸", "末日废土"),
    ("武侠", "武侠"),
    ("江湖", "武侠"),
    ("宫斗", "古装宫斗"),
    ("皇帝", "古装"),
    ("恋爱", "言情"),
    ("青梅竹马", "言情"),
    ("异能", "都市异能"),
    ("系统", "系统流"),
)

_STYLE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("重生", "国漫赛璐璐，暖色调，带怀旧滤镜"),
    ("回到", "国漫赛璐璐，暖色调，带怀旧滤镜"),
    ("校园", "日系清新校园，柔和光感"),
    ("大学", "日系清新校园，柔和光感"),
    ("悬疑", "暗调高对比，冷色系"),
    ("科幻", "科幻写实，冷蓝主色"),
    ("武侠", "水墨武侠风，留白构图"),
)


def infer_genre(text: str, fallback: str | None = None) -> str:
    if fallback:
        return fallback
    for needle, label in _GENRE_KEYWORDS:
        if needle in text:
            return label
    return "剧情"


def infer_style(text: str, fallback: str | None = None) -> str:
    if fallback:
        return fallback
    for needle, label in _STYLE_KEYWORDS:
        if needle in text:
            return label
    return "国漫赛璐璐，电影感构图"


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？!?\n])", text)
    return [part.strip() for part in parts if part.strip()]


def first_clause(text: str, *, max_length: int = 20) -> str:
    cleaned = re.sub(r"\s+", "", text)
    if not cleaned:
        return "未命名故事"
    for mark in "。！？，,；;":
        index = cleaned.find(mark)
        if 0 < index <= max_length:
            return cleaned[:index]
    return cleaned[:max_length]


def infer_title(text: str, fallback: str | None = None) -> str:
    if fallback:
        return fallback
    return first_clause(text) or "未命名故事"


def episode_title(sentences: list[str], index: int) -> str:
    """A short,看點式 episode title from that episode's own sentences.

    Phase 4's planner prompt asks for a hook-style title rather than "第 N 集",
    so the offline provider derives one from the beat it was given. Falls back to
    a positional title only when the sentences carry nothing usable.
    """
    for sentence in sentences:
        clause = first_clause(sentence, max_length=12)
        if clause and len(clause) >= 3:
            return clause
    return f"第 {index + 1} 集"
