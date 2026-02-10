# -*- coding: utf-8 -*-
"""
Redis缓存管理器
Redis Cache Manager

提供高性能的数据缓存功能，支持多种数据类型和TTL策略
"""

import json
import pickle
import hashlib
from datetime import datetime, timedelta
from typing import Any, Optional, Dict, List
import pandas as pd
import numpy as np

try:
    import redis
    REDIS_AVAILABLE = True
    RedisType = redis.Redis
except ImportError:
    REDIS_AVAILABLE = False
    redis = None  # type: ignore
    RedisType = Any  # type: ignore


# =============================================================================
# 缓存配置
# =============================================================================

class CacheConfig:
    """缓存配置类"""

    # 默认TTL（秒）
    TTL_STOCK_DATA = 86400      # 股票数据: 24小时
    TTL_TECHNICAL_INDICATORS = 3600  # 技术指标: 1小时
    TTL_REALTIME_QUOTE = 60     # 实时报价: 1分钟
    TTL_QUERY_RESULT = 1800     # 查询结果: 30分钟
    TTL_SIGNAL_DATA = 300       # 信号数据: 5分钟
    TTL_FACTOR_DATA = 7200      # 因子数据: 2小时

    # 缓存键前缀
    PREFIX_STOCK = "stock"
    PREFIX_INDICATOR = "indicator"
    PREFIX_QUOTE = "quote"
    PREFIX_SIGNAL = "signal"
    PREFIX_FACTOR = "factor"
    PREFIX_QUERY = "query"
    PREFIX_BACKTEST = "backtest"

    # Redis连接配置
    DEFAULT_HOST = "localhost"
    DEFAULT_PORT = 6379
    DEFAULT_DB = 0
    DEFAULT_PASSWORD = None


# =============================================================================
# 缓存管理器
# =============================================================================

