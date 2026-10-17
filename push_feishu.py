#!/usr/bin/env python3
import os
import re
import time
import requests
import feedparser
from dotenv import load_dotenv

load_dotenv()

WEBHOOK = os.getenv("FEISHU_WEBHOOK")
QW_KEY = os.getenv("QWEATHER_KEY")
API_HOST = os.getenv("API_HOST")
LOCATION = "122.99,41.11"

# ========== 5板块配置 ==========
BLOCKS = [
    {
        "name": "军事",
        "cap": 10,
        "hard": ["导弹", "军", "俄", "乌", "以军", "美军", "解放军", "航母",
                 "无人机", "北约", "演习", "战机", "俄军", "防空", "袭击", "核"],
        "srcs": ["http://www.chinanews.com.cn/rss/mil.xml"],
    },
    {
        "name": "国际政治",
        "cap": 10,
        "hard": ["美", "俄", "普", "特朗", "内塔", "伊朗", "联合国", "峰会",
                 "拜登", "普京", "安理会", "王毅", "以色列", "乌克兰", "制裁"],
        "srcs": ["http://www.chinanews.com.cn/rss/world.xml"],
    },
    {
        "name": "亚洲台海",
        "cap": 10,
        "hard": ["台", "南海", "钓鱼岛", "解放军", "菲律宾", "朝鲜", "日本", "韩国",
                 "两岸", "台办", "金正恩", "尹锡悦", "马科斯", "仁爱礁", "黄岩岛"],
        "srcs": [
            "http://www.chinanews.com.cn/rss/world.xml",
            "http://www.chinanews.com.cn/rss/tw.xml",
        ],
    },
    {
        "name": "油气",
        "cap": 10,
        "hard": ["石油", "油价", "原油", "布伦特", "天然气", "霍尔木兹", "油轮", "能源", "LNG"],
        "srcs": ["http://www.chinanews.com.cn/rss/finance.xml"],
    },
    {
        "name": "辽宁民生",
        "cap": 10,
        "hard": ["辽宁", "鞍山", "沈阳", "大连", "物价", "菜价", "供暖", "寒潮", "防汛"],
        "srcs": [
            "http://www.chinanews.com.cn/rss/society.xml",
            "http://www.chinanews.com.cn/rss/china.xml",
        ],
    },
]

HOT_WEIGHT = {
    "普京": 20, "特朗普": 20, "拜登": 18, "内塔尼亚胡": 18, "金正恩": 18,
    "台海": 20, "赖清德": 18, "钓鱼岛": 18, "仁爱礁": 18, "霍尔木兹": 18,
    "解放军": 18, "导弹": 12, "无人机": 12, "航母": 12, "北约": 14,
    "伊朗": 16, "以色列": 16, "俄罗斯": 14, "乌克兰": 14,
    "菲律宾": 14, "马科斯": 16, "朝鲜": 14, "日本": 12, "韩国": 12,
    "原油": 10, "布伦特": 12, "欧佩克": 12,
    "辽宁": 12, "鞍山": 14, "沈阳": 12, "大连": 12,
}

LN_PRICE_URL = "https://fgw.ln.gov.cn/fgw/xxgk/jgjc/mrjg/index.shtml"

PRICE_WANT = ["鲜猪肉", "牛肉", "羊肉", "鸡肉", "鸡蛋", "豆油",
              "大米", "面粉", "大白菜", "黄瓜", "土豆", "西红柿",
              "青椒", "芸豆", "韭菜", "菠菜", "芹菜"]


# ========== 天气（原样保留你的） ==========
def fetch_weather():
    headers = {"X-QW-Api-Key": QW_KEY}
    now = requests.get(f"{API_HOST}/v7/weather/now",
                       params={"location": LOCATION}, headers=headers, timeout=10).json()
    hourly = requests.get(f"{API_HOST}/v7/weather/24h",
                          params={"location": LOCATION}, headers=headers, timeout=10).json()
    daily = requests.get(f"{API_HOST}/v7/weather/3d",
                         params={"location": LOCATION}, headers=headers, timeout=10).json()
    return {"now": now, "hourly": hourly, "daily": daily}


def build_weather_text(data):
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


