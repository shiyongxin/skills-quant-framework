# -*- coding: utf-8 -*-
"""批次1 收口回归: M22 / M15 / M18 / M16 (docs/OPEN_ITEMS_PLAN_2026-10-25.md)

- **M22** multi_stock_backtester: 聚合语义 (worst_drawdown=最差个股, 非组合)
  + 抽样可复现 (seed) + 体制标签按数据窗口对齐
- **M15** historical_data_manager: get_stock_name / batch 股票池改走
  stock_list_manager 单例 (__file__ 基准, 不再 CWD 相对)
- **M18** 北交所取数: sina_daily.format_symbol 前缀规则单一真相源
  (4/8/92→bj) + bj 走新浪 klc 直连 (akshare 对 bj 在 amount 步骤崩溃)
  + 5 个调用方全部改走共享层
- **M16** stock_data_fetcher quotes/ 快照按 (股票, 口径) 去重,
  文件名带口径标签, MRC `{index_code}_*.csv` glob 兼容

全部离线: 网络步骤 (klc/因子 HTTP + 解码) 用 monkeypatch 打桩。
"""

import pathlib
import sys

import pandas as pd
import pytest

_SKILLS = pathlib.Path(__file__).resolve().parent.parent / '.claude' / 'skills'
sys.path.insert(0, str(_SKILLS))
sys.path.insert(0, str(_SKILLS.parent.parent))


def _read(name: str) -> str:
    return (_SKILLS / name).read_text(encoding='utf-8')


# =============================================================================
# M22 — 聚合语义 / 抽样种子 / 体制窗口
# =============================================================================

class TestM22AggregateSemantics:
    """worst_drawdown = 各股回撤的横截面最大值, 不是组合最大回撤"""

    def test_field_renamed_and_value_is_cross_sectional_max(self):
        import dataclasses
        from multi_stock_backtester import AggregateStats, MultiStockBacktester
        from vectorized_backtest import BacktestMetrics

        names = {f.name for f in dataclasses.fields(AggregateStats)}
        assert 'worst_drawdown' in names
        assert 'max_drawdown' not in names  # 旧字段名会被误读为组合口径

        bt = MultiStockBacktester.__new__(MultiStockBacktester)
        stats = bt._aggregate([
            BacktestMetrics(max_drawdown=12.0),
            BacktestMetrics(max_drawdown=30.0),
            BacktestMetrics(max_drawdown=5.0),
        ])
        assert stats.worst_drawdown == 30.0
        assert stats.mean_drawdown == pytest.approx(15.666, abs=0.01)

    def test_report_labels_are_honest(self):
        src = _read('multi_stock_backtester.py')
        assert '最差个股回撤' in src          # compare 表列名
        assert "'最大回撤%'" not in src       # 旧列名删除
        assert '非组合回撤' in src            # format_report 口径标注
        assert '无组合净值曲线' in src        # 报告口径脚注

    def test_format_report_states_scope(self):
        from multi_stock_backtester import (
            AggregateStats, EvaluationReport, MultiStockBacktester,
        )

        overall = AggregateStats(
            count=3, mean_return=1.0, median_return=1.0, p10_return=0.0,
            p90_return=2.0, std_return=1.0, pct_positive=66.0,
            pct_above_10=0.0, mean_sharpe=0.5, median_sharpe=0.5,
            mean_drawdown=10.0, median_drawdown=10.0, worst_drawdown=25.0,
            mean_win_rate=50.0, mean_trades=5.0, mean_holding_days=10.0,
            mean_profit_factor=1.2,
        )
        report = EvaluationReport(
            system_name='t', params={}, overall=overall, by_regime={},
            stock_results=[], timestamp='2026-01-01',
        )
        bt = MultiStockBacktester.__new__(MultiStockBacktester)
        out = bt.format_report(report)
        assert '无组合净值曲线' in out
        assert '最差=25.0%' in out
        assert '非组合回撤' in out


