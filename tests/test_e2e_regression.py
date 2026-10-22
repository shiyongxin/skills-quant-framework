# -*- coding: utf-8 -*-
"""
C-P2-19 端到端回归测试 (7 模块, 合成数据, 全离线)

审计建议 P2-19: 用合成数据跑通 7 个模块 →
1. 断言输出结构 (契约不漂移)
2. 断言无未来列 (点时截断后同一 bar 结果不变)
3. 断言训练/测试无重叠 (ml_predictor)

覆盖模块: signal_generator (S1) / daily_signal_generator (S2) /
multi_factor_selection (S3) / stock_selector (S4) /
long_term_selector (S5) / reversal_detector (S6) / ml_predictor (S7)
"""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from core.fetch_result import FetchResult


def mk_ohlcv(n=120, seed=17, base=10.0):
    rng = np.random.default_rng(seed)
    close = base * np.cumprod(1 + rng.normal(0, 0.01, n))
    return pd.DataFrame({
        '日期': pd.bdate_range('2023-01-02', periods=n),
        '开盘': close * (1 + rng.normal(0, 0.002, n)),
        '最高': close * 1.01,
        '最低': close * 0.99,
        '收盘': close,
        '成交量': rng.integers(1e6, 3e6, n).astype(float),
    })


def mk_indicator_df(n=120, seed=17):
    """含滚动指标的完整输入 (全部因果滚动, 供无未来列测试)"""
    df = mk_ohlcv(n=n, seed=seed)
    c = df['收盘']
    df['MA5'] = c.rolling(5).mean()
    df['MA20'] = c.rolling(20).mean()
    ema12 = c.ewm(span=12).mean()
    ema26 = c.ewm(span=26).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_Signal'] = df['MACD'].ewm(span=9).mean()
    low9 = df['最低'].rolling(9).min()
    high9 = df['最高'].rolling(9).max()
    rsv = (c - low9) / (high9 - low9) * 100
    df['K'] = rsv.ewm(3).mean()
    df['D'] = df['K'].ewm(3).mean()
    diff = c.diff()
    gain = diff.clip(lower=0).ewm(alpha=1 / 14, min_periods=14).mean()
    loss = (-diff.clip(upper=0)).ewm(alpha=1 / 14, min_periods=14).mean()
    df['RSI'] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    df['BB_Middle'] = c.rolling(20).mean()
    std = c.rolling(20).std()
    df['BB_Upper'] = df['BB_Middle'] + 2 * std
    df['BB_Lower'] = df['BB_Middle'] - 2 * std
    df['Vol_MA5'] = df['成交量'].rolling(5).mean()
    return df


def mk_financial(n_stocks=8, seed=3):
    rng = np.random.default_rng(seed)
    codes = [f'{i:06d}.SH' for i in range(1, n_stocks + 1)]
    return pd.DataFrame({
        '市盈率-动态': rng.uniform(5, 40, n_stocks),
        '市净率': rng.uniform(0.5, 8, n_stocks),
        '市销率': rng.uniform(0.5, 10, n_stocks),
        '股息率': rng.uniform(0, 6, n_stocks),
        '营业总收入同比增长': rng.uniform(-20, 60, n_stocks),
        '净利润同比增长': rng.uniform(-30, 80, n_stocks),
        '净资产收益率': rng.uniform(-5, 30, n_stocks),
        '销售毛利率': rng.uniform(5, 70, n_stocks),
        '销售净利率': rng.uniform(-5, 40, n_stocks),
        '总资产净利率': rng.uniform(-3, 20, n_stocks),
        '资产负债率': rng.uniform(10, 80, n_stocks),
        '流动比率': rng.uniform(0.5, 5, n_stocks),
        '速动比率': rng.uniform(0.3, 4, n_stocks),
    }, index=codes)


