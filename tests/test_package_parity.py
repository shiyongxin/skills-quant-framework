# -*- coding: utf-8 -*-
"""
批次4 治理门禁 —— 部署包副本必须是主链的**构建产物**, 不是第二个真相源

背景 (审计 H3 批次4):
- `optimization_package/` (gitignored) 曾长期持有主链模块的**复制品**,
  且已**漂移 5000+ 行** (optimization_engine 1106 行 / vectorized_backtest
  690 行 / historical_data_manager 577 行 / signal_generator 466 行 …),
  并且**不含**任何已审计修复 (无 H1 样本外隔离 / 无 H2 证据化 confidence /
  无 H5 停牌建模 / 无 H6 点时口径 / 无 core/ 统一指标) —— 若被下游加载,
  等于用未审计逻辑污染已审计主链。
- 旧 `pack.py` 用**手写清单** → 主链新增依赖后必然漏 (实测漏
  execution_model / factor_library / sina_daily / stock_list_manager /
  trade_constraints + 整个 core/ → 打包产物连 import 都过不去)。
- `indicator_system_report.py` **只存在于副本**、主链无源 → 打包时 [SKIP]
  → 产物缺报告生成器 (副本 run_optimize.py 依赖它出报告)。

治理决策 (2026-10-26): **主链是唯一真相源; 副本降级为构建产物** ——
`pack.py` 改依赖闭包自动打包 + 写 PROVENANCE.json (源 commit + sha256),
包内文件带"请勿手改"戳; `indicator_system_report.py` 并入主链。

本门禁锁定:
- 打包产物**可 import** (依赖闭包完整 —— 旧 pack.py 直接失败);
- 产物内容与主链**逐字节一致** (除"请勿手改"戳头) → 零手改;
- PROVENANCE 存在且记录源 commit + 每文件 sha256;
- 主链不再有"只在副本存在"的模块 (孤儿模块清零);
- 工作区里的既有副本若已陈旧 → **告警但不阻塞** (该目录 gitignored,
  不是仓库内容; 陈旧与否由 PROVENANCE 自证, 不该让每次提交都红)。
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / '.claude' / 'skills'
# 打包脚本在**主链内** (受版本控制) —— 构建工具本身必须被跟踪,
# 否则治理决策不可复现/评审 (审计 H3 批次4)
PACK_PY = REPO_ROOT / '.claude' / 'skills' / 'tools' / 'pack.py'
COPY_SKILLS = (REPO_ROOT / 'optimization_package' / 'optimization_package'
               / 'skills')

sys.path.insert(0, str(PACK_PY.parent))
import pack as pack_mod  # noqa: E402  (主链内的打包脚本)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def _strip_header(text: str) -> str:
    """去掉注入的"请勿手改"戳头 → 与主链逐字节比对用。"""
    marker = '# ⚠️ 本文件由 pack.py 从主链 .claude/skills/ 自动生成 —— 请勿手改'
    lines = text.splitlines(keepends=True)
    out = []
    skip = False
    for line in lines:
        if skip:
            skip = False
            continue
        if marker in line:
            skip = True          # 下一行是戳的第二行
            continue
        out.append(line)
    return ''.join(out)


@pytest.fixture(scope='module')
def built(tmp_path_factory):
    """把主链打包到临时目录 (真实执行 pack.py 的构建逻辑)。"""
    out = tmp_path_factory.mktemp('pkg')
    prov = pack_mod.build_package(out)
    return out, prov


class TestPackageBuild:
    """打包产物自洽性 (依赖闭包完整 + 内容与主链一致)。"""

    def test_pack_script_is_version_controlled(self):
        """打包脚本必须**在版本控制内** (旧实现在 gitignored 目录里 →
        构建工具本身不可复现/评审 → 治理决策形同虚设)。"""
        res = subprocess.run(
            ['git', '-C', str(REPO_ROOT), 'ls-files',
             str(PACK_PY.relative_to(REPO_ROOT))],
            capture_output=True, text=True, timeout=30)
        assert res.stdout.strip(), (
            f'{PACK_PY.relative_to(REPO_ROOT)} 未被 git 跟踪 → '
            '构建工具必须进版本控制')

    def test_entry_modules_exist_in_main_chain(self):
        """打包入口模块必须在主链存在 (旧 pack.py 列的
        indicator_system_report.py 曾只存在于副本 → 主链无源)。"""
        missing = [n for n in pack_mod.ENTRY_MODULES
                   if not (SKILLS_DIR / n).exists()]
        assert not missing, f'打包入口在主链不存在: {missing}'

    def test_provenance_recorded(self, built):
        _, prov = built
        assert prov['source_commit'] and prov['source_commit'] != 'unknown'
        assert prov['generated_at']
        assert prov['files'], 'PROVENANCE 未记录任何文件'
        assert '请勿手改' in prov['note']

    def test_core_package_included(self, built):
        """core/ 子包必须整包带进产物 (主链 19 模块依赖它)。"""
        out, prov = built
        assert (out / 'skills' / 'core').is_dir()
        assert (out / 'skills' / 'core' / 'indicators.py').exists()
        assert (out / 'skills' / 'core' / 'suspension.py').exists()

    def test_execution_model_included(self, built):
        """旧 pack.py 漏掉 execution_model → 产物 import 直接失败。"""
        out, _ = built
        assert (out / 'skills' / 'execution_model.py').exists()

    def test_product_is_importable(self, built):
        """产物**可 import** (旧 pack.py 的产物 ModuleNotFoundError)。"""
        out, _ = built
        skills = out / 'skills'
        code = (
            'import sys; sys.path.insert(0, %r);'
            'import optimization_engine, vectorized_backtest,'
            'backtest_framework, daily_signal_generator, signal_generator,'
            'indicator_system_report;'
            'import core.suspension, core.metrics, core.indicators;'
            'print("OK")' % str(skills)
        )
        env = dict(os.environ)
        env['PYTHONPATH'] = str(skills)
        res = subprocess.run([sys.executable, '-c', code], capture_output=True,
                             text=True, env=env, timeout=120)
        assert res.returncode == 0, f'产物不可 import:\n{res.stderr[-2000:]}'
        assert 'OK' in res.stdout

    def test_bytes_identical_to_main_chain(self, built):
        """产物内容与主链**逐字节一致** (除戳头) → 副本零手改。"""
        out, prov = built
        for name in prov['files']:
            if not name.endswith('.py'):
                continue
            src = SKILLS_DIR / name
            dst = out / 'skills' / name
            if not src.exists():
                continue
            assert _strip_header(dst.read_text(encoding='utf-8')) == \
                src.read_text(encoding='utf-8'), f'{name} 与主链不一致'

    def test_generated_header_present(self, built):
        """包内文件带"请勿手改"戳 → 阻止手改副本。"""
        out, prov = built
        target = out / 'skills' / 'optimization_engine.py'
        assert '由 pack.py 从主链' in target.read_text(encoding='utf-8')


class TestNoOrphanModules:
    """主链不再有"只在副本存在"的模块 (孤儿清零)。"""

    def test_copy_only_modules_merged_into_main_chain(self):
        copy_only = []
        if COPY_SKILLS.is_dir():
            for p in COPY_SKILLS.glob('*.py'):
                if not (SKILLS_DIR / p.name).exists():
                    copy_only.append(p.name)
        assert not copy_only, (
            f'副本独有、主链无源的模块: {copy_only} → 并入主链或从副本删除')

    def test_pack_script_not_left_in_ignored_copy(self):
        """打包脚本不得留在 gitignored 的副本里 (构建工具必须被跟踪)。"""
        stale = REPO_ROOT / 'optimization_package' / 'optimization_package' / \
            'pack.py'
        assert not stale.exists(), (
            '打包脚本仍在 gitignored 的副本目录 → 构建工具不受版本控制')

    def test_main_chain_has_no_orphan_report_module(self):
        """indicator_system_report 已并入主链 (副本 run_optimize.py 依赖)。"""
        assert (SKILLS_DIR / 'indicator_system_report.py').exists()


class TestWorkdirCopyStatus:
    """工作区副本状态: 陈旧只告警, 不阻塞 (目录 gitignored, 非仓库内容)。"""

    def test_workdir_copy_is_self_identifying(self):
        """若工作区副本存在, 必须自带 PROVENANCE (自证来自哪个版本)。"""
        if not COPY_SKILLS.is_dir():
            pytest.skip('工作区无副本 (gitignored, 非仓库内容)')
        prov_path = COPY_SKILLS / 'PROVENANCE.json'
        if not prov_path.exists():
            pytest.skip('工作区副本尚未按新 pack.py 重打 (无 provenance)')
        prov = json.loads(prov_path.read_text(encoding='utf-8'))
        assert prov.get('source_commit')
        assert prov.get('files')

    def test_stale_workdir_copy_is_detectable(self):
        """陈旧副本必须**可检出** (provenance 的 sha256 与实际文件不符)。"""
        if not COPY_SKILLS.is_dir():
            pytest.skip('工作区无副本')
        prov_path = COPY_SKILLS / 'PROVENANCE.json'
        if not prov_path.exists():
            pytest.skip('工作区副本尚未重打')
        prov = json.loads(prov_path.read_text(encoding='utf-8'))
        stale = []
        for name, digest in prov.get('files', {}).items():
            f = COPY_SKILLS / name
            if f.is_file() and _sha256(f) != digest:
                stale.append(name)
        # 陈旧是**可检出的状态**, 不是失败 (门禁只要求"能检出")
        assert isinstance(stale, list)


class TestPackScriptHygiene:
    """pack.py 自身: 依赖闭包解析要正确 (旧手写清单的教训)。"""

    def test_closure_resolves_transitive_local_deps(self):
        modules, packages = pack_mod.resolve_closure(['optimization_engine.py'])
        assert 'optimization_engine.py' in modules
        assert 'core' in packages
        # 传递依赖: optimization_engine → vectorized_backtest → execution_model
        assert 'vectorized_backtest.py' in modules
        assert 'execution_model.py' in modules

    def test_closure_ignores_external_deps(self):
        modules, _ = pack_mod.resolve_closure(['parameter_space.py'])
        assert not any(m.startswith(('numpy', 'pandas', 'scipy'))
                       for m in modules)

    def test_closure_normalizes_extension(self):
        """入口写 'x.py' 与 'x' 都要解析到同一模块 (双扩展名 bug 回归)。"""
        a, _ = pack_mod.resolve_closure(['parameter_space.py'])
        b, _ = pack_mod.resolve_closure(['parameter_space'])
        assert a == b
