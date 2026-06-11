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


def calculate_indicators(df):
    """计算技术指标"""
    close = df['收盘'].values
    high = df['最高'].values
    low = df['最低'].values

    # MA
    df['MA5'] = df['收盘'].rolling(5).mean()
    df['MA10'] = df['收盘'].rolling(10).mean()
    df['MA20'] = df['收盘'].rolling(20).mean()
    df['MA60'] = df['收盘'].rolling(60).mean()

    # 成交量MA
    df['Vol_MA5'] = df['成交量'].rolling(5).mean()
    df['Vol_MA20'] = df['成交量'].rolling(20).mean()

    # RSI
    delta = pd.Series(close).diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['RSI14'] = 100 - (100 / (1 + rs))

    # KDJ
    low_n = pd.Series(low).rolling(9).min()
    high_n = pd.Series(high).rolling(9).max()
    rsv = (pd.Series(close) - low_n) / (high_n - low_n) * 100
    df['K'] = rsv.ewm(alpha=1/3).mean()
    df['D'] = df['K'].ewm(alpha=1/3).mean()
    df['J'] = 3 * df['K'] - 2 * df['D']

    # MACD
    ema12 = pd.Series(close).ewm(span=12).mean()
    ema26 = pd.Series(close).ewm(span=26).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_Signal'] = df['MACD'].ewm(span=9).mean()
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']

    # ATR
    high_low = pd.Series(high) - pd.Series(low)
    high_close = np.abs(pd.Series(high) - pd.Series(close).shift(1))
    low_close = np.abs(pd.Series(low) - pd.Series(close).shift(1))
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['ATR'] = tr.rolling(14).mean()

    # 布林带
    df['BB_Mid'] = df['收盘'].rolling(20).mean()
    bb_std = df['收盘'].rolling(20).std()
    df['BB_Upper'] = df['BB_Mid'] + 2 * bb_std
    df['BB_Lower'] = df['BB_Mid'] - 2 * bb_std

    return df


def detect_reversal_signals(df, buy_threshold=4, sell_threshold=4):
    """检测转折点信号"""
    signals = []

    for i in range(60, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]

        buy_signals = []
        buy_score = 0

        # 买入信号
        if row['RSI14'] < 30:
            buy_signals.append(f"RSI超卖({row['RSI14']:.1f})")
            buy_score += 2
        elif row['RSI14'] < 40:
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

        # 卖出信号
        sell_signals = []
        sell_score = 0

        if row['RSI14'] > 80:
            sell_signals.append(f"RSI严重超买({row['RSI14']:.1f})")
            sell_score += 3
        elif row['RSI14'] > 70:
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
            'buy_score': buy_score,
            'sell_signals': sell_signals,
            'sell_score': sell_score,
            'rsi': float(row['RSI14']) if pd.notna(row['RSI14']) else 50,
            'j': float(row['J']) if pd.notna(row['J']) else 50,
            'macd': float(row['MACD']) if pd.notna(row['MACD']) else 0
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


