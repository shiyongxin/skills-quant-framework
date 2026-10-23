# -*- coding: utf-8 -*-
"""
C-P1-12 统一交易约束过滤器: 模块行为 + 7 模块接线回归

审计 C-P1-12: 停牌/涨跌停/流动性 (ADV/最低价/市值) 封装为 7 个
信号/选股模块共用的前置过滤。回测执行侧涨跌停已由 execution_model
覆盖, 本套测试锁信号/选股侧的标注与过滤行为。
"""
import numpy as np
import pandas as pd
import pytest

import factor_library
import trade_constraints as tc
from trade_constraints import ConstraintConfig, check_last_bar, check_close_panel

from test_e2e_regression import mk_ohlcv, mk_indicator_df, mk_financial


def mk_df(n=60, seed=7, base=10.0):
    """含成交额的合成 OHLCV (ADV/参与率检查用)"""
    rng = np.random.default_rng(seed)
    close = base * np.cumprod(1 + rng.normal(0.0005, 0.01, n))
    return pd.DataFrame({
        '日期': pd.bdate_range('2023-01-02', periods=n),
        '开盘': close,
        '最高': close * 1.01,
        '最低': close * 0.99,
        '收盘': close,
        '成交量': rng.integers(1e6, 3e6, n).astype(float),
        '成交额': rng.uniform(1e7, 5e7, n),
    })


def seal(df, pct):
    """最后一根改为平栏 (高==低, 蕴含开=高=低=收) 于板价 pct 处"""
    prev = float(df['收盘'].iloc[-2])
    price = round(prev * (1 + pct), 2)
    i = df.index[-1]
    for col in ('开盘', '最高', '最低', '收盘'):
        df.at[i, col] = price
    df.at[i, '成交量'] = 5e6
    if '成交额' in df.columns:
        df.at[i, '成交额'] = 2e7
    return df


class TestLimitBoard:
    def test_sealed_limit_up_blocks_buy_only(self):
        df = seal(mk_df(), 0.10)
        buy = check_last_bar(df, code='600000', side='buy')
        assert not buy.ok
        assert any('涨停' in r for r in buy.blocked_reasons)
        # 一字涨停不阻卖出
        sell = check_last_bar(df, code='600000', side='sell')
        assert sell.ok

    def test_sealed_limit_down_blocks_sell_only(self):
        df = seal(mk_df(), -0.10)
        sell = check_last_bar(df, code='600000', side='sell')
        assert not sell.ok
        assert any('跌停' in r for r in sell.blocked_reasons)
        buy = check_last_bar(df, code='600000', side='buy')
        assert buy.ok

    def test_chinext_uses_20pct_band(self):
        # 创业板 300xxx -10% 平栏: 20% 限幅下未触板 → 双向可执行
        df = seal(mk_df(), -0.10)
        assert check_last_bar(df, code='300001', side='both').ok
        # -19.9% 触及 20% 跌停板 → 卖出阻
        df2 = seal(mk_df(), -0.199)
        rep = check_last_bar(df2, code='300001', side='sell')
        assert not rep.ok
        assert rep.details['limit_pct'] == 0.20

    def test_unsealed_limit_close_passes(self):
        # 收盘触板但非平栏 (高>低) → 日内有成交, 不按一字板阻断
        df = mk_df()
        prev = float(df['收盘'].iloc[-2])
        price = round(prev * 1.10, 2)
        i = df.index[-1]
        df.at[i, '开盘'] = price * 0.99
        df.at[i, '最高'] = price * 1.02
        df.at[i, '最低'] = price * 0.98
        df.at[i, '收盘'] = price
        rep = check_last_bar(df, code='600000', side='buy')
        assert rep.ok
        assert rep.details['sealed_bar'] is False

    def test_code_none_skips_board_check(self):
        rep = check_last_bar(mk_df(), code=None, side='both')
        assert rep.ok
        assert any('一字板' in s for s in rep.skipped_checks)

    def test_invalid_side_raises(self):
        with pytest.raises(ValueError, match='side'):
            check_last_bar(mk_df(), side='hold')

    def test_empty_df_blocked(self):
        rep = check_last_bar(pd.DataFrame(), code='600000')
        assert not rep.ok


