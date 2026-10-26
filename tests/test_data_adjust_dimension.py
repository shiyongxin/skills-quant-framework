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
        raw = mgr.load('600000')
        assert len(raw) == 3
        qfq = mgr.load('600000', adjust='qfq')
        assert len(qfq) == 0

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
