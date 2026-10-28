# -*- coding: utf-8 -*-
"""
审计 H3 回归测试 —— 历史验证链重做

背景 (审计原文):
- `historical_backtest_validator` 的回测引擎是**死属性**（全文仅 `:86`
  一处实例化，从未使用）；验证参数来自"全历史优化出的"产物 → IS/OOS
  隔离仍破；样本按评估结果过滤（`forward_returns[hd] != 0`）；报告区间
  硬编码（`:504`）。
- 性质: 需重做验证链 (批次 3 最重的一条)。

复验结论 (本批实测):
- ① `self.backtester = VectorizedBacktester()` 是死属性 → 挂着"回测引擎"
  却从不回测, 让人误以为验证链跑过引擎;
- ② **IS/OOS 隔离仍破**: 验证参数来自优化产物 (在整段历史上拟合), 而
  manifest **已落盘** `data_start`/`data_end` → pick 日期可能落在拟合
  区间内 → 参数已见过这些日期的数据, 但旧实现**从不读**这两个字段;
- ③ 样本按评估结果过滤: 聚合层用 `forward_returns[hd] != 0` 判有效性,
  而 `0` 既是"无数据"哨兵又可能是**真实**的中位收益 → 真实 0 样本被
  静默丢弃, 且覆盖率在报告里不可见;
- ④ 报告区间硬编码 `"评估范围: 1996-01 ~ 2026-06"`, 关键结论与明细表
  写死 180 天 → 换数据/持有期时报告会**说谎**;
- ⑤ 单一股票池覆盖所有 pick 日期 → 对最早的日期是未来视角。

修复 (用户 2026-10-26 拍板):
- 段 0: 删死属性 + docstring 自证"本引擎不做回测";
- 段 1: **样本外隔离** —— pick 日期必须落在参数拟合区间之后; 无可用
  样本外区间 → **不出验证结论** (默认严格; `allow_in_sample=True` 才
  允许退化为样本内且报告如实标注);
- 段 2: 每 pick 日期各自的点时股票池 (默认 per_pick);
- 段 3/4: 覆盖度记账 + 聚合不再按 0 过滤 (显式有效性标记);
- 段 5: 报告口径自证 (区间由实际数据推导 + 主口径持有期可传)。
"""
import ast
import inspect
import json
import textwrap

import numpy as np
import pandas as pd
import pytest

import historical_backtest_validator as hbv
from execution_model import CostModel


# ------------------------------------------------------------------ 夹具

def _index(n=400, start='2022-01-03'):
    dates = pd.bdate_range(start, periods=n)
    close = 3000 * np.cumprod(1 + np.full(n, 0.0004))
    return pd.DataFrame({'日期': dates, '开盘': close, '最高': close * 1.002,
                         '最低': close * 0.998, '收盘': close,
                         '成交量': [1e8] * n})


def _stock(n=2400, start='2015-01-05', seed=1):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start, periods=n)
    close = 10 * np.cumprod(1 + rng.normal(0.001, 0.01, n))
    return pd.DataFrame({'日期': dates, '开盘': close * 0.999,
                         '最高': close * 1.01, '最低': close * 0.99,
                         '收盘': close, '成交量': [1e6] * n})


