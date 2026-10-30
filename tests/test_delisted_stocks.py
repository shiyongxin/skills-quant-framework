# -*- coding: utf-8 -*-
"""D1 退市股数据基建门禁 (docs/OPEN_ITEMS_PLAN_2026-10-25.md §5.3)

覆盖四块 (全部离线: 名录/klc/解码一律打桩):

1. **清单基建** (`delisted_stocks`): 归一化 (6位码/B股范围/去重)、落盘读回、
   缺文件 = 不可用 (没查过 ≠ 没有偏差)、覆盖起点 = 各交易所最早记录的
   **最晚者**、刷新全成功才落盘。
2. **取数路由** (`sina_daily`): 仅 akshare **股本步骤确定性崩溃** (demjson
   解 (null), bj/退市同根因) 才回退 klc 直连; 网络类错误原样上抛不回退
   (回退不得掩盖根因 —— 曾因此把"网络失败"救活成成功, 反向失实)。
3. **幸存者偏差证据规则** (`_universe_meta` 四规则): 无清单 / 未补齐 /
   清单过期 / 参考日早于覆盖起点 → 保守 True; 全满足才 False 且带证据。
4. **CLI** (`delisted refresh/status/fetch`): 注入 manager+fetcher 测试,
   不碰仓库默认 data_dir (测试隔离红线)。
"""

from argparse import Namespace
from datetime import datetime, timedelta

import pandas as pd
import pytest

from delisted_stocks import (REGISTRY_MAX_AGE_DAYS, DelistedRegistry,
                             default_registry_path, normalize_delisted_frame,
                             write_registry)
from historical_data_manager import (HistoricalDataManager,
                                     _run_delisted_command)


# ---------------------------------------------------------------- fixtures
def _raw_rows():
    """沪深各一条 + B股一条 (B股 900953 不在框架范围)"""
    return pd.DataFrame([
        {'code': '600625', 'name': 'PT水仙', 'list_date': '1993-01-06',
         'delist_date': '2001-04-25', 'exchange': 'sh',
         'source_event': '暂停上市日期'},
        {'code': '600005', 'name': '武钢股份', 'list_date': '1999-08-03',
         'delist_date': '2017-02-14', 'exchange': 'sh',
         'source_event': '暂停上市日期'},
        {'code': '000018', 'name': '神城A退', 'list_date': '1992-06-16',
         'delist_date': '2020-01-07', 'exchange': 'sz',
         'source_event': '终止上市日期'},
        {'code': '900953', 'name': '凯马B', 'list_date': '1998-06-24',
         'delist_date': '2024-07-05', 'exchange': 'sh',
         'source_event': '暂停上市日期'},
    ])


def _write(tmp_path, rows=None, fetched_at=None):
    df = normalize_delisted_frame(rows if rows is not None else _raw_rows())
    if fetched_at is not None:
        df['fetched_at'] = fetched_at
    path = write_registry(df, tmp_path / 'delisted' / 'delisted_list.csv')
    # write_registry 会重新归一化 (fetched_at=now) → 显式时间需绕过
    if fetched_at is not None:
        df.to_csv(path, index=False, encoding='utf-8-sig')
    return path


def _manager(tmp_path, stocks=None):
    """tmp data_dir 的 HDM (不碰仓库 ./stock_data)"""
    m = HistoricalDataManager(data_dir=str(tmp_path))
    for code, (first, last) in (stocks or {}).items():
        m.metadata['stocks'][code] = {
            'first_date': first, 'last_date': last,
            'row_count': 3000, 'updated': '2026-01-01T00:00:00'}
    return m


def _args(cmd, **kw):
    base = dict(delisted_cmd=cmd, start='19900101', end=None, workers=4,
                delay=0.0, include_b=False, adjust='hfq')
    base.update(kw)
    return Namespace(**base)


