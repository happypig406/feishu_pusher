#!/usr/bin/env python3
import os
import re
import time
from datetime import datetime, timezone

import feedparser
import requests

# ========== 读取 Secrets（不用 dotenv，直接读 GitHub Actions 注入的环境变量） ==========
WEBHOOK = os.getenv("FEISHU_WEBHOOK")
QW_KEY = os.getenv("QWEATHER_KEY")
API_HOST = os.getenv("API_HOST")
LOCATION = os.getenv("LOCATION", "122.99,41.11")

NEWS_LAST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_news.txt")
REQUEST_TIMEOUT = 10

# ========== RSS 源与分类定义 ==========
# 为保证每类不少于 20 条，尽量聚合多条 feed（同源会去重）。
CATEGORY_DEFS = [
    {
        "key": "military",
        "name": "军事",
        "feeds": [
            "http://www.chinanews.com.cn/rss/mil.xml",
            "http://www.chinanews.com.cn/rss/world.xml",
        ],
        "keywords": ["导弹", "无人机", "拦截", "战机", "航母", "军演", "海军", "陆军", "空军", "核"],
        "min_items": 20,
    },
    {
        "key": "oil_gas",
        "name": "油气",
        "feeds": [
            "http://www.chinanews.com.cn/rss/finance.xml",
            "http://www.chinanews.com.cn/rss/world.xml",
        ],
        "keywords": ["石油", "油价", "原油", "布伦特", "成品油", "天然气", "油轮", "能源", "产量", "OPEC"],
        "min_items": 20,
    },
    {
        "key": "intl_politics",
        "name": "国际政治",
        "feeds": [
            "http://www.chinanews.com.cn/rss/world.xml",
            # 增加其他通用国际新闻源（如果某些环境没有网络或被屏蔽，代码会平滑降级）
            "http://rss.cnn.com/rss/edition_world.rss",
            "http://feeds.bbci.co.uk/news/world/rss.xml",
        ],
        "keywords": ["联合国", "峰会", "制裁", "外交", "协议", "冲突", "战略", "总统", "政府", "战争"],
        "min_items": 20,
    },
    {
        "key": "liaoning_life",
        "name": "辽宁民生",
        "feeds": [
            # 使用地方新闻和全国新闻中带有辽宁关键词的条目
            "http://www.chinanews.com.cn/rss/local.xml",
            "http://www.chinanews.com.cn/rss/finance.xml",
            "http://www.chinanews.com.cn/rss/world.xml",
        ],
        "keywords": ["辽宁", "鞍山", "沈阳", "抚顺", "本溪", "营口", "丹东", "锦州", "大连", "阜新", "民生", "楼市", "物价"],
        "min_items": 20,
    },
]

# ========== 其他配置 ==========
LN_PRICE_URL = "https://fgw.ln.gov.cn/fgw/xxgk/jgjc/mrjg/index.shtml"
PRICE_WANT = ["鲜猪肉", "牛肉", "羊肉", "鸡肉", "鸡蛋", "豆油",
              "大白菜", "黄瓜", "土豆", "西红柿", "青椒", "芸豆", "韭菜"]

# ========== 通用工具 ==========

def normalize_api_base():
    if not API_HOST:
        raise RuntimeError("API_HOST 是空，检查 Secrets 或 YAML env 注入")
    host = API_HOST.strip().rstrip("/")
    if host.startswith("http://") or host.startswith("https://"):
        return host
    return f"https://{host}"


def safe_get_json(session, url, params=None, headers=None):
    response = session.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
    try:
        body = response.json()
    except ValueError:
        raise RuntimeError(f"{url} 返回非 JSON：{response.text[:200]}")

    if isinstance(body, dict):
        code = body.get("code")
        if code not in (None, 0):
            raise RuntimeError(f"{url} 返回失败：code={code} msg={body.get('msg')} detail={body.get('detail')}")
    return body


