# -*- coding: utf-8 -*-
"""源码卫生门禁: 模块 docstring 必须是第一条语句

`from __future__ import annotations` 排到 docstring **之前**, docstring 会被
降级成一条无意义的表达式语句 (PEP 257), `__doc__` 变 `None` —— 看着只像加了
一行无害的 import, 实际悄悄丢了整个模块说明。

此类问题运行时无感 (import 照常成功), 只能靠源码级门禁拦。
"""
import ast
from pathlib import Path

_SKILLS = Path(__file__).resolve().parent.parent / '.claude' / 'skills'


def _modules():
    for py in sorted(_SKILLS.rglob('*.py')):
        if py.name == '__init__.py':
            continue
        yield py, py.relative_to(_SKILLS).as_posix()


def _is_docstring(node) -> bool:
    return (isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str))


class TestModuleDocstringIntegrity:
    def test_future_import_must_not_precede_docstring(self):
        offenders = []
        for py, rel in _modules():
            body = ast.parse(py.read_text(encoding='utf-8')).body
            if not body:
                continue
            first = body[0]
            if not (isinstance(first, ast.ImportFrom)
                    and first.module == '__future__'):
                continue
            rest = body[1:]
            if rest and _is_docstring(rest[0]):
                offenders.append(rel)
        assert not offenders, (
            f"__future__ import 排在 docstring 之前 → docstring 失效 "
            f"(__doc__ = None): {offenders} —— 请把 __future__ 移到 docstring 之后")

    def test_every_module_keeps_its_docstring(self):
        """每个模块的 docstring 必须真的存在 (第一条语句就是字符串)。"""
        broken = []
        for py, rel in _modules():
            body = ast.parse(py.read_text(encoding='utf-8')).body
            if not body:
                broken.append(rel)
                continue
            first = body[0]
            if _is_docstring(first):
                continue
            if (isinstance(first, ast.ImportFrom) and first.module == '__future__'
                    and len(body) > 1 and _is_docstring(body[1])):
                broken.append(rel)
        assert not broken, f"模块 docstring 缺失或位置不对: {broken}"
