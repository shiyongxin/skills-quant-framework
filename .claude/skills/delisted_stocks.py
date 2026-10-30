# -*- coding: utf-8 -*-
"""退市股清单基建 —— 消除幸存者偏差的前提 (审计 D1)

H4 把幸存者偏差**显式标记**了出来 (`survivorship_bias=True`), 本模块是把
标记变成事实的前置条件: 退市股的"存在性"清单 + 缓存覆盖统计。行情本身
由 `sina_daily` 的 klc 直连兜底路径取 (见该模块, akshare 对退市股在股本
步骤确定性失败)。

## 数据源实测 (2026-10-30, 本机, akshare 1.18.64)

- **退市名录**: `ak.stock_info_sh_delist` (上交所, 记录 2001-04-25 起) +
  `ak.stock_info_sz_delist` (深交所, 记录 1999-07-12 起) → 去重 367 只
  (A股 337 + B股 30)。
  - 沪市字段是**暂停上市日期**、深市是**终止上市日期** (语义略异, 如实存
    `source_event` 列)。
  - **北交所无公开退市名录接口** → 北交所退市股不在清单内 (残余限制)。
- **退市股历史行情**: 新浪 klc 直连**可用** —— 6 样本 (2001/2017/2020/
  2024/2025/2026 退市, 沪深各 3) 全部有完整历史且含 `amount` 字段;
  `qfq`/`hfq` 复权因子端点同样全样本可用 (退市不缺复权因子)。
- **akshare `stock_zh_a_daily` (sh/sz) 对退市股不可用**: 主行情 klc 有数据,
  但随后调 `getAmountBySymbol` 补 outstanding_share —— 该接口对退市股返回
  `(null)` → demjson "No value to decode" (与北交所 bj 同根因)。
- 备选源实测: 腾讯 fqkline 有数据 (列口径不同); 东财 push2his 本机连接被
  重置; 网易 chddata 502。

## 清单缓存

`{data_dir}/delisted/delisted_list.csv` (data_dir 默认 `./stock_data`,
与行情缓存同级、同为**数据缓存不入库**) → 首次使用需 `delisted refresh`
联网刷新; 离线时降级为"清单不可用" 并**如实标记** (`available=False`),
不把"没查过"说成"没有偏差"。
"""

from pathlib import Path

import pandas as pd

# 清单里 A股范围外的前缀: 900xxx (沪B) / 200xxx (深B) —— 框架股票池
# (`stock_list.csv`) 本身不含 B股 (5522 行只有 0/3/6/92 前缀) → B股退市股
# 不进补齐范围, 否则"清单内全部已缓存"永远达不成。
_B_SHARE_PREFIXES = ('900', '200')

# 幸存者偏差 **False 声明**的证据新鲜度门槛: 清单超过该天数未刷新 →
# 期间可能已有新退市股未入清单 → 不足以支撑"偏差已消除" → 保守保持 True。
REGISTRY_MAX_AGE_DAYS = 90

_COLUMNS = ['code', 'name', 'list_date', 'delist_date', 'exchange',
            'source_event', 'in_scope', 'fetched_at']

_SH_RAW = dict(code='公司代码', name='公司简称', list_date='上市日期',
               delist_date='暂停上市日期', exchange='sh',
               source_event='暂停上市日期')
_SZ_RAW = dict(code='证券代码', name='证券简称', list_date='上市日期',
               delist_date='终止上市日期', exchange='sz',
               source_event='终止上市日期')


def default_registry_path(data_dir="./stock_data") -> Path:
    """清单默认路径 (与行情缓存同 data_dir; 运行时相对仓库根)"""
    return Path(data_dir) / "delisted" / "delisted_list.csv"


