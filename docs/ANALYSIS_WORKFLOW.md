# 量化投资分析流程指南

## 流程概览

```
┌─────────────────────────────────────────────────────────────────────┐
│                        量化投资分析完整流程                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐            │
│  │ 阶段1   │ → │ 阶段2   │ → │ 阶段3   │ → │ 阶段4   │            │
│  │ 数据获取 │   │ 指标计算 │   │ 形态识别 │   │ 综合评分 │            │
│  └─────────┘   └─────────┘   └─────────┘   └─────────┘            │
│       ↓             ↓             ↓             ↓                  │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐                            │
│  │ 阶段5   │ → │ 阶段6   │ → │ 阶段7   │                            │
│  │ 风险评估 │   │ 回测验证 │   │ 仓位建议 │                            │
│  └─────────┘   └─────────┘   └─────────┘                            │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

## 各阶段详细说明

### 阶段1: 数据获取与清洗

**目标**: 获取高质量的历史行情数据

**输入**:
- 股票代码列表: `['600036', '000858', ...]`
- 或股票字典: `{'600036': '招商银行', '000858': '五粮液'}`

**处理步骤**:
1. 使用腾讯接口获取数据 (AKShare)
2. 标准化列名 (日期/开盘/收盘/最高/最低/成交量)
3. 数据清洗: 去重/去空值/排序
4. 数据验证: 检查数据完整性

**输出**:
```python
{
    '600036': {
        'name': '招商银行',
        'data': DataFrame  # 包含标准化的OHLCV数据
    }
}
```

**相关模块**: `stock_data_fetcher.py`

---

### 阶段2: 技术指标计算

**目标**: 计算各类技术分析指标

**指标分类**:

| 类别 | 指标 | 说明 |
|------|------|------|
| **趋势** | MA5/10/20/60 | 简单移动平均 |
| | EMA20/50 | 指数移动平均 |
| | HMA, KAMA | 优化移动平均 |
| **动量** | MACD | 指数平滑异同移动平均 |
| | RSI | 相对强弱指标 |
| **震荡** | KDJ | 随机指标 |
| | CCI | 顺势指标 |
| **波动** | Bollinger Bands | 布林带 |
| | ATR | 平均真实波幅 |
| **成交量** | OBV | 能量潮 |
| | MFI | 资金流量 |
| **支撑压力** | Ichimoku Cloud | 一目均衡表 |

**输出**: 原数据 + 30+ 技术指标列

**相关模块**:
- `advanced_indicators.py`
- `trend_indicators.py`

---

### 阶段3: 形态识别

**目标**: 识别K线形态和价格形态

**K线形态识别**:
- 单根: Doji, Hammer, Shooting Star, Hanging Man
- 双根: Engulfing (吞没), Harami (孕线)
- 三根: Morning Star, Evening Star, Three Soldiers

**价格形态识别**:
- 支撑/压力位
- 趋势突破
- 整理形态

**输出**:
```python
{
    'candlestick': DataFrame with pattern columns,
    'price': {
        'support': 35.50,
        'resistance': 42.80,
        'trend': 'uptrend'
    }
}
```

**相关模块**: `pattern_recognition.py`

---

### 阶段4: 综合评分

**目标**: 多维度量化评分，排序选股

**评分体系** (满分100分):

```
┌─────────────┬──────────┬────────────────────┐
│ 维度        │ 权重     │ 评分标准           │
├─────────────┼──────────┼────────────────────┤
│ 趋势得分    │ 25分     │ EMA排列/价格位置   │
│ 动量得分    │ 25分     │ MACD/涨跌幅        │
│ 超买超卖    │ 25分     │ RSI/KDJ位置        │
│ 成交量      │ 15分     │ 量能放大           │
│ 形态信号    │ 10分     │ K线形态            │
└─────────────┴──────────┴────────────────────┘
```

**得分解读**:
- **80+**: 强烈关注
- **60-79**: 关注
- **40-59**: 观望
- **<40**: 不建议

**输出**: 按得分排序的股票列表

---

### 阶段5: 风险评估

**目标**: 量化股票风险水平

**风险指标**:

| 指标 | 公式 | 说明 |
|------|------|------|
| 年化波动率 | std(returns) × √252 | 价格波动程度 |
| 最大回撤 | max((cummax-price)/cummax) | 历史最大亏损 |
| VaR(95%) | percentile(returns, 5%) | 95%置信日损失 |
| 夏普比率 | (return-rf)/volatility | 风险调整收益 |
| 索提诺比率 | (return-rf)/downside_vol | 下行风险调整 |

**风险等级**:
- **高**: 年化波动率 > 40%
- **中**: 年化波动率 25%-40%
- **低**: 年化波动率 < 25%

**相关模块**: `risk_management.py`

---

### 阶段6: 回测验证

**目标**: 验证策略历史表现

**回测流程**:
1. 定义交易信号 (如MA金叉)
2. 模拟历史交易
3. 计算绩效指标
4. 评估策略有效性

**绩效指标**:
- 总收益率
- 年化收益率
- 夏普比率
- 最大回撤
- 胜率
- 交易次数

**内置策略**:
- MA Cross (5/20, 10/30)
- MACD Cross
- RSI Overbought/Oversold
- Bollinger Bands
- Multi-Signal

**相关模块**: `backtest_framework.py`

---

### 阶段7: 仓位管理

**目标**: 确定合理的买入仓位

**仓位计算方法**:

1. **固定比例法** (推荐)
   ```
   仓位 = 本金 × 风险比例 / 止损幅度
   例如: 100000 × 0.02 / 0.08 = 25000元
   ```

2. **凯利公式**
   ```
   f = (胜率 × 平均盈利 - 平均亏损) / 平均盈利
   ```

3. **ATR波动法**
   ```
   股数 = 本金 × 风险比例 / ATR
   ```

**风控规则**:
- 单股最大仓位: 20%
- 板块总仓位: ≤50%
- 止损: -8% 至 -10%
- 止盈: +15% 至 +20%

**相关模块**: `risk_management.py` (PositionSizing)

---

## 快速开始

### 基本用法

```python
from quant_analysis_workflow import QuantAnalysisWorkflow

