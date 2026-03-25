from __future__ import annotations

import re


def _norm(s: str) -> str:
    v = (s or "").strip().lower()
    # Remove common punctuation/whitespace so that inputs like
    # “中国石油大学（北京）” can match “中国石油大学北京”.
    v = re.sub(r"[\s·•\-\u2013\u2014\uFF0D_/，,。()（）【】\[\]{}]+", "", v)
    return v


_IVY = {
    # English
    "harvarduniversity",
    "yaleuniversity",
    "princetonuniversity",
    "columbiauniversity",
    "brownuniversity",
    "dartmouthcollege",
    "cornelluniversity",
    "universityofpennsylvania",
    "upenn",
    # Chinese common names
    "哈佛大学",
    "耶鲁大学",
    "普林斯顿大学",
    "哥伦比亚大学",
    "布朗大学",
    "达特茅斯学院",
    "康奈尔大学",
    "宾夕法尼亚大学",
}

_IVY_NORM = {_norm(x) for x in _IVY}


# 985 universities: official list (39).
_C985_OFFICIAL = {
    "北京大学",
    "清华大学",
    "中国人民大学",
    "北京航空航天大学",
    "北京理工大学",
    "中国农业大学",
    "北京师范大学",
    "中央民族大学",
    "南开大学",
    "天津大学",
    "大连理工大学",
    "东北大学",
    "吉林大学",
    "哈尔滨工业大学",
    "复旦大学",
    "同济大学",
    "上海交通大学",
    "华东师范大学",
    "南京大学",
    "东南大学",
    "浙江大学",
    "中国科学技术大学",
    "厦门大学",
    "山东大学",
    "中国海洋大学",
    "武汉大学",
    "华中科技大学",
    "中南大学",
    "湖南大学",
    "国防科技大学",
    "中山大学",
    "华南理工大学",
    "四川大学",
    "电子科技大学",
    "重庆大学",
    "西安交通大学",
    "西北工业大学",
    "兰州大学",
    "西北农林科技大学",
}

_C985 = _C985_OFFICIAL
_C985_NORM = {_norm(x) for x in _C985}


# 211 universities (non-985) from your provided list/images.
_C211_NON985 = {
    "南京航空航天大学",
    "西安电子科技大学",
    "中央财经大学",
    "上海财经大学",
    "南京理工大学",
    "北京交通大学",
    "北京科技大学",
    "对外经济贸易大学",
    "北京邮电大学",
    "哈尔滨工程大学",
    "南京农业大学",
    "中国政法大学",
    "暨南大学",
    "华东理工大学",
    "苏州大学",
    "武汉理工大学",
    "西南交通大学",
    "中国矿业大学",
    "中国矿业大学北京",
    "中国矿业大学徐州",
    "西南大学",
    "河海大学",
    "东北师范大学",
    "北京外国语大学",
    "上海外国语大学",
    "合肥工业大学",
    "郑州大学",
    "中国石油大学",
    "中国石油大学北京",
    "中国石油大学华东",
    "中国地质大学",
    "中国地质大学武汉",
    "中国地质大学北京",
    "华北电力大学",
    "华北电力大学北京",
    "华北电力大学保定",
    "华中师范大学",
    "西南财经大学",
    "南京师范大学",
    "江南大学",
    "华中农业大学",
    "上海大学",
    "福州大学",
    "云南大学",
    "南昌大学",
    "东华大学",
    "中南财经政法大学",
    "陕西师范大学",
    "北京化工大学",
    "北京工业大学",
    "中国传媒大学",
    "西北大学",
    "长安大学",
    "北京林业大学",
    "安徽大学",
    "天津医科大学",
    "华南师范大学",
    "湖南师范大学",
    "北京中医药大学",
    "大连海事大学",
    "广西大学",
    "河北工业大学",
    "贵州大学",
    "太原理工大学",
    "海南大学",
    "中国药科大学",
    "内蒙古大学",
    "北京体育大学",
    "四川农业大学",
    "东北林业大学",
    "辽宁大学",
    "东北农业大学",
    "新疆大学",
    "石河子大学",
    "延边大学",
    "中央音乐学院",
    "宁夏大学",
    "青海大学",
    "西藏大学",
}

_C211 = _C211_NON985
_C211_NORM = {_norm(x) for x in _C211}


def classify_university(school: str) -> tuple[str, str]:
    """
    Returns (tag, label):
    - ("ivy", "常青藤") / ("985", "985") / ("211", "211") / ("", "")
    """
    raw = (school or "").strip()
    if not raw:
        return "", ""

    n = _norm(raw)
    if n in _IVY_NORM:
        return "ivy", "常青藤"
    if n in _C985_NORM:
        return "985", "985"
    if n in _C211_NORM:
        return "211", "211"
    return "", ""

