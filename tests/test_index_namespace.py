# -*- coding: utf-8 -*-
"""指数独立命名空间 + 前缀/接口规则 (审计 M12)

修复前的三个缺陷 (均实测复验于 2026-10-25):

1. 前缀错: `_format_symbol` 把一切 0/3 开头代码映射成 sz —— 沪深300 是
   **沪市**指数 (000300→sh000300), 取 sz000300 在新浪必然落空
2. 取错标的: 000001 既是上证指数 (sh000001) 又是平安银行 (sz000001) ——
   只换前缀不换接口, 000001 会取回**个股行情冒充上证指数**
3. 命名空间冲突: 指数与个股共用 historical/{code}.parquet —— 体制判定
   (daily_signal_generator) 与交易日历 (ensure_calendar) 读到的是平安银行

修复: `is_index` 显式声明 (不靠代码猜 —— stock_list.csv 证实 000905/000852
等 000xxx 个股东有占用) + 指数走 `stock_zh_index_daily` 接口 + 指数存
historical/index/ 独立命名空间, 个股与同代码指数互不覆盖。
"""
import ast
from pathlib import Path

import pandas as pd
import pytest

_SKILLS = Path(__file__).resolve().parent.parent / '.claude' / 'skills'


def _stock_frame(n=5, base=10.0):
    """个股行情 (已标准化列名)"""
    return pd.DataFrame({
        '日期': pd.bdate_range('2024-01-01', periods=n),
        '开盘': [base + i for i in range(n)],
        '最高': [base + 0.5 + i for i in range(n)],
        '最低': [base - 0.5 + i for i in range(n)],
        '收盘': [base + i for i in range(n)],
        '成交量': [100000.0 + i for i in range(n)],
    })


def _sina_index_frame(n=8, base=3500.0):
    """ak.stock_zh_index_daily 的返回形状 (sina: date/open/high/low/close/volume)"""
    return pd.DataFrame({
        'date': pd.bdate_range('2024-01-01', periods=n),
        'open': [base + i for i in range(n)],
        'high': [base + 5.0 + i for i in range(n)],
        'low': [base - 5.0 + i for i in range(n)],
        'close': [base + 2.0 + i for i in range(n)],
        'volume': [1e9 + i for i in range(n)],
    })


@pytest.fixture
def mgr(tmp_path):
    from historical_data_manager import HistoricalDataManager
    return HistoricalDataManager(data_dir=str(tmp_path))


# =============================================================================
# 前缀规则 (M12 #1)
# =============================================================================

class TestFormatSymbol:
    def test_stock_prefix_unchanged(self, mgr):
        """个股规则不动: 既有取数行为不受 M12 影响"""
        assert mgr._format_symbol('600000') == 'sh600000'
        assert mgr._format_symbol('000001') == 'sz000001'   # 平安银行
        assert mgr._format_symbol('300059') == 'sz300059'
        assert mgr._format_symbol('688001') == 'sh688001'

    def test_index_prefix_by_exchange(self, mgr):
        """指数按交易所分前缀: 000xxx→sh (沪市), 399xxx→sz (深市)"""
        assert mgr._format_symbol('000300', is_index=True) == 'sh000300'  # 沪深300
        assert mgr._format_symbol('000001', is_index=True) == 'sh000001'  # 上证指数
        assert mgr._format_symbol('000905', is_index=True) == 'sh000905'  # 中证500
        assert mgr._format_symbol('399006', is_index=True) == 'sz399006'  # 创业板指
        assert mgr._format_symbol('399300', is_index=True) == 'sz399300'  # 沪深300(深)

    def test_same_code_differs_by_semantics(self, mgr):
        """同一代码两种语义前缀不同 —— 这正是必须显式声明 is_index 的原因"""
        assert (mgr._format_symbol('000001')
                != mgr._format_symbol('000001', is_index=True))


# =============================================================================
# 取数接口 + 独立命名空间 (M12 #2/#3)
# =============================================================================