# 定义股票池
stocks = {
    '600036': '招商银行',
    '000858': '五粮液',
    '600519': '贵州茅台'
}

# 创建分析器
workflow = QuantAnalysisWorkflow(initial_capital=100000)

# 执行完整分析
results = workflow.run_full_analysis(stocks, days=252)

# 查看推荐
for rec in results['recommendations']:
    print(f"{rec['name']}: {rec['price']:.2f}, 得分: {rec['total_score']:.0f}")
```

### 单独使用各阶段

```python
workflow = QuantAnalysisWorkflow()

# 只执行数据获取
data = workflow.stage1_data_acquisition(['600036'])

# 只执行技术分析
data = workflow.stage2_technical_indicators(data)

# 只执行评分
scores = workflow.stage4_scoring(data, {})
```

---

## 输出报告结构

```python
results = {
    'data': {...},              # 原始数据 + 指标
    'patterns': {...},          # 形态识别结果
    'scores': [...],            # 评分排序列表
    'risk': [...],              # 风险评估报告
    'backtest': [...],          # 回测结果
    'recommendations': [...]    # 最终推荐
}
```

---

## Skills模块清单

| 模块 | 功能 | 主要类/函数 |
|------|------|-------------|
| stock_data_fetcher.py | 数据获取 | StockDataFetcher |
| advanced_indicators.py | 高级指标 | AdvancedIndicators |
| trend_indicators.py | 趋势指标 | TrendIndicators |
| pattern_recognition.py | 形态识别 | CandlestickPatterns, PricePatterns |
| risk_management.py | 风险管理 | RiskMetrics, PositionSizing, StopLossManager |
| backtest_framework.py | 回测引擎 | BacktestEngine, StrategyFactory |
| multi_factor_selection.py | 多因子选股 | MultiFactorSelector, SmartBetaStrategy |
| quant_analysis_workflow.py | **完整流程** | QuantAnalysisWorkflow |

---

## 注意事项

1. **数据源**: 腾讯接口比东方财富更稳定
2. **数据质量**: 建议至少200天历史数据
3. **计算时间**: 指标计算可能需要几秒到几分钟
4. **结果解读**: 技术分析仅供参考，不构成投资建议
5. **风险提示**: 历史表现不代表未来收益

---

## 更新日志

- 2026-02-03: 创建完整流程框架
- 使用腾讯接口解决数据获取问题
- 整合7个核心skills模块
