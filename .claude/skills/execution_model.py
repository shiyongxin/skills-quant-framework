# -*- coding: utf-8 -*-
"""
执行模型 - A股回测撮合与交易成本
Execution Model: fill timing, A-share costs, limit rules

全回测引擎共用（backtest_framework / vectorized_backtest /
reversal_backtest / historical_backtest_validator / multi_stock_backtester）。

设计要点:
- t+1 撮合: 信号在 bar t 收盘生成 → 订单在 bar t+1 开盘成交（杜绝同根 bar 未来函数）
- 成本: 佣金万三（每笔最低 5 元）+ 卖出印花税 0.05% + 过户费 0.001% 双边 + 滑点
- 涨跌停: 开盘价触及涨/跌停 → 该方向不可成交；一字板日内同样拦截
- 停牌: 数据侧无停牌标记（停牌日无行）。兜底 = 自然日持仓天数
  + 复牌日开盘涨跌停检查（不虚构交易日历）

适用范围: 主板 ±10%、创业板/科创板（代码前缀 30/68）±20%。
ST 股 ±5% 未建模（数据侧无 ST 标记），调用方可传 is_st=True 启用。
"""

from dataclasses import dataclass
from typing import Optional, Union

LIMIT_PCT_MAIN = 0.10
LIMIT_PCT_20 = 0.20
LIMIT_PCT_ST = 0.05
LIMIT_TOLERANCE = 0.002  # 判定容差: 9.8% / 19.8% / 4.8% 视为触及板价

try:
    import pandas as _pd
except ImportError:  # pragma: no cover
    _pd = None


def limit_pct_for(code: Optional[Union[str, int]], is_st: bool = False) -> float:
    """按代码前缀返回涨跌停幅度。30x/68x → 20%，ST → 5%，其余 10%。"""
    if is_st:
        return LIMIT_PCT_ST
    prefix = str(code or '')
    if prefix.startswith(('30', '68')):
        return LIMIT_PCT_20
    return LIMIT_PCT_MAIN


def is_limit_up_price(price: float, prev_close: float,
                      code: Optional[Union[str, int]] = None, is_st: bool = False) -> bool:
    """price 是否触及涨停价（含容差）。prev_close <= 0 视为不可判定 → False。"""
    if prev_close <= 0 or price is None:
        return False
    return price >= prev_close * (1 + limit_pct_for(code, is_st) - LIMIT_TOLERANCE) - 1e-9


def is_limit_down_price(price: float, prev_close: float,
                        code: Optional[Union[str, int]] = None, is_st: bool = False) -> bool:
    """price 是否触及跌停价（含容差）。"""
    if prev_close <= 0 or price is None:
        return False
    return price <= prev_close * (1 - limit_pct_for(code, is_st) + LIMIT_TOLERANCE) + 1e-9


def can_buy_at_open(open_price: float, prev_close: float,
                    code: Optional[Union[str, int]] = None, is_st: bool = False) -> bool:
    """开盘能否买入: 开盘即涨停（含一字板）→ 无卖盘，不可成交。"""
    return not is_limit_up_price(open_price, prev_close, code, is_st)


def can_sell_at_open(open_price: float, prev_close: float,
                     code: Optional[Union[str, int]] = None, is_st: bool = False) -> bool:
    """开盘能否卖出: 开盘即跌停（含一字板）→ 无买盘，不可成交。"""
    return not is_limit_down_price(open_price, prev_close, code, is_st)


def can_sell_intraday(open_price: float, high: float, low: float, close: float,
                      prev_close: float, code: Optional[Union[str, int]] = None,
                      is_st: bool = False) -> bool:
    """
    日内（止损/止盈）能否卖出:
    - 开盘即跌停 → 全天无法成交
    - 一字跌停（开=高=低=收 且收在跌停）→ 无买盘
    """
    if is_limit_down_price(open_price, prev_close, code, is_st):
        return False
    if (open_price == high == low == close and
            is_limit_down_price(close, prev_close, code, is_st)):
        return False
    return True


def can_buy_intraday(open_price: float, high: float, low: float, close: float,
                     prev_close: float, code: Optional[Union[str, int]] = None,
                     is_st: bool = False) -> bool:
    """日内能否买入（对称规则，预留）。"""
    if is_limit_up_price(open_price, prev_close, code, is_st):
        return False
    if (open_price == high == low == close and
            is_limit_up_price(close, prev_close, code, is_st)):
        return False
    return True


