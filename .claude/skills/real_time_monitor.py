# -*- coding: utf-8 -*-
"""
实时监控模块 - 完整版
Real-Time Monitor Module

提供股票价格监控、信号提醒、告警推送等功能
支持多种监控条件和告警方式
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path


class AlertType(Enum):
    """告警类型"""
    PRICE_ABOVE = "price_above"         # 价格突破上限
    PRICE_BELOW = "price_below"         # 价格跌破下限
    CHANGE_UP = "change_up"             # 涨幅超限
    CHANGE_DOWN = "change_down"         # 跌幅超限
    BREAKOUT_HIGH = "breakout_high"     # 突破N日高点
    BREAKOUT_LOW = "breakout_low"       # 跌破N日低点
    SIGNAL_BUY = "signal_buy"           # 买入信号
    SIGNAL_SELL = "signal_sell"         # 卖出信号
    VOLUME_SURGE = "volume_surge"       # 成交量放大


class AlertPriority(Enum):
    """告警优先级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


@dataclass
class AlertCondition:
    """告警条件"""
    alert_type: AlertType
    threshold: float = 0.0          # 阈值
    period: int = 0                 # 周期（用于突破判断）
    enabled: bool = True            # 是否启用
    priority: AlertPriority = AlertPriority.MEDIUM
    message_template: str = ""      # 消息模板

    def to_dict(self) -> dict:
        return {
            'alert_type': self.alert_type.value,
            'threshold': self.threshold,
            'period': self.period,
            'enabled': self.enabled,
            'priority': self.priority.value,
            'message_template': self.message_template
        }

    @staticmethod
    def from_dict(data: dict) -> 'AlertCondition':
        return AlertCondition(
            alert_type=AlertType(data['alert_type']),
            threshold=data.get('threshold', 0.0),
            period=data.get('period', 0),
            enabled=data.get('enabled', True),
            priority=AlertPriority(data.get('priority', 'medium')),
            message_template=data.get('message_template', '')
        )


@dataclass
class Alert:
    """告警记录"""
    id: str
    symbol: str
    name: str
    alert_type: AlertType
    message: str
    priority: AlertPriority
    timestamp: datetime
    data: Dict[str, Any] = field(default_factory=dict)
    is_read: bool = False

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'symbol': self.symbol,
            'name': self.name,
            'alert_type': self.alert_type.value,
            'message': self.message,
            'priority': self.priority.value,
            'timestamp': self.timestamp.isoformat(),
            'data': self.data,
            'is_read': self.is_read
        }


@dataclass
class MonitorStock:
    """监控股票"""
    symbol: str
    name: str
    conditions: List[AlertCondition] = field(default_factory=list)
    last_check: Optional[datetime] = None
    last_price: Optional[float] = None
    last_high: Optional[float] = None
    last_low: Optional[float] = None

    def add_condition(self, condition: AlertCondition):
        """添加监控条件"""
        self.conditions.append(condition)

    def remove_condition(self, alert_type: AlertType):
        """移除监控条件"""
        self.conditions = [c for c in self.conditions if c.alert_type != alert_type]

    def to_dict(self) -> dict:
        return {
            'symbol': self.symbol,
            'name': self.name,
            'conditions': [c.to_dict() for c in self.conditions],
            'last_check': self.last_check.isoformat() if self.last_check else None,
            'last_price': self.last_price
        }


