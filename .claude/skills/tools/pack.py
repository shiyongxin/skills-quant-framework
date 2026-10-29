# -*- coding: utf-8 -*-
"""
打包脚本 —— 把主链模块打包成可离线分发的部署包 (审计 H3 批次4 治理)

治理定位 (2026-10-26 决策):
- **主链 `.claude/skills/` 是唯一真相源**; 本目录的 `skills/` 是**构建
  产物** —— 由本脚本生成, **请勿手改** (下次打包即被覆盖)。
- 旧实现用**手写清单** (`SKILLS = [...]`) → 主链新增依赖后必然漏
  (实测: 漏 execution_model / factor_library / sina_daily /
  stock_list_manager / trade_constraints + 整个 core/ 包 → 打包产物
  连 import 都过不去, `ModuleNotFoundError: No module named
  'execution_model'`), 而副本因长期漏打已**漂移 5000+ 行**, 且带着
  **未审计的旧语义** (无 H1 样本外隔离 / 无 H2 证据化 confidence /
  无 H5 停牌建模 / 无 H6 点时口径) —— 若被下游加载, 等于用旧逻辑污染
  已审计主链。
- 现改为**依赖闭包自动发现** (AST 扫描 + 递归) + 整包复制 `core/` →
  结构上不可能再漏依赖; 并写 `PROVENANCE.json` (源 commit + 时间戳 +
  每文件 sha256) → 部署包自带"来自哪个版本"的证据, 陈旧产物无法冒充最新。

用法 (在仓库根目录运行):
    python .claude/skills/tools/pack.py
    python .claude/skills/tools/pack.py --out /tmp/pkg

位置说明 (审计 H3 批次4): 本脚本**在主链内** (受版本控制) —— 旧实现在
gitignored 的 `optimization_package/optimization_package/pack.py`, 即
**构建工具本身不在版本控制里** → 治理决策无法复现/评审。现在脚本受
跟踪, 产物 (skills/) 仍 gitignored。
"""
import argparse
import ast
import hashlib
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

# 本脚本位于 <repo>/.claude/skills/tools/pack.py
REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = REPO_ROOT / '.claude' / 'skills'
# 默认产物目录 (部署包根: 与 README.md / run_optimize.py 同级)
DEFAULT_PKG_DIR = REPO_ROOT / 'optimization_package' / 'optimization_package'

# 打包入口 (从这些模块出发, 按 import 闭包自动扩展)
ENTRY_MODULES = [
    'market_regime_classifier.py',
    'historical_data_manager.py',
    'parameter_space.py',
    'vectorized_backtest.py',
    'optimization_engine.py',
    'multi_stock_backtester.py',
    'optimization_config.py',
    'daily_signal_generator.py',
    'indicator_system_report.py',
    'signal_generator.py',
    'technical_analyzer.py',
    'stock_data_fetcher.py',
    'advanced_indicators.py',
    'trend_indicators.py',
    'pattern_recognition.py',
    'risk_management.py',
    'backtest_framework.py',
]

# 资源文件 (非 .py, 但运行必需)
RESOURCE_FILES = ['stock_list.csv']

# 包内配置 (若有)
CONFIG_DIR_NAME = 'config'

GENERATED_HEADER = (
    "# ⚠️ 本文件由 pack.py 从主链 .claude/skills/ 自动生成 —— 请勿手改\n"
    "# (下次打包即被覆盖; 改动请改主链, 再重跑 pack.py)\n"
)


def _local_imports(path: Path) -> set:
    """取模块的**本地**顶层 import (同名 .py 或 core 子包)。"""
    out = set()
    try:
        tree = ast.parse(path.read_text(encoding='utf-8'))
    except (SyntaxError, UnicodeDecodeError):
        return out
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            out.add(node.module.split('.')[0])
    return out


def resolve_closure(entry: list) -> tuple:
    """依赖闭包解析 → (单文件模块集合, 子包集合)。

    单文件: `foo.py` 同名模块; 子包: `core` (整目录复制)。
    入口/依赖一律按**模块名** (无扩展名) 归一, 避免 'x.py' + '.py' 双扩展名。
    """
    modules, packages = set(), set()
    stack = [str(n).removesuffix('.py') for n in entry]
    seen = set()
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        if name == 'core':
            packages.add(name)
            continue
        src = SRC_DIR / f'{name}.py'
        if not src.exists():
            continue          # 外部依赖 (numpy/pandas/scipy...) → 忽略
        modules.add(f'{name}.py')
        stack.extend(_local_imports(src))
    return modules, packages


