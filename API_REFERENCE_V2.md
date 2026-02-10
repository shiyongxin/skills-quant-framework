# Skills 模块 API 参考文档 v2.0

**版本：** v2.0
**更新日期：** 2026-02-06

---

## 新增模块 (Phase 3)

### 9. Web应用 (web_app.py)

基于Streamlit的交互式Web应用。

```python
# 启动应用
streamlit run .claude/skills/web_app.py

# 或使用启动脚本
python run_web_app.py
```

**页面：**
- 首页/仪表盘 - 市场概况、自选股、最新信号
- 数据分析 - K线图、技术指标、交易信号
- 策略回测 - 参数配置、回测结果、策略对比
- 组合管理 - 创建组合、持仓详情、绩效分析
- 实时监控 - 监控状态、告警管理

---

### 10. 缓存管理器 (cache_manager.py)

Redis缓存管理，提升数据访问速度。

```python
from cache_manager import CacheManager, get_cache_manager

# 初始化
cache = CacheManager(host='localhost', port=6379)

# 基础操作
cache.set(key, value, ttl=3600)
value = cache.get(key)
cache.delete(key)
cache.invalidate("pattern:*")

# 股票数据缓存
cache.cache_stock_data(symbol, df, ttl=86400)
data = cache.get_stock_data(symbol)

# 技术指标缓存
cache.cache_indicators(symbol, df, ttl=3600)
indicators = cache.get_indicators(symbol)

# 实时报价缓存
cache.cache_quote(symbol, quote, ttl=60)
quote = cache.get_quote(symbol)
```

**缓存策略：**
| 数据类型 | TTL | 说明 |
|----------|-----|------|
| 股票数据 | 24小时 | 历史行情 |
| 技术指标 | 1小时 | 计算后的指标 |
| 实时报价 | 1分钟 | 最新价格 |
| 信号数据 | 5分钟 | 交易信号 |
| 因子数据 | 2小时 | 多因子数据 |

---

### 11. 并发获取器 (concurrent_fetcher.py)

多线程并发数据获取，性能提升10倍。

```python
from concurrent_fetcher import ConcurrentDataFetcher, BatchFetcher

# 初始化
fetcher = ConcurrentDataFetcher(
    max_workers=10,
    use_cache=True
)

# 获取单只股票
data = fetcher.fetch_one('600519', days=120)

# 并发获取多只
results = fetcher.fetch_stocks_parallel(
    symbols=['600519', '000858', '002415'],
    days=120
)

# 带重试获取
results = fetcher.fetch_with_retry(
    symbols=symbols,
    max_retries=3
)

# 限速获取
results = fetcher.fetch_with_limit(
    symbols=symbols,
    rate_limit=100
)

# 获取并计算指标
results = fetcher.fetch_and_calculate(symbols, days=120)
```

**性能对比：**
| 股票数 | 串行耗时 | 并发耗时 | 提升 |
|--------|----------|----------|------|
| 10 | 30秒 | 5秒 | 6x |
| 50 | 150秒 | 20秒 | 7.5x |
| 100 | 300秒 | 30秒 | 10x |

---

### 12. 数据库管理器 (database_manager.py)

PostgreSQL数据库集成。

```python
from database_manager import DatabaseManager

# 初始化
db = DatabaseManager(
    host='localhost',
    port=5432,
    database='stocks_db',
    user='postgres',
    password='password'
)

# 创建表
db.create_tables()
# 表: stocks, stock_quotes, signals, backtest_results, portfolios

# 保存数据
db.save_stock_info('600519', '贵州茅台', market='SH')
db.batch_save_stock_quotes(data_df)

# 查询数据
data = db.query_stock_quotes('600519', start_date, end_date)
quote = db.get_latest_quote('600519')

# 组合操作
portfolio_id = db.create_portfolio('我的策略', 1000000)
db.save_position(portfolio_id, '600519', 100, 1800)
```

---

### 13. ML预测器 (ml_predictor.py)

机器学习股票预测。

```python
from ml_predictor import MLPredictor, RegressionPredictor

# 分类预测器（涨/跌）
predictor = MLPredictor(model_type="random_forest")

# 训练
evaluation = predictor.train(
    data,
    test_size=0.2,
    forward_days=5,    # 预测未来5天
    threshold=0.02     # 涨幅>2%为上涨
)

print(f"准确率: {evaluation.accuracy:.2%}")
print(f"特征重要性: {evaluation.feature_importance}")

# 预测
result = predictor.predict(data)
print(f"预测: {result.prediction}")
print(f"概率: {result.probability:.2%}")
print(f"置信度: {result.confidence:.2%}")

# 回归预测器（预测涨跌幅）
regressor = RegressionPredictor()
metrics = regressor.train(data, forward_days=5)
predicted_return = regressor.predict_return(data)
```

**特征工程（30+特征）：**
- 价格特征：price_change, momentum
- 波动率：volatility_5/10/20
- 技术指标：RSI, MACD, 布林带
- 成交量：volume_ratio
- 形态特征：锤子线、流星线、吞没

---

### 14. 策略优化器 (strategy_optimizer.py)

策略参数自动优化。

```python
from strategy_optimizer import (
    StrategyOptimizer,
    MAStrategy,
    MACDStrategy,
    RSIStrategy,
    OptimizationConfig
)

# 创建优化器
optimizer = StrategyOptimizer(
    strategy=MAStrategy(),
    config=OptimizationConfig(target_metric="sharpe_ratio")
)

# 网格搜索
result = optimizer.grid_search(
    data,
    param_grid={
        'short_period': [5, 10, 15, 20],
        'long_period': [20, 30, 40, 60]
    }
)

print(f"最佳参数: {result.parameters}")
print(f"最佳夏普比率: {result.score:.4f}")

# 随机搜索
result2 = optimizer.random_search(data, n_iter=50)

# 贝叶斯优化
result3 = optimizer.bayesian_optimize(
    data,
    param_bounds={
        'short_period': (5, 20),
        'long_period': (20, 60)
    }
)
```

**内置策略模板：**
- MA交叉 - 均线金叉死叉
- MACD - MACD指标交叉
- RSI - RSI超买超卖
- 多因子 - 综合信号

---

## 依赖安装

### 完整依赖

```bash
pip install streamlit
pip install redis
pip install sqlalchemy psycopg2-binary
pip install scikit-learn scipy
```

### 数据库服务

```bash
# Redis
redis-server

# PostgreSQL
pg_ctl start
# 或
sudo service postgresql start
```

---

**文档版本：** v2.0
**最后更新：** 2026-02-06
