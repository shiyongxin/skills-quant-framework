# Skills 量化交易框架 - 模块索引

**版本：** v2.0
**更新日期：** 2026-02-09

---

## 模块概览

Skills框架包含14个功能模块，覆盖量化交易全流程：

```
数据层 → 分析层 → 交易层 → 展示层
```

---

## 模块列表

### 一、核心模块 (v1.0)

| # | 模块 | 文件 | 代码行数 | 主要功能 |
|---|------|------|----------|----------|
| 1 | 数据获取 | stock_data_fetcher.py | 800 | 历史行情、实时数据、财务指标 |
| 2 | 信号生成 | signal_generator.py | 750 | 7种信号类型、综合评分 |
| 3 | 技术分析 | technical_analyzer.py | 600 | 30+技术指标、形态识别 |
| 4 | 回测框架 | backtest_framework.py | 900 | 完整回测引擎、多策略对比 |
| 5 | 多因子选股 | multi_factor_selection.py | 750 | 5大类因子、有效性检验 |
| 6 | 组合管理 | portfolio_manager.py | 700 | 组合管理（无资金限制） |
| 7 | 实时监控 | real_time_monitor.py | 500 | 8种告警类型、自定义回调 |
| 8 | 数据可视化 | chart_visualizer.py | 900 | 8种图表类型、自定义样式 |

**Phase 1-2 总计：** 8个模块，5,900行代码

### 二、高级模块 (v2.0)

| # | 模块 | 文件 | 代码行数 | 主要功能 |
|---|------|------|----------|----------|
| 9 | Web应用 | web_app.py | 1500 | Streamlit交互式平台 |
| 10 | 缓存管理 | cache_manager.py | 700 | Redis高性能缓存 |
| 11 | 并发获取 | concurrent_fetcher.py | 450 | 多线程数据获取 |
| 12 | 数据库管理 | database_manager.py | 700 | PostgreSQL持久化 |
| 13 | ML预测器 | ml_predictor.py | 600 | 机器学习预测 |
| 14 | 策略优化器 | strategy_optimizer.py | 550 | 参数自动优化 |

**Phase 3 总计：** 6个模块，4,500行代码

---

## 模块详解

### 1. 数据获取模块

**文件：** `stock_data_fetcher.py`

**主要功能：**
- 历史行情数据（日线、周线、月线）
- 实时行情数据
- 财务指标数据
- 技术指标计算
- 数据缓存管理

**核心类：**
```python
class StockDataFetcher:
    def get_quote_data(symbol, days)      # 获取历史行情
    def get_realtime_data(symbols)        # 获取实时数据
    def get_financial_data(symbol)        # 获取财务数据
    def calculate_technical_indicators(data)  # 计算技术指标
```

**使用示例：**
```python
from stock_data_fetcher import StockDataFetcher

fetcher = StockDataFetcher()
data = fetcher.get_quote_data('600519', days=252)
data = fetcher.calculate_technical_indicators(data)
```

---

### 2. 信号生成模块

**文件：** `signal_generator.py`

**主要功能：**
- 7种信号类型（MA、MACD、RSI、布林带、KDJ、成交量、综合）
- 信号强度评分
- 历史成功率统计
- 多指标综合分析

**核心类：**
```python
class SignalGenerator:
    def generate_signals(data)             # 生成所有信号
    def get_latest_signal(data)            # 获取最新信号
    def format_signal_report(signal_info)  # 格式化信号报告
```

**使用示例：**
```python
from signal_generator import SignalGenerator

generator = SignalGenerator()
data = generator.generate_signals(data)
latest_signal = generator.get_latest_signal(data)
```

---

### 3. 技术分析模块

**文件：** `technical_analyzer.py`

**主要功能：**
- 30+技术指标计算
- K线形态识别
- 趋势分析
- 支撑阻力位计算

**核心类：**
```python
class TechnicalAnalyzer:
    def calculate_all_indicators(data)     # 计算所有指标
    def detect_patterns(data)              # 识别K线形态
    def find_support_resistance(data)      # 计算支撑阻力
```

---

### 4. 回测框架模块

**文件：** `backtest_framework.py`

**主要功能：**
- 完整的回测引擎
- 多策略对比
- 参数优化
- 绩效分析

