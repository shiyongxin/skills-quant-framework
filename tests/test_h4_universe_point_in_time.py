# -*- coding: utf-8 -*-
"""
审计 H4 回归测试 —— point-in-time 股票池 (幸存者偏差)

背景 (审计原文):
- 幸存者偏差: `get_universe()` **无 `as_of` 参数**, 用 `datetime.now()`
  回溯到 1996; `stock_selector.get_hot_stocks` 硬编码热门股字典。
- 证据: `historical_data_manager.py` `get_universe(min_history_days=5000,
  min_rows=2000)` —— 无 as_of 参数。
- 性质: 与 C-P0-7 的 point-in-time 止血契约同源, 但因子层没跟上。

复验结论:
- `datetime.now()` 既是**前视** (用"今天"描述"历史"), 又让同一份代码在
  不同时间跑出**不同股票池** (不可复现);
- `get_hot_stocks` 的 35 只名单是**人工挑的板块股** (ai/chip/new_energy/
  military/consumer/finance/tmt) —— 与任何日期无关 → 历史回测里等于
  "用今天的名单回测过去";
- 本地缓存只含**当前在市**的股票 → 任何 as_of 口径的股票池都**仍带
  幸存者偏差** (当时已退市的股票根本不在池内) → 不可消除, 只能标记。

修复:
- `get_universe(..., as_of=)`: 参考日 = 显式 as_of 或**缓存最新日**
  (数据驱动, 不用 wall clock) → point-in-time 判定 (当时已上市 + 数据
  覆盖到 as_of + 历史长度相对 as_of); 缓存不覆盖 as_of → ValueError
  (拒绝部分覆盖的静默有偏股票池);
- `get_universe_meta()`: 输出口径元数据 + **幸存者偏差如实标记**;
- `get_hot_stocks`: 手写名单 → **数据驱动** (本地缓存股票池 + 近期涨幅
  排序; 缓存不可用 → 如实空列表 + 告警);
- 验证器: 报告/JSON 带 `universe_meta` (含幸存者偏差标记)。
"""
import ast
import inspect

import pandas as pd
import pytest

from historical_data_manager import HistoricalDataManager
from stock_selector import StockSelector, get_hot_stocks as hot_stocks_fn


def _manager(tmp_path, stocks):
    """构造带假元数据的数据管理器 (不碰磁盘数据)。"""
    dm = HistoricalDataManager(data_dir=str(tmp_path))
    dm.metadata = {'last_update': None, 'stock_count': len(stocks),
                   'stocks': stocks, 'indexes': {}}
    return dm


def _stock(first, last, rows=3000):
    return {'first_date': first, 'last_date': last, 'row_count': rows,
            'adjust': 'qfq'}


class TestPointInTimeUniverse:
    """get_universe(as_of=): point-in-time 股票池。"""

    def test_reference_date_is_data_driven_not_wall_clock(self, tmp_path):
        """参考日 = 缓存最新日 (数据驱动) → 不用 datetime.now()。

        旧实现: cutoff = now − 5000 天, 且只要 last_date ≥ cutoff 就入选
        → 早已停更的股票也会进池, 且结果随墙钟变化。
        """
        dm = _manager(tmp_path, {
            '600000': _stock('2005-01-01', '2024-06-28'),
            '600001': _stock('2005-01-01', '2020-01-01'),   # 数据早已停更
        })
        pool = dm.get_universe(min_history_days=5000, min_rows=2000)
        assert pool == ['600000']

    def test_excludes_stocks_listed_after_as_of(self, tmp_path):
        """as_of 之后才上市的股票 → 不在当时的池子里 (前视)。"""
        dm = _manager(tmp_path, {
            '600000': _stock('2005-01-01', '2024-06-28'),
            '600002': _stock('2020-01-01', '2024-06-28'),   # as_of 后上市
        })
        pool = dm.get_universe(min_history_days=3000, min_rows=2000,
                               as_of='2015-06-30')
        assert pool == ['600000']

    def test_excludes_stocks_without_data_at_as_of(self, tmp_path):
        """数据没覆盖到 as_of (已退市/未取到) → 不在池子里。"""
        dm = _manager(tmp_path, {
            '600000': _stock('2005-01-01', '2024-06-28'),
            '600003': _stock('2005-01-01', '2012-01-01'),   # as_of 前已无数据
        })
        pool = dm.get_universe(min_history_days=3000, min_rows=2000,
                               as_of='2015-06-30')
        assert pool == ['600000']

    def test_history_length_relative_to_as_of(self, tmp_path):
        """历史长度判据相对 as_of (不是相对 now)。"""
        dm = _manager(tmp_path, {
            '600000': _stock('2005-01-01', '2024-06-28'),   # 老牌 → 入选
            '600004': _stock('2014-01-01', '2024-06-28'),   # as_of 时仅 1.5 年
        })
        pool = dm.get_universe(min_history_days=3000, min_rows=2000,
                               as_of='2015-06-30')
        assert pool == ['600000']

    def test_as_of_beyond_cache_raises(self, tmp_path):
        """缓存不覆盖 as_of → 报错 (部分覆盖的股票池 = 静默有偏)。"""
        dm = _manager(tmp_path, {'600000': _stock('2005-01-01', '2024-06-28')})
        with pytest.raises(ValueError, match='不覆盖'):
            dm.get_universe(min_history_days=5000, min_rows=2000,
                            as_of='2030-01-01')

    def test_min_rows_filter(self, tmp_path):
        dm = _manager(tmp_path, {
            '600000': _stock('2005-01-01', '2024-06-28', rows=3000),
            '600005': _stock('2005-01-01', '2024-06-28', rows=10),
        })
        pool = dm.get_universe(min_history_days=5000, min_rows=2000)
        assert pool == ['600000']

    def test_empty_cache_returns_empty(self, tmp_path):
        dm = _manager(tmp_path, {})
        assert dm.get_universe() == []