class RealTimeMonitor:
    """实时监控器"""

    def __init__(self, data_dir: str = None):
        """
        初始化实时监控器

        Args:
            data_dir: 数据存储目录
        """
        self.data_dir = data_dir or "monitor_data"
        self.stocks: Dict[str, MonitorStock] = {}
        self.alerts: List[Alert] = []
        self.alert_callbacks: List[Callable] = []

        # 导入数据获取模块
        from stock_data_fetcher import StockDataFetcher
        from signal_generator import SignalGenerator

        self.fetcher = StockDataFetcher()
        self.signal_generator = SignalGenerator()

    def add_stock(self, symbol: str, name: str = "",
                 conditions: List[AlertCondition] = None) -> bool:
        """
        添加监控股票

        Args:
            symbol: 股票代码
            name: 股票名称
            conditions: 监控条件列表

        Returns:
            是否成功
        """
        if symbol in self.stocks:
            return False

        if not name:
            from stock_list_manager import get_stock_name
            name = get_stock_name(symbol)

        monitor_stock = MonitorStock(
            symbol=symbol,
            name=name,
            conditions=conditions or []
        )

        self.stocks[symbol] = monitor_stock
        return True

    def remove_stock(self, symbol: str) -> bool:
        """
        移除监控股票

        Args:
            symbol: 股票代码

        Returns:
            是否成功
        """
        if symbol not in self.stocks:
            return False

        del self.stocks[symbol]
        return True

    def add_condition(self, symbol: str, condition: AlertCondition) -> bool:
        """
        为股票添加监控条件

        Args:
            symbol: 股票代码
            condition: 告警条件

        Returns:
            是否成功
        """
        if symbol not in self.stocks:
            return False

        self.stocks[symbol].add_condition(condition)
        return True

    def remove_condition(self, symbol: str, alert_type: AlertType) -> bool:
        """
        移除股票的监控条件

        Args:
            symbol: 股票代码
            alert_type: 告警类型

        Returns:
            是否成功
        """
        if symbol not in self.stocks:
            return False

        self.stocks[symbol].remove_condition(alert_type)
        return True

    def check_conditions(self, symbol: str) -> List[Alert]:
        """
        检查股票的所有监控条件

        Args:
            symbol: 股票代码

        Returns:
            触发的告警列表
        """
        if symbol not in self.stocks:
            return []

        monitor_stock = self.stocks[symbol]
        triggered_alerts = []

        # 获取最新数据
        try:
            data = self.fetcher.get_quote_data(symbol, days=120)
            if data is None or len(data) == 0:
                return triggered_alerts

            latest = data.iloc[-1]

            # 更新监控信息
            monitor_stock.last_check = datetime.now()
            monitor_stock.last_price = latest['收盘']
            monitor_stock.last_high = data['最高'].max()
            monitor_stock.last_low = data['最低'].min()

        except Exception as e:
            return triggered_alerts

        # 检查每个条件
        for condition in monitor_stock.conditions:
            if not condition.enabled:
                continue

            alert = self._check_single_condition(
                symbol, monitor_stock.name, condition, data, latest
            )

            if alert:
                triggered_alerts.append(alert)
                self.alerts.append(alert)

        # 触发回调
        for alert in triggered_alerts:
            self._trigger_callbacks(alert)

        return triggered_alerts

    def _check_single_condition(self, symbol: str, name: str,
                               condition: AlertCondition,
                               data: pd.DataFrame, latest: pd.Series) -> Optional[Alert]:
        """检查单个条件"""
        current_price = latest['收盘']
        alert_type = condition.alert_type

        alert = None

        # 价格突破上限
        if alert_type == AlertType.PRICE_ABOVE:
            if current_price > condition.threshold:
                message = f"{name}({symbol}) 价格突破上限: {current_price:.2f} > {condition.threshold:.2f}"
                alert = self._create_alert(symbol, name, condition, message, latest)

        # 价格跌破下限
        elif alert_type == AlertType.PRICE_BELOW:
            if current_price < condition.threshold:
                message = f"{name}({symbol}) 价格跌破下限: {current_price:.2f} < {condition.threshold:.2f}"
                alert = self._create_alert(symbol, name, condition, message, latest)

        # 涨幅超限
        elif alert_type == AlertType.CHANGE_UP:
            change_pct = (latest['涨跌幅'] if '涨跌幅' in latest else
                          (current_price / data['收盘'].iloc[-2] - 1) * 100)
            if change_pct > condition.threshold:
                message = f"{name}({symbol}) 涨幅超限: {change_pct:+.2f}% > {condition.threshold:.2f}%"
                alert = self._create_alert(symbol, name, condition, message, latest)

        # 跌幅超限
        elif alert_type == AlertType.CHANGE_DOWN:
            change_pct = (latest['涨跌幅'] if '涨跌幅' in latest else
                          (current_price / data['收盘'].iloc[-2] - 1) * 100)
            if change_pct < -condition.threshold:
                message = f"{name}({symbol}) 跌幅超限: {change_pct:+.2f}% < -{condition.threshold:.2f}%"
                alert = self._create_alert(symbol, name, condition, message, latest)

        # 突破N日高点
        elif alert_type == AlertType.BREAKOUT_HIGH:
            period = condition.period or 20
            high_period = data['最高'].iloc[-period:].max()
            if current_price > high_period:
                message = f"{name}({symbol}) 突破{period}日高点: {current_price:.2f} > {high_period:.2f}"
                alert = self._create_alert(symbol, name, condition, message, latest)

        # 跌破N日低点
        elif alert_type == AlertType.BREAKOUT_LOW:
            period = condition.period or 20
            low_period = data['最低'].iloc[-period:].min()
            if current_price < low_period:
                message = f"{name}({symbol}) 跌破{period}日低点: {current_price:.2f} < {low_period:.2f}"
                alert = self._create_alert(symbol, name, condition, message, latest)

        # 买入信号
        elif alert_type == AlertType.SIGNAL_BUY:
            data_with_indicators = self.fetcher.calculate_technical_indicators(data.copy())
            signal = self.signal_generator.get_latest_signal(data_with_indicators)

            if signal['buy_signal']:
                message = f"{name}({symbol}) 买入信号: 强度 {signal['strength']:+.1f}"
                alert = self._create_alert(symbol, name, condition, message, latest, signal)

        # 卖出信号
        elif alert_type == AlertType.SIGNAL_SELL:
            data_with_indicators = self.fetcher.calculate_technical_indicators(data.copy())
            signal = self.signal_generator.get_latest_signal(data_with_indicators)

            if signal['sell_signal']:
                message = f"{name}({symbol}) 卖出信号: 强度 {signal['strength']:+.1f}"
                alert = self._create_alert(symbol, name, condition, message, latest, signal)

        # 成交量放大
        elif alert_type == AlertType.VOLUME_SURGE:
            if '成交量' in latest:
                avg_volume = data['成交量'].iloc[-20:].mean()
                volume_ratio = latest['成交量'] / avg_volume if avg_volume > 0 else 1

                if volume_ratio > condition.threshold:
                    message = f"{name}({symbol}) 成交量放大: {volume_ratio:.1f}倍 > {condition.threshold:.1f}倍"
                    alert = self._create_alert(symbol, name, condition, message, latest)

        return alert

    def _create_alert(self, symbol: str, name: str, condition: AlertCondition,
                     message: str, latest: pd.Series, extra_data: dict = None) -> Alert:
        """创建告警"""
        alert_id = f"{symbol}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

        data = {
            'price': latest['收盘'],
            'change': latest.get('涨跌幅', 0),
            'volume': latest.get('成交量', 0),
            'high': latest.get('最高', latest['收盘']),
            'low': latest.get('最低', latest['收盘'])
        }

        if extra_data:
            data.update(extra_data)

        return Alert(
            id=alert_id,
            symbol=symbol,
            name=name,
            alert_type=condition.alert_type,
            message=message,
            priority=condition.priority,
            timestamp=datetime.now(),
            data=data
        )

    def check_all_stocks(self) -> Dict[str, List[Alert]]:
        """
        检查所有监控股票

        Returns:
            {股票代码: 告警列表}
        """
        all_alerts = {}

        for symbol in self.stocks.keys():
            alerts = self.check_conditions(symbol)
            if alerts:
                all_alerts[symbol] = alerts

        return all_alerts

    def send_alert(self, alert: Alert) -> bool:
        """
        发送告警

        Args:
            alert: 告警对象

        Returns:
            是否成功
        """
        # 打印告警
        priority_str = f"[{alert.priority.value.upper()}]"
        print(f"{priority_str} {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')} - {alert.message}")

        # 这里可以扩展其他发送方式
        # - 邮件
        # - 微信
        # - 钉钉
        # - Telegram

        return True

    def register_callback(self, callback: Callable[[Alert], None]):
        """
        注册告警回调函数

        Args:
            callback: 回调函数，接收Alert参数
        """
        self.alert_callbacks.append(callback)

    def _trigger_callbacks(self, alert: Alert):
        """触发所有回调函数"""
        for callback in self.alert_callbacks:
            try:
                callback(alert)
            except Exception as e:
                print(f"Callback error: {e}")

    def get_alert_history(self, symbol: str = None,
                         unread_only: bool = False,
                         limit: int = 100) -> List[Alert]:
        """
        获取告警历史

        Args:
            symbol: 股票代码（None表示全部）
            unread_only: 只获取未读告警
            limit: 返回数量限制

        Returns:
            告警列表
        """
        alerts = self.alerts

        if symbol:
            alerts = [a for a in alerts if a.symbol == symbol]

        if unread_only:
            alerts = [a for a in alerts if not a.is_read]

        # 按时间倒序
        alerts.sort(key=lambda a: a.timestamp, reverse=True)

        return alerts[:limit]

    def mark_as_read(self, alert_id: str) -> bool:
        """
        标记告警为已读

        Args:
            alert_id: 告警ID

        Returns:
            是否成功
        """
        for alert in self.alerts:
            if alert.id == alert_id:
                alert.is_read = True
                return True
        return False

    def mark_all_as_read(self, symbol: str = None) -> int:
        """
        标记所有告警为已读

        Args:
            symbol: 股票代码（None表示全部）

        Returns:
            标记数量
        """
        count = 0
        for alert in self.alerts:
            if symbol is None or alert.symbol == symbol:
                if not alert.is_read:
                    alert.is_read = True
                    count += 1
        return count

    def get_monitor_status(self) -> Dict:
        """
        获取监控状态

        Returns:
            状态字典
        """
        total_stocks = len(self.stocks)
        total_conditions = sum(len(s.conditions) for s in self.stocks.values())
        unread_alerts = sum(1 for a in self.alerts if not a.is_read)

        # 按类型统计告警
        alert_types = {}
        for alert in self.alerts:
            alert_type = alert.alert_type.value
            alert_types[alert_type] = alert_types.get(alert_type, 0) + 1

        return {
            'total_stocks': total_stocks,
            'total_conditions': total_conditions,
            'total_alerts': len(self.alerts),
            'unread_alerts': unread_alerts,
            'alert_types': alert_types,
            'stocks': [
                {
                    'symbol': s.symbol,
                    'name': s.name,
                    'conditions': len(s.conditions),
                    'last_check': s.last_check.isoformat() if s.last_check else None
                }
                for s in self.stocks.values()
            ]
        }

    def generate_monitor_report(self, symbol: str = None) -> str:
        """
        生成监控报告

        Args:
            symbol: 股票代码（None表示全部）

        Returns:
            报告文本
        """
        status = self.get_monitor_status()

        lines = []
        lines.append("=" * 70)
        lines.append("                      监控状态报告")
        lines.append("=" * 70)
        lines.append("")

        lines.append("【总体概况】")
        lines.append(f"  监控股票: {status['total_stocks']} 只")
        lines.append(f"  监控条件: {status['total_conditions']} 个")
        lines.append(f"  告警总数: {status['total_alerts']} 条")
        lines.append(f"  未读告警: {status['unread_alerts']} 条")
        lines.append("")

        lines.append("【监控股票】")
        for stock in status['stocks']:
            last_check_str = stock['last_check'][:19] if stock['last_check'] else "未检查"
            lines.append(f"  {stock['symbol']} {stock['name']}")
            lines.append(f"    条件数: {stock['conditions']}")
            lines.append(f"    最后检查: {last_check_str}")
            lines.append("")

        lines.append("【告警统计】")
        for alert_type, count in status['alert_types'].items():
            lines.append(f"  {alert_type}: {count} 条")

        lines.append("")

        lines.append("=" * 70)

        return "\n".join(lines)

    def save_monitor_data(self, filepath: str = None) -> bool:
        """
        保存监控数据

        Args:
            filepath: 保存路径

        Returns:
            是否成功
        """
        if filepath is None:
            filepath = f"{self.data_dir}/monitor_data.json"

        import os
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        data = {
            'stocks': {k: v.to_dict() for k, v in self.stocks.items()},
            'alerts': [a.to_dict() for a in self.alerts[-1000:]]  # 保存最近1000条
        }

        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"Save failed: {e}")
            return False

    def load_monitor_data(self, filepath: str = None) -> bool:
        """
        加载监控数据

        Args:
            filepath: 文件路径

        Returns:
            是否成功
        """
        if filepath is None:
            filepath = f"{self.data_dir}/monitor_data.json"

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 加载股票
            for symbol, stock_data in data.get('stocks', {}).items():
                monitor_stock = MonitorStock(
                    symbol=stock_data['symbol'],
                    name=stock_data['name'],
                    conditions=[
                        AlertCondition.from_dict(c) for c in stock_data.get('conditions', [])
                    ]
                )
                if stock_data.get('last_check'):
                    monitor_stock.last_check = datetime.fromisoformat(stock_data['last_check'])
                monitor_stock.last_price = stock_data.get('last_price')
                self.stocks[symbol] = monitor_stock

            # 加载告警
            for alert_data in data.get('alerts', []):
                alert = Alert(
                    id=alert_data['id'],
                    symbol=alert_data['symbol'],
                    name=alert_data['name'],
                    alert_type=AlertType(alert_data['alert_type']),
                    message=alert_data['message'],
                    priority=AlertPriority(alert_data['priority']),
                    timestamp=datetime.fromisoformat(alert_data['timestamp']),
                    data=alert_data.get('data', {}),
                    is_read=alert_data.get('is_read', False)
                )
                self.alerts.append(alert)

            return True

        except Exception as e:
            print(f"Load failed: {e}")
            return False


