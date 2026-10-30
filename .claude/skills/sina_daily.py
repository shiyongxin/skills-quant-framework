# -*- coding: utf-8 -*-
"""新浪日线取数共享层 — 前缀规则单一真相源 + 北交所 bj 直连 (审计 M18)

收敛两处分裂:

1. **前缀规则**: `format_symbol` 收敛 5 个模块各自内联的 sh/sz 映射
   (`stock_data_fetcher` / `historical_data_manager` / `long_term_selector` /
   `reversal_backtest` / `reversal_detector`)。旧映射全部缺北交所分支:
   4/8/92 开头的裸码要么原样裸发、要么被错拼成 `sz920002`, 新浪一律 404,
   异常又被上层 try/except 吞掉 —— 北交所股票历史行情静默取不到。
   (本仓库股票池 stock_list.csv 中北交所代码为 920xxx 新码段, 共 315 只;
   4/8 为审计记录的旧码段, 一并覆盖。)

2. **klc 直连路径** (`_fetch_klc_direct`, bj + 退市 sh/sz 回退):
   `ak.stock_zh_a_daily` 对两类代码**不可用** —— 主行情 `hisdata_klc2` 有
   数据, 但 akshare 紧接着调 `getAmountBySymbol` 补 outstanding_share, 该
   接口返回 `(null)`, demjson 解码处抛 JSONDecodeError (akshare 1.18.64):
   - **bj** (实测 bj430047/bj836247): 补充接口本就不支持北交所;
   - **退市 sh/sz** (实测 sz000004/sh600625 等 6 样本, 2026-10-30): 补充
     接口对退市股同样返回 `(null)` —— 同一根因。而 klc 主行情对退市股有
     **完整历史含 amount**, qfq/hfq 因子端点亦可用 (见 delisted_stocks)。

   备选源实测: 腾讯 fqkline 对 bj 返回 `day:[]`; 东财 push2his 对本机连接
   被重置; 网易 chddata 502 → 当前可用的只有新浪 klc 直连, 故单独解码,
   输出列与 `ak.stock_zh_a_daily` 对齐 (outstanding_share/turnover 置
   NaN: 股本补充接口对这些代码不可用, 不拿 0 冒充)。

sh/sz 在市代码: 先走 `ak.stock_zh_a_daily` (行为与改动前一致), **仅当其
因股本步骤确定性崩溃** (demjson 解 `(null)`, 见 `_is_amount_step_failure`)
时回退 klc 直连 —— 退市股由回退路径透明救回 (审计 D1); 网络类等其他错误
原样上抛不回退 (回退不得掩盖根因), 在市代码正常情况下零改动。
"""

import json
import re

import akshare as ak
import pandas as pd

from js_runtime import decode_klc_payload

# 新浪日线 (KLC 加密) 与复权因子端点 —— 与 akshare stock/cons.py 同源
_KLC_URL = "https://finance.sina.com.cn/realstock/company/{}/hisdata_klc2/klc_kl.js"
_QFQ_URL = "https://finance.sina.com.cn/realstock/company/{}/qfq.js"
_HFQ_URL = "https://finance.sina.com.cn/realstock/company/{}/hfq.js"

_OUT_COLS = ["date", "open", "high", "low", "close", "volume", "amount",
             "outstanding_share", "turnover"]


def format_symbol(symbol) -> str:
    """6 位裸码 → sh/sz/bj 前缀 (新浪接口要求); 已带前缀/非纯数字原样返回

    规则 (审计 M18, 5 个模块唯一真相源):
    - 6 开头 → sh (沪市主板/科创板)
    - 0/3 开头 → sz (深市主板/创业板)
    - 4/8/92 开头 → bj (北交所; 920xxx 为现行码段, 43xxxx/83xxxx 为旧码段)
    - 其余 (如 900xxx B股) → 原样返回, 不猜前缀 (诚实失败)
    """
    s = str(symbol)
    if s.isdigit():
        s = s.zfill(6)
        if s.startswith("6"):
            return f"sh{s}"
        if s[0] in ("0", "3"):
            return f"sz{s}"
        if s.startswith("92") or s[0] in ("4", "8"):
            return f"bj{s}"
        return s
    return str(symbol)