class TestUniverseMeta:
    """get_universe_meta: 口径元数据 + 幸存者偏差如实标记。"""

    def test_meta_fields(self, tmp_path):
        dm = _manager(tmp_path, {'600000': _stock('2005-01-01', '2024-06-28')})
        meta = dm.get_universe_meta(min_history_days=5000, min_rows=2000)
        assert meta['n_stocks'] == 1
        assert meta['universe'] == ['600000']
        assert meta['as_of'] == '2024-06-28'
        assert meta['survivorship_bias'] is True
        assert '退市' in meta['survivorship_note']

    def test_meta_as_of_uses_point_in_time(self, tmp_path):
        dm = _manager(tmp_path, {
            '600000': _stock('2005-01-01', '2024-06-28'),
            '600002': _stock('2020-01-01', '2024-06-28'),
        })
        meta = dm.get_universe_meta(min_history_days=3000, min_rows=2000,
                                    as_of='2015-06-30')
        assert meta['universe'] == ['600000']
        assert meta['as_of'] == '2015-06-30'


def _fake_bars(symbol, changes, start='2024-01-01', periods=40):
    """构造一段日线: 每日按 changes 的收益率递增。"""
    dates = pd.bdate_range(start, periods=periods)
    close = 10.0
    closes = []
    for i in range(periods):
        closes.append(close)
        close *= (1 + changes)
    df = pd.DataFrame({'日期': dates, '开盘': closes, '最高': closes,
                       '最低': closes, '收盘': closes,
                       '成交量': [1e6] * periods})
    df['symbol'] = symbol
    return df