class _StubFetcher:
    """PositionAnalyzer/StockSelector 数据源: 合成 OHLCV + FetchResult 契约"""
    def __init__(self, df):
        self._df = df

    def get_quote_data(self, symbol, days=120, **k):
        return self._df.copy()

    def get_quote_result(self, symbol, start_date=None, end_date=None, days=120):
        return FetchResult.success(self._df.copy(), source='e2e-stub')


class TestOutputStructure:
    """7 模块输出结构契约 (C-P2-19.1)"""

    def test_s1_signal_generator(self):
        from signal_generator import SignalGenerator
        df = mk_indicator_df()
        out = SignalGenerator().generate_signals(df)
        for col in ('signal_ma_cross', 'signal_macd', 'signal_kdj',
                    'signal_rsi', 'signal_bb', 'signal_volume',
                    'signal_breakout', 'signal_buy', 'signal_sell',
                    'signal_strength'):
            assert col in out.columns, col
        assert len(out) == len(df)

    def test_s2_generate_signal_dict(self):
        from daily_signal_generator import generate_signal
        result = generate_signal(mk_indicator_df(), {})
        assert result is not None
        assert set(result) >= {'buy_score', 'sell_score', 'signal',
                               'strength', 'reasons', 'indicators'}
        assert result['signal'] in ('BUY', 'HOLD', 'SELL')

    def test_s2_generate_for_stock_dataclass(self):
        from daily_signal_generator import DailySignalGenerator
        from daily_signal_generator import StockSignal

        df = mk_indicator_df(n=150)
        gen = DailySignalGenerator.__new__(DailySignalGenerator)
        gen.data_manager = SimpleNamespace(
            load=lambda sym: df.copy(),
            get_stock_name=lambda sym: '测试股票')
        gen.systems = {}
        gen.default_params = {}
        gen._current_regime = 'SIDEWAYS'
        gen.get_params_for_regime = lambda r: {}

        sig = gen.generate_for_stock('000001.SZ', regime='SIDEWAYS')
        assert isinstance(sig, StockSignal)
        assert sig.signal in ('BUY', 'HOLD', 'SELL')
        assert np.isfinite(sig.buy_score) and np.isfinite(sig.sell_score)
        assert np.isfinite(sig.signal_strength)

    def test_s3_mfs_select_stocks(self):
        from multi_factor_selection import MultiFactorSelector
        fin = mk_financial()
        selected = MultiFactorSelector().select_stocks(fin, top_n=3)
        assert isinstance(selected, pd.DataFrame)
        assert len(selected) <= 3
        assert 'Composite_Score' in selected.columns
        assert selected['Composite_Score'].notna().all()

    def test_s4_stock_selector_screen(self):
        from stock_selector import StockSelector
        df = mk_indicator_df(n=80)
        ss = StockSelector(fetcher=_StubFetcher(df))
        results = ss.screen_stocks(['600000', '600001'],
                                   min_score=0, max_count=5)
        assert isinstance(results, list)
        assert len(results) <= 5
        if results:
            assert set(results[0]) >= {'symbol', 'score', 'price',
                                       'change_1d', 'change_5d'}

    def test_s5_long_term_selector(self):
        from long_term_selector import LongTermSelector, StockAnalysis
        lts = LongTermSelector()
        df = mk_indicator_df(n=300, seed=23)
        lts.get_stock_data = lambda code, days=500: df.copy()
        analysis = lts.analyze_stock('600000', '测试')
        assert isinstance(analysis, StockAnalysis)
        assert np.isfinite(analysis.total_score)
        assert analysis.recommendation  # 非空建议

        selected = lts.select_stocks({'600000': '测试', '000001': '测试2'},
                                     top_k=2)
        assert 0 < len(selected) <= 2

    def test_s6_reversal_detector(self):
        from reversal_detector import ReversalDetector, ReversalAlert
        rd = ReversalDetector()
        df = mk_indicator_df(n=200, seed=31)
        rd.get_stock_data = lambda code, days=250: df.copy()
        alert = rd.analyze_reversal('600000', '测试')
        assert isinstance(alert, ReversalAlert)
        assert alert.alert_type in ('BUY', 'SELL', 'WATCH')
        assert np.isfinite(alert.confidence)
        assert 0 <= alert.confidence <= 100

    def test_s7_ml_predictor_train_predict(self):
        pytest.importorskip('sklearn')
        from ml_predictor import MLPredictor
        mp = MLPredictor()
        evaluation = mp.train(mk_ohlcv(n=400, seed=41))
        assert np.isfinite(evaluation.accuracy)
        prediction = mp.predict(mk_ohlcv(n=400, seed=41))
        assert prediction.prediction in ('up', 'down', 'hold')
        assert 0 <= prediction.probability <= 1


