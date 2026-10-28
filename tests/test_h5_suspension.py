# -*- coding: utf-8 -*-
"""
审计 H5 回归测试 —— 回测引擎侧停牌建模

背景 (审计原文):
- 停牌建模**只落在信号层** (`trade_constraints` + `core/trading_calendar`),
  4 套回测引擎 (`backtest_framework` / `vectorized_backtest` /
  `reversal_backtest` / `historical_backtest_validator`) 对停牌**零感知**
  —— `rg 停牌|suspend` 在 4 引擎 → 0 命中; `execution_model.py` docstring
  自述"停牌: 数据侧无停牌标记 …… 不虚构交易日历"。
- 后果: ① "停牌期间持仓无法平仓"从未被显式建模; ② 持仓跨停牌的跳空
  敞口在任何指标里都看不见; ③ 以 **bar 数** 为单位的期限口径 (年化分母 /
  持有天数) 被停牌**静默压扁** → 年化收益与夏普**虚高**。

修复 (单一真相源 `core/suspension.py`):
- `SuspensionModel`: 由**真实交易日历** + 个股行情行推导真停牌日
  (个股在日历中有、自身无行); 复用 `TradingCalendar.missing_trading_days`
  → 日历已排除节假日, 不会误伤;
- 引擎 A/B: 停牌日不撮合 + 净值曲线按**交易日对齐** (停牌日市值持平)
  → 年化分母用交易日数, 夏普按交易日对齐; 逐笔记录持仓跨停牌天数;
- 引擎 D: 停牌日不撮合 + 期末停牌不可平仓 → 盯市 (不虚构成交);
- 引擎 E: 持有期按**交易日** (旧实现按个股 bar 数 → 停牌静默拉长窗口),
  到期日停牌 → 顺延到下一个可交易日并如实记录;
- **无日历 = 不建模** (如实记 suspension_modeled=False), 默认路径逐位不变。
"""
import inspect

import numpy as np
import pandas as pd
import pytest

from backtest_framework import BacktestEngine, get_balanced_config
from core.suspension import SuspensionModel, trading_day_index
from core.trading_calendar import TradingCalendar
from reversal_backtest import ReversalBacktester
from vectorized_backtest import VectorizedBacktester, metrics_from_trades


# ------------------------------------------------------------------ 数据工厂

def _calendar(n_days=60, halt=(20, 25), start='2024-01-01'):
    """构造交易日历: n_days 个工作日, 其中 [halt) 为个股停牌区间。"""
    days = pd.bdate_range(start, periods=n_days)
    cal = TradingCalendar.from_dates([d.date() for d in days], source='manual')
    return cal, days, set(days[halt[0]:halt[1]])


def _stock(days, seed=7, base=10.0):
    """按给定日期序列生成个股行情 (缺失的日期 = 停牌)。"""
    rng = np.random.default_rng(seed)
    close = base * np.cumprod(1 + rng.normal(0.001, 0.012, len(days)))
    return pd.DataFrame({
        '日期': list(days),
        '开盘': close * 0.999,
        '最高': close * 1.012,
        '最低': close * 0.988,
        '收盘': close,
        '成交量': 1e6,
        '成交额': 1e6 * close,
    })


def _with_halt(n_days=60, halt=(20, 25)):
    """日历 + 含停牌缺口的个股行情。"""
    cal, days, halted = _calendar(n_days, halt)
    keep = [d for d in days if d not in halted]
    return cal, _stock(keep), days, halted


# ------------------------------------------------------------------ core 语义

