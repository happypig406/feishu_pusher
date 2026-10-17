#!/usr/bin/env python3
import os
import re
import time
import requests
import feedparser

WEBHOOK = os.getenv("FEISHU_WEBHOOK")
QW_KEY = os.getenv("QWEATHER_KEY")
API_HOST = os.getenv("API_HOST")
LOCATION = "122.99,41.11"

NEWS_LAST_FILE = "news_last.txt"

# ========== 天气 ==========
def fetch_weather():
    if not API_HOST or not QW_KEY:
        raise RuntimeError("API_HOST 或 QWEATHER_KEY 没配置")
    url = f"https://{API_HOST}/v7/weather/now?location={LOCATION}&key={QW_KEY}"
    resp = requests.get(url, timeout=8)
    return resp.json()

def build_weather_text(data):
    if data.get("code") != "200":
        return f"⚠️ 天气获取失败: {data.get('code')}"
    now = data["now"]
    return (f"🌤️ 实时天气\n"
            f"天气：{now['text']}\n"
            f"气温：{now['temp']}℃ (体感 {now['feelsLike']}℃)\n"
            f"风向：{now['windDir']} {now['windScale']}级\n"
            f"湿度：{now['humidity']}%")

# ========== 新闻 RSS ==========
RSS_SOURCES = [
    {"name": "军事", "url": "http://www.xilu.com/rss/mil.xml", "max": 3, "kw": ["军事", "防务", "武器", "军队"]},
    {"name": "油气", "url": "https://oil.in-en.com/feed.xml", "max": 3, "kw": ["石油", "油气", "原油", "能源"]},
]

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
                if not title or not link or title in seen: continue
                kw = src.get("kw", [])
                if kw and not any(k in title for k in kw): continue
                seen.add(title)
                results.append((src["name"], title, link))
                count += 1
                if count >= src["max"]: break
        except Exception as ex:
            print(f"[{src['name']}] RSS失败: {ex}")
    return results

def news_block():
    items = fetch_news()
    if not items: return "—— 军事/油气资讯 ——\n（今日无匹配条目）"
    seen8 = set()
    dedup = []
    for s, t, u in items:
        k8 = t[:8]
        if k8 in seen8: continue
        seen8.add(k8)
        dedup.append((s, t, u))
    key = "\n".join(f"{s}|{t}" for s, t, _ in dedup)
    last = ""
    if os.path.exists(NEWS_LAST_FILE): last = open(NEWS_LAST_FILE, encoding="utf-8").read().strip()
    if key == last: return "—— 军事/油气资讯 ——\n（无新条目）"
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

# ========== 物价（占位） ==========
def price_block():
    return "—— 物价信息 ——\n（暂未配置）"

# ========== 飞书推送 ==========
def push_feishu(text):
    if not WEBHOOK: raise RuntimeError("FEISHU_WEBHOOK 没配置")
    for attempt in range(3):
        try:
            resp = requests.post(WEBHOOK, json={"msg_type": "text", "content": {"text": text}}, timeout=8)
            body = resp.json()
            code = body.get("code", 0)
            if code == 0:
                print("✅ 飞书真实发送成功")
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
    try:
        push_feishu(build_weather_text(fetch_weather()))
        print("✅ 第1条（天气）完成")
    except Exception as e: print(f"❌ 第1条失败: {e}")
    time.sleep(2)

    try:
        push_feishu(news_block())
        print("✅ 第2条（新闻）完成")
    except Exception as e: print(f"❌ 第2条失败: {e}")
    time.sleep(2)

    try:
        push_feishu(price_block())
        print("✅ 第3条（物价）完成")
    except Exception as e: print(f"❌ 第3条失败: {e}")
    print("✅ 全部完成")

if __name__ == "__main__":
    main()