def _validator(tmp_path, index_df=None, stocks=None, manifest=None):
    """构造验证器 (全部数据走内存桩, 不联网)。"""
    idx = index_df if index_df is not None else _index()
    books = stocks if stocks is not None else {'600000': _stock()}

    class _DM:
        def __init__(self):
            self.universe_calls = []

        def load(self, symbol):
            return books.get(symbol, pd.DataFrame()).copy()

        def load_index(self, code):
            return idx.copy()

        def get_stock_name(self, symbol):
            return f'股票{symbol}'

        def get_universe(self, min_history_days=5000, min_rows=2000,
                         as_of=None):
            self.universe_calls.append(as_of)
            return list(books.keys())

        def get_universe_meta(self, min_history_days=5000, min_rows=2000,
                              as_of=None):
            self.universe_calls.append(as_of)
            return {'as_of': str(as_of), 'universe': list(books.keys()),
                    'n_stocks': len(books), 'survivorship_bias': True,
                    'survivorship_note': '测试桩'}

    v = hbv.HistoricalBacktestValidator.__new__(hbv.HistoricalBacktestValidator)
    v.data_dir = str(tmp_path)
    v.data_manager = _DM()
    v.cost_model = CostModel()
    v.systems = {'BULL': {'params': {'ma_fast': 5, 'ma_slow': 20},
                          'name': '测试体系'}}
    v._calendar = None
    v._universe_meta = {}
    v._param_fit_range = {}
    v._suspension_stats = {'modeled': False, 'deferred_picks': 0,
                           'deferred_trading_days_total': 0,
                           'suspended_days_total': 0}
    v._load_index_data = lambda code='000300': idx.copy()
    return v


def _write_manifest(tmp_path, data_start=None, data_end=None,
                    systems=None):
    """写一份优化产物 manifest (审计 H3 的 data_start/data_end 是关键)。"""
    path = tmp_path / 'optimization_result.json'
    payload = {
        'systems': systems or [{'name': '测试体系', 'applicable_regimes': ['BULL'],
                                'params': {'ma_fast': 5, 'ma_slow': 20}}],
    }
    if data_start:
        payload['data_start'] = data_start
    if data_end:
        payload['data_end'] = data_end
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return path


def _patch_signal(monkeypatch, buy_score=70.0, signal='BUY'):
    """桩掉信号生成 (离线可跑)。"""
    def fake(data, params):
        return {'buy_score': buy_score, 'sell_score': 0.0, 'signal': signal,
                'strength': 1.0, 'reasons': [], 'indicators': {}}
    monkeypatch.setattr(hbv, 'generate_signal', fake)


# ------------------------------------------------------------------ 段 0

class TestDeadBacktesterAttribute:
    """段 0: 死属性清零 + docstring 自证。"""

    def test_no_backtester_attribute(self):
        """类体内不得再出现 self.backtester = ... (死属性)。"""
        tree = ast.parse(textwrap.dedent(inspect.getsource(hbv)))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute)
                    and node.attr == 'backtester'
                    and isinstance(node.ctx, ast.Store)):
                raise AssertionError('仍有 self.backtester 赋值 (死属性)')

    def test_no_backtester_import(self):
        """不得再 import VectorizedBacktester (本引擎不做回测)。"""
        tree = ast.parse(textwrap.dedent(inspect.getsource(hbv)))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                         else [node.module or ''])
                assert not any('VectorizedBacktester' in nm for nm in names), \
                    '仍导入 VectorizedBacktester → 暗示"验证链跑过回测引擎"'

    def test_docstring_states_no_backtest(self):
        """docstring 必须自证"不做回测" (避免后来者再挂引擎属性)。"""
        doc = hbv.HistoricalBacktestValidator.__doc__ or ''
        assert '不做回测' in doc

    def test_validator_has_no_backtester_instance_attr(self):
        """正常构造的实例也没有 backtester 属性。"""
        v = hbv.HistoricalBacktestValidator.__new__(
            hbv.HistoricalBacktestValidator)
        assert not hasattr(v, 'backtester')


# ------------------------------------------------------------------ 段 1

