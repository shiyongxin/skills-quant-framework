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