def fetch_delisted_list() -> pd.DataFrame:
    """联网拉取退市名录 (上交所 + 深交所), 归一化后的清单。

    两市**都拉成功才返回** —— 半份清单 (缺一市) 会让"清单内已全部补齐"
    的 False 声明建立在缺失数据上, 属静默有偏 → 任一失败即抛错,
    不落盘半份。

    Returns:
        pd.DataFrame: code/name/list_date/delist_date/exchange/
                      source_event/in_scope/fetched_at

    Raises:
        RuntimeError: 任一交易所名录拉取失败
    """
    import akshare as ak  # 函数内 import: 离线用法 (load/stats) 不拖 akshare

    frames = []
    errors = []
    for raw, fn in ((_SH_RAW, 'stock_info_sh_delist'),
                    (_SZ_RAW, 'stock_info_sz_delist')):
        try:
            df = getattr(ak, fn)()
        except Exception as e:  # noqa: BLE001 — 网络/接口错误如实汇总
            errors.append(f'{raw["exchange"]}: {type(e).__name__} '
                          f'{str(e)[:80]}')
            continue
        if df is None or len(df) == 0:
            errors.append(f'{raw["exchange"]}: {fn} 返回空表')
            continue
        part = pd.DataFrame({
            'code': df[raw['code']],
            'name': df[raw['name']],
            'list_date': df[raw['list_date']],
            'delist_date': df[raw['delist_date']],
            'exchange': raw['exchange'],
            'source_event': raw['source_event'],
        })
        frames.append(part)

    if errors:
        raise RuntimeError('退市名录拉取失败 (不落盘半份清单): '
                           + '; '.join(errors))
    return normalize_delisted_frame(pd.concat(frames, ignore_index=True))


def normalize_delisted_frame(df: pd.DataFrame) -> pd.DataFrame:
    """清单归一化: 6位码 / 日期列 / in_scope 标记 / fetched_at

    - 代码 `zfill(6)` + 去重 (按 code 保留首条)
    - `in_scope`: 是否在框架股票池范围内 (B股 900/200 → False)
    - 日期解析失败的行剔除 (退市日期缺失的记录无法支撑点时判定)
    """
    out = df.copy()
    out['code'] = out['code'].astype(str).str.strip().str.zfill(6)
    out['exchange'] = out['exchange'].astype(str).str.strip().str.lower()
    for col in ('list_date', 'delist_date'):
        out[col] = pd.to_datetime(out[col], errors='coerce')
    out = out.dropna(subset=['delist_date'])
    out['in_scope'] = ~out['code'].str.startswith(_B_SHARE_PREFIXES)
    out['fetched_at'] = pd.Timestamp.now().floor('s')
    out = out.drop_duplicates(subset=['code'], keep='first')
    return out[_COLUMNS].reset_index(drop=True)