class TestOOSIsolation:
    """段 1: 样本外隔离 (pick 日期必须晚于参数拟合区间)。"""

    def test_fit_range_read_from_manifest(self, tmp_path):
        path = _write_manifest(tmp_path, data_start='2022-01-03',
                               data_end='2022-06-30')
        v = _validator(tmp_path)
        v._load_systems(str(path))
        assert v._param_fit_range['known'] is True
        assert v._param_fit_range['data_end'] == '2022-06-30'

    def test_old_manifest_marks_fit_range_unknown(self, tmp_path):
        path = _write_manifest(tmp_path)   # 无 data_start/data_end
        v = _validator(tmp_path)
        v._load_systems(str(path))
        assert v._param_fit_range['known'] is False
        assert 'data_start' in v._param_fit_range['note']

    def test_pick_dates_after_fit_range(self, tmp_path):
        """pick 日期必须全部晚于 data_end。"""
        idx = _index(300)
        v = _validator(tmp_path, index_df=idx)
        v._param_fit_range = {'known': True, 'data_start': '2022-01-03',
                              'data_end': '2022-06-30', 'note': ''}
        dates = v.select_pick_dates(n_dates=3, oos_only=True)
        assert dates
        assert all(d > '2022-06-30' for d in dates)

    def test_no_oos_range_returns_no_dates(self, tmp_path):
        """拟合区间覆盖全部可用日期 → 无样本外日期 → 不出结论。"""
        idx = _index(300)
        v = _validator(tmp_path, index_df=idx)
        v._param_fit_range = {'known': True, 'data_start': '2022-01-03',
                              'data_end': '2024-12-31', 'note': ''}
        assert v.select_pick_dates(n_dates=3, oos_only=True) == []

    def test_validate_without_oos_gives_no_conclusion(self, tmp_path,
                                                      monkeypatch):
        """默认严格: 无样本外区间 → 报告无聚合 (不出验证结论)。"""
        _patch_signal(monkeypatch)
        idx = _index(300)
        v = _validator(tmp_path, index_df=idx)
        v._param_fit_range = {'known': True, 'data_start': '2022-01-03',
                              'data_end': '2024-12-31', 'note': ''}
        report = v.validate(n_dates=3, holding_days_list=[20])
        assert report is not None
        assert report.oos['available'] is False
        assert report.oos['reason']
        assert report.aggregate == {}          # 无结论数字
        assert report.n_dates == 0

    def test_allow_in_sample_marks_in_sample(self, tmp_path, monkeypatch):
        """显式退路: allow_in_sample=True → 样本内, 报告如实标注。"""
        _patch_signal(monkeypatch)
        v = _validator(tmp_path)
        v._param_fit_range = {'known': True, 'data_start': '2022-01-03',
                              'data_end': '2024-12-31', 'note': ''}
        report = v.validate(n_dates=2, holding_days_list=[20],
                            allow_in_sample=True)
        assert report.oos['in_sample'] is True
        assert '样本内' in report.oos['reason']

    def test_unknown_fit_range_not_claimed_as_oos(self, tmp_path, monkeypatch):
        """旧 manifest (拟合区间未知) → 不假装样本外, 且默认严格 → 不出结论。"""
        _patch_signal(monkeypatch)
        v = _validator(tmp_path)
        v._param_fit_range = {'known': False, 'data_start': None,
                              'data_end': None,
                              'note': '优化产物未记录 data_start/data_end'}
        report = v.validate(n_dates=2, holding_days_list=[20])
        assert report.oos['available'] is False
        assert report.oos['fit_range_known'] is False
        # 用户拍板: 默认严格 → 拟合区间未知 = 无法构造样本外 → 不出结论
        assert report.aggregate == {}
        assert report.n_dates == 0
        assert '不出验证结论' in report.oos['reason']

    def test_unknown_fit_range_allowed_when_explicit(self, tmp_path, monkeypatch):
        """显式 allow_in_sample → 允许退化为样本内 (报告如实标注)。"""
        _patch_signal(monkeypatch)
        v = _validator(tmp_path)
        v._param_fit_range = {'known': False, 'data_start': None,
                              'data_end': None,
                              'note': '优化产物未记录 data_start/data_end'}
        report = v.validate(n_dates=2, holding_days_list=[20],
                            allow_in_sample=True)
        assert report.oos['in_sample'] is True
        assert report.n_dates > 0

    def test_pit_pool_coverage_failure_skips_date(self, tmp_path, monkeypatch):
        """点时池覆盖不足 (H4 严格口径抛错) → 跳过该日期, 不中断整轮。"""
        _patch_signal(monkeypatch)
        v = _validator(tmp_path)
        v._param_fit_range = {'known': True, 'data_start': '2022-01-03',
                              'data_end': '2022-06-30', 'note': ''}

        def boom(min_history_days=5000, min_rows=2000, as_of=None):
            raise ValueError('缓存数据不覆盖 as_of=... → 拒绝部分覆盖的股票池')

        v.data_manager.get_universe = boom
        report = v.validate(n_dates=2, holding_days_list=[20])
        # 没有崩溃, 且跳过原因被记录 (不静默)
        assert 'skipped_dates' in report.universe_meta
        assert report.universe_meta['skipped_dates']


