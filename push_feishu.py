#!/usr/bin/env python3
import os
import re
import time
import requests
import feedparser

# ========== 读取 Secrets（不用 dotenv，直接读 GitHub Actions 注入的环境变量） ==========
WEBHOOK = os.getenv("FEISHU_WEBHOOK")
QW_KEY = os.getenv("QWEATHER_KEY")
API_HOST = os.getenv("API_HOST")
LOCATION = "122.99,41.11"

NEWS_LAST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_news.txt")

# 中新网官方RSS
RSS_SOURCES = [
    {
        "name": "军事",
        "url": "http://www.chinanews.com.cn/rss/mil.xml",
        "max": 4,
        "kw": [],
    },
    {
        "name": "军事",
        "url": "http://www.chinanews.com.cn/rss/world.xml",
        "max": 3,
        "kw": ["导弹", "无人机", "拦截", "俄", "乌", "以军", "以色列",
               "伊朗", "霍尔木兹", "美军", "北约", "演习", "核", "战机", "航母"],
    },
    {
        "name": "油气",
        "url": "http://www.chinanews.com.cn/rss/finance.xml",
        "max": 3,
        "kw": ["石油", "油价", "原油", "布伦特", "成品油", "调价",
               "天然气", "霍尔木兹", "油轮", "能源"],
    },
]

LN_PRICE_URL = "https://fgw.ln.gov.cn/fgw/xxgk/jgjc/mrjg/index.shtml"

PRICE_WANT = ["鲜猪肉", "牛肉", "羊肉", "鸡肉", "鸡蛋", "豆油",
              "大白菜", "黄瓜", "土豆", "西红柿", "青椒", "芸豆", "韭菜"]


# ========== 天气（修复URL拼接，适配你带 https:// 的 Secret） ==========
def fetch():
    if not API_HOST:
        raise RuntimeError("API_HOST 是空，检查 Secrets 或 YAML env 注入")
    if not QW_KEY:
        raise RuntimeError("QWEATHER_KEY 是空")

    # 自动处理：Secret 里带不带 https:// 都能正确拼
    if API_HOST.startswith("http://") or API_HOST.startswith("https://"):
        base = API_HOST.rstrip("/")
    else:
        base = f"https://{API_HOST}"

    headers = {"X-QW-Api-Key": QW_KEY}
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


# ========== 新闻（军事/油气） ==========
def fetch_news():
    results = []
    seen = set()
    for src in RSS_SOURCES:
        try:
            d = feedparser.parse(src["url"])
            count = 0
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
                results.append((src["name"], title, link))
                count += 1
                if count >= src["max"]:
                    break
        except Exception as ex:
            print(f"[{src['name']}] RSS失败: {ex}")
    return results


def news_block():
    items = fetch_news()
    if not items:
        return "—— 军事/油气资讯 ——\n（今日无匹配条目）"

    seen8 = set()
    dedup = []
    for s, t, u in items:
        k8 = t[:8]
        if k8 in seen8:
            continue
        seen8.add(k8)
        dedup.append((s, t, u))

    key = "\n".join(f"{s}|{t}" for s, t, _ in dedup)
    last = ""
    if os.path.exists(NEWS_LAST_FILE):
        last = open(NEWS_LAST_FILE, encoding="utf-8").read().strip()
    if key == last:
        return "—— 军事/油气资讯 ——\n（无新条目）"

    lines = ["—— 军事/油气资讯 ——"]
    cur = None
    for s, t, u in dedup:
        if s != cur:
            cur = s
            lines.append(f"\n【{s}】")
        lines.append(f"· {t}")
        lines.append(f"  {u}")

    open(NEWS_LAST_FILE, "w", encoding="utf-8").write(key)
    return "\n".join(lines)


# ========== 飞书推送（加重试+频控） ==========
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
        data = fetch()
        push_feishu(build_text(data))
        print("✅ 第1条（天气）完成")
    except Exception as e:
        print(f"❌ 第1条（天气）失败: {e}")
        try:
            push_feishu(f"⚠️ 天气推送失败：{e}")
        except Exception:
            pass

    time.sleep(2)

    # 第2条：新闻
    try:
        push_feishu(news_block())
        print("✅ 第2条（新闻）完成")
    except Exception as e:
        print(f"❌ 第2条（新闻）失败: {e}")

    time.sleep(2)

    # 第3条：物价
    try:
        push_feishu(price_block())
        print("✅ 第3条（物价）完成")
    except Exception as e:
        print(f"❌ 第3条（物价）失败: {e}")

    print("✅ 全部完成")


if __name__ == "__main__":
    main()