class TestSuspensionModel:
    """core/suspension.py: 真停牌日推导。"""

    def test_no_calendar_no_model(self):
        assert SuspensionModel.build(None, [pd.Timestamp('2024-01-01')]) is None

    def test_detects_true_suspension_days(self):
        cal, df, days, halted = _with_halt()
        model = SuspensionModel.build(cal, df['日期'].tolist())
        assert model is not None
        # 停牌 5 个交易日 (区间 [20,25) 共 5 天)
        assert len(model.suspended_days) == 5
        assert all(d.date() in model.suspended_days for d in halted)

    def test_is_suspended_and_tradable(self):
        cal, df, days, halted = _with_halt()
        model = SuspensionModel.build(cal, df['日期'].tolist())
        assert model.is_suspended(sorted(halted)[0]) is True
        assert model.is_tradable(sorted(halted)[0]) is False
        first_trading = days[0]
        assert model.is_suspended(first_trading) is False

    def test_suspended_days_between_counts_trading_days(self):
        cal, df, days, halted = _with_halt()
        model = SuspensionModel.build(cal, df['日期'].tolist())
        lo, hi = days[18], days[26]
        assert model.suspended_days_between(lo, hi) == 5

    def test_holiday_not_counted_as_suspension(self):
        """日历已排除节假日 → 节假日不算停牌 (不误伤)。"""
        # 交易日: 仅 3 天; 个股只有第 1 天和第 3 天 → 第 2 天是真停牌
        cal = TradingCalendar.from_dates(
            [pd.Timestamp('2024-01-02').date(),
             pd.Timestamp('2024-01-03').date(),
             pd.Timestamp('2024-01-04').date()], source='manual')
        model = SuspensionModel.build(
            cal, [pd.Timestamp('2024-01-02'), pd.Timestamp('2024-01-04')])
        assert len(model.suspended_days) == 1
        assert model.suspended_days == frozenset(
            [pd.Timestamp('2024-01-03').date()])

    def test_trading_day_index_forward_fills(self):
        """停牌日 → 沿用上一根 bar (市值持平, 精确口径)。"""
        cal, df, days, halted = _with_halt()
        model = SuspensionModel.build(cal, df['日期'].tolist())
        idx = trading_day_index(cal, df['日期'].tolist())
        assert idx is not None
        # 交易日数 = 日历天数; 映射单调不减且不越界
        assert len(idx) == len(cal.days)
        assert idx.min() >= 0 and idx.max() < len(df)
        assert list(idx) == sorted(idx)

    def test_trading_day_index_none_without_calendar(self):
        assert trading_day_index(None, [pd.Timestamp('2024-01-01')]) is None

# ------------------------------------------------------------------ 引擎 A

def _strategy_a(view):
    """简单策略: 第 8 根买入, 第 20 根卖出。"""
    n = len(view)
    if n == 8:
        return 1
    if n == 20:
        return -1
    return 0


class TestEngineA:
    """引擎 A (backtest_framework): 停牌建模。"""

    def _run(self, calendar=None, n_days=60):
        cal, df, days, halted = _with_halt(n_days)
        eng = BacktestEngine(position_config=get_balanced_config())
        res = eng.run(df, _strategy_a, '600000', trading_calendar=calendar)
        return res, cal, df

    def test_without_calendar_not_modeled(self):
        res, _, _ = self._run(calendar=None)
        assert res['suspension_modeled'] is False
        assert res['suspension_days'] == 0
        assert res['equity_aligned_to_trading_days'] is False

    def test_with_calendar_modeled(self):
        res, cal, _ = self._run(calendar=_with_halt(60)[0])
        assert res['suspension_modeled'] is True
        assert res['suspension_days'] == 5
        assert res['equity_aligned_to_trading_days'] is True

    def test_equity_curve_aligned_to_trading_days(self):
        cal, df, days, halted = _with_halt(60)
        res, _, _ = self._run(calendar=cal)
        # 净值曲线长度 = 权益记录区间内的交易日数 (停牌日以持平点补入)
        eq = res['equity_curve']
        expected = len(cal.trading_days_between(
            pd.Timestamp(eq['date'].iloc[0]).date(),
            pd.Timestamp(eq['date'].iloc[-1]).date()))
        assert len(eq) == expected
        assert len(eq) > len(df) - 1   # 比 bar 数多 (停牌日补入)

    def test_total_return_and_drawdown_unchanged(self):
        """停牌不产生价格 → 总收益/回撤不变 (只有时间口径被修正)。"""
        cal, df, days, halted = _with_halt(60)
        r_no, _, _ = self._run(calendar=None)
        r_cal, _, _ = self._run(calendar=cal)
        assert r_cal['total_return'] == pytest.approx(r_no['total_return'])
        assert r_cal['max_drawdown'] == pytest.approx(r_no['max_drawdown'])

    def test_annualized_return_uses_trading_days(self):
        """旧实现按 bar 数年化 → 停牌期被当作没发生 (虚高)。"""
        cal, df, days, halted = _with_halt(60)
        r_no, _, _ = self._run(calendar=None)
        r_cal, _, _ = self._run(calendar=cal)
        # 分母变大 (交易日 > bar 数) → 年化绝对值更小 (不再是虚高)
        assert abs(r_cal['annualized_return']) < abs(r_no['annualized_return'])

    def test_trade_records_suspension_exposure(self):
        """逐笔记录持仓跨越的停牌交易日数。"""
        cal, df, days, halted = _with_halt(60)
        res, _, _ = self._run(calendar=cal)
        trades = res['trades']
        assert 'suspended_days' in trades.columns
        sells = trades[trades['action'] == 'sell']
        assert len(sells) >= 1
        assert sells['suspended_days'].sum() > 0


# ------------------------------------------------------------------ 引擎 B

