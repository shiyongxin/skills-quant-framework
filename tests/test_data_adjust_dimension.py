# -*- coding: utf-8 -*-
"""复权维度 + 存量数据清洗测试（审计 P0-4）。

覆盖:
- core.fetch_result: adjust 维度随结果记录
- historical_data_manager: 复权口径进文件名/元数据; load 缺口径时返回空
  (不拿不复权冒充前复权)
- data_cleaner: 单位判定 (股/手/元/万元) + 结构清洗 + 除权跳空只标记
"""
import json

import pandas as pd
import pytest

from pathlib import Path as _Path

_SKILLS_PATH = _Path(__file__).resolve().parents[1] / '.claude' / 'skills'

from core.fetch_result import FetchResult
from data_cleaner import (clean_ohlcv_frame, detect_units,
                          find_suspicious_jumps, scan_directory)


def _frame(volume=1_000_000.0, amount=10_000_000.0, close=10.0, n=30):
    return pd.DataFrame({
        '日期': pd.bdate_range('2024-01-01', periods=n),
        '开盘': close, '最高': close * 1.01, '最低': close * 0.99,
        '收盘': close, '成交量': volume, '成交额': amount,
    })


class TestFetchResultAdjust:
    def test_adjust_recorded(self):
        r = FetchResult.success(_frame(), source='x', adjust='qfq')
        assert r.adjust == 'qfq'
        assert r.ok

    def test_failure_carries_adjust(self):
        r = FetchResult.failure('boom', source='x', adjust='hfq')
        assert r.adjust == 'hfq'
        assert not r.ok and r.error == 'boom'

    def test_default_adjust_none(self):
        assert FetchResult(ok=True).adjust is None


class TestHistoricalDataManagerAdjustDimension:
    def test_path_includes_adjust(self, tmp_path):
        from historical_data_manager import HistoricalDataManager
        mgr = HistoricalDataManager(data_dir=str(tmp_path))
        raw = mgr._get_parquet_path('600000')
        qfq = mgr._get_parquet_path('600000', 'qfq')
        hfq = mgr._get_parquet_path('600000', 'hfq')
        assert raw.name == '600000.parquet'
        assert qfq.name == '600000_qfq.parquet'
        assert hfq.name == '600000_hfq.parquet'
        assert len({raw, qfq, hfq}) == 3

    def test_adjust_tag_normalization(self, tmp_path):
        from historical_data_manager import HistoricalDataManager
        mgr = HistoricalDataManager(data_dir=str(tmp_path))
        assert mgr._adjust_tag('') == ''
        assert mgr._adjust_tag('QFQ') == 'qfq'
        assert mgr._adjust_tag('none') == ''
        assert mgr._adjust_tag('bfq') == ''

    def test_load_missing_adjust_returns_empty_not_raw(self, tmp_path):
        """缺该复权口径文件 → 空 DF (不拿不复权数据冒充)"""
        pytest.importorskip('pyarrow')
        from historical_data_manager import HistoricalDataManager
        mgr = HistoricalDataManager(data_dir=str(tmp_path))
        pd.DataFrame({'日期': pd.bdate_range('2024-01-01', periods=3),
                      '收盘': [1.0, 2.0, 3.0]}).to_parquet(
            mgr._get_parquet_path('600000'), index=False)
        raw = mgr.load('600000', adjust='')
        assert len(raw) == 3
        qfq = mgr.load('600000', adjust='qfq')
        assert len(qfq) == 0
        default = mgr.load('600000')  # 默认口径 (hfq) 缺文件 → 同样不冒充
        assert len(default) == 0

    def test_metadata_records_adjust(self, tmp_path, monkeypatch):
        pytest.importorskip('pyarrow')
        from historical_data_manager import HistoricalDataManager
        mgr = HistoricalDataManager(data_dir=str(tmp_path))
        new = _frame(n=5)
        monkeypatch.setattr(mgr, '_fetch_from_api',
                            lambda *a, **k: new.copy())
        mgr.fetch_and_cache('600000', adjust='qfq')
        meta = json.loads(mgr.metadata_file.read_text(encoding='utf-8'))
        assert '600000_qfq' in meta['stocks']
        assert meta['stocks']['600000_qfq']['adjust'] == 'qfq'
        assert (tmp_path / 'historical' / '600000_qfq.parquet').exists()


