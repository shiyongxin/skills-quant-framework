# -*- coding: utf-8 -*-
"""
审计项 20 回归测试 — 风控接入下单路径

- PortfolioManager: 集中度/现金闸门阻断下单, rebalance 超限阻断,
  StopLossManager 接线, PortfolioRiskMonitor 接线, HHI 双刻度一致
- VectorizedBacktester: max_position_pct 硬上限 (默认不改历史行为)
- PositionConfig: max_position_pct>=1.0 触发无上限警告
"""
import numpy as np
import pandas as pd
import pytest

from portfolio_manager import PortfolioManager


def _mk_prices(n=300, seed=3, base=10.0):
    rng = np.random.default_rng(seed)
    close = base * np.cumprod(1 + rng.normal(0, 0.01, n))
    return pd.DataFrame({
        '日期': pd.bdate_range('2023-01-02', periods=n),
        '开盘': close * (1 + rng.normal(0, 0.002, n)),
        '最高': close * 1.01,
        '最低': close * 0.99,
        '收盘': close,
        '成交量': rng.integers(1e6, 2e6, n).astype(float),
    })


class TestPortfolioOrderGates:
    def test_add_position_blocks_oversized(self, capsys):
        pm = PortfolioManager()  # max_position_pct=0.33, risk_block=True
        pm.create_portfolio('p', initial_cash=100000)
        # 50% 单票 → 超过 33% 上限
        assert pm.add_position('p', '600519', shares=5000, price=10) is False
        assert '风控阻断' in capsys.readouterr().out
        assert pm.get_portfolio('p').cash == 100000  # 未成交

    def test_add_position_allows_within_cap(self):
        pm = PortfolioManager()
        pm.create_portfolio('p', initial_cash=100000)
        assert pm.add_position('p', '600519', shares=3000, price=10) is True
        assert pm.get_portfolio('p').cash == 70000

    def test_add_position_blocks_cash_overdraft(self, capsys):
        pm = PortfolioManager(max_position_pct=1.0)  # 隔离现金闸门
        pm.create_portfolio('p', initial_cash=100000)
        assert pm.add_position('p', '600519', shares=11000, price=10) is False
        assert '超过可用现金' in capsys.readouterr().out

    def test_risk_block_false_warns_only(self, capsys):
        pm = PortfolioManager(max_position_pct=0.1, risk_block=False)
        pm.create_portfolio('p', initial_cash=100000)
        assert pm.add_position('p', '600519', shares=5000, price=10) is True
        out = capsys.readouterr().out
        assert '风控告警' in out and '未阻断' in out

    def test_rebalance_blocks_oversized_target(self):
        pm = PortfolioManager()
        pm.create_portfolio('p', initial_cash=100000)
        with pytest.raises(ValueError, match='风控阻断再平衡'):
            pm.rebalance('p', {'600519': 0.8},
                         price_dict={'600519': 10.0})

    def test_rebalance_allows_within_cap(self):
        pm = PortfolioManager()
        pm.create_portfolio('p', initial_cash=100000)
        adj = pm.rebalance('p', {'600519': 0.3},
                           price_dict={'600519': 10.0})
        assert adj == {'600519': 3000}

    def test_hhi_dual_scale_consistent(self):
        pm = PortfolioManager()
        pm.create_portfolio('p', initial_cash=100000)
        assert pm.add_position('p', 'A', shares=3000, price=10) is True
        assert pm.add_position('p', 'B', shares=3000, price=10) is True
        m = pm.get_risk_metrics('p')
        # 两票等权 (不含现金): hhi_01 = 0.5, 传统刻度 5000
        assert m['hhi_normalized'] == pytest.approx(0.5, abs=1e-6)
        assert m['hhi'] == pytest.approx(m['hhi_normalized'] * 10000, abs=1e-6)
        assert m['concentration_level'] == 'HIGH'

    def test_check_risk_var_structure(self):
        pm = PortfolioManager()
        pm.create_portfolio('p', initial_cash=100000)
        pm.add_position('p', 'A', shares=3000, price=10)
        pm.add_position('p', 'B', shares=3000, price=10)
        rng = np.random.default_rng(0)
        returns = pd.DataFrame({
            'A': rng.normal(0, 0.01, 100),
            'B': rng.normal(0, 0.01, 100),
        })
        report = pm.check_risk('p', returns)
        assert 'within_limit' in report and 'daily_var' in report

    def test_stop_loss_wiring(self):
        pm = PortfolioManager()
        pm.create_portfolio('p', initial_cash=100000)
        assert pm.add_position('p', 'A', shares=3000, price=10.0,
                               stop_loss_pct=0.05) is True
        results = pm.check_stop_losses({'A': 9.0})  # -10% < -5% 止损线
        assert results['A']['action'] == 'sell'
        assert results['A']['type'] == 'stop_loss'
        # 清仓后止损注册一并移除
        pm.remove_position('p', 'A', price=9.0)
        assert 'A' not in pm.stop_monitor.positions


class TestVectorizedMaxPositionClamp:
    def test_clamp_equivalent_to_lower_size(self):
        from vectorized_backtest import VectorizedBacktester

        data = _mk_prices()
        bt = VectorizedBacktester()
        base = {'stop_loss_pct': 0.08, 'take_profit_pct': 0.20,
                'min_holding_days': 5}
        m_full = bt.backtest(data, {**base, 'position_size_pct': 0.9})
        assert m_full.num_trades > 0, 'GBM数据未产生交易, 测试无效'

        # clamp 生效 == 直接用更小仓位
        m_clamped = bt.backtest(data, {**base, 'position_size_pct': 0.9,
                                       'max_position_pct': 0.45})
        m_direct = bt.backtest(data, {**base, 'position_size_pct': 0.45})
        assert m_clamped.total_return == pytest.approx(m_direct.total_return)
        assert m_clamped.total_return != pytest.approx(m_full.total_return)

    def test_default_unchanged(self):
        from vectorized_backtest import VectorizedBacktester

        data = _mk_prices(seed=11)
        bt = VectorizedBacktester()
        base = {'stop_loss_pct': 0.08, 'take_profit_pct': 0.20,
                'min_holding_days': 5, 'position_size_pct': 0.8}
        m1 = bt.backtest(data, base)
        m2 = bt.backtest(data, {**base, 'max_position_pct': 1.0})
        assert m1.total_return == pytest.approx(m2.total_return)


class TestPositionConfigWarning:
    def test_default_warns(self):
        from backtest_framework import PositionConfig

        with pytest.warns(UserWarning, match='无上限'):
            PositionConfig()

    def test_capped_no_warning(self):
        import warnings
        from backtest_framework import PositionConfig

        with warnings.catch_warnings(record=True) as record:
            warnings.simplefilter('always')
            PositionConfig(max_position_pct=0.5)
        assert len(record) == 0
