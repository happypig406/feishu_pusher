import os
import time
import requests
import feedparser

WEBHOOK = os.environ.get("FEISHU_WEBHOOK")

HOT_WEIGHT = {
    "普京": 10, "特朗普": 10, "内塔尼亚胡": 8, "导弹": 7, "军演": 6,
    "台海": 9, "赖清德": 9, "仁爱礁": 8, "钓鱼岛": 8, "解放军": 8,
    "霍尔木兹": 8, "布伦特": 7, "原油": 6, "欧佩克": 6
}

BLOCKS = [
    {
        "name": "军事",
        "srcs": [{"url": "http://www.chinanews.com.cn/rss/mil.xml"}],
        "hard": ["导弹", "军演", "普京", "特朗普", "台海", "解放军"],
        "cap": 10
    },
    {
        "name": "国际政治",
        "srcs": [{"url": "http://www.chinanews.com.cn/rss/world.xml"}],
        "hard": ["普京", "特朗普", "内塔尼亚胡", "伊朗", "朝鲜"],
        "cap": 10
    },
    {
        "name": "亚洲台海",
        "srcs": [{"url": "http://www.chinanews.com.cn/rss/world.xml"}, {"url": "http://www.chinanews.com.cn/rss/tw.xml"}],
        "hard": ["台海", "赖清德", "仁爱礁", "钓鱼岛", "解放军", "菲律宾", "朝鲜", "韩国"],
        "cap": 10
    },
    {
        "name": "油气",
        "srcs": [{"url": "http://www.chinanews.com.cn/rss/finance.xml"}],
        "hard": ["布伦特", "霍尔木兹", "原油", "欧佩克", "油价"],
        "cap": 10
    },
    {
        "name": "辽宁民生",
        "srcs": [{"url": "http://www.chinanews.com.cn/rss/society.xml"}, {"url": "http://www.chinanews.com.cn/rss/china.xml"}],
        "hard": ["辽宁", "鞍山", "沈阳", "大连", "供暖", "物价", "寒潮"],
        "cap": 10
    }
]

def sanitize(s):
    return str(s).replace("\n", " ").strip()

def relevance(title, hards):
    score = 0
    for k in hards:
        if k in title:
            score += HOT_WEIGHT.get(k, 3)
    return score

def build_text(content):
    return content

def fetch_weather():
    return "[天气模块占位]\n（请在此处接入你的真实天气获取代码）"

def price_block():
    return "—— 辽宁物价（全省均价） ——\n（暂无数据）"

def fetch_block(cfg):
    picked = []
    seen = set()
    for src in cfg["srcs"]:
        url = src["url"]
        try:
            r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            d = feedparser.parse(r.text)
        except Exception as ex:
            print(f"[{cfg['name']}] RSS拉取失败: {sanitize(str(ex))}")
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
        for t, u in fill:
            if len(picked) >= cfg["cap"]:
                break
            picked.append((t, u))
    return picked

def push_feishu(text):
    if not WEBHOOK:
        print("⚠️ FEISHU_WEBHOOK 未配置，跳过")
        return
    for attempt in range(3):
        try:
            resp = requests.post(WEBHOOK, json={"msg_type": "text", "content": {"text": text}}, timeout=8)
            try:
                body = resp.json()
            except Exception:
                body = {}
            code = body.get("code", 0)
            if code == 0:
                return
            print(f"飞书返回 code={code} msg={body.get('msg')}")
            if code in (11232, 9499):
                time.sleep(2 * (attempt + 1))
                continue
            return
        except Exception as e:
            print(f"推送异常: {sanitize(str(e))}")
            time.sleep(2)
    print("❌ 该条消息发送失败（已重试3次）")

def main():
    # 第1条：天气
    try:
        push_feishu(build_text(fetch_weather()))
        print("✅ 天气发送成功")
    except Exception as e:
        print(f"❌ 天气失败: {sanitize(str(e))}")

    time.sleep(1.5)

    # 第2条：军事 + 国际政治 + 亚洲台海
    try:
        part1 = ["—— 新闻资讯（一） ——"]
        for name in ["军事", "国际政治", "亚洲台海"]:
            cfg = next(b for b in BLOCKS if b["name"] == name)
            items = fetch_block(cfg)
            part1.append(f"\n【{name}】（{len(items)}条）")
            if not items:
                part1.append("（暂无）")
            for t, u in items:
                part1.append(f"· {t}")
                part1.append(f"  {u}")
        push_feishu("\n".join(part1))
        print("✅ 第一部分新闻发送成功")
    except Exception as e:
        print(f"❌ 第一部分失败: {sanitize(str(e))}")

    time.sleep(2)

    # 第3条：油气 + 辽宁民生 + 物价
    try:
        part2 = ["—— 新闻资讯（二） ——"]
        for name in ["油气", "辽宁民生"]:
            cfg = next(b for b in BLOCKS if b["name"] == name)
            items = fetch_block(cfg)
            part2.append(f"\n【{name}】（{len(items)}条）")
            if not items:
                part2.append("（暂无）")
            for t, u in items:
                part2.append(f"· {t}")
                part2.append(f"  {u}")
        part2.append("\n" + price_block())
        push_feishu("\n".join(part2))
        print("✅ 第二部分新闻+物价发送成功")
    except Exception as e:
        print(f"❌ 第二部分失败: {sanitize(str(e))}")

    print("✅ 全部完成")

if __name__ == "__main__":
    main()
