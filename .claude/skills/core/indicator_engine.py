# -*- coding: utf-8 -*-
"""共享技术指标引擎（审计路线图项 21 / 审计 C #10）。

背景: 收敛前全仓有 11 处独立 MACD 实现、8 处 KDJ、6 处 BOLL，且同名列
（K/D/J、MACD/MACD_Hist、BB_Middle）口径分裂——`reversal_*` 用
`ewm(adjust=True)`，其余 10+ 站点用 `adjust=False`（递归 EMA），同名不同值。

本模块提供两层:
1. `core/indicators.py` — 纯函数层（数值真相源，bitwise 唯一实现）。
2. 本文件 `IndicatorEngine` — 批量计算层: 统一产出**规范列名**的指标表，
   并提供"规范名 → 各模块历史列名"的映射，使各业务模块零数值变化地
   切换到共享实现（列名契约保留在各模块自己的历史口径上）。

规范列名（canonical）:
    MA{period} / EMA{period} / DIF / DEA / HIST / RSI / K / D / J /
    BB_Upper / BB_Middle / BB_Lower / BB_Std / TR / ATR / Vol_MA{period} /
    VWAP / OBV

用法::

    eng = IndicatorEngine(df)                     # df 含 收盘/最高/最低/成交量
    df['MACD'], df['MACD_Signal'] = eng.macd_named('MACD', 'MACD_Signal')
"""
from typing import Dict, Iterable, List, Optional, Sequence

import pandas as pd

from .indicators import (atr as _atr, bollinger as _bollinger, ema as _ema,
                         kdj as _kdj, macd as _macd, obv as _obv, rsi as _rsi,
                         sma as _sma, true_range as _true_range,
                         volume_ma as _volume_ma, vwap as _vwap)

CANONICAL_COLUMNS = (
    'DIF', 'DEA', 'HIST', 'RSI', 'K', 'D', 'J',
    'BB_Upper', 'BB_Middle', 'BB_Lower', 'BB_Std',
    'TR', 'ATR', 'VWAP', 'OBV',
)

# 各模块历史列名 → 规范列名（反向查表用：判断某模块产出是否等价于规范口径）
LEGACY_COLUMN_ALIASES: Dict[str, str] = {
    # MACD
    'MACD': 'DIF', 'macd': 'DIF',
    'MACD_Signal': 'DEA', 'macd_signal': 'DEA',
    'MACD_Hist': 'HIST', 'macd_hist': 'HIST',
    # 布林带
    'BB_Middle': 'BB_Middle', 'BB_Mid': 'BB_Middle',
    'bb_middle': 'BB_Middle', 'bb_mid': 'BB_Middle',
    'BB_Std': 'BB_Std', 'bb_std': 'BB_Std',
    'BB_Upper': 'BB_Upper', 'BB_Lower': 'BB_Lower',
    'bb_upper': 'BB_Upper', 'bb_lower': 'BB_Lower',
    # 量均线
    'Vol_MA5': 'Vol_MA5', 'vol_ma5': 'Vol_MA5', 'volume_ma5': 'Vol_MA5',
    'VOL_MA5': 'Vol_MA5',
    'Vol_MA20': 'Vol_MA20', 'vol_ma20': 'Vol_MA20',
    'volume_ma20': 'Vol_MA20',
    # RSI
    'RSI': 'RSI', 'rsi': 'RSI',
}

# 规范列名 → 默认历史列名（各模块按需覆盖）
DEFAULT_LEGACY_NAMES: Dict[str, str] = {
    'DIF': 'MACD',
    'DEA': 'MACD_Signal',
    'HIST': 'MACD_Hist',
    'BB_Middle': 'BB_Middle',
    'BB_Std': 'BB_Std',
    'BB_Upper': 'BB_Upper',
    'BB_Lower': 'BB_Lower',
    'Vol_MA5': 'Vol_MA5',
    'Vol_MA20': 'Vol_MA20',
    'RSI': 'RSI',
}