class TestSuspensionAndStale:
    def test_zero_volume_blocks(self):
        df = mk_df()
        df.at[df.index[-1], '成交量'] = 0
        rep = check_last_bar(df, code='600000')
        assert not rep.ok
        assert any('零成交量' in r for r in rep.blocked_reasons)

    def test_zero_amount_blocks(self):
        df = mk_df()
        df.at[df.index[-1], '成交额'] = 0
        rep = check_last_bar(df, code='600000')
        assert not rep.ok
        assert any('零成交额' in r for r in rep.blocked_reasons)

    def test_stale_blocks_when_configured(self):
        cfg = ConstraintConfig(max_stale_days=5)
        df = mk_df()
        last = pd.Timestamp(df['日期'].iloc[-1])
        rep = check_last_bar(df, config=cfg, code='600000',
                             as_of=last + pd.Timedelta(days=10))
        assert not rep.ok
        assert any('过期' in r for r in rep.blocked_reasons)
        assert rep.details['stale_days'] == 10
        # 新鲜数据 (1天) → 通过
        ok = check_last_bar(df, config=cfg, code='600000',
                            as_of=last + pd.Timedelta(days=1))
        assert ok.ok

    def test_no_as_of_records_skip(self):
        rep = check_last_bar(mk_df(), code='600000')
        assert any('as_of' in s for s in rep.skipped_checks)

    def test_default_config_stale_off(self):
        # 默认 max_stale_days=None: 给 as_of 也不查 (无交易日历, 不误伤节假日)
        rep = check_last_bar(mk_df(), code='600000', as_of='2030-01-01')
        assert rep.ok
        assert any('max_stale_days' in s for s in rep.skipped_checks)


class TestLiquidity:
    def test_min_price_blocks(self):
        df = mk_df()
        df.at[df.index[-1], '收盘'] = 0.9
        rep = check_last_bar(df, code='600000')
        assert not rep.ok
        assert any('最低价格' in r for r in rep.blocked_reasons)

    def test_min_price_disabled(self):
        df = mk_df()
        df.at[df.index[-1], '收盘'] = 0.9
        cfg = ConstraintConfig(min_price=0)
        assert check_last_bar(df, config=cfg, code='600000').ok

    def test_adv_floor_blocks_when_enabled(self):
        # 默认关闭 (历史成交额单位未清洗, 防误杀)
        assert check_last_bar(mk_df(), code='600000').ok
        cfg = ConstraintConfig(min_adv_amount=1e12)
        rep = check_last_bar(mk_df(), config=cfg, code='600000')
        assert not rep.ok
        assert any('ADV20' in r for r in rep.blocked_reasons)
        assert 'adv20' in rep.details

    def test_adv_floor_skipped_without_amount_column(self):
        df = mk_df().drop(columns=['成交额'])
        cfg = ConstraintConfig(min_adv_amount=1e12)
        rep = check_last_bar(df, config=cfg, code='600000')
        assert rep.ok  # 不伪造检查
        assert any('min_adv_amount' in s for s in rep.skipped_checks)

    def test_participation_cap(self):
        df = mk_df()
        cap_case = check_last_bar(df, code='600000', target_amount=1e3)
        assert cap_case.ok
        big_case = check_last_bar(df, code='600000', target_amount=1e12)
        assert not big_case.ok
        assert any('目标金额' in r for r in big_case.blocked_reasons)
        assert 'amount_cap' in big_case.details

    def test_market_cap_skipped_when_no_column(self):
        cfg = ConstraintConfig(min_market_cap=1e10)
        rep = check_last_bar(mk_df(), config=cfg, code='600000')
        assert rep.ok
        assert any('min_market_cap' in s for s in rep.skipped_checks)


class TestConfig:
    def test_json_factory_equals_builtin_defaults(self):
        raw = factor_library.load_config('trade_constraints')
        assert raw is not None, 'config/trade_constraints.json 必须存在'
        assert {'min_price', 'min_adv_amount', 'max_adv_participation',
                'min_market_cap', 'max_stale_days'} <= set(raw)
        cfg = tc.get_config(refresh=True)
        assert cfg == ConstraintConfig()  # 出厂值=内置默认 (C-P1-11 模式)

    def test_get_config_returns_cached_dataclass(self):
        assert isinstance(tc.get_config(), ConstraintConfig)
        assert tc.get_config() is tc.get_config()


class TestClosePanel:
    def test_penny_and_nan_dropped(self):
        panel = pd.DataFrame(
            {'d1': [10.0, 10.0, 10.0],
             'd2': [10.1, 0.9, np.nan]},
            index=['AAA', 'BBB', 'CCC'])
        keep, reasons = check_close_panel(panel)
        assert keep['AAA']
        assert not keep['BBB']
        assert not keep['CCC']
        assert '最低价格' in reasons['BBB']
        assert '停牌' in reasons['CCC']

    def test_none_and_empty_safe(self):
        keep, reasons = check_close_panel(None)
        assert len(keep) == 0 and reasons == {}
        keep2, _ = check_close_panel(pd.DataFrame())
        assert len(keep2) == 0


# ==========================================================================
# 7 模块接线
# ==========================================================================

class _MapFetcher:
    """按 symbol 返回不同 DataFrame 的数据源 (PositionAnalyzer 契约)"""
    def __init__(self, frames):
        self.frames = frames

    def get_quote_data(self, symbol, days=120, **k):
        return self.frames[symbol].copy()

    def get_quote_result(self, symbol, start_date=None, end_date=None,
                         days=120):
        from core.fetch_result import FetchResult
        return FetchResult.success(self.frames[symbol].copy(), source='stub')


