# -*- coding: utf-8 -*-
"""
股票分析Web应用
Stock Analysis Web Application

基于Streamlit开发的交互式股票分析平台
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import sys
import os

# 添加模块路径
sys.path.append('.')
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

# 导入核心模块
try:
    from stock_data_fetcher import StockDataFetcher
    from signal_generator import SignalGenerator
    from chart_visualizer import ChartVisualizer, ChartStyle
    from backtest_framework import BacktestEngine, PositionConfig
    from portfolio_manager import PortfolioManager
    from real_time_monitor import RealTimeMonitor
    MODULES_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import modules: {e}")
    MODULES_AVAILABLE = False


# =============================================================================
# 页面配置
# =============================================================================

def setup_page_config():
    """配置页面基本设置"""
    st.set_page_config(
        page_title="Skills 股票分析平台",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # 自定义CSS
    st.markdown("""
    <style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        margin-bottom: 1rem;
    }
    .metric-card {
        background-color: #f0f2f6;
        border-radius: 10px;
        padding: 1rem;
        margin: 0.5rem 0;
    }
    .signal-buy {
        color: #00AA00;
        font-weight: bold;
    }
    .signal-sell {
        color: #FF4444;
        font-weight: bold;
    }
    </style>
    """, unsafe_allow_html=True)


# =============================================================================
# Session State 初始化
# =============================================================================

def init_session_state():
    """初始化Session State"""
    if 'fetcher' not in st.session_state:
        if MODULES_AVAILABLE:
            st.session_state.fetcher = StockDataFetcher()
            st.session_state.generator = SignalGenerator()
            st.session_state.visualizer = ChartVisualizer()
            st.session_state.manager = PortfolioManager()
        else:
            st.session_state.fetcher = None
            st.session_state.generator = None
            st.session_state.visualizer = None
            st.session_state.manager = None

    if 'watchlist' not in st.session_state:
        st.session_state.watchlist = ['600519', '000858', '002415']

    if 'selected_stock' not in st.session_state:
        st.session_state.selected_stock = '600519'

    if 'data_cache' not in st.session_state:
        st.session_state.data_cache = {}

    if 'dark_mode' not in st.session_state:
        st.session_state.dark_mode = False


# =============================================================================
# 侧边栏
# =============================================================================

def render_sidebar():
    """渲染侧边栏"""
    with st.sidebar:
        st.title("📈 Skills 股票分析")

        st.divider()

        # 页面导航
        st.subheader("导航")
        page = st.radio(
            "选择页面",
            ["🏠 首页", "📊 数据分析", "🔙 策略回测", "💼 组合管理", "⚠️ 实时监控"],
            label_visibility="collapsed"
        )

        st.divider()

        # 快速操作
        st.subheader("快速操作")

        # 股票代码输入
        stock_input = st.text_input(
            "股票代码",
            value=st.session_state.selected_stock,
            placeholder="输入6位代码",
            key="sidebar_stock_input"
        )

        if st.button("🔄 刷新数据", key="sidebar_refresh"):
            with st.spinner("正在获取数据..."):
                st.session_state.data_cache.clear()
                st.success("数据已刷新！")
                st.rerun()

        if stock_input and stock_input != st.session_state.selected_stock:
            st.session_state.selected_stock = stock_input
            st.rerun()

        st.divider()

        # 设置
        st.subheader("设置")

        # 主题切换
        dark_mode = st.checkbox("暗色模式", value=st.session_state.dark_mode)
        if dark_mode != st.session_state.dark_mode:
            st.session_state.dark_mode = dark_mode

        # 数据天数
        data_days = st.slider("数据天数", 30, 500, 120)
        st.session_state.data_days = data_days

        st.divider()

        # 自选股管理
        st.subheader("自选股")
        watchlist = st.session_state.watchlist

        selected_watch = st.selectbox(
            "选择自选股",
            watchlist,
            key="sidebar_watchlist"
        )

        if selected_watch:
            st.session_state.selected_stock = selected_watch

        # 添加新股票
        new_stock = st.text_input("添加股票", placeholder="600519", key="sidebar_add_stock")
        if st.button("添加", key="sidebar_add_btn"):
            if new_stock and new_stock not in watchlist:
                st.session_state.watchlist.append(new_stock)
                st.success(f"已添加 {new_stock}")
                st.rerun()

        st.divider()

        # 关于
        st.caption("Skills v2.0")
        st.caption("© 2026 股票分析平台")

    return page


# =============================================================================
# 首页/仪表盘
# =============================================================================

def render_dashboard():
    """渲染仪表盘页面"""
    st.markdown('<h1 class="main-header">📊 市场仪表盘</h1>', unsafe_allow_html=True)

    if not MODULES_AVAILABLE:
        st.error("核心模块未加载，请检查依赖安装")
        return

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label="📈 今日关注",
            value=len(st.session_state.watchlist),
            delta="只股票"
        )

    with col2:
        st.metric(
            label="💰 模拟资金",
            value="¥1,000,000",
            delta="+23.5%"
        )

    with col3:
        st.metric(
            label="🎯 信号数量",
            value="5",
            delta="2个买入"
        )

    with col4:
        st.metric(
            label="📊 组合收益",
            value="+15.3%",
            delta="+2.1%"
        )

    st.divider()

    # 自选股概览
    st.subheader("📋 自选股概览")

    watchlist_data = []
    for symbol in st.session_state.watchlist:
        try:
            data = get_stock_data(symbol, days=5)
            if data is not None and len(data) > 0:
                latest = data.iloc[-1]
                change_pct = latest.get('涨跌幅', 0)

                # 获取信号
                signal = get_stock_signal(symbol)
                signal_text = "买入" if signal.get('buy_signal', False) else (
                    "卖出" if signal.get('sell_signal', False) else "中性"
                )
                signal_class = "signal-buy" if signal.get('buy_signal') else (
                    "signal-sell" if signal.get('sell_signal') else ""
                )

                watchlist_data.append({
                    '代码': symbol,
                    '名称': get_stock_name(symbol),
                    '最新价': f"¥{latest['收盘']:.2f}",
                    '涨跌幅': f"{change_pct:+.2f}%",
                    '涨跌幅_值': change_pct,
                    '信号': signal_text,
                    '信号_class': signal_class
                })
        except Exception as e:
            pass

    if watchlist_data:
        df_watchlist = pd.DataFrame(watchlist_data)

        # 显示表格
        for _, row in df_watchlist.iterrows():
            with st.container():
                cols = st.columns([1, 2, 2, 2, 2])
                cols[0].write(f"**{row['代码']}**")
                cols[1].write(row['名称'])
                cols[2].write(row['最新价'])

                change_color = "🔴" if row['涨跌幅_值'] > 0 else "🟢" if row['涨跌幅_值'] < 0 else "⚪"
                cols[3].write(f"{change_color} {row['涨跌幅']}")

                if row['信号_class']:
                    cols[4].markdown(f"<span class='{row['信号_class']}'>{row['信号']}</span>", unsafe_allow_html=True)
                else:
                    cols[4].write(row['信号'])

                st.divider()

    # 最新信号
    st.subheader("🎯 最新交易信号")

    signals = get_all_signals(st.session_state.watchlist)

    if signals:
        buy_signals = [s for s in signals if s.get('buy_signal', False)]
        sell_signals = [s for s in signals if s.get('sell_signal', False)]

        col1, col2 = st.columns(2)

        with col1:
            st.write("**买入信号**")
            for signal in buy_signals[:5]:
                st.success(f"{signal['symbol']}: 强度 {signal['strength']:+.1f}")

        with col2:
            st.write("**卖出信号**")
            for signal in sell_signals[:5]:
                st.error(f"{signal['symbol']}: 强度 {signal['strength']:+.1f}")


# =============================================================================
# 数据分析页面
# =============================================================================

def render_analysis():
    """渲染数据分析页面"""
    st.markdown('<h1 class="main-header">📊 技术分析</h1>', unsafe_allow_html=True)

    if not MODULES_AVAILABLE:
        st.error("核心模块未加载，请检查依赖安装")
        return

    # 股票选择
    col1, col2, col3 = st.columns([2, 2, 1])

    with col1:
        symbol = st.text_input(
            "股票代码",
            value=st.session_state.selected_stock,
            key="analysis_symbol"
        )

    with col2:
        days = st.selectbox(
            "分析周期",
            [30, 60, 120, 252],
            index=2,
            key="analysis_days"
        )

    with col3:
        if st.button("分析", key="analysis_btn", type="primary"):
            st.session_state.selected_stock = symbol
            st.rerun()

    if not symbol:
        st.warning("请输入股票代码")
        return

    # 获取数据
    with st.spinner("正在获取数据..."):
        data = get_stock_data(symbol, days=days)

    if data is None or len(data) == 0:
        st.error(f"无法获取 {symbol} 的数据")
        return

    # 显示基本信息
    st.subheader(f"📈 {symbol} - {get_stock_name(symbol)}")

    latest = data.iloc[-1]
    change_pct = latest.get('涨跌幅', 0)

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.metric("最新价", f"¥{latest['收盘']:.2f}")

    with col2:
        delta = f"{change_pct:+.2f}%" if change_pct != 0 else "0.00%"
        st.metric("涨跌幅", delta, delta=delta)

    with col3:
        st.metric("最高", f"¥{latest['最高']:.2f}")

    with col4:
        st.metric("最低", f"¥{latest['最低']:.2f}")

    with col5:
        st.metric("成交量", f"{latest['成交量']:,.0f}")

    st.divider()

    # 技术指标
    st.subheader("📊 技术指标")

    # 计算技术指标
    data = st.session_state.fetcher.calculate_technical_indicators(data)
    latest_indicators = data.iloc[-1]

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.write("**均线系统**")
        st.write(f"MA5: {latest_indicators.get('MA5', 0):.2f}")
        st.write(f"MA20: {latest_indicators.get('MA20', 0):.2f}")
        st.write(f"MA60: {latest_indicators.get('MA60', 0):.2f}")

    with col2:
        st.write("**MACD**")
        st.write(f"MACD: {latest_indicators.get('MACD', 0):.2f}")
        st.write(f"Signal: {latest_indicators.get('MACD_Signal', 0):.2f}")
        st.write(f"Hist: {latest_indicators.get('MACD_Hist', 0):.2f}")

    with col3:
        st.write("**KDJ**")
        st.write(f"K: {latest_indicators.get('K', 0):.2f}")
        st.write(f"D: {latest_indicators.get('D', 0):.2f}")
        st.write(f"J: {latest_indicators.get('J', 0):.2f}")

    with col4:
        st.write("**其他指标**")
        st.write(f"RSI: {latest_indicators.get('RSI', 0):.2f}")
        st.write(f"ATR: {latest_indicators.get('ATR', 0):.2f}")
        st.write(f"布林带上轨: {latest_indicators.get('BB_Upper', 0):.2f}")

    st.divider()

    # 交易信号
    st.subheader("🎯 交易信号")

    signal = get_stock_signal(symbol)

    col1, col2, col3 = st.columns(3)

    with col1:
        if signal.get('buy_signal', False):
            st.success("**买入信号** ✅")
        elif signal.get('sell_signal', False):
            st.error("**卖出信号** ✅")
        else:
            st.info("**观望** ⚪")

    with col2:
        st.metric("信号强度", f"{signal['strength']:+.1f}")

    with col3:
        st.write("**建议**")
        if signal['strength'] > 5:
            st.write("🟢 积极买入")
        elif signal['strength'] > 2:
            st.write("🟡 考虑买入")
        elif signal['strength'] > -2:
            st.write("⚪ 观望")
        elif signal['strength'] > -5:
            st.write("🟡 考虑卖出")
        else:
            st.write("🔴 积极卖出")

    st.divider()

    # K线图
    st.subheader("📈 K线图表")

    chart_type = st.selectbox(
        "图表类型",
        ["K线图", "MACD", "RSI", "布林带", "综合分析"],
        key="analysis_chart_type"
    )

    try:
        import matplotlib.pyplot as plt
        import matplotlib
        matplotlib.use('Agg')

        if chart_type == "K线图":
            # 绘制K线图
            fig, ax = plt.subplots(figsize=(12, 6))

            # 简化K线绘制
            for i in range(len(data)):
                row = data.iloc[i]
                color = '#FF4444' if row['收盘'] >= row['开盘'] else '#00AA00'

                # 绘制实体
                height = abs(row['收盘'] - row['开盘'])
                bottom = min(row['收盘'], row['开盘'])
                ax.bar(i, height, bottom=bottom, width=0.6, color=color, alpha=0.8)

            # 绘制均线
            ax.plot(range(len(data)), data['MA5'], label='MA5', linewidth=1)
            ax.plot(range(len(data)), data['MA20'], label='MA20', linewidth=1)
            ax.plot(range(len(data)), data['MA60'], label='MA60', linewidth=1)

            ax.set_title(f"{symbol} K线图")
            ax.legend()
            ax.grid(True, alpha=0.3)

            st.pyplot(fig)
            plt.close()

        elif chart_type == "MACD":
            fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(12, 8), sharex=True)

            # 价格
            ax1.plot(range(len(data)), data['收盘'], label='收盘价', color='black')
            ax1.set_title(f"{symbol} MACD分析")
            ax1.legend()
            ax1.grid(True, alpha=0.3)

            # MACD线
            ax2.plot(range(len(data)), data['MACD'], label='MACD', color='blue')
            ax2.plot(range(len(data)), data['MACD_Signal'], label='Signal', color='red')
            ax2.legend()
            ax2.grid(True, alpha=0.3)

            # 柱状图
            colors = ['#FF4444' if x > 0 else '#00AA00' for x in data['MACD_Hist']]
            ax3.bar(range(len(data)), data['MACD_Hist'], color=colors, alpha=0.6)
            ax3.axhline(y=0, color='black', linewidth=0.5)
            ax3.grid(True, alpha=0.3)

            st.pyplot(fig)
            plt.close()

        elif chart_type == "RSI":
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 6), sharex=True)

            ax1.plot(range(len(data)), data['收盘'], label='收盘价')
            ax1.set_title(f"{symbol} RSI分析")
            ax1.legend()
            ax1.grid(True, alpha=0.3)

            ax2.plot(range(len(data)), data['RSI'], label='RSI', color='purple')
            ax2.axhline(y=70, color='red', linestyle='--', alpha=0.5, label='超买')
            ax2.axhline(y=30, color='green', linestyle='--', alpha=0.5, label='超卖')
            ax2.set_ylim(0, 100)
            ax2.legend()
            ax2.grid(True, alpha=0.3)

            st.pyplot(fig)
            plt.close()

        elif chart_type == "布林带":
            fig, ax = plt.subplots(figsize=(12, 6))

            ax.plot(range(len(data)), data['收盘'], label='收盘价', color='black')
            ax.plot(range(len(data)), data['BB_Upper'], label='上轨', color='red', linestyle='--')
            ax.plot(range(len(data)), data['BB_Middle'], label='中轨', color='blue', linestyle='--')
            ax.plot(range(len(data)), data['BB_Lower'], label='下轨', color='green', linestyle='--')
            ax.fill_between(range(len(data)), data['BB_Lower'], data['BB_Upper'], alpha=0.1)

            ax.set_title(f"{symbol} 布林带")
            ax.legend()
            ax.grid(True, alpha=0.3)

            st.pyplot(fig)
            plt.close()

        elif chart_type == "综合分析":
            st.info("综合分析图包含多个子图，请查看完整的图表功能")
            # 这里可以添加更复杂的综合图表

    except Exception as e:
        st.warning(f"图表生成失败: {str(e)}")


# =============================================================================
# 策略回测页面
# =============================================================================

def render_backtest():
    """渲染策略回测页面"""
    st.markdown('<h1 class="main-header">🔙 策略回测</h1>', unsafe_allow_html=True)

    if not MODULES_AVAILABLE:
        st.error("核心模块未加载，请检查依赖安装")
        return

    # 策略选择
    st.subheader("策略配置")

    col1, col2, col3 = st.columns(3)

    with col1:
        symbol = st.text_input(
            "股票代码",
            value="600519",
            key="backtest_symbol"
        )

    with col2:
        strategy = st.selectbox(
            "策略类型",
            ["MA交叉", "MACD", "多因子", "自定义"],
            key="backtest_strategy"
        )

    with col3:
        initial_cash = st.number_input(
            "初始资金",
            min_value=10000,
            max_value=10000000,
            value=1000000,
            step=100000,
            key="backtest_cash"
        )

    st.divider()

    # 策略参数
    st.subheader("策略参数")

    if strategy == "MA交叉":
        col1, col2 = st.columns(2)
        with col1:
            ma_short = st.slider("短期均线", 5, 20, 5)
        with col2:
            ma_long = st.slider("长期均线", 20, 60, 20)

    elif strategy == "MACD":
        st.info("使用默认MACD参数 (12, 26, 9)")

    elif strategy == "多因子":
        st.write("使用信号生成器的综合信号")

    st.divider()

    # 回测参数
    col1, col2, col3 = st.columns(3)

    with col1:
        backtest_days = st.slider("回测天数", 60, 500, 252)

    with col2:
        max_positions = st.slider("最大持仓", 1, 20, 5)

    with col3:
        position_size = st.slider("单只仓位(%)", 5, 50, 20)

    st.divider()

    # 运行回测
    if st.button("🚀 运行回测", type="primary", key="backtest_run_btn"):
        with st.spinner("正在运行回测..."):
            try:
                # 获取数据
                data = get_stock_data(symbol, days=backtest_days)

                if data is None or len(data) == 0:
                    st.error(f"无法获取 {symbol} 的数据")
                    return

                # 计算技术指标
                data = st.session_state.fetcher.calculate_technical_indicators(data)

                # 生成信号
                if strategy == "MA交叉":
                    data[f'MA{ma_short}'] = data['收盘'].rolling(ma_short).mean()
                    data[f'MA{ma_long}'] = data['收盘'].rolling(ma_long).mean()
                    data['signal_buy'] = (
                        (data[f'MA{ma_short}'] > data[f'MA{ma_long}']) &
                        (data[f'MA{ma_short}'].shift(1) <= data[f'MA{ma_long}'].shift(1))
                    )
                    data['signal_sell'] = (
                        (data[f'MA{ma_short}'] < data[f'MA{ma_long}']) &
                        (data[f'MA{ma_short}'].shift(1) >= data[f'MA{ma_long}'].shift(1))
                    )
                else:
                    data = st.session_state.generator.generate_signals(data)

                # 创建回测引擎
                engine = BacktestEngine(
                    initial_cash=initial_cash,
                    position_config=PositionConfig(
                        sizing_value=position_size / 100,
                        max_position_pct=0.5
                    )
                )

                # 运行回测
                def simple_strategy(data):
                    if len(data) < 2:
                        return 0
                    latest = data.iloc[-1]
                    if latest.get('signal_buy', 0) == 1:
                        return 1  # 买入
                    elif latest.get('signal_sell', 0) == 1:
                        return -1  # 卖出
                    return 0  # 持有

                result = engine.run(data, simple_strategy, symbol=symbol)

                # 显示结果
                st.success("回测完成！")

                st.divider()
                st.subheader("📊 回测结果")

                # 核心指标
                col1, col2, col3, col4 = st.columns(4)

                with col1:
                    st.metric("总收益率", f"{result.get('total_return', 0):.2f}%")

                with col2:
                    st.metric("年化收益率", f"{result.get('annualized_return', 0):.2f}%")

                with col3:
                    st.metric("夏普比率", f"{result.get('sharpe_ratio', 0):.2f}")

                with col4:
                    st.metric("最大回撤", f"{result.get('max_drawdown', 0):.2f}%")

                st.divider()

                # 交易统计
                col1, col2, col3 = st.columns(3)

                with col1:
                    st.metric("总交易次数", result.get('trade_count', 0))

                with col2:
                    st.metric("胜率", f"{result.get('win_rate', 0):.1f}%")

                with col3:
                    st.metric("盈亏比", f"{result.get('profit_factor', 0):.2f}")

                st.divider()

                # 净值曲线
                st.subheader("📈 净值曲线")

                try:
                    import matplotlib.pyplot as plt
                    import matplotlib
                    matplotlib.use('Agg')

                    fig, ax = plt.subplots(figsize=(12, 6))

                    equity_curve = result.get('equity_curve')
                    if equity_curve is not None and len(equity_curve) > 0:
                        equity_values = equity_curve['value'].values
                        ax.plot(range(len(equity_values)), equity_values, label='策略净值', linewidth=2)
                        ax.axhline(y=initial_cash, color='red', linestyle='--', label='初始资金')

                    ax.set_title("净值曲线")
                    ax.set_xlabel("交易日")
                    ax.set_ylabel("净值")
                    ax.legend()
                    ax.grid(True, alpha=0.3)

                    st.pyplot(fig)
                    plt.close()

                except Exception as e:
                    st.warning(f"图表生成失败: {str(e)}")

                # 交易记录
                st.subheader("📋 交易记录")

                trades_df = result.get('trades')
                if trades_df is not None and len(trades_df) > 0:
                    # 显示可用的列
                    display_cols = [col for col in ['date', 'symbol', 'action', 'price', 'shares', 'pnl', 'pnl_pct']
                                   if col in trades_df.columns]
                    st.dataframe(
                        trades_df[display_cols] if display_cols else trades_df,
                        use_container_width=True
                    )
                else:
                    st.info("无交易记录")

            except Exception as e:
                st.error(f"回测失败: {str(e)}")


# =============================================================================
# 组合管理页面
# =============================================================================

def render_portfolio():
    """渲染组合管理页面"""
    st.markdown('<h1 class="main-header">💼 组合管理</h1>', unsafe_allow_html=True)

    if not MODULES_AVAILABLE:
        st.error("核心模块未加载，请检查依赖安装")
        return

    manager = st.session_state.manager

    # 创建新组合
    with st.expander("➕ 创建新组合", expanded=False):
        col1, col2 = st.columns(2)

        with col1:
            portfolio_name = st.text_input("组合名称", "我的策略", key="new_portfolio_name")

        with col2:
            initial_cash = st.number_input(
                "初始资金",
                min_value=100000,
                max_value=10000000,
                value=1000000,
                step=100000,
                key="new_portfolio_cash"
            )

        if st.button("创建组合", key="create_portfolio_btn"):
            try:
                portfolio_obj = manager.create_portfolio(portfolio_name, initial_cash)
                st.success(f"组合创建成功！组合名称: {portfolio_obj.name}")
                st.rerun()
            except Exception as e:
                st.error(f"创建失败: {str(e)}")

    st.divider()

    # 组合列表
    portfolios = []
    for name, portfolio in manager.portfolios.items():
        portfolios.append({
            'name': portfolio.name,
            'id': name,
            'total_value': portfolio.total_value,
            'return_pct': portfolio.total_profit_loss_pct / 100.0  # 转换为小数
        })

    if portfolios:
        st.subheader("📋 组合列表")

        for portfolio in portfolios:
            with st.container():
                col1, col2, col3, col4 = st.columns([3, 2, 2, 1])

                with col1:
                    st.write(f"**{portfolio['name']}**")
                    st.caption(f"ID: {portfolio['id']}")

                with col2:
                    st.metric("总资产", f"¥{portfolio['total_value']:,.2f}")

                with col3:
                    st.metric("收益率", f"{portfolio['return_pct']:.2%}")

                with col4:
                    if st.button("详情", key=f"portfolio_{portfolio['id']}_detail"):
                        st.session_state.selected_portfolio = portfolio['id']
                        st.rerun()

                st.divider()

                # 持仓详情
                portfolio_obj = manager.get_portfolio(portfolio['id'])
                positions = portfolio_obj.positions.values() if portfolio_obj else []

                if positions:
                    st.write("**当前持仓:**")

                    pos_data = []
                    for pos in positions:
                        pos_data.append({
                            '代码': pos.symbol,
                            '名称': pos.name or get_stock_name(pos.symbol),
                            '持仓': pos.shares,
                            '成本价': f"¥{pos.cost_price:.2f}",
                            '现价': f"¥{pos.current_price:.2f}",
                            '市值': f"¥{pos.market_value:,.2f}",
                            '盈亏': f"{pos.profit_loss_pct:.2%}"
                        })

                    st.dataframe(pd.DataFrame(pos_data), use_container_width=True)
                else:
                    st.info("暂无持仓")

                st.divider()

                # 操作按钮
                col1, col2, col3 = st.columns(3)

                with col1:
                    if st.button("🔄 再平衡", key=f"rebalance_{portfolio['id']}"):
                        st.info("再平衡功能开发中...")

                with col2:
                    if st.button("📊 分析", key=f"analyze_{portfolio['id']}"):
                        st.info("分析功能开发中...")

                with col3:
                    if st.button("📄 报告", key=f"report_{portfolio['id']}"):
                        st.info("报告功能开发中...")

                st.divider()

    else:
        st.info("暂无组合，请创建新组合")


# =============================================================================
# 实时监控页面
# =============================================================================

def render_monitor():
    """渲染实时监控页面"""
    st.markdown('<h1 class="main-header">⚠️ 实时监控</h1>', unsafe_allow_html=True)

    if not MODULES_AVAILABLE:
        st.error("核心模块未加载，请检查依赖安装")
        return

    st.info("实时监控功能开发中...")

    # 监控状态
    st.subheader("监控状态")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("监控股票", "3")

    with col2:
        st.metric("告警条件", "12")

    with col3:
        st.metric("今日告警", "5")

    with col4:
        st.metric("未读告警", "2")

    st.divider()

    # 添加监控
    with st.expander("➕ 添加监控", expanded=False):
        col1, col2 = st.columns(2)

        with col1:
            monitor_symbol = st.text_input("股票代码", key="monitor_symbol")

        with col2:
            alert_type = st.selectbox(
                "告警类型",
                ["价格突破", "价格跌破", "涨跌幅", "突破信号"],
                key="monitor_alert_type"
            )

        if alert_type == "价格突破":
            threshold = st.number_input("突破价格", key="monitor_above_price")
        elif alert_type == "价格跌破":
            threshold = st.number_input("跌破价格", key="monitor_below_price")
        else:
            threshold = st.number_input("阈值(%)", key="monitor_threshold")

        if st.button("添加监控", key="add_monitor_btn"):
            st.success(f"已添加 {monitor_symbol} 的监控")
            st.rerun()

    st.divider()

    # 监控列表
    st.subheader("监控列表")

    monitor_list = [
        {'symbol': '600519', 'name': '贵州茅台', 'conditions': '价格突破2000', 'status': '正常'},
        {'symbol': '000858', 'name': '五粮液', 'conditions': '涨幅超过5%', 'status': '告警'},
        {'symbol': '002415', 'name': '海康威视', 'conditions': '买入信号', 'status': '正常'},
    ]

    for monitor in monitor_list:
        with st.container():
            col1, col2, col3, col4 = st.columns([2, 3, 2, 1])

            with col1:
                st.write(f"**{monitor['symbol']}**")

            with col2:
                st.write(monitor['conditions'])

            with col3:
                if monitor['status'] == '告警':
                    st.error(monitor['status'])
                else:
                    st.success(monitor['status'])

            with col4:
                if st.button("删除", key=f"del_{monitor['symbol']}"):
                    st.rerun()

            st.divider()


# =============================================================================
# 辅助函数
# =============================================================================

def get_stock_name(symbol: str) -> str:
    """获取股票名称"""
    name_map = {
        '600519': '贵州茅台',
        '000858': '五粮液',
        '002415': '海康威视',
        '600036': '招商银行',
        '000001': '平安银行',
        '601318': '中国平安',
        '600276': '恒瑞医药',
        '002304': '洋河股份',
        '000333': '美的集团',
        '600887': '伊利股份'
    }
    return name_map.get(symbol, symbol)


def get_stock_data(symbol: str, days: int = 120) -> Optional[pd.DataFrame]:
    """获取股票数据（带缓存）"""
    cache_key = f"{symbol}_{days}"

    # 检查缓存
    if cache_key in st.session_state.data_cache:
        return st.session_state.data_cache[cache_key]

    # 获取数据
    if st.session_state.fetcher:
        try:
            data = st.session_state.fetcher.get_quote_data(symbol, days=days)
            if data is not None and len(data) > 0:
                st.session_state.data_cache[cache_key] = data
                return data
        except Exception as e:
            st.error(f"获取数据失败: {str(e)}")

    return None


def get_stock_signal(symbol: str) -> Dict:
    """获取股票信号"""
    try:
        data = get_stock_data(symbol, days=120)
        if data is not None and len(data) > 0:
            data = st.session_state.fetcher.calculate_technical_indicators(data)
            signal = st.session_state.generator.get_latest_signal(data)
            return signal
    except Exception as e:
        pass

    return {
        'buy_signal': False,
        'sell_signal': False,
        'strength': 0
    }


def get_all_signals(symbols: List[str]) -> List[Dict]:
    """获取所有股票的信号"""
    signals = []

    for symbol in symbols:
        signal = get_stock_signal(symbol)
        signal['symbol'] = symbol
        signals.append(signal)

    # 按强度排序
    signals.sort(key=lambda x: abs(x.get('strength', 0)), reverse=True)

    return signals


# =============================================================================
# 主应用
# =============================================================================

def main():
    """主应用入口"""
    # 配置页面
    setup_page_config()

    # 初始化Session State
    init_session_state()

    # 渲染侧边栏并获取当前页面
    page = render_sidebar()

    # 根据页面路由
    if page == "🏠 首页":
        render_dashboard()
    elif page == "📊 数据分析":
        render_analysis()
    elif page == "🔙 策略回测":
        render_backtest()
    elif page == "💼 组合管理":
        render_portfolio()
    elif page == "⚠️ 实时监控":
        render_monitor()


# =============================================================================
# 应用启动
# =============================================================================

if __name__ == "__main__":
    main()