class TestIndexNamespace:
    def test_index_fetch_uses_index_api_and_separate_namespace(self, mgr,
                                                               monkeypatch):
        import historical_data_manager as hdm
        calls = []
        monkeypatch.setattr(hdm.ak, 'stock_zh_index_daily',
                            lambda symbol: (calls.append(symbol)
                                            or _sina_index_frame()))

        df = mgr.fetch_and_cache('000300', is_index=True)

        assert calls == ['sh000300'], "指数必须走指数接口且前缀为 sh000300"
        assert len(df) == 8
        for col in ('日期', '开盘', '最高', '最低', '收盘', '成交量', '涨跌幅'):
            assert col in df.columns, f"指数行情应标准化出 {col} 列"
        assert (mgr.index_dir / '000300.parquet').exists(), "指数存独立命名空间"
        assert not (mgr.historical_dir / '000300.parquet').exists(), \
            "不得写个股命名空间"
        assert len(mgr.load_index('000300')) == 8
        assert len(mgr.load('000300')) == 0, "个股 load() 不得读到指数数据"
        assert '000300' in mgr.metadata['indexes']
        assert '000300' not in mgr.metadata['stocks'], \
            "指数不得混进股票池元数据 (get_universe/get_all_symbols 只认 stocks)"

    def test_same_code_stock_and_index_do_not_collide(self, mgr, monkeypatch):
        """000001: 个股(平安银行) 与 指数(上证指数) 共存且互不覆盖"""
        import historical_data_manager as hdm
        monkeypatch.setattr(mgr, '_fetch_from_api',
                            lambda *a, **k: _stock_frame(n=5).copy())
        mgr.fetch_and_cache('000001', end_date='20240105')

        monkeypatch.setattr(hdm.ak, 'stock_zh_index_daily',
                            lambda symbol: _sina_index_frame(n=8))
        mgr.fetch_and_cache('000001', is_index=True, end_date='20240112')

        loaded = mgr.load('000001')
        idx = mgr.load_index('000001')
        assert (len(loaded), len(idx)) == (5, 8), "同代码个股/指数互不覆盖"
        assert float(loaded['收盘'].iloc[0]) == 10.0     # 平安银行
        assert float(idx['收盘'].iloc[0]) == 3502.0      # 上证指数
        assert (mgr.historical_dir / '000001_hfq.parquet').exists(), \
            '个股走默认复权口径文件名 (DEFAULT_ADJUST=hfq)'
        assert (mgr.index_dir / '000001.parquet').exists()
        assert ('000001_hfq' in mgr.metadata['stocks']
                and '000001' in mgr.metadata['indexes'])

    def test_index_ignores_adjust_with_notice(self, mgr, monkeypatch,
                                              capsys):
        import historical_data_manager as hdm
        monkeypatch.setattr(hdm.ak, 'stock_zh_index_daily',
                            lambda symbol: _sina_index_frame(n=4))
        mgr.fetch_and_cache('000300', adjust='qfq', is_index=True)
        assert (mgr.index_dir / '000300.parquet').exists(), \
            "指数无复权口径: 不生成 {code}_qfq 文件"
        assert '忽略' in capsys.readouterr().out

    def test_load_index_falls_back_to_csv(self, tmp_path, monkeypatch):
        """指数读路径同样走 Parquet→CSV 降级 (与个股共享 _read_local)"""
        from historical_data_manager import HistoricalDataManager
        mgr = HistoricalDataManager(data_dir=str(tmp_path))
        frame = _stock_frame(n=5)
        frame.to_csv(mgr.index_dir / '000300.csv', index=False,
                     encoding='utf-8-sig')

        def _no_pyarrow_read(*a, **k):
            raise ImportError("No module named 'pyarrow'")
        monkeypatch.setattr(pd, 'read_parquet', _no_pyarrow_read)

        df = mgr.load_index('000300')
        assert len(df) == 5
        assert pd.api.types.is_datetime64_any_dtype(df['日期'])


# =============================================================================
# 下游消费方: 体制判定 / 交易日历 不得读个股命名空间 (M12 影响面)
# =============================================================================

