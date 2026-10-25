# -*- coding: utf-8 -*-
"""可选依赖降级路径契约 (系统性盲区收口)

审计发现: 仓库里每个可选依赖都有一条"依赖缺失时怎么办"的分支, 但**没有任何一条
测试覆盖过** —— 测试套件中与可选依赖相关的唯一写法是 ``pytest.importorskip(...)``,
依赖缺失时**跳过**, 恰好绕开了降级路径本身; 于是"降级行为是什么"从来没人验证过。

本文件做两件事:

1. 为每条降级路径补一条"依赖缺失时如何表现"的用例 (锁定契约)
2. 加一条**门禁测试**: 任何新增的模块级 ``except ImportError`` 守卫 (非核心依赖)
   都必须在 ``OPTIONAL_DEP_CONTRACTS`` 登记, 且登记项必须对应一个真实存在的测试 ——
   以后再出现同类盲区, 测试直接失败, 不可能再溜过去。
"""

import ast
import contextlib
import importlib.util
import json
import sys
import types
import warnings
from pathlib import Path

import pandas as pd
import pytest

_SKILLS = Path(__file__).resolve().parent.parent / '.claude' / 'skills'

# 核心依赖: 缺失即 ImportError, 不属于"降级路径"
# (口径见 .claude/skills/requirements.txt 的"核心"段)
CORE_DEPS = {'pandas', 'numpy', 'scipy', 'akshare'}


# =============================================================================
# 工具: 模拟依赖缺失 / 加载模块独立副本
# =============================================================================

class _BlockFinder:
    """meta_path 拦截器: 被拦截的包 (含子模块) 一律 ImportError。"""

    def __init__(self, packages):
        self.packages = set(packages)

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in self.packages:
            raise ModuleNotFoundError(
                f"No module named {fullname!r}", name=fullname)
        return None


@contextlib.contextmanager
def missing(*packages):
    """模拟依赖缺失。

    拦截 import (meta_path) + 摘除已缓存的模块 —— 只做后者不够: 已缓存的
    子模块会绕过父包检查, 降级分支根本不会触发。
    """
    finder = _BlockFinder(packages)
    saved = {}
    for pkg in packages:
        for name in list(sys.modules):
            if name == pkg or name.startswith(pkg + '.'):
                saved[name] = sys.modules.pop(name)
    sys.meta_path.insert(0, finder)
    try:
        yield
    finally:
        sys.meta_path.remove(finder)
        for name, mod in saved.items():
            sys.modules[name] = mod


