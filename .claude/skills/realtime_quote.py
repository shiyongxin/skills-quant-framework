# -*- coding: utf-8 -*-
"""
实时股价查询模块
Real-Time Quote Module

使用腾讯财经API获取实时股价行情
稳定、快速、免费
"""

import requests
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional, Union
from dataclasses import dataclass
import time


@dataclass
class RealTimeQuote:
    """实时行情数据"""
    code: str           # 股票代码
    name: str           # 股票名称
    price: float        # 当前价
    pre_close: float    # 昨收价
    change: float       # 涨跌额
    change_pct: float   # 涨跌幅%
    open: float         # 开盘价
    high: float         # 最高价
    low: float          # 最低价
    volume: float       # 成交量(手)
    amount: float       # 成交额(元)
    timestamp: datetime = None

    def to_dict(self) -> dict:
        return {
            'code': self.code,
            'name': self.name,
            'price': self.price,
            'pre_close': self.pre_close,
            'change': self.change,
            'change_pct': self.change_pct,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'volume': self.volume,
            'amount': self.amount,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None
        }


class RealTimeQuoteAPI:
    """实时行情API"""

    # 腾讯财经API地址
    TENCENT_API_URL = "http://qt.gtimg.cn/q="

    def __init__(self, timeout: int = 10):
        """
        初始化

        Args:
            timeout: 请求超时时间(秒)
        """
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def _format_code(self, code: str) -> str:
        """
        格式化股票代码

        Args:
            code: 6位股票代码

        Returns:
            带前缀的完整代码 (如: sz002236, sh600519)
        """
        code = str(code).strip().zfill(6)

        if code.startswith('6'):
            return f'sh{code}'  # 上海
        elif code.startswith('8') or code.startswith('4'):
            return f'bj{code}'  # 北京
        else:
            return f'sz{code}'  # 深圳

    def get_quote(self, code: str) -> Optional[RealTimeQuote]:
        """
        获取单只股票实时行情

        Args:
            code: 股票代码 (6位数字)

        Returns:
            RealTimeQuote 对象，失败返回 None
        """
        formatted_code = self._format_code(code)

        try:
            url = f"{self.TENCENT_API_URL}{formatted_code}"
            response = self.session.get(url, timeout=self.timeout)
            response.encoding = 'gbk'

            if response.status_code != 200:
                return None

            content = response.text.strip()

            # 解析返回数据
            return self._parse_quote(formatted_code, content)

        except Exception as e:
            print(f"获取 {code} 行情失败: {e}")
            return None

    def get_quotes(self, codes: List[str]) -> Dict[str, RealTimeQuote]:
        """
        批量获取股票实时行情

        Args:
            codes: 股票代码列表

        Returns:
            {代码: RealTimeQuote} 字典
        """
        # 格式化代码
        formatted_codes = [self._format_code(c) for c in codes]
        query_str = ','.join(formatted_codes)

        try:
            url = f"{self.TENCENT_API_URL}{query_str}"
            response = self.session.get(url, timeout=self.timeout)
            response.encoding = 'gbk'

            if response.status_code != 200:
                return {}

            content = response.text.strip()

            # 解析每只股票
            results = {}
            lines = content.split('\n')

            for i, line in enumerate(lines):
                if 'v_' in line:
                    code = codes[i] if i < len(codes) else formatted_codes[i]
                    quote = self._parse_quote(formatted_codes[i], line)
                    if quote:
                        results[code] = quote

            return results

        except Exception as e:
            print(f"批量获取行情失败: {e}")
            return {}

    def get_quotes_from_csv(self, csv_path: str) -> Dict[str, RealTimeQuote]:
        """
        从CSV文件读取股票并获取实时行情

        CSV格式:
        股票代码,股票名称,持股数量,成本价
        002078,太阳纸业,300,6.965

        Args:
            csv_path: CSV文件路径

        Returns:
            {代码: RealTimeQuote} 字典
        """
        try:
            df = pd.read_csv(csv_path, encoding='utf-8-sig')

            # 获取股票代码列
            code_col = None
            for col in ['股票代码', 'code', '代码']:
                if col in df.columns:
                    code_col = col
                    break

            if code_col is None:
                raise ValueError("CSV文件缺少股票代码列")

            codes = df[code_col].astype(str).str.zfill(6).tolist()
            return self.get_quotes(codes)

        except Exception as e:
            print(f"从CSV读取失败: {e}")
            return {}

    def _parse_quote(self, code: str, content: str) -> Optional[RealTimeQuote]:
        """
        解析腾讯API返回的行情数据

        数据格式 (以~分隔):
        v_sz002236="51~大华股份~002236~18.92~18.70~18.70~167330~...
        索引:         0     1      2      3     4     5     6
        内容:         未知  名称   代码   现价  昨收  今开  成交量(手)

        Args:
            code: 股票代码
            content: API返回内容

        Returns:
            RealTimeQuote 对象
        """
        if not content or '~' not in content:
            return None

        try:
            # 提取数据部分
            start = content.find('"') + 1
            end = content.rfind('"')
            data_str = content[start:end]

            parts = data_str.split('~')
            if len(parts) < 35:
                return None

            name = parts[1]
            price = self._safe_float(parts[3])
            pre_close = self._safe_float(parts[4])
            open_price = self._safe_float(parts[5])
            volume = self._safe_float(parts[6])  # 手

            # 涨跌额和涨跌幅
            change = self._safe_float(parts[31])
            change_pct = self._safe_float(parts[32])

            # 最高最低
            high = self._safe_float(parts[33])
            low = self._safe_float(parts[34])

            # 成交额(万) -> 转换为元
            amount_wan = self._safe_float(parts[37]) if len(parts) > 37 else 0
            amount = amount_wan * 10000

            # 去除代码前缀
            pure_code = code.replace('sh', '').replace('sz', '').replace('bj', '')

            return RealTimeQuote(
                code=pure_code,
                name=name,
                price=price,
                pre_close=pre_close,
                change=change,
                change_pct=change_pct,
                open=open_price,
                high=high,
                low=low,
                volume=volume,
                amount=amount,
                timestamp=datetime.now()
            )

        except Exception as e:
            print(f"解析 {code} 数据失败: {e}")
            return None

    def _safe_float(self, value: str) -> float:
        """安全转换浮点数"""
        try:
            if value and str(value).strip():
                return float(str(value).strip())
        except:
            pass
        return 0.0

    def format_quote_table(self, quotes: Union[RealTimeQuote, Dict[str, RealTimeQuote], List[RealTimeQuote]]) -> str:
        """
        格式化行情表格

        Args:
            quotes: 单个行情对象或字典或列表

        Returns:
            格式化的表格字符串
        """
        # 转换为列表
        if isinstance(quotes, RealTimeQuote):
            quote_list = [quotes]
        elif isinstance(quotes, dict):
            quote_list = list(quotes.values())
        else:
            quote_list = quotes

        if not quote_list:
            return "暂无数据"

        lines = []
        lines.append("=" * 100)
        lines.append(f"{'代码':<8}{'名称':<12}{'现价':<10}{'涨跌':<10}{'涨跌幅':<10}{'今开':<10}{'最高':<10}{'最低':<10}{'成交量(手)':<12}")
        lines.append("-" * 100)

        for q in quote_list:
            change_str = f"{q.change:+.2f}"
            pct_str = f"{q.change_pct:+.2f}%"

            # 根据涨跌添加颜色标记(用符号代替)
            prefix = ""
            suffix = ""
            if q.change > 0:
                prefix = ""
            elif q.change < 0:
                prefix = ""

            lines.append(
                f"{q.code:<8}{q.name:<12}{q.price:>8.2f}   {change_str:>8} {pct_str:>9} "
                f"{q.open:>8.2f}  {q.high:>8.2f}  {q.low:>8.2f}  {q.volume:>12.0f}"
            )

        lines.append("=" * 100)

        return "\n".join(lines)

    def format_portfolio_table(self, quotes: Dict[str, RealTimeQuote],
                               positions: Dict[str, Dict]) -> str:
        """
        格式化持仓盈亏表格

        Args:
            quotes: 实时行情字典 {代码: RealTimeQuote}
            positions: 持仓信息字典 {代码: {'shares': 数量, 'cost': 成本}}

        Returns:
            格式化的表格字符串
        """
        if not quotes:
            return "暂无数据"

        lines = []
        lines.append("=" * 120)
        lines.append(f"{'代码':<8}{'名称':<10}{'持仓':<8}{'成本':<10}{'现价':<10}{'市值':<12}{'盈亏':<12}{'盈亏%':<10}{'涨跌幅':<10}")
        lines.append("-" * 120)

        total_cost = 0
        total_value = 0
        total_profit = 0

        for code, quote in quotes.items():
            if code not in positions:
                continue

            pos = positions[code]
            shares = pos.get('shares', 0)
            cost = pos.get('cost', 0)

            if shares == 0 or cost == 0:
                continue

            cost_value = cost * shares
            current_value = quote.price * shares
            profit = current_value - cost_value
            profit_pct = (quote.price / cost - 1) * 100

            total_cost += cost_value
            total_value += current_value
            total_profit += profit

            profit_str = f"{profit:+,.0f}"
            profit_pct_str = f"{profit_pct:+.2f}%"
            change_pct_str = f"{quote.change_pct:+.2f}%"

            lines.append(
                f"{code:<8}{quote.name:<10}{shares:>6}   {cost:>8.2f}  {quote.price:>8.2f}  "
                f"{current_value:>10,.0f}  {profit_str:>10}  {profit_pct_str:>9}  {change_pct_str:>9}"
            )

        lines.append("-" * 120)
        total_profit_pct = (total_value / total_cost - 1) * 100 if total_cost > 0 else 0
        lines.append(
            f"{'合计':<18}{'':>16}{'':>20}{'':>11}{total_value:>10,.0f}  {total_profit:>+10,.0f}  "
            f"{total_profit_pct:>+8.2f}%"
        )
        lines.append("=" * 120)

        return "\n".join(lines)


