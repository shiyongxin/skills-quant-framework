# -*- coding: utf-8 -*-
"""
历史数据管理器 - Historical Data Manager

使用Parquet格式高效管理A股30年历史数据。
支持增量更新、批量获取、数据验证等功能。

存储格式:
    个股 (+复权口径) 一个Parquet文件
    - 不复权 (adjust=''): stock_data/historical/{symbol}.parquet
    - 复权   (adjust='qfq'/'hfq'): stock_data/historical/{symbol}_{adjust}.parquet
    指数 独立命名空间 (审计 M12)
    - stock_data/historical/index/{symbol}.parquet (指数无复权口径)
    与同代码个股互不覆盖: 000001 在个股命名空间是平安银行, 在指数命名空间
    是上证指数 —— 请用 `load()` 读个股 / `load_index()` 读指数。
    Parquet 不可用 (缺 pyarrow / 写失败) 时同名降级为 .csv, 读写两侧对称
    (审计 M13)。

复权是**数据维度**而非装饰 (审计 P0-4): 不同复权口径的序列混在一起会在除权日
产生虚假跳空, 收益率与全部技术指标随之失真。因此复权口径进入文件名与元数据,
不同口径互不覆盖; `load(..., adjust=...)` 只读对应口径的文件, 缺失时返回空
DataFrame (不拿不复权数据冒充前复权)。
"""

import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Semaphore

from core.dataframe import (standardize_daily_frame,
                            standardize_ohlcv_columns)
from core.fetch_result import FetchResult
from sina_daily import fetch_daily, format_symbol
from delisted_stocks import (DelistedRegistry, REGISTRY_MAX_AGE_DAYS,
                            default_registry_path)
from stock_list_manager import get_stock_name as _lookup_stock_name
from js_runtime import js_guard


