# -*- coding: utf-8 -*-
"""信号层合并: S2 内层并入 S1 + S1 三问题修复 (审计项 21 合并批).

覆盖:
- S1 买卖互斥仲裁 (投票制 + 加权制): 两侧分值都过阈值时只允许一侧成立
- S1 分值列暴露 (signal_buy_score / signal_sell_score) 与分项求和一致
- S1 报告标签与逻辑对齐 (旧版把"突破上轨(买)"标成"触及下轨(买)")
- S1 死变量清理 (volume_ma20)
- S1 column_map / RSI 阈值可配
- S2 内层 = S1: 逐位等价 + 布林口径统一 + schema 不变 + reasons 同标签表
- S2 源码级: 不再自带打分 (单一真相源)
"""
import pathlib
import numpy as np
import pandas as pd
import pytest


SKILLS = pathlib.Path(__file__).resolve().parents[1] / '.claude' / 'skills'


# ==================== 数据构造 ====================

def _raw(n=120, seed=11):
    """原始 OHLCV (无指标列)"""
    rng = np.random.default_rng(seed)
    c = 10 * np.cumprod(1 + rng.normal(0.0005, 0.015, n))
    return pd.DataFrame({
        '日期': pd.bdate_range('2024-01-02', periods=n),
        '开盘': c,
        '最高': c * 1.01,
        '最低': c * 0.99,
        '收盘': c,
        '成交量': rng.integers(1e6, 2e6, n).astype(float),
    })


def _crafted(side='buy'):
    """构造两侧分值都过阈值的 frame (side='buy' → 买分更高; 'sell' → 卖分更高).

    指标列直接给值, 以精确控制最后一根 bar 的分项档位。
    """
    n = 30
    base = dict(
        close=10.0, high=10.0, low=10.0, vol=1e6, ma5=10.0, ma20=10.0,
        macd=0.0, macd_sig=0.0, k=50.0, d=50.0, rsi=50.0,
        bb_u=10.0, bb_l=9.5,
    )
    if side == 'buy':
        # 买分: MA金叉(+1) + KDJ金叉(+1) + 量增价涨(+0.5) = 2.5
        # 卖分: RSI进超买(-1) + 从布林上轨回落(-1) = 2.0  (两侧都过阈值)
        last = dict(base, close=10.5, high=10.55, low=10.45, vol=10e6,
                    ma5=10.2, ma20=10.0, k=55.0, d=45.0, rsi=75.0,
                    bb_u=11.0, bb_l=9.5)
        prior = dict(base, high=10.6, low=9.5, bb_u=10.0, bb_l=9.5)
    else:
        # 买分: MA金叉(+1) + KDJ金叉(+1) = 2.0
        # 卖分: RSI进超买(-1) + 从布林上轨回落(-1) + 缩量(-0.2) + 跌破20日低点(-1)
        last = dict(base, close=9.0, high=9.05, low=8.9, vol=0.1e6,
                    ma5=10.2, ma20=10.0, k=55.0, d=45.0, rsi=75.0,
                    bb_u=10.0, bb_l=8.5)
        prior = dict(base, high=10.2, low=9.5, bb_u=10.0, bb_l=9.5)

    def series(key, override=None):
        values = np.full(n, prior[key], dtype=float)
        values[-1] = last[key]
        return values

    return pd.DataFrame({
        '日期': pd.bdate_range('2024-01-02', periods=n),
        '开盘': series('close'),
        '最高': series('high'),
        '最低': series('low'),
        '收盘': series('close'),
        '成交量': series('vol'),
        'MA5': series('ma5'),
        'MA20': series('ma20'),
        'MACD': series('macd'),
        'MACD_Signal': series('macd_sig'),
        'K': series('k'),
        'D': series('d'),
        'RSI': series('rsi'),
        'BB_Upper': series('bb_u'),
        'BB_Lower': series('bb_l'),
    })


# ==================== S1: 三个现存问题 ====================

