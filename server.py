"""
南方2倍做空三星电子 ETF (7347.HK) 实时监控
- 三星电子 KRX:005930  韩国时间 09:00-15:30 (UTC+9)
- ETF 7347.HK          香港时间 09:30-16:00 (UTC+8)
"""

import json
import threading
import time
from datetime import datetime, timedelta

import yfinance as yf
from flask import Flask, jsonify, send_file

app = Flask(__name__)

# 缓存
cache = {
    "historical": None,
    "historical_ts": 0,
    "realtime": None,
    "realtime_ts": 0,
}
cache_lock = threading.Lock()

HIST_TTL = 3600       # 历史数据1小时刷新
REALTIME_TTL = 30     # 实时数据30秒刷新


def get_market_status():
    """判断韩股和港股当前是否开盘 (吉隆坡时间 UTC+8 显示)"""
    from zoneinfo import ZoneInfo
    now_utc = datetime.utcnow()

    # 韩国 KST = UTC+9
    kst = now_utc + timedelta(hours=9)
    krx_open = kst.weekday() < 5 and 900 <= kst.hour * 100 + kst.minute <= 1530

    # 香港 HKT = UTC+8
    hkt = now_utc + timedelta(hours=8)
    # 简化: 不考虑午休 (12:00-13:00)
    hkex_open = hkt.weekday() < 5 and 930 <= hkt.hour * 100 + hkt.minute <= 1600

    # 吉隆坡时间 MYT = UTC+8 (与HKT相同)
    myt = hkt

    return {
        "kst_time": kst.strftime("%Y-%m-%d %H:%M:%S KST"),
        "hkt_time": hkt.strftime("%Y-%m-%d %H:%M:%S HKT"),
        "myt_time": myt.strftime("%Y-%m-%d %H:%M:%S MYT"),
        "krx_open": krx_open,
        "hkex_open": hkex_open,
        "krx_status": "开盘中" if krx_open else "已收盘",
        "hkex_status": "开盘中" if hkex_open else "已收盘",
    }


