# 量化交易Skills 完整功能清单

## 模块总览

```
.claude/skills/
├── stock_data_fetcher.py       # 数据获取 (基础)
├── advanced_indicators.py      # 高级技术指标 (12种)
├── backtest_framework.py       # 回测框架
├── risk_management.py          # 风险管理
├── trend_indicators.py         # 趋势指标 (新增)
├── pattern_recognition.py      # 形态识别 (新增)
├── multi_factor_selection.py  # 多因子选股 (新增)
└── examples/
    ├── 选股示例.py
    ├── 技术分析与回测.py
    └── 自动更新数据.py
```

---

## 模块详细功能

### 1. 数据获取 (stock_data_fetcher.py)

| 功能 | 说明 |
|------|------|
| get_stock_list() | 获取A股列表 |
| get_quote_data() | 历史行情 (日/周/月) |
| get_financial_indicator() | 财务指标 |
| get_stock_money_flow() | 资金流向 |
| get_realtime_quote() | 实时行情 |
| batch_get_quotes() | 批量获取 |
| export_to_excel() | 导出综合分析 |

---

### 2. 高级技术指标 (advanced_indicators.py)

| 指标 | 参数 | 用途 |
|------|------|------|
| ATR | period=14 | 波动性 |
| KDJ | n=9, m1=3, m2=3 | 超买超卖 |
| CCI | period=20 | 价格偏离 |
| Williams %R | period=14 | 动量震荡 |
| OBV | - | 成交量能量 |
| AD | - | 累积/派发 |
| DPO | period=14 | 周期识别 |
| TRIX | period=14 | 趋势过滤 |
| VWAP | - | 成交量均价 |
| Keltner Channel | period=20, mult=2 | 波动通道 |
| Donchian Channel | period=20 | 突破通道 |
| MFI | period=14 | 资金流量 |

---

### 3. 趋势指标 (trend_indicators.py) - 新增

| 指标 | 说明 |
|------|------|
| EMA | 指数移动平均 |
| DEMA | 双指数移动平均 (减少滞后) |
| TEMA | 三重指数移动平均 (进一步减少滞后) |
| VWMA | 成交量加权移动平均 |
| HMA | Hull移动平均 (几乎零滞后) |
| KAMA | Kaufman自适应移动平均 |
| MG | McGinley动态指标 |
| VWAP | 成交量加权平均价 |
| Ichimoku | 一目均衡表 (转换线/基准线/先行带/滞后跨度) |
| Triple Screen | 三屏过滤系统 |
| ABands | Abohar Bands (基于ATR的通道) |

---

### 4. 形态识别 (pattern_recognition.py) - 新增

#### K线形态
- Doji (十字星)
- Hammer / Hanging Man (锤子线/上吊线)
- Bullish/Bearish Engulfing (看涨/看跌吞没)
- Bullish/Bearish Harami (看涨/看跌孕线)
- Morning Star (早晨之星)
- Evening Star (黄昏之星)
- Piercing (刺透)
- Dark Cloud Cover (乌云盖顶)

#### 价格形态
- Support Level Detection (支撑位识别)
- Resistance Level Detection (压力位识别)
- Trend Detection (趋势判断)
- Consolidation Detection (整理识别)
- Breakout Detection (突破识别)

---

### 5. 多因子选股 (multi_factor_selection.py) - 新增

#### 因子类型

| 因子类别 | 包含因子 |
|----------|----------|
| 价值因子 | PE, PB, PS, PCF, 股息率 |
| 成长因子 | 营收增长, 利润增长, ROE, 毛利率 |
| 质量因子 | ROE, ROA, 财务健康度, 盈利稳定性 |
| 动量因子 | 20日/60日/120日动量 |
| 波动率因子 | 历史波动率, 下行风险 |

#### Smart Beta策略

- 低波动策略 (Low Volatility)
- 高股息策略 (High Dividend)
- 质量因子策略 (Quality Factor)
- 动量策略 (Momentum)

---

### 6. 回测框架 (backtest_framework.py)

#### BacktestEngine
- 完整的回测引擎
- 支持自定义策略
- 自动计算手续费和滑点
- 生成交易记录和资金曲线

