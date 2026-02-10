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

# 缓存和数据库
pip install redis psycopg2-binary sqlalchemy

# 机器学习
pip install scikit-learn scipy
```

或使用requirements文件：

```bash
pip install -r requirements.txt
pip install -r web_requirements.txt
```

### 3. 安装Redis

#### Windows

```bash
# 使用Chocolatey
choco install redis

# 或下载MSI安装包
# https://github.com/microsoftarchive/redis/releases
```

#### Linux

```bash
sudo apt update
sudo apt install redis-server
sudo systemctl start redis
```

#### macOS

```bash
brew install redis
brew services start redis
```

验证Redis：

```bash
redis-cli ping
# 应返回: PONG
```

### 4. 安装PostgreSQL（可选）

#### Windows

```bash
# 下载安装包
# https://www.enterprisedb.com/downloads/postgresql-install/

# 或使用Chocolatey
choco install postgresql
```

#### Linux

```bash
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql
```

#### macOS

```bash
brew install postgresql
brew services start postgresql
```

创建数据库：

```bash
# 切换到postgres用户
sudo -u postgres psql

# 创建数据库
CREATE DATABASE stocks_db;

# 创建用户
CREATE USER stocks_user WITH PASSWORD 'your_password';

# 授权
GRANT ALL PRIVILEGES ON DATABASE stocks_db TO stocks_user;

# 退出
\q
```

---

## 应用配置

### 1. 配置文件

创建 `.env` 文件：

```ini
# 数据库配置
DB_HOST=localhost
DB_PORT=5432
DB_NAME=stocks_db
DB_USER=stocks_user
DB_PASSWORD=your_password

# Redis配置
REDIS_HOST=localhost
REDIS_PORT=6379

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

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc g++ libpq-dev \
    && rm -rf /var/lib/apt/lists/*

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
    environment:
      - REDIS_HOST=redis
      - DB_HOST=db
    depends_on:
      - redis
      - db
    volumes:
      - ./stock_data:/app/stock_data
      - ./charts:/app/charts
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    restart: unless-stopped

  db:
    image: postgres:15-alpine
    environment:
      - POSTGRES_DB=stocks_db
      - POSTGRES_USER=stocks_user
      - POSTGRES_PASSWORD=your_password
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

volumes:
  redis_data:
  postgres_data:
```

启动：

```bash
docker-compose up -d
```

---

## 性能优化

### 1. Redis配置

编辑 `redis.conf`：

```conf
# 最大内存限制
maxmemory 2gb

# 淘汰策略
maxmemory-policy allkeys-lru

# 持久化
save 900 1
save 300 10
save 60 10000
```

### 2. PostgreSQL配置

编辑 `postgresql.conf`：

```conf
# 连接数
max_connections = 200

# 内存配置
shared_buffers = 256MB
effective_cache_size = 1GB

# 查询优化
random_page_cost = 1.1
effective_io_concurrency = 200

# WAL配置
wal_buffers = 16MB
checkpoint_completion_target = 0.9
```

### 3. 应用优化

```python
# 并发配置
import os
os.environ['OMP_NUM_THREADS'] = '4'

# 内存限制
import resource
resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 4 * 1024**3))
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

### 性能监控

```python
# 缓存统计
from cache_manager import get_cache_manager

cache = get_cache_manager()
stats = cache.get_stats()
print(f"缓存命中率: {stats['hit_rate']:.2%}")

# 数据库统计
from database_manager import DatabaseManager

db = DatabaseManager()
stats = db.get_table_stats()
print(f"数据记录数: {stats}")
```

---

## 故障排查

### 问题1：Redis连接失败

```bash
# 检查Redis状态
redis-cli ping

# 启动Redis
# Windows
redis-server

# Linux
sudo systemctl start redis
```

### 问题2：数据库连接失败

```bash
# 检查PostgreSQL状态
sudo systemctl status postgresql

# 启动PostgreSQL
sudo systemctl start postgresql

# 检查连接
psql -h localhost -U stocks_user -d stocks_db
```

### 问题3：端口被占用

```bash
# 查看端口占用
# Windows
netstat -ano | findstr :8501

# Linux/macOS
lsof -i :8501

# 更改端口
streamlit run web_app.py --server.port 8502
```

### 问题4：模块导入错误

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