def fetch_daily(symbol: str, start_date, end_date, adjust: str = "") -> pd.DataFrame:
    """取日线 (`symbol` 须已带 sh/sz/bj 前缀)

    输出列与 `ak.stock_zh_a_daily` 对齐:
    date, open, high, low, close, volume, amount, outstanding_share, turnover

    路由 (审计 D1):

    - bj: 新浪 klc 直连 (见模块 docstring; akshare 对 bj 在股本步骤崩溃)
    - sh/sz: 先走 `ak.stock_zh_a_daily` (在市代码行为与改动前一致),
      **仅当其因股本步骤确定性崩溃时**回退 klc 直连 (`_is_amount_step_
      failure`: demjson 解 `getAmountBySymbol` 对退市股/bj 返回的
      `(null)` → "No value to decode"; 与 bj 同根因) —— 这是已知的结构性
      失败, 换直连即可取到数据 (klc 主行情对退市股有完整历史)。
      **其余错误 (网络/参数等) 原样上抛, 不回退** —— 否则回退会把根因
      掩盖成"直连也失败"的合并错误, 调用方拿不到真实原因。
      回退路径的 outstanding_share/turnover 为 NaN (股本接口本就不可用),
      amount 仍来自 klc, 不拿 0 冒充。
    """
    if str(symbol).startswith("bj"):
        return _fetch_klc_direct(symbol, start_date, end_date, adjust)
    try:
        return ak.stock_zh_a_daily(symbol=symbol, start_date=start_date,
                                   end_date=end_date, adjust=adjust)
    except Exception as ak_err:
        if not _is_amount_step_failure(ak_err):
            raise   # 非股本步骤的确定性崩溃 → 根因原样上抛 (不掩盖)
        try:
            df = _fetch_klc_direct(symbol, start_date, end_date, adjust)
        except Exception as direct_err:
            raise RuntimeError(
                f'{symbol} 日线取数失败: akshare 股本步骤崩溃后 klc 直连也'
                f'失败: {type(direct_err).__name__}: {direct_err}'
            ) from ak_err
        print(f"[INFO] {symbol} akshare 股本步骤崩溃 → 已回退新浪 klc 直连 "
              f"(demjson: {str(ak_err)[:50]})")
        return df


def _is_amount_step_failure(err: BaseException) -> bool:
    """akshare 是否死于**股本步骤**的确定性崩溃 (demjson 解 `(null)`)

    `ak.stock_zh_a_daily` 主行情 (klc) 拿到数据后, 紧接着调
    `getAmountBySymbol` 补 outstanding_share —— 该接口对 **bj** 与
    **退市 sh/sz** 返回 `(null)`, vendored demjson 解空串抛
    `JSONDecodeError: No value to decode` (模块 akshare.utils.demjson,
    实测 bj430047 / sz000004 / sh600625)。这是结构性失败 (换直连即解),
    与网络类瞬时错误必须区分开 (后者不得回退, 见 fetch_daily docstring)。
    """
    t = type(err)
    return (t.__name__ == 'JSONDecodeError'
            and 'demjson' in getattr(t, '__module__', ''))


# ===========================================================================
# klc 直连路径 (bj + 退市 sh/sz 回退)
# ===========================================================================

def _fetch_klc_direct(symbol: str, start_date, end_date, adjust: str = "") -> pd.DataFrame:
    """新浪 klc 直连日线 (解密 klc 数据)

    适用: bj 代码 (akshare 不支持) + 退市 sh/sz (akshare 在股本步骤崩溃)。
    根因与实测见模块 docstring。历史名 `_fetch_bj_daily` (审计 D1 后
    扩展用途, 2026-10-30 改名)。
    """
    text = _http_get(_KLC_URL.format(symbol))
    payload = _extract_js_payload(text)
    rows = _decode_klc(payload)
    if not rows:
        raise ValueError(f"新浪 klc 无 {symbol} 数据")

    df = pd.DataFrame(rows)
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"新浪 klc 响应缺列: {sorted(missing)}")
    if "amount" not in df.columns:
        # klc 正常响应含 amount (实测 bj430047); 缺失时置 NaN 如实标记,
        # 不拿 0 冒充成交额 (下游 ADV/流动性检查会按无数据跳过)
        print(f"[WARN] {symbol} klc 响应无 amount, 成交额置 NaN")
        df["amount"] = float("nan")

    # 统一为 tz-naive 时间戳 (klc 日期形如 2010-04-22T00:00:00.000Z)
    df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=True)
    df["date"] = df["date"].dt.tz_localize(None)
    df = df.dropna(subset=["date"]).sort_values("date")

    tag = (adjust or "").strip()
    if tag in ("", "none", "raw", "bfq"):
        df = _filter_window(df, start_date, end_date)
        df = df.drop_duplicates(
            subset=["open", "high", "low", "close", "volume", "amount"])
        for col in ("open", "high", "low", "close"):
            df[col] = df[col].round(2)
        df = df.dropna(subset=["date", "open", "high", "low", "close", "volume"])
    elif tag in ("qfq", "hfq"):
        factor = _fetch_sina_factor(symbol, tag)
        df = _apply_sina_factor(df, factor, tag)
        df = _filter_window(df, start_date, end_date)
    else:
        raise ValueError(f"未知复权口径: {adjust!r} (支持 ''/qfq/hfq)")

    # 列序与 ak.stock_zh_a_daily 对齐; outstanding_share/turnover 对 bj
    # 无数据 → NaN (补充接口不返回 bj, 不拿 0 冒充)
    df = df.copy()
    df["outstanding_share"] = float("nan")
    df["turnover"] = float("nan")
    df = df[_OUT_COLS]
    # akshare 输出的 date 为 python date 对象 (口径对齐)
    df["date"] = df["date"].dt.date
    return df.reset_index(drop=True)