class TestUnitDetection:
    def test_shares_and_yuan(self):
        u = detect_units(_frame())
        assert u['volume_unit'] == 'shares'
        assert u['amount_unit'] == 'yuan'

    def test_lots_detected(self):
        """成交量单位=手 (成交额/成交量 ≈ 价格/100)"""
        u = detect_units(_frame(volume=10_000.0, amount=10_000_000.0))
        assert u['volume_unit'] == 'lots'
        assert u['amount_unit'] == 'yuan'

    def test_wan_yuan_detected(self):
        """成交额单位=万元 (比值 ≈ 价格/1e4)"""
        u = detect_units(_frame(volume=1_000_000.0, amount=1_000.0))
        assert u['amount_unit'] == 'wan_yuan'
        assert u['volume_unit'] == 'shares'

    def test_lots_and_wan_yuan_combined(self):
        """两者同时错 (手 + 万元) → 比值 ≈ 1e-2"""
        u = detect_units(_frame(volume=10_000.0, amount=1_000.0))
        assert u['volume_unit'] == 'lots'
        assert u['amount_unit'] == 'wan_yuan'

    def test_missing_columns_unknown(self):
        u = detect_units(pd.DataFrame({'a': [1, 2, 3]}))
        assert u['volume_unit'] == 'unknown'
        assert u['ratio_source'] == 'missing_columns'


class TestCleanFrame:
    def test_lots_converted_to_shares(self):
        df = _frame(volume=10_000.0, amount=10_000_000.0)
        cleaned, report = clean_ohlcv_frame(df)
        assert report['actions']
        assert cleaned['成交量'].iloc[-1] == pytest.approx(1_000_000.0)

    def test_wan_yuan_converted_to_yuan(self):
        df = _frame(volume=1_000_000.0, amount=1_000.0)
        cleaned, report = clean_ohlcv_frame(df)
        assert cleaned['成交额'].iloc[-1] == pytest.approx(10_000_000.0)

    def test_lots_and_wan_yuan_both_converted(self):
        df = _frame(volume=10_000.0, amount=1_000.0)
        cleaned, report = clean_ohlcv_frame(df)
        assert cleaned['成交量'].iloc[-1] == pytest.approx(1_000_000.0)
        assert cleaned['成交额'].iloc[-1] == pytest.approx(10_000_000.0)

    def test_column_aliases_normalized(self):
        df = pd.DataFrame({'date': pd.bdate_range('2024-01-01', periods=3),
                           'open': 1.0, 'high': 2.0, 'low': 0.5,
                           'close': 1.5, 'volume': 100.0, 'amount': 150.0})
        cleaned, report = clean_ohlcv_frame(df)
        assert '日期' in cleaned.columns and '收盘' in cleaned.columns

    def test_duplicate_dates_deduped(self):
        df = _frame(n=3)
        df = pd.concat([df, df], ignore_index=True)
        cleaned, report = clean_ohlcv_frame(df)
        assert len(cleaned) == 3
        assert any('去重' in a for a in report['actions'])

    def test_pct_change_filled_when_missing(self):
        df = _frame(n=5)
        cleaned, report = clean_ohlcv_frame(df)
        assert '涨跌幅' in cleaned.columns

    def test_suspicious_jump_flagged_not_rewritten(self):
        df = _frame(n=5)
        df.loc[df.index[-1], '收盘'] = 5.0     # 单日 -50% (疑似除权)
        df.loc[df.index[-1], '成交额'] = 5_000_000.0
        cleaned, report = clean_ohlcv_frame(df)
        assert report['warnings']
        assert any('疑似除权' in w for w in report['warnings'])
        # 价格不被改写 (无除权因子不可还原)
        assert cleaned['收盘'].iloc[-1] == pytest.approx(5.0)

    def test_find_suspicious_jumps(self):
        df = _frame(n=4)
        df.loc[df.index[-1], '收盘'] = 4.0
        jumps = find_suspicious_jumps(df)
        assert len(jumps) == 1
        assert abs(jumps[0]['pct']) > 20

    def test_adjusted_file_skips_unit_conversion(self):
        """复权文件不做单位判定: 收盘被因子缩放 → 比值结构性失真,
        按不复权阈值归一会写坏量额 (实测 000002_hfq ratio 0.0098
        落入手+万元区间, 隐含因子仅 101.6)."""
        # ratio = amount/volume/close = 0.01 → 不复权阈值会判 手+万元
        df = _frame(volume=1_000_000.0, amount=100_000.0, close=10.0)
        cleaned_raw, rep_raw = clean_ohlcv_frame(df.copy())
        assert rep_raw['units_detected']['volume_unit'] == 'lots'
        # 同一份数据标 hfq → 跳过判定, 量额逐位不变
        cleaned, report = clean_ohlcv_frame(df.copy(), adjust='hfq')
        assert cleaned['成交量'].iloc[-1] == pytest.approx(1_000_000.0)
        assert cleaned['成交额'].iloc[-1] == pytest.approx(100_000.0)
        assert not any('单位' in a for a in report['actions'])
        assert report['units_detected']['ratio_source'] == \
            'adjusted_close_not_verifiable'
        assert any('不做单位判定' in w for w in report['warnings'])

    def test_adjusted_file_jump_warning_not_refetch_advice(self):
        """复权文件的大波动不再建议"按复权口径重新取数" (它已经是)"""
        df = _frame(n=5)
        df.loc[df.index[-1], '收盘'] = 5.0     # -50%
        df.loc[df.index[-1], '成交额'] = 5_000_000.0
        _, report = clean_ohlcv_frame(df, adjust='hfq')
        assert report['warnings'], "应仍标记波动 (只标记不改写)"
        joined = ' '.join(report['warnings'])
        assert '疑似除权' not in joined
        assert '请按复权口径重新取数' not in joined
        # 不复权文件仍给正确的重新取数建议
        _, rep_raw = clean_ohlcv_frame(df.copy())
        assert any('请按复权口径重新取数' in w for w in rep_raw['warnings'])


