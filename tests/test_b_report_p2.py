# -*- coding: utf-8 -*-
"""
B-report P2 批次回归 (路线图 #9-13):
- position_analyzer days 参数透传 (审计 B-P1: 静默失效修复)
- pattern_recognition price_position 取"价格下方最近支撑/上方最近压力" (B-P2)
- 列名契约: technical_analyzer/position_analyzer 产出 EMA20 + MACD_Hist (B-C7)
- advanced_indicators.obv 向量化与参考循环语义一致 (B-P2)
- scan_all_patterns 向量化与逐条形态函数语义一致 + 形态函数 dict 返回统一
"""
import numpy as np
import pandas as pd
import pytest

from pattern_recognition import CandlestickPatterns, PricePatterns
from position_analyzer import PositionAnalyzer
import position_analyzer as position_analyzer_mod
from technical_analyzer import TechnicalAnalyzer
from advanced_indicators import AdvancedIndicators
from core.fetch_result import FetchResult


def mk_ohlcv(n=100, seed=7, start_price=50.0, last_close=None):
    rng = np.random.default_rng(seed)
    rets = rng.normal(0, 0.02, n)
    close = start_price * np.cumprod(1 + rets)
    open_ = np.concatenate(([start_price], close[:-1])) * (1 + rng.normal(0, 0.005, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, n)))
    volume = rng.integers(1_000_000, 5_000_000, n).astype(float)
    if last_close is not None:
        close = close.copy()
        close[-1] = last_close
    idx = pd.date_range('2024-01-01', periods=n, freq='B')
    return pd.DataFrame({
        '开盘': open_, '收盘': close, '最高': high, '最低': low,
        '成交量': volume,
    }, index=idx)


class _CapturingFetcher:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def get_quote_result(self, symbol, days=120, adjust='hfq'):
        self.calls.append({'symbol': symbol, 'days': days})
        return FetchResult.success(self.data.copy(), source='test')


class TestPositionAnalyzerDays:
    def test_analyze_position_passes_days_to_fetcher(self):
        df = mk_ohlcv(80)
        fetcher = _CapturingFetcher(df)
        analyzer = PositionAnalyzer(fetcher=fetcher)
        result = analyzer.analyze_position('000001', 100, 40.0, days=90)
        assert result is not None
        assert fetcher.calls[-1]['days'] == 90

    def test_convenience_function_passes_days(self, monkeypatch):
        captured = {}

        class FakeAnalyzer:
            def analyze_position(self, symbol, shares, cost_price,
                                 stock_name=None, days=120):
                captured['days'] = days
                return {'symbol': symbol}

        monkeypatch.setattr(position_analyzer_mod, 'PositionAnalyzer', FakeAnalyzer)
        out = position_analyzer_mod.analyze_position('000001', 100, 10.0, days=45)
        assert captured['days'] == 45
        assert out == {'symbol': '000001'}

    def test_default_days_still_120(self):
        df = mk_ohlcv(80)
        fetcher = _CapturingFetcher(df)
        analyzer = PositionAnalyzer(fetcher=fetcher)
        analyzer.analyze_position('000001', 100, 40.0)
        assert fetcher.calls[-1]['days'] == 120


class TestPricePositionSemantics:
    def test_picks_below_support_and_above_resistance(self, monkeypatch):
        # 价格 138: 支撑列表含已跌破位 145, 压力列表含已突破位 130
        df = mk_ohlcv(80, seed=3, last_close=138.0)
        monkeypatch.setattr(
            PricePatterns, 'detect_support_level',
            staticmethod(lambda df, **kw: [145.0, 120.0, 100.0]))
        monkeypatch.setattr(
            PricePatterns, 'detect_resistance_level',
            staticmethod(lambda df, **kw: [130.0, 150.0, 160.0]))

        res = PricePatterns.analyze_patterns(df)
        pp = res['price_position']
        # 旧实现: vs_support 用 145 (价格上方), vs_resistance 用 130 → 荒谬负值
        assert pp['nearest_support'] == 120.0
        assert pp['nearest_resistance'] == 150.0
        assert pp['vs_support'] == pytest.approx((138.0 - 120.0) / 120.0 * 100)
        assert pp['vs_resistance'] == pytest.approx((150.0 - 138.0) / 150.0 * 100)
        assert pp['vs_resistance'] > 0
        assert pp['vs_support'] > 0

    def test_all_supports_above_price_gives_none(self, monkeypatch):
        df = mk_ohlcv(80, seed=3, last_close=90.0)
        monkeypatch.setattr(
            PricePatterns, 'detect_support_level',
            staticmethod(lambda df, **kw: [145.0, 140.0]))
        monkeypatch.setattr(
            PricePatterns, 'detect_resistance_level',
            staticmethod(lambda df, **kw: [150.0]))

        pp = PricePatterns.analyze_patterns(df)['price_position']
        assert pp['nearest_support'] is None
        assert pp['vs_support'] is None
        assert pp['nearest_resistance'] == 150.0