# 便捷函数
def get_quote(code: str) -> Optional[RealTimeQuote]:
    """获取单只股票实时行情"""
    api = RealTimeQuoteAPI()
    return api.get_quote(code)


def get_quotes(codes: List[str]) -> Dict[str, RealTimeQuote]:
    """批量获取股票实时行情"""
    api = RealTimeQuoteAPI()
    return api.get_quotes(codes)


def monitor_portfolio(csv_path: str, cash: float = 0) -> Dict:
    """
    监控持仓组合

    Args:
        csv_path: 持仓CSV文件路径
        cash: 可用现金

    Returns:
        包含行情、盈亏、总资产的字典
    """
    api = RealTimeQuoteAPI()

    # 读取持仓
    df = pd.read_csv(csv_path, encoding='utf-8-sig')

    # 标准化列名
    column_map = {
        '股票代码': 'code', 'code': 'code',
        '股票名称': 'name', 'name': 'name',
        '持股数量': 'shares', 'shares': 'shares', '数量': 'shares',
        '成本价': 'cost', 'cost_price': 'cost', '成本': 'cost'
    }
    df = df.rename(columns=column_map)

    # 获取实时行情
    codes = df['code'].astype(str).str.zfill(6).tolist()
    quotes = api.get_quotes(codes)

    # 计算持仓盈亏
    positions = {}
    for _, row in df.iterrows():
        code = str(row['code']).zfill(6)
        positions[code] = {
            'shares': int(row['shares']),
            'cost': float(row['cost'])
        }

    # 汇总
    total_cost = 0
    total_value = 0

    for code, quote in quotes.items():
        if code in positions:
            pos = positions[code]
            cost_value = pos['cost'] * pos['shares']
            current_value = quote.price * pos['shares']
            total_cost += cost_value
            total_value += current_value

    total_assets = total_value + cash
    total_profit = total_value - total_cost
    total_profit_pct = (total_value / total_cost - 1) * 100 if total_cost > 0 else 0

    return {
        'quotes': quotes,
        'positions': positions,
        'total_cost': total_cost,
        'total_value': total_value,
        'total_profit': total_profit,
        'total_profit_pct': total_profit_pct,
        'cash': cash,
        'total_assets': total_assets,
        'timestamp': datetime.now()
    }


