# 南方2倍做空三星电子 ETF 实时监控

**CSOP Samsung Electronics Daily (-2x) Inverse Product (7347.HK)**

👉 **在线查看**: [https://amoukyou.github.io/Samsung--2x-etf/](https://amoukyou.github.io/Samsung--2x-etf/)

实时追踪三星电子 (KRX:005930) 股价与 ETF 理论净值的偏离，帮助识别溢价/折价交易机会。

## 核心功能

- **理论NAV计算** — `NAV_t = NAV_{t-1} × (1 - 2 × r_t)`，基于三星每日收益逐日复合
- **偏离率监控** — 实际ETF价格 vs 理论NAV，识别情绪性溢价/折价
- **波动损耗分析** — 量化杠杆ETF的路径依赖损耗（简单-2x预期 vs 实际收益）
- **时差处理** — 韩股KRX (UTC+9) vs 港股HKEX (UTC+8) 开收盘状态同步
- **自动刷新** — 实时报价60秒刷新

## 可视化图表

- **价格归一化对比** — 双Y轴(左=三星，右=ETF)，基准=100，3条线全部可见
- **偏离率走势** — 溢价区(金色)/折价区(蓝色)分色显示
- **累计收益率** — 双Y轴，三星 vs 理论ETF vs 实际ETF
- **理论NAV vs 实际价格** — 直接对比HKD价格
- **逐日明细表格** — 偏离超±3%高亮标注
- 所有图表支持鼠标悬停查看数据、十字线跟踪
- 直线连接数据点，休市日断开，真实反映开收盘价差

## 部署

纯前端静态应用，无需后端。

```bash
# 本地预览
open index.html

# 或部署到任意静态托管 (GitHub Pages, Netlify, Vercel...)
```

## 数据来源

Yahoo Finance API (通过CORS代理在浏览器端直接获取)

## 技术栈

HTML + JavaScript + Chart.js + chartjs-plugin-annotation
