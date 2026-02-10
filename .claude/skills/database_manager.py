# -*- coding: utf-8 -*-
"""
PostgreSQL数据库管理器
PostgreSQL Database Manager

提供数据库连接、数据存储、查询等功能
"""

import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
import pandas as pd
import numpy as np
from contextlib import contextmanager

try:
    from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, Date, DECIMAL, BIGINT, Index, text, func
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import sessionmaker, Session
    from sqlalchemy.pool import QueuePool
    from sqlalchemy.exc import SQLAlchemyError
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False

try:
    import psycopg2
    from psycopg2.extras import register_uuid
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False


# =============================================================================
# 基础模型
# =============================================================================

if SQLALCHEMY_AVAILABLE:
    Base = declarative_base()

    class Stock(Base):
        """股票基础信息表"""
        __tablename__ = 'stocks'

        id = Column(Integer, primary_key=True, autoincrement=True)
        symbol = Column(String(10), unique=True, nullable=False, index=True)
        name = Column(String(50), nullable=False)
        market = Column(String(10))  # SH/SZ
        industry = Column(String(50))
        sector = Column(String(50))
        list_date = Column(Date)
        delist_date = Column(Date)
        is_active = Column(Boolean, default=True)
        created_at = Column(DateTime, default=datetime.now)
        updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    class StockQuote(Base):
        """股票历史行情表"""
        __tablename__ = 'stock_quotes'

        id = Column(Integer, primary_key=True, autoincrement=True)
        symbol = Column(String(10), nullable=False, index=True)
        date = Column(Date, nullable=False, index=True)
        open = Column(DECIMAL(10, 2))
        high = Column(DECIMAL(10, 2))
        low = Column(DECIMAL(10, 2))
        close = Column(DECIMAL(10, 2))
        volume = Column(BIGINT)
        amount = Column(BIGINT)
        change_pct = Column(Float)
        turnover_rate = Column(Float)

        # 复合索引
        __table_args__ = (
            Index('idx_symbol_date', 'symbol', 'date'),
        )

    class Signal(Base):
        """交易信号表"""
        __tablename__ = 'signals'

        id = Column(Integer, primary_key=True, autoincrement=True)
        symbol = Column(String(10), nullable=False, index=True)
        date = Column(Date, nullable=False, index=True)
        signal_type = Column(String(20))  # buy/sell/hold
        strength = Column(Float)
        source = Column(String(50))  # 信号来源
        created_at = Column(DateTime, default=datetime.now)

    class BacktestResult(Base):
        """回测结果表"""
        __tablename__ = 'backtest_results'

        id = Column(Integer, primary_key=True, autoincrement=True)
        strategy_name = Column(String(50), nullable=False)
        symbol = Column(String(10))
        start_date = Column(Date)
        end_date = Column(Date)
        initial_cash = Column(DECIMAL(15, 2))
        final_value = Column(DECIMAL(15, 2))
        total_return = Column(Float)
        annual_return = Column(Float)
        sharpe_ratio = Column(Float)
        max_drawdown = Column(Float)
        win_rate = Column(Float)
        profit_factor = Column(Float)
        total_trades = Column(Integer)
        parameters = Column(String(500))  # JSON string
        created_at = Column(DateTime, default=datetime.now)

    class Portfolio(Base):
        """投资组合表"""
        __tablename__ = 'portfolios'

        id = Column(Integer, primary_key=True, autoincrement=True)
        name = Column(String(50), nullable=False)
        description = Column(String(200))
        initial_cash = Column(DECIMAL(15, 2))
        created_at = Column(DateTime, default=datetime.now)
        updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    class Position(Base):
        """持仓表"""
        __tablename__ = 'positions'

        id = Column(Integer, primary_key=True, autoincrement=True)
        portfolio_id = Column(Integer, nullable=False, index=True)
        symbol = Column(String(10), nullable=False)
        shares = Column(Integer)
        avg_cost = Column(DECIMAL(10, 2))
        current_price = Column(DECIMAL(10, 2))
        market_value = Column(DECIMAL(15, 2))
        profit_loss = Column(DECIMAL(15, 2))
        profit_pct = Column(Float)
        opened_at = Column(DateTime)
        updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# =============================================================================
# 数据库管理器
# =============================================================================