class TestColumnContract:
    def test_technical_analyzer_produces_ema20_and_macd_hist(self):
        df = mk_ohlcv(80)
        out = TechnicalAnalyzer(fetcher=_CapturingFetcher(df))._calculate_indicators(df.copy())
        assert 'EMA20' in out.columns
        assert 'EMA_20' in out.columns  # 向后兼容别名
        assert np.allclose(out['EMA20'], out['EMA_20'])
        assert 'MACD_Hist' in out.columns
        assert np.allclose(out['MACD_Hist'], out['MACD'] - out['MACD_Signal'])

    def test_position_analyzer_produces_macd_hist(self):
        df = mk_ohlcv(80)
        data = PositionAnalyzer(fetcher=_CapturingFetcher(df)).get_stock_data('000001')
        assert 'MACD_Hist' in data.columns
        assert 'EMA20' in data.columns
        assert np.allclose(data['MACD_Hist'], data['MACD'] - data['MACD_Signal'])


class TestObvVectorization:
    def test_matches_reference_loop(self):
        df = mk_ohlcv(60, seed=11)
        out = AdvancedIndicators.obv(df)

        ref = [float(df['成交量'].iloc[0])]
        for i in range(1, len(df)):
            c_now, c_prev = df['收盘'].iloc[i], df['收盘'].iloc[i - 1]
            v = float(df['成交量'].iloc[i])
            if c_now > c_prev:
                ref.append(ref[-1] + v)
            elif c_now < c_prev:
                ref.append(ref[-1] - v)
            else:
                ref.append(ref[-1])

        assert np.allclose(out['OBV'].to_numpy(dtype=float), np.array(ref))

    def test_flat_price_keeps_obv_constant(self):
        df = mk_ohlcv(20, seed=5)
        df['收盘'] = 10.0
        out = AdvancedIndicators.obv(df)
        assert np.allclose(out['OBV'].to_numpy(), out['成交量'].iloc[0])