class TestPointInTimeTruncation:
    """无未来列: 同一 bar 在全量 vs 截断数据上的结果必须一致 (C-P2-19.2)"""

    def _assert_no_lookahead(self, fn, df, ts=(119, 109, 90)):
        full = fn(df.copy())
        for t in ts:
            if t >= len(df):
                continue
            trunc = fn(df.iloc[: t + 1].copy())
            pd.testing.assert_series_equal(
                full.iloc[t], trunc.iloc[t],
                check_names=False,
                obj=f'bar {t} 在全量与截断数据上不一致 (存在未来函数)')

    def test_signal_generator_signals(self):
        from signal_generator import SignalGenerator
        df = mk_indicator_df(n=130, seed=51)

        def fn(d):
            return SignalGenerator().generate_signals(d)

        self._assert_no_lookahead(fn, df)

    def test_dsg_compute_indicators(self):
        from daily_signal_generator import compute_indicators

        def fn(d):
            return compute_indicators(d, {})

        self._assert_no_lookahead(fn, mk_indicator_df(n=130, seed=52))

    def test_reversal_indicators(self):
        from reversal_backtest import ReversalBacktester

        def fn(d):
            return ReversalBacktester().calculate_indicators(d)

        self._assert_no_lookahead(fn, mk_ohlcv(n=130, seed=53))

    def test_reversal_detector_indicators(self):
        from reversal_detector import ReversalDetector

        def fn(d):
            return ReversalDetector().calculate_indicators(d)

        self._assert_no_lookahead(fn, mk_ohlcv(n=130, seed=54))

    def test_vectorized_indicators(self):
        from vectorized_backtest import VectorizedBacktester
        vt = VectorizedBacktester()

        def fn(d):
            return vt._compute_indicators(d, {})

        self._assert_no_lookahead(fn, mk_ohlcv(n=130, seed=55))


class TestTrainTestNoOverlap:
    """训练/测试无重叠 (C-P2-19.3, e2e 层; 细节由 test_ml_predictor_timeseries 钉住)"""

    def test_ml_predictor_split_e2e(self):
        pytest.importorskip('sklearn')
        from ml_predictor import MLPredictor, _time_series_split

        mp = MLPredictor()
        features, target = mp.prepare_data(mk_ohlcv(n=400, seed=61),
                                           forward_days=5, threshold=0.02)
        tr, te, ytr, yte = _time_series_split(features, target, 0.2)
        assert tr.index.max() < te.index.min()
        assert len(set(tr.index) & set(te.index)) == 0

    def test_train_succeeds_on_trending_data(self):
        pytest.importorskip('sklearn')
        from ml_predictor import MLPredictor

        rng = np.random.default_rng(7)
        n = 400
        close = 100 * np.cumprod(1 + rng.normal(0.001, 0.015, n))
        df = pd.DataFrame({
            '日期': pd.bdate_range('2022-01-03', periods=n),
            '开盘': close, '最高': close * 1.02, '最低': close * 0.98,
            '收盘': close,
            '成交量': rng.integers(1e6, 5e6, n).astype(float),
        })
        evaluation = MLPredictor().train(df)
        assert 0 <= evaluation.accuracy <= 1
        assert evaluation.confusion_matrix is not None
