# -*- coding: utf-8 -*-
"""
Stage 2 回归测试（commit 34e6a41 批次修复）:
- market_regime_classifier: get_regime_for_dates 反向 idxmax（取最近交易日）
- advanced_indicators: keltner_channel 外部 ATR 守卫（不覆写）
- database_manager: save_position 运算优先级 (current_price or avg_cost) - avg_cost
- concurrent_fetcher: 拆分 import 守卫（fetcher 失败不级联 CacheManager NameError）
- signal_generator: 趋势档 0.5/-0.5 语义、向量化量价、pandas>=3 可执行
- strategy_optimizer: evaluate_params 真实回测（非 -999 哨兵）
- multi_factor_selection: 横截面动量/波动率因子
"""
import importlib
import sys
from contextlib import contextmanager
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest


class TestMarketRegimeIdxmax:
    @staticmethod
    def _mrc():
        from market_regime_classifier import MarketRegimeClassifier
        m = MarketRegimeClassifier()
        m.index_data = pd.DataFrame({'日期': pd.to_datetime(
            ['2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05'])})
        m.regime_series = pd.Series(['BULL', 'BEAR', 'SIDEWAYS', 'CRASH'])
        return m

    def test_uses_last_trading_day_not_first(self):
        m = self._mrc()
        q = pd.DatetimeIndex(['2024-01-01', '2024-01-03',
                              '2024-01-03 12:00', '2024-01-10'])
        out = m.get_regime_for_dates(q)
        # 旧 bug mask.idxmax() 取首个 True: 01-03 会返回 01-02 的 BULL
        assert out.tolist() == ['SIDEWAYS', 'BEAR', 'BEAR', 'CRASH']

    def test_missing_regime_series_raises(self):
        from market_regime_classifier import MarketRegimeClassifier
        m = MarketRegimeClassifier()
        m.index_data = pd.DataFrame({'日期': pd.to_datetime(['2024-01-02'])})
        with pytest.raises(ValueError):
            m.get_regime_for_dates(pd.DatetimeIndex(['2024-01-03']))


class TestKeltnerAtrGuard:
    @staticmethod
    def _df(n=60):
        rng = np.random.default_rng(0)
        close = 10 * np.cumprod(1 + rng.normal(0, 0.01, n))
        return pd.DataFrame({
            '日期': pd.date_range('2024-01-01', periods=n, freq='B'),
            '开盘': close, '最高': close * 1.02, '最低': close * 0.98,
            '收盘': close,
            '成交量': rng.integers(1e6, 2e6, n).astype(float),
        })

    def test_preset_atr_not_overwritten(self):
        from advanced_indicators import AdvancedIndicators
        df = self._df()
        df['ATR'] = 7.77
        out = AdvancedIndicators.keltner_channel(df, period=20, multiplier=2)
        # 旧 bug: 无条件 atr() 重算覆写外部 ATR
        assert (out['ATR'] == 7.77).all()
        assert np.allclose(out['KC_Upper'] - out['KC_Middle'], 2 * 7.77)

    def test_atr_computed_when_absent(self):
        from advanced_indicators import AdvancedIndicators
        out = AdvancedIndicators.keltner_channel(self._df(), period=20)
        assert 'ATR' in out.columns
        assert out['ATR'].notna().any()
        assert out['ATR'].dropna().gt(0).all()