class IndicatorEngine:
    """共享技术指标引擎（数值全部来自 `core.indicators`）。

    只做"取哪段、叫什么名"的事，公式一律不在本类内出现。
    """

    def __init__(self, df: pd.DataFrame,
                 close_col: str = '收盘', high_col: str = '最高',
                 low_col: str = '最低', volume_col: str = '成交量'):
        self.df = df
        self.close_col = close_col
        self.high_col = high_col
        self.low_col = low_col
        self.volume_col = volume_col

    # ---------- 列访问（缺列时给出明确错误，不静默造 0） ----------

    def _col(self, name: str) -> pd.Series:
        if name not in self.df.columns:
            raise KeyError(
                f"IndicatorEngine 缺少列 '{name}'; 现有列: "
                f"{list(self.df.columns)[:12]}...")
        return self.df[name]

    @property
    def close(self) -> pd.Series:
        return self._col(self.close_col)

    @property
    def high(self) -> pd.Series:
        return self._col(self.high_col)

    @property
    def low(self) -> pd.Series:
        return self._col(self.low_col)

    @property
    def volume(self) -> pd.Series:
        return self._col(self.volume_col)

    # ---------- 单指标 ----------

    def ma(self, period: int) -> pd.Series:
        return _sma(self.close, period)

    def ema(self, period: int) -> pd.Series:
        return _ema(self.close, period)

    def rsi(self, period: int = 14) -> pd.Series:
        return _rsi(self.close, period)

    def macd(self, fast: int = 12, slow: int = 26, signal: int = 9):
        """→ (dif, dea, hist)"""
        return _macd(self.close, fast, slow, signal)

    def kdj(self, n: int = 9, k_period: int = 3, d_period: int = 3):
        """→ (k, d, j)"""
        return _kdj(self.high, self.low, self.close, n, k_period, d_period)

    def bollinger(self, period: int = 20, std_mult: float = 2.0):
        """→ (upper, middle, lower, std)"""
        return _bollinger(self.close, period, std_mult)

    def true_range(self) -> pd.Series:
        return _true_range(self.high, self.low, self.close)

    def atr(self, period: int = 14) -> pd.Series:
        return _atr(self.high, self.low, self.close, period)

    def volume_ma(self, period: int) -> pd.Series:
        return _volume_ma(self.volume, period)

    def obv(self) -> pd.Series:
        return _obv(self.close, self.volume)

    def vwap(self) -> pd.Series:
        return _vwap(self.high, self.low, self.close, self.volume)

    # ---------- 批量 / 列名映射 ----------

    def compute(self, ma_periods: Sequence[int] = (5, 10, 20, 60),
                ema_periods: Sequence[int] = (20, 50),
                macd_params: Optional[dict] = None,
                kdj_params: Optional[dict] = None,
                bb_params: Optional[dict] = None,
                rsi_period: Optional[int] = None,
                atr_period: Optional[int] = None,
                vol_ma_periods: Sequence[int] = (5, 20),
                with_vwap: bool = False,
                with_obv: bool = False) -> pd.DataFrame:
        """批量计算 → 规范列名 DataFrame（与入参同 index）。"""
        out = pd.DataFrame(index=self.df.index)
        for p in ma_periods or ():
            out[f'MA{p}'] = self.ma(p)
        for p in ema_periods or ():
            out[f'EMA{p}'] = self.ema(p)
        mp = dict(fast=12, slow=26, signal=9)
        mp.update(macd_params or {})
        dif, dea, hist = self.macd(mp['fast'], mp['slow'], mp['signal'])
        out['DIF'], out['DEA'], out['HIST'] = dif, dea, hist
        kp = dict(n=9, k_period=3, d_period=3)
        kp.update(kdj_params or {})
        k, d, j = self.kdj(kp['n'], kp['k_period'], kp['d_period'])
        out['K'], out['D'], out['J'] = k, d, j
        bp = dict(period=20, std_mult=2.0)
        bp.update(bb_params or {})
        upper, middle, lower, std = self.bollinger(bp['period'],
                                                    bp['std_mult'])
        out['BB_Upper'], out['BB_Middle'] = upper, middle
        out['BB_Lower'], out['BB_Std'] = lower, std
        if rsi_period:
            out['RSI'] = self.rsi(rsi_period)
        if atr_period:
            out['TR'] = self.true_range()
            out['ATR'] = self.atr(atr_period)
        for p in vol_ma_periods or ():
            out[f'Vol_MA{p}'] = self.volume_ma(p)
        if with_vwap:
            out['VWAP'] = self.vwap()
        if with_obv:
            out['OBV'] = self.obv()
        return out

    @staticmethod
    def to_legacy(df: pd.DataFrame,
                  mapping: Optional[Dict[str, str]] = None) -> pd.DataFrame:
        """规范列名 → 历史列名（rename，不改数值）。

        Args:
            df: 规范列名的指标表
            mapping: {规范列名: 历史列名}；默认用 `DEFAULT_LEGACY_NAMES`
                （各业务模块按自己的历史列名契约覆盖即可）
        """
        rename = mapping if mapping is not None else DEFAULT_LEGACY_NAMES
        applied = {canonical: legacy for canonical, legacy in rename.items()
                   if canonical in df.columns and legacy not in df.columns}
        return df.rename(columns=applied)

    @staticmethod
    def to_canonical(df: pd.DataFrame) -> pd.DataFrame:
        """历史列名 → 规范列名（用于比对"某模块产出是否等价于共享口径"）。"""
        applied = {legacy: canonical
                   for legacy, canonical in LEGACY_COLUMN_ALIASES.items()
                   if legacy in df.columns and canonical not in df.columns}
        return df.rename(columns=applied)

    def attach(self, df: pd.DataFrame, columns: Dict[str, pd.Series],
               ) -> pd.DataFrame:
        """把指标列写回业务 DataFrame（原地返回同一对象）。"""
        for name, series in columns.items():
            df[name] = series
        return df