# ------------------------------------------------------------------ 段 3/4

class TestCoverageAccounting:
    """段 3/4: 覆盖度记账 + 聚合不再按 0 过滤。"""

    def _run(self, tmp_path, monkeypatch, returns_by_hd):
        """returns_by_hd: {hd: [各 pick 的收益或 None]} → 驱动覆盖度。"""
        _patch_signal(monkeypatch)
        idx = _index(300)
        stocks = {'600000': _stock(), '600001': _stock(seed=2)}
        v = _validator(tmp_path, index_df=idx, stocks=stocks)
        v._param_fit_range = {'known': True, 'data_start': '2022-01-03',
                              'data_end': '2022-06-30', 'note': ''}
        seq = dict(returns_by_hd)
        # 逐股调用 → 按 pick 推进序列 (同一 pick 的所有股票取同一个值,
        # 这样 pick 的中位收益 = 该 pick 的设定值)
        state = {hd: {'last_pick': None, 'i': 0} for hd in seq}

        def fake_forward(symbol, pick_date, holding_days, trading_calendar=None):
            if holding_days not in seq:
                return None, None
            st = state[holding_days]
            if st['last_pick'] != pick_date:
                st['last_pick'] = pick_date
                st['i'] += 1
            vals = seq[holding_days]
            i = st['i'] - 1
            if 0 <= i < len(vals):
                return vals[i], 0.5
            return None, None

        monkeypatch.setattr(v, 'calculate_forward_return', fake_forward)
        report = v.validate(n_dates=2, holding_days_list=[20, 40],
                            universe=['600000', '600001'])
        return report

    def test_zero_return_pick_is_counted(self, tmp_path, monkeypatch):
        """真实 0 收益样本必须被计入 (旧口径按 != 0 把它丢了)。"""
        # 第一个 pick 的 20 天收益 = 0.0 (真实值), 第二个 = 5.0
        report = self._run(tmp_path, monkeypatch,
                           {20: [0.0, 5.0], 40: [0.0, 5.0]})
        pick0 = report.picks[0]
        assert pick0.valid[20] is True
        assert pick0.forward_returns[20] == 0.0
        # 聚合里两个 pick 都在 (旧口径只会有 1 个)
        assert report.aggregate[20]['n_valid_picks'] == 2
        assert report.aggregate[20]['n_picks_total'] == 2

    def test_missing_data_marked_invalid(self, tmp_path, monkeypatch):
        """数据不足的样本 → valid=False + n_missing 记账, 不进聚合。

        注意记账单位: n_evaluated / n_missing 计的是**股票数**
        (每个 pick 的 top_n 只股票逐一评估), n_valid_picks 计的是 pick 数。
        """
        report = self._run(tmp_path, monkeypatch,
                           {20: [None, 5.0], 40: [None, 5.0]})
        pick0 = report.picks[0]
        assert pick0.valid[20] is False
        assert pick0.n_missing[20] == 2      # 该 pick 的 2 只股票都缺数据
        assert pick0.n_evaluated[20] == 0
        assert report.aggregate[20]['n_valid_picks'] == 1   # 只有 1 个 pick 有效

    def test_coverage_block_reported(self, tmp_path, monkeypatch):
        """覆盖度进报告 (看得见结论基于几个样本)。"""
        report = self._run(tmp_path, monkeypatch,
                           {20: [1.0, 5.0], 40: [1.0, 5.0]})
        cov = report.coverage[20]
        assert cov['n_picks'] == 2
        assert cov['n_valid_picks'] == 2
        assert cov['coverage'] == pytest.approx(1.0)
        assert cov['n_evaluated'] == 4      # 2 picks × 2 股票


