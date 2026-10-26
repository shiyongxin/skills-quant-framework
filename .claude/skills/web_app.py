# -*- coding: utf-8 -*-
"""
股票分析Web应用
Stock Analysis Web Application

基于Streamlit开发的交互式股票分析平台
"""

# Streamlit 是可选依赖: 缺失时模块仍可被 import (供测试/工具链导入),
# 但界面不可用 —— 如实降级, 不再以 ImportError 硬崩 (审计: 可选依赖降级路径零覆盖)
try:
    import streamlit as st
    STREAMLIT_AVAILABLE = True
except ImportError:
    st = None
    STREAMLIT_AVAILABLE = False

import pandas as pd
from typing import Optional, Dict, List
import sys
import os
import inspect
import traceback

# 模块路径: 基于 __file__, 不依赖启动时的工作目录
# (修复审计 F-P1: 旧实现 sys.path.append('.') 与 '../..' 换目录即断)
_SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(_SKILLS_DIR))
for _p in (_SKILLS_DIR, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 导入核心模块 (失败时保留完整 traceback, 由 render_import_error 显式展示)
IMPORT_ERROR: Optional[str] = None
try:
    from stock_data_fetcher import StockDataFetcher
    from signal_generator import SignalGenerator, generator_from_params
    from optimized_params import load_optimized_params, list_systems
    from chart_visualizer import ChartVisualizer
    from backtest_framework import BacktestEngine, PositionConfig
    from portfolio_manager import PortfolioManager
    from realtime_quote import RealTimeQuoteAPI
    # 统一信号契约 (审计 C #9): web 层消费 Signal, 不再各页面自拼信号字典
    from core.signal import (ACTION_BUY, ACTION_HOLD, ACTION_SELL, Signal)
    from core.indicators import sma as _core_sma
    # 交易日历 (审计 C-P1-12 遗留项: 停牌建模) — 本地指数/缓存, 不联网
    try:
        from core.trading_calendar import ensure_calendar
        ensure_calendar()
    except Exception:
        pass
    MODULES_AVAILABLE = True
except ImportError:
    MODULES_AVAILABLE = False
    IMPORT_ERROR = traceback.format_exc()


def render_import_error():
    """显式错误页: 模块导入失败时展示完整 traceback

    修复审计 F-P1: 旧实现仅 print 一行 Warning 后静默降级,
    5 个页面各自 st.error 一句无诊断价值的提示。

    streamlit 本身缺失时无界面可渲染 → 如实打到 stderr, 不假装成功。
    """
    if st is None:
        print("核心模块导入失败 — 功能不可用 (streamlit 未安装)", file=sys.stderr)
        print(IMPORT_ERROR or "未知导入错误", file=sys.stderr)
        return
    st.error("核心模块导入失败 — 功能不可用")
    st.code(IMPORT_ERROR or "未知导入错误", language="text")
    st.caption(f"skills 目录: {_SKILLS_DIR}")


def render_missing_streamlit():
    """streamlit 未安装: 无法启动界面, 如实报错并给出安装指引"""
    print("=" * 60, file=sys.stderr)
    print("[ERROR] 未安装 streamlit — Web 界面无法启动", file=sys.stderr)
    print("       pip install streamlit", file=sys.stderr)
    print("=" * 60, file=sys.stderr)


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
            # matplotlib 缺失时 ChartVisualizer() 会 raise — 降级为 None,
            # 图表区显示提示而非整页崩溃 (对齐可选依赖守卫模式)
            try:
                st.session_state.visualizer = ChartVisualizer()
            except ImportError:
                st.session_state.visualizer = None
            st.session_state.manager = PortfolioManager()
            # requests 缺失时 RealTimeQuoteAPI() 会 raise — 降级为 None,
            # 实时监控页显示提示而非整页崩溃
            try:
                st.session_state.rt_api = RealTimeQuoteAPI()
            except ImportError:
                st.session_state.rt_api = None
        else:
            st.session_state.fetcher = None
            st.session_state.generator = None
            st.session_state.visualizer = None
            st.session_state.manager = None
            st.session_state.rt_api = None

    if 'watchlist' not in st.session_state:
        st.session_state.watchlist = ['600519', '000858', '002415']

    # 优化参数下发状态 (E-P1 #19): None = 出厂投票制;
    # 加载 best_params.json 后 generator 换实例, 信号面全站跟随
    if 'optimized_params' not in st.session_state:
        st.session_state.optimized_params = None

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

        # 优化参数下发 (审计 E-P1 #19 闭环: best_params.json → 信号层)
        # 加载后 st.session_state.generator 换实例 — 首页/分析页/信号图/
        # 回测多因子四个调用面零改动即跟随
        st.subheader("🎯 优化参数")
        _opt_params = st.session_state.optimized_params
        if _opt_params:
            _mode = ("加权评分" if _opt_params.get('use_weighted_scoring')
                     else "投票制")
            st.caption(f"已加载 {len(_opt_params)} 键 · {_mode}")
            if st.button("清除 (回出厂投票制)", key="sidebar_params_clear"):
                st.session_state.optimized_params = None
                st.session_state.generator = SignalGenerator()
                st.rerun()

        params_path = st.text_input(
            "结果文件", value="stock_data/optimization_result.json",
            key="sidebar_params_path",
            help="OptimizationEngine save_results 落盘的 best_params JSON")

        systems = []
        if params_path:
            try:
                systems = list_systems(params_path)
            except FileNotFoundError:
                st.caption("文件不存在 — 先运行优化器产出结果")
            except Exception as e:
                st.caption(f"结果文件读取失败: {e}")

        regime_options = None
        regime_choice = None
        if systems:
            regime_options = ["自动 (全局优先)"] + [
                f"{s['regime'] or 'GLOBAL'} · {s['name']}" for s in systems]
            regime_choice = st.selectbox(
                "体制系统", regime_options, key="sidebar_params_regime",
                help="多体制结果需显式选择; 自动=全局系统优先")
        else:
            st.caption("检测到结果文件后可选择体制系统")

        if systems and st.button("⬇️ 加载参数", key="sidebar_params_load"):
            idx = (regime_options.index(regime_choice) - 1
                   if regime_choice and regime_choice != "自动 (全局优先)"
                   else -1)
            regime = None if idx < 0 else systems[idx]['regime']
            try:
                params = load_optimized_params(params_path, regime=regime)
            except ValueError as e:
                st.error(str(e))
            else:
                st.session_state.optimized_params = params
                st.session_state.generator = generator_from_params(params)
                _mode = ("加权评分" if params.get('use_weighted_scoring')
                         else "投票制")
                st.success(f"已加载 {len(params)} 键 · {_mode} — 信号即刻生效")
                st.rerun()

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

    # (审计 #18 S1: 旧版 4 个指标里 3 个硬编码假数据 —
    #  ¥1,000,000/+23.5%/信号5/收益+15.3% 凭空捏造;
    #  现全部来自 watchlist 真实信号 + 组合管理器真实持仓)
    signals = get_all_signals(st.session_state.watchlist)
    buy_count = sum(1 for s in signals if s.action == ACTION_BUY)
    sell_count = sum(1 for s in signals if s.action == ACTION_SELL)

    manager = st.session_state.manager
    total_value = sum(p.total_value for p in manager.portfolios.values())
    total_pnl_pct = 0.0
    if manager.portfolios:
        total_initial = sum(p.initial_cash for p in manager.portfolios.values())
        if total_initial > 0:
            total_pnl_pct = (total_value / total_initial - 1) * 100

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label="📈 今日关注",
            value=len(st.session_state.watchlist),
            delta="只股票"
        )

    with col2:
        st.metric(
            label="💰 组合总资产",
            value=f"¥{total_value:,.2f}",
            delta=f"{len(manager.portfolios)} 个组合"
        )

    with col3:
        st.metric(
            label="🎯 买入信号",
            value=buy_count,
            delta=f"{sell_count} 个卖出"
        )

    with col4:
        st.metric(
            label="📊 组合收益",
            value=f"{total_pnl_pct:+.2f}%" if manager.portfolios else "—",
            delta=None if not manager.portfolios else "vs 初始资金"
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

                # 获取信号 (统一契约)
                signal = get_stock_signal(symbol)
                signal_text = ("买入" if signal.action == ACTION_BUY else
                               "卖出" if signal.action == ACTION_SELL else "中性")
                signal_class = ("signal-buy" if signal.action == ACTION_BUY else
                                "signal-sell" if signal.action == ACTION_SELL else "")

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

    if signals:
        buy_signals = [s for s in signals if s.action == ACTION_BUY]
        sell_signals = [s for s in signals if s.action == ACTION_SELL]

        col1, col2 = st.columns(2)

        with col1:
            st.write("**买入信号**")
            for signal in buy_signals[:5]:
                st.success(f"{signal.symbol}: 强度 {signal.strength:+.1f}")

        with col2:
            st.write("**卖出信号**")
            for signal in sell_signals[:5]:
                st.error(f"{signal.symbol}: 强度 {signal.strength:+.1f}")


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
        if signal.action == ACTION_BUY:
            st.success("**买入信号** ✅")
        elif signal.action == ACTION_SELL:
            st.error("**卖出信号** ✅")
        else:
            st.info("**观望** ⚪")

    with col2:
        st.metric("信号强度", f"{signal.strength:+.1f}")

    with col3:
        st.write("**建议**")
        if signal.strength > 5:
            st.write("🟢 积极买入")
        elif signal.strength > 2:
            st.write("🟡 考虑买入")
        elif signal.strength > -2:
            st.write("⚪ 观望")
        elif signal.strength > -5:
            st.write("🟡 考虑卖出")
        else:
            st.write("🔴 积极卖出")

    st.divider()

    # K线图
    st.subheader("📈 K线图表")

    chart_type = st.selectbox(
        "图表类型",
        ["K线图", "MACD", "RSI", "布林带", "综合分析", "信号图"],
        key="analysis_chart_type"
    )

    # (审计 #19: 旧版在此内联重写 4 种 matplotlib 图表 95 行,
    #  与 chart_visualizer 完全重复且实例化后从未调用 —
    #  现全部委托 session_state.visualizer, 输出图片后 st.image 展示)
    viz = st.session_state.visualizer
    if viz is None:
        st.warning("matplotlib 未安装，图表功能不可用（pip install matplotlib）")
        return

    try:
        if chart_type == "K线图":
            path = viz.plot_candlestick(
                data, symbol=symbol, ma_periods=[5, 20, 60])
            st.image(path, **st_fill_width(st.image))

        elif chart_type == "MACD":
            path = viz.plot_macd(data, symbol=symbol)
            st.image(path, **st_fill_width(st.image))

        elif chart_type == "RSI":
            path = viz.plot_rsi(data, symbol=symbol)
            st.image(path, **st_fill_width(st.image))

        elif chart_type == "布林带":
            path = viz.plot_bollinger_bands(data, symbol=symbol)
            st.image(path, **st_fill_width(st.image))

        elif chart_type == "综合分析":
            path = viz.plot_combined_analysis(data, symbol=symbol)
            st.image(path, **st_fill_width(st.image))

        elif chart_type == "信号图":
            # (审计 #20: 图表买卖点与回测引擎用同一 generate_signals 产出,
            #  int 0/1 信号列, 不再有独立阈值/映射口径)
            signals_df = st.session_state.generator.generate_signals(data)
            path = viz.plot_signals(data, signals_df, symbol=symbol)
            st.image(path, **st_fill_width(st.image))

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
                    data[f'MA{ma_short}'] = _core_sma(data['收盘'], ma_short)
                    data[f'MA{ma_long}'] = _core_sma(data['收盘'], ma_long)
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

                equity_curve = result.get('equity_curve')
                if equity_curve is not None and len(equity_curve) > 0:
                    if st.session_state.visualizer is not None:
                        # (审计 #19: 委托 chart_visualizer, 替换内联 matplotlib)
                        try:
                            eq_path = st.session_state.visualizer.plot_equity_curve(
                                equity_curve, symbol=symbol)
                            st.image(eq_path, **st_fill_width(st.image))
                        except Exception as e:
                            st.warning(f"图表生成失败: {str(e)}")
                    else:
                        st.info("matplotlib 未安装，无法绘制净值曲线")
                else:
                    st.info("无净值数据")

                # 交易记录
                st.subheader("📋 交易记录")

                trades_df = result.get('trades')
                if trades_df is not None and len(trades_df) > 0:
                    # 显示可用的列
                    display_cols = [col for col in ['date', 'symbol', 'action', 'price', 'shares', 'pnl', 'pnl_pct']
                                   if col in trades_df.columns]
                    st.dataframe(
                        trades_df[display_cols] if display_cols else trades_df,
                        **st_fill_width(st.dataframe)
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

                    st.dataframe(pd.DataFrame(pos_data), **st_fill_width(st.dataframe))
                else:
                    st.info("暂无持仓")

                st.divider()

                # 操作按钮
                # (审计 #18 S4: 旧版三个按钮只弹占位提示, 无真实功能 —
                #  现接 PortfolioManager 真实 API: 等权再平衡建议 /
                #  绩效指标 / 标准报告)
                col1, col2, col3 = st.columns(3)

                with col1:
                    if st.button("🔄 再平衡", key=f"rebalance_{portfolio['id']}"):
                        positions = portfolio_obj.positions if portfolio_obj else {}
                        if not positions:
                            st.info("暂无持仓，无需再平衡")
                        else:
                            equal_w = 1.0 / len(positions)
                            target_weights = {s: equal_w for s in positions}
                            try:
                                adjustments = manager.rebalance(
                                    portfolio['id'], target_weights)
                                if adjustments:
                                    adj_df = pd.DataFrame(
                                        [{'代码': k, '调整股数': v}
                                         for k, v in adjustments.items()])
                                    st.dataframe(adj_df, **st_fill_width(st.dataframe))
                                else:
                                    st.success("当前持仓已接近等权，无需调整")
                            except ValueError as e:
                                st.error(str(e))

                with col2:
                    if st.button("📊 分析", key=f"analyze_{portfolio['id']}"):
                        perf = manager.get_performance(portfolio['id'])
                        if perf:
                            pc1, pc2, pc3 = st.columns(3)
                            pc1.metric("总收益率", f"{perf['total_return']:.2f}%")
                            pc2.metric("现金占比", f"{perf['cash_ratio']:.2f}%")
                            pc3.metric("持仓数", perf['position_count'])
                            if perf['positions']:
                                st.dataframe(
                                    pd.DataFrame(perf['positions']),
                                    **st_fill_width(st.dataframe))

                with col3:
                    if st.button("📄 报告", key=f"report_{portfolio['id']}"):
                        report = manager.generate_report(portfolio['id'])
                        if report:
                            st.code(report, language=None)
                        else:
                            st.info("报告生成失败")

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

    # (审计 #18 S2/S3: 旧版整页是桩 — "开发中" + 硬编码指标 3/12/5/2 +
    #  3 条假监控列表 (600519/000858/002415 固定条件) —
    #  现接 realtime_quote 腾讯接口, 拉 watchlist 真实行情并按涨跌幅告警)
    watchlist = st.session_state.watchlist

    if not watchlist:
        st.info("自选股列表为空，请在侧边栏添加股票")
        return

    rt_api = st.session_state.rt_api
    if rt_api is None:
        st.error("requests 未安装 — 实时行情不可用 (pip install requests)")
        return

    with st.spinner("正在获取实时行情..."):
        quotes = {}
        try:
            quotes = rt_api.get_quotes(watchlist)
        except Exception as e:
            st.error(f"获取实时行情失败: {str(e)}")

    if not quotes:
        st.warning("未能获取任何实时行情（非交易时段或网络异常）")
        return

    # 告警阈值设置
    alert_threshold = st.slider(
        "涨跌幅告警阈值 (%)", 1.0, 20.0, 5.0, 0.5, key="monitor_threshold")

    # 统计指标 (真实数据)
    up_count = sum(1 for q in quotes.values() if q.change_pct > 0)
    down_count = sum(1 for q in quotes.values() if q.change_pct < 0)
    alert_count = sum(1 for q in quotes.values()
                      if abs(q.change_pct) >= alert_threshold)

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("监控股票", len(quotes))
    with col2:
        st.metric("上涨", up_count)
    with col3:
        st.metric("下跌", down_count)
    with col4:
        st.metric("触阈告警", alert_count)

    st.divider()

    # 监控列表 (真实行情)
    st.subheader("监控列表")

    for symbol in watchlist:
        q = quotes.get(symbol)
        with st.container():
            col1, col2, col3, col4, col5 = st.columns([2, 2, 2, 2, 2])

            with col1:
                st.write(f"**{symbol}** {q.name if q else ''}")

            if q is None:
                with col2:
                    st.error("无数据")
            else:
                with col2:
                    st.write(f"¥{q.price:.2f}")

                with col3:
                    st.metric(
                        "涨跌幅", f"{q.change_pct:+.2f}%",
                        delta=f"{q.change:+.2f}",
                        delta_color="normal"
                    )

                with col4:
                    st.write(f"成交量 {q.volume:,.0f} 手")

                with col5:
                    if abs(q.change_pct) >= alert_threshold:
                        st.error(f"⚠️ 触发告警")
                    else:
                        st.success("正常")

        st.divider()


# =============================================================================
# 辅助函数
# =============================================================================

def st_fill_width(func) -> Dict[str, object]:
    """返回"占满容器宽度"的参数 — streamlit 的宽度参数逐版漂移。

    实测 (签名随版本变):
      - 1.37 `st.image` 只有 `width`(int) + `use_column_width`，
        **`use_container_width` 已被移除** → 硬传会 TypeError
        ("ImageMixin.image() got an unexpected keyword argument")
      - 1.40+ `width` 变成 'stretch'/'content'/int, `use_container_width` 弃用
      - `st.altair_chart` 到 1.66 的 `width` 仍是 int (不能用 'stretch')

    策略: 完全按**运行时签名**判定, 签名里不存在的参数一律不传
    (宁可不铺满, 也不 TypeError)。
    """
    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return {}

    width = params.get('width')
    if width is not None and isinstance(width.default, str):
        # 新 API: width 接受 'stretch' (默认值是字符串)
        return {'width': 'stretch'}
    if 'use_container_width' in params:
        return {'use_container_width': True}
    if 'use_column_width' in params:
        return {'use_column_width': True}
    return {}


_STOCK_NAME_CACHE: Optional[Dict[str, str]] = None


def _load_stock_names() -> Dict[str, str]:
    """懒加载 stock_list.csv (5523 只) → {代码: 名称}, 模块级缓存"""
    global _STOCK_NAME_CACHE
    if _STOCK_NAME_CACHE is None:
        names: Dict[str, str] = {}
        csv_path = os.path.join(_SKILLS_DIR, 'stock_list.csv')
        try:
            df = pd.read_csv(csv_path, dtype={'code': str})
            names = dict(zip(df['code'].str.zfill(6), df['name']))
        except Exception:
            names = {}
        _STOCK_NAME_CACHE = names
    return _STOCK_NAME_CACHE


def get_stock_name(symbol: str) -> str:
    """获取股票名称 (审计 #18: 替换硬编码 10 只 → stock_list.csv 全量)"""
    return _load_stock_names().get(str(symbol).zfill(6), symbol)


def get_stock_data(symbol: str, days: int = 120) -> Optional[pd.DataFrame]:
    """获取股票数据（带缓存）"""
    cache_key = f"{symbol}_{days}"

    # 检查缓存
    if cache_key in st.session_state.data_cache:
        return st.session_state.data_cache[cache_key]

    # 获取数据
    if st.session_state.fetcher:
        try:
            result = st.session_state.fetcher.get_quote_result(symbol, days=days)
            if result.ok and len(result.data) > 0:
                st.session_state.data_cache[cache_key] = result.data
                return result.data
            st.error(f"获取 {symbol} 数据失败: {result.error or '无数据'}")
        except Exception as e:
            st.error(f"获取数据失败: {str(e)}")

    return None


def get_stock_signal(symbol: str) -> Signal:
    """获取股票信号 (统一契约 Signal, 审计 C #9).

    数据不可用时返回 HOLD 的空契约 (executable=True, 无阻断原因)。
    """
    try:
        data = get_stock_data(symbol, days=120)
        if data is not None and len(data) > 0:
            data = st.session_state.fetcher.calculate_technical_indicators(data)
            return st.session_state.generator.to_signal(data, symbol=symbol)
    except Exception:
        pass

    return Signal(symbol=symbol, signal_date='', action=ACTION_HOLD,
                  strength=0.0, source='web_app')


def get_all_signals(symbols: List[str]) -> List[Signal]:
    """获取所有股票的信号 (统一契约 Signal 列表)"""
    signals = []

    for symbol in symbols:
        signals.append(get_stock_signal(symbol))

    # 按强度排序
    signals.sort(key=lambda x: abs(x.strength), reverse=True)

    return signals


# =============================================================================
# 主应用
# =============================================================================

def main():
    """主应用入口"""
    # streamlit 缺失 → 无界面可渲染, 如实报错退出 (不硬崩, 不假装启动成功)
    if not STREAMLIT_AVAILABLE:
        render_missing_streamlit()
        return

    # 配置页面
    setup_page_config()

    # 导入失败 → 显式错误页 + 完整 traceback, 不再静默降级 (审计 F-P1)
    if not MODULES_AVAILABLE:
        render_import_error()
        st.stop()
        return

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
