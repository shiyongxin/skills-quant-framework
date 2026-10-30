# -*- coding: utf-8 -*-
"""信号语义诚实性测试 (审计 B10 / C2: shift(1) 保护 + 真交叉 + NaN 诚实).

覆盖:
- technical_analyzer: MACD/KDJ 真交叉 (不把水平状态叫金叉) + NaN 记
  "数据不足" 而非静默无信号 + t+1 执行语义字段
- position_analyzer: 指标不可用时评分不静默当 0 分 (记 score_unavailable) +
  MACD 真交叉标签 (同日金叉冒充修复, B10/L4) + signal_timing 声明
"""
import numpy as np
import pandas as pd


def _mk_ohlcv(n=120, seed=5):
    rng = np.random.default_rng(seed)
    close = 10 * np.cumprod(1 + rng.normal(0, 0.012, n))
    df = pd.DataFrame({
        '日期': pd.bdate_range('2024-01-01', periods=n),
        '开盘': close * (1 + rng.normal(0, 0.002, n)),
        '最高': close * 1.01,
        '最低': close * 0.99,
        '收盘': close,
        '成交量': rng.integers(1e6, 3e6, n).astype(float),
        '成交额': rng.integers(1e7, 3e7, n).astype(float),
    })
    df['涨跌幅'] = df['收盘'].pct_change() * 100
    return df


def _analyzer():
    from technical_analyzer import TechnicalAnalyzer
    return TechnicalAnalyzer()


class TestTechnicalAnalyzerSignalSemantics:
    def test_returns_signals_and_unavailable(self):
        ta = _analyzer()
        df = ta._calculate_indicators(_mk_ohlcv())
        out = ta._analyze_signals(df)
        assert isinstance(out, tuple) and len(out) == 2
        signals, unavailable = out
        assert isinstance(signals, list) and isinstance(unavailable, list)

    def test_kdj_level_state_not_called_cross(self):
        """K>D 的水平状态不得报 'KDJ金叉' (只有真交叉才报)"""
        ta = _analyzer()
        df = ta._calculate_indicators(_mk_ohlcv(n=200, seed=9))
        for cut in (60, 120, 199):
            signals, _ = ta._analyze_signals(df.iloc[:cut + 1].copy())
            k = df['K'].iloc[cut]
            d = df['D'].iloc[cut]
            prev_k = df['K'].iloc[cut - 1]
            prev_d = df['D'].iloc[cut - 1]
            crossed = (k > d and prev_k <= prev_d) or (k < d and prev_k >= prev_d)
            if not crossed:
                assert 'KDJ金叉' not in signals
                assert 'KDJ死叉' not in signals
                if k > d:
                    assert 'KDJ多头(未交叉)' in signals
                else:
                    assert 'KDJ空头(未交叉)' in signals

    def test_kdj_true_cross_detected(self):
        ta = _analyzer()
        df = ta._calculate_indicators(_mk_ohlcv(n=200, seed=9))
        k, d = df['K'], df['D']
        cross_idx = np.flatnonzero(((k > d) & (k.shift(1) <= d.shift(1))).values)
        assert len(cross_idx) > 0
        i = int(cross_idx[-1])
        signals, _ = ta._analyze_signals(df.iloc[:i + 1].copy())
        assert 'KDJ金叉' in signals

    def test_macd_level_state_labelled_explicitly(self):
        ta = _analyzer()
        df = ta._calculate_indicators(_mk_ohlcv(n=200, seed=3))
        macd, sig = df['MACD'], df['MACD_Signal']
        cross_idx = np.flatnonzero(
            ((macd > sig) & (macd.shift(1) <= sig.shift(1))).values)
        i = int(cross_idx[-1])
        signals, _ = ta._analyze_signals(df.iloc[:i + 2].copy())
        # 次根: 非金叉, 水平状态用中性标签
        assert 'MACD金叉' not in signals
        if macd.iloc[i + 1] > sig.iloc[i + 1]:
            assert 'MACD多头(未交叉)' in signals

    def test_nan_indicator_reported_as_unavailable(self):
        """指标 NaN (数据不足) → 记入 unavailable, 不静默当无信号"""
        ta = _analyzer()
        df = ta._calculate_indicators(_mk_ohlcv(n=120, seed=5))
        df.loc[df.index[-1], 'RSI'] = np.nan
        signals, unavailable = ta._analyze_signals(df)
        assert any('RSI' in u for u in unavailable)
        assert 'RSI超买' not in signals
        assert 'RSI超卖' not in signals

    def test_analyze_result_has_t1_timing(self):
        from core.fetch_result import FetchResult

        class _Stub:
            def get_quote_result(self, symbol, days=120, adjust='hfq'):
                return FetchResult(ok=True, data=_mk_ohlcv(n=120),
                                   source='stub')

        ta = _analyzer()
        ta.fetcher = _Stub()
        res = ta.analyze('600519')
        assert res is not None
        assert 't+1' in res['signal_timing']
        assert 'signals_unavailable' in res
        assert isinstance(res['signals_unavailable'], list)

    def test_report_mentions_timing_and_unavailable(self):
        from core.fetch_result import FetchResult

        class _Stub:
            def get_quote_result(self, symbol, days=120, adjust='hfq'):
                return FetchResult(ok=True, data=_mk_ohlcv(n=120),
                                   source='stub')

        ta = _analyzer()
        ta.fetcher = _Stub()
        res = ta.analyze('600519')
        report = ta.generate_report(res)
        assert 't+1' in report