class TestM22SeedReproducibility:
    """random.sample 无种子 → 每次运行评估不同样本 (审计 M22)"""

    @staticmethod
    def _bt(load_log):
        from multi_stock_backtester import MultiStockBacktester
        bt = MultiStockBacktester.__new__(MultiStockBacktester)
        bt.backtester = None  # 数据全空, 走不到回测

        class _Mgr:
            def load(self, sym):
                load_log.append(sym)
                return pd.DataFrame()  # 全部计入"数据缺失", 返回 None

        bt.data_manager = _Mgr()
        return bt

    def _run(self, seed='unset'):
        log = []
        bt = self._bt(log)
        kwargs = {} if seed == 'unset' else {'seed': seed}
        bt.evaluate_system({}, symbols=[f'{i:06d}' for i in range(10)],
                           n_stocks=5, **kwargs)
        return log

    def test_same_seed_same_sample(self):
        assert self._run(seed=42) == self._run(seed=42)

    def test_default_seed_equals_42(self):
        assert self._run() == self._run(seed=42)

    def test_different_seed_different_sample(self):
        # random.Random 序列确定: 42 与 7 的样本在此固定输入下必然不同
        assert self._run(seed=42) != self._run(seed=7)

    def test_sample_size_respected(self):
        assert len(self._run(seed=42)) == 5

    def test_compare_systems_signature_has_seed(self):
        import inspect
        from multi_stock_backtester import MultiStockBacktester
        params = inspect.signature(MultiStockBacktester.compare_systems).parameters
        assert 'seed' in params and params['seed'].default == 42


class TestM22RegimeWindowAlignment:
    """体制标签取全历史众数 → 应按该股数据窗口对齐 (审计 M22)"""

    @staticmethod
    def _bt():
        from multi_stock_backtester import MultiStockBacktester
        return MultiStockBacktester.__new__(MultiStockBacktester)

    @staticmethod
    def _labels():
        # 50 天 BULL + 5 天 BEAR (2020-02-20 ~ 02-24)
        return {'000001': pd.Series(
            ['BULL'] * 50 + ['BEAR'] * 5,
            index=pd.date_range('2020-01-01', periods=55, freq='D'))}

    def test_window_picks_window_regime_not_full_history(self):
        win = pd.date_range('2020-02-20', periods=5)  # 全 BEAR
        assert self._bt()._get_dominant_regime(
            '000001', self._labels(), window=win) == 'BEAR'

    def test_no_window_falls_back_to_full_history(self):
        assert self._bt()._get_dominant_regime(
            '000001', self._labels()) == 'BULL'

    def test_window_without_labels_returns_unknown(self):
        assert self._bt()._get_dominant_regime(
            '000001', self._labels(),
            window=pd.date_range('2030-01-01', periods=3)) == 'UNKNOWN'

    def test_symbol_without_labels_returns_unknown(self):
        win = pd.date_range('2020-02-20', periods=5)
        assert self._bt()._get_dominant_regime(
            '600000', self._labels(), window=win) == 'UNKNOWN'

    def test_evaluate_system_passes_window(self):
        # 源码级: 调用点必须带 window= (防止回退成全历史众数)
        src = _read('multi_stock_backtester.py')
        assert 'window=window' in src


# =============================================================================
# M15 — stock_list 路径 (__file__ 基准, 不再 CWD 相对)
# =============================================================================

class TestM15StockListPath:
    def test_get_stock_name_works_from_any_cwd(self, tmp_path, monkeypatch):
        from historical_data_manager import HistoricalDataManager
        mgr = HistoricalDataManager.__new__(HistoricalDataManager)
        # 仓库根之外: 旧实现 Path(".claude/skills/stock_list.csv") 必然落空
        monkeypatch.chdir(tmp_path)
        assert mgr.get_stock_name('000001') == '平安银行'
        assert mgr.get_stock_name(1) == '平安银行'      # int 入参 (旧 int() 匹配)
        assert mgr.get_stock_name('600519') == '贵州茅台'
        assert mgr.get_stock_name('999999') == '999999'  # 查不到返回入参

    def test_hdm_source_has_no_cwd_relative_stock_list(self):
        src = _read('historical_data_manager.py')
        assert 'Path(".claude' not in src
        # batch CLI 也改走单例
        assert 'get_stock_list().get_all_stocks()' in src

    def test_hdm_uses_stock_list_manager_singleton(self):
        src = _read('historical_data_manager.py')
        assert 'from stock_list_manager import get_stock_name as _lookup_stock_name' in src


# =============================================================================
# M18 — 北交所前缀规则 + bj 直连 + 5 个调用方接线
# =============================================================================

