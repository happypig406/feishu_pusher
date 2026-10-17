#!/usr/bin/env python3
import os
import re
import time
from datetime import datetime, timezone

import feedparser
import requests

# ========== 读取 Secrets（不用 dotenv，直接读 GitHub Actions 注入的环境变量） ==========
WEBHOOK = os.getenv("FEISHU_WEBHOOK")
QW_KEY = os.getenv("QWEATHER_KEY")  # 保留以兼容旧配置，但已不再使用
API_HOST = os.getenv("API_HOST")
LOCATION = os.getenv("LOCATION", "122.99,41.11")  # 已不再使用

NEWS_LAST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_news.txt")
REQUEST_TIMEOUT = 10

# ========== RSS 源与分类定义 ==========
# 我把你要求的来源添加进来了：人民网、澎湃（第三方 RSS）以及本地聚合源（通过 RSSHub）
CATEGORY_DEFS = [
    {
        "key": "military",
        "name": "军事",
        "feeds": [
            "http://www.chinanews.com.cn/rss/mil.xml",
            "http://www.chinanews.com.cn/rss/world.xml",
            # 人民网军事频道
            "http://www.people.com.cn/rss/military.xml",
            # 澎湃（第三方聚合）
            "https://rsshub.app/thepaper/featured",
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
            # 人民网财经/要闻（可提供更多宏观/能源类报道）
            "http://www.people.com.cn/rss/ywkx.xml",
            # 澎湃聚合（能源/财经相关也会出现在这里）
            "https://rsshub.app/thepaper/featured",
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
            # 人民网国际/时政
            "http://www.people.com.cn/rss/world.xml",
            "http://www.people.com.cn/rss/politics.xml",
            # 澎湃（第三方聚合）
            "https://rsshub.app/thepaper/featured",
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
            # 人民网要闻/社会（覆盖更多全国性与地方性报道）
            "http://www.people.com.cn/rss/ywkx.xml",
            "http://www.people.com.cn/rss/society.xml",
            # 澎湃（第三方聚合）
            "https://rsshub.app/thepaper/featured",
            # 本地聚合（通过 RSSHub）：网易、新浪的辽宁频道（第三方）
            "https://rsshub.app/netease/news/liaoning",
            "https://rsshub.app/sina/rollnews/liaoning",
        ],
        "keywords": ["辽宁", "鞍山", "沈阳", "抚顺", "本溪", "营口", "丹东", "锦州", "大连", "民生", "房价", "物价"],
        "min_items": 20,
    },
]

LN_PRICE_URL = "https://fgw.ln.gov.cn/fgw/xxgk/jgjc/mrjg/index.shtml"
PRICE_WANT = [
    "鲜猪肉", "牛肉", "羊肉", "鸡肉", "鸡蛋", "豆油",
    "大白菜", "黄瓜", "土豆", "西红柿", "青椒", "芸豆", "韭菜"
]

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
    # 兼容旧实现的接口结构（保留以备将来可��使用 API_HOST）
    if not isinstance(body, dict):
        return {}
    if section_name in body and isinstance(body[section_name], (dict, list)):
        return body[section_name]
    if section_name == 'now':
        if any(k in body for k in ('temp', 'text', 'feelsLike')):
            return body
    if section_name == 'hourly' and isinstance(body, dict) and 'hourly' in body:
        return body.get('hourly')
    if section_name == 'daily' and isinstance(body, dict) and 'daily' in body:
        return body.get('daily')
    return {}


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


# ========== 辽宁经济（尝试抓取若干关键指标，基于环境变量 LN_ECON_URL 可配置） ==========
LN_ECON_URL = os.getenv("LN_ECON_URL", "http://tjj.ln.gov.cn/")


def fetch_ln_economy():
    """尝试抓取并解析辽宁统计或政府网站上的若干经济指标（启发式），返回键值对列表。
    该函数尽量容错：若未设置或抓取失败，会返回空列表。
    """
    try:
        r = requests.get(LN_ECON_URL, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        text = re.sub(r"<.*?>", " ", r.text)
        text = re.sub(r"\s+", " ", text)
    except Exception as e:
        print("经济页拉取失败:", e)
        return []

    indicators = []

    patterns = [
        ("地区生产总值(GDP)", r"(地区生产总值|GDP)[：:\s]*([\d,.]+\s*(?:亿元|万亿元|万元|万|亿)?)"),
        ("CPI(居民消费价格指数)", r"(CPI|居民消费价格指数)[：:\s]*([\d.]+%)"),
        ("社会消费品零售总额", r"(社会消费品零售总额)[：:\s]*([\d,.]+\s*(?:亿元|万元|万)?)"),
        ("固定资产投资", r"(固定资产投资)[：:\s]*([\d,.]+\s*(?:亿元|万元|万)?)"),
        ("进出口总额", r"(进出口总额|进出口额)[：:\s]*([\d,.]+\s*(?:亿美元|亿元|万元)?)"),
    ]

    for label, pat in patterns:
        m = re.search(pat, text)
        if m:
            # 取最后一个捕获组作为值（数值+单位）
            val = m.group(len(m.groups()))
            indicators.append((label, val.strip()))

    # 如果未找到，也尝试抓取类似“同比”数据（例如：GDP同比+X%）
    if not indicators:
        for key in ["GDP", "同比", "增长"]:
            m = re.search(r"(GDP|地区生产总值).{0,30}([+-]?\d+\.\d+%|\d+%|增长\d+\.\d+%)", text)
            if m:
                indicators.append(("GDP同比/增长", m.group(2).strip()))
                break

    return indicators


def econ_block():
    # 合并物价与经济指标为一条推送
    price_rows, mtime = fetch_ln_prices()
    econ_items = fetch_ln_economy()

    lines = ["—— 辽宁经济与物价速览 ——"]
    if mtime:
        lines.append(f"物价监测时间：{mtime}")

    if price_rows:
        lines.append("\n*物价（全省均价）*")
        for p in price_rows:
            lines.append(f"· {p}")
        lines.append("来源：辽宁省发改委")
    else:
        lines.append("（物价数据暂未获取到）")

    if econ_items:
        lines.append("\n*经济指标（启发式抓取）*")
        for k, v in econ_items:
            lines.append(f"· {k}：{v}")
        lines.append("注：指标为页面抓取结果，可能需手动核验来源与口径。")
    else:
        lines.append("（未抓取到显著的经济指���；可通过设置环境变量 LN_ECON_URL 指向统计/政府发布页来改进）")

    return format_feishu_post("辽宁经济与物价", "\n".join(lines))


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


# ========== Main：分2条推送（新闻 + 辽宁经济/物价） ==========
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

    # 第1条：新闻（按分类）
    safe_send("第1条（新闻）", news_block)
    time.sleep(2)

    # 第2条：辽宁物价与经济
    safe_send("第2条（辽宁物价与经济）", econ_block)

    print("✅ 全部完成")


if __name__ == "__main__":
    main()
