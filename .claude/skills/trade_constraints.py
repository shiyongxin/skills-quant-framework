# -*- coding: utf-8 -*-
"""
统一交易约束过滤器 - 信号/选股层前置可执行性检查 (审计 C-P1-12)

背景: 回测执行侧的 t+1/成本/涨跌停/一字板拦截已由 execution_model 覆盖
(4 个回测引擎已接); 但 7 个信号/选股模块 (signal_generator /
daily_signal_generator / multi_factor_selection / stock_selector /
long_term_selector / reversal_detector / ml_predictor) 在推荐与输出时
从不检查停牌、涨跌停、流动性 — "信号可执行"缺代码落点。

本模块是 7 个模块共用的前置过滤, 涨跌停判定复用 execution_model 单一
真相源 (limit_pct_for / is_limit_up_price / is_limit_down_price),
不另写第二套规则。

检查项与覆盖边界 (无法检查的诚实记入 skipped_checks, 不伪造):
- 一字板 (常开): 最后一根 高==低 (蕴含 开=高=低=收, 审计近似
  "收盘==最高==最低") 且收盘触及板价。买入仅被一字涨停阻、卖出仅被
  一字跌停阻 (与 execution_model.can_buy/sell_at_open 语义对齐)。
  数据侧无涨跌停价列, 用前收+幅度近似; ST 幅度数据侧无 ST 标记,
  默认按非 ST 判定 (调用方可传 is_st=True)。
- 停牌/数据过期: 数据侧无停牌标记 (停牌日无行, execution_model 同结论)
    - 零成交末 bar (成交量==0 或 成交额==0) → 停牌嫌疑, 常开;
    - as_of + max_stale_days: 最新 bar 距 as_of 自然日超限 → 阻断
      (默认 max_stale_days=None 关闭 — 无交易日历, 节假日会误伤)。
- 流动性:
    - min_price: 最新收盘 < min_price (默认 1.0 元) → 阻断;
    - min_adv_amount: 20 日均成交额下限, 默认 0=关闭 (历史成交额
      单位维度未清洗 — 审计遗留, 防误杀, 部署方按需启用);
    - max_adv_participation: 仅调用方给 target_amount 时生效
      (目标金额 ≤ ADV20 × 占比上限);
    - min_market_cap: 数据侧无市值列 → 记 skipped (配置占位)。
- 收盘面板 (check_close_panel, S3 用): 仅收盘宽面板可查 min_price +
  最新交易日缺数据 (停牌嫌疑); 一字板需高低价、ADV 需成交额 — 缺数据
  时不伪造检查。

用法:
    report = check_last_bar(df, code='600000', side='buy')
    if not report.ok:
        ...  # report.blocked_reasons 给出阻断原因
"""

from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

import factor_library
from execution_model import (
    limit_pct_for,
    is_limit_up_price,
    is_limit_down_price,
)


@dataclass
class ConstraintConfig:
    """交易约束配置 (config/trade_constraints.json 出厂值=内置默认)"""
    min_price: float = 1.0                    # 最低收盘价 (元); <=0 关闭
    min_adv_amount: float = 0.0               # 20日均成交额下限 (元); 0=关闭
    max_adv_participation: float = 0.1        # 目标金额/ADV20 上限
    min_market_cap: Optional[float] = None    # 最小市值 (元); None=关闭 (无市值数据)
    max_stale_days: Optional[int] = None      # 最新bar距 as_of 自然日上限; None=关闭


@dataclass
class ConstraintReport:
    """单次检查结果: 阻断原因 + 诚实跳过项 + 诊断细节"""
    ok: bool = True
    blocked_reasons: List[str] = field(default_factory=list)
    skipped_checks: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def block(self, reason: str) -> None:
        self.ok = False
        self.blocked_reasons.append(reason)

    def as_signal_fields(self) -> Dict[str, Any]:
        """→ 契约字段 (审计 C #9 收口: 各模块不再各自拼装可执行性字段).

        统一产出 executable / blocked_reasons / skipped_checks 三字段,
        与 core.signal.Signal 的字段同名同义。
        """
        return {
            'executable': bool(self.ok),
            'blocked_reasons': list(self.blocked_reasons),
            'skipped_checks': list(self.skipped_checks),
        }


_CONFIG_CACHE: Optional[ConstraintConfig] = None


