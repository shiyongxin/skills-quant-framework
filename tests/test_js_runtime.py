# -*- coding: utf-8 -*-
"""V8 闸门门禁 —— py_mini_racer 非线程安全, 并发用即崩进程 (批量取数崩溃)

**崩溃现象**: `historical_data_manager.py batch` 跑到一半

    [FATAL:address_pool_manager.cc(67)] Check failed: !pool->IsInitialized().
    zsh: trace trap

V8 的 CHECK 断言 SIGTRAP 打死进程 —— **不是 Python 异常**, 线程池的
`future.result()` / `try/except` 全都拦不住 → 整批取数当场全丢。

**根因**: akshare 的 `stock_zh_a_daily` / `stock_zh_index_daily` 与本仓
`sina_daily._decode_klc` 都用 `py_mini_racer` 解密新浪 KLC 载荷; V8 的
isolate 不是线程安全的, 两个线程同时进 V8 → 地址池重复初始化 → abort。

**门禁作用**: `js_runtime` 把所有 V8 操作串行化到一把 RLock 上。本文件
锁住三件事:
  1. 闸门确实装上了 (akshare 内部自建 MiniRacer, 只能从这里收口)
  2. 代理**不改变语义** (仍是独立 context, 不共享 JS 全局变量 —— 共享
     会让不同库的同名函数互相顶掉 → 静默解密出错)
  3. 并发跑 V8 **不再崩进程** (未打闸门时这个用例会把 pytest 进程一起
     打死, 因此它同时是崩溃的回归证明)

无法在本文件里"先崩一次再证明修好了": 崩溃是 SIGTRAP, 会带走整个测试
进程 —— 故这里只验证"闸门在 + 语义未变 + 并发不崩"。
"""

import threading

import pytest

import js_runtime


class TestGateInstalled:
    """闸门必须在任何 JS 调用前装好 (akshare 内部自建 MiniRacer, 无调用点可改)"""

    def test_mini_racer_is_replaced_by_proxy(self):
        py_mini_racer = pytest.importorskip("py_mini_racer")
        assert py_mini_racer.MiniRacer is js_runtime._SerialMiniRacer, (
            "py_mini_racer.MiniRacer 未被代理类替换 → 并发取数会崩进程 "
            "(V8 CHECK 断言 SIGTRAP, 拦不住)")

    def test_install_is_idempotent(self):
        """重复安装不得套娃 (否则锁会被套 N 层, 或代理套代理)"""
        py_mini_racer = pytest.importorskip("py_mini_racer")
        before = py_mini_racer.MiniRacer
        assert js_runtime.install_js_serialization() is True
        assert py_mini_racer.MiniRacer is before

    def test_sina_daily_import_installs_gate(self):
        """取数主链路 import sina_daily 即应带上闸门 (不靠"记得调用安装")"""
        pytest.importorskip("py_mini_racer")
        import sina_daily  # noqa: F401  (副作用: 链路上的闸门)
        import py_mini_racer
        assert py_mini_racer.MiniRacer is js_runtime._SerialMiniRacer


class TestProxySemantics:
    """代理必须与原类行为一致 (否则修崩溃修出数据错误)"""

    def test_eval_and_call_work(self):
        pytest.importorskip("py_mini_racer")
        js = js_runtime._SerialMiniRacer()
        js.eval("function twice(x) { return x * 2; }")
        assert js.call("twice", 21) == 42

    def test_each_context_is_isolated(self):
        """每次仍是独立 context —— 共享会把不同调用方的同名函数顶掉"""
        pytest.importorskip("py_mini_racer")
        a = js_runtime._SerialMiniRacer()
        a.eval("var marker = 'a'; function pick() { return marker; }")
        b = js_runtime._SerialMiniRacer()
        b.eval("var marker = 'b'; function pick() { return marker; }")
        assert a.call("pick") == "a"
        assert b.call("pick") == "b"

    def test_real_class_is_preserved(self):
        """代理必须仍指向真实 MiniRacer 类 (不能自我替换成代理的代理)"""
        pytest.importorskip("py_mini_racer")
        import py_mini_racer
        assert js_runtime._REAL_CLASS is not js_runtime._SerialMiniRacer
        assert issubclass(js_runtime._SerialMiniRacer, object)
        assert py_mini_racer.MiniRacer is js_runtime._SerialMiniRacer


class TestConcurrencySafety:
    """并发跑 V8 不再崩进程 (回归门禁: 未打闸门时本用例会 SIGTRAP 打死 pytest)"""

    def test_concurrent_mini_racer_does_not_crash(self):
        pytest.importorskip("py_mini_racer")
        workers, rounds = 4, 8
        errors = []
        seen = []
        lock = threading.Lock()

        def work(tid):
            for r in range(rounds):
                try:
                    js = js_runtime._SerialMiniRacer()
                    js.eval("function f(x) { return x + 1; }")
                    out = js.call("f", tid * 100 + r)
                    with lock:
                        seen.append(out)
                except Exception as exc:  # noqa: BLE001  (汇总到主线程断言)
                    with lock:
                        errors.append(repr(exc))

        threads = [threading.Thread(target=work, args=(i,))
                   for i in range(workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"并发 V8 报错: {errors[:3]}"
        assert len(seen) == workers * rounds
        # 每个线程每次的返回值必须等于它自己的入参 +1 (无串味)
        assert sorted(seen) == sorted(
            t * 100 + r + 1 for t in range(workers) for r in range(rounds))

    def test_js_guard_serializes_blocks(self):
        """js_guard 段内互斥 (闸门未生效时的深度防御)"""
        counter = {"n": 0, "max": 0}
        lock = threading.Lock()
        inner = threading.Lock()

        def work():
            with js_runtime.js_guard():
                with inner:
                    counter["n"] += 1
                    counter["max"] = max(counter["max"], counter["n"])
                # 让出 GIL, 让别的线程有机会闯入
                threading.Event().wait(0.01)
                with inner:
                    counter["n"] -= 1

        threads = [threading.Thread(target=work) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert counter["max"] == 1, "js_guard 未串行化 (闸门失效)"


@pytest.mark.data
class TestKlcDecode:
    """真实载荷解密 (需联网; 失败即跳过 —— 不是门禁, 只是冒烟)"""

    def test_decode_klc_payload(self):
        pytest.importorskip("py_mini_racer")
        import re
        import requests
        try:
            resp = requests.get(
                "https://finance.sina.com.cn/realstock/company/sh600000/"
                "hisdata_klc2/klc_kl.js", timeout=15)
            m = re.search(r'="([^"]*)"', resp.text)
        except Exception as exc:  # noqa: BLE001  (网络不可用 → 跳过)
            pytest.skip(f"新浪接口不可达: {exc}")
        if not m:
            pytest.skip("新浪响应格式异常, 跳过")
        out = js_runtime.decode_klc_payload(m.group(1))
        assert isinstance(out, list) and out, "解密结果为空"
        assert "date" in out[0] and "close" in out[0]