class TestHotStocksDataDriven:
    """get_hot_stocks: 数据驱动 (不用手写热门股名单)。"""

    def test_hardcoded_list_removed(self):
        """源码里不得再有手写热门股名单 (审计 H4 的核心证据)。"""
        import stock_selector
        src = open(stock_selector.__file__, encoding='utf-8').read()
        # 热门板块名单的签名 (ai/chip/new_energy/... 各 5 只的硬编码序列)
        for pair in ("'002415', '300059'", "'300750', '002594'",
                     "'600584', '002156'", "'600030', '601318'"):
            assert pair not in src, f'残留手写热门股名单: {pair}'
        # 主题键也不该再有
        for theme in ("'new_energy'", "'military'", "'tmt'"):
            assert theme not in src, f'残留热门板块键: {theme}'

    def test_ranks_by_recent_return(self, tmp_path, monkeypatch):
        """按最近 period 个交易日的涨幅排序 (数据驱动)。"""
        sel = StockSelector(data_dir=str(tmp_path))
        frames = {
            '600000': _fake_bars('600000', 0.01),    # 涨
            '600001': _fake_bars('600001', -0.01),   # 跌
        }
        monkeypatch.setattr(sel, '_cached_data',
                            lambda sym, as_of=None: frames.get(sym))
        out = sel.get_hot_stocks(count=5, universe=['600000', '600001'])
        assert [r['symbol'] for r in out] == ['600000', '600001']
        assert out[0]['change_pct'] > out[1]['change_pct']

    def test_empty_cache_returns_empty_not_fabricated(self, tmp_path, capsys):
        """缓存不可用 → 如实空列表 + 告警 (不再用手写名单顶替)。"""
        sel = StockSelector(data_dir=str(tmp_path))
        out = sel.get_hot_stocks(count=5, universe=[])
        assert out == []
        assert 'WARN' in capsys.readouterr().out

    def test_market_filter(self, tmp_path, monkeypatch):
        """market='sh' 只留 6 开头; 'sz' 只留非 6 开头。"""
        sel = StockSelector(data_dir=str(tmp_path))
        frames = {
            '600000': _fake_bars('600000', 0.01),
            '000001': _fake_bars('000001', 0.02),
        }
        monkeypatch.setattr(sel, '_cached_data',
                            lambda sym, as_of=None: frames.get(sym))
        pool = ['600000', '000001']
        sh = sel.get_hot_stocks(market='sh', count=5, universe=pool)
        sz = sel.get_hot_stocks(market='sz', count=5, universe=pool)
        assert [r['symbol'] for r in sh] == ['600000']
        assert [r['symbol'] for r in sz] == ['000001']

    def test_as_of_truncates_data(self, tmp_path, monkeypatch):
        """as_of → 只用该日之前的数据排序 (point-in-time)。"""
        sel = StockSelector(data_dir=str(tmp_path))
        df = _fake_bars('600000', 0.01, periods=60)
        seen = {}

        def fake(sym, as_of=None):
            seen['as_of'] = as_of
            if as_of is not None and '日期' in df.columns:
                return df[pd.to_datetime(df['日期']) <= pd.Timestamp(as_of)]
            return df

        monkeypatch.setattr(sel, '_cached_data', fake)
        out = sel.get_hot_stocks(count=1, universe=['600000'],
                                 as_of='2024-03-01')
        assert seen['as_of'] == '2024-03-01'
        assert len(out) == 1

    def test_module_level_function_forwards(self, tmp_path, monkeypatch):
        """模块级便捷函数转发新参数 (不吞掉 as_of)。"""
        import stock_selector
        captured = {}

        def fake_get(self, market='all', count=10, as_of=None, period=20,
                     universe=None):
            captured.update({'as_of': as_of, 'count': count,
                             'universe': universe})
            return []

        monkeypatch.setattr(StockSelector, 'get_hot_stocks', fake_get)
        hot_stocks_fn(count=3, as_of='2015-06-30', universe=['600000'],
                      data_dir=str(tmp_path))
        assert captured['as_of'] == '2015-06-30'
        assert captured['count'] == 3


class TestValidatorUniverseMeta:
    """验证器报告带股票池口径 (含幸存者偏差标记)。"""

    def test_report_carries_universe_meta(self, tmp_path):
        from historical_backtest_validator import ValidationReport
        rep = ValidationReport(n_dates=1, holding_days_list=[20], picks=[],
                                aggregate={}, system_breakdown={},
                                beat_benchmark={},
                                universe_meta={'as_of': '2015-06-30',
                                               'survivorship_bias': True})
        assert rep.universe_meta['survivorship_bias'] is True


class TestSourceHonesty:
    """源码级门禁: 不得回退到 wall clock / 手写名单。"""

    def test_get_universe_no_datetime_now(self):
        """get_universe / _reference_date 不得依赖 datetime.now()。

        wall clock 让同一份代码在不同时间跑出不同股票池 (不可复现),
        且用"今天"描述"历史" = 前视。
        """
        import historical_data_manager as hdm
        for fn in (HistoricalDataManager.get_universe,
                   HistoricalDataManager._reference_date,
                   HistoricalDataManager.get_universe_meta):
            import textwrap
            src = inspect.getsource(fn)
            tree = ast.parse(textwrap.dedent('\n'.join(
                ln for ln in src.splitlines()
                if not ln.strip().startswith('@'))))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == 'now'):
                    raise AssertionError(
                        f'{fn.__name__} 用了 .now() → 不可复现 + 前视')

    def test_cli_supports_as_of(self):
        """CLI 提供 --as-of (point-in-time 股票池)。"""
        import historical_data_manager as hdm
        src = open(hdm.__file__, encoding='utf-8').read()
        assert "'--as-of'" in src

    def test_as_of_is_optional_and_default_none(self):
        """as_of 缺省 None → 当前视角 (向后兼容, 旧调用不变)。"""
        params = inspect.signature(
            HistoricalDataManager.get_universe).parameters
        assert 'as_of' in params
        assert params['as_of'].default is None
