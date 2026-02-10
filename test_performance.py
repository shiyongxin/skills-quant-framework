# -*- coding: utf-8 -*-
"""
性能测试和演示
Performance Test and Demo

测试缓存和并发获取的性能提升
"""

import time
import sys
sys.path.append('.')

from concurrent_fetcher import (
    ConcurrentDataFetcher,
    BatchFetcher,
    performance_test
)
from cache_manager import get_cache_manager, CacheConfig


def test_cache_performance():
    """测试缓存性能"""
    print("=" * 60)
    print("缓存性能测试")
    print("=" * 60)
    print()

    # 测试股票
    symbols = ['600519', '000858', '002415', '600036', '000001']

    # 创建缓存管理器
    cache = get_cache_manager()

    if not cache.is_enabled():
        print("Redis未连接，跳过缓存测试")
        return

    # 第一次获取（无缓存）
    print("第一次获取（无缓存）...")
    fetcher = ConcurrentDataFetcher(max_workers=5, use_cache=True)
    fetcher.reset_stats()

    start = time.time()
    results1 = fetcher.fetch_stocks_parallel(symbols, days=120, show_progress=False)
    time1 = time.time() - start

    stats1 = fetcher.get_stats()

    print(f"  耗时: {time1:.2f}秒")
    print(f"  API调用: {stats1['api_calls']}")
    print(f"  缓存命中: {stats1['cache_hits']}")

    # 第二次获取（有缓存）
    print("\n第二次获取（有缓存）...")
    fetcher.reset_stats()

    start = time.time()
    results2 = fetcher.fetch_stocks_parallel(symbols, days=120, show_progress=False)
    time2 = time.time() - start

    stats2 = fetcher.get_stats()

    print(f"  耗时: {time2:.2f}秒")
    print(f"  API调用: {stats2['api_calls']}")
    print(f"  缓存命中: {stats2['cache_hits']}")

    # 性能对比
    speedup = time1 / time2 if time2 > 0 else 0
    print(f"\n性能提升: {speedup:.1f}x")

    return results2


def test_concurrent_performance():
    """测试并发获取性能"""
    print("\n" + "=" * 60)
    print("并发性能测试")
    print("=" * 60)
    print()

    # 测试股票列表
    test_symbols = [
        '600519', '000858', '002415', '600036', '000001',
        '601318', '600276', '002304', '000333', '600887'
    ]

    print(f"测试 {len(test_symbols)} 只股票")

    # 性能测试
    results = performance_test(
        symbols=test_symbols,
        max_workers_list=[1, 5, 10]
    )

    print("\n性能测试结果:")
    print(results.to_string(index=False))

    # 最佳配置
    best = results.loc[results['rate'].idxmax()]
    print(f"\n最佳配置: {best['workers']} 线程")
    print(f"  速率: {best['rate']:.2f} 股票/秒")


def test_large_batch():
    """测试大批量获取"""
    print("\n" + "=" * 60)
    print("大批量获取测试")
    print("=" * 60)
    print()

    # 大批量测试
    large_batch = [
        '600519', '000858', '002415', '600036', '000001',
        '601318', '600276', '002304', '000333', '600887',
        '000002', '601166', '600000', '601328', '600104'
    ]

    print(f"获取 {len(large_batch)} 只股票...")

    fetcher = ConcurrentDataFetcher(max_workers=10)
    start = time.time()

    results = fetcher.fetch_and_calculate(large_batch, days=120)

    elapsed = time.time() - start

    print(f"\n完成! 耗时: {elapsed:.2f}秒")
    print(f"  成功: {len(results)}/{len(large_batch)}")
    print(f"  平均: {elapsed/len(large_batch):.2f}秒/股")


def test_cache_operations():
    """测试缓存操作"""
    print("\n" + "=" * 60)
    print("缓存操作测试")
    print("=" * 60)
    print()

    cache = get_cache_manager()

    if not cache.is_enabled():
        print("Redis未连接，跳过测试")
        return

    # 测试基本操作
    print("测试基本操作...")

    # SET
    cache.set("test:key1", {"value": "test1"}, ttl=60)
    print("✓ SET 操作")

    # GET
    value = cache.get("test:key1")
    print(f"✓ GET 操作: {value}")

    # EXISTS
    exists = cache.exists("test:key1")
    print(f"✓ EXISTS 操作: {exists}")

    # DELETE
    cache.delete("test:key1")
    print("✓ DELETE 操作")

    # 统计
    stats = cache.get_stats()
    print(f"\n缓存统计:")
    print(f"  命中: {stats['hits']}")
    print(f"  未命中: {stats['misses']}")
    print(f"  命中率: {stats['hit_rate']:.2%}")


def main():
    """主函数"""
    print("\n")
    print("╔" + "═" * 58 + "╗")
    print("║" + " " * 15 + "性能测试和演示" + " " * 27 + "║")
    print("╚" + "═" * 58 + "╝")
    print()

    try:
        # 1. 缓存性能测试
        test_cache_performance()

        # 2. 并发性能测试
        test_concurrent_performance()

        # 3. 大批量测试
        test_large_batch()

        # 4. 缓存操作测试
        test_cache_operations()

        print("\n" + "=" * 60)
        print("所有测试完成！")
        print("=" * 60)

    except Exception as e:
        print(f"\n测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
