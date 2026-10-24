# -*- coding: utf-8 -*-
"""统一信号输出契约 Signal (审计 C #9, 项 21 #9a).

覆盖:
- core.signal 契约自身: 动作校验 / 刻度校验 / 互斥映射 / 约束并入 / 序列扁平化
- S1 适配器: SignalGenerator.to_signal + 便捷入口 get_signal
- S2 适配器: StockSignal.to_signal + DailyReport.contract_signals
- trade_constraints 收口: ConstraintReport.as_signal_fields 统一装配
- web_app 消费契约 (源码级接线断言)
"""
import pathlib
import numpy as np
import pandas as pd
import pytest


SKILLS = pathlib.Path(__file__).resolve().parents[1] / '.claude' / 'skills'


def _raw(n=120, seed=13):
    rng = np.random.default_rng(seed)
    c = 10 * np.cumprod(1 + rng.normal(0.0005, 0.015, n))
    return pd.DataFrame({
        '日期': pd.bdate_range('2024-01-02', periods=n),
        '开盘': c, '最高': c * 1.01, '最低': c * 0.99, '收盘': c,
        '成交量': rng.integers(1e6, 2e6, n).astype(float),
    })


def _indicator_df(n=120, seed=13):
    """含 S1 所需指标列的 frame (与 stock_data_fetcher 口径一致)"""
    from stock_data_fetcher import StockDataFetcher
    return StockDataFetcher().calculate_technical_indicators(_raw(n, seed))


# ==================== 契约自身 ====================

class TestSignalContract:
    def test_required_fields_present(self):
        from core.signal import Signal
        s = Signal(symbol='600519', signal_date='2024-01-02', action='BUY',
                   strength=3.0)
        for field in ('symbol', 'signal_date', 'action', 'strength', 'scale',
                      'reasons', 'confidence', 'target_weight', 'execute_at',
                      'executable', 'blocked_reasons', 'skipped_checks',
                      'source', 'extra'):
            assert hasattr(s, field), field

    def test_invalid_action_rejected(self):
        from core.signal import Signal
        with pytest.raises(ValueError, match='action'):
            Signal(symbol='x', signal_date='2024-01-02', action='LONG')

    def test_prob_scale_rejects_out_of_range(self):
        from core.signal import Signal, SCALE_PROB
        with pytest.raises(ValueError, match='scale'):
            Signal(symbol='x', signal_date='2024-01-02', action='BUY',
                   strength=80.0, scale=SCALE_PROB)

    def test_vote_norm_scale_rejects_out_of_range(self):
        """契约完整性: 声明了刻度就必须落在该刻度的量纲内"""
        from core.signal import Signal, SCALE_VOTE_NORM
        with pytest.raises(ValueError, match='scale'):
            Signal(symbol='x', signal_date='2024-01-02', action='BUY',
                   strength=6.0, scale=SCALE_VOTE_NORM)
        # [-1, 1] 合法 (负值=卖方一侧)
        Signal(symbol='x', signal_date='2024-01-02', action='SELL',
               strength=-0.8, scale=SCALE_VOTE_NORM)

    def test_action_from_flags_mutual_exclusion(self):
        from core.signal import action_from_flags
        assert action_from_flags(True, False) == 'BUY'
        assert action_from_flags(False, True) == 'SELL'
        assert action_from_flags(False, False) == 'HOLD'
        with pytest.raises(ValueError, match='互斥'):
            action_from_flags(True, True)

    def test_apply_constraints_merges_report(self):
        from core.signal import Signal, apply_constraints
        from trade_constraints import ConstraintReport
        report = ConstraintReport(ok=False, blocked_reasons=['一字涨停封板'],
                                  skipped_checks=['市值无数据'])
        s = apply_constraints(
            Signal(symbol='x', signal_date='2024-01-02', action='BUY'), report)
        assert s.executable is False
        assert s.blocked_reasons == ['一字涨停封板']
        assert s.skipped_checks == ['市值无数据']

    def test_normalize_date_variants(self):
        from core.signal import normalize_date
        assert normalize_date(None) == ''
        assert normalize_date('2024-01-02') == '2024-01-02'
        assert normalize_date('2024-01-02 15:00:00') == '2024-01-02'
        assert normalize_date(pd.Timestamp('2024-01-02 09:30')) == '2024-01-02'

    def test_signals_to_frame_flat(self):
        from core.signal import Signal, signals_to_frame
        s1 = Signal(symbol='a', signal_date='2024-01-02', action='BUY',
                    strength=2.0, reasons=['MA金叉'])
        s2 = Signal(symbol='b', signal_date='2024-01-02', action='SELL',
                    strength=-1.0, scale='vote_norm')
        df = signals_to_frame([s1, s2])
        assert list(df['symbol']) == ['a', 'b']
        assert df.iloc[0]['reasons'] == 'MA金叉'
        assert df.iloc[1]['action'] == 'SELL'
        assert 'is_actionable' in df.columns

    def test_empty_signals_frame_has_columns(self):
        from core.signal import signals_to_frame
        df = signals_to_frame([])
        assert 'action' in df.columns and len(df) == 0

    def test_is_actionable(self):
        from core.signal import Signal
        buy = Signal(symbol='x', signal_date='2024-01-02', action='BUY')
        assert buy.is_actionable is True
        hold = Signal(symbol='x', signal_date='2024-01-02', action='HOLD')
        assert hold.is_actionable is False
        blocked = Signal(symbol='x', signal_date='2024-01-02', action='BUY',
                         executable=False)
        assert blocked.is_actionable is False


