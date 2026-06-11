# -*- coding: utf-8 -*-
"""
每日信号生成器 - Daily Signal Generator (体制自适应)

实时判断大盘态势 → 选择对应的指标体系 → 用该体系的参数计算指标 →
生成买卖信号 → 评分排名 → 输出推荐。

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
import sys

from historical_data_manager import HistoricalDataManager
from vectorized_backtest import VectorizedBacktester
from parameter_space import ParameterSpace


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
    buy_score: float           # 买入得分 (0-10)
    sell_score: float          # 卖出得分 (0-10)
    signal: str                # "BUY" / "HOLD" / "SELL"
    signal_strength: float     # 信号强度 (-1 ~ 1)
    reasons: list              # 信号原因
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
    distance_to_resistance: float  # 距压力位百分比


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

    # RSI
    rsi_period = int(params.get('rsi_period', 14))
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(rsi_period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(rsi_period).mean()
    rs = gain / loss.replace(0, np.nan)
    df['RSI'] = 100 - (100 / (1 + rs))

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

    # ATR
    atr_period = int(params.get('atr_period', 14))
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(atr_period).mean()

    # 成交量均线
    df['Vol_MA5'] = volume.rolling(5).mean()
    df['Vol_MA20'] = volume.rolling(20).mean()

    return df


def generate_signal(data: pd.DataFrame, params: dict) -> dict:
    """
    对单只股票生成买卖信号

    Returns:
    --------
    dict : {buy_score, sell_score, signal, strength, reasons, indicators}
    """
    if len(data) < 60:
        return None

    df = compute_indicators(data, params)
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest

    buy_threshold = float(params.get('buy_threshold', 2.0))
    sell_threshold = float(params.get('sell_threshold', 2.0))
    rsi_oversold = float(params.get('rsi_oversold', 30))
    rsi_overbought = float(params.get('rsi_overbought', 70))

    buy_score = 0.0
    sell_score = 0.0
    buy_reasons = []
    sell_reasons = []

    close = latest['收盘']
    ma_fast = latest['MA_Fast']
    ma_slow = latest['MA_Slow']
    macd = latest['MACD']
    macd_sig = latest['MACD_Signal']
    macd_hist = latest['MACD_Hist']
    rsi = latest['RSI']
    k = latest['K']
    d = latest['D']
    bb_upper = latest['BB_Upper']
    bb_lower = latest['BB_Lower']
    bb_mid = latest['BB_Mid']
    vol = latest['成交量']
    vol_ma5 = latest['Vol_MA5']

    # 1. MA金叉/死叉
    if ma_fast > ma_slow and prev['MA_Fast'] <= prev['MA_Slow']:
        buy_score += 1.0
        buy_reasons.append("MA金叉")
    elif ma_fast < ma_slow and prev['MA_Fast'] >= prev['MA_Slow']:
        sell_score += 1.0
        sell_reasons.append("MA死叉")

    # 价格站上/跌破MA慢线
    if close > ma_slow:
        buy_score += 0.3
    else:
        sell_score += 0.3

    # 2. MACD金叉/死叉
    if macd > macd_sig and prev['MACD'] <= prev['MACD_Signal']:
        buy_score += 1.0
        buy_reasons.append("MACD金叉")
    elif macd < macd_sig and prev['MACD'] >= prev['MACD_Signal']:
        sell_score += 1.0
        sell_reasons.append("MACD死叉")

    # MACD柱由负转正
    if macd_hist > 0 and prev['MACD_Hist'] <= 0:
        buy_score += 0.5
        buy_reasons.append("MACD柱转正")

    # 3. RSI
    if rsi < rsi_oversold:
        buy_score += 0.5
        buy_reasons.append(f"RSI超卖({rsi:.0f})")
    elif rsi > rsi_overbought:
        sell_score += 0.5
        sell_reasons.append(f"RSI超买({rsi:.0f})")

    # 4. KDJ金叉/死叉
    if k > d and prev['K'] <= prev['D']:
        buy_score += 0.8
        buy_reasons.append("KDJ金叉")
    elif k < d and prev['K'] >= prev['D']:
        sell_score += 0.8
        sell_reasons.append("KDJ死叉")

    # KDJ超买超卖
    if k < 20:
        buy_score += 0.3
        buy_reasons.append("KDJ超卖")
    elif k > 80:
        sell_score += 0.3
        sell_reasons.append("KDJ超买")

    # 5. 布林带
    if close <= bb_lower * 1.02:
        buy_score += 0.5
        buy_reasons.append("触及布林下轨")
    elif close >= bb_upper * 0.98:
        sell_score += 0.5
        sell_reasons.append("触及布林上轨")

    # 6. 放量/缩量
    if not np.isnan(vol_ma5) and vol_ma5 > 0:
        vol_ratio = vol / vol_ma5
        if vol_ratio > 1.5:
            buy_score += 0.3
            buy_reasons.append(f"放量(量比{vol_ratio:.1f})")
        elif vol_ratio < 0.5:
            sell_score += 0.2

    # 综合判断
    signal = "HOLD"
    if buy_score >= buy_threshold and buy_score > sell_score:
        signal = "BUY"
    elif sell_score >= sell_threshold and sell_score > buy_score:
        signal = "SELL"

    strength = (buy_score - sell_score) / max(buy_score + sell_score, 1)

    # 布林带位置
    bb_range = bb_upper - bb_lower
    bb_pos = (close - bb_lower) / bb_range if bb_range > 0 else 0.5

    # MA趋势
    if ma_fast > ma_slow:
        ma_trend = "UP"
    elif ma_fast < ma_slow:
        ma_trend = "DOWN"
    else:
        ma_trend = "FLAT"

    return {
        'buy_score': buy_score,
        'sell_score': sell_score,
        'signal': signal,
        'strength': strength,
        'reasons': buy_reasons if signal == "BUY" else sell_reasons if signal == "SELL" else [],
        'indicators': {
            'ma_trend': ma_trend,
            'macd_hist': macd_hist,
            'rsi': rsi,
            'kdj_k': k,
            'bb_position': bb_pos,
            'volume_ratio': vol / vol_ma5 if vol_ma5 > 0 else 1.0,
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
        self.systems = {}       # {regime: {name, params, ...}}
        self.default_params = ParameterSpace.get_defaults()
        self._index_labels = None
        self._current_regime = None

        if optimization_result_file and Path(optimization_result_file).exists():
            self.load_systems(optimization_result_file)

    def load_systems(self, filepath):
        """加载优化后的指标体系"""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        for sys_data in data.get('systems', []):
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
        )

    def generate_daily_report(self, symbols: list = None,
                              n_stocks: int = 50,
                              top_n: int = 10) -> DailyReport:
        """
        生成每日推荐报告

        Parameters:
        -----------
        symbols : list or None
            股票列表，None则从股票池随机抽样
        n_stocks : int
            分析股票数
        top_n : int
            推荐TOP N

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

        # 获取股票池
        if symbols is None:
            symbols = self.data_manager.get_universe(min_rows=2000)
            if len(symbols) > n_stocks:
                import random
                symbols = random.sample(symbols, n_stocks)

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

        # 体制切换预警
        alert = self._check_regime_switch()

        report = DailyReport(
            date=datetime.now().strftime('%Y-%m-%d'),
            current_regime=regime,
            regime_cn=regime_cn,
            system_used=self.get_system_name_for_regime(regime),
            system_description=self.systems.get(regime, {}).get('description', ''),
            total_analyzed=len(signals),
            signals=signals,
            regime_switch_alert=alert,
            timestamp=datetime.now().isoformat(),
        )

        return report

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
                      show_all: bool = False) -> str:
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
            lines.append(f"【买入推荐 TOP {min(10, len(buy_signals))}】")
            lines.append(f"  {'代码':<8} {'名称':<8} {'价格':>8} {'涨跌%':>7} "
                        f"{'买分':>5} {'信号强度':>8} {'原因'}")
            lines.append("  " + "-" * 65)
            for s in buy_signals[:10]:
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
            for s in sell_signals[:10]:
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
        top_n=args.top,
    )

    # 格式化输出
    text = generator.format_report(report, show_all=args.show_all)
    print(text)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f"\n[OK] 报告已保存: {args.output}")


if __name__ == "__main__":
    main()
