# -*- coding: utf-8 -*-
"""两个选择器必须走共享数据层 (审计 M20, 批次 2)

复验结论 (2026-10-29): 审计 M20 属实 —— `long_term_selector` /
`reversal_detector` 各自直接调 `sina_daily.fetch_daily`, 绕过了
`historical_data_manager` 这一共享数据层, 于是同时缺四样东西:

1. **无复权维度** (P0-4 矛盾): 硬编码不复权 → 除权跳空进入收益率/指标
2. **无 as_of**: 用 `datetime.now()` 划窗口 → 无法复现、无法做历史截面
3. **无 FetchResult** (项 11): 取数失败/数据不足一律 `return None`
   → 调用方无法区分"取数失败"与"确实没数据"
4. **无交易日历**: 窗口靠 `days * 2` 自然日启发式 → 与真实交易日无关

修复: 数据层新增 `get_daily_result()` (复权维度 + 参考日 + FetchResult +
交易日历), 两个选择器改走该入口。

门禁:
- 源码级: 两个模块不得再直接引取数层 / 不得自行用 wall clock 划窗口
- 行为: 数据层的 FetchResult 语义 (失败带原因/口径落 result/窗口裁剪/
  参考日/复权维度透传/交易日历换算 + 无日历降级标记)
- 行为: 两个选择器确实走数据层 (失败可见, 不静默)
"""
import ast
from pathlib import Path

import pandas as pd
import pytest

_SKILLS = Path(__file__).resolve().parent.parent / '.claude' / 'skills'
_HDM = _SKILLS / 'historical_data_manager.py'
_LTS = _SKILLS / 'long_term_selector.py'
_RD = _SKILLS / 'reversal_detector.py'
_SELECTORS = (_LTS, _RD)


def _read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


class TestSelectorsRouteThroughSharedLayer:
    """源码级: 选择器不得再自行取数 (M20)。"""

    @pytest.mark.parametrize('path', _SELECTORS, ids=lambda p: p.name)
    def test_no_direct_fetch_layer_import(self, path):
        src = _read(path)
        assert 'from sina_daily import' not in src, (
            f'{path.name} 仍直接引取数层 → 应走共享数据层 (审计 M20)')
        assert 'fetch_daily(' not in src, (
            f'{path.name} 仍自行取数 → 应走共享数据层 (审计 M20)')

    @pytest.mark.parametrize('path', _SELECTORS, ids=lambda p: p.name)
    def test_uses_shared_data_manager(self, path):
        src = _read(path)
        assert 'historical_data_manager' in src, (
            f'{path.name} 未走共享数据层 (审计 M20)')
        assert 'get_daily_result' in src

    @pytest.mark.parametrize('path', _SELECTORS, ids=lambda p: p.name)
    def test_no_wall_clock_window(self, path):
        """取数窗口不得再由 `datetime.now()` 划 (前视 + 不可复现)。"""
        tree = ast.parse(_read(path))
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == 'now' and isinstance(
                        node.func.value, ast.Name) and node.func.value.id == 'datetime':
                    offenders.append(node.lineno)
        # datetime.now() 仅允许用于"打印时间戳", 不得用于取数窗口
        assert len(offenders) <= 2, (
            f'{path.name} 仍用 datetime.now() ({offenders}) —— 取数窗口必须'
            f'由共享数据层按参考日/as_of 计算')

    @pytest.mark.parametrize('path', _SELECTORS, ids=lambda p: p.name)
    def test_cache_key_includes_dimension(self, path):
        """**若模块有缓存**, 缓存键必须含复权/参考日维度
        (同一股票不同口径不是同一份数据)。"""
        src = _read(path)
        if 'self.cache' not in src:
            return          # 无缓存 → 无"按旧口径串味"的风险
        assert 'cache_key' in src, (
            f'{path.name} 缓存未按口径分键 → 换 adjust 会拿到旧口径的数据')


class _StubManager:
    """数据层替身: 记录调用参数, 返回预置 FetchResult。"""

    SOURCE = 'stub'

    def __init__(self, result=None):
        self.result = result
        self.calls = []

    def get_daily_result(self, symbol, **kwargs):
        self.calls.append((symbol, kwargs))
        return self.result