class TestM18FormatSymbolRules:
    @pytest.mark.parametrize('raw,expected', [
        ('600000', 'sh600000'),
        ('688001', 'sh688001'),
        ('000001', 'sz000001'),
        ('300059', 'sz300059'),
        ('920002', 'bj920002'),   # 北交所现行码段 (stock_list.csv 315 只)
        ('430047', 'bj430047'),   # 北交所旧码段
        ('836247', 'bj836247'),
        ('sh600000', 'sh600000'),  # 已带前缀原样返回
        ('900901', '900901'),      # 9 但非 92 → 不猜前缀 (诚实失败)
    ])
    def test_sina_daily_format_symbol(self, raw, expected):
        from sina_daily import format_symbol
        assert format_symbol(raw) == expected

    def test_hdm_format_symbol_stock_and_index(self):
        from historical_data_manager import HistoricalDataManager
        mgr = HistoricalDataManager.__new__(HistoricalDataManager)
        assert mgr._format_symbol('920002') == 'bj920002'
        assert mgr._format_symbol('430047') == 'bj430047'
        # M12 指数分支不动
        assert mgr._format_symbol('000300', is_index=True) == 'sh000300'
        assert mgr._format_symbol('399006', is_index=True) == 'sz399006'
        assert mgr._format_symbol('000001') == 'sz000001'
        assert mgr._format_symbol('000001', is_index=True) == 'sh000001'

    def test_sdf_format_symbol_delegates(self):
        from stock_data_fetcher import StockDataFetcher
        f = StockDataFetcher.__new__(StockDataFetcher)
        assert f._format_symbol('920002') == 'bj920002'
        assert f._format_symbol('600000') == 'sh600000'


class TestM18FetchRouting:
    def test_bj_routes_to_klc_direct(self, monkeypatch):
        import sina_daily
        seen = {}

        def fake_bj(symbol, start_date, end_date, adjust=""):
            seen['bj'] = (symbol, adjust)
            return 'BJ-SENTINEL'

        # 实现名 2026-10-30 由 _fetch_bj_daily 改为 _fetch_klc_direct
        # (审计 D1: 该直连路径同时服务退市 sh/sz 回退); 路由语义不变
        monkeypatch.setattr(sina_daily, '_fetch_klc_direct', fake_bj)
        out = sina_daily.fetch_daily('bj920002', '20240101', '20240201',
                                     adjust='qfq')
        assert out == 'BJ-SENTINEL'
        assert seen['bj'] == ('bj920002', 'qfq')

    def test_sh_sz_pass_through_to_akshare(self, monkeypatch):
        import akshare as ak
        import sina_daily
        seen = {}

        def fake_ak(**kw):
            seen.update(kw)
            return 'AK-SENTINEL'

        monkeypatch.setattr(ak, 'stock_zh_a_daily', fake_ak)
        out = sina_daily.fetch_daily('sh600000', '20240101', '20240201',
                                     adjust='hfq')
        assert out == 'AK-SENTINEL'
        assert seen['symbol'] == 'sh600000'
        assert seen['adjust'] == 'hfq'

    def test_five_callers_route_through_shared_layer(self):
        # 直连 akshare 清零 (M18 契约不变): 5 个取数方都必须走共享层 ——
        # 其中 3 个直接用取数层 (sina_daily), 2 个选择器在 M20 后进一步
        # 改走**数据层** (historical_data_manager → 内部再走取数层)
        for name in ('stock_data_fetcher.py', 'historical_data_manager.py',
                     'long_term_selector.py', 'reversal_backtest.py',
                     'reversal_detector.py'):
            src = _read(name)
            assert 'ak.stock_zh_a_daily(' not in src, name  # 直连调用清零
        for name in ('stock_data_fetcher.py', 'historical_data_manager.py',
                     'reversal_backtest.py'):
            src = _read(name)
            assert 'sina_daily' in src, name
        # M20: 两个选择器不再自行取数 (复权维度/as_of/FetchResult/日历
        # 统一由数据层提供) → 不得再直接引取数层
        for name in ('long_term_selector.py', 'reversal_detector.py'):
            src = _read(name)
            assert 'historical_data_manager' in src, name
            assert 'from sina_daily import' not in src, name
        # 3 个内联前缀模块不再手拼 sh/sz
        for name in ('long_term_selector.py', 'reversal_backtest.py',
                     'reversal_detector.py'):
            src = _read(name)
            assert "f'sz{" not in src and "f'sh{" not in src, name