def backtest_stock(code, name, signals_df, buy_threshold=4, sell_threshold=4, position_config=None):
    """对单只股票进行回测（带仓位管理）"""
    initial_cash = 100000
    cash = initial_cash
    shares = 0
    trades = []
    position = None
    daily_logs = []  # 详细日志

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

        # 卖出逻辑 - 优先处理卖出信号
        if sell_score >= sell_threshold and shares > 0:
            buy_ratio, sell_ratio = calculate_position_size(buy_score, sell_score, position_config)
            sell_shares = int(shares * sell_ratio / 100) * 100  # 100股取整

            daily_log['action'] = 'SELL'
            daily_log['action_reason'] = f'卖出信号{sell_score}分≥阈值{sell_threshold}|{",".join(sell_signals)}'
            daily_log['action_detail'] = f'计划卖出{sell_ratio*100:.0f}%仓位'

            if sell_shares > 0 and sell_shares <= shares:
                revenue = sell_shares * price
                cash += revenue

                # 计算卖出部分的成本（按比例分摊总成本）
                cost_of_sold = position['cost'] * (sell_shares / shares)
                profit = revenue - cost_of_sold
                profit_pct = profit / cost_of_sold * 100 if cost_of_sold > 0 else 0

                trades.append({
                    'type': 'SELL',
                    'date': signal['date'],
                    'price': price,
                    'shares': sell_shares,
                    'revenue': revenue,
                    'profit': profit,
                    'profit_pct': profit_pct,
                    'sell_ratio': sell_ratio,
                    'entry_price': position['entry_price'],
                    'shares_before': shares,
                    'shares_after': shares - sell_shares
                })

                daily_log['action_result'] = f'卖出{sell_shares}股@{price:.2f}元,收入{revenue:.2f}元,盈亏{profit:+.2f}元({profit_pct:+.1f}%)'

                shares -= sell_shares

                if shares == 0:
                    position = None
                else:
                    # 更新剩余持仓的成本
                    position['cost'] -= cost_of_sold
                    position['shares'] = shares
            else:
                daily_log['action'] = 'SKIP'
                daily_log['action_reason'] = f'卖出信号{sell_score}分但计算卖出股数为0或超过持仓'

        # 买入逻辑 - 支持建仓和加仓
        elif buy_score >= buy_threshold:
            buy_ratio, _ = calculate_position_size(buy_score, sell_score, position_config)
            cost_per_share = price
            max_shares = int((cash * buy_ratio) / cost_per_share / 100) * 100  # 100股取整

            daily_log['action'] = 'BUY' if position is None else 'ADD'
            daily_log['action_reason'] = f'买入信号{buy_score}分≥阈值{buy_threshold}|{",".join(buy_signals)}'
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
                        'entry_price': total_cost / total_shares,  # 更新加权平均价
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
                daily_log['action_reason'] = f'买入信号{buy_score}分但资金不足(现金{cash:.2f}元)'
        else:
            # 没有触发买卖信号
            if buy_score > 0 or sell_score > 0:
                daily_log['action_reason'] = f'买入{buy_score}分(阈值{buy_threshold})|卖出{sell_score}分(阈值{sell_threshold})'
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
        'trade_count': len([t for t in trades if t['type'] == 'SELL']),
        'total_profit': final_value - initial_cash,
        'profit_pct': (final_value - initial_cash) / initial_cash * 100,
        'daily_logs': daily_logs,
        'buy_count': len([t for t in trades if t['type'] in ('BUY', 'ADD')]),
        'sell_count': len([t for t in trades if t['type'] == 'SELL'])
    }


def run_backtest_task(task_id, stock_list, days, buy_threshold, sell_threshold, position_config=None, start_date=None, end_date=None):
    """执行回测任务（后台线程）"""
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

            # 计算指标
            df = calculate_indicators(df)

            # 检测信号
            signals = detect_reversal_signals(df, buy_threshold, sell_threshold)
            if len(signals) == 0:
                skipped.append({'code': code, 'name': name, 'reason': '无信号'})
                continue

            # 回测
            result = backtest_stock(code, name, signals, buy_threshold, sell_threshold, position_config)
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
                if t['type'] == 'SELL':
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
                'buy_threshold': buy_threshold,
                'sell_threshold': sell_threshold
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

    # 启动后台线程（传递日期范围参数）
    thread = threading.Thread(
        target=run_backtest_task,
        args=(task_id, stocks, days, buy_threshold, sell_threshold, position_config, start_date, end_date)
    )
    thread.start()

    return jsonify({'task_id': task_id})


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

    # 获取数据（支持日期范围）
    df = get_stock_data(code, days=days, start_date=start_date, end_date=end_date)
    if df is None:
        return jsonify({'error': '数据获取失败'}), 404

    # 计算指标
    df = calculate_indicators(df)

    # 检测信号
    signals = detect_reversal_signals(df, buy_threshold, sell_threshold)

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

    # 获取数据（支持日期范围）
    df = get_stock_data(code, days=days, start_date=start_date, end_date=end_date)
    if df is None:
        return jsonify({'error': '数据获取失败'}), 404

    # 计算指标
    df = calculate_indicators(df)

    # 检测信号
    signals = detect_reversal_signals(df, buy_threshold, sell_threshold)

    # 执行回测获取详细日志
    result = backtest_stock(code, '', signals, buy_threshold, sell_threshold)

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