def _frame(n=300, start='2024-01-01'):
    dates = pd.date_range(start, periods=n, freq='D')
    return pd.DataFrame({
        '日期': dates,
        '开盘': range(n), '最高': range(1, n + 1), '最低': range(n),
        '收盘': [float(i) for i in range(n)],
        '成交量': [100.0] * n, '成交额': [1000.0] * n,
    })


class TestSelectorsUseSharedLayer:
    def test_long_term_selector_forwards_dimensions(self):
        from core.fetch_result import FetchResult
        from long_term_selector import LongTermSelector

        lts = LongTermSelector()
        ok = FetchResult.success(_frame(), source='stub', adjust='qfq',
                                 as_of='2024-01-01')
        stub = _StubManager(ok)
        lts._data_manager = stub

        df = lts.get_stock_data('600000', days=250, adjust='qfq',
                                as_of='2024-01-01')
        assert df is not None and len(df) == 300
        symbol, kwargs = stub.calls[0]
        assert symbol == '600000'
        assert kwargs['adjust'] == 'qfq'
        assert kwargs['as_of'] == '2024-01-01'
        assert kwargs['days'] == 250
        assert kwargs['min_rows'] == 250

    def test_reversal_detector_forwards_dimensions(self):
        from core.fetch_result import FetchResult
        from reversal_detector import ReversalDetector

        rd = ReversalDetector()
        ok = FetchResult.success(_frame(200), source='stub', adjust='')
        stub = _StubManager(ok)
        rd._data_manager = stub

        df = rd.get_stock_data('600000', days=250, adjust='', as_of=None)
        assert df is not None and len(df) == 200
        _, kwargs = stub.calls[0]
        assert kwargs['adjust'] == ''
        assert kwargs['min_rows'] == 60

    def test_failure_is_visible_not_silent(self, capsys):
        """取数失败 → 打印原因 + 返回 None (不再无声吞掉)。"""
        from core.fetch_result import FetchResult
        from long_term_selector import LongTermSelector

        lts = LongTermSelector()
        lts._data_manager = _StubManager(
            FetchResult.failure('API 失败', source='stub'))
        assert lts.get_stock_data('600000') is None
        out = capsys.readouterr().out
        assert '取数失败' in out and 'API 失败' in out

    def test_cache_is_dimension_aware(self):
        from core.fetch_result import FetchResult
        from long_term_selector import LongTermSelector

        lts = LongTermSelector()
        stub = _StubManager(FetchResult.success(_frame(), source='stub'))
        lts._data_manager = stub

        lts.get_stock_data('600000', adjust='')
        lts.get_stock_data('600000', adjust='')
        assert len(stub.calls) == 1          # 同口径命中缓存
        lts.get_stock_data('600000', adjust='qfq')
        assert len(stub.calls) == 2          # 换口径 → 重新取数


