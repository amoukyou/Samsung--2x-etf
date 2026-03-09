"""GitHub Actions 定时抓取三星电子 + ETF 数据，输出 data.json"""
import json
from datetime import datetime
import yfinance as yf


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
    intraday = {"samsung": [], "etf": []}
    try:
        sam_intra = samsung.history(period="2d", interval="5m", auto_adjust=False)
        for idx, row in sam_intra.iterrows():
            ts = int(idx.timestamp())
            intraday["samsung"].append({
                "t": ts,
                "p": round(float(row["Close"]), 0),
            })
    except Exception as e:
        print(f"三星日内数据获取失败: {e}")

    try:
        etf_intra = etf.history(period="2d", interval="5m", auto_adjust=False)
        for idx, row in etf_intra.iterrows():
            ts = int(idx.timestamp())
            intraday["etf"].append({
                "t": ts,
                "p": round(float(row["Close"]), 4),
            })
    except Exception as e:
        print(f"ETF日内数据获取失败: {e}")

    print(f"日内数据: 三星{len(intraday['samsung'])}条, ETF{len(intraday['etf'])}条")

    output = {
        "updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "results": results,
        "stats": stats,
        "realtime": realtime,
        "intraday": intraday,
    }

    with open("data.json", "w") as f:
        json.dump(output, f, separators=(",", ":"))

    print(f"完成: {len(results)} 条历史数据, 更新时间 {output['updated']}")


if __name__ == "__main__":
    fetch()