class TestSavePositionPriority:
    @staticmethod
    def _dm():
        pytest.importorskip("sqlalchemy")
        from database_manager import DatabaseManager
        dm = DatabaseManager.__new__(DatabaseManager)
        dm._connected = True
        session = MagicMock()

        @contextmanager
        def fake_get_session():
            yield session

        dm.get_session = fake_get_session
        return dm, session

    def test_insert_branch_market_value_and_pl(self):
        dm, session = self._dm()
        session.query.return_value.filter.return_value.first.return_value = None
        ok = dm.save_position(1, '600519', shares=100, avg_cost=10.0,
                              current_price=15.0)
        assert ok is True
        pos = session.add.call_args[0][0]
        # 旧 bug: (current_price or avg_cost - avg_cost) * shares → 1500
        assert pos.market_value == 1500.0
        assert pos.profit_loss == 500.0
        assert pos.profit_pct == pytest.approx(50.0)

    def test_update_branch_assigns_recomputed_fields(self):
        dm, session = self._dm()
        mock_pos = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = mock_pos
        ok = dm.save_position(1, '600519', shares=100, avg_cost=10.0,
                              current_price=15.0)
        assert ok is True
        assert mock_pos.profit_loss == 500.0
        assert mock_pos.market_value == 1500.0

    def test_none_current_price_falls_back_to_avg_cost(self):
        dm, session = self._dm()
        session.query.return_value.filter.return_value.first.return_value = None
        ok = dm.save_position(1, '600519', shares=100, avg_cost=10.0,
                              current_price=None)
        assert ok is True
        pos = session.add.call_args[0][0]
        assert pos.profit_loss == 0.0
        assert pos.market_value == 1000.0
        assert pos.current_price == 10.0


class TestConcurrentFetcherGuards:
    def test_fetcher_failure_does_not_cascade(self, monkeypatch):
        monkeypatch.setitem(sys.modules, 'stock_data_fetcher', None)
        sys.modules.pop('concurrent_fetcher', None)
        cf = importlib.import_module('concurrent_fetcher')
        # 旧 bug: 两段导入在同一个 try 块 → fetcher 缺失时 CacheManager 未绑定 NameError
        assert cf._FETCHER_AVAILABLE is False
        assert 'CacheManager' in vars(cf)
        assert 'get_cache_manager' in vars(cf)
        assert cf._CACHE_AVAILABLE is True


