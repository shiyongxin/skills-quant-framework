# -*- coding: utf-8 -*-
"""工程基座门禁 (审计 L3 / L1 / L2 / L5 / L9 / L10 / L11, 批次 4.2)

复验结论 (2026-10-29): 批次 4.2 的 8 条里 **2 条已过时** (L4/L5 的旧证据),
**6 条属实**, 且其中两条的严重性被审计低估:

- **L1** (不是"网格与规范不一致", 而是**两套参数空间并存**):
  `strategy_optimizer` 的 5 处手写网格是**优化器实际在用**的 (属性式调用
  `self.strategy.get_param_grid()`), 参数名 (`short_period` vs `ma_fast`) 与
  范围都漂移, `sell_threshold` **符号相反** (手写负值 = 强度刻度; 规范正值
  = 分值刻度) → 同名不同义, 跨系统拷贝参数会得到反向行为。
- **L5** (不是"仓库根目录的 test_tool.py", 而是 `.claude/skills/test_tool.py`):
  模块级打网络 / 建 `./test_data/` / `exit(1)`, 且文件名匹配 pytest 的
  `python_files = test_*.py` → 被收集时副作用发生在**导入期**。

门禁:
- L3: `pyproject.toml` 存在且**模块清单与磁盘一致**; CI 工作流存在且跑离线套件
- L1: 策略网格必须**派生自 `ParameterSpace`** (参数名/范围不得手写);
      `sell_threshold` 符号必须与规范一致 (正)
- L2: 不得再出现**他人机器的绝对路径**
- L5: skills 目录下不得再有"import 即执行"且匹配 `test_*.py` 的脚本
- L9: `OptimizationConfig` 类名全仓**只允许一处**定义 (同名遮蔽)
- L10: VWAP 的 docstring 不得再写"当日/单日" (实现是累积口径)
- L11: 体制表示统一为**字符串** (枚举实例 ≠ 字符串 → 跨系统比较必错)
"""
import ast
import re
import tomllib
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SKILLS = _REPO / '.claude' / 'skills'
_WEB = _REPO / '.claude' / 'skills' / 'web_app.py'


