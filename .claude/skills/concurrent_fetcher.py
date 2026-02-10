# -*- coding: utf-8 -*-
"""
并发数据获取器
Concurrent Data Fetcher

使用多线程并发获取多只股票数据，大幅提升性能
"""

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime
import pandas as pd

# 导入数据获取模块
try:
    from stock_data_fetcher import StockDataFetcher
    from cache_manager import CacheManager, get_cache_manager
    MODULES_AVAILABLE = True
except ImportError:
    MODULES_AVAILABLE = False


# =============================================================================
# 配置类
# =============================================================================

class FetcherConfig:
    """并发获取器配置"""

    # 默认参数
    DEFAULT_MAX_WORKERS = 10
    DEFAULT_DELAY = 0.5  # 秒
    DEFAULT_MAX_RETRIES = 3
    DEFAULT_TIMEOUT = 30  # 秒

    # 速率限制
    DEFAULT_RATE_LIMIT = 100  # 每分钟请求数


# =============================================================================
# 进度回调
# =============================================================================

class ProgressTracker:
    """进度跟踪器"""

    def __init__(self, total: int, callback: Callable[[int, int, str], None] = None):
        """
        初始化进度跟踪器

        Args:
            total: 总任务数
            callback: 进度回调函数 (current, total, message)
        """
        self.total = total
        self.current = 0
        self.success = 0
        self.failed = 0
        self.start_time = time.time()
        self.callback = callback

    def update(self, success: bool = True, symbol: str = ""):
        """
        更新进度

        Args:
            success: 是否成功
            symbol: 股票代码
        """
        self.current += 1
        if success:
            self.success += 1
        else:
            self.failed += 1

        if self.callback:
            self.callback(self.current, self.total, symbol)

    def get_progress(self) -> Dict[str, Any]:
        """
        获取进度信息

        Returns:
            进度信息字典
        """
        elapsed = time.time() - self.start_time
        rate = self.current / elapsed if elapsed > 0 else 0
        eta = (self.total - self.current) / rate if rate > 0 else 0

        return {
            'total': self.total,
            'current': self.current,
            'success': self.success,
            'failed': self.failed,
            'progress_pct': self.current / self.total * 100,
            'elapsed': elapsed,
            'rate': rate,
            'eta': eta
        }


# =============================================================================
# 并发数据获取器
# =============================================================================

