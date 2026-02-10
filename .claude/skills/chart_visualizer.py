# -*- coding: utf-8 -*-
"""
数据可视化模块 - 完整版
Chart Visualizer Module

提供K线图、技术指标图表、收益曲线、回撤曲线等可视化功能
使用matplotlib实现
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import warnings

# Matplotlib imports
try:
    import matplotlib
    matplotlib.use('Agg')  # 使用非交互式后端
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.patches import Rectangle
    from matplotlib.lines import Line2D

    MATPLOTLIB_AVAILABLE = True
except ImportError as e:
    MATPLOTLIB_AVAILABLE = False
    warnings.warn(f"Matplotlib not available: {e}. Chart functions will be disabled.")


class ChartStyle:
    """图表样式配置"""
    def __init__(self):
        # 颜色配置
        self.up_color = '#FF4444'      # 上涨颜色（红）
        self.down_color = '#00AA00'    # 下跌颜色（绿）
        self.bg_color = '#FFFFFF'      # 背景色
        self.grid_color = '#E0E0E0'    # 网格线颜色
        self.text_color = '#333333'    # 文字颜色

        # 图表尺寸
        self.figure_size = (14, 8)
        self.dpi = 100

        # 字体配置
        self.font_family = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']

        # 线宽配置
        self.line_width = 1.5
        self.candle_width = 0.6


class ChartVisualizer:
    """图表可视化器"""

    def __init__(self, style: ChartStyle = None, output_dir: str = None):
        """
        初始化图表可视化器

        Args:
            style: 图表样式
            output_dir: 输出目录
        """
        if not MATPLOTLIB_AVAILABLE:
            raise ImportError("Matplotlib is required for chart visualization")

        self.style = style or ChartStyle()
        self.output_dir = output_dir or "charts"

        # 配置matplotlib
        plt.rcParams['font.sans-serif'] = self.style.font_family
        plt.rcParams['axes.unicode_minus'] = False
        plt.rcParams['figure.facecolor'] = self.style.bg_color
        plt.rcParams['figure.dpi'] = self.style.dpi

        # 创建输出目录
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

    def plot_candlestick(self, data: pd.DataFrame, symbol: str = "",
                         title: str = None, ma_periods: List[int] = None,
                         save_path: str = None) -> str:
        """
        绘制K线图

        Args:
            data: 包含OHLCV的DataFrame
            symbol: 股票代码
            title: 图表标题
            ma_periods: 均线周期列表
            save_path: 保存路径

        Returns:
            图片文件路径
        """
        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=self.style.figure_size,
            gridspec_kw={'height_ratios': [3, 1]},
            sharex=True
        )

        fig.patch.set_facecolor(self.style.bg_color)

        # 准备数据
        plot_data = data.copy()
        plot_data['date_num'] = mdates.date2num(plot_data['日期'].values)

        # 绘制K线 (不使用mplfinance)
        for i in range(len(plot_data)):
            row = plot_data.iloc[i]
            open_ = row['开盘']
            close = row['收盘']
            high = row['最高']
            low = row['最低']

            color = self.style.up_color if close >= open_ else self.style.down_color

            # 绘制影线
            ax1.plot([row['date_num'], row['date_num']], [low, high],
                    color=color, linewidth=1, alpha=0.6)

            # 绘制实体
            height = abs(close - open_)
            bottom = min(close, open_)
            ax1.bar(row['date_num'], height, bottom=bottom, width=self.style.candle_width,
                     color=color, alpha=0.8, edgecolor=color)

        # 绘制均线
        if ma_periods:
            for period in ma_periods:
                ma = plot_data['收盘'].rolling(window=period).mean()
                ax1.plot(plot_data['date_num'], ma, label=f'MA{period}',
                        linewidth=self.style.line_width, alpha=0.8)

        ax1.set_title(title or f"{symbol} K线图", fontsize=14, fontweight='bold')
        ax1.grid(True, color=self.style.grid_color, alpha=0.5)
        ax1.legend(loc='upper left')

        # 绘制成交量
        colors = [self.style.up_color if close >= open_ else self.style.down_color
                  for close, open_ in zip(plot_data['收盘'], plot_data['开盘'])]
        ax2.bar(plot_data['date_num'], plot_data['成交量'], color=colors,
               width=self.style.candle_width, alpha=0.6)

        ax2.set_ylabel("成交量")
        ax2.grid(True, color=self.style.grid_color, alpha=0.5)

        # 格式化x轴
        ax1.xaxis_date()
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        ax1.xaxis.set_major_locator(mdates.DayLocator(interval=15))
        plt.setp(ax1.xaxis.get_majorticklabels(), rotation=30)

        plt.tight_layout()

        # 保存图片
        if save_path is None:
            save_path = f"{self.output_dir}/{symbol}_candlestick.png"

        plt.savefig(save_path, facecolor=self.style.bg_color, dpi=self.style.dpi, bbox_inches='tight')
        plt.close()

        return save_path

    def plot_macd(self, data: pd.DataFrame, symbol: str = "",
                 save_path: str = None) -> str:
        """
        绘制MACD图

        Args:
            data: 包含MACD指标的DataFrame
            symbol: 股票代码
            save_path: 保存路径

        Returns:
            图片文件路径
        """
        fig, (ax1, ax2, ax3) = plt.subplots(
            3, 1, figsize=self.style.figure_size,
            sharex=True, gridspec_kw={'height_ratios': [2, 1, 1]}
        )

        fig.patch.set_facecolor(self.style.bg_color)

        # 准备数据
        if 'MACD' not in data.columns:
            # 计算MACD
            close = data['收盘']
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd = ema12 - ema26
            macd_signal = macd.ewm(span=9, adjust=False).mean()
            macd_hist = macd - macd_signal
        else:
            macd = data['MACD']
            macd_signal = data['MACD_Signal']
            macd_hist = data['MACD_Hist']

        x = range(len(macd))

        # 绘制K线价格
        ax1.plot(x, data['收盘'], label='收盘价', color='black', linewidth=1)
        ax1.set_title(f"{symbol} MACD分析", fontsize=14, fontweight='bold')
        ax1.grid(True, color=self.style.grid_color, alpha=0.5)
        ax1.legend(loc='upper left')

        # 绘制MACD和信号线
        ax2.plot(x, macd, label='MACD', color='blue', linewidth=self.style.line_width)
        ax2.plot(x, macd_signal, label='Signal', color='red', linewidth=self.style.line_width)
        ax2.grid(True, color=self.style.grid_color, alpha=0.5)
        ax2.legend(loc='upper left')

        # 绘制柱状图
        colors = [self.style.up_color if v > 0 else self.style.down_color for v in macd_hist]
        ax3.bar(x, macd_hist, color=colors, alpha=0.6)
        ax3.axhline(y=0, color='black', linewidth=0.5)
        ax3.grid(True, color=self.style.grid_color, alpha=0.5)

        ax1.set_ylabel("价格")
        ax2.set_ylabel("MACD")
        ax3.set_ylabel("Histogram")

        plt.tight_layout()

        # 保存图片
        if save_path is None:
            save_path = f"{self.output_dir}/{symbol}_macd.png"

        plt.savefig(save_path, facecolor=self.style.bg_color, dpi=self.style.dpi, bbox_inches='tight')
        plt.close()

        return save_path

    def plot_rsi(self, data: pd.DataFrame, symbol: str = "",
                 period: int = 14, oversold: float = 30, overbought: float = 70,
                 save_path: str = None) -> str:
        """
        绘制RSI图

        Args:
            data: 包含价格数据的DataFrame
            symbol: 股票代码
            period: RSI周期
            oversold: 超卖线
            overbought: 超买线
            save_path: 保存路径

        Returns:
            图片文件路径
        """
        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=self.style.figure_size,
            sharex=True, gridspec_kw={'height_ratios': [2, 1]}
        )

        fig.patch.set_facecolor(self.style.bg_color)

        # 计算RSI
        close = data['收盘']
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        x = range(len(rsi))

        # 绘制价格
        ax1.plot(x, close, label='收盘价', color='black', linewidth=1)
        ax1.set_title(f"{symbol} RSI分析({period}日)", fontsize=14, fontweight='bold')
        ax1.grid(True, color=self.style.grid_color, alpha=0.5)
        ax1.legend(loc='upper left')

        # 绘制RSI
        ax2.plot(x, rsi, label='RSI', color='purple', linewidth=self.style.line_width)
        ax2.axhline(y=overbought, color='red', linestyle='--', alpha=0.5, label=f'超买({overbought})')
        ax2.axhline(y=oversold, color='green', linestyle='--', alpha=0.5, label=f'超卖({oversold})')
        ax2.fill_between(x, oversold, overbought, alpha=0.1, color='gray')
        ax2.set_ylim(0, 100)
        ax2.set_ylabel("RSI")
        ax2.grid(True, color=self.style.grid_color, alpha=0.5)
        ax2.legend(loc='upper left')

        plt.tight_layout()

        # 保存图片
        if save_path is None:
            save_path = f"{self.output_dir}/{symbol}_rsi.png"

        plt.savefig(save_path, facecolor=self.style.bg_color, dpi=self.style.dpi, bbox_inches='tight')
        plt.close()

        return save_path

    def plot_bollinger_bands(self, data: pd.DataFrame, symbol: str = "",
                             period: int = 20, std: float = 2,
                             save_path: str = None) -> str:
        """
        绘制布林带图

        Args:
            data: 包含价格数据的DataFrame
            symbol: 股票代码
            period: 周期
            std: 标准差倍数
            save_path: 保存路径

        Returns:
            图片文件路径
        """
        fig, ax = plt.subplots(figsize=self.style.figure_size)

        fig.patch.set_facecolor(self.style.bg_color)

        # 计算布林带
        close = data['收盘']
        middle = close.rolling(window=period).mean()
        std_dev = close.rolling(window=period).std()
        upper = middle + std * std_dev
        lower = middle - std * std_dev

        x = range(len(close))

        # 绘制
        ax.plot(x, close, label='收盘价', color='black', linewidth=1.5)
        ax.plot(x, upper, label='上轨', color='red', linestyle='--', alpha=0.6)
        ax.plot(x, middle, label='中轨', color='blue', linestyle='--', alpha=0.6)
        ax.plot(x, lower, label='下轨', color='green', linestyle='--', alpha=0.6)

        # 填充区域
        ax.fill_between(x, lower, upper, alpha=0.1, color='gray')

        ax.set_title(f"{symbol} 布林带({period}日, ±{std}σ)", fontsize=14, fontweight='bold')
        ax.set_xlabel("时间")
        ax.set_ylabel("价格")
        ax.grid(True, color=self.style.grid_color, alpha=0.5)
        ax.legend(loc='upper left')

        plt.tight_layout()

        # 保存图片
        if save_path is None:
            save_path = f"{self.output_dir}/{symbol}_bollinger.png"

        plt.savefig(save_path, facecolor=self.style.bg_color, dpi=self.style.dpi, bbox_inches='tight')
        plt.close()

        return save_path

    def plot_equity_curve(self, equity_curve: pd.DataFrame, symbol: str = "",
                         benchmark_return: float = None,
                         save_path: str = None) -> str:
        """
        绘制净值曲线

        Args:
            equity_curve: 包含date和value的DataFrame
            symbol: 组合名称
            benchmark_return: 基准收益率
            save_path: 保存路径

        Returns:
            图片文件路径
        """
        fig, ax = plt.subplots(figsize=self.style.figure_size)

        fig.patch.set_facecolor(self.style.bg_color)

        # 计算收益率
        initial_value = equity_curve['value'].iloc[0]
        returns = (equity_curve['value'] / initial_value - 1) * 100

        # 绘制净值曲线
        ax.plot(equity_curve['date'], returns, label='策略净值', color='blue', linewidth=2)

        # 绘制基准
        if benchmark_return is not None:
            benchmark_returns = np.linspace(0, benchmark_return, len(equity_curve))
            ax.plot(equity_curve['date'], benchmark_returns, label='基准', color='gray', linestyle='--', alpha=0.6)

        ax.set_title(f"{symbol} 净值曲线", fontsize=14, fontweight='bold')
        ax.set_xlabel("日期")
        ax.set_ylabel("收益率 (%)")
        ax.grid(True, color=self.style.grid_color, alpha=0.5)
        ax.legend(loc='upper left')

        # 格式化x轴
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=30)

        plt.tight_layout()

        # 保存图片
        if save_path is None:
            save_path = f"{self.output_dir}/{symbol}_equity.png"

        plt.savefig(save_path, facecolor=self.style.bg_color, dpi=self.style.dpi, bbox_inches='tight')
        plt.close()

        return save_path

    def plot_drawdown(self, equity_curve: pd.DataFrame, symbol: str = "",
                     save_path: str = None) -> str:
        """
        绘制回撤曲线

        Args:
            equity_curve: 包含date和value的DataFrame
            symbol: 组合名称
            save_path: 保存路径

        Returns:
            图片文件路径
        """
        fig, ax = plt.subplots(figsize=self.style.figure_size)

        fig.patch.set_facecolor(self.style.bg_color)

        # 计算回撤
        values = equity_curve['value'].values
        cummax = np.maximum.accumulate(values)
        drawdown = (values / cummax - 1) * 100

        # 绘制回撤曲线
        ax.fill_between(equity_curve['date'], drawdown, 0, alpha=0.3, color='red')
        ax.plot(equity_curve['date'], drawdown, color='red', linewidth=1)

        # 标记最大回撤
        max_dd_idx = np.argmin(drawdown)
        max_dd_value = drawdown[max_dd_idx]
        ax.scatter([equity_curve['date'].iloc[max_dd_idx]], [max_dd_value],
                  color='darkred', s=100, zorder=5)
        ax.annotate(f'最大回撤: {max_dd_value:.2f}%',
                   xy=(equity_curve['date'].iloc[max_dd_idx], max_dd_value),
                   xytext=(10, 10), textcoords='offset points',
                   bbox=dict(boxstyle='round,pad=0.5', fc='yellow', alpha=0.7),
                   arrowprops=dict(arrowstyle='->', color='red'))

        ax.set_title(f"{symbol} 回撤曲线", fontsize=14, fontweight='bold')
        ax.set_xlabel("日期")
        ax.set_ylabel("回撤 (%)")
        ax.grid(True, color=self.style.grid_color, alpha=0.5)

        # 格式化x轴
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=30)

        plt.tight_layout()

        # 保存图片
        if save_path is None:
            save_path = f"{self.output_dir}/{symbol}_drawdown.png"

        plt.savefig(save_path, facecolor=self.style.bg_color, dpi=self.style.dpi, bbox_inches='tight')
        plt.close()

        return save_path

    def plot_signals(self, data: pd.DataFrame, signals: pd.DataFrame,
                    symbol: str = "", save_path: str = None) -> str:
        """
        绘制带信号标注的K线图

        Args:
            data: 包含OHLCV的DataFrame
            signals: 包含买卖信号的DataFrame
            symbol: 股票代码
            save_path: 保存路径

        Returns:
            图片文件路径
        """
        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=self.style.figure_size,
            gridspec_kw={'height_ratios': [3, 1]},
            sharex=True
        )

        fig.patch.set_facecolor(self.style.bg_color)

        # 准备数据
        plot_data = data.copy()
        plot_data['date_num'] = mdates.date2num(plot_data['日期'].values)

        # 绘制K线 (不使用mplfinance)
        for i in range(len(plot_data)):
            row = plot_data.iloc[i]
            open_ = row['开盘']
            close = row['收盘']
            high = row['最高']
            low = row['最低']

            color = self.style.up_color if close >= open_ else self.style.down_color

            # 绘制影线
            ax1.plot([row['date_num'], row['date_num']], [low, high],
                    color=color, linewidth=1, alpha=0.6)

            # 绘制实体
            height = abs(close - open_)
            bottom = min(close, open_)
            ax1.bar(row['date_num'], height, bottom=bottom, width=self.style.candle_width,
                     color=color, alpha=0.8, edgecolor=color)

        # 绘制均线
        ma5 = plot_data['收盘'].rolling(window=5).mean()
        ma20 = plot_data['收盘'].rolling(window=20).mean()
        ax1.plot(plot_data['date_num'], ma5, label='MA5', linewidth=1, alpha=0.8)
        ax1.plot(plot_data['date_num'], ma20, label='MA20', linewidth=1, alpha=0.8)

        # 标注买卖信号
        if 'signal_buy' in signals.columns:
            buy_signals = signals[signals['signal_buy'] == True]
            for date in buy_signals['日期']:
                idx = plot_data[plot_data['日期'] == date].index
                if len(idx) > 0:
                    price = plot_data.loc[idx[0], '最低']
                    ax1.scatter(plot_data.loc[idx[0], 'date_num'], price,
                              marker='^', color='red', s=200, zorder=5, label='Buy')

        if 'signal_sell' in signals.columns:
            sell_signals = signals[signals['signal_sell'] == True]
            for date in sell_signals['日期']:
                idx = plot_data[plot_data['日期'] == date].index
                if len(idx) > 0:
                    price = plot_data.loc[idx[0], '最高']
                    ax1.scatter(plot_data.loc[idx[0], 'date_num'], price,
                              marker='v', color='green', s=200, zorder=5, label='Sell')

        ax1.set_title(f"{symbol} 技术信号", fontsize=14, fontweight='bold')
        ax1.grid(True, color=self.style.grid_color, alpha=0.5)

        # 绘制信号强度
        if 'signal_strength' in signals.columns:
            ax2.bar(signals['日期'], signals['signal_strength'],
                   color=['red' if x > 0 else 'green' for x in signals['signal_strength']],
                   alpha=0.6)
            ax2.axhline(y=0, color='black', linewidth=0.5)
            ax2.set_ylabel("信号强度")

        plt.tight_layout()

        # 保存图片
        if save_path is None:
            save_path = f"{self.output_dir}/{symbol}_signals.png"

        plt.savefig(save_path, facecolor=self.style.bg_color, dpi=self.style.dpi, bbox_inches='tight')
        plt.close()

        return save_path

    def plot_combined_analysis(self, data: pd.DataFrame, symbol: str = "",
                               save_path: str = None) -> str:
        """
        绘制综合分析图表

        Args:
            data: 包含OHLCV及技术指标的DataFrame
            symbol: 股票代码
            save_path: 保存路径

        Returns:
            图片文件路径
        """
        fig = plt.figure(figsize=(self.style.figure_size[0] * 1.5, self.style.figure_size[1] * 1.5))
        gs = fig.add_gridspec(3, 2, hspace=0.3, wspace=0.3)

        fig.patch.set_facecolor(self.style.bg_color)

        # 准备数据
        plot_data = data.copy()
        plot_data['date_num'] = mdates.date2num(plot_data['日期'].values)
        x = range(len(plot_data))

        # 1. K线图 (顶部，跨两列)
        ax_candle = fig.add_subplot(gs[0, :])

        # 绘制K线 (不使用mplfinance)
        for i in range(len(plot_data)):
            row = plot_data.iloc[i]
            open_ = row['开盘']
            close = row['收盘']
            high = row['最高']
            low = row['最低']

            color = self.style.up_color if close >= open_ else self.style.down_color

            # 绘制影线
            ax_candle.plot([row['date_num'], row['date_num']], [low, high],
                          color=color, linewidth=0.5, alpha=0.5)

            # 绘制实体
            height = abs(close - open_)
            bottom = min(close, open_)
            ax_candle.bar(row['date_num'], height, bottom=bottom, width=0.6,
                          color=color, alpha=0.7)

        ma5 = plot_data['收盘'].rolling(window=5).mean()
        ma20 = plot_data['收盘'].rolling(window=20).mean()
        ma60 = plot_data['收盘'].rolling(window=60).mean()
        ax_candle.plot(plot_data['date_num'], ma5, label='MA5', linewidth=1)
        ax_candle.plot(plot_data['date_num'], ma20, label='MA20', linewidth=1)
        ax_candle.plot(plot_data['date_num'], ma60, label='MA60', linewidth=1)
        ax_candle.set_title(f"{symbol} 综合分析", fontsize=14, fontweight='bold')
        ax_candle.grid(True, color=self.style.grid_color, alpha=0.5)
        ax_candle.legend(loc='upper left')

        # 2. MACD (中间左侧)
        ax_macd = fig.add_subplot(gs[1, 0])
        if 'MACD' in plot_data.columns:
            ax_macd.plot(x, plot_data['MACD'], label='MACD', linewidth=1)
            ax_macd.plot(x, plot_data['MACD_Signal'], label='Signal', linewidth=1)
            colors = [self.style.up_color if v > 0 else self.style.down_color
                      for v in plot_data['MACD_Hist']]
            ax_macd.bar(x, plot_data['MACD_Hist'], color=colors, alpha=0.3)
        ax_macd.set_title("MACD")
        ax_macd.grid(True, color=self.style.grid_color, alpha=0.5)

        # 3. RSI (中间右侧)
        ax_rsi = fig.add_subplot(gs[1, 1])
        if 'RSI' in plot_data.columns:
            ax_rsi.plot(x, plot_data['RSI'], label='RSI', color='purple', linewidth=1)
        else:
            close = plot_data['收盘']
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            ax_rsi.plot(x, rsi, label='RSI', color='purple', linewidth=1)
        ax_rsi.axhline(y=70, color='red', linestyle='--', alpha=0.5)
        ax_rsi.axhline(y=30, color='green', linestyle='--', alpha=0.5)
        ax_rsi.set_ylim(0, 100)
        ax_rsi.set_title("RSI")
        ax_rsi.grid(True, color=self.style.grid_color, alpha=0.5)

        # 4. 成交量 (底部左侧)
        ax_volume = fig.add_subplot(gs[2, 0])
        colors = [self.style.up_color if close >= open_ else self.style.down_color
                  for close, open_ in zip(plot_data['收盘'], plot_data['开盘'])]
        ax_volume.bar(x, plot_data['成交量'], color=colors, alpha=0.6)
        ax_volume.set_title("成交量")

        # 5. KDJ (底部右侧)
        ax_kdj = fig.add_subplot(gs[2, 1])
        if 'K' in plot_data.columns:
            ax_kdj.plot(x, plot_data['K'], label='K', linewidth=1)
            ax_kdj.plot(x, plot_data['D'], label='D', linewidth=1)
            ax_kdj.plot(x, plot_data['J'], label='J', linewidth=1)
        ax_kdj.set_title("KDJ")
        ax_kdj.grid(True, color=self.style.grid_color, alpha=0.5)

        plt.tight_layout()

        # 保存图片
        if save_path is None:
            save_path = f"{self.output_dir}/{symbol}_combined.png"

        plt.savefig(save_path, facecolor=self.style.bg_color, dpi=self.style.dpi, bbox_inches='tight')
        plt.close()

        return save_path


# 便捷函数
def plot_stock_chart(data: pd.DataFrame, symbol: str, chart_type: str = 'candlestick',
                     save_dir: str = None) -> str:
    """
    绘制股票图表的便捷函数

    Args:
        data: 包含OHLCV的DataFrame
        symbol: 股票代码
        chart_type: 图表类型 (candlestick/macd/rsi/bollinger/equity/drawdown/signals/combined)
        save_dir: 保存目录

    Returns:
        图片文件路径
    """
    visualizer = ChartVisualizer(output_dir=save_dir)

    if chart_type == 'candlestick':
        return visualizer.plot_candlestick(data, symbol)
    elif chart_type == 'macd':
        return visualizer.plot_macd(data, symbol)
    elif chart_type == 'rsi':
        return visualizer.plot_rsi(data, symbol)
    elif chart_type == 'bollinger':
        return visualizer.plot_bollinger_bands(data, symbol)
    elif chart_type == 'equity':
        return visualizer.plot_equity_curve(data, symbol)
    elif chart_type == 'drawdown':
        return visualizer.plot_drawdown(data, symbol)
    elif chart_type == 'signals':
        # 需要signals数据
        from signal_generator import SignalGenerator
        generator = SignalGenerator()
        signals = generator.generate_signals(data)
        return visualizer.plot_signals(data, signals, symbol)
    elif chart_type == 'combined':
        return visualizer.plot_combined_analysis(data, symbol)
    else:
        raise ValueError(f"Unknown chart type: {chart_type}")


if __name__ == "__main__":
    print("Chart Visualizer - Complete Version v1.0")
    print("\nChart Types:")
    print("- Candlestick: K线图")
    print("- MACD: MACD图")
    print("- RSI: RSI图")
    print("- Bollinger Bands: 布林带图")
    print("- Equity Curve: 净值曲线")
    print("- Drawdown: 回撤曲线")
    print("- Signals: 信号标注图")
    print("- Combined: 综合分析图")