#### StrategyFactory (预定义策略)
- MA Cross (均线交叉)
- MACD Cross (MACD交叉)
- RSI Overbought/Oversold (RSI超买超卖)
- Bollinger Bands (布林带突破)
- Multi-Signal (多信号融合)

#### ParameterOptimizer
- 网格搜索 (Grid Search)
- 滚动窗口优化 (Walk Forward)

#### PerformanceReport
- 总收益率、超额收益
- 夏普/索提诺/卡玛比率
- 最大回撤、持续期
- 胜率、盈亏比

---

### 7. 风险管理 (risk_management.py)

#### RiskMetrics (风险指标)
- VaR/CVaR (在险价值)
- 最大回撤
- Sharpe/Sortino/Calmar比率
- Beta/Alpha
- Information Ratio

#### PositionSizing (仓位管理)
- 等权重
- 凯利公式
- 固定风险比例
- ATR仓位
- 波动率调整
- 风险平价

#### StopLossManager (止损止盈)
- 固定止损
- 移动止损
- 止盈

---

## 快速使用指南

### 数据获取 + 指标计算
```python
from stock_data_fetcher import StockDataFetcher
from advanced_indicators import AdvancedIndicators
from trend_indicators import TrendIndicators

fetcher = StockDataFetcher()
data = fetcher.get_quote_data("600519", "20230101", "20231231")

# 基础指标
data = AdvancedIndicators.calculate_all(data)

# 趋势指标
data = TrendIndicators.all_trend_indicators(data)
```

### 形态识别
```python
from pattern_recognition import CandlestickPatterns, PricePatterns

# K线形态
df_patterns = CandlestickPatterns.scan_all_patterns(data)

# 价格形态分析
analysis = PricePatterns.analyze_patterns(data)
print(f"支撑位: {analysis['support_levels']}")
print(f"压力位: {analysis['resistance_levels']}")
```

### 多因子选股
```python
from multi_factor_selection import MultiFactorSelector

selector = MultiFactorSelector(
    factor_weights={'value': 0.3, 'growth': 0.3, 'quality': 0.2, 'momentum': 0.2}
)
selected = selector.select_stocks(financial_df, price_df, top_n=20)
```

### 策略回测
```python
from backtest_framework import BacktestEngine, StrategyFactory

strategy = StrategyFactory.ma_cross(5, 20)
engine = BacktestEngine(initial_cash=100000, commission=0.0003)
results = engine.run(data, strategy)

print(f"总收益: {results['total_return']:.2f}%")
print(f"夏普: {results['sharpe_ratio']:.2f}")
```

### 参数优化
```python
from backtest_framework import ParameterOptimizer

optimizer = ParameterOptimizer()
best_params, best_result = optimizer.grid_search(
    data, StrategyFactory.ma_cross,
    param_grid={'fast': [5, 10, 15], 'slow': [20, 30, 40]},
    metric='sharpe_ratio'
)
```

### 风险控制
```python
from risk_management import RiskMetrics, PositionSizing, StopLossManager

# 风险指标
var = RiskMetrics.var(returns, confidence=0.95)
sharpe = RiskMetrics.sharpe_ratio(returns)

# 仓位管理
position = PositionSizing.kelly_criterion(win_rate=0.55, avg_win=5, avg_loss=3, capital=100000)

# 止损管理
sl_manager = StopLossManager()
sl_manager.add_position('600519', entry_price=100, quantity=1000, stop_loss_pct=0.05)
```

---

## 安装依赖

```bash
# 核心依赖
pip install akshare pandas numpy scipy

# 可选依赖
pip install scikit-learn xgboost
pip install backtrader
pip install matplotlib plotly seaborn
```

---

## 进阶功能规划

### 第二阶段
- [ ] 统计套利 (配对交易)
- [ ] 协整检验
- [ ] 均值回归策略

### 第三阶段
- [ ] 机器学习预测
- [ ] 特征工程
- [ ] 模型评估与选择

### 第四阶段
- [ ] LSTM时间序列预测
- [ ] Transformer模型
- [ ] 强化学习交易
- [ ] 实盘交易系统

---

*更新日期: 2026-02-03*
