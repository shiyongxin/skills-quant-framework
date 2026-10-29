# -*- coding: utf-8 -*-
"""
指标体系报告生成器 - Indicator System Report Generator

将优化结果格式化为可读的指标体系报告，包含：
- 每套体系的名称、适用场景、参数、性能统计
- 使用说明和注意事项
- Markdown/HTML/纯文本格式输出

审计 H3 批次4 (副本治理): 本模块原先**只存在于 gitignored 的部署包
副本** (`optimization_package/.../skills/`) 里, 主链无源 → `pack.py`
打包时对它 [SKIP] → 打包产物缺报告生成器 (副本的 run_optimize.py 依赖
它出报告)。现并入主链作为**唯一真相源**, 打包时由 pack.py 自动收录。
"""

import json
from pathlib import Path
from datetime import datetime


# ==================== 参数名称映射 ====================

PARAM_NAMES = {
    'ma_fast': 'MA快线周期',
    'ma_slow': 'MA慢线周期',
    'ma_mid': 'MA中线周期',
    'macd_fast': 'MACD快线',
    'macd_slow': 'MACD慢线',
    'macd_signal': 'MACD信号线',
    'rsi_period': 'RSI周期',
    'rsi_oversold': 'RSI超卖阈值',
    'rsi_overbought': 'RSI超买阈值',
    'kdj_n': 'KDJ周期',
    'bb_period': '布林带周期',
    'bb_std': '布林带标准差倍数',
    'atr_period': 'ATR周期',
    'w_trend': '趋势权重(%)',
    'w_momentum': '动量权重(%)',
    'w_risk': '风险权重(%)',
    'w_performance': '近期表现权重(%)',
    'buy_threshold': '买入信号阈值',
    'sell_threshold': '卖出信号阈值',
    'score_buy_threshold': '综合评分买入阈值',
    'score_sell_threshold': '综合评分卖出阈值',
    'stop_loss_pct': '止损比例(%)',
    'take_profit_pct': '止盈比例(%)',
    'position_size_pct': '仓位比例(%)',
    'trailing_stop_pct': '追踪止损(%)',
}

REGIME_CN = {
    'BULL': '牛市',
    'BEAR': '熊市',
    'SIDEWAYS': '横盘震荡',
    'CRASH': '暴跌',
    'RECOVERY': '反弹',
    'GLOBAL': '全局通用',
    'ROBUST': '跨体制稳健',
    'ITERATIVE': '迭代优化',
}

# 体系使用建议模板
USAGE_ADVICE = {
    'BULL': [
        "优先选择趋势向上的行业龙头",
        "在大盘站稳60日均线后启用",
        "配合量能放大确认突破",
        "可适当放宽止损，让利润奔跑",
        "关注MACD金叉和均线多头排列",
    ],
    'BEAR': [
        "仅在极端超卖时介入",
        "控制仓位在30%以内",
        "快速止盈不贪心",
        "严格止损，亏损超过止损线立即离场",
        "关注RSI超卖和KDJ低位金叉",
    ],
    'SIDEWAYS': [
        "采用高抛低吸策略",
        "在布林带下轨附近买入，上轨附近卖出",
        "控制仓位在50%以内",
        "关注KDJ超买超卖信号",
        "避免追涨杀跌",
    ],
    'CRASH': [
        "空仓观望为主",
        "如必须操作，仓位控制在20%以内",
        "等待暴跌结束信号(5日跌幅收窄)",
        "关注超跌反弹机会",
        "严格止损，亏损3%即离场",
    ],
    'RECOVERY': [
        "关注超跌反弹的优质标的",
        "在放量突破短期均线时介入",
        "控制仓位在40%以内",
        "快进快出，不恋战",
        "关注成交量放大配合",
    ],
}


