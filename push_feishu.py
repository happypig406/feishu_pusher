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

# ===== 关键词大幅扩充 =====
RSS_SOURCES = [
    {
        "name": "军事",
        "url": "http://www.chinanews.com.cn/rss/mil.xml",
        "max": 8,
        "kw": [
            # 装备体系
            "导弹", "无人机", "战机", "轰炸机", "战斗机", "预警机", "侦察机",
            "航母", "军舰", "驱逐舰", "护卫舰", "潜艇", "核潜艇", "登陆舰",
            "坦克", "装甲车", "火炮", "火箭炮", "雷达", "卫星",
            # 战略武器
            "核", "核武器", "弹道", "巡航导弹", "高超音速", "拦截", "反导",
            # 地缘热点
            "俄", "乌", "以军", "以色列", "伊朗", "叙利亚", "胡塞", "黎巴嫩",
            "朝鲜", "半岛", "台海", "南海", "东海",
            # 行动与态势
            "军演", "演习", "演训", "部署", "增兵", "撤军", "空袭", "袭击",
            "击落", "击沉", "击毙", "俘虏", "战损", "停火", "和谈",
            "北约", "美军", "俄军", "以军", "日军", "韩军", "解放军",
            "国防部", "参谋长", "司令", "上将",
        ],
    },
    {
        "name": "国际",
        "url": "http://www.chinanews.com.cn/rss/world.xml",
        "max": 6,
        "kw": [
            # 冲突与战争
            "导弹", "无人机", "拦截", "俄", "乌", "乌克兰", "以色列", "伊朗",
            "以军", "哈马斯", "胡塞", "真主党", "叙利亚", "黎巴嫩",
            "空袭", "袭击", "炮击", "轰炸", "伤亡", "阵亡",
            "停火", "谈判", "和谈", "斡旋",
            # 军事部署
            "美军", "北约", "驻军", "基地", "军演", "演习",
            # 地缘能源（国际视角）
            "霍尔木兹", "海峡", "能源", "石油", "原油", "天然气", "油价",
            "制裁", "禁运", "出口", "进口", "关税",
            # 大国关系
            "普京", "泽连斯基", "内塔尼亚胡", "特朗普", "拜登",
            "特朗普", "会晤", "通话", "访美", "访俄", "访华",
        ],
    },
    {
        "name": "油气",
        "url": "http://www.chinanews.com.cn/rss/finance.xml",
        "max": 5,
        "kw": [
            # 品类
            "石油", "油价", "原油", "布伦特", "成品油", "汽油", "柴油",
            "天然气", "液化天然气", "LNG", "页岩气", "页岩油",
            # 价格与调价
            "调价", "上涨", "下跌", "暴跌", "暴涨", "企稳", "震荡",
            # 地缘供应
            "霍尔木兹", "海峡", "减产", "增产", "欧佩克", "限产",
            # 物流
            "油轮", "油港", "管道", "出口", "进口", "炼化", "炼厂",
            # 宏观
            "能源", "燃料", "柴油车", "汽油车",
        ],
    },
]

LN_PRICE_URL = "https://fgw.ln.gov.cn/fgw/xxgk/jgjc/mrjg/index.shtml"

PRICE_WANT = ["鲜猪肉", "牛肉", "羊肉", "鸡肉", "鸡蛋", "豆油",
              "大白菜", "黄瓜", "土豆", "西红柿", "青椒", "芸豆", "韭菜"]


# ========== 天气 ==========
def fetch():
    headers = {"X-QW-Api-Key": QW_KEY}
    now = requests.get(f"{API_HOST}/v7/weather/now",
                       params={"location": LOCATION}, headers=headers, timeout=10).json()
    hourly = requests.get(f"{API_HOST}/v7/weather/24h",
                          params={"location": LOCATION}, headers=headers, timeout=10).json()
    daily = requests.get(f"{API_HOST}/v7/weather/3d",
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


# ========== 辽宁物价 ==========
def fetch_ln_prices():
    try:
        r = requests.get(LN_PRICE_URL, timeout=10,
                         headers={"User-Agent": "Mozilla/5.0"})
        r.encoding = "utf-8"
        text = re.sub(r"<.*?>", " ", r.text)
        text = re.sub(r"\s+", " ", text)
    except Exception as e:
        print("物价页拉取失败:", e)
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
def relevance(title, kw_list):
    """命中关键词越多、越靠前，分越高，用来排序挑典型"""
    score = 0
    for i, kw in enumerate(kw_list):
        if kw in title:
            score += (len(kw_list) - i)  # 靠前的词权重高
    return score


def fetch_news():
    results = []
    seen = set()
    for src in RSS_SOURCES:
        try:
            d = feedparser.parse(src["url"])
            count = 0
            # 先给本源所有候选打分排序，挑最典型的
            cands = []
            for e in d.entries:
                title = (e.get("title") or "").strip()
                link = (e.get("link") or "").strip()
                if not title or not link:
                    continue
                if title in seen:
                    continue
                kw = src.get("kw", [])
                if kw and not any(k in title for k in kw):
                    continue
                seen.add(title)
                cands.append((src["name"], title, link, relevance(title, kw)))
            cands.sort(key=lambda x: -x[3])
            for item in cands:
                if count >= src["max"]:
                    break
                results.append((item[0], item[1], item[2]))
                count += 1
        except Exception as ex:
            print(f"[{src['name']}] RSS失败: {ex}")
    return results


def news_block():
    items = fetch_news()
    if not items:
        return "—— 军事/油气资讯 ——\n（今日无匹配条目）"

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
        return "—— 军事/油气资讯 ——\n（无新条目）"

    # 按分类归组，每类最多 6 条
    groups = {}
    for s, t, u in dedup:
        groups.setdefault(s, []).append((t, u))

    lines = ["—— 军事/油气资讯 ——"]
    order = ["军事", "国际", "油气"]
    for name in order:
        if name not in groups:
            continue
        lines.append(f"\n【{name}】")
        for t, u in groups[name][:6]:
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
        print(f"❌ 出错: {e}")
        try:
            push_feishu(f"监控推送失败：{e}")
        except Exception:
            pass


if __name__ == "__main__":
    main()
