# Skills模块使用指南

**版本：** v1.1
**更新日期：** 2026-02-04

---

## 目录

1. [快速开始](#一快速开始)
2. [模块概览](#二模块概览)
3. [基础用法](#三基础用法)
4. [进阶用法](#四进阶用法)
5. [完整流程](#五完整流程)
6. [常见问题](#六常见问题)

---

## 一、快速开始

### 1.1 最简单的使用方式

```python
# 导入统一工作流
from quant_workflow import QuantWorkflow

# 创建工作流实例
workflow = QuantWorkflow()

# 快速分析一只股票
result = workflow.quick_analyze('600519')
print(workflow.generate_report(result))
```

### 1.2 分析自己的持仓

```python
# 分析持仓（包含盈亏计算）
result = workflow.full_analyze(
    symbol='002415',
    shares=500,      # 持股数量
    cost_price=30.0  # 成本价
)
print(workflow.generate_report(result, 'full'))
```

---

## 二、模块概览

### 2.1 核心模块（12个）

| 模块文件 | 功能 | 优先级 | 状态 |
|----------|------|--------|------|
| quant_workflow.py | 统一工作流 | P0 | ✅ 新增 |
| stock_data_fetcher.py | 数据获取 | P0 | ✅ 完成 |
| stock_list_manager.py | 股票列表 | P0 | ✅ 完成 |
| signal_generator.py | 信号生成 | P1 | ✅ 完成 |
| technical_analyzer.py | 技术分析 | P1 | ✅ 完成 |
| position_analyzer.py | 持仓分析 | P1 | ✅ 完成 |
| stock_selector.py | 选股筛选 | P1 | ✅ 完成 |
| trend_indicators.py | 趋势指标 | P1 | ✅ 完成 |
| advanced_indicators.py | 高级指标 | P1 | ✅ 完成 |
| pattern_recognition.py | 形态识别 | P1 | ✅ 完成 |
| risk_management.py | 风险管理 | P1 | ✅ 完成 |
| backtest_framework.py | 回测框架 | P2 | 🔄 部分完成 |
| multi_factor_selection.py | 多因子选股 | P2 | 🔄 部分完成 |

### 2.2 模块依赖关系

```
quant_workflow.py (统一工作流)
    ├── stock_data_fetcher.py (数据获取)
    ├── stock_list_manager.py (股票列表)
    ├── signal_generator.py (信号生成)
    ├── technical_analyzer.py (技术分析)
    ├── position_analyzer.py (持仓分析)
    └── stock_selector.py (选股筛选)
```

---

## 三、基础用法

### 3.1 快速分析单只股票

```python
from quant_workflow import QuantWorkflow

workflow = QuantWorkflow()

# 快速分析（不需要持仓信息）
result = workflow.quick_analyze('600519')

# 查看结果
print(f"股票: {result['name']}")
print(f"价格: {result['price']:.2f} 元")
print(f"评分: {result['score']:.0f}/100")
print(f"趋势: {result['trend']}")
print(f"建议: {result['recommendation']['level']}")
```

**返回字段：**
- `symbol` - 股票代码
- `name` - 股票名称
- `price` - 当前价格
- `change_1d` - 日涨跌幅
- `score` - 技术评分 (0-100)
- `trend` - 趋势方向
- `risk_level` - 风险等级
- `buy_signal` - 是否有买入信号
- `sell_signal` - 是否有卖出信号
- `signal_strength` - 信号强度 (-10到+10)
- `recommendation` - 操作建议

### 3.2 完整分析（含持仓）

```python
# 分析持仓（包含盈亏、回本分析等）
result = workflow.full_analyze(
    symbol='002415',
    shares=500,      # 必填：持股数量
    cost_price=30.0  # 必填：成本价
)

# 包含快速分析的所有信息
# 额外包含：
# - position['shares'] - 持股数量
# - position['cost_price'] - 成本价
# - position['market_value'] - 持仓市值
# - position['profit_loss'] - 浮动盈亏
# - position['profit_loss_pct'] - 盈亏比例
# - position['recover_gain'] - 回本需要的涨幅
# - position['loss_level'] - 亏损等级
# - position['advice'] - 操作建议（含T+策略）
```

### 3.3 批量选股

```python
# 定义股票池
stock_pool = ['600519', '000858', '002415', '600036', '000001']

# 筛选股票（评分>=60分）
screened = workflow.screen_stocks(
    stock_list=stock_pool,
    min_score=60,    # 最低评分
    max_count=5      # 最多返回数量
)

# 查看结果
for stock in screened:
    print(f"{stock['symbol']} - 评分: {stock['score']}")
```

### 3.4 热门股票分析

```python
# 获取热门股票并分析
hot_stocks = workflow.hot_stocks_analysis(
    market='all',   # 市场范围：all/sh/sz
    count=10        # 返回数量
)

# 已包含技术分析
for stock in hot_stocks:
    print(f"{stock['symbol']} - {stock['name']} - {stock['score']}/100")
```

---

## 四、进阶用法

### 4.1 单独使用各个模块

#### 股票列表查询

```python
from stock_list_manager import get_stock_name, get_stock_code, search_stocks

# 代码查名称
name = get_stock_name('600519')  # 贵州茅台

# 名称查代码
code = get_stock_code('茅台')      # 600519

# 模糊搜索
results = search_stocks('银行')
```

#### 技术分析

```python
from technical_analyzer import TechnicalAnalyzer, generate_technical_report

analyzer = TechnicalAnalyzer()
result = analyzer.analyze('600519', days=120)
report = generate_technical_report(result)
print(report)
```

#### 持仓分析

```python
from position_analyzer import analyze_position, format_position_report

result = analyze_position(
    symbol='002415',
    shares=500,
    cost_price=30.0,
    stock_name='海康威视'
)
report = format_position_report(result)
print(report)
```

#### 信号生成

```python
from signal_generator import SignalGenerator

generator = SignalGenerator()
signal = generator.get_latest_signal(data)

# 查看信号
if signal['buy_signal']:
    print(f"买入信号！强度: {signal['strength']}")
```

### 4.2 组合分析

```python
# 定义持仓
positions = [
    {'symbol': '600519', 'shares': 100, 'cost': 1500},
    {'symbol': '000858', 'shares': 200, 'cost': 100},
    {'symbol': '002415', 'shares': 500, 'cost': 30}
]

# 分析组合
portfolio = workflow.portfolio_analysis(positions)

# 查看组合概况
print(f"组合市值: {portfolio['total_value']:,.2f} 元")
print(f"盈亏比例: {portfolio['total_profit_loss_pct']:+.2f}%")
```

---

## 五、完整流程

### 5.1 量化选股完整流程

```python
from quant_workflow import QuantWorkflow

workflow = QuantWorkflow()

# 步骤1：定义股票池
stock_pool = ['600519', '000858', '002415', '600036', '600893', '000568']

# 步骤2：批量筛选
screened = workflow.screen_stocks(stock_pool, min_score=60, max_count=5)

print(f"筛选出 {len(screened)} 只股票")

# 步骤3：详细分析
for stock in screened:
    result = workflow.quick_analyze(stock['symbol'])
    report = workflow.generate_report(result, 'quick')
    print(report)
    print()

# 步骤4：根据信号过滤
buy_signals = [s for s in screened if s['buy_signal']]
print(f"有买入信号的: {len(buy_signals)} 只")
```

### 5.2 持仓管理流程

```python
# 我的持仓
my_positions = [
    {'symbol': '002415', 'shares': 700, 'cost': 23.83},
    {'symbol': '600519', 'shares': 100, 'cost': 1500}
]

# 分析组合
portfolio = workflow.portfolio_analysis(my_positions)

# 查看各持仓详情
for pos in portfolio['positions']:
    symbol = pos['symbol']
    name = pos['name']

    if 'position' in pos:
        # 有持仓信息
        p = pos['position']
        print(f"{symbol} {name}")
        print(f"  盈亏: {p['profit_loss']:+,.2f} 元 ({p['profit_loss_pct']:+.2f}%)")
        print(f"  建议: {p['advice']['strategy']}")
    else:
        # 仅快速分析
        print(f"{symbol} {name}")
        print(f"  评分: {pos['score']}/100")
```

### 5.3 热点追踪流程

```python
# 获取热门股票
hot_stocks = workflow.hot_stocks_analysis(market='all', count=20)

# 过滤出有买入信号的
buy_candidates = [s for s in hot_stocks if s['buy_signal']]

# 按评分排序
buy_candidates.sort(key=lambda x: x['score'], reverse=True)

# 显示前5只
for i, stock in enumerate(buy_candidates[:5], 1):
    print(f"{i}. {stock['symbol']} {stock['name']}")
    print(f"   评分: {stock['score']}/100")
    print(f"   建议: {stock['recommendation']['action']}")
```

---

## 六、常见问题

### Q1: 如何获取股票数据？

```python
from stock_data_fetcher import StockDataFetcher

fetcher = StockDataFetcher()

# 获取行情数据
data = fetcher.get_quote_data('600519', days=120)

# 计算技术指标
data = fetcher.calculate_technical_indicators(data)
```

### Q2: 如何查询股票名称？

```python
from stock_list_manager import get_stock_name, get_stock_code, search_stocks

# 方式1：代码查名称
name = get_stock_name('600519')

# 方式2：名称查代码
code = get_stock_code('茅台')

# 方式3：模糊搜索
results = search_stocks('银行')
```

### Q3: 如何判断买卖信号？

```python
from signal_generator import SignalGenerator
from stock_data_fetcher import StockDataFetcher

# 获取数据
fetcher = StockDataFetcher()
data = fetcher.get_quote_data('600519', days=120)
data = fetcher.calculate_technical_indicators(data)

# 生成信号
generator = SignalGenerator()
signal = generator.get_latest_signal(data)

# 判断
if signal['buy_signal']:
    print("建议买入")
elif signal['sell_signal']:
    print("建议卖出")
else:
    print("观望")
```

### Q4: 如何分析持仓盈亏？

```python
from position_analyzer import analyze_position

result = analyze_position(
    symbol='002415',
    shares=500,
    cost_price=30.0
)

print(f"盈亏: {result['profit_loss']:+,.2f} 元")
print(f"回本需要: +{result['recover_gain']:.2f}%")
```

### Q5: 如何批量筛选股票？

```python
from stock_selector import StockSelector

selector = StockSelector()

# 方式1：按评分筛选
results = selector.screen_stocks(
    stock_list=['600519', '000858'],
    min_score=60,
    max_count=5
)

# 方式2：按条件筛选
results = selector.filter_by_criteria(
    stock_list=['600519', '000858'],
    criteria={'min_price': 100, 'trend': 'up'}
)

# 方式3：按表现排名
results = selector.rank_by_performance(
    stock_list=['600519', '000858'],
    period=20
)
```

---

## 七、最佳实践

### 7.1 数据更新

```python
# 每日更新数据（建议收盘后执行）
from stock_data_fetcher import StockDataFetcher

fetcher = StockDataFetcher()

# 更新热门股票
hot_stocks = ['600519', '000858', '002415', '600893', '000568']
for symbol in hot_stocks:
    data = fetcher.get_quote_data(symbol, days=120)
```

### 7.2 错误处理

```python
from quant_workflow import QuantWorkflow

workflow = QuantWorkflow()

try:
    result = workflow.quick_analyze('600519')
    if 'error' in result:
        print(f"分析失败: {result['error']}")
    else:
        print(workflow.generate_report(result))
except Exception as e:
    print(f"发生错误: {e}")
```

### 7.3 性能优化

```python
# 使用缓存，避免重复请求
# 数据会自动缓存到 stock_data/ 目录

# 批量分析时使用批量方法
workflow = QuantWorkflow()

# 推荐
results = workflow.batch_analysis(stock_list)

# 不推荐（每个都单独请求）
for symbol in stock_list:
    workflow.quick_analyze(symbol)  # 慢
```

---

## 八、示例代码

### 示例1：每日选股

```python
from quant_workflow import QuantWorkflow

workflow = QuantWorkflow()

# 我的股票池
my_pool = ['600519', '000858', '002415', '600893', '000568', '600036']

# 筛选
screened = workflow.screen_stocks(my_pool, min_score=60)

# 显示有买入信号的
for stock in screened:
    if stock['buy_signal']:
        result = workflow.quick_analyze(stock['symbol'])
        print(f"{result['name']} - {result['recommendation']['level']}")
```

### 示例2：持仓复盘

```python
# 我的持仓
positions = [
    {'symbol': '002415', 'shares': 700, 'cost': 23.83},
    {'symbol': '600519', 'shares': 100, 'cost': 1500}
]

workflow = QuantWorkflow()
portfolio = workflow.portfolio_analysis(positions)

# 查看整体盈亏
print(f"总市值: {portfolio['total_value']:,.2f}")
print(f"总盈亏: {portfolio['total_profit_loss']:+,.2f}")

# 查看各持仓建议
for pos in portfolio['positions']:
    if 'position' in pos:
        p = pos['position']
        print(f"\n{pos['symbol']} {pos['name']}")
        print(f"  建议: {p['advice']['strategy']}")
```

### 示例3：热点追踪

```python
workflow = QuantWorkflow()

# 获取热门股票
hot = workflow.hot_stocks_analysis(market='all', count=30)

# 筛选出强烈推荐的
recommended = [
    s for s in hot
    if s['score'] >= 70 and s['buy_signal']
]

print(f"找到 {len(recommended)} 只强烈推荐股票")
for stock in recommended[:5]:
    print(f"{stock['symbol']} {stock['name']} - {stock['score']}/100")
```

---

## 九、更新日志

### v1.2 (2026-02-10)
- ✅ 新增 `long_term_selector.py` 中长期选股策略
- ✅ 新增 `realtime_quote.py` 实时股价查询
- ✅ 支持CSV文件输入股票列表

### v1.1 (2026-02-04)
- ✅ 新增 `quant_workflow.py` 统一工作流
- ✅ 新增 `signal_generator.py` 信号生成器
- ✅ 整合所有模块，提供统一接口
- ✅ 完善文档和使用示例

### v1.0 (2026-02-03)
- ✅ 基础模块完成（10个）
- ✅ 数据获取、技术分析、持仓分析、选股筛选

---

## 十、高级功能

### 10.1 中长期选股策略 (long_term_selector.py)

基于多周期趋势分析的中长期选股工具，适合持有3-12个月的投资。

**命令行使用:**

```bash
# 分析指定股票列表文件
python .claude/skills/long_term_selector.py --file 候选股票.csv --top 20

# 分析持仓股票
python .claude/skills/long_term_selector.py --file 持仓.csv --top 10

# 使用默认股票池
python .claude/skills/long_term_selector.py --top 30 --limit 200
```

**参数说明:**

| 参数 | 简写 | 说明 | 默认值 |
|------|------|------|--------|
| --file | -f | 股票列表CSV文件 | 无 |
| --pool | | 股票池文件路径 | stock_list.csv |
| --top | | 显示Top N只股票 | 30 |
| --limit | | 分析股票数量限制 | 200 |

**CSV文件格式:**

```csv
股票代码,股票名称
002078,太阳纸业
002236,大华股份
600056,中国医药
```

或简化的:

```csv
code,name
002078,太阳纸业
002236,大华股份
```

**Python调用:**

```python
import sys
sys.path.append('.claude/skills')
from long_term_selector import LongTermSelector, load_stock_list_from_file

# 方式1: 从CSV文件加载
stock_pool = load_stock_list_from_file('候选股票.csv')
selector = LongTermSelector()
results = selector.select_stocks(stock_pool, top_k=20)

# 方式2: 直接定义股票池
stock_pool = {
    '002078': '太阳纸业',
    '002236': '大华股份',
    '600056': '中国医药'
}
results = selector.select_stocks(stock_pool, top_k=10)

# 查看结果
for r in results:
    print(f'{r.name}({r.code}): 得分{r.total_score:.1f} 3月涨幅{r.return_3m:+.2f}%')
```

**输出字段说明:**

| 字段 | 说明 |
|------|------|
| 1月% | 1个月收益率 |
| 3月% | 3个月收益率 |
| 6月% | 6个月收益率 |
| 1年% | 1年收益率 |
| 短/中/长 | 短期/中期/长期趋势 (^=UP, v=DOWN, -=SIDE) |
| 得分 | 综合评分 (0-100) |
| 建议 | STRONG_BUY/BUY/HOLD/AVOID |

---

### 10.2 实时股价查询 (realtime_quote.py)

使用腾讯财经API获取实时股价，稳定快速。

**命令行使用:**

```bash
# 查询持仓股票实时行情
python -c "
import sys; sys.path.append('.claude/skills')
from realtime_quote import monitor_portfolio
result = monitor_portfolio('持仓.csv')
print(f'总资产: {result[\"total_assets\"]:,.0f} 盈亏: {result[\"total_profit\"]:+,.0f}')
"
```

**Python调用:**

```python
import sys
sys.path.append('.claude/skills')
from realtime_quote import RealTimeQuoteAPI, get_quote, get_quotes, monitor_portfolio

# 方式1: 查询单只股票
quote = get_quote('002236')
print(f'{quote.name}: {quote.price:.2f} ({quote.change_pct:+.2f}%)')

# 方式2: 批量查询
quotes = get_quotes(['002078', '002236', '600056'])
for code, q in quotes.items():
    print(f'{q.name}: {q.price:.2f}')

# 方式3: 持仓监控
result = monitor_portfolio('持仓.csv')
print(f'总资产: {result["total_assets"]:,.0f}')
print(f'总盈亏: {result["total_profit"]:+,.0f}')

# 方式4: 使用API类
api = RealTimeQuoteAPI()
quotes = api.get_quotes(['002236', '600519'])
print(api.format_quote_table(quotes))
```

**返回字段 (RealTimeQuote):**

| 字段 | 类型 | 说明 |
|------|------|------|
| code | str | 股票代码 |
| name | str | 股票名称 |
| price | float | 当前价 |
| pre_close | float | 昨收价 |
| change | float | 涨跌额 |
| change_pct | float | 涨跌幅% |
| open | float | 开盘价 |
| high | float | 最高价 |
| low | float | 最低价 |
| volume | float | 成交量(手) |
| amount | float | 成交额(元) |

---

## 十一、联系与支持

- **GitHub:** [项目地址]
- **文档:** `.claude/skills/`
- **问题反馈:** 请提交Issue

---
*最后更新：2026-02-10*
