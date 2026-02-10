# 图表可视化模块完成报告

**模块名称：** chart_visualizer.py
**完成日期：** 2026-02-06
**版本：** v1.0

---

## 📋 模块概述

图表可视化模块为股票分析系统提供了完整的图表绘制功能，支持多种技术指标图表、收益曲线、回撤分析等。

### 核心特性

- 8种图表类型
- 自定义K线绘制（无需mplfinance依赖）
- 可配置样式系统
- 批量图表生成
- 中文标签支持
- 非交互式后端（适用于服务器环境）

---

## 🎨 图表类型

### 1. K线图 (Candlestick Chart)

**方法：** `plot_candlestick(data, symbol, title, ma_periods=[5, 10, 20, 60], save_path=None)`

**功能：**
- 绘制K线图（蜡烛图）
- 支持多条移动平均线叠加
- 成交量柱状图
- 涨跌颜色区分（红涨绿跌）

**参数：**
| 参数 | 类型 | 说明 |
|------|------|------|
| data | DataFrame | 包含开高低收量的数据 |
| symbol | str | 股票代码 |
| title | str | 图表标题 |
| ma_periods | List[int] | 移动平均线周期 |
| save_path | str | 保存路径 |

---

### 2. MACD指标图

**方法：** `plot_macd(data, symbol, save_path=None)`

**功能：**
- MACD DIF线
- DEA信号线
- MACD柱状图
- 零轴标注

---

### 3. RSI指标图

**方法：** `plot_rsi(data, symbol, period=14, oversold=30, overbought=70, save_path=None)`

**功能：**
- RSI曲线
- 超买/超卖界线
- 可配置周期和阈值

---

### 4. 布林带图

**方法：** `plot_bollinger_bands(data, symbol, period=20, std=2, save_path=None)`

**功能：**
- 布林上轨、中轨、下轨
- K线叠加
- 可配置周期和标准差倍数

---

### 5. 收益曲线图

**方法：** `plot_equity_curve(equity_curve, symbol, benchmark_return=None, save_path=None)`

**功能：**
- 组合净值曲线
- 基准对比（可选）
- 对数Y轴
- 收益率标注

---

### 6. 回撤曲线图

**方法：** `plot_drawdown(equity_curve, symbol, save_path=None)`

**功能：**
- 回撤曲线
- 填充负面区域
- 最大回撤标注

---

### 7. 信号标注图

**方法：** `plot_signals(data, signals, symbol, save_path=None)`

**功能：**
- K线图基础
- 买卖信号箭头标注
- 信号强度显示

---

### 8. 综合分析图

**方法：** `plot_combined_analysis(data, symbol, save_path=None)`

**功能：**
- 6合1综合图表
- 包含：K线、成交量、MACD、RSI、布林带、信号
- 共享X轴

---

## 🎨 样式配置

### ChartStyle 类

```python
class ChartStyle:
    def __init__(self):
        # 颜色配置
        self.up_color = '#FF4444'        # 上涨（红）
        self.down_color = '#00AA00'      # 下跌（绿）
        self.bg_color = '#FFFFFF'        # 背景色
        self.grid_color = '#E0E0E0'      # 网格色

        # 图表尺寸
        self.figure_size = (14, 8)
        self.dpi = 100

        # K线配置
        self.candle_width = 0.6
        self.volume_alpha = 0.5

        # 字体配置
        self.title_fontsize = 14
        self.label_fontsize = 10
```

---

## 🔧 技术实现

### 自定义K线绘制

为避免mplfinance依赖问题，实现了自定义K线绘制：

```python
# 绘制K线
for i in range(len(plot_data)):
    row = plot_data.iloc[i]
    open_ = row['开盘']
    close = row['收盘']
    high = row['最高']
    low = row['最低']

    color = self.style.up_color if close >= open_ else self.style.down_color

    # 绘制影线
    ax.plot([row['date_num'], row['date_num']], [low, high],
            color=color, linewidth=1, alpha=0.6)

    # 绘制实体
    height = abs(close - open_)
    bottom = min(close, open_)
    ax.bar(row['date_num'], height, bottom=bottom,
           width=self.style.candle_width, color=color, alpha=0.8)
```

### 非交互式后端

```python
import matplotlib
matplotlib.use('Agg')  # 适用于服务器环境
```

---

## ✅ 测试结果

### 测试覆盖

| 测试项 | 状态 |
|--------|------|
| K线图绘制 | ✅ 通过 |
| MACD图表 | ✅ 通过 |
| RSI图表 | ✅ 通过 |
| 布林带图表 | ✅ 通过 |
| 收益曲线 | ✅ 通过 |
| 回撤曲线 | ✅ 通过 |
| 信号标注 | ✅ 通过 |
| 综合分析图 | ✅ 通过 |
| 批量生成 | ✅ 通过 |
| 自定义样式 | ✅ 通过 |

**通过率：** 10/10 (100%)

### 生成的图表文件

```
charts/
├── 600519_candlestick.png    # K线图
├── 600519_macd.png           # MACD图
├── 600519_rsi.png            # RSI图
├── 600519_bollinger.png      # 布林带图
├── 模拟组合_equity.png        # 收益曲线
├── 模拟组合_drawdown.png      # 回撤曲线
├── 600519_signals.png        # 信号标注图
├── 600519_combined.png       # 综合分析图
└── ... (批量生成图表)
```

---

## 📊 API参考

### 初始化

```python
from chart_visualizer import ChartVisualizer, ChartStyle

# 使用默认样式
visualizer = ChartVisualizer()

# 使用自定义样式
style = ChartStyle()
style.up_color = '#FF0000'
style.down_color = '#00FF00'
visualizer = ChartVisualizer(style=style)
```

### 使用示例

```python
# 绘制K线图
path = visualizer.plot_candlestick(
    data=df,
    symbol='600519',
    title='贵州茅台 - 日K线',
    ma_periods=[5, 10, 20, 60]
)

# 绘制综合分析图
path = visualizer.plot_combined_analysis(
    data=df,
    symbol='600519'
)

# 批量生成
symbols = ['600519', '000858', '002415']
for symbol in symbols:
    df = fetch_data(symbol)
    visualizer.plot_candlestick(df, symbol)
```

---

## 🎯 完成状态

| 任务 | 状态 |
|------|------|
| 核心功能开发 | ✅ 完成 |
| 8种图表类型 | ✅ 完成 |
| 样式系统 | ✅ 完成 |
| 自定义K线 | ✅ 完成 |
| 测试用例 | ✅ 完成 |
| 文档 | ✅ 完成 |

---

## 📈 后续计划

### v1.1 增强功能（可选）

- [ ] 添加更多技术指标（KDJ、OBV等）
- [ ] 支持plotly交互式图表
- [ ] 图表模板系统
- [ ] 图表导出为PDF/SVG
- [ ] 实时数据图表更新

### v2.0 高级功能

- [ ] Web界面集成
- [ ] 图表分享功能
- [ ] 自定义指标开发工具
- [ ] 图表性能优化

---

**报告生成时间：** 2026-02-06
**模块版本：** v1.0
**测试状态：** 全部通过 ✅
