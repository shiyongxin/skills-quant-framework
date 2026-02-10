# Skills 模块快速入门指南

**版本：** v1.0
**更新日期：** 2026-02-06

---

## 📚 目录

1. [简介](#简介)
2. [安装准备](#安装准备)
3. [5分钟快速上手](#5分钟快速上手)
4. [核心概念](#核心概念)
5. [常见使用场景](#常见使用场景)
6. [FAQ](#faq)

---

## 简介

Skills 是一个完整的 Python 股票量化分析框架，提供从数据获取、技术分析、信号生成、回测测试到组合管理的全流程功能。

### 主要功能

| 模块 | 功能 |
|------|------|
| 数据获取 | 获取A股历史行情、实时数据、财务指标 |
| 技术分析 | 计算30+技术指标，识别K线形态 |
| 信号生成 | 7种信号类型，综合评分系统 |
| 回测框架 | 完整回测引擎，支持止损止盈 |
| 多因子选股 | 5大类20+因子，有效性检验 |
| 组合管理 | 投资组合创建、分析、再平衡 |
| 实时监控 | 8种告警类型，自定义回调 |
| 数据可视化 | 8种图表类型，自定义样式 |

---

## 安装准备

### 环境要求

- Python 3.7+
- 依赖库：pandas, numpy, matplotlib, akshare

### 安装依赖

```bash
pip install pandas numpy matplotlib akshare openpyxl
```

### 目录结构

```
Stocks/
├── .claude/
│   └── skills/              # 模块目录
│       ├── stock_data_fetcher.py
│       ├── signal_generator.py
│       ├── backtest_framework.py
│       ├── multi_factor_selection.py
│       ├── portfolio_manager.py
│       ├── real_time_monitor.py
│       └── chart_visualizer.py
├── stock_data/              # 数据存储目录
├── charts/                  # 图表输出目录
└── examples/                # 示例代码
```

---

## 5分钟快速上手

### 第一步：获取股票数据

```python
from stock_data_fetcher import StockDataFetcher

# 创建数据获取器
fetcher = StockDataFetcher()

# 获取贵州茅台最近120天数据
data = fetcher.get_quote_data('600519', days=120)

# 计算技术指标
data = fetcher.calculate_technical_indicators(data)

# 查看最新数据
print(data[['日期', '收盘', 'MA5', 'MA20', 'MACD', 'RSI']].tail())
```

**输出：**
```
           收盘     MA5     MA20    MACD    RSI
日期
2026-02-01  1850.00  1845.2  1820.5   5.32   58.4
2026-02-02  1860.00  1850.1  1822.3   6.15   60.2
2026-02-03  1855.00  1852.3  1824.1   5.89   59.1
```

---

### 第二步：生成交易信号

```python
from signal_generator import SignalGenerator

# 创建信号生成器
generator = SignalGenerator()

# 获取最新信号
signal = generator.get_latest_signal(data)

# 打印信号报告
report = generator.format_signal_report(signal)
print(report)
```

**输出：**
```
============================================================
交易信号报告
============================================================

日期: 2026-02-06
价格: 1855.00 元

综合信号:
  买入信号: 是
  卖出信号: 否
  信号强度: +5.3

分项信号:
  均线: 买入 (金叉)
  MACD: 买入 (金叉)
  KDJ: 中性
  RSI: 强势区
  布林带: 中性
  突破: 买入 (突破新高)

============================================================
```

---

### 第三步：绘制K线图

```python
from chart_visualizer import ChartVisualizer

# 创建可视化器
visualizer = ChartVisualizer()

# 绘制K线图
path = visualizer.plot_candlestick(
    data=data,
    symbol='600519',
    title='贵州茅台 - 日K线',
    ma_periods=[5, 20, 60]
)

print(f"图表已保存: {path}")
```

**生成的图表：** `charts/600519_candlestick.png`

---

### 第四步：简单回测

```python
from backtest_framework import BacktestEngine, PositionConfig

# 创建回测引擎
engine = BacktestEngine(
    initial_cash=1000000,  # 初始资金100万
    position_config=PositionConfig(
        max_positions=5,    # 最多5只股票
        position_size_pct=0.2  # 单只股票20%
    )
)

# 生成完整信号
data_with_signals = generator.generate_signals(data)

# 运行回测
result = engine.run_backtest(
    data=data_with_signals,
    signals=data_with_signals
)

# 查看结果
print(result.generate_report())
```

**输出示例：**
```
============================================================
回测报告
============================================================

【基本信息】
  初始资金: 1,000,000 元
  最终资金: 1,235,600 元
  总收益率: 23.56%
  年化收益率: 18.23%

【风险指标】
  最大回撤: -8.45%
  夏普比率: 1.32
  索提诺比率: 1.85
  卡玛比率: 2.16

【交易统计】
  总交易次数: 24
  盈利交易: 16
  亏损交易: 8
  胜率: 66.67%
  盈亏比: 2.15

============================================================
```

---

## 核心概念

### 1. 数据格式

所有模块使用统一的数据格式（DataFrame）：

```python
DataFrame({
    '日期': datetime,     # 交易日期
    '开盘': float,        # 开盘价
    '最高': float,        # 最高价
    '最低': float,        # 最低价
    '收盘': float,        # 收盘价
    '成交量': float,      # 成交量
    '涨跌幅': float       # 涨跌幅(%)
})
```

### 2. 信号类型

| 信号 | 说明 | 取值 |
|------|------|------|
| signal_buy | 综合买入信号 | 0/1 |
| signal_sell | 综合卖出信号 | 0/1 |
| signal_strength | 信号强度 | -10到10 |

### 3. 回测流程

```
数据获取 → 技术指标 → 信号生成 → 回测 → 结果分析
```

### 4. 配置对象

大多数模块使用配置对象来设置参数：

```python
# 持仓配置
PositionConfig(
    sizing_method=...,      # 持仓方法
    stop_loss_method=...,   # 止损方法
    max_positions=...,      # 最大持仓数
    position_size_pct=...   # 仓位比例
)

# 图表样式
ChartStyle(
    up_color=...,      # 上涨颜色
    down_color=...,    # 下跌颜色
    figure_size=...    # 图表尺寸
)
```

---

## 常见使用场景

### 场景1：单只股票分析

```python
from stock_data_fetcher import StockDataFetcher
from signal_generator import SignalGenerator
from chart_visualizer import ChartVisualizer

# 获取数据
fetcher = StockDataFetcher()
data = fetcher.get_quote_data('600519', days=120)
data = fetcher.calculate_technical_indicators(data)

# 分析信号
generator = SignalGenerator()
signal = generator.get_latest_signal(data)

# 决策
if signal['buy_signal']:
    print(f"建议买入！信号强度: {signal['strength']}")
else:
    print("暂无买入信号")

# 绘图
visualizer = ChartVisualizer()
visualizer.plot_candlestick(data, '600519')
```

---

### 场景2：多股票筛选

```python
# 股票池
stocks = ['600519', '000858', '002415', '600036', '601318']

# 批量获取
all_data = fetcher.batch_get_quotes(stocks, days=120)

# 筛选买入信号
buy_signals = []
for symbol, data in all_data.items():
    if len(data) > 0:
        data = fetcher.calculate_technical_indicators(data)
        signal = generator.get_latest_signal(data)
        if signal['buy_signal'] and signal['strength'] > 5:
            buy_signals.append((symbol, signal['strength']))

# 排序
buy_signals.sort(key=lambda x: x[1], reverse=True)

print("强烈买入信号:")
for symbol, strength in buy_signals:
    print(f"  {symbol}: 强度 {strength:+.1f}")
```

---

### 场景3：策略回测

```python
from backtest_framework import BacktestEngine, PositionConfig

# 定义策略：MA金叉
data['MA5'] = data['收盘'].rolling(5).mean()
data['MA20'] = data['收盘'].rolling(20).mean()
data['signal_buy'] = (
    (data['MA5'] > data['MA20']) &
    (data['MA5'].shift(1) <= data['MA20'].shift(1))
)

# 回测
engine = BacktestEngine(initial_cash=1000000)
result = engine.run_backtest(data, data)

# 评估
if result.sharpe_ratio > 1.5:
    print("策略表现优秀！")
elif result.sharpe_ratio > 1.0:
    print("策略表现良好")
else:
    print("策略需要优化")
```

---

### 场景4：实时监控

```python
from real_time_monitor import (
    RealTimeMonitor,
    AlertCondition,
    AlertType,
    AlertPriority
)

# 创建监控器
monitor = RealTimeMonitor()

# 添加股票和条件
monitor.add_stock('600519', '贵州茅台')

# 价格告警
alert = AlertCondition(
    alert_type=AlertType.PRICE_ABOVE,
    threshold=2000,
    priority=AlertPriority.HIGH
)
monitor.add_condition('600519', alert)

# 定期检查
alerts = monitor.check_conditions('600519')
if alerts:
    print(f"触发 {len(alerts)} 个告警！")
    for alert in alerts:
        print(alert.message)
```

---

## FAQ

### Q1: 如何获取多只股票的数据？

```python
# 方法1：批量获取
stocks = ['600519', '000858', '002415']
all_data = fetcher.batch_get_quotes(stocks, days=120)

# 方法2：循环获取
all_data = {}
for symbol in stocks:
    data = fetcher.get_quote_data(symbol, days=120)
    all_data[symbol] = data
```

### Q2: 信号强度如何解读？

| 强度范围 | 解读 | 建议 |
|----------|------|------|
| > 7 | 强烈信号 | 积极买入 |
| 3 ~ 7 | 中等信号 | 考虑买入 |
| 0 ~ 3 | 弱信号 | 观望 |
| < -3 | 弱卖出信号 | 考虑卖出 |
| < -7 | 强卖出信号 | 积极卖出 |

### Q3: 回测结果如何才算好？

| 指标 | 优秀 | 良好 | 一般 |
|------|------|------|------|
| 年化收益率 | > 20% | > 10% | > 5% |
| 夏普比率 | > 2 | > 1 | > 0.5 |
| 最大回撤 | < -10% | < -20% | < -30% |
| 胜率 | > 60% | > 50% | > 40% |

### Q4: 如何优化策略参数？

```python
# 网格搜索
best_sharpe = -999
best_params = None

for short in [5, 10, 15]:
    for long in [20, 30, 40]:
        # 计算指标
        data['MA_Short'] = data['收盘'].rolling(short).mean()
        data['MA_Long'] = data['收盘'].rolling(long).mean()

        # 生成信号
        data['signal_buy'] = data['MA_Short'] > data['MA_Long']

        # 回测
        result = engine.run_backtest(data, data)

        # 记录最佳
        if result.sharpe_ratio > best_sharpe:
            best_sharpe = result.sharpe_ratio
            best_params = (short, long)

print(f"最佳参数: MA{best_params[0]} / MA{best_params[1]}")
```

### Q5: 图表支持哪些格式？

```python
# PNG（默认）
visualizer.plot_candlestick(data, '600519')

# 指定分辨率
style = ChartStyle()
style.dpi = 300
visualizer = ChartVisualizer(style=style)

# 自定义尺寸
style.figure_size = (20, 10)
```

### Q6: 如何处理数据缺失？

```python
# 方法1：前向填充
data = data.fillna(method='ffill')

# 方法2：删除
data = data.dropna()

# 方法3：跳过不足数据
if len(data) < 60:
    print("数据不足，跳过")
    continue
```

### Q7: 如何导出回测结果？

```python
# 导出交易记录
result.trades.to_csv('trades.csv', encoding='utf-8-sig')

# 导出净值曲线
result.equity_curve.to_csv('equity.csv', encoding='utf-8-sig')

# 导出完整报告
with open('report.txt', 'w', encoding='utf-8') as f:
    f.write(result.generate_report())
```

### Q8: 实时监控如何持续运行？

```python
import time

while True:
    # 检查所有股票
    all_alerts = monitor.check_all_stocks()

    # 处理告警
    for symbol, alerts in all_alerts.items():
        for alert in alerts:
            print(alert.message)

    # 等待下次检查
    time.sleep(3600)  # 每小时检查一次
```

---

## 下一步

1. 查看 [API 参考文档](API_REFERENCE.md) 了解详细API
2. 查看 [使用示例](USAGE_EXAMPLES.md) 学习更多用法
3. 运行 [examples](.claude/skills/examples/) 目录下的示例代码
4. 根据自己的需求定制策略

---

**文档版本：** v1.0
**最后更新：** 2026-02-06
**问题反馈：** 请在项目仓库提交 Issue