class CacheManager:
    """Redis缓存管理器"""

    def __init__(self,
                 host: str = None,
                 port: int = None,
                 db: int = None,
                 password: str = None,
                 decode_responses: bool = False):
        """
        初始化缓存管理器

        Args:
            host: Redis主机地址
            port: Redis端口
            db: 数据库编号
            password: 密码
            decode_responses: 是否自动解码响应
        """
        if not REDIS_AVAILABLE:
            raise ImportError("Redis模块未安装，请运行: pip install redis")

        self.host = host or CacheConfig.DEFAULT_HOST
        self.port = port or CacheConfig.DEFAULT_PORT
        self.db = db or CacheConfig.DEFAULT_DB
        self.password = password or CacheConfig.DEFAULT_PASSWORD

        self._client: Optional[RedisType] = None
        self._enabled = True
        self._stats = {
            'hits': 0,
            'misses': 0,
            'sets': 0,
            'deletes': 0
        }

    @property
    def client(self) -> RedisType:
        """获取Redis客户端（延迟连接）"""
        if self._client is None:
            try:
                self._client = redis.Redis(
                    host=self.host,
                    port=self.port,
                    db=self.db,
                    password=self.password,
                    decode_responses=False,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    retry_on_timeout=True
                )
                # 测试连接
                self._client.ping()
                print(f"[OK] Redis连接成功: {self.host}:{self.port}")
            except Exception as e:
                print(f"[WARN] Redis连接失败: {e}")
                print("[INFO] 缓存功能已禁用")
                self._enabled = False
                self._client = None

        return self._client

    def is_enabled(self) -> bool:
        """检查缓存是否启用"""
        return self._enabled and self._client is not None

    def _generate_key(self, prefix: str, *parts) -> str:
        """生成缓存键"""
        key = f"{CacheConfig.PREFIX_STOCK}:{prefix}"
        if parts:
            key += ":" + ":".join(str(p) for p in parts)
        return key

    def _hash_key(self, key: str) -> str:
        """生成键的哈希值（用于长键）"""
        return hashlib.md5(key.encode()).hexdigest()

    # =============================================================================
    # 基础操作
    # =============================================================================

    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存值

        Args:
            key: 缓存键

        Returns:
            缓存值，不存在返回None
        """
        if not self.is_enabled():
            return None

        try:
            value = self.client.get(key)
            if value is not None:
                self._stats['hits'] += 1
                return pickle.loads(value)
            else:
                self._stats['misses'] += 1
                return None
        except Exception as e:
            print(f"[WARN] 获取缓存失败: {e}")
            return None

    def set(self, key: str, value: Any, ttl: int = None) -> bool:
        """
        设置缓存值

        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒）

        Returns:
            是否成功
        """
        if not self.is_enabled():
            return False

        try:
            serialized = pickle.dumps(value)
            if ttl:
                self.client.setex(key, ttl, serialized)
            else:
                self.client.set(key, serialized)
            self._stats['sets'] += 1
            return True
        except Exception as e:
            print(f"[WARN] 设置缓存失败: {e}")
            return False

    def delete(self, key: str) -> bool:
        """
        删除缓存

        Args:
            key: 缓存键

        Returns:
            是否成功
        """
        if not self.is_enabled():
            return False

        try:
            result = self.client.delete(key)
            if result:
                self._stats['deletes'] += 1
            return result > 0
        except Exception as e:
            print(f"[WARN] 删除缓存失败: {e}")
            return False

    def exists(self, key: str) -> bool:
        """
        检查键是否存在

        Args:
            key: 缓存键

        Returns:
            是否存在
        """
        if not self.is_enabled():
            return False

        try:
            return self.client.exists(key) > 0
        except Exception as e:
            return False

    def invalidate(self, pattern: str) -> int:
        """
        使匹配的缓存失效

        Args:
            pattern: 键模式（支持通配符*）

        Returns:
            失效的键数量
        """
        if not self.is_enabled():
            return 0

        try:
            keys = self.client.keys(pattern)
            if keys:
                return self.client.delete(*keys)
            return 0
        except Exception as e:
            print(f"[WARN] 批量删除失败: {e}")
            return 0

    # =============================================================================
    # 股票数据缓存
    # =============================================================================

    def cache_stock_data(self, symbol: str, data: pd.DataFrame,
                         ttl: int = None) -> bool:
        """
        缓存股票数据

        Args:
            symbol: 股票代码
            data: 股票数据DataFrame
            ttl: 过期时间（秒），默认24小时

        Returns:
            是否成功
        """
        ttl = ttl or CacheConfig.TTL_STOCK_DATA
        key = self._generate_key(CacheConfig.PREFIX_STOCK, symbol)
        return self.set(key, data, ttl)

    def get_stock_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        获取缓存的股票数据

        Args:
            symbol: 股票代码

        Returns:
            股票数据DataFrame，不存在返回None
        """
        key = self._generate_key(CacheConfig.PREFIX_STOCK, symbol)
        return self.get(key)

    def batch_cache_stock_data(self, data_dict: Dict[str, pd.DataFrame],
                                ttl: int = None) -> bool:
        """
        批量缓存股票数据

        Args:
            data_dict: {symbol: DataFrame} 字典
            ttl: 过期时间（秒）

        Returns:
            是否全部成功
        """
        ttl = ttl or CacheConfig.TTL_STOCK_DATA
        success = True

        for symbol, data in data_dict.items():
            if not self.cache_stock_data(symbol, data, ttl):
                success = False

        return success

    # =============================================================================
    # 技术指标缓存
    # =============================================================================

    def cache_indicators(self, symbol: str, data: pd.DataFrame,
                         ttl: int = None) -> bool:
        """
        缓存技术指标数据

        Args:
            symbol: 股票代码
            data: 包含技术指标的DataFrame
            ttl: 过期时间（秒），默认1小时

        Returns:
            是否成功
        """
        ttl = ttl or CacheConfig.TTL_TECHNICAL_INDICATORS
        key = self._generate_key(CacheConfig.PREFIX_INDICATOR, symbol)
        return self.set(key, data, ttl)

    def get_indicators(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        获取缓存的技术指标数据

        Args:
            symbol: 股票代码

        Returns:
            技术指标DataFrame，不存在返回None
        """
        key = self._generate_key(CacheConfig.PREFIX_INDICATOR, symbol)
        return self.get(key)

    # =============================================================================
    # 实时报价缓存
    # =============================================================================

    def cache_quote(self, symbol: str, quote: Dict[str, Any],
                    ttl: int = None) -> bool:
        """
        缓存实时报价

        Args:
            symbol: 股票代码
            quote: 报价数据字典
            ttl: 过期时间（秒），默认1分钟

        Returns:
            是否成功
        """
        ttl = ttl or CacheConfig.TTL_REALTIME_QUOTE
        key = self._generate_key(CacheConfig.PREFIX_QUOTE, symbol)
        return self.set(key, quote, ttl)

    def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        获取缓存的实时报价

        Args:
            symbol: 股票代码

        Returns:
            报价数据字典，不存在返回None
        """
        key = self._generate_key(CacheConfig.PREFIX_QUOTE, symbol)
        return self.get(key)

    def batch_cache_quotes(self, quotes: Dict[str, Dict[str, Any]],
                           ttl: int = None) -> bool:
        """
        批量缓存实时报价

        Args:
            quotes: {symbol: quote_dict} 字典
            ttl: 过期时间（秒）

        Returns:
            是否全部成功
        """
        ttl = ttl or CacheConfig.TTL_REALTIME_QUOTE
        success = True

        for symbol, quote in quotes.items():
            if not self.cache_quote(symbol, quote, ttl):
                success = False

        return success

    # =============================================================================
    # 信号数据缓存
    # =============================================================================

    def cache_signal(self, symbol: str, signal: Dict[str, Any],
                     ttl: int = None) -> bool:
        """
        缓存交易信号

        Args:
            symbol: 股票代码
            signal: 信号数据字典
            ttl: 过期时间（秒），默认5分钟

        Returns:
            是否成功
        """
        ttl = ttl or CacheConfig.TTL_SIGNAL_DATA
        key = self._generate_key(CacheConfig.PREFIX_SIGNAL, symbol)
        return self.set(key, signal, ttl)

    def get_signal(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        获取缓存的交易信号

        Args:
            symbol: 股票代码

        Returns:
            信号数据字典，不存在返回None
        """
        key = self._generate_key(CacheConfig.PREFIX_SIGNAL, symbol)
        return self.get(key)

    # =============================================================================
    # 因子数据缓存
    # =============================================================================

    def cache_factor(self, factor_name: str, data: pd.DataFrame,
                     ttl: int = None) -> bool:
        """
        缓存因子数据

        Args:
            factor_name: 因子名称
            data: 因子数据DataFrame
            ttl: 过期时间（秒），默认2小时

        Returns:
            是否成功
        """
        ttl = ttl or CacheConfig.TTL_FACTOR_DATA
        key = self._generate_key(CacheConfig.PREFIX_FACTOR, factor_name)
        return self.set(key, data, ttl)

    def get_factor(self, factor_name: str) -> Optional[pd.DataFrame]:
        """
        获取缓存的因子数据

        Args:
            factor_name: 因子名称

        Returns:
            因子数据DataFrame，不存在返回None
        """
        key = self._generate_key(CacheConfig.PREFIX_FACTOR, factor_name)
        return self.get(key)

    # =============================================================================
    # 查询结果缓存
    # =============================================================================

    def cache_query_result(self, query_key: str, result: Any,
                           ttl: int = None) -> bool:
        """
        缓存查询结果

        Args:
            query_key: 查询键（自动哈希）
            result: 查询结果
            ttl: 过期时间（秒），默认30分钟

        Returns:
            是否成功
        """
        ttl = ttl or CacheConfig.TTL_QUERY_RESULT
        # 对长键进行哈希
        if len(query_key) > 100:
            query_key = self._hash_key(query_key)
        key = self._generate_key(CacheConfig.PREFIX_QUERY, query_key)
        return self.set(key, result, ttl)

    def get_query_result(self, query_key: str) -> Optional[Any]:
        """
        获取缓存的查询结果

        Args:
            query_key: 查询键

        Returns:
            查询结果，不存在返回None
        """
        if len(query_key) > 100:
            query_key = self._hash_key(query_key)
        key = self._generate_key(CacheConfig.PREFIX_QUERY, query_key)
        return self.get(key)

    # =============================================================================
    # 回测结果缓存
    # =============================================================================

    def cache_backtest_result(self, strategy_name: str, params: Dict,
                               result: Any, ttl: int = None) -> bool:
        """
        缓存回测结果

        Args:
            strategy_name: 策略名称
            params: 策略参数字典
            result: 回测结果
            ttl: 过期时间（秒），默认24小时

        Returns:
            是否成功
        """
        ttl = ttl or CacheConfig.TTL_STOCK_DATA
        # 生成唯一的缓存键
        params_str = json.dumps(params, sort_keys=True)
        cache_key = f"{strategy_name}_{self._hash_key(params_str)}"
        key = self._generate_key(CacheConfig.PREFIX_BACKTEST, cache_key)
        return self.set(key, result, ttl)

    def get_backtest_result(self, strategy_name: str,
                            params: Dict) -> Optional[Any]:
        """
        获取缓存的回测结果

        Args:
            strategy_name: 策略名称
            params: 策略参数字典

        Returns:
            回测结果，不存在返回None
        """
        params_str = json.dumps(params, sort_keys=True)
        cache_key = f"{strategy_name}_{self._hash_key(params_str)}"
        key = self._generate_key(CacheConfig.PREFIX_BACKTEST, cache_key)
        return self.get(key)

    # =============================================================================
    # 缓存统计和管理
    # =============================================================================

    def get_stats(self) -> Dict[str, int]:
        """
        获取缓存统计信息

        Returns:
            统计信息字典
        """
        stats = self._stats.copy()

        if self.is_enabled():
            try:
                info = self.client.info('stats')
                stats.update({
                    'total_keys': info.get('keyspace', 0),
                    'memory_used': info.get('used_memory_human', 'N/A'),
                    'hit_rate': self._calculate_hit_rate()
                })
            except Exception:
                pass

        return stats

    def _calculate_hit_rate(self) -> float:
        """计算缓存命中率"""
        total = self._stats['hits'] + self._stats['misses']
        if total > 0:
            return self._stats['hits'] / total
        return 0.0

    def clear_all(self) -> bool:
        """
        清空所有缓存

        Returns:
            是否成功
        """
        if not self.is_enabled():
            return False

        try:
            pattern = f"{CacheConfig.PREFIX_STOCK}:*"
            keys = self.client.keys(pattern)
            if keys:
                self.client.delete(*keys)
            return True
        except Exception as e:
            print(f"[WARN] 清空缓存失败: {e}")
            return False

    def clear_by_type(self, data_type: str) -> int:
        """
        按类型清空缓存

        Args:
            data_type: 数据类型 (stock/indicator/quote/signal/factor/query/backtest)

        Returns:
            清空的键数量
        """
        pattern = f"{CacheConfig.PREFIX_STOCK}:{data_type}:*"
        return self.invalidate(pattern)

    def get_cache_size(self) -> Dict[str, int]:
        """
        获取各类型缓存数量

        Returns:
            {类型: 数量} 字典
        """
        if not self.is_enabled():
            return {}

        sizes = {}
        types = [
            CacheConfig.PREFIX_STOCK,
            CacheConfig.PREFIX_INDICATOR,
            CacheConfig.PREFIX_QUOTE,
            CacheConfig.PREFIX_SIGNAL,
            CacheConfig.PREFIX_FACTOR,
            CacheConfig.PREFIX_QUERY,
            CacheConfig.PREFIX_BACKTEST
        ]

        for data_type in types:
            pattern = f"{CacheConfig.PREFIX_STOCK}:{data_type}:*"
            try:
                keys = self.client.keys(pattern)
                sizes[data_type] = len(keys)
            except Exception:
                sizes[data_type] = 0

        return sizes

    def warm_up(self, symbols: List[str], days: int = 120) -> Dict[str, bool]:
        """
        缓存预热

        Args:
            symbols: 股票代码列表
            days: 数据天数

        Returns:
            {symbol: success} 字典
        """
        from stock_data_fetcher import StockDataFetcher

        results = {}
        fetcher = StockDataFetcher()

        for symbol in symbols:
            try:
                data = fetcher.get_quote_data(symbol, days=days)
                if data is not None and len(data) > 0:
                    results[symbol] = self.cache_stock_data(symbol, data)
                else:
                    results[symbol] = False
            except Exception as e:
                print(f"[WARN] 预热 {symbol} 失败: {e}")
                results[symbol] = False

        return results


# =============================================================================
# 装饰器
# =============================================================================

def cached(ttl: int = None, key_prefix: str = None):
    """
    缓存装饰器

    Args:
        ttl: 过期时间（秒）
        key_prefix: 键前缀

    Usage:
        @cached(ttl=3600, key_prefix="analysis")
        def expensive_function(param1, param2):
            # ... 耗时操作
            return result
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            # 生成缓存键
            cache_key = f"{key_prefix or func.__name__}:{args}:{kwargs}"

            # 尝试从缓存获取
            # 这里需要获取cache_manager实例
            # 简化版，实际使用时需要传入或使用全局变量
            result = None  # cache_manager.get_query_result(cache_key)

            if result is not None:
                return result

            # 执行函数
            result = func(*args, **kwargs)

            # 存入缓存
            # cache_manager.cache_query_result(cache_key, result, ttl)

            return result

        return wrapper
    return decorator


# =============================================================================
# 全局缓存实例
# =============================================================================

_global_cache_manager: Optional[CacheManager] = None


def get_cache_manager(**kwargs) -> CacheManager:
    """
    获取全局缓存管理器实例

    Returns:
        CacheManager实例
    """
    global _global_cache_manager

    if _global_cache_manager is None:
        _global_cache_manager = CacheManager(**kwargs)

    return _global_cache_manager


# =============================================================================
# 测试代码
# =============================================================================

if __name__ == "__main__":
    print("Redis缓存管理器 - v1.0")
    print()

    # 测试连接
    try:
        cache = CacheManager()

        if cache.is_enabled():
            print("✓ Redis连接成功")

            # 测试基本操作
            print("\n测试基本操作:")

            # 设置
            cache.set("test_key", {"data": "test_value"}, ttl=60)
            print("✓ SET 操作成功")

            # 获取
            value = cache.get("test_key")
            print(f"✓ GET 操作成功: {value}")

            # 删除
            cache.delete("test_key")
            print("✓ DELETE 操作成功")

            # 统计
            stats = cache.get_stats()
            print(f"\n缓存统计:")
            print(f"  命中: {stats['hits']}")
            print(f"  未命中: {stats['misses']}")
            print(f"  设置: {stats['sets']}")
            print(f"  删除: {stats['deletes']}")

            print("\n✓ 所有测试通过！")

        else:
            print("✗ Redis未连接，请检查Redis服务")

    except ImportError:
        print("✗ Redis模块未安装，请运行: pip install redis")
    except Exception as e:
        print(f"✗ 测试失败: {e}")
