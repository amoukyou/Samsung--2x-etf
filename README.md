# 南方2倍做空三星电子 ETF 实时监控

**CSOP Samsung Electronics Daily (-2x) Inverse Product (7347.HK)**

实时追踪三星电子 (KRX:005930) 股价与 ETF 理论净值的偏离，帮助识别溢价/折价交易机会。

## 核心功能

- **理论NAV计算** — `NAV_t = NAV_{t-1} × (1 - 2 × r_t)`，基于三星每日收益逐日复合
- **偏离率监控** — 实际ETF价格 vs 理论NAV，识别情绪性溢价/折价
- **波动损耗分析** — 量化杠杆ETF的路径依赖损耗
- **时差处理** — 韩股KRX (UTC+9) vs 港股HKEX (UTC+8) 状态同步
- **自动刷新** — 实时报价30秒刷新，历史数据1小时刷新

## 可视化

- 价格归一化对比 (基准=100)
- ETF偏离率走势 (溢价/折价区间)
- 累计收益率对比
- 理论NAV vs 实际价格
- 逐日明细表格（偏离高亮）

## 部署

```bash
pip install -r requirements.txt
python server.py
# 访问 http://localhost:3471
```

## 数据来源

Yahoo Finance (yfinance)

## 技术栈

Python Flask + Chart.js + chartjs-plugin-annotation
