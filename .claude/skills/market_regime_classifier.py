# -*- coding: utf-8 -*-
"""
大盘态势分类器 - Market Regime Classifier

将A股历史按大盘走势分为不同体制(牛市/熊市/震荡市等)，
为指标优化提供按体制分段的数据基础。

使用沪深300指数(000300)作为主指数，上证指数(000001)辅助验证。
"""

import pandas as pd
import numpy as np
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import json


class Regime(Enum):
    """市场体制枚举"""
    BULL = "BULL"           # 牛市
    BEAR = "BEAR"           # 熊市
    SIDEWAYS = "SIDEWAYS"   # 横盘震荡
    CRASH = "CRASH"         # 暴跌
    RECOVERY = "RECOVERY"   # 反弹恢复


@dataclass
class RegimeWindow:
    """一个体制时段"""
    regime: Regime
    start_date: str
    end_date: str
    start_idx: int
    end_idx: int
    duration_days: int
    index_return: float  # 该时段指数涨跌幅(%)


@dataclass
class RegimeStats:
    """体制统计信息"""
    regime: Regime
    count: int              # 出现次数
    total_days: int         # 总天数
    avg_duration: float     # 平均持续天数
    pct_of_total: float     # 占总时间比例(%)
    avg_return: float       # 平均涨跌幅(%)


