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

import sys
import argparse
import json
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from historical_data_manager import HistoricalDataManager
from vectorized_backtest import VectorizedBacktester
from daily_signal_generator import generate_signal
from parameter_space import ParameterSpace


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


class HistoricalBacktestValidator:
    """
    历史回测验证器

    严格防前瞻偏差:
    - 只使用 pick_date 当日及之前的数据
    - pick_date 当日的信号基于 iloc[:pick_idx+1] 的数据
    """

    REGIME_CN = {
        'BULL': '牛市', 'BEAR': '熊市', 'SIDEWAYS': '横盘震荡',
        'CRASH': '暴跌', 'RECOVERY': '反弹'
    }

    def __init__(self, data_dir="./stock_data",
                 optimization_result_file=None):
        self.data_dir = data_dir
        self.data_manager = HistoricalDataManager(data_dir)
        self.backtester = VectorizedBacktester()
        self.systems = {}  # {regime: IndicatorSystem}
        self._load_systems(optimization_result_file)

    def _load_systems(self, filepath):
        """加载指标体系"""
        if not filepath or not Path(filepath).exists():
            print("[WARN] 未提供优化结果文件，仅使用默认参数")
            return

        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

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
                          index_code='000300') -> list:
        """
        均匀选择历史推荐日期

        Parameters:
        -----------
        n_dates : int
            选取日期数
        min_history_days : int
            最少历史天数(确保每个日期都有足够历史数据)
        """
        # 加载指数数据 (尝试多个来源)
        index_data = self._load_index_data(index_code)

        if len(index_data) == 0:
            print("[ERROR] 无法获取指数数据，请先获取000300指数数据")
            return []

        index_data['日期'] = pd.to_datetime(index_data['日期'])
        index_data = index_data.sort_values('日期').reset_index(drop=True)

        # 跳过前min_history_days天
        skip = min_history_days
        if len(index_data) <= skip + n_dates:
            print(f"[WARN] 数据量不足，仅 {len(index_data)} 天")
            skip = max(0, len(index_data) - n_dates - 1)

        # 均匀间隔选日期
        available = len(index_data) - skip
        step = max(1, available // n_dates)
        pick_indices = [skip + i * step for i in range(n_dates)]
        pick_indices = [i for i in pick_indices if i < len(index_data)][:n_dates]

        dates = [str(index_data['日期'].iloc[i].date())
                 for i in pick_indices]

        print(f"[OK] 选取 {len(dates)} 个历史日期: {dates[0]} ~ {dates[-1]}")
        return dates

    def _load_index_data(self, index_code='000300'):
        """加载指数数据，尝试多个来源"""
        # 1. 本地缓存
        data = self.data_manager.load(index_code)
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
            data = self.data_manager.load('000001')
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
        ma60 = close.rolling(60).mean().iloc[-1]
        ma120 = close.rolling(120).mean().iloc[-1]
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
                                  holding_days: int) -> tuple:
        """
        计算从pick_date买入并持有holding_days天的实际收益

        Returns:
        --------
        (return_pct, csi300_return_pct) or (None, None) if no data
        """
        pick_dt = pd.to_datetime(pick_date)
        end_dt = pick_dt + timedelta(days=int(holding_days * 1.5))

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

        # 实际持有天数(取近似)
        actual_days = min(holding_days, len(stock_data) - 1)
        if actual_days < 1:
            return None, None

        entry_price = stock_data.iloc[0]['收盘']
        exit_price = stock_data.iloc[actual_days]['收盘']
        if entry_price <= 0:
            return None, None
        stock_return = (exit_price / entry_price - 1) * 100

        # 沪深300同期收益
        csi_data = self._load_index_data('000300')
        if len(csi_data) == 0:
            return stock_return, None

        csi_data['日期'] = pd.to_datetime(csi_data['日期'])
        csi_data = csi_data[
            (csi_data['日期'] >= pick_dt) & (csi_data['日期'] <= end_dt)
        ].reset_index(drop=True)

        if len(csi_data) < 2:
            return stock_return, None

        csi_entry = csi_data.iloc[0]['收盘']
        csi_exit = csi_data.iloc[min(holding_days, len(csi_data)-1)]['收盘']
        csi_return = (csi_exit / csi_entry - 1) * 100

        return stock_return, csi_return

    def validate(self, n_dates=30, top_n=10,
                 holding_days_list=None,
                 universe=None) -> ValidationReport:
        """
        运行历史回测验证

        Parameters:
        -----------
        n_dates : int
            历史日期数
        top_n : int
            每次推荐的Top N股票
        holding_days_list : list
            持有天数列表, 默认 [90, 180, 270, 365, 540]
        universe : list or None
            股票池, None则用全部可用股票
        """
        if holding_days_list is None:
            holding_days_list = [90, 180, 270, 365, 540]

        # 选择历史日期
        pick_dates = self.select_pick_dates(n_dates=n_dates)
        if not pick_dates:
            print("[ERROR] 无可选日期")
            return None

        # 股票池
        if universe is None:
            universe = self.data_manager.get_universe(min_rows=2000)
        print(f"[INFO] 股票池: {len(universe)} 只")

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

            # 生成推荐
            top_picks = self.generate_top_picks(pick_date, params, universe, top_n)
            print(f"  推荐股票: {len(top_picks)} 只")

            # 计算各持有期收益
            forward_returns = {}
            csi300_returns = {}
            hit_target = {}

            for hd in holding_days_list:
                stock_returns = []
                csi_returns = []
                for pick in top_picks:
                    ret, csi_ret = self.calculate_forward_return(
                        pick['symbol'], pick_date, hd
                    )
                    if ret is not None:
                        stock_returns.append(ret)
                    if csi_ret is not None:
                        csi_returns.append(csi_ret)

                if stock_returns:
                    forward_returns[hd] = float(np.median(stock_returns))
                    csi300_returns[hd] = float(np.median(csi_returns)) if csi_returns else 0
                    hit_target[hd] = sum(1 for r in stock_returns if r >= 10) / len(stock_returns)
                else:
                    forward_returns[hd] = 0
                    csi300_returns[hd] = 0
                    hit_target[hd] = 0

                print(f"  {hd}天后: 中位收益={forward_returns[hd]:+.1f}%, "
                      f"达标率={hit_target[hd]:.1%}, 沪深300={csi300_returns[hd]:+.1f}%")

            pick = HistoricalPick(
                pick_date=pick_date,
                regime=regime,
                regime_cn=regime_cn,
                system_name=system_name,
                top_stocks=[(p['symbol'], p['name'], p['buy_score']) for p in top_picks],
                forward_returns=forward_returns,
                csi300_return=csi300_returns,
                hit_target_10pct=hit_target,
            )
            picks.append(pick)

        # 聚合统计
        aggregate = {}
        beat_benchmark = {}
        for hd in holding_days_list:
            rets = [p.forward_returns[hd] for p in picks if p.forward_returns[hd] != 0]
            csi = [p.csi300_return[hd] for p in picks if p.forward_returns[hd] != 0]
            hits = [p.hit_target_10pct[hd] for p in picks if p.forward_returns[hd] != 0]

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
                }
                if csi:
                    beat = sum(1 for r, c in zip(rets, csi) if r > c) / len(rets)
                    beat_benchmark[hd] = beat

        # 按体系分组
        system_breakdown = {}
        for sys_name in set(p.system_name for p in picks):
            sys_picks = [p for p in picks if p.system_name == sys_name]
            if len(sys_picks) < 2:
                continue
            sys_stats = {}
            for hd in holding_days_list:
                rets = [p.forward_returns[hd] for p in sys_picks if p.forward_returns[hd] != 0]
                if rets:
                    sys_stats[hd] = {
                        'n_picks': len(rets),
                        'median_return': float(np.median(rets)),
                        'hit_10pct_rate': sum(1 for r in rets if r >= 10) / len(rets),
                    }
            system_breakdown[sys_name] = sys_stats

        return ValidationReport(
            n_dates=len(picks),
            holding_days_list=holding_days_list,
            picks=picks,
            aggregate=aggregate,
            system_breakdown=system_breakdown,
            beat_benchmark=beat_benchmark,
        )

    def format_report(self, report: ValidationReport) -> str:
        """格式化验证报告"""
        lines = []
        lines.append("=" * 80)
        lines.append("                  历史回测验证报告")
        lines.append("=" * 80)
        lines.append(f"  验证日期数: {report.n_dates}")
        lines.append(f"  持有期(天): {report.holding_days_list}")
        lines.append(f"  评估范围: 1996-01 ~ 2026-06 (30年A股数据)")
        lines.append("")

        # 聚合统计
        lines.append("【按持有期统计】")
        lines.append(f"  {'持有天数':<10} {'中位收益':>10} {'平均收益':>10} "
                    f"{'正收益%':>10} {'>10%概率':>10} {'最大':>8} {'最小':>8}")
        lines.append("  " + "-" * 76)
        for hd in report.holding_days_list:
            if hd in report.aggregate:
                s = report.aggregate[hd]
                lines.append(f"  {hd:<10} {s['median_return']:>+9.1f}% "
                           f"{s['mean_return']:>+9.1f}% "
                           f"{s['positive_rate']*100:>9.1f}% "
                           f"{s['hit_10pct_rate']*100:>9.1f}% "
                           f"{s['best']:>+7.1f}% {s['worst']:>+7.1f}%")
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

        # 详细记录(前10条)
        lines.append("【历史推荐明细(前10条)】")
        lines.append(f"  {'日期':<12} {'体制':<8} {'体系':<12} "
                    f"{'180天收益':>10} {'达标率':>8}")
        lines.append("  " + "-" * 60)
        for p in report.picks[:10]:
            hd = 180 if 180 in p.forward_returns else list(p.forward_returns.keys())[0]
            lines.append(f"  {p.pick_date:<12} {p.regime_cn:<8} {p.system_name:<12} "
                       f"{p.forward_returns[hd]:>+9.1f}% "
                       f"{p.hit_target_10pct[hd]*100:>7.1f}%")
        if len(report.picks) > 10:
            lines.append(f"  ... 共 {len(report.picks)} 条")
        lines.append("")

        # 关键结论
        lines.append("【关键结论】")
        if 180 in report.aggregate:
            s180 = report.aggregate[180]
            lines.append(f"  · 180天持有期中位收益 {s180['median_return']:+.1f}%")
            lines.append(f"  · 180天持有期达标率(>10%) {s180['hit_10pct_rate']:.1%}")
            target_met = s180['hit_10pct_rate'] >= 0.80
            lines.append(f"  · 目标80%达标率: {'✓ 达成' if target_met else '✗ 未达成'}")

        if report.beat_benchmark and 180 in report.beat_benchmark:
            beat = report.beat_benchmark[180]
            lines.append(f"  · 180天跑赢沪深300比例: {beat*100:.1f}%")

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

    args = parser.parse_args()

    holding_days = [int(x) for x in args.holding_days.split(',')]

    validator = HistoricalBacktestValidator(
        optimization_result_file=args.systems,
    )

    report = validator.validate(
        n_dates=args.n_dates,
        top_n=args.top,
        holding_days_list=holding_days,
    )

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
        'aggregate': report.aggregate,
        'beat_benchmark': report.beat_benchmark,
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
            }
            for p in report.picks
        ],
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] 结果已保存: {output_path}")


if __name__ == "__main__":
    main()