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
- 实时监控 - watchlist 实时行情（realtime_quote 腾讯接口）、涨跌幅告警阈值

---

### 10. ML预测器 (ml_predictor.py)

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

### 11. 策略优化器 (strategy_optimizer.py)

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

```bash
pip install streamlit
pip install scikit-learn scipy
```

注：`cache_manager`/`concurrent_fetcher`/`database_manager`/`web_backtest` 已随孤岛清理删除（项 15），Redis/PostgreSQL 依赖不再需要。

---

**文档版本：** v2.0
**最后更新：** 2026-10-22
