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

# ========== 新闻源（中新网官方 RSS） ==========
RSS_SOURCES = [
    {
        "name": "军事",
        "url": "http://www.chinanews.com.cn/rss/mil.xml",
        "max": 8,
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
        "name": "国际",
        "url": "http://www.chinanews.com.cn/rss/world.xml",
        "max": 8,
        "kw": [
            "导弹", "无人机", "空袭", "袭击", "炮击", "轰炸",
            "俄", "乌", "乌克兰", "以色列", "伊朗", "以军", "哈马斯", "胡塞",
            "叙利亚", "黎巴嫩", "普京", "泽连斯基", "内塔尼亚胡",
            "停火", "和谈", "谈判", "制裁",
            "美军", "北约", "驻军", "基地",
            "霍尔木兹", "石油", "天然气", "油价",
        ],
    },
    {
        "name": "国际政治",
        "url": "http://www.chinanews.com.cn/rss/world.xml",
        "max": 6,
        "kw": [
            # 日韩
            "日本", "东京", "岸田", "石破", "自民党", "自卫队", "日美",
            "韩国", "首尔", "尹锡悦", "李在明", "韩军", "美日韩",
            # 台海
            "台海", "台湾", "台军", "解放军", "环台", "实弹",
            # 东南亚
            "菲律宾", "马科斯", "南海", "仁爱礁", "黄岩岛", "东盟",
            "越南", "缅甸", "泰国", "柬埔寨", "印尼",
            # 朝鲜半岛
            "朝鲜", "平壤", "金正恩", "射弹", "洲际导弹",
            # 大局势
            "会晤", "通话", "访华", "访美", "峰会", "联合声明",
        ],
    },
    {
        "name": "油气",
        "url": "http://www.chinanews.com.cn/rss/finance.xml",
        "max": 6,
        "kw": [
            "石油", "油价", "原油", "布伦特", "成品油", "汽油", "柴油",
            "天然气", "液化天然气", "LNG", "页岩气",
            "调价", "上涨", "下跌", "暴跌", "增产", "减产", "限产",
            "欧佩克", "霍尔木兹", "油轮", "管道", "炼化", "炼厂",
            "能源", "燃料",
        ],
    },
    {
        "name": "国内",
        "url": "http://www.chinanews.com.cn/rss/china.xml",
        "max": 6,
        "kw": [
            "辽宁", "鞍山", "沈阳", "大连", "东北",
            "防汛", "暴雨", "台风", "寒潮", "高温", "预警",
            "发改委", "物价", "保供", "粮价", "菜价",
            "政策", "国务院", "民生", "补贴", "养老金",
            "事故", "救援", "地震", "洪水",
        ],
    },
    {
        "name": "辽宁民生",
        "url": "http://www.chinanews.com.cn/rss/society.xml",
        "max": 4,
        "kw": [
            "辽宁", "鞍山", "沈阳", "大连",
            "菜价", "肉价", "物价", "保供",
            "供暖", "供气", "水电", "公交",
            "补贴", "民生", "预警", "防汛",
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


# ========== 新闻 ==========
def sanitize(msg):
    """把报错里的 URL / host 打成 <hidden>，避免回传飞书暴露域名"""
    msg = re.sub(r"https?://[^\s'\"]+", "<hidden>", msg)
    msg = re.sub(r"[a-z0-9\-]+\.(qweatherapi\.com|chinanews\.com\.cn|ln\.gov\.cn)", "<hidden>", msg)
    return msg


def relevance(title, kw_list):
    score = 0
    for kw in kw_list:
        if kw in title:
            # 词越长越具体，权重越高；短词（如"俄"）权重低
            score += len(kw)
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
            # 按权重降序，取最典型的
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


def news_block():
    items = fetch_news()
    if not items:
        return "—— 新闻资讯 ——\n（暂无匹配条目）"

    seen12 = set()
    dedup = []
    for s, t, u in items:
        k12 = t[:12]
        if k12 in seen12:
            continue
        seen12.add(k12)
        dedup.append((s, t, u))

    key = "\n".join(f"{s}|{t}" for s, t, _ in dedup)
    last = ""
    if os.path.exists(NEWS_LAST_FILE):
        last = open(NEWS_LAST_FILE, encoding="utf-8").read().strip()
    if key == last:
        return "—— 新闻资讯 ——\n（无新条目）"

    groups = {}
    for s, t, u in dedup:
        groups.setdefault(s, []).append((t, u))

    lines = ["—— 新闻资讯 ——"]
    order = ["军事", "国际政治", "国际", "油气", "国内", "辽宁民生"]
    cap = {"军事": 6, "国际政治": 6, "国际": 5, "油气": 5, "国内": 4, "辽宁民生": 3}
    for name in order:
        if name not in groups:
            continue
        lines.append(f"\n【{name}】")
        for t, u in groups[name][:cap.get(name, 5)]:
            lines.append(f"· {t}")
            lines.append(f"  {u}")

    open(NEWS_LAST_FILE, "w", encoding="utf-8").write(key)
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
        data = fetch()
        text = build_text(data)
        text += "\n\n" + price_block()
        text += "\n\n" + news_block()
        push_feishu(text)
        print("✅ 完成")
    except Exception as e:
        print(f"❌ 出错: {sanitize(str(e))}")
        try:
            push_feishu(f"监控推送失败：{sanitize(str(e))}")
        except Exception:
            pass


if __name__ == "__main__":
    main()