class TestS1MutualExclusion:
    """买卖可同时为真 → 修复为互斥仲裁"""

    def test_buy_wins_when_both_scores_pass(self):
        from signal_generator import SignalGenerator
        out = SignalGenerator().generate_signals(_crafted('buy'))
        last = out.iloc[-1]
        # 两侧分值都过阈值 (旧实现会同时给出买+卖)
        assert last['signal_buy_score'] >= 2.0
        assert last['signal_sell_score'] >= 2.0
        assert last['signal_buy'] == 1
        assert last['signal_sell'] == 0
        assert not ((out['signal_buy'] == 1) & (out['signal_sell'] == 1)).any()

    def test_sell_wins_when_both_scores_pass(self):
        from signal_generator import SignalGenerator
        out = SignalGenerator().generate_signals(_crafted('sell'))
        last = out.iloc[-1]
        assert last['signal_sell_score'] >= 2.0
        assert last['signal_buy_score'] >= 2.0
        assert last['signal_sell'] == 1
        assert last['signal_buy'] == 0
        assert not ((out['signal_buy'] == 1) & (out['signal_sell'] == 1)).any()

    def test_weighted_mode_mutual_exclusion(self):
        from signal_generator import SignalGenerator
        sg = SignalGenerator(use_weighted_scoring=True,
                             scoring_params={'score_buy_threshold': 0.0,
                                             'score_sell_threshold': 0.0})
        out = sg.generate_signals(_crafted('buy'))
        last = out.iloc[-1]
        assert not ((out['signal_buy'] == 1) & (out['signal_sell'] == 1)).any()
        # 严格比较: 分值高者成立
        assert last['signal_buy'] == int(last['signal_buy_score']
                                         > last['signal_sell_score'])

    def test_score_columns_match_component_sum(self):
        from signal_generator import SignalGenerator
        out = SignalGenerator().generate_signals(_crafted('buy'))
        comps = ['signal_ma_cross', 'signal_macd', 'signal_kdj', 'signal_rsi',
                 'signal_bb', 'signal_volume', 'signal_breakout']
        buy = out[comps].clip(lower=0).sum(axis=1)
        sell = (-out[comps].clip(upper=0)).sum(axis=1)
        pd.testing.assert_series_equal(out['signal_buy_score'], buy,
                                       check_names=False)
        pd.testing.assert_series_equal(out['signal_sell_score'], sell,
                                       check_names=False)


class TestS1ReportLabels:
    """报告标签与逻辑对齐 (旧版 BB 标签与实际档位相反)"""

    def test_bb_label_matches_signal_value(self):
        from signal_generator import SignalGenerator, SIGNAL_LABELS
        sg = SignalGenerator()
        for side in ('buy', 'sell'):
            info = sg.get_latest_signal(_crafted(side))
            val = float(info['bb'])
            expected = SIGNAL_LABELS['signal_bb'][round(val, 2)]
            text = sg.format_signal_report(info)
            direction = '买入' if val > 0 else '卖出'
            assert f"布林带: {direction} ({expected})" in text

    def test_old_wrong_labels_gone(self):
        from signal_generator import SignalGenerator
        sg = SignalGenerator()
        text = sg.format_signal_report(sg.get_latest_signal(_crafted('buy')))
        assert '买入 (触及下轨)' not in text
        assert '卖出 (突破上轨)' not in text

    def test_label_table_covers_all_tiers(self):
        from signal_generator import SIGNAL_LABELS, describe_signals
        for col, labels in SIGNAL_LABELS.items():
            for value in labels:
                got = describe_signals({col: value}, side='all')
                assert got == [labels[value]], (col, value)


class TestS1DeadCode:
    def test_no_dead_volume_ma20(self):
        src = (SKILLS / 'signal_generator.py').read_text(encoding='utf-8')
        assert 'volume_ma20' not in src


# ==================== S1: 可配置性 ====================

