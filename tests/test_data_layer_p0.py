# -*- coding: utf-8 -*-
"""
P0-2/项11/P0-5 回归测试:
- FetchResult 类型 (ok/error/as_of) + get_quote_result 结构化返回
- concurrent_fetcher 空数据计入 failed (旧逻辑恒 0)
- historical_data_manager API失败不再静默 (打印WARN, 返回旧数据有提示)
- optimization_engine load_data 0只成功 → RuntimeError (旧假成功)
- market_regime_classifier: bull/bear_trend_pct 生效 + 迟滞合并短段
"""
import numpy as np
import pandas as pd
import pytest

from core.fetch_result import FetchResult


class TestFetchResult:
    def test_success_and_failure_factories(self):
        df = pd.DataFrame({'收盘': [1.0]})
        ok = FetchResult.success(df, source='test')
        assert ok.ok and ok.error is None and ok.as_of is not None
        assert ok.source == 'test'

        bad = FetchResult.failure('boom', source='test')
        assert not bad.ok and bad.error == 'boom'
        assert len(bad.data) == 0 and bad.as_of is not None

    def test_get_quote_result_reports_failure(self, tmp_path, monkeypatch):
        import stock_data_fetcher as sdf_mod
        fetcher = sdf_mod.StockDataFetcher(data_dir=str(tmp_path))

        def boom(*a, **k):
            raise RuntimeError('network down')

        monkeypatch.setattr(sdf_mod.ak, 'stock_zh_a_daily', boom)
        res = fetcher.get_quote_result('600519', days=30)
        assert isinstance(res, FetchResult)
        assert not res.ok
        assert 'network down' in res.error
        # 旧接口仍返回空DF (兼容), 但结构化结果记录了真实原因
        df = fetcher.get_quote_data('600519', days=30)
        assert isinstance(df, pd.DataFrame) and len(df) == 0

    def test_get_quote_result_reports_success(self, tmp_path, monkeypatch):
        import stock_data_fetcher as sdf_mod
        fetcher = sdf_mod.StockDataFetcher(data_dir=str(tmp_path))

        fake = pd.DataFrame({
            'date': pd.to_datetime(['2024-01-02', '2024-01-03']),
            'open': [10.0, 10.1], 'high': [10.5, 10.6],
            'low': [9.8, 9.9], 'close': [10.2, 10.3],
            'volume': [1e6, 1.1e6], 'amount': [1e7, 1.1e7],
        })
        monkeypatch.setattr(sdf_mod.ak, 'stock_zh_a_daily',
                            lambda **k: fake.copy())
        res = fetcher.get_quote_result('600519', days=30)
        assert res.ok and len(res.data) == 2
        assert '收盘' in res.data.columns


class TestConcurrentFetcherStats:
    @staticmethod
    def _mk_fetcher():
        import concurrent_fetcher as cf_mod
        fetcher = cf_mod.ConcurrentDataFetcher.__new__(cf_mod.ConcurrentDataFetcher)
        fetcher.use_cache = False
        fetcher.cache_manager = None
        fetcher._stats = {'total_fetched': 0, 'cache_hits': 0,
                          'api_calls': 0, 'failed': 0}
        return fetcher

    def test_empty_data_counts_as_failed(self, monkeypatch):
        fetcher = self._mk_fetcher()

        class _Stub:
            def get_quote_data(self, symbol, days=120):
                return pd.DataFrame()  # 上游吞异常返回的空DF

        monkeypatch.setattr(fetcher, '_get_fetcher', lambda: _Stub())
        result = fetcher.fetch_one('600519')
        assert result is None
        assert fetcher._stats['failed'] == 1  # 旧逻辑恒 0

    def test_exception_counts_as_failed(self, monkeypatch):
        fetcher = self._mk_fetcher()

        class _Boom:
            def get_quote_data(self, symbol, days=120):
                raise RuntimeError('api down')

        monkeypatch.setattr(fetcher, '_get_fetcher', lambda: _Boom())
        result = fetcher.fetch_one('600519')
        assert result is None
        assert fetcher._stats['failed'] == 1