# ==================== S1 适配器 ====================

class TestS1Adapter:
    def test_to_signal_fields(self):
        from signal_generator import SignalGenerator
        sig = SignalGenerator().to_signal(_indicator_df(), symbol='600519')
        assert sig.symbol == '600519'
        assert sig.action in ('BUY', 'HOLD', 'SELL')
        assert sig.scale == 'vote'
        assert sig.source == 'signal_generator'
        assert sig.signal_date == '2024-01-02' or len(sig.signal_date) == 10
        assert isinstance(sig.executable, bool)
        assert 'price' in sig.extra and 'buy_score' in sig.extra

    def test_to_signal_weighted_scale(self):
        from signal_generator import SignalGenerator
        sig = SignalGenerator(use_weighted_scoring=True).to_signal(
            _indicator_df(), symbol='600519')
        assert sig.scale == 'weighted'

    def test_convenience_entry_matches_method(self):
        from signal_generator import SignalGenerator, get_signal
        df = _indicator_df()
        a = SignalGenerator().to_signal(df, symbol='600519')
        b = get_signal(df, symbol='600519')
        assert a == b

    def test_reasons_follow_action_side(self):
        """reasons 只能来自动作同侧 (不出现卖出理由混进买入)"""
        from signal_generator import SignalGenerator
        df = _indicator_df()
        sig = SignalGenerator().to_signal(df, symbol='x')
        assert isinstance(sig.reasons, list)
        if sig.action == 'BUY':
            assert all('死叉' not in r and '回落' not in r and '卖出' not in r
                       for r in sig.reasons)
        elif sig.action == 'SELL':
            assert all('金叉' not in r and '突破布林上轨' not in r
                       for r in sig.reasons)

    def test_target_weight_and_execute_at_passed(self):
        from signal_generator import SignalGenerator
        sig = SignalGenerator().to_signal(_indicator_df(), symbol='x',
                                          target_weight=0.3,
                                          execute_at='2024-01-03')
        assert sig.target_weight == 0.3
        assert sig.execute_at == '2024-01-03'

    def test_blocked_signal_carries_reasons(self):
        """零成交末 bar → 阻断原因进入契约"""
        from signal_generator import SignalGenerator
        df = _indicator_df()
        df.at[df.index[-1], '成交量'] = 0
        sig = SignalGenerator().to_signal(df, symbol='x')
        assert sig.executable is False
        assert sig.blocked_reasons


# ==================== S2 适配器 ====================