# ================================================================ 1. 清单
class TestRegistryNormalizeAndIO:
    def test_normalize_scope_and_dedup(self):
        raw = _raw_rows()
        raw = pd.concat([raw, raw.iloc[[0]]], ignore_index=True)  # 重复行
        raw.loc[len(raw)] = {**raw.iloc[0].to_dict(), 'delist_date': None}
        df = normalize_delisted_frame(raw)
        # 去重 (按 code) + 退市日期缺失的行剔除
        assert sorted(df['code']) == ['000018', '600005', '600625', '900953']
        # B股不在框架股票池范围
        assert dict(zip(df['code'], df['in_scope']))['900953'] is False
        assert all(df[df['code'] != '900953']['in_scope'])
        assert 'fetched_at' in df.columns

    def test_write_load_roundtrip_preserves_fetched_at(self, tmp_path):
        path = _write(tmp_path, fetched_at=pd.Timestamp('2026-01-01 00:00:00'))
        reg = DelistedRegistry.load(path)
        assert reg.available
        # 加载**不得**刷新 fetched_at (否则新鲜度证据永不过期 → 门槛失效)
        assert reg.stats()['fetched_at'].startswith('2026-01-01')
        assert reg.stats()['fresh'] is False
        assert sorted(reg.codes()) == ['000018', '600005', '600625', '900953']
        assert sorted(reg.codes(in_scope=True)) == ['000018', '600005', '600625']
        assert reg.is_delisted('600625') and reg.is_delisted(600005)
        assert not reg.is_delisted('600000')

    def test_missing_file_is_unavailable_not_empty_claim(self, tmp_path):
        reg = DelistedRegistry.load(tmp_path / 'nope' / 'x.csv')
        assert not reg.available
        assert reg.codes() == []
        assert reg.is_delisted('600625') is False      # 没查过 → 不假装有
        st = reg.stats()
        assert st['available'] is False and st['fresh'] is False

    def test_coverage_start_is_max_of_exchange_mins(self, tmp_path):
        """覆盖起点 = 各交易所最早退市记录的**最晚者** (取 min 会对
        另一市的空白期误发 False 声明)。"""
        reg = DelistedRegistry.load(_write(tmp_path))
        st = reg.stats()
        assert st['coverage_start_by_exchange'] == {
            'sh': '2001-04-25', 'sz': '2020-01-07'}
        assert st['coverage_start'] == '2020-01-07'
        # coverage 按**在范围 (A股)** 记录算: B股 900953 (2024) 不计
        assert st['coverage_end'] == '2020-01-07'
        assert st['n'] == 4 and st['n_in_scope'] == 3 and st['n_out_of_scope'] == 1

    def test_refresh_failure_keeps_old_file(self, tmp_path):
        path = _write(tmp_path)
        reg = DelistedRegistry.load(path)
        before = path.read_text(encoding='utf-8')

        def boom():
            raise RuntimeError('网络错误')
        with pytest.raises(RuntimeError):
            reg.refresh(fetcher=boom)
        # 半份/失败不得落盘 (旧清单原样)
        assert path.read_text(encoding='utf-8') == before
        assert DelistedRegistry.load(path).available

    def test_refresh_success_replaces(self, tmp_path):
        reg = DelistedRegistry.load(_write(tmp_path))
        new = pd.DataFrame([{'code': '000004', 'name': '国华退',
                             'list_date': '1993-01-14',
                             'delist_date': '2026-07-14', 'exchange': 'sz',
                             'source_event': '终止上市日期'}])
        reg.refresh(fetcher=lambda: new)
        assert reg.available
        assert reg.codes(in_scope=True) == ['000004']

    def test_default_path_under_data_dir(self):
        assert str(default_registry_path('./stock_data')).replace('\\', '/') \
            == 'stock_data/delisted/delisted_list.csv'