class MarketRegimeClassifier:
    """
    大盘态势分类器

    基于沪深300指数的多维度指标，将每个交易日标注为对应的市场体制。

    分类方法:
    - ADAPTIVE: 根据指数实际波动率动态调整阈值
    - FIXED: 使用固定阈值

    细分体制:
    - CRASH: 单月跌幅>10% 或 连续5日跌幅>8%
    - RECOVERY: 从CRASH中恢复，20日涨幅>8%
    - BULL: MA60>MA120 且 趋势向上
    - BEAR: MA60<MA120 且 趋势向下
    - SIDEWAYS: 其余情况
    """

    def __init__(self, data_dir="./stock_data"):
        self.data_dir = Path(data_dir)
        self.index_data = None
        self.regime_series = None

    def load_index_data(self, index_code="000300", start_date="19960101", end_date=None):
        """
        加载大盘指数数据

        Parameters:
        -----------
        index_code : str
            指数代码，"000300"(沪深300) 或 "000001"(上证指数)
        start_date : str
            开始日期
        end_date : str
            结束日期，默认今天
        """
        import akshare as ak

        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")

        print(f"[INFO] 加载指数 {index_code} 数据 ({start_date} ~ {end_date})...")

        try:
            # akshare获取指数数据
            if index_code == "000300":
                df = ak.stock_zh_index_daily(symbol="sh000300")
            elif index_code == "000001":
                df = ak.stock_zh_index_daily(symbol="sh000001")
            else:
                # 尝试通用接口
                df = ak.stock_zh_index_daily(symbol=f"sh{index_code}")

            if df is not None and len(df) > 0:
                # 标准化列名
                col_map = {'date': '日期', 'open': '开盘', 'high': '最高',
                           'low': '最低', 'close': '收盘', 'volume': '成交量'}
                df = df.rename(columns=col_map)
                df['日期'] = pd.to_datetime(df['日期'])
                df = df.sort_values('日期').reset_index(drop=True)

                # 过滤日期范围
                start_dt = pd.to_datetime(start_date)
                end_dt = pd.to_datetime(end_date)
                df = df[(df['日期'] >= start_dt) & (df['日期'] <= end_dt)]
                df = df.reset_index(drop=True)

                self.index_data = df
                print(f"[OK] 加载 {len(df)} 条指数数据 ({df['日期'].iloc[0].date()} ~ {df['日期'].iloc[-1].date()})")
                return df

        except Exception as e:
            print(f"[ERROR] 加载指数数据失败: {e}")

        # 备用方案: 从本地缓存加载
        return self._load_from_local_cache(index_code, start_date, end_date)

    def _load_from_local_cache(self, index_code, start_date, end_date):
        """从本地CSV缓存加载指数数据"""
        cache_dir = self.data_dir / "quotes"
        pattern = f"{index_code}_*.csv"
        files = sorted(cache_dir.glob(pattern))

        if not files:
            print(f"[WARN] 本地无 {index_code} 缓存数据")
            return None

        # 加载最新文件
        df = pd.read_csv(files[-1], encoding='utf-8-sig')
        if '日期' in df.columns:
            df['日期'] = pd.to_datetime(df['日期'])
        df = df.sort_values('日期').reset_index(drop=True)
        self.index_data = df
        print(f"[OK] 从缓存加载 {len(df)} 条指数数据")
        return df

    def classify(self, method='adaptive', crash_threshold=-10.0,
                 recovery_threshold=8.0, bull_trend_pct=5.0,
                 bear_trend_pct=-5.0) -> pd.Series:
        """
        对每个交易日标注大盘态势

        Parameters:
        -----------
        method : str
            'adaptive' - 根据波动率动态调整阈值
            'fixed' - 使用固定阈值
        crash_threshold : float
            暴跌阈值(%)，月跌幅超过此值判定为暴跌
        recovery_threshold : float
            反弹阈值(%)，从暴跌低点20日涨幅超过此值判定为反弹
        bull_trend_pct : float
            牛市趋势阈值(%)，20日涨幅超过此值且MA60>MA120判定为牛市
        bear_trend_pct : float
            熊市趋势阈值(%)，20日跌幅超过此值且MA60<MA120判定为熊市

        Returns:
        --------
        pd.Series : 与index_data等长的体制标签序列
        """
        if self.index_data is None:
            raise ValueError("请先调用 load_index_data() 加载指数数据")

        df = self.index_data.copy()
        close = df['收盘']

        # 计算辅助指标
        ma20 = close.rolling(20).mean()
        ma60 = close.rolling(60).mean()
        ma120 = close.rolling(120).mean()

        # 20日涨跌幅
        ret_20d = close.pct_change(20) * 100
        # 5日涨跌幅
        ret_5d = close.pct_change(5) * 100
        # 月度涨跌幅(约20个交易日)
        ret_month = close.pct_change(20) * 100

        # 20日滚动波动率(年化)
        daily_ret = close.pct_change()
        vol_20d = daily_ret.rolling(20).std() * np.sqrt(252) * 100

        # 自适应阈值: 根据历史波动率中位数调整
        if method == 'adaptive':
            vol_median = vol_20d.rolling(252).median()
            vol_ratio = vol_20d / vol_median.clip(lower=1)
            # 波动率高时放宽阈值
            crash_threshold = crash_threshold * vol_ratio
            bear_trend_pct = bear_trend_pct * vol_ratio
            bull_trend_pct = bull_trend_pct * vol_ratio

        # 分类逻辑
        regimes = pd.Series(Regime.SIDEWAYS.value, index=df.index)

        # Step 1: 检测暴跌 (优先级最高)
        is_crash = (ret_month < crash_threshold) | (ret_5d < -8)
        regimes[is_crash] = Regime.CRASH.value

        # Step 2: 检测反弹 (从暴跌中恢复)
        # 找到最近的暴跌结束点，检查之后20日涨幅
        crash_end = is_crash.shift(1) & ~is_crash  # 暴跌结束的那天
        recovery_window = 20
        for i in range(recovery_window, len(regimes)):
            if crash_end.iloc[max(0, i-recovery_window):i].any():
                # 最近20天内有暴跌结束
                if ret_20d.iloc[i] > recovery_threshold and regimes.iloc[i] != Regime.CRASH.value:
                    regimes.iloc[i] = Regime.RECOVERY.value

        # Step 3: 牛市判定 (MA60>MA120 且 趋势向上)
        is_bull = (ma60 > ma120) & (ret_20d > bull_trend_pct) & (regimes == Regime.SIDEWAYS.value)
        regimes[is_bull] = Regime.BULL.value

        # Step 4: 熊市判定 (MA60<MA120 且 趋势向下)
        is_bear = (ma60 < ma120) & (ret_20d < bear_trend_pct) & (regimes == Regime.SIDEWAYS.value)
        regimes[is_bear] = Regime.BEAR.value

        # Step 5: 补充规则 - MA60>MA120 但涨幅不大也算偏牛市
        is_mild_bull = (ma60 > ma120) & (ret_20d > 0) & (regimes == Regime.SIDEWAYS.value)
        regimes[is_mild_bull] = Regime.BULL.value

        # Step 6: 补充规则 - MA60<MA120 但跌幅不大也算偏熊市
        is_mild_bear = (ma60 < ma120) & (ret_20d < 0) & (regimes == Regime.SIDEWAYS.value)
        regimes[is_mild_bear] = Regime.BEAR.value

        self.regime_series = regimes
        return regimes

    def get_regime_windows(self, regime_series=None) -> dict[str, list[RegimeWindow]]:
        """
        返回每种体制的连续时间段列表

        Returns:
        --------
        dict : {regime_name: [RegimeWindow, ...]}
        """
        if regime_series is None:
            regime_series = self.regime_series
        if regime_series is None:
            raise ValueError("请先调用 classify() 进行分类")

        df = self.index_data
        windows = {}

        # 找出连续的体制段
        current_regime = regime_series.iloc[0]
        start_idx = 0

        for i in range(1, len(regime_series)):
            if regime_series.iloc[i] != current_regime:
                # 体制切换
                window = RegimeWindow(
                    regime=Regime(current_regime),
                    start_date=str(df['日期'].iloc[start_idx].date()),
                    end_date=str(df['日期'].iloc[i-1].date()),
                    start_idx=start_idx,
                    end_idx=i-1,
                    duration_days=i - start_idx,
                    index_return=(df['收盘'].iloc[i-1] / df['收盘'].iloc[start_idx] - 1) * 100
                )
                regime_name = current_regime
                if regime_name not in windows:
                    windows[regime_name] = []
                windows[regime_name].append(window)

                current_regime = regime_series.iloc[i]
                start_idx = i

        # 最后一段
        window = RegimeWindow(
            regime=Regime(current_regime),
            start_date=str(df['日期'].iloc[start_idx].date()),
            end_date=str(df['日期'].iloc[-1].date()),
            start_idx=start_idx,
            end_idx=len(regime_series) - 1,
            duration_days=len(regime_series) - start_idx,
            index_return=(df['收盘'].iloc[-1] / df['收盘'].iloc[start_idx] - 1) * 100
        )
        regime_name = current_regime
        if regime_name not in windows:
            windows[regime_name] = []
        windows[regime_name].append(window)

        return windows

    def get_regime_stats(self, regime_series=None) -> list[RegimeStats]:
        """
        各体制统计信息

        Returns:
        --------
        list[RegimeStats]
        """
        windows = self.get_regime_windows(regime_series)
        total_days = len(regime_series) if regime_series is not None else len(self.regime_series)

        stats = []
        for regime_name, window_list in windows.items():
            regime = Regime(regime_name)
            all_days = sum(w.duration_days for w in window_list)
            all_returns = [w.index_return for w in window_list]

            stats.append(RegimeStats(
                regime=regime,
                count=len(window_list),
                total_days=all_days,
                avg_duration=all_days / len(window_list) if window_list else 0,
                pct_of_total=all_days / total_days * 100 if total_days > 0 else 0,
                avg_return=np.mean(all_returns) if all_returns else 0
            ))

        # 按占比排序
        stats.sort(key=lambda x: x.pct_of_total, reverse=True)
        return stats

    def get_regime_for_dates(self, dates: pd.DatetimeIndex, regime_series=None) -> pd.Series:
        """
        获取指定日期的体制标签

        Parameters:
        -----------
        dates : pd.DatetimeIndex
            要查询的日期列表
        regime_series : pd.Series
            体制标签序列，默认使用上次classify的结果

        Returns:
        --------
        pd.Series : 指定日期的体制标签
        """
        if regime_series is None:
            regime_series = self.regime_series
        if regime_series is None:
            raise ValueError("请先调用 classify() 进行分类")

        idx_dates = self.index_data['日期']
        result = pd.Series(Regime.SIDEWAYS.value, index=dates)

        for date in dates:
            # 找到最近的交易日
            mask = idx_dates <= date
            if mask.any():
                last_idx = mask.idxmax()
                result[date] = regime_series.iloc[last_idx]

        return result

    def format_report(self, regime_series=None) -> str:
        """
        格式化输出体制分类报告
        """
        if regime_series is None:
            regime_series = self.regime_series

        stats = self.get_regime_stats(regime_series)
        windows = self.get_regime_windows(regime_series)

        lines = []
        lines.append("=" * 80)
        lines.append("                    大盘态势分类报告")
        lines.append("=" * 80)
        lines.append("")

        if self.index_data is not None:
            lines.append(f"  指数: 沪深300")
            lines.append(f"  区间: {self.index_data['日期'].iloc[0].date()} ~ {self.index_data['日期'].iloc[-1].date()}")
            lines.append(f"  总交易日: {len(self.index_data)}")
            lines.append("")

        # 体制统计表
        lines.append("  【各体制统计】")
        lines.append(f"  {'体制':<12} {'出现次数':<10} {'总天数':<10} {'平均持续':<10} {'占比':<10} {'平均涨跌':<10}")
        lines.append("  " + "-" * 62)

        regime_names = {
            'BULL': '牛市',
            'BEAR': '熊市',
            'SIDEWAYS': '横盘震荡',
            'CRASH': '暴跌',
            'RECOVERY': '反弹'
        }

        for s in stats:
            name = regime_names.get(s.regime.value, s.regime.value)
            lines.append(f"  {name:<12} {s.count:<10} {s.total_days:<10} "
                        f"{s.avg_duration:<10.1f} {s.pct_of_total:<10.1f} {s.avg_return:<10.2f}%")

        lines.append("")

        # 主要体制时段
        lines.append("  【主要体制时段】")
        for regime_name, window_list in windows.items():
            name = regime_names.get(regime_name, regime_name)
            lines.append(f"\n  {name} (共{len(window_list)}段):")
            for w in sorted(window_list, key=lambda x: x.duration_days, reverse=True)[:5]:
                lines.append(f"    {w.start_date} ~ {w.end_date} "
                           f"({w.duration_days}天, 指数{w.index_return:+.1f}%)")

        lines.append("")
        lines.append("=" * 80)

        return "\n".join(lines)

    def save_labels(self, filepath, regime_series=None):
        """保存体制标签到文件"""
        if regime_series is None:
            regime_series = self.regime_series

        df = pd.DataFrame({
            '日期': self.index_data['日期'],
            '收盘': self.index_data['收盘'],
            'regime': regime_series.values
        })
        df.to_csv(filepath, index=False, encoding='utf-8-sig')
        print(f"[OK] 体制标签已保存: {filepath}")

    def load_labels(self, filepath) -> pd.Series:
        """从文件加载体制标签"""
        df = pd.read_csv(filepath, encoding='utf-8-sig')
        self.index_data = df[['日期', '收盘']].copy()
        self.index_data['日期'] = pd.to_datetime(self.index_data['日期'])
        self.regime_series = df['regime']
        print(f"[OK] 加载 {len(df)} 条体制标签")
        return self.regime_series


def main():
    """测试入口"""
    import argparse

    parser = argparse.ArgumentParser(description='大盘态势分类器')
    parser.add_argument('--index', default='000300', help='指数代码')
    parser.add_argument('--start', default='19960101', help='开始日期')
    parser.add_argument('--end', default=None, help='结束日期')
    parser.add_argument('--method', default='adaptive', choices=['adaptive', 'fixed'],
                       help='分类方法')
    parser.add_argument('--save', default=None, help='保存标签文件路径')
    parser.add_argument('--load', default=None, help='加载标签文件')

    args = parser.parse_args()

    classifier = MarketRegimeClassifier()

    if args.load:
        classifier.load_labels(args.load)
    else:
        classifier.load_index_data(args.index, args.start, args.end)
        classifier.classify(method=args.method)

        if args.save:
            classifier.save_labels(args.save)

    # 输出报告
    print(classifier.format_report())


if __name__ == "__main__":
    main()
