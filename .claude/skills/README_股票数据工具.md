# 📈 股票数据获取工具 - 使用指南

基于 **AKShare** 的中国股市数据获取工具，专用于**投资分析**和**量化交易**。

## 📦 安装依赖

```bash
pip install akshare pandas numpy openpyxl
```

## 🚀 快速开始

### 1️⃣ 导入工具

```python
from skills.stock_data_fetcher import StockDataFetcher, quick_fetch, batch_fetch

# 创建数据获取器
fetcher = StockDataFetcher(data_dir="./stock_data")
```

### 2️⃣ 获取股票列表

```python
# 获取所有A股列表
stock_list = fetcher.get_stock_list()
print(stock_list.head())

# 输出示例:
#     code  name
# 0  000001  平安银行
# 1  000002  万科A
# 2  000004  国华网安
```

### 3️⃣ 获取历史行情

```python
# 获取平安银行2023年行情
data = fetcher.get_quote_data(
    symbol="000001",           # 股票代码
    start_date="20230101",     # 开始日期
    end_date="20231231",       # 结束日期
    period="daily",            # daily/weekly/monthly
    adjust="qfq"               # 前复权
)

# 查看数据
print(data.head())
print(data.columns)

# 数据列包括:
# - 日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额
# - 振幅, 涨跌幅, 涨跌额, 换手率
```

### 4️⃣ 获取财务指标

```python
# 获取年度财务指标
financial = fetcher.get_financial_indicator(
    symbol="000001",
    indicator="按年度"  # 或 "按季度"
)

# 包括指标:
# - ROE(净资产收益率)
# - 毛利率, 净利率
# - 资产负债率
# - 流动比率, 速动比率
# - 每股收益(EPS)
# - 等等...
```

### 5️⃣ 导出综合分析报告

```python
# 一键导出Excel（包含行情、财务、资金流向）
fetcher.export_to_excel(
    symbol="000001",
    start_date="20230101",
    end_date="20231231"
)

# 生成文件: stock_data/000001_综合分析_20230101_20231231.xlsx
# 包含多个sheet: 行情数据、财务指标、资金流向
```

---

## 📊 完整使用示例

### 场景1: 选股分析

```python
# 假设你要分析沪深300成分股
fetcher = StockDataFetcher()

# 获取股票列表
stock_list = fetcher.get_stock_list()

# 选择前10只作为示例
target_stocks = stock_list['code'].head(10).tolist()

# 批量获取数据
batch_data = fetcher.batch_get_quotes(
    symbols=target_stocks,
    start_date="20230101",
    end_date="20231231",
    delay=1  # 请求间隔1秒
)

# 分析每只股票的涨跌幅
for code, data in batch_data.items():
    if not data.empty:
        data = fetcher.calculate_technical_indicators(data)
        total_return = (data['收盘'].iloc[-1] / data['收盘'].iloc[0] - 1) * 100
        print(f"{code}: 总收益率 {total_return:.2f}%")
```

### 场景2: 基本面分析

```python
# 获取一只股票的基本面数据
fundamental = fetcher.get_stock_fundamental("000001")

# 查看财务指标
financial = fundamental['financial_indicator']
if not financial.empty:
    print(financial[['日期', '净资产收益率', '毛利率', '净利率']])
```

### 场景3: 技术指标计算

```python
# 获取行情数据
data = fetcher.get_quote_data("000001", "20230101", "20231231")

# 计算技术指标
data = fetcher.calculate_technical_indicators(data)

# 查看均线
print(data[['日期', '收盘', 'MA5', 'MA10', 'MA20', 'MA60']].tail())

# 判断金叉死叉
latest = data.iloc[-1]
if latest['MA5'] > latest['MA10']:
    print("⚠️ 短期均线上穿，可能上涨")
else:
    print("⚠️ 短期均线下穿，可能下跌")
```

---

## 🎯 常用功能速查

| 功能 | 函数 | 说明 |
|-----|------|------|
| 股票列表 | `get_stock_list()` | 获取A股列表 |
| 历史行情 | `get_quote_data()` | 获取OHLCV数据 |
| 财务指标 | `get_financial_indicator()` | ROE、毛利率等 |
| 资金流向 | `get_stock_money_flow()` | 个股资金流向 |
| 实时行情 | `get_realtime_quote()` | 实时价格 |
| 批量获取 | `batch_get_quotes()` | 多只股票 |
| 技术指标 | `calculate_technical_indicators()` | MA、MACD等 |
| 导出Excel | `export_to_excel()` | 综合分析报告 |

---

## 💡 实用技巧

### 技巧1: 自动更新数据