class TestHistoricalDataManager:
    def test_api_failure_logs_warning(self, tmp_path, capsys):
        import historical_data_manager as hdm_mod
        mgr = hdm_mod.HistoricalDataManager(data_dir=str(tmp_path))

        def boom(*a, **k):
            raise RuntimeError('quota exceeded')

        # _fetch_from_api 内部使用 akshare — 通过替换模块级引用
        original = hdm_mod.ak
        try:
            hdm_mod.ak = type('A', (), {'stock_zh_a_daily': boom})()
            result = mgr._fetch_from_api('600519', '20240101', '20240201')
        finally:
            hdm_mod.ak = original

        assert result is None
        captured = capsys.readouterr()
        assert 'API获取失败' in captured.out  # 旧逻辑 pass 静默

    def test_fetch_and_cache_warns_on_stale(self, tmp_path, capsys):
        pytest.importorskip("pyarrow")
        import historical_data_manager as hdm_mod
        mgr = hdm_mod.HistoricalDataManager(data_dir=str(tmp_path))

        # 预置旧数据
        old = pd.DataFrame({
            '日期': pd.to_datetime(['2024-01-02', '2024-01-03']),
            '开盘': [10.0, 10.1], '最高': [10.5, 10.6],
            '最低': [9.8, 9.9], '收盘': [10.2, 10.3],
            '成交量': [1e6, 1.1e6], '成交额': [1e7, 1.1e7],
            '涨跌幅': [0.0, 0.98],
        })
        parquet_path = mgr._get_parquet_path('600519')
        old.to_parquet(parquet_path, index=False)

        original = hdm_mod.ak
        try:
            # API 返回 None (失败)
            hdm_mod.ak = type('A', (), {'stock_zh_a_daily': lambda **k: None})()
            result = mgr.fetch_and_cache('600519', start_date='20240104')
        finally:
            hdm_mod.ak = original

        captured = capsys.readouterr()
        # 返回旧数据但必须有提示 (旧逻辑静默把旧当新)
        assert '返回本地旧数据' in captured.out
        assert len(result) == 2


class TestOptimizationEngineLoad:
    def test_zero_loaded_raises(self):
        import optimization_engine as oe_mod
        engine = oe_mod.OptimizationEngine.__new__(oe_mod.OptimizationEngine)
        engine._index_regime_labels = None
        engine.stock_data = {}

        class _EmptyMgr:
            def get_universe(self, **k):
                return ['600519', '000001']

            def load(self, sym):
                return pd.DataFrame()  # 空数据

        engine.data_manager = _EmptyMgr()
        with pytest.raises(RuntimeError, match='加载股票数据失败'):
            engine.load_data(symbols=None)

    def test_partial_load_warns_not_raises(self, capsys):
        import optimization_engine as oe_mod
        engine = oe_mod.OptimizationEngine.__new__(oe_mod.OptimizationEngine)
        engine._index_regime_labels = None
        engine.stock_data = {}

        good = pd.DataFrame({'日期': pd.bdate_range('2023-01-02', periods=300),
                             '收盘': np.linspace(10, 12, 300)})

        class _Mgr:
            def get_universe(self, **k):
                return ['600519', '000001']

            def load(self, sym):
                return good if sym == '600519' else pd.DataFrame()

        engine.data_manager = _Mgr()
        engine.load_data(symbols=None)  # 不应 raise
        assert list(engine.stock_data.keys()) == ['600519']
        captured = capsys.readouterr()
        assert '数据不足' in captured.out


