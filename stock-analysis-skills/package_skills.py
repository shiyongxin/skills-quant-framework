# -*- coding: utf-8 -*-
"""Package script for stock-analysis-skills"""
import sys
import os
import zipfile
from pathlib import Path

# Set UTF-8 encoding for Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def package_skill(skill_path, output_dir=None):
    """Package a skill into a .skill file"""
    skill_path = Path(skill_path)
    if not skill_path.exists():
        print(f"Error: Skill path not found: {skill_path}")
        return False

    skill_name = skill_path.name
    output_file = skill_path.parent / f"{skill_name}.skill"

    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"{skill_name}.skill"

    # Create zip file
    # 注: 输出目录默认就在技能目录内 (`<skill>/dist`) → 必须排除 dist 与
    # 输出文件本身, 否则打包会**把自身打进去** (自我包含 → 文件无限增长)
    excluded_dirs = {output_file.parent.resolve()}

    with zipfile.ZipFile(output_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file_path in sorted(skill_path.rglob('*')):
            if not file_path.is_file():
                continue
            if file_path.resolve() == output_file.resolve():
                continue
            if any(parent.resolve() in excluded_dirs
                   for parent in file_path.parents):
                continue
            # 不打包字节码缓存 (体积大、随环境变化)
            if '__pycache__' in file_path.parts or file_path.suffix == '.pyc':
                continue
            arcname = file_path.relative_to(skill_path)
            zipf.write(file_path, arcname)
            print(f"  Added: {arcname}")

    print(f"Created: {output_file}")
    return True

def discover_skill_dirs(base_dir: Path) -> list:
    """发现技能目录 (含 `SKILL.md` 的子目录) —— 不写死技能名清单。

    审计 L2: 旧实现写死了**他人机器**的绝对路径
    (`F:/Users/shiyo/80.soft_dev/Stocks/stock-analysis-skills`) + 一份
    **已过时**的技能名清单 (仓库里一个都不存在) → 脚本在本机必然全量失败,
    且清单永远会随仓库结构变化而过期。
    """
    if not base_dir.is_dir():
        return []
    found = []
    # 根目录自身即一个技能 (本仓库布局: `.claude/skills/SKILL.md`)
    if (base_dir / 'SKILL.md').exists():
        found.append(base_dir)
    # 子目录形式的技能 (每个子目录自带 SKILL.md)
    found.extend(sorted(p for p in base_dir.iterdir()
                        if p.is_dir() and (p / 'SKILL.md').exists()))
    return found


def main(argv=None):
    """打包所有技能。

    用法:
        python package_skills.py [技能根目录]

    默认根目录 = 本脚本所在目录 (审计 L2: 不再写死他人机器的绝对路径)。
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    base_dir = (Path(argv[0]).expanduser().resolve() if argv
                else Path(__file__).resolve().parent)
    skills = discover_skill_dirs(base_dir)

    print(f"技能根目录: {base_dir}")
    if not skills:
        print("[WARN] 该目录下没有含 SKILL.md 的技能目录 → 无可打包内容")
        return

    dist_dir = base_dir / "dist"
    dist_dir.mkdir(exist_ok=True)

    for skill_path in skills:
        print(f"\nPackaging: {skill_path.name}")
        if package_skill(skill_path, dist_dir):
            print("  Success!")
        else:
            print("  Failed!")

    print(f"\nAll skills packaged to: {dist_dir}")

if __name__ == "__main__":
    main()