# ========== 天气（修复URL拼接，适配你带 https:// 的 Secret） ==========
def fetch():
    if not QW_KEY:
        raise RuntimeError("QWEATHER_KEY 是空")

    base = normalize_api_base()
    headers = {"X-QW-Api-Key": QW_KEY}
    session = requests.Session()

    now = safe_get_json(session, f"{base}/v7/weather/now", {"location": LOCATION}, headers)
    hourly = safe_get_json(session, f"{base}/v7/weather/24h", {"location": LOCATION}, headers)
    daily = safe_get_json(session, f"{base}/v7/weather/3d", {"location": LOCATION}, headers)
    return {"now": now, "hourly": hourly, "daily": daily}


def build_text(data):
    now = data.get("now", {}).get("now", {})
    lines = ["监控推送 · 鞍山天气"]
    lines.append(
        f"当前：{now.get('text', '?')} {now.get('temp', '?')}℃ (体感 {now.get('feelsLike', '?')}℃)"
    )
    lines.append(
        f"湿度 {now.get('humidity', '?')}%  {now.get('windDir', '')}{now.get('windScale', '?')}级"
    )
    lines.append("")
    lines.append("—— 未来24小时 ——")
    hourly = data.get("hourly", {}).get("hourly", [])
    for i, h in enumerate(hourly):
        if i % 3 != 0:
            continue
        fx_time = (h.get("fxTime") or "")
        t = fx_time[11:16] if len(fx_time) >= 16 else "?"
        lines.append(f"{t} {h.get('text', '?')} {h.get('temp', '?')}℃ 降水{h.get('pop', '0')}%")
    lines.append("")
    lines.append("—— 未来3天 ——")
    for d in data.get("daily", {}).get("daily", [])[:3]:
        lines.append(
            f"{d.get('fxDate', '?')} {d.get('textDay', '?')} {d.get('tempMin', '?')}~{d.get('tempMax', '?')}℃"
        )
    return "\n".join(lines)