class TestEngineB:
    """引擎 B (vectorized_backtest): 停牌建模 + 交易日时间轴。"""

    def _params(self):
        return {'ma_fast': 5, 'ma_slow': 20, 'macd_fast': 12,
                'macd_slow': 26, 'macd_signal': 9, 'rsi_period': 14,
                'bollinger_period': 20, 'bollinger_std': 2.0,
                'stop_loss_pct': 0.08, 'take_profit_pct': 0.20,
                'position_size_pct': 0.8, 'trailing_stop_pct': 0.05,
                'min_holding_days': 0}

    def _run(self, calendar=None):
        cal, df, days, halted = _with_halt(120)
        bt = VectorizedBacktester()
        m = bt.backtest(df, self._params(), trading_calendar=calendar)
        return m, cal, df

    def test_without_calendar_not_modeled(self):
        m, _, _ = self._run(None)
        assert m.suspension_days == 0
        assert m.suspension_trading_days == 0

    def test_with_calendar_reports_suspension(self):
        cal, df, days, halted = _with_halt(120)
        m = VectorizedBacktester().backtest(df, self._params(),
                                            trading_calendar=cal)
        assert m.suspension_days == 5
        assert m.suspension_trading_days == len(cal.days)

    def test_total_return_unchanged(self):
        cal, df, days, halted = _with_halt(120)
        bt = VectorizedBacktester()
        m_no = bt.backtest(df, self._params())
        m_cal = bt.backtest(df, self._params(), trading_calendar=cal)
        assert m_cal.total_return == pytest.approx(m_no.total_return)
        assert m_cal.max_drawdown == pytest.approx(m_no.max_drawdown)

    def test_annualized_return_uses_trading_days(self):
        cal, df, days, halted = _with_halt(120)
        bt = VectorizedBacktester()
        m_no = bt.backtest(df, self._params())
        m_cal = bt.backtest(df, self._params(), trading_calendar=cal)
        assert abs(m_cal.annualized_return) < abs(m_no.annualized_return)

    def test_trade_detail_records_suspension_days(self):
        cal, df, days, halted = _with_halt(120)
        bt = VectorizedBacktester()
        _, details = bt.backtest_with_details(df, self._params(),
                                               trading_calendar=cal)
        for d in details:
            assert d.suspended_days >= 0

    def test_metrics_from_trades_default_path_unchanged(self):
        """不传 trading_day_index → 旧口径逐位不变 (默认路径不建模)。"""
        pnl = np.array([1.0, -0.5, 2.0])
        holding = np.array([3.0, 4.0, 5.0])
        spans = [(0, 2), (3, 5), (6, 8)]
        close = np.linspace(10, 12, 10)
        open_arr = close * 0.999
        m = metrics_from_trades(pnl, holding, spans, close, open_arr, 0.8)
        assert m.num_trades == 3
        assert m.annualized_return != 0.0

    def test_metrics_from_trades_aligned_changes_only_time_axis(self):
        """对齐到交易日轴 → 回撤不变, 年化分母变化。"""
        pnl = np.array([1.0, -0.5, 2.0])
        holding = np.array([3.0, 4.0, 5.0])
        spans = [(0, 2), (3, 5), (6, 8)]
        close = np.linspace(10, 12, 10)
        open_arr = close * 0.999
        m_no = metrics_from_trades(pnl, holding, spans, close, open_arr, 0.8)
        # 假装 20 个交易日 (比 10 根 bar 长) → 年化分母变大
        tdi = np.clip(np.arange(20) // 2, 0, 9).astype(np.int64)
        m_al = metrics_from_trades(pnl, holding, spans, close, open_arr, 0.8,
                                   trading_day_index=tdi)
        assert m_al.max_drawdown == pytest.approx(m_no.max_drawdown)
        assert abs(m_al.annualized_return) < abs(m_no.annualized_return)


# ------------------------------------------------------------------ 引擎 D

class TestEngineD:
    """引擎 D (reversal_backtest): 停牌建模。"""

    def _bt(self, df):
        bt = ReversalBacktester()
        bt.get_stock_data = lambda code, days=365: df.copy()
        return bt

    def test_without_calendar_not_modeled(self):
        cal, df, days, halted = _with_halt(120)
        bt = self._bt(df)
        res = bt.backtest_single('600000', '测试')
        assert res is not None
        assert res.suspension_modeled is False
        assert res.suspension_days == 0

    def test_with_calendar_reports_suspension(self):
        cal, df, days, halted = _with_halt(120)
        bt = self._bt(df)
        res = bt.backtest_single('600000', '测试', trading_calendar=cal)
        assert res is not None
        assert res.suspension_modeled is True
        assert res.suspension_days == 5


# ------------------------------------------------------------------ 引擎 E

class TestEngineE:
    """引擎 E (historical_backtest_validator): 持有期按交易日。"""

    def _validator(self, stock_df, index_df):
        from historical_backtest_validator import HistoricalBacktestValidator
        v = HistoricalBacktestValidator.__new__(HistoricalBacktestValidator)
        v.cost_model = __import__('execution_model').CostModel()
        v.systems = {}
        v._calendar = None
        v._suspension_stats = {'modeled': False, 'deferred_picks': 0,
                               'deferred_trading_days_total': 0,
                               'suspended_days_total': 0}

        class _DM:
            def load(self, symbol):
                return stock_df.copy()

            def load_index(self, code):
                return index_df.copy()

        v.data_manager = _DM()
        # stub 指数加载 (不走 akshare 联网路径, 测试必须离线)
        v._load_index_data = lambda code='000300': index_df.copy()
        return v

    def _data(self, halt_len=10):
        """60 个交易日, 个股中间停牌 halt_len 天; 指数每个交易日都有行。"""
        days = pd.bdate_range('2024-01-01', periods=60)
        index_df = pd.DataFrame({'日期': days,
                                 '收盘': np.linspace(3000, 3300, len(days))})
        halted = set(days[25:25 + halt_len])
        keep = [d for d in days if d not in halted]
        rng = np.random.default_rng(2)
        close = 10 * np.cumprod(1 + rng.normal(0.001, 0.01, len(keep)))
        stock = pd.DataFrame({
            '日期': keep,
            '开盘': close * 0.999,
            '最高': close * 1.01,
            '最低': close * 0.99,
            '收盘': close,
            '成交量': 1e6,
        })
        return stock, index_df, days, halted

    def test_calendar_built_from_index(self):
        stock, index_df, days, halted = self._data()
        v = self._validator(stock, index_df)
        cal = v._get_calendar()
        assert cal is not None
        assert len(cal.days) == len(days)

    def test_holding_horizon_uses_trading_days(self):
        """旧实现按个股 bar 数 → 停牌静默拉长窗口; 现按交易日。

        到期日落在停牌区间内 → 顺延到下一个可交易日, 顺延如实记录。
        """
        stock, index_df, days, halted = self._data(halt_len=10)
        v = self._validator(stock, index_df)
        pick = str(days[0].date())
        ret, csi = v.calculate_forward_return('600000', pick, 30)
        assert ret is not None
        stats = v._stats()
        assert stats['modeled'] is True
        # 停牌顺延被如实记录
        assert stats['deferred_picks'] >= 1
        assert stats['deferred_trading_days_total'] > 0

    def test_without_calendar_falls_back_to_bar_count(self):
        """无指数数据 → 无日历 → 如实回退旧口径 (不臆造日历)。"""
        stock, index_df, days, halted = self._data(halt_len=0)
        v = self._validator(stock, pd.DataFrame())
        assert v._get_calendar() is None
        ret, csi = v.calculate_forward_return('600000', str(days[0].date()), 20)
        assert ret is not None
        assert v._stats()['modeled'] is False


# ------------------------------------------------------------------ 源码门禁

class TestSourceHonesty:
    """源码级门禁: 4 引擎必须显式支持交易日历, 且不静默伪造。"""

    def test_engines_accept_trading_calendar(self):
        assert 'trading_calendar' in inspect.signature(
            BacktestEngine.run).parameters
        assert 'trading_calendar' in inspect.signature(
            VectorizedBacktester.backtest).parameters
        assert 'trading_calendar' in inspect.signature(
            ReversalBacktester.backtest_single).parameters
        assert 'trading_calendar' in inspect.signature(
            __import__('historical_backtest_validator')
            .HistoricalBacktestValidator.calculate_forward_return).parameters

    def test_calendar_is_explicit_not_implicit(self):
        """默认 None (不建模) —— 引擎不得隐式取全局日历 (破坏可复现性)。"""
        assert inspect.signature(
            BacktestEngine.run).parameters['trading_calendar'].default is None
        assert inspect.signature(
            VectorizedBacktester.backtest
        ).parameters['trading_calendar'].default is None

    def test_execution_model_docstring_updated(self):
        """旧的"停牌: 数据侧无停牌标记 …… 不虚构交易日历"自述必须更新。"""
        import execution_model
        src = open(execution_model.__file__, encoding='utf-8').read()
        assert '不虚构交易日历' not in src
        assert '停牌' in src  # 仍如实说明停牌口径

    def test_core_suspension_is_single_source(self):
        """4 引擎不得各写一套停牌推导 —— 统一走 core/suspension.py。"""
        for mod in ('backtest_framework', 'vectorized_backtest',
                    'reversal_backtest', 'historical_backtest_validator'):
            src = open(f'.claude/skills/{mod}.py', encoding='utf-8').read()
            assert 'core.suspension' in src or 'core import suspension' in src, (
                f'{mod} 未接入 core/suspension.py')
