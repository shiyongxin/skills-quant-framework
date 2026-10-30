# -*- coding: utf-8 -*-
"""
批次3回归测试 (审计 P0-3 残余 / P0-7 / 项 19):
- RSI 全仓收口: 8 处新增实现全部改调 core (跨模块同值)
- ATR 全仓收口: Wilder 统一口径; pattern_recognition 单根TR量纲bug修复
- keltner_channel 不再覆写调用方 ATR
- FitnessEvaluator 权重接通 FitnessConfig (w_* 不再死参数)
- 腾讯实时行情: 成交额万元→元, 日期/时间字段语义修正
- get_quote_data_fallback: adjust 默认与主路径对齐, 成交量手→股
- SKILL.md 只描述真实存在的 API
"""
import inspect
import re
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from core.indicators import rsi, atr as core_atr, true_range as core_true_range


def mk_ohlcv(n=80, seed=0, base=10.0):
    rng = np.random.default_rng(seed)
    close = base * np.cumprod(1 + rng.normal(0, 0.01, n))
    return pd.DataFrame({
        '日期': pd.date_range('2024-01-01', periods=n, freq='B'),
        '开盘': close * (1 + rng.normal(0, 0.002, n)),
        '最高': close * 1.01, '最低': close * 0.99, '收盘': close,
        '成交量': rng.integers(1e6, 2e6, n).astype(float),
    })


class TestRsiRemainingSites:
    """8 处残留 RSI 实现 → core"""

    def test_stock_data_fetcher_calculate_technical_indicators(self):
        import stock_data_fetcher as m
        got = m.StockDataFetcher.__new__(m.StockDataFetcher).calculate_technical_indicators(
            mk_ohlcv(seed=5))
        expected = rsi(mk_ohlcv(seed=5)['收盘'], 14)
        assert np.allclose(got['RSI'].values, expected.values, equal_nan=True)

    def test_ml_predictor_features(self):
        from ml_predictor import FeatureEngineer
        df = mk_ohlcv(seed=6)
        got = FeatureEngineer().create_technical_features(df.copy())
        expected = rsi(df['收盘'], 14)
        assert np.allclose(got['rsi'].values, expected.values, equal_nan=True)

    def test_reversal_backtest_indicators(self):
        from reversal_backtest import ReversalBacktester
        df = mk_ohlcv(seed=7)
        got = ReversalBacktester().calculate_indicators(df.copy())
        expected = rsi(df['收盘'], 14)
        assert np.allclose(got['RSI14'].values, expected.values, equal_nan=True)
        assert np.allclose(got['RSI6'].values, rsi(df['收盘'], 6).values, equal_nan=True)

    def test_no_bare_rsi_formulas_left(self):
        # 除 core 外, 不允许再出现裸 gain/loss RSI 公式
        import pathlib
        skills = pathlib.Path(__file__).resolve().parents[1] / '.claude' / 'skills'
        leftover = []
        for f in skills.glob('*.py'):
            text = f.read_text(encoding='utf-8')
            if '100 - (100 / (1 + rs))' in text or '100 - 100 / (1 + rs)' in text:
                leftover.append(f.name)
        assert leftover == [], f"残留本地 RSI 公式: {leftover}"