class HistoricalDataManager:
    """
    历史数据管理器

    使用Parquet格式存储，支持:
    - 增量更新: 读取已有数据，仅获取缺失日期
    - 批量获取: 多线程并发+限速
    - 数据验证: 完整性、异常值检查
    - 股票池管理: 按历史天数过滤
    """

    SOURCE = 'historical_data_manager'   # FetchResult.source 标记

    def __init__(self, data_dir="./stock_data"):
        self.data_dir = Path(data_dir)
        self.historical_dir = self.data_dir / "historical"
        self.historical_dir.mkdir(parents=True, exist_ok=True)
        # 指数独立命名空间 (审计 M12): 沪深300(000300) 与上证指数(000001) 此前
        # 与个股共用 {symbol}.parquet —— 000001 既是上证指数又是平安银行, 取错
        # 前缀会把个股行情写进指数位置 (反之亦然), 体制判定/交易日历随之用错标的
        self.index_dir = self.historical_dir / "index"
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.historical_dir / "metadata.json"
        self.metadata = self._load_metadata()

    def _load_metadata(self) -> dict:
        """加载元数据"""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                # 旧元数据无 indexes 段: 补空段, 避免调用方判 None
                meta.setdefault("indexes", {})
                return meta
            except (json.JSONDecodeError, OSError) as e:
                # 元数据损坏不是小事: 静默重置会让股票池/缓存状态凭空消失
                print(f"[WARN] 元数据文件损坏, 重建空元数据: {str(e)[:80]}")
        return {"last_update": None, "stock_count": 0, "stocks": {},
                "indexes": {}}

    def _save_metadata(self):
        """保存元数据 (原子写: 先写临时文件再改名, 避免读者读到半截 JSON)

        写失败只告警不抛 —— 数据此时已落库, 元数据可事后重建, 不应让
        整次取数失败。
        """
        try:
            tmp = self.metadata_file.with_name(self.metadata_file.name + '.tmp')
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.metadata, f, ensure_ascii=False, indent=2)
            tmp.replace(self.metadata_file)
        except Exception as e:
            print(f"[WARN] 元数据保存失败: {str(e)[:100]}")

    def _format_symbol(self, symbol: str, is_index: bool = False) -> str:
        """格式化为新浪接口格式 (sh/sz/bj 前缀)

        个股: 6→sh (沪市主板), 0/3→sz (深市主板/创业板),
              4/8/92→bj (北交所, 规则单一真相源 sina_daily.format_symbol,
              审计 M18 —— 旧实现缺 bj 分支, 920xxx 裸码取数静默失败)
        指数: 000xxx→sh (沪市指数, 如 沪深300=000300/上证50=000016),
              399xxx→sz (深市指数, 如 深证成指=399001/创业板指=399006)

        ⚠️ 指数必须显式声明 is_index=True, **不能靠代码猜** (审计 M12):
        000001 既是上证指数(sh000001)又是平安银行(sz000001); 000905/000852
        等也是"既有个股又有指数"的占用关系 (见 stock_list.csv)。此前无此
        标志, 指数一律被映射成 sz000300 —— 沪深300 在沪市, 新浪无该代码,
        取数必然落空; 而 000001 会取回**平安银行个股行情**冒充上证指数。
        """
        symbol = str(symbol).zfill(6)
        if is_index:
            if symbol.startswith('399'):
                return f'sz{symbol}'
            # 000xxx (沪深300/上证50/中证500 等) 与其余指数码默认按沪市
            return f'sh{symbol}'
        return format_symbol(symbol)

    def _get_index_path(self, symbol: str) -> Path:
        """指数行情的Parquet路径 (独立命名空间, 审计 M12)

        historical/index/{symbol}.parquet —— 与个股 {symbol}.parquet 隔离:
        000001 在个股命名空间是平安银行, 在指数命名空间是上证指数, 互不覆盖。
        """
        return self.index_dir / f"{str(symbol).zfill(6)}.parquet"

    def _get_index_csv_path(self, symbol: str) -> Path:
        """指数行情的CSV降级路径 (与Parquet路径同构)"""
        return self.index_dir / f"{str(symbol).zfill(6)}.csv"

    def _get_parquet_path(self, symbol: str, adjust: str = "") -> Path:
        """获取Parquet文件路径 (复权口径进文件名, 审计 P0-4)

        不复权 → {symbol}.parquet (向后兼容既有文件)
        复权   → {symbol}_{adjust}.parquet (qfq/hfq 互不覆盖)
        """
        code = str(symbol).zfill(6)
        tag = (adjust or "").strip().lower()
        if not tag or tag in ("none", "raw", "bfq"):
            return self.historical_dir / f"{code}.parquet"
        return self.historical_dir / f"{code}_{tag}.parquet"

    @staticmethod
    def _adjust_tag(adjust: str) -> str:
        """复权口径的规范标签 (''=不复权)"""
        tag = (adjust or "").strip().lower()
        return "" if tag in ("", "none", "raw", "bfq") else tag

    def _get_csv_path(self, symbol: str, adjust: str = "") -> Path:
        """获取CSV路径 (Parquet不可用时的降级路径, 审计 P0-4)

        与 `_get_parquet_path` 同构: 文件名带复权口径标签, 不同口径互不覆盖。
        旧实现降级时固定写 {symbol}.csv → qfq 数据占用"不复权"位置,
        load(adjust='') 会把前复权序列当不复权返回 (口径冒充)。
        """
        code = str(symbol).zfill(6)
        tag = self._adjust_tag(adjust)
        if not tag:
            return self.historical_dir / f"{code}.csv"
        return self.historical_dir / f"{code}_{tag}.csv"

    def _migrate_legacy_csv(self, symbol: str) -> Optional[Path]:
        """存量迁移: 旧版无标签 CSV ({symbol}.csv) → 按元数据判定口径后改名

        旧实现的降级文件不带复权标签, 可能装的是任一口径的序列。元数据
        (metadata['stocks'][symbol*]['adjust']) 是旧文件口径的唯一证据:
          - 只记录了一个**非不复权**口径 (qfq/hfq) → 该文件就是这一口径的
            序列, 改名为 {symbol}_{tag}.csv, 之后各归各位 (不复权请求不再命中)
          - 其它 (记的是不复权 / 记了多个口径 / 没有元数据) → 不动它,
            按"不复权"惯例处理 (与 {symbol}.parquet 口径一致)

        Returns:
            迁移后的路径 (未迁移则 None)
        """
        code = str(symbol).zfill(6)
        legacy = self.historical_dir / f"{code}.csv"
        if not legacy.exists():
            return None
        recorded = set()
        for key, meta in (self.metadata.get("stocks") or {}).items():
            if key == code or key.startswith(f"{code}_"):
                recorded.add(str((meta or {}).get("adjust") or ""))
        if len(recorded) != 1:
            return None
        tag = next(iter(recorded))
        if not tag:
            return None
        target = self._get_csv_path(code, tag)
        if target.exists():
            return None
        try:
            legacy.replace(target)
        except OSError as e:
            print(f"[WARN] {code} 存量CSV口径迁移失败: {str(e)[:80]}")
            return None
        print(f"[INFO] {code} 存量CSV口径迁移: {legacy.name} → {target.name} "
              f"(依据元数据 adjust={tag})")
        return target

    @staticmethod
    def _read_local(parquet_path: Path, csv_path: Path,
                    label: str = "") -> Optional[pd.DataFrame]:
        """读本地缓存: Parquet 优先, 失败降级同口径 CSV (审计 M13)

        写路径早有 CSV 降级 (pyarrow 缺失/to_parquet 失败时落 CSV), 读路径
        此前却是裸 `pd.read_parquet` —— 缺 pyarrow 时 `load()` 直接抛
        ImportError。两侧现在对称: 读不到 Parquet 就读同口径 CSV。

        Returns:
            DataFrame 或 None (两者都读不了 / 都不存在)
        """
        if parquet_path.exists():
            try:
                return pd.read_parquet(parquet_path)
            except Exception as e:
                print(f"[WARN] {label} Parquet读取失败({type(e).__name__}), "
                      f"降级读同口径CSV: {str(e)[:80]}")
        if csv_path.exists():
            try:
                df = pd.read_csv(csv_path, encoding='utf-8-sig')
                if '日期' in df.columns:
                    df['日期'] = pd.to_datetime(df['日期'])
                return df
            except Exception as e:
                print(f"[WARN] {label} CSV读取失败: {str(e)[:80]}")
        return None

    @staticmethod
    def _save_local(df: pd.DataFrame, parquet_path: Path, csv_path: Path,
                    label: str = "") -> None:
        """落盘: Parquet 优先, 失败降级同口径 CSV (写路径, 原有行为不变)"""
        try:
            df.to_parquet(parquet_path, engine='pyarrow', compression='snappy',
                          index=False)
        except Exception as e:
            print(f"[WARN] {label} Parquet保存失败: {e}")
            df.to_csv(csv_path, index=False, encoding='utf-8-sig')

    def fetch_and_cache(self, symbol: str, start_date: str = "19960101",
                        end_date: str = None, adjust: str = "",
                        is_index: bool = False,
                        _persist_metadata: bool = True) -> pd.DataFrame:
        """
        获取并缓存历史数据（增量更新, 按复权口径分文件存储）

        Parameters:
        -----------
        symbol : str
            股票代码，如 "000001"; is_index=True 时为指数代码 (如 "000300")
        start_date : str
            开始日期
        end_date : str
            结束日期，默认今天
        adjust : str
            复权口径 — ''(不复权, 默认) / 'qfq' / 'hfq'。不同口径写不同
            Parquet 文件, 互不覆盖 (审计 P0-4)。指数无复权概念, is_index=True
            时被忽略
        is_index : bool
            是否指数 (审计 M12)。True 时: ① 按指数规则加前缀 (000xxx→sh,
            399xxx→sz) ② 走指数接口 stock_zh_index_daily ③ 存入独立命名空间
            historical/index/, 与同代码个股 (如 000001 平安银行 vs 上证指数)
            互不覆盖
        _persist_metadata : bool
            是否把元数据落盘 (默认 True)。批量路径传 False —— 由
            batch_fetch 主线程统一落盘, 避免多线程并发写同一文件。

        Returns:
        --------
        pd.DataFrame : 完整的历史数据
        """
        symbol = str(symbol).zfill(6)
        adjust = self._adjust_tag(adjust)
        if is_index and adjust:
            print(f"[INFO] {symbol} 指数行情无复权口径, 忽略 adjust='{adjust}'")
            adjust = ""
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")

        if is_index:
            parquet_path = self._get_index_path(symbol)
            csv_path = self._get_index_csv_path(symbol)
        else:
            parquet_path = self._get_parquet_path(symbol, adjust)
            csv_path = self._get_csv_path(symbol, adjust)

        # 检查已有数据 (Parquet 优先, 读不到降级同口径 CSV — 审计 M13:
        # 此前 CSV 降级存的数据在增量更新时读不到, 每次都从头全量重取)
        existing_df = self._read_local(parquet_path, csv_path, label=symbol)
        try:
            if existing_df is not None and len(existing_df) > 0:
                last_date = pd.to_datetime(existing_df['日期'].iloc[-1])
                # 如果数据足够新(距今3天内)，直接返回
                if last_date >= pd.to_datetime(end_date) - timedelta(days=3):
                    return existing_df
                # 增量获取: 从最后日期的下一天开始
                start_date = (last_date + timedelta(days=1)).strftime("%Y%m%d")
        except Exception:
            existing_df = None

        # 从API获取数据
        if is_index:
            new_df = self._fetch_index_from_api(symbol, start_date, end_date)
        else:
            new_df = self._fetch_from_api(symbol, start_date, end_date, adjust)

        if new_df is None or len(new_df) == 0:
            # API失败或无新数据: 返回已有数据, 但明确提示"这是旧数据"
            if existing_df is not None:
                last_date = pd.to_datetime(existing_df['日期'].iloc[-1])
                print(f"[WARN] {symbol} API无新数据/失败, 返回本地旧数据(最后日期 {last_date.date()})")
                return existing_df
            return pd.DataFrame()

        # 合并数据
        if existing_df is not None and len(existing_df) > 0:
            combined = pd.concat([existing_df, new_df], ignore_index=True)
            combined = combined.drop_duplicates(subset=['日期'], keep='last')
            combined = combined.sort_values('日期').reset_index(drop=True)
        else:
            combined = new_df

        # 保存 (Parquet 优先, 失败降级同口径 CSV)
        self._save_local(combined, parquet_path, csv_path, label=symbol)

        # 更新元数据 (复权口径入库, 审计 P0-4; 指数单独记, 不进股票池)
        entry = {
            "first_date": str(combined['日期'].iloc[0].date()) if hasattr(combined['日期'].iloc[0], 'date') else str(combined['日期'].iloc[0]),
            "last_date": str(combined['日期'].iloc[-1].date()) if hasattr(combined['日期'].iloc[-1], 'date') else str(combined['日期'].iloc[-1]),
            "row_count": len(combined),
            "updated": datetime.now().isoformat()
        }
        if is_index:
            entry["symbol"] = self._format_symbol(symbol, is_index=True)
            self.metadata["indexes"][symbol] = entry
        else:
            entry["adjust"] = adjust
            meta_key = symbol if not adjust else f"{symbol}_{adjust}"
            self.metadata["stocks"][meta_key] = entry
        self.metadata["last_update"] = datetime.now().isoformat()
        self.metadata["stock_count"] = len(self.metadata["stocks"])
        # 元数据落盘 (复权口径/日期范围/行数) —— 旧实现只改内存不落盘,
        # 导致 metadata.json 永远不存在: get_cache_status/list_cached_symbols
        # 恒空, 且存量 CSV 的口径判定 (按元数据) 无据可依
        if _persist_metadata:
            self._save_metadata()

        return combined

    def _fetch_from_api(self, symbol: str, start_date: str, end_date: str,
                        adjust: str = "") -> pd.DataFrame:
        """从新浪接口获取数据 (adjust=复权口径, 审计 P0-4)

        sh/sz 透传 ak.stock_zh_a_daily; bj 走 sina_daily 的 klc 直连
        (akshare 对 bj 在 amount 步骤崩溃 — 审计 M18)。
        """
        sina_symbol = self._format_symbol(symbol)
        adjust = self._adjust_tag(adjust)

        try:
            start_dt = datetime.strptime(start_date, "%Y%m%d").date()
            end_dt = datetime.strptime(end_date, "%Y%m%d").date()

            df = fetch_daily(
                symbol=sina_symbol,
                start_date=start_dt,
                end_date=end_dt,
                adjust=adjust
            )

            if df is not None and len(df) > 0:
                # 标准化列名 + 日期排序 + 涨跌幅 (共享单一真相源, 审计 M19)
                df = standardize_daily_frame(df)

                return df

        except Exception as e:
            # 不再静默: 记录错误, 调用方 (fetch_and_cache) 会区分"API失败"与"无新数据"
            print(f"[WARN] {symbol} API获取失败: {str(e)[:120]}")

        return None

    def _fetch_index_from_api(self, symbol: str, start_date: str,
                              end_date: str) -> pd.DataFrame:
        """从 akshare 指数接口获取数据 (审计 M12)

        与个股分开走 `stock_zh_index_daily` (与 market_regime_classifier /
        historical_backtest_validator 同一接口), 不复用个股的
        `stock_zh_a_daily`: 指数与个股代码存在占用关系 (000001 上证指数 vs
        平安银行), 只换前缀不换接口仍可能取错标的。
        """
        sina_symbol = self._format_symbol(symbol, is_index=True)
        try:
            # 指数接口内部用 py_mini_racer 解密 (V8 非线程安全) → 整段串行化:
            # 闸门未生效时也能保证"同一时刻只有一个线程在 V8 里" (崩溃根因)
            with js_guard():
                df = ak.stock_zh_index_daily(symbol=sina_symbol)

            if df is not None and len(df) > 0:
                df = standardize_ohlcv_columns(df)
                if '日期' not in df.columns:
                    print(f"[WARN] {symbol} 指数接口返回列异常, 无日期列")
                    return None
                df['日期'] = pd.to_datetime(df['日期'])
                start_dt = pd.to_datetime(start_date)
                end_dt = pd.to_datetime(end_date)
                df = df[(df['日期'] >= start_dt) & (df['日期'] <= end_dt)]
                # 标准化 (幂等) + 按日期排序 + 重置索引 + 涨跌幅
                # (共享单一真相源, 审计 M19)
                df = standardize_daily_frame(df)

                return df

        except Exception as e:
            print(f"[WARN] {symbol} 指数API获取失败: {str(e)[:120]}")

        return None

    # ------------------------------------------------------------------
    # 共享数据层的日线入口 (审计 M20)
    # ------------------------------------------------------------------
    def get_daily_result(self, symbol: str, *, days: int = None,
                          start_date: str = None, end_date: str = None,
                          adjust: str = '', as_of: str = None,
                          min_rows: int = 0,
                          trading_calendar=None) -> FetchResult:
        """共享数据层的日线入口 —— 供"各自取数"的模块统一走本层 (审计 M20)。

        一次给齐以前缺失的四件事:

        - **复权维度** (adjust): ''=不复权 / 'qfq' / 'hfq'。落库文件名与
          元数据都带该维度 (审计 P0-4) → 不复权序列含除权跳空, 收益率/指标
          会失真。此前 `long_term_selector` / `reversal_detector` 自行调
          `fetch_daily` → **无此维度**, 与 P0-4 口径矛盾。
        - **参考日** (as_of): 显式 as_of 优先; None → 今天 (实时取数默认)。
          结果的 `as_of` 字段记录实际参考日 → 需要可复现的调用方必须显式传。
        - **FetchResult**: 失败带 error (不再静默 None / 空 DF 假装成功)。
        - **交易日历**: 用"最近 N 个**交易日**"换算取数窗口 (无日历 → 降级
          为自然日并在 meta 标记 `calendar_used=False`, 不静默)。

        Args:
            symbol: 股票代码 (6 位; 前缀规则由本层处理)
            days: 需要最近多少根日线 (按交易日换算窗口)
            start_date / end_date: 显式窗口 (优先于 days)
            adjust: 复权口径
            as_of: 参考日 (显式传入 → 可复现)
            min_rows: 最少行数 (不足 → ok=False + 原因)
            trading_calendar: 交易日历 (None → 尝试用本地指数现算, 不联网)

        Returns:
            FetchResult (ok=False 时 data 为空 DF, error 说明原因)
        """
        symbol = str(symbol).zfill(6)
        adjust = self._adjust_tag(adjust)

        # 参考日: 显式 as_of 优先, 否则今天 (实时取数默认; 结果记录实际值)
        if as_of is not None:
            try:
                ref = pd.Timestamp(as_of).date()
            except (TypeError, ValueError):
                return FetchResult.failure(
                    f'as_of 解析失败: {as_of!r}', source=self.SOURCE,
                    adjust=adjust)
        else:
            ref = datetime.now().date()

        # 取数窗口起点
        win_start = None
        calendar_used = False
        if start_date is not None:
            try:
                win_start = pd.Timestamp(start_date).date()
            except (TypeError, ValueError):
                return FetchResult.failure(
                    f'start_date 解析失败: {start_date!r}',
                    source=self.SOURCE, adjust=adjust)
        elif days:
            win_start, calendar_used = self._window_start(ref, days,
                                                          trading_calendar)

        end = end_date or ref.strftime('%Y%m%d')
        begin = win_start.strftime('%Y%m%d') if win_start else "19960101"

        df = self.fetch_and_cache(symbol, start_date=begin, end_date=end,
                                  adjust=adjust)
        if df is None or len(df) == 0:
            return FetchResult.failure(
                f'取数失败或无数据 (symbol={symbol}, adjust={adjust or "raw"})',
                source=self.SOURCE, adjust=adjust,
                as_of=ref.isoformat(),
                meta={'window_start': begin, 'window_end': end,
                      'calendar_used': calendar_used, 'n_rows': 0})

        # 裁剪到请求窗口 (fetch_and_cache 会与本地缓存合并 → 可能含窗口外行)
        if '日期' in df.columns:
            mask = pd.to_datetime(df['日期']) <= pd.Timestamp(ref)
            if win_start is not None:
                mask &= pd.to_datetime(df['日期']) >= pd.Timestamp(win_start)
            df = df[mask].reset_index(drop=True)

        if len(df) < min_rows:
            return FetchResult.failure(
                f'数据不足 ({len(df)} 行 < 要求的 {min_rows} 行)',
                source=self.SOURCE, adjust=adjust,
                as_of=ref.isoformat(),
                meta={'window_start': begin, 'window_end': end,
                      'calendar_used': calendar_used, 'n_rows': len(df)})

        return FetchResult(
            ok=True, data=df, source=self.SOURCE, adjust=adjust,
            as_of=ref.isoformat(),
            meta={'window_start': begin, 'window_end': end,
                  'calendar_used': calendar_used, 'n_rows': len(df)})

    def _window_start(self, ref, days: int, trading_calendar=None):
        """取数窗口起点: 有交易日历 → N 个交易日前; 无 → 自然日 days*2。

        日历来源: 显式传入 > 本地指数行情现算 (不联网、不落盘)。都没有 →
        降级为自然日并返回 `calendar_used=False` (如实标记, 不静默)。
        """
        cal = trading_calendar
        if cal is None:
            cal = self._local_calendar()
        if cal is not None:
            try:
                first = cal.first_day          # property (不是方法)
                tdays = (cal.trading_days_between(first, ref)
                         if first is not None else [])
            except Exception:
                tdays = []
            if tdays:
                if len(tdays) > days:
                    return tdays[len(tdays) - days], True
                return tdays[0], True
        return ref - timedelta(days=days * 2), False

    def _local_calendar(self):
        """由本地指数行情现算交易日历 (不联网、**不落盘**)。

        `build_calendar_from_index` 会写日历 JSON 并注入进程级单例 →
        取数路径不写仓库目录, 故这里直接用 `TradingCalendar.from_index`。
        本地无指数行情 → None (不臆造日历)。
        """
        try:
            index_df = self.load_index('000001')
        except Exception:
            return None
        if index_df is None or len(index_df) == 0:
            return None
        try:
            from core.trading_calendar import TradingCalendar
            return TradingCalendar.from_index(index_df)
        except Exception:
            return None

    def load(self, symbol: str, start_date: str = None,
             end_date: str = None, adjust: str = "") -> pd.DataFrame:
        """
        加载本地缓存的**个股**历史数据 (按复权口径取对应文件)

        指数请用 `load_index()` (独立命名空间, 审计 M12)。

        Parameters:
        -----------
        symbol : str
            股票代码
        start_date : str
            开始日期 (可选)
        end_date : str
            结束日期 (可选)
        adjust : str
            复权口径 (''/qfq/hfq) — 缺失该口径文件时返回**空 DataFrame**
            (不拿不复权数据冒充前复权, 审计 P0-4)

        Returns:
        --------
        pd.DataFrame
        """
        symbol = str(symbol).zfill(6)
        adjust = self._adjust_tag(adjust)
        # 存量: 旧版无标签 CSV 先按元数据判定口径并归位 (一次性迁移)
        self._migrate_legacy_csv(symbol)
        # 同口径标签: 缺 qfq 文件不拿不复权 CSV 冒充
        df = self._read_local(self._get_parquet_path(symbol, adjust),
                              self._get_csv_path(symbol, adjust),
                              label=symbol)
        if df is None:
            return pd.DataFrame()

        # 日期过滤
        if start_date:
            df = df[df['日期'] >= pd.to_datetime(start_date)]
        if end_date:
            df = df[df['日期'] <= pd.to_datetime(end_date)]

        return df.reset_index(drop=True)

    def load_index(self, symbol: str, start_date: str = None,
                   end_date: str = None) -> pd.DataFrame:
        """
        加载本地缓存的**指数**历史数据 (独立命名空间, 审计 M12)

        与个股命名空间隔离: 000001 在 `load()` 是平安银行, 在 `load_index()`
        是上证指数, 互不覆盖。指数数据由
        `fetch_and_cache(code, is_index=True)` 写入 historical/index/。

        Parameters:
        -----------
        symbol : str
            指数代码 (如 "000300" 沪深300 / "000001" 上证指数)
        start_date : str
            开始日期 (可选)
        end_date : str
            结束日期 (可选)

        Returns:
        --------
        pd.DataFrame : 无缓存时返回空 DataFrame (不臆造)
        """
        symbol = str(symbol).zfill(6)
        df = self._read_local(self._get_index_path(symbol),
                              self._get_index_csv_path(symbol),
                              label=f"指数{symbol}")
        if df is None:
            return pd.DataFrame()

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
                df = self.fetch_and_cache(sym, start_date, end_date,
                                          _persist_metadata=False)
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

    def _reference_date(self, as_of=None):
        """股票池的**参考日** (审计 H4)。

        旧实现用 `datetime.now()` → ① 同一份代码在不同时间跑出不同股票池
        (不可复现); ② 用"今天"当基准去描述"历史" → 前视。

        现改为**数据驱动**: 显式 `as_of` 优先, 否则取**缓存最新日**
        (本地数据实际覆盖到的最新日期) —— 与 wall clock 无关, 可复现。
        """
        if as_of is not None:
            try:
                return pd.Timestamp(as_of).date()
            except (ValueError, TypeError):
                raise ValueError(f'as_of 解析失败: {as_of!r}')

        latest = None
        for info in self.metadata.get("stocks", {}).values():
            raw = info.get("last_date")
            if not raw:
                continue
            try:
                d = pd.Timestamp(raw).date()
            except (ValueError, TypeError):
                continue
            if latest is None or d > latest:
                latest = d
        return latest

    def delisted_registry(self) -> DelistedRegistry:
        """退市清单 (本 manager 的 data_dir 下)

        每次现读, **不设读缓存**: 清单是数据缓存, 缓存读侧对象会让
        `delisted refresh` 后仍读到旧清单 (新鲜度证据失效)。
        """
        return DelistedRegistry.load(default_registry_path(self.data_dir))

    def _universe_meta(self, as_of=None) -> dict:
        """股票池口径元数据 (幸存者偏差**由证据得出**) —— 审计 H4 + D1。

        H4 阶段此处是硬编码 True (退市股行情缺位 → 只能标记); D1 补齐
        退市清单基建后, 标记改按 **四条证据规则**推导 —— 任一不满足即
        保守保持 True, 全部满足才允许 False:

        ① **清单可用**: 没刷新过退市清单 → "没查过" ≠ "没有偏差"
        ② **补齐**: 缓存含清单内**全部在范围**退市股 (B股 900/200 不在
           框架股票池范围, 见 delisted_stocks)
        ③ **新鲜**: 清单刷新于 REGISTRY_MAX_AGE_DAYS 内 —— 过期则期间
           可能已有新退市股未入清单, 不足以支撑"偏差已消除"
        ④ **覆盖**: 参考日 ≥ 各交易所最早退市记录的**最晚者**, 且沪深
           两市均有记录 —— 早于清单覆盖起点的参考日, 当时更早的退市
           记录未知 (北交所无公开名录接口, 残余限制写进 note)

        元数据键 `delisted_registry` 落全部证据 (清单统计 + 缓存补齐数)
        → 报告/落盘可复核, 不是口头声明。
        """
        stocks = self.metadata.get("stocks", {})
        firsts, lasts = [], []
        for info in stocks.values():
            for key, bucket in (("first_date", firsts), ("last_date", lasts)):
                raw = info.get(key)
                if not raw:
                    continue
                try:
                    bucket.append(pd.Timestamp(raw).date())
                except (ValueError, TypeError):
                    continue
        ref = self._reference_date(as_of)

        reg = self.delisted_registry()
        st = reg.stats()
        in_scope_codes = reg.codes(in_scope=True)
        n_scope = len(in_scope_codes)
        n_done = sum(1 for c in in_scope_codes if c in stocks)

        # ---- 四条证据规则 (任一不满足 → 保守 True) ----
        by_ex = st.get('coverage_start_by_exchange') or {}
        both_exchanges = {'sh', 'sz'} <= set(by_ex)
        coverage_start = (pd.Timestamp(st['coverage_start']).date()
                          if st.get('coverage_start') else None)

        if not st['available'] or n_scope == 0:
            bias = True
            note = ('本地缓存未含退市股行情 (退市清单未刷新或为空) → '
                    '当时已退市的股票不在池内 → 股票池带幸存者偏差; '
                    '清单缺失 = 没查过, 不等于没有偏差 '
                    '(刷新清单: historical_data_manager.py delisted refresh)')
        elif n_done < n_scope:
            bias = True
            note = (f'本地缓存已补 {n_done}/{n_scope} 只在范围退市股行情, '
                    f'仍缺 {n_scope - n_done} 只 → 池内仍缺当时已退市股票 '
                    f'→ 幸存者偏差仍开 (补齐: historical_data_manager.py '
                    f'delisted fetch)')
        elif not st['fresh']:
            bias = True
            note = (f'退市清单已 {st["age_days"]} 天未刷新 '
                    f'(新鲜度门槛 {REGISTRY_MAX_AGE_DAYS} 天) → 期间可能有'
                    f'新退市股未入清单 → 不足以声明偏差已消除 '
                    f'(刷新: historical_data_manager.py delisted refresh)')
        elif ref is None or not both_exchanges:
            bias = True
            miss = sorted({'sh', 'sz'} - set(by_ex))
            why = ('参考日不可得' if ref is None
                   else f'清单缺 {"/".join(miss)} 市退市记录')
            note = (f'{why} → 无法验证覆盖完整性 → 保守保持幸存者偏差标记'
                    f' (清单覆盖起点 {st.get("coverage_start")})')
        elif ref < coverage_start:
            bias = True
            note = (f'清单覆盖的退市记录始于 {coverage_start} (各交易所最早'
                    f'记录的最晚者); 参考日 {ref} 早于该起点 → 早期退市'
                    f'记录未知 → 残余幸存者偏差')
        else:
            bias = False
            note = (f'本地缓存含全部 {n_scope} 只在范围退市股行情 '
                    f'(清单: {st.get("exchanges")}, 退市记录覆盖 '
                    f'{coverage_start} ~ {st.get("coverage_end")}, 刷新于 '
                    f'{st.get("fetched_at")}) → 点时股票池含当时已退市股票 '
                    f'→ 幸存者偏差已消除; 范围外残余: B股 '
                    f'{st.get("n_out_of_scope", 0)} 只 (框架股票池不含), '
                    f'北交所无公开退市名录接口')

        return {
            'as_of': str(ref) if ref else None,
            'n_cached_stocks': len(stocks),
            'data_range': [str(min(firsts)) if firsts else None,
                           str(max(lasts)) if lasts else None],
            'survivorship_bias': bias,
            'survivorship_note': note,
            # 证据落盘 (清单统计 + 补齐数) → 声明可复核 (审计 D1)
            'delisted_registry': {**st, 'n_cached_in_scope': n_done,
                                  'n_in_scope': n_scope},
        }

    def get_universe(self, min_history_days: int = 5000,
                     min_rows: int = 2000, as_of=None) -> list:
        """
        获取有足够历史数据的股票池 (审计 H4: 支持 point-in-time)

        Parameters:
        -----------
        min_history_days : int
            最少历史天数(自然日) —— 相对 **参考日** (as_of 或缓存最新日)
        min_rows : int
            最少数据行数(交易日)
        as_of : date or None
            截止日。None = 当前视角 (参考日 = 缓存最新日)。
            给出时按 **point-in-time** 判定: 该股须在 as_of 之前已上市
            (first_date ≤ as_of − min_history_days) 且**数据覆盖到 as_of**
            (last_date ≥ as_of) → 不含"as_of 之后才上市/才有数据"的股票
            (前视)。缓存不覆盖 as_of → 直接报错 (部分覆盖的股票池 =
            静默有偏的股票池)。

        Returns:
        --------
        list : 符合条件的股票代码列表

        Raises:
            ValueError: as_of 超出缓存覆盖范围 (拒绝静默给出偏池)
        """
        universe = []

        ref_date = self._reference_date(as_of)
        if ref_date is None:
            return []

        if as_of is not None:
            # 缓存必须覆盖 as_of, 否则池子会静默缺数据 → 拒绝
            latest = max((pd.Timestamp(i.get("last_date")).date()
                           for i in self.metadata.get("stocks", {}).values()
                           if i.get("last_date")), default=None)
            if latest is None or latest < ref_date:
                raise ValueError(
                    f'缓存数据不覆盖 as_of={ref_date} (缓存最新 {latest}) — '
                    '拒绝返回部分覆盖的股票池 (会静默引入偏差)')

        cutoff_date = ref_date - timedelta(days=min_history_days)

        for sym, info in self.metadata.get("stocks", {}).items():
            row_count = info.get("row_count", 0)
            last_date_str = info.get("last_date", "")
            first_date_str = info.get("first_date", "")

            if row_count < min_rows:
                continue

            try:
                last_date = datetime.strptime(last_date_str, "%Y-%m-%d").date()
                first_date = datetime.strptime(first_date_str, "%Y-%m-%d").date()
            except (TypeError, ValueError):
                # 日期缺失/格式坏 → 视为数据不足, 跳过 (非意外错误)
                continue

            # 数据必须覆盖到参考日 (否则该股在参考日"不存在" —— 已退市
            # 或数据未取到)
            if last_date < ref_date:
                continue

            # 历史长度相对**参考日**判定 (旧实现相对 now → 前视)
            if first_date > cutoff_date:
                continue

            universe.append(sym)

        return sorted(universe)

    def get_universe_meta(self, min_history_days: int = 5000,
                          min_rows: int = 2000, as_of=None) -> dict:
        """股票池 + 口径元数据 (含幸存者偏差标记) —— 审计 H4。

        Returns:
            dict: {universe, as_of, n_stocks, survivorship_bias, ...}
        """
        meta = self._universe_meta(as_of)
        meta.update({
            'min_history_days': min_history_days,
            'min_rows': min_rows,
        })
        meta['universe'] = self.get_universe(min_history_days, min_rows, as_of)
        meta['n_stocks'] = len(meta['universe'])
        return meta

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

    def get_trading_calendar(self, index_code: str = "000001"):
        """由本地指数行情构建交易日历 (审计 C-P1-12 遗留项: 停牌建模)。

        指数每个交易日都有行情行 → 指数日期集合即交易日历;
        个股缺失的交易日 = 真停牌日 (不再误伤节假日)。

        Args:
            index_code: 指数代码 (默认上证 000001; 读**指数**命名空间
                `load_index()`, 不是同代码个股 —— 000001 是上证指数不是
                平安银行; 本地无该指数数据时返回 None)

        Returns:
            core.trading_calendar.TradingCalendar 或 None (无指数数据, 不臆造)
        """
        from core.trading_calendar import build_calendar_from_index

        try:
            index_df = self.load_index(index_code)
        except Exception as e:
            print(f"[WARN] 交易日历构建失败({index_code}): {str(e)[:80]}")
            return None
        if index_df is None or len(index_df) == 0:
            return None
        return build_calendar_from_index(index_df, data_dir=str(self.data_dir))

    def get_all_symbols(self) -> list:
        """获取所有已缓存的股票代码"""
        return sorted(self.metadata.get("stocks", {}).keys())

    def get_stock_name(self, symbol: str) -> str:
        """获取股票名称 (stock_list_manager 单例, __file__ 基准 — 审计 M15)

        旧实现用 CWD 相对路径读 skills 目录下的 stock_list.csv: 仓库根
        以外运行即取不到; 每次调用重读 CSV; 用 int(symbol) 匹配 (非数字代码
        直接 ValueError)。现复用 stock_list_manager 单例 (路径基于 __file__,
        加载一次)。查不到时返回入参本身 (与旧行为一致)。
        """
        s = str(symbol)
        if s.isdigit():
            s = s.zfill(6)
        name = _lookup_stock_name(s)
        return name if name else str(symbol)