def _fetch_sina_factor(symbol: str, tag: str) -> pd.DataFrame:
    """拉取新浪复权因子 (qfq/hfq), 返回以 date 为索引的单列 DataFrame"""
    url = _QFQ_URL if tag == "qfq" else _HFQ_URL
    text = _http_get(url.format(symbol))
    payload = _extract_json(text)
    data = payload.get("data") or []
    if not data:
        raise ValueError(f"新浪无 {symbol} 的 {tag} 因子")
    factor = pd.DataFrame(data)
    if not {"d", "f"} <= set(factor.columns):
        raise ValueError(f"新浪 {tag} 因子响应缺列: {list(factor.columns)}")
    factor["date"] = pd.to_datetime(factor["d"], errors="coerce", utc=True)
    factor["date"] = factor["date"].dt.tz_localize(None)
    factor[f"{tag}_factor"] = pd.to_numeric(factor["f"], errors="coerce")
    factor = factor.dropna(subset=["date", f"{tag}_factor"])
    return factor.set_index("date")[[f"{tag}_factor"]]


def _apply_sina_factor(df: pd.DataFrame, factor: pd.DataFrame,
                       tag: str) -> pd.DataFrame:
    """复权因子应用 (与 akshare stock_zh_a_daily 同口径)

    qfq: 价格 / 因子; hfq: 价格 * 因子 (akshare 的除/乘方向逐字对齐)。

    与 akshare 的一处有意差异: outer 合并在因子事件日 (及因子表首行) 会引入
    **无行情的假行**, ffill 会把上一日价格带进去 —— akshare 保留这些假行,
    这里按 ffill 前的"无价掩码"剔除, 只留真实有行情的交易日。
    """
    col = f"{tag}_factor"
    merged = pd.merge(df.set_index("date"), factor,
                      left_index=True, right_index=True, how="outer")
    merged = merged.sort_index()
    no_price = merged["close"].isna()  # 因子事件日/因子表首行引入的无价行
    merged.ffill(inplace=True)
    merged = merged[~no_price]
    merged = merged.astype(float)
    merged.dropna(inplace=True)
    merged.drop_duplicates(
        subset=["open", "high", "low", "close", "volume", "amount"], inplace=True)
    if tag == "qfq":
        for c in ("open", "high", "low", "close"):
            merged[c] = merged[c] / merged[col]
    else:
        for c in ("open", "high", "low", "close"):
            merged[c] = merged[c] * merged[col]
    merged = merged.drop(columns=[col])
    for c in ("open", "high", "low", "close"):
        merged[c] = merged[c].round(2)
    merged = merged.dropna()
    return merged.reset_index()


def _filter_window(df: pd.DataFrame, start_date, end_date) -> pd.DataFrame:
    """按 [start_date, end_date] 过滤 (含端点)"""
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    out = df[(df["date"] >= start) & (df["date"] <= end)]
    return out.reset_index(drop=True)


def _http_get(url: str) -> str:
    # 函数内 import: requests 仅 bj 路径需要 (akshare 硬依赖必然已装);
    # 顶层 import 会在缺失时把 sh/sz 透传路径一起拖下水
    import requests
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return resp.text


def _decode_klc(payload: str) -> list:
    """解密新浪 KLC 日线载荷 (py_mini_racer 执行 akshare 内置解码 JS)

    依赖 py_mini_racer 与 akshare.stock.cons.hk_js_decode —— 二者均由
    akshare 传递安装; 缺失时此处抛 ImportError, 由调用方的异常路径如实上报。

    解密交给 `js_runtime.decode_klc_payload`: V8 非线程安全, 批量取数并发
    时会**崩进程** (V8 CHECK 断言 SIGTRAP, 非 Python 异常, try/except
    拦不住) —— 闸门在 js_runtime 收口, 见该模块 docstring。
    """
    return decode_klc_payload(payload)


def _extract_js_payload(text: str) -> str:
    """提取 `var XXX="PAYLOAD";` 中的载荷 (载荷可含 '=', 不能用 split('='))"""
    m = re.search(r'="([^"]*)"', text)
    if not m:
        raise ValueError("新浪 klc 响应缺少数据载荷")
    return m.group(1)


def _extract_json(text: str) -> dict:
    """提取响应中的第一个 JSON 对象 (忽略尾部注释)"""
    start = text.find("{")
    if start < 0:
        raise ValueError("新浪复权因子响应缺少 JSON")
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    return obj
