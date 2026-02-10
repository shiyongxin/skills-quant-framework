# 组合管理模块完成报告

**完成日期：** 2026-02-05
**版本：** v1.0
**模块：** portfolio_manager.py

---

## 一、模块概览

### 1.1 核心功能

| 功能 | 描述 | 状态 |
|------|------|------|
| **组合创建** | 创建新投资组合 | ✅ 完成 |
| **持仓管理** | 添加/移除/更新持仓 | ✅ 完成 |
| **价格更新** | 批量更新持仓价格 | ✅ 完成 |
| **组合再平衡** | 等权重/目标权重再平衡 | ✅ 完成 |
| **绩效分析** | 收益、盈亏计算 | ✅ 完成 |
| **风险指标** | 集中度、HHI等 | ✅ 完成 |
| **报告生成** | 标准报告/详细报告/风险报告 | ✅ 完成 |
| **保存加载** | JSON格式保存加载 | ✅ 完成 |

---

## 二、API参考

### 2.1 PortfolioManager类

```python
class PortfolioManager:
    """组合管理器"""

    def create_portfolio(name, initial_cash=100000) -> Portfolio
        # 创建新组合

    def get_portfolio(name) -> Portfolio
        # 获取组合

    def delete_portfolio(name) -> bool
        # 删除组合

    def list_portfolios() -> List[str]
        # 列出所有组合

    def add_position(portfolio_name, symbol, name, shares, price) -> bool
        # 添加或更新持仓

    def remove_position(portfolio_name, symbol, shares=None, price) -> bool
        # 移除持仓

    def update_prices(portfolio_name, price_dict) -> bool
        # 更新持仓价格

    def rebalance(portfolio_name, target_weights, method, price_dict) -> Dict
        # 组合再平衡

    def get_performance(portfolio_name) -> Dict
        # 获取组合绩效

    def get_risk_metrics(portfolio_name, returns_df) -> Dict
        # 获取风险指标

    def generate_report(portfolio_name, report_type) -> str
        # 生成报告

    def save_portfolio(portfolio_name, filepath) -> bool
        # 保存组合

    def load_portfolio(filepath, portfolio_name) -> Portfolio
        # 加载组合
```

### 2.2 Portfolio类

```python
@dataclass
class Portfolio:
    """投资组合"""
    name: str
    initial_cash: float = 100000.0
    cash: float
    positions: Dict[str, Position]
    created_date: datetime
    last_updated: datetime

    @property
    def total_value(self) -> float
        # 总资产

    @property
    def total_cost(self) -> float
        # 总成本

    @property
    def total_profit_loss(self) -> float
        # 总盈亏

    @property
    def total_profit_loss_pct(self) -> float
        # 总盈亏比例
```

### 2.3 Position类

```python
@dataclass
class Position:
    """持仓信息"""
    symbol: str
    name: str
    shares: int
    cost_price: float
    current_price: float
    market_value: float
    profit_loss: float
    profit_loss_pct: float
    weight: float
    entry_date: datetime
```

---

## 三、使用示例

### 3.1 创建和管理组合

```python
from portfolio_manager import PortfolioManager

# 创建管理器
manager = PortfolioManager()

# 创建组合
portfolio = manager.create_portfolio("my_portfolio", initial_cash=100000)

# 添加持仓
manager.add_position("my_portfolio", "600519", "贵州茅台", 100, 100)
manager.add_position("my_portfolio", "000858", "五粮液", 200, 50)
manager.add_position("my_portfolio", "002415", "海康威视", 500, 30)

# 更新价格
price_dict = {
    '600519': 110,
    '000858': 55,
    '002415': 28
}
manager.update_prices("my_portfolio", price_dict)
```

### 3.2 获取绩效分析

```python
# 获取绩效
performance = manager.get_performance("my_portfolio")

print(f"Total Return: {performance['total_return']:.2f}%")
print(f"Profit/Loss: {performance['total_profit_loss']:+,.2f}")

# 查看持仓明细
for pos in performance['positions']:
    print(f"{pos['symbol']}: {pos['shares']} shares, P/L: {pos['profit_loss_pct']:+.2f}%")
```

### 3.3 组合再平衡