def _delisted_coverage(reg: DelistedRegistry, manager: "HistoricalDataManager"):
    """清单内**尚未缓存**的在范围退市股 (审计 D1 的补齐口径)"""
    codes = reg.codes(in_scope=True)
    cached = manager.metadata.get("stocks", {})
    missing = [c for c in codes if c not in cached]
    return codes, missing


def _run_delisted_command(args, manager, fetcher=None) -> int:
    """`delisted` 子命令分派 —— 退市清单与历史行情 (审计 D1)

    独立成模块级函数: 可注入 manager (临时目录) 与 fetcher (测试打桩),
    不碰仓库默认 data_dir (测试隔离红线, 见 tests/conftest.py 教训)。

    子命令:
        refresh — 联网刷新退市清单 (上交所+深交所; **全成功才落盘**,
                  半份清单会让"清单内已全部补齐"的 False 声明建立在
                  缺失数据上)
        status  — 清单证据 (来源/时间/覆盖) + 缓存补齐覆盖统计
        fetch   — 补齐清单内尚未缓存的 A股退市股行情 (batch 路径;
                  已退市数据不会变 → 已缓存的不重取)

    Returns:
        int: 退出码 —— 0 = 成功且证据齐 (status: 已补齐); 1 = 失败 /
             缺子命令 / 证据不齐 (清单不可用、有缺股、刷新失败)
    """
    reg = DelistedRegistry.load(default_registry_path(manager.data_dir))
    cmd = args.delisted_cmd   # 子命令未给时 argparse 置 None (set_defaults)

    if cmd == "refresh":
        try:
            reg.refresh(fetcher=fetcher)
        except Exception as e:  # noqa: BLE001 — 如实报错, 旧清单未动
            print(f"[ERROR] 退市清单刷新失败 (旧清单未动): {e}")
            return 1
        st = reg.stats()
        print(f"[OK] 退市清单已刷新 → {reg.path}")
        print(f"     共 {st['n']} 只 (在范围 A股 {st['n_in_scope']} / "
              f"B股 {st['n_out_of_scope']}); 退市记录 "
              f"{st['coverage_start']} ~ {st['coverage_end']}")
        return 0

    if cmd == "status":
        st = reg.stats()
        print(f"清单文件: {st['path']}")
        if not st["available"]:
            print("[WARN] 清单不可用 (未刷新过) → 幸存者偏差保持 True "
                  "(没查过 ≠ 没有偏差)")
            return 1
        codes, missing = _delisted_coverage(reg, manager)
        print(f"刷新于: {st['fetched_at']} ({st['age_days']} 天前"
              f"{'' if st['fresh'] else ', **已过期**'})")
        print(f"记录: 共 {st['n']} 只 (在范围 {st['n_in_scope']} / "
              f"B股 {st['n_out_of_scope']}); 交易所 {st['exchanges']}")
        print(f"退市记录覆盖: {st['coverage_start']} ~ {st['coverage_end']}")
        print(f"缓存补齐: {len(codes) - len(missing)}/{len(codes)} "
              f"(尚缺 {len(missing)} 只)")
        if missing:
            head = ", ".join(missing[:10])
            print(f"  缺: {head}{' ...' if len(missing) > 10 else ''}")
            print("  补齐: historical_data_manager.py delisted fetch")
        return 0 if not missing else 1

    if cmd == "fetch":
        if not reg.available:
            print("[ERROR] 退市清单不可用 → 先跑: "
                  "historical_data_manager.py delisted refresh")
            return 1
        codes = reg.codes(in_scope=None if args.include_b else True)
        cached = manager.metadata.get("stocks", {})
        missing = [c for c in codes if c not in cached]
        n_b = reg.stats()["n_out_of_scope"]
        print(f"[INFO] 清单{'全量' if args.include_b else '在范围'} "
              f"{len(codes)} 只: 已缓存 {len(codes) - len(missing)} 只, "
              f"本次补齐 {len(missing)} 只"
              + (f"; B股 {n_b} 只{'已纳入' if args.include_b else '默认跳过'}"
                 f" (框架股票池不含B股)" if n_b else ""))
        if not missing:
            return 0
        manager.batch_fetch(missing, start_date=args.start,
                            end_date=args.end, delay=args.delay,
                            max_workers=args.workers)
        manager._save_metadata()
        still = [c for c in codes if c not in
                 manager.metadata.get("stocks", {})]
        if still:
            print(f"[WARN] 补齐后仍缺 {len(still)} 只 (取数失败/接口无数据) "
                  f"→ 幸存者偏差保持 True")
            return 1
        print(f"[OK] 清单内 {len(codes)} 只退市股行情全部在缓存 → "
              f"幸存者偏差证据齐 (下次 meta 判定见四条规则)")
        return 0

    print("用法: historical_data_manager.py delisted "
          "{refresh,status,fetch} (缺子命令)")
    return 1


