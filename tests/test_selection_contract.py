# -*- coding: utf-8 -*-
"""选股结果契约 Selection + reversal/ml 的 Signal 适配 (审计 C #9b, 项 21).

覆盖:
- Selection 契约自身: 字段/刻度校验/排名校验/is_selected/序列扁平化
- MFS/SS/LTS 三个 L1 选股模块 → Selection 适配器
- reversal_detector / ml_predictor → Signal 适配器
- 契约分立: Selection 不含 action, Signal 不含 rank (语义边界)
"""
import pathlib
from datetime import datetime

import numpy as np
import pandas as pd
import pytest


SKILLS = pathlib.Path(__file__).resolve().parents[1] / '.claude' / 'skills'


# ==================== Selection 契约自身 ====================

class TestSelectionContract:
    def test_fields(self):
        from core.signal import Selection
        s = Selection(symbol='600519', as_of='2024-01-05', score=78.5,
                      scale='score', rank=1, selected=True, grade='BUY')
        for field in ('symbol', 'as_of', 'score', 'scale', 'rank', 'selected',
                      'grade', 'reasons', 'executable', 'blocked_reasons',
                      'skipped_checks', 'source', 'extra'):
            assert hasattr(s, field), field

    def test_score_scale_range_checked(self):
        from core.signal import Selection
        with pytest.raises(ValueError, match='score'):
            Selection(symbol='x', score=150.0, scale='score')

    def test_zscore_unbounded(self):
        from core.signal import Selection
        Selection(symbol='x', score=-3.2, scale='zscore')

    def test_rank_must_be_one_based(self):
        from core.signal import Selection
        with pytest.raises(ValueError, match='rank'):
            Selection(symbol='x', rank=0)

    def test_is_selected_requires_selected_and_executable(self):
        from core.signal import Selection
        assert Selection(symbol='x', selected=True).is_selected is True
        assert Selection(symbol='x', selected=False).is_selected is False
        assert Selection(symbol='x', selected=True,
                         executable=False).is_selected is False

    def test_selection_and_signal_are_separate_contracts(self):
        """契约分立: Selection 无 action, Signal 无 rank (语义不混用)"""
        from core.signal import Selection, Signal
        assert 'action' not in Selection.__dataclass_fields__
        assert 'rank' not in Signal.__dataclass_fields__
        assert 'score' in Selection.__dataclass_fields__
        assert 'strength' in Signal.__dataclass_fields__

    def test_selections_to_frame(self):
        from core.signal import Selection, selections_to_frame
        s1 = Selection(symbol='a', as_of='2024-01-05', score=80.0, rank=1)
        s2 = Selection(symbol='b', as_of='2024-01-05', score=60.0, rank=2,
                       selected=False)
        df = selections_to_frame([s1, s2])
        assert list(df['symbol']) == ['a', 'b']
        assert df.iloc[1]['selected'] is False or not df.iloc[1]['selected']
        assert 'as_of' in df.columns

    def test_empty_selections_frame(self):
        from core.signal import selections_to_frame
        df = selections_to_frame([])
        assert len(df) == 0 and 'symbol' in df.columns


# ==================== L1 三件套 → Selection ====================

class TestMfsAdapter:
    def test_to_selections(self):
        from multi_factor_selection import to_selections
        df = pd.DataFrame({
            'Value_Score': [1.2, 0.8],
            'Growth_Score': [0.5, 0.9],
            'Composite_Score': [1.0, 0.7],
        }, index=['600519', '000858'])
        sels = to_selections(df, as_of='2024-01-05')
        assert [s.symbol for s in sels] == ['600519', '000858']
        assert sels[0].rank == 1 and sels[1].rank == 2
        assert sels[0].scale == 'zscore'
        assert sels[0].as_of == '2024-01-05'
        assert sels[0].source == 'multi_factor_selection'
        assert sels[0].extra['Value_Score'] == 1.2

    def test_nan_score_rows_skipped(self):
        from multi_factor_selection import to_selections
        df = pd.DataFrame({'Composite_Score': [1.0, np.nan]},
                          index=['a', 'b'])
        sels = to_selections(df)
        assert [s.symbol for s in sels] == ['a']

    def test_empty_input(self):
        from multi_factor_selection import to_selections
        assert to_selections(pd.DataFrame()) == []
        assert to_selections(None) == []

    def test_missing_composite_score_column(self):
        from multi_factor_selection import to_selections
        df = pd.DataFrame({'Value_Score': [1.0]}, index=['a'])
        assert to_selections(df) == []


class TestStockSelectorAdapter:
    def test_to_selections(self):
        from stock_selector import to_selections
        sels = to_selections([
            {'symbol': '600519', 'score': 75.0, 'price': 1500.0,
             'change_1d': 1.2, 'change_5d': 3.4},
            {'symbol': '000858', 'score': 61.0, 'price': 180.0},
        ])
        assert [s.symbol for s in sels] == ['600519', '000858']
        assert sels[0].rank == 1
        assert sels[0].scale == 'score'
        assert sels[0].score == 75.0
        assert sels[0].selected is True
        # SS 是实盘实时筛选 → 无 point-in-time 基准日, 如实留空
        assert sels[0].as_of == ''
        assert sels[0].extra['price'] == 1500.0

    def test_empty_results(self):
        from stock_selector import to_selections
        assert to_selections([]) == []


