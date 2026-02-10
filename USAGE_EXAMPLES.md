# Skills 模块使用示例

**版本：** v1.0
**更新日期：** 2026-02-06

---

## 目录

1. [快速入门](#快速入门)
2. [数据获取示例](#数据获取示例)
3. [技术分析示例](#技术分析示例)
4. [信号生成示例](#信号生成示例)
5. [回测示例](#回测示例)
6. [多因子选股示例](#多因子选股示例)
7. [组合管理示例](#组合管理示例)
8. [实时监控示例](#实时监控示例)
9. [数据可视化示例](#数据可视化示例)
10. [完整工作流示例](#完整工作流示例)

---

## 快速入门

### 5分钟上手

```python
# 1. 导入模块
from stock_data_fetcher import StockDataFetcher
from signal_generator import SignalGenerator
from chart_visualizer import ChartVisualizer

# 2. 获取数据
fetcher = StockDataFetcher()
data = fetcher.get_quote_data('600519', days=120)
data = fetcher.calculate_technical_indicators(data)

# 3. 生成信号
generator = SignalGenerator()
signal = generator.get_latest_signal(data)
print(f"买入信号: {signal['buy_signal']}")
print(f"信号强度: {signal['strength']:+.1f}")

# 4. 绘制图表
visualizer = ChartVisualizer()
visualizer.plot_candlestick(data, '600519')
```

---

## 数据获取示例

### 示例1：获取单只股票历史数据

```python
from stock_data_fetcher import StockDataFetcher

fetcher = StockDataFetcher()

# 获取最近120天数据
data = fetcher.get_quote_data('600519', days=120)

# 指定日期范围
data = fetcher.get_quote_data(
    symbol='600519',
    start_date='20230101',
    end_date='20231231'
)

print(f"数据范围: {data['日期'].min()} 到 {data['日期'].max()}")
print(f"共 {len(data)} 条记录")
```

### 示例2：批量获取多只股票

```python
# 定义股票池
stocks = ['600519', '000858', '002415', '600036', '000001']

# 批量获取
all_data = fetcher.batch_get_quotes(
    symbols=stocks,
    days=180,
    delay=0.5  # 每次请求间隔0.5秒
)

# 访问数据
for symbol, data in all_data.items():
    print(f"{symbol}: {len(data)} 条记录")
    print(f"  最新收盘价: {data['收盘'].iloc[-1]:.2f}")
```

### 示例3：获取实时行情

```python
# 获取实时行情
quote = fetcher.get_realtime_quote('600519')

print(f"股票: 600519")
print(f"最新价: {quote['收盘']:.2f}")
print(f"涨跌幅: {quote['涨跌幅']:+.2f}%")
print(f"成交量: {quote['成交量']:,.0f}")
```

### 示例4：导出综合报告到Excel

```python
# 导出Excel综合报告
fetcher.export_to_excel(
    symbol='600519',
    start_date='20230101',
    end_date='20231231'
)

# 会生成包含多个sheet的Excel文件：
# - 行情数据 (含技术指标)
# - 财务指标
```

---

## 技术分析示例

### 示例1：计算技术指标

```python
from stock_data_fetcher import StockDataFetcher

fetcher = StockDataFetcher()
data = fetcher.get_quote_data('600519', days=120)

# 计算所有技术指标
data = fetcher.calculate_technical_indicators(data)

# 查看最新指标
latest = data.iloc[-1]
print(f"收盘价: {latest['收盘']:.2f}")
print(f"MA5: {latest['MA5']:.2f}")
print(f"MA20: {latest['MA20']:.2f}")
print(f"MACD: {latest['MACD']:.2f}")
print(f"RSI: {latest['RSI']:.2f}")
print(f"K值: {latest['K']:.2f}")
print(f"D值: {latest['D']:.2f}")
```

### 示例2：查找支撑位和阻力位

```python
from technical_analyzer import TechnicalAnalyzer

analyzer = TechnicalAnalyzer()

# 获取支撑阻力位
levels = analyzer.get_support_resistance(data, n=5)

print("支撑位:")
for price in levels['support']:
    print(f"  {price:.2f}")

print("阻力位:")
for price in levels['resistance']:
    print(f"  {price:.2f}")
```

### 示例3：检测K线形态

```python
# 检测K线形态
pattern = analyzer.detect_pattern(data)

if pattern:
    print(f"发现形态: {pattern['name']}")
    print(f"类型: {pattern['type']}")  # 看涨/看跌
    print(f"可靠性: {pattern['reliability']}")  # 高/中/低
else:
    print("未检测到明显形态")
```

### 示例4：趋势判断

```python
# 判断当前趋势
trend = analyzer.analyze_trend(data)

print(f"趋势方向: {trend['direction']}")  # 上升/下降/横盘
print(f"趋势强度: {trend['strength']}")    # 强/中/弱
print(f"持续时间: {trend['duration']} 天")
```

---

## 信号生成示例

### 示例1：获取最新交易信号

```python
from stock_data_fetcher import StockDataFetcher
from signal_generator import SignalGenerator

# 获取数据并计算指标
fetcher = StockDataFetcher()
data = fetcher.get_quote_data('600519', days=120)
data = fetcher.calculate_technical_indicators(data)

# 生成信号
generator = SignalGenerator()
signal = generator.get_latest_signal(data)

# 打印信号报告
report = generator.format_signal_report(signal)
print(report)
```

### 示例2：批量检查多只股票

```python
stocks = ['600519', '000858', '002415', '600036']

for symbol in stocks:
    data = fetcher.get_quote_data(symbol, days=120)
    if len(data) > 0:
        data = fetcher.calculate_technical_indicators(data)
        signal = generator.get_latest_signal(data)

        print(f"\n{symbol}:")
        print(f"  价格: {signal['price']:.2f}")
        print(f"  买入: {signal['buy_signal']}")
        print(f"  卖出: {signal['sell_signal']}")
        print(f"  强度: {signal['strength']:+.1f}")
```

### 示例3：自定义信号过滤

```python
# 生成所有信号
data_with_signals = generator.generate_signals(data)

# 筛选强买入信号（强度>5）
strong_buy = data_with_signals[
    (data_with_signals['signal_buy'] == True) &
    (data_with_signals['signal_strength'] > 5)
]

print(f"发现 {len(strong_buy)} 个强买入信号")
print(strong_buy[['日期', '收盘', 'signal_strength']])
```

### 示例4：信号统计

```python
# 统计信号分布
data_with_signals = generator.generate_signals(data)

buy_signals = data_with_signals['signal_buy'].sum()
sell_signals = data_with_signals['signal_sell'].sum()
avg_strength = data_with_signals['signal_strength'].mean()

print(f"买入信号: {buy_signals} 次")
print(f"卖出信号: {sell_signals} 次")
print(f"平均强度: {avg_strength:+.2f}")
```

---

## 回测示例

### 示例1：简单回测

```python
from backtest_framework import BacktestEngine, PositionConfig

# 创建回测引擎
engine = BacktestEngine(
    initial_cash=1000000,
    position_config=PositionConfig(
        max_positions=10,
        position_size_pct=0.1
    )
)

# 准备数据
data = fetcher.get_quote_data('600519', days=252)
data = fetcher.calculate_technical_indicators(data)

# 生成信号
from signal_generator import SignalGenerator
generator = SignalGenerator()
data_with_signals = generator.generate_signals(data)

# 运行回测
result = engine.run_backtest(
    data=data_with_signals,
    signals=data_with_signals
)

# 打印结果
print(result.generate_report())
```

### 示例2：带止损止盈的回测

```python
from backtest_framework import PositionConfig, PositionSizingMethod, StopLossMethod

# 配置止损止盈
config = PositionConfig(
    sizing_method=PositionSizingMethod.EQUAL_WEIGHT,
    stop_loss_method=StopLossMethod.FIXED_PERCENTAGE,
    stop_loss_pct=0.05,      # 5%止损
    take_profit_pct=0.15,    # 15%止盈
    max_positions=5
)

engine = BacktestEngine(
    initial_cash=1000000,
    position_config=config
)

result = engine.run_backtest(data, signals)
print(f"最大回撤: {result.max_drawdown:.2%}")
print(f"夏普比率: {result.sharpe_ratio:.2f}")
```

### 示例3：多策略对比

```python
# 定义多个策略
strategies = {}

# 策略1: MA交叉
strategies['MA交叉'] = data.copy()
strategies['MA交叉']['signal_buy'] = (
    (strategies['MA交叉']['MA5'] > strategies['MA交叉']['MA20']) &
    (strategies['MA交叉']['MA5'].shift(1) <= strategies['MA交叉']['MA20'].shift(1))
)

# 策略2: MACD
strategies['MACD'] = data.copy()
strategies['MACD']['signal_buy'] = (
    (strategies['MACD']['MACD'] > strategies['MACD']['MACD_Signal']) &
    (strategies['MACD']['MACD'].shift(1) <= strategies['MACD']['MACD_Signal'].shift(1))
)

# 对比回测
comparison = engine.compare_strategies(data, strategies)

print(comparison.summary)
print("\n最佳策略:", comparison.best_strategy)
```

### 示例4：参数优化

```python
# 优化移动平均线参数
best_result = None
best_sharpe = -999

for short in range(5, 20, 5):
    for long in range(30, 60, 10):
        # 计算自定义均线
        data[f'MA{short}'] = data['收盘'].rolling(short).mean()
        data[f'MA{long}'] = data['收盘'].rolling(long).mean()

        # 生成信号
        data['signal_buy'] = (
            (data[f'MA{short}'] > data[f'MA{long}']) &
            (data[f'MA{short}'].shift(1) <= data[f'MA{long}'].shift(1))
        )

        # 回测
        result = engine.run_backtest(data, data)

        if result.sharpe_ratio > best_sharpe:
            best_sharpe = result.sharpe_ratio
            best_result = result
            best_params = (short, long)

print(f"最佳参数: MA{best_params[0]} / MA{best_params[1]}")
print(f"夏普比率: {best_sharpe:.2f}")
```

---

## 多因子选股示例

### 示例1：基础多因子选股

```python
from multi_factor_selection import MultiFactorSelector

selector = MultiFactorSelector()

# 准备股票池
stock_pool = ['600519', '000858', '002415', '600036', '000001',
              '600036', '000002', '601318', '600276', '002304']

# 获取数据
stock_data = {}
for symbol in stock_pool:
    data = fetcher.get_quote_data(symbol, days=252)
    if len(data) > 0:
        stock_data[symbol] = fetcher.calculate_technical_indicators(data)

# 多因子选股
selected = selector.select_stocks(
    stock_pool=stock_data,
    factor_weights={
        '估值': 0.3,
        '成长': 0.3,
        '质量': 0.2,
        '技术': 0.2
    },
    top_n=5
)

print("选股结果:")
for stock, score in selected:
    print(f"  {stock}: 综合得分 {score:.2f}")
```

### 示例2：因子有效性检验

```python
# 计算因子
factors = selector.calculate_factors(stock_data)

# 检验有效性
for factor_name in factors.columns:
    validity = selector.test_factor_validity(factors[[factor_name]])
    print(f"\n{factor_name}:")
    print(f"  IC: {validity['IC']:.3f}")
    print(f"  IR: {validity['IR']:.2f}")
    print(f"  显著性: {'显著' if validity['p_value'] < 0.05 else '不显著'}")
```

### 示例3：动态权重调整

```python
# 根据因子有效性动态调整权重
factor_validity = {}
for factor in ['估值', '成长', '质量', '技术']:
    validity = selector.test_factor_validity(factors[[factor]])
    factor_validity[factor] = validity['IR']

# 按IR比例分配权重
total_ir = sum(abs(v) for v in factor_validity.values())
dynamic_weights = {
    factor: abs(ir) / total_ir
    for factor, ir in factor_validity.items()
}

print("动态权重:")
for factor, weight in dynamic_weights.items():
    print(f"  {factor}: {weight:.1%}")

# 使用动态权重选股
selected = selector.select_stocks(
    stock_pool=stock_data,
    factor_weights=dynamic_weights,
    top_n=10
)
```

---

## 组合管理示例

### 示例1：创建和管理组合

```python
from portfolio_manager import PortfolioManager

manager = PortfolioManager()

# 创建组合
portfolio_id = manager.create_portfolio(
    name='我的策略',
    cash=1000000
)

# 添加持仓
manager.add_position(
    portfolio_id=portfolio_id,
    symbol='600519',
    shares=100,
    price=1800
)

# 查看组合
positions = manager.get_positions(portfolio_id)
print("当前持仓:")
for pos in positions:
    print(f"  {pos['symbol']}: {pos['shares']} 股")
```

### 示例2：组合再平衡

```python
# 目标权重
target_weights = {
    '600519': 0.3,
    '000858': 0.3,
    '002415': 0.2,
    '600036': 0.2
}

# 再平衡
manager.rebalance(
    portfolio_id=portfolio_id,
    target_weights=target_weights
)
```

### 示例3：获取绩效分析

```python
# 获取绩效
performance = manager.get_performance(portfolio_id)

print(f"总收益率: {performance['total_return']:.2%}")
print(f"年化收益率: {performance['annual_return']:.2%}")
print(f"夏普比率: {performance['sharpe_ratio']:.2f}")
print(f"最大回撤: {performance['max_drawdown']:.2%}")
print(f"胜率: {performance['win_rate']:.2%}")
```

### 示例4：风险分析

```python
# 获取风险指标
risk = manager.get_risk_metrics(portfolio_id)

print(f"组合波动率: {risk['volatility']:.2%}")
print(f"Beta: {risk['beta']:.2f}")
print(f"VaR (95%): {risk['var_95']:.2%}")
print(f"CVaR: {risk['cvar']:.2%}")
```

---

## 实时监控示例

### 示例1：价格监控

```python
from real_time_monitor import RealTimeMonitor, AlertCondition, AlertType, AlertPriority

monitor = RealTimeMonitor()

# 添加监控股票
monitor.add_stock('600519', '贵州茅台')

# 设置价格告警
upper_alert = AlertCondition(
    alert_type=AlertType.PRICE_ABOVE,
    threshold=2000,
    priority=AlertPriority.HIGH
)
monitor.add_condition('600519', upper_alert)

lower_alert = AlertCondition(
    alert_type=AlertType.PRICE_BELOW,
    threshold=1500,
    priority=AlertPriority.HIGH
)
monitor.add_condition('600519', lower_alert)
```

### 示例2：信号监控

```python
# 添加买卖信号监控
buy_alert = AlertCondition(
    alert_type=AlertType.SIGNAL_BUY,
    priority=AlertPriority.MEDIUM
)
monitor.add_condition('600519', buy_alert)

sell_alert = AlertCondition(
    alert_type=AlertType.SIGNAL_SELL,
    priority=AlertPriority.MEDIUM
)
monitor.add_condition('600519', sell_alert)

# 检查条件
alerts = monitor.check_conditions('600519')
for alert in alerts:
    print(alert.message)
```

### 示例3：自定义告警处理

```python
# 定义告警回调
def email_handler(alert):
    import smtplib
    # 发送邮件
    send_email(
        to='trader@example.com',
        subject=f"股票告警: {alert.symbol}",
        body=alert.message
    )

def wechat_handler(alert):
    # 发送微信通知
    send_wechat(alert.message)

# 注册回调
monitor.register_callback(email_handler)
monitor.register_callback(wechat_handler)

# 检查时会自动触发回调
monitor.check_conditions('600519')
```

### 示例4：监控报告

```python
# 生成监控报告
report = monitor.generate_monitor_report()
print(report)

# 获取告警历史
alerts = monitor.get_alert_history(unread_only=True, limit=10)
for alert in alerts:
    print(f"{alert.timestamp}: {alert.message}")
```

---

## 数据可视化示例

### 示例1：绘制K线图

```python
from chart_visualizer import ChartVisualizer, ChartStyle

# 创建可视化器
visualizer = ChartVisualizer()

# 绘制K线图
path = visualizer.plot_candlestick(
    data=data,
    symbol='600519',
    title='贵州茅台 - 日K线',
    ma_periods=[5, 10, 20, 60]
)
print(f"图表已保存: {path}")
```

### 示例2：绘制综合分析图

```python
# 绘制6合1综合图
path = visualizer.plot_combined_analysis(
    data=data,
    symbol='600519'
)
```

### 示例3：批量生成图表

```python
stocks = ['600519', '000858', '002415']

for symbol in stocks:
    data = fetcher.get_quote_data(symbol, days=120)
    if len(data) > 0:
        data = fetcher.calculate_technical_indicators(data)

        # 生成多种图表
        visualizer.plot_candlestick(data, symbol)
        visualizer.plot_macd(data, symbol)
        visualizer.plot_rsi(data, symbol)
        visualizer.plot_bollinger_bands(data, symbol)
```

### 示例4：绘制回测结果

```python
# 绘制净值曲线
equity_data = pd.DataFrame({
    'date': result.equity_curve.index,
    'value': result.equity_curve.values
})

visualizer.plot_equity_curve(
    equity_curve=equity_data,
    symbol='回测策略',
    benchmark_return=15.0
)

# 绘制回撤曲线
visualizer.plot_drawdown(
    equity_curve=equity_data,
    symbol='回测策略'
)
```

### 示例5：自定义样式

```python
# 创建自定义样式
style = ChartStyle()
style.up_color = '#FF0000'        # 红色上涨
style.down_color = '#00FF00'      # 绿色下跌
style.figure_size = (16, 9)       # 更大的尺寸
style.dpi = 150                   # 更高分辨率

visualizer = ChartVisualizer(style=style)
visualizer.plot_candlestick(data, '600519')
```

---

## 完整工作流示例

### 量化策略完整流程

```python
from stock_data_fetcher import StockDataFetcher
from signal_generator import SignalGenerator
from backtest_framework import BacktestEngine, PositionConfig
from chart_visualizer import ChartVisualizer

# 1. 获取数据
print("Step 1: 获取数据...")
fetcher = StockDataFetcher()
data = fetcher.get_quote_data('600519', days=252)
data = fetcher.calculate_technical_indicators(data)

# 2. 生成信号
print("Step 2: 生成信号...")
generator = SignalGenerator()
data_with_signals = generator.generate_signals(data)

# 3. 回测
print("Step 3: 回测...")
engine = BacktestEngine(
    initial_cash=1000000,
    position_config=PositionConfig(
        max_positions=5,
        position_size_pct=0.2
    )
)

result = engine.run_backtest(
    data=data_with_signals,
    signals=data_with_signals
)

# 4. 打印结果
print("\n" + "="*50)
print("回测结果")
print("="*50)
print(result.generate_report())

# 5. 绘制图表
print("\nStep 4: 生成图表...")
visualizer = ChartVisualizer()

# K线图
visualizer.plot_candlestick(data, '600519')

# 净值曲线
equity_data = pd.DataFrame({
    'date': result.equity_curve.index,
    'value': result.equity_curve.values
})
visualizer.plot_equity_curve(equity_data, '600519策略')

# 回撤曲线
visualizer.plot_drawdown(equity_data, '600519策略')

print("\n完成！")
```

### 多股票组合策略

```python
from multi_factor_selection import MultiFactorSelector
from portfolio_manager import PortfolioManager

# 1. 股票池
stock_pool = ['600519', '000858', '002415', '600036', '000001',
              '601318', '600276', '002304', '000333', '600887']

# 2. 多因子选股
print("Step 1: 多因子选股...")
selector = MultiFactorSelector()

stock_data = {}
for symbol in stock_pool:
    data = fetcher.get_quote_data(symbol, days=252)
    if len(data) > 0:
        stock_data[symbol] = fetcher.calculate_technical_indicators(data)

selected = selector.select_stocks(
    stock_pool=stock_data,
    factor_weights={
        '估值': 0.25,
        '成长': 0.25,
        '质量': 0.25,
        '技术': 0.25
    },
    top_n=5
)

print(f"选出 {len(selected)} 只股票:")
for stock, score in selected:
    print(f"  {stock}: {score:.2f}")

# 3. 创建组合
print("\nStep 2: 创建组合...")
manager = PortfolioManager()
portfolio_id = manager.create_portfolio('多因子策略', 1000000)

# 4. 等权重配置
print("Step 3: 配置组合...")
selected_symbols = [s[0] for s in selected]
weight_per_stock = 1.0 / len(selected_symbols)
target_weights = {s: weight_per_stock for s in selected_symbols}

manager.rebalance(portfolio_id, target_weights)

# 5. 分析组合
print("\nStep 4: 分析组合...")
performance = manager.get_performance(portfolio_id)
risk = manager.get_risk_metrics(portfolio_id)

print(f"预期年化收益: {performance['annual_return']:.2%}")
print(f"预期波动率: {risk['volatility']:.2%}")
print(f"夏普比率: {performance['sharpe_ratio']:.2f}")
```

---

## 常见代码片段

### 数据预处理

```python
# 填充缺失值
data = data.fillna(method='ffill')

# 过滤交易天数不足的股票
data = data.dropna(subset=['MA20'])

# 按日期过滤
data = data[data['日期'] >= '2023-01-01']
```

### 信号处理

```python
# 平滑信号：连续信号只保留第一个
data['signal_buy_new'] = (
    data['signal_buy'] &
    ~data['signal_buy'].shift(1).fillna(False)
)

# 信号确认：需要连续2天才触发
data['signal_buy_confirmed'] = (
    data['signal_buy'] &
    data['signal_buy'].shift(1).fillna(False)
)
```

### 回测后处理

```python
# 过滤小交易
result.trades = result.trades[result.trades['amount'] > 10000]

# 按月份统计收益
monthly_returns = result.equity_curve.resample('M').last().pct_change()

# 计算滚动夏普
rolling_sharpe = (
    result.equity_curve.pct_change().rolling(60).mean() /
    result.equity_curve.pct_change().rolling(60).std() *
    np.sqrt(252)
)
```

---

**文档版本：** v1.0
**最后更新：** 2026-02-06