class TestWiringS1SignalGenerator:
    def test_latest_signal_has_executable_keys(self):
        from signal_generator import SignalGenerator
        info = SignalGenerator().get_latest_signal(mk_indicator_df())
        assert info['executable'] is True
        assert info['blocked_reasons'] == []
        assert isinstance(info['skipped_checks'], list)

    def test_zero_volume_flags_not_executable(self):
        from signal_generator import SignalGenerator
        df = mk_indicator_df()
        df.at[df.index[-1], '成交量'] = 0
        info = SignalGenerator().get_latest_signal(df)
        assert info['executable'] is False
        assert any('零成交量' in r for r in info['blocked_reasons'])

    def test_report_shows_block_reasons(self):
        from signal_generator import SignalGenerator
        sg = SignalGenerator()
        info = sg.get_latest_signal(mk_indicator_df())
        info['blocked_reasons'] = ['一字涨停封板 (限幅10%) → 买入不可成交']
        out = sg.format_signal_report(info)
        assert '阻断' in out
        assert '一字涨停' in out

    def test_normal_report_has_no_block_section(self):
        from signal_generator import SignalGenerator
        sg = SignalGenerator()
        out = sg.format_signal_report(sg.get_latest_signal(mk_indicator_df()))
        assert '可执行性检查' not in out


class TestWiringS2DailySignalGenerator:
    @staticmethod
    def _stub_gen(data):
        from types import SimpleNamespace
        from daily_signal_generator import DailySignalGenerator
        gen = DailySignalGenerator.__new__(DailySignalGenerator)
        gen.data_manager = SimpleNamespace(
            load=lambda sym: data.copy(),
            get_stock_name=lambda sym: '测试股票')
        gen.systems = {}
        gen.default_params = {}
        gen._current_regime = 'SIDEWAYS'
        gen.get_params_for_regime = lambda r: {}
        return gen

    def test_generate_for_stock_normal_executable(self):
        sig = self._stub_gen(mk_ohlcv(n=150)).generate_for_stock(
            '000001.SZ', regime='SIDEWAYS')
        assert sig.executable is True
        assert sig.blocked_reasons == []

    def test_generate_for_stock_zero_volume_blocked(self):
        data = mk_ohlcv(n=150)
        data.at[data.index[-1], '成交量'] = 0
        sig = self._stub_gen(data).generate_for_stock(
            '000001.SZ', regime='SIDEWAYS')
        assert sig.executable is False
        assert any('零成交量' in r for r in sig.blocked_reasons)

    def test_daily_report_filters_blocked_signals(self):
        from types import SimpleNamespace
        from daily_signal_generator import (DailySignalGenerator,
                                            StockSignal)
        gen = DailySignalGenerator.__new__(DailySignalGenerator)
        gen.data_dir = './stock_data'
        gen.systems = {}
        gen.default_params = {}
        gen.optimization_result_file = None
        gen._index_labels = None
        gen._current_regime = None
        gen.data_manager = SimpleNamespace(
            get_universe=lambda min_rows=0: ['a', 'b', 'c'])
        gen.detect_current_regime = lambda index_data=None: 'SIDEWAYS'
        gen.get_params_for_regime = lambda regime: {'p': 1}
        gen.get_system_name_for_regime = lambda regime: 'test-system'
        gen._check_regime_switch = lambda: ''

        def fake_stock(sym, regime, params):
            blocked = (sym == 'b')
            return StockSignal(
                symbol=sym, name=sym, price=10.0, change_pct=0.0,
                regime=regime, system_name='x',
                buy_score=1.0, sell_score=0.0, signal='BUY',
                signal_strength=0.5, reasons=[], ma_trend='UP',
                macd_hist=0.0, rsi=50.0, kdj_k=50.0, bb_position=0.5,
                volume_ratio=1.0, atr_pct=1.0, distance_to_support=1.0,
                distance_to_resistance=1.0,
                executable=not blocked,
                blocked_reasons=['零成交量 (停牌嫌疑) → 无法成交'] if blocked else [])

        gen.generate_for_stock = fake_stock
        report = gen.generate_daily_report(symbols=['a', 'b', 'c'])
        # 不可执行 (b) 剔除, total_analyzed 仍记分析数
        assert [s.symbol for s in report.signals] == ['a', 'c']
        assert report.total_analyzed == 3