# ================================================================ 2. 路由
class TestAmountStepFallbackRouting:
    """仅股本步骤的确定性崩溃才回退 klc 直连; 其余错误原样上抛。"""

    @staticmethod
    def _demjson_err():
        # 与 akshare.utils.demjson.JSONDecodeError 同名同模块 (实测)
        cls = type('JSONDecodeError', (Exception,), {})
        cls.__module__ = 'akshare.utils.demjson'
        return cls('No value to decode')

    def test_amount_step_failure_falls_back(self, monkeypatch):
        import akshare as ak
        import sina_daily
        calls = {'direct': 0}

        def fake_ak(**kw):
            raise self._demjson_err()

        def fake_direct(symbol, start_date, end_date, adjust=""):
            calls['direct'] += 1
            return 'DIRECT-SENTINEL'

        monkeypatch.setattr(ak, 'stock_zh_a_daily', fake_ak)
        monkeypatch.setattr(sina_daily, '_fetch_klc_direct', fake_direct)
        out = sina_daily.fetch_daily('sz000004', '19900101', '20261030',
                                     adjust='')
        assert out == 'DIRECT-SENTINEL' and calls['direct'] == 1

    def test_other_errors_do_not_fall_back(self, monkeypatch):
        """网络类错误不得被回退掩盖 (曾把"网络失败"救活成成功 → 反向失实)"""
        import akshare as ak
        import sina_daily
        calls = {'direct': 0}

        def fake_ak(**kw):
            raise RuntimeError('network down')

        def fake_direct(symbol, start_date, end_date, adjust=""):
            calls['direct'] += 1
            return 'SHOULD-NOT-BE-CALLED'

        monkeypatch.setattr(ak, 'stock_zh_a_daily', fake_ak)
        monkeypatch.setattr(sina_daily, '_fetch_klc_direct', fake_direct)
        with pytest.raises(RuntimeError, match='network down'):
            sina_daily.fetch_daily('sh600519', '19900101', '20261030')
        assert calls['direct'] == 0

    def test_both_paths_fail_reports_direct_error(self, monkeypatch):
        import akshare as ak
        import sina_daily

        monkeypatch.setattr(ak, 'stock_zh_a_daily',
                            lambda **kw: (_ for _ in ()).throw(self._demjson_err()))
        monkeypatch.setattr(
            sina_daily, '_fetch_klc_direct',
            lambda *a, **k: (_ for _ in ()).throw(ValueError('新浪 klc 无数据')))
        with pytest.raises(RuntimeError) as ei:
            sina_daily.fetch_daily('sz000004', '19900101', '20261030')
        assert 'klc 直连也失败' in str(ei.value)
        assert isinstance(ei.value.__cause__, Exception)  # 根因保留

    def test_failure_classifier(self):
        from sina_daily import _is_amount_step_failure
        assert _is_amount_step_failure(self._demjson_err())
        import json
        assert not _is_amount_step_failure(
            json.JSONDecodeError('Expecting value', 'x', 0))
        assert not _is_amount_step_failure(RuntimeError('network down'))
        assert not _is_amount_step_failure(ValueError('bad symbol'))


