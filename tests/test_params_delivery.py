# -*- coding: utf-8 -*-
"""参数下发契约 + signal_generator 评分双模式 (审计 E-P1 #19 闭环 P1+P2).

- optimized_params: best_params JSON → 生产参数字典 (systems 选择/软校验/
  use_weighted_scoring 标注); save_results 落盘新增模式键
- signal_generator: use_weighted_scoring 双模式 (默认 False 生产零变化),
  综合信号走 weighted_factor_scores 列名适配, 便捷函数 params 直通
"""
import json

import numpy as np
import pandas as pd
import pytest

from optimized_params import load_optimized_params, list_systems
from signal_generator import SignalGenerator
import signal_generator as sg_module
from core.indicators import rsi as core_rsi

from tests.test_weighted_scoring import _ohlcv, _swing_ohlcv


def _result_json(tmp_path, systems, weighted=True):
    payload = {
        'timestamp': '2026-10-24T00:00:00', 'seed': 42,
        'use_weighted_scoring': weighted, 'systems': systems,
    }
    path = tmp_path / 'result.json'
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return str(path)


def _system(params, regime=None, name='s'):
    return {'name': name, 'description': 'd', 'applicable_regimes': ['GLOBAL'],
            'params': params, 'fitness_scores': {str(regime): 0.5},
            'confidence': 0.6, 'sample_count': 10, 'regime': regime}


class TestLoadOptimizedParams:
    def test_prefers_global_system(self, tmp_path):
        path = _result_json(tmp_path, [
            {'regime': 'BULL', 'params': {'rsi_period': 9}, 'name': 'bull'},
            {'regime': None, 'params': {'rsi_period': 7}, 'name': 'global'},
        ])
        params = load_optimized_params(path)
        assert params['rsi_period'] == 7
        assert params['use_weighted_scoring'] is True

    def test_regime_selection(self, tmp_path):
        path = _result_json(tmp_path, [
            {'regime': 'BULL', 'params': {'rsi_period': 9}, 'name': 'bull'},
            {'regime': 'BEAR', 'params': {'rsi_period': 5}, 'name': 'bear'},
        ])
        assert load_optimized_params(path, regime='BULL')['rsi_period'] == 9
        assert load_optimized_params(path, regime='BEAR')['rsi_period'] == 5

    def test_missing_regime_raises_with_available(self, tmp_path):
        path = _result_json(tmp_path, [
            {'regime': 'BULL', 'params': {'rsi_period': 9}}])
        with pytest.raises(ValueError, match="可用: \\['BULL'\\]"):
            load_optimized_params(path, regime='CRASH')

    def test_multiple_non_global_without_regime_raises(self, tmp_path):
        path = _result_json(tmp_path, [
            {'regime': 'BULL', 'params': {'a': 1}},
            {'regime': 'BEAR', 'params': {'a': 2}},
        ])
        with pytest.raises(ValueError, match='regime='):
            load_optimized_params(path)

    def test_old_json_defaults_weighted_true(self, tmp_path):
        path = tmp_path / 'old.json'
        path.write_text(json.dumps(
            {'systems': [{'regime': None, 'params': {'a': 1}}]}), encoding='utf-8')
        assert load_optimized_params(str(path))['use_weighted_scoring'] is True

    def test_explicit_flag_overrides_json(self, tmp_path):
        path = _result_json(tmp_path,
                            [{'regime': None, 'params': {'a': 1}}], weighted=True)
        out = load_optimized_params(path, use_weighted_scoring=False)
        assert out['use_weighted_scoring'] is False

    def test_empty_systems_raises(self, tmp_path):
        path = _result_json(tmp_path, [])
        with pytest.raises(ValueError, match='systems'):
            load_optimized_params(path)

    def test_missing_params_raises(self, tmp_path):
        path = _result_json(tmp_path, [{'regime': None, 'params': {}}])
        with pytest.raises(ValueError, match='params'):
            load_optimized_params(path)

    def test_list_systems_summary(self, tmp_path):
        path = _result_json(tmp_path, [
            {'regime': None, 'params': {'a': 1}, 'name': 'g',
             'fitness_scores': {'GLOBAL': 0.4}},
            {'regime': 'BULL', 'params': {'a': 2}, 'name': 'b',
             'fitness_scores': {'BULL': 0.6}},
        ])
        summary = list_systems(path)
        assert [s['name'] for s in summary] == ['g', 'b']
        assert summary[1]['fitness'] == 0.6

    def test_save_results_records_flag_and_roundtrip(self, tmp_path):
        from optimization_engine import (
            OptimizationEngine, IndicatorSystem, Individual, OptimizationResult)
        engine = OptimizationEngine(seed=1)
        system = IndicatorSystem(
            name='s', description='d', applicable_regimes=['GLOBAL'],
            params={'rsi_period': 7}, fitness_scores={'GLOBAL': 0.5},
            confidence=0.6, sample_count=10)
        engine.results = {'GLOBAL': OptimizationResult(
            regime='GLOBAL',
            best_individual=Individual(params={'rsi_period': 7}, fitness=0.5),
            best_system=system, all_systems=[system],
            generations_run=1, total_time_sec=0.1, convergence_gen=1)}
        path = tmp_path / 'opt.json'
        engine.save_results(str(path))
        data = json.loads(path.read_text(encoding='utf-8'))
        assert data['use_weighted_scoring'] is True
        params = load_optimized_params(str(path))
        assert params['rsi_period'] == 7
        assert params['use_weighted_scoring'] is True


