# -*- coding: utf-8 -*-
"""共享测试夹具"""

import contextlib
import sys
import types

import pytest


class _SessionState:
    """同时支持 `in` 判断与属性访问 (与 streamlit.session_state 语义一致)。"""

    def __init__(self):
        object.__setattr__(self, '_d', {})

    def __contains__(self, key):
        return key in object.__getattribute__(self, '_d')

    def __getattr__(self, key):
        try:
            return object.__getattribute__(self, '_d')[key]
        except KeyError:
            raise AttributeError(key) from None

    def __setattr__(self, key, value):
        object.__getattribute__(self, '_d')[key] = value


def build_fake_streamlit():
    """streamlit 桩: 记录调用, 不做任何真实渲染。"""
    mod = types.ModuleType('streamlit')
    calls = []
    mod.calls = calls
    mod.error = lambda msg: calls.append(('error', msg))
    mod.code = lambda msg, language=None: calls.append(('code', msg))
    mod.caption = lambda msg: calls.append(('caption', msg))
    mod.info = lambda msg: calls.append(('info', msg))
    mod.warning = lambda msg: calls.append(('warning', msg))
    mod.markdown = lambda msg, **kw: calls.append(('markdown', msg))

    @contextlib.contextmanager
    def _spinner(msg=''):
        yield

    mod.spinner = _spinner
    mod.session_state = _SessionState()
    mod.stop = lambda: calls.append(('stop', None))
    return mod


@pytest.fixture
def web_app():
    """加载 web_app 模块 —— streamlit 缺失时用桩, 保证测试始终可跑。

    (web_app 顶层 import 已加守卫, 缺 streamlit 时模块仍可 import)
    """
    saved = sys.modules.get('streamlit')
    if saved is None:
        try:
            import streamlit  # noqa: F401
        except ImportError:
            sys.modules['streamlit'] = build_fake_streamlit()
    try:
        import web_app as _web_app
        return _web_app
    finally:
        if saved is None and 'streamlit' in sys.modules:
            mod = sys.modules['streamlit']
            if isinstance(mod, types.ModuleType) and hasattr(mod, 'calls'):
                sys.modules.pop('streamlit', None)


# ===========================================================================
# 日历隔离: 测试进程不得读/写开发者本地的 ./stock_data (CWD 相对默认路径)
# ===========================================================================
#
# `core.trading_calendar` 有两处按 **CWD 相对** 的默认路径取日历:
#   - `get_calendar()`  未注入进程级日历时回退读
#     `./stock_data/calendar/trading_days.json`
#   - `ensure_calendar()` 默认 `data_dir='./stock_data'` → 读本地指数行情并
#     **把算出的日历写回** `./stock_data/calendar/` (web_app 导入时即触发)
# 于是本地一旦存过指数行情 (例: `historical_data_manager.py fetch --index
# 000001` —— 正常用法), 整套"无日历"用例 (停牌阻断 / 数据过期 / 限价约束,
# 共 28 例) 全部翻转; 反之测试自己写出的日历 JSON 也会污染仓库目录
# (此前已发生过一次: 29 用例连环失败)。
#
# 处置: 测试期**只屏蔽隐式默认目录**的读写 (显式 path/data_dir 的调用照常
# 生效 → 本地缓存读写仍可用例覆盖, 一律传 tmp_path)。补丁在 conftest
# **导入期**生效 —— 因为 web_app 在 import 时就会调 `ensure_calendar()`,
# 等到 fixture 才补就晚了 (写盘已经发生)。

_DEFAULT_DATA_DIR = './stock_data'


def _isolate_local_calendar() -> None:
    """屏蔽测试期对 CWD 相对默认目录 `./stock_data` 的日历读写"""
    from core import trading_calendar as tc

    orig_from_local_cache = tc.TradingCalendar.from_local_cache
    orig_ensure_calendar = tc.ensure_calendar

    @classmethod
    def _from_local_cache(cls, path=None, data_dir=_DEFAULT_DATA_DIR):
        # 无参调用 = 隐式读 CWD 相对默认目录 → 测试期禁用
        if path is None and data_dir == _DEFAULT_DATA_DIR:
            return None
        return orig_from_local_cache.__func__(cls, path, data_dir)

    def _ensure_calendar(data_dir=_DEFAULT_DATA_DIR, refresh=False):
        # 默认目录 = 隐式读本地指数 + 写回本地日历 → 测试期禁用
        if data_dir == _DEFAULT_DATA_DIR:
            return None
        return orig_ensure_calendar(data_dir=data_dir, refresh=refresh)

    tc.TradingCalendar.from_local_cache = _from_local_cache
    tc.ensure_calendar = _ensure_calendar


_isolate_local_calendar()


@pytest.fixture(autouse=True)
def _reset_process_calendar():
    """每个用例前后清空进程级日历 → 用例之间不串味

    进程级日历是全局单例: 某个用例注入日历后若不清理, 后续"无日历"用例
    会被上一个用例的残留翻转 (与本地缓存无关的另一种串味)。
    """
    from core.trading_calendar import set_calendar

    set_calendar(None)
    yield
    set_calendar(None)
