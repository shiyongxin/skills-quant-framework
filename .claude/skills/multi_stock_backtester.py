# -*- coding: utf-8 -*-
"""
多股票回测评估器 - Multi-Stock Backtester

跨多只股票评估指标体系的表现，提供分层抽样、跨截面聚合、
按市场体制分组分析等功能。
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime
import json

from vectorized_backtest import VectorizedBacktester, BacktestMetrics
from historical_data_manager import HistoricalDataManager


@dataclass
class StockEvalResult:
    """单只股票的评估结果"""
    symbol: str
    metrics: BacktestMetrics
    regime: str = "UNKNOWN"  # 该股票主要处于的体制


@dataclass
class AggregateStats:
    """聚合统计"""
    count: int
    # 收益率统计
    mean_return: float
    median_return: float
    p10_return: float       # 10分位
    p90_return: float       # 90分位
    std_return: float
    pct_positive: float     # 正收益率占比(%)
    pct_above_10: float     # 超10%收益占比(%)
    # 夏普比率统计
    mean_sharpe: float
    median_sharpe: float
    # 回撤统计
    mean_drawdown: float
    median_drawdown: float
    max_drawdown: float
    # 其他
    mean_win_rate: float
    mean_trades: float
    mean_holding_days: float
    mean_profit_factor: float


@dataclass
class EvaluationReport:
    """完整评估报告"""
    system_name: str
    params: dict
    overall: AggregateStats
    by_regime: dict          # {regime: AggregateStats}
    stock_results: list      # list[StockEvalResult]
    timestamp: str


class MultiStockBacktester:
    """
    多股票回测评估器

    功能:
    - 跨多只股票回测同一套参数
    - 跨截面聚合统计(均值/中位/分位数)
    - 按市场体制分组分析
    - 分层抽样(按板块/市值)
    """

    def __init__(self, data_dir="./stock_data"):
        self.data_manager = HistoricalDataManager(data_dir)
        self.backtester = VectorizedBacktester()

    def evaluate_system(self, params: dict, symbols: list = None,
                        n_stocks: int = 100, regime_labels: dict = None,
                        min_rows: int = 2000) -> EvaluationReport:
        """
        评估一套参数在多只股票上的表现

        Parameters:
        -----------
        params : dict
            参数字典
        symbols : list or None
            指定股票列表，None则自动选择
        n_stocks : int
            评估股票数
        regime_labels : dict or None
            {symbol: pd.Series} 体制标签
        min_rows : int
            最少数据行数

        Returns:
        --------
        EvaluationReport
        """
        # 获取股票池
        if symbols is None:
            symbols = self.data_manager.get_universe(min_rows=min_rows)

        if len(symbols) > n_stocks:
            import random
            symbols = random.sample(symbols, n_stocks)

        print(f"[INFO] 评估参数在 {len(symbols)} 只股票上的表现...")

        stock_results = []
        for i, sym in enumerate(symbols):
            data = self.data_manager.load(sym)
            if len(data) < 252:
                continue

            try:
                metrics = self.backtester.backtest(data, params)
                if metrics.num_trades > 0:
                    regime = self._get_dominant_regime(sym, regime_labels)
                    stock_results.append(StockEvalResult(
                        symbol=sym, metrics=metrics, regime=regime
                    ))
            except Exception:
                continue

            if (i + 1) % 20 == 0:
                print(f"  [{i+1}/{len(symbols)}] 已评估...")

        if not stock_results:
            print("[WARN] 无有效评估结果")
            return None

        # 聚合统计
        overall = self._aggregate([r.metrics for r in stock_results])

        # 按体制分组
        by_regime = {}
        if regime_labels:
            regime_groups = {}
            for r in stock_results:
                if r.regime not in regime_groups:
                    regime_groups[r.regime] = []
                regime_groups[r.regime].append(r.metrics)

            for regime, metrics_list in regime_groups.items():
                if len(metrics_list) >= 5:
                    by_regime[regime] = self._aggregate(metrics_list)

        report = EvaluationReport(
            system_name=params.get('_name', 'unnamed'),
            params=params,
            overall=overall,
            by_regime=by_regime,
            stock_results=stock_results,
            timestamp=datetime.now().isoformat(),
        )

        print(f"[OK] 评估完成: {len(stock_results)} 只有效")
        return report

    def compare_systems(self, systems: list, symbols: list = None,
                        n_stocks: int = 100,
                        regime_labels: dict = None) -> pd.DataFrame:
        """
        对比多套参数体系

        Parameters:
        -----------
        systems : list[dict]
            参数字典列表，每个需包含 '_name' 键

        Returns:
        --------
        pd.DataFrame : 对比表格
        """
        reports = []
        for system in systems:
            report = self.evaluate_system(
                system, symbols, n_stocks, regime_labels
            )
            if report:
                reports.append(report)

        if not reports:
            return pd.DataFrame()

        # 构建对比表
        rows = []
        for report in reports:
            s = report.overall
            row = {
                '体系名称': report.system_name,
                '样本数': s.count,
                '中位收益率%': s.median_return,
                '平均收益率%': s.mean_return,
                '正收益率%': s.pct_positive,
                '超10%占比%': s.pct_above_10,
                '中位夏普': s.median_sharpe,
                '中位回撤%': s.median_drawdown,
                '最大回撤%': s.max_drawdown,
                '平均胜率%': s.mean_win_rate,
                '平均交易次数': s.mean_trades,
                '平均持有天数': s.mean_holding_days,
            }
            rows.append(row)

        df = pd.DataFrame(rows)
        return df

    def _aggregate(self, metrics_list: list) -> AggregateStats:
        """计算聚合统计"""
        returns = [m.total_return for m in metrics_list]
        sharpes = [m.sharpe_ratio for m in metrics_list]
        drawdowns = [m.max_drawdown for m in metrics_list]
        win_rates = [m.win_rate for m in metrics_list]
        trades = [m.num_trades for m in metrics_list]
        holding_days = [m.avg_holding_days for m in metrics_list]
        profit_factors = [m.profit_factor for m in metrics_list]

        return AggregateStats(
            count=len(metrics_list),
            mean_return=np.mean(returns),
            median_return=np.median(returns),
            p10_return=np.percentile(returns, 10),
            p90_return=np.percentile(returns, 90),
            std_return=np.std(returns),
            pct_positive=sum(1 for r in returns if r > 0) / len(returns) * 100,
            pct_above_10=sum(1 for r in returns if r >= 10) / len(returns) * 100,
            mean_sharpe=np.mean(sharpes),
            median_sharpe=np.median(sharpes),
            mean_drawdown=np.mean(drawdowns),
            median_drawdown=np.median(drawdowns),
            max_drawdown=max(drawdowns),
            mean_win_rate=np.mean(win_rates),
            mean_trades=np.mean(trades),
            mean_holding_days=np.mean(holding_days),
            mean_profit_factor=np.mean(profit_factors),
        )

    def _get_dominant_regime(self, symbol, regime_labels):
        """获取股票主要处于的体制"""
        if regime_labels and symbol in regime_labels:
            labels = regime_labels[symbol]
            return labels.value_counts().index[0] if len(labels) > 0 else "UNKNOWN"
        return "UNKNOWN"

    def format_report(self, report: EvaluationReport) -> str:
        """格式化评估报告"""
        lines = []
        lines.append("=" * 70)
        lines.append(f"  多股票回测评估报告: {report.system_name}")
        lines.append("=" * 70)
        lines.append(f"  评估时间: {report.timestamp}")
        lines.append(f"  有效样本: {report.overall.count} 只股票")
        lines.append("")

        # 总体统计
        s = report.overall
        lines.append("【总体统计】")
        lines.append(f"  收益率: 中位={s.median_return:.1f}%  "
                     f"均值={s.mean_return:.1f}%  "
                     f"P10={s.p10_return:.1f}%  P90={s.p90_return:.1f}%")
        lines.append(f"  正收益率占比: {s.pct_positive:.1f}%")
        lines.append(f"  超10%收益占比: {s.pct_above_10:.1f}%")
        lines.append(f"  夏普比率: 中位={s.median_sharpe:.2f}  "
                     f"均值={s.mean_sharpe:.2f}")
        lines.append(f"  最大回撤: 中位={s.median_drawdown:.1f}%  "
                     f"最大={s.max_drawdown:.1f}%")
        lines.append(f"  胜率: {s.mean_win_rate:.1f}%")
        lines.append(f"  平均交易次数: {s.mean_trades:.1f}")
        lines.append(f"  平均持有天数: {s.mean_holding_days:.0f}")
        lines.append("")

        # 按体制分组
        if report.by_regime:
            lines.append("【按市场体制分组】")
            regime_names = {
                'BULL': '牛市', 'BEAR': '熊市', 'SIDEWAYS': '震荡',
                'CRASH': '暴跌', 'RECOVERY': '反弹'
            }
            for regime, stats in sorted(report.by_regime.items()):
                name = regime_names.get(regime, regime)
                lines.append(f"  {name} ({stats.count}只):")
                lines.append(f"    中位收益={stats.median_return:.1f}%  "
                             f"达标率={stats.pct_above_10:.1f}%  "
                             f"夏普={stats.median_sharpe:.2f}  "
                             f"回撤={stats.median_drawdown:.1f}%")
            lines.append("")

        # TOP/BOTTOM 5
        sorted_results = sorted(report.stock_results,
                               key=lambda r: r.metrics.total_return, reverse=True)
        lines.append("【收益TOP5】")
        for r in sorted_results[:5]:
            lines.append(f"  {r.symbol}: {r.metrics.total_return:+.1f}% "
                        f"(夏普={r.metrics.sharpe_ratio:.2f}, "
                        f"回撤={r.metrics.max_drawdown:.1f}%)")
        lines.append("")
        lines.append("【收益BOTTOM5】")
        for r in sorted_results[-5:]:
            lines.append(f"  {r.symbol}: {r.metrics.total_return:+.1f}% "
                        f"(夏普={r.metrics.sharpe_ratio:.2f}, "
                        f"回撤={r.metrics.max_drawdown:.1f}%)")

        lines.append("")
        lines.append("=" * 70)
        return "\n".join(lines)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='多股票回测评估')
    parser.add_argument('--params-file', required=True,
                       help='参数JSON文件(优化结果)')
    parser.add_argument('--n-stocks', type=int, default=100,
                       help='评估股票数')
    parser.add_argument('--regime-labels',
                       default='stock_data/regime_labels.csv',
                       help='体制标签文件')

    args = parser.parse_args()

    # 加载参数
    with open(args.params_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    backtester = MultiStockBacktester()

    # 加载体制标签
    regime_labels = None
    if Path(args.regime_labels).exists():
        # 简单加载，实际需要按股票分配
        print(f"[INFO] 体制标签: {args.regime_labels}")

    # 评估每套体系
    systems = []
    for sys_data in data.get('systems', []):
        params = sys_data['params']
        params['_name'] = sys_data['name']
        systems.append(params)

    for params in systems:
        report = backtester.evaluate_system(
            params, n_stocks=args.n_stocks
        )
        if report:
            print(backtester.format_report(report))


if __name__ == "__main__":
    main()