```python
# 定期更新股票数据（例如每周）
import schedule
import time

def update_data():
    fetcher = StockDataFetcher()
    today = datetime.now().strftime("%Y%m%d")
    last_week = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")

    # 更新自选股
    my_stocks = ["000001", "600519", "000858"]
    fetcher.batch_get_quotes(my_stocks, last_week, today)
    print("✅ 数据已更新")

# 每周日晚上8点更新
schedule.every().sunday.at="20:00".do(update_data)

while True:
    schedule.run_pending()
    time.sleep(60)
```

### 技巧2: 筛选优质股票

```python
fetcher = StockDataFetcher()
stock_list = fetcher.get_stock_list()

quality_stocks = []

for code in stock_list['code'].head(100):  # 测试前100只
    financial = fetcher.get_financial_indicator(code)

    if not financial.empty:
        latest = financial.iloc[0]

        # 筛选条件: ROE>15%, 毛利率>30%
        if latest['净资产收益率'] > 15 and latest['销售毛利率'] > 30:
            quality_stocks.append(code)
            print(f"✅ {code} 符合条件")

print(f"\n找到 {len(quality_stocks)} 只优质股票")
```

### 技巧3: 回测简单策略

```python
# 简单的均线策略
def backtest_ma_strategy(code, start_date, end_date):
    data = fetcher.get_quote_data(code, start_date, end_date)
    data = fetcher.calculate_technical_indicators(data)

    signals = []

    for i in range(1, len(data)):
        today = data.iloc[i]
        yesterday = data.iloc[i-1]

        # 金叉买入
        if yesterday['MA5'] <= yesterday['MA10'] and today['MA5'] > today['MA10']:
            signals.append({'date': today['日期'], 'action': 'buy', 'price': today['收盘']})

        # 死叉卖出
        elif yesterday['MA5'] >= yesterday['MA10'] and today['MA5'] < today['MA10']:
            signals.append({'date': today['日期'], 'action': 'sell', 'price': today['收盘']})

    return signals

# 运行回测
signals = backtest_ma_strategy("000001", "20230101", "20231231")
print(f"产生 {len(signals)} 个交易信号")
```

---

## 📁 数据目录结构

```
stock_data/
├── quotes/              # 历史行情数据
│   └── 000001_20230101_20231231.csv
├── financial/           # 财务指标
│   └── 000001_financial_indicator_按年度.csv
├── reports/            # 三大报表
│   └── 000001_cash_flow_按年度.csv
├── market/             # 市场数据
│   └── 000001_money_flow.csv
└── stock_list.csv      # 股票列表
```

---

## ⚙️ 配置说明

### 数据存储路径

```python
# 自定义数据存储目录
fetcher = StockDataFetcher(data_dir="D:/my_stock_data")
```

### 请求延迟

```python
# 批量获取时设置延迟（避免被封IP）
fetcher.batch_get_quotes(
    symbols=stock_list,
    start_date="20230101",
    end_date="20231231",
    delay=2  # 每次请求间隔2秒
)
```

### 复权方式

```python
# 不复权
fetcher.get_quote_data("000001", "20230101", "20231231", adjust="")

# 前复权（推荐，用于技术分析）
fetcher.get_quote_data("000001", "20230101", "20231231", adjust="qfq")

# 后复权（用于计算收益率）
fetcher.get_quote_data("000001", "20230101", "20231231", adjust="hfq")
```

---

## 🚨 注意事项

1. **请求频率**: AKShare依赖第三方网站，建议批量获取时设置延迟（1-2秒）
2. **数据时效**: 财报数据有滞后性，年报最晚4月发布
3. **停牌股票**: 停牌期间没有行情数据
4. **退市股票**: 退市后可能无法获取数据
5. **数据质量**: 建议使用前复权数据进行技术分析

---

## 📚 进阶资源

### AKShare 官方文档
- 官网: https://akshare.akfamily.xyz/
- GitHub: https://github.com/akfamily/akshare

### 推荐学习路径
1. 先熟悉基础数据获取（行情、财务）
2. 学习技术指标计算（MA、MACD、RSI）
3. 尝试简单策略回测
4. 逐步构建自己的量化系统

### 常用量化库
```bash
# 回测框架
pip install backtrader

# 技术指标
pip install ta-lib

# 机器学习
pip install scikit-learn

# 数据可视化
pip install matplotlib plotly
```

---

## 🤝 贡献与反馈

如果您在使用中遇到问题或有改进建议，欢迎反馈！

**更新日志**:
- 2025-02-03: 初始版本发布
- 支持行情、财务、资金流向等核心数据
- 提供批量获取和导出功能
