# -*- coding: utf-8 -*-
"""
股票代码和名称管理模块
提供股票代码查询、名称查询等功能
"""
import pandas as pd
import os

class StockList:
    """股票代码和名称管理类"""

    def __init__(self):
        """初始化，加载股票列表"""
        self._stock_list = None
        self._load_stock_list()

    def _load_stock_list(self):
        """加载股票列表"""
        # 获取当前文件所在目录
        current_dir = os.path.dirname(os.path.abspath(__file__))
        csv_file = os.path.join(current_dir, 'stock_list.csv')

        try:
            self._stock_list = pd.read_csv(csv_file, encoding='utf-8-sig')
            # 将代码列转换为字符串类型，保持6位格式
            self._stock_list['code'] = self._stock_list['code'].astype(str).str.zfill(6)
        except Exception as e:
            print(f"[WARNING] 加载股票列表失败: {e}")
            self._stock_list = pd.DataFrame(columns=['code', 'name', 'market'])

    def get_name(self, code):
        """
        根据股票代码获取名称

        Args:
            code: 股票代码 (6位数字，如 '600519')

        Returns:
            str: 股票名称，如果找不到返回 None
        """
        if self._stock_list is None or len(self._stock_list) == 0:
            return None

        result = self._stock_list[self._stock_list['code'] == str(code)]
        if len(result) > 0:
            return result.iloc[0]['name']
        return None

    def get_code(self, name):
        """
        根据股票名称获取代码

        Args:
            name: 股票名称 (支持模糊匹配)

        Returns:
            str: 股票代码，如果找不到返回 None
        """
        if self._stock_list is None or len(self._stock_list) == 0:
            return None

        # 精确匹配
        result = self._stock_list[self._stock_list['name'] == name]
        if len(result) > 0:
            return result.iloc[0]['code']

        # 模糊匹配
        result = self._stock_list[self._stock_list['name'].str.contains(name, na=False)]
        if len(result) > 0:
            return result.iloc[0]['code']

        return None

    def get_market(self, code):
        """
        根据股票代码获取所属市场

        Args:
            code: 股票代码

        Returns:
            str: 市场名称 ('上海主板', '深圳主板', '深圳创业板', '上海科创板')
        """
        if self._stock_list is None or len(self._stock_list) == 0:
            return None

        result = self._stock_list[self._stock_list['code'] == str(code)]
        if len(result) > 0:
            return result.iloc[0]['market']
        return None

    def search(self, keyword):
        """
        搜索股票（支持代码或名称模糊匹配）

        Args:
            keyword: 搜索关键词

        Returns:
            DataFrame: 匹配的股票列表
        """
        if self._stock_list is None or len(self._stock_list) == 0:
            return pd.DataFrame(columns=['code', 'name', 'market'])

        # 代码匹配
        code_match = self._stock_list[self._stock_list['code'].str.contains(keyword, na=False)]

        # 名称匹配
        name_match = self._stock_list[self._stock_list['name'].str.contains(keyword, na=False)]

        # 合并结果
        result = pd.concat([code_match, name_match]).drop_duplicates()

        return result

    def get_stocks_by_market(self, market):
        """
        获取指定市场的所有股票

        Args:
            market: 市场名称 ('上海主板', '深圳主板', '深圳创业板', '上海科创板')

        Returns:
            DataFrame: 指定市场的股票列表
        """
        if self._stock_list is None or len(self._stock_list) == 0:
            return pd.DataFrame(columns=['code', 'name', 'market'])

        return self._stock_list[self._stock_list['market'] == market]

    def get_all_stocks(self):
        """
        获取所有股票列表

        Returns:
            DataFrame: 所有股票列表
        """
        return self._stock_list.copy() if self._stock_list is not None else pd.DataFrame()

    def get_stock_count(self):
        """
        获取股票总数

        Returns:
            int: 股票总数
        """
        return len(self._stock_list) if self._stock_list is not None else 0

    def get_market_summary(self):
        """
        获取各市场股票数量统计

        Returns:
            dict: 各市场的股票数量
        """
        if self._stock_list is None or len(self._stock_list) == 0:
            return {}

        return self._stock_list['market'].value_counts().to_dict()


# 全局实例
_stock_list_instance = None

def get_stock_list():
    """
    获取StockList单例实例

    Returns:
        StockList: 股票列表管理实例
    """
    global _stock_list_instance
    if _stock_list_instance is None:
        _stock_list_instance = StockList()
    return _stock_list_instance


# 便捷函数
def get_stock_name(code):
    """根据股票代码获取名称"""
    return get_stock_list().get_name(code)


def get_stock_code(name):
    """根据股票名称获取代码"""
    return get_stock_list().get_code(name)


def get_stock_market(code):
    """根据股票代码获取所属市场"""
    return get_stock_list().get_market(code)


def search_stocks(keyword):
    """搜索股票"""
    return get_stock_list().search(keyword)


# 测试代码
if __name__ == "__main__":
    sl = StockList()

    print("=" * 60)
    print("股票代码和名称管理模块测试")
    print("=" * 60)
    print()

    print(f"股票总数: {sl.get_stock_count()}")
    print()

    print("各市场统计:")
    for market, count in sl.get_market_summary().items():
        print(f"  {market}: {count}只")
    print()

    # 测试查询
    print("查询测试:")
    print(f"  600519 -> {sl.get_name('600519')}")
    print(f"  贵州茅台 -> {sl.get_code('贵州茅台')}")
    print(f"  600519 所属市场 -> {sl.get_market('600519')}")
    print()

    # 搜索测试
    print("搜索 '茅台':")
    results = sl.search('茅台')
    print(results)
    print()

    print("搜索 '银行':")
    results = sl.search('银行')
    print(results.head(10))
    print()

    print("=" * 60)
    print("测试完成")
    print("=" * 60)