class IndicatorSystemReport:
    """指标体系报告生成器"""

    def __init__(self):
        self.systems = []
        self.metadata = {}

    def load(self, filepath):
        """加载优化结果"""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        self.systems = data.get('systems', [])
        self.metadata = {
            'timestamp': data.get('timestamp', ''),
            'file': str(filepath),
        }
        print(f"[OK] 加载 {len(self.systems)} 套指标体系")

    def load_from_engine(self, engine):
        """从OptimizationEngine加载结果"""
        self.systems = []
        for key, result in engine.results.items():
            sys = result.best_system
            self.systems.append({
                'name': sys.name,
                'description': sys.description,
                'applicable_regimes': sys.applicable_regimes,
                'params': sys.params,
                'fitness_scores': sys.fitness_scores,
                'confidence': sys.confidence,
                'median_return': sys.median_return,
                'win_rate_above_10pct': sys.win_rate_above_10pct,
                'median_sharpe': sys.median_sharpe,
                'median_max_drawdown': sys.median_max_drawdown,
                'median_holding_days': sys.median_holding_days,
                'num_trades': sys.num_trades,
                'sample_count': sys.sample_count,
                'regime': result.regime,
            })

    def generate_text_report(self) -> str:
        """生成纯文本格式报告"""
        lines = []
        lines.append("=" * 80)
        lines.append("                    技术分析指标体系优化报告")
        lines.append("=" * 80)
        lines.append(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"  体系数量: {len(self.systems)}")
        lines.append("")

        for i, sys_data in enumerate(self.systems, 1):
            lines.extend(self._format_system_text(sys_data, i))

        # 对比表
        if len(self.systems) > 1:
            lines.extend(self._format_comparison_table())

        # 使用指南
        lines.extend(self._format_usage_guide())

        lines.append("=" * 80)
        return "\n".join(lines)

    def generate_markdown_report(self) -> str:
        """生成Markdown格式报告"""
        lines = []
        lines.append("# 技术分析指标体系优化报告")
        lines.append("")
        lines.append(f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"- 体系数量: {len(self.systems)}")
        lines.append("")

        for i, sys_data in enumerate(self.systems, 1):
            lines.extend(self._format_system_markdown(sys_data, i))

        # 对比表
        if len(self.systems) > 1:
            lines.extend(self._comparison_markdown())

        lines.append("---")
        lines.append(f"*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        return "\n".join(lines)

    def _format_system_text(self, sys_data, idx) -> list:
        """格式化单套体系(纯文本)"""
        lines = []
        name = sys_data.get('name', f'体系{idx}')
        desc = sys_data.get('description', '')
        regimes = sys_data.get('applicable_regimes', [])
        params = sys_data.get('params', {})

        lines.append("-" * 80)
        lines.append(f"  指标体系 #{idx}: \"{name}\"")
        lines.append(f"  适用场景: {desc}")
        lines.append(f"  适用体制: {', '.join(REGIME_CN.get(r, r) for r in regimes)}")
        lines.append("-" * 80)
        lines.append("")

        # 性能统计
        lines.append("  【历史表现】")
        lines.append(f"    中位收益率: {sys_data.get('median_return', 0):+.1f}%")
        lines.append(f"    超10%收益概率: {sys_data.get('win_rate_above_10pct', 0):.1%}")
        lines.append(f"    中位夏普比: {sys_data.get('median_sharpe', 0):.2f}")
        lines.append(f"    中位最大回撤: {sys_data.get('median_max_drawdown', 0):.1f}%")
        lines.append(f"    平均持有天数: {sys_data.get('median_holding_days', 0):.0f}")
        lines.append(f"    平均交易次数: {sys_data.get('num_trades', 0):.0f}")
        lines.append(f"    置信度: {sys_data.get('confidence', 0):.0%}")
        lines.append(f"    样本数: {sys_data.get('sample_count', 0)}")
        lines.append("")

        # 参数
        lines.append("  【指标参数】")
        param_groups = self._group_params(params)
        for group_name, group_params in param_groups.items():
            lines.append(f"    {group_name}:")
            for k, v in group_params.items():
                cn_name = PARAM_NAMES.get(k, k)
                if isinstance(v, float):
                    lines.append(f"      {cn_name}: {v:.2f}")
                else:
                    lines.append(f"      {cn_name}: {v}")
        lines.append("")

        # 使用建议
        primary_regime = regimes[0] if regimes else 'SIDEWAYS'
        advice = USAGE_ADVICE.get(primary_regime, USAGE_ADVICE['SIDEWAYS'])
        lines.append("  【使用建议】")
        for a in advice:
            lines.append(f"    - {a}")
        lines.append("")

        return lines

    def _format_system_markdown(self, sys_data, idx) -> list:
        """格式化单套体系(Markdown)"""
        lines = []
        name = sys_data.get('name', f'体系{idx}')
        desc = sys_data.get('description', '')
        regimes = sys_data.get('applicable_regimes', [])
        params = sys_data.get('params', {})

        lines.append(f"## 指标体系 #{idx}: \"{name}\"")
        lines.append("")
        lines.append(f"**适用场景**: {desc}")
        lines.append(f"**适用体制**: {', '.join(REGIME_CN.get(r, r) for r in regimes)}")
        lines.append("")

        # 性能统计
        lines.append("### 历史表现")
        lines.append("")
        lines.append(f"| 指标 | 值 |")
        lines.append(f"|------|-----|")
        lines.append(f"| 中位收益率 | {sys_data.get('median_return', 0):+.1f}% |")
        lines.append(f"| 超10%收益概率 | {sys_data.get('win_rate_above_10pct', 0):.1%} |")
        lines.append(f"| 中位夏普比 | {sys_data.get('median_sharpe', 0):.2f} |")
        lines.append(f"| 中位最大回撤 | {sys_data.get('median_max_drawdown', 0):.1f}% |")
        lines.append(f"| 平均持有天数 | {sys_data.get('median_holding_days', 0):.0f} |")
        lines.append(f"| 置信度 | {sys_data.get('confidence', 0):.0%} |")
        lines.append("")

        # 参数
        lines.append("### 指标参数")
        lines.append("")
        lines.append("| 参数 | 值 |")
        lines.append("|------|-----|")
        for k, v in sorted(params.items()):
            cn_name = PARAM_NAMES.get(k, k)
            if isinstance(v, float):
                lines.append(f"| {cn_name} | {v:.2f} |")
            else:
                lines.append(f"| {cn_name} | {v} |")
        lines.append("")

        # 使用建议
        primary_regime = regimes[0] if regimes else 'SIDEWAYS'
        advice = USAGE_ADVICE.get(primary_regime, USAGE_ADVICE['SIDEWAYS'])
        lines.append("### 使用建议")
        lines.append("")
        for a in advice:
            lines.append(f"- {a}")
        lines.append("")

        return lines

    def _format_comparison_table(self) -> list:
        """对比表(纯文本)"""
        lines = []
        lines.append("=" * 80)
        lines.append("  指标体系对比")
        lines.append("=" * 80)
        lines.append("")

        header = f"  {'体系名称':<16} {'中位收益':>8} {'达标率':>8} {'夏普':>6} {'回撤':>8} {'持有天':>6}"
        lines.append(header)
        lines.append("  " + "-" * 58)

        for sys_data in self.systems:
            name = sys_data.get('name', '?')[:14]
            lines.append(
                f"  {name:<16} "
                f"{sys_data.get('median_return', 0):>+7.1f}% "
                f"{sys_data.get('win_rate_above_10pct', 0):>7.1%} "
                f"{sys_data.get('median_sharpe', 0):>6.2f} "
                f"{sys_data.get('median_max_drawdown', 0):>7.1f}% "
                f"{sys_data.get('median_holding_days', 0):>6.0f}"
            )
        lines.append("")
        return lines

    def _comparison_markdown(self) -> list:
        """对比表(Markdown)"""
        lines = []
        lines.append("## 指标体系对比")
        lines.append("")
        lines.append("| 体系名称 | 中位收益 | 达标率 | 夏普 | 回撤 | 持有天 |")
        lines.append("|----------|----------|--------|------|------|--------|")

        for sys_data in self.systems:
            name = sys_data.get('name', '?')
            lines.append(
                f"| {name} "
                f"| {sys_data.get('median_return', 0):+.1f}% "
                f"| {sys_data.get('win_rate_above_10pct', 0):.1%} "
                f"| {sys_data.get('median_sharpe', 0):.2f} "
                f"| {sys_data.get('median_max_drawdown', 0):.1f}% "
                f"| {sys_data.get('median_holding_days', 0):.0f} |"
            )
        lines.append("")
        return lines

    def _format_usage_guide(self) -> list:
        """使用指南"""
        lines = []
        lines.append("=" * 80)
        lines.append("  使用指南")
        lines.append("=" * 80)
        lines.append("")
        lines.append("  1. 首先判断当前大盘态势(牛市/熊市/震荡/暴跌/反弹)")
        lines.append("  2. 选择对应体制的指标体系")
        lines.append("  3. 用该体系的参数计算技术指标")
        lines.append("  4. 根据买入/卖出阈值生成信号")
        lines.append("  5. 结合使用建议决定操作")
        lines.append("")
        lines.append("  注意事项:")
        lines.append("  - 历史表现不代表未来收益，仅供参考")
        lines.append("  - 建议配合基本面分析使用")
        lines.append("  - 严格执行止损纪律")
        lines.append("  - 定期重新优化参数(建议每季度)")
        lines.append("")
        return lines

    def _group_params(self, params) -> dict:
        """将参数按组分类"""
        groups = {
            '移动平均线': {},
            'MACD': {},
            'RSI': {},
            'KDJ': {},
            '布林带': {},
            'ATR': {},
            '评分权重': {},
            '信号阈值': {},
            '仓位管理': {},
        }

        for k, v in params.items():
            if 'ma_' in k:
                groups['移动平均线'][k] = v
            elif 'macd' in k:
                groups['MACD'][k] = v
            elif 'rsi' in k:
                groups['RSI'][k] = v
            elif 'kdj' in k:
                groups['KDJ'][k] = v
            elif 'bb_' in k:
                groups['布林带'][k] = v
            elif 'atr' in k:
                groups['ATR'][k] = v
            elif k.startswith('w_'):
                groups['评分权重'][k] = v
            elif 'threshold' in k:
                groups['信号阈值'][k] = v
            elif 'stop' in k or 'profit' in k or 'position' in k:
                groups['仓位管理'][k] = v

        # 移除空组
        return {k: v for k, v in groups.items() if v}

    def save_text(self, filepath):
        """保存纯文本报告"""
        text = self.generate_text_report()
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f"[OK] 文本报告已保存: {filepath}")

    def save_markdown(self, filepath):
        """保存Markdown报告"""
        text = self.generate_markdown_report()
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f"[OK] Markdown报告已保存: {filepath}")

    def save_html(self, filepath):
        """保存HTML报告"""
        md_text = self.generate_markdown_report()
        # 简单的Markdown→HTML转换
        html = self._md_to_html(md_text)
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"[OK] HTML报告已保存: {filepath}")

    def _md_to_html(self, md_text) -> str:
        """简单的Markdown转HTML"""
        lines = md_text.split('\n')
        html_lines = []
        html_lines.append("<!DOCTYPE html>")
        html_lines.append("<html><head><meta charset='utf-8'>")
        html_lines.append("<title>指标体系优化报告</title>")
        html_lines.append("<style>")
        html_lines.append("body { font-family: 'Microsoft YaHei', sans-serif; "
                         "max-width: 900px; margin: 0 auto; padding: 20px; }")
        html_lines.append("table { border-collapse: collapse; width: 100%; "
                         "margin: 10px 0; }")
        html_lines.append("th, td { border: 1px solid #ddd; padding: 8px; "
                         "text-align: left; }")
        html_lines.append("th { background-color: #4CAF50; color: white; }")
        html_lines.append("tr:nth-child(even) { background-color: #f2f2f2; }")
        html_lines.append("h1 { color: #333; border-bottom: 2px solid #4CAF50; "
                         "padding-bottom: 10px; }")
        html_lines.append("h2 { color: #4CAF50; margin-top: 30px; }")
        html_lines.append("h3 { color: #666; }")
        html_lines.append(".positive { color: #4CAF50; }")
        html_lines.append(".negative { color: #f44336; }")
        html_lines.append("</style></head><body>")

        in_table = False
        for line in lines:
            if line.startswith('# '):
                html_lines.append(f"<h1>{line[2:]}</h1>")
            elif line.startswith('## '):
                html_lines.append(f"<h2>{line[3:]}</h2>")
            elif line.startswith('### '):
                html_lines.append(f"<h3>{line[4:]}</h3>")
            elif line.startswith('- '):
                html_lines.append(f"<li>{line[2:]}</li>")
            elif '|' in line and not in_table:
                in_table = True
                cells = [c.strip() for c in line.split('|')[1:-1]]
                html_lines.append("<table><tr>")
                for cell in cells:
                    html_lines.append(f"<th>{cell}</th>")
                html_lines.append("</tr>")
            elif '|' in line and in_table:
                if set(line.replace('|', '').strip()) <= {'-', ' ', ':'}:
                    continue  # skip separator
                cells = [c.strip() for c in line.split('|')[1:-1]]
                html_lines.append("<tr>")
                for cell in cells:
                    css = ""
                    if '%' in cell and cell.startswith('+'):
                        css = ' class="positive"'
                    elif '%' in cell and cell.startswith('-'):
                        css = ' class="negative"'
                    html_lines.append(f"<td{css}>{cell}</td>")
                html_lines.append("</tr>")
            elif in_table:
                in_table = False
                html_lines.append("</table>")
                if line.strip():
                    html_lines.append(f"<p>{line}</p>")
            elif line.startswith('---'):
                html_lines.append("<hr>")
            elif line.strip():
                html_lines.append(f"<p>{line}</p>")

        if in_table:
            html_lines.append("</table>")

        html_lines.append("</body></html>")
        return "\n".join(html_lines)


# ==================== CLI ====================

def main():
    import argparse

    parser = argparse.ArgumentParser(description='指标体系报告生成')
    parser.add_argument('--input', required=True, help='优化结果JSON文件')
    parser.add_argument('--format', choices=['text', 'markdown', 'html', 'all'],
                       default='all', help='输出格式')
    parser.add_argument('--output-dir', default='stock_data/reports',
                       help='输出目录')

    args = parser.parse_args()

    report = IndicatorSystemReport()
    report.load(args.input)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.format in ('text', 'all'):
        report.save_text(output_dir / "indicator_systems.txt")

    if args.format in ('markdown', 'all'):
        report.save_markdown(output_dir / "indicator_systems.md")

    if args.format in ('html', 'all'):
        report.save_html(output_dir / "indicator_systems.html")

    # 同时打印文本版
    if args.format == 'text' or args.format == 'all':
        print(report.generate_text_report())


if __name__ == "__main__":
    main()