def _read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def _code_strings(path: Path):
    """源码里的**代码字符串**常量 (跳过 docstring) —— 文本类门禁用它,
    避免把"引用历史问题的说明文字"当成违规。"""
    tree = ast.parse(_read(path))
    doc_ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = getattr(node, 'body', [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                doc_ids.add(id(body[0].value))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in doc_ids):
            yield node.lineno, node.value


def _py_files():
    for py in sorted(_SKILLS.rglob('*.py')):
        if '__pycache__' in py.parts:
            continue
        yield py


class TestL3ProjectMetadata:
    """L3: 项目元数据 + CI。"""

    def test_pyproject_exists(self):
        assert (_REPO / 'pyproject.toml').is_file(), (
            '缺 pyproject.toml → 无法 pip install -e . (审计 L3)')

    def test_pyproject_parses(self):
        with open(_REPO / 'pyproject.toml', 'rb') as f:
            data = tomllib.load(f)
        assert data['project']['name'] == 'skills-quant-framework'
        assert data['build-system']['build-backend'] == 'setuptools.build_meta'

    def test_py_modules_match_disk(self):
        """`py-modules` 必须与磁盘上的平铺模块一致 (新增/删除模块须同步)。"""
        with open(_REPO / 'pyproject.toml', 'rb') as f:
            data = tomllib.load(f)
        listed = set(data['tool']['setuptools']['py-modules'])
        on_disk = {p.stem for p in _SKILLS.glob('*.py')
                   if p.name != '__init__.py'}
        # 手动冒烟脚本会联网, 不作为可安装模块 (见其模块 docstring)
        on_disk.discard('smoke_test_tool')
        assert listed == on_disk, (
            f'pyproject 的 py-modules 与磁盘不一致: '
            f'多={sorted(listed - on_disk)} 少={sorted(on_disk - listed)}')

    def test_pyproject_has_no_pytest_section(self):
        """pytest 配置只留 `pytest.ini` 一处 (两处都写 → 静默忽略其中一份)。"""
        with open(_REPO / 'pyproject.toml', 'rb') as f:
            data = tomllib.load(f)
        assert 'pytest' not in data.get('tool', {}), (
            'pyproject.toml 不得再写 [tool.pytest.ini_options] → '
            'pytest.ini 是唯一真相源')

    def test_core_package_declared(self):
        with open(_REPO / 'pyproject.toml', 'rb') as f:
            data = tomllib.load(f)
        assert data['tool']['setuptools']['package-dir'] == {'': '.claude/skills'}
        assert 'core*' in data['tool']['setuptools']['packages']['find']['include']

    def test_ci_workflow_exists_and_runs_offline_suite(self):
        wf_dir = _REPO / '.github' / 'workflows'
        assert wf_dir.is_dir(), '缺 .github/workflows → 无 CI (审计 L3)'
        files = list(wf_dir.glob('*.yml')) + list(wf_dir.glob('*.yaml'))
        assert files, 'CI 工作流为空'
        content = '\n'.join(_read(f) for f in files)
        assert 'pytest' in content and 'tests/' in content, (
            'CI 必须跑离线测试套件')
        # 不得在 CI 里打真实行情接口 (套件是离线的)
        assert 'akshare' not in content.replace(
            'pip install -r .claude/skills/requirements.txt', ''), (
            'CI 不应直接依赖 akshare 行情接口 (离线套件不需要)')


class TestL1ParameterSpaceSingleSource:
    """L1: 参数网格必须派生自 ParameterSpace。"""

    def test_parameter_space_has_grid_for(self):
        from parameter_space import ParameterSpace
        assert hasattr(ParameterSpace, 'grid_for')

    @pytest.mark.parametrize('strategy_name,dims', [
        ('MAStrategy', ('ma_fast', 'ma_slow')),
        ('MACDStrategy', ('macd_fast', 'macd_slow', 'macd_signal')),
        ('RSIStrategy', ('rsi_period', 'rsi_oversold', 'rsi_overbought')),
        ('MultiFactorStrategy', ('buy_threshold', 'sell_threshold')),
    ])
    def test_strategy_grid_uses_canonical_names(self, strategy_name, dims):
        import strategy_optimizer
        from parameter_space import ParameterSpace
        cls = getattr(strategy_optimizer, strategy_name)
        assert tuple(cls.PARAM_DIMS) == dims
        grid = cls().get_param_grid()
        assert set(grid) == set(dims), (
            f'{strategy_name} 网格参数名与规范不符: {sorted(grid)}')
        # 每个候选值都必须落在规范定义范围内
        for name, values in grid.items():
            pdef = ParameterSpace.get_param_def(name)
            for v in values:
                assert pdef.low <= v <= pdef.high, (
                    f'{strategy_name}.{name}={v} 越出规范范围 '
                    f'[{pdef.low}, {pdef.high}]')

    def test_grid_values_start_from_canonical_default(self):
        """网格首值 = 规范默认值 (compare_strategies 取首值 → 用默认参数)。"""
        import strategy_optimizer
        from parameter_space import ParameterSpace
        for name in ('MAStrategy', 'MACDStrategy', 'RSIStrategy',
                     'MultiFactorStrategy'):
            grid = getattr(strategy_optimizer, name)().get_param_grid()
            for dim, values in grid.items():
                default = ParameterSpace.get_param_def(dim).default
                assert values[0] == default, (
                    f'{name}.{dim} 网格首值 {values[0]} ≠ 规范默认 {default}')

    def test_sell_threshold_sign_matches_canonical(self):
        """`sell_threshold` 符号必须与规范一致 (旧手写网格用负值 → 反向行为)。"""
        import strategy_optimizer
        from parameter_space import ParameterSpace
        canonical = ParameterSpace.get_param_def('sell_threshold')
        assert canonical.low > 0, '规范 sell_threshold 应为正值 (分值刻度)'
        grid = strategy_optimizer.MultiFactorStrategy().get_param_grid()
        assert all(v > 0 for v in grid['sell_threshold']), (
            '策略网格的 sell_threshold 必须为正 (与规范同名同义)')

    def test_no_handwritten_param_grids(self):
        """策略类不得再手写网格 (必须走基类的派生实现)。"""
        src = _read(_SKILLS / 'strategy_optimizer.py')
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for meth in node.body:
                if not isinstance(meth, ast.FunctionDef):
                    continue
                if meth.name != 'get_param_grid':
                    continue
                # 基类的派生实现允许; 子类的"手写字典"不允许
                returns_dict = any(
                    isinstance(n, ast.Return) and isinstance(n.value, ast.Dict)
                    for n in ast.walk(meth))
                assert not returns_dict, (
                    f'{node.name}.get_param_grid 手写网格 → 必须派生自 '
                    f'ParameterSpace (审计 L1)')


class TestL2NoForeignAbsolutePaths:
    """L2: 不得出现他人机器的绝对路径。"""

    def test_no_windows_absolute_paths(self):
        """代码里不得再出现他人机器的绝对路径 (docstring 里的历史说明不计)。"""
        pattern = re.compile(r'[A-Za-z]:[\\/]Users[\\/][^\s\'"]+')
        offenders = []
        for py in list(_py_files()) + [_REPO / 'stock-analysis-skills'
                                       / 'package_skills.py']:
            if not py.is_file():
                continue
            for lineno, text in _code_strings(py):
                m = pattern.search(text)
                if m:
                    offenders.append(f'{py.relative_to(_REPO)}:{lineno}: '
                                     f'{m.group(0)}')
        assert not offenders, f'他人机器绝对路径: {offenders}'

    def test_package_script_derives_base_dir(self):
        src = _read(_REPO / 'stock-analysis-skills' / 'package_skills.py')
        assert 'Path(__file__)' in src, (
            '打包脚本必须从 __file__ 推导根目录 (不得写死绝对路径)')


class TestL5NoImportTimeSideEffects:
    """L5: skills 目录下不得有"import 即执行"的脚本。"""

    def test_no_script_matching_pytest_pattern_in_skills(self):
        offenders = [p.name for p in _SKILLS.glob('test_*.py')]
        assert not offenders, (
            f'skills 目录下有匹配 pytest 收集规则 (test_*.py) 的脚本: '
            f'{offenders} → 改名为 smoke_*.py 之类')

    def test_smoke_script_is_import_safe(self):
        """冒烟脚本: 顶层只允许定义/导入, 副作用必须在 main() 里。"""
        py = _SKILLS / 'smoke_test_tool.py'
        assert py.is_file()
        tree = ast.parse(_read(py))
        for node in tree.body:
            if isinstance(node, ast.If):
                # 只允许 `if __name__ == '__main__':` 这道标准守卫
                test = node.test
                ok_guard = (isinstance(test, ast.Compare)
                            and isinstance(test.left, ast.Name)
                            and test.left.id == '__name__')
                assert ok_guard, (
                    f'模块层出现条件语句 (行 {node.lineno}) → import 即执行')
                continue
            if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef,
                                 ast.ClassDef, ast.Assign, ast.AnnAssign,
                                 ast.Expr)):
                if isinstance(node, ast.Expr) and not isinstance(
                        node.value, ast.Constant):
                    raise AssertionError(
                        f'模块层出现副作用表达式 (行 {node.lineno})')
                continue
            raise AssertionError(
                f'模块层出现可执行语句 (行 {node.lineno}) → import 即执行')

    def test_no_bare_exit_calls(self):
        """`exit()` 来自 site 内置, 在部分环境不存在 → 应用 sys.exit。"""
        offenders = []
        for py in _py_files():
            tree = ast.parse(_read(py))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id == 'exit'):
                    offenders.append(f'{py.relative_to(_REPO)}:{node.lineno}')
        assert not offenders, (
            f'裸 exit() 调用 (应改 sys.exit()): {offenders}')