class TestSignalGeneratorRegression:
    @staticmethod
    def _sg():
        from signal_generator import SignalGenerator
        return SignalGenerator()

    def test_ma_cross_up_trend_semantics(self):
        sg = self._sg()
        n = 30
        ma5 = pd.Series(np.linspace(9, 11, n))
        ma20 = pd.Series(np.full(n, 10.0))
        close = ma5 + 0.3
        df = pd.DataFrame({'MA5': ma5, 'MA20': ma20, '收盘': close})
        sig = sg._ma_cross_signal(df)
        cross = [i for i in range(1, n)
                 if ma5.iloc[i] > ma20.iloc[i] and ma5.iloc[i - 1] <= ma20.iloc[i - 1]]
        assert cross, "构造数据中应存在金叉"
        # 金叉必须保持 1.0（不被趋势档 0.5 覆盖）
        assert sig.iloc[cross[0]] == 1.0
        # 仅趋势上行（非交叉）→ 0.5（旧 dead-fillna → 0）
        trend_only = [i for i in range(1, n)
                      if i not in cross
                      and close.iloc[i] > ma5.iloc[i] and ma5.iloc[i] > ma20.iloc[i]]
        assert trend_only
        assert sig.iloc[trend_only[0]] == 0.5
        # 浮点 dtype：pandas>=3 下 int64 赋 0.5 会 TypeError
        assert sig.dtype == np.float64

    def test_ma_cross_down_trend_semantics(self):
        sg = self._sg()
        n = 30
        ma5 = pd.Series(np.linspace(11, 9, n))
        ma20 = pd.Series(np.full(n, 10.0))
        close = ma5 - 0.3
        df = pd.DataFrame({'MA5': ma5, 'MA20': ma20, '收盘': close})
        sig = sg._ma_cross_signal(df)
        death = [i for i in range(1, n)
                 if ma5.iloc[i] < ma20.iloc[i] and ma5.iloc[i - 1] >= ma20.iloc[i - 1]]
        assert death, "构造数据中应存在死叉"
        assert sig.iloc[death[0]] == -1.0
        trend_only = [i for i in range(1, n)
                      if i not in death
                      and close.iloc[i] < ma5.iloc[i] and ma5.iloc[i] < ma20.iloc[i]]
        assert trend_only
        assert sig.iloc[trend_only[0]] == -0.5
        assert sig.dtype == np.float64

    def test_volume_signal_vectorized_values(self):
        sg = self._sg()
        n = 25
        vol = np.full(n, 1e6)
        vol[20] = 2e6
        vol[21] = 0.4e6
        close = np.full(n, 10.0)
        close[20] = 10.5
        close[21] = 10.6
        close[22] = 10.2
        df = pd.DataFrame({'成交量': vol, '收盘': close})
        sig = sg._volume_signal(df)
        # 放量+价涨 → 0.5（覆盖 0.3）
        assert sig.iloc[20] == 0.5
        # 缩量+价涨 → -0.2（缩量优先）
        assert sig.iloc[21] == -0.2
        # 价跌但量未增 → 0.0
        assert sig.iloc[22] == 0.0
        assert sig.dtype == np.float64

    def test_combine_thresholds_and_sign_exclusion(self):
        sg = self._sg()
        assert sg.buy_threshold == 2.0 and sg.sell_threshold == 2.0
        df = pd.DataFrame({
            'signal_ma_cross': [1.0, 0.5, -1.0, 0.0],
            'signal_macd':     [0.5, 0.0, -0.5, 0.0],
            'signal_rsi':      [0.5, 0.0, -0.5, 0.0],
        })
        buy = sg._combine_buy_signals(df)
        sell = sg._combine_sell_signals(df)
        # 正分合计 2.0 达阈值 → 1; 0.5 未达 → 0; 负信号不计入买
        assert buy.tolist() == [1, 0, 0, 0]
        # 负分合计 -2.0 → 卖出 1; 正信号不计入卖
        assert sell.tolist() == [0, 0, 1, 0]
        assert buy.dtype == np.int64 and sell.dtype == np.int64

    def test_generate_signals_end_to_end_pandas3(self):
        sg = self._sg()
        rng = np.random.default_rng(1)
        n = 30
        c = 10 * np.cumprod(1 + rng.normal(0, 0.01, n))
        df = pd.DataFrame({
            '日期': pd.date_range('2024-01-01', periods=n, freq='B'),
            '开盘': c, '最高': c * 1.02, '最低': c * 0.98, '收盘': c,
            '成交量': rng.integers(1e6, 2e6, n).astype(float),
            'MA5': pd.Series(c).rolling(5).mean(),
            'MA20': pd.Series(c).rolling(20).mean(),
            'MACD': rng.normal(0, 0.1, n),
            'MACD_Signal': rng.normal(0, 0.1, n),
            'K': rng.uniform(20, 80, n),
            'D': rng.uniform(20, 80, n),
            'RSI': rng.uniform(20, 80, n),
            'BB_Upper': c * 1.05,
            'BB_Lower': c * 0.95,
        })
        # 旧 bug: 信号列 int64 + 0.5 赋值 → pandas>=3 TypeError
        out = sg.generate_signals(df)
        for col in ('signal_ma_cross', 'signal_macd', 'signal_kdj',
                    'signal_rsi', 'signal_bb', 'signal_volume',
                    'signal_breakout', 'signal_buy', 'signal_sell',
                    'signal_strength'):
            assert col in out.columns, col
        assert out['signal_ma_cross'].dtype == np.float64
        assert np.isfinite(out['signal_strength']).all()


class TestStrategyOptimizerEvaluate:
    def test_evaluate_params_runs_real_backtest(self):
        from strategy_optimizer import StrategyOptimizer
        rng = np.random.default_rng(2)
        n = 250
        c = 10 * np.cumprod(1 + rng.normal(0.0005, 0.015, n))
        data = pd.DataFrame({
            '日期': pd.bdate_range('2023-01-02', periods=n),
            '开盘': c, '最高': c * 1.02, '最低': c * 0.98, '收盘': c,
            '成交量': rng.integers(1e6, 5e6, n).astype(float),
            'MA5': pd.Series(c).rolling(5).mean(),
            'MA20': pd.Series(c).rolling(20).mean(),
        })
        opt = StrategyOptimizer()
        res = opt.evaluate_params(data, {'short_period': 5, 'long_period': 20})
        # 旧 bug (PositionConfig 字段名 + run_backtest 方法名) → 异常被吞 → -999
        assert res.get('sharpe_ratio') != -999
        assert set(res) == {'sharpe_ratio', 'annual_return', 'max_drawdown',
                            'total_return', 'win_rate', 'profit_factor'}
        assert all(np.isfinite(v) for v in res.values())


