# -*- coding: utf-8 -*-
"""JS 运行时闸门 —— py_mini_racer (V8) 非线程安全, 并发用即崩进程

**现象**: `historical_data_manager.py batch` 批量取数跑到一半直接

    [FATAL:address_pool_manager.cc(67)] Check failed: !pool->IsInitialized().
    zsh: trace trap

进程被 V8 的 CHECK 断言 SIGTRAP 打死 —— **不是 Python 异常**: 线程池的
`future.result()`、`try/except` 一律拦不住, 整批取数当场全丢。

**根因**: 新浪日线/指数的 KLC 载荷是 JS 加密的, 解密必须跑 V8:
  - akshare `stock_zh_a_daily` (sh/sz 个股, 本仓主路径) → `py_mini_racer`
  - akshare `stock_zh_index_daily` (指数)                → `py_mini_racer`
  - 本仓 `sina_daily._decode_klc` (北交所直连)           → `py_mini_racer`
V8 的 isolate **不是线程安全**的: 两个线程同时创建/执行 isolate → 地址池
重复初始化 → CHECK 失败 → abort。批量取数默认 4 线程并发, 必然撞上
(实测: 4 线程并发 MiniRacer 5/5 必崩; 单线程连做 20 次不崩)。

**处置**: 进程级**闸门** —— 所有 V8 操作 (建 isolate / eval / call / 释放
isolate) 串行化到一把 `RLock` 上; 网络 I/O 仍在各线程并行 (JS 解密约占
每只股票 ~10ms, 网络 ~1s) → 并发收益基本不损失。

**为什么全局打补丁**: akshare 在包内自建 `py_mini_racer.MiniRacer()`,
调用点散落在 stock/index/fund/bond/movie/air/... 各处, 逐个改不可能;
能收口的只有 `py_mini_racer.MiniRacer` 这个类本身 → 用代理类替换它:
语义不变 (每次仍是**独立** context, 不共享 JS 状态 —— 共享会把不同库
各自的同名函数互相顶掉), 只是把每个 V8 操作包进锁。

缺 py_mini_racer 时本模块降级为"什么都不做" (导入不炸), 由真正需要
JS 的调用方按缺失依赖如实报错。
"""

import threading
from contextlib import contextmanager
from functools import wraps

# V8 全局闸门 (RLock: 代理类内部与 js_guard() 双重加锁时同线程可重入)
JS_LOCK = threading.RLock()

# 真实的 MiniRacer 类 (安装闸门时捕获) —— 未安装时为 None
_REAL_CLASS = None

# 闸门是否已安装 (幂等标记)
_installed = False


class _SerialMiniRacer:
    """`py_mini_racer.MiniRacer` 的线程安全代理 (V8 闸门)

    行为与原类一致, 只多两件事:
      - 建 isolate / eval / call / 释放 isolate 全部持 `JS_LOCK` → 任一
        时刻只有一个线程在 V8 内部 (崩溃根因即"两个线程同时在 V8 里")
      - 每次仍是**独立** context → 不同调用方的 JS 全局变量互不可见
        (共享 context 会让 A 库的 `d()` 被 B 库的同名函数顶掉 → 静默
        解密出错)

    Attributes:
        _ctx: 真实的 MiniRacer 实例 (代理只持有一个引用)
    """

    def __init__(self, *args, **kwargs):
        with JS_LOCK:
            self._ctx = _REAL_CLASS(*args, **kwargs)

    def __getattr__(self, name):
        # 只在常规查找失败时触发; `_ctx` 未就绪时必须直接报错, 否则递归
        if name.startswith("_"):
            raise AttributeError(name)
        attr = getattr(self._ctx, name)
        if not callable(attr):
            return attr

        @wraps(attr)
        def _guarded(*args, **kwargs):
            with JS_LOCK:
                return attr(*args, **kwargs)

        return _guarded

    def __del__(self):
        # 释放 isolate 同样要与其它线程的 V8 操作互斥 (析构也是 V8 活动)
        ctx = self.__dict__.get("_ctx")
        if ctx is None:
            return
        try:
            with JS_LOCK:
                self.__dict__["_ctx"] = None
        except Exception:
            # 解释器退出期等极端场景: 锁不可用就直接放手, 绝不因析构抛错
            self.__dict__["_ctx"] = None


def install_js_serialization() -> bool:
    """把 `py_mini_racer.MiniRacer` 换成串行化代理 (幂等)

    Returns:
        bool: True = 闸门已生效 (含此前已安装); False = py_mini_racer 缺失
            (降级: 不装闸门, 由调用方按缺失依赖如实报错)
    """
    global _REAL_CLASS, _installed
    if _installed:
        return True
    try:
        import py_mini_racer
    except ImportError:
        return False
    current = getattr(py_mini_racer, "MiniRacer", None)
    if current is _SerialMiniRacer:
        _installed = True
        return True
    _REAL_CLASS = current
    py_mini_racer.MiniRacer = _SerialMiniRacer
    _installed = True
    return True


@contextmanager
def js_guard():
    """把一整段可能触碰 V8 的调用串行化 (深度防御)

    闸门(代理类)已把每个 V8 操作单独加锁, 本守卫用于**调用方自己**
    持有 V8 的场景 (如 akshare 内部自建 context 的函数): 即使闸门没装上
    (py_mini_racer 缺失/被换实现), 整段调用仍然互斥 → 不会并发进 V8。

    注意: 网络 I/O 也在锁内 —— 只用在"网络占比小"或"必须整体互斥"的
    路径上 (指数取数), 不要用在批量个股取数的主路径 (会把并发抹平)。
    """
    with JS_LOCK:
        yield


def decode_klc_payload(payload: str):
    """用 V8 解密新浪 KLC 载荷 (闸门内)

    Args:
        payload: 新浪 klc 响应里的密文载荷

    Returns:
        list: 解密后的记录列表 (字段与 `ak.stock_zh_a_daily` 一致)
    """
    from py_mini_racer import MiniRacer
    from akshare.stock.cons import hk_js_decode

    with JS_LOCK:
        js = MiniRacer()
        js.eval(hk_js_decode)
        return js.call("d", payload)


# 导入即装闸门: 任何触达 JS 的路径 (取数/指数/回测) 只要 import 本模块,
# 就自动获得串行化保护 —— 不依赖"记得在某处调用 install"
install_js_serialization()
