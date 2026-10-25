# -*- coding: utf-8 -*-
"""交易日历与停牌建模测试（审计 C-P1-12 遗留项）。

覆盖:
- core/trading_calendar: 构造 / 查询 / 交易日计数 / 缺失交易日识别
- trade_constraints: 真停牌阻断 (有日历时) + 无日历降级 (零成交启发式)
- 数据过期: 有日历时按交易日计 (节假日不误伤), 无日历时回退自然日并记 skipped
- check_close_panel: 有日历时识别落后于市场的个股 (真停牌)
"""
import json
from datetime import date, timedelta

import pandas as pd
import pytest

from core.trading_calendar import (TradingCalendar, build_calendar_from_index,
                                   get_calendar, set_calendar)
from trade_constraints import ConstraintConfig, check_close_panel, check_last_bar


def _calendar(n=30, start='2024-01-01'):
    """连续工作日日历 (合成, 不含节假日 —— 用于确定性断言)"""
    days = pd.bdate_range(start, periods=n)
    return TradingCalendar.from_dates(list(days), source='test')


def _ohlcv(dates, close=10.0, volume=1_000_000.0):
    idx = pd.DatetimeIndex(dates)
    return pd.DataFrame({
        '日期': idx,
        '开盘': close, '最高': close * 1.01, '最低': close * 0.99,
        '收盘': close, '成交量': volume, '成交额': volume * close,
    })


class TestTradingCalendar:
    def test_from_index(self):
        df = pd.DataFrame({'日期': pd.bdate_range('2024-01-01', periods=10)})
        cal = TradingCalendar.from_index(df)
        assert cal is not None and len(cal) == 10
        assert cal.source == 'index'
        assert cal.first_day == date(2024, 1, 1)
        assert cal.last_day == date(2024, 1, 12)

    def test_from_index_empty_returns_none(self):
        """无数据 → None（不返回空日历假装可用）"""
        assert TradingCalendar.from_index(pd.DataFrame()) is None
        assert TradingCalendar.from_index(None) is None

    def test_from_index_datetimeindex(self):
        df = pd.DataFrame({'close': range(5)},
                          index=pd.bdate_range('2024-02-01', periods=5))
        cal = TradingCalendar.from_index(df)
        assert cal is not None and len(cal) == 5

    def test_is_trading_day(self):
        cal = _calendar()
        assert cal.is_trading_day('2024-01-01') is True
        assert cal.is_trading_day('2024-01-06') is False   # 周六
        assert cal.is_trading_day('not-a-date') is False

    def test_latest_trading_day(self):
        cal = _calendar()
        # 2024-01-06 是周六 → 最近交易日应为 2024-01-05
        assert cal.latest_trading_day('2024-01-06') == date(2024, 1, 5)
        assert cal.latest_trading_day('2024-01-01') == date(2024, 1, 1)

    def test_trading_days_between(self):
        cal = _calendar()
        days = cal.trading_days_between('2024-01-01', '2024-01-05')
        assert days == [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3),
                        date(2024, 1, 4), date(2024, 1, 5)]

    def test_trading_days_since_counts_missing(self):
        cal = _calendar()
        # 停在 1/1, 到 1/5 缺 4 个交易日
        assert cal.trading_days_since('2024-01-01', '2024-01-05') == 4
        assert cal.trading_days_since('2024-01-05', '2024-01-05') == 0

    def test_missing_trading_days_detects_suspension(self):
        cal = _calendar()
        stock_dates = pd.bdate_range('2024-01-01', periods=5).append(
            pd.bdate_range('2024-01-10', periods=3))
        missing = cal.missing_trading_days(stock_dates, '2024-01-01',
                                            '2024-01-12')
        assert date(2024, 1, 8) in missing and date(2024, 1, 9) in missing
        assert date(2024, 1, 1) not in missing

    def test_save_and_load_roundtrip(self, tmp_path):
        cal = _calendar(n=5)
        path = cal.save(data_dir=str(tmp_path))
        assert path.exists()
        loaded = TradingCalendar.from_local_cache(path)
        assert loaded is not None and len(loaded) == 5
        assert loaded.source == 'test'

    def test_local_cache_missing_returns_none(self, tmp_path):
        assert TradingCalendar.from_local_cache(
            tmp_path / 'nope.json') is None

    def test_build_calendar_from_index_injects_process_calendar(self):
        df = pd.DataFrame({'日期': pd.bdate_range('2024-03-01', periods=8)})
        cal = build_calendar_from_index(df, data_dir='/tmp/_cal_test')
        assert cal is not None
        assert get_calendar() is not None
        set_calendar(None)

    def test_build_calendar_from_none_returns_none(self):
        assert build_calendar_from_index(None) is None
        set_calendar(None)