class TestM18BjFetchOffline:
    """bj 直连: HTTP + KLC 解码打桩, 验证列契约/窗口过滤/复权数学"""

    KLC_ROWS = [
        {'date': '2023-12-28T00:00:00.000Z', 'open': 100.0, 'high': 110.0,
         'low': 90.0, 'close': 105.0, 'volume': 1000.0, 'amount': 105000.0},
        {'date': '2023-12-29T00:00:00.000Z', 'open': 106.0, 'high': 112.0,
         'low': 100.0, 'close': 110.0, 'volume': 1100.0, 'amount': 121000.0},
        {'date': '2024-01-02T00:00:00.000Z', 'open': 55.0, 'high': 60.0,
         'low': 50.0, 'close': 58.0, 'volume': 1200.0, 'amount': 69600.0},
        {'date': '2024-01-03T00:00:00.000Z', 'open': 59.0, 'high': 62.0,
         'low': 55.0, 'close': 60.0, 'volume': 1300.0, 'amount': 78000.0},
    ]

    @pytest.fixture(autouse=True)
    def _stub_net(self, monkeypatch):
        import sina_daily

        def fake_http(url):
            if 'hisdata_klc2' in url:
                # 载荷含 '=' —— 不能用 split('=') 截断 (旧 akshare 写法隐患)
                return 'var KLC_K2_bj430047="PAY=LOAD==";'
            if '/qfq.js' in url:
                return ('var bj430047qfq={"total":2,"data":['
                        '{"d":"1900-01-01","f":"2.0000"},'
                        '{"d":"2024-01-01","f":"2.0000"}]}\n'
                        '/* trailing comment */')
            if '/hfq.js' in url:
                return ('var bj430047hfq={"total":1,"data":['
                        '{"d":"1900-01-01","f":"1.0000"}]}')
            raise AssertionError(f'unexpected url {url}')

        monkeypatch.setattr(sina_daily, '_http_get', fake_http)
        monkeypatch.setattr(sina_daily, '_decode_klc',
                            lambda payload: list(self.KLC_ROWS))
        # 解码载荷必须完整 (含 '=')
        self._payloads = []
        orig = sina_daily._extract_js_payload
        monkeypatch.setattr(
            sina_daily, '_extract_js_payload',
            lambda text: (self._payloads.append(orig(text)), orig(text))[1])

    def test_raw_window_filter_and_schema(self):
        from sina_daily import fetch_daily
        df = fetch_daily('bj430047', '2024-01-01', '2024-01-31', adjust='')
        assert list(df.columns) == [
            'date', 'open', 'high', 'low', 'close', 'volume', 'amount',
            'outstanding_share', 'turnover']
        assert len(df) == 2
        assert df['date'].iloc[0] == pd.Timestamp('2024-01-02').date()
        # akshare 口径: date 为 python date, OHLC 2 位小数
        assert df['outstanding_share'].isna().all()  # 补充接口对 bj 不可用
        assert df['turnover'].isna().all()
        # 载荷含 '=' 不被截断
        assert self._payloads == ['PAY=LOAD==']

    def test_qfq_divides_by_factor(self):
        from sina_daily import fetch_daily
        raw = fetch_daily('bj430047', '2024-01-01', '2024-01-31', adjust='')
        qfq = fetch_daily('bj430047', '2024-01-01', '2024-01-31', adjust='qfq')
        assert len(qfq) == len(raw) == 2
        # 因子 2.0 → qfq = raw / 2 (akshare 除法方向)
        assert qfq['close'].iloc[0] == round(raw['close'].iloc[0] / 2, 2)
        assert qfq['open'].iloc[1] == round(raw['open'].iloc[1] / 2, 2)

    def test_hfq_multiplies_by_factor(self):
        from sina_daily import fetch_daily
        raw = fetch_daily('bj430047', '2024-01-01', '2024-01-31', adjust='')
        hfq = fetch_daily('bj430047', '2024-01-01', '2024-01-31', adjust='hfq')
        # 因子 1.0 → 数值不变, 但路径必须走通
        assert len(hfq) == len(raw)
        assert hfq['close'].iloc[0] == raw['close'].iloc[0]

    def test_unknown_adjust_raises(self):
        from sina_daily import fetch_daily
        with pytest.raises(ValueError, match='复权口径'):
            fetch_daily('bj430047', '2024-01-01', '2024-01-31', adjust='bfq2')

    def test_empty_window_returns_empty_frame(self):
        from sina_daily import fetch_daily
        df = fetch_daily('bj430047', '2030-01-01', '2030-01-31', adjust='')
        assert len(df) == 0
        assert 'date' in df.columns

    def test_missing_payload_raises(self):
        import sina_daily
        with pytest.raises(ValueError, match='载荷'):
            sina_daily._extract_js_payload('var nothing here')