# ================================================================ 3. 证据
class TestSurvivorshipEvidenceRules:
    """_universe_meta 四条证据规则: 任一不满足 → 保守 True。"""

    def test_no_registry_conservative_true(self, tmp_path):
        m = _manager(tmp_path, {'600000': ('2005-01-01', '2024-06-28')})
        meta = m.get_universe_meta(min_history_days=1000, min_rows=100)
        assert meta['survivorship_bias'] is True
        assert '退市' in meta['survivorship_note']
        assert meta['delisted_registry']['available'] is False

    def test_incomplete_backfill_stays_true(self, tmp_path):
        _write(tmp_path)   # 3 只在范围 (600625/600005/000018) + 1 B股
        m = _manager(tmp_path, {
            '600625': ('1993-01-06', '2001-04-25'),
            '600000': ('2005-01-01', '2024-06-28'),
        })
        meta = m.get_universe_meta(min_history_days=1000, min_rows=100)
        assert meta['survivorship_bias'] is True
        assert '1/3' in meta['survivorship_note']      # 已补/应补
        assert 'delisted fetch' in meta['survivorship_note']
        assert meta['delisted_registry']['n_cached_in_scope'] == 1

    def test_complete_fresh_covered_claims_false(self, tmp_path):
        _write(tmp_path)   # fetched_at = now (新鲜)
        m = _manager(tmp_path, {
            '600625': ('1993-01-06', '2001-04-25'),
            '600005': ('1999-08-03', '2017-02-14'),
            '000018': ('1992-06-16', '2020-01-07'),
            '600000': ('2005-01-01', '2024-06-28'),
        })
        meta = m.get_universe_meta(min_history_days=1000, min_rows=100,
                                   as_of='2021-06-30')
        assert meta['survivorship_bias'] is False
        assert '已消除' in meta['survivorship_note']
        # 残余限制如实写明 (B股 + 北交所名录缺失)
        assert 'B股' in meta['survivorship_note']
        assert '北交所' in meta['survivorship_note']
        st = meta['delisted_registry']
        assert st['available'] and st['fresh']
        assert st['n_cached_in_scope'] == st['n_in_scope'] == 3

    def test_b_shares_do_not_block_false_claim(self, tmp_path):
        """B股不在框架范围 → 不要求缓存它们 (清单含 900953 未缓存也判 False)"""
        _write(tmp_path)
        m = _manager(tmp_path, {
            '600625': ('1993-01-06', '2001-04-25'),
            '600005': ('1999-08-03', '2017-02-14'),
            '000018': ('1992-06-16', '2020-01-07'),
        })
        meta = m._universe_meta('2021-06-30')
        assert meta['survivorship_bias'] is False
        assert '900953' not in str(meta['delisted_registry']['n_cached_in_scope'])

    def test_stale_registry_stays_true(self, tmp_path):
        old = (datetime.now() - timedelta(
            days=REGISTRY_MAX_AGE_DAYS + 10)).isoformat(sep=' ')
        _write(tmp_path, fetched_at=pd.Timestamp(old))
        m = _manager(tmp_path, {
            '600625': ('1993-01-06', '2001-04-25'),
            '600005': ('1999-08-03', '2017-02-14'),
            '000018': ('1992-06-16', '2020-01-07'),
        })
        meta = m._universe_meta('2021-06-30')
        assert meta['survivorship_bias'] is True
        assert '未刷新' in meta['survivorship_note']
        assert meta['delisted_registry']['fresh'] is False

    def test_ref_before_coverage_stays_true(self, tmp_path):
        """参考日早于清单覆盖起点 → 早期退市记录未知 → 不发 False"""
        _write(tmp_path)
        m = _manager(tmp_path, {
            '600625': ('1993-01-06', '2001-04-25'),
            '600005': ('1999-08-03', '2017-02-14'),
            '000018': ('1992-06-16', '2020-01-07'),
            '600000': ('1986-01-01', '2024-06-28'),
        })
        meta = m.get_universe_meta(min_history_days=1000, min_rows=100,
                                   as_of='1999-06-30')
        assert meta['survivorship_bias'] is True
        assert '早于' in meta['survivorship_note']

    def test_single_exchange_registry_stays_true(self, tmp_path):
        """清单缺一市记录 → 覆盖完整性无法验证 → 保守 True"""
        rows = pd.DataFrame([
            {'code': '600625', 'name': 'PT水仙', 'list_date': '1993-01-06',
             'delist_date': '2001-04-25', 'exchange': 'sh',
             'source_event': '暂停上市日期'},
        ])
        _write(tmp_path, rows=rows)
        m = _manager(tmp_path, {'600625': ('1993-01-06', '2001-04-25')})
        meta = m._universe_meta('2021-06-30')
        assert meta['survivorship_bias'] is True
        assert 'sz' in meta['survivorship_note']


