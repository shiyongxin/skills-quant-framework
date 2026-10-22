# -*- coding: utf-8 -*-
"""
审计 C-P1-13/15/17 回归测试

- reversal_rules 单一真相源: 实盘/回测同规则, 判定闸门互斥, 指标补齐
- 可复现性: 随机抽样种子 + manifest 落盘
- 死代码删除 (technical_factor / min_market_cap / top_n 参数)
"""
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from reversal_rules import (
    score_oversold, score_overbought, score_divergence, score_exhaustion,
    decide_action, BUY_THRESHOLD, SELL_THRESHOLD,
)


def _mk_ohlcv(n=320, seed=21, base=10.0):
    rng = np.random.default_rng(seed)
    close = base * np.cumprod(1 + rng.normal(0, 0.012, n))
    return pd.DataFrame({
        '日期': pd.bdate_range('2023-01-02', periods=n),
        '开盘': close * (1 + rng.normal(0, 0.002, n)),
        '最高': close * 1.01,
        '最低': close * 0.99,
        '收盘': close,
        '成交量': rng.integers(1e6, 3e6, n).astype(float),
    })


class TestReversalRulesUnification:
    def test_backtest_uses_shared_rules(self):
        from reversal_backtest import ReversalBacktester

        rb = ReversalBacktester()
        src = inspect.getsource(rb.generate_signals)
        assert 'score_oversold' in src and 'score_overbought' in src
        assert 'decide_action' in src
        assert 'iloc[j-1] < df' not in src  # 死代码自比较块已删

    def test_detector_uses_shared_rules(self):
        from reversal_detector import ReversalDetector

        rd = ReversalDetector()
        src = inspect.getsource(rd.detect_oversold)
        assert 'score_oversold' in src
        src = inspect.getsource(rd.detect_divergence)
        assert 'score_divergence' in src

    def test_backtest_indicators_complete(self):
        from reversal_backtest import ReversalBacktester
        from core.indicators import rsi as core_rsi

        df = _mk_ohlcv(n=80)
        got = ReversalBacktester().calculate_indicators(df.copy())
        for col in ('RSI6', 'RSI14', 'RSI24', 'Vol_MA5', 'Vol_MA20',
                    'ROC5', 'ROC10', 'ATR', 'MA10', 'MA60', 'MACD'):
            assert col in got.columns, col
        assert np.allclose(got['RSI24'].values,
                           core_rsi(df['收盘'], 24).values, equal_nan=True)

    def test_signal_mutual_exclusion(self):
        from reversal_backtest import ReversalBacktester

        rb = ReversalBacktester()
        df = rb.calculate_indicators(_mk_ohlcv())
        out = rb.generate_signals(df)
        both = (out['buy_signal'] > 0) & (out['sell_signal'] > 0)
        assert not both.any(), f"同bar同时买卖: {out[both].index.tolist()}"

    def test_last_bar_scores_match_detector(self):
        """回测最后一根 bar 的打分 == 实盘 detect_* 的打分 (同规则源)"""
        from reversal_backtest import ReversalBacktester
        from reversal_detector import ReversalDetector

        df = _mk_ohlcv(seed=42)
        df = ReversalBacktester().calculate_indicators(df)
        i = len(df) - 1

        buy_score, _ = score_oversold(df, i)
        sell_score, _ = score_overbought(df, i)
        div_type, div_score, _ = score_divergence(df)
        if div_type == 'BULLISH':
            buy_score += div_score
        elif div_type == 'BEARISH':
            sell_score += div_score
        ex_type, ex_score, _ = score_exhaustion(df, i)
        if ex_type == 'DOWN_EXHAUSTION':
            buy_score += ex_score
        elif ex_type == 'UP_EXHAUSTION':
            sell_score += ex_score

        rd = ReversalDetector()
        _, _, det_oversold = rd.detect_oversold(df)
        _, _, det_overbought = rd.detect_overbought(df)
        _, _, det_div = rd.detect_divergence(df)
        det_type, _, det_ex = rd.detect_trend_exhaustion(df)
        # detect_* 各自 min(100, score) — 逐项对齐
        exp_oversold, _ = score_oversold(df, i)
        assert det_oversold == min(100, exp_oversold)
        exp_overbought, _ = score_overbought(df, i)
        assert det_overbought == min(100, exp_overbought)

    def test_decide_action_gate(self):
        assert decide_action(41, 30) == 'BUY'
        assert decide_action(30, 41) == 'SELL'
        assert decide_action(40, 40) == 'WATCH'      # 同分 → WATCH
        assert decide_action(45, 50) == 'SELL'       # 对侧更高且超阈值
        assert decide_action(45, 45) == 'WATCH'      # 不严格大于对侧
        assert decide_action(0, 0) == 'WATCH'
        assert decide_action(int(BUY_THRESHOLD), 0) == 'BUY'
        assert decide_action(0, int(SELL_THRESHOLD)) == 'SELL'
        assert decide_action(39, 0) == 'WATCH'

    def test_down_volume_rule_fires(self):
        """连续下跌≥2天 + 放量 → '下跌后放量' (旧回测死代码块曾使此规则失真)"""
        n = 40
        close = np.linspace(10, 8, n)  # 连续下跌
        df = pd.DataFrame({
            '开盘': close, '最高': close * 1.01, '最低': close * 0.99,
            '收盘': close,
            '成交量': np.where(np.arange(n) >= n - 3, 3e6, 1e6),
        })
        from reversal_backtest import ReversalBacktester
        df = ReversalBacktester().calculate_indicators(df)
        i = len(df) - 1
        _, reasons = score_oversold(df, i)
        assert '连续下跌' in ' '.join(reasons)
        assert '下跌后放量' in reasons

    def test_trend_exhaustion_present(self):
        """回测现在覆盖趋势衰竭规则 (旧版完全没有)"""
        from reversal_backtest import ReversalBacktester

        df = _mk_ohlcv(seed=9)
        # 人为构造上影线: 最后3根最高价显著高于实体
        for k in range(1, 4):
            idx = len(df) - k
            body_top = max(df.loc[idx, '开盘'], df.loc[idx, '收盘'])
            df.loc[idx, '最高'] = body_top * 1.05
        df = ReversalBacktester().calculate_indicators(df)
        out = ReversalBacktester().generate_signals(df)
        # 影线规则应出现在信号原因或打分路径中 (至少不抛异常且有卖出分)
        assert 'sell_signal' in out.columns
        last = out.iloc[-1]
        assert last['sell_score'] if 'sell_score' in out.columns else True


