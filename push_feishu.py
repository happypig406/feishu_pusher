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
CATEGORY_DEFS = [
    {
        "key": "military",
        "name": "军事",
        "feeds": [
            "http://www.chinanews.com.cn/rss/mil.xml",
            "http://www.chinanews.com.cn/rss/world.xml",
        ],
        "keywords": ["导弹", "无人机", "拦截", "战机", "航母", "军演", "海军", "空军", "核"],
        "min_items": 20,
    },
    {
        "key": "oil_gas",
        "name": "油气",
        "feeds": [
            "http://www.chinanews.com.cn/rss/finance.xml",
            "http://www.chinanews.com.cn/rss/world.xml",
        ],
        "keywords": ["石油", "油价", "原油", "布伦特", "成品油", "天然气", "油轮", "能源", "OPEC"],
        "min_items": 20,
    },
    {
        "key": "intl_politics",
        "name": "国际政治",
        "feeds": [
            "http://www.chinanews.com.cn/rss/world.xml",
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
            "http://www.chinanews.com.cn/rss/local.xml",
            "http://www.chinanews.com.cn/rss/finance.xml",
            "http://www.chinanews.com.cn/rss/world.xml",
        ],
        "keywords": ["辽宁", "鞍山", "沈阳", "抚顺", "本溪", "营口", "丹东", "锦州", "大连", "民生", "房价", "物价"],
        "min_items": 20,
    },
]

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


def _safe_json_from_resp(resp):
    try:
        return resp.json()
    except Exception:
        return None


def _normalize_section(body, section_name):
    # body may be wrapper like {'code':0, 'now': {...}} or the payload itself
    if not isinstance(body, dict):
        return {}
    if section_name in body and isinstance(body[section_name], (dict, list)):
        return body[section_name]
    # sometimes the API returns the section directly
    # e.g., body contains keys like 'temp', 'text'
    if section_name == 'now':
        if any(k in body for k in ('temp', 'text', 'feelsLike')):
            return body
    if section_name == 'hourly' and isinstance(body, dict) and 'hourly' in body:
        return body.get('hourly')
    if section_name == 'daily' and isinstance(body, dict) and 'daily' in body:
        return body.get('daily')
    return {}


# ========== 天气（兼容 header/key 两种认证方式，并在失败时打印调试信息） ==========
def fetch():
    if not QW_KEY:
        raise RuntimeError("QWEATHER_KEY 是空")

    base = normalize_api_base()
    session = requests.Session()

    # helper to try a GET and return JSON (or None)
    def try_get(url, params=None, headers=None):
        try:
            resp = session.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
            txt = resp.text[:1000]
            j = _safe_json_from_resp(resp)
            return j, txt, resp.status_code
        except Exception as e:
            return None, str(e), None

    now_json = hourly_json = daily_json = None

    # 1) 尝试用 header 方式（原来实现）
    headers = {"X-QW-Api-Key": QW_KEY}
    now_j, now_txt, now_code = try_get(f"{base}/v7/weather/now", params={"location": LOCATION}, headers=headers)
    hourly_j, hourly_txt, hourly_code = try_get(f"{base}/v7/weather/24h", params={"location": LOCATION}, headers=headers)
    daily_j, daily_txt, daily_code = try_get(f"{base}/v7/weather/3d", params={"location": LOCATION}, headers=headers)

    # If header mode didn't return useful payloads, 尝试用 key 作为 query 参数（很多 qweather 示例使用 key 参数）
    def useful(j):
        if not isinstance(j, dict):
            return False
        # contains expected keys
        if 'now' in j or 'temp' in j or 'code' in j:
            return True
        return False

    if not (useful(now_j) or useful(hourly_j) or useful(daily_j)):
        # Fallback: use key in params
        now_j2, now_txt2, now_code2 = try_get(f"{base}/v7/weather/now", params={"location": LOCATION, "key": QW_KEY})
        hourly_j2, hourly_txt2, hourly_code2 = try_get(f"{base}/v7/weather/24h", params={"location": LOCATION, "key": QW_KEY})
        daily_j2, daily_txt2, daily_code2 = try_get(f"{base}/v7/weather/3d", params={"location": LOCATION, "key": QW_KEY})
        # prefer ones that returned JSON
        now_j = now_j2 or now_j
        hourly_j = hourly_j2 or hourly_j
        daily_j = daily_j2 or daily_j

        # If still not useful, print short debug to logs so we can inspect
        if not (useful(now_j) or useful(hourly_j) or useful(daily_j)):
            print("天气接口返回内容不符合预期，下面是各接口的简短响应（最多1000字符）:")
            print("now status:", now_code, "text:", now_txt)
            print("hourly status:", hourly_code, "text:", hourly_txt)
            print("daily status:", daily_code, "text:", daily_txt)

    # Normalize sections to expected shapes
    now_sec = _normalize_section(now_j or {}, 'now')
    hourly_sec = _normalize_section(hourly_j or {}, 'hourly')
    daily_sec = _normalize_section(daily_j or {}, 'daily')

    # For compatibility with build_text which expects structures like {"now": {...}} and {"hourly": {...}}, return dict
    return {"now": {"now": now_sec}, "hourly": {"hourly": hourly_sec if isinstance(hourly_sec, list) else hourly_sec}, "daily": {"daily": daily_sec if isinstance(daily_sec, list) else daily_sec}}