def fetch_historical():
    """获取从ETF上市日到今天的全部历史数据"""
    samsung = yf.Ticker("005930.KS")
    etf = yf.Ticker("7347.HK")

    sam_hist = samsung.history(start="2025-05-27", auto_adjust=False)
    etf_hist = etf.history(start="2025-05-27", auto_adjust=False)

    # 整理三星数据
    samsung_data = {}
    for idx, row in sam_hist.iterrows():
        d = str(idx)[:10]
        samsung_data[d] = float(row["Close"])

    # 整理ETF数据
    etf_data = {}
    for idx, row in etf_hist.iterrows():
        d = str(idx)[:10]
        etf_data[d] = {
            "close": float(row["Close"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "open": float(row["Open"]),
        }

    # 按日期排序
    all_samsung_dates = sorted(samsung_data.keys())

    # 找到ETF上市日
    etf_start_date = "2025-05-28"
    # 需要前一天计算第一天的return
    start_idx = 0
    for i, d in enumerate(all_samsung_dates):
        if d >= etf_start_date:
            start_idx = max(0, i - 1)
            break

    samsung_dates = all_samsung_dates[start_idx:]

    # 计算理论NAV
    initial_nav = 7.26  # ETF首日价格
    nav = initial_nav
    prev_price = None
    results = []

    for date in samsung_dates:
        price = samsung_data[date]
        if prev_price is None:
            prev_price = price
            continue

        daily_ret = (price - prev_price) / prev_price
        etf_daily_ret = -2.0 * daily_ret
        nav = nav * (1 + etf_daily_ret)

        etf_info = etf_data.get(date, None)
        actual_close = etf_info["close"] if etf_info else None
        actual_high = etf_info["high"] if etf_info else None
        actual_low = etf_info["low"] if etf_info else None
        actual_open = etf_info["open"] if etf_info else None

        # 偏离率: (实际价格 - 理论NAV) / 理论NAV * 100
        deviation = None
        if actual_close and nav > 0:
            deviation = round((actual_close - nav) / nav * 100, 2)

        results.append({
            "date": date,
            "samsung_price": price,
            "samsung_return": round(daily_ret * 100, 4),
            "etf_daily_return": round(etf_daily_ret * 100, 4),
            "theoretical_nav": round(nav, 6),
            "actual_close": actual_close,
            "actual_open": actual_open,
            "actual_high": actual_high,
            "actual_low": actual_low,
            "deviation_pct": deviation,
        })

        prev_price = price

    # 累计收益率
    if results:
        s_base = results[0]["samsung_price"]
        t_base = results[0]["theoretical_nav"]
        a_base = results[0]["actual_close"] if results[0]["actual_close"] else 7.26

        for r in results:
            r["samsung_cum"] = round((r["samsung_price"] / s_base - 1) * 100, 2)
            r["theoretical_cum"] = round((r["theoretical_nav"] / t_base - 1) * 100, 2)
            if r["actual_close"]:
                r["actual_cum"] = round((r["actual_close"] / a_base - 1) * 100, 2)
            else:
                r["actual_cum"] = None

        # 统计
        final = results[-1]
        samsung_total = (final["samsung_price"] / s_base - 1)
        simple_2x = -2 * samsung_total
        theo_ret = (final["theoretical_nav"] / t_base - 1)
        drag = theo_ret - simple_2x

        # 偏离率统计
        devs = [r["deviation_pct"] for r in results if r["deviation_pct"] is not None]
        stats = {
            "samsung_total_return": round(samsung_total * 100, 2),
            "simple_minus2x": round(simple_2x * 100, 2),
            "theoretical_return": round(theo_ret * 100, 2),
            "actual_return": round((final["actual_close"] / a_base - 1) * 100, 2) if final["actual_close"] else None,
            "volatility_drag": round(drag * 100, 2),
            "current_deviation": final["deviation_pct"],
            "max_premium": round(max(devs), 2) if devs else None,
            "max_discount": round(min(devs), 2) if devs else None,
            "avg_deviation": round(sum(devs) / len(devs), 2) if devs else None,
            "data_points": len(results),
        }
    else:
        stats = {}

    return {"results": results, "stats": stats}


def fetch_realtime():
    """获取最新实时报价"""
    sam = yf.Ticker("005930.KS")
    etf = yf.Ticker("7347.HK")

    sam_info = sam.fast_info
    etf_info = etf.fast_info

    sam_price = float(sam_info.last_price) if hasattr(sam_info, "last_price") else None
    sam_prev = float(sam_info.previous_close) if hasattr(sam_info, "previous_close") else None
    etf_price = float(etf_info.last_price) if hasattr(etf_info, "last_price") else None
    etf_prev = float(etf_info.previous_close) if hasattr(etf_info, "previous_close") else None

    sam_change = None
    if sam_price and sam_prev:
        sam_change = round((sam_price / sam_prev - 1) * 100, 4)

    etf_change = None
    if etf_price and etf_prev:
        etf_change = round((etf_price / etf_prev - 1) * 100, 4)

    # 用最新三星日涨跌计算理论ETF应有变动
    expected_etf_change = None
    if sam_change is not None:
        expected_etf_change = round(-2 * sam_change, 4)

    return {
        "samsung_price": sam_price,
        "samsung_prev_close": sam_prev,
        "samsung_change_pct": sam_change,
        "etf_price": etf_price,
        "etf_prev_close": etf_prev,
        "etf_change_pct": etf_change,
        "expected_etf_change_pct": expected_etf_change,
        "intraday_deviation": round(etf_change - expected_etf_change, 4) if etf_change is not None and expected_etf_change is not None else None,
        "ts": datetime.utcnow().isoformat() + "Z",
    }


@app.route("/")
def index():
    return send_file("index.html")


@app.route("/api/historical")
def api_historical():
    now = time.time()
    with cache_lock:
        if cache["historical"] and now - cache["historical_ts"] < HIST_TTL:
            return jsonify(cache["historical"])

    data = fetch_historical()
    with cache_lock:
        cache["historical"] = data
        cache["historical_ts"] = time.time()
    return jsonify(data)


@app.route("/api/realtime")
def api_realtime():
    now = time.time()
    with cache_lock:
        if cache["realtime"] and now - cache["realtime_ts"] < REALTIME_TTL:
            data = cache["realtime"]
        else:
            data = None

    if data is None:
        try:
            data = fetch_realtime()
        except Exception as e:
            data = {"error": str(e)}
        with cache_lock:
            cache["realtime"] = data
            cache["realtime_ts"] = time.time()

    market = get_market_status()
    data["market_status"] = market
    return jsonify(data)


@app.route("/api/refresh")
def api_refresh():
    """强制刷新所有缓存"""
    with cache_lock:
        cache["historical"] = None
        cache["historical_ts"] = 0
        cache["realtime"] = None
        cache["realtime_ts"] = 0
    return jsonify({"status": "ok", "message": "缓存已清除"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3471, debug=False)
