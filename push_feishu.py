#!/usr/bin/env python3
import os
import re
import requests
import feedparser
from dotenv import load_dotenv

load_dotenv()

WEBHOOK = os.getenv("FEISHU_WEBHOOK")
QW_KEY = os.getenv("QWEATHER_KEY")
API_HOST = os.getenv("API_HOST")
LOCATION = "122.99,41.11"

NEWS_LAST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_news.txt")

# ========== 新闻源 ==========
RSS_SOURCES = [
    {
        "name": "军事",
        "url": "http://www.chinanews.com.cn/rss/mil.xml",
        "max": 20,
        "kw": [
            "导弹", "无人机", "战机", "轰炸机", "战斗机", "预警机", "侦察机",
            "航母", "军舰", "驱逐舰", "护卫舰", "潜艇", "核潜艇",
            "坦克", "火炮", "火箭炮", "雷达",
            "核", "弹道", "巡航导弹", "高超音速", "拦截", "反导",
            "俄", "乌", "乌克兰", "以军", "以色列", "伊朗", "叙利亚", "胡塞",
            "朝鲜", "台海", "南海",
            "空袭", "袭击", "军演", "演习", "部署", "增兵", "撤军",
            "击落", "击沉", "停火",
            "北约", "美军", "俄军", "解放军", "国防部",
        ],
    },
    {
        "name": "国际政治",
        "url": "http://www.chinanews.com.cn/rss/world.xml",
        "max": 20,
        "kw": [
            "美国", "白宫", "特朗普", "拜登", "布林肯",
            "俄罗斯", "普京", "克里姆林宫", "拉夫罗夫",
            "中国", "外交部", "王毅",
            "以色列", "内塔尼亚胡", "伊朗",
            "乌克兰", "停火", "和谈", "谈判", "制裁",
            "美军", "北约", "驻军", "基地",
            "会晤", "通话", "访华", "访美", "峰会", "联合声明",
            "联合国", "安理会", "G7", "G20",
        ],
    },
    {
        "name": "亚洲台海",
        "url": "http://www.chinanews.com.cn/rss/world.xml",
        "max": 20,
        "kw": [
            "台海", "台湾", "台军", "赖清德", "民进党", "以武谋独",
            "解放军", "环台", "实弹", "演训", "海峡中线",
            "钓鱼岛", "东海",
            "日本", "岸田", "石破", "自卫队", "日美",
            "韩国", "尹锡悦", "李在明", "美日韩",
            "朝鲜", "金正恩", "射弹", "洲际导弹",
            "菲律宾", "马科斯", "南海", "仁爱礁", "黄岩岛", "东盟",
            "越南", "缅甸", "泰国", "柬埔寨", "印尼",
        ],
    },
    {
        # 台海国内视角补一条源，提高命中量
        "name": "亚洲台海",
        "url": "http://www.chinanews.com.cn/rss/china.xml",
        "max": 20,
        "kw": [
            "台海", "台湾", "赖清德", "台军", "解放军", "环台",
            "钓鱼岛", "南海", "仁爱礁", "黄岩岛",
            "辽宁", "鞍山", "台办", "两岸",
        ],
    },
    {
        "name": "油气",
        "url": "http://www.chinanews.com.cn/rss/finance.xml",
        "max": 20,
        "kw": [
            "石油", "油价", "原油", "布伦特", "成品油", "汽油", "柴油",
            "天然气", "液化天然气", "LNG", "页岩气",
            "调价", "上涨", "下跌", "暴跌", "增产", "减产", "限产",
            "欧佩克", "霍尔木兹", "油轮", "管道", "炼化", "炼厂",
            "能源", "燃料", "储备",
        ],
    },
    {
        "name": "辽宁民生",
        "url": "http://www.chinanews.com.cn/rss/society.xml",
        "max": 20,
        "kw": [
            "辽宁", "鞍山", "沈阳", "大连",
            "菜价", "肉价", "物价", "保供",
            "供暖", "供气", "水电", "公交",
            "补贴", "民生", "预警", "防汛", "寒潮",
        ],
    },
]