class TestRegimeClassifier:
    @staticmethod
    def _mk_index(n=600, seed=0):
        rng = np.random.default_rng(seed)
        close = 100 * np.cumprod(1 + rng.normal(0.0002, 0.008, n))
        return pd.DataFrame({
            '日期': pd.bdate_range('2022-01-03', periods=n),
            '开盘': close, '最高': close * 1.01, '最低': close * 0.99,
            '收盘': close, '成交量': np.full(n, 1e9),
        })

    def test_trend_thresholds_affect_labels(self):
        from market_regime_classifier import MarketRegimeClassifier

        def labels_for(bull, bear):
            clf = MarketRegimeClassifier()
            clf.index_data = self._mk_index(seed=1)
            return clf.classify(method='fixed', bull_trend_pct=bull,
                                bear_trend_pct=bear, min_segment_days=0)

        loose = labels_for(0.0, 0.0)     # 阈值宽松 → 更多 BULL/BEAR
        strict = labels_for(40.0, -40.0)  # 阈值极端 → 几乎全 SIDEWAYS

        n_loose = (loose != 'SIDEWAYS').sum()
        n_strict = (strict != 'SIDEWAYS').sum()
        assert n_loose > n_strict  # 旧bug: 两组完全相同(死参数)

    def test_hysteresis_reduces_switching(self):
        from market_regime_classifier import MarketRegimeClassifier

        clf = MarketRegimeClassifier()
        index_data = self._mk_index(n=900, seed=2)
        clf.index_data = index_data
        raw = clf.classify(method='fixed', bull_trend_pct=5.0,
                           bear_trend_pct=-5.0, min_segment_days=0)
        smooth = clf.classify(method='fixed', bull_trend_pct=5.0,
                              bear_trend_pct=-5.0, min_segment_days=10)

        switches_raw = (raw != raw.shift(1)).sum() - 1
        switches_smooth = (smooth != smooth.shift(1)).sum() - 1
        assert switches_smooth < switches_raw
        # 平滑后所有普通段 ≥ 10 天
        values = smooth.tolist()
        runs, start = [], 0
        for i in range(1, len(values) + 1):
            if i == len(values) or values[i] != values[start]:
                runs.append((start, i, values[start]))
                start = i
        protected = {'CRASH', 'RECOVERY'}
        for s, e, lab in runs:
            if lab not in protected:
                assert (e - s) >= 10

    def test_adaptive_first_year_not_all_sideways(self):
        from market_regime_classifier import MarketRegimeClassifier

        # 构造前252日有明显趋势的数据 — 旧bug: vol_median NaN → 阈值 NaN → 全 SIDEWAYS
        n = 600
        close = 100 * np.exp(np.linspace(0, 0.6, n))  # 持续上涨
        rng = np.random.default_rng(3)
        close = close * np.cumprod(1 + rng.normal(0, 0.005, n))
        clf = MarketRegimeClassifier()
        clf.index_data = pd.DataFrame({
            '日期': pd.bdate_range('2022-01-03', periods=n),
            '收盘': close,
        })
        labels = clf.classify(method='adaptive', bull_trend_pct=1.0)
        first_year = labels.iloc[:252]
        assert (first_year == 'BULL').sum() > 0  # 旧bug: 前252日恒 SIDEWAYS

    def test_get_regime_for_dates_returns_latest(self):
        from market_regime_classifier import MarketRegimeClassifier

        clf = MarketRegimeClassifier()
        n = 300
        index_data = pd.DataFrame({
            '日期': pd.bdate_range('2023-01-02', periods=n),
            '收盘': np.linspace(100, 110, n),
        })
        clf.index_data = index_data
        # 人为构造标签: 前半 SIDEWAYS, 后半 BULL
        labels = pd.Series(['SIDEWAYS'] * (n // 2) + ['BULL'] * (n - n // 2))
        clf.regime_series = labels
        query = pd.DatetimeIndex([index_data['日期'].iloc[-1]])
        result = clf.get_regime_for_dates(query)
        assert result.iloc[0] == 'BULL'  # 旧bug: idxmax 返回第一天的标签
