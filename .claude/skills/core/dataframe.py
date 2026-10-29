# -*- coding: utf-8 -*-
"""日线 DataFrame 列名标准化与派生列的单一真相源 (审计 M19)

背景 (审计 M19, 2026-10-29 复验):
- 日线列名标准化 (英文列 → 中文列) 的映射字典在 **5 个模块各写一遍**
  (`stock_data_fetcher` / `historical_data_manager` 个股 + 指数 /
  `long_term_selector` / `reversal_detector`), 且**内容已漂移**: 3 处含
  `成交额`、2 处不含 → 同一份数据经不同模块得到不同列集。
- "缺失时补 `涨跌幅`" 的 pct_change 块在 **6 处各写一遍**
  (`stock_data_fetcher` ×2 / `historical_data_manager` ×2 /
  `position_analyzer` / `data_cleaner`), 口径也不统一: 5 处不转数值、
  1 处 `to_numeric`; 5 处"缺失才补"、1 处无条件覆盖。

本模块是唯一实现, 各调用方只调函数, 不再自带映射/公式:
- `OHLCV_COLUMN_MAP`             英文 → 中文 列名映射 (7 列, 唯一真相源)
- `standardize_ohlcv_columns(df)` 重命名 (幂等; 缺失列自动跳过; 额外列保留)
- `change_pct(close, ...)`         收盘价百分比变化序列 (×100)
- `ensure_change_pct(df, ...)`    补 `涨跌幅` 列 (缺失才补; overwrite 才覆盖)
- `sort_by_date(df)`              日期列转 datetime + 按日期排序 + 重置索引
- `standardize_daily_frame(df)`   标准化 + 排序 + (可选) 补涨跌幅

口径约定:
- `涨跌幅` 单位为**百分比** (10.0 = +10%), 与 akshare 的 `涨跌幅` 一致
- 列名映射只覆盖 date/OHLCV/成交额; 其余列 (如 `outstanding_share`) 原样保留
- 缺 `日期` 列 → 抛 KeyError (各调用方自行决定记 WARN 还是失败)
- 全部函数**不原地改写入参** (返回新 frame), 避免调用方意外被改
"""
import pandas as pd

# 英文 → 中文 列名映射 (唯一真相源; 审计 M19)
# 注: `df.rename(columns=...)` 对不存在的列自动跳过 → 7 列统一映射对
# "接口不返回成交额" 的场景 (指数接口) 同样适用, 无需各写各的子集
OHLCV_COLUMN_MAP = {
    'date': '日期',
    'open': '开盘',
    'high': '最高',
    'low': '最低',
    'close': '收盘',
    'volume': '成交量',
    'amount': '成交额',
}

CHANGE_PCT_COLUMN = '涨跌幅'
DATE_COLUMN = '日期'
CLOSE_COLUMN = '收盘'


def standardize_ohlcv_columns(df: pd.DataFrame) -> pd.DataFrame:
    """按 `OHLCV_COLUMN_MAP` 重命名日线列 (英文 → 中文)。

    - 幂等: 已是中文名的列不受影响 (映射键都是英文, 不冲突)
    - 缺失列自动跳过 (指数接口无 `成交额` 也能用同一套映射)
    - 额外列 (如 `outstanding_share`) 原样保留
    """
    if df is None:
        return df
    return df.rename(columns=OHLCV_COLUMN_MAP)


def change_pct(close, *, coerce: bool = False) -> pd.Series:
    """收盘价的百分比变化序列 (`pct_change() * 100`)。

    `coerce=True` 时先 `to_numeric(errors='coerce')` —— CSV 读入的列可能是
    字符串, 不转数值会在 pct_change 时抛 TypeError。
    """
    series = pd.to_numeric(close, errors='coerce') if coerce else close
    return series.pct_change() * 100


def ensure_change_pct(df: pd.DataFrame, *, overwrite: bool = False,
                      coerce: bool = False) -> pd.DataFrame:
    """确保存在 `涨跌幅` 列 (百分比) = 收盘.pct_change()*100。

    - 缺 `收盘` 列 → 不动 (不臆造)
    - 已有 `涨跌幅` 且 `overwrite=False` → 保留原值 (不覆盖既有口径)
    - `overwrite=True` → 无条件重算 (仅当调用方明确要求以收盘口径为准)
    """
    if df is None or CLOSE_COLUMN not in df.columns:
        return df
    if CHANGE_PCT_COLUMN in df.columns and not overwrite:
        return df
    df[CHANGE_PCT_COLUMN] = change_pct(df[CLOSE_COLUMN], coerce=coerce)
    return df


def sort_by_date(df: pd.DataFrame) -> pd.DataFrame:
    """`日期` 列转 datetime + 按日期升序 + 重置索引。

    缺 `日期` 列 → 抛 KeyError (调用方据此记 WARN 或失败, 不静默跳过)。
    """
    if DATE_COLUMN not in df.columns:
        raise KeyError(f"日线数据缺 '{DATE_COLUMN}' 列 (标准化后仍无)")
    out = df.copy()
    out[DATE_COLUMN] = pd.to_datetime(out[DATE_COLUMN])
    return out.sort_values(DATE_COLUMN).reset_index(drop=True)


def standardize_daily_frame(df: pd.DataFrame, *, add_change: bool = True,
                             overwrite_change: bool = False,
                             coerce_change: bool = False) -> pd.DataFrame:
    """日线标准化一步到位: 列名 → 日期排序 → (可选) 补 `涨跌幅`。

    Args:
        df: 原始日线 frame (英文列或中文列均可)
        add_change: 是否补 `涨跌幅` 列 (默认补; 不需要的调用方传 False)
        overwrite_change: 已有 `涨跌幅` 时是否重算 (默认保留原值)
        coerce_change: 计算涨跌幅前是否把收盘价转数值 (CSV 路径需要)
    """
    out = standardize_ohlcv_columns(df)
    out = sort_by_date(out)
    if add_change:
        out = ensure_change_pct(out, overwrite=overwrite_change,
                                coerce=coerce_change)
    return out