def next_open_fill(bar, prev_close: float, side: str,
                   code: Optional[Union[str, int]] = None, is_st: bool = False) -> Optional[float]:
    """
    t+1 开盘撮合判定（接受含 开盘/最高/最低/收盘 的 Series/dict）。

    Returns:
        成交价（含滑点前的裸开盘价，调用方自行加滑点/费用）；不可成交返回 None
    """
    open_price = bar['开盘']
    if side == 'buy':
        if not can_buy_at_open(open_price, prev_close, code, is_st):
            return None
        return open_price
    elif side == 'sell':
        if not can_sell_at_open(open_price, prev_close, code, is_st):
            return None
        return open_price
    return None


# ---------------------------------------------------------------------------
# 成交容量约束 (审计 B14 / H7)
# ---------------------------------------------------------------------------
#
# 旧问题: 成交量只用于信号打分 (放量/缩量), 从不做成交容量校验 —— 引擎可以在
# 日成交额百万的票上买上亿元而不作任何惩罚 (↑乐观)。现按"单笔买入金额 ≤
# 当日成交额 × 参与率" 封顶, 部分成交 (不足则按上限成交, 不足 1 手不买)。
#
# 数据口径: 优先 '成交额' 列; 缺失时用 '成交量' × 价格近似 (VWAP≈收盘价,
# 假设成交量单位为股 —— repo 的 data_cleaner 已把 手/股 归一为股)。

DEFAULT_MAX_VOLUME_PARTICIPATION = 0.05  # 默认单笔 ≤ 当日成交额的 5%


def bar_turnover_amount(bar, price: Optional[float] = None) -> Optional[float]:
    """取 bar 的当日成交额 (元)

    Args:
        bar: 含 '成交额'/'成交量'/'收盘' 的 Series 或 dict
        price: 成交价 (缺省用 bar['收盘'])

    Returns:
        成交额 (元); 两列都缺 → None (调用方如实跳过容量检查)。
        当日零成交返回 0.0 (不是 None) —— 零成交日不得成交。
    """
    def _get(obj, key):
        try:
            return obj.get(key)
        except AttributeError:
            return None

    def _isna(v):
        if v is None:
            return True
        if _pd is not None:
            try:
                return bool(_pd.isna(v))
            except (TypeError, ValueError):
                return False
        return False

    amount = _get(bar, '成交额')
    if amount is not None and not _isna(amount):
        return float(amount)

    volume = _get(bar, '成交量')
    if volume is None or _isna(volume):
        return None
    px = price if price is not None else _get(bar, '收盘')
    if px is None or _isna(px) or float(px) <= 0:
        return None
    return float(volume) * float(px)


def capacity_limit_notional(amount: Optional[float],
                             participation: Optional[float]) -> Optional[float]:
    """单笔成交金额上限 (元) —— 当日成交额 × 参与率

    Args:
        amount: 当日成交额 (元); None = 数据缺失 → 无法判断
        participation: 参与率上限 (0.05 = 当日成交额的 5%); <=0 = 关闭约束

    Returns:
        上限金额 (元); None = 不限制 (缺数据或显式关闭)。
        当日零成交 (amount == 0) → 返回 0.0 (买不进, 不是"不限制")。
    """
    if participation is None:
        return None
    try:
        part = float(participation)
    except (TypeError, ValueError):
        return None
    if part <= 0:
        return None
    if amount is None:
        return None
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        return None
    if amt != amt:  # NaN
        return None
    if amt <= 0:
        return 0.0
    return amt * part


# ---------------------------------------------------------------------------
# 向量化版本（numpy 数组入参，供向量化引擎批量判定）
# ---------------------------------------------------------------------------

def buy_open_ok(open_arr, prev_close_arr, code: Optional[Union[str, int]] = None,
                is_st: bool = False):
    """开盘可买入掩码（True=可成交）。open/prev_close 为等长 ndarray。"""
    import numpy as np
    open_arr = np.asarray(open_arr, dtype=np.float64)
    prev_close_arr = np.asarray(prev_close_arr, dtype=np.float64)
    limit = limit_pct_for(code, is_st)
    threshold = prev_close_arr * (1 + limit - LIMIT_TOLERANCE)
    return ~((open_arr >= threshold - 1e-9) & (prev_close_arr > 0))