# =============================================================================
# M16 — quotes/ 快照去重 (同 (股票, 口径) 只留最新) + MRC 兼容
# =============================================================================

class TestM16QuoteCacheDedupe:
    def test_get_quote_data_dedupes_per_symbol_and_adjust(self, tmp_path,
                                                          monkeypatch):
        import akshare as ak
        from stock_data_fetcher import StockDataFetcher

        # 桩: 避免网络
        rows = pd.DataFrame({
            'date': pd.to_datetime(['2024-06-03', '2024-06-04']),
            'open': [30.0, 31.0], 'high': [31.0, 32.0],
            'low': [29.0, 30.0], 'close': [30.5, 31.5],
            'volume': [1000.0, 1100.0], 'amount': [30500.0, 34650.0],
            'outstanding_share': [1e8, 1e8], 'turnover': [0.01, 0.01],
        })
        monkeypatch.setattr(ak, 'stock_zh_a_daily', lambda **kw: rows.copy())

        f = StockDataFetcher(data_dir=str(tmp_path))
        qdir = tmp_path / 'quotes'
        (qdir / '000001_20200101_20240101.csv').write_text('stale-raw')
        (qdir / '000001_qfq_20200101_20240101.csv').write_text('stale-qfq')
        (qdir / '000002_20200101_20240101.csv').write_text('other')

        # raw 取数 → 旧 raw 删, qfq/其他保留, 新 raw 写入
        f.get_quote_data('000001', start_date='20240601', end_date='20240630',
                         adjust='')
        names = sorted(p.name for p in qdir.glob('*.csv'))
        assert '000001_20200101_20240101.csv' not in names
        assert '000001_qfq_20200101_20240101.csv' in names
        assert '000002_20200101_20240101.csv' in names
        raw_files = [n for n in names
                     if n.startswith('000001_') and '_qfq_' not in n]
        assert len(raw_files) == 1

        # qfq 取数 → 口径标签进文件名, 只留 1 个 qfq 快照
        f.get_quote_data('000001', start_date='20240601', end_date='20240630',
                         adjust='qfq')
        names = sorted(p.name for p in qdir.glob('*.csv'))
        assert '000001_qfq_20200101_20240101.csv' not in names
        assert sum(1 for n in names if n.startswith('000001_qfq_')) == 1
        assert any('_qfq_' in n for n in names)

        # 同口径再次取数 (不同区间) → 仍只有 1 个 (区间重叠不再累积)
        f.get_quote_data('000001', start_date='20240101', end_date='20241231',
                         adjust='')
        raw_files = [p.name for p in qdir.glob('000001_*.csv')
                     if '_qfq_' not in p.name]
        assert len(raw_files) == 1

    def test_dedupe_keeps_other_adjusts_and_symbols(self, tmp_path):
        from stock_data_fetcher import StockDataFetcher
        f = StockDataFetcher(data_dir=str(tmp_path))
        qdir = tmp_path / 'quotes'
        (qdir / '600000_20200101_20210101.csv').write_text('a')
        (qdir / '600000_hfq_20200101_20210101.csv').write_text('b')
        (qdir / '600000_20210101_20220101.csv').write_text('c')

        f._dedupe_quote_cache('600000', '', keep='600000_20210101_20220101.csv')
        names = sorted(p.name for p in qdir.glob('*.csv'))
        # 同口径旧快照删, hfq 口径与 keep 保留
        assert names == ['600000_20210101_20220101.csv',
                         '600000_hfq_20200101_20210101.csv']

    def test_mrc_glob_still_matches_both_names(self, tmp_path):
        """MRC `_load_from_local_cache` 的 `{index_code}_*.csv` 不能被改名打断"""
        import market_regime_classifier as mrc
        qdir = tmp_path / 'quotes'
        qdir.mkdir(parents=True)
        pd.DataFrame({'日期': ['2024-01-02'], '收盘': [1.0]}).to_csv(
            qdir / '000300_20200101_20231231.csv',
            index=False, encoding='utf-8-sig')
        pd.DataFrame({'日期': ['2024-01-03'], '收盘': [2.0]}).to_csv(
            qdir / '000300_qfq_20200101_20231231.csv',
            index=False, encoding='utf-8-sig')

        m = mrc.MarketRegimeClassifier.__new__(mrc.MarketRegimeClassifier)
        m.data_dir = tmp_path
        df = m._load_from_local_cache('000300', None, None)
        assert df is not None and len(df) >= 1
        assert '日期' in df.columns
