"""GitHub Actions 定时抓取三星电子 + ETF 数据，输出 data.json"""
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import re
from datetime import datetime
import yfinance as yf


def translate_to_zh(text):
    """用 Google Translate 免费接口翻译成中文"""
    if not text:
        return text
    try:
        url = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=zh-CN&dt=t&q=" + urllib.parse.quote(text[:500])
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return "".join(part[0] for part in data[0] if part[0])
    except Exception:
        return text


def fetch_google_news():
    """从 Google News RSS 获取三星电子相关新闻"""
    results = []
    queries = [
        "Samsung+Electronics+stock",
        "삼성전자",  # 韩文
        "Samsung+Electronics+strike+union",
        "Samsung+semiconductor",
    ]
    seen_titles = set()

    for q in queries:
        try:
            url = f"https://news.google.com/rss/search?q={q}&hl=en&gl=US&ceid=US:en"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                xml_data = resp.read().decode("utf-8")
            root = ET.fromstring(xml_data)
            for item in root.findall(".//item")[:8]:
                title = item.findtext("title", "")
                if not title or title in seen_titles:
                    continue
                seen_titles.add(title)
                link = item.findtext("link", "")
                pub_date = item.findtext("pubDate", "")
                source = item.findtext("source", "")
                # 清理HTML
                desc = item.findtext("description", "")
                desc = re.sub(r"<[^>]+>", "", desc)[:200] if desc else ""

                results.append({
                    "title": title,
                    "link": link,
                    "pub": source,
                    "time": pub_date,
                    "summary": desc,
                    "thumb": None,
                    "source": "google",
                })
        except Exception as e:
            print(f"  Google News ({q}) 失败: {e}")

    print(f"  Google News: {len(results)}条")
    return results


def classify_sentiment(title, summary=""):
    """判断新闻对三星股价的利多/利空倾向"""
    text = (title + " " + summary).lower()

    bearish_kw = [
        "strike", "罢工", "protest", "抗议",
        "downgrade", "下调", "sell", "卖出",
        "decline", "drop", "fall", "plunge", "crash", "slump", "tumble",
        "下跌", "暴跌", "大跌",
        "lawsuit", "诉讼", "fine", "罚款", "penalty", "处罚",
        "ban", "禁令", "sanction", "制裁", "tariff", "关税",
        "delay", "延迟", "shortage", "短缺",
        "loss", "亏损", "weak", "疲软",
        "risk", "风险", "concern", "担忧", "worry", "fear",
        "cut", "削减", "layoff", "裁员",
        "war", "战争", "conflict", "冲突",
    ]

    bullish_kw = [
        "upgrade", "上调", "buy", "买入",
        "rise", "rally", "surge", "jump", "soar", "gain",
        "上涨", "飙升", "大涨",
        "record", "创纪录", "beat", "超预期",
        "profit", "利润", "revenue", "营收", "earnings", "业绩",
        "growth", "增长", "expand", "扩张",
        "dividend", "分红", "buyback", "回购",
        "launch", "发布", "new", "新品",
        "breakthrough", "突破", "innovation", "创新",
        "ai", "hbm", "order", "订单", "deal", "合作",
        "target price raise", "目标价上调",
    ]

    bear_score = sum(1 for kw in bearish_kw if kw in text)
    bull_score = sum(1 for kw in bullish_kw if kw in text)

    if bear_score > bull_score:
        return "bearish"
    elif bull_score > bear_score:
        return "bullish"
    else:
        return "neutral"