if __name__ == "__main__":
    print("=" * 60)
    print("实时股价查询模块测试")
    print("=" * 60)

    # 创建API实例
    api = RealTimeQuoteAPI()

    # 测试1: 单股查询
    print("\n【测试1】单股查询 - 贵州茅台")
    quote = api.get_quote("600519")
    if quote:
        print(f"  {quote.name} ({quote.code})")
        print(f"  现价: {quote.price:.2f} 元")
        print(f"  涨跌: {quote.change:+.2f} ({quote.change_pct:+.2f}%)")
        print(f"  今开: {quote.open:.2f}  最高: {quote.high:.2f}  最低: {quote.low:.2f}")

    # 测试2: 批量查询
    print("\n【测试2】批量查询 - 持仓股票")
    codes = ['002078', '002236', '600056', '600993', '601360']
    quotes = api.get_quotes(codes)
    print(api.format_quote_table(quotes))

    # 测试3: 持仓监控
    print("\n【测试3】持仓盈亏监控")
    result = monitor_portfolio("持仓.csv", cash=0)
    print(api.format_portfolio_table(result['quotes'], result['positions']))
    print(f"\n账户总资产: {result['total_assets']:,.0f} 元")
    print(f"总盈亏: {result['total_profit']:+,.0f} 元 ({result['total_profit_pct']:+.2f}%)")