**核心类：**
```python
class BacktestEngine:
    def __init__(initial_cash, commission) # 初始化引擎
    def run(data, strategy)                # 运行回测

class StrategyFactory:
    def ma_cross(fast, slow)               # 均线交叉策略
    def macd_cross(fast, slow, signal)     # MACD策略
    def rsi_overbought_oversold(...)       # RSI策略
```

**使用示例：**
```python
from backtest_framework import BacktestEngine, StrategyFactory

engine = BacktestEngine(initial_cash=100000)
strategy = StrategyFactory.ma_cross(fast=5, slow=20)
result = engine.run(data, strategy)
```

---

### 5. 多因子选股模块

**文件：** `multi_factor_selection.py`

**主要功能：**
- 5大类因子（价值、成长、质量、动量、技术）
- 20+细分因子
- 因子有效性检验
- 因子中性化处理

**核心类：**
```python
class MultiFactorSelector:
    def select_stocks(universe, factors, top_n)  # 多因子选股
    def test_factor_effectiveness(factor_data)    # 因子有效性检验
    def neutralize_factors(factor_data)           # 因子中性化
```

---

### 6. 组合管理模块

**文件：** `portfolio_manager.py`

**主要功能：**
- 组合创建与管理
- 持仓跟踪与分析
- 组合再平衡
- 绩效归因分析
- **无资金限制**（v2.0新增）

**核心类：**
```python
class PortfolioManager:
    def create_portfolio(name, initial_cash)  # 创建组合
    def add_position(portfolio_name, symbol, shares, price)  # 添加持仓
    def get_performance(portfolio_name)       # 获取绩效
    def get_risk_metrics(portfolio_name)      # 获取风险指标
    def rebalance(portfolio_name, method)     # 组合再平衡
```

**v2.0改进：**
- ✅ 移除资金限制
- ✅ 支持记录型组合

---

### 7. 实时监控模块

**文件：** `real_time_monitor.py`

**主要功能：**
- 8种告警类型
- 自定义告警条件
- 多种通知方式
- 监控历史记录

**核心类：**
```python
class RealTimeMonitor:
    def add_monitor(symbol, condition, callback)  # 添加监控
    def remove_monitor(symbol)                     # 移除监控
    def check_monitors(data)                       # 检查所有监控
```

---

### 8. 数据可视化模块

**文件：** `chart_visualizer.py`

**主要功能：**
- 8种图表类型
- 自定义样式
- 图表叠加显示
- 批量生成图表

**核心类：**
```python
class ChartVisualizer:
    def plot_candlestick(data, style)    # K线图
    def plot_macd(data)                  # MACD图
    def plot_kdj(data)                   # KDJ图
    def plot_equity_curve(equity_data)   # 净值曲线
```

---

### 9. Web应用模块

**文件：** `web_app.py` (v2.0新增)

**主要功能：**
- Streamlit交互式平台
- 5个功能页面
- 实时数据展示
- 交互式操作

**页面列表：**
1. 仪表盘 - 市场概况、自选股、最新信号
2. 数据分析 - 技术指标、K线图表、多股对比
3. 策略回测 - 参数配置、回测结果、策略对比
4. 组合管理 - 组合列表、持仓详情、绩效分析
5. 实时监控 - 监控状态、告警列表、监控配置

**启动方式：**
```bash
python run_web_app.py
# 访问 http://localhost:8501
```

---

### 10. 缓存管理模块

**文件：** `cache_manager.py` (v2.0新增)

**主要功能：**
- Redis高性能缓存
- 7种缓存策略
- 自动TTL管理
- 缓存统计

**核心类：**
```python
class CacheManager:
    def cache_stock_data(symbol, data, ttl)  # 缓存股票数据
    def get_stock_data(symbol)               # 获取缓存数据
    def clear_cache(pattern)                 # 清除缓存
    def get_stats()                          # 获取缓存统计
```

**缓存策略：**
- 股票数据：24小时
- 技术指标：1小时
- 实时报价：1分钟
- 查询结果：30分钟

---

### 11. 并发获取模块

**文件：** `concurrent_fetcher.py` (v2.0新增)

**主要功能：**
- 多线程数据获取
- 速率限制
- 自动重试
- 性能优化（10倍提升）

**核心类：**
```python
class ConcurrentDataFetcher:
    def fetch_stocks_parallel(symbols, days)  # 并发获取
    def fetch_with_limit(symbols, rate_limit)  # 速率限制
    def fetch_with_retry(symbols, max_retries)  # 自动重试
```

