# -*- coding: utf-8 -*-
"""
Web应用启动脚本
Web Application Launcher
"""

import os
import sys
import subprocess

def install_dependencies():
    """安装依赖 — 以依赖清单文件为唯一真相源

    (旧实现内联硬编码列表, 已与实际依赖脱节: 仍装 redis/psycopg2/SQLAlchemy
     —— 这三个模块早已删除; 反而漏装 matplotlib —— web 层图表的守卫依赖)
    """
    root = os.path.dirname(os.path.abspath(__file__))
    manifests = [
        os.path.join(root, 'web_requirements.txt'),
        os.path.join(root, '.claude', 'skills', 'requirements.txt'),
    ]
    for manifest in manifests:
        if not os.path.exists(manifest):
            print(f"[SKIP] 依赖清单不存在: {manifest}")
            continue
        print(f"安装 {manifest} ...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", manifest],
                       capture_output=True)

    print("依赖安装完成！")


def run_app():
    """启动Web应用"""
    # 设置环境变量
    os.environ['PYTHONPATH'] = os.path.dirname(os.path.abspath(__file__))

    # Streamlit配置
    app_path = os.path.join(os.path.dirname(__file__), ".claude", "skills", "web_app.py")

    print("=" * 50)
    print("Skills 股票分析平台")
    print("=" * 50)
    print()
    print("正在启动Web应用...")
    print(f"应用地址: http://localhost:8501")
    print()
    print("按 Ctrl+C 停止应用")
    print("=" * 50)
    print()

    # 启动Streamlit
    subprocess.run([sys.executable, "-m", "streamlit", "run", app_path,
                   "--server.port=8501",
                   "--server.address=localhost",
                   "--theme.base=light"])


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Skills Web应用启动器")
    parser.add_argument("--install", action="store_true", help="安装依赖")
    parser.add_argument("--run", action="store_true", help="运行应用（默认）")

    args = parser.parse_args()

    if args.install:
        install_dependencies()

    # 默认运行应用
    run_app()