class TestWiringS3MultiFactorSelection:
    def test_select_stocks_drops_penny_stock(self):
        from multi_factor_selection import MultiFactorSelector
        fin = mk_financial(n_stocks=4, seed=1)
        dates = pd.bdate_range('2024-01-01', periods=30)
        wide = pd.DataFrame(10.0, index=dates, columns=list(fin.index))
        penny = list(fin.index)[0]
        wide.iloc[-1, 0] = 0.9  # 最新交易日仙股 → 停牌/退市风险
        out = MultiFactorSelector().select_stocks(
            fin, price_df={'收盘': wide}, top_n=10, as_of='2024-06-30')
        assert penny not in out.index
        assert len(out) == len(fin) - 1
        assert out['Composite_Score'].notna().all()

    def test_select_stocks_without_price_df_unchanged(self):
        from multi_factor_selection import MultiFactorSelector
        fin = mk_financial(n_stocks=4, seed=1)
        out = MultiFactorSelector().select_stocks(
            fin, top_n=10, as_of='2024-06-30')
        assert len(out) == len(fin)  # 无价格数据不做价格侧过滤


class TestWiringS4StockSelector:
    def test_screen_drops_sealed_limit_up_stock(self):
        from stock_selector import StockSelector
        frames = {
            '600000': mk_indicator_df(n=80, seed=2),
            '600001': seal(mk_indicator_df(n=80, seed=3), 0.10),
        }
        ss = StockSelector(fetcher=_MapFetcher(frames))
        res = ss.screen_stocks(['600000', '600001'],
                               min_score=0, max_count=5)
        assert [r['symbol'] for r in res] == ['600000']

    def test_filter_by_criteria_drops_sealed_stock(self):
        from stock_selector import StockSelector
        frames = {
            '600000': mk_indicator_df(n=80, seed=4),
            '600001': seal(mk_indicator_df(n=80, seed=5), 0.10),
        }
        ss = StockSelector(fetcher=_MapFetcher(frames))
        res = ss.filter_by_criteria(['600000', '600001'], {})
        assert [r['symbol'] for r in res] == ['600000']


class TestWiringS5LongTermSelector:
    @staticmethod
    def _stub_lts(normal, bad):
        from long_term_selector import LongTermSelector
        lts = LongTermSelector()
        lts.get_stock_data = lambda code, days=500: (
            bad.copy() if code == '600001' else normal.copy())
        return lts

    def test_analyze_stock_annotates_blocked(self):
        lts = self._stub_lts(mk_ohlcv(n=300, seed=23),
                             seal(mk_ohlcv(n=300, seed=24), 0.10))
        blocked = lts.analyze_stock('600001', 'B')
        assert blocked is not None  # 标注而非返 None
        assert blocked.executable is False
        assert any('涨停' in r for r in blocked.blocked_reasons)

    def test_select_stocks_filters_blocked(self):
        lts = self._stub_lts(mk_ohlcv(n=300, seed=23),
                             seal(mk_ohlcv(n=300, seed=24), 0.10))
        sel = lts.select_stocks({'600000': 'A', '600001': 'B'}, top_k=2)
        assert [a.code for a in sel] == ['600000']


class TestWiringS6ReversalDetector:
    def test_alert_annotated_executable(self):
        from reversal_detector import ReversalDetector
        rd = ReversalDetector()
        rd.get_stock_data = lambda code, days=250: mk_indicator_df(
            n=200, seed=31).copy()
        alert = rd.analyze_reversal('600000', 'T')
        assert alert is not None
        assert alert.executable is True
        assert alert.blocked_reasons == []

    def test_analyze_stocks_filters_blocked_alert(self):
        from reversal_detector import ReversalDetector, ReversalAlert
        rd = ReversalDetector()
        good = ReversalAlert(
            code='600000', name='A', price=10.0, alert_type='BUY',
            signals=['s'], confidence=60.0, timing='即将', risk_note='',
            action='分批建仓')
        bad = ReversalAlert(
            code='600001', name='B', price=10.0, alert_type='SELL',
            signals=['s'], confidence=70.0, timing='即将', risk_note='',
            action='注意风险',
            executable=False, blocked_reasons=['零成交量 (停牌嫌疑) → 无法成交'])
        rd.analyze_reversal = lambda code, name='': (
            good if code == '600000' else bad)
        out = rd.analyze_stocks({'600000': 'A', '600001': 'B'})
        assert [a.code for a in out] == ['600000']


class TestWiringS7MLPredictor:
    def test_predict_annotates_executable(self):
        pytest.importorskip('sklearn')
        from ml_predictor import MLPredictor
        mp = MLPredictor()
        mp.train(mk_ohlcv(n=400, seed=41))
        good = mp.predict(mk_ohlcv(n=400, seed=41))
        assert good.executable is True
        # 零成交末 bar → 双向阻断 (与预测方向无关)
        bad_df = mk_ohlcv(n=400, seed=41)
        bad_df.at[bad_df.index[-1], '成交量'] = 0
        bad = mp.predict(bad_df)
        assert bad.executable is False
        assert bad.blocked_reasons