# ========== 辽宁物价（原样保留你的） ==========
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


# ========== 单板块抓取（hard过滤+权重排序+兜底10条） ==========
def fetch_block(cfg):
    picked = []
    seen = set()
    for url in cfg["srcs"]:
        try:
            r = requests.get(url, timeout=10,
                             headers={"User-Agent": "Mozilla/5.0"})
            d = feedparser.parse(r.text)
        except Exception as ex:
            print(f"[{cfg['name']}] RSS拉取失败: {ex}")
            continue

        cands = []
        fill = []
        for e in d.entries:
            title = (e.get("title") or "").strip()
            link = (e.get("link") or "").strip()
            if not title or not link or title in seen:
                continue
            seen.add(title)
            hit = any(k in title for k in cfg["hard"])
            score = 0
            for k in cfg["hard"]:
                if k in title:
                    score += HOT_WEIGHT.get(k, len(k))
            if hit:
                cands.append((score, title, link))
            else:
                fill.append((title, link))

        cands.sort(key=lambda x: -x[0])
        for _, t, u in cands:
            if len(picked) >= cfg["cap"]:
                break
            picked.append((t, u))
        for t, u in fill:
            if len(picked) >= cfg["cap"]:
                break
            picked.append((t, u))

    # 兜底：不够10条用占位补满
    while len(picked) < cfg["cap"]:
        picked.append((f"（暂无更多{cfg['name']}资讯）", ""))

    return picked[:cfg["cap"]]


# ========== 飞书推送（加重试+频控处理） ==========
def push_feishu(text):
    if not WEBHOOK:
        raise RuntimeError("FEISHU_WEBHOOK 没配置")
    for attempt in range(3):
        try:
            resp = requests.post(WEBHOOK,
                                 json={"msg_type": "text", "content": {"text": text}},
                                 timeout=8)
            body = resp.json()
            code = body.get("code", 0)
            if code == 0:
                print("✅ 飞书发送成功")
                return
            print(f"飞书返回 code={code} msg={body.get('msg')}")
            if code in (11232, 9499):
                time.sleep(2 * (attempt + 1))
                continue
            raise RuntimeError(f"飞书错误 code={code} msg={body.get('msg')}")
        except Exception as e:
            print(f"推送异常: {e}")
            time.sleep(2)
    raise RuntimeError("飞书推送失败（重试3次）")


# ========== Main：分3条推送 ==========
def main():
    # 第1条：天气
    try:
        weather_data = fetch_weather()
        push_feishu(build_weather_text(weather_data))
        print("✅ 第1条（天气）完成")
    except Exception as e:
        print(f"❌ 第1条失败: {e}")

    time.sleep(2)

    # 第2条：军事 + 国际政治 + 亚洲台海
    try:
        lines = ["—— 新闻资讯（一） ——"]
        for name in ["军事", "国际政治", "亚洲台海"]:
            cfg = next(b for b in BLOCKS if b["name"] == name)
            items = fetch_block(cfg)
            lines.append(f"\n【{name}】（{len([x for x in items if x[0]])}条）")
            for t, u in items:
                if u:
                    lines.append(f"· {t}")
                    lines.append(f"  {u}")
                else:
                    lines.append(f"· {t}")
        push_feishu("\n".join(lines))
        print("✅ 第2条（军事/国际/台海）完成")
    except Exception as e:
        print(f"❌ 第2条失败: {e}")

    time.sleep(2)

    # 第3条：油气 + 辽宁民生 + 物价
    try:
        lines = ["—— 新闻资讯（二） ——"]
        for name in ["油气", "辽宁民生"]:
            cfg = next(b for b in BLOCKS if b["name"] == name)
            items = fetch_block(cfg)
            lines.append(f"\n【{name}】（{len([x for x in items if x[0]])}条）")
            for t, u in items:
                if u:
                    lines.append(f"· {t}")
                    lines.append(f"  {u}")
                else:
                    lines.append(f"· {t}")
        lines.append("\n" + price_block())
        push_feishu("\n".join(lines))
        print("✅ 第3条（油气/民生/物价）完成")
    except Exception as e:
        print(f"❌ 第3条失败: {e}")

    print("✅ 全部完成")


if __name__ == "__main__":
    main()