LN_PRICE_URL = "https://fgw.ln.gov.cn/fgw/xxgk/jgjc/mrjg/index.shtml"

PRICE_WANT = ["鲜猪肉", "牛肉", "羊肉", "鸡肉", "鸡蛋", "豆油",
              "大米", "面粉", "大白菜", "黄瓜", "土豆", "西红柿",
              "青椒", "芸豆", "韭菜", "菠菜", "芹菜"]


# ========== 天气 ==========
def fetch():
    headers = {"X-QW-Api-Key": QW_KEY}
    base = API_HOST.rstrip("/")
    now = requests.get(f"{base}/v7/weather/now",
                       params={"location": LOCATION}, headers=headers, timeout=10).json()
    hourly = requests.get(f"{base}/v7/weather/24h",
                          params={"location": LOCATION}, headers=headers, timeout=10).json()
    daily = requests.get(f"{base}/v7/weather/3d",
                         params={"location": LOCATION}, headers=headers, timeout=10).json()
    return {"now": now, "hourly": hourly, "daily": daily}


def build_text(data):
    now = data["now"].get("now", {})
    lines = ["监控推送 · 鞍山天气"]
    lines.append(
        f"当前：{now.get('text', '?')} {now.get('temp', '?')}℃ "
        f"（体感 {now.get('feelsLike', '?')}℃）"
    )
    lines.append(
        f"湿度 {now.get('humidity', '?')}%  "
        f"{now.get('windDir', '')}{now.get('windScale', '?')}级"
    )
    lines.append("")
    lines.append("—— 未来24小时 ——")
    for i, h in enumerate(data["hourly"].get("hourly", [])):
        if i % 3 != 0:
            continue
        t = h.get("fxTime", "")[11:16]
        lines.append(f"{t} {h.get('text', '?')} {h.get('temp', '?')}℃ 降水{h.get('pop', '0')}%")
    lines.append("")
    lines.append("—— 未来3天 ——")
    for d in data["daily"].get("daily", [])[:3]:
        lines.append(f"{d.get('fxDate', '?')} {d.get('textDay', '?')} {d.get('tempMin', '?')}~{d.get('tempMax', '?')}℃")
    return "\n".join(lines)


# ========== 物价 ==========
def fetch_ln_prices():
    try:
        r = requests.get(LN_PRICE_URL, timeout=10,
                         headers={"User-Agent": "Mozilla/5.0"})
        r.encoding = "utf-8"
        text = re.sub(r"<.*?>", " ", r.text)
        text = re.sub(r"\s+", " ", text)
    except Exception as e:
        print("物价页拉取失败:", sanitize(str(e)))
        return [], ""
    mtime = ""
    m = re.search(r"监测时间[:：]\s*(\d{4}-\d{2}-\d{2})", text)
    if m:
        mtime = m.group(1)
    rows = []
    for name in PRICE_WANT:
        pat = re.escape(name) + r".*?([\d]+\.[\d]+)"
        m2 = re.search(pat, text)
        if m2:
            rows.append(f"{name} {m2.group(1)}元")
    return rows, mtime


def price_block():
    rows, mtime = fetch_ln_prices()
    lines = ["—— 辽宁物价（全省均价） ——"]
    if mtime:
        lines.append(f"监测时间：{mtime}")
    if not rows:
        lines.append("（暂未获取到，稍后重试）")
        return "\n".join(lines)
    for x in rows:
        lines.append(f"· {x}")
    lines.append("数据：辽宁省发改委")
    return "\n".join(lines)


# ========== 脱敏 ==========
def sanitize(msg):
    msg = re.sub(r"https?://[^\s'\"]+", "<hidden>", msg)
    msg = re.sub(r"[a-z0-9\-]+\.(qweatherapi\.com|chinanews\.com\.cn|ln\.gov\.cn)", "<hidden>", msg)
    return msg