class TestScanAllPatternsVectorized:
    def _inject_known_patterns(self, df):
        df = df.copy()
        n = len(df)
        # 十字星 @30
        df.iloc[30, df.columns.get_loc('开盘')] = 10.0
        df.iloc[30, df.columns.get_loc('收盘')] = 10.05
        df.iloc[30, df.columns.get_loc('最高')] = 10.5
        df.iloc[30, df.columns.get_loc('最低')] = 9.5
        # 早晨之星 @50-52
        df.iloc[50, df.columns.get_loc('开盘')] = 20.0
        df.iloc[50, df.columns.get_loc('收盘')] = 18.0   # 大阴线
        df.iloc[50, df.columns.get_loc('最高')] = 20.2
        df.iloc[50, df.columns.get_loc('最低')] = 17.8
        df.iloc[51, df.columns.get_loc('开盘')] = 18.1
        df.iloc[51, df.columns.get_loc('收盘')] = 18.2   # 小实体
        df.iloc[51, df.columns.get_loc('最高')] = 18.3
        df.iloc[51, df.columns.get_loc('最低')] = 18.0
        df.iloc[52, df.columns.get_loc('开盘')] = 18.3
        df.iloc[52, df.columns.get_loc('收盘')] = 20.0   # 大阳线过中点
        df.iloc[52, df.columns.get_loc('最高')] = 20.2
        df.iloc[52, df.columns.get_loc('最低')] = 18.2
        # 锤子线 @70 (前一根收盘需 >= 今开 → downtrend 分支 → hammer)
        df.iloc[69, df.columns.get_loc('开盘')] = 21.0
        df.iloc[69, df.columns.get_loc('收盘')] = 21.0
        df.iloc[69, df.columns.get_loc('最高')] = 21.2
        df.iloc[69, df.columns.get_loc('最低')] = 20.8
        df.iloc[70, df.columns.get_loc('开盘')] = 20.0
        df.iloc[70, df.columns.get_loc('收盘')] = 20.4
        df.iloc[70, df.columns.get_loc('最高')] = 20.5
        df.iloc[70, df.columns.get_loc('最低')] = 15.0
        # 看涨吞没 @90-91
        df.iloc[90, df.columns.get_loc('开盘')] = 25.0
        df.iloc[90, df.columns.get_loc('收盘')] = 24.0
        df.iloc[90, df.columns.get_loc('最高')] = 25.2
        df.iloc[90, df.columns.get_loc('最低')] = 23.8
        df.iloc[91, df.columns.get_loc('开盘')] = 23.9
        df.iloc[91, df.columns.get_loc('收盘')] = 25.1
        df.iloc[91, df.columns.get_loc('最高')] = 25.3
        df.iloc[91, df.columns.get_loc('最低')] = 23.7
        return df

    def test_vectorized_matches_per_bar_functions(self):
        df = self._inject_known_patterns(mk_ohlcv(120, seed=13))
        out = CandlestickPatterns.scan_all_patterns(df)
        ref_df = df.reset_index(drop=True)

        assert bool(out['Pattern_Doji'].iloc[30])
        assert out['Pattern_MorningStar'].iloc[52]
        assert out['Pattern_Hammer'].iloc[70] is True
        assert out['Pattern_BullishEngulfing'].iloc[91]

        for i in range(len(df)):
            assert bool(out['Pattern_Doji'].iloc[i]) == \
                CandlestickPatterns.is_doji(ref_df, i)['is_doji'], i

            h = CandlestickPatterns.is_hammer(ref_df, i)
            expect_hammer = bool(h['is_hammer'] and h['type'] == 'hammer')
            expect_hanging = bool(h['is_hammer'] and h['type'] == 'hanging_man')
            got_h = out['Pattern_Hammer'].iloc[i] is True
            got_hm = out['Pattern_HangingMan'].iloc[i] is True
            assert got_h == expect_hammer, i
            assert got_hm == expect_hanging, i

            e = CandlestickPatterns.is_engulfing(ref_df, i)
            assert bool(out['Pattern_BullishEngulfing'].iloc[i]) == \
                bool(e['is_engulfing'] and e['type'] == 'bullish'), i
            assert bool(out['Pattern_BearishEngulfing'].iloc[i]) == \
                bool(e['is_engulfing'] and e['type'] == 'bearish'), i

            hm = CandlestickPatterns.is_harami(ref_df, i)
            assert bool(out['Pattern_BullishHarami'].iloc[i]) == \
                bool(hm['is_harami'] and hm['type'] == 'bullish'), i
            assert bool(out['Pattern_BearishHarami'].iloc[i]) == \
                bool(hm['is_harami'] and hm['type'] == 'bearish'), i

            assert bool(out['Pattern_MorningStar'].iloc[i]) == \
                CandlestickPatterns.is_morning_star(ref_df, i)['is_morning_star'], i
            assert bool(out['Pattern_EveningStar'].iloc[i]) == \
                CandlestickPatterns.is_evening_star(ref_df, i)['is_evening_star'], i
            assert bool(out['Pattern_Piercing'].iloc[i]) == \
                CandlestickPatterns.is_piercing(ref_df, i)['is_piercing'], i
            assert bool(out['Pattern_DarkCloud'].iloc[i]) == \
                CandlestickPatterns.is_dark_cloud(ref_df, i)['is_dark_cloud'], i

    def test_preserves_index(self):
        df = mk_ohlcv(30, seed=2)
        df.index = [f'row-{i}' for i in range(len(df))]
        out = CandlestickPatterns.scan_all_patterns(df)
        assert list(out.index) == list(df.index)


class TestPatternFunctionReturnTypes:
    @pytest.mark.parametrize('fn_name,key', [
        ('is_doji', 'is_doji'),
        ('is_morning_star', 'is_morning_star'),
        ('is_evening_star', 'is_evening_star'),
        ('is_piercing', 'is_piercing'),
        ('is_dark_cloud', 'is_dark_cloud'),
    ])
    def test_returns_dict_with_bool(self, fn_name, key):
        df = mk_ohlcv(10, seed=4)
        r = getattr(CandlestickPatterns, fn_name)(df, 5)
        assert isinstance(r, dict)
        assert set(r.keys()) == {key}
        assert isinstance(r[key], bool)
