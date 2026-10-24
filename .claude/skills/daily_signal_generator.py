# -*- coding: utf-8 -*-
"""
每日信号生成器 - Daily Signal Generator (体制自适应)

实时判断大盘态势 → 选择对应的指标体系 → 用该体系的参数计算指标 →
生成买卖信号 → 评分排名 → 输出推荐。

内层信号打分已并入 signal_generator (项 21 合并): 本模块只保留
"体制检测 + 参数体系 + 批量日报 + manifest" 外壳, 打分口径与
signal_generator 完全一致 (单一真相源)。

用法:
    python daily_signal_generator.py --universe 50 --top 10
    python daily_signal_generator.py --symbols 000001 600519 --output report.txt
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timedelta
import json
import random
import subprocess
import sys

from historical_data_manager import HistoricalDataManager
from vectorized_backtest import VectorizedBacktester
from parameter_space import ParameterSpace
from core.indicators import rsi as _core_rsi, atr as _core_atr
from signal_generator import SignalGenerator, SIGNAL_LABELS, describe_signals
import trade_constraints


# ==================== 数据结构 ====================

@dataclass
class StockSignal:
    """单只股票的信号"""
    symbol: str
    name: str
    price: float
    change_pct: float          # 日涨跌幅
    regime: str                # 当前大盘体制
    system_name: str           # 使用的指标体系
    buy_score: float           # 买入得分 (S1 分值: 投票制累加或 0-100 加权评分)
    sell_score: float          # 卖出得分 (S1 分值, 同上)
    signal: str                # "BUY" / "HOLD" / "SELL"
    signal_strength: float     # 信号强度 (-1 ~ 1)
    reasons: list              # 信号原因 (S1 标签表)
    # 技术指标
    ma_trend: str              # "UP" / "DOWN" / "FLAT"
    macd_hist: float
    rsi: float
    kdj_k: float
    bb_position: float         # 在布林带中的位置 (0=下轨, 1=上轨)
    volume_ratio: float        # 量比
    # 风险指标
    atr_pct: float             # ATR占价格百分比
    distance_to_support: float # 距支撑位百分比
    distance_to_resistance: float # 距压力位百分比
    # 交易约束前置检查 (审计 C-P1-12): False = 停牌/涨跌停/流动性阻断
    executable: bool = True
    blocked_reasons: list = field(default_factory=list)
    skipped_checks: list = field(default_factory=list)

    def to_signal(self, signal_date=None, execute_at=None,
                  target_weight=None):
        """→ 统一契约 Signal (审计 C #9 / 项 21 #9a).

        Args:
            signal_date: 信号日期; None = 由调用方给 (日报用报告日期)
            execute_at: 可执行时点; None = 由执行层 (t+1 开盘) 决定
            target_weight: 目标仓位比例; None = 由下游风控决定

        Returns:
            core.signal.Signal
        """
        return to_signal(self, signal_date=signal_date,
                         execute_at=execute_at, target_weight=target_weight)


def to_signal(stock_signal, signal_date=None, execute_at=None,
              target_weight=None):
    """StockSignal (或同形对象) → 统一契约 Signal (审计 C #9).

    鸭子类型读取 (缺字段用默认值), 因此测试桩/历史结构也能安全转换。
    """
    from core.signal import (ACTION_BUY, ACTION_HOLD, ACTION_SELL,
                             SCALE_VOTE_NORM, Signal, normalize_date)

    raw_action = getattr(stock_signal, 'signal', 'HOLD')
    action = (ACTION_BUY if raw_action == 'BUY'
              else ACTION_SELL if raw_action == 'SELL' else ACTION_HOLD)

    def _f(name, default=0.0):
        value = getattr(stock_signal, name, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    return Signal(
        symbol=getattr(stock_signal, 'symbol', ''),
        signal_date=normalize_date(signal_date),
        action=action,
        strength=_f('signal_strength'),
        scale=SCALE_VOTE_NORM,
        reasons=list(getattr(stock_signal, 'reasons', []) or []),
        target_weight=target_weight,
        execute_at=execute_at,
        executable=bool(getattr(stock_signal, 'executable', True)),
        blocked_reasons=list(getattr(stock_signal, 'blocked_reasons', []) or []),
        skipped_checks=list(getattr(stock_signal, 'skipped_checks', []) or []),
        source='daily_signal_generator',
        extra={
            'name': getattr(stock_signal, 'name', ''),
            'price': _f('price'),
            'change_pct': _f('change_pct'),
            'regime': getattr(stock_signal, 'regime', ''),
            'system_name': getattr(stock_signal, 'system_name', ''),
            'buy_score': _f('buy_score'),
            'sell_score': _f('sell_score'),
            'rsi': _f('rsi'),
            'kdj_k': _f('kdj_k'),
            'bb_position': _f('bb_position'),
            'volume_ratio': _f('volume_ratio'),
            'atr_pct': _f('atr_pct'),
        },
    )


@dataclass
class DailyReport:
    """每日推荐报告"""
    date: str
    current_regime: str
    regime_cn: str
    system_used: str
    system_description: str
    total_analyzed: int
    signals: list              # list[StockSignal]
    regime_switch_alert: str   # 体制切换预警
    timestamp: str
    # 统一契约信号 (审计 C #9): 与 signals 同源, 供下游/落盘直接消费
    contract_signals: list = field(default_factory=list)


# ==================== 指标计算 ====================

def compute_indicators(data: pd.DataFrame, params: dict) -> pd.DataFrame:
    """
    用指定参数计算技术指标

    Parameters:
    -----------
    data : pd.DataFrame
        股票历史数据
    params : dict
        参数字典 (来自优化结果)

    Returns:
    --------
    pd.DataFrame : 添加了技术指标的DataFrame
    """
    df = data.copy()
    close = df['收盘'].astype(float)
    high = df['最高'].astype(float)
    low = df['最低'].astype(float)
    volume = df['成交量'].astype(float)

    # 移动平均线
    ma_fast = int(params.get('ma_fast', 5))
    ma_slow = int(params.get('ma_slow', 20))
    ma_mid = int(params.get('ma_mid', 10))

    df['MA_Fast'] = close.rolling(ma_fast).mean()
    df['MA_Mid'] = close.rolling(ma_mid).mean()
    df['MA_Slow'] = close.rolling(ma_slow).mean()

    # MACD
    macd_fast = int(params.get('macd_fast', 12))
    macd_slow = int(params.get('macd_slow', 26))
    macd_signal_p = int(params.get('macd_signal', 9))

    ema_fast = close.ewm(span=macd_fast, adjust=False).mean()
    ema_slow = close.ewm(span=macd_slow, adjust=False).mean()
    df['MACD'] = ema_fast - ema_slow
    df['MACD_Signal'] = df['MACD'].ewm(span=macd_signal_p, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']

    # RSI（core 权威口径，消灭 replace(NaN) 分歧）
    rsi_period = int(params.get('rsi_period', 14))
    df['RSI'] = _core_rsi(close, rsi_period)

    # KDJ
    kdj_n = int(params.get('kdj_n', 9))
    low_n = low.rolling(kdj_n).min()
    high_n = high.rolling(kdj_n).max()
    rsv = (close - low_n) / (high_n - low_n).replace(0, np.nan) * 100
    df['K'] = rsv.ewm(span=3, adjust=False).mean()
    df['D'] = df['K'].ewm(span=3, adjust=False).mean()

    # 布林带
    bb_period = int(params.get('bb_period', 20))
    bb_std_mult = float(params.get('bb_std', 2.0))
    df['BB_Mid'] = close.rolling(bb_period).mean()
    bb_std = close.rolling(bb_period).std()
    df['BB_Upper'] = df['BB_Mid'] + bb_std_mult * bb_std
    df['BB_Lower'] = df['BB_Mid'] - bb_std_mult * bb_std

    # ATR (core Wilder 单一真相源, 旧: SMA)
    atr_period = int(params.get('atr_period', 14))
    df['ATR'] = _core_atr(high, low, close, atr_period)

    # 成交量均线
    df['Vol_MA5'] = volume.rolling(5).mean()
    df['Vol_MA20'] = volume.rolling(20).mean()

    return df


def generate_signal(data: pd.DataFrame, params: dict) -> dict:
    """
    对单只股票生成买卖信号 (内层打分 = signal_generator, 单一真相源)

    指标仍按 params 计算 (周期可配: ma_fast/ma_slow/kdj_n/bb_period/...),
    但打分口径完全走 signal_generator:
      - 布林统一为 S1 的"突破跟随" (原 S2 的"触下轨即买"均值回归口径已废)
      - RSI 统一为 S1 的"进入区间"事件语义 (原 S2 为"处于区间"状态语义)
      - 新增 S1 的突破分项 (20 日新高/新低) 与量价配合档

    Returns:
    --------
    dict : {buy_score, sell_score, signal, strength, reasons, indicators}
        buy_score/sell_score = S1 的分值 (投票制累加或 0-100 加权评分)
        strength = (buy_score - sell_score) / (buy_score + sell_score) ∈ [-1, 1]
    """
    if len(data) < 60:
        return None

    df = compute_indicators(data, params)
    latest = df.iloc[-1]

    generator = SignalGenerator(
        buy_threshold=float(params.get('buy_threshold', 2.0)),
        sell_threshold=float(params.get('sell_threshold', 2.0)),
        use_weighted_scoring=bool(params.get('use_weighted_scoring', False)),
        scoring_params=params,
        rsi_oversold=float(params.get('rsi_oversold', 30.0)),
        rsi_overbought=float(params.get('rsi_overbought', 70.0)),
        # S1 契约列名 → 本模块 params 驱动的均线列 (周期不写死在列名里)
        column_map={'MA5': 'MA_Fast', 'MA10': 'MA_Mid', 'MA20': 'MA_Slow'},
    )
    sig_df = generator.generate_signals(df)
    last = sig_df.iloc[-1]

    buy_score = float(last['signal_buy_score'])
    sell_score = float(last['signal_sell_score'])
    buy_signal = int(last['signal_buy'])
    sell_signal = int(last['signal_sell'])

    # 综合判断 (S1 已做买卖互斥仲裁, 此处只映射三态)
    if buy_signal:
        signal = "BUY"
    elif sell_signal:
        signal = "SELL"
    else:
        signal = "HOLD"

    strength = (buy_score - sell_score) / max(buy_score + sell_score, 1)

    # 信号原因 (按档位值翻译, 与 S1 报告层同一标签表)
    values = {col: last[col] for col in SIGNAL_LABELS if col in sig_df.columns}
    if signal == "BUY":
        reasons = describe_signals(values, side='buy')
    elif signal == "SELL":
        reasons = describe_signals(values, side='sell')
    else:
        reasons = []

    # 布林带位置
    bb_upper = latest['BB_Upper']
    bb_lower = latest['BB_Lower']
    bb_range = bb_upper - bb_lower
    bb_pos = (latest['收盘'] - bb_lower) / bb_range if bb_range > 0 else 0.5

    # MA趋势
    ma_fast = latest['MA_Fast']
    ma_slow = latest['MA_Slow']
    if ma_fast > ma_slow:
        ma_trend = "UP"
    elif ma_fast < ma_slow:
        ma_trend = "DOWN"
    else:
        ma_trend = "FLAT"

    vol_ma5 = latest['Vol_MA5']
    close = latest['收盘']

    return {
        'buy_score': buy_score,
        'sell_score': sell_score,
        'signal': signal,
        'strength': strength,
        'reasons': reasons,
        'indicators': {
            'ma_trend': ma_trend,
            'macd_hist': latest['MACD_Hist'],
            'rsi': latest['RSI'],
            'kdj_k': latest['K'],
            'bb_position': bb_pos,
            'volume_ratio': latest['成交量'] / vol_ma5 if vol_ma5 > 0 else 1.0,
            'atr_pct': latest['ATR'] / close * 100 if close > 0 else 0,
        }
    }


# ==================== 每日信号生成器 ====================

class DailySignalGenerator:
    """
    每日信号生成器

    流程:
    1. 检测当前大盘态势
    2. 选择对应的指标体系
    3. 用该体系参数对每只股票计算信号
    4. 评分排名输出推荐
    """

    def __init__(self, data_dir="./stock_data",
                 optimization_result_file=None):
        """
        Parameters:
        -----------
        data_dir : str
            数据目录
        optimization_result_file : str or None
            优化结果JSON文件路径
        """
        self.data_manager = HistoricalDataManager(data_dir)
        self.data_dir = data_dir
        self.systems = {}       # {regime: {name, params, ...}}
        self.default_params = ParameterSpace.get_defaults()
        self.optimization_result_file = None
        self._index_labels = None
        self._current_regime = None

        if optimization_result_file and Path(optimization_result_file).exists():
            self.optimization_result_file = optimization_result_file
            self.load_systems(optimization_result_file)

    def load_systems(self, filepath):
        """加载优化后的指标体系"""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 评分模式 (E-P1 #19): manifest 顶层 use_weighted_scoring 决定日报
        # 用加权评分还是投票制; 缺键 → False (旧优化文件保持投票制口径)
        use_weighted = bool(data.get('use_weighted_scoring', False))

        for sys_data in data.get('systems', []):
            params = sys_data.get('params') or {}
            params.setdefault('use_weighted_scoring', use_weighted)
            sys_data['params'] = params
            regimes = sys_data.get('applicable_regimes', [])
            for regime in regimes:
                if regime not in self.systems:
                    self.systems[regime] = sys_data
                else:
                    # 保留置信度更高的
                    if sys_data.get('confidence', 0) > self.systems[regime].get('confidence', 0):
                        self.systems[regime] = sys_data

        print(f"[OK] 加载 {len(data.get('systems', []))} 套指标体系")

    def load_regime_labels(self, filepath):
        """加载大盘体制标签(用于回测/验证)"""
        df = pd.read_csv(filepath, encoding='utf-8-sig')
        df['日期'] = pd.to_datetime(df['日期'])
        self._index_labels = df
        print(f"[OK] 加载体制标签: {len(df)} 条")

    def detect_current_regime(self, index_data=None) -> str:
        """
        检测当前大盘态势

        Parameters:
        -----------
        index_data : pd.DataFrame or None
            指数数据，None则从缓存加载

        Returns:
        --------
        str : 当前体制 "BULL" / "BEAR" / "SIDEWAYS" / "CRASH" / "RECOVERY"
        """
        if index_data is None:
            # 尝试从缓存加载沪深300
            index_data = self.data_manager.load('000300')
            if len(index_data) == 0:
                # 尝试加载上证指数
                index_data = self.data_manager.load('000001')

        if len(index_data) < 120:
            print("[WARN] 指数数据不足，默认SIDEWAYS")
            self._current_regime = 'SIDEWAYS'
            return 'SIDEWAYS'

        close = index_data['收盘'].astype(float)
        ma60 = close.rolling(60).mean()
        ma120 = close.rolling(120).mean()
        ret_20d = close.pct_change(20) * 100
        ret_5d = close.pct_change(5) * 100
        ret_month = close.pct_change(20) * 100

        latest_ma60 = ma60.iloc[-1]
        latest_ma120 = ma120.iloc[-1]
        latest_ret20 = ret_20d.iloc[-1]
        latest_ret5 = ret_5d.iloc[-1]
        latest_ret_month = ret_month.iloc[-1]

        # 分类逻辑 (与 MarketRegimeClassifier 一致)
        if latest_ret_month < -10 or latest_ret5 < -8:
            regime = 'CRASH'
        elif latest_ma60 > latest_ma120 and latest_ret20 > 5:
            regime = 'BULL'
        elif latest_ma60 < latest_ma120 and latest_ret20 < -5:
            regime = 'BEAR'
        elif latest_ma60 > latest_ma120 and latest_ret20 > 0:
            regime = 'BULL'
        elif latest_ma60 < latest_ma120 and latest_ret20 < 0:
            regime = 'BEAR'
        else:
            regime = 'SIDEWAYS'

        self._current_regime = regime
        return regime

    def get_params_for_regime(self, regime: str) -> dict:
        """获取指定体制的参数"""
        if regime in self.systems:
            return self.systems[regime]['params']
        # 尝试通用型
        if 'GLOBAL' in self.systems:
            return self.systems['GLOBAL']['params']
        if 'ROBUST' in self.systems:
            return self.systems['ROBUST']['params']
        return self.default_params

    def get_system_name_for_regime(self, regime: str) -> str:
        """获取指定体制的体系名称"""
        if regime in self.systems:
            return self.systems[regime].get('name', '未命名')
        return '默认参数'

    def generate_for_stock(self, symbol: str, regime: str = None,
                           params: dict = None) -> StockSignal:
        """
        为单只股票生成信号

        Parameters:
        -----------
        symbol : str
            股票代码
        regime : str or None
            大盘体制，None则自动检测
        params : dict or None
            参数，None则使用对应体制的参数

        Returns:
        --------
        StockSignal
        """
        if regime is None:
            regime = self._current_regime or self.detect_current_regime()

        if params is None:
            params = self.get_params_for_regime(regime)

        # 加载数据
        data = self.data_manager.load(symbol)
        if len(data) < 60:
            return None

        # 生成信号
        sig_result = generate_signal(data, params)
        if sig_result is None:
            return None

        latest = data.iloc[-1]
        prev = data.iloc[-2] if len(data) > 1 else latest

        # 计算支撑压力位
        close = latest['收盘']
        recent_low = data['最低'].tail(20).min()
        recent_high = data['最高'].tail(20).max()
        support_dist = (close - recent_low) / close * 100 if close > 0 else 0
        resist_dist = (recent_high - close) / close * 100 if close > 0 else 0

        # 获取股票名称
        name = self.data_manager.get_stock_name(symbol)

        change_pct = (close / prev['收盘'] - 1) * 100 if prev['收盘'] > 0 else 0

        # 审计 C-P1-12: 前置可执行性检查 (方向按信号取, HOLD 双向)
        side = {'BUY': 'buy', 'SELL': 'sell'}.get(sig_result['signal'], 'both')
        constraint = trade_constraints.check_last_bar(
            data, code=symbol, side=side)
        # 审计 C #9 收口: 约束字段统一装配 (不再各模块手拼)
        cfields = constraint.as_signal_fields()

        return StockSignal(
            symbol=symbol,
            name=name,
            price=close,
            change_pct=change_pct,
            regime=regime,
            system_name=self.get_system_name_for_regime(regime),
            buy_score=sig_result['buy_score'],
            sell_score=sig_result['sell_score'],
            signal=sig_result['signal'],
            signal_strength=sig_result['strength'],
            reasons=sig_result['reasons'],
            ma_trend=sig_result['indicators']['ma_trend'],
            macd_hist=sig_result['indicators']['macd_hist'],
            rsi=sig_result['indicators']['rsi'],
            kdj_k=sig_result['indicators']['kdj_k'],
            bb_position=sig_result['indicators']['bb_position'],
            volume_ratio=sig_result['indicators']['volume_ratio'],
            atr_pct=sig_result['indicators']['atr_pct'],
            distance_to_support=support_dist,
            distance_to_resistance=resist_dist,
            executable=cfields['executable'],
            blocked_reasons=cfields['blocked_reasons'],
            skipped_checks=cfields['skipped_checks'],
        )

    def generate_daily_report(self, symbols: list = None,
                              n_stocks: int = 50,
                              seed: int = None) -> DailyReport:
        """
        生成每日推荐报告

        Parameters:
        -----------
        symbols : list or None
            股票列表，None则从股票池随机抽样
        n_stocks : int
            分析股票数 (推荐展示条数由 format_report 控制)
        seed : int or None
            随机抽样种子 (审计 C-P1-15: 传入即可复现同一股票池)

        Returns:
        --------
        DailyReport
        """
        # 检测大盘态势
        regime = self.detect_current_regime()
        regime_cn = {
            'BULL': '牛市', 'BEAR': '熊市', 'SIDEWAYS': '横盘震荡',
            'CRASH': '暴跌', 'RECOVERY': '反弹'
        }.get(regime, regime)

        print(f"[INFO] 当前大盘态势: {regime_cn} ({regime})")
        print(f"[INFO] 使用指标体系: {self.get_system_name_for_regime(regime)}")

        # 获取股票池 (审计 C-P1-15: 旧 random.sample 无种子 → 不可复现)
        if symbols is None:
            symbols = self.data_manager.get_universe(min_rows=2000)
            if len(symbols) > n_stocks:
                symbols = random.Random(seed).sample(symbols, n_stocks)

        # 生成信号
        params = self.get_params_for_regime(regime)
        signals = []

        for sym in symbols:
            try:
                sig = self.generate_for_stock(sym, regime, params)
                if sig is not None:
                    signals.append(sig)
            except Exception:
                continue

        # 按信号强度排序
        signals.sort(key=lambda s: abs(s.signal_strength), reverse=True)

        # 审计 C-P1-12: 不可执行信号不进推荐列表 (total_analyzed 仍记分析数)
        analyzed_count = len(signals)
        executable_signals = [
            s for s in signals if getattr(s, 'executable', True)]
        blocked_n = analyzed_count - len(executable_signals)
        if blocked_n:
            print(f"[INFO] 交易约束过滤 (C-P1-12): {blocked_n} 只因"
                  f"停牌/涨跌停/流动性被剔除")
        signals = executable_signals

        # 体制切换预警
        alert = self._check_regime_switch()

        report_date = datetime.now().strftime('%Y-%m-%d')
        report = DailyReport(
            date=report_date,
            current_regime=regime,
            regime_cn=regime_cn,
            system_used=self.get_system_name_for_regime(regime),
            system_description=self.systems.get(regime, {}).get('description', ''),
            total_analyzed=analyzed_count,
            signals=signals,
            regime_switch_alert=alert,
            timestamp=datetime.now().isoformat(),
            # 统一契约信号 (审计 C #9): 与 signals 同源派生, 供下游/落盘消费
            contract_signals=[to_signal(s, signal_date=report_date)
                              for s in signals],
        )

        return report

    def save_manifest(self, filepath: str, report: DailyReport = None,
                      seed: int = None) -> bool:
        """
        落盘运行清单 (审计 C-P1-15): 时间戳 / git sha / 种子 / 数据目录 /
        优化结果文件 / 体制 / 该体制实际使用的参数 — 让任一推荐结果可事后复现

        Args:
            filepath: manifest JSON 输出路径
            report: generate_daily_report 的返回值 (可选, 有则记入体制与样本数)
            seed: 本次抽样种子

        Returns:
            是否成功
        """
        try:
            root = Path(__file__).resolve().parents[2]
            git_sha = subprocess.check_output(
                ['git', 'rev-parse', 'HEAD'], cwd=str(root),
                stderr=subprocess.DEVNULL).decode().strip()
        except Exception:
            git_sha = 'unknown'

        regime = report.current_regime if report is not None else None
        try:
            params = self.get_params_for_regime(regime) if regime else None
        except Exception:
            params = None

        manifest = {
            'timestamp': datetime.now().isoformat(),
            'git_sha': git_sha,
            'seed': seed,
            'data_dir': str(self.data_dir),
            'optimization_result_file': self.optimization_result_file,
            'regime': regime,
            'regime_cn': report.regime_cn if report is not None else None,
            'system_used': report.system_used if report is not None else None,
            'n_analyzed': report.total_analyzed if report is not None else None,
            'regime_switch_alert': (report.regime_switch_alert
                                    if report is not None else None),
            'params': params,
        }

        path = Path(filepath)
        if path.parent and not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2, default=str)
        return True

    def _check_regime_switch(self) -> str:
        """检查是否有体制切换预警"""
        if self._index_labels is None:
            return ""

        labels = self._index_labels
        if len(labels) < 5:
            return ""

        recent = labels['regime'].tail(5).tolist()
        current = recent[-1]

        # 如果最近5天有2次以上不同体制，可能在切换
        unique_regimes = set(recent)
        if len(unique_regimes) > 1:
            from collections import Counter
            counts = Counter(recent)
            if counts[current] <= 3:
                return f"近期体制不稳定，可能切换 (最近5天: {dict(counts)})"

        return ""

    def format_report(self, report: DailyReport,
                      show_all: bool = False, top: int = 10) -> str:
        """格式化每日报告"""
        lines = []
        lines.append("=" * 70)
        lines.append(f"            每日信号推荐报告 ({report.date})")
        lines.append("=" * 70)
        lines.append("")

        # 大盘态势
        lines.append(f"  当前大盘态势: {report.regime_cn} ({report.current_regime})")
        lines.append(f"  使用指标体系: {report.system_used}")
        if report.system_description:
            lines.append(f"  体系说明: {report.system_description}")
        lines.append(f"  分析股票数: {report.total_analyzed}")

        if report.regime_switch_alert:
            lines.append(f"  ⚠ 预警: {report.regime_switch_alert}")
        lines.append("")

        # 买入推荐
        buy_signals = [s for s in report.signals if s.signal == "BUY"]
        if buy_signals:
            lines.append(f"【买入推荐 TOP {min(top, len(buy_signals))}】")
            lines.append(f"  {'代码':<8} {'名称':<8} {'价格':>8} {'涨跌%':>7} "
                        f"{'买分':>5} {'信号强度':>8} {'原因'}")
            lines.append("  " + "-" * 65)
            for s in buy_signals[:top]:
                reasons_str = ", ".join(s.reasons[:3])
                lines.append(
                    f"  {s.symbol:<8} {s.name:<8} {s.price:>8.2f} "
                    f"{s.change_pct:>+7.2f} {s.buy_score:>5.1f} "
                    f"{s.signal_strength:>+8.2f} {reasons_str}"
                )
            lines.append("")
        else:
            lines.append("  无买入信号")
            lines.append("")

        # 卖出警告
        sell_signals = [s for s in report.signals if s.signal == "SELL"]
        if sell_signals:
            lines.append(f"【卖出警告】")
            lines.append(f"  {'代码':<8} {'名称':<8} {'价格':>8} {'涨跌%':>7} "
                        f"{'卖分':>5} {'原因'}")
            lines.append("  " + "-" * 55)
            for s in sell_signals[:top]:
                reasons_str = ", ".join(s.reasons[:3])
                lines.append(
                    f"  {s.symbol:<8} {s.name:<8} {s.price:>8.2f} "
                    f"{s.change_pct:>+7.2f} {s.sell_score:>5.1f} {reasons_str}"
                )
            lines.append("")

        # 详细指标 (可选)
        if show_all:
            lines.append("【全部股票信号详情】")
            lines.append(f"  {'代码':<8} {'信号':<5} {'买分':>5} {'卖分':>5} "
                        f"{'RSI':>5} {'K':>5} {'BB位置':>6} {'量比':>5} {'ATR%':>5}")
            lines.append("  " + "-" * 60)
            for s in report.signals:
                lines.append(
                    f"  {s.symbol:<8} {s.signal:<5} {s.buy_score:>5.1f} "
                    f"{s.sell_score:>5.1f} {s.rsi:>5.1f} {s.kdj_k:>5.1f} "
                    f"{s.bb_position:>6.2f} {s.volume_ratio:>5.2f} "
                    f"{s.atr_pct:>5.2f}"
                )
            lines.append("")

        lines.append("=" * 70)
        return "\n".join(lines)


# ==================== CLI ====================

def main():
    import argparse

    parser = argparse.ArgumentParser(description='每日信号生成器')
    parser.add_argument('--systems-file',
                       default='stock_data/optimization_result.json',
                       help='优化结果文件')
    parser.add_argument('--regime-labels',
                       default='stock_data/regime_labels.csv',
                       help='体制标签文件')
    parser.add_argument('--symbols', nargs='+', help='指定股票代码')
    parser.add_argument('--n-stocks', type=int, default=50,
                       help='分析股票数')
    parser.add_argument('--top', type=int, default=10,
                       help='推荐TOP N')
    parser.add_argument('--seed', type=int, default=None,
                       help='随机抽样种子 (可复现股票池, 审计 C-P1-15)')
    parser.add_argument('--manifest',
                       help='运行清单JSON输出路径 (时间戳/git sha/种子/参数)')
    parser.add_argument('--output', help='输出文件路径')
    parser.add_argument('--show-all', action='store_true',
                       help='显示全部股票详情')

    args = parser.parse_args()

    # 初始化
    generator = DailySignalGenerator(
        optimization_result_file=args.systems_file
    )

    if Path(args.regime_labels).exists():
        generator.load_regime_labels(args.regime_labels)

    # 生成报告
    report = generator.generate_daily_report(
        symbols=args.symbols,
        n_stocks=args.n_stocks,
        seed=args.seed,
    )

    # 运行清单 (审计 C-P1-15)
    if args.manifest:
        generator.save_manifest(args.manifest, report=report, seed=args.seed)
        print(f"[INFO] 运行清单已写入: {args.manifest}")

    # 格式化输出
    text = generator.format_report(report, show_all=args.show_all,
                                   top=args.top)
    print(text)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f"\n[OK] 报告已保存: {args.output}")


if __name__ == "__main__":
    main()