def _fresh(module_name, file_name=None):
    """加载模块的独立副本 (不污染已导入的模块对象, 可安全反复加载)。"""
    path = _SKILLS / (file_name or f"{module_name}.py")
    alias = f"_optdep_{module_name}"
    spec = importlib.util.spec_from_file_location(alias, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(alias, None)
    return mod


def _ohlcv_frame(n=5):
    return pd.DataFrame({
        '日期': pd.bdate_range('2024-01-01', periods=n),
        '开盘': [10.0 + i for i in range(n)],
        '最高': [10.5 + i for i in range(n)],
        '最低': [9.5 + i for i in range(n)],
        '收盘': [10.0 + i for i in range(n)],
        '成交量': [100000.0 + i for i in range(n)],
        '成交额': [1000000.0 + i for i in range(n)],
    })


class _SessionState:
    """同时支持 `in` 判断与属性访问 (与 streamlit.session_state 语义一致)。"""

    def __init__(self):
        object.__setattr__(self, '_d', {})

    def __contains__(self, key):
        return key in object.__getattribute__(self, '_d')

    def __getattr__(self, key):
        try:
            return object.__getattribute__(self, '_d')[key]
        except KeyError:
            raise AttributeError(key) from None

    def __setattr__(self, key, value):
        object.__getattribute__(self, '_d')[key] = value


def _fake_streamlit():
    """streamlit 桩: 记录调用, 不做任何真实渲染。"""
    mod = types.ModuleType('streamlit')
    calls = []
    mod.calls = calls
    mod.error = lambda msg: calls.append(('error', msg))
    mod.code = lambda msg, language=None: calls.append(('code', msg))
    mod.caption = lambda msg: calls.append(('caption', msg))
    mod.info = lambda msg: calls.append(('info', msg))
    mod.warning = lambda msg: calls.append(('warning', msg))
    mod.markdown = lambda msg, **kw: calls.append(('markdown', msg))

    @contextlib.contextmanager
    def _spinner(msg=''):
        yield

    mod.spinner = _spinner
    mod.session_state = _SessionState()
    mod.stop = lambda: calls.append(('stop', None))
    return mod


@contextlib.contextmanager
def _streamlit_stub():
    """把 streamlit 换成桩 (用完还原)。"""
    saved = sys.modules.get('streamlit')
    fake = _fake_streamlit()
    sys.modules['streamlit'] = fake
    try:
        yield fake
    finally:
        if saved is None:
            sys.modules.pop('streamlit', None)
        else:
            sys.modules['streamlit'] = saved


# =============================================================================
# 1. chart_visualizer: matplotlib 缺失
# =============================================================================

class TestChartVisualizerDegradation:
    def test_missing_matplotlib_disables_charts(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with missing('matplotlib'):
                mod = _fresh('chart_visualizer')

        assert mod.MATPLOTLIB_AVAILABLE is False
        assert any('Matplotlib' in str(w.message) for w in caught), \
            "缺 matplotlib 时应给出明确告警, 而不是静默"
        with pytest.raises(ImportError, match='Matplotlib'):
            mod.ChartVisualizer(output_dir='charts_optdep_test')


# =============================================================================
# 2. ml_predictor: scikit-learn 缺失
# =============================================================================

class TestMlPredictorDegradation:
    def test_missing_sklearn_raises_on_predictor_init(self):
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            with missing('sklearn'):
                mod = _fresh('ml_predictor')

        assert mod.SKLEARN_AVAILABLE is False
        with pytest.raises(ImportError, match='scikit-learn'):
            mod.MLPredictor()
        with pytest.raises(ImportError, match='scikit-learn'):
            mod.RegressionPredictor()


# =============================================================================
# 3. strategy_optimizer: backtest_framework 缺失
# =============================================================================

class TestStrategyOptimizerDegradation:
    def test_missing_backtest_framework_raises(self):
        with missing('backtest_framework'):
            mod = _fresh('strategy_optimizer')

        assert mod.MODULES_AVAILABLE is False
        with pytest.raises(ImportError, match='必要模块未安装'):
            mod.StrategyOptimizer()


# =============================================================================
# 4. web_app: streamlit 缺失 / 核心模块缺失
# =============================================================================

class TestWebAppDegradation:
    def test_missing_streamlit_degrades_without_crash(self):
        with missing('streamlit'):
            mod = _fresh('web_app')

        assert mod.STREAMLIT_AVAILABLE is False
        assert mod.st is None
        mod.render_missing_streamlit()   # 不抛异常
        mod.main()                       # 不抛异常, 且不触碰 st.*

    def test_missing_core_module_renders_error_page(self):
        with _streamlit_stub() as fake:
            with missing('backtest_framework'):
                mod = _fresh('web_app')

            assert mod.MODULES_AVAILABLE is False
            assert mod.STREAMLIT_AVAILABLE is True
            assert 'Traceback' in (mod.IMPORT_ERROR or ''), \
                "核心模块缺失应保留完整 traceback, 不静默降级"

            mod.render_import_error()
            kinds = [c[0] for c in fake.calls]
            assert 'error' in kinds and 'code' in kinds
            assert any('Traceback' in str(c[1]) for c in fake.calls
                       if c[0] == 'code')

    def test_missing_matplotlib_degrades_visualizer_to_none(self, monkeypatch):
        """matplotlib 缺失 → visualizer=None (图表区提示), 不是整页崩溃。"""
        import chart_visualizer
        with _streamlit_stub():
            mod = _fresh('web_app')

        assert mod.MODULES_AVAILABLE is True
        monkeypatch.setattr(chart_visualizer, 'MATPLOTLIB_AVAILABLE', False)
        mod.init_session_state()
        assert mod.st.session_state.visualizer is None

    def test_missing_streamlit_and_core_module_does_not_crash(self):
        with missing('streamlit', 'backtest_framework'):
            mod = _fresh('web_app')

        assert mod.STREAMLIT_AVAILABLE is False
        assert mod.MODULES_AVAILABLE is False
        mod.render_import_error()   # streamlit 缺失 → 退化 stderr 输出, 不崩
        mod.main()                   # 缺 streamlit 先短路, 不碰 st.stop()


# =============================================================================
# 5. historical_data_manager: pyarrow 缺失 → CSV 降级 (且带复权维度)
# =============================================================================

class TestHistoricalDataManagerDegradation:
    def test_parquet_failure_falls_back_to_csv_with_adjust_tag(self, tmp_path,
                                                                 monkeypatch):
        from historical_data_manager import HistoricalDataManager
        mgr = HistoricalDataManager(data_dir=str(tmp_path))
        frame = _ohlcv_frame()
        monkeypatch.setattr(mgr, '_fetch_from_api',
                            lambda *a, **k: frame.copy())

        def _no_pyarrow(self, *a, **k):
            raise ImportError("No module named 'pyarrow'")

        monkeypatch.setattr(pd.DataFrame, 'to_parquet', _no_pyarrow)
        mgr.fetch_and_cache('600000', adjust='qfq')

        hist = tmp_path / 'historical'
        assert (hist / '600000_qfq.csv').exists(), \
            "CSV 降级文件应带复权口径标签"
        assert not (hist / '600000.csv').exists(), \
            "前复权数据不得占用'不复权'文件名 (口径冒充)"

    def test_load_csv_fallback_does_not_borrow_other_adjust(self, tmp_path):
        from historical_data_manager import HistoricalDataManager
        hist = tmp_path / 'historical'
        hist.mkdir(parents=True, exist_ok=True)
        _ohlcv_frame().to_csv(hist / '600000.csv', index=False,
                               encoding='utf-8-sig')

        mgr = HistoricalDataManager(data_dir=str(tmp_path))
        assert len(mgr.load('600000')) == 5
        assert len(mgr.load('600000', adjust='qfq')) == 0, \
            "缺该复权口径文件时必须返回空, 不拿不复权数据冒充前复权"

    def test_legacy_untagged_csv_assigned_by_metadata(self, tmp_path):
        """存量: 旧版无标签 CSV 的口径由元数据判定 (只在该口径下可用)。"""
        from historical_data_manager import HistoricalDataManager
        hist = tmp_path / 'historical'
        hist.mkdir(parents=True, exist_ok=True)
        _ohlcv_frame().to_csv(hist / '600000.csv', index=False,
                               encoding='utf-8-sig')
        (hist / 'metadata.json').write_text(json.dumps({
            'stocks': {'600000_qfq': {'adjust': 'qfq', 'row_count': 5}},
        }), encoding='utf-8')

        mgr = HistoricalDataManager(data_dir=str(tmp_path))
        assert len(mgr.load('600000', adjust='qfq')) == 5, \
            "元数据证明它是前复权序列 → 该口径下应可用"
        assert len(mgr.load('600000')) == 0, \
            "同一文件不得同时被当作不复权序列返回 (口径冒充)"


# =============================================================================
# 6. optimized_params: parameter_space 缺失 → 软校验跳过
# =============================================================================

class TestOptimizedParamsDegradation:
    def test_missing_parameter_space_skips_soft_validation(self, tmp_path):
        from optimized_params import load_optimized_params
        path = tmp_path / 'opt.json'
        path.write_text(json.dumps({
            'use_weighted_scoring': True,
            'systems': [{'name': 'sys0', 'regime': 'GLOBAL',
                         'params': {'ma_fast': 5, 'unknown_key': 1}}],
        }), encoding='utf-8')

        with missing('parameter_space'):
            out = load_optimized_params(str(path))

        assert out['ma_fast'] == 5
        assert out['use_weighted_scoring'] is True
        assert 'unknown_key' in out, "软校验缺失时应放行未知键, 不阻断下发"


# =============================================================================
# 7. data_cleaner: 无 pyarrow 环境 (CSV 为主存储) 也要能体检
# =============================================================================

class TestDataCleanerCsvSupport:
    def test_scan_directory_covers_csv(self, tmp_path):
        from data_cleaner import scan_directory
        hist = tmp_path / 'historical'
        hist.mkdir(parents=True)
        frame = _ohlcv_frame()
        frame['成交量'] = frame['成交量'] * 100      # 手 → 股 (待归一)
        frame.to_csv(hist / '600000_qfq.csv', index=False, encoding='utf-8-sig')

        reports = scan_directory(str(tmp_path), dry_run=True)
        assert len(reports) == 1
        assert reports[0]['file'] == '600000_qfq.csv'
        assert reports[0]['adjust'] == 'qfq'
        assert reports[0]['units_detected']['volume_unit'] == 'lots'


# =============================================================================
# 8. requests 缺失: realtime_quote / stock_data_fetcher
# =============================================================================

class TestRequestsDegradation:
    def test_missing_requests_raises_on_api_init(self):
        with missing('requests'):
            mod = _fresh('realtime_quote')

        assert mod.REQUESTS_AVAILABLE is False
        with pytest.raises(ImportError, match='requests'):
            mod.RealTimeQuoteAPI()

    def test_missing_requests_returns_none_for_realtime_quote(self, tmp_path,
                                                              capsys):
        with missing('requests'):
            mod = _fresh('stock_data_fetcher')

        assert mod.REQUESTS_AVAILABLE is False
        fetcher = mod.StockDataFetcher(data_dir=str(tmp_path))
        assert fetcher.get_realtime_quote('600519') is None
        assert 'requests' in capsys.readouterr().out

    def test_web_app_degrades_rt_api_when_requests_missing(self, monkeypatch):
        """requests 缺失 → rt_api=None (监控页提示), 不是整页崩溃。"""
        import realtime_quote
        with _streamlit_stub():
            mod = _fresh('web_app')
        assert mod.MODULES_AVAILABLE is True

        monkeypatch.setattr(realtime_quote, 'REQUESTS_AVAILABLE', False)
        mod.init_session_state()
        assert mod.st.session_state.rt_api is None


# =============================================================================
# 9. 门禁: 可选依赖守卫必须登记降级契约
# =============================================================================

OPTIONAL_DEP_CONTRACTS = [
    {'file': 'chart_visualizer.py', 'scope': 'module',
     'flag': 'MATPLOTLIB_AVAILABLE', 'dep': 'matplotlib',
     'test': 'test_missing_matplotlib_disables_charts'},
    {'file': 'ml_predictor.py', 'scope': 'module',
     'flag': 'SKLEARN_AVAILABLE', 'dep': 'sklearn',
     'test': 'test_missing_sklearn_raises_on_predictor_init'},
    {'file': 'strategy_optimizer.py', 'scope': 'module',
     'flag': 'MODULES_AVAILABLE', 'dep': 'backtest_framework',
     'test': 'test_missing_backtest_framework_raises'},
    {'file': 'web_app.py', 'scope': 'module',
     'flag': 'STREAMLIT_AVAILABLE', 'dep': 'streamlit',
     'test': 'test_missing_streamlit_degrades_without_crash'},
    {'file': 'web_app.py', 'scope': 'module',
     'flag': 'MODULES_AVAILABLE', 'dep': '核心模块',
     'test': 'test_missing_core_module_renders_error_page'},
    {'file': 'realtime_quote.py', 'scope': 'module',
     'flag': 'REQUESTS_AVAILABLE', 'dep': 'requests',
     'test': 'test_missing_requests_raises_on_api_init'},
    {'file': 'stock_data_fetcher.py', 'scope': 'module',
     'flag': 'REQUESTS_AVAILABLE', 'dep': 'requests',
     'test': 'test_missing_requests_returns_none_for_realtime_quote'},
    {'file': 'optimized_params.py', 'scope': 'function', 'flag': None,
     'dep': 'parameter_space',
     'test': 'test_missing_parameter_space_skips_soft_validation'},
    {'file': 'historical_data_manager.py', 'scope': 'runtime', 'flag': None,
     'dep': 'pyarrow',
     'test': 'test_parquet_failure_falls_back_to_csv_with_adjust_tag'},
]


def _module_level_guards(path):
    """返回该文件**模块顶层** try/except ImportError 守卫清单。

    每项: {'flag': 守卫标志名 | 'NO_FLAG', 'deps': {被 import 的模块根名}}

    只看模块顶层 (ast.Try 是 module.body 的直接子节点): 函数内的局部导入
    属于"该函数不可用", 不改变模块能否导入 —— 那类守卫由注册表显式登记
    (scope='function')。
    """
    tree = ast.parse(path.read_text(encoding='utf-8'))
    blocks = []
    for node in tree.body:
        if not isinstance(node, ast.Try):
            continue
        handles = False
        for handler in node.handlers:
            t = handler.type
            if isinstance(t, ast.Name) and t.id == 'ImportError':
                handles = True
            elif isinstance(t, ast.Tuple) and any(
                    isinstance(e, ast.Name) and e.id == 'ImportError'
                    for e in t.elts):
                handles = True
        if not handles:
            continue
        deps = set()
        for stmt in node.body:
            if isinstance(stmt, ast.Import):
                for alias in stmt.names:
                    deps.add(alias.name.split('.')[0])
            elif isinstance(stmt, ast.ImportFrom):
                if stmt.module and stmt.level == 0:
                    deps.add(stmt.module.split('.')[0])
        flag = None
        for handler in node.handlers:
            for stmt in ast.walk(handler):
                if not isinstance(stmt, ast.Assign):
                    continue
                if not (isinstance(stmt.value, ast.Constant)
                        and stmt.value.value is False):
                    continue
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        flag = target.id
                        break
            if flag:
                break
        blocks.append({'flag': flag or 'NO_FLAG', 'deps': deps})
    return blocks


class TestOptionalDepGate:
    def test_every_module_level_guard_has_contract(self):
        registered = {(c['file'], c['flag']) for c in OPTIONAL_DEP_CONTRACTS
                      if c['scope'] == 'module'}
        unguarded = []
        for py in sorted(_SKILLS.rglob('*.py')):
            rel = py.relative_to(_SKILLS).as_posix()
            for block in _module_level_guards(py):
                deps = block['deps']
                if deps and deps <= CORE_DEPS:
                    continue          # 纯核心依赖 → 不是降级路径
                if (rel, block['flag']) not in registered:
                    unguarded.append(f"{rel}: {block['flag']} ({sorted(deps)})")
        assert not unguarded, (
            "新增的可选依赖守卫未登记降级契约 (OPTIONAL_DEP_CONTRACTS): "
            f"{unguarded} —— 请补一条『依赖缺失时如何表现』的用例")

    def test_every_module_contract_is_still_discovered(self):
        discovered = set()
        for py in sorted(_SKILLS.rglob('*.py')):
            rel = py.relative_to(_SKILLS).as_posix()
            for block in _module_level_guards(py):
                deps = block['deps']
                if deps and deps <= CORE_DEPS:
                    continue
                discovered.add((rel, block['flag']))
        stale = [f"{c['file']}: {c['flag']}" for c in OPTIONAL_DEP_CONTRACTS
                 if c['scope'] == 'module' and (c['file'], c['flag']) not in discovered]
        assert not stale, (
            f"登记的模块级守卫已不存在 (契约过期, 请删或改): {stale}")

    def test_every_contract_has_live_test(self):
        src = Path(__file__).read_text(encoding='utf-8')
        missing_tests = [c['test'] for c in OPTIONAL_DEP_CONTRACTS
                         if f"def {c['test']}(" not in src]
        assert not missing_tests, (
            f"登记的降级契约测试不存在: {missing_tests}")

    def test_contract_targets_still_guard(self):
        """契约登记的守卫标志必须仍在源码里 (防止标志被改名后契约空转)。"""
        for c in OPTIONAL_DEP_CONTRACTS:
            if not c['flag']:
                continue
            src = (_SKILLS / c['file']).read_text(encoding='utf-8')
            assert c['flag'] in src, \
                f"{c['file']} 的守卫标志 {c['flag']} 不存在, 契约需同步更新"
