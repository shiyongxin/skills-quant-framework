# -*- coding: utf-8 -*-
"""存量历史数据清洗工具（审计 P0-4: 单位统一 + 复权维度化 + 存量数据清洗）。

背景（A 报告 R4/P0-4）:
    落库主路径 `ak.stock_zh_a_daily` 成交量单位=**股**、成交额单位=**元**、
    复权=**不复权**；而备用路径 `ak.stock_zh_a_hist` 成交量单位=**手**、
    复权默认曾为 **qfq**。同一份落库数据可能混入不同单位/不同复权口径的片段:
      - 成交量差 100 倍 → 换手率/量能因子全错
      - 成交额差 1e4 倍 → 流动性/ADV 判断全错
      - 复权混用 → 除权日虚假跳空, 收益率与全部指标失真

本工具做三件事（只做**可判定**的事, 不可判定的如实报"疑似"）:
    1. 单位判定与归一: 用 `成交额/成交量 ≈ 收盘价` 的中位数比值反推单位
       (比值≈1 → 元/股; ≈100 → 成交量是手; ≈1e-4 → 成交额是万元;
       ≈1e-2 → 两者同时错)
    2. 结构清洗: 列名标准化 / 日期 dtype / 排序 / 重复日期去重 /
       缺失涨跌幅补算
    3. 复权体检: 单日异常跳空 (疑似除权日) 只**标记不改写** ——
       没有除权因子就无法还原, 正确做法是按复权口径重新取数
       (复权维度已落库, 见 HistoricalDataManager)

用法:
    python .claude/skills/data_cleaner.py --data-dir stock_data          # 体检
    python .claude/skills/data_cleaner.py --data-dir stock_data --apply   # 落盘
"""
import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

COLUMN_ALIASES = {
    'date': '日期', 'open': '开盘', 'high': '最高', 'low': '最低',
    'close': '收盘', 'volume': '成交量', 'amount': '成交额',
    '日期时间': '日期', '股票代码': '代码',
}

# 单位判定阈值 (比值 = median(成交额/成交量) / median(收盘))
#   成交量单位=股 且 成交额单位=元 → 比值 ≈ 1
#   成交量单位=手 (1手=100股)   → 成交额/手数 = 100×价格 → 比值 ≈ 100
#   成交额单位=万元              → 成交额(万)/股数 = 价格/1e4 → 比值 ≈ 1e-4
#   两者同时错 (手 + 万元)      → 比值 ≈ 1e-2
_RATIO_OK = (0.5, 2.0)          # 成交额=元, 成交量=股
_RATIO_LOTS = (50.0, 200.0)     # 成交量=手 (×100)
_RATIO_WAN = (0.00005, 0.0002)  # 成交额=万元 (×1e4)
_RATIO_LOTS_WAN = (0.005, 0.02)  # 成交量=手 且 成交额=万元

# 单日涨跌幅绝对值超过该值 → 疑似除权/复权跳空 (A 股日内涨跌停 10/20%)
_SUSPICIOUS_JUMP_PCT = 20.0