# 便捷函数
def create_price_alert(symbol: str, upper: float = None, lower: float = None):
    """创建价格告警条件"""
    monitor = RealTimeMonitor()

    name = symbol  # 可以通过get_stock_name获取名称
    monitor.add_stock(symbol, name)

    if upper is not None:
        condition = AlertCondition(
            alert_type=AlertType.PRICE_ABOVE,
            threshold=upper,
            priority=AlertPriority.HIGH,
            message_template=f"{symbol}价格突破{upper:.2f}元"
        )
        monitor.add_condition(symbol, condition)

    if lower is not None:
        condition = AlertCondition(
            alert_type=AlertType.PRICE_BELOW,
            threshold=lower,
            priority=AlertPriority.HIGH,
            message_template=f"{symbol}价格跌破{lower:.2f}元"
        )
        monitor.add_condition(symbol, condition)

    return monitor


def create_signal_alert(symbol: str):
    """创建信号告警"""
    monitor = RealTimeMonitor()

    from stock_list_manager import get_stock_name
    name = get_stock_name(symbol)
    monitor.add_stock(symbol, name)

    # 买入信号
    buy_condition = AlertCondition(
        alert_type=AlertType.SIGNAL_BUY,
        priority=AlertPriority.MEDIUM
    )
    monitor.add_condition(symbol, buy_condition)

    # 卖出信号
    sell_condition = AlertCondition(
        alert_type=AlertType.SIGNAL_SELL,
        priority=AlertPriority.MEDIUM
    )
    monitor.add_condition(symbol, sell_condition)

    return monitor


if __name__ == "__main__":
    print("Real-Time Monitor - Complete Version v1.0")
    print("\nAlert Types:")
    print("- Price Above/Below: 价格突破/跌破")
    print("- Change Up/Down: 涨跌幅超限")
    print("- Breakout High/Low: 突破N日高低点")
    print("- Signal Buy/Sell: 买卖信号")
    print("- Volume Surge: 成交量放大")
    print("\nFeatures:")
    print("- add_stock(): 添加监控股票")
    print("- check_conditions(): 检查条件")
    print("- send_alert(): 发送告警")
    print("- generate_monitor_report(): 生成报告")
