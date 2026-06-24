# -*- coding: utf-8 -*-
"""
转折点策略回测 - Web UI 版本 v2.1
增加仓位管理功能，根据信号强度决定买卖数量
"""

from flask import Flask, render_template, request, jsonify
import sys
sys.path.append('.claude/skills')

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import akshare as ak
from pathlib import Path
import json
import threading
import uuid

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

# 存储回测任务状态
backtest_tasks = {}

# 股票名称缓存（code -> name）
stock_name_cache = None
stock_name_cache_time = None


# ============== 优化方案加载（来自 stock_data/optimization_result.json）==============

OPTIMIZATION_PATH = Path("stock_data/optimization_result.json")
_optimization_cache = {"mtime": None, "by_name": {}, "timestamp": None, "warning": None}

# 25 个参数 + 4 个 scoring 权重的默认值；作为手动模式预设 + 系统模式的 merge 底
DEFAULT_PARAMS = {
    # 指标周期
    "ma_fast": 5, "ma_mid": 10, "ma_slow": 20,
    "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
    "rsi_period": 14, "rsi_oversold": 30, "rsi_overbought": 70,
    "kdj_n": 9, "bb_period": 20, "bb_std": 2.0, "atr_period": 14,
    # 信号阈值（手动模式：点计数阈值；系统模式：连续分阈值 0-100）
    "buy_threshold": 4.0, "sell_threshold": 4.0,
    # 仓位/风控
    "stop_loss_pct": 0.0, "take_profit_pct": 0.0,
    "trailing_stop_pct": 0.0, "min_holding_days": 0,
    "position_size_pct": 1.0,
    # 加权评分（仅在系统模式下生效）
    "score_buy_threshold": 50.0, "score_sell_threshold": 50.0,
    "w_trend": 25.0, "w_momentum": 25.0, "w_risk": 25.0, "w_performance": 25.0,
    "use_weighted_scoring": False,
}