class TestS2Adapter:
    @staticmethod
    def _stock_signal(**kw):
        from daily_signal_generator import StockSignal
        base = dict(
            symbol='000001', name='测试', price=10.0, change_pct=1.0,
            regime='BULL', system_name='g', buy_score=3.0, sell_score=0.0,
            signal='BUY', signal_strength=1.0, reasons=['MA金叉'],
            ma_trend='UP', macd_hist=0.1, rsi=40.0, kdj_k=50.0,
            bb_position=0.6, volume_ratio=1.2, atr_pct=2.0,
            distance_to_support=1.0, distance_to_resistance=2.0)
        base.update(kw)
        return StockSignal(**base)

    def test_to_signal_fields(self):
        sig = self._stock_signal().to_signal(signal_date='2024-01-02')
        assert sig.symbol == '000001'
        assert sig.action == 'BUY'
        assert sig.scale == 'vote_norm'
        assert sig.source == 'daily_signal_generator'
        assert sig.signal_date == '2024-01-02'
        assert sig.reasons == ['MA金叉']
        assert sig.extra['regime'] == 'BULL'

    def test_hold_maps_to_hold(self):
        sig = self._stock_signal(signal='HOLD').to_signal('2024-01-02')
        assert sig.action == 'HOLD'
        assert sig.is_actionable is False

    def test_blocked_fields_carried(self):
        sig = self._stock_signal(executable=False,
                                 blocked_reasons=['停牌嫌疑']).to_signal(
            '2024-01-02')
        assert sig.executable is False
        assert sig.blocked_reasons == ['停牌嫌疑']
        assert sig.is_actionable is False

    def test_daily_report_carries_contract_signals(self):
        from types import SimpleNamespace
        from daily_signal_generator import (DailySignalGenerator,
                                            DailyReport)
        gen = DailySignalGenerator.__new__(DailySignalGenerator)
        gen.data_dir = './stock_data'
        gen.systems = {}
        gen.default_params = {}
        gen.optimization_result_file = None
        gen._index_labels = None
        gen._current_regime = None
        gen.data_manager = SimpleNamespace(
            get_universe=lambda min_rows=0: ['a', 'b'])
        gen.detect_current_regime = lambda index_data=None: 'SIDEWAYS'
        gen.get_params_for_regime = lambda regime: {}
        gen.get_system_name_for_regime = lambda regime: 'test'
        gen._check_regime_switch = lambda: ''

        def fake_stock(sym, regime, params):
            return self._stock_signal(symbol=sym)

        gen.generate_for_stock = fake_stock
        report = gen.generate_daily_report(symbols=['a', 'b'], n_stocks=2)
        assert isinstance(report, DailyReport)
        assert len(report.contract_signals) == len(report.signals)
        assert all(s.signal_date == report.date for s in report.contract_signals)


# ==================== trade_constraints 收口 ====================

class TestConstraintReportContractFields:
    def test_as_signal_fields(self):
        from trade_constraints import ConstraintReport
        report = ConstraintReport(ok=False, blocked_reasons=['x'],
                                  skipped_checks=['y'])
        fields = report.as_signal_fields()
        assert fields == {'executable': False, 'blocked_reasons': ['x'],
                          'skipped_checks': ['y']}

    def test_all_producers_use_uniform_assembly(self):
        """各模块不再手拼可执行性字段 (统一走 as_signal_fields)"""
        for name in ('daily_signal_generator.py', 'long_term_selector.py',
                     'ml_predictor.py', 'reversal_detector.py'):
            src = (SKILLS / name).read_text(encoding='utf-8')
            assert 'executable=constraint.ok' not in src, name
            assert 'as_signal_fields()' in src, name


# ==================== web_app 消费契约 ====================

class TestWebConsumesContract:
    def test_web_uses_signal_contract(self):
        src = (SKILLS / 'web_app.py').read_text(encoding='utf-8')
        assert 'from core.signal import' in src
        assert 'def get_stock_signal(symbol: str) -> Signal:' in src
        assert "signal.action == ACTION_BUY" in src
        # 旧的 dict 式访问已清除
        assert "signal.get('buy_signal'" not in src
        assert "signal['strength']" not in src

    def test_web_still_uses_generator_signals_for_chart(self):
        src = (SKILLS / 'web_app.py').read_text(encoding='utf-8')
        assert 'generator.generate_signals(data)' in src
        assert 'get_all_signals(' in src

    def test_s1_s2_contract_field_parity(self):
        """S1/S2 产出的契约字段完全同构 (下游可统一处理)"""
        from signal_generator import SignalGenerator
        from daily_signal_generator import to_signal
        from core.signal import Signal
        s1 = SignalGenerator().to_signal(_indicator_df(), symbol='x')
        s2 = to_signal(type('S', (), {
            'symbol': 'x', 'signal': 'BUY', 'signal_strength': 0.5,
            'reasons': ['MA金叉'], 'executable': True,
            'blocked_reasons': [], 'skipped_checks': [],
        })(), signal_date='2024-01-02')
        assert set(s1.__dataclass_fields__) == set(s2.__dataclass_fields__)
        assert set(s1.__dataclass_fields__) == set(Signal.__dataclass_fields__)