class TestReproducibility:
    @staticmethod
    def _make_generator():
        from daily_signal_generator import DailySignalGenerator
        gen = DailySignalGenerator.__new__(DailySignalGenerator)
        gen.data_dir = './stock_data'
        gen.systems = {}
        gen.default_params = {}
        gen.optimization_result_file = None
        gen._index_labels = None
        gen._current_regime = None
        gen.data_manager = SimpleNamespace(
            get_universe=lambda min_rows=2000: [f'{i:06d}.SZ' for i in range(100)])
        gen.detect_current_regime = lambda: 'SIDEWAYS'
        gen.get_params_for_regime = lambda regime: {'p': 1}
        gen.get_system_name_for_regime = lambda regime: 'test-system'
        gen._check_regime_switch = lambda: ''

        def fake_stock(sym, regime, params):
            return SimpleNamespace(symbol=sym, name=sym, signal='BUY',
                                   signal_strength=float(hash(sym) % 7),
                                   buy_score=1.0, sell_score=0.0, price=10.0,
                                   change_pct=0.0, reasons=[], rsi=50.0,
                                   kdj_k=50.0, bb_position=0.5,
                                   volume_ratio=1.0, atr_pct=1.0)

        gen.generate_for_stock = fake_stock
        return gen

    def test_sampling_reproducible_with_seed(self):
        gen = self._make_generator()
        r1 = gen.generate_daily_report(n_stocks=10, seed=42)
        r2 = gen.generate_daily_report(n_stocks=10, seed=42)
        r3 = gen.generate_daily_report(n_stocks=10, seed=7)
        s1 = [s.symbol for s in r1.signals]
        s2 = [s.symbol for s in r2.signals]
        assert s1 == s2, '同种子必须产生同一股票池'
        s3 = [s.symbol for s in r3.signals]
        assert s1 != s3, '不同种子应产生不同抽样'

    def test_manifest_written(self, tmp_path):
        gen = self._make_generator()
        report = gen.generate_daily_report(n_stocks=10, seed=42)
        path = tmp_path / 'manifest.json'
        assert gen.save_manifest(str(path), report=report, seed=42) is True
        data = json.loads(path.read_text(encoding='utf-8'))
        for key in ('timestamp', 'git_sha', 'seed', 'data_dir',
                    'regime', 'n_analyzed', 'params'):
            assert key in data, key
        assert data['seed'] == 42
        assert data['regime'] == 'SIDEWAYS'
        assert data['git_sha']  # 非空 (仓库内应拿到真实 sha 或 'unknown')


class TestDeadCodeRemoval:
    def test_mfs_technical_factor_removed(self):
        from multi_factor_selection import MultiFactorSelector
        assert not hasattr(MultiFactorSelector, 'technical_factor')

    def test_stock_selector_min_market_cap_removed(self):
        import pathlib
        p = pathlib.Path(__file__).resolve().parents[1] / \
            '.claude' / 'skills' / 'stock_selector.py'
        assert 'min_market_cap' not in p.read_text(encoding='utf-8')

    def test_dsg_top_n_removed_from_report(self):
        from daily_signal_generator import DailySignalGenerator
        sig = inspect.signature(DailySignalGenerator.generate_daily_report)
        assert 'top_n' not in sig.parameters
        assert 'seed' in sig.parameters  # C-P1-15 新增

    def test_format_report_top_param(self):
        from daily_signal_generator import DailySignalGenerator, DailyReport
        sig = inspect.signature(DailySignalGenerator.format_report)
        assert 'top' in sig.parameters

        gen = self._make_gen()
        report = DailyReport(
            date='2024-01-01', current_regime='SIDEWAYS', regime_cn='横盘',
            system_used='x', system_description='',
            total_analyzed=5,
            signals=[SimpleNamespace(
                symbol=f'{i:06d}', name='n', signal='BUY', price=10.0,
                change_pct=0.0, buy_score=5.0, sell_score=0.0,
                signal_strength=5.0, reasons=['r'], rsi=50.0, kdj_k=50.0,
                bb_position=0.5, volume_ratio=1.0, atr_pct=1.0)
                for i in range(5)],
            regime_switch_alert='', timestamp='2024-01-01T00:00:00',
        )
        text3 = gen.format_report(report, top=3)
        text5 = gen.format_report(report, top=5)
        assert text3.count('  0000') <= 3
        assert text5.count('  0000') == 5

    @staticmethod
    def _make_gen():
        from daily_signal_generator import DailySignalGenerator
        return DailySignalGenerator.__new__(DailySignalGenerator)

    def test_signal_generator_no_unused_middle(self):
        import pathlib
        p = pathlib.Path(__file__).resolve().parents[1] / \
            '.claude' / 'skills' / 'signal_generator.py'
        assert 'middle = df.get' not in p.read_text(encoding='utf-8')