class TestAtrUnification:
    def test_core_wilder_definition(self):
        df = mk_ohlcv(n=60, seed=8)
        got = core_atr(df['最高'], df['最低'], df['收盘'], 14)
        # 手工 Wilder RMA: alpha=1/14, 首14根NaN (TR自index1起)
        tr = core_true_range(df['最高'], df['最低'], df['收盘'])
        manual = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        assert np.allclose(got.values, manual.values, equal_nan=True)
        assert got.isna().sum() == 13  # index 0..12 (TR 首根 skipna 有效)

    def test_advanced_indicators_matches_core(self):
        from advanced_indicators import AdvancedIndicators
        df = mk_ohlcv(seed=9)
        got = AdvancedIndicators.atr(df.copy(), 14)['ATR']
        expected = core_atr(df['最高'], df['最低'], df['收盘'], 14)
        assert np.allclose(got.values, expected.values, equal_nan=True)

    def test_keltner_does_not_overwrite_atr(self):
        from advanced_indicators import AdvancedIndicators
        df = mk_ohlcv(seed=10)
        df['ATR'] = 123.456  # 调用方已按自己周期算好
        out = AdvancedIndicators.keltner_channel(df.copy(), period=20, multiplier=2)
        assert out['ATR'].iloc[-1] == 123.456

    def test_backtest_engine_atr_matches_core(self):
        from backtest_framework import BacktestEngine
        df = mk_ohlcv(seed=11)
        got = BacktestEngine.__new__(BacktestEngine)._calculate_atr(df.copy(), 14)
        expected = core_atr(df['最高'], df['最低'], df['收盘'], 14)
        assert np.allclose(got['ATR'].values, expected.values, equal_nan=True)

    def test_position_analyzer_atr_matches_core(self):
        from position_analyzer import PositionAnalyzer
        df = mk_ohlcv(n=80, seed=12)

        class _StubFetcher:
            def get_quote_data(self, symbol, days=120):
                return df.copy()

            def get_quote_result(self, symbol, start_date=None, end_date=None, days=120, adjust='hfq'):
                from core.fetch_result import FetchResult
                return FetchResult.success(df.copy(), source='test')

        got = PositionAnalyzer(fetcher=_StubFetcher()).get_stock_data('600519')
        expected = core_atr(df['最高'], df['最低'], df['收盘'], 14)
        assert np.allclose(got['ATR'].values, expected.values, equal_nan=True)

    def test_daily_signal_generator_atr_matches_core(self):
        from daily_signal_generator import compute_indicators
        df = mk_ohlcv(seed=13)
        got = compute_indicators(df.copy(), {})['ATR']
        expected = core_atr(df['最高'], df['最低'], df['收盘'], 14)
        assert np.allclose(got.values, expected.values, equal_nan=True)

    def test_reversal_detector_atr_matches_core(self):
        from reversal_detector import ReversalDetector
        df = mk_ohlcv(seed=14)
        got = ReversalDetector().calculate_indicators(df.copy())['ATR']
        expected = core_atr(df['最高'], df['最低'], df['收盘'], 14)
        assert np.allclose(got.values, expected.values, equal_nan=True)

    def test_breakout_strength_uses_real_atr(self):
        from pattern_recognition import PricePatterns
        n = 60
        close = np.linspace(10, 12, n)
        close[-1] = close[-2] * 1.05  # 末根大涨, 突破前20根高点
        df = pd.DataFrame({
            '日期': pd.date_range('2024-01-01', periods=n, freq='B'),
            '开盘': close * 0.999, '最高': close * 1.005,
            '最低': close * 0.995, '收盘': close,
            '成交量': np.full(n, 1e6),
        })
        res = PricePatterns.detect_breakout(df, period=20, threshold=1.5)
        assert res['breakout'] and res['direction'] == 'up'
        # 手工: strength 应基于多bar Wilder ATR, 而非单根 TR
        expected_atr = core_atr(df['最高'], df['最低'], df['收盘'], 14).iloc[-1]
        prev_high = df['最高'].iloc[-21:-1].max()
        expected_strength = (df['收盘'].iloc[-1] - prev_high) / expected_atr
        assert res['strength'] == pytest.approx(expected_strength, rel=1e-9)
        # 旧bug (单根TR) 数值不同 — 且此处两值必须有差异才能证明改动生效
        old_atr = (df['最高'].iloc[-1] - df['最低'].iloc[-1])
        if old_atr != expected_atr:
            assert res['strength'] != pytest.approx(
                (df['收盘'].iloc[-1] - prev_high) / old_atr)


class TestFitnessWeights:
    def _metrics(self, rets, sharpes=None, dds=None):
        n = len(rets)
        return [SimpleNamespace(
            total_return=r,
            sharpe_ratio=(sharpes[i] if sharpes else 0.5),
            max_drawdown=(dds[i] if dds else 10.0),
            win_rate=50.0, num_trades=10, avg_holding_days=5.0,
        ) for i, r in enumerate(rets)]

    def test_default_weights_equal_old_hardcoded(self):
        from optimization_engine import FitnessEvaluator
        ev = FitnessEvaluator()
        assert ev.weights == {'target_rate': 0.40, 'return': 0.25,
                              'sharpe': 0.20, 'drawdown': 0.15}
        assert ev.target_return == 10.0
        assert ev.max_drawdown_limit == 25.0

    def test_target_probability_dead_field_removed(self):
        """审计 M2: target_probability 是死配置 (存入 self 从不使用) → 已删。

        若将来接入机会约束型适应度, 应恢复字段并同时接入 _compute_fitness,
        届时本门禁需同步更新 —— 不允许再出现"接收/存储/校验/落盘俱全、
        唯独不参与计算"的字段。
        """
        import dataclasses
        from optimization_config import FitnessConfig, OptimizationConfig
        from optimization_engine import FitnessEvaluator
        names = {f.name for f in dataclasses.fields(FitnessConfig)}
        assert 'target_probability' not in names
        assert not hasattr(FitnessEvaluator(), 'target_probability')
        # 存量 JSON 兼容: 旧版配置文件带该键 → 过滤后仍可加载 (WARN 提示)
        loaded = OptimizationConfig._from_dict(
            {'fitness': {'target_return': 12.0, 'target_probability': 0.9}})
        assert loaded.fitness.target_return == 12.0

    def test_config_weights_drive_fitness(self):
        from optimization_engine import FitnessEvaluator
        from optimization_config import FitnessConfig
        metrics = self._metrics([20.0, 20.0])

        cfg = FitnessConfig(w_target_rate=1.0, w_return=0.0,
                            w_sharpe=0.0, w_drawdown=0.0)
        ev = FitnessEvaluator(fitness_config=cfg)
        fitness, details = ev._compute_fitness(metrics)
        # 只剩达标率项 (20% > 10% 目标 → 达标率1.0), 无交易惩罚 (10笔)
        assert fitness == pytest.approx(1.0)

        cfg2 = FitnessConfig(w_target_rate=0.0, w_return=0.0,
                             w_sharpe=0.0, w_drawdown=1.0)
        ev2 = FitnessEvaluator(fitness_config=cfg2)
        f2, d2 = ev2._compute_fitness(metrics)
        # 只剩回撤分: dd=10, limit=25 → 1-10/25=0.6
        assert f2 == pytest.approx(0.6)

    def test_legacy_kwargs_override_config(self):
        from optimization_engine import FitnessEvaluator
        from optimization_config import FitnessConfig
        ev = FitnessEvaluator(target_return=5.0,
                              fitness_config=FitnessConfig(target_return=99.0))
        assert ev.target_return == 5.0