# ------------------------------------------------------------------ 段 2

class TestPerPickUniverse:
    """段 2: 每个 pick 日期各自的点时股票池 (默认开)。"""

    def test_per_pick_default(self, tmp_path, monkeypatch):
        _patch_signal(monkeypatch)
        v = _validator(tmp_path)
        v._param_fit_range = {'known': True, 'data_start': '2022-01-03',
                              'data_end': '2022-06-30', 'note': ''}
        report = v.validate(n_dates=2, holding_days_list=[20])
        assert report.universe_meta['mode'] == 'per_pick'
        # 每个 pick 日期各取一次池 (as_of = 该 pick 日期)
        assert len(v.data_manager.universe_calls) >= 1
        assert all(c is not None for c in v.data_manager.universe_calls)

    def test_single_mode_uses_one_pool(self, tmp_path, monkeypatch):
        _patch_signal(monkeypatch)
        v = _validator(tmp_path)
        v._param_fit_range = {'known': True, 'data_start': '2022-01-03',
                              'data_end': '2022-06-30', 'note': ''}
        report = v.validate(n_dates=2, holding_days_list=[20],
                            universe_mode='single')
        assert report.universe_meta['mode'] == 'single'

    def test_caller_supplied_pool_marked(self, tmp_path, monkeypatch):
        _patch_signal(monkeypatch)
        v = _validator(tmp_path)
        v._param_fit_range = {'known': True, 'data_start': '2022-01-03',
                              'data_end': '2022-06-30', 'note': ''}
        report = v.validate(n_dates=2, holding_days_list=[20],
                            universe=['600000'])
        assert report.universe_meta['source'] == 'caller_supplied'
        assert report.universe_meta['survivorship_bias'] is None


# ------------------------------------------------------------------ 段 5

class TestReportSelfCertification:
    """段 5: 报告口径自证 (不写死区间/持有期)。"""

    def _report(self, tmp_path, monkeypatch, **kw):
        _patch_signal(monkeypatch)
        v = _validator(tmp_path)
        v._param_fit_range = {'known': True, 'data_start': '2022-01-03',
                              'data_end': '2022-06-30', 'note': ''}
        report = v.validate(n_dates=2, holding_days_list=[20, 40], **kw)
        return v, report

    def test_no_hardcoded_range(self, tmp_path, monkeypatch):
        """报告不得再出现写死的 "1996-01 ~ 2026-06"。"""
        _, report = self._report(tmp_path, monkeypatch)
        text = hbv.HistoricalBacktestValidator.format_report(
            report, ) if False else None
        v = _validator(tmp_path)
        text = v.format_report(report)
        assert '1996-01 ~ 2026-06' not in text
        assert '30年A股数据' not in text

    def test_range_derived_from_actual_picks(self, tmp_path, monkeypatch):
        _, report = self._report(tmp_path, monkeypatch)
        v = _validator(tmp_path)
        text = v.format_report(report)
        assert '验证区间' in text
        if report.picks:
            assert report.picks[0].pick_date in text

    def test_certification_block_present(self, tmp_path, monkeypatch):
        _, report = self._report(tmp_path, monkeypatch)
        v = _validator(tmp_path)
        text = v.format_report(report)
        assert '【口径自证】' in text
        assert '样本外' in text
        assert '股票池' in text
        assert '停牌建模' in text

    def test_primary_holding_days_configurable(self, tmp_path, monkeypatch):
        """主口径持有期可传 → 结论段跟着变 (旧实现写死 180)。"""
        _, report = self._report(tmp_path, monkeypatch,
                                 primary_holding_days=40)
        assert report.primary_holding_days == 40
        v = _validator(tmp_path)
        text = v.format_report(report)
        assert '40天持有期中位收益' in text
        assert '180天持有期中位收益' not in text

    def test_primary_defaults_to_median(self, tmp_path, monkeypatch):
        _, report = self._report(tmp_path, monkeypatch)
        assert report.primary_holding_days == 40   # [20,40] 的中位项

    def test_no_conclusion_report_says_so(self, tmp_path, monkeypatch):
        """无聚合 → 报告明确写"无验证结论"。"""
        _patch_signal(monkeypatch)
        v = _validator(tmp_path)
        v._param_fit_range = {'known': True, 'data_start': '2022-01-03',
                              'data_end': '2024-12-31', 'note': ''}
        report = v.validate(n_dates=2, holding_days_list=[20])
        text = v.format_report(report)
        assert '【无验证结论】' in text
        assert '关键结论' not in text


