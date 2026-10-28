# -*- coding: utf-8 -*-
"""
历史回测验证器 - Historical Backtest Validator

按原开发计划验证方案第4项: 模拟30个历史日期的推荐，检查实际收益。

功能:
- 选取30个历史日期(均匀分布在数据范围内)
- 每个日期只使用该日期之前的数据(严格防前瞻偏差)
- 检测当日大盘态势
- 选择对应体制的指标体系
- 用当日数据生成Top N推荐
- 跟踪6-18个月后的实际收益
- 对比沪深300买入持有基准
- 输出胜率、中位收益、最大回撤等指标

用法:
    python historical_backtest_validator.py --systems optimization_result.json
    python historical_backtest_validator.py --n-dates 50 --top 10 --holding-days 180
"""

import argparse
import json
import sys
import traceback
import numpy as np
import pandas as pd

from core.indicators import sma as _core_sma
from core.suspension import SuspensionModel
from core.trading_calendar import TradingCalendar
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from historical_data_manager import HistoricalDataManager
from daily_signal_generator import generate_signal
from parameter_space import ParameterSpace
from execution_model import CostModel


@dataclass
class HistoricalPick:
    """单次历史推荐记录"""
    pick_date: str                # 推荐日期
    regime: str                   # 当日大盘体制
    regime_cn: str                # 体制中文
    system_name: str              # 使用的体系
    top_stocks: list              # Top N股票 [(symbol, name, buy_score), ...]
    forward_returns: dict         # 各持有期收益 {holding_days: median_return}
    csi300_return: dict           # 同区间沪深300收益
    hit_target_10pct: dict        # 是否达标 {holding_days: bool}
    # 审计 H3: 覆盖度记账 (旧实现用 0 当"无数据"哨兵 → 真实 0 收益样本
    # 被静默丢弃, 且报告看不出覆盖率)
    n_picks: int = 0                       # 当日推荐数
    n_evaluated: dict = field(default_factory=dict)  # {hd: 有效样本数}
    n_missing: dict = field(default_factory=dict)    # {hd: 数据不足数}
    valid: dict = field(default_factory=dict)        # {hd: 该持有期是否有效}


@dataclass
class ValidationReport:
    """历史验证报告"""
    n_dates: int
    holding_days_list: list       # [90, 180, 270, 365, 540]
    picks: list                   # list[HistoricalPick]
    # 聚合统计
    aggregate: dict               # {holding_days: {metric: value}}
    # 体系对比
    system_breakdown: dict        # {system_name: {metric: value}}
    # 基准对比
    beat_benchmark: dict          # {holding_days: pct_stocks_beat_csi300}
    # 停牌建模口径 (审计 H5): 持有期按交易日计 → 停牌顺延如实记录
    suspension: dict = field(default_factory=dict)
    # 股票池口径 (审计 H4): point-in-time 参考日 + 幸存者偏差标记
    universe_meta: dict = field(default_factory=dict)
    # 样本外判定 (审计 H3): 参数拟合区间 vs 验证区间
    oos: dict = field(default_factory=dict)
    # 覆盖度 (审计 H3): {holding_days: {n_picks, n_evaluated, n_missing, coverage}}
    coverage: dict = field(default_factory=dict)
    # 报告主口径持有期 (审计 H3: 旧实现把 180 天写死)
    primary_holding_days: int = 0


