# -*- coding: utf-8 -*-
"""源码卫生门禁: 模块 docstring 必须是第一条语句 + 无裸 except
   + 死 import / 解析后从不判断的 CLI flag / 类 docstring 参数计数

`from __future__ import annotations` 排到 docstring **之前**, docstring 会被
降级成一条无意义的表达式语句 (PEP 257), `__doc__` 变 `None` —— 看着只像加了
一行无害的 import, 实际悄悄丢了整个模块说明。

此类问题运行时无感 (import 照常成功), 只能靠源码级门禁拦。

裸 `except:` 会连 KeyboardInterrupt/SystemExit 一起吞, 静默失败 (审计 M14)。

死 import / 未读 CLI flag / docstring 计数漂移同样是运行时无感的诚实性问题
(审计 L6/L7/L8, 批次 1)。
"""
import ast
import re
from pathlib import Path

_SKILLS = Path(__file__).resolve().parent.parent / '.claude' / 'skills'
_REPO_ROOT = Path(__file__).resolve().parent.parent


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


class TestNoBareExcept:
    """裸 `except:` (AST ExceptHandler type=None) 会吞掉 KeyboardInterrupt /
    SystemExit, 让静默失败无法排查 (审计 M14, 批次 1)。"""

    def test_no_bare_except_in_skills(self):
        offenders = []
        for py, rel in _modules():
            tree = ast.parse(py.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler) and node.type is None:
                    offenders.append(f"{rel}:{node.lineno}")
        assert not offenders, (
            f"裸 except: 捕获范围包含 KeyboardInterrupt/SystemExit, "
            f"会把意外崩溃变成静默失败 —— 请显式写 except Exception "
            f"(或更具体的异常类型): {offenders}")


def _unused_imports(py: Path) -> list:
    """返回模块内顶层绑定后从未被 Name 引用的 import 名 (L6 死 import 探测)。"""
    tree = ast.parse(py.read_text(encoding='utf-8'))
    imported = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if (isinstance(node, ast.ImportFrom)
                    and node.module == '__future__'):
                continue
            for a in node.names:
                if a.name == '*':
                    continue
                imported.setdefault(a.asname or a.name.split('.')[0],
                                    node.lineno)
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    # 类型注解字符串/文档里引用的名字不算使用; 只认真实 Name 引用
    return [f"{name}(:{imported[name]})" for name in sorted(imported)
            if name not in used]


class TestWebAppImportHygiene:
    """web_app 顶层死 import (审计 L6, 批次 1): np/datetime/timedelta/
    ChartStyle/RealTimeMonitor 共 5 个 import 后从不使用。

    死 import 的害处不只美观: 暗示该依赖被实际使用 (误导维护者与依赖审计),
    且顶层 import 非核心包时会让模块在缺依赖环境直接 ImportError —— 而它
    根本没被用到。"""

    def test_web_app_has_no_unused_imports(self):
        unused = _unused_imports(_SKILLS / 'web_app.py')
        assert not unused, (
            f"web_app.py 存在 import 后从不使用的名称 (死 import): {unused} —— "
            f"删掉它; 若确实需要副作用 import, 请改用显式注册并在此豁免")

    def test_run_web_app_has_no_unused_imports(self):
        unused = _unused_imports(_REPO_ROOT / 'run_web_app.py')
        assert not unused, f"run_web_app.py 死 import: {unused}"


def _argparse_dests_and_reads(tree) -> tuple:
    """收集模块内 add_argument 声明的 dest 集合与 args.<attr> 读取集合。"""
    dests, addargs, reads = set(), 0, set()

    def dests_of(call: ast.Call) -> set:
        got, has_long = set(), False
        for a in call.args:
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                opt = a.value
                if opt.startswith('--'):
                    has_long = True
                    got.add(opt[2:].replace('-', '_'))
                elif opt.startswith('-') and len(opt) > 1:
                    got.add(opt[1:].replace('-', '_'))  # 无长选项时才生效
                else:  # 位置参数
                    got.add(opt.replace('-', '_'))
        kw = {k.arg: k.value for k in call.keywords if k.arg}
        if 'dest' in kw and isinstance(kw['dest'], ast.Constant):
            return {kw['dest'].value}
        if has_long:  # 有 --long 时丢弃短选项推导 (如 -f 不覆盖 --file)
            return {o[2:].replace('-', '_') for a in call.args
                    if isinstance(a, ast.Constant) and isinstance(a.value, str)
                    and (o := a.value).startswith('--')}
        return got

    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == 'add_argument'):
            addargs += 1
            dests |= dests_of(node)
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id == 'args'):
            reads.add(node.attr)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == 'getattr'
                and len(node.args) >= 2
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == 'args'
                and isinstance(node.args[1], ast.Constant)):
            reads.add(node.args[1].value)
    return dests, addargs, reads