def sell_open_ok(open_arr, prev_close_arr, code: Optional[Union[str, int]] = None,
                 is_st: bool = False):
    """开盘可卖出掩码（True=可成交）。"""
    import numpy as np
    open_arr = np.asarray(open_arr, dtype=np.float64)
    prev_close_arr = np.asarray(prev_close_arr, dtype=np.float64)
    limit = limit_pct_for(code, is_st)
    threshold = prev_close_arr * (1 - limit + LIMIT_TOLERANCE)
    return ~((open_arr <= threshold + 1e-9) & (prev_close_arr > 0))


def sell_intraday_ok(open_arr, high_arr, low_arr, close_arr, prev_close_arr,
                     code: Optional[Union[str, int]] = None, is_st: bool = False):
    """日内可卖出掩板（开盘跌停或一字跌停 → False）。数组须等长。"""
    import numpy as np
    open_arr = np.asarray(open_arr, dtype=np.float64)
    high_arr = np.asarray(high_arr, dtype=np.float64)
    low_arr = np.asarray(low_arr, dtype=np.float64)
    close_arr = np.asarray(close_arr, dtype=np.float64)
    prev_close_arr = np.asarray(prev_close_arr, dtype=np.float64)
    limit = limit_pct_for(code, is_st)
    down = prev_close_arr * (1 - limit + LIMIT_TOLERANCE)
    valid = prev_close_arr > 0
    open_down = (open_arr <= down + 1e-9) & valid
    sealed_down = ((open_arr == high_arr) & (high_arr == low_arr) &
                   (low_arr == close_arr) & (close_arr <= down + 1e-9) & valid)
    return ~(open_down | sealed_down)


@dataclass
class CostModel:
    """
    A股交易成本模型

    - 佣金: 万三双边，每笔最低 5 元（min_commission）
    - 印花税: 0.05% 仅卖出（2023-08 起现行税率）
    - 过户费: 0.001% 双边（沪深统一）
    - 滑点: 按比例作用于成交价（买加卖减）

    纯费率版 fee_rate(side) 不含最低佣金，供不追踪股数的向量化引擎使用。
    """
    commission_rate: float = 0.0003
    min_commission: float = 5.0
    stamp_tax: float = 0.0005
    transfer_fee: float = 0.0001
    slippage: float = 0.001

    def commission(self, notional: float) -> float:
        if notional <= 0:
            return 0.0
        return max(notional * self.commission_rate, self.min_commission)

    def buy_cost(self, price: float, shares: int) -> float:
        """买入总费用（佣金+过户费，不含滑点；滑点体现在成交价上）。"""
        notional = price * shares
        if notional <= 0 or shares <= 0:
            return 0.0
        return self.commission(notional) + notional * self.transfer_fee

    def sell_cost(self, price: float, shares: int) -> float:
        """卖出总费用（佣金+过户费+印花税）。"""
        notional = price * shares
        if notional <= 0 or shares <= 0:
            return 0.0
        return (self.commission(notional)
                + notional * (self.transfer_fee + self.stamp_tax))

    def fill_buy_price(self, price: float) -> float:
        """买入成交价（加滑点）。"""
        return price * (1 + self.slippage)

    def fill_sell_price(self, price: float) -> float:
        """卖出成交价（减滑点）。"""
        return price * (1 - self.slippage)

    def fee_rate(self, side: str) -> float:
        """
        纯费率（无最低佣金）: buy = 佣金+过户；sell = 佣金+过户+印花税。
        用于不追踪股数的向量化引擎（B/optimization_engine）。
        """
        if side == 'buy':
            return self.commission_rate + self.transfer_fee
        if side == 'sell':
            return self.commission_rate + self.transfer_fee + self.stamp_tax
        raise ValueError(f"未知方向: {side}")

    def buy_price_incl(self, price: float) -> float:
        """买入价 × (1+滑点) × (1+费率) — 纯费率版，向量化引擎用。"""
        return price * (1 + self.slippage) * (1 + self.fee_rate('buy'))

    def sell_price_incl(self, price: float) -> float:
        """卖出价 × (1-滑点) × (1-费率) — 纯费率版，向量化引擎用。"""
        return price * (1 - self.slippage) * (1 - self.fee_rate('sell'))

    @classmethod
    def from_engine(cls, commission: float = 0.0003, slippage: float = 0.001) -> 'CostModel':
        """兼容旧引擎构造参数（commission/slippage 比率）。"""
        return cls(commission_rate=commission, slippage=slippage)