def _inject_header(path: Path) -> None:
    """给生成的模块加"请勿手改"戳 (幂等: 已带戳则跳过)。"""
    text = path.read_text(encoding='utf-8')
    if '由 pack.py 从主链' in text:
        return
    lines = text.splitlines(keepends=True)
    # 保留 shebang + coding 行, 其后插入戳
    insert_at = 0
    for i, line in enumerate(lines[:3]):
        if line.startswith('#!') or 'coding' in line:
            insert_at = i + 1
    new_text = ''.join(lines[:insert_at]) + GENERATED_HEADER + \
        ''.join(lines[insert_at:])
    path.write_text(new_text, encoding='utf-8')


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ['git', '-C', str(REPO_ROOT), 'rev-parse', 'HEAD'],
            capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or 'unknown'
    except (OSError, subprocess.SubprocessError):
        return 'unknown'


def build_package(dst_dir: Path) -> dict:
    """执行打包 → 返回 provenance 字典。"""
    skills_dst = dst_dir / 'skills'
    if skills_dst.exists():
        shutil.rmtree(skills_dst)
    skills_dst.mkdir(parents=True, exist_ok=True)

    modules, packages = resolve_closure(ENTRY_MODULES)

    copied = []
    for name in sorted(modules):
        shutil.copy2(SRC_DIR / name, skills_dst / name)
        _inject_header(skills_dst / name)
        copied.append(name)

    # 整包复制子包 (core/ 等)
    for pkg in sorted(packages):
        src_pkg = SRC_DIR / pkg
        if not src_pkg.is_dir():
            continue
        shutil.copytree(src_pkg, skills_dst / pkg,
                        ignore=shutil.ignore_patterns('__pycache__'))
        copied.append(f'{pkg}/ (目录)')

    # 资源文件
    for name in RESOURCE_FILES:
        src = SRC_DIR / name
        if src.exists():
            shutil.copy2(src, skills_dst / name)
            copied.append(name)

    # 配置目录 (若有)
    cfg = SRC_DIR / CONFIG_DIR_NAME
    if cfg.is_dir():
        shutil.copytree(cfg, skills_dst / CONFIG_DIR_NAME,
                        ignore=shutil.ignore_patterns('__pycache__'))
        copied.append(f'{CONFIG_DIR_NAME}/ (目录)')

    provenance = {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'source_commit': _git_commit(),
        'source_dir': str(SRC_DIR),
        'entry_modules': list(ENTRY_MODULES),
        'files': {name: _sha256(skills_dst / name)
                  for name in sorted(copied)
                  if (skills_dst / name).is_file()},
        'note': ('本包由 pack.py 从主链 .claude/skills/ 生成; 真相源在主链, '
                 '包内文件请勿手改 (下次打包即被覆盖)'),
    }
    (skills_dst / 'PROVENANCE.json').write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2), encoding='utf-8')
    return provenance


def main():
    parser = argparse.ArgumentParser(description='打包主链模块为离线部署包')
    parser.add_argument('--out', default=None,
                        help='输出目录 (默认: optimization_package/optimization_package/)')
    args = parser.parse_args()

    # 默认: 部署包根目录 (与 README.md / run_optimize.py / requirements.txt
    # 同处一个部署包里 → 生成其下的 skills/)
    dst = Path(args.out) if args.out else DEFAULT_PKG_DIR
    dst.mkdir(parents=True, exist_ok=True)

    print(f"打包源目录: {SRC_DIR}")
    print(f"输出目录:   {dst / 'skills'}")

    prov = build_package(dst)
    n = len(prov['files'])
    print(f"\n[OK] 打包完成: {n} 个文件 + PROVENANCE.json")
    print(f"     源 commit: {prov['source_commit']}")
    print(f"     生成时间: {prov['generated_at']}")
    print("     (真相源在主链 .claude/skills/; 包内文件请勿手改)")


if __name__ == '__main__':
    main()