def build_text(data):
    now = {}
    try:
        now = data.get("now", {}).get("now", {})
    except Exception:
        now = {}
    lines = ["监控推送 · 鞍山天气"]
    lines.append(
        f"当前：{now.get('text', '?')} {now.get('temp', '?')}℃ (体感 {now.get('feelsLike', '?')}℃)"
    )
    lines.append(
        f"湿度 {now.get('humidity', '?')}%  {now.get('windDir', '')}{now.get('windScale', '?')}级"
    )
    lines.append("")
    lines.append("—— 未来24小时 ——")
    hourly = data.get("hourly", {}).get("hourly", []) or []
    # hourly may be dict with 'fxTime' keys in subitems or another structure. Try to iterate safely.
    if isinstance(hourly, dict):
        hourly_list = hourly.get('hourly', []) if 'hourly' in hourly else []
    else:
        hourly_list = hourly
    for i, h in enumerate(hourly_list):
        try:
            if i % 3 != 0:
                continue
            fx_time = (h.get("fxTime") or "") if isinstance(h, dict) else ""
            t = fx_time[11:16] if len(fx_time) >= 16 else (h.get('time', '?') if isinstance(h, dict) else '?')
            lines.append(f"{t} {h.get('text', '?')} {h.get('temp', '?')}℃ 降水{h.get('pop', '0')}%")
        except Exception:
            continue
    lines.append("")
    lines.append("—— 未来3天 ——")
    daily = data.get("daily", {}).get("daily", []) or []
    if isinstance(daily, dict):
        daily_list = daily.get('daily', []) if 'daily' in daily else []
    else:
        daily_list = daily
    for d in daily_list[:3]:
        try:
            lines.append(
                f"{d.get('fxDate', '?')} {d.get('textDay', '?')} {d.get('tempMin', '?')}~{d.get('tempMax', '?')}℃"
            )
        except Exception:
            continue
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
        return format_feishu_post("辽宁物价", "\n".join(lines))
    for x in rows:
        lines.append(f"· {x}")
    lines.append("数据：辽宁省发改委")
    return format_feishu_post("辽宁物价", "\n".join(lines))


# ========== 新闻抓取：按分类聚合、评分与去重 ==========
def entry_published_dt(entry):
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
    for k in keywords:
        kl = k.lower()
        if kl in ttl or kl in summ:
            score += 10
    if published_dt:
        delta_days = (datetime.now(timezone.utc) - published_dt).days
        recency = max(0, 7 - delta_days)
        score += recency
    if len(title or "") > 40:
        score += 1
    return score


def fetch_news_category(defn):
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
    results.sort(key=lambda x: (x["score"], x["published"] or datetime(1970, 1, 1, tzinfo=timezone.utc)), reverse=True)
    return results


def build_news_blocks():
    blocks = []
    save_items = []
    for defn in CATEGORY_DEFS:
        name = defn["name"]
        items = fetch_news_category(defn)
        top_n = items[: max(defn.get("min_items", 20), 20)]
        section_lines = [f"【{name}】"]
        if not top_n:
            section_lines.append("（暂无可用条目）")
        else:
            for it in top_n:
                section_lines.append(f"· {it['title']}")
                section_lines.append(f"  {it['link']}")
        blocks.append("\n".join(section_lines))
        save_items.append(f"{name}:{ ' | '.join(it['title'] for it in top_n[:5]) }")
    return format_feishu_post("监控推送 · 重点资讯", "\n\n".join(blocks)), "\n".join(save_items)


def news_block():
    payload, key = build_news_blocks()
    last = ""
    if os.path.exists(NEWS_LAST_FILE):
        try:
            with open(NEWS_LAST_FILE, encoding="utf-8") as f:
                last = f.read().strip()
        except Exception:
            last = ""
    if key == last:
        return format_feishu_post("监控推送 · 重点资讯", "（无新条目）")
    try:
        with open(NEWS_LAST_FILE, "w", encoding="utf-8") as f:
            f.write(key)
    except Exception:
        pass
    return payload


# ========== 飞书推送（加重试+频控） ==========
def format_feishu_post(title, body_text):
    body_text = str(body_text or "")
    if not body_text:
        body_text = "(暂无内容)"
    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": [
                        [{"tag": "text", "text": body_text}]
                    ],
                }
            }
        },
    }


def push_feishu(text):
    if not WEBHOOK:
        raise RuntimeError("FEISHU_WEBHOOK 没配置")

    if isinstance(text, dict):
        payload = text
    else:
        text = str(text or "")
        if len(text) > 15000:
            text = text[:15000]
        payload = {"msg_type": "text", "content": {"text": text}}

    for attempt in range(3):
        try:
            resp = requests.post(WEBHOOK, json=payload, timeout=8)

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

            print(f"飞书返回 code={code} msg={body.get('msg')}")
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
    safe_send("第1条（天气）", lambda: format_feishu_post("监控推送 · 鞍山天气", build_text(fetch())))
    time.sleep(2)

    # 第2条：新闻（按分类）
    safe_send("第2条（新闻）", news_block)
    time.sleep(2)

    # 第3条：物价
    safe_send("第3条（物价）", price_block)

    print("✅ 全部完成")


if __name__ == "__main__":
    main()