**性能对比：**
- 优化前：100只股票 → 5分钟
- 优化后：100只股票 → 30秒

---

### 12. 数据库管理模块

**文件：** `database_manager.py` (v2.0新增)

**主要功能：**
- PostgreSQL持久化
- 6张数据表
- 连接池管理
- 批量操作

**核心类：**
```python
class DatabaseManager:
    def save_stock_data(data)               # 保存股票数据
    def load_stock_data(symbol, start, end) # 加载股票数据
    def save_backtest_result(result)        # 保存回测结果
    def query_portfolio_stats(...)           # 查询组合统计
```

**数据表：**
1. stocks - 股票基础信息
2. stock_quotes - 历史行情数据
3. signals - 交易信号
4. backtest_results - 回测结果
5. portfolios - 投资组合
6. positions - 持仓记录

---

### 13. ML预测器模块

**文件：** `ml_predictor.py` (v2.0新增)

**主要功能：**
- 机器学习预测
- 30+特征工程
- 3种预测模型
- 模型评估

**核心类：**
```python
class MLPredictor:
    def train(data, model_type)              # 训练模型
    def predict(data)                        # 预测涨跌
    def get_feature_importance()             # 特征重要性
```

**预测模型：**
- 随机森林分类
- 逻辑回归分类
- 梯度提升分类

---

### 14. 策略优化器模块

**文件：** `strategy_optimizer.py` (v2.0新增)

**主要功能：**
- 参数自动优化
- 3种优化算法
- 4种策略模板
- 优化结果分析

**核心类：**
```python
class StrategyOptimizer:
    def grid_search(data, param_grid)        # 网格搜索
    def random_search(data, param_grid)      # 随机搜索
    def bayesian_optimization(data, bounds)  # 贝叶斯优化
```

**策略模板：**
1. MA交叉策略
2. MACD策略
3. RSI策略
4. 多因子策略

---

## 依赖关系

```
web_app.py
  ├── stock_data_fetcher.py
  ├── signal_generator.py
  ├── backtest_framework.py
  ├── portfolio_manager.py
  ├── chart_visualizer.py
  └── real_time_monitor.py

concurrent_fetcher.py
  ├── stock_data_fetcher.py
  └── cache_manager.py

ml_predictor.py
  ├── stock_data_fetcher.py
  └── scikit-learn (可选)

strategy_optimizer.py
  ├── backtest_framework.py
  └── scipy (可选)
```

---

## 性能指标

| 指标 | 数值 |
|------|------|
| 总代码行数 | ~9,200行 |
| 核心模块数 | 14个 |
| 测试用例数 | 87+ |
| 文档数量 | 12个 |
| 数据获取性能 | 10倍提升 |

---

## 快速开始

### 安装依赖

```bash
# 基础依赖
pip install pandas numpy akshare matplotlib

# 可选依赖
pip install streamlit redis psycopg2-binary scikit-learn scipy
```

### 基础使用

```python
from stock_data_fetcher import StockDataFetcher
from signal_generator import SignalGenerator
from backtest_framework import BacktestEngine

# 获取数据
fetcher = StockDataFetcher()
data = fetcher.get_quote_data('600519', days=252)

# 生成信号
generator = SignalGenerator()
data = generator.generate_signals(data)

# 回测
engine = BacktestEngine(initial_cash=100000)
result = engine.run(data, strategy)
```

### Web应用

```bash
python run_web_app.py
# 访问 http://localhost:8501
```

---

## 文档链接

| 文档 | 说明 |
|------|------|
| [SKILLS_DEVELOPMENT_SUMMARY.md](../SKILLS_DEVELOPMENT_SUMMARY.md) | 开发总结 |
| [API_REFERENCE_V2.md](../API_REFERENCE_V2.md) | API参考 |
| [USER_MANUAL_V2.md](../USER_MANUAL_V2.md) | 用户手册 |
| [DEPLOYMENT_GUIDE.md](../DEPLOYMENT_GUIDE.md) | 部署指南 |
| [CHANGELOG.md](../CHANGELOG.md) | 更新日志 |

---

**版本：** v2.0
**最后更新：** 2026-02-09

---

*Skills - 让量化交易更简单*
