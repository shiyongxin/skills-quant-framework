# Skills 用户手册 v2.0

**版本：** v2.0
**更新日期：** 2026-02-06

---

## 快速开始

### 安装

```bash
# 克隆项目
git clone <repository_url>
cd Stocks

# 安装依赖
pip install -r requirements.txt
pip install -r web_requirements.txt
```

### 启动Web应用

```bash
# 方法1：使用启动脚本
python run_web_app.py

# 方法2：直接使用Streamlit
streamlit run .claude/skills/web_app.py
```

访问: http://localhost:8501

---

## 功能指南

### 1. 数据获取

#### 基础使用

```python
from stock_data_fetcher import StockDataFetcher

fetcher = StockDataFetcher()

# 获取单只股票
data = fetcher.get_quote_data('600519', days=120)

# 获取多只股票（带缓存）
from concurrent_fetcher import ConcurrentDataFetcher

fetcher = ConcurrentDataFetcher(max_workers=10, use_cache=True)
results = fetcher.fetch_stocks_parallel(
    symbols=['600519', '000858', '002415'],
    days=120
)
```

#### 数据格式

```python
DataFrame({
    '日期': datetime,
    '开盘': float,
    '最高': float,
    '最低': float,
    '收盘': float,
    '成交量': int,
    '涨跌幅': float
})
```

---

### 2. 技术分析

#### 计算技术指标

```python
# 自动计算所有指标
data = fetcher.calculate_technical_indicators(data)

# 包含：
# - MA5, MA10, MA20, MA60 (移动平均线)
# - EMA20, EMA50 (指数移动平均)
# - MACD, MACD_Signal, MACD_Hist
# - RSI (相对强弱指标)
# - K, D, J (随机指标)
# - 布林带 (上轨、中轨、下轨)
# - ATR (真实波动幅度)
```

#### 查看技术指标

```python
print(data[['日期', '收盘', 'MA5', 'MA20', 'RSI', 'MACD']].tail())
```

---

### 3. 交易信号

#### 生成交易信号

```python
from signal_generator import SignalGenerator

generator = SignalGenerator()

# 生成所有信号
data_with_signals = generator.generate_signals(data)

# 查看最新信号
signal = generator.get_latest_signal(data)

print(f"买入信号: {signal['buy_signal']}")
print(f"卖出信号: {signal['sell_signal']}")
print(f"信号强度: {signal['strength']:+.1f}")
```

#### 信号类型

| 信号 | 说明 | 取值 |
|------|------|------|
| signal_ma_cross | 均线交叉 | -1~1 |
| signal_macd | MACD信号 | -1~1 |
| signal_kdj | KDJ信号 | -1~1 |
| signal_rsi | RSI信号 | -1~1 |
| signal_bb | 布林带信号 | -1~1 |
| signal_volume | 成交量信号 | -0.5~0.5 |
| signal_breakout | 突破信号 | -1~1 |
| signal_buy | 综合买入 | 0/1 |
| signal_sell | 综合卖出 | 0/1 |
| signal_strength | 信号强度 | -10~10 |

---

### 4. 策略回测

#### 基础回测

```python
from backtest_framework import BacktestEngine, PositionConfig

# 创建回测引擎
engine = BacktestEngine(
    initial_cash=1000000,
    position_config=PositionConfig(
        max_positions=5,
        position_size_pct=0.2
    )
)

# 运行回测
result = engine.run_backtest(data_with_signals, data_with_signals)

# 查看结果
print(f"总收益率: {result.total_return:.2%}")
print(f"年化收益率: {result.annual_return:.2%}")
print(f"夏普比率: {result.sharpe_ratio:.2f}")
print(f"最大回撤: {result.max_drawdown:.2%}")
```

#### 持仓配置

```python
from backtest_framework import PositionSizingMethod, StopLossMethod

config = PositionConfig(
    # 持仓方法
    sizing_method=PositionSizingMethod.EQUAL_WEIGHT,

    # 止损方法
    stop_loss_method=StopLossMethod.FIXED_PERCENTAGE,
    stop_loss_pct=0.05,      # 5%止损
    take_profit_pct=0.15,    # 15%止盈

    max_positions=10,           # 最多10只股票
    position_size_pct=0.1      # 单只10%仓位
)
```

---

### 5. 组合管理

#### 创建组合

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

# 再平衡
manager.rebalance(
    portfolio_id=portfolio_id,
    target_weights={
        '600519': 0.3,
        '000858': 0.3,
        '002415': 0.4
    }
)

# 查看绩效
performance = manager.get_performance(portfolio_id)
risk = manager.get_risk_metrics(portfolio_id)
```

---

### 6. 实时监控

#### 设置监控

```python
from real_time_monitor import (
    RealTimeMonitor,
    AlertCondition,
    AlertType,
    AlertPriority
)

monitor = RealTimeMonitor()

# 添加股票
monitor.add_stock('600519', '贵州茅台')

# 价格告警
alert = AlertCondition(
    alert_type=AlertType.PRICE_ABOVE,
    threshold=2000,
    priority=AlertPriority.HIGH
)
monitor.add_condition('600519', alert)

# 检查条件
alerts = monitor.check_conditions('600519')
for alert in alerts:
    print(alert.message)
