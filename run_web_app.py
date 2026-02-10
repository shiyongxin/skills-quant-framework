# -*- coding: utf-8 -*-
"""
Web应用启动脚本
Web Application Launcher
"""

import os
import sys
import subprocess

def install_dependencies():
    """安装Web应用依赖"""
    print("正在安装Web应用依赖...")

    requirements = [
        "streamlit>=1.28.0",
        "redis>=5.0.0",
        "psycopg2-binary>=2.9.9",
        "SQLAlchemy>=2.0.0",
        "scikit-learn>=1.3.0",
    ]

    for req in requirements:
        print(f"安装 {req}...")
        subprocess.run([sys.executable, "-m", "pip", "install", req],
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