class TestCrossSectionFactors:
    @staticmethod
    def _wide(seed=5):
        rng = np.random.default_rng(seed)
        dates = pd.bdate_range('2024-01-01', periods=150)
        drifts = {'AAA': 0.002, 'BBB': 0.0, 'CCC': -0.002}
        wide = pd.DataFrame({
            s: 100 * np.cumprod(1 + rng.normal(d, 0.01, len(dates)))
            for s, d in drifts.items()
        }, index=dates)
        wide.index.name = '日期'
        return wide

    def test_wide_panel_transposed_to_stock_by_date(self):
        from multi_factor_selection import FactorModels
        panel = FactorModels._price_cross_section({'收盘': self._wide()})
        assert panel.shape == (3, 150)
        assert panel.index.tolist() == ['AAA', 'BBB', 'CCC']

    def test_momentum_scores_follow_raw_returns(self):
        from multi_factor_selection import FactorModels
        wide = self._wide()
        mom = FactorModels.momentum_factor({'收盘': wide},
                                           periods=[20, 60, 120])
        assert mom.index.tolist() == ['AAA', 'BBB', 'CCC']
        raw20 = wide.iloc[-1] / wide.iloc[-21] - 1
        assert mom['Momentum_20'].idxmax() == raw20.idxmax()
        assert mom['Momentum_20'].idxmin() == raw20.idxmin()
        assert mom['Momentum_20'].mean() == pytest.approx(0.0, abs=1e-9)
        assert mom['Momentum_Score'].notna().all()

    def test_single_stock_returns_empty(self):
        from multi_factor_selection import FactorModels
        wide = self._wide()
        assert FactorModels._price_cross_section({'收盘': wide['AAA']}) is None
        assert FactorModels.momentum_factor(
            {'收盘': wide['AAA']}, periods=[20]).empty
        assert FactorModels.volatility_factor({'收盘': wide['AAA']}).empty

    def test_stacked_matches_wide(self):
        from multi_factor_selection import FactorModels
        wide = self._wide()
        stack = wide.T.stack()
        stack.index.names = ['股票', '日期']
        mom_wide = FactorModels.momentum_factor({'收盘': wide},
                                                periods=[20, 60, 120])
        mom_stack = FactorModels.momentum_factor({'收盘': stack},
                                                 periods=[20, 60, 120])
        assert np.allclose(mom_wide.sort_index().values,
                           mom_stack.sort_index().values)

    def test_insufficient_history_returns_empty(self):
        from multi_factor_selection import FactorModels
        short = {'收盘': self._wide().iloc[:30]}
        assert FactorModels.momentum_factor(
            short, periods=[60, 120]).shape == (0, 0)

    def test_volatility_scores_present(self):
        from multi_factor_selection import FactorModels
        vol = FactorModels.volatility_factor({'收盘': self._wide()}, period=20)
        assert vol.index.tolist() == ['AAA', 'BBB', 'CCC']
        assert vol['Volatility_Score'].notna().all()

    def test_calculate_factors_attaches_scores(self):
        from multi_factor_selection import MultiFactorSelector
        fin = pd.DataFrame({'PE': [10, 20, 30], 'ROE': [0.2, 0.1, 0.05]},
                           index=['AAA', 'BBB', 'CCC'])
        fin.index.name = '股票代码'
        cf = MultiFactorSelector().calculate_factors(
            fin, price_df={'收盘': self._wide()})
        assert 'Momentum_Score' in cf.columns
        assert 'Volatility_Score' in cf.columns
        assert cf['Momentum_Score'].notna().all()

    def test_smartbeta_momentum_top_n(self):
        from multi_factor_selection import SmartBetaStrategy
        top = SmartBetaStrategy().momentum_strategy(
            {'收盘': self._wide()}, period=120, top_n=2)
        assert top == ['AAA', 'BBB']
