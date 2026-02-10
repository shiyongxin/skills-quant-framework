# Skills 模块 API 参考文档

**版本：** v1.0
**更新日期：** 2026-02-06

---

## 目录

1. [数据获取模块 (stock_data_fetcher.py)](#1-数据获取模块)
2. [信号生成器 (signal_generator.py)](#2-信号生成器)
3. [技术分析器 (technical_analyzer.py)](#3-技术分析器)
4. [回测框架 (backtest_framework.py)](#4-回测框架)
5. [多因子选股 (multi_factor_selection.py)](#5-多因子选股)
6. [组合管理 (portfolio_manager.py)](#6-组合管理)
7. [实时监控 (real_time_monitor.py)](#7-实时监控)
8. [数据可视化 (chart_visualizer.py)](#8-数据可视化)

---

## 1. 数据获取模块

### StockDataFetcher

股票数据获取器，支持获取历史行情、财务指标、实时行情等。

#### 初始化

```python
from stock_data_fetcher import StockDataFetcher

fetcher = StockDataFetcher(data_dir="./stock_data")
```

**参数：**
- `data_dir` (str): 数据存储目录，默认 "./stock_data"

#### 方法

##### get_quote_data()

获取历史行情数据。

```python
df = fetcher.get_quote_data(
    symbol="600519",
    start_date="20230101",
    end_date="20231231",
    days=252
)
```

**参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| symbol | str | 是 | 股票代码，如 "600519" |
| start_date | str/datetime | 否 | 开始日期，格式 "20230101" |
| end_date | str/datetime | 否 | 结束日期，默认今天 |
| days | int | 否 | 获取天数，默认252（约1年） |

**返回：** DataFrame with columns: `日期, 开盘, 最高, 最低, 收盘, 成交量, 成交额, 涨跌幅`

---

##### calculate_technical_indicators()

计算技术指标。

```python
df = fetcher.calculate_technical_indicators(df)
```

**添加的指标：**
- **均线：** MA5, MA10, MA20, MA60, EMA20, EMA50
- **MACD：** MACD, MACD_Signal, MACD_Hist
- **RSI：** RSI (14日)
- **KDJ：** K, D, J
- **布林带：** BB_Middle, BB_Upper, BB_Lower, BB_Std
- **ATR：** ATR (14日)
- **成交量：** VOL_MA5

---

##### get_realtime_quote()

获取实时行情。

```python
quote = fetcher.get_realtime_quote("600519")
```

**返回：** dict with keys: `日期, 开盘, 最高, 最低, 收盘, 成交量, 涨跌幅`

---

##### batch_get_quotes()

批量获取多只股票数据。

```python
data_dict = fetcher.batch_get_quotes(
    symbols=["600519", "000858", "002415"],
    start_date="20230101",
    delay=0.5
)
```

**参数：**
- `symbols` (List[str]): 股票代码列表
- `start_date` (str/datetime): 开始日期
- `end_date` (str/datetime): 结束日期
- `delay` (float): 请求间隔（秒），避免频繁请求

---

## 2. 信号生成器

### SignalGenerator

根据技术指标生成买卖信号。

#### 初始化

```python
from signal_generator import SignalGenerator

generator = SignalGenerator()
```

#### 方法

##### generate_signals()

生成交易信号。

```python
df = generator.generate_signals(data)
```

**添加的信号列：**
| 列名 | 说明 | 取值范围 |
|------|------|----------|
| signal_ma_cross | 均线交叉信号 | -1, -0.5, 0, 0.5, 1 |
| signal_macd | MACD信号 | -1, -0.3, 0, 0.3, 1 |
| signal_kdj | KDJ信号 | -1, -0.5, 0, 0.5, 1 |
| signal_rsi | RSI信号 | -1, -0.2, 0, 0.2, 1 |
| signal_bb | 布林带信号 | -1, -0.5, 0, 0.5, 1 |
| signal_volume | 成交量信号 | -0.5, -0.2, 0, 0.3, 0.5 |
| signal_breakout | 突破信号 | -1, 0, 1 |
| signal_buy | 综合买入信号 | 0, 1 |
| signal_sell | 综合卖出信号 | 0, 1 |
| signal_strength | 信号强度 | -10 到 10 |

---

##### get_latest_signal()

获取最新信号。

```python
signal_info = generator.get_latest_signal(data)
```

**返回：**
```python
{
    'date': datetime,           # 日期
    'price': float,             # 价格
    'buy_signal': bool,         # 买入信号
    'sell_signal': bool,        # 卖出信号
    'strength': float,          # 信号强度 (-10到10)
    'ma_cross': float,          # 均线信号
    'macd': float,              # MACD信号
    'kdj': float,               # KDJ信号
    'rsi': float,               # RSI信号
    'bb': float,                # 布林带信号
    'volume': float,            # 成交量信号
    'breakout': float           # 突破信号
}
```

---

##### format_signal_report()

格式化信号报告。

```python
report = generator.format_signal_report(signal_info)
print(report)
```

**输出示例：**
```
============================================================
交易信号报告
============================================================

日期: 2026-02-06
价格: 1850.00 元

综合信号:
  买入信号: 是
  卖出信号: 否
  信号强度: +5.3

分项信号:
  均线: 买入 (金叉)
  MACD: 买入 (金叉)
  KDJ: 中性
  RSI: 买入 (超卖)
  布林带: 中性
  突破: 买入 (突破新高)

============================================================
```

---

## 3. 技术分析器

### TechnicalAnalyzer

技术分析指标计算和分析。

#### 初始化

```python
from technical_analyzer import TechnicalAnalyzer

analyzer = TechnicalAnalyzer()
```

#### 主要方法

##### calculate_all_indicators()

计算所有技术指标。

```python
df = analyzer.calculate_all_indicators(df)
```

##### get_support_resistance()

获取支撑位和阻力位。

```python
levels = analyzer.get_support_resistance(df, n=5)
```

**返回：**
```python
{
    'support': [1500, 1450, 1400, ...],    # 支撑位
    'resistance': [1600, 1650, 1700, ...]  # 阻力位
}
```

---

##### detect_pattern()

检测K线形态。

```python
pattern = analyzer.detect_pattern(df)
```

**可检测的形态：**
- 锤子线 (Hammer)
- 上吊线 (Hanging Man)
- 流星线 (Shooting Star)
- 吞没形态 (Engulfing)
- 三只乌鸦 (Three Black Crows)
- 三白兵 (Three White Soldiers)

---

## 4. 回测框架

### BacktestEngine

完整的回测引擎，支持多股票、止损止盈、多策略对比。

#### 初始化

```python
from backtest_framework import BacktestEngine, PositionConfig, PositionSizingMethod, StopLossMethod

engine = BacktestEngine(
    initial_cash=1000000,
    position_config=PositionConfig(
        sizing_method=PositionSizingMethod.EQUAL_WEIGHT,
        stop_loss_method=StopLossMethod.FIXED_PERCENTAGE,
        stop_loss_pct=0.05
    )
)
```

#### 配置类

##### PositionConfig

持仓配置类。

```python
config = PositionConfig(
    sizing_method=PositionSizingMethod.EQUAL_WEIGHT,    # 持仓方法
    stop_loss_method=StopLossMethod.FIXED_PERCENTAGE,   # 止损方法
    stop_loss_pct=0.05,                                  # 止损比例
    take_profit_pct=0.15,                                # 止盈比例
    max_positions=10,                                    # 最大持仓数
    position_size_pct=0.1                                # 单只股票仓位比例
)
```

**PositionSizingMethod 枚举：**
| 方法 | 说明 |
|------|------|
| FIXED | 固定金额 |
| EQUAL_WEIGHT | 等权重分配 |
| RISK_PARITY | 风险平价 |
| VOLATILITY_TARGET | 目标波动率 |
| KELLY_CRITERION | 凯利公式 |

**StopLossMethod 枚举：**
| 方法 | 说明 |
|------|------|
| NONE | 不止损 |
| FIXED_PERCENTAGE | 固定百分比止损 |
| ATR_TRAILING | ATR跟踪止损 |
| PEAK_TRAILING | 峰值跟踪止损 |

---

#### 方法

##### run_backtest()

运行回测。

```python
result = engine.run_backtest(
    data=data,           # 股票数据
    signals=signals      # 买卖信号
)
```

**返回：** BacktestResult对象

---

##### compare_strategies()

对比多个策略。

```python
strategies = {
    'MA交叉': ma_signals,
    'MACD': macd_signals,
    '多因子': multi_signals
}

comparison = engine.compare_strategies(data, strategies)
print(comparison.summary)
```

---

### BacktestResult

回测结果类。

#### 属性

```python
result.total_return       # 总收益率
result.annual_return      # 年化收益率
result.sharpe_ratio       # 夏普比率
result.sortino_ratio      # 索提诺比率
result.max_drawdown       # 最大回撤
result.calmar_ratio       # 卡玛比率
result.win_rate           # 胜率
result.profit_factor      # 盈亏比
result.equity_curve       # 净值曲线
result.trades             # 交易列表
```

#### 方法

##### generate_report()

生成报告。

```python
report = result.generate_report(format='text')  # 'text', 'html', 'dict'
print(report)
```

---

## 5. 多因子选股

### MultiFactorSelector

多因子选股模型，支持因子计算、有效性检验、组合优化。

#### 初始化

```python
from multi_factor_selection import MultiFactorSelector

selector = MultiFactorSelector()
```

#### 方法

##### calculate_factors()

计算所有因子。

```python
factors = selector.calculate_factors(stock_data)
```

**支持的因子类别：**
- **估值因子：** PE, PB, PS, PCF
- **成长因子：** 营收增长, 利润增长, ROE
- **质量因子：** ROA, 毛利率, 负债率
- **技术因子：** 动量, 波动率, 换手率
- **情绪因子：** 量比, 涨跌幅

---

##### select_stocks()

多因子选股。

```python
selected = selector.select_stocks(
    stock_pool=all_stocks,
    factor_weights={
        '估值': 0.3,
        '成长': 0.3,
        '质量': 0.2,
        '技术': 0.2
    },
    top_n=20
)
```

---

##### test_factor_validity()

因子有效性检验。

```python
validity = selector.test_factor_validity(factor_data)
```

**返回：**
```python
{
    'IC': 0.05,           # 信息系数
    'IC_mean': 0.04,
    'IC_std': 0.02,
    'IR': 2.0,            # 信息比率
    'p_value': 0.01       # 显著性水平
}
```

---

## 6. 组合管理

### PortfolioManager

投资组合管理器。

#### 初始化

```python
from portfolio_manager import PortfolioManager

manager = PortfolioManager()
```

#### 方法

##### create_portfolio()

创建组合。

```python
portfolio_id = manager.create_portfolio(
    name='我的策略',
    cash=1000000
)
```

---

##### add_position()

添加持仓。

```python
manager.add_position(
    portfolio_id=portfolio_id,
    symbol='600519',
    shares=100,
    price=1800
)
```

---

##### rebalance()

组合再平衡。

```python
manager.rebalance(
    portfolio_id=portfolio_id,
    target_weights={
        '600519': 0.3,
        '000858': 0.3,
        '002415': 0.4
    }
)
```

---

##### get_performance()

获取绩效。

```python
performance = manager.get_performance(portfolio_id)
```

---

## 7. 实时监控

### RealTimeMonitor

实时股票监控和告警。

#### 初始化

```python
from real_time_monitor import RealTimeMonitor, AlertCondition, AlertType, AlertPriority

monitor = RealTimeMonitor()
```

#### 方法

##### add_stock()

添加监控股票。

```python
monitor.add_stock(
    symbol='600519',
    name='贵州茅台'
)
```

---

##### add_condition()

添加监控条件。

```python
condition = AlertCondition(
    alert_type=AlertType.PRICE_ABOVE,
    threshold=2000,
    priority=AlertPriority.HIGH
)
monitor.add_condition('600519', condition)
```

**AlertType 枚举：**
| 类型 | 说明 |
|------|------|
| PRICE_ABOVE | 价格突破上限 |
| PRICE_BELOW | 价格跌破下限 |
| CHANGE_UP | 涨幅超限 |
| CHANGE_DOWN | 跌幅超限 |
| BREAKOUT_HIGH | 突破N日高点 |
| BREAKOUT_LOW | 跌破N日低点 |
| SIGNAL_BUY | 买入信号 |
| SIGNAL_SELL | 卖出信号 |
| VOLUME_SURGE | 成交量放大 |

**AlertPriority 枚举：** LOW, MEDIUM, HIGH, URGENT

---

##### check_conditions()

检查监控条件。

```python
alerts = monitor.check_conditions('600519')
for alert in alerts:
    print(alert.message)
```

---

##### register_callback()

注册告警回调。

```python
def my_handler(alert):
    send_email(alert.message)

monitor.register_callback(my_handler)
```

---

## 8. 数据可视化

### ChartVisualizer

图表可视化器。

#### 初始化

```python
from chart_visualizer import ChartVisualizer, ChartStyle

visualizer = ChartVisualizer(
    style=ChartStyle(),
    output_dir="charts"
)
```

#### ChartStyle 配置

```python
style = ChartStyle()
style.up_color = '#FF4444'        # 上涨颜色
style.down_color = '#00AA00'      # 下跌颜色
style.figure_size = (14, 8)       # 图表尺寸
style.dpi = 100                   # 分辨率
```

---

#### 方法

##### plot_candlestick()

绘制K线图。

```python
path = visualizer.plot_candlestick(
    data=df,
    symbol='600519',
    title='贵州茅台 - 日K线',
    ma_periods=[5, 10, 20, 60]
)
```

---

##### plot_macd()

绘制MACD图。

```python
path = visualizer.plot_macd(data=df, symbol='600519')
```

---

##### plot_equity_curve()

绘制收益曲线。

```python
path = visualizer.plot_equity_curve(
    equity_curve=equity_data,
    symbol='我的策略',
    benchmark_return=15.0
)
```

---

##### plot_combined_analysis()

绘制综合分析图（6合1）。

```python
path = visualizer.plot_combined_analysis(data=df, symbol='600519')
```

---

## 附录：数据格式

### 股票行情数据格式

```python
DataFrame({
    '日期': datetime,
    '开盘': float,
    '最高': float,
    '最低': float,
    '收盘': float,
    '成交量': float,
    '涨跌幅': float  # 可选
})
```

### 信号数据格式

```python
DataFrame({
    '日期': datetime,
    'signal_buy': bool,      # 买入信号
    'signal_sell': bool,     # 卖出信号
    'signal_strength': float # 信号强度
})
```

---

**文档版本：** v1.0
**最后更新：** 2026-02-06