class TestL9NoDuplicateConfigClass:
    """L9: OptimizationConfig 类名全仓只允许一处定义。"""

    def test_optimization_config_defined_once(self):
        found = []
        for py in list(_py_files()) + [_REPO / 'run_web_app.py']:
            if not py.is_file():
                continue
            tree = ast.parse(_read(py))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == \
                        'OptimizationConfig':
                    found.append(f'{py.relative_to(_REPO)}:{node.lineno}')
        assert len(found) == 1, (
            f'OptimizationConfig 定义了 {len(found)} 处: {found} → '
            f'同名不同形会遮蔽 (审计 L9)')

    def test_strategy_optimizer_uses_distinct_name(self):
        import strategy_optimizer
        assert hasattr(strategy_optimizer, 'StrategyOptimizationConfig')
        assert not hasattr(strategy_optimizer, 'OptimizationConfig'), (
            'strategy_optimizer 不得再导出 OptimizationConfig (遮蔽风险)')


class TestL10VwapSemantics:
    """L10: VWAP 文档不得与实现漂移 (实现是累积口径)。"""

    def test_no_single_day_claims(self):
        """VWAP 函数的 docstring 不得再宣称"当日/单日" (实现是累积口径)。"""
        from trend_indicators import TrendIndicators
        from core.indicators import vwap as core_vwap
        targets = [
            ('core.indicators.vwap', core_vwap.__doc__ or ''),
            ('trend_indicators.vwap', TrendIndicators.vwap.__doc__ or ''),
        ]
        for name, doc in targets:
            assert '当日累积' not in doc, (
                f'{name} docstring 仍写"当日累积" → 实现是累积口径')
            assert '单日数据' not in doc, (
                f'{name} docstring 仍写"单日数据" → 实现接受序列')

    def test_core_vwap_is_cumulative(self):
        """core 的实现是累积口径 (锚定序列起点) —— 门禁锁定该语义。"""
        import numpy as np
        import pandas as pd
        from core.indicators import vwap
        n = 5
        high = pd.Series([10.0] * n)
        low = pd.Series([8.0] * n)
        close = pd.Series([9.0] * n)
        vol = pd.Series([100.0] * n)
        out = vwap(high, low, close, vol)
        # 等价于 (H+L+C)/3 = 9.0 (等权等量 → 累积 VWAP 恒为 9)
        assert np.allclose(out.values, 9.0)


class TestL11RegimeRepresentation:
    """L11: 体制表示统一为字符串。"""

    def test_regime_dataclasses_use_str(self):
        from market_regime_classifier import RegimeStats, RegimeWindow
        assert RegimeWindow.__annotations__['regime'] in (str, 'str')
        assert RegimeStats.__annotations__['regime'] in (str, 'str')

    def test_regime_enum_provides_value_set(self):
        from market_regime_classifier import Regime
        assert Regime.values() == ('BULL', 'BEAR', 'SIDEWAYS', 'CRASH',
                                   'RECOVERY')
        assert Regime.is_valid('BULL')
        assert not Regime.is_valid('bull')

    def test_no_enum_instances_in_classifier_output(self):
        """分类器不得把枚举实例塞进体制序列/数据结构。"""
        src = _read(_SKILLS / 'market_regime_classifier.py')
        tree = ast.parse(src)
        offenders = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == 'Regime'):
                offenders.append(node.lineno)
        assert not offenders, (
            f'分类器仍在把体制转成枚举实例 (行 {offenders}) → 统一用字符串')