class ConcurrentDataFetcher:
    """并发数据获取器"""

    def __init__(self,
                 max_workers: int = None,
                 cache_manager: CacheManager = None,
                 use_cache: bool = True):
        """
        初始化并发数据获取器

        Args:
            max_workers: 最大工作线程数
            cache_manager: 缓存管理器
            use_cache: 是否使用缓存
        """
        if not MODULES_AVAILABLE:
            raise ImportError("必要模块未安装")

        self.max_workers = max_workers or FetcherConfig.DEFAULT_MAX_WORKERS
        self.cache_manager = cache_manager or (get_cache_manager() if use_cache else None)
        self.use_cache = use_cache and self.cache_manager is not None

        # 创建数据获取器实例池
        self._fetchers = []

        # 统计信息
        self._stats = {
            'total_fetched': 0,
            'cache_hits': 0,
            'api_calls': 0,
            'failed': 0
        }

    def _get_fetcher(self) -> StockDataFetcher:
        """获取数据获取器实例"""
        if not self._fetchers:
            return StockDataFetcher()
        return self._fetchers[0]

    def fetch_one(self, symbol: str, days: int = 120,
                   use_cache: bool = None) -> Optional[pd.DataFrame]:
        """
        获取单只股票数据（带缓存）

        Args:
            symbol: 股票代码
            days: 数据天数
            use_cache: 是否使用缓存

        Returns:
            股票数据DataFrame
        """
        use_cache = use_cache if use_cache is not None else self.use_cache

        # 尝试从缓存获取
        if use_cache and self.cache_manager:
            cached_data = self.cache_manager.get_stock_data(symbol)
            if cached_data is not None:
                self._stats['cache_hits'] += 1
                return cached_data

        # 从API获取
        fetcher = self._get_fetcher()
        try:
            data = fetcher.get_quote_data(symbol, days=days)
            if data is not None and len(data) > 0:
                self._stats['api_calls'] += 1
                self._stats['total_fetched'] += 1

                # 存入缓存
                if use_cache and self.cache_manager:
                    self.cache_manager.cache_stock_data(symbol, data)

                return data
        except Exception as e:
            self._stats['failed'] += 1
            print(f"[WARN] 获取 {symbol} 失败: {e}")

        return None

    def fetch_stocks_parallel(self,
                               symbols: List[str],
                               days: int = 120,
                               delay: float = None,
                               show_progress: bool = True) -> Dict[str, pd.DataFrame]:
        """
        并发获取多只股票数据

        Args:
            symbols: 股票代码列表
            days: 数据天数
            delay: 请求延迟（秒）
            show_progress: 是否显示进度

        Returns:
            {symbol: DataFrame} 字典
        """
        delay = delay or FetcherConfig.DEFAULT_DELAY

        results = {}

        # 进度跟踪
        tracker = None
        if show_progress:
            def progress_callback(current, total, symbol):
                pct = current / total * 100
                print(f"\r进度: {current}/{total} ({pct:.1f}%) - {symbol}", end='')

            tracker = ProgressTracker(len(symbols), progress_callback)
            print(f"开始获取 {len(symbols)} 只股票数据...")

        # 并发获取
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交任务
            future_to_symbol = {
                executor.submit(self.fetch_one, symbol, days): symbol
                for symbol in symbols
            }

            # 处理结果
            for future in as_completed(future_to_symbol):
                symbol = future_to_symbol[future]

                try:
                    data = future.result(timeout=FetcherConfig.DEFAULT_TIMEOUT)
                    if data is not None:
                        results[symbol] = data
                        if tracker:
                            tracker.update(True, symbol)
                    else:
                        if tracker:
                            tracker.update(False, symbol)

                    # 延迟（避免过快请求）
                    if delay > 0:
                        time.sleep(delay)

                except Exception as e:
                    print(f"\n[ERROR] {symbol} 获取异常: {e}")
                    if tracker:
                        tracker.update(False, symbol)

        if show_progress and tracker:
            print()  # 换行
            progress = tracker.get_progress()
            print(f"完成! 成功: {progress['success']}, 失败: {progress['failed']}, "
                  f"耗时: {progress['elapsed']:.1f}秒")

        return results

    def fetch_with_limit(self,
                         symbols: List[str],
                         days: int = 120,
                         rate_limit: int = None) -> Dict[str, pd.DataFrame]:
        """
        限速获取数据

        Args:
            symbols: 股票代码列表
            days: 数据天数
            rate_limit: 每分钟请求数

        Returns:
            {symbol: DataFrame} 字典
        """
        rate_limit = rate_limit or FetcherConfig.DEFAULT_RATE_LIMIT

        results = {}
        batch_size = max_workers = min(self.max_workers, rate_limit // 6)

        print(f"限速获取: 每分钟{rate_limit}次，批次大小{batch_size}")

        # 分批处理
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]

            # 获取当前批次
            batch_results = self.fetch_stocks_parallel(
                batch, days, delay=0, show_progress=False
            )
            results.update(batch_results)

            print(f"批次 {i // batch_size + 1}/{(len(symbols) + batch_size - 1) // batch_size} 完成")

            # 等待（控制速率）
            if i + batch_size < len(symbols):
                time.sleep(60 / rate_limit * batch_size)

        return results

    def fetch_with_retry(self,
                         symbols: List[str],
                         days: int = 120,
                         max_retries: int = None) -> Dict[str, pd.DataFrame]:
        """
        带重试的数据获取

        Args:
            symbols: 股票代码列表
            days: 数据天数
            max_retries: 最大重试次数

        Returns:
            {symbol: DataFrame} 字典
        """
        max_retries = max_retries or FetcherConfig.DEFAULT_MAX_RETRIES

        results = {}
        failed_symbols = symbols.copy()

        for retry in range(max_retries + 1):
            if not failed_symbols:
                break

            print(f"第 {retry + 1}/{max_retries + 1} 次尝试，剩余 {len(failed_symbols)} 只")

            batch_results = self.fetch_stocks_parallel(
                failed_symbols, days, show_progress=(retry == 0)
            )

            results.update(batch_results)
            failed_symbols = [s for s in failed_symbols if s not in batch_results]

        if failed_symbols:
            print(f"\n警告: {len(failed_symbols)} 只股票获取失败:")
            for symbol in failed_symbols:
                print(f"  - {symbol}")

        return results

    def fetch_and_calculate(self,
                            symbols: List[str],
                            days: int = 120) -> Dict[str, pd.DataFrame]:
        """
        获取数据并计算技术指标

        Args:
            symbols: 股票代码列表
            days: 数据天数

        Returns:
            {symbol: DataFrame with indicators} 字典
        """
        print("正在获取股票数据...")
        results = self.fetch_stocks_parallel(symbols, days)

        print(f"\n正在计算技术指标...")
        fetcher = self._get_fetcher()

        results_with_indicators = {}
        for symbol, data in results.items():
            try:
                data_with_indicators = fetcher.calculate_technical_indicators(data)
                results_with_indicators[symbol] = data_with_indicators
            except Exception as e:
                print(f"[WARN] {symbol} 计算指标失败: {e}")
                results_with_indicators[symbol] = data

        print(f"完成! 处理了 {len(results_with_indicators)} 只股票")

        return results_with_indicators

    # =============================================================================
    # 统计信息
    # =============================================================================

    def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息

        Returns:
            统计信息字典
        """
        return self._stats.copy()

    def reset_stats(self):
        """重置统计信息"""
        self._stats = {
            'total_fetched': 0,
            'cache_hits': 0,
            'api_calls': 0,
            'failed': 0
        }


# =============================================================================
# 批量操作辅助类
# =============================================================================

class BatchFetcher:
    """批量获取辅助类"""

    @staticmethod
    def fetch_all_stocks(market: str = "A股",
                         days: int = 120,
                         max_workers: int = 10) -> Dict[str, pd.DataFrame]:
        """
        获取市场所有股票数据

        Args:
            market: 市场类型
            days: 数据天数
            max_workers: 最大工作线程数

        Returns:
            {symbol: DataFrame} 字典
        """
        from stock_list_manager import get_stock_list

        # 获取股票列表
        stock_list = get_stock_list(market)
        symbols = [s['代码'] for s in stock_list]

        print(f"获取 {market} 市场，共 {len(symbols)} 只股票")

        # 并发获取
        fetcher = ConcurrentDataFetcher(max_workers=max_workers)
        return fetcher.fetch_stocks_parallel(symbols, days)

    @staticmethod
    def fetch_index_components(index_code: str = "000300",
                                days: int = 120) -> Dict[str, pd.DataFrame]:
        """
        获取指数成分股数据

        Args:
            index_code: 指数代码（如000300沪深300）
            days: 数据天数

        Returns:
            {symbol: DataFrame} 字典
        """
        # 这里可以调用获取成分股的接口
        # 简化版：使用预定义列表
        index_components = {
            "000300": [  # 沪深300
                "600519", "000858", "002415", "600036", "000001",
                "601318", "600276", "002304", "000333", "600887"
            ]
        }

        symbols = index_components.get(index_code, [])

        if not symbols:
            print(f"未找到指数 {index_code} 的成分股")
            return {}

        print(f"获取 {index_code} 成分股，共 {len(symbols)} 只")

        fetcher = ConcurrentDataFetcher()
        return fetcher.fetch_stocks_parallel(symbols, days)

    @staticmethod
    def fetch_watchlist(watchlist: List[str],
                         days: int = 120) -> Dict[str, pd.DataFrame]:
        """
        获取自选股数据

        Args:
            watchlist: 自选股列表
            days: 数据天数

        Returns:
            {symbol: DataFrame} 字典
        """
        print(f"获取自选股，共 {len(watchlist)} 只")

        fetcher = ConcurrentDataFetcher()
        return fetcher.fetch_and_calculate(watchlist, days)


# =============================================================================
# 性能测试
# =============================================================================

def performance_test(symbols: List[str],
                    max_workers_list: List[int] = None) -> pd.DataFrame:
    """
    性能测试

    Args:
        symbols: 测试用的股票列表
        max_workers_list: 测试的线程数列表

    Returns:
        性能测试结果DataFrame
    """
    max_workers_list = max_workers_list or [1, 5, 10, 20]

    results = []

    for workers in max_workers_list:
        print(f"\n测试 {workers} 线程...")

        fetcher = ConcurrentDataFetcher(max_workers=workers)
        fetcher.reset_stats()

        start_time = time.time()
        data = fetcher.fetch_stocks_parallel(symbols, days=120, show_progress=False)
        elapsed = time.time() - start_time

        stats = fetcher.get_stats()

        results.append({
            'workers': workers,
            'total_symbols': len(symbols),
            'success': len(data),
            'elapsed': elapsed,
            'rate': len(symbols) / elapsed if elapsed > 0 else 0,
            'cache_hits': stats['cache_hits'],
            'api_calls': stats['api_calls']
        })

    return pd.DataFrame(results)


# =============================================================================
# 测试代码
# =============================================================================

if __name__ == "__main__":
    print("并发数据获取器 - v1.0")
    print()

    # 测试股票列表
    test_symbols = ['600519', '000858', '002415', '600036', '000001']

    print("测试并发获取...")

    # 创建并发获取器
    fetcher = ConcurrentDataFetcher(max_workers=5)

    # 并发获取
    results = fetcher.fetch_stocks_parallel(
        symbols=test_symbols,
        days=120
    )

    print(f"\n获取到 {len(results)} 只股票数据")

    for symbol, data in results.items():
        print(f"  {symbol}: {len(data)} 条记录")

    # 统计信息
    stats = fetcher.get_stats()
    print(f"\n统计信息:")
    print(f"  总获取: {stats['total_fetched']}")
    print(f"  缓存命中: {stats['cache_hits']}")
    print(f"  API调用: {stats['api_calls']}")
    print(f"  失败: {stats['failed']}")

    print("\n✓ 测试完成！")
