# 部署安装指南 v2.0

**版本：** v2.0
**更新日期：** 2026-02-06

---

## 系统要求

### 操作系统

- Windows 10/11
- Linux (Ubuntu 20.04+, Debian 10+, CentOS 7+)
- macOS 10.15+

### Python版本

- Python 3.7+
- 推荐 Python 3.10

### 硬件要求

- CPU: 2核心+
- 内存: 4GB+
- 磁盘: 10GB+

---

## 环境安装

### 1. 安装Python

#### Windows

```bash
# 下载Python 3.10
# https://www.python.org/downloads/

# 安装时勾选：
# ☑ Add Python to PATH
# ☑ pip
```

#### Linux (Ubuntu/Debian)

```bash
sudo apt update
sudo apt install python3.10 python3-pip python3-venv
```

#### macOS

```bash
# 使用Homebrew
brew install python@3.10
```

### 2. 安装依赖

```bash
# 基础依赖
pip install pandas numpy matplotlib akshare openpyxl

# Web应用依赖
pip install streamlit

# 机器学习
pip install scikit-learn scipy
```

或使用requirements文件：

```bash
pip install -r requirements.txt
pip install -r web_requirements.txt
```

> 注：Redis/PostgreSQL 不再需要——`cache_manager`/`database_manager` 已随孤岛清理删除（项 15），回测数据真相为本地 Parquet。

---

## 应用配置

### 1. 配置文件

创建 `.env` 文件：

```ini
# 应用配置
DATA_DIR=./stock_data
CHARTS_DIR=./charts
LOG_LEVEL=INFO
```

### 2. 目录结构

```
Stocks/
├── .claude/
│   └── skills/           # 核心模块
├── stock_data/           # 数据存储
├── charts/               # 图表输出
├── logs/                 # 日志文件
├── tests/                # 测试文件
├── web_requirements.txt
├── requirements.txt
└── run_web_app.py
```

---

## 启动应用

### 开发模式

```bash
# 启动Web应用
python run_web_app.py

# 或直接使用Streamlit
streamlit run .claude/skills/web_app.py --server.port=8501
```

### 生产模式

#### 使用Gunicorn (Linux/macOS)

```bash
# 安装gunicorn
pip install gunicorn

# 启动
gunicorn -w 4 -k uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8501 \
    web_app:main
```

#### 使用systemd服务

创建 `/etc/systemd/system/skills-app.service`:

```ini
[Unit]
Description=Skills Stock Analysis App
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/Stocks
ExecStart=/path/to/venv/bin/streamlit run \
    .claude/skills/web_app.py \
    --server.port=8501 \
    --server.address=0.0.0.0
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable skills-app
sudo systemctl start skills-app
```

---

## Docker部署

### Dockerfile

```dockerfile
FROM python:3.10-slim

WORKDIR /app

# 复制依赖文件
COPY requirements.txt web_requirements.txt ./

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -r web_requirements.txt

# 复制应用代码
COPY .claude/skills/ /app/.claude/skills/

# 暴露端口
EXPOSE 8501

# 健康检查
HEALTHCHECK CMD streamlit hello /dev/null || exit 1

# 启动应用
CMD ["streamlit", "run", ".claude/skills/web_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

### docker-compose.yml

```yaml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "8501:8501"
    volumes:
      - ./stock_data:/app/stock_data
      - ./charts:/app/charts
    restart: unless-stopped
```

启动：

```bash
docker-compose up -d
```

---

## 性能优化

```python
# 并发配置
import os
os.environ['OMP_NUM_THREADS'] = '4'
```

---

## 监控和日志

### 日志配置

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/app.log'),
        logging.StreamHandler()
    ]
)
```

---

## 故障排查

### 问题：端口被占用

```bash
# 查看端口占用
# Windows
netstat -ano | findstr :8501

# Linux/macOS
lsof -i :8501

# 更改端口
streamlit run web_app.py --server.port 8502
```

### 问题：模块导入错误

```bash
# 确认Python路径
export PYTHONPATH="${PYTHONPATH}:/path/to/Stocks"

# 或在代码中添加
sys.path.append('/path/to/Stocks')
sys.path.append('/path/to/Stocks/.claude/skills')
```

---

## 更新升级

### 更新代码

```bash
# 拉取最新代码
git pull

# 更新依赖
pip install --upgrade -r requirements.txt
pip install --upgrade -r web_requirements.txt
```

### 数据迁移

```bash
# 备份数据
cp -r stock_data stock_data.backup

# 运行迁移脚本
python scripts/migrate.py
```

---

**文档版本：** v2.0
**最后更新：** 2026-02-06