def get_config(refresh: bool = False) -> ConstraintConfig:
    """读 config/trade_constraints.json; 缺失/键不匹配回退内置默认。"""
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None or refresh:
        raw = factor_library.load_config('trade_constraints') or {}
        valid = {f.name for f in fields(ConstraintConfig)}
        _CONFIG_CACHE = ConstraintConfig(
            **{k: v for k, v in raw.items() if k in valid})
    return _CONFIG_CACHE


def _last_bar_date(df: pd.DataFrame) -> Optional[pd.Timestamp]:
    """最新 bar 的日期 (日期列优先, 其次 DatetimeIndex); 无法判定返回 None。"""
    try:
        if '日期' in df.columns:
            return pd.Timestamp(df['日期'].iloc[-1])
        if isinstance(df.index, pd.DatetimeIndex):
            return pd.Timestamp(df.index[-1])
        if isinstance(df.index[-1], (pd.Timestamp, datetime)):
            return pd.Timestamp(df.index[-1])
    except Exception:
        return None
    return None


def check_last_bar(df: pd.DataFrame,
                   code: Optional[str] = None,
                   side: str = 'both',
                   config: Optional[ConstraintConfig] = None,
                   as_of=None,
                   is_st: bool = False,
                   target_amount: Optional[float] = None) -> ConstraintReport:
    """
    对单只股票最新 bar 做交易约束检查 (审计 C-P1-12)。

    Args:
        df: 含 OHLCV 的行情数据 (最后一根 = 待检查 bar)
        code: 股票代码 (决定板块限幅 10%/20%; None → 一字板检查跳过)
        side: 'buy' / 'sell' / 'both' — 限板按方向阻断
        config: 约束配置 (None 读 config JSON)
        as_of: 检查基准日 (None → 数据过期检查跳过)
        is_st: 是否 ST (5% 幅度; 数据侧无 ST 标记, 默认 False)
        target_amount: 目标下单金额 (元, 给定时检查 ADV 占比上限)

    Returns:
        ConstraintReport (永不抛异常; 缺数据项记 skipped_checks)
    """
    if side not in ('buy', 'sell', 'both'):
        raise ValueError(f"side 必须是 buy/sell/both, 得到: {side}")
    cfg = config if config is not None else get_config()
    report = ConstraintReport()

    if df is None or len(df) == 0:
        report.block('无数据')
        return report

    latest = df.iloc[-1]

    # ---- 一字板 (复用 execution_model 单一真相源) ----
    board_cols = ('开盘', '最高', '最低', '收盘')
    if code is None:
        report.skipped_checks.append('一字板: 无股票代码 (无法判定板块限幅), 未检查')
    elif not all(c in df.columns for c in board_cols):
        report.skipped_checks.append('一字板: 缺开高低收列, 未检查')
    elif len(df) < 2:
        report.skipped_checks.append('一字板: 不足2根 (无昨收), 未检查')
    else:
        pct = limit_pct_for(code, is_st)
        report.details['limit_pct'] = pct
        high, low = latest['最高'], latest['最低']
        close, prev_close = latest['收盘'], df['收盘'].iloc[-2]
        if not (pd.isna(high) or pd.isna(low) or pd.isna(close)
                or pd.isna(prev_close)):
            # 平栏 (高==低) 蕴含 开=高=低=收 — 审计近似一字板
            if high == low:
                report.details['sealed_bar'] = True
                if side in ('buy', 'both') and is_limit_up_price(
                        float(close), float(prev_close), code, is_st):
                    report.block(
                        f'一字涨停封板 (限幅{pct:.0%}) → 买入不可成交')
                if side in ('sell', 'both') and is_limit_down_price(
                        float(close), float(prev_close), code, is_st):
                    report.block(
                        f'一字跌停封板 (限幅{pct:.0%}) → 卖出不可成交')
            else:
                report.details['sealed_bar'] = False

    # ---- 停牌嫌疑: 零成交末 bar (常开) ----
    zero_checked = False
    for col in ('成交量', '成交额'):
        if col not in df.columns:
            continue
        zero_checked = True
        try:
            if float(latest[col]) == 0.0:
                report.block(f'零{col} (停牌嫌疑) → 无法成交')
        except (TypeError, ValueError):
            pass
    if not zero_checked:
        report.skipped_checks.append('停牌/零成交: 缺成交量与成交额列, 未检查')

    # ---- 数据过期 (需 as_of + max_stale_days 同时给定) ----
    if as_of is None:
        report.skipped_checks.append('数据过期: 未提供 as_of, 未检查')
    elif cfg.max_stale_days is None:
        report.skipped_checks.append('数据过期: max_stale_days 未配置, 未检查')
    else:
        last_date = _last_bar_date(df)
        if last_date is None or pd.isna(last_date):
            report.skipped_checks.append('数据过期: 无法定位最新 bar 日期, 未检查')
        else:
            age = (pd.Timestamp(as_of).normalize()
                   - last_date.normalize()).days
            report.details['stale_days'] = age
            if age > cfg.max_stale_days:
                report.block(
                    f'数据过期 {age} 天 > {cfg.max_stale_days} (停牌嫌疑)')

    # ---- 最低价格 ----
    if '收盘' not in df.columns:
        report.skipped_checks.append('min_price: 缺收盘列, 未检查')
    else:
        close = latest['收盘']
        if pd.isna(close):
            report.skipped_checks.append('min_price: 最新收盘为 NaN, 未检查')
        elif cfg.min_price and close < cfg.min_price:
            report.block(f'收盘价 {float(close):.2f} < 最低价格 {cfg.min_price}')

    # ---- 流动性: ADV 下限 + 目标金额占比 (仅配置启用/给定时) ----
    adv20 = None
    need_adv = (cfg.min_adv_amount > 0) or (target_amount is not None)
    if need_adv:
        if '成交额' not in df.columns:
            if cfg.min_adv_amount > 0:
                report.skipped_checks.append('min_adv_amount: 缺成交额列, 未检查')
            if target_amount is not None:
                report.skipped_checks.append(
                    'adv_participation: 缺成交额列, 未检查')
        else:
            adv20 = df['成交额'].rolling(20, min_periods=20).mean().iloc[-1]
            if pd.isna(adv20):
                if cfg.min_adv_amount > 0:
                    report.skipped_checks.append(
                        'min_adv_amount: 不足20根无ADV20, 未检查')
                if target_amount is not None:
                    report.skipped_checks.append(
                        'adv_participation: 不足20根无ADV20, 未检查')
                adv20 = None
            else:
                report.details['adv20'] = float(adv20)
                if cfg.min_adv_amount > 0 and adv20 < cfg.min_adv_amount:
                    report.block(
                        f'ADV20 {adv20:,.0f} < 下限 {cfg.min_adv_amount:,.0f} (元)')
    if target_amount is not None and adv20 is not None:
        cap = adv20 * cfg.max_adv_participation
        report.details['amount_cap'] = float(cap)
        if target_amount > cap:
            report.block(
                f'目标金额 {target_amount:,.0f} > ADV20×{cfg.max_adv_participation:.0%} '
                f'= {cap:,.0f} (元)')

    # ---- 最小市值 (数据侧通常无市值列 → 诚实跳过) ----
    if cfg.min_market_cap:
        mcap_col = next(
            (c for c in ('流通市值', '总市值') if c in df.columns), None)
        if mcap_col is None:
            report.skipped_checks.append(
                'min_market_cap: 数据无市值列, 未检查')
        else:
            mc = latest[mcap_col]
            if pd.isna(mc):
                report.skipped_checks.append(
                    'min_market_cap: 最新市值为 NaN, 未检查')
            elif mc < cfg.min_market_cap:
                report.block(
                    f'市值 {float(mc):,.0f} < 下限 {cfg.min_market_cap:,.0f} (元)')

    return report