def detect_units(df: pd.DataFrame) -> Dict[str, object]:
    """判定成交量/成交额单位。

    依据: 成交额(元) / 成交量(股) ≈ 成交均价 ≈ 收盘价。
    比值落在不同数量级即对应不同单位组合。

    Returns:
        {'volume_unit': 'shares'|'lots'|'unknown',
         'amount_unit': 'yuan'|'wan_yuan'|'unknown',
         'ratio': float|None, 'ratio_source': str}
    """
    if df is None or len(df) == 0:
        return {'volume_unit': 'unknown', 'amount_unit': 'unknown',
                'ratio': None, 'ratio_source': 'empty'}
    if not {'成交额', '成交量', '收盘'}.issubset(df.columns):
        return {'volume_unit': 'unknown', 'amount_unit': 'unknown',
                'ratio': None, 'ratio_source': 'missing_columns'}

    amount = pd.to_numeric(df['成交额'], errors='coerce')
    volume = pd.to_numeric(df['成交量'], errors='coerce')
    close = pd.to_numeric(df['收盘'], errors='coerce')
    mask = amount.notna() & volume.notna() & close.notna() & (volume > 0)
    if mask.sum() < 5:
        return {'volume_unit': 'unknown', 'amount_unit': 'unknown',
                'ratio': None, 'ratio_source': 'too_few_rows'}
    ratio = (amount[mask] / volume[mask] / close[mask]).median()
    if not np.isfinite(ratio) or ratio <= 0:
        return {'volume_unit': 'unknown', 'amount_unit': 'unknown',
                'ratio': None, 'ratio_source': 'non_finite'}

    if _RATIO_LOTS[0] <= ratio <= _RATIO_LOTS[1]:
        return {'volume_unit': 'lots', 'amount_unit': 'yuan',
                'ratio': float(ratio), 'ratio_source': 'median'}
    if _RATIO_WAN[0] <= ratio <= _RATIO_WAN[1]:
        return {'volume_unit': 'shares', 'amount_unit': 'wan_yuan',
                'ratio': float(ratio), 'ratio_source': 'median'}
    if _RATIO_LOTS_WAN[0] <= ratio <= _RATIO_LOTS_WAN[1]:
        return {'volume_unit': 'lots', 'amount_unit': 'wan_yuan',
                'ratio': float(ratio), 'ratio_source': 'median'}
    if _RATIO_OK[0] <= ratio <= _RATIO_OK[1]:
        return {'volume_unit': 'shares', 'amount_unit': 'yuan',
                'ratio': float(ratio), 'ratio_source': 'median'}
    return {'volume_unit': 'unknown', 'amount_unit': 'unknown',
            'ratio': float(ratio), 'ratio_source': 'out_of_range'}


def find_suspicious_jumps(df: pd.DataFrame) -> List[Dict[str, object]]:
    """疑似除权/复权跳空的 bar (只标记, 不改写)。

    没有除权因子就无法还原价格 —— 正确处置是按复权口径重新取数
    (复权维度已进落库文件名/元数据)。
    """
    if df is None or len(df) == 0 or '收盘' not in df.columns:
        return []
    close = pd.to_numeric(df['收盘'], errors='coerce')
    if '日期' in df.columns:
        dates = df['日期']
    else:
        dates = pd.Series(df.index, index=df.index)
    ret = close.pct_change() * 100
    out = []
    for i in ret.index:
        val = ret.loc[i]
        if pd.notna(val) and abs(val) > _SUSPICIOUS_JUMP_PCT:
            out.append({'date': str(dates.loc[i]), 'pct': round(float(val), 2)})
    return out


def clean_ohlcv_frame(df: pd.DataFrame, adjust: str = ''
                      ) -> Tuple[pd.DataFrame, Dict[str, object]]:
    """清洗单个 OHLCV 表 (结构 + 单位), 复权异常只标记。

    Args:
        df: 原始表
        adjust: 该文件的复权口径 (''=不复权) — 仅记录, 不改写价格

    Returns:
        (清洗后的 DataFrame, 报告 dict)
    """
    report: Dict[str, object] = {
        'adjust': adjust or '',
        'rows_in': int(len(df)) if df is not None else 0,
        'rows_out': 0,
        'actions': [],
        'warnings': [],
    }
    if df is None or len(df) == 0:
        report['warnings'].append('空表, 跳过')
        return df, report

    out = df.copy()
    renamed = {}
    for col in list(out.columns):
        std = COLUMN_ALIASES.get(str(col))
        if std and std != col:
            renamed[col] = std
    if renamed:
        out = out.rename(columns=renamed)
        report['actions'].append(f'列名标准化: {renamed}')

    if '日期' in out.columns:
        out['日期'] = pd.to_datetime(out['日期'], errors='coerce')
        out = out.dropna(subset=['日期'])
        out = out.sort_values('日期').reset_index(drop=True)
        before = len(out)
        out = out.drop_duplicates(subset=['日期'], keep='last')
        if len(out) != before:
            report['actions'].append(f'重复日期去重: -{before - len(out)} 行')

    units = detect_units(out)
    report['units_detected'] = units
    if units['volume_unit'] == 'lots':
        out['成交量'] = pd.to_numeric(out['成交量'], errors='coerce') * 100
        report['actions'].append('成交量单位 手→股 (×100)')
    if units['amount_unit'] == 'wan_yuan':
        out['成交额'] = pd.to_numeric(out['成交额'], errors='coerce') * 10000
        report['actions'].append('成交额单位 万元→元 (×10000)')

    if '收盘' in out.columns and '涨跌幅' not in out.columns:
        out['涨跌幅'] = pd.to_numeric(out['收盘'], errors='coerce').pct_change() * 100
        report['actions'].append('补算 涨跌幅 列')

    jumps = find_suspicious_jumps(out)
    if jumps:
        report['warnings'].append(
            f'疑似除权/复权跳空 {len(jumps)} 处 (单日涨跌幅 > '
            f'{_SUSPICIOUS_JUMP_PCT:.0f}%): {jumps[:5]}'
            + (' …' if len(jumps) > 5 else ''))
        report['warnings'].append(
            '除权因子本地不可得, 不改写价格; 请按复权口径重新取数 '
            '(adjust 已进落库维度)')

    report['rows_out'] = int(len(out))
    return out, report


