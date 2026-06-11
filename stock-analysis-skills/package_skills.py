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
    with zipfile.ZipFile(output_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file_path in skill_path.rglob('*'):
            if file_path.is_file():
                arcname = file_path.relative_to(skill_path)
                zipf.write(file_path, arcname)
                print(f"  Added: {arcname}")

    print(f"Created: {output_file}")
    return True

def main():
    """Package all skills"""
    base_dir = Path("F:/Users/shiyo/80.soft_dev/Stocks/stock-analysis-skills")
    skills = [
        "stock-analysis",
        "stock-data-fetcher",
        "stock-technical-analysis",
        "stock-selection",
        "stock-position-analysis",
        "stock-backtesting",
        "stock-visualization",
    ]

    dist_dir = base_dir / "dist"
    dist_dir.mkdir(exist_ok=True)

    for skill in skills:
        print(f"\nPackaging: {skill}")
        skill_path = base_dir / skill
        if package_skill(skill_path, dist_dir):
            print(f"  Success!")
        else:
            print(f"  Failed!")

    print(f"\nAll skills packaged to: {dist_dir}")

if __name__ == "__main__":
    main()
