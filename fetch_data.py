"""GitHub Actions 定时抓取三星电子 + ETF 数据，输出 data.json"""
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import re
import time
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed


# ---- Yahoo Finance v8 直接接口 (不依赖 yfinance) ----

_HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def yf_chart(symbol, period1, period2=None, interval="1d"):
    """调用 Yahoo Finance chart API, 返回 {timestamps, closes, highs, lows, opens}"""
    if period2 is None:
        period2 = int(time.time())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?period1={period1}&period2={period2}&interval={interval}")
    req = urllib.request.Request(url, headers=_HDR)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    result = data["chart"]["result"][0]
    ts = result["timestamp"]
    q = result["indicators"]["quote"][0]
    return {
        "timestamps": ts,
        "closes": q["close"],
        "highs": q["high"],
        "lows": q["low"],
        "opens": q["open"],
        "meta": result["meta"],
    }


def yf_quote(symbol):
    """从 chart API meta 取实时报价"""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?range=1d&interval=1d")
    req = urllib.request.Request(url, headers=_HDR)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    meta = data["chart"]["result"][0]["meta"]
    return {
        "price": meta.get("regularMarketPrice", 0),
        "prevClose": meta.get("chartPreviousClose", meta.get("previousClose", 0)),
    }


def yf_news(symbol):
    """获取 Yahoo Finance 新闻"""
    url = f"https://query1.finance.yahoo.com/v1/finance/search?q={urllib.parse.quote(symbol)}&newsCount=20&quotesCount=0"
    req = urllib.request.Request(url, headers=_HDR)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("news", [])


# ---- 翻译 & 新闻 ----

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
        urllib.parse.quote("삼성전자"),
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


# ---- 主逻辑 ----

