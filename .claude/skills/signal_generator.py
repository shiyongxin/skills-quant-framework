# -*- coding: utf-8 -*-
"""
信号生成器模块
根据技术指标生成买卖信号

单一真相源 (项 21 合并): 本模块是全项目唯一的信号打分实现;
daily_signal_generator (S2) 的内层已并入此处, S2 只保留体制检测/批量日报外壳。
"""
import sys
sys.path.append('.')
import pandas as pd
import numpy as np

import trade_constraints
from core.indicators import sma as _core_sma, volume_ma as _core_volume_ma


# ==================== 分项信号标签 (报告层与日报共用) ====================

# 分项信号列 → 值 → 中文标签 (值决定档位语义, 报告措辞不得按符号硬编码)
SIGNAL_LABELS = {
    'signal_ma_cross': {
        1.0: 'MA金叉', 0.5: '均线多头排列',
        -0.5: '均线空头排列', -1.0: 'MA死叉',
    },
    'signal_macd': {
        1.0: 'MACD金叉', 0.3: 'MACD零轴上方',
        -0.3: 'MACD零轴下方', -1.0: 'MACD死叉',
    },
    'signal_kdj': {
        1.0: 'KDJ金叉', 0.5: 'KDJ超卖',
        -0.5: 'KDJ超买', -1.0: 'KDJ死叉',
    },
    'signal_rsi': {
        1.0: 'RSI进入超卖区', 0.2: 'RSI强势区',
        -0.2: 'RSI弱势区', -1.0: 'RSI进入超买区',
    },
    'signal_bb': {
        1.0: '从布林下轨回归', 0.5: '突破布林上轨',
        -0.5: '触及布林下轨', -1.0: '从布林上轨回落',
    },
    'signal_volume': {
        0.5: '量增价涨', 0.3: '放量',
        -0.2: '缩量', -0.5: '量增价跌',
    },
    'signal_breakout': {
        1.0: '突破20日新高', -1.0: '跌破20日低点',
    },
}

# 报告层展示名 (列名 → 中文)
SIGNAL_DISPLAY_NAMES = {
    'signal_ma_cross': '均线',
    'signal_macd': 'MACD',
    'signal_kdj': 'KDJ',
    'signal_rsi': 'RSI',
    'signal_bb': '布林带',
    'signal_volume': '成交量',
    'signal_breakout': '突破',
}


def describe_signals(values, side='all'):
    """把分项信号值翻译成中文标签 (值 → 档位语义).

    Args:
        values: {列名: 值} 或 pd.Series
        side: 'buy' 只取正值 / 'sell' 只取负值 / 'all' 全取

    Returns:
        list[str]: 标签列表 (按 SIGNAL_LABELS 声明顺序)
    """
    if isinstance(values, pd.Series):
        values = values.to_dict()
    out = []
    for col, labels in SIGNAL_LABELS.items():
        if col not in values:
            continue
        val = values[col]
        if val is None:
            continue
        try:
            val = float(val)
        except (TypeError, ValueError):
            continue
        if np.isnan(val) or val == 0:
            continue
        if side == 'buy' and val < 0:
            continue
        if side == 'sell' and val > 0:
            continue
        label = labels.get(round(val, 2))
        if label:
            out.append(label)
    return out


