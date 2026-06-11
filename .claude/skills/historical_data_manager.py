# -*- coding: utf-8 -*-
"""
历史数据管理器 - Historical Data Manager

使用Parquet格式高效管理A股30年历史数据。
支持增量更新、批量获取、数据验证等功能。

存储格式: 每只股票一个Parquet文件 (stock_data/historical/{symbol}.parquet)
"""

import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import json
import time
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Semaphore


class HistoricalDataManager:
    """
    历史数据管理器

    使用Parquet格式存储，支持:
    - 增量更新: 读取已有数据，仅获取缺失日期
    - 批量获取: 多线程并发+限速
    - 数据验证: 完整性、异常值检查
    - 股票池管理: 按历史天数过滤
    """

    def __init__(self, data_dir="./stock_data"):
        self.data_dir = Path(data_dir)
        self.historical_dir = self.data_dir / "historical"
        self.historical_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.historical_dir / "metadata.json"
        self.metadata = self._load_metadata()

    def _load_metadata(self) -> dict:
        """加载元数据"""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {"last_update": None, "stock_count": 0, "stocks": {}}

    def _save_metadata(self):
        """保存元数据"""
        with open(self.metadata_file, 'w', encoding='utf-8') as f:
            json.dump(self.metadata, f, ensure_ascii=False, indent=2)

    def _format_symbol(self, symbol: str) -> str:
        """格式化为腾讯接口格式"""
        symbol = str(symbol).zfill(6)
        if symbol.startswith('6'):
            return f'sh{symbol}'
        elif symbol.startswith('0') or symbol.startswith('3'):
            return f'sz{symbol}'
        return symbol

    def _get_parquet_path(self, symbol: str) -> Path:
        """获取Parquet文件路径"""
        return self.historical_dir / f"{str(symbol).zfill(6)}.parquet"

    def fetch_and_cache(self, symbol: str, start_date: str = "19960101",
                        end_date: str = None) -> pd.DataFrame:
        """
        获取并缓存股票历史数据（增量更新）

        Parameters:
        -----------
        symbol : str
            股票代码，如 "000001"
        start_date : str
            开始日期
        end_date : str
            结束日期，默认今天

        Returns:
        --------
        pd.DataFrame : 完整的历史数据
        """
        symbol = str(symbol).zfill(6)
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")

        parquet_path = self._get_parquet_path(symbol)
        existing_df = None

        # 检查已有数据
        if parquet_path.exists():
            try:
                existing_df = pd.read_parquet(parquet_path)
                if len(existing_df) > 0:
                    last_date = pd.to_datetime(existing_df['日期'].iloc[-1])
                    # 如果数据足够新(距今3天内)，直接返回
                    if last_date >= pd.to_datetime(end_date) - timedelta(days=3):
                        return existing_df
                    # 增量获取: 从最后日期的下一天开始
                    start_date = (last_date + timedelta(days=1)).strftime("%Y%m%d")
            except Exception:
                existing_df = None

        # 从API获取数据
        new_df = self._fetch_from_api(symbol, start_date, end_date)

        if new_df is None or len(new_df) == 0:
            # API无新数据，返回已有数据
            return existing_df if existing_df is not None else pd.DataFrame()

        # 合并数据
        if existing_df is not None and len(existing_df) > 0:
            combined = pd.concat([existing_df, new_df], ignore_index=True)
            combined = combined.drop_duplicates(subset=['日期'], keep='last')
            combined = combined.sort_values('日期').reset_index(drop=True)
        else:
            combined = new_df

        # 保存到Parquet
        try:
            combined.to_parquet(parquet_path, engine='pyarrow', compression='snappy',
                              index=False)
        except Exception as e:
            print(f"[WARN] {symbol} Parquet保存失败: {e}")
            # 降级保存为CSV
            csv_path = self.historical_dir / f"{symbol}.csv"
            combined.to_csv(csv_path, index=False, encoding='utf-8-sig')

        # 更新元数据
        self.metadata["stocks"][symbol] = {
            "first_date": str(combined['日期'].iloc[0].date()) if hasattr(combined['日期'].iloc[0], 'date') else str(combined['日期'].iloc[0]),
            "last_date": str(combined['日期'].iloc[-1].date()) if hasattr(combined['日期'].iloc[-1], 'date') else str(combined['日期'].iloc[-1]),
            "row_count": len(combined),
            "updated": datetime.now().isoformat()
        }
        self.metadata["last_update"] = datetime.now().isoformat()
        self.metadata["stock_count"] = len(self.metadata["stocks"])

        return combined

    def _fetch_from_api(self, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        """从akshare API获取数据"""
        tencent_symbol = self._format_symbol(symbol)

        try:
            start_dt = datetime.strptime(start_date, "%Y%m%d").date()
            end_dt = datetime.strptime(end_date, "%Y%m%d").date()

            df = ak.stock_zh_a_daily(
                symbol=tencent_symbol,
                start_date=start_dt,
                end_date=end_dt
            )

            if df is not None and len(df) > 0:
                # 标准化列名
                col_map = {
                    'date': '日期', 'open': '开盘', 'high': '最高',
                    'low': '最低', 'close': '收盘', 'volume': '成交量',
                    'amount': '成交额'
                }
                df = df.rename(columns=col_map)
                df['日期'] = pd.to_datetime(df['日期'])
                df = df.sort_values('日期').reset_index(drop=True)

                # 计算涨跌幅
                if '涨跌幅' not in df.columns:
                    df['涨跌幅'] = df['收盘'].pct_change() * 100

                return df

        except Exception as e:
            pass  # 静默失败，批量获取时会有很多失败

        return None

    def load(self, symbol: str, start_date: str = None,
             end_date: str = None) -> pd.DataFrame:
        """
        加载本地缓存的历史数据

        Parameters:
        -----------
        symbol : str
            股票代码
        start_date : str
            开始日期 (可选)
        end_date : str
            结束日期 (可选)

        Returns:
        --------
        pd.DataFrame
        """
        symbol = str(symbol).zfill(6)
        parquet_path = self._get_parquet_path(symbol)

        if not parquet_path.exists():
            # 尝试CSV降级
            csv_path = self.historical_dir / f"{symbol}.csv"
            if csv_path.exists():
                df = pd.read_csv(csv_path, encoding='utf-8-sig')
                df['日期'] = pd.to_datetime(df['日期'])
            else:
                return pd.DataFrame()
        else:
            df = pd.read_parquet(parquet_path)

        # 日期过滤
        if start_date:
            df = df[df['日期'] >= pd.to_datetime(start_date)]
        if end_date:
            df = df[df['日期'] <= pd.to_datetime(end_date)]

        return df.reset_index(drop=True)

    def batch_fetch(self, symbols: list, start_date: str = "19960101",
                    end_date: str = None, delay: float = 0.3,
                    max_workers: int = 4, save_interval: int = 50):
        """
        批量获取多只股票的历史数据

        Parameters:
        -----------
        symbols : list
            股票代码列表
        start_date : str
            开始日期
        end_date : str
            结束日期
        delay : float
            请求间隔(秒)
        max_workers : int
            最大并发数
        save_interval : int
            每处理N只股票保存一次元数据
        """
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")

        total = len(symbols)
        success = 0
        failed = 0
        skipped = 0
        semaphore = Semaphore(max_workers)

        print(f"[INFO] 开始批量获取 {total} 只股票的历史数据")
        print(f"       日期范围: {start_date} ~ {end_date}")
        print(f"       并发数: {max_workers}, 间隔: {delay}s")
        print()

        def fetch_one(sym):
            semaphore.acquire()
            try:
                time.sleep(delay)
                df = self.fetch_and_cache(sym, start_date, end_date)
                return sym, len(df) if df is not None else 0
            except Exception as e:
                return sym, -1
            finally:
                semaphore.release()

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(fetch_one, sym): sym for sym in symbols}

            for i, future in enumerate(as_completed(futures), 1):
                sym, count = future.result()
                if count > 0:
                    success += 1
                    status = f"OK ({count}条)"
                elif count == 0:
                    skipped += 1
                    status = "SKIP (无数据)"
                else:
                    failed += 1
                    status = "FAIL"

                if i % 10 == 0 or i == total:
                    print(f"  [{i}/{total}] {sym} {status} "
                          f"(成功:{success} 跳过:{skipped} 失败:{failed})")

                # 定期保存元数据
                if i % save_interval == 0:
                    self._save_metadata()

        # 最终保存
        self._save_metadata()

        print()
        print(f"[OK] 批量获取完成: 成功 {success}, 跳过 {skipped}, 失败 {failed}")

    def get_cache_status(self) -> pd.DataFrame:
        """
        获取缓存状态概览

        Returns:
        --------
        pd.DataFrame : 每只股票的缓存信息
        """
        records = []
        for sym, info in self.metadata.get("stocks", {}).items():
            records.append({
                'symbol': sym,
                'first_date': info.get('first_date'),
                'last_date': info.get('last_date'),
                'row_count': info.get('row_count', 0),
                'updated': info.get('updated')
            })

        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)
        df = df.sort_values('symbol').reset_index(drop=True)
        return df

    def get_universe(self, min_history_days: int = 5000,
                     min_rows: int = 2000) -> list:
        """
        获取有足够历史数据的股票池

        Parameters:
        -----------
        min_history_days : int
            最少历史天数(自然日)
        min_rows : int
            最少数据行数(交易日)

        Returns:
        --------
        list : 符合条件的股票代码列表
        """
        universe = []
        cutoff_date = datetime.now() - timedelta(days=min_history_days)

        for sym, info in self.metadata.get("stocks", {}).items():
            row_count = info.get("row_count", 0)
            last_date_str = info.get("last_date", "")

            if row_count < min_rows:
                continue

            try:
                last_date = datetime.strptime(last_date_str, "%Y-%m-%d")
                if last_date < cutoff_date:
                    continue
            except:
                continue

            universe.append(sym)

        return sorted(universe)

    def validate_integrity(self, symbol: str) -> dict:
        """
        验证单只股票的数据完整性

        Returns:
        --------
        dict : 验证结果
        """
        df = self.load(symbol)
        if len(df) == 0:
            return {"symbol": symbol, "valid": False, "reason": "无数据"}

        result = {
            "symbol": symbol,
            "valid": True,
            "row_count": len(df),
            "first_date": str(df['日期'].iloc[0].date()),
            "last_date": str(df['日期'].iloc[-1].date()),
            "issues": []
        }

        # 检查重复日期
        dups = df['日期'].duplicated().sum()
        if dups > 0:
            result["issues"].append(f"重复日期: {dups}条")

        # 检查零成交量
        if '成交量' in df.columns:
            zero_vol = (df['成交量'] == 0).sum()
            if zero_vol > len(df) * 0.05:
                result["issues"].append(f"零成交量天数过多: {zero_vol}天({zero_vol/len(df)*100:.1f}%)")

        # 检查价格异常(单日涨跌>20%)
        if '涨跌幅' in df.columns:
            extreme = (df['涨跌幅'].abs() > 20).sum()
            if extreme > 0:
                result["issues"].append(f"极端涨跌幅(>20%): {extreme}天")

        # 检查缺失值
        null_count = df.isnull().sum().sum()
        if null_count > 0:
            result["issues"].append(f"缺失值: {null_count}个")

        if result["issues"]:
            result["valid"] = len(result["issues"]) <= 1  # 1个问题以内算有效

        return result

    def get_all_symbols(self) -> list:
        """获取所有已缓存的股票代码"""
        return sorted(self.metadata.get("stocks", {}).keys())

    def get_stock_name(self, symbol: str) -> str:
        """获取股票名称(从stock_list.csv)"""
        stock_list_path = Path(".claude/skills/stock_list.csv")
        if stock_list_path.exists():
            df = pd.read_csv(stock_list_path, encoding='utf-8-sig')
            row = df[df['code'] == int(symbol)]
            if len(row) > 0:
                return row.iloc[0]['name']
        return symbol