class TestPositionAnalyzerNaNHonesty:
    def test_score_unavailable_reported(self):
        from core.fetch_result import FetchResult
        from position_analyzer import PositionAnalyzer

        df = _mk_ohlcv(n=120, seed=5)

        class _Stub:
            def get_quote_result(self, symbol, days=120, adjust='hfq'):
                return FetchResult(ok=True, data=df.copy(), source='stub')

        pa = PositionAnalyzer(fetcher=_Stub())
        res = pa.analyze_position('600519', shares=100, cost_price=10.0)
        assert res is not None
        assert 'score_unavailable' in res
        assert isinstance(res['score_unavailable'], list)

    def test_nan_rsi_marked_unavailable(self):
        """指标 NaN → 记入 score_unavailable (不静默当 0 分)"""
        from core.fetch_result import FetchResult
        from position_analyzer import PositionAnalyzer

        df = _mk_ohlcv(n=120, seed=5)

        class _Stub:
            def get_quote_result(self, symbol, days=120, adjust='hfq'):
                return FetchResult(ok=True, data=df.copy(), source='stub')

        pa = PositionAnalyzer(fetcher=_Stub())
        data = pa.get_stock_data('600519', days=120)
        assert data is not None
        data = data.copy()
        data.loc[data.index[-1], 'RSI'] = np.nan
        pa._last_score_unavailable = []
        pa._calculate_score(data, data.iloc[-1])
        assert any('RSI' in u for u in pa._last_score_unavailable)


class TestPositionAnalyzerMacdCross:
    """MACD 真交叉标签 + t+1 声明 (审计 B10/L4: 同日金叉冒充修复).

    旧实现 `latest['MACD'] > latest['MACD_Signal']` 是水平比较 ——
    多头状态连续多日全部标"金叉"; 新实现与 technical_analyzer 同源:
    只有当根发生穿越才叫金叉, 水平状态报"多头(未交叉)".
    """

    def _data_with_indicators(self, n=200, seed=3):
        from core.fetch_result import FetchResult
        from position_analyzer import PositionAnalyzer

        df = _mk_ohlcv(n=n, seed=seed)

        class _Stub:
            def get_quote_result(self, symbol, days=120, adjust='hfq'):
                return FetchResult(ok=True, data=df.copy(), source='stub')

        pa = PositionAnalyzer(fetcher=_Stub())
        data = pa.get_stock_data('600519', days=n)
        assert data is not None
        return pa, data

    def test_level_state_not_called_golden_cross(self):
        """水平多头 (末两根同在信号线上方) 不得标'金叉'"""
        pa, data = self._data_with_indicators()
        macd, sig = data['MACD'], data['MACD_Signal']
        # 找一个非交叉的多头末根
        for cut in range(len(data) - 1, 60, -1):
            w = data.iloc[:cut + 1]
            if (pd.notna(macd.iloc[cut]) and pd.notna(sig.iloc[cut])
                    and macd.iloc[cut] > sig.iloc[cut]
                    and macd.iloc[cut - 1] > sig.iloc[cut - 1]):
                label = pa._macd_cross_label(w)
                assert label == '多头(未交叉)', label
                return
        raise AssertionError("构造数据中未找到非交叉多头末根 (换 seed)")

    def test_true_cross_labelled_golden_cross(self):
        pa, data = self._data_with_indicators()
        macd, sig = data['MACD'], data['MACD_Signal']
        cross_idx = np.flatnonzero(
            ((macd > sig) & (macd.shift(1) <= sig.shift(1))).values)
        assert len(cross_idx) > 0, "构造数据中应存在 MACD 金叉"
        i = int(cross_idx[-1])
        label = pa._macd_cross_label(data.iloc[:i + 1])
        assert label == '金叉'

    def test_nan_last_bar_reported_insufficient(self):
        pa, data = self._data_with_indicators()
        data = data.copy()
        data.loc[data.index[-1], 'MACD'] = np.nan
        assert pa._macd_cross_label(data) == '数据不足'

    def test_analyze_result_declares_t1(self):
        """结果带 signal_timing 声明 (advisory, 不是可成交指令)"""
        from core.fetch_result import FetchResult
        from position_analyzer import PositionAnalyzer

        df = _mk_ohlcv(n=120, seed=5)

        class _Stub:
            def get_quote_result(self, symbol, days=120, adjust='hfq'):
                return FetchResult(ok=True, data=df.copy(), source='stub')

        pa = PositionAnalyzer(fetcher=_Stub())
        res = pa.analyze_position('600519', shares=100, cost_price=10.0)
        assert res is not None
        assert 't+1' in res['signal_timing']
        report = pa.format_report(res)
        assert 't+1' in report