# ------------------------------------------------------------------ web 出口

class TestWebValidationPage:
    """段 6: web 出口 (决策③: CLI + web 都要有)。"""

    def _web_src(self):
        import os
        path = os.path.join(os.path.dirname(hbv.__file__), 'web_app.py')
        return open(path, encoding='utf-8').read()

    def test_page_registered_in_nav_and_router(self):
        """导航项 + 路由都要接上 (不然页面永远进不去)。"""
        src = self._web_src()
        assert '🧪 历史验证' in src
        assert 'render_validation()' in src

    def test_page_shows_certification_fields(self):
        """页面必须展示口径自证 (样本外/股票池/停牌/覆盖度)。"""
        src = self._web_src()
        for token in ('口径自证', '样本外', '幸存者偏差', '有效样本覆盖'):
            assert token in src, f'web 页缺少口径自证项: {token}'

    def test_page_has_no_conclusion_state(self):
        """无结论时如实提示, 不显示聚合数字。"""
        src = self._web_src()
        assert '无验证结论' in src

    def test_no_hardcoded_width_kwarg(self):
        """st.dataframe 必须走 st_fill_width 兼容层 (streamlit 1.37 漂移)。"""
        src = self._web_src()
        block = src.split('def render_validation')[1].split('def ')[0]
        assert 'use_container_width=True' not in block
        assert 'st_fill_width(st.dataframe)' in block

    def test_loader_handles_missing_and_broken_json(self, tmp_path):
        """缺失/损坏的 JSON → None (页面如实提示, 不崩)。"""
        import web_app
        assert web_app._load_validation_report(str(tmp_path / 'nope.json')) is None
        bad = tmp_path / 'bad.json'
        bad.write_text('{not json', encoding='utf-8')
        assert web_app._load_validation_report(str(bad)) is None

    def test_loader_reads_valid_json(self, tmp_path):
        import web_app
        good = tmp_path / 'ok.json'
        good.write_text(json.dumps({'n_dates': 2, 'aggregate': {}}),
                        encoding='utf-8')
        data = web_app._load_validation_report(str(good))
        assert data['n_dates'] == 2


# ------------------------------------------------------------------ 端到端

class TestValidationChainEndToEnd:
    """端到端: 合成数据 → validate → 报告含全部口径字段。"""

    def test_full_report_fields(self, tmp_path, monkeypatch):
        _patch_signal(monkeypatch)
        v = _validator(tmp_path)
        v._param_fit_range = {'known': True, 'data_start': '2022-01-03',
                              'data_end': '2022-06-30', 'note': ''}
        report = v.validate(n_dates=2, holding_days_list=[20, 40])
        assert report.oos['available'] is True
        assert report.oos['pick_range'][0] is not None
        assert report.coverage
        assert report.universe_meta
        assert report.suspension is not None
        assert report.picks
        # 逐 pick 的覆盖度字段齐备
        for p in report.picks:
            assert p.n_picks >= 0
            assert set(p.valid) == {20, 40}
            assert set(p.n_evaluated) == {20, 40}