class TestDataLayerDailyResult:
    """数据层 `get_daily_result` 的语义。"""

    @staticmethod
    def _manager(tmp_path, monkeypatch, api_df=None, api_error=None):
        from historical_data_manager import HistoricalDataManager
        m = HistoricalDataManager(str(tmp_path))

        def fake_fetch(symbol, start_date='19960101', end_date=None,
                       adjust='', **kwargs):
            if api_error:
                raise api_error
            return api_df if api_df is not None else pd.DataFrame()

        monkeypatch.setattr(m, 'fetch_and_cache', fake_fetch)
        return m

    def test_success_carries_dimensions(self, tmp_path, monkeypatch):
        # 数据范围覆盖参考日之前的窗口 (as_of 与数据末端对齐)
        m = self._manager(tmp_path, monkeypatch,
                          api_df=_frame(400, start='2023-01-01'))
        res = m.get_daily_result('600000', days=30, adjust='qfq',
                                  as_of='2024-01-01', min_rows=50)
        assert res.ok
        assert res.adjust == 'qfq'
        assert res.as_of.startswith('2024-01-01')
        assert res.source == 'historical_data_manager'
        assert res.meta['n_rows'] >= 50

    def test_api_failure_is_reported(self, tmp_path, monkeypatch):
        m = self._manager(tmp_path, monkeypatch, api_df=pd.DataFrame())
        res = m.get_daily_result('600000', days=10)
        assert not res.ok
        assert res.error and '取数失败' in res.error
        assert len(res.data) == 0

    def test_insufficient_rows_is_reported(self, tmp_path, monkeypatch):
        m = self._manager(tmp_path, monkeypatch,
                          api_df=_frame(30, start='2023-12-01'))
        res = m.get_daily_result('600000', days=10, as_of='2024-01-01',
                                 min_rows=250)
        assert not res.ok
        assert '数据不足' in res.error
        # meta 记的是**窗口裁剪后**的行数; 失败时 data 按 FetchResult
        # 契约为空 DF (调用方先看 ok), 故两者不等
        assert 0 < res.meta['n_rows'] < 30
        assert len(res.data) == 0

    def test_window_is_trimmed_to_as_of(self, tmp_path, monkeypatch):
        """返回数据必须裁剪到请求窗口 (fetch_and_cache 会与缓存合并)。"""
        df = _frame(400, start='2023-01-01')
        m = self._manager(tmp_path, monkeypatch, api_df=df)
        res = m.get_daily_result('600000', days=30, as_of='2023-01-20')
        assert res.ok
        assert res.ok
        assert res.data['日期'].max() <= pd.Timestamp('2023-01-20')

    def test_as_of_is_forwarded_to_fetch(self, tmp_path, monkeypatch):
        m = self._manager(tmp_path, monkeypatch,
                          api_df=_frame(50, start='2023-01-01'))
        seen = {}

        def spy(symbol, start_date='19960101', end_date=None, adjust='',
                **kwargs):
            seen['start'] = start_date
            seen['end'] = end_date
            seen['adjust'] = adjust
            return _frame(50)

        monkeypatch.setattr(m, 'fetch_and_cache', spy)
        m.get_daily_result('600000', days=30, adjust='hfq', as_of='2023-06-01')
        assert seen['end'] == '20230601'
        assert seen['adjust'] == 'hfq'
        assert seen['start'] < seen['end']

    def test_calendar_converts_trading_days(self, tmp_path, monkeypatch):
        """有交易日历 → 窗口按**交易日**换算 (不是自然日 ×2)。"""
        from core.trading_calendar import TradingCalendar
        m = self._manager(tmp_path, monkeypatch,
                          api_df=_frame(50, start='2023-01-01'))
        days = pd.bdate_range('2024-01-01', periods=40)
        cal = TradingCalendar.from_dates(days)
        seen = {}

        def spy(symbol, start_date='19960101', end_date=None, adjust='',
                **kwargs):
            seen['start'] = start_date
            return _frame(50)

        monkeypatch.setattr(m, 'fetch_and_cache', spy)
        res = m.get_daily_result('600000', days=10, as_of='2024-02-09',
                                  trading_calendar=cal)
        assert res.meta['calendar_used'] is True
        # 交易日历: 参考日 2024-02-09 前推 10 个**交易日** → 2024-01-29
        # (自然日 ×2 启发式会落到 2024-01-30 之后 → 少取 3 个交易日)
        assert seen['start'] == '20240129'

    def test_calendar_absent_falls_back_and_marks(self, tmp_path, monkeypatch):
        """无日历 → 降级为自然日并**如实标记** (不静默)。"""
        m = self._manager(tmp_path, monkeypatch,
                          api_df=_frame(50, start='2023-01-01'))
        monkeypatch.setattr(m, '_local_calendar', lambda: None)
        res = m.get_daily_result('600000', days=10, as_of='2024-02-09')
        assert res.meta['calendar_used'] is False

    def test_local_calendar_does_not_write_repo(self, tmp_path, monkeypatch):
        """取数路径现算日历**不落盘** (不污染仓库目录)。"""
        m = self._manager(tmp_path, monkeypatch,
                          api_df=_frame(50, start='2023-01-01'))
        idx = _frame(30, start='2024-01-01')
        monkeypatch.setattr(m, 'load_index', lambda *a, **k: idx)
        cal = m._local_calendar()
        assert cal is not None
        assert not (tmp_path / 'calendar').exists()