```python
# 定义目标权重（等权重）
target_weights = {
    '600519': 0.30,
    '000858': 0.30,
    '002415': 0.30
}

# 计算再平衡建议
adjustments = manager.rebalance("my_portfolio", target_weights)

for symbol, shares in adjustments.items():
    action = "Buy" if shares > 0 else "Sell"
    print(f"{symbol}: {action} {abs(shares)} shares")
```

### 3.4 生成报告

```python
# 标准报告
report = manager.generate_report("my_portfolio", 'standard')
print(report)

# 风险报告
risk_report = manager.generate_report("my_portfolio", 'risk')
print(risk_report)
```

---

## 四、测试结果

### 4.1 测试覆盖

| 测试项 | 结果 |
|--------|------|
| 创建组合 | ✅ PASS |
| 添加持仓 | ✅ PASS |
| 更新价格 | ✅ PASS |
| 组合再平衡 | ✅ PASS |
| 绩效分析 | ✅ PASS |
| 风险指标 | ✅ PASS |
| 移除持仓 | ✅ PASS |
| 保存加载 | ✅ PASS |
| 报告生成 | ✅ PASS |

### 4.2 测试输出示例

```
Portfolio Performance:
  Total Value:     101,000.00
  Total Return:    +1.00%
  Profit/Loss:     +1,000.00
  Cash:            65,000.00

Risk Metrics:
  Position Count:       3
  Max Position:         10.00%
  Top10 Concentration:  30.00%
  HHI:                  300
  Cash Ratio:           70.00%
```

---

## 五、风险指标说明

| 指标 | 说明 | 计算方法 |
|------|------|----------|
| **Position Count** | 持仓数量 | 组合中股票数量 |
| **Max Position** | 最大单一持仓 | 最大的单个持仓占比 |
| **Top10 Concentration** | 前十大持仓占比 | 前10大持仓总权重 |
| **HHI** | 赫芬达尔指数 | Σ(权重²) × 10000 |
| **Cash Ratio** | 现金占比 | 现金 / 总资产 |

### 风险评估

| 情况 | 提示 |
|------|------|
| 最大持仓 > 20% | 单一持仓风险较高 |
| 前十大占比 > 80% | 组合集中度较高 |
| HHI > 1000 | 组合集中度较高 |
| 现金比例 < 5% | 现金储备不足 |

---

## 六、报告类型

### 6.1 标准报告

包含组合概况和持仓明细：
- 总资产、总盈亏
- 持仓列表（按市值排序）
- 每个持仓的详细信息

### 6.2 详细报告

包含更完整的信息：
- 初始资金、当前市值
- 总收益率
- 风险指标
- 完整持仓明细

### 6.3 风险报告

专注于风险分析：
- 集中度指标
- 风险提示
- 改进建议

---

## 七、文件结构

```
portfolio_manager.py
├── Position (dataclass)
│   └── 持仓信息
├── Portfolio (dataclass)
│   ├── total_value (property)
│   ├── total_cost (property)
│   ├── total_profit_loss (property)
│   └── total_profit_loss_pct (property)
├── RebalanceMethod (enum)
│   ├── EQUAL_WEIGHT
│   ├── TARGET_WEIGHTS
│   ├── MIN_VARIANCE
│   └── RISK_PARITY
└── PortfolioManager (class)
    ├── 组合管理方法
    ├── 持仓操作方法
    ├── 分析方法
    └── 报告生成方法
```

---

## 八、下一步计划

### 8.1 增强功能

- [ ] 支持多币种组合
- [ ] 支持衍生品持仓
- [ ] 添加更多风险指标（Beta、Alpha等）
- [ ] 支持组合对比

### 8.2 集成功能

- [ ] 与回测框架集成
- [ ] 与信号生成器集成
- [ ] 自动再平衡功能

---

## 九、文件清单

| 文件 | 说明 |
|------|------|
| `.claude/skills/portfolio_manager.py` | 组合管理模块 |
| `test_portfolio_manager.py` | 测试脚本 |
| `PORTFOLIO_MANAGER_REPORT.md` | 本报告 |

---

*报告生成时间：2026-02-05*
*组合管理模块版本：v1.0*