class DatabaseManager:
    """PostgreSQL数据库管理器"""

    def __init__(self,
                 connection_string: str = None,
                 host: str = "localhost",
                 port: int = 5432,
                 database: str = "stocks_db",
                 user: str = "postgres",
                 password: str = None,
                 pool_size: int = 5,
                 max_overflow: int = 10):
        """
        初始化数据库管理器

        Args:
            connection_string: 完整连接字符串
            host: 数据库主机
            port: 数据库端口
            database: 数据库名称
            user: 用户名
            password: 密码
            pool_size: 连接池大小
            max_overflow: 最大溢出连接数
        """
        if not SQLALCHEMY_AVAILABLE:
            raise ImportError("SQLAlchemy未安装，请运行: pip install sqlalchemy psycopg2-binary")

        # 构建连接字符串
        if connection_string:
            self.connection_string = connection_string
        else:
            password = password or ""
            self.connection_string = f"postgresql://{user}:{password}@{host}:{port}/{database}"

        # 创建引擎
        self.engine = None
        self.SessionLocal = None
        self._connected = False

        # 尝试连接
        self._connect()

    def _connect(self):
        """建立数据库连接"""
        try:
            # 创建引擎
            self.engine = create_engine(
                self.connection_string,
                poolclass=QueuePool,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,  # 检查连接有效性
                echo=False
            )

            # 创建Session工厂
            self.SessionLocal = sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=self.engine
            )

            # 测试连接
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))

            self._connected = True
            print(f"[OK] 数据库连接成功")

        except Exception as e:
            print(f"[WARN] 数据库连接失败: {e}")
            print("[INFO] 将使用离线模式")
            self._connected = False

    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self._connected

    @contextmanager
    def get_session(self):
        """获取数据库会话（上下文管理器）"""
        if not self._connected:
            yield None
            return

        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()

    # =============================================================================
    # 表管理
    # =============================================================================

    def create_tables(self):
        """创建所有表"""
        if not self._connected:
            print("[WARN] 数据库未连接，跳过创建表")
            return False

        try:
            Base.metadata.create_all(self.engine)
            print("[OK] 数据表创建成功")
            return True
        except Exception as e:
            print(f"[ERROR] 创建表失败: {e}")
            return False

    def drop_tables(self):
        """删除所有表"""
        if not self._connected:
            return False

        try:
            Base.metadata.drop_all(self.engine)
            print("[OK] 数据表已删除")
            return True
        except Exception as e:
            print(f"[ERROR] 删除表失败: {e}")
            return False

    # =============================================================================
    # 股票数据操作
    # =============================================================================

    def save_stock_info(self, symbol: str, name: str, market: str = None,
                       industry: str = None) -> bool:
        """
        保存股票基础信息

        Args:
            symbol: 股票代码
            name: 股票名称
            market: 市场
            industry: 行业

        Returns:
            是否成功
        """
        if not self._connected:
            return False

        try:
            with self.get_session() as session:
                # 查找是否存在
                stock = session.query(Stock).filter(Stock.symbol == symbol).first()

                if stock:
                    # 更新
                    stock.name = name
                    stock.market = market
                    stock.industry = industry
                    stock.updated_at = datetime.now()
                else:
                    # 新增
                    stock = Stock(
                        symbol=symbol,
                        name=name,
                        market=market,
                        industry=industry
                    )
                    session.add(stock)

                return True
        except Exception as e:
            print(f"[ERROR] 保存股票信息失败: {e}")
            return False

    def batch_save_stock_quotes(self, data: pd.DataFrame) -> int:
        """
        批量保存行情数据

        Args:
            data: DataFrame with columns: 日期, 开盘, 最高, 最低, 收盘, 成交量

        Returns:
            保存的记录数
        """
        if not self._connected or data is None or len(data) == 0:
            return 0

        try:
            # 提取symbol（假设从数据中）
            symbol = data.get('symbol', [None])[0] if 'symbol' in data.columns else None
            if symbol is None:
                return 0

            saved_count = 0

            with self.get_session() as session:
                for _, row in data.iterrows():
                    # 检查是否已存在
                    existing = session.query(StockQuote).filter(
                        StockQuote.symbol == symbol,
                        StockQuote.date == row['日期']
                    ).first()

                    if not existing:
                        quote = StockQuote(
                            symbol=symbol,
                            date=row['日期'],
                            open=float(row['开盘']) if pd.notna(row['开盘']) else None,
                            high=float(row['最高']) if pd.notna(row['最高']) else None,
                            low=float(row['最低']) if pd.notna(row['最低']) else None,
                            close=float(row['收盘']) if pd.notna(row['收盘']) else None,
                            volume=int(row['成交量']) if pd.notna(row['成交量']) else None,
                            change_pct=float(row['涨跌幅']) if '涨跌幅' in row and pd.notna(row['涨跌幅']) else None
                        )
                        session.add(quote)
                        saved_count += 1

            return saved_count

        except Exception as e:
            print(f"[ERROR] 批量保存行情数据失败: {e}")
            return 0

    def query_stock_quotes(self, symbol: str, start_date: datetime = None,
                          end_date: datetime = None) -> Optional[pd.DataFrame]:
        """
        查询股票行情数据

        Args:
            symbol: 股票代码
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            行情数据DataFrame
        """
        if not self._connected:
            return None

        try:
            with self.get_session() as session:
                query = session.query(StockQuote).filter(StockQuote.symbol == symbol)

                if start_date:
                    query = query.filter(StockQuote.date >= start_date)
                if end_date:
                    query = query.filter(StockQuote.date <= end_date)

                query = query.order_by(StockQuote.date)

                results = query.all()

                if results:
                    data = pd.DataFrame([{
                        '日期': r.date,
                        '开盘': float(r.open) if r.open else None,
                        '最高': float(r.high) if r.high else None,
                        '最低': float(r.low) if r.low else None,
                        '收盘': float(r.close) if r.close else None,
                        '成交量': int(r.volume) if r.volume else None,
                        '涨跌幅': r.change_pct
                    } for r in results])

                    return data

                return None

        except Exception as e:
            print(f"[ERROR] 查询行情数据失败: {e}")
            return None

    def get_latest_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        获取最新报价

        Args:
            symbol: 股票代码

        Returns:
            报价数据字典
        """
        if not self._connected:
            return None

        try:
            with self.get_session() as session:
                quote = session.query(StockQuote).filter(
                    StockQuote.symbol == symbol
                ).order_by(StockQuote.date.desc()).first()

                if quote:
                    return {
                        'symbol': symbol,
                        'date': quote.date,
                        'open': float(quote.open) if quote.open else None,
                        'high': float(quote.high) if quote.high else None,
                        'low': float(quote.low) if quote.low else None,
                        'close': float(quote.close) if quote.close else None,
                        'volume': int(quote.volume) if quote.volume else None,
                        'change_pct': quote.change_pct
                    }

                return None

        except Exception as e:
            print(f"[ERROR] 获取最新报价失败: {e}")
            return None

    # =============================================================================
    # 信号数据操作
    # =============================================================================

    def save_signal(self, symbol: str, date: datetime, signal_type: str,
                    strength: float = 0, source: str = "system") -> bool:
        """
        保存交易信号

        Args:
            symbol: 股票代码
            date: 日期
            signal_type: 信号类型 (buy/sell/hold)
            strength: 信号强度
            source: 信号来源

        Returns:
            是否成功
        """
        if not self._connected:
            return False

        try:
            with self.get_session() as session:
                signal = Signal(
                    symbol=symbol,
                    date=date,
                    signal_type=signal_type,
                    strength=strength,
                    source=source
                )
                session.add(signal)
                return True
        except Exception as e:
            print(f"[ERROR] 保存信号失败: {e}")
            return False

    def query_signals(self, symbol: str = None, start_date: datetime = None,
                     end_date: datetime = None, signal_type: str = None) -> List[Signal]:
        """
        查询交易信号

        Args:
            symbol: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            signal_type: 信号类型

        Returns:
            信号列表
        """
        if not self._connected:
            return []

        try:
            with self.get_session() as session:
                query = session.query(Signal)

                if symbol:
                    query = query.filter(Signal.symbol == symbol)
                if start_date:
                    query = query.filter(Signal.date >= start_date)
                if end_date:
                    query = query.filter(Signal.date <= end_date)
                if signal_type:
                    query = query.filter(Signal.signal_type == signal_type)

                query = query.order_by(Signal.date.desc())

                return query.all()

        except Exception as e:
            print(f"[ERROR] 查询信号失败: {e}")
            return []

    # =============================================================================
    # 回测结果操作
    # =============================================================================

    def save_backtest_result(self, strategy_name: str, params: Dict,
                             result_metrics: Dict) -> bool:
        """
        保存回测结果

        Args:
            strategy_name: 策略名称
            params: 策略参数
            result_metrics: 回测结果指标

        Returns:
            是否成功
        """
        if not self._connected:
            return False

        try:
            import json

            with self.get_session() as session:
                backtest = BacktestResult(
                    strategy_name=strategy_name,
                    symbol=params.get('symbol'),
                    start_date=params.get('start_date'),
                    end_date=params.get('end_date'),
                    initial_cash=result_metrics.get('initial_cash', 0),
                    final_value=result_metrics.get('final_value', 0),
                    total_return=result_metrics.get('total_return', 0),
                    annual_return=result_metrics.get('annual_return', 0),
                    sharpe_ratio=result_metrics.get('sharpe_ratio', 0),
                    max_drawdown=result_metrics.get('max_drawdown', 0),
                    win_rate=result_metrics.get('win_rate', 0),
                    profit_factor=result_metrics.get('profit_factor', 0),
                    total_trades=result_metrics.get('total_trades', 0),
                    parameters=json.dumps(params, ensure_ascii=False)
                )
                session.add(backtest)
                return True

        except Exception as e:
            print(f"[ERROR] 保存回测结果失败: {e}")
            return False

    def query_backtest_results(self, strategy_name: str = None,
                               symbol: str = None) -> List[BacktestResult]:
        """
        查询回测结果

        Args:
            strategy_name: 策略名称
            symbol: 股票代码

        Returns:
            回测结果列表
        """
        if not self._connected:
            return []

        try:
            with self.get_session() as session:
                query = session.query(BacktestResult)

                if strategy_name:
                    query = query.filter(BacktestResult.strategy_name == strategy_name)
                if symbol:
                    query = query.filter(BacktestResult.symbol == symbol)

                query = query.order_by(BacktestResult.created_at.desc())

                return query.all()

        except Exception as e:
            print(f"[ERROR] 查询回测结果失败: {e}")
            return []

    # =============================================================================
    # 组合操作
    # =============================================================================

    def create_portfolio(self, name: str, initial_cash: float,
                         description: str = None) -> Optional[int]:
        """
        创建投资组合

        Args:
            name: 组合名称
            initial_cash: 初始资金
            description: 描述

        Returns:
            组合ID
        """
        if not self._connected:
            return None

        try:
            with self.get_session() as session:
                portfolio = Portfolio(
                    name=name,
                    description=description,
                    initial_cash=initial_cash
                )
                session.add(portfolio)
                session.flush()
                return portfolio.id

        except Exception as e:
            print(f"[ERROR] 创建组合失败: {e}")
            return None

    def save_position(self, portfolio_id: int, symbol: str, shares: int,
                      avg_cost: float, current_price: float = None) -> bool:
        """
        保存持仓

        Args:
            portfolio_id: 组合ID
            symbol: 股票代码
            shares: 持仓数量
            avg_cost: 平均成本
            current_price: 当前价格

        Returns:
            是否成功
        """
        if not self._connected:
            return False

        try:
            with self.get_session() as session:
                # 查找现有持仓
                position = session.query(Position).filter(
                    Position.portfolio_id == portfolio_id,
                    Position.symbol == symbol
                ).first()

                market_value = shares * (current_price or avg_cost)
                profit_loss = (current_price or avg_cost - avg_cost) * shares
                profit_pct = ((current_price or avg_cost) / avg_cost - 1) * 100 if avg_cost > 0 else 0

                if position:
                    # 更新
                    position.shares = shares
                    position.avg_cost = avg_cost
                    position.current_price = current_price or avg_cost
                    position.market_value = market_value
                    position.profit_loss = profit_loss
                    position.profit_pct = profit_pct
                    position.updated_at = datetime.now()
                else:
                    # 新增
                    position = Position(
                        portfolio_id=portfolio_id,
                        symbol=symbol,
                        shares=shares,
                        avg_cost=avg_cost,
                        current_price=current_price or avg_cost,
                        market_value=market_value,
                        profit_loss=profit_loss,
                        profit_pct=profit_pct,
                        opened_at=datetime.now()
                    )
                    session.add(position)

                return True

        except Exception as e:
            print(f"[ERROR] 保存持仓失败: {e}")
            return False

    # =============================================================================
    # 统计查询
    # =============================================================================

    def get_table_stats(self) -> Dict[str, int]:
        """
        获取各表的记录统计

        Returns:
            {表名: 记录数} 字典
        """
        if not self._connected:
            return {}

        stats = {}

        try:
            with self.get_session() as session:
                stats['stocks'] = session.query(Stock).count()
                stats['quotes'] = session.query(StockQuote).count()
                stats['signals'] = session.query(Signal).count()
                stats['backtests'] = session.query(BacktestResult).count()
                stats['portfolios'] = session.query(Portfolio).count()
                stats['positions'] = session.query(Position).count()

        except Exception as e:
            print(f"[ERROR] 获取统计信息失败: {e}")

        return stats


# =============================================================================
# 辅助函数
# =============================================================================

def get_database_manager(**kwargs) -> DatabaseManager:
    """
    获取数据库管理器实例

    Returns:
        DatabaseManager实例
    """
    return DatabaseManager(**kwargs)


# =============================================================================
# 测试代码
# =============================================================================

if __name__ == "__main__":
    print("PostgreSQL数据库管理器 - v1.0")
    print()

    # 测试连接
    try:
        db = DatabaseManager()

        if db.is_connected():
            print("✓ 数据库连接成功")

            # 创建表
            print("\n创建数据表...")
            db.create_tables()

            # 获取统计
            stats = db.get_table_stats()
            print("\n数据库统计:")
            for table, count in stats.items():
                print(f"  {table}: {count} 条记录")

            print("\n✓ 测试完成！")

        else:
            print("✗ 数据库未连接，请检查PostgreSQL服务")

    except ImportError:
        print("✗ 依赖模块未安装，请运行:")
        print("   pip install sqlalchemy psycopg2-binary")
    except Exception as e:
        print(f"✗ 测试失败: {e}")
