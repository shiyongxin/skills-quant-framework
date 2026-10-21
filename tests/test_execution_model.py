# -*- coding: utf-8 -*-
"""execution_model 单元测试：成本、涨跌停规则、标量与向量化一致性。"""
import numpy as np
import pytest

from execution_model import (
    CostModel,
    buy_open_ok,
    can_buy_at_open,
    can_sell_at_open,
    can_sell_intraday,
    is_limit_up_price,
    limit_pct_for,
    sell_open_ok,
    sell_intraday_ok,
)


class TestLimitRules:
    def test_limit_pct_by_code(self):
        assert limit_pct_for('300001') == 0.20
        assert limit_pct_for('688001') == 0.20
        assert limit_pct_for('600519') == 0.10
        assert limit_pct_for('600519', is_st=True) == 0.05

    def test_limit_up_detection_with_tolerance(self):
        assert is_limit_up_price(10.99, 10.0, '600519')
        assert not is_limit_up_price(10.9, 10.0, '600519')
        # 20cm: 11.99 触板, 11.9 不触
        assert not can_buy_at_open(11.99, 10.0, '300001')
        assert can_buy_at_open(11.9, 10.0, '300001')

    def test_open_limit_blocks(self):
        assert not can_buy_at_open(10.99, 10.0, '600519')    # 开盘涨停买不进
        assert not can_sell_at_open(9.01, 10.0, '600519')    # 开盘跌停卖不出

    def test_sealed_down_board_intraday(self):
        # 一字跌停: 开=高=低=收 且收在跌停 → 日内不可卖
        assert not can_sell_intraday(9.01, 9.01, 9.01, 9.01, 10.0, '600519')
        assert can_sell_intraday(9.5, 9.8, 9.2, 9.4, 10.0, '600519')

    def test_invalid_prev_close(self):
        assert not is_limit_up_price(10.99, 0.0, '600519')


class TestCostModel:
    def test_buy_cost_with_min_commission(self):
        cm = CostModel()
        # notional 50000 → 佣金 max(15, 5)=15, 过户 5
        assert abs(cm.buy_cost(10.0, 5000) - 20) < 1e-9
        # notional 100 → 佣金 max(0.03, 5)=5 最低佣金生效
        assert abs(cm.buy_cost(1.0, 100) - 5.01) < 1e-9

    def test_sell_cost_includes_stamp_tax(self):
        cm = CostModel()
        # 15 佣金 + 50000*(0.0001+0.0005)=30 → 45
        assert abs(cm.sell_cost(10.0, 5000) - 45) < 1e-9

    def test_pure_rate_prices(self):
        cm = CostModel()
        assert abs(cm.buy_price_incl(10) - 10 * 1.001 * 1.0004) < 1e-12
        assert abs(cm.sell_price_incl(10) - 10 * 0.999 * 0.9991) < 1e-12

    def test_fee_rate(self):
        cm = CostModel()
        assert abs(cm.fee_rate('buy') - 0.0004) < 1e-12
        assert abs(cm.fee_rate('sell') - 0.0009) < 1e-12
        with pytest.raises(ValueError):
            cm.fee_rate('hold')

    def test_from_engine_compat(self):
        cm = CostModel.from_engine(commission=0.0005, slippage=0.002)
        assert cm.commission_rate == 0.0005 and cm.slippage == 0.002


class TestVectorizedMasks:
    def test_masks_match_scalar(self):
        o = np.array([10.99, 9.01, 10.0])
        pc = np.array([10.0, 10.0, 10.0])
        assert list(buy_open_ok(o, pc, '600519')) == [False, True, True]
        assert list(sell_open_ok(o, pc, '600519')) == [True, False, True]

    def test_sell_intraday_mask(self):
        # 一行正常、一行开盘跌停、一行一字跌停
        o = np.array([9.5, 9.01, 9.01])
        h = np.array([9.8, 9.01, 9.01])
        l = np.array([9.2, 9.01, 9.01])
        c = np.array([9.4, 9.01, 9.01])
        pc = np.array([10.0, 10.0, 10.0])
        assert list(sell_intraday_ok(o, h, l, c, pc, '600519')) == [True, False, False]