def load_optimization_systems():
    """加载 stock_data/optimization_result.json 里的 8 个系统。

    带 mtime 缓存：文件变化时自动重读。文件缺失或损坏返回 None。
    返回 {"timestamp", "by_name", "warning"} 字典。
    """
    global _optimization_cache
    if not OPTIMIZATION_PATH.exists():
        return None
    try:
        mtime = OPTIMIZATION_PATH.stat().st_mtime
    except OSError:
        return None
    if _optimization_cache["mtime"] == mtime and _optimization_cache["by_name"]:
        return _optimization_cache
    try:
        with open(OPTIMIZATION_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    by_name = {}
    for sys in data.get("systems", []):
        name = sys.get("name")
        if not name:
            continue
        # 注入 use_weighted_scoring=True 标志
        merged = {**sys.get("params", {}), "use_weighted_scoring": True}
        by_name[name] = {**sys, "params": merged}
    _optimization_cache = {
        "mtime": mtime,
        "by_name": by_name,
        "timestamp": data.get("timestamp"),
        "warning": None,
    }
    return _optimization_cache


def resolve_system_params(system_name):
    """根据 system_name 解析得到合并后的 params dict；找不到则返回 None（手动模式）。"""
    if not system_name:
        return None
    cache = load_optimization_systems()
    if not cache:
        return None
    sys = cache["by_name"].get(system_name)
    if not sys:
        return None
    return sys["params"]


# ============== 核心算法函数 ==============

def get_stock_data(code, days=365, start_date=None, end_date=None):
    """获取股票历史数据

    Args:
        code: 股票代码
        days: 天数（向后推算，与start_date/end_date二选一）
        start_date: 开始日期 (datetime对象或YYYY-MM-DD字符串)
        end_date: 结束日期 (datetime对象或YYYY-MM-DD字符串)
    """
    try:
        # 日期处理：优先使用start_date/end_date，否则使用days
        if end_date is None:
            end_date = datetime.now()
        elif isinstance(end_date, str):
            end_date = datetime.strptime(end_date, '%Y-%m-%d')

        if start_date is None:
            start_date = end_date - timedelta(days=days)
        elif isinstance(start_date, str):
            start_date = datetime.strptime(start_date, '%Y-%m-%d')

        if code.startswith('6'):
            symbol = f'sh{code}'
        else:
            symbol = f'sz{code}'

        df = ak.stock_zh_a_daily(symbol=symbol, start_date=start_date.date(), end_date=end_date.date())

        if df is None or len(df) < 60:
            return None

        df = df.rename(columns={
            'date': '日期',
            'open': '开盘',
            'high': '最高',
            'low': '最低',
            'close': '收盘',
            'volume': '成交量'
        })
        df['日期'] = pd.to_datetime(df['日期'])
        df = df.sort_values('日期')

        return df

    except Exception:
        return None


def calculate_indicators(df, params=None):
    """计算技术指标。

    列名固定为 MA5/MA10/MA20/MA60/RSI14/K/D/J/MACD/MACD_Signal/ATR/BB_*
    以保持与图表接口兼容；具体周期由 params 决定。
    """
    p = {**DEFAULT_PARAMS, **(params or {})}
    close = df['收盘'].values
    high = df['最高'].values
    low = df['最低'].values

    # MA — 列名固定为 5/10/20/60，内部周期取自 params
    df['MA5'] = df['收盘'].rolling(p['ma_fast']).mean()
    df['MA10'] = df['收盘'].rolling(p['ma_mid']).mean()
    df['MA20'] = df['收盘'].rolling(p['ma_slow']).mean()
    df['MA60'] = df['收盘'].rolling(60).mean()

    # 成交量MA（未在参数空间中，保持固定）
    df['Vol_MA5'] = df['成交量'].rolling(5).mean()
    df['Vol_MA20'] = df['成交量'].rolling(20).mean()

    # RSI
    rsi_period = int(p['rsi_period'])
    delta = pd.Series(close).diff()
    gain = (delta.where(delta > 0, 0)).rolling(rsi_period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(rsi_period).mean()
    rs = gain / loss
    df['RSI14'] = 100 - (100 / (1 + rs))

    # KDJ
    kdj_n = int(p['kdj_n'])
    low_n = pd.Series(low).rolling(kdj_n).min()
    high_n = pd.Series(high).rolling(kdj_n).max()
    rsv = (pd.Series(close) - low_n) / (high_n - low_n) * 100
    df['K'] = rsv.ewm(alpha=1/3).mean()
    df['D'] = df['K'].ewm(alpha=1/3).mean()
    df['J'] = 3 * df['K'] - 2 * df['D']

    # MACD
    macd_fast = int(p['macd_fast'])
    macd_slow = int(p['macd_slow'])
    macd_signal = int(p['macd_signal'])
    ema_fast = pd.Series(close).ewm(span=macd_fast).mean()
    ema_slow = pd.Series(close).ewm(span=macd_slow).mean()
    df['MACD'] = ema_fast - ema_slow
    df['MACD_Signal'] = df['MACD'].ewm(span=macd_signal).mean()
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']

    # ATR
    atr_period = int(p['atr_period'])
    high_low = pd.Series(high) - pd.Series(low)
    high_close = np.abs(pd.Series(high) - pd.Series(close).shift(1))
    low_close = np.abs(pd.Series(low) - pd.Series(close).shift(1))
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(atr_period).mean()

    # 布林带
    bb_period = int(p['bb_period'])
    bb_std_mult = float(p['bb_std'])
    df['BB_Mid'] = df['收盘'].rolling(bb_period).mean()
    bb_std = df['收盘'].rolling(bb_period).std()
    df['BB_Upper'] = df['BB_Mid'] + bb_std_mult * bb_std
    df['BB_Lower'] = df['BB_Mid'] - bb_std_mult * bb_std

    return df


def calculate_weighted_score(row, prev, p):
    """多因子加权评分（0-100）。

    4 个子分数各为 0-100：
      - trend (w_trend):        MA 排列 + MACD 方向 + MA20 突破
      - momentum (w_momentum):  RSI 位置 + KDJ 金叉
      - risk (w_risk):          布林带位置（越低越安全 → 越高分）
      - performance (w_performance): 短期收益率

    返回 (buy_score, sell_score) 加权后归一化到 0-100。
    sell_score 通过反转每个子分数计算（独立加权）。
    """
    # --- trend_bull: 0-100 ---
    trend_bull = 0.0
    if pd.notna(row['MA5']) and pd.notna(row['MA10']) and pd.notna(row['MA20']):
        if row['MA5'] > row['MA10'] > row['MA20']:
            trend_bull += 40
        elif row['MA5'] > row['MA20']:
            trend_bull += 20
    if pd.notna(row['MACD']) and pd.notna(row['MACD_Signal']):
        if row['MACD'] > row['MACD_Signal']:
            trend_bull += 40
    if pd.notna(prev['收盘']) and pd.notna(prev['MA20']):
        if row['收盘'] > row['MA20'] and prev['收盘'] <= prev['MA20']:
            trend_bull += 20
    trend_bull = min(100, trend_bull)

    # --- momentum_bull: 0-100 ---
    rsi = row['RSI14'] if pd.notna(row['RSI14']) else 50
    if rsi < 30:
        mom_bull = 90
    elif rsi < 50:
        mom_bull = 70
    elif rsi < 70:
        mom_bull = 40
    else:
        mom_bull = 10
    if pd.notna(row['K']) and pd.notna(row['D']):
        if row['K'] > row['D'] and row['K'] < 80:
            mom_bull = min(100, mom_bull + 10)
    mom_bull = min(100, mom_bull)

    # --- risk_bull: 0-100（布林带位置越低越适合买入）---
    if pd.notna(row['BB_Upper']) and pd.notna(row['BB_Lower']):
        bb_range = row['BB_Upper'] - row['BB_Lower']
        if bb_range > 0:
            bb_pos = (row['收盘'] - row['BB_Lower']) / bb_range
            bb_pos = max(0.0, min(1.0, bb_pos))
            risk_bull = (1 - bb_pos) * 100
        else:
            risk_bull = 50
    else:
        risk_bull = 50

    # --- performance_bull: 0-100（5日收益率）---
    if pd.notna(prev['收盘']) and prev['收盘'] > 0:
        ret5 = (row['收盘'] / prev['收盘'] - 1)
        perf_bull = 50 + ret5 * 500
        perf_bull = max(0, min(100, perf_bull))
    else:
        perf_bull = 50

    # 卖方子分数 = 100 - 买方子分数
    trend_bear = 100 - trend_bull
    mom_bear = 100 - mom_bull
    risk_bear = 100 - risk_bull
    perf_bear = 100 - perf_bull

    wsum = p['w_trend'] + p['w_momentum'] + p['w_risk'] + p['w_performance']
    if wsum <= 0:
        wsum = 100.0
    buy_score = (p['w_trend'] * trend_bull
                 + p['w_momentum'] * mom_bull
                 + p['w_risk'] * risk_bull
                 + p['w_performance'] * perf_bull) / wsum
    sell_score = (p['w_trend'] * trend_bear
                  + p['w_momentum'] * mom_bear
                  + p['w_risk'] * risk_bear
                  + p['w_performance'] * perf_bear) / wsum
    return buy_score, sell_score


def detect_reversal_signals(df, params=None):
    """检测转折点信号。

    双模式：
      - 手动模式（默认）：原有点计数评分（兼容旧行为）
      - 系统模式（params 中 use_weighted_scoring=True）：4 因子加权评分，0-100 连续分
    """
    p = {**DEFAULT_PARAMS, **(params or {})}
    use_weighted = p.get('use_weighted_scoring', False)

    # 加权模式下使用 score_*_threshold，否则使用 buy/sell_threshold
    buy_threshold = float(p['score_buy_threshold']) if use_weighted else float(p['buy_threshold'])
    sell_threshold = float(p['score_sell_threshold']) if use_weighted else float(p['sell_threshold'])
    rsi_oversold = float(p['rsi_oversold'])
    rsi_overbought = float(p['rsi_overbought'])

    signals = []

    for i in range(60, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]

        if use_weighted:
            # ---- 加权模式 ----
            buy_score_f, sell_score_f = calculate_weighted_score(row, prev, p)
            buy_score = buy_score_f
            sell_score = sell_score_f

            buy_signals = []
            sell_signals = []

            # 标注主要因子
            if buy_score_f >= buy_threshold:
                # 找出贡献最大的子分数
                wsum = p['w_trend'] + p['w_momentum'] + p['w_risk'] + p['w_performance']
                if wsum <= 0:
                    wsum = 100.0
                rsi_val = row['RSI14'] if pd.notna(row['RSI14']) else 50
                contribs = {
                    '趋势': p['w_trend'] * (50 if pd.isna(row['MA5']) or row['MA5'] <= row['MA20'] else 70) / wsum,
                    '动量': p['w_momentum'] * (50 if rsi_val >= 50 else 70) / wsum,
                    '风险': p['w_risk'] * 50 / wsum,
                    '表现': p['w_performance'] * 50 / wsum,
                }
                top = max(contribs, key=contribs.get)
                buy_signals.append(f"加权{buy_score_f:.0f}分(主:{top})")

            if sell_score_f >= sell_threshold:
                sell_signals.append(f"加权{sell_score_f:.0f}分")
        else:
            # ---- 手动模式（点计数，原行为）----
            buy_signals = []
            buy_score = 0

            if row['RSI14'] < rsi_oversold:
                buy_signals.append(f"RSI超卖({row['RSI14']:.1f})")
                buy_score += 2
            elif row['RSI14'] < rsi_oversold + 10:
                buy_signals.append(f"RSI偏低({row['RSI14']:.1f})")
                buy_score += 1

            if prev['J'] > 100 and row['J'] < prev['J']:
                buy_signals.append(f"KDJ回落({row['J']:.0f})")
                buy_score += 2
            elif row['J'] < 20:
                buy_signals.append(f"KDJ超卖({row['J']:.0f})")
                buy_score += 2

            if row['收盘'] <= row['BB_Lower'] * 1.02:
                buy_signals.append("触及下轨")
                buy_score += 2

            if prev['MACD'] <= prev['MACD_Signal'] and row['MACD'] > row['MACD_Signal']:
                buy_signals.append("MACD金叉")
                buy_score += 2

            if row['收盘'] > row['MA20'] and prev['收盘'] <= prev['MA20']:
                buy_signals.append("站上MA20")
                buy_score += 2

            if row['成交量'] > row['Vol_MA20'] * 1.5:
                buy_signals.append("放量")
                buy_score += 1

            sell_signals = []
            sell_score = 0

            if row['RSI14'] > rsi_overbought + 10:
                sell_signals.append(f"RSI严重超买({row['RSI14']:.1f})")
                sell_score += 3
            elif row['RSI14'] > rsi_overbought:
                sell_signals.append(f"RSI超买({row['RSI14']:.1f})")
                sell_score += 2

            if prev['J'] < 0 and row['J'] > prev['J']:
                sell_signals.append(f"KDJ回升({row['J']:.0f})")
                sell_score += 2
            elif row['J'] > 100:
                sell_signals.append(f"KDJ超买({row['J']:.0f})")
                sell_score += 2

            if row['收盘'] >= row['BB_Upper'] * 0.98:
                sell_signals.append("触及上轨")
                sell_score += 2

            if prev['MACD'] >= prev['MACD_Signal'] and row['MACD'] < row['MACD_Signal']:
                sell_signals.append("MACD死叉")
                sell_score += 2

            if row['收盘'] < row['MA20'] and prev['收盘'] >= prev['MA20']:
                sell_signals.append("跌破MA20")
                sell_score += 2

            if row['成交量'] < row['Vol_MA20'] * 0.7:
                sell_signals.append("缩量")
                sell_score += 1

        signals.append({
            'date': row['日期'].strftime('%Y-%m-%d'),
            'close': float(row['收盘']),
            'buy_signals': buy_signals,
            'buy_score': float(buy_score),
            'sell_signals': sell_signals,
            'sell_score': float(sell_score),
            'rsi': float(row['RSI14']) if pd.notna(row['RSI14']) else 50,
            'j': float(row['J']) if pd.notna(row['J']) else 50,
            'macd': float(row['MACD']) if pd.notna(row['MACD']) else 0,
            'use_weighted': use_weighted,
        })

    return pd.DataFrame(signals)


def calculate_position_size(buy_score, sell_score, position_config=None):
    """
    根据信号强度计算仓位比例

    支持自定义仓位配置，四档买入和四档卖出

    Args:
        buy_score: 买入信号分数 (0-15)
        sell_score: 卖出信号分数 (0-15)
        position_config: 自定义仓位配置 {
            'buy_levels': [低, 中低, 中高, 高],  # 买入比例列表，如 [25, 50, 67, 100]
            'sell_levels': [低, 中低, 中高, 高]  # 卖出比例列表，如 [33, 50, 67, 100]
        }
    """
    # 默认配置
    default_config = {
        'buy_levels': [25, 50, 67, 100],
        'sell_levels': [33, 50, 67, 100]
    }

    if position_config is None:
        position_config = default_config

    # 获取配置列表
    buy_levels = position_config.get('buy_levels', default_config['buy_levels'])
    sell_levels = position_config.get('sell_levels', default_config['sell_levels'])

    # 转换为小数
    buy_levels = [x / 100 for x in buy_levels]
    sell_levels = [x / 100 for x in sell_levels]

    # 买入仓位：根据分数选择档位
    if buy_score <= 3:
        buy_ratio = buy_levels[0]  # 低信号
    elif buy_score <= 5:
        buy_ratio = buy_levels[1]  # 中低信号
    elif buy_score <= 7:
        buy_ratio = buy_levels[2]  # 中高信号
    else:
        buy_ratio = buy_levels[3]  # 高信号

    # 卖出仓位：根据分数选择档位
    if sell_score <= 3:
        sell_ratio = sell_levels[0]  # 低信号
    elif sell_score <= 5:
        sell_ratio = sell_levels[1]  # 中低信号
    elif sell_score <= 7:
        sell_ratio = sell_levels[2]  # 中高信号
    else:
        sell_ratio = sell_levels[3]  # 高信号

    return buy_ratio, sell_ratio


def backtest_stock(code, name, signals_df, params=None, position_config=None):
    """对单只股票进行回测（带仓位管理 + 止损/止盈/移动止损）。"""
    p = {**DEFAULT_PARAMS, **(params or {})}
    use_weighted = p.get('use_weighted_scoring', False)
    # 阈值选择
    if use_weighted:
        buy_threshold = float(p['score_buy_threshold'])
        sell_threshold = float(p['score_sell_threshold'])
    else:
        buy_threshold = float(p['buy_threshold'])
        sell_threshold = float(p['sell_threshold'])

    stop_loss_pct     = float(p['stop_loss_pct'])
    take_profit_pct   = float(p['take_profit_pct'])
    trailing_stop_pct = float(p['trailing_stop_pct'])
    min_holding_days  = int(p['min_holding_days'])
    position_size_cap = float(p['position_size_pct'])

    initial_cash = 100000
    cash = initial_cash
    shares = 0
    trades = []
    position = None
    daily_logs = []  # 详细日志

    def execute_sell(qty, price, trade_type, reason, signal):
        """执行卖出，accounting 与原 SELL 分支一致。"""
        nonlocal shares, cash, position
        revenue = qty * price
        cash += revenue
        cost_of_sold = position['cost'] * (qty / shares) if shares > 0 else 0
        profit = revenue - cost_of_sold
        profit_pct = profit / cost_of_sold * 100 if cost_of_sold > 0 else 0
        shares_before = shares
        shares -= qty
        trades.append({
            'type': trade_type,
            'date': signal['date'],
            'price': float(price),
            'shares': qty,
            'revenue': revenue,
            'profit': profit,
            'profit_pct': profit_pct,
            'entry_price': position['entry_price'],
            'shares_before': shares_before,
            'shares_after': shares,
        })
        if shares == 0:
            position = None
        else:
            position['cost'] -= cost_of_sold
            position['shares'] = shares
        return profit, profit_pct

    for idx, signal in signals_df.iterrows():
        price = signal['close']
        buy_score = signal['buy_score']
        sell_score = signal['sell_score']
        buy_signals = signal.get('buy_signals', [])
        sell_signals = signal.get('sell_signals', [])

        # 记录当日日志
        daily_log = {
            'date': signal['date'],
            'price': float(price),
            'buy_score': buy_score,
            'sell_score': sell_score,
            'buy_signals': buy_signals,
            'sell_signals': sell_signals,
            'cash_before': cash,
            'shares_before': shares,
            'position_before': position.copy() if position else None,
            'action': None,
            'action_reason': '',
            'action_detail': ''
        }

        # ---- 持仓期：先检查止损/止盈/移动止损 ----
        if position and shares > 0:
            if price > position['highest_price']:
                position['highest_price'] = price
            holding_days = (datetime.strptime(signal['date'], '%Y-%m-%d')
                            - datetime.strptime(position['entry_date'], '%Y-%m-%d')).days

            # 1) 固定止损（任何时间）
            if stop_loss_pct > 0:
                sl_price = position['entry_price'] * (1 - stop_loss_pct)
                if price <= sl_price:
                    daily_log['action'] = 'STOP_LOSS'
                    daily_log['action_reason'] = (
                        f'触发止损 {stop_loss_pct*100:.1f}% '
                        f'(现价{price:.2f} ≤ 止损线{sl_price:.2f})'
                    )
                    p_profit, p_pct = execute_sell(shares, price, 'STOP_LOSS', daily_log['action_reason'], signal)
                    daily_log['action_result'] = (
                        f'止损平仓 {shares} 股@{price:.2f}元, 盈亏 {p_profit:+.2f}元({p_pct:+.1f}%)'
                    )
                    daily_logs.append(daily_log)
                    continue

            # 2) 止盈（受 min_holding_days 约束）
            if take_profit_pct > 0 and holding_days >= min_holding_days:
                tp_price = position['entry_price'] * (1 + take_profit_pct)
                if price >= tp_price:
                    daily_log['action'] = 'TAKE_PROFIT'
                    daily_log['action_reason'] = (
                        f'触发止盈 {take_profit_pct*100:.1f}% '
                        f'(现价{price:.2f} ≥ 止盈线{tp_price:.2f}, 已持仓{holding_days}天)'
                    )
                    p_profit, p_pct = execute_sell(shares, price, 'TAKE_PROFIT', daily_log['action_reason'], signal)
                    daily_log['action_result'] = (
                        f'止盈平仓 {shares} 股@{price:.2f}元, 盈亏 {p_profit:+.2f}元({p_pct:+.1f}%)'
                    )
                    daily_logs.append(daily_log)
                    continue

            # 3) 移动止损（只在创新高后启动，止损线须在成本价之上）
            if (trailing_stop_pct > 0
                    and position['highest_price'] > position['entry_price']):
                ts_price = position['highest_price'] * (1 - trailing_stop_pct)
                if price <= ts_price and ts_price > position['entry_price']:
                    daily_log['action'] = 'TRAILING_STOP'
                    daily_log['action_reason'] = (
                        f'触发移动止损 {trailing_stop_pct*100:.1f}% '
                        f'(高点{position["highest_price"]:.2f}, 止损线{ts_price:.2f})'
                    )
                    p_profit, p_pct = execute_sell(shares, price, 'TRAILING_STOP', daily_log['action_reason'], signal)
                    daily_log['action_result'] = (
                        f'移动止损平仓 {shares} 股@{price:.2f}元, 盈亏 {p_profit:+.2f}元({p_pct:+.1f}%)'
                    )
                    daily_logs.append(daily_log)
                    continue

        # 卖出逻辑（信号驱动，受 min_holding_days 约束）
        if sell_score >= sell_threshold and shares > 0:
            holding_days = 0
            if position:
                holding_days = (datetime.strptime(signal['date'], '%Y-%m-%d')
                                - datetime.strptime(position['entry_date'], '%Y-%m-%d')).days
            if holding_days < min_holding_days:
                daily_log['action'] = 'HOLD_MIN_DAYS'
                daily_log['action_reason'] = (
                    f'卖出信号{sell_score:.1f}分但未到最小持仓天数 '
                    f'({holding_days}/{min_holding_days})'
                )
                daily_logs.append(daily_log)
                continue

            buy_ratio, sell_ratio = calculate_position_size(buy_score, sell_score, position_config)
            sell_shares = int(shares * sell_ratio / 100) * 100  # 100股取整

            daily_log['action'] = 'SELL'
            daily_log['action_reason'] = f'卖出信号{sell_score:.1f}分≥阈值{sell_threshold:.1f}|{",".join(sell_signals)}'
            daily_log['action_detail'] = f'计划卖出{sell_ratio*100:.0f}%仓位'

            if sell_shares > 0 and sell_shares <= shares:
                p_profit, p_pct = execute_sell(sell_shares, price, 'SELL', daily_log['action_reason'], signal)
                daily_log['action_result'] = (
                    f'卖出{sell_shares}股@{price:.2f}元, 收入{p_profit + (position["cost"] * (sell_shares / (sell_shares + shares)) if position else 0):.2f}元, '
                    f'盈亏{p_profit:+.2f}元({p_pct:+.1f}%)'
                )
            else:
                daily_log['action'] = 'SKIP'
                daily_log['action_reason'] = f'卖出信号{sell_score:.1f}分但计算卖出股数为0或超过持仓'

        # 买入逻辑 - 支持建仓和加仓
        elif buy_score >= buy_threshold:
            buy_ratio, _ = calculate_position_size(buy_score, sell_score, position_config)
            # 用 position_size_pct 给信号分数档位加一个上限（系统模式生效）
            if position_size_cap < 1.0:
                buy_ratio = min(buy_ratio, position_size_cap)
            cost_per_share = price
            max_shares = int((cash * buy_ratio) / cost_per_share / 100) * 100  # 100股取整

            daily_log['action'] = 'BUY' if position is None else 'ADD'
            daily_log['action_reason'] = f'买入信号{buy_score:.1f}分≥阈值{buy_threshold:.1f}|{",".join(buy_signals)}'
            daily_log['action_detail'] = f'计划使用{buy_ratio*100:.0f}%资金({cash*buy_ratio:.0f}元)'

            if max_shares > 0:
                shares_before = shares
                shares += max_shares
                cost = max_shares * cost_per_share
                cash -= cost

                # 更新或创建position记录（使用加权平均成本）
                if position is None:
                    # 建仓
                    position = {
                        'entry_date': signal['date'],
                        'entry_price': cost_per_share,
                        'highest_price': cost_per_share,
                        'shares': shares,
                        'cost': cost,
                        'buy_score': buy_score,
                        'buy_ratio': buy_ratio
                    }
                    trade_type = 'BUY'
                    daily_log['action_result'] = f'建仓买入{max_shares}股@{cost_per_share:.2f}元,成本{cost:.2f}元'
                else:
                    # 加仓 - 更新加权平均成本
                    total_cost = position['cost'] + cost
                    total_shares = position['shares'] + max_shares
                    old_avg_price = position['entry_price']
                    new_avg_price = total_cost / total_shares
                    position = {
                        'entry_date': position['entry_date'],  # 保持首次建仓日期
                        'entry_price': new_avg_price,  # 更新加权平均价
                        'highest_price': max(position.get('highest_price', cost_per_share), cost_per_share),
                        'shares': total_shares,
                        'cost': total_cost,
                        'buy_score': max(position.get('buy_score', 0), buy_score),  # 更新最高买入分数
                        'buy_ratio': buy_ratio
                    }
                    trade_type = 'ADD'
                    daily_log['action_result'] = f'加仓买入{max_shares}股@{cost_per_share:.2f}元,成本{cost:.2f}元,均价{old_avg_price:.2f}→{new_avg_price:.2f}'

                trades.append({
                    'type': trade_type,
                    'date': signal['date'],
                    'price': cost_per_share,
                    'shares': max_shares,
                    'cost': cost,
                    'buy_ratio': buy_ratio,
                    'position_size': buy_ratio,
                    'shares_before': shares_before,
                    'shares_after': shares
                })
            else:
                daily_log['action'] = 'SKIP'
                daily_log['action_reason'] = f'买入信号{buy_score:.1f}分但资金不足(现金{cash:.2f}元)'
        else:
            # 没有触发买卖信号
            if buy_score > 0 or sell_score > 0:
                daily_log['action_reason'] = f'买入{buy_score:.1f}分(阈值{buy_threshold:.1f})|卖出{sell_score:.1f}分(阈值{sell_threshold:.1f})'
            else:
                daily_log['action_reason'] = '无买卖信号'

        # 每日日志记录完成
        daily_logs.append(daily_log)

    # 最终平仓
    final_value = cash
    if shares > 0 and position:
        last_price = signals_df.iloc[-1]['close']
        final_value = cash + shares * last_price

    return {
        'code': code,
        'name': name,
        'initial_cash': initial_cash,
        'final_value': final_value,
        'trades': trades,
        'trade_count': len([t for t in trades if t['type'] in ('SELL', 'STOP_LOSS', 'TAKE_PROFIT', 'TRAILING_STOP')]),
        'total_profit': final_value - initial_cash,
        'profit_pct': (final_value - initial_cash) / initial_cash * 100,
        'daily_logs': daily_logs,
        'buy_count': len([t for t in trades if t['type'] in ('BUY', 'ADD')]),
        'sell_count': len([t for t in trades if t['type'] in ('SELL', 'STOP_LOSS', 'TAKE_PROFIT', 'TRAILING_STOP')])
    }


def run_backtest_task(task_id, stock_list, days, buy_threshold, sell_threshold,
                       position_config=None, start_date=None, end_date=None,
                       system_name=None):
    """执行回测任务（后台线程）。

    system_name: 优化方案名（None=手动模式，使用 buy/sell_threshold；非空则加载
    optimization_result.json 中的系统参数，覆盖 buy/sell_threshold 并启用加权评分）。
    """
    # 解析系统参数
    if system_name:
        system_params = resolve_system_params(system_name)
        if system_params:
            params = system_params
        else:
            # 找不到该系统，回退到手动模式
            params = {**DEFAULT_PARAMS, 'buy_threshold': buy_threshold, 'sell_threshold': sell_threshold}
            system_name = None
    else:
        params = {**DEFAULT_PARAMS, 'buy_threshold': buy_threshold, 'sell_threshold': sell_threshold}

    try:
        backtest_tasks[task_id]['status'] = 'running'
        backtest_tasks[task_id]['progress'] = 0
        backtest_tasks[task_id]['message'] = '开始回测...'

        results = []
        skipped = []
        total = len(stock_list)

        for idx, stock in enumerate(stock_list):
            code = stock['code']
            name = stock['name']

            backtest_tasks[task_id]['message'] = f'正在分析 {name}({code})...'
            backtest_tasks[task_id]['current_stock'] = f'{name}({code})'
            backtest_tasks[task_id]['progress'] = int((idx + 1) / total * 100)

            # 获取数据（支持日期范围）
            df = get_stock_data(code, days=days, start_date=start_date, end_date=end_date)
            if df is None or len(df) < 60:
                skipped.append({'code': code, 'name': name, 'reason': '数据不足'})
                continue

            # 计算指标（用系统 params）
            df = calculate_indicators(df, params=params)

            # 检测信号（用系统 params）
            signals = detect_reversal_signals(df, params=params)
            if len(signals) == 0:
                skipped.append({'code': code, 'name': name, 'reason': '无信号'})
                continue

            # 回测（用系统 params）
            result = backtest_stock(code, name, signals, params=params, position_config=position_config)
            results.append(result)

            backtest_tasks[task_id]['progress'] = int((idx + 1) / total * 100)

        # 计算汇总
        total_initial = sum(r['initial_cash'] for r in results)
        total_final = sum(r['final_value'] for r in results)
        total_profit = total_final - total_initial
        avg_profit_pct = total_profit / total_initial * 100 if total_initial > 0 else 0

        win_trades = []
        loss_trades = []
        total_trades_cnt = 0

        for r in results:
            for t in r['trades']:
                if t['type'] in ('SELL', 'STOP_LOSS', 'TAKE_PROFIT', 'TRAILING_STOP'):
                    total_trades_cnt += 1
                    if t.get('profit', 0) > 0:
                        win_trades.append(t['profit_pct'])
                    else:
                        loss_trades.append(t['profit_pct'])

        win_rate = len(win_trades) / total_trades_cnt * 100 if total_trades_cnt > 0 else 0
        avg_win = np.mean(win_trades) if win_trades else 0
        avg_loss = np.mean(loss_trades) if loss_trades else 0

        # 按收益率排序
        results_sorted = sorted(results, key=lambda x: x['profit_pct'], reverse=True)

        backtest_tasks[task_id]['status'] = 'completed'
        backtest_tasks[task_id]['progress'] = 100
        backtest_tasks[task_id]['message'] = '回测完成'
        backtest_tasks[task_id]['results'] = {
            'summary': {
                'total_stocks': len(stock_list),
                'analyzed': len(results),
                'skipped': len(skipped),
                'total_initial': total_initial,
                'total_final': total_final,
                'total_profit': total_profit,
                'avg_profit_pct': avg_profit_pct,
                'total_trades_cnt': total_trades_cnt,
                'win_rate': win_rate,
                'avg_win': avg_win,
                'avg_loss': avg_loss
            },
            'stocks': results_sorted,
            'skipped': skipped,
            'params': {
                'days': days,
                'start_date': start_date,
                'end_date': end_date,
                'buy_threshold': float(params['buy_threshold']),
                'sell_threshold': float(params['sell_threshold']),
                'system_name': system_name,
                'all_params': {k: (float(v) if isinstance(v, (int, float)) else v)
                               for k, v in params.items()},
            }
        }

    except Exception as e:
        backtest_tasks[task_id]['status'] = 'error'
        backtest_tasks[task_id]['message'] = f'错误: {str(e)}'
        backtest_tasks[task_id]['error'] = str(e)


# ============== 路由 ==============

@app.route('/')
def index():
    """首页"""
    return render_template('backtest_ui_v3.html')


@app.route('/api/stock-pools', methods=['GET'])
def get_stock_pools():
    """获取可用的股票池"""
    pools = []

    # 读取持仓
    if Path('持仓.csv').exists():
        try:
            df = pd.read_csv('持仓.csv', encoding='utf-8-sig')
            stocks = []
            for _, row in df.iterrows():
                code = str(row.iloc[0]).zfill(6)
                name = str(row.iloc[1]) if len(row) > 1 else f'股票{code}'
                stocks.append({'code': code, 'name': name})
            pools.append({'name': '持仓.csv', 'stocks': stocks})
        except:
            pass

    # 读取候选股票
    if Path('候选股票.csv').exists():
        try:
            df = pd.read_csv('候选股票.csv', encoding='utf-8-sig')
            stocks = []
            for _, row in df.iterrows():
                code = str(row.iloc[0]).zfill(6)
                name = str(row.iloc[1]) if len(row) > 1 else f'股票{code}'
                stocks.append({'code': code, 'name': name})
            pools.append({'name': '候选股票.csv', 'stocks': stocks})
        except:
            pass

    # 读取回测股票
    if Path('backtest_stocks.csv').exists():
        try:
            df = pd.read_csv('backtest_stocks.csv', encoding='utf-8-sig')
            stocks = []
            for _, row in df.iterrows():
                code = str(row.iloc[0]).zfill(6)
                name = str(row.iloc[1]) if len(row) > 1 else f'股票{code}'
                stocks.append({'code': code, 'name': name})
            pools.append({'name': 'backtest_stocks.csv', 'stocks': stocks})
        except:
            pass

    return jsonify(pools)


@app.route('/api/backtest/start', methods=['POST'])
def start_backtest():
    """启动回测任务"""
    data = request.json
    stocks = data.get('stocks', [])
    days = data.get('days', 365)
    buy_threshold = data.get('buy_threshold', 4)
    sell_threshold = data.get('sell_threshold', 4)
    # 接收仓位配置
    position_config = data.get('position_config', None)
    # 接收日期范围参数
    start_date = data.get('start_date', None)  # 格式: YYYY-MM-DD
    end_date = data.get('end_date', None)      # 格式: YYYY-MM-DD
    # 接收优化方案名
    system_name = data.get('system_name', None)
    if system_name == '' or system_name == 'manual':
        system_name = None

    if len(stocks) > 25:
        return jsonify({'error': '每次回测最多支持25只股票'}), 400

    if len(stocks) == 0:
        return jsonify({'error': '请选择至少一只股票'}), 400

    # 创建任务
    task_id = str(uuid.uuid4())
    backtest_tasks[task_id] = {
        'status': 'pending',
        'progress': 0,
        'message': '任务已创建',
        'results': None
    }

    # 启动后台线程（传递日期范围 + system_name）
    thread = threading.Thread(
        target=run_backtest_task,
        args=(task_id, stocks, days, buy_threshold, sell_threshold,
              position_config, start_date, end_date, system_name)
    )
    thread.start()

    return jsonify({'task_id': task_id})


@app.route('/api/optimization-systems', methods=['GET'])
def get_optimization_systems():
    """获取可用的优化方案列表（来自 stock_data/optimization_result.json）"""
    cache = load_optimization_systems()
    if not cache:
        return jsonify({
            'systems': [],
            'warning': '未找到优化结果文件或文件格式错误',
        })
    systems = []
    for name, sys in cache['by_name'].items():
        systems.append({
            'name': name,
            'description': sys.get('description', ''),
            'applicable_regimes': sys.get('applicable_regimes', []),
            'regime': sys.get('regime'),
            'fitness_scores': sys.get('fitness_scores', {}),
            'confidence': sys.get('confidence'),
            'median_return': sys.get('median_return'),
            'win_rate_above_10pct': sys.get('win_rate_above_10pct'),
            'median_sharpe': sys.get('median_sharpe'),
            'median_max_drawdown': sys.get('median_max_drawdown'),
            'median_holding_days': sys.get('median_holding_days'),
            'num_trades': sys.get('num_trades'),
            'sample_count': sys.get('sample_count'),
            'params': sys.get('params', {}),
        })
    return jsonify({
        'timestamp': cache.get('timestamp'),
        'systems': systems,
    })


@app.route('/api/optimization-systems/<path:name>', methods=['GET'])
def get_optimization_system(name):
    """获取单个优化方案详情"""
    cache = load_optimization_systems()
    if not cache or name not in cache['by_name']:
        return jsonify({'error': f'方案不存在: {name}'}), 404
    sys = cache['by_name'][name]
    return jsonify(sys)


@app.route('/api/backtest/status/<task_id>', methods=['GET'])
def get_backtest_status(task_id):
    """获取回测任务状态"""
    if task_id not in backtest_tasks:
        return jsonify({'error': '任务不存在'}), 404

    task = backtest_tasks[task_id]

    return jsonify({
        'status': task['status'],
        'progress': task.get('progress', 0),
        'message': task.get('message', ''),
        'current_stock': task.get('current_stock', ''),
        'has_results': task.get('results') is not None
    })


@app.route('/api/backtest/results/<task_id>', methods=['GET'])
def get_backtest_results(task_id):
    """获取回测结果"""
    if task_id not in backtest_tasks:
        return jsonify({'error': '任务不存在'}), 404

    task = backtest_tasks[task_id]

    if task.get('results') is None:
        return jsonify({'error': '结果尚未生成'}), 400

    return jsonify(task['results'])


@app.route('/api/stock-detail/<code>', methods=['GET'])
def get_stock_detail(code):
    """获取股票详细数据（K线+指标+买卖点）"""
    days = request.args.get('days', 365, type=int)
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)
    buy_threshold = request.args.get('buy_threshold', 4, type=int)
    sell_threshold = request.args.get('sell_threshold', 4, type=int)
    system_name = request.args.get('system_name', None)
    if system_name in ('', 'manual', 'null'):
        system_name = None

    # 解析参数
    if system_name:
        params = resolve_system_params(system_name)
    else:
        params = {**DEFAULT_PARAMS, 'buy_threshold': buy_threshold, 'sell_threshold': sell_threshold}
    if params is None:
        params = {**DEFAULT_PARAMS, 'buy_threshold': buy_threshold, 'sell_threshold': sell_threshold}

    # 获取数据（支持日期范围）
    df = get_stock_data(code, days=days, start_date=start_date, end_date=end_date)
    if df is None:
        return jsonify({'error': '数据获取失败'}), 404

    # 计算指标
    df = calculate_indicators(df, params=params)

    # 检测信号
    signals = detect_reversal_signals(df, params=params)

    # 准备K线数据
    kline_data = []
    for _, row in df.iterrows():
        kline_data.append({
            'date': row['日期'].strftime('%Y-%m-%d'),
            'open': float(row['开盘']),
            'high': float(row['最高']),
            'low': float(row['最低']),
            'close': float(row['收盘']),
            'volume': float(row['成交量']),
            'ma5': float(row['MA5']) if pd.notna(row['MA5']) else None,
            'ma10': float(row['MA10']) if pd.notna(row['MA10']) else None,
            'ma20': float(row['MA20']) if pd.notna(row['MA20']) else None,
            'ma60': float(row['MA60']) if pd.notna(row['MA60']) else None,
            'bb_upper': float(row['BB_Upper']) if pd.notna(row['BB_Upper']) else None,
            'bb_lower': float(row['BB_Lower']) if pd.notna(row['BB_Lower']) else None,
            'rsi': float(row['RSI14']) if pd.notna(row['RSI14']) else 50,
            'kdj_k': float(row['K']) if pd.notna(row['K']) else 50,
            'kdj_d': float(row['D']) if pd.notna(row['D']) else 50,
            'kdj_j': float(row['J']) if pd.notna(row['J']) else 50,
            'macd': float(row['MACD']) if pd.notna(row['MACD']) else 0
        })

    # 找出买卖点
    buy_points = []
    sell_points = []
    for _, signal in signals.iterrows():
        if signal['buy_score'] >= buy_threshold:
            buy_points.append({
                'date': signal['date'],
                'price': signal['close'],
                'signals': signal['buy_signals'],
                'score': signal['buy_score']
            })
        if signal['sell_score'] >= sell_threshold:
            sell_points.append({
                'date': signal['date'],
                'price': signal['close'],
                'signals': signal['sell_signals'],
                'score': signal['sell_score']
            })

    return jsonify({
        'code': code,
        'kline': kline_data,
        'buy_points': buy_points,
        'sell_points': sell_points,
        'buy_threshold': buy_threshold,
        'sell_threshold': sell_threshold
    })


@app.route('/api/stock-logs/<code>', methods=['GET'])
def get_stock_logs(code):
    """获取股票回测详细日志"""
    days = request.args.get('days', 365, type=int)
    start_date = request.args.get('start_date', None)
    end_date = request.args.get('end_date', None)
    buy_threshold = request.args.get('buy_threshold', 4, type=int)
    sell_threshold = request.args.get('sell_threshold', 4, type=int)
    system_name = request.args.get('system_name', None)
    if system_name in ('', 'manual', 'null'):
        system_name = None

    if system_name:
        params = resolve_system_params(system_name)
    else:
        params = {**DEFAULT_PARAMS, 'buy_threshold': buy_threshold, 'sell_threshold': sell_threshold}
    if params is None:
        params = {**DEFAULT_PARAMS, 'buy_threshold': buy_threshold, 'sell_threshold': sell_threshold}

    # 获取数据（支持日期范围）
    df = get_stock_data(code, days=days, start_date=start_date, end_date=end_date)
    if df is None:
        return jsonify({'error': '数据获取失败'}), 404

    # 计算指标
    df = calculate_indicators(df, params=params)

    # 检测信号
    signals = detect_reversal_signals(df, params=params)

    # 执行回测获取详细日志
    result = backtest_stock(code, '', signals, params=params)

    return jsonify({
        'code': code,
        'logs': result.get('daily_logs', [])
    })


@app.route('/api/stock-name/<code>', methods=['GET'])
def get_stock_name_dict():
    """获取股票代码到名称的映射（带缓存）"""
    global stock_name_cache, stock_name_cache_time

    now = datetime.now()
    # 缓存1小时有效
    if stock_name_cache is not None and stock_name_cache_time is not None:
        if (now - stock_name_cache_time).total_seconds() < 3600:
            return stock_name_cache

    try:
        # 获取所有A股的代码和名称
        stock_info = ak.stock_info_a_code_name()
        if stock_info is not None and len(stock_info) > 0:
            # 转换为字典 {code: name}
            stock_dict = dict(zip(stock_info['code'], stock_info['name']))
            stock_name_cache = stock_dict
            stock_name_cache_time = now
            print(f"已更新股票名称缓存，共 {len(stock_dict)} 只股票")
            return stock_dict
    except Exception as e:
        print(f"获取股票名称列表失败: {e}")

    return {}


@app.route('/api/stock-name/<code>', methods=['GET'])
def get_stock_name(code):
    """根据代码查找股票名称"""
    code = code.zfill(6)

    # 1. 先从各股票池中查找
    for pool_file in ['持仓.csv', '候选股票.csv', 'backtest_stocks.csv']:
        if Path(pool_file).exists():
            try:
                df = pd.read_csv(pool_file, encoding='utf-8-sig')
                for _, row in df.iterrows():
                    stock_code = str(row.iloc[0]).zfill(6)
                    if stock_code == code:
                        return jsonify({'code': code, 'name': str(row.iloc[1]) if len(row) > 1 else f'股票{code}'})
            except:
                pass

    # 2. 从缓存的股票名称映射中查找
    stock_dict = get_stock_name_dict()
    if code in stock_dict:
        return jsonify({'code': code, 'name': stock_dict[code]})

    # 3. 返回默认名称
    return jsonify({'code': code, 'name': f'股票{code}'})


if __name__ == '__main__':
    # 创建templates目录
    Path('templates').mkdir(exist_ok=True)

    print("=" * 60)
    print("   转折点策略回测系统 - Web UI v3")
    print("=" * 60)
    print()
    print("新增功能: 仓位管理")
    print("=" * 60)
    print()
    print("启动服务器...")
    print("请在浏览器中打开: http://localhost:5000")
    print()
    print("按 Ctrl+C 停止服务器")
    print("=" * 60)

    app.run(host='0.0.0.0', port=5000, debug=False)