def _indicator_frame(df):
    """按 stock_data_fetcher.calculate_technical_indicators 同名口径补指标列."""
    close, high, low = df['收盘'], df['最高'], df['最低']
    out = df.copy()
    out['MA5'] = close.rolling(5).mean()
    out['MA10'] = close.rolling(10).mean()
    out['MA20'] = close.rolling(20).mean()
    ema_f = close.ewm(span=12, adjust=False).mean()
    ema_s = close.ewm(span=26, adjust=False).mean()
    out['MACD'] = ema_f - ema_s
    out['MACD_Signal'] = out['MACD'].ewm(span=9, adjust=False).mean()
    out['RSI'] = core_rsi(close, 14)
    low_n = low.rolling(9).min()
    high_n = high.rolling(9).max()
    rsv = (close - low_n) / (high_n - low_n) * 100
    out['K'] = rsv.ewm(span=3, adjust=False).mean()
    out['D'] = out['K'].ewm(span=3, adjust=False).mean()
    mid = close.rolling(20).mean()
    std = close.rolling(20).std()
    out['BB_Upper'] = mid + 2 * std
    out['BB_Lower'] = mid - 2 * std
    return out


class TestSignalGeneratorDualMode:
    def test_default_vote_unchanged(self):
        df = _indicator_frame(_ohlcv(150))
        s_default = SignalGenerator().generate_signals(df)
        s_off = SignalGenerator(use_weighted_scoring=False).generate_signals(df)
        for col in ('signal_buy', 'signal_sell', 'signal_strength'):
            pd.testing.assert_series_equal(s_default[col], s_off[col])

    def test_weighted_differs_from_vote(self):
        df = _indicator_frame(_swing_ohlcv())
        vote = SignalGenerator().generate_signals(df)
        wtd = SignalGenerator(use_weighted_scoring=True).generate_signals(df)
        assert not vote['signal_buy'].equals(wtd['signal_buy'])
        assert not vote['signal_sell'].equals(wtd['signal_sell'])
        # 报告层强度尺度保持 -10..10
        assert wtd['signal_strength'].between(-10, 10).all()

    def test_score_thresholds_gate(self):
        df = _indicator_frame(_swing_ohlcv())
        blocked = SignalGenerator(
            use_weighted_scoring=True,
            scoring_params={'score_buy_threshold': 101,
                            'score_sell_threshold': 101},
        ).generate_signals(df)
        assert (blocked['signal_buy'] == 0).all()
        assert (blocked['signal_sell'] == 0).all()

    def test_weighted_missing_columns_raises(self):
        raw = _ohlcv(60)[['日期', '开盘', '最高', '最低', '收盘', '成交量']]
        with pytest.raises(ValueError, match='缺少指标列'):
            SignalGenerator(use_weighted_scoring=True).generate_signals(raw)

    def test_get_latest_signal_weighted_contract(self):
        df = _indicator_frame(_ohlcv(150))
        info = SignalGenerator(use_weighted_scoring=True).get_latest_signal(df)
        assert {'buy_signal', 'sell_signal', 'executable',
                'blocked_reasons', 'skipped_checks'} <= set(info)

    def test_convenience_params_passthrough(self):
        df = _indicator_frame(_ohlcv(150))
        params = {'use_weighted_scoring': True, 'score_buy_threshold': 101,
                  'score_sell_threshold': 101, 'w_trend': 30}
        out = sg_module.generate_signals(df, params)
        assert (out['signal_buy'] == 0).all()
        info = sg_module.get_latest_signal(df, params)
        assert info['buy_signal'] is False
        # 无 params → 与默认投票制逐位一致
        no_params = sg_module.generate_signals(df)
        vote = SignalGenerator().generate_signals(df)
        pd.testing.assert_series_equal(no_params['signal_buy'],
                                       vote['signal_buy'])

    def test_loader_output_drops_into_generator(self, tmp_path):
        path = _result_json(tmp_path, [{'regime': None, 'name': 'g', 'params': {
            'score_buy_threshold': 101, 'score_sell_threshold': 101}}])
        params = load_optimized_params(path)
        df = _indicator_frame(_ohlcv(150))
        out = sg_module.generate_signals(df, params)
        assert (out['signal_buy'] == 0).all()
        assert (out['signal_sell'] == 0).all()