class TestRealtimeQuoteParsing:
    def test_amount_in_yuan_and_datetime_fields(self, monkeypatch):
        import stock_data_fetcher as m

        parts = [''] * 41
        parts[1] = '贵州茅台'
        parts[3] = '1700.00'
        parts[4] = '1690.00'
        parts[5] = '1695.00'
        parts[30] = '20240102150405'
        parts[31] = '10.00'
        parts[33] = '1710.00'
        parts[34] = '1680.00'
        parts[36] = '12345'
        parts[37] = '6789.5'  # 万元

        class _Resp:
            status_code = 200
            encoding = 'gbk'
            text = 'v_sh600519="' + '~'.join(parts) + '";'

        monkeypatch.setattr('requests.get', lambda *a, **k: _Resp())

        fetcher = m.StockDataFetcher.__new__(m.StockDataFetcher)
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            result = fetcher.get_realtime_quote('600519')

        assert result['成交额'] == pytest.approx(6789.5 * 10000)  # 万元→元 (审计R10)
        assert result['日期'] == '20240102'
        assert result['时间'] == '150405'  # 旧bug: 时间=parts[31](涨跌)
        assert result['最高'] == 1710.0
        assert result['涨跌'] == pytest.approx(10.0)


class TestFallbackAlignment:
    def test_default_adjust_matches_main_path(self):
        from core.fetch_result import DEFAULT_ADJUST
        import stock_data_fetcher as m
        sig = inspect.signature(m.StockDataFetcher.get_quote_data_fallback)
        assert sig.parameters['adjust'].default == DEFAULT_ADJUST
        main = inspect.signature(m.StockDataFetcher.get_quote_data)
        assert main.parameters['adjust'].default == DEFAULT_ADJUST, \
            '主路径与回退路径口径必须一致 (审计 R4)'

    def test_volume_converted_to_shares(self, monkeypatch):
        import stock_data_fetcher as m
        hist = pd.DataFrame({
            '日期': ['2024-01-02'], '开盘': [10.0], '收盘': [10.2],
            '最高': [10.5], '最低': [9.9], '成交量': [100.0],  # 手
            '成交额': [1.0e6],
        })
        monkeypatch.setattr(m.ak, 'stock_zh_a_hist',
                            lambda **k: hist.copy())
        fetcher = m.StockDataFetcher.__new__(m.StockDataFetcher)
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            got = fetcher.get_quote_data_fallback('600519', '20240101', '20240103')
        assert got['成交量'].iloc[0] == 10000.0  # 手→股 (×100, 审计R4)


class TestSkillMdHonesty:
    @staticmethod
    def _skill_text():
        import pathlib
        p = pathlib.Path(__file__).resolve().parents[1] / '.claude' / 'skills' / 'SKILL.md'
        return p.read_text(encoding='utf-8')

    def test_all_documented_calls_exist(self):
        from chart_visualizer import ChartVisualizer
        text = self._skill_text()
        methods = set(re.findall(r'visualizer\.(plot_\w+)', text))
        methods |= set(re.findall(r'(?<!\.)\b(plot_stock_chart)\b', text))
        assert methods, "SKILL.md 应至少引用一个绘图方法"
        from chart_visualizer import plot_stock_chart  # noqa: F401
        for name in methods:
            if name == 'plot_stock_chart':
                continue
            assert hasattr(ChartVisualizer, name), f"SKILL.md 引用了不存在的 {name}"

    def test_forbidden_fiction_removed(self):
        text = self._skill_text()
        for fiction in ['plot_kdj', 'plot_comparison', 'references/chart_types.md',
                        "style='dark'", 'equity_data=']:
            assert fiction not in text, f"SKILL.md 仍含虚构/错误项: {fiction}"

    def test_real_apis_are_documented(self):
        text = self._skill_text()
        for real in ['plot_rsi', 'plot_bollinger_bands', 'plot_drawdown',
                     'plot_signals', 'plot_combined_analysis', 'plot_equity_curve']:
            assert real in text, f"SKILL.md 漏掉真实 API: {real}"