def scan_directory(data_dir: str = './stock_data', dry_run: bool = True
                   ) -> List[Dict[str, object]]:
    """扫描历史数据目录并 (可选) 落盘清洗结果。

    Args:
        data_dir: 数据根目录 (含 historical/ 子目录)
        dry_run: True = 只体检不写盘

    Returns:
        每个文件的报告列表
    """
    hist_dir = Path(data_dir) / 'historical'
    if not hist_dir.exists():
        return []
    reports: List[Dict[str, object]] = []
    for path in sorted(hist_dir.glob('*.parquet')):
        try:
            df = pd.read_parquet(path)
        except Exception as e:
            reports.append({'file': path.name, 'error': str(e)[:120]})
            continue
        adjust = ''
        stem = path.stem
        if '_' in stem:
            tail = stem.rsplit('_', 1)[-1]
            if tail in ('qfq', 'hfq'):
                adjust = tail
        cleaned, report = clean_ohlcv_frame(df, adjust=adjust)
        report['file'] = path.name
        report['path'] = str(path)
        if not dry_run and report.get('actions'):
            try:
                cleaned.to_parquet(path, engine='pyarrow',
                                   compression='snappy', index=False)
                report['written'] = True
            except Exception as e:
                report['written'] = False
                report['write_error'] = str(e)[:120]
        reports.append(report)
    return reports


def main():
    parser = argparse.ArgumentParser(
        description='历史数据体检/清洗 (单位归一 + 结构清洗 + 复权异常标记)')
    parser.add_argument('--data-dir', default='./stock_data',
                        help='数据根目录 (默认 ./stock_data)')
    parser.add_argument('--apply', action='store_true',
                        help='落盘清洗结果 (默认只体检)')
    parser.add_argument('--json', action='store_true', help='以 JSON 输出')
    args = parser.parse_args()

    reports = scan_directory(args.data_dir, dry_run=not args.apply)
    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2, default=str))
        return
    if not reports:
        print(f"[INFO] {args.data_dir}/historical 无 parquet 文件")
        return
    for r in reports:
        if 'error' in r:
            print(f"[SKIP] {r['file']}: {r['error']}")
            continue
        acts = r.get('actions') or []
        warns = r.get('warnings') or []
        print(f"[{r['file']}] rows {r['rows_in']}→{r['rows_out']} "
              f"adjust={r.get('adjust') or 'raw'} "
              f"units={(r.get('units_detected') or {}).get('volume_unit')}"
              f"/{(r.get('units_detected') or {}).get('amount_unit')}")
        for a in acts:
            print(f"    - {a}")
        for w in warns:
            print(f"    ! {w}")
    print(f"[OK] 体检 {len(reports)} 个文件"
          + ('(未落盘, 加 --apply 落盘)' if not args.apply else '(已落盘)'))


if __name__ == '__main__':
    main()
