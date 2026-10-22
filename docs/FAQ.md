# Skills 模块常见问题 (FAQ)

**版本：** v1.0
**更新日期：** 2026-02-06

---

## 📋 目录

1. [安装与配置](#安装与配置)
2. [数据获取](#数据获取)
3. [技术分析](#技术分析)
4. [信号与策略](#信号与策略)
5. [回测相关](#回测相关)
6. [组合管理](#组合管理)
7. [监控与告警](#监控与告警)
8. [可视化](#可视化)
9. [性能优化](#性能优化)
10. [错误排查](#错误排查)

---

## 安装与配置

### Q1: 安装时出现依赖冲突怎么办？

**A:** 建议使用虚拟环境：

```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 安装依赖
pip install pandas numpy matplotlib akshare openpyxl
```

### Q2: 如何确认安装成功？

```python
# 测试导入
try:
    import akshare
    import pandas
    import matplotlib
    from stock_data_fetcher import StockDataFetcher
    print("安装成功！")
except Exception as e:
    print(f"安装失败: {e}")
```

### Q3: 如何设置数据存储路径？

```python
from stock_data_fetcher import StockDataFetcher

# 方法1：初始化时指定
fetcher = StockDataFetcher(data_dir="D:/my_stock_data")

# 方法2：修改配置
import os
os.environ['STOCK_DATA_DIR'] = 'D:/my_stock_data'
```

---

## 数据获取

### Q4: 获取数据失败怎么办？

**A:** 常见原因和解决方案：

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 连接超时 | 网络问题 | 检查网络连接，增加重试 |
| 数据为空 | 股票代码错误 | 确认代码格式（6位数字） |
| 部分数据缺失 | 停牌/新股 | 正常现象，跳过处理 |

```python
# 添加重试机制
import time

def get_data_with_retry(symbol, max_retries=3):
    for i in range(max_retries):
        data = fetcher.get_quote_data(symbol, days=120)
        if not data.empty:
            return data
        time.sleep(1)
    return None
```

### Q5: 如何获取复权数据？

**A:** 当前使用腾讯接口默认前复权。如需其他复权方式：

```python
# 使用备用方法
data = fetcher.get_quote_data_fallback(
    symbol='600519',
    start_date='20230101',
    end_date='20231231',
    adjust='qfq'  # qfq前复权, hfq后复权, ''不复权
)
```

### Q6: 批量获取时请求过快被限制怎么办？

```python
# 增加请求延迟
all_data = fetcher.batch_get_quotes(
    symbols=stocks,
    delay=1.0  # 增加到1秒
)

# 或分批处理
def batch_get_in_groups(symbols, group_size=5):
    results = {}
    for i in range(0, len(symbols), group_size):
        group = symbols[i:i+group_size]
        batch = fetcher.batch_get_quotes(group, delay=0.5)
        results.update(batch)
        time.sleep(2)  # 组间等待
    return results
```

### Q7: 如何获取历史数据更早的数据？

```python
# 指定日期范围
data = fetcher.get_quote_data(
    symbol='600519',
    start_date='20200101',  # 从2020年开始
    end_date='20231231'
)

# 注意：腾讯接口最早可到2015年左右
```

---

## 技术分析

### Q8: 如何自定义技术指标？

```python
def custom_indicator(data, period=14):
    """自定义指标示例"""
    close = data['收盘']

    # 计算你的指标
    indicator = close.rolling(period).apply(
        lambda x: (x.iloc[-1] - x.min()) / (x.max() - x.min()) * 100
    )

    return indicator

# 使用
data['Custom'] = custom_indicator(data, 14)
```

### Q9: 技术指标计算出现NaN怎么办？

```python
# 处理NaN
data = data.fillna(method='ffill')  # 前向填充
data = data.fillna(method='bfill')  # 后向填充

# 或删除NaN
data = data.dropna()

# 或只删除前面不足的数据
min_periods = 60
data = data.iloc[min_periods:]
```

### Q10: 如何识别特定K线形态？

```python
from technical_analyzer import TechnicalAnalyzer

analyzer = TechnicalAnalyzer()

# 检测所有形态
pattern = analyzer.detect_pattern(data)

# 查找特定形态
def find_hammer(data):
    """查找锤子线"""
    for i in range(1, len(data)):
        prev = data.iloc[i-1]
        curr = data.iloc[i]

        # 锤子线条件
        body = abs(curr['收盘'] - curr['开盘'])
        lower_shadow = min(curr['开盘'], curr['收盘']) - curr['最低']
        upper_shadow = curr['最高'] - max(curr['开盘'], curr['收盘'])

        if (lower_shadow > body * 2 and
            upper_shadow < body * 0.3 and
            body < curr['收盘'] * 0.03):
            print(f"锤子线: {curr['日期']}")
```

---

## 信号与策略

### Q11: 信号强度如何计算？

```python
# 信号强度由7个子信号加权求和：
# - 均线交叉 (±1)
# - MACD (±1)
# - KDJ (±1)
# - RSI (±1)
# - 布林带 (±1)
# - 成交量 (±0.5)
# - 突破 (±1)

# 总范围: -10 到 +10

# 自定义权重
def custom_signal_strength(df):
    weights = {
        'ma_cross': 2.0,    # 提高均线权重
        'macd': 1.5,
        'kdj': 1.0,
        'rsi': 0.5,        # 降低RSI权重
        'bb': 1.0,
        'volume': 1.0,
        'breakout': 2.0    # 提高突破权重
    }

    strength = sum(df[f'signal_{sig}'] * w
                   for sig, w in weights.items())

    return strength.clip(-10, 10)
```

### Q12: 如何创建自定义策略？

```python
def my_strategy(data):
    """自定义策略示例"""

    # 计算指标
    data['MA20'] = data['收盘'].rolling(20).mean()
    data['RSI'] = calculate_rsi(data['收盘'])

    # 买入条件
    buy_conditions = (
        (data['收盘'] > data['MA20']) &  # 趋势向上
        (data['RSI'] < 70) &              # 非超买
        (data['成交量'] > data['成交量'].rolling(20).mean() * 1.5)  # 放量
    )

    # 卖出条件
    sell_conditions = (
        (data['RSI'] > 80) |  # 超买
        (data['收盘'] < data['MA20'] * 0.95)  # 跌破均线5%
    )

    data['signal_buy'] = buy_conditions
    data['signal_sell'] = sell_conditions

    return data
```

### Q13: 如何过滤假信号？

```python
# 方法1: 信号确认
def confirm_signals(data, confirm_days=2):
    """需要连续N天才触发"""
    for col in ['signal_buy', 'signal_sell']:
        data[f'{col}_confirmed'] = (
            data[col].rolling(confirm_days).sum() == confirm_days
        )
    return data

# 方法2: 趋势过滤
def filter_by_trend(data):
    """只在上升趋势中买入"""
    data['uptrend'] = data['MA20'] > data['MA60']
    data['signal_buy'] = (
        data['signal_buy'] & data['uptrend']
    )
    return data

# 方法3: 波动率过滤
def filter_by_volatility(data, max_vol=0.05):
    """过滤高波动股票"""
    data['volatility'] = data['收盘'].pct_change().rolling(20).std()
    data['signal_buy'] = (
        data['signal_buy'] & (data['volatility'] < max_vol)
    )
    return data
```

---

## 回测相关

### Q14: 回测结果不理想怎么办？

**A:** 优化方向检查清单：

| 检查项 | 说明 |
|--------|------|
| ✓ 信号质量 | 信号胜率是否足够高 |
| ✓ 交易成本 | 是否考虑了手续费和滑点 |
| ✓ 持仓时间 | 是否过度交易 |
| ✓ 仓位管理 | 是否仓位过重 |
| ✓ 止损止盈 | 是否设置了合理的止损 |
| ✓ 样本外测试 | 是否在样本外验证过 |

```python
# 添加交易成本
engine = BacktestEngine(
    initial_cash=1000000,
    commission=0.0003,  # 万三手续费
    slippage=0.001      # 千一滑点
)
```

### Q15: 如何处理停牌股票？

```python
def filter_suspended_stocks(data):
    """过滤停牌股票"""
    # 方法1: 检查成交量
    data['normal'] = data['成交量'] > 0

    # 方法2: 检查价格变化
    data['price_changed'] = data['收盘'].pct_change().abs() > 0

    # 标记正常交易日
    data['trading_day'] = data['normal'] | data['price_changed']

    return data[data['trading_day']]
```

### Q16: 如何进行样本外测试？

```python
# 分割数据集
split_date = '2023-01-01'
train_data = data[data['日期'] < split_date]
test_data = data[data['日期'] >= split_date]

# 在训练集上优化
# ... 优化参数 ...

# 在测试集上验证
result = engine.run_backtest(test_data, test_data)

# 比较结果
print(f"训练集年化收益: {train_result.annual_return:.2%}")
print(f"测试集年化收益: {result.annual_return:.2%}")
```

### Q17: 如何分析回测失败原因？

```python
def analyze_failure(result):
    """分析失败原因"""

    # 检查交易次数
    if len(result.trades) < 10:
        print("⚠️ 交易次数过少，信号可能过弱")

    # 检查胜率
    if result.win_rate < 0.4:
        print("⚠️ 胜率过低，需要优化入场条件")

    # 检查盈亏比
    if result.profit_factor < 1.5:
        print("⚠️ 盈亏比不佳，需要优化出场条件")

    # 检查最大回撤
    if result.max_drawdown < -0.3:
        print("⚠️ 回撤过大，需要添加止损")

    # 检查交易分布
    trades_per_month = len(result.trades) / (result.trades['exit_date'].max().month - result.trades['exit_date'].min().month + 1)
    if trades_per_month > 20:
        print("⚠️ 交易过于频繁，考虑增加信号过滤")
```

---

## 组合管理

### Q18: 如何创建等权组合？

```python
from portfolio_manager import PortfolioManager

manager = PortfolioManager()
portfolio_id = manager.create_portfolio('等权组合', 1000000)

# 等权配置
stocks = ['600519', '000858', '002415', '600036']
weight = 1.0 / len(stocks)
target_weights = {s: weight for s in stocks}

manager.rebalance(portfolio_id, target_weights)
```

### Q19: 如何实现定期再平衡？

```python
import schedule
import time

def rebalance_job():
    """定期再平衡任务"""
    # 获取最新目标权重
    target_weights = get_target_weights()

    # 再平衡
    manager.rebalance(portfolio_id, target_weights)

    print(f"再平衡完成: {datetime.now()}")

# 每周一执行
schedule.every().monday.at('9:30').do(rebalance_job)

while True:
    schedule.run_pending()
    time.sleep(60)
```

### Q20: 如何计算组合风险？

```python
# 获取风险指标
risk = manager.get_risk_metrics(portfolio_id)

# 风险评估
if risk['volatility'] > 0.3:
    print("⚠️ 组合波动率过高，考虑降低仓位")

if risk['var_95'] < -0.05:
    print("⚠️ VaR风险过大，需要风控")

if risk['beta'] > 1.5:
    print("⚠️ Beta过高，组合系统性风险大")
```

---

## 监控与告警

### Q21: 如何设置多重告警？

```python
from real_time_monitor import AlertCondition, AlertType, AlertPriority

# 价格告警
price_alerts = [
    AlertCondition(AlertType.PRICE_ABOVE, 2000, AlertPriority.HIGH),
    AlertCondition(AlertType.PRICE_BELOW, 1500, AlertPriority.URGENT),
]

# 涨跌幅告警
change_alerts = [
    AlertCondition(AlertType.CHANGE_UP, 5.0, AlertPriority.MEDIUM),
    AlertCondition(AlertType.CHANGE_DOWN, 5.0, AlertPriority.HIGH),
]

# 突破告警
breakout_alerts = [
    AlertCondition(AlertType.BREAKOUT_HIGH, 20, AlertPriority.HIGH),
    AlertCondition(AlertType.BREAKOUT_LOW, 20, AlertPriority.MEDIUM),
]

# 批量添加
for alert in price_alerts + change_alerts + breakout_alerts:
    monitor.add_condition('600519', alert)
```

### Q22: 如何发送微信/邮件告警？

```python
# 邮件告警
def email_alert(alert):
    import smtplib
    from email.mime.text import MIMEText

    msg = MIMEText(alert.message)
    msg['Subject'] = f"股票告警: {alert.symbol}"
    msg['From'] = 'your@email.com'
    msg['To'] = 'trader@email.com'

    smtp = smtplib.SMTP('smtp.gmail.com', 587)
    smtp.send_message(msg)
    smtp.quit()

# 微信告警（使用Server酱）
def wechat_alert(alert):
    import requests

    url = f"https://sctapi.ftqq.com/YOUR_KEY.send"
    data = {
        'title': f"股票告警: {alert.symbol}",
        'desp': alert.message
    }
    requests.post(url, data=data)

# 注册
monitor.register_callback(email_alert)
monitor.register_callback(wechat_alert)
```

### Q23: 如何避免重复告警？

```python
# 方法1: 冷却时间
class CooldownMonitor:
    def __init__(self, cooldown_seconds=3600):
        self.cooldown = {}
        self.cooldown_seconds = cooldown_seconds

    def check_with_cooldown(self, symbol):
        now = datetime.now()

        # 检查冷却时间
        if symbol in self.cooldown:
            elapsed = (now - self.cooldown[symbol]).total_seconds()
            if elapsed < self.cooldown_seconds:
                return False

        # 执行检查
        alerts = monitor.check_conditions(symbol)
        if alerts:
            self.cooldown[symbol] = now
            return True

        return False

# 使用
cooldown_monitor = CooldownMonitor(cooldown_seconds=3600)
if cooldown_monitor.check_with_cooldown('600519'):
    print("触发告警")
```

---

## 可视化

### Q24: 如何自定义图表样式？

```python
from chart_visualizer import ChartStyle

# 创建自定义样式
style = ChartStyle()
style.up_color = '#FF0000'         # 红色上涨
style.down_color = '#00FF00'       # 绿色下跌
style.bg_color = '#1E1E1E'         # 深色背景
style.grid_color = '#444444'       # 深色网格
style.text_color = '#FFFFFF'       # 白色文字
style.figure_size = (16, 9)        # 宽屏
style.dpi = 150                    # 高清

# 应用样式
visualizer = ChartVisualizer(style=style)
```

### Q25: 如何批量生成图表？

```python
import os
from concurrent.futures import ThreadPoolExecutor

def generate_charts_for_stock(symbol):
    """为单只股票生成所有图表"""
    try:
        data = fetcher.get_quote_data(symbol, days=120)
        if len(data) == 0:
            return

        data = fetcher.calculate_technical_indicators(data)

        # 生成多种图表
        charts = [
            visualizer.plot_candlestick(data, symbol),
            visualizer.plot_macd(data, symbol),
            visualizer.plot_rsi(data, symbol),
            visualizer.plot_bollinger_bands(data, symbol),
            visualizer.plot_combined_analysis(data, symbol),
        ]

        print(f"✓ {symbol}: 生成 {len(charts)} 张图表")

    except Exception as e:
        print(f"✗ {symbol}: {e}")

# 批量生成
stocks = ['600519', '000858', '002415', '600036', '601318']

with ThreadPoolExecutor(max_workers=3) as executor:
    executor.map(generate_charts_for_stock, stocks)
```

### Q26: 图表中文显示乱码怎么办？

```python
import matplotlib.pyplot as plt

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False

# 或在ChartVisualizer中设置
style = ChartStyle()
style.font_family = ['SimHei', 'Microsoft YaHei']
visualizer = ChartVisualizer(style=style)
```

---

## 性能优化

### Q27: 如何提高数据获取速度？

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def fast_batch_fetch(symbols, days=120, max_workers=5):
    """多线程批量获取"""
    fetcher = StockDataFetcher()

    def fetch_one(symbol):
        return symbol, fetcher.get_quote_data(symbol, days=days)

    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_one, s): s for s in symbols}

        for future in as_completed(futures):
            symbol, data = future.result()
            if not data.empty:
                results[symbol] = data

    return results

# 使用
data = fast_batch_fetch(stocks, days=120, max_workers=5)
```

### Q28: 如何减少内存使用？

```python
# 方法1: 分块处理
def process_in_chunks(symbols, chunk_size=10):
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i:i+chunk_size]
        # 处理这一批
        process_batch(chunk)
        # 清理内存
        import gc
        gc.collect()

# 方法2: 只保留需要的列
data = data[['日期', '开盘', '最高', '最低', '收盘', '成交量']]

# 方法3: 使用适当的数据类型
data['成交量'] = data['成交量'].astype('int32')
data['收盘'] = data['收盘'].astype('float32')
```

### Q29: 如何缓存数据？

```python
import pickle
from datetime import datetime, timedelta

class CachedFetcher:
    def __init__(self, cache_hours=24):
        self.cache_dir = 'cache'
        self.cache_hours = cache_hours
        os.makedirs(self.cache_dir, exist_ok=True)

    def get_quote_data(self, symbol, days=120):
        # 检查缓存
        cache_file = f"{self.cache_dir}/{symbol}_{days}.pkl"

        if os.path.exists(cache_file):
            # 检查缓存是否过期
            cache_time = datetime.fromtimestamp(os.path.getmtime(cache_file))
            if datetime.now() - cache_time < timedelta(hours=self.cache_hours):
                with open(cache_file, 'rb') as f:
                    return pickle.load(f)

        # 获取新数据
        fetcher = StockDataFetcher()
        data = fetcher.get_quote_data(symbol, days)

        # 保存缓存
        with open(cache_file, 'wb') as f:
            pickle.dump(data, f)

        return data
```

---

## 错误排查

### Q30: 常见错误及解决方法

| 错误 | 原因 | 解决方法 |
|------|------|----------|
| `KeyError: '收盘'` | 列名不匹配 | 检查列名是否正确 |
| `IndexError: list index out of range` | 数据不足 | 增加数据量或检查代码 |
| `ConnectionError` | 网络问题 | 检查网络或重试 |
| `ValueError: could not convert string to float` | 数据格式错误 | 清洗数据或转换格式 |
| `AttributeError: 'DataFrame' object has no attribute 'xxx'` | 方法名错误 | 检查方法名拼写 |

### Q31: 如何调试策略？

```python
# 打印中间结果
def debug_strategy(data):
    print("数据形状:", data.shape)
    print("列名:", data.columns.tolist())

    # 检查信号分布
    print("买入信号:", data['signal_buy'].sum())
    print("卖出信号:", data['signal_sell'].sum())

    # 检查信号位置
    buy_dates = data[data['signal_buy']]['日期']
    print("买入日期:", buy_dates.tolist())

    # 可视化
    import matplotlib.pyplot as plt
    plt.figure(figsize=(12, 6))
    plt.plot(data['日期'], data['收盘'])
    plt.scatter(buy_dates, data[data['signal_buy']]['收盘'],
                color='red', marker='^', s=100)
    plt.show()

debug_strategy(data)
```

### Q32: 如何记录日志？

```python
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger('my_strategy')

# 使用日志
logger.info("开始回测")
logger.warning("数据量不足，可能影响结果")
logger.error("数据获取失败")

# 在关键位置添加日志
def backtest(data, signals):
    logger.info(f"回测数据范围: {data['日期'].min()} 到 {data['日期'].max()}")
    logger.info(f"买入信号数量: {signals['signal_buy'].sum()}")

    result = engine.run_backtest(data, signals)

    logger.info(f"回测完成，收益率: {result.total_return:.2%}")
    return result
```

---

**文档版本：** v1.0
**最后更新：** 2026-02-06