def write_registry(df: pd.DataFrame, path) -> Path:
    """归一化并落盘清单 (utf-8-sig, 与 stock_list.csv 同编码惯例)"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = normalize_delisted_frame(df)
    normalized.to_csv(path, index=False, encoding='utf-8-sig')
    return path


class DelistedRegistry:
    """退市清单的读侧 (离线友好: 缺文件 = 不可用, 不抛错)"""

    def __init__(self, frame: pd.DataFrame, path, available: bool):
        self._frame = frame
        self.path = Path(path)
        self.available = bool(available)

    @classmethod
    def load(cls, path) -> "DelistedRegistry":
        """读清单 CSV; 文件不存在/读不出 → available=False 的空清单

        离线降级语义: `available=False` 表示"没查过", 调用方**不得**把它
        当成"没有退市股" → 幸存者偏差标记必须保持保守 (True)。
        """
        path = Path(path)
        if not path.is_file():
            return cls(pd.DataFrame(columns=_COLUMNS), path, False)
        try:
            df = pd.read_csv(path, encoding='utf-8-sig',
                             dtype={'code': str})
        except Exception:  # noqa: BLE001 — 损坏文件 = 不可用, 如实降级
            return cls(pd.DataFrame(columns=_COLUMNS), path, False)
        if 'code' not in df.columns:
            return cls(pd.DataFrame(columns=_COLUMNS), path, False)
        # 已归一化落盘 → 直接用 (不再重算 fetched_at, 否则"新鲜度"每次读取
        # 都被刷新 = 永远新鲜 → 证据新鲜度门槛失效)
        df['code'] = df['code'].astype(str).str.zfill(6)
        if 'in_scope' not in df.columns:
            df['in_scope'] = ~df['code'].str.startswith(_B_SHARE_PREFIXES)
        return cls(df.reset_index(drop=True), path, True)

    def refresh(self, fetcher=None) -> pd.DataFrame:
        """联网刷新清单 (fetcher 可注入以便测试); 全成功才落盘"""
        df = (fetcher or fetch_delisted_list)()
        write_registry(df, self.path)
        fresh = DelistedRegistry.load(self.path)
        self._frame = fresh._frame
        self.available = fresh.available
        return self._frame

    # ------------------------------------------------------------------
    def codes(self, in_scope=None) -> list:
        """清单代码 (in_scope=None 全量 / True 仅A股范围 / False 仅B股)"""
        if not self.available:
            return []
        df = self._frame
        if in_scope is True:
            df = df[df['in_scope']]
        elif in_scope is False:
            df = df[~df['in_scope']]
        return df['code'].tolist()

    def is_delisted(self, code) -> bool:
        """该代码是否在清单内 (清单不可用 → False + 调用方须另查 available)"""
        if not self.available:
            return False
        return str(code).zfill(6) in set(self._frame['code'])

    def stats(self) -> dict:
        """清单证据统计 (供幸存者偏差标记与 status 命令消费)"""
        base = {
            'available': self.available,
            'path': str(self.path),
            'fetched_at': None,
            'age_days': None,
            'fresh': False,
            'n': 0,
            'n_in_scope': 0,
            'n_out_of_scope': 0,
            'exchanges': {},
            'coverage_start': None,       # 各交易所最早退市记录 (见下)
            'coverage_start_by_exchange': {},
            'coverage_end': None,
        }
        if not self.available or len(self._frame) == 0:
            return base
        df = self._frame
        fetched = None
        if 'fetched_at' in df.columns and len(df):
            try:
                fetched = pd.Timestamp(df['fetched_at'].iloc[0])
            except (TypeError, ValueError):
                fetched = None
        age = None
        if fetched is not None:
            age = max(0, int((pd.Timestamp.now().floor('d')
                              - fetched).days))
        by_ex = {}
        for ex, grp in df.groupby('exchange')['delist_date']:
            ts = pd.to_datetime(grp, errors='coerce').dropna()
            if len(ts):
                by_ex[str(ex)] = str(ts.min().date())
        # 覆盖起点 = **各交易所最早记录的最晚者**: 两市名录上线时间不同
        # (沪 2001-04 / 深 1999-07), 取 max 才能保证"此前的退市记录两市
        # 都已知" —— 取 min 会对另一市的空白期误发 False 声明。
        coverage_start = max(by_ex.values()) if by_ex else None
        in_scope = df[df['in_scope']] if 'in_scope' in df.columns else df
        delist_range = pd.to_datetime(in_scope['delist_date'],
                                      errors='coerce').dropna()
        return {
            **base,
            'fetched_at': str(fetched) if fetched is not None else None,
            'age_days': age,
            'fresh': age is not None and age <= REGISTRY_MAX_AGE_DAYS,
            'n': int(len(df)),
            'n_in_scope': int(len(in_scope)),
            'n_out_of_scope': int(len(df) - len(in_scope)),
            'exchanges': df['exchange'].value_counts().to_dict(),
            'coverage_start': coverage_start,
            'coverage_start_by_exchange': by_ex,
            'coverage_end': (str(delist_range.max().date())
                             if len(delist_range) else None),
        }