class SignalGenerator:
    """信号生成器类 (双模式: 投票制默认 / 4 因子加权评分 — E-P1 #19 闭环)"""

    def __init__(self, buy_threshold=2.0, sell_threshold=2.0,
                 use_weighted_scoring=False, scoring_params=None,
                 rsi_oversold=30.0, rsi_overbought=70.0, column_map=None):
        """
        初始化

        Parameters:
        -----------
        buy_threshold : float
            买入信号阈值，信号得分>=此值触发买入 (默认2.0, 投票制)
        sell_threshold : float
            卖出信号阈值，信号得分>=此值触发卖出 (默认2.0, 投票制)
        use_weighted_scoring : bool
            True 时综合信号改用 4 因子 0-100 加权评分
            (score_buy/sell_threshold 触发, 参数来自 scoring_params);
            分项信号列照常产出, 仅作报告明细 (默认 False = 生产投票制零变化)
        scoring_params : dict or None
            评分/阈值参数 (w_trend/w_momentum/w_risk/w_performance/
            score_buy_threshold/score_sell_threshold), 与优化器 best_params
            JSON 下发的 params 同一契约; None → 出厂默认
        rsi_oversold / rsi_overbought : float
            RSI 超卖/超买阈值 (默认 30/70); 供参数化周期体系 (S2 日报) 复用
        column_map : dict or None
            指标列名映射 {本模块契约列名: 实际列名}; None → 恒等。
            例: {'MA5': 'MA_Fast', 'MA20': 'MA_Slow'} 用于对接
            params 驱动周期 (S2) 的列名, 避免"列名写死周期"的假口径
        """
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.use_weighted_scoring = use_weighted_scoring
        self.scoring_params = dict(scoring_params or {})
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.column_map = dict(column_map or {})

    def _col(self, df, name):
        """按 column_map 取指标列; 列不存在返回 None (调用方按缺列降级)"""
        real = self.column_map.get(name, name)
        if real in df.columns:
            return df[real]
        return None

    def generate_signals(self, data):
        """
        生成交易信号

        Args:
            data: 包含技术指标的DataFrame

        Returns:
            DataFrame: 添加了信号列的DataFrame
        """
        df = data.copy()

        # 生成各类信号 (投票制分项明细, 两种模式下均产出供报告展示)
        df['signal_ma_cross'] = self._ma_cross_signal(df)
        df['signal_macd'] = self._macd_signal(df)
        df['signal_kdj'] = self._kdj_signal(df)
        df['signal_rsi'] = self._rsi_signal(df)
        df['signal_bb'] = self._bollinger_signal(df)
        df['signal_volume'] = self._volume_signal(df)
        df['signal_breakout'] = self._breakout_signal(df)

        # 综合信号 (双模式)
        if self.use_weighted_scoring:
            buy_score, sell_score = self._weighted_scores(df)
            df['signal_buy_score'] = buy_score
            df['signal_sell_score'] = sell_score
            sb = float(self.scoring_params.get('score_buy_threshold', 60.0))
            ss = float(self.scoring_params.get('score_sell_threshold', 35.0))
            # 买卖互斥 (审计项21 合并): 同一根 bar 不得同时给出买/卖信号
            buy_sig = ((buy_score >= sb) & (buy_score > sell_score)).astype(int)
            sell_sig = ((sell_score >= ss) & (sell_score > buy_score)).astype(int)
            # 与 vectorized_backtest 评分模式同一 warmup 口径
            warmup = min(60, max(10, len(df) // 3))
            buy_sig.iloc[:warmup] = 0
            sell_sig.iloc[:warmup] = 0
            df['signal_buy'] = buy_sig
            df['signal_sell'] = sell_sig
            # 强度改用评分差/10, 保持报告层 -10..10 尺度
            df['signal_strength'] = ((buy_score - sell_score) / 10).clip(-10, 10)
        else:
            buy_score, sell_score = self._score_signals(df)
            df['signal_buy_score'] = buy_score
            df['signal_sell_score'] = sell_score
            # 买卖互斥: 分值高者才成立 (旧实现两侧各自独立判阈值, 可同时为 1)
            df['signal_buy'] = ((buy_score >= self.buy_threshold) &
                                (buy_score > sell_score)).astype(int)
            df['signal_sell'] = ((sell_score >= self.sell_threshold) &
                                 (sell_score > buy_score)).astype(int)
            df['signal_strength'] = self._calculate_signal_strength(df)

        return df

    def _weighted_scores(self, df):
        """列名适配后调用 vectorized_backtest.weighted_factor_scores。

        signal_generator 列名 (MA5/MA10/MACD/RSI/K/BB_*) → 评分函数列名
        (ma_fast/ma_mid/macd/rsi/k/bb_*); MA10 缺失时就地补算 rolling(10)。
        缺关键指标列直接抛错 (分数会静默变 50 档垃圾值, 不软降级)。
        """
        from vectorized_backtest import weighted_factor_scores

        def real(name):
            return self.column_map.get(name, name)

        required = ['收盘', 'MA5', 'MA20', 'MACD', 'MACD_Signal',
                    'RSI', 'K', 'D', 'BB_Upper', 'BB_Lower']
        missing = [c for c in required
                   if c != '收盘' and real(c) not in df.columns]
        if missing:
            raise ValueError(
                f"加权评分缺少指标列 {missing} — 先经 "
                "stock_data_fetcher.calculate_technical_indicators 计算")

        mid_col = real('MA10')
        m = pd.DataFrame({
            '收盘': df['收盘'],
            'ma_fast': df[real('MA5')],
            'ma_mid': (df[mid_col] if mid_col in df.columns
                       else _core_sma(df['收盘'], 10)),
            'ma_slow': df[real('MA20')],
            'macd': df[real('MACD')],
            'macd_signal': df[real('MACD_Signal')],
            'rsi': df[real('RSI')],
            'k': df[real('K')],
            'd': df[real('D')],
            'bb_upper': df[real('BB_Upper')],
            'bb_lower': df[real('BB_Lower')],
        }, index=df.index)
        return weighted_factor_scores(m, self.scoring_params)

    def _ma_cross_signal(self, df):
        """均线交叉信号"""
        ma5 = self._col(df, 'MA5')
        ma20 = self._col(df, 'MA20')
        if ma5 is None or ma20 is None:
            return pd.Series(0.0, index=df.index)

        close = df['收盘']

        # 金叉：MA5上穿MA20
        golden_cross = (ma5 > ma20) & (ma5.shift(1) <= ma20.shift(1))

        # 死叉：MA5下穿MA20
        death_cross = (ma5 < ma20) & (ma5.shift(1) >= ma20.shift(1))

        signal = pd.Series(0.0, index=df.index)
        signal[golden_cross] = 1   # 买入信号
        signal[death_cross] = -1  # 卖出信号

        # 趋势确认（仅填未定档位，不覆盖交叉 1/-1）
        trend_up = (close > ma5) & (ma5 > ma20)
        trend_down = (close < ma5) & (ma5 < ma20)

        signal[trend_up & (signal == 0)] = 0.5
        signal[trend_down & (signal == 0)] = -0.5

        return signal

    def _macd_signal(self, df):
        """MACD信号"""
        macd = self._col(df, 'MACD')
        signal_line = self._col(df, 'MACD_Signal')
        if macd is None or signal_line is None:
            return pd.Series(0.0, index=df.index)

        # 金叉
        golden_cross = (macd > signal_line) & (macd.shift(1) <= signal_line.shift(1))

        # 死叉
        death_cross = (macd < signal_line) & (macd.shift(1) >= signal_line.shift(1))

        signal = pd.Series(0.0, index=df.index)
        signal[golden_cross] = 1
        signal[death_cross] = -1

        # 零轴上方（仅填未定档位）
        above_zero = (macd > 0) & (signal_line > 0)
        below_zero = (macd < 0) & (signal_line < 0)

        signal[above_zero & (signal == 0)] = 0.3
        signal[below_zero & (signal == 0)] = -0.3

        return signal

    def _kdj_signal(self, df):
        """KDJ信号"""
        k = self._col(df, 'K')
        d = self._col(df, 'D')
        if k is None or d is None:
            return pd.Series(0.0, index=df.index)

        # 金叉
        golden_cross = (k > d) & (k.shift(1) <= d.shift(1))

        # 死叉
        death_cross = (k < d) & (k.shift(1) >= d.shift(1))

        signal = pd.Series(0.0, index=df.index)
        signal[golden_cross] = 1
        signal[death_cross] = -1

        # 超买超卖（仅填未定档位）
        overbought = k > 80
        oversold = k < 20

        signal[overbought & (signal == 0)] = -0.5  # 超买考虑卖出
        signal[oversold & (signal == 0)] = 0.5     # 超卖考虑买入

        return signal

    def _rsi_signal(self, df):
        """RSI信号 (超卖/超买阈值可配, 默认 30/70)"""
        rsi = self._col(df, 'RSI')
        if rsi is None:
            return pd.Series(0.0, index=df.index)

        signal = pd.Series(0.0, index=df.index)

        # 超卖区买入信号 (进入超卖区当根给满分)
        oversold = ((rsi < self.rsi_oversold) &
                    (rsi.shift(1) >= self.rsi_oversold))
        signal[oversold] = 1

        # 超买区卖出信号
        overbought = ((rsi > self.rsi_overbought) &
                      (rsi.shift(1) <= self.rsi_overbought))
        signal[overbought] = -1

        # 强势区（仅填未定档位）
        strong = rsi > 50
        weak = rsi < 50

        signal[strong & (signal == 0)] = 0.2
        signal[weak & (signal == 0)] = -0.2

        return signal

    def _bollinger_signal(self, df):
        """布林带信号 (突破跟随口径: 突破上轨买 / 触下轨卖 / 回归中轨 ±1)"""
        upper = self._col(df, 'BB_Upper')
        lower = self._col(df, 'BB_Lower')
        if upper is None or lower is None:
            return pd.Series(0.0, index=df.index)

        close = df['收盘']

        signal = pd.Series(0.0, index=df.index)

        # 突破上轨
        break_upper = close > upper
        signal[break_upper] = 0.5

        # 触及下轨
        touch_lower = close < lower
        signal[touch_lower] = -0.5

        # 回归中轨
        return_from_upper = (close < upper) & (close.shift(1) >= upper.shift(1))
        return_from_lower = (close > lower) & (close.shift(1) <= lower.shift(1))

        signal[return_from_lower] = 1   # 从下轨回归买入
        signal[return_from_upper] = -1  # 从上轨回归卖出

        return signal

    def _volume_signal(self, df):
        """成交量信号"""
        if '成交量' not in df:
            return pd.Series(0.0, index=df.index)

        volume = df['成交量']
        volume_ma5 = _core_volume_ma(volume, 5)

        signal = pd.Series(0.0, index=df.index)

        # 放量
        high_volume = volume > volume_ma5 * 1.5
        signal[high_volume] = 0.3

        # 缩量
        low_volume = volume < volume_ma5 * 0.7
        signal[low_volume] = -0.2

        # 量价配合
        close = df['收盘']
        price_up = close > close.shift(1)
        volume_up = volume > volume_ma5

        price_down = close < close.shift(1)
        volume_down = volume < volume_ma5

        # 量增价涨（整列布尔条件，回测序列与当日实盘口径一致）
        signal[price_up & volume_up] = 0.5

        # 量增价跌
        signal[price_down & volume_up] = -0.5

        return signal

    def _breakout_signal(self, df):
        """突破信号"""
        close = df['收盘']
        high = df['最高']
        low = df['最低']

        # 20日新高
        high_20 = high.rolling(20).max()
        low_20 = low.rolling(20).min()

        signal = pd.Series(0.0, index=df.index)

        # 突破20日高点
        break_high = close > high_20.shift(1)
        signal[break_high] = 1

        # 跌破20日低点
        break_low = close < low_20.shift(1)
        signal[break_low] = -1

        return signal

    def _score_signals(self, df):
        """买卖分值 (分项正值和 / 负值和绝对值和) — 唯一计算点.

        Returns:
            (buy_score, sell_score): 两条 float Series
        """
        buy_score = pd.Series(0.0, index=df.index)
        sell_score = pd.Series(0.0, index=df.index)
        for sig in SIGNAL_LABELS:
            if sig in df.columns:
                col = df[sig]
                buy_score = buy_score + col.clip(lower=0)
                sell_score = sell_score + (-col.clip(upper=0))
        return buy_score, sell_score

    def _combine_buy_signals(self, df):
        """综合买入信号 (仅阈值判定, 不含互斥仲裁; 仲裁在 generate_signals)"""
        buy_score, _ = self._score_signals(df)
        return (buy_score >= self.buy_threshold).astype(int)

    def _combine_sell_signals(self, df):
        """综合卖出信号 (仅阈值判定, 不含互斥仲裁; 仲裁在 generate_signals)"""
        _, sell_score = self._score_signals(df)
        return (sell_score >= self.sell_threshold).astype(int)

    def _calculate_signal_strength(self, df):
        """计算信号强度 (分项有符号求和, clip 到 -10..10)"""
        strength = pd.Series(0.0, index=df.index)

        for sig in SIGNAL_LABELS:
            if sig in df.columns:
                strength += df[sig]

        # 归一化到-10到10
        strength = strength.clip(-10, 10)

        return strength

    def get_latest_signal(self, data):
        """
        获取最新信号

        Args:
            data: 包含技术指标的DataFrame

        Returns:
            dict: 最新信号信息
        """
        df = self.generate_signals(data)
        latest = df.iloc[-1]

        # 审计 C-P1-12: 前置可执行性检查 (本 API 无 symbol → 一字板记 skipped)
        report = trade_constraints.check_last_bar(df, code=None, side='both')

        return {
            'date': latest.name if hasattr(latest.name, 'strftime') else latest['日期'],
            'price': latest['收盘'],
            'buy_signal': bool(latest['signal_buy']),
            'sell_signal': bool(latest['signal_sell']),
            'strength': latest['signal_strength'],
            'buy_score': float(latest['signal_buy_score']),
            'sell_score': float(latest['signal_sell_score']),
            'ma_cross': latest['signal_ma_cross'],
            'macd': latest['signal_macd'],
            'kdj': latest['signal_kdj'],
            'rsi': latest['signal_rsi'],
            'bb': latest['signal_bb'],
            'volume': latest['signal_volume'],
            'breakout': latest['signal_breakout'],
            # 契约列名 → 值 (报告层标签翻译用, 项21 合并新增)
            'signals': {col: float(latest[col]) for col in SIGNAL_LABELS},
            'executable': report.ok,
            'blocked_reasons': list(report.blocked_reasons),
            'skipped_checks': list(report.skipped_checks),
        }

    def to_signal(self, data, symbol=None, target_weight=None,
                  execute_at=None, signal_date=None):
        """产出统一契约 Signal (审计 C #9 / 项 21 #9a).

        取最新一根 bar 的信号; 可执行性检查复用 `get_latest_signal` 已算好的
        约束结果 (不重复调用 trade_constraints)。

        Args:
            data: 含技术指标的 DataFrame
            symbol: 标的代码 (缺省留空)
            target_weight: 目标仓位比例; None = 由下游风控决定
            execute_at: 可执行时点; None = 由执行层 (t+1 开盘) 决定
            signal_date: 信号日期; None = 取最新 bar 的日期

        Returns:
            core.signal.Signal
        """
        from core.signal import (ACTION_BUY, ACTION_HOLD, ACTION_SELL,
                                 SCALE_VOTE, SCALE_WEIGHTED, Signal,
                                 normalize_date)

        info = self.get_latest_signal(data)
        action = (ACTION_BUY if info['buy_signal']
                  else ACTION_SELL if info['sell_signal'] else ACTION_HOLD)
        side = ('buy' if action == ACTION_BUY
                else 'sell' if action == ACTION_SELL else 'all')
        reasons = (describe_signals(info['signals'], side=side)
                   if action != ACTION_HOLD else [])

        return Signal(
            symbol=symbol or '',
            signal_date=normalize_date(
                signal_date if signal_date is not None else info['date']),
            action=action,
            strength=float(info['strength']),
            scale=SCALE_WEIGHTED if self.use_weighted_scoring else SCALE_VOTE,
            reasons=reasons,
            target_weight=target_weight,
            execute_at=execute_at,
            executable=bool(info['executable']),
            blocked_reasons=list(info['blocked_reasons']),
            skipped_checks=list(info['skipped_checks']),
            source='signal_generator',
            extra={
                'price': float(info['price']),
                'buy_score': float(info['buy_score']),
                'sell_score': float(info['sell_score']),
            },
        )

    def format_signal_report(self, signal_info):
        """格式化信号报告"""
        lines = []
        lines.append("=" * 60)
        lines.append("交易信号报告")
        lines.append("=" * 60)
        lines.append("")

        lines.append(f"日期: {signal_info['date']}")
        lines.append(f"价格: {signal_info['price']:.2f} 元")
        lines.append("")

        lines.append("综合信号:")
        lines.append(f"  买入信号: {'是' if signal_info['buy_signal'] else '否'}")
        lines.append(f"  卖出信号: {'是' if signal_info['sell_signal'] else '否'}")
        lines.append(f"  信号强度: {signal_info['strength']:+.1f}")
        lines.append("")

        lines.append("分项信号:")

        # 分项信号 (措辞按档位值翻译, 不再按符号硬编码 — 旧版把
        # "突破上轨(买)" 标成 "触及下轨(买)"、"触下轨(卖)" 标成 "突破上轨(卖)")
        values = signal_info.get('signals') or {}
        legacy = {
            'signal_ma_cross': signal_info.get('ma_cross', 0.0),
            'signal_macd': signal_info.get('macd', 0.0),
            'signal_kdj': signal_info.get('kdj', 0.0),
            'signal_rsi': signal_info.get('rsi', 0.0),
            'signal_bb': signal_info.get('bb', 0.0),
            'signal_volume': signal_info.get('volume', 0.0),
            'signal_breakout': signal_info.get('breakout', 0.0),
        }
        for col, display in SIGNAL_DISPLAY_NAMES.items():
            val = values.get(col, legacy.get(col, 0.0))
            labels = describe_signals({col: val}, side='all')
            if labels:
                direction = '买入' if float(val) > 0 else '卖出'
                lines.append(f"  {display}: {direction} ({labels[0]})")
            else:
                lines.append(f"  {display}: 中性")


        # 审计 C-P1-12: 可执行性阻断提示 (仅在存在阻断时输出)
        blocked = signal_info.get('blocked_reasons') or []
        if blocked:
            lines.append("")
            lines.append("可执行性检查 (C-P1-12):")
            for reason in blocked:
                lines.append(f"  [阻断] {reason}")

        lines.append("")
        lines.append("=" * 60)

        return "\n".join(lines)


# 便捷函数
def generator_from_params(params):
    """按下发参数构造生成器 (E-P1 #19 契约公开入口): None → 出厂投票制;
    dict → optimized_params.load_optimized_params 下发字典直通
    (阈值/模式/评分参数同源)。web_app 加载优化参数时经此换实例,
    既有 signal_buy/sell/strength 调用面零改动。"""
    if not params:
        return SignalGenerator()
    return SignalGenerator(
        buy_threshold=float(params.get('buy_threshold', 2.0)),
        sell_threshold=float(params.get('sell_threshold', 2.0)),
        use_weighted_scoring=bool(params.get('use_weighted_scoring', False)),
        scoring_params=params,
        # 优化器参数空间含 RSI 阈值维 (parameter_space RSI_OVERSOLD/OVERBOUGHT),
        # 下发时必须真的生效 (缺键 → 出厂 30/70)
        rsi_oversold=float(params.get('rsi_oversold', 30.0)),
        rsi_overbought=float(params.get('rsi_overbought', 70.0)))


def generate_signals(data, params=None):
    """生成交易信号 (params: 优化器下发参数字典, 可选)"""
    return generator_from_params(params).generate_signals(data)


def get_latest_signal(data, params=None):
    """获取最新信号 (params 同上)"""
    return generator_from_params(params).get_latest_signal(data)


def get_signal(data, params=None, symbol=None, **kwargs):
    """产出统一契约 Signal (审计 C #9 便捷入口).

    Args:
        data: 含技术指标的 DataFrame
        params: 优化器下发参数字典 (同 generate_signals)
        symbol: 标的代码
        **kwargs: 透传 to_signal (target_weight/execute_at/signal_date)

    Returns:
        core.signal.Signal
    """
    return generator_from_params(params).to_signal(data, symbol=symbol,
                                                    **kwargs)


def format_signal_report(signal_info):
    """格式化信号报告"""
    generator = SignalGenerator()
    return generator.format_signal_report(signal_info)


# 测试
if __name__ == "__main__":
    from stock_data_fetcher import StockDataFetcher

    fetcher = StockDataFetcher()

    # 测试信号生成
    print("测试信号生成器...")
    print()

    data = fetcher.get_quote_data('600519', days=120)
    if data is not None and len(data) > 0:
        # 计算技术指标
        data = fetcher.calculate_technical_indicators(data)

        # 生成信号
        generator = SignalGenerator()
        signal_info = generator.get_latest_signal(data)

        report = generator.format_signal_report(signal_info)
        print(report)
    else:
        print("无法获取数据")
