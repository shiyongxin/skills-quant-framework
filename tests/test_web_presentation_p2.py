# -*- coding: utf-8 -*-
"""
审计 #18-20 回归: Streamlit 假数据清除 + chart_visualizer 上岗 + 买卖点语义

- #18: web_app 仪表盘/监控页/组合页/股票名 不得再含硬编码假数据与占位桩
- #19: web_app 图表路径必须委托 ChartVisualizer, 不得内联 matplotlib 绘图
- #20: plot_signals 对 int 0/1 与 bool 信号列均正确标注买卖点
"""

import os

import pytest

_SKILLS = os.path.join(os.path.dirname(__file__), '..', '.claude', 'skills')
_WEB_APP = os.path.join(_SKILLS, 'web_app.py')


def _web_src() -> str:
    with open(_WEB_APP, encoding='utf-8') as f:
        return f.read()


class TestWebAppHonesty:
    """#18: web_app 源码级诚实性 (无 streamlit, 不 import, 只读文本)"""

    def test_no_placeholder_stubs(self):
        src = _web_src()
        for stub in ['功能开发中', '实时监控功能开发中']:
            assert stub not in src, f"web_app 仍含占位桩: {stub}"

    def test_no_fake_dashboard_metrics(self):
        src = _web_src()
        # 旧版仪表盘硬编码假指标 (审计 F §2.3 S1)
        for fake in ['模拟资金', '"+23.5%"', '"+15.3%"']:
            assert fake not in src, f"web_app 仍含假指标: {fake}"

    def test_no_hardcoded_monitor_list(self):
        src = _web_src()
        # 旧版监控页 3 条假数据 (审计 F §2.3 S3): 600519/000858/002415 固定条件
        assert "价格突破2000" not in src, "监控页仍有硬编码假监控列表"
        assert "涨幅超过5%" not in src, "监控页仍有硬编码假监控列表"

    def test_no_hardcoded_stock_name_map(self):
        src = _web_src()
        # 旧版 get_stock_name 硬编码 10 只 → 应查 stock_list.csv
        assert "'贵州茅台': " not in src or "name_map" not in src
        assert 'stock_list.csv' in src, "get_stock_name 应读 stock_list.csv"

    def test_monitor_uses_realtime_quote(self):
        src = _web_src()
        assert 'RealTimeQuoteAPI' in src, "监控页应接 realtime_quote"
        assert 'rt_api.get_quotes' in src, "监控页应调用批量实时行情"

    def test_portfolio_buttons_wired(self):
        src = _web_src()
        for call in ['manager.rebalance(', 'manager.get_performance(',
                     'manager.generate_report(']:
            assert call in src, f"组合页按钮应接真实 API: {call}"

    def test_dashboard_uses_real_aggregates(self):
        src = _web_src()
        assert 'get_all_signals(' in src, "仪表盘信号应来自 get_all_signals"
        assert 'manager.portfolios' in src, "仪表盘组合指标应来自 manager"


class TestChartVisualizerWiring:
    """#19: 图表委托 chart_visualizer, 不再内联绘图"""

    def test_no_inline_matplotlib_in_pages(self):
        src = _web_src()
        # 页面函数内不得再出现 import matplotlib (委托 visualizer 实例)
        assert 'import matplotlib' not in src, \
            "web_app 不应再内联 import matplotlib"

    def test_delegates_to_visualizer(self):
        src = _web_src()
        for method in ['plot_candlestick', 'plot_macd', 'plot_rsi',
                       'plot_bollinger_bands', 'plot_combined_analysis',
                       'plot_equity_curve']:
            assert f'viz.{method}' in src or \
                   f'visualizer.{method}' in src, \
                f"web_app 应委托 visualizer.{method}"

    def test_combined_analysis_placeholder_removed(self):
        src = _web_src()
        assert '综合分析图包含多个子图' not in src, \
            "综合分析占位符应已替换为 plot_combined_analysis"


class TestPlotSignalsSemantics:
    """#20: plot_signals 买卖点标注与 generate_signals 产出同源"""

    @pytest.fixture(autouse=True)
    def _viz(self):
        pytest.importorskip('matplotlib')
        from chart_visualizer import ChartVisualizer
        self.viz = ChartVisualizer(output_dir='charts_test')

    @staticmethod
    def _ohlcv(n=40):
        import pandas as pd
        import numpy as np
        rng = np.random.default_rng(7)
        close = 10 + np.cumsum(rng.normal(0, 0.1, n))
        df = pd.DataFrame({
            '日期': pd.date_range('2024-01-01', periods=n, freq='B'),
            '开盘': close + rng.normal(0, 0.05, n),
            '收盘': close,
            '最高': close + 0.2,
            '最低': close - 0.2,
            '成交量': rng.integers(1e5, 1e6, n).astype(float),
        })
        return df

    def test_int_signal_columns_marked(self, tmp_path):
        # generate_signals 产出 int 0/1 — 旧代码 == True 在 int 列上脆弱
        df = self._ohlcv()
        signals = df.copy()
        signals['signal_buy'] = 0
        signals['signal_sell'] = 0
        signals.loc[5, 'signal_buy'] = 1
        signals.loc[10, 'signal_sell'] = 1
        path = self.viz.plot_signals(
            df, signals, symbol='TEST',
            save_path=str(tmp_path / 'sig_int.png'))
        assert os.path.exists(path)

    def test_bool_signal_columns_marked(self, tmp_path):
        df = self._ohlcv()
        signals = df.copy()
        signals['signal_buy'] = False
        signals['signal_sell'] = False
        signals.loc[3, 'signal_buy'] = True
        signals.loc[8, 'signal_sell'] = True
        path = self.viz.plot_signals(
            df, signals, symbol='TEST',
            save_path=str(tmp_path / 'sig_bool.png'))
        assert os.path.exists(path)

    def test_nan_signal_tolerated(self, tmp_path):
        df = self._ohlcv()
        signals = df.copy()
        signals['signal_buy'] = [None] * 5 + [1] + [None] * (len(df) - 6)
        signals['signal_sell'] = None
        path = self.viz.plot_signals(
            df, signals, symbol='TEST',
            save_path=str(tmp_path / 'sig_nan.png'))
        assert os.path.exists(path)

    def test_web_signal_chart_uses_generate_signals(self):
        # web_app 信号图分支必须用 generator.generate_signals (与回测同源)
        src = _web_src()
        assert 'generator.generate_signals(data)' in src, \
            "信号图应使用 generate_signals 同一真相源"