```

#### 告警类型

| 类型 | 说明 | 配置 |
|------|------|------|
| PRICE_ABOVE | 价格突破上限 | threshold: 上限价格 |
| PRICE_BELOW | 价格跌破下限 | threshold: 下限价格 |
| CHANGE_UP | 涨幅超限 | threshold: 涨幅% |
| CHANGE_DOWN | 跌幅超限 | threshold: 跌幅% |
| BREAKOUT_HIGH | 突破N日高点 | period: 天数 |
| BREAKOUT_LOW | 跌破N日低点 | period: 天数 |
| SIGNAL_BUY | 买入信号 | - |
| SIGNAL_SELL | 卖出信号 | - |
| VOLUME_SURGE | 成交量放大 | threshold: 放大倍数 |

---

### 7. 数据可视化

#### 生成图表

```python
from chart_visualizer import ChartVisualizer

visualizer = ChartVisualizer(output_dir="charts")

# K线图
visualizer.plot_candlestick(
    data=data,
    symbol='600519',
    ma_periods=[5, 10, 20, 60]
)

# MACD图
visualizer.plot_macd(data, '600519')

# RSI图
visualizer.plot_rsi(data, '600519')

# 布林带图
visualizer.plot_bollinger_bands(data, '600519')

# 综合分析图
visualizer.plot_combined_analysis(data, '600519')
```

---

### 8. 机器学习预测

#### 训练模型

```python
from ml_predictor import MLPredictor

predictor = MLPredictor(model_type="random_forest")

# 训练
evaluation = predictor.train(
    data,
    test_size=0.2,
    forward_days=5,    # 预测未来5天
    threshold=0.02     # 涨幅>2%为上涨
)

print(f"模型准确率: {evaluation.accuracy:.2%}")
```

#### 使用预测

```python
# 预测
result = predictor.predict(data)

if result.prediction == "up":
    print(f"预测上涨，概率: {result.probability:.2%}")
else:
    print(f"预测下跌，概率: {1-result.probability:.2%}")
```

---

### 9. 策略优化

#### 参数优化

```python
from strategy_optimizer import StrategyOptimizer, MAStrategy

optimizer = StrategyOptimizer(
    strategy=MAStrategy()
)

# 网格搜索
result = optimizer.grid_search(
    data,
    param_grid={
        'short_period': [5, 10, 15],
        'long_period': [20, 30, 40]
    }
)

print(f"最佳参数: {result.parameters}")
print(f"最佳夏普比率: {result.score:.4f}")
```

---

## 常见场景

### 场景1：选股策略

```python
# 1. 获取股票池
from concurrent_fetcher import BatchFetcher

symbols = ['600519', '000858', '002415', '600036', '000001']
data_dict = BatchFetcher.fetch_watchlist(symbols)

# 2. 生成信号
from signal_generator import SignalGenerator

generator = SignalGenerator()
signals = {}
for symbol, data in data_dict.items():
    signal = generator.get_latest_signal(data)
    signals[symbol] = signal

# 3. 筛选
buy_stocks = [s for s, sig in signals.items() if sig['buy_signal']]
print(f"推荐买入: {buy_stocks}")
```

### 场景2：回测验证

```python
# 1. 定义策略
def ma_strategy(data):
    data['MA5'] = data['收盘'].rolling(5).mean()
    data['MA20'] = data['收盘'].rolling(20).mean()
    data['signal_buy'] = (data['MA5'] > data['MA20'])
    return data

# 2. 回测
data = ma_strategy(data.copy())
engine = BacktestEngine(initial_cash=1000000)
result = engine.run_backtest(data, data)

# 3. 评估
if result.sharpe_ratio > 1.5:
    print("策略表现优秀")
```

### 场景3：实时监控

```python
# 1. 设置监控
monitor = RealTimeMonitor()
monitor.add_stock('600519', '贵州茅台')

alert = AlertCondition(
    alert_type=AlertType.SIGNAL_BUY,
    priority=AlertPriority.MEDIUM
)
monitor.add_condition('600519', alert)

# 2. 注册回调
def send_notification(alert):
    print(f"告警: {alert.message}")
    # 发送邮件/微信等

monitor.register_callback(send_notification)

# 3. 定期检查
while True:
    alerts = monitor.check_conditions('600519')
    if alerts:
        for alert in alerts:
            send_notification(alert)
    time.sleep(3600)  # 每小时检查
```

---

## 最佳实践

### 1. 数据缓存

```python
# 启用缓存提升性能
from concurrent_fetcher import ConcurrentDataFetcher

fetcher = ConcurrentDataFetcher(use_cache=True)
```

### 2. 错误处理

```python
try:
    data = fetcher.get_quote_data(symbol, days=120)
except Exception as e:
    print(f"获取数据失败: {e}")
    # 使用备用方案
    data = fetcher.get_quote_data_fallback(symbol, ...)
```

### 3. 批量操作

```python
# 批量获取
symbols = ['600519', '000858', '002415']
from concurrent_fetcher import BatchFetcher

results = BatchFetcher.fetch_watchlist(symbols)

# 批量回测
for symbol, data in results.items():
    result = engine.run_backtest(data, data)
```

---

**文档版本：** v2.0
**最后更新：** 2026-02-06