def fetch():
    t0 = time.time()

    # 并行获取所有数据
    SAM = "005930.KS"
    ETF = "7347.HK"
    p1_hist = int(datetime(2025, 5, 27, tzinfo=timezone.utc).timestamp())
    now_ts = int(time.time())

    print("并行请求数据...")
    with ThreadPoolExecutor(max_workers=8) as pool:
        f_sam_daily = pool.submit(yf_chart, SAM, p1_hist, now_ts, "1d")
        f_etf_daily = pool.submit(yf_chart, ETF, p1_hist, now_ts, "1d")
        f_sam_intra = pool.submit(yf_chart, SAM, now_ts - 3 * 86400, now_ts, "5m")
        f_etf_intra = pool.submit(yf_chart, ETF, now_ts - 3 * 86400, now_ts, "5m")
        f_sam_quote = pool.submit(yf_quote, SAM)
        f_etf_quote = pool.submit(yf_quote, ETF)
        f_yahoo_news = pool.submit(yf_news, "Samsung Electronics")
        f_google_news = pool.submit(fetch_google_news)

    sam_daily = f_sam_daily.result()
    etf_daily = f_etf_daily.result()
    print(f"  历史日线: 三星{len(sam_daily['timestamps'])}条, ETF{len(etf_daily['timestamps'])}条 ({time.time()-t0:.1f}s)")

    sam_intra = f_sam_intra.result()
    etf_intra = f_etf_intra.result()
    print(f"  日内5min: 三星{len(sam_intra['timestamps'])}条, ETF{len(etf_intra['timestamps'])}条 ({time.time()-t0:.1f}s)")

    sam_quote = f_sam_quote.result()
    etf_quote = f_etf_quote.result()
    print(f"  实时报价: ({time.time()-t0:.1f}s)")

    # ---- 整理日线数据 ----
    samsung_prices = []
    for i, ts in enumerate(sam_daily["timestamps"]):
        c = sam_daily["closes"][i]
        if c is None:
            continue
        d = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        samsung_prices.append({"date": d, "close": round(c, 2)})

    etf_prices = {}
    for i, ts in enumerate(etf_daily["timestamps"]):
        c = etf_daily["closes"][i]
        if c is None:
            continue
        d = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        etf_prices[d] = {
            "close": round(c, 4),
            "high": round(etf_daily["highs"][i] or c, 4),
            "low": round(etf_daily["lows"][i] or c, 4),
            "open": round(etf_daily["opens"][i] or c, 4),
        }

    samsung_prices.sort(key=lambda x: x["date"])

    # ---- 计算估算理论价 ----
    # 注意: 这是简化模型, 不考虑管理费/swap费/汇率(USD→HKD), 非官方NAV
    initial_nav = 7.26
    nav = initial_nav
    nav_before_last = initial_nav  # 上一个交易日的理论价, 用于日内基准
    prev_price = None
    results = []

    for item in samsung_prices:
        date = item["date"]
        price = item["close"]

        if date < "2025-05-28":
            continue

        if date == "2025-05-28":
            prev_price = price
            ei = etf_prices.get(date)
            results.append({
                "d": date, "sp": price, "sr": 0,
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

        nav_before_last = nav  # 保存本次计算前的理论价
        daily_ret = (price - prev_price) / prev_price
        nav = nav * (1 + (-2) * daily_ret)

        ei = etf_prices.get(date)
        ac = ei["close"] if ei else None
        dev = round((ac - nav) / nav * 100, 2) if (ac and nav > 0) else None

        results.append({
            "d": date, "sp": price,
            "sr": round(daily_ret * 100, 4),
            "tn": round(nav, 6),
            "ac": ac,
            "ah": ei["high"] if ei else None,
            "al": ei["low"] if ei else None,
            "dv": dev,
        })
        prev_price = price

    # ---- 实时报价 ----
    realtime = None
    try:
        if sam_quote and etf_quote:
            realtime = {
                "sam_price": round(float(sam_quote["price"]), 0),
                "sam_prev": round(float(sam_quote["prevClose"]), 0),
                "etf_price": round(float(etf_quote["price"]), 4),
                "etf_prev": round(float(etf_quote["prevClose"]), 4),
            }
    except Exception as e:
        print(f"实时报价处理失败: {e}")

    # ---- 统计 ----
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
            # 上一交易日的理论价, 供日内/实时计算用 (避免用ETF实际前收带入溢折价)
            "theo_prev": round(nav_before_last, 6),
        }
    else:
        stats = {}

    # ---- 日内数据 (5分钟K线) ----
    intraday = {"days": []}
    try:
        # 三星日内按天分组 (KST = UTC+9)
        sam_by_day = {}
        for i, ts in enumerate(sam_intra["timestamps"]):
            c = sam_intra["closes"][i]
            if c is None:
                continue

            kst = datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=9)))
            day = kst.strftime("%Y-%m-%d")
            if day not in sam_by_day:
                sam_by_day[day] = []
            sam_by_day[day].append({"t": ts, "p": round(c, 0)})

        # ETF日内按天分组 (HKT = UTC+8)
        etf_by_day = {}
        for i, ts in enumerate(etf_intra["timestamps"]):
            c = etf_intra["closes"][i]
            if c is None:
                continue

            hkt = datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=8)))
            day = hkt.strftime("%Y-%m-%d")
            if day not in etf_by_day:
                etf_by_day[day] = []
            etf_by_day[day].append({"t": ts, "p": round(c, 4)})

        # 前收盘价 (从日线数据取)
        sam_daily_closes = {}
        for i, ts in enumerate(sam_daily["timestamps"]):
            c = sam_daily["closes"][i]
            if c is not None:
                d = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
                sam_daily_closes[d] = round(c, 0)

        etf_daily_closes = {}
        for i, ts in enumerate(etf_daily["timestamps"]):
            c = etf_daily["closes"][i]
            if c is not None:
                d = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
                etf_daily_closes[d] = round(c, 4)

        all_days = sorted(set(list(sam_by_day.keys()) + list(etf_by_day.keys())))
        sam_daily_sorted = sorted(sam_daily_closes.keys())
        etf_daily_sorted = sorted(etf_daily_closes.keys())

        # 从日线结果中构建 日期→理论价 映射, 用于日内基准
        theo_nav_by_date = {}
        for r in results:
            theo_nav_by_date[r["d"]] = r["tn"]
        theo_dates_sorted = sorted(theo_nav_by_date.keys())

        for day in all_days:
            sam_prev = None
            for d in sam_daily_sorted:
                if d < day:
                    sam_prev = sam_daily_closes[d]
            etf_prev = None
            for d in etf_daily_sorted:
                if d < day:
                    etf_prev = etf_daily_closes[d]
            # 前一交易日的理论价 (不含当日溢折价)
            theo_prev = None
            for d in theo_dates_sorted:
                if d < day:
                    theo_prev = theo_nav_by_date[d]

            intraday["days"].append({
                "date": day,
                "sam_prev": sam_prev,
                "etf_prev": etf_prev,
                "theo_prev": round(theo_prev, 6) if theo_prev else None,
                "samsung": sam_by_day.get(day, []),
                "etf": etf_by_day.get(day, []),
            })

        # 当ETF日内数据为空但实时报价可用时, 用实时报价补一个点
        # (Yahoo对低流动性产品的5分钟K线有延迟, 但实时报价先到)
        if realtime and intraday["days"]:
            latest_day = intraday["days"][-1]
            if not latest_day["etf"] and latest_day["samsung"]:
                # 用三星最新数据点的时间戳, 补一个ETF实时价
                last_sam_ts = latest_day["samsung"][-1]["t"]
                latest_day["etf"].append({
                    "t": last_sam_ts,
                    "p": round(float(realtime["etf_price"]), 4),
                })
                print(f"  ETF日内数据为空, 用实时报价补点: {realtime['etf_price']}")

        total_sam = sum(len(d["samsung"]) for d in intraday["days"])
        total_etf = sum(len(d["etf"]) for d in intraday["days"])
        print(f"日内数据: {len(intraday['days'])}天, 三星{total_sam}条, ETF{total_etf}条")
    except Exception as e:
        print(f"日内数据获取失败: {e}")
        import traceback
        traceback.print_exc()

    # ---- 新闻 (Yahoo + Google 并行已完成) ----
    news = []
    seen_titles = set()
    try:
        yahoo_news = f_yahoo_news.result()
        for item in (yahoo_news or [])[:20]:
            title = item.get("title", "")
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)
            link = item.get("link", "")
            publisher = item.get("publisher", "")
            pub_time = ""
            if item.get("providerPublishTime"):
                pub_time = datetime.fromtimestamp(item["providerPublishTime"], tz=timezone.utc).isoformat()
            thumb = None
            if item.get("thumbnail", {}).get("resolutions"):
                thumb = item["thumbnail"]["resolutions"][-1].get("url")

            news.append({
                "title_en": title,
                "summary_en": "",
                "link": link,
                "pub": publisher,
                "time": pub_time,
                "thumb": thumb,
                "source": "yahoo",
            })
        print(f"  Yahoo Finance: {len(news)}条")

        google_news = f_google_news.result()
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

        # 分类 + 翻译
        for n in news:
            n["sent"] = classify_sentiment(n["title_en"], n.get("summary_en", ""))
            n["title"] = translate_to_zh(n["title_en"])
            n["summary"] = translate_to_zh(n["summary_en"]) if n.get("summary_en") else ""

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
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "results": results,
        "stats": stats,
        "realtime": realtime,
        "intraday": intraday,
        "news": news,
    }

    with open("data.json", "w") as f:
        json.dump(output, f, separators=(",", ":"))

    elapsed = time.time() - t0
    print(f"完成: {len(results)} 条历史数据, 耗时 {elapsed:.1f}s")


if __name__ == "__main__":
    fetch()