class HistoricalBacktestValidator:
    """
    历史回测验证器

    严格防前瞻偏差:
    - 只使用 pick_date 当日及之前的数据
    - pick_date 当日的信号基于 iloc[:pick_idx+1] 的数据

    审计 H3 (验证链重做) —— 本引擎**不做回测**:
    - 旧实现挂着 `self.backtester = VectorizedBacktester()` 却**从未使用**
      (全文仅实例化那一处) —— 让人误以为"验证链跑过回测引擎"。已删除:
      本引擎的评估口径是**买入持有的前瞻收益** (含A股往返成本), 与
      4 套回测引擎不是一回事, 不该借一个死属性暗示两者等价。
    - 参数的**样本外隔离**: 验证用的参数来自优化产物 (在整段历史上拟合),
      故 pick 日期必须落在参数拟合区间**之后**才谈得上"样本外验证";
      拟合区间来自 manifest 的 `data_start`/`data_end` (优化器已落盘)。
      无样本外区间 → **不出验证结论** (不拿样本内结果冒充)。
    - 样本保留: 旧实现用 `forward_returns[hd] != 0` 过滤 pick (0 既是
      "无数据"哨兵又可能是真实收益) → 现改为显式有效性标记 + 覆盖度记账。
    """

    REGIME_CN = {
        'BULL': '牛市', 'BEAR': '熊市', 'SIDEWAYS': '横盘震荡',
        'CRASH': '暴跌', 'RECOVERY': '反弹'
    }

    # 审计 H3 (段2): 点时股票池的门槛 —— 只要求"当时有足够历史算信号"
    # (信号本身需要 ≥252 根 bar, 见 generate_top_picks)。
    # 旧实现用 min_history_days=5000/min_rows=2000 —— 那是**墙钟锚定**的
    # 口径 (今天往前 13.7 年), 套到历史日期上既过严又口径错位。
    UNIVERSE_MIN_HISTORY_DAYS = 504   # ≈2 自然年 (相对 as_of)
    UNIVERSE_MIN_ROWS = 252           # ≥1 年交易日 (信号所需最小历史)

    def __init__(self, data_dir="./stock_data",
                 optimization_result_file=None):
        self.data_dir = data_dir
        self.data_manager = HistoricalDataManager(data_dir)
        self.cost_model = CostModel()  # 前向收益统一扣减A股往返成本
        self.systems = {}  # {regime: IndicatorSystem}
        self._calendar = None  # 审计 H5: 交易日历 (由指数行情反推, 懒加载)
        self._universe_meta = {}   # 审计 H4: 股票池口径 (幸存者偏差标记)
        # 审计 H3: 参数拟合区间 (manifest 的 data_start/data_end) → 样本外判定
        self._param_fit_range = {}
        self._suspension_stats = {
            'modeled': False,
            'deferred_picks': 0,       # 因停牌顺延出场的选股次数
            'deferred_trading_days_total': 0,  # 顺延的累计**交易日**数
            'suspended_days_total': 0,  # 区间内观测到的停牌交易日数
        }
        self._load_systems(optimization_result_file)

    def _get_calendar(self, injected=None):
        """取交易日历 (审计 H5): 由**指数行情**反推 —— 指数每个交易日都有行,
        个股缺行才是真停牌 (不会误伤节假日)。无指数数据 → None (不建模,
        如实回退旧口径, 不臆造日历)。可显式注入 (优先)。"""
        if injected is not None:
            return injected
        cached = getattr(self, '_calendar', None)
        if cached is not None:
            return cached
        try:
            index_df = self._load_index_data('000300')
        except Exception:
            index_df = pd.DataFrame()
        if len(index_df) == 0:
            return None
        cal = TradingCalendar.from_index(index_df)
        if cal is not None:
            self._calendar = cal
            self._stats()['modeled'] = True
        return cal

    def _stats(self) -> dict:
        """停牌统计累加器 (对 __new__ 构造的实例也安全)。"""
        stats = getattr(self, '_suspension_stats', None)
        if stats is None:
            stats = {'modeled': False, 'deferred_picks': 0,
                     'deferred_trading_days_total': 0,
                     'suspended_days_total': 0}
            self._suspension_stats = stats
        return stats

    def _load_systems(self, filepath):
        """加载指标体系

        审计 H3: 同时读出**参数拟合区间** (manifest 顶层 `data_start`/
        `data_end`, 优化器已落盘) —— 验证日期必须落在该区间**之后**,
        否则"验证"用的参数已经见过这些日期的数据 = 样本内冒充样本外。
        旧 manifest 无这两项 → 如实标记为"未知" (不假装是样本外)。
        """
        if not filepath or not Path(filepath).exists():
            print("[WARN] 未提供优化结果文件，仅使用默认参数")
            self._param_fit_range = {'known': False, 'data_start': None,
                                     'data_end': None,
                                     'note': '未提供优化结果文件 → 参数拟合区间未知'}
            return

        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 审计 H3: 参数拟合区间 (样本外判定的前提)
        d_start = data.get('data_start')
        d_end = data.get('data_end')
        self._param_fit_range = {
            'known': bool(d_start and d_end),
            'data_start': d_start,
            'data_end': d_end,
            'note': '' if (d_start and d_end) else
                    '优化产物未记录 data_start/data_end → 参数拟合区间未知',
        }

        for sys_data in data.get('systems', []):
            regimes = sys_data.get('applicable_regimes', [])
            name = sys_data.get('name', '')
            # 提取体制标识
            for regime in regimes:
                if regime not in self.systems:
                    self.systems[regime] = sys_data
                else:
                    # 优先保留专用型(applicable_regimes 短的)
                    existing_regimes = len(self.systems[regime].get('applicable_regimes', []))
                    if len(regimes) < existing_regimes:
                        self.systems[regime] = sys_data

        print(f"[OK] 加载 {len(self.systems)} 个体制指标体系")

    def select_pick_dates(self, n_dates=30, min_history_days=252*3,
                          index_code='000300', oos_only=True) -> list:
        """
        均匀选择历史推荐日期

        审计 H3 (样本外隔离): 验证用的参数是在**整段历史**上拟合的 →
        pick 日期必须落在参数拟合区间 (`data_end`) **之后**, 否则参数已经
        见过这些日期的数据 → "验证"实为样本内。故:
        - 拟合区间已知 → 只在**区间之后**的交易日里均匀取日期;
        - 拟合区间未知 (旧 manifest) → 仍返回日期, 但由 validate() 如实
          标记 `oos.available=False` (不假装样本外);
        - 区间之后**没有可用日期** → 返回空列表 → validate() **不出
          验证结论** (用户拍板: 默认严格)。

        Parameters:
        -----------
        n_dates : int
            选取日期数
        min_history_days : int
            最少历史天数(确保每个日期都有足够历史数据)
        oos_only : bool
            True → 只取参数拟合区间之后的日期 (样本外); False → 全区间取
                (仅供显式声明 in-sample 的退路使用)
        """
        # 加载指数数据 (尝试多个来源)
        index_data = self._load_index_data(index_code)

        if len(index_data) == 0:
            print("[ERROR] 无法获取指数数据，请先获取000300指数数据")
            return []

        index_data['日期'] = pd.to_datetime(index_data['日期'])
        index_data = index_data.sort_values('日期').reset_index(drop=True)

        # 审计 H3: 样本外候选区间的起点 = 参数拟合区间终点之后
        start_idx = 0
        fit = getattr(self, '_param_fit_range', {}) or {}
        if oos_only and fit.get('known') and fit.get('data_end'):
            end_dt = pd.Timestamp(fit['data_end'])
            start_idx = int((index_data['日期'] > end_dt).sum())
            if start_idx == 0:
                print(f"[WARN] 参数拟合区间结束于 {fit['data_end']}, 之后没有"
                      f"可用交易日 → 无法构造样本外验证 (不出验证结论)")
                return []
            print(f"[OK] 样本外区间: {fit['data_end']} 之后 "
                  f"({len(index_data) - start_idx} 个交易日)")

        # 跳过前min_history_days天 (相对候选区间起点)
        skip = start_idx + min_history_days
        if len(index_data) <= skip + n_dates:
            print(f"[WARN] 数据量不足，仅 {len(index_data) - start_idx} 天")
            skip = min(start_idx, max(0, len(index_data) - n_dates - 1))

        # 均匀间隔选日期
        available = len(index_data) - skip
        step = max(1, available // n_dates)
        pick_indices = [skip + i * step for i in range(n_dates)]
        pick_indices = [i for i in pick_indices if i < len(index_data)][:n_dates]

        dates = [str(index_data['日期'].iloc[i].date())
                 for i in pick_indices]

        if dates:
            print(f"[OK] 选取 {len(dates)} 个历史日期: {dates[0]} ~ {dates[-1]}")
        return dates

    def _load_index_data(self, index_code='000300'):
        """加载指数数据，尝试多个来源"""
        # 1. 本地缓存 (指数命名空间, 审计 M12: 000001 是上证指数不是平安银行)
        data = self.data_manager.load_index(index_code)
        if len(data) > 0:
            return data

        # 2. 尝试akshare API
        try:
            import akshare as ak
            symbol = f'sh{index_code}'
            df = ak.stock_zh_index_daily(symbol=symbol)
            if df is not None and len(df) > 0:
                col_map = {'date': '日期', 'open': '开盘', 'high': '最高',
                           'low': '最低', 'close': '收盘', 'volume': '成交量'}
                df = df.rename(columns=col_map)
                df['日期'] = pd.to_datetime(df['日期'])
                df = df.sort_values('日期').reset_index(drop=True)
                print(f"[OK] 从akshare获取指数{index_code}: {len(df)}天")
                return df
        except Exception as e:
            print(f"[WARN] akshare获取指数失败: {e}")

        # 3. 备选: 用000001(上证指数)
        if index_code != '000001':
            data = self.data_manager.load_index('000001')
            if len(data) > 0:
                print("[INFO] 用上证指数(000001)替代沪深300")
                return data
            try:
                import akshare as ak
                df = ak.stock_zh_index_daily(symbol='sh000001')
                if df is not None and len(df) > 0:
                    col_map = {'date': '日期', 'open': '开盘', 'high': '最高',
                               'low': '最低', 'close': '收盘', 'volume': '成交量'}
                    df = df.rename(columns=col_map)
                    df['日期'] = pd.to_datetime(df['日期'])
                    df = df.sort_values('日期').reset_index(drop=True)
                    print(f"[OK] 从akshare获取上证指数: {len(df)}天")
                    return df
            except Exception:
                pass

        return pd.DataFrame()

    def detect_regime(self, pick_date: str) -> str:
        """检测当日大盘态势"""
        index_data = self._load_index_data('000300')
        if len(index_data) == 0:
            return 'SIDEWAYS'

        index_data['日期'] = pd.to_datetime(index_data['日期'])
        index_data = index_data[index_data['日期'] <= pd.to_datetime(pick_date)]
        if len(index_data) < 120:
            return 'SIDEWAYS'

        close = index_data['收盘'].astype(float)
        ma60 = _core_sma(close, 60).iloc[-1]
        ma120 = _core_sma(close, 120).iloc[-1]
        ret_20d = (close.iloc[-1] / close.iloc[-20] - 1) * 100 if len(close) >= 20 else 0
        ret_month = (close.iloc[-1] / close.iloc[-21] - 1) * 100 if len(close) >= 21 else 0

        if ret_month < -10 or ret_20d < -8:
            return 'CRASH'
        if ma60 > ma120 and ret_20d > 5:
            return 'BULL'
        if ma60 < ma120 and ret_20d < -5:
            return 'BEAR'
        if ma60 > ma120:
            return 'BULL'
        if ma60 < ma120:
            return 'BEAR'
        return 'SIDEWAYS'

    def get_params_for_regime(self, regime: str) -> tuple:
        """获取体制对应参数"""
        if regime in self.systems:
            sys_data = self.systems[regime]
            return sys_data.get('params'), sys_data.get('name', '未命名')

        # 备选: 通用基线/稳健型
        for key in ['GLOBAL', 'ROBUST']:
            if key in self.systems:
                sys_data = self.systems[key]
                return sys_data.get('params'), sys_data.get('name', '默认')

        # 最后备选: 默认参数
        return ParameterSpace.get_defaults(), '默认参数'

    def generate_top_picks(self, pick_date: str, params: dict,
                          universe: list, top_n: int = 10) -> list:
        """
        基于当日及之前数据生成Top N推荐

        Returns:
        --------
        list of (symbol, name, buy_score, signal)
        """
        picks = []
        pick_dt = pd.to_datetime(pick_date)

        for sym in universe:
            try:
                data = self.data_manager.load(sym)
                if len(data) < 252:
                    continue

                # 严格只使用pick_date及之前数据
                data['日期'] = pd.to_datetime(data['日期'])
                data = data[data['日期'] <= pick_dt].reset_index(drop=True)
                if len(data) < 60:
                    continue

                sig = generate_signal(data, params)
                if sig is None:
                    continue

                if sig['signal'] == 'BUY':
                    picks.append({
                        'symbol': sym,
                        'name': self.data_manager.get_stock_name(sym),
                        'buy_score': sig['buy_score'],
                        'signal': sig['signal'],
                        'strength': sig['strength'],
                        'entry_price': data.iloc[-1]['收盘'],
                    })
            except Exception:
                continue

        # 按买入得分排序
        picks.sort(key=lambda x: x['buy_score'], reverse=True)
        return picks[:top_n]

    def calculate_forward_return(self, symbol: str, pick_date: str,
                                  holding_days: int,
                                  trading_calendar=None) -> tuple:
        """
        计算从pick_date买入并持有holding_days天的实际收益

        审计 H5 (停牌建模): 旧实现用**个股 bar 数**计持有窗口
        (`actual_days = min(holding_days, len(stock_data) - 1)`) → 停牌把
        窗口**静默拉长** (60 根 bar 可能横跨 75 个交易日) → 不同个股的
        实际持有期不可比, 且"持有 N 天"的语义名不副实。现按**交易日**计:
        到期日 = pick 日后第 N 个交易日; 个股在到期日停牌 → 顺延到下一个
        可交易日 (现实: 卖不掉只能继续持有), 顺延的交易日数如实记录。
        无交易日历 (无指数数据) → 如实回退旧口径, 不臆造日历。

        trading_calendar: 可显式注入交易日历 (默认由指数行情反推)。

        Returns:
        --------
        (return_pct, csi300_return_pct) or (None, None) if no data
        """
        pick_dt = pd.to_datetime(pick_date)
        cal = self._get_calendar(trading_calendar)

        # 交易日口径需要更宽的取数窗口 (停牌顺延会吃掉余量)
        span_days = int(holding_days * 2.5) + 15 if cal is not None \
            else int(holding_days * 1.5)
        end_dt = pick_dt + timedelta(days=span_days)

        # 股票收益
        stock_data = self.data_manager.load(symbol)
        if len(stock_data) == 0:
            return None, None
        stock_data['日期'] = pd.to_datetime(stock_data['日期'])
        stock_data = stock_data[
            (stock_data['日期'] >= pick_dt) & (stock_data['日期'] <= end_dt)
        ].reset_index(drop=True)

        if len(stock_data) < 2:
            return None, None

        # 入场: pick日收盘出信号 → 次一交易日开盘成交(信号日已在数据中则取其后一根)
        entry_row = 1 if stock_data.iloc[0]['日期'] <= pick_dt else 0

        actual_days = None
        exit_row = None
        deferral_days = 0
        if cal is not None:
            # 交易日口径的到期日 (审计 H5)
            tdays = cal.trading_days_between(
                pick_dt, pick_dt + timedelta(days=span_days))
            if len(tdays) > holding_days:
                horizon = tdays[holding_days]
                # 该股的停牌模型 (统一走 core/suspension.py)
                model = SuspensionModel.build(
                    cal, stock_data['日期'].dt.date.tolist())
                exit_day = (model.next_tradable_after(horizon)
                            if model is not None else horizon)
                dates = stock_data['日期'].values
                pos = int(np.searchsorted(
                    dates, np.datetime64(pd.Timestamp(exit_day)), side='left'))
                if pos < len(stock_data):
                    exit_row = pos
                    if model is not None:
                        deferral_days = model.suspended_days_between(
                            horizon, exit_day)
            if exit_row is None:
                # 日历覆盖不足 / 到期日无行情 → 如实回退旧口径 (bar 数)
                actual_days = min(holding_days, len(stock_data) - 1)
        else:
            actual_days = min(holding_days, len(stock_data) - 1)

        if actual_days is not None:
            if actual_days < 1:
                return None, None
            if actual_days <= entry_row:
                return None, None
            exit_row = int(actual_days)

        if exit_row is None or exit_row <= entry_row:
            return None, None

        # 审计 H5: 停牌顺延的观测 (如实记录, 不静默)
        if cal is not None and deferral_days > 0:
            stats = self._stats()
            stats['deferred_picks'] += 1
            stats['deferred_trading_days_total'] += deferral_days

        raw_entry = stock_data.iloc[entry_row]['开盘']
        raw_exit = stock_data.iloc[exit_row]['收盘']
        if raw_entry <= 0:
            return None, None

        # 往返成本: 滑点+佣金+过户(买) / 另加印花税(卖)
        entry_price = self.cost_model.buy_price_incl(float(raw_entry))
        exit_price = self.cost_model.sell_price_incl(float(raw_exit))
        stock_return = (exit_price / entry_price - 1) * 100

        # 沪深300同期收益 — 与个股入场/出场日期严格对齐(同窗口可比)
        csi_data = self._load_index_data('000300')
        if len(csi_data) == 0:
            return stock_return, None

        csi_data['日期'] = pd.to_datetime(csi_data['日期'])
        stock_entry_dt = stock_data.iloc[entry_row]['日期']
        stock_exit_dt = stock_data.iloc[exit_row]['日期']
        csi_aligned = csi_data[
            (csi_data['日期'] >= stock_entry_dt) & (csi_data['日期'] <= stock_exit_dt)
        ].reset_index(drop=True)

        if len(csi_aligned) < 2:
            return stock_return, None

        # 基准取毛收益(指数点位不套用个股往返成本: 无印花税/佣金口径,
        # 且净策略 vs 毛基准是偏保守方向, 不虚增跑赢比例)
        csi_entry = float(csi_aligned.iloc[0]['收盘'])
        csi_exit = float(csi_aligned.iloc[-1]['收盘'])
        if csi_entry <= 0:
            return stock_return, None
        csi_return = (csi_exit / csi_entry - 1) * 100

        return stock_return, csi_return

    def validate(self, n_dates=30, top_n=10,
                 holding_days_list=None,
                 universe=None,
                 universe_as_of=None,
                 universe_mode='per_pick',
                 allow_in_sample=False,
                 primary_holding_days=None) -> ValidationReport:
        """
        运行历史回测验证

        审计 H3 (验证链重做) 的三条硬约束:
        ① **样本外隔离**: pick 日期必须落在参数拟合区间 (`data_end`) 之后;
           无可用样本外区间 → **不出验证结论** (报告里如实说明原因);
           显式 `allow_in_sample=True` 才允许退化为样本内 (报告标红)。
        ② **股票池点时**: `universe_mode='per_pick'` (默认) → 每个 pick
           日期用**该日期**的 PIT 股票池 (旧实现一个池子覆盖所有日期 →
           对最早的日期是未来视角); `'single'` → 统一池 (快, 有偏, 如实标记)。
        ③ **样本保留**: 聚合不再用 `forward_returns[hd] != 0` 过滤 (0 既是
           "无数据"哨兵又可能是真实收益) → 改用显式有效性标记 + 覆盖度记账。

        Parameters:
        -----------
        n_dates : int
            历史日期数
        top_n : int
            每次推荐的Top N股票
        holding_days_list : list
            持有天数列表, 默认 [90, 180, 270, 365, 540]
        universe : list or None
            股票池, None则用点时股票池
        universe_as_of : date or None
            统一池 (universe_mode='single') 的 point-in-time 截止日
        universe_mode : str
            'per_pick' (默认, 每个 pick 日期各自的 PIT 池) / 'single'
        allow_in_sample : bool
            True → 允许在无样本外区间时退化为样本内 (报告如实标注);
            默认 False = 无样本外区间即不出验证结论
        primary_holding_days : int or None
            报告的主口径持有期 (默认取 holding_days_list 的中位项;
            旧实现把 180 天写死 → 换持有期列表时报告会跟着变)
        """
        if holding_days_list is None:
            holding_days_list = [90, 180, 270, 365, 540]
        if primary_holding_days is None:
            primary_holding_days = sorted(holding_days_list)[
                len(holding_days_list) // 2]

        # ---- ① 样本外判定 (默认严格: 无法构造样本外 → 不出验证结论) ----
        fit = getattr(self, '_param_fit_range', {}) or {}
        oos = {
            'available': False,
            'in_sample': False,
            'param_fit_start': fit.get('data_start'),
            'param_fit_end': fit.get('data_end'),
            'fit_range_known': bool(fit.get('known')),
            'reason': '',
        }

        if not oos['fit_range_known'] and not allow_in_sample:
            # 拟合区间未知 → 无法判定样本外 → 按"默认严格"不出验证结论
            oos['reason'] = (fit.get('note') or
                             '参数产物未记录拟合区间 (data_start/data_end) '
                             '→ 无法判定样本外')
            oos['reason'] += ' → 按默认严格口径, **不出验证结论** ' \
                             '(如确需样本内验证请显式 allow_in_sample=True)'
            print(f"[ERROR] {oos['reason']}")
            return self._empty_report(holding_days_list, oos,
                                      primary_holding_days)

        # 选择历史日期 (样本外: 只取参数拟合区间之后)
        pick_dates = self.select_pick_dates(n_dates=n_dates,
                                            oos_only=not allow_in_sample)
        if not pick_dates:
            oos['reason'] = ('参数拟合区间之后没有可用交易日 → 无法构造'
                             '样本外验证 → 不出验证结论')
            print(f"[ERROR] {oos['reason']}")
            return self._empty_report(holding_days_list, oos,
                                      primary_holding_days)

        if oos['fit_range_known'] and not allow_in_sample:
            oos['available'] = True
            oos['reason'] = (f"pick 日期全部位于参数拟合区间终点 "
                             f"{fit.get('data_end')} 之后 → 样本外")
        else:
            oos['in_sample'] = True
            oos['reason'] = (fit.get('note') or
                             '未声明参数拟合区间 → 无法判定样本外')
            if allow_in_sample:
                oos['reason'] = ('allow_in_sample=True → 显式退化为**样本内**'
                                 f"验证 (参数拟合区间: {fit.get('data_start')}"
                                 f" ~ {fit.get('data_end')})")
            print(f"[WARN] {oos['reason']}")

        # ---- ② 股票池 (per_pick: 每个日期各自的 PIT 池) ----
        pick_pools = {}
        if universe is not None:
            # 调用方自带股票池 → 其点时口径/幸存者偏差由调用方负责,
            # 本引擎**不假装知道** (如实留空 + 说明)
            self._universe_meta = {
                'source': 'caller_supplied',
                'mode': 'caller_supplied',
                'n_stocks': len(universe),
                'survivorship_bias': None,
                'survivorship_note': ('股票池由调用方提供 → 其点时口径与'
                                       '幸存者偏差本引擎未核查 (不假装知道)'),
            }
        elif universe_mode == 'per_pick':
            self._universe_meta = {
                'source': 'point_in_time_per_pick',
                'mode': 'per_pick',
                'survivorship_bias': True,
                'survivorship_note': ('本地缓存仅含当前在市股票; 当时已退市的'
                                       '股票不在池内 → 股票池仍带幸存者偏差'
                                       ' (无法用本地数据消除, 只能标记)'),
                'pools': {},
            }
            for d in pick_dates:
                try:
                    pool = self.data_manager.get_universe(
                        min_history_days=self.UNIVERSE_MIN_HISTORY_DAYS,
                        min_rows=self.UNIVERSE_MIN_ROWS, as_of=d)
                except (AttributeError, TypeError):
                    pool = self.data_manager.get_universe(
                        min_rows=self.UNIVERSE_MIN_ROWS)
                except ValueError as e:
                    # 缓存不覆盖该日期 → 该 pick **无法用点时池**评估
                    # (H4 的严格口径) → 如实跳过该日期并记录原因,
                    # 不用"部分覆盖的池"顶替 (那是静默有偏)
                    self._universe_meta.setdefault('skipped_dates', {})[d] = \
                        str(e)[:160]
                    print(f"[WARN] {d} 点时池不可用, 跳过该日期: {str(e)[:80]}")
                    continue
                pick_pools[d] = pool
                self._universe_meta['pools'][d] = len(pool)
        else:
            # 审计 H4: point-in-time 股票池 + 幸存者偏差如实标记
            try:
                meta = self.data_manager.get_universe_meta(
                    min_rows=self.UNIVERSE_MIN_ROWS, as_of=universe_as_of)
            except (AttributeError, TypeError):
                meta = None
            if meta:
                universe = meta['universe']
                meta['mode'] = 'single'
                self._universe_meta = meta
            else:
                universe = self.data_manager.get_universe(
                    min_rows=self.UNIVERSE_MIN_ROWS)
                self._universe_meta = {'source': 'legacy', 'mode': 'single',
                                       'n_stocks': len(universe),
                                       'survivorship_bias': None}

        if not universe and not pick_pools:
            universe = []
        print(f"[INFO] 股票池: {len(universe) if universe else len(pick_pools)} 只")
        if getattr(self, '_universe_meta', None):
            m = self._universe_meta
            print(f"[INFO] 股票池口径: {m.get('mode', '-')} "
                  f"| 幸存者偏差: {'是' if m.get('survivorship_bias') else '否'}")

        picks = []

        for i, pick_date in enumerate(pick_dates, 1):
            print(f"\n[{i}/{len(pick_dates)}] 推荐日期: {pick_date}")

            # 检测体制
            regime = self.detect_regime(pick_date)
            regime_cn = self.REGIME_CN.get(regime, regime)
            print(f"  大盘态势: {regime_cn}")

            # 选择参数
            params, system_name = self.get_params_for_regime(regime)
            print(f"  使用体系: {system_name}")

            # 生成推荐 (per_pick: 用该日期的 PIT 池)
            pool = pick_pools.get(pick_date, universe)
            top_picks = self.generate_top_picks(pick_date, params, pool,
                                                top_n)
            print(f"  推荐股票: {len(top_picks)} 只")

            # 计算各持有期收益 (审计 H3: 显式记账覆盖度, 不用 0 当哨兵)
            forward_returns = {}
            csi300_returns = {}
            hit_target = {}
            valid = {}
            n_evaluated = {}
            n_missing = {}

            for hd in holding_days_list:
                stock_returns = []
                csi_returns = []
                missing = 0
                for pick in top_picks:
                    ret, csi_ret = self.calculate_forward_return(
                        pick['symbol'], pick_date, hd
                    )
                    if ret is not None:
                        stock_returns.append(ret)
                        if csi_ret is not None:
                            csi_returns.append(csi_ret)
                    else:
                        missing += 1

                if stock_returns:
                    forward_returns[hd] = float(np.median(stock_returns))
                    csi300_returns[hd] = (float(np.median(csi_returns))
                                          if csi_returns else 0)
                    hit_target[hd] = (sum(1 for r in stock_returns
                                          if r >= 10) / len(stock_returns))
                    valid[hd] = True
                else:
                    forward_returns[hd] = 0
                    csi300_returns[hd] = 0
                    hit_target[hd] = 0
                    valid[hd] = False
                n_evaluated[hd] = len(stock_returns)
                n_missing[hd] = missing

                print(f"  {hd}天后: 中位收益={forward_returns[hd]:+.1f}%, "
                      f"达标率={hit_target[hd]:.1%}, "
                      f"沪深300={csi300_returns[hd]:+.1f}% "
                      f"(有效 {n_evaluated[hd]}/{len(top_picks)})")

            pick = HistoricalPick(
                pick_date=pick_date,
                regime=regime,
                regime_cn=regime_cn,
                system_name=system_name,
                top_stocks=[(p['symbol'], p['name'], p['buy_score'])
                            for p in top_picks],
                forward_returns=forward_returns,
                csi300_return=csi300_returns,
                hit_target_10pct=hit_target,
                n_picks=len(top_picks),
                n_evaluated=n_evaluated,
                n_missing=n_missing,
                valid=valid,
            )
            picks.append(pick)

        # 聚合统计 (审计 H3: 不再按 `forward_returns[hd] != 0` 过滤 ——
        # 0 既是"无数据"哨兵又可能是**真实**的中位收益 → 旧口径把真实 0
        # 收益样本静默丢弃, 且覆盖率不可见; 现用显式有效性标记 + 覆盖度)
        aggregate = {}
        beat_benchmark = {}
        coverage = {}
        for hd in holding_days_list:
            valid_picks = [p for p in picks if p.valid.get(hd)]
            rets = [p.forward_returns[hd] for p in valid_picks]
            csi = [p.csi300_return[hd] for p in valid_picks]
            hits = [p.hit_target_10pct[hd] for p in valid_picks]

            n_eval_total = sum(p.n_evaluated.get(hd, 0) for p in picks)
            n_missing_total = sum(p.n_missing.get(hd, 0) for p in picks)
            coverage[hd] = {
                'n_picks': len(picks),
                'n_valid_picks': len(valid_picks),
                'n_evaluated': n_eval_total,
                'n_missing': n_missing_total,
                'coverage': (len(valid_picks) / len(picks)) if picks else 0.0,
            }

            if rets:
                aggregate[hd] = {
                    'median_return': float(np.median(rets)),
                    'mean_return': float(np.mean(rets)),
                    'positive_rate': sum(1 for r in rets if r > 0) / len(rets),
                    'hit_10pct_rate': sum(1 for r in rets if r >= 10) / len(rets),
                    'std_return': float(np.std(rets)),
                    'best': float(max(rets)),
                    'worst': float(min(rets)),
                    'mean_hit_rate': float(np.mean(hits)),
                    # 审计 H3: 有效样本数 (报告里看得见"结论基于几个样本")
                    'n_valid_picks': len(valid_picks),
                    'n_picks_total': len(picks),
                }
                if csi:
                    beat = sum(1 for r, c in zip(rets, csi) if r > c) / len(rets)
                    beat_benchmark[hd] = beat

        # 按体系分组 (同样用显式有效性标记)
        system_breakdown = {}
        for sys_name in set(p.system_name for p in picks):
            sys_picks = [p for p in picks if p.system_name == sys_name]
            if len(sys_picks) < 2:
                continue
            sys_stats = {}
            for hd in holding_days_list:
                rets = [p.forward_returns[hd] for p in sys_picks
                        if p.valid.get(hd)]
                if rets:
                    sys_stats[hd] = {
                        'n_picks': len(rets),
                        'median_return': float(np.median(rets)),
                        'hit_10pct_rate': sum(1 for r in rets if r >= 10) / len(rets),
                    }
            system_breakdown[sys_name] = sys_stats

        oos['pick_range'] = ([min(p.pick_date for p in picks),
                               max(p.pick_date for p in picks)]
                              if picks else [None, None])
        oos['n_dates'] = len(picks)

        return ValidationReport(
            n_dates=len(picks),
            holding_days_list=holding_days_list,
            picks=picks,
            aggregate=aggregate,
            system_breakdown=system_breakdown,
            beat_benchmark=beat_benchmark,
            # 审计 H5: 停牌建模口径 (持有期按交易日计 + 顺延记录)
            suspension=dict(self._stats()),
            # 审计 H4: 股票池口径 (point-in-time 参考日 + 幸存者偏差标记)
            universe_meta=dict(getattr(self, '_universe_meta', {}) or {}),
            # 审计 H3: 样本外判定 + 覆盖度 + 主口径持有期
            oos=dict(oos),
            coverage=coverage,
            primary_holding_days=primary_holding_days,
        )

    def _empty_report(self, holding_days_list, oos, primary_holding_days):
        """无样本外区间时的**空报告** (审计 H3: 不出验证结论, 但结构完整)。

        不返回 None: 调用方 (CLI / web) 需要知道"为什么没有结论", 而不是
        拿到一个 None 自己猜。
        """
        return ValidationReport(
            n_dates=0,
            holding_days_list=holding_days_list,
            picks=[],
            aggregate={},
            system_breakdown={},
            beat_benchmark={},
            suspension=dict(self._stats()),
            universe_meta=dict(getattr(self, '_universe_meta', {}) or {}),
            oos=dict(oos),
            coverage={},
            primary_holding_days=primary_holding_days,
        )

    def format_report(self, report: ValidationReport) -> str:
        """格式化验证报告 (审计 H3: 口径自证, 不写死区间/持有期)"""
        lines = []
        lines.append("=" * 80)
        lines.append("                  历史回测验证报告")
        lines.append("=" * 80)
        lines.append(f"  验证日期数: {report.n_dates}")
        lines.append(f"  持有期(天): {report.holding_days_list}")

        # 审计 H3: 评估范围从**实际数据**推导 (旧实现写死
        # "1996-01 ~ 2026-06 (30年A股数据)" → 与真实区间无关, 会说谎)
        oos = report.oos or {}
        pr = oos.get('pick_range') or [None, None]
        fit_s, fit_e = oos.get('param_fit_start'), oos.get('param_fit_end')
        if pr and pr[0]:
            lines.append(f"  验证区间: {pr[0]} ~ {pr[1]}")
        else:
            lines.append("  验证区间: — (无可用样本外区间)")
        if fit_s and fit_e:
            lines.append(f"  参数拟合区间: {fit_s} ~ {fit_e} (优化产物落盘)")
        lines.append("")

        # 审计 H3: 口径自证块 —— 结论的成立条件写在报告头上
        lines.append("【口径自证】")
        if oos.get('available'):
            lines.append(f"  · 样本外: ✅ 是 — {oos.get('reason', '')}")
        elif oos.get('in_sample'):
            lines.append(f"  · 样本外: ⚠️ 否（样本内）— {oos.get('reason', '')}")
        else:
            lines.append(f"  · 样本外: ❌ 无法判定 — {oos.get('reason', '')}")
        um = report.universe_meta or {}
        lines.append(f"  · 股票池: {um.get('mode') or um.get('source') or '-'}"
                     f" | 幸存者偏差: "
                     f"{'是' if um.get('survivorship_bias') else ('否' if um.get('survivorship_bias') is False else '未核查')}")
        sus = report.suspension or {}
        lines.append(f"  · 停牌建模: {'是' if sus.get('modeled') else '否'}"
                     f" | 因停牌顺延出场: {sus.get('deferred_picks', 0)} 次"
                     f" (累计 {sus.get('deferred_trading_days_total', 0)} 交易日)")
        if report.coverage:
            cov_txt = ", ".join(
                f"{hd}天 {c.get('n_valid_picks', 0)}/{c.get('n_picks', 0)}"
                for hd, c in report.coverage.items())
            lines.append(f"  · 有效样本覆盖: {cov_txt}")
        lines.append("")

        # 审计 H3: 无样本外区间 → **不出验证结论** (不给结论数字)
        if not report.aggregate:
            lines.append("【无验证结论】")
            lines.append(f"  {oos.get('reason') or '无可用样本外验证区间'}")
            lines.append("")
            lines.append("=" * 80)
            return "\n".join(lines)

        # 聚合统计
        lines.append("【按持有期统计】")
        lines.append(f"  {'持有天数':<10} {'中位收益':>10} {'平均收益':>10} "
                     f"{'正收益%':>10} {'>10%概率':>10} {'最大':>8} {'最小':>8} "
                     f"{'有效样本':>8}")
        lines.append("  " + "-" * 84)
        for hd in report.holding_days_list:
            if hd in report.aggregate:
                s = report.aggregate[hd]
                lines.append(f"  {hd:<10} {s['median_return']:>+9.1f}% "
                           f"{s['mean_return']:>+9.1f}% "
                           f"{s['positive_rate']*100:>9.1f}% "
                           f"{s['hit_10pct_rate']*100:>9.1f}% "
                           f"{s['best']:>+7.1f}% {s['worst']:>+7.1f}% "
                           f"{s.get('n_valid_picks', 0):>8}")
        lines.append("")

        # 跑赢基准
        lines.append("【vs 沪深300买入持有】")
        for hd in report.holding_days_list:
            if hd in report.beat_benchmark:
                pct = report.beat_benchmark[hd] * 100
                lines.append(f"  持有{hd}天: {pct:.1f}% 的推荐跑赢沪深300")
        lines.append("")

        # 按体系分组
        if report.system_breakdown:
            lines.append("【按使用体系分组】")
            for sys_name, stats in report.system_breakdown.items():
                lines.append(f"  {sys_name}:")
                for hd, s in stats.items():
                    lines.append(f"    {hd}天: 中位收益={s['median_return']:+.1f}%, "
                               f"达标率={s['hit_10pct_rate']:.1%} (n={s['n_picks']})")
            lines.append("")

        # 详细记录(前10条) —— 审计 H3: 用主口径持有期 (旧实现写死 180)
        phd = report.primary_holding_days or (
            sorted(report.holding_days_list)[len(report.holding_days_list) // 2])
        lines.append("【历史推荐明细(前10条)】")
        lines.append(f"  {'日期':<12} {'体制':<8} {'体系':<12} "
                     f"{str(phd)+'天收益':>12} {'达标率':>8} {'有效':>6}")
        lines.append("  " + "-" * 68)
        for p in report.picks[:10]:
            hd = phd if phd in p.forward_returns else list(p.forward_returns.keys())[0]
            lines.append(f"  {p.pick_date:<12} {p.regime_cn:<8} {p.system_name:<12} "
                       f"{p.forward_returns[hd]:>+11.1f}% "
                       f"{p.hit_target_10pct[hd]*100:>7.1f}% "
                       f"{p.n_evaluated.get(hd, 0):>4}/{p.n_picks}")
        if len(report.picks) > 10:
            lines.append(f"  ... 共 {len(report.picks)} 条")
        lines.append("")

        # 关键结论 —— 审计 H3: 用主口径持有期 (旧实现写死 180)
        lines.append("【关键结论】")
        if phd in report.aggregate:
            s = report.aggregate[phd]
            lines.append(f"  · {phd}天持有期中位收益 {s['median_return']:+.1f}%")
            lines.append(f"  · {phd}天持有期达标率(>10%) {s['hit_10pct_rate']:.1%}")
            target_met = s['hit_10pct_rate'] >= 0.80
            lines.append(f"  · 目标80%达标率: {'✓ 达成' if target_met else '✗ 未达成'}")
            lines.append(f"  · 结论基于 {s.get('n_valid_picks', 0)}/"
                         f"{s.get('n_picks_total', 0)} 个有效样本")

        if report.beat_benchmark and phd in report.beat_benchmark:
            beat = report.beat_benchmark[phd]
            lines.append(f"  · {phd}天跑赢沪深300比例: {beat*100:.1f}%")

        lines.append("")
        lines.append("=" * 80)
        return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description='历史回测验证')
    parser.add_argument('--systems', default='stock_data/optimization_result.json',
                       help='优化结果文件')
    parser.add_argument('--n-dates', type=int, default=30, help='历史日期数')
    parser.add_argument('--top', type=int, default=10, help='每次推荐Top N')
    parser.add_argument('--holding-days', default='90,180,270,365,540',
                       help='持有天数列表(逗号分隔)')
    parser.add_argument('--output', default='stock_data/historical_validation.json',
                       help='结果输出文件')
    # 审计 H3: 验证链口径开关
    parser.add_argument('--allow-in-sample', action='store_true',
                        help='显式允许退化为样本内验证 (默认: 无样本外区间即不出结论)')
    parser.add_argument('--universe-mode', dest='universe_mode',
                        default='per_pick', choices=['per_pick', 'single'],
                        help='股票池口径: per_pick=每个 pick 日期各自的点时池 (默认) / single=统一池')
    parser.add_argument('--primary-holding-days', dest='primary_holding_days',
                        type=int, default=None,
                        help='报告主口径持有期 (默认取 holding 列表中位项)')

    args = parser.parse_args()

    holding_days = [int(x) for x in args.holding_days.split(',')]

    validator = HistoricalBacktestValidator(
        optimization_result_file=args.systems,
    )

    try:
        report = validator.validate(
            n_dates=args.n_dates,
            top_n=args.top,
            holding_days_list=holding_days,
            universe_mode=args.universe_mode,
            allow_in_sample=args.allow_in_sample,
            primary_holding_days=args.primary_holding_days,
        )
    except Exception as e:
        # 审计 H3: CLI 不裸崩 —— 打印错误与完整 traceback 后退出 (诊断信息
        # 不丢, 但不吐一个无上下文的栈到用户脸上)
        print(f"[ERROR] 历史验证失败: {str(e)[:200]}", file=sys.stderr)
        traceback.print_exc()
        raise SystemExit(1)

    if report is None:
        return

    # 打印报告
    text = validator.format_report(report)
    print(text)

    # 保存JSON结果
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    result_data = {
        'timestamp': datetime.now().isoformat(),
        'n_dates': report.n_dates,
        'holding_days_list': report.holding_days_list,
        'primary_holding_days': report.primary_holding_days,
        'aggregate': report.aggregate,
        'beat_benchmark': report.beat_benchmark,
        # 审计 H5: 停牌建模口径 (持有期按交易日计 + 顺延记录)
        'suspension': report.suspension,
        # 审计 H4: 股票池口径 (point-in-time 参考日 + 幸存者偏差标记)
        'universe_meta': report.universe_meta,
        # 审计 H3: 样本外判定 + 覆盖度 (结论的成立条件)
        'oos': report.oos,
        'coverage': report.coverage,
        'system_breakdown': report.system_breakdown,
        'picks': [
            {
                'pick_date': p.pick_date,
                'regime': p.regime,
                'regime_cn': p.regime_cn,
                'system_name': p.system_name,
                'forward_returns': p.forward_returns,
                'csi300_return': p.csi300_return,
                'hit_target_10pct': p.hit_target_10pct,
                # 审计 H3: 覆盖度记账 (每个 pick 每个持有期的有效/缺失数)
                'n_picks': p.n_picks,
                'n_evaluated': p.n_evaluated,
                'n_missing': p.n_missing,
                'valid': p.valid,
            }
            for p in report.picks
        ],
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] 结果已保存: {output_path}")


if __name__ == "__main__":
    main()