class TestS1Configurability:
    def test_column_map_equivalence(self):
        """column_map: S1 契约列名 → 实际列名 (S2 params 驱动周期列)"""
        from signal_generator import SignalGenerator
        df = _crafted('buy')
        renamed = df.rename(columns={'MA5': 'MA_Fast', 'MA20': 'MA_Slow'})
        direct = SignalGenerator().generate_signals(df)
        mapped = SignalGenerator(column_map={'MA5': 'MA_Fast',
                                             'MA20': 'MA_Slow'}
                                 ).generate_signals(renamed)
        pd.testing.assert_frame_equal(
            direct[['signal_ma_cross', 'signal_buy', 'signal_sell']],
            mapped[['signal_ma_cross', 'signal_buy', 'signal_sell']])

    def test_rsi_threshold_configurable(self):
        from signal_generator import SignalGenerator
        df = _crafted('buy')
        rsi = np.full(len(df), 50.0)
        rsi[-2] = 45.0
        rsi[-1] = 35.0            # 跌破 40 但未跌破 30
        df['RSI'] = rsi
        default = SignalGenerator().generate_signals(df)
        tuned = SignalGenerator(rsi_oversold=40.0).generate_signals(df)
        # 默认 30: 未进超卖区 → 仅弱势档 -0.2
        assert default.iloc[-1]['signal_rsi'] == -0.2
        # 阈值 40: 进入超卖区 → +1
        assert tuned.iloc[-1]['signal_rsi'] == 1.0

    def test_generator_from_params_honors_rsi_thresholds(self):
        """优化器参数空间的 RSI 阈值维下发后必须真的生效"""
        from signal_generator import generator_from_params
        df = _crafted('buy')
        rsi = np.full(len(df), 50.0)
        rsi[-2] = 45.0
        rsi[-1] = 35.0
        df['RSI'] = rsi
        out = generator_from_params({'rsi_oversold': 40.0}).generate_signals(df)
        assert out.iloc[-1]['signal_rsi'] == 1.0
        # 缺键 → 出厂 30/70
        out0 = generator_from_params({}).generate_signals(df)
        assert out0.iloc[-1]['signal_rsi'] == -0.2


# ==================== S2: 内层并入 S1 ====================

