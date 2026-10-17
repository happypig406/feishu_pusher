#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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

LN_PRICE_URL = "https://fgw.ln.gov.cn/fgw/xxgk/jgjc/mrjg/index.shtml"

# ========== 板块配置 ==========
# hard：必须含其中一个才算该类（防日本地震/非遗混入台海）
# kw ：用于权重打分，命中高分词排前面
# srcs：该板块抓取的源
BLOCKS = [
    {
        "name": "军事",
        "cap": 10,
        "hard": ["导弹", "军", "俄", "乌", "以军", "美军", "解放军", "航母",
                 "无人机", "北约", "演习", "战机", "俄军", "以军"],
        "srcs": ["http://www.chinanews.com.cn/rss/mil.xml"],
    },
    {
        "name": "国际政治",
        "cap": 10,
        "hard": ["美", "俄", "普", "特朗", "内塔", "伊朗", "联合国", "峰会",
                 "拜登", "普京", "安理会", "王毅", "以色列", "乌克兰"],
        "srcs": ["http://www.chinanews.com.cn/rss/world.xml"],
    },
    {
        "name": "亚洲台海",
        "cap": 10,
        "hard": ["台", "南海", "钓鱼岛", "解放军", "菲律宾", "朝鲜", "日本", "韩国",
                 "两岸", "台办", "金正恩", "尹锡悦", "马科斯"],
        "srcs": [
            "http://www.chinanews.com.cn/rss/world.xml",
            "http://www.chinanews.com.cn/rss/taiwan.xml",
        ],
    },
    {
        "name": "油气",
        "cap": 10,
        "hard": ["油", "气", "能源", "霍尔木兹"],
        "srcs": ["http://www.chinanews.com.cn/rss/finance.xml"],
    },
    {
        "name": "辽宁民生",
        "cap": 10,
        "hard": ["辽宁", "鞍山", "沈阳", "大连", "物价", "菜价", "供暖", "寒潮"],
        "srcs": [
            "http://www.chinanews.com.cn/rss/society.xml",
            "http://www.chinanews.com.cn/rss/china.xml",
        ],
    },
]

PRICE_WANT = ["鲜猪肉", "牛肉", "羊肉", "鸡肉", "鸡蛋", "豆油",
              "大米", "面粉", "大白菜", "黄瓜", "土豆", "西红柿",
              "青椒", "芸豆", "韭菜", "菠菜", "芹菜"]

# 关键词权重：大国/核心热点高分，排最前
HOT_WEIGHT = {
    "习近平": 20, "王毅": 18, "外交部": 16,
    "特朗普": 20, "拜登": 18, "布林肯": 16, "白宫": 18,
    "普京": 20, "拉夫罗夫": 16, "克里姆林宫": 18, "俄罗斯": 14,
    "以色列": 16, "内塔尼亚胡": 18, "伊朗": 16, "最高领袖": 18,
    "解放军": 18, "美军": 16, "俄军": 16, "以军": 16, "北约": 14,
    "导弹": 12, "无人机": 12, "航母": 12, "核潜艇": 14, "高超音速": 16,
    "台海": 20, "赖清德": 18, "以武谋独": 20, "环台": 18, "实弹": 16,
    "钓鱼岛": 18, "仁爱礁": 18, "黄岩岛": 18, "南海": 14,
    "日本": 12, "石破": 14, "岸田": 14, "自卫队": 12,
    "韩国": 12, "尹锡悦": 14, "李在明": 14,
    "朝鲜": 14, "金正恩": 18, "洲际导弹": 18,
    "菲律宾": 14, "马科斯": 16, "东盟": 12,
    "霍尔木兹": 18, "欧佩克": 12, "布伦特": 12, "原油": 10,
    "会晤": 14, "峰会": 14, "联合声明": 14, "安理会": 14, "联合国": 10,
    "停火": 12, "制裁": 12,
    "辽宁": 12, "鞍山": 14, "沈阳": 12, "大连": 12,
    "寒潮": 14, "预警": 10, "物价": 10,
}


# ========== 天气 ==========
def fetch_weather():
    headers = {"X-QW-Api-Key": QW_KEY}
    base = API_HOST.rstrip("/")
    return {
        "now": requests.get(f"{base}/v7/weather/now", params={"location": LOCATION},
                            headers=headers, timeout=10).json(),
        "hourly": requests.get(f"{base}/v7/weather/24h", params={"location": LOCATION},
                               headers=headers, timeout=10).json(),
        "daily": requests.get(f"{base}/v7/weather/3d", params={"location": LOCATION},
                              headers=headers, timeout=10).json(),
    }


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


def relevance(title, hard):
    score = 0
    for kw in hard:
        if kw in title:
            score += HOT_WEIGHT.get(kw, len(kw))
    return score


# ========== 单板块抓取（独立去重 + 宽兜底） ==========
def fetch_block(cfg):
    picked = []
    seen = set()
    for url in cfg["srcs"]:
        try:
            d = feedparser.parse(url)
            cands = []
            fill = []   # 兜底：不满足 hard 但也属本源的最新条目
            for e in d.entries:
                title = (e.get("title") or "").strip()
                link = (e.get("link") or "").strip()
                if not title or not link or title in seen:
                    continue
                seen.add(title)
                hit = any(k in title for k in cfg["hard"])
                score = relevance(title, cfg["hard"])
                if hit:
                    cands.append((score, title, link))
                else:
                    fill.append((title, link))
            cands.sort(key=lambda x: -x[0])
            for _, t, u in cands:
                if len(picked) >= cfg["cap"]:
                    break
                picked.append((t, u))
            # 不够 cap 时用兜底补满
            for t, u in fill:
                if len(picked) >= cfg["cap"]:
                    break
                picked.append((t, u))
        except Exception as ex:
            print(f"[{cfg['name']}] RSS失败: {sanitize(str(ex))}")
    return picked


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
        # 1) 天气单独一条
        push_feishu(build_text(fetch_weather()))

        # 2) 五块各一条
        for cfg in BLOCKS:
            items = fetch_block(cfg)
            lines = [f"—— {cfg['name']}资讯 ——"]
            if not items:
                lines.append("（暂无相关条目）")
            for t, u in items:
                lines.append(f"· {t}")
                lines.append(f"  {u}")
            push_feishu("\n".join(lines))

        # 3) 物价单独一条
        push_feishu(price_block())
        print("✅ 完成")
    except Exception as e:
        print(f"❌ 出错: {sanitize(str(e))}")
        try:
            push_feishu(f"监控推送失败：{sanitize(str(e))}")
        except Exception:
            pass


if __name__ == "__main__":
    main()