def fetch():
    samsung = yf.Ticker("005930.KS")
    etf = yf.Ticker("7347.HK")

    sam_hist = samsung.history(start="2025-05-27", auto_adjust=False)
    etf_hist = etf.history(start="2025-05-27", auto_adjust=False)

    # 整理
    samsung_prices = []
    for idx, row in sam_hist.iterrows():
        samsung_prices.append({
            "date": str(idx)[:10],
            "close": round(float(row["Close"]), 2),
        })

    etf_prices = {}
    for idx, row in etf_hist.iterrows():
        etf_prices[str(idx)[:10]] = {
            "close": round(float(row["Close"]), 4),
            "high": round(float(row["High"]), 4),
            "low": round(float(row["Low"]), 4),
            "open": round(float(row["Open"]), 4),
        }

    samsung_prices.sort(key=lambda x: x["date"])

    # 计算理论NAV
    # ETF 2025-05-28 上市, 首日NAV = 7.26
    # 第一个计算日是 05-29 (用05-28的三星价格作为基准)
    initial_nav = 7.26
    nav = initial_nav
    prev_price = None
    results = []

    for item in samsung_prices:
        date = item["date"]
        price = item["close"]

        if date < "2025-05-28":
            continue

        if date == "2025-05-28":
            # 上市首日, NAV就是7.26, 记录但不计算变动
            prev_price = price
            ei = etf_prices.get(date)
            results.append({
                "d": date,
                "sp": price,
                "sr": 0,
                "tn": round(nav, 6),
                "ac": ei["close"] if ei else None,
                "ah": ei["high"] if ei else None,
                "al": ei["low"] if ei else None,
                "dv": round((ei["close"] - nav) / nav * 100, 2) if (ei and nav > 0) else None,
            })
            continue

        if prev_price is None:
            prev_price = price
            continue

        daily_ret = (price - prev_price) / prev_price
        nav = nav * (1 + (-2) * daily_ret)

        ei = etf_prices.get(date)
        ac = ei["close"] if ei else None
        dev = round((ac - nav) / nav * 100, 2) if (ac and nav > 0) else None

        results.append({
            "d": date,
            "sp": price,
            "sr": round(daily_ret * 100, 4),
            "tn": round(nav, 6),
            "ac": ac,
            "ah": ei["high"] if ei else None,
            "al": ei["low"] if ei else None,
            "dv": dev,
        })

        prev_price = price

    # 实时报价
    try:
        sam_info = samsung.fast_info
        etf_info = etf.fast_info
        realtime = {
            "sam_price": round(float(sam_info.last_price), 0),
            "sam_prev": round(float(sam_info.previous_close), 0),
            "etf_price": round(float(etf_info.last_price), 4),
            "etf_prev": round(float(etf_info.previous_close), 4),
        }
    except Exception:
        realtime = None

    # 统计
    if results:
        s_base = results[0]["sp"]
        t_base = results[0]["tn"]
        first_ac = next((r["ac"] for r in results if r["ac"]), 7.26)
        f = results[-1]
        sam_t = f["sp"] / s_base - 1
        s2x = -2 * sam_t
        th_r = f["tn"] / t_base - 1
        devs = [r["dv"] for r in results if r["dv"] is not None]

        stats = {
            "sam_total": round(sam_t * 100, 2),
            "s2x": round(s2x * 100, 2),
            "theo_ret": round(th_r * 100, 2),
            "act_ret": round((f["ac"] / first_ac - 1) * 100, 2) if f["ac"] else None,
            "drag": round((th_r - s2x) * 100, 2),
            "cur_dev": f["dv"],
            "max_prem": round(max(devs), 2) if devs else None,
            "max_disc": round(min(devs), 2) if devs else None,
            "s_base": s_base,
            "t_base": t_base,
            "a_base": first_ac,
        }
    else:
        stats = {}

    # ---- 日内数据 (5分钟K线, 最近2天) ----
    # 按天分组, 每天记录前收盘价
    intraday = {"days": []}
    try:
        sam_intra = samsung.history(period="2d", interval="5m", auto_adjust=False)
        etf_intra = etf.history(period="2d", interval="5m", auto_adjust=False)

        # 三星按天分组
        sam_by_day = {}
        for idx, row in sam_intra.iterrows():
            # idx 带时区, 转成 KST 日期
            kst_time = idx.tz_convert("Asia/Seoul")
            day = kst_time.strftime("%Y-%m-%d")
            if day not in sam_by_day:
                sam_by_day[day] = []
            sam_by_day[day].append({
                "t": int(idx.timestamp()),
                "p": round(float(row["Close"]), 0),
            })

        # ETF按天分组
        etf_by_day = {}
        for idx, row in etf_intra.iterrows():
            hkt_time = idx.tz_convert("Asia/Hong_Kong")
            day = hkt_time.strftime("%Y-%m-%d")
            if day not in etf_by_day:
                etf_by_day[day] = []
            etf_by_day[day].append({
                "t": int(idx.timestamp()),
                "p": round(float(row["Close"]), 4),
            })

        # 获取每天的前收盘价
        sam_daily = samsung.history(period="5d", interval="1d", auto_adjust=False)
        etf_daily = etf.history(period="5d", interval="1d", auto_adjust=False)

        sam_daily_closes = {}
        for idx, row in sam_daily.iterrows():
            d = str(idx)[:10]
            sam_daily_closes[d] = round(float(row["Close"]), 0)

        etf_daily_closes = {}
        for idx, row in etf_daily.iterrows():
            d = str(idx)[:10]
            etf_daily_closes[d] = round(float(row["Close"]), 4)

        all_days = sorted(set(list(sam_by_day.keys()) + list(etf_by_day.keys())))
        sam_daily_sorted = sorted(sam_daily_closes.keys())
        etf_daily_sorted = sorted(etf_daily_closes.keys())

        for day in all_days:
            # 找前一个交易日的收盘价
            sam_prev = None
            for d in sam_daily_sorted:
                if d < day:
                    sam_prev = sam_daily_closes[d]
            etf_prev = None
            for d in etf_daily_sorted:
                if d < day:
                    etf_prev = etf_daily_closes[d]

            intraday["days"].append({
                "date": day,
                "sam_prev": sam_prev,
                "etf_prev": etf_prev,
                "samsung": sam_by_day.get(day, []),
                "etf": etf_by_day.get(day, []),
            })

        total_sam = sum(len(d["samsung"]) for d in intraday["days"])
        total_etf = sum(len(d["etf"]) for d in intraday["days"])
        print(f"日内数据: {len(intraday['days'])}天, 三星{total_sam}条, ETF{total_etf}条")
        for day_data in intraday["days"]:
            print(f"  {day_data['date']}: sam_prev={day_data['sam_prev']}, etf_prev={day_data['etf_prev']}, sam={len(day_data['samsung'])}条, etf={len(day_data['etf'])}条")

    except Exception as e:
        print(f"日内数据获取失败: {e}")
        import traceback
        traceback.print_exc()

    # ---- 三星电子相关新闻 (Yahoo Finance + Google News) ----
    news = []
    seen_titles = set()
    try:
        # 1. Yahoo Finance 新闻
        sam_news = samsung.news
        for item in (sam_news or [])[:20]:
            content = item.get("content", item)
            title = content.get("title", item.get("title", ""))
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)
            summary = content.get("summary", content.get("description", ""))
            pub = content.get("pubDate", content.get("displayTime", ""))
            provider = content.get("provider", {})
            publisher = provider.get("displayName", item.get("publisher", ""))
            link = content.get("canonicalUrl", {}).get("url", item.get("link", ""))
            if not link:
                link = f"https://finance.yahoo.com/news/{item.get('id', '')}"
            thumb = None
            tn = content.get("thumbnail")
            if tn and tn.get("resolutions"):
                thumb = tn["resolutions"][-1].get("url") or tn["resolutions"][0].get("url")

            news.append({
                "title_en": title,
                "summary_en": summary[:200] if summary else "",
                "link": link,
                "pub": publisher,
                "time": pub,
                "thumb": thumb,
                "source": "yahoo",
            })
        print(f"  Yahoo Finance: {len(news)}条")

        # 2. Google News 补充
        google_news = fetch_google_news()
        for item in google_news:
            if item["title"] in seen_titles:
                continue
            seen_titles.add(item["title"])
            news.append({
                "title_en": item["title"],
                "summary_en": item["summary"],
                "link": item["link"],
                "pub": item["pub"],
                "time": item["time"],
                "thumb": None,
                "source": "google",
            })

        # 3. 分类利多/利空 + 翻译
        for n in news:
            n["sent"] = classify_sentiment(n["title_en"], n.get("summary_en", ""))
            n["title"] = translate_to_zh(n["title_en"])
            n["summary"] = translate_to_zh(n["summary_en"]) if n.get("summary_en") else ""

        # 按利空优先排(做空ETF角度利空=利多), 然后利多, 最后中性
        order = {"bearish": 0, "bullish": 1, "neutral": 2}
        news.sort(key=lambda x: (order.get(x["sent"], 2),))

        bull = sum(1 for n in news if n["sent"] == "bullish")
        bear = sum(1 for n in news if n["sent"] == "bearish")
        neut = sum(1 for n in news if n["sent"] == "neutral")
        print(f"新闻合计: {len(news)}条 (利多={bull}, 利空={bear}, 中性={neut})")
    except Exception as e:
        print(f"新闻获取失败: {e}")
        import traceback
        traceback.print_exc()

    output = {
        "updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "results": results,
        "stats": stats,
        "realtime": realtime,
        "intraday": intraday,
        "news": news,
    }

    with open("data.json", "w") as f:
        json.dump(output, f, separators=(",", ":"))

    print(f"完成: {len(results)} 条历史数据, 更新时间 {output['updated']}")


if __name__ == "__main__":
    fetch()