class TestArgparseFlagsAreRead:
    """CLI flag 解析后必须被判断 (审计 L7, 批次 1)。

    run_web_app.py `--run` 解析了从不判断 (默认行为就是运行, flag 纯误导);
    reversal_detector.py `--top` 解析了从不判断 (限流是假的)。两者均已处置:
    前者删 flag, 后者接线到 analyze_stocks(top=)。此门禁防止再次溜进来。"""

    def test_every_parsed_dest_is_read(self):
        offenders = []
        targets = [(p, p.relative_to(_REPO_ROOT).as_posix())
                   for p in sorted(_SKILLS.rglob('*.py'))]
        targets.append((_REPO_ROOT / 'run_web_app.py', 'run_web_app.py'))
        for py, rel in targets:
            if not py.exists() or py.name == '__init__.py':
                continue
            tree = ast.parse(py.read_text(encoding='utf-8'))
            dests, addargs, reads = _argparse_dests_and_reads(tree)
            if not addargs:
                continue
            unread = dests - reads
            if unread:
                offenders.append(f"{rel}: {sorted(unread)}")
        assert not offenders, (
            f"add_argument 声明的 flag 解析后从未被读取 (用户传了也没用, "
            f"属于对用户的虚假承诺) —— 要么接线使用, 要么删掉 flag: {offenders}")


class TestParameterSpaceDocstringCounts:
    """ParameterSpace docstring 的参数计数必须与实际 ParamDef 一致 (审计 L8)。

    旧 docstring 三个数互不相等: 声明"共25个"、分项和 24 (12+4+4+4)、
    实际 26 (indicator 13 / scoring 4 / signal 4 / position 5)。
    计数漂移会让"参数空间有多少维"这类研究性问题答错, 只能源码级拦。"""

    _GROUP_KEYS = {'指标参数': 'indicator', '评分权重': 'scoring',
                   '信号阈值': 'signal', '仓位参数': 'position'}

    def _actual_counts(self) -> dict:
        tree = ast.parse((_SKILLS / 'parameter_space.py').read_text(encoding='utf-8'))
        counts, total = {}, 0
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)):
                continue
            v = node.value
            if not (isinstance(v, ast.Call) and isinstance(v.func, ast.Name)
                    and v.func.id == 'ParamDef'):
                continue
            gkw = [k for k in v.keywords if k.arg == 'group']
            g = gkw[0].value.value if gkw and isinstance(gkw[0].value, ast.Constant) else None
            counts[g] = counts.get(g, 0) + 1
            total += 1
        counts['__total__'] = total
        return counts

    def test_docstring_counts_match_actual_paramdefs(self):
        src = (_SKILLS / 'parameter_space.py').read_text(encoding='utf-8')
        tree = ast.parse(src)
        cls_doc = None
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == 'ParameterSpace':
                cls_doc = ast.get_docstring(node)
                break
        assert cls_doc, "ParameterSpace 类 docstring 缺失"

        m_total = re.search(r'共(\d+)个可优化参数', cls_doc)
        assert m_total, "docstring 缺少『共N个可优化参数』总计数"
        assert int(m_total.group(1)) >= 1

        actual = self._actual_counts()
        assert int(m_total.group(1)) == actual['__total__'], (
            f"docstring 总计数 {m_total.group(1)} ≠ 实际 ParamDef 数 "
            f"{actual['__total__']}")

        for label, group in self._GROUP_KEYS.items():
            m = re.search(re.escape(label) + r'\s*\((\d+)个\)', cls_doc)
            assert m, f"docstring 缺少『{label} (N个)』分项计数"
            assert int(m.group(1)) == actual.get(group, 0), (
                f"docstring {label} 计数 {m.group(1)} ≠ 实际 group="
                f"'{group}' 数 {actual.get(group, 0)}")

        assert sum(actual.get(g, 0) for g in self._GROUP_KEYS.values()) \
            == actual['__total__'], (
                f"存在未被 docstring 分项覆盖的 group: {actual}")