class TestDownstreamConsumers:
    def test_regime_and_calendar_read_index_namespace(self, tmp_path, monkeypatch):
        """daily_signal_generator 走 load_index → 个股不冒充, 指数就位后可判体制"""
        import historical_data_manager as hdm
        from core.trading_calendar import set_calendar
        from daily_signal_generator import DailySignalGenerator

        gen = DailySignalGenerator(data_dir=str(tmp_path))
        dm = gen.data_manager
        monkeypatch.setattr(dm, '_fetch_from_api',
                            lambda *a, **k: _stock_frame(n=3).copy())
        dm.fetch_and_cache('000001', end_date='20240103')   # 平安银行

        assert gen.detect_current_regime() == 'SIDEWAYS', \
            "个股 000001 不得冒充指数; 指数缺失时如实走「数据不足」降级"

        monkeypatch.setattr(hdm.ak, 'stock_zh_index_daily',
                            lambda symbol: _sina_index_frame(n=130))
        dm.fetch_and_cache('000300', is_index=True, end_date='20240708')
        regime = gen.detect_current_regime()
        assert regime != 'SIDEWAYS', \
            "130 天沪深300行情就位后不应再是「数据不足」降级; " \
            f"实际判定 = {regime}"
        set_calendar(None)

    def test_trading_calendar_from_index_not_stock(self, tmp_path, monkeypatch):
        """get_trading_calendar 取指数命名空间: 仅有平安银行行情时不得建日历"""
        import historical_data_manager as hdm
        from core.trading_calendar import set_calendar

        mgr = hdm.HistoricalDataManager(data_dir=str(tmp_path))
        monkeypatch.setattr(mgr, '_fetch_from_api',
                            lambda *a, **k: _stock_frame(n=3).copy())
        mgr.fetch_and_cache('000001', end_date='20240103')
        set_calendar(None)
        assert mgr.get_trading_calendar() is None, \
            "个股行情 ≠ 市场日历: 平安银行的 3 天不得变成交易日历"

        monkeypatch.setattr(hdm.ak, 'stock_zh_index_daily',
                            lambda symbol: _sina_index_frame(n=5))
        mgr.fetch_and_cache('000001', is_index=True, end_date='20240105')
        cal = mgr.get_trading_calendar()
        assert cal is not None and len(cal) == 5, "日历来自指数命名空间"
        set_calendar(None)

    def test_ensure_calendar_skips_stock_namespace(self, tmp_path, monkeypatch):
        """core.ensure_calendar (trade_constraints/web_app 的日历来源) 同样只认指数"""
        import historical_data_manager as hdm
        from core.trading_calendar import ensure_calendar, set_calendar

        mgr = hdm.HistoricalDataManager(data_dir=str(tmp_path))
        monkeypatch.setattr(mgr, '_fetch_from_api',
                            lambda *a, **k: _stock_frame(n=3).copy())
        mgr.fetch_and_cache('000001', end_date='20240103')   # 仅平安银行

        set_calendar(None)
        assert ensure_calendar(data_dir=str(tmp_path), refresh=True) is None, \
            "平安银行行情不得被当作上证指数构建日历"

        monkeypatch.setattr(hdm.ak, 'stock_zh_index_daily',
                            lambda symbol: _sina_index_frame(n=5))
        mgr.fetch_and_cache('000001', is_index=True, end_date='20240105')
        set_calendar(None)
        cal = ensure_calendar(data_dir=str(tmp_path), refresh=True)
        assert cal is not None and len(cal) == 5
        set_calendar(None)

    def test_regime_calendar_follows_instance_data_dir(self, tmp_path,
                                                       monkeypatch):
        """detect_current_regime 顺带建的日历须落在实例 data_dir

        此前 `build_calendar_from_index(index_data)` 用默认 data_dir=
        './stock_data' —— 自定义 data_dir 的实例会把日历写到 CWD (测试里
        就是污染仓库目录, 曾制造出一份假 2024 日历让 29 个用例连环失败)。
        """
        import historical_data_manager as hdm
        from core.trading_calendar import set_calendar
        from daily_signal_generator import DailySignalGenerator

        gen = DailySignalGenerator(data_dir=str(tmp_path))
        monkeypatch.setattr(hdm.ak, 'stock_zh_index_daily',
                            lambda symbol: _sina_index_frame(n=130))
        gen.data_manager.fetch_and_cache('000300', is_index=True,
                                         end_date='20240708')
        gen.detect_current_regime()

        assert (tmp_path / 'calendar' / 'trading_days.json').exists(), \
            "日历必须跟随实例 data_dir, 而非写死 CWD 的 ./stock_data"
        set_calendar(None)


# =============================================================================
# 源码级门禁: 以后不得再出现"指数代码走个股 load()"
# =============================================================================

class TestSourceGates:
    _INDEX_CODES = ('000300', '000001', '000905', '399001', '399006', '399300')

    def test_index_codes_never_go_through_stock_load(self):
        """指数代码作为字面量传给 data_manager.load() → 读到的是同代码个股"""
        offenders = []
        for rel in ('daily_signal_generator.py', 'historical_backtest_validator.py',
                    'historical_data_manager.py', 'core/trading_calendar.py'):
            src = (_SKILLS / rel).read_text(encoding='utf-8')
            for node in ast.walk(ast.parse(src)):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == 'load'
                        and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and str(node.args[0].value) in self._INDEX_CODES):
                    offenders.append(f'{rel}:{node.lineno}')
        assert not offenders, \
            f"指数代码不得走个股 load() (会读到同代码个股), 违规处: {offenders}"

    def test_trading_calendar_reads_index_namespace(self):
        src = (_SKILLS / 'core' / 'trading_calendar.py').read_text(encoding='utf-8')
        assert "mgr.load_index('000001')" in src, \
            "ensure_calendar 第 3 级来源必须是指数命名空间"