class TestScanDirectory:
    def test_scan_empty_dir(self, tmp_path):
        assert scan_directory(str(tmp_path)) == []

    def test_scan_reports_files(self, tmp_path):
        pytest.importorskip('pyarrow')
        hist = tmp_path / 'historical'
        hist.mkdir(parents=True)
        _frame(n=5).to_parquet(hist / '600000.parquet', index=False)
        reports = scan_directory(str(tmp_path), dry_run=True)
        assert len(reports) == 1
        assert reports[0]['file'] == '600000.parquet'
        assert reports[0]['adjust'] == ''

    def test_scan_detects_adjust_suffix(self, tmp_path):
        pytest.importorskip('pyarrow')
        hist = tmp_path / 'historical'
        hist.mkdir(parents=True)
        _frame(n=5).to_parquet(hist / '600000_qfq.parquet', index=False)
        reports = scan_directory(str(tmp_path), dry_run=True)
        assert reports[0]['adjust'] == 'qfq'


class TestDefaultHfqWiring:
    """数据入口默认后复权 —— 产品决策 2026-10-30 (台账 §5.4)。

    原则: 回测/信号/选择分析链默认 DEFAULT_ADJUST('hfq') (除权日无虚假
    跳空、增量缓存追加永远正确); 真实价格场景 (持仓成本对比、实时监控)
    必须显式 adjust='' —— 由本组门禁双向钉死。
    """

    def test_constant_is_hfq(self):
        from core.fetch_result import DEFAULT_ADJUST
        assert DEFAULT_ADJUST == 'hfq'

    def test_hdm_entry_defaults_follow_constant(self):
        import inspect
        from core.fetch_result import DEFAULT_ADJUST
        from historical_data_manager import HistoricalDataManager as M
        for name in ('fetch_and_cache', 'load', 'get_daily_result',
                     'batch_fetch', '_fetch_from_api'):
            default = inspect.signature(
                getattr(M, name)).parameters['adjust'].default
            assert default == DEFAULT_ADJUST, f'{name}: {default!r}'

    def test_fetcher_entry_defaults_follow_constant(self):
        import inspect
        from core.fetch_result import DEFAULT_ADJUST
        from stock_data_fetcher import StockDataFetcher as F
        for name in ('get_quote_data', 'get_quote_result',
                     'get_quote_data_fallback'):
            default = inspect.signature(
                getattr(F, name)).parameters['adjust'].default
            assert default == DEFAULT_ADJUST, f'{name}: {default!r}'

    def test_analysis_selectors_follow_constant(self):
        import inspect
        from core.fetch_result import DEFAULT_ADJUST
        from long_term_selector import LongTermSelector
        from reversal_detector import ReversalDetector
        for cls in (LongTermSelector, ReversalDetector):
            default = inspect.signature(
                cls.get_stock_data).parameters['adjust'].default
            assert default == DEFAULT_ADJUST, cls.__name__

    def test_position_analyzer_stays_raw_and_forwards(self):
        """持仓成本是真实价格 → 默认不复权, 且透传给取数层 (不许被默认
        hfq 顶掉 —— 顶掉后浮盈浮亏用虚增的 hfq 现价对比真实成本)。"""
        import inspect
        from position_analyzer import PositionAnalyzer
        default = inspect.signature(
            PositionAnalyzer.get_stock_data).parameters['adjust'].default
        assert default == ''

        seen = {}

        class _Fetch:
            def get_quote_result(self, symbol, days=120, adjust=''):
                seen['adjust'] = adjust
                from core.fetch_result import FetchResult
                return FetchResult.failure('stub')

        PositionAnalyzer(fetcher=_Fetch()).get_stock_data('600000')
        assert seen['adjust'] == ''

    def test_real_time_monitor_explicit_raw_source(self):
        """实时告警与实时报价同口径: 源码钉死 adjust='' (行为断言见
        tests/test_web_presentation_p2 同类桩)。"""
        import ast as _ast
        src = (_SKILLS_PATH / 'real_time_monitor.py').read_text(
            encoding='utf-8')
        tree = _ast.parse(src)
        hits = [n for n in _ast.walk(tree)
                if isinstance(n, _ast.Call)
                and isinstance(n.func, _ast.Attribute)
                and n.func.attr == 'get_quote_result'
                and any(k.arg == 'adjust'
                        and isinstance(k.value, _ast.Constant)
                        and k.value.value == ''
                        for k in n.keywords)]
        assert hits, 'real_time_monitor 必须显式 adjust="" (实时口径)'

    def test_cli_adjust_flag_defaults_to_constant_source(self):
        """CLI --adjust 缺省 = DEFAULT_ADJUST (源码级; 门禁禁 getattr)。"""
        src = (_SKILLS_PATH / 'historical_data_manager.py').read_text(
            encoding='utf-8')
        assert src.count("add_argument('--adjust', default=DEFAULT_ADJUST") \
            == 3, 'fetch/batch/delisted-fetch 三个子命令都要有 --adjust'
        assert src.count('adjust=args.adjust') == 3, \
            '三个分派点都要把 args.adjust 透传下去 (禁 getattr)'
        assert 'getattr(args' not in src

    def test_fetch_and_cache_default_writes_hfq(self, tmp_path,
                                                monkeypatch):
        pytest.importorskip('pyarrow')
        from historical_data_manager import HistoricalDataManager
        mgr = HistoricalDataManager(data_dir=str(tmp_path))
        monkeypatch.setattr(mgr, '_fetch_from_api',
                            lambda *a, **k: _frame(n=5).copy())
        mgr.fetch_and_cache('600000')
        hist = tmp_path / 'historical'
        assert (hist / '600000_hfq.parquet').exists()
        assert not (hist / '600000.parquet').exists(), \
            '默认口径写 _hfq, 不得落不复权文件名'
        meta = json.loads(mgr.metadata_file.read_text(encoding='utf-8'))
        assert meta['stocks']['600000_hfq']['adjust'] == 'hfq'
        assert meta['stock_count'] == 1, 'stock_count 计唯一基础代码'

    def test_universe_strips_labels_and_dedupes(self, tmp_path):
        from historical_data_manager import HistoricalDataManager
        mgr = HistoricalDataManager(data_dir=str(tmp_path))
        row = {'first_date': '2020-01-01', 'last_date': '2026-01-02',
               'row_count': 3000, 'updated': 'x'}
        mgr.metadata['stocks'] = {
            '600000': dict(row), '600000_hfq': dict(row),
            '000001_hfq': dict(row),
        }
        got = mgr.get_universe(min_history_days=0, min_rows=0)
        assert got == ['000001', '600000'], \
            '口径标签必须剥掉且同股去重 (不得出现 600000_hfq 假代码)'
        assert mgr.get_all_symbols() == ['000001', '600000']
        assert mgr.metadata['stocks'] and len(
            {mgr._base_symbol(k) for k in mgr.metadata['stocks']}) == 2

    def test_universe_meta_counts_unique_bases(self, tmp_path):
        from historical_data_manager import HistoricalDataManager
        mgr = HistoricalDataManager(data_dir=str(tmp_path))
        row = {'first_date': '2020-01-01', 'last_date': '2026-01-02',
               'row_count': 3000, 'updated': 'x'}
        mgr.metadata['stocks'] = {
            '600000': dict(row), '600000_hfq': dict(row)}
        meta = mgr._universe_meta()
        assert meta['n_cached_stocks'] == 1, '同一股票多口径不是多只股票'

    def test_has_stock_any_adjust_accepts_labeled_keys(self, tmp_path):
        """证据/补齐判定: 只取过 hfq 的股票也算已缓存 (D1 规则②不误报)。"""
        from historical_data_manager import HistoricalDataManager
        mgr = HistoricalDataManager(data_dir=str(tmp_path))
        mgr.metadata['stocks'] = {'600625_hfq': {'adjust': 'hfq'}}
        assert mgr._has_stock_any_adjust('600625')
        assert not mgr._has_stock_any_adjust('000001')
        mgr.metadata['stocks'] = {'600625': {}}
        assert mgr._has_stock_any_adjust('600625')

    def test_base_symbol_helper(self):
        from historical_data_manager import HistoricalDataManager as M
        assert M._base_symbol('600000_hfq') == '600000'
        assert M._base_symbol('600000_qfq') == '600000'
        assert M._base_symbol('600000') == '600000'
        assert M._base_symbol('900953') == '900953'
        # 非口径后缀不得被误剥 (rpartition 只认 qfq/hfq 标签)
        assert M._base_symbol('sh600000') == 'sh600000'