def check_close_panel(panel: Optional[pd.DataFrame],
                      config: Optional[ConstraintConfig] = None
                      ) -> Tuple[pd.Series, Dict[str, str]]:
    """
    收盘横截面面板 (index=股票码, columns=日期) 的可执行性过滤 (S3 接线)。

    仅收盘面板可查: 最低价格 + 最新交易日缺数据 (停牌嫌疑)。
    一字板 (需高低价) / ADV (需成交额) 数据不可得 — 不伪造检查,
    由调用方 docstring 记录边界。

    Returns:
        (keep: Series[bool] 按股票, reasons: {股票: 剔除原因})
    """
    if panel is None or len(panel) == 0 or len(panel.columns) == 0:
        return pd.Series(dtype=bool), {}
    cfg = config if config is not None else get_config()
    latest = panel.iloc[:, -1]
    keep = pd.Series(True, index=panel.index)
    reasons: Dict[str, str] = {}
    for stock, close in latest.items():
        try:
            if pd.isna(close):
                keep[stock] = False
                reasons[stock] = '最新交易日无收盘数据 (停牌嫌疑)'
            elif cfg.min_price and float(close) < cfg.min_price:
                keep[stock] = False
                reasons[stock] = f'收盘 {float(close):.2f} < 最低价格 {cfg.min_price}'
        except (TypeError, ValueError):
            continue
    return keep, reasons