def indicator_columns(engine: IndicatorEngine,
                      ma_periods: Iterable[int] = (),
                      ema_periods: Iterable[int] = (),
                      macd: bool = True,
                      kdj: bool = True,
                      bollinger: bool = True,
                      rsi_period: Optional[int] = None,
                      atr_period: Optional[int] = None,
                      vol_ma_periods: Iterable[int] = (),
                      ) -> Dict[str, pd.Series]:
    """便捷函数: 按需返回 {列名: Series}（规范列名）。"""
    cols: Dict[str, pd.Series] = {}
    for p in ma_periods:
        cols[f'MA{p}'] = engine.ma(p)
    for p in ema_periods:
        cols[f'EMA{p}'] = engine.ema(p)
    if macd:
        dif, dea, hist = engine.macd()
        cols['DIF'], cols['DEA'], cols['HIST'] = dif, dea, hist
    if kdj:
        k, d, j = engine.kdj()
        cols['K'], cols['D'], cols['J'] = k, d, j
    if bollinger:
        upper, middle, lower, std = engine.bollinger()
        cols['BB_Upper'], cols['BB_Middle'] = upper, middle
        cols['BB_Lower'], cols['BB_Std'] = lower, std
    if rsi_period:
        cols['RSI'] = engine.rsi(rsi_period)
    if atr_period:
        cols['TR'] = engine.true_range()
        cols['ATR'] = engine.atr(atr_period)
    for p in vol_ma_periods:
        cols[f'Vol_MA{p}'] = engine.volume_ma(p)
    return cols


__all__ = ['CANONICAL_COLUMNS', 'DEFAULT_LEGACY_NAMES',
           'LEGACY_COLUMN_ALIASES', 'IndicatorEngine', 'indicator_columns']