class TestSuspensionDetection:
    def test_suspended_stock_blocked_with_calendar(self):
        """停牌 (缺交易日) → 阻断买卖"""
        cal = _calendar()
        df = _ohlcv(pd.bdate_range('2024-01-01', periods=3))
        report = check_last_bar(df, code='600000', side='buy',
                                calendar=cal, as_of='2024-01-10')
        assert not report.ok
        assert any('交易日无行情' in r for r in report.blocked_reasons)
        assert report.details['missing_trading_days'] > 0

    def test_fresh_stock_not_blocked(self):
        cal = _calendar()
        dates = cal.trading_days_between('2024-01-01', '2024-01-30')[-1:]
        df = _ohlcv(dates)
        report = check_last_bar(df, code='600000', side='buy',
                                calendar=cal, as_of=dates[-1])
        assert report.ok, report.blocked_reasons
        assert report.details['missing_trading_days'] == 0

    def test_no_calendar_falls_back_to_zero_volume_and_records_skipped(self):
        """无日历时: 零成交启发式仍生效, 且如实记 '真停牌未检查'"""
        set_calendar(None)
        df = _ohlcv(pd.bdate_range('2024-01-01', periods=3), volume=0.0)
        report = check_last_bar(df, code='600000', side='buy',
                                as_of='2024-01-05')
        assert not report.ok
        assert any('零成交量' in r for r in report.blocked_reasons)
        assert any('无交易日历' in c for c in report.skipped_checks)

    def test_no_calendar_and_normal_volume_not_blocked(self):
        set_calendar(None)
        df = _ohlcv(pd.bdate_range('2024-01-01', periods=3))
        report = check_last_bar(df, code='600000', side='buy',
                                as_of='2024-01-05')
        assert report.ok, report.blocked_reasons
        assert any('无交易日历' in c for c in report.skipped_checks)

    def test_suspension_check_can_be_disabled(self):
        cal = _calendar()
        df = _ohlcv(pd.bdate_range('2024-01-01', periods=2))
        cfg = ConstraintConfig(suspension_check=False, min_price=0.0)
        report = check_last_bar(df, code='600000', side='buy', config=cfg,
                                calendar=cal, as_of='2024-01-10')
        assert report.ok, report.blocked_reasons
        assert report.details['missing_trading_days'] > 0


class TestStaleDataTradingDayBasis:
    def test_stale_uses_trading_days_when_calendar_present(self):
        """节假日/周末不计入过期 (交易日口径)"""
        cal = _calendar()
        df = _ohlcv(pd.bdate_range('2024-01-01', periods=2))
        cfg = ConstraintConfig(max_stale_days=1, min_price=0.0,
                               suspension_check=False)
        # 数据最后到 1/2, as_of=1/5 (周五) → 缺 3 个交易日 (1/3, 1/4, 1/5)
        report = check_last_bar(df, code='600000', side='buy', config=cfg,
                                calendar=cal, as_of='2024-01-05')
        assert report.details['stale_basis'] == 'trading_days'
        assert report.details['stale_days'] == 3
        assert not report.ok

    def test_stale_falls_back_to_calendar_days_without_calendar(self):
        set_calendar(None)
        df = _ohlcv(pd.bdate_range('2024-01-01', periods=2))
        cfg = ConstraintConfig(max_stale_days=1, min_price=0.0,
                               suspension_check=False)
        report = check_last_bar(df, code='600000', side='buy', config=cfg,
                                as_of='2024-01-05')
        assert report.details['stale_basis'] == 'calendar_days'
        assert any('无交易日历' in c for c in report.skipped_checks)

    def test_weekend_gap_not_stale_with_calendar(self):
        """周五的数据 + 周一的 as_of → 只缺 1 个交易日 (周一)"""
        cal = _calendar()
        df = _ohlcv([date(2024, 1, 5)])
        cfg = ConstraintConfig(max_stale_days=1, min_price=0.0,
                               suspension_check=False)
        report = check_last_bar(df, code='600000', side='buy', config=cfg,
                                calendar=cal, as_of='2024-01-08')
        assert report.details['stale_days'] == 1
        assert report.ok, report.blocked_reasons


class TestClosePanelSuspension:
    def test_panel_drops_suspended_stock(self):
        cal = _calendar()
        days = list(pd.bdate_range('2024-01-01', periods=6))
        # index=股票码, columns=日期; 600000 全有, 600001 只到第 2 天 (之后停牌)
        panel = pd.DataFrame(
            [[10.0] * 6, [10.0] * 2 + [None] * 4],
            index=['600000', '600001'], columns=days)
        keep, reasons = check_close_panel(panel, calendar=cal)
        assert bool(keep['600000']) is True
        assert bool(keep['600001']) is False
        assert '交易日无行情' in reasons['600001']

    def test_panel_without_calendar_keeps_previous_behavior(self):
        set_calendar(None)
        days = list(pd.bdate_range('2024-01-01', periods=4))
        panel = pd.DataFrame([[10.0] * 4], index=['600000'], columns=days)
        keep, reasons = check_close_panel(panel)
        assert bool(keep['600000']) is True
        assert reasons == {}


class TestEnsureCalendar:
    def test_ensure_uses_local_cache(self, tmp_path):
        from core.trading_calendar import ensure_calendar
        _calendar(n=4).save(data_dir=str(tmp_path))
        set_calendar(None)
        cal = ensure_calendar(data_dir=str(tmp_path))
        assert cal is not None and len(cal) == 4
        set_calendar(None)

    def test_ensure_returns_none_without_data(self, tmp_path):
        from core.trading_calendar import ensure_calendar
        set_calendar(None)
        assert ensure_calendar(data_dir=str(tmp_path)) is None

    def test_ensure_reuses_injected_calendar(self, tmp_path):
        from core.trading_calendar import ensure_calendar
        cal = _calendar(n=7)
        set_calendar(cal)
        assert ensure_calendar(data_dir=str(tmp_path)) is cal
        set_calendar(None)


class TestCalendarPersistence:
    def test_saved_calendar_json_shape(self, tmp_path):
        cal = _calendar(n=3)
        path = cal.save(data_dir=str(tmp_path))
        raw = json.loads(path.read_text(encoding='utf-8'))
        assert raw['source'] == 'test'
        assert len(raw['trading_days']) == 3