# ================================================================ 4. CLI
class TestDelistedCli:
    def test_refresh_writes_and_reports(self, tmp_path, capsys):
        m = _manager(tmp_path)
        rc = _run_delisted_command(_args('refresh'), m,
                                   fetcher=lambda: _raw_rows())
        out = capsys.readouterr().out
        assert rc == 0 and '[OK]' in out
        st = DelistedRegistry.load(
            default_registry_path(m.data_dir)).stats()
        assert st['available'] and st['n'] == 4 and st['n_in_scope'] == 3

    def test_refresh_failure_keeps_old_and_rc1(self, tmp_path, capsys):
        m = _manager(tmp_path)
        _run_delisted_command(_args('refresh'), m,
                              fetcher=lambda: _raw_rows())
        before = (tmp_path / 'delisted' / 'delisted_list.csv').read_bytes()

        def boom():
            raise RuntimeError('接口 502')
        rc = _run_delisted_command(_args('refresh'), m, fetcher=boom)
        out = capsys.readouterr().out
        assert rc == 1 and '旧清单未动' in out
        assert (tmp_path / 'delisted' / 'delisted_list.csv').read_bytes() \
            == before

    def test_status_without_registry_rc1(self, tmp_path, capsys):
        rc = _run_delisted_command(_args('status'), _manager(tmp_path))
        out = capsys.readouterr().out
        assert rc == 1 and '清单不可用' in out

    def test_status_complete_rc0_incomplete_rc1(self, tmp_path, capsys):
        _write(tmp_path)
        m = _manager(tmp_path, {'600625': ('1993-01-06', '2001-04-25'),
                                '600005': ('1999-08-03', '2017-02-14'),
                                '000018': ('1992-06-16', '2020-01-07')})
        rc = _run_delisted_command(_args('status'), m)
        assert rc == 0 and '3/3' in capsys.readouterr().out
        # 缺一只 → rc1 + 提示补齐命令
        m2 = _manager(tmp_path, {'600625': ('1993-01-06', '2001-04-25')})
        rc = _run_delisted_command(_args('status'), m2)
        out = capsys.readouterr().out
        assert rc == 1 and '尚缺 2 只' in out and 'delisted fetch' in out

    def test_fetch_only_missing_and_skips_b(self, tmp_path, capsys):
        _write(tmp_path)   # 3 A + 1 B
        m = _manager(tmp_path, {'600625': ('1993-01-06', '2001-04-25')})
        seen = {}

        def fake_batch(symbols, start_date=None, end_date=None,
                       delay=0.0, max_workers=4, adjust='hfq'):
            seen['symbols'] = list(symbols)
            seen['adjust'] = adjust
            # 模拟取数落库 (batch 的效果)
            for s in symbols:
                m.metadata['stocks'][s] = {
                    'first_date': '1990-01-01', 'last_date': '2026-07-14',
                    'row_count': 100, 'updated': 'x'}
        m.batch_fetch = fake_batch
        rc = _run_delisted_command(_args('fetch'), m)
        out = capsys.readouterr().out
        assert rc == 0 and seen['adjust'] == 'hfq', 'CLI 默认口径透传到 batch'
        # 只取缺失的 2 只 (600005/000018), 已缓存的 600625 不重取,
        # B股 900953 默认不进
        assert sorted(seen['symbols']) == ['000018', '600005']
        assert 'B股 1 只默认跳过' in out

    def test_fetch_include_b(self, tmp_path, capsys):
        _write(tmp_path)
        m = _manager(tmp_path)
        seen = {}

        def fake_batch(symbols, start_date=None, end_date=None,
                       delay=0.0, max_workers=4, adjust='hfq'):
            seen['symbols'] = list(symbols)
            for s in symbols:
                m.metadata['stocks'][s] = {
                    'first_date': '1990-01-01', 'last_date': '2026-07-14',
                    'row_count': 100, 'updated': 'x'}
        m.batch_fetch = fake_batch
        rc = _run_delisted_command(_args('fetch', include_b=True), m)
        assert rc == 0
        assert '900953' in seen['symbols']

    def test_fetch_without_registry_rc1(self, tmp_path, capsys):
        m = _manager(tmp_path)
        m.batch_fetch = lambda *a, **k: pytest.fail('不应取数')
        rc = _run_delisted_command(_args('fetch'), m)
        assert rc == 1 and 'delisted refresh' in capsys.readouterr().out

    def test_no_subcommand_rc1(self, tmp_path, capsys):
        rc = _run_delisted_command(_args(None), _manager(tmp_path))
        assert rc == 1 and 'delisted {' in capsys.readouterr().out


# ================================================================ 5. 接线
class TestWiring:
    def test_per_pick_routes_through_meta(self):
        """per_pick 分支改经 get_universe_meta 取池 (池+偏差证据一体)"""
        src = open('.claude/skills/historical_backtest_validator.py',
                   encoding='utf-8').read()
        i = src.index('point_in_time_per_pick')
        seg = src[i:i + 3500]
        assert 'get_universe_meta(' in seg
        assert "mode': 'per_pick'" in seg

    def test_cli_registers_delisted_subcommands(self):
        src = open('.claude/skills/historical_data_manager.py',
                   encoding='utf-8').read()
        assert "'delisted'" in src
        for sub in ("'refresh'", "'status'", "'fetch'", "'--include-b'"):
            assert sub in src, sub

    def test_registry_module_has_no_wall_clock_universe(self):
        """清单模块不得把"没查过"写成"没有" (available=False 语义)"""
        src = open('.claude/skills/delisted_stocks.py', encoding='utf-8').read()
        assert 'available' in src and '没查过' in src
        # freshness 证据必须由落盘时间决定, 加载不得刷新
        assert 'fetched_at' in src