def main():
    """测试入口"""
    import argparse

    parser = argparse.ArgumentParser(description='历史数据管理器')
    subparsers = parser.add_subparsers(dest='command', help='子命令')

    # fetch: 获取单只股票 (或指数, --index)
    p_fetch = subparsers.add_parser('fetch', help='获取单只股票或指数数据')
    p_fetch.add_argument('symbol', help='股票代码; --index 时为指数代码 (如 000300)')
    p_fetch.add_argument('--start', default='19960101', help='开始日期')
    p_fetch.add_argument('--end', default=None, help='结束日期')
    p_fetch.add_argument('--index', action='store_true',
                         help='按指数取数 (审计 M12: 前缀/接口/命名空间均按指数)')

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
    p_universe.add_argument('--as-of', dest='as_of', default=None,
                            help='point-in-time 截止日 (审计 H4: 缺省=缓存最新日)')

    # validate: 验证数据
    p_validate = subparsers.add_parser('validate', help='验证数据完整性')
    p_validate.add_argument('symbol', nargs='?', help='股票代码(不指定则验证全部)')

    # delisted: 退市股清单与历史行情 (审计 D1)
    p_del = subparsers.add_parser(
        'delisted', help='退市股清单与历史行情 (审计 D1: 幸存者偏差消除前提)')
    del_sub = p_del.add_subparsers(dest='delisted_cmd', help='子命令')
    del_sub.add_parser('refresh',
                       help='联网刷新退市清单 (上交所+深交所; 全成功才落盘)')
    del_sub.add_parser('status',
                       help='清单证据 + 缓存补齐覆盖统计')
    p_dfetch = del_sub.add_parser(
        'fetch', help='补齐清单内尚未缓存的 A股退市股行情')
    p_dfetch.add_argument('--start', default='19900101',
                          help='开始日期 (退市样本最早 1991 年)')
    p_dfetch.add_argument('--end', default=None, help='结束日期')
    p_dfetch.add_argument('--workers', type=int, default=4, help='并发数')
    p_dfetch.add_argument('--delay', type=float, default=0.3,
                          help='请求间隔(秒)')
    p_dfetch.add_argument('--include-b', action='store_true',
                          help='连B股一起取 (框架股票池不含B股, 默认跳过)')

    args = parser.parse_args()
    manager = HistoricalDataManager()

    if args.command == 'fetch':
        df = manager.fetch_and_cache(args.symbol, args.start, args.end,
                                     is_index=args.index)
        kind = "指数" if args.index else "股票"
        print(f"获取{kind} {args.symbol}: {len(df)} 条记录")
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
            # 从 stock_list.csv 加载 (stock_list_manager 单例, __file__ 基准
            # — 审计 M15: 旧实现 CWD 相对路径, 非仓库根运行即取不到)
            from stock_list_manager import get_stock_list
            df = get_stock_list().get_all_stocks()
            if len(df) > 0:
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
        meta = manager.get_universe_meta(min_history_days=args.min_days,
                                         as_of=args.as_of)
        universe = meta['universe']
        print(f"\n符合条件的股票: {len(universe)} 只 (参考日 {meta['as_of']})")
        if meta.get('survivorship_bias'):
            print(f"[WARN] {meta['survivorship_note']}")
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

    elif args.command == 'delisted':
        rc = _run_delisted_command(args, manager)
        if rc:
            raise SystemExit(rc)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