# ========== 权重表（大国/热点高分） ==========
HOT_WEIGHT = {
    # 大国
    "习近平": 20, "王毅": 18, "外交部": 16,
    "特朗普": 20, "拜登": 18, "布林肯": 16, "白宫": 18,
    "普京": 20, "拉夫罗夫": 16, "克里姆林宫": 18, "俄罗斯": 14,
    # 中东
    "以色列": 16, "内塔尼亚胡": 18, "伊朗": 16, "最高领袖": 18,
    "哈马斯": 14, "真主党": 14,
    # 军事核心
    "解放军": 18, "美军": 16, "俄军": 16, "以军": 16, "北约": 14,
    "导弹": 12, "无人机": 12, "航母": 12, "核潜艇": 14, "高超音速": 16,
    # 台海/亚洲（高分）
    "台海": 20, "赖清德": 18, "以武谋独": 20, "环台": 18, "实弹": 16,
    "钓鱼岛": 18, "仁爱礁": 18, "黄岩岛": 18, "南海": 14,
    "日本": 12, "石破": 14, "岸田": 14, "自卫队": 12,
    "韩国": 12, "尹锡悦": 14, "李在明": 14,
    "朝鲜": 14, "金正恩": 18, "洲际导弹": 18,
    "菲律宾": 14, "马科斯": 16, "东盟": 12,
    # 油气
    "霍尔木兹": 18, "欧佩克": 12, "布伦特": 12, "原油": 10,
    # 互动
    "会晤": 14, "峰会": 14, "联合声明": 14, "安理会": 14, "联合国": 10,
    "停火": 12, "制裁": 12,
}


def relevance(title, kw_list):
    score = 0
    for kw in kw_list:
        if kw in title:
            score += HOT_WEIGHT.get(kw, len(kw))
    return score


def fetch_news():
    results = []
    seen = set()
    for src in RSS_SOURCES:
        try:
            d = feedparser.parse(src["url"])
            cands = []
            for e in d.entries:
                title = (e.get("title") or "").strip()
                link = (e.get("link") or "").strip()
                if not title or not link or title in seen:
                    continue
                kw = src.get("kw", [])
                if kw and not any(k in title for k in kw):
                    continue
                seen.add(title)
                cands.append((src["name"], title, link, relevance(title, kw)))
            cands.sort(key=lambda x: -x[3])
            count = 0
            for item in cands:
                if count >= src["max"]:
                    break
                results.append((item[0], item[1], item[2]))
                count += 1
        except Exception as ex:
            print(f"[{src['name']}] RSS失败: {sanitize(str(ex))}")
    return results


def news_groups():
    items = fetch_news()
    seen12 = set()
    dedup = []
    for s, t, u in items:
        k12 = t[:12]
        if k12 in seen12:
            continue
        seen12.add(k12)
        dedup.append((s, t, u))

    groups = {}
    for s, t, u in dedup:
        groups.setdefault(s, []).append((t, u))
    return groups


def block_for(names, cap=10):
    groups = news_groups()
    lines = []
    for name in names:
        if name not in groups:
            continue
        lines.append(f"\n【{name}】")
        for t, u in groups[name][:cap]:
            lines.append(f"· {t}")
            lines.append(f"  {u}")
    return "\n".join(lines)


# ========== 飞书 ==========
def push_feishu(text):
    if not WEBHOOK:
        raise RuntimeError("FEISHU_WEBHOOK 没配置")
    resp = requests.post(WEBHOOK,
                         json={"msg_type": "text", "content": {"text": text}},
                         timeout=5)
    print("飞书返回:", resp.json())


def main():
    try:
        # 第一条：天气 + 军事/国际政治/亚洲台海
        text1 = build_text(fetch())
        text1 += "\n\n—— 新闻资讯（一） ——"
        text1 += block_for(["军事", "国际政治", "亚洲台海"], cap=10)
        push_feishu(text1)

        # 第二条：油气 + 辽宁民生 + 物价
        text2 = "—— 新闻资讯（二） ——"
        text2 += block_for(["油气", "辽宁民生"], cap=10)
        text2 += "\n\n" + price_block()
        push_feishu(text2)

        print("✅ 完成")
    except Exception as e:
        print(f"❌ 出错: {sanitize(str(e))}")
        try:
            push_feishu(f"监控推送失败：{sanitize(str(e))}")
        except Exception:
            pass


if __name__ == "__main__":
    main()