class TestS2InnerLayerDelegatesToS1:
    def test_scores_bitwise_equal_to_s1(self):
        from signal_generator import SignalGenerator
        from daily_signal_generator import generate_signal, compute_indicators
        data = _raw()
        params = {}
        s2 = generate_signal(data, params)

        frame = compute_indicators(data, params)
        s1 = SignalGenerator(column_map={'MA5': 'MA_Fast', 'MA10': 'MA_Mid',
                                         'MA20': 'MA_Slow'}
                             ).generate_signals(frame)
        last = s1.iloc[-1]
        assert s2['buy_score'] == pytest.approx(float(last['signal_buy_score']))
        assert s2['sell_score'] == pytest.approx(float(last['signal_sell_score']))
        expect = ('BUY' if last['signal_buy']
                  else 'SELL' if last['signal_sell'] else 'HOLD')
        assert s2['signal'] == expect

    def test_schema_unchanged(self):
        from daily_signal_generator import generate_signal
        s2 = generate_signal(_raw(), {})
        assert s2 is not None
        assert set(s2) >= {'buy_score', 'sell_score', 'signal', 'strength',
                           'reasons', 'indicators'}
        assert s2['signal'] in ('BUY', 'HOLD', 'SELL')
        assert -1.0 <= s2['strength'] <= 1.0
        assert set(s2['indicators']) >= {'ma_trend', 'macd_hist', 'rsi',
                                         'kdj_k', 'bb_position',
                                         'volume_ratio', 'atr_pct'}

    def test_reasons_use_s1_label_table(self):
        from signal_generator import SIGNAL_LABELS
        from daily_signal_generator import generate_signal
        all_labels = {lab for labels in SIGNAL_LABELS.values()
                      for lab in labels.values()}
        s2 = generate_signal(_raw(seed=3), {})
        assert all(r in all_labels for r in s2['reasons'])

    def test_bb_polarity_follows_s1_breakout_semantics(self):
        """布林口径统一为 S1 突破跟随: S2 的 reasons/分值与 S1 分项完全一致"""
        from signal_generator import (SignalGenerator, SIGNAL_LABELS,
                                      describe_signals)
        from daily_signal_generator import generate_signal, compute_indicators
        data = _raw(seed=7)
        params = {}
        frame = compute_indicators(data, params)
        s1 = SignalGenerator(column_map={'MA5': 'MA_Fast', 'MA10': 'MA_Mid',
                                         'MA20': 'MA_Slow'}
                             ).generate_signals(frame)
        last = s1.iloc[-1]
        s2 = generate_signal(data, params)

        values = {c: last[c] for c in SIGNAL_LABELS}
        side = ('buy' if s2['signal'] == 'BUY'
                else 'sell' if s2['signal'] == 'SELL' else 'all')
        expected = (describe_signals(values, side=side)
                    if s2['signal'] != 'HOLD' else [])
        assert s2['reasons'] == expected
        # 买入理由里不得出现 S1 的卖出档标签 (旧 S2 把"触下轨"当买入理由)
        if s2['signal'] == 'BUY':
            assert '触及布林下轨' not in s2['reasons']

    def test_params_periods_still_driven(self):
        """params 驱动的均线周期仍生效 (不被写死列名吞掉)"""
        from daily_signal_generator import compute_indicators
        data = _raw()
        default = compute_indicators(data, {})
        tuned = compute_indicators(data, {'ma_slow': 30})
        assert not default['MA_Slow'].equals(tuned['MA_Slow'])
        assert tuned['MA_Slow'].iloc[-1] == pytest.approx(
            data['收盘'].astype(float).rolling(30).mean().iloc[-1])

    def test_weighted_mode_switchable_by_params(self):
        from daily_signal_generator import generate_signal
        s2 = generate_signal(_raw(), {'use_weighted_scoring': True,
                                      'score_buy_threshold': 101.0,
                                      'score_sell_threshold': 101.0})
        assert s2['signal'] != 'BUY'
        assert s2['signal'] != 'SELL'

    def test_source_has_no_own_scoring(self):
        """源码级: S2 不再自带打分累加 (单一真相源)"""
        src = (SKILLS / 'daily_signal_generator.py').read_text(encoding='utf-8')
        assert 'buy_score +=' not in src
        assert 'sell_score +=' not in src
        assert 'from signal_generator import SignalGenerator' in src


class TestS2RegimeWiring:
    """优化结果 manifest → 体制参数 → 评分模式 (E-P1 #19 与 S1 合并后的接线)"""

    @staticmethod
    def _manifest(tmp_path, use_weighted=None):
        import json
        payload = {'systems': [{
            'name': 'g', 'applicable_regimes': ['BULL'],
            'params': {'buy_threshold': 2.0, 'ma_slow': 20},
        }]}
        if use_weighted is not None:
            payload['use_weighted_scoring'] = use_weighted
        path = tmp_path / 'optimization_result.json'
        path.write_text(json.dumps(payload), encoding='utf-8')
        return path

    @staticmethod
    def _gen():
        from daily_signal_generator import DailySignalGenerator
        gen = DailySignalGenerator.__new__(DailySignalGenerator)
        gen.systems = {}
        gen.default_params = {}
        return gen

    def test_manifest_flag_injected_into_params(self, tmp_path):
        gen = self._gen()
        gen.load_systems(str(self._manifest(tmp_path, True)))
        assert gen.get_params_for_regime('BULL')['use_weighted_scoring'] is True

    def test_legacy_manifest_stays_vote_mode(self, tmp_path):
        gen = self._gen()
        gen.load_systems(str(self._manifest(tmp_path)))
        assert gen.get_params_for_regime('BULL')['use_weighted_scoring'] is False