# ========== 辽宁物价 ==========
def fetch_ln_prices():
    try:
        r = requests.get(LN_PRICE_URL, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
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
    seen = set()
    for name in PRICE_WANT:
        pattern = re.escape(name) + r".*?([0-9]+(?:\.[0-9]+)?)"
        match = re.search(pattern, text)
        if not match:
            continue
        row = f"{name} {match.group(1)}元"
        if row in seen:
            continue
        seen.add(row)
        rows.append(row)

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


# ========== 新闻抓取：按分类聚合、评分与去重 ==========

def entry_published_dt(entry):
    # 返回 UTC datetime 或 None
    try:
        if "published_parsed" in entry and entry.published_parsed:
            t = time.mktime(entry.published_parsed)
            return datetime.fromtimestamp(t, tz=timezone.utc)
        if "updated_parsed" in entry and entry.updated_parsed:
            t = time.mktime(entry.updated_parsed)
            return datetime.fromtimestamp(t, tz=timezone.utc)
    except Exception:
        pass
    return None


def score_entry(title, summary, published_dt, keywords):
    score = 0
    ttl = (title or "").lower()
    summ = (summary or "").lower()
    # 关键字匹配：每个关键词匹配 +10
    for k in keywords:
        kl = k.lower()
        if kl in ttl or kl in summ:
            score += 10
    # 新近程度得分：7天内按天数加分
    if published_dt:
        delta_days = (datetime.now(timezone.utc) - published_dt).days
        recency = max(0, 7 - delta_days)
        score += recency
    # 简单长度/热度启发：标题长度较长轻微加分
    if len(title or "") > 40:
        score += 1
    return score


def fetch_news_category(defn):
    # 聚合 feeds，计算评分并返回排好序的条目列表
    results = []
    seen_titles = set()
    for feed_url in defn.get("feeds", []):
        try:
            d = feedparser.parse(feed_url)
            for e in d.entries:
                title = (e.get("title") or "").strip()
                link = (e.get("link") or "").strip()
                summary = (e.get("summary") or "")
                if not title or not link:
                    continue
                if title in seen_titles:
                    continue
                seen_titles.add(title)
                pub_dt = entry_published_dt(e)
                sc = score_entry(title, summary, pub_dt, defn.get("keywords", []))
                results.append({"title": title, "link": link, "score": sc, "published": pub_dt})
        except Exception as ex:
            print(f"[{defn.get('name')}] RSS失败 {feed_url}: {ex}")
    # 首先按 score 降序，再按发布时间降序
    results.sort(key=lambda x: (x["score"], x["published"] or datetime(1970, 1, 1, tzinfo=timezone.utc)), reverse=True)
    return results


def build_news_blocks():
    blocks = ["—— 军事/油气/国际/辽宁民生资讯 ——"]
    all_top_keys = []
    for defn in CATEGORY_DEFS:
        name = defn["name"]
        items = fetch_news_category(defn)
        # 尝试保证至少 min_items：如果不足，放宽（其实已聚合多源，通常够）
        if len(items) < defn.get("min_items", 20):
            # 如果不足，尝试再次从同源取更多（已取所有 entries），无法再扩充则直接使用已有
            pass
        top_n = items[: max(defn.get("min_items", 20), 20)]
        blocks.append(f"\n【{name}】")
        if not top_n:
            blocks.append("（暂无可用条目）")
            continue
        for it in top_n:
            # 格式：· 标题\n  链接
            blocks.append(f"· {it['title']}")
            blocks.append(f"  {it['link']}")
        # 用于去重检测：记录前 5 标题
        keys = "|".join(it["title"] for it in top_n[:5])
        all_top_keys.append(f"{name}:{keys}")
    # 保存组合 key
    save_key = "\n".join(all_top_keys)
    return "\n".join(blocks), save_key


def news_block():
    text, key = build_news_blocks()
    last = ""
    if os.path.exists(NEWS_LAST_FILE):
        try:
            with open(NEWS_LAST_FILE, encoding="utf-8") as f:
                last = f.read().strip()
        except Exception:
            last = ""
    if key == last:
        return "—— 军事/油气资讯 ——\n（无新条目）"
    try:
        with open(NEWS_LAST_FILE, "w", encoding="utf-8") as f:
            f.write(key)
    except Exception:
        pass
    return text


# ========== 飞书推送（加重试+频控） ==========
def push_feishu(text):
    if not WEBHOOK:
        raise RuntimeError("FEISHU_WEBHOOK 没配置")

    text = str(text or "")
    if len(text) > 15000:
        text = text[:15000]

    for attempt in range(3):
        try:
            resp = requests.post(
                WEBHOOK,
                json={"msg_type": "text", "content": {"text": text}},
                timeout=8,
            )

            try:
                body = resp.json()
            except ValueError:
                body = {"code": -1, "msg": resp.text[:200]}

            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")

            code = body.get("code", 0)
            if code == 0:
                print("✅ 飞书发送成功")
                return

            print(f"��书返回 code={code} msg={body.get('msg')}")
            if code in (11232, 9499):
                time.sleep(2 * (attempt + 1))
                continue
            raise RuntimeError(f"飞书错误 code={code} msg={body.get('msg')}")
        except Exception as e:
            print(f"推送异常: {e}")
            if attempt < 2:
                time.sleep(2)
                continue
            raise RuntimeError("飞书推送失败（重试3次）") from e

    raise RuntimeError("飞书推送失败（重试3次）")


# ========== Main：分3条推送 ==========
def main():
    def safe_send(label, sender):
        try:
            payload = sender()
            if payload is None:
                return
            push_feishu(payload)
            print(f"✅ {label} 完成")
        except Exception as e:
            print(f"❌ {label} 失败: {e}")
            if WEBHOOK:
                try:
                    push_feishu(f"⚠️ {label} 失败：{e}")
                except Exception:
                    pass

    # 第1条：天气
    safe_send("第1条（天气）", lambda: build_text(fetch()))
    time.sleep(2)

    # 第2条：新闻（按分类）
    safe_send("第2条（新闻）", news_block)
    time.sleep(2)

    # 第3条：物价
    safe_send("第3条（物价）", price_block)

    print("✅ 全部完成")


if __name__ == "__main__":
    main()