def main():
    """测试入口"""
    import argparse

    parser = argparse.ArgumentParser(description='历史数据管理器')
    subparsers = parser.add_subparsers(dest='command', help='子命令')

    # fetch: 获取单只股票
    p_fetch = subparsers.add_parser('fetch', help='获取单只股票数据')
    p_fetch.add_argument('symbol', help='股票代码')
    p_fetch.add_argument('--start', default='19960101', help='开始日期')
    p_fetch.add_argument('--end', default=None, help='结束日期')

    # batch: 批量获取
    p_batch = subparsers.add_parser('batch', help='批量获取数据')
    p_batch.add_argument('--symbols', nargs='+', help='股票代码列表')
    p_batch.add_argument('--file', help='股票列表文件(CSV)')
    p_batch.add_argument('--n', type=int, default=100, help='随机选择N只')
    p_batch.add_argument('--start', default='19960101', help='开始日期')
    p_batch.add_argument('--end', default=None, help='结束日期')
    p_batch.add_argument('--workers', type=int, default=4, help='并发数')
    p_batch.add_argument('--delay', type=float, default=0.3, help='请求间隔(秒)')

    # status: 查看缓存状态
    p_status = subparsers.add_parser('status', help='查看缓存状态')

    # universe: 获取股票池
    p_universe = subparsers.add_parser('universe', help='获取有足够历史的股票池')
    p_universe.add_argument('--min-days', type=int, default=5000, help='最少历史天数')

    # validate: 验证数据
    p_validate = subparsers.add_parser('validate', help='验证数据完整性')
    p_validate.add_argument('symbol', nargs='?', help='股票代码(不指定则验证全部)')

    args = parser.parse_args()
    manager = HistoricalDataManager()

    if args.command == 'fetch':
        df = manager.fetch_and_cache(args.symbol, args.start, args.end)
        print(f"获取 {args.symbol}: {len(df)} 条记录")
        manager._save_metadata()

    elif args.command == 'batch':
        symbols = []
        if args.symbols:
            symbols = args.symbols
        elif args.file:
            df = pd.read_csv(args.file, encoding='utf-8-sig')
            col = 'code' if 'code' in df.columns else '股票代码'
            symbols = [str(c).zfill(6) for c in df[col].tolist()]
        else:
            # 从stock_list.csv加载
            stock_list = Path(".claude/skills/stock_list.csv")
            if stock_list.exists():
                df = pd.read_csv(stock_list, encoding='utf-8-sig')
                col = 'code' if 'code' in df.columns else '股票代码'
                all_symbols = [str(c).zfill(6) for c in df[col].tolist()]
                if args.n < len(all_symbols):
                    import random
                    symbols = random.sample(all_symbols, args.n)
                else:
                    symbols = all_symbols

        if symbols:
            manager.batch_fetch(symbols, args.start, args.end,
                              delay=args.delay, max_workers=args.workers)

    elif args.command == 'status':
        status_df = manager.get_cache_status()
        if len(status_df) > 0:
            print(f"\n缓存股票数: {len(status_df)}")
            print(f"最新更新: {manager.metadata.get('last_update', 'N/A')}")
            print(f"\n数据概览:")
            print(f"  最早数据: {status_df['first_date'].min()}")
            print(f"  最新数据: {status_df['last_date'].max()}")
            print(f"  平均行数: {status_df['row_count'].mean():.0f}")
            print(f"  总行数: {status_df['row_count'].sum():,.0f}")
        else:
            print("暂无缓存数据")

    elif args.command == 'universe':
        universe = manager.get_universe(min_history_days=args.min_days)
        print(f"\n符合条件的股票: {len(universe)} 只")
        for s in universe[:20]:
            name = manager.get_stock_name(s)
            info = manager.metadata["stocks"][s]
            print(f"  {s} {name} ({info['first_date']} ~ {info['last_date']}, {info['row_count']}行)")
        if len(universe) > 20:
            print(f"  ... 共 {len(universe)} 只")

    elif args.command == 'validate':
        if args.symbol:
            result = manager.validate_integrity(args.symbol)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            all_symbols = manager.get_all_symbols()
            print(f"验证 {len(all_symbols)} 只股票...")
            valid = 0
            invalid = 0
            for sym in all_symbols:
                result = manager.validate_integrity(sym)
                if result['valid']:
                    valid += 1
                else:
                    invalid += 1
                    if result.get('issues'):
                        print(f"  {sym}: {', '.join(result['issues'])}")
            print(f"\n有效: {valid}, 无效: {invalid}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