class TestEarlyReturnRegistersMeta:
    """文件在但元数据键缺 (中断写盘) → "无新数据"早退路径必须补登记,
    否则 universe/validate/status 对这份文件永久失明 (2026-10-30 实测
    13 只 hfq 文件因批量被中断而缺键)。"""

    def test_early_return_registers_missing_key(self, tmp_path,
                                                monkeypatch):
        pytest.importorskip('pyarrow')
        from historical_data_manager import HistoricalDataManager
        mgr = HistoricalDataManager(data_dir=str(tmp_path))
        frame = _frame(n=5)   # 2024-01-01 ~ 2024-01-05
        # 文件已存在, 元数据缺键 (模拟中断的批量写盘)
        frame.to_parquet(mgr._get_parquet_path('600000', 'hfq'),
                         index=False)
        assert '600000_hfq' not in mgr.metadata['stocks']

        monkeypatch.setattr(mgr, '_fetch_from_api',
                            lambda *a, **k: pd.DataFrame())  # 无新数据
        out = mgr.fetch_and_cache('600000', adjust='hfq')
        assert len(out) == 5
        entry = mgr.metadata['stocks'].get('600000_hfq')
        assert entry is not None, '早退路径必须补登记缺失的口径键'
        assert entry['adjust'] == 'hfq'
        assert entry['row_count'] == 5
        # 落盘后读回仍在 (persist 默认 True)
        import json as _json
        on_disk = _json.loads(mgr.metadata_file.read_text(encoding='utf-8'))
        assert '600000_hfq' in on_disk['stocks']