class TestLongTermSelectorAdapter:
    @staticmethod
    def _analysis(**kw):
        from long_term_selector import StockAnalysis
        base = dict(
            code='600519', name='测试', current_price=1500.0,
            return_1m=0.05, return_3m=0.1, return_6m=0.2, return_1y=0.5,
            trend_score_3m=80.0, trend_score_6m=70.0, trend_score_1y=60.0,
            total_score=78.5, ma20=1400.0, ma60=1300.0, ma120=1200.0,
            ma250=1100.0, short_trend='UP', mid_trend='UP', long_trend='UP',
            recommendation='STRONG_BUY')
        base.update(kw)
        return StockAnalysis(**base)

    def test_to_selection(self):
        s = self._analysis().to_selection(rank=1)
        assert s.symbol == '600519'
        assert s.score == 78.5
        assert s.scale == 'score'
        assert s.rank == 1
        assert s.grade == 'STRONG_BUY'
        assert s.selected is True
        assert s.is_selected is True
        assert s.source == 'long_term_selector'
        assert s.extra['return_1y'] == 0.5

    def test_avoid_grade_not_selected(self):
        s = self._analysis(recommendation='AVOID').to_selection()
        assert s.selected is False
        assert s.is_selected is False
        assert s.grade == 'AVOID'

    def test_blocked_carries_executable_false(self):
        s = self._analysis(executable=False,
                           blocked_reasons=['一字涨停封板']).to_selection()
        assert s.executable is False
        assert s.blocked_reasons == ['一字涨停封板']
        assert s.is_selected is False

    def test_as_of_empty_when_unknown(self):
        """LTS 无 point-in-time 语义 (审计 L10) → 契约如实留空"""
        s = self._analysis().to_selection()
        assert s.as_of == ''


# ==================== reversal / ml → Signal ====================

class TestReversalAdapter:
    @staticmethod
    def _alert(**kw):
        from reversal_detector import ReversalAlert
        base = dict(
            code='600519', name='测试', price=1500.0, alert_type='SELL',
            signals=['RSI顶背离', '上影线长'], confidence=85.0,
            timing='1-2天', risk_note='高位放量', action='减仓')
        base.update(kw)
        return ReversalAlert(**base)

    def test_sell_alert(self):
        s = self._alert().to_signal(signal_date='2024-01-05')
        assert s.action == 'SELL'
        assert s.strength == 85.0
        assert s.scale == 'score'
        assert s.reasons == ['RSI顶背离', '上影线长']
        assert s.signal_date == '2024-01-05'
        assert s.source == 'reversal_detector'
        assert s.extra['timing'] == '1-2天'

    def test_watch_maps_to_hold(self):
        s = self._alert(alert_type='WATCH').to_signal()
        assert s.action == 'HOLD'
        assert s.is_actionable is False

    def test_buy_alert(self):
        s = self._alert(alert_type='BUY', confidence=60.0).to_signal()
        assert s.action == 'BUY'
        assert s.is_actionable is True

    def test_blocked_alert_not_actionable(self):
        s = self._alert(executable=False,
                        blocked_reasons=['停牌嫌疑']).to_signal()
        assert s.executable is False
        assert s.is_actionable is False


class TestMlAdapter:
    @staticmethod
    def _result(**kw):
        from ml_predictor import PredictionResult
        base = dict(
            symbol='600519', date=datetime(2024, 1, 5), prediction='up',
            probability=0.72, confidence=0.65, features={'rsi': 35.0})
        base.update(kw)
        return PredictionResult(**base)

    def test_up_prediction(self):
        s = self._result().to_signal()
        assert s.action == 'BUY'
        assert s.strength == 0.72
        assert s.scale == 'prob'
        assert s.confidence == 0.65
        assert s.signal_date == '2024-01-05'
        assert s.source == 'ml_predictor'
        assert s.extra['features']['rsi'] == 35.0

    def test_down_prediction(self):
        s = self._result(prediction='down').to_signal()
        assert s.action == 'SELL'

    def test_hold_prediction(self):
        s = self._result(prediction='hold').to_signal()
        assert s.action == 'HOLD'
        assert s.is_actionable is False

    def test_probability_out_of_range_rejected(self):
        """契约完整性: prob 刻度越界直接抛错"""
        s = self._result(probability=72.0)
        with pytest.raises(ValueError, match='scale'):
            s.to_signal()


# ==================== 源码级接线 ====================

class TestAdapterWiring:
    def test_all_producers_expose_adapters(self):
        expectations = {
            'multi_factor_selection.py': 'def to_selections(',
            'stock_selector.py': 'def to_selections(',
            'long_term_selector.py': 'def to_selection(',
            'reversal_detector.py': 'def to_signal(',
            'ml_predictor.py': 'def to_signal(',
        }
        for name, marker in expectations.items():
            src = (SKILLS / name).read_text(encoding='utf-8')
            assert marker in src, name

    def test_core_exports_selection(self):
        import core
        assert hasattr(core, 'Selection')
        assert hasattr(core, 'selections_to_frame')
        assert 'Selection' in core.__all__